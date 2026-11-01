#!/usr/bin/env python3
"""mcp-vn v4 private pull worker: scene-grounded ComfyUI, cutouts and pre-publication QA."""
import io
from collections import OrderedDict
import base64
import threading
import concurrent.futures
import subprocess
import tempfile
import json
import hashlib
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageOps, ImageStat, ImageChops
from scene_compositor import compose as compose_cg
from pose_presets import pose_prompt,wants_fresh_latent,pose_control_guide
from wardrobe_contract import wants_unclothed
from neural_scene_guards import neural_scene_guards
from panel_guard import detect_four_panel_collage
from local_repair import archive_rejected_candidate,apply_inpaint_graph,cleanup as cleanup_repair
from comfy_manifest import load as load_manifest,persist as persist_manifest,digest as workflow_digest
from scene_constraints import scene_constraints
from scene_contract import scene_contract,crowd_condition
from pose_library import select_story_pose
from pose_reference_selector import choose_approved_reference
from actor_layout import region_for_actor, assert_cast_supported
from render_invariants import narrator_invariants
from render_retry import retry_plan,permanent_render_failure
from engine_policy import assert_engine_snapshot
from scene_action_contract import wall_brace_required,resolve_scene_action
from pose_geometry_runtime import verify_with_comfy

SERVER = os.environ.get("VN_SERVER", "http://192.168.50.29:3100").rstrip("/")
TOKEN = os.environ["VN_WORKER_TOKEN"]
COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
OUTPUT = Path(os.environ.get("COMFY_OUTPUT", str(Path.home()/".local/share/mcp-vn-comfy/output")))
def is_unclothed(spec):
    outfit=str((spec.get("variant") or {}).get("outfit","default")).strip().lower()
    return wants_unclothed(outfit)

STYLES = {
    "anime": ("waiIllustriousSDXL_v170.safetensors", 24, 6.0),
    "animation": ("BASNSFWBetterAnimeStyleForNSFWHentai_baseV10.safetensors", 8, 1.0),
    "semireal": ("CyberRealisticPony_V18.0_F16.safetensors", 32, 5.0),
    "realistic": ("CyberRealisticPony_V18.0_F16.safetensors", 32, 5.0),
    "poster": ("CyberRealisticPony_V18.0_F16.safetensors", 32, 5.0),
}
SESSION = None
SESSION_LOCK=threading.Lock()
VISION=os.environ.get("VN_VISION_URL","http://127.0.0.1:9312")
POLL=float(os.environ.get("VN_COMFY_POLL_SECONDS","1"))
CPU_THREADS=max(1,min(3,int(os.environ.get("VN_CPU_WORKERS","2"))))
# Small immutable reference PNG byte cache. Images and character anchors
# are immutable UUID assets. Keep <= 128 MiB in RAM and decode a fresh PIL
# image per request, so image transforms cannot mutate cached references.
REF_CACHE_LIMIT=max(0,min(256,int(os.environ.get("VN_ASSET_CACHE_MIB","128"))))*1024*1024
_REF_CACHE=OrderedDict()
_REF_CACHE_BYTES=0
_REF_LOCK=threading.RLock()

def request(base, path, method="GET", data=None, headers=None, timeout=15):
    h = dict(headers or {})
    if base == SERVER:
        h["Authorization"] = "Bearer " + TOKEN
    if data is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    raw = json.dumps(data).encode() if data is not None and not isinstance(data, bytes) else data
    req = Request(base+path, data=raw, headers=h, method=method)
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
        return json.loads(payload) if "json" in response.headers.get("Content-Type", "") else payload

def pil_png(image):
    buffer=io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()

def upload_to_comfy(data, name):
    boundary="----mcpvn"+uuid.uuid4().hex
    form=(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"image\"; filename=\""+
       name+"\"\r\nContent-Type: image/png\r\n\r\n").encode()+data+
       ("\r\n--"+boundary+"--\r\n").encode())
    result=request(COMFY,"/upload/image","POST",form,
        {"Content-Type":"multipart/form-data; boundary="+boundary},timeout=75)
    if not result.get("name"):
        raise RuntimeError("ComfyUI upload returned no filename")
    return result["name"]

def fetch_asset(name):
    global _REF_CACHE_BYTES
    if not name:
        return None
    if "/" in name or ".." in name:
        raise ValueError("Invalid asset name")
    data=None
    if REF_CACHE_LIMIT:
        with _REF_LOCK:
            data=_REF_CACHE.get(name)
            if data is not None:
                _REF_CACHE.move_to_end(name)
    if data is None:
        data=request(SERVER,"/worker/asset/"+name,timeout=30)
        if len(data)>35_000_000:
            raise ValueError("Reference image exceeds 35 MB")
        if REF_CACHE_LIMIT and len(data)<12*1024*1024:
            with _REF_LOCK:
                existing=_REF_CACHE.get(name)
                if existing is None:
                    while (_REF_CACHE and
                           _REF_CACHE_BYTES+len(data)>REF_CACHE_LIMIT):
                        _,removed=_REF_CACHE.popitem(last=False)
                        _REF_CACHE_BYTES-=len(removed)
                    if len(data)<=REF_CACHE_LIMIT:
                        _REF_CACHE[name]=data
                        _REF_CACHE_BYTES+=len(data)
                else:
                    data=existing
                    _REF_CACHE.move_to_end(name)
    return Image.open(io.BytesIO(data)).convert("RGBA")

def background_context(image):
    if image is None:
        return "Natural neutral cinematic lighting", None
    sample=image.convert("RGB").resize((48,48))
    r,g,b=ImageStat.Stat(sample).mean
    brightness=.2126*r+.7152*g+.0722*b
    period="low-key dusk or moonlight" if brightness<85 else "soft twilight" if brightness<145 else "daylight"
    temp="warm amber illumination" if r>b+8 else "cool blue ambient lighting" if b>r+8 else "neutral ambient lighting"
    direction="light from camera left" if sum(ImageStat.Stat(sample.crop((0,0,24,48))).mean)>sum(ImageStat.Stat(sample.crop((24,0,48,48))).mean) else "light from camera right"
    return period+", "+temp+", "+direction, (r,g,b)

def regional_face_attention_mask(index,width,height,count=2,region=None):
    """Comfy LoadImage alpha mask for each principal, not a fixed two-way split."""
    layer=Image.new("RGBA",(width,height),(0,0,0,255))
    # For a single principal, applying the identity reference to the whole
    # canvas can clone that same person on incidental background figures.
    # Without explicit blocking, bias the face reference to central foreground.
    if count==1 and region is None:
        region=[.18,.04,.64,.92]
    x0,y0,x1,y1=region_for_actor(index,count,region)
    ImageDraw.Draw(layer).rectangle(
        (int(width*x0),int(height*y0),int(width*x1),int(height*y1)),
        fill=(0,0,0,0))
    return layer

def scene_mask(background, characters):
    """Transparent hole in original photo becomes ComfyUI's LoadImage MASK."""
    w,h=1216,704
    image=ImageOps.fit(background.convert("RGB"),(w,h),method=Image.Resampling.LANCZOS)
    cover=image.convert("RGBA")
    mask=Image.new("L",(w,h),255)
    draw=ImageDraw.Draw(mask)
    n=min(3,max(1,len(characters)))
    width=.28 if n>=2 else .43
    centers=[.50] if n==1 else ([.31,.70] if n==2 else [.21,.50,.79])
    for c in centers:
        left=int(w*(c-width/2))
        right=int(w*(c+width/2))
        draw.rounded_rectangle((left,int(h*.13),right,int(h*.99)),radius=52,fill=0)
    mask=mask.filter(ImageFilter.GaussianBlur(12))
    cover.putalpha(mask)
    return cover

def appearance_tags(description):
    """Preserve the most significant traits in Russian user-owned descriptions for English SDXL CLIP."""
    t=str(description or "").lower()
    tags=[]
    def anyof(*words):return any(word in t for word in words)
    if anyof("женщин", "девушк", "проводниц"):tags.append("adult female character")
    elif anyof("мужчин", "парень", "авантюрист"):tags.append("adult male character")
    if anyof("короткие тёмные волосы","короткие темные волосы","короткими тёмными волосами","короткими темными волосами"):
        tags.append("short dark brown hair")
    elif anyof("тёмные волосы","темные волосы"):tags.append("dark brown hair")
    if anyof("серебрист", "седые пряди"):tags.append("distinctive silver hair streaks at the forehead")
    if anyof("русые волосы","светло-каштан", "светло-коричнев"):tags.append("light brown hair")
    if anyof("рыжие волос"):tags.append("red hair")
    if anyof("коса", "заплет", "косич"):tags.append("braided hair")
    if anyof("короткая бород", "короткой бород", "аккуратная щетина", "короткая щетина"):
        tags.append("well groomed short beard and stubble")
    if anyof("бород") and not any("beard" in x for x in tags):tags.append("short beard")
    if anyof("серьг"):tags.append("small dark hoop earring")
    if anyof("зелён", "зелен"):
        tags.append("forest-green cloak" if "плащ" in t else "green color accents")
    if anyof("красн"):
        tags.append("dark red accents on adventurer outfit")
    if anyof("кожан", "кожа"):
        tags.append("leather adventure gear")
    if anyof("золот") and "золот" in t:tags.append("gold accents")
    if anyof("серебрист") and "знак" in t:tags.append("silver rune symbol")
    return ", ".join(tags[:10])

def prompt_builder(job, background):
    spec=job.get("spec") or {}
    assert_engine_snapshot(spec.get("engine"))
    kind=job["kind"]
    style=job["style"]
    lighting,_=background_context(background)
    place=spec.get("location") or "unknown location"
    env=spec.get("environment") or {}
    envpositive=", ".join(env.get("positive") or [])
    envnegative=", ".join(env.get("negative") or [])
    subject=job.get("prompt","")
    world=spec.get("world","")
    time_of_day=spec.get("target_time_of_day") or ""
    weather=spec.get("target_weather") or ""
    if style=="realistic":
        stylehint="cinematic photorealistic still frame, natural human anatomy and textures, photographic realism, 35mm lens, coherent ambient light"
    elif style=="semireal":
        stylehint="cohesive semirealistic 2.5D visual novel film still, painterly realism, elegant natural light"
    elif style=="anime":
        stylehint="Japanese anime visual novel illustration, expressive manga facial features, precise cel shading, coherent anime background palette"
    elif style=="animation":
        stylehint="handcrafted animated film illustration, expressive 2D animation, lively organic shapes, painterly colors, soft illustrated materials, not a Japanese anime screencap"
    else:
        stylehint="high detail cinematic fantasy photograph, fine skin detail, coherent perspective"
    retry=" Strictly one clean subject on an even backdrop, head and feet in frame." if job.get("attempts",1)>1 and kind=="sprite" else ""
    if kind=="sprite":
        appearance=spec.get("appearance","")
        variant=spec.get("variant") or {}
        outfit=str(variant.get("outfit","default")).strip().lower()
        pose=variant.get("pose","standing")
        emotion=variant.get("emotion","neutral")
        is_unclothed=wants_unclothed(outfit)
        # Clothing instructions must never leak out of the canonical face description.
        traits=appearance_tags(appearance)
        if outfit!="default":
            traits=", ".join(x for x in traits.split(", ") if
                not any(part in x for part in ("cloak","gear","outfit","color accents","leather")))
        stable_description=appearance if outfit=="default" else (
            "Use the attached canonical reference for the same adult person's face, hair, "
            "age and build. Previous wardrobe must not be copied.")
        wardrobe=("Non-erotic classical fine-art nude of a fictional adult; "
                  "entirely unclothed with no garments or costume elements worn on the body; any carried clothes stay entirely off the body."
                   if is_unclothed else
                   f"Required wardrobe: {outfit}; do not retain previous clothing."
                   if outfit!="default" else "")
        stage_pose="Required body pose geometry: "+pose_prompt(pose)+"."
        expression=f" Facial expression: {emotion}." if emotion!="neutral" else ""
        positive=(f"{stylehint}. A single adult fictional character, {job.get('character','')}. "
           f"Stable physical characteristics: {traits}. Identity: {stable_description}. "
           f"Wardrobe state: {wardrobe}. {stage_pose} {expression} Story direction: {subject}. "
           f"FULL LENGTH character design, head to boots or toes in frame, centered person, "
           f"single uninterrupted subject, camera at eye level, clean simple solid uniform neutral-grey seamless studio backdrop "
           f"for background removal, no environment, no scenery, no floor objects. "
           f"Subject illumination must match the active scene: {lighting}. {retry}")
        negative=("multiple people, duplicate bodies, extra arms, extra legs, extra fingers, cut off head, cropped feet, "
                  "different person, green screen texture, checkerboard, room, architecture, mountains, forest, street, "
                  "busy background, painted landscape, text, watermark, logo, bad anatomy, child, underage")
        if is_unclothed:
            negative+=(", clothing, costume, armor, dress, shirt, jacket, coat, cloak, bra, "
                       "bikini, briefs, loincloth, trousers, skirt, swimsuit, lingerie")
    elif kind=="local_cg":
        state=spec.get("local_visual_state") or {}
        people=[]
        for char in state.get("characters") or []:
            reference=next((c for c in spec.get("characters",[])
                            if c.get("name")==char.get("name")), {})
            identity_traits=", ".join(t for t in
                appearance_tags(reference.get("appearance","")).split(", ")
                if not any(w in t for w in ("cloak","gear","outfit",
                                           "leather","color accents")))
            people.append(
                str(char.get("name",""))+": "+
                identity_traits+
                ". Wardrobe: "+str(char.get("outfit",""))+
                ". Gear: "+str(char.get("equipment",""))+
                ". Body pose: "+str(char.get("pose",""))+
                ". Expression: "+str(char.get("expression",""))+
                ". Action: "+str(char.get("action","")))
        principal_count=len(people)
        count_note=(f"Exactly {principal_count} established adult principal figures in this scene, "
                    "and no unlisted extra figures.")
        camera_text=str(state.get("camera",""))
        if re.search(r"(close[- ]?up|tight framing|portrait)",camera_text,re.I):
            framing_note=("Honor the requested tight framing. Include identifiable principal "
                          "figures; partial bodies may naturally extend beyond the image edges.")
        elif principal_count==1:
            framing_note="Keep the single main subject clearly visible; do not invent a companion."
        else:
            framing_note=("Place the requested main characters together in the same coherent "
                          "scene, respecting the requested camera angle.")
        # Put the pose and action FIRST. SDXL attention otherwise locks onto
        # the long canonical wardrobe and setting before reaching the beat.
        positive=(f"{stylehint}. {count_note} "
          f"PRIMARY ACTION: {state.get('activity','')}. "
          f"Physical character instructions: {'; '.join(people)}. "
          f"CAMERA: {state.get('camera','')}. {framing_note} "
          f"REQUIRED LOCATION: {envpositive}. "
          f"Location: {state.get('location',place)}. Environment: {state.get('environment','')}. "
          f"Lighting: {state.get('lighting',lighting)}. "
          "Preserve individual recognizable adult identities and logical interaction. "
          "All equipment and garments must match the physical moment, not an old frame. "
          "Realistic anatomy and coherent perspective. "
          f"Additional scene description: {subject}. ")
        negative=(("single person portrait when multiple characters are required, "
          "missing second main character, " if principal_count>1 else
          "unlisted extra principal figure, ")+
          "unrelated landscape, duplicate persons, "
          "fused bodies, swapped faces, incorrect number of people, "
          "extra limbs, wrong hair identity, flat cutout collage, disconnected perspective, "
          "text, watermark, logo, child, underage, "+envnegative)
    elif kind=="scene":
        people=", ".join(c["name"]+": "+appearance_tags(c.get("appearance",""))+
                         ". "+str(c.get("appearance",""))[:140] for c in spec.get("characters",[]))
        positive=(f"{stylehint}. REQUIRED LOCATION: {envpositive}. Location: {place}. "
           f"Preserve established character identity, natural hair and body proportions. "
           f"Exactly {len(spec.get('characters') or [])} established adult principal characters: {people}. "
           f"Story action and camera: {subject}. Match the scene lighting ({lighting}), "
           "scale, perspective, shadows and colors. Coherent single frame.")
        negative=("split screen, collage, framed portraits, poster, isolated character card, borders, text, watermark, "
                  f"duplicated faces, disfigured hands, wrong hair color, wrong hair style, different body type, child, underage, {envnegative}")
    else:
        positive=(f"{stylehint}. Essential scene geometry: {envpositive}. "
           f"Open-air PUBLIC SQUARE with sky and buildings OUTSIDE if market square. "
           f"Location: {place}. Time of day: {time_of_day}. Weather: {weather}. "
           f"World: {world}. Scene direction: {subject}. "
           "Real-world coherent perspective, natural light, environmental depth, wide establishing shot, no portraits.")
        negative=(f"{envnegative}, collage, separate portrait, split-screen, picture-in-picture, "
          "text, watermark, logo, blurry, deformed buildings, child, underage")
    # For a VN Web story turn, the selected LLM authors the complete
    # image-positive text. Do not prepend old outfit descriptions or generic
    # camera directions that contradict the just-narrated visual moment.
    # Keep only invariant style/identity/asset safety constraints here.
    if spec.get("narrator_prompt") is True and kind in ("background","sprite","scene") and subject.strip():
        positive=f"{stylehint}. {subject.strip()}."
        if kind=="sprite":
            positive+=(f" Exactly one established adult fictional character: "
                      f"{job.get('character','')}. Stable face identity; "
                      "neutral solid backdrop for alpha extraction, no scenery.")
        elif kind=="scene":
            names=[str(c.get("name","")) for c in (spec.get("characters") or [])]
            positive+=(f" Exactly {len(names)} established adult principal figures "
                      f"({', '.join(names)}), no invented protagonists. "
                      f"Same required location: {place}. Unified camera perspective.")
        else:
            positive+=(f" Environment only, no identifiable named characters. "
                      f"Required location: {place}.")
    if spec.get("narrator_prompt") is True and kind in ("background","sprite","scene"):
        essential_positive, essential_negative = narrator_invariants(job)
        if essential_positive:
            positive=essential_positive+" "+positive
        if essential_negative:
            negative=essential_negative+", "+negative
    if kind=="scene" and spec.get("composition")=="neural_story":
        lead,extra_negative,_=neural_scene_guards(
            spec,int(job.get("attempts",1)),job.get("error",""),subject)
        # Put the cardinality/location first; SDXL may otherwise treat
        # a reference identity as a request for multiple appearances.
        positive=lead+positive
        negative=extra_negative+negative
        crowd_positive,crowd_negative=crowd_condition(spec)
        if crowd_positive:positive=crowd_positive+positive
        if crowd_negative:negative=crowd_negative+", "+negative
        scene_positive,scene_negative=scene_constraints(spec,subject)
        if scene_positive:positive=scene_positive+" "+positive
        if scene_negative:negative=scene_negative+", "+negative
    # Model-specific prompt rules
    if style in ("semireal","realistic","poster"):
        # CyberRealistic Pony v18: score ladder + source_photo + rating_explicit
        # Negative should include score_6/5/4 and anti-cartoon
        positive="score_9, score_8_up, score_7_up. "+positive
        negative+=", score_6, score_5, score_4, cartoon, anime, 3d render, plastic skin, airbrushed"
    elif style=="anime":
        # WAI-Illustrious: masterpiece/best quality, not score tags
        positive="masterpiece, best quality, high quality, very aesthetic, detailed. "+positive
        negative+=", lowres, bad anatomy, bad hands, worst quality, low quality"
    elif style=="animation":
        # Anima/BAS:NSFW: animation style, not Japanese anime screencap
        positive="masterpiece, best quality, highly detailed, sharp focus. "+positive
    # The selected storyteller owns the exact camera and pose. Keyword-based
    # rewriting used to force a rear view for unrelated mentions of "wall" or
    # body parts, contradicting the actual scene and causing repeated rejects.
    # Teeth fix
    if kind in ("scene","sprite"):
        negative += ", bad teeth, ugly teeth, crooked teeth, missing teeth, deformed teeth, open mouth with bad teeth, extra teeth"
    if kind=="local_cg" and job.get("attempts",1)>1:
        error=str(job.get("error","")).lower()
        if "principal" in error or "one=" in error:
            if len((spec.get("local_visual_state") or {}).get("characters") or [])>1:
                positive+=(" Place the requested distinct main figures visibly within "
                           "the requested camera frame, not as an unrelated portrait.")
            else:
                positive+=" Show exactly one adult principal figure, no invented companion."
        if "forest" in error and spec.get("environment",{}).get("id") in (
                "outdoor_market_square","outdoor_street","outdoor_courtyard"):
            positive+=(" Show unmistakable buildings, shops and stone streets "
              "of the required urban setting, not woodland scenery.")
            negative+=", dense forest covering the entire background, forest landscape"
    if kind=="sprite" and job.get("attempts",1)>1:
        error=str(job.get("error","")).lower()
        color_error=re.search(r"expected ([a-z]+), image described as ([a-z]+)",error)
        if color_error:
            expected_color,wrong_color=color_error.groups()
            positive+=f" Correct the previous color mistake: prominent {expected_color} cloak, natural clearly {expected_color} fabric, not {wrong_color}."
            negative+=f", {wrong_color} cloak, {wrong_color} robe, {wrong_color} outerwear"
    retry=retry_plan(job)
    if retry["positive"]:
        positive=retry["positive"]+" "+positive
    if retry["negative"]:
        negative=retry["negative"]+", "+negative
    return positive[:5500],negative[:1000]

def image_graph(job):
    kind=job["kind"]
    spec=job.get("spec") or {}
    assert_engine_snapshot(spec.get("engine"))
    scene_contract(spec)
    model,steps,cfg=STYLES[job["style"]]
    is_animation=job["style"]=="animation"
    vae_ref=["14",0] if is_animation else ["1",2]
    quality=spec.get("quality","standard")
    # Private CG may use a stronger SDXL checkpoint while canonical assets
    # and the locked story visual style remain untouched.
    local_cg_model=os.environ.get("VN_LOCAL_CG_CHECKPOINT","").strip()
    specialized=(kind=="local_cg" and not is_animation and
                 job["style"] in ("semireal","realistic","poster") and bool(local_cg_model))
    if specialized:
        if "/" in local_cg_model or "\\" in local_cg_model or not local_cg_model.endswith(".safetensors"):
            raise ValueError("Invalid local CG checkpoint basename")
        model=local_cg_model
        steps=max(32,int(os.environ.get("VN_LOCAL_CG_STEPS","32")))
        cfg=float(os.environ.get("VN_LOCAL_CG_CFG","5"))

    if kind=="sprite" and is_unclothed(spec) and job["style"]=="semireal":
        # Clothed img2img references tend to copy garments even when instructed
        # otherwise. Use a fresh latent and the canonical IPAdapter face only.
        steps=max(14,steps)
        cfg=max(3.2,cfg)
    if spec.get("preview_only"):
        if kind=="local_cg":
            steps=max(32,steps) if specialized else max(18,round(steps*(2.5 if quality=="cinematic" else 1.8)))
            cfg=cfg if specialized else max(cfg,3.2)
        else:
            steps=max(12,min(18,round(steps*.56)))
    if quality=="fast" and not spec.get("preview_only"):steps=max(12,round(steps*.72))
    elif quality=="cinematic":steps=max(steps,round(steps*1.2))
    width,height=tuple(spec.get("resolution") or ((832,1216) if kind=="sprite" else (1216,704)))
    background=fetch_asset(spec.get("background_asset")) if kind in ("sprite","scene","local_cg") and spec.get("background_asset") else None
    positive,negative=prompt_builder(job,background)
    graph={
      "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":model}},
      "2":{"class_type":"EmptyLatentImage","inputs":{"width":width,"height":height,"batch_size":1}},
      "3":{"class_type":"CLIPTextEncode","inputs":{"clip":["1",1],"text":positive}},
      "4":{"class_type":"CLIPTextEncode","inputs":{"clip":["1",1],"text":negative}},
      "5":{"class_type":"KSampler","inputs":{"model":["1",0],"positive":["3",0],
         "negative":["4",0],"latent_image":["2",0],"seed":int.from_bytes(os.urandom(6),"big"),
         "steps":steps,"cfg":cfg,
         "sampler_name":("euler" if is_animation else
                         "euler_ancestral" if job["style"]=="anime" else "dpmpp_2m"),
         "scheduler":"sgm_uniform" if is_animation else
                     "normal" if job["style"]=="anime" else "karras",
         "denoise":1}},
      "6":{"class_type":"VAEDecode","inputs":{"samples":["5",0],"vae":vae_ref}},
      "7":{"class_type":"SaveImage","inputs":{"images":["6",0],"filename_prefix":"mcp_vn_"+job["id"]}}
    }
    if is_animation:
        # Anima is NOT an SDXL checkpoint. Its native UNET, text encoder
        # and Qwen image VAE have distinct ComfyUI loaders. Never apply
        # SDXL IPAdapter or OpenPose ControlNet to this architecture.
        graph["1"]={"class_type":"UNETLoader","inputs":{
            "unet_name":model,"weight_dtype":"default"}}
        graph["13"]={"class_type":"CLIPLoader","inputs":{
            "clip_name":"qwen_3_06b_base.safetensors",
            "type":"stable_diffusion","device":"default"}}
        graph["14"]={"class_type":"VAELoader","inputs":{
            "vae_name":"qwen_image_vae.safetensors"}}
        graph["3"]["inputs"]["clip"]=["13",0]
        graph["4"]["inputs"]["clip"]=["13",0]
        graph["5"]["inputs"].update({"steps":8,"cfg":1.0})
    if specialized or job["style"] in ("semireal","realistic","poster","anime"):
        # Pony/WAI SDXL-based models use CLIP skip 2. ClipSetLastLayer
        # changes only text conditioning, not face-reference CLIPVision.
        graph["8"]={"class_type":"CLIPSetLastLayer",
                    "inputs":{"clip":["1",1],"stop_at_clip_layer":-2}}
        graph["3"]["inputs"]["clip"]=["8",0]
        graph["4"]["inputs"]["clip"]=["8",0]
    if kind=="local_cg":
        # The *whole frame* is synthesized by ComfyUI on the GPU; no CPU
        # collage is returned as a local story CG. Use the last accepted
        # local frame when possible, or a canonical composition as a seed.
        base=None
        variants=spec.get("local_sprite_assets") or []
        if spec.get("local_basis_asset"):
            # Do not propagate a published-but-incorrect frame as a seed.
            # The home server already verified scene, cast and continuity.
            if spec.get("local_basis_verified") is not True:
                raise ValueError("Unverified local frame cannot be used as an image seed")
            base=fetch_asset(spec["local_basis_asset"])
            if base is None:raise ValueError("Verified reference frame is unavailable")
        elif (not spec.get("local_fresh_composition") and
              len(variants)==len(spec.get("characters") or []) and variants and
              spec.get("location")==spec.get("expected_location")):
            # A local move to another place must never start from the main
            # story's market-square backdrop. New locations use fresh latents.
            base,_=compose_cg(job,fetch_asset)
        # Only the first image in an unchanged setting may use the
        # canonical background with its original character poses.
        if (base is None and not spec.get("local_fresh_composition") and
            background is not None and spec.get("location")==spec.get("expected_location")):
            canonical_job={**job,"kind":"scene","spec":{
                **spec,"local_sprite_assets":[]}}
            base,_=compose_cg(canonical_job,fetch_asset)
        if base is not None:
            prepared=ImageOps.fit(base.convert("RGB"),(width,height),
                method=Image.Resampling.LANCZOS)
            filename=upload_to_comfy(pil_png(prepared),
                "mcp_vn_story_basis_"+job["id"]+".png")
            graph["10"]={"class_type":"LoadImage","inputs":{"image":filename}}
            graph["11"]={"class_type":"VAEEncode","inputs":{
                "pixels":["10",0],"vae":vae_ref}}
            graph["5"]["inputs"].update({"latent_image":["11",0],
                "denoise":.72 if variants else .86})
        # Regional face references keep independent established identities
        # without constraining body poses to canned silhouettes.
        people=(spec.get("characters") or [])
        try:
            if (not is_animation and 1<=len(people)<=4 and
                all(c.get("anchor_face_asset") or c.get("sprite_asset") for c in people)):
                graph["60"]={"class_type":"CLIPVisionLoader","inputs":{
                    "clip_name":"CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"}}
                graph["61"]={"class_type":"IPAdapterModelLoader","inputs":{
                    "ipadapter_file":"ip-adapter-plus-face_sdxl_vit-h.safetensors"}}
                source_model=["1",0]
                for i,actor in enumerate(people):
                    ref=fetch_asset(actor.get("anchor_face_asset") or actor["sprite_asset"])
                    head=ImageOps.fit(ref.convert("RGB"),(512,512),
                        method=Image.Resampling.LANCZOS) if actor.get("anchor_face_asset") else (
                        ImageOps.fit(head_crop(ref),(512,512),
                        method=Image.Resampling.LANCZOS))
                    head_name=upload_to_comfy(pil_png(head),
                        "mcp_vn_story_face_"+str(i)+"_"+job["id"]+".png")
                    mask=regional_face_attention_mask(
                        i,width,height,len(people),actor.get("actor_region"))
                    mask_name=upload_to_comfy(pil_png(mask),
                        "mcp_vn_story_region_"+str(i)+"_"+job["id"]+".png")
                    face_node,region_node,apply_node=str(62+i*3),str(63+i*3),str(64+i*3)
                    graph[face_node]={"class_type":"LoadImage","inputs":{"image":head_name}}
                    graph[region_node]={"class_type":"LoadImage","inputs":{"image":mask_name}}
                    graph[apply_node]={"class_type":"IPAdapterAdvanced","inputs":{
                        "model":source_model,"ipadapter":["61",0],"image":[face_node,0],
                        "clip_vision":["60",0],"attn_mask":[region_node,1],
                        "weight":0.58,"weight_type":"linear","combine_embeds":"concat",
                        "start_at":0.0,"end_at":0.9,"embeds_scaling":"V only"}}
                    source_model=[apply_node,0]
                graph["5"]["inputs"]["model"]=source_model
                print("STORY_REGIONAL_FACES",job["id"],len(people),flush=True)
        except (OSError,HTTPError,URLError,TimeoutError,ValueError) as error:
            for key in ["60","61"]+[str(62+i*3+j) for i in range(len(people)) for j in range(3)]:
                graph.pop(key,None)
            graph["5"]["inputs"]["model"]=["1",0]
            print("STORY_IDENTITY_FALLBACK",job["id"],str(error)[:140],flush=True)
    elif kind=="scene" and spec.get("composition")=="neural_story" and not is_animation:
        # A neural CG must inherit the established location, not start as an
        # isolated portrait on a generic studio latent. Base image is an
        # independently accepted canonical background, never a failed CG.
        if background is None:
            raise ValueError("Accepted location background required for neural CG")
        prepared=ImageOps.fit(background.convert("RGB"),(width,height),
            method=Image.Resampling.LANCZOS)
        bg_name=upload_to_comfy(pil_png(prepared),
            "mcp_vn_scene_environment_"+job["id"]+".png")
        graph["10"]={"class_type":"LoadImage","inputs":{"image":bg_name}}
        graph["11"]={"class_type":"VAEEncode","inputs":{
            "pixels":["10",0],"vae":vae_ref}}
        graph["5"]["inputs"].update({"latent_image":["11",0],"denoise":0.78})
        graph["3"]["inputs"]["text"]+=(
            " Wide environmental shot, recognizable detailed location behind the "
            "characters, not a studio portrait or flat backdrop, a single camera view.")
        # A neural CG replaces the whole shot, so it must be conditioned on
        # immutable identity anchors, NOT on a disposable pose/outfit sprite.
        people=(spec.get("characters") or [])
        assert_cast_supported(people)
        if not people or any(not (p.get("anchor_face_asset") or p.get("anchor_asset"))
                             for p in people):
            raise ValueError("Canonical face/reference missing for neural CG")
        graph["60"]={"class_type":"CLIPVisionLoader","inputs":{
            "clip_name":"CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"}}
        graph["61"]={"class_type":"IPAdapterModelLoader","inputs":{
            "ipadapter_file":"ip-adapter-plus-face_sdxl_vit-h.safetensors"}}
        model_ref=["1",0]
        for i,actor in enumerate(people):
            anchor=fetch_asset(actor.get("anchor_face_asset") or actor["anchor_asset"])
            if anchor is None:
                raise ValueError("Canonical face reference cannot be loaded for "+actor["name"])
            # Face-only image reference preserves identity across camera angles,
            # without forcing the body pose from a studio sprite onto a CG.
            head=(ImageOps.fit(anchor.convert("RGB"),(512,512),
                              method=Image.Resampling.LANCZOS)
                  if actor.get("anchor_face_asset") else
                  ImageOps.fit(head_crop(anchor),(512,512),
                              method=Image.Resampling.LANCZOS))
            filename=upload_to_comfy(pil_png(head),
                "mcp_vn_canonical_face_"+str(i)+"_"+job["id"]+".png")
            img_node=str(62+i*3)
            apply_node=str(64+i*3)
            graph[img_node]={"class_type":"LoadImage","inputs":{"image":filename}}
            # Low face weight on rear poses: keep identity, reduce looking-at-camera prior
            face_weight = 0.74
            subj = str(job.get("prompt") or "").lower()
            if any(w in subj for w in ["from behind","rear","bent forward","buttock","back view","not facing"]):
                face_weight = 0.55
            adapter={"model":model_ref,"ipadapter":["61",0],"image":[img_node,0],
                "clip_vision":["60",0],"weight":face_weight,"weight_type":"linear",
                "combine_embeds":"concat","start_at":0.0,"end_at":0.95,
                "embeds_scaling":"V only"}
            mask=regional_face_attention_mask(
                i,width,height,len(people),actor.get("actor_region"))
            mask_file=upload_to_comfy(pil_png(mask),
                "mcp_vn_cg_face_region_"+str(i)+"_"+job["id"]+".png")
            mask_node=str(63+i*3)
            graph[mask_node]={"class_type":"LoadImage","inputs":{"image":mask_file}}
            adapter["attn_mask"]=[mask_node,1]
            graph[apply_node]={"class_type":"IPAdapterAdvanced","inputs":adapter}
            model_ref=[apply_node,0]
        graph["5"]["inputs"]["model"]=model_ref
        print("CANONICAL_CG_FACES",job["id"],len(people),flush=True)
    elif kind=="scene" and background is not None and not is_animation and spec.get("composition")!="neural_story":
        source=scene_mask(background,spec.get("characters",[]))
        filename=upload_to_comfy(pil_png(source),"mcp_vn_mask_"+job["id"]+".png")
        graph["10"]={"class_type":"LoadImage","inputs":{"image":filename}}
        graph["11"]={"class_type":"InpaintModelConditioning","inputs":{
          "positive":["3",0],"negative":["4",0],"vae":vae_ref,
          "pixels":["10",0],"mask":["10",1],"noise_mask":True}}
        graph["5"]["inputs"].update({"positive":["11",0],"negative":["11",1],
                                      "latent_image":["11",2],"denoise":.88})
        graph["12"]={"class_type":"ImageCompositeMasked","inputs":{
          "destination":["10",0],"source":["6",0],"x":0,"y":0,
          "resize_source":False,"mask":["10",1]}}
        graph["7"]["inputs"]["images"]=["12",0]
    elif kind=="sprite" and not is_unclothed(spec) and not wants_fresh_latent(
            spec.get("variant",{}).get("pose","standing"),bool(spec.get("face_asset"))) and (
            spec.get("anchor_asset") or spec.get("previous_sprite_asset")):
        try:
            # Always return to the canonical anchor, rather than iterating over the
            # last generated frame (which would cause identity drift).
            asset=(spec.get("anchor_asset") if spec.get("anchor_style")==job.get("style")
                   else spec.get("previous_sprite_asset"))
            if not asset:raise ValueError("No same-style anchor")
            old=fetch_asset(asset)
            # A neutral matte prevents an earlier scene becoming a background in img2img.
            matte=Image.new("RGBA",old.size,(125,125,125,255))
            matte.alpha_composite(old)
            prepared=ImageOps.fit(matte.convert("RGB"),(width,height),method=Image.Resampling.LANCZOS)
            filename=upload_to_comfy(pil_png(prepared),"mcp_vn_ref_"+job["id"]+".png")
            graph["10"]={"class_type":"LoadImage","inputs":{"image":filename}}
            graph["11"]={"class_type":"VAEEncode","inputs":{"pixels":["10",0],"vae":vae_ref}}
            previous_error=str(job.get("error","")).lower()
            # Stronger img2img freedom after a failed color check; preserve pose
            # on normal first-pass identity-preserving character revisions.
            changing_pose=spec.get("variant",{}).get("pose","standing")!="standing"
            changing_outfit=spec.get("variant",{}).get("outfit","default")!="default"
            denoise=.64 if (changing_pose or changing_outfit) else .43
            if job.get("attempts",1)>1 and "color" in previous_error:denoise=max(denoise,.74)
            graph["5"]["inputs"].update({"latent_image":["11",0],"denoise":denoise})
        except (HTTPError,OSError,ValueError) as error:
            print("REFERENCE_UNAVAILABLE",job["id"],str(error)[:120],flush=True)
    # v5 identity lock: IP-Adapter Plus Face SDXL conditions the diffusion
    # model with the immutable canonical face crop. This supplements body
    # img2img, which alone cannot preserve a face across new poses/outfits.
    if kind=="sprite" and not is_animation and spec.get("face_asset"):
        enabled=os.environ.get("VN_IPADAPTER","1").lower() not in ("0","false","off")
        previous_error=str(job.get("error","")).lower()
        if enabled and not (job.get("attempts",1)>1 and ("ipadapter" in previous_error or "clipvision" in previous_error)):
            try:
                face=fetch_asset(spec["face_asset"]).convert("RGB")
                face=ImageOps.fit(face,(512,512),method=Image.Resampling.LANCZOS)
                name=upload_to_comfy(pil_png(face),"mcp_vn_face_"+job["id"]+".png")
                graph["15"]={"class_type":"CLIPVisionLoader","inputs":{
                    "clip_name":"CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"}}
                graph["16"]={"class_type":"IPAdapterModelLoader","inputs":{
                    "ipadapter_file":"ip-adapter-plus-face_sdxl_vit-h.safetensors"}}
                graph["17"]={"class_type":"LoadImage","inputs":{"image":name}}
                graph["18"]={"class_type":"IPAdapterAdvanced","inputs":{
                    "model":["1",0],"ipadapter":["16",0],"image":["17",0],
                    "clip_vision":["15",0],
                    "weight":0.70 if is_unclothed(spec) else 0.78,"weight_type":"linear",
                    "combine_embeds":"concat","start_at":0.0,"end_at":0.9,
                    "embeds_scaling":"V only"}}
                graph["5"]["inputs"]["model"]=["18",0]
                # Allow wardrobe/pose changes while the face reference is fixed.
                if "11" in graph and graph["11"].get("class_type")=="VAEEncode":
                    has_variant=spec.get("variant",{}).get("pose","standing")!="standing" or (
                        spec.get("variant",{}).get("outfit","default")!="default")
                    graph["5"]["inputs"]["denoise"]=.73 if has_variant else .52
                print("IDENTITY_IPADAPTER",job["id"],"face_anchor",spec["face_asset"],flush=True)
            except (OSError,HTTPError,ValueError,TimeoutError) as exc:
                print("IPADAPTER_FALLBACK",job["id"],str(exc)[:150],flush=True)
    # Approved A/B test: pose ControlNet improves running and kneeling
    # full-body framing without reducing CLIP face identity on the tested character.
    # Unsupported poses intentionally fall back to textual pose prompts.
    # A neural CG has no 'variant.pose'. Defaulting it to "standing"
    # silently activates an unrelated ControlNet guide on every shot.
    pose_kind=str((spec.get("variant") or {}).get("pose","standing")) if kind=="sprite" else ""
    if kind=="scene" and spec.get("composition")=="neural_story":
        subj = str(job.get("prompt") or "").lower()
        # Only use a hard-coded OpenPose guide for a matching explicit
        # camera+body configuration. Do not infer a rear pose from a location
        # word ("rear door", "wall") or body-part mentions alone.
        from_rear=any(w in subj for w in (
            "from behind","rear view","back view","from the back"))
        bent=any(w in subj for w in (
            "bent forward","bending forward","leaning forward"))
        wall=any(w in subj for w in ("against the wall","braced on the wall"))
        if from_rear and bent:
            pose_kind = "bent_forward_rear"
        elif from_rear and wall:
            pose_kind = "leaning_wall_rear"
    pose_filename=pose_control_guide(pose_kind)
    use_pose_library_v2=False
    approved_reference=None
    action_contract=resolve_scene_action(spec,job.get("prompt") or spec.get("prompt"))
    action_required=(kind=="scene" and action_contract["required"])
    pose_reference_enabled=(
        os.environ.get("VN_POSE_REFERENCE_ENABLED","1").lower() in ("1","true","yes"))
    if action_required and not pose_reference_enabled:
        print("POSE_REFERENCE_SKIPPED",job["id"],"disabled",flush=True)
    if kind=="scene" and spec.get("composition")=="neural_story" and pose_reference_enabled:
        approved_reference,decision=choose_approved_reference(str(job.get("prompt") or ""),spec=spec)
        print("POSE_REFERENCE_DECISION",job["id"],decision,
              "contract",action_contract,flush=True)
        if action_required and approved_reference is None:
            # No matching reference: leave generation guided by the exact
            # scene text instead of blocking the entire CG rendering.
            print("POSE_REFERENCE_ADVISORY",job["id"],decision,flush=True)
        if approved_reference:
            pose_kind=approved_reference["name"]
            pose_filename=approved_reference["file"].name
            print("POSE_REFERENCE_SELECTED",job["id"],pose_kind,flush=True)
        else:
            print("POSE_REFERENCE_SKIPPED",job["id"],decision,flush=True)
    # Draft library: opt-in only. A near-match must never silently override
    # the storyteller's camera geometry or a previously approved guide.
    if approved_reference is None and kind=="scene" and spec.get("composition")=="neural_story" and (
        os.environ.get("VN_POSE_LIBRARY_V2","0").lower() in ("1","true","yes")
    ):
        suggested=select_story_pose(str(job.get("prompt") or ""))
        if suggested:
            pose_kind=suggested
            pose_filename=suggested+".png"
            use_pose_library_v2=True
    env_enabled=os.environ.get("VN_POSE_CONTROL","1").lower() not in ("0","false","off")
    if approved_reference is not None and not env_enabled:
        raise RuntimeError("Approved DWPose was selected but ControlNet is disabled")
    previous_error=str(job.get("error","")).lower()
    if ((kind=="sprite" or (kind=="scene" and spec.get("composition")=="neural_story")) and not is_animation and env_enabled and pose_filename and
        not (approved_reference is None and job.get("attempts",1)>1 and ("controlnet" in previous_error or
               "control net" in previous_error or "out of memory" in previous_error))):
        try:
            directory=Path(os.environ.get("VN_POSE_GUIDE_DIR",
                str(Path.home()/".local/share/mcp-vn/pose-guides")))
            if use_pose_library_v2:
                directory=Path(os.environ.get("VN_POSE_LIBRARY_V2_DIR",
                    str(Path.home()/".local/share/mcp-vn/pose-guides-v2/cg")))
            if approved_reference:
                directory=approved_reference["file"].parent
            filename=directory/pose_filename
            if (use_pose_library_v2 or approved_reference) and filename.is_file():
                with Image.open(filename) as guide_image:
                    if guide_image.size!=(width,height):
                        raise ValueError("CG OpenPose guide has wrong canvas size")
            if not filename.is_file():
                raise FileNotFoundError("Pose guide not available: "+str(filename))
            guide_upload=upload_to_comfy(filename.read_bytes(),
                  "mcp_vn_pose_"+job["id"]+".png")
            graph["23"]={"class_type":"ControlNetLoader","inputs":{
              "control_net_name":"xinsir-openpose-sdxl-1.0.safetensors"}}
            graph["24"]={"class_type":"LoadImage","inputs":{"image":guide_upload}}
            graph["25"]={"class_type":"ControlNetApplyAdvanced","inputs":{
              "positive":graph["5"]["inputs"]["positive"],
              "negative":graph["5"]["inputs"]["negative"],
              "control_net":["23",0],"image":["24",0],
              "strength":retry_plan(job)["control_strength"],
              "start_percent":0.0,"end_percent":retry_plan(job)["control_end"]}}
            graph["5"]["inputs"]["positive"]=["25",0]
            graph["5"]["inputs"]["negative"]=["25",1]
            if approved_reference:
                control=graph.get("25",{})
                assert (control.get("class_type")=="ControlNetApplyAdvanced"
                    and graph["5"]["inputs"]["positive"]==["25",0]
                    and graph["5"]["inputs"]["negative"]==["25",1]), (
                        "Approved DWPose must be connected to the sampler")
                print("POSE_CONTROL_GRAPH_VERIFIED",job["id"],
                      approved_reference["name"],
                      "guide",approved_reference["file"].name,
                      "strength",control["inputs"]["strength"],
                      "end",control["inputs"]["end_percent"],
                      "nodes",("23","24","25"),flush=True)
            print("POSE_CONTROL_ACTIVE",job["id"],pose_kind,flush=True)
        except (OSError,HTTPError,URLError,ValueError,TimeoutError,AssertionError) as error:
            if approved_reference:
                raise RuntimeError(
                    "Approved DWPose ControlNet could not be applied: "+str(error)) from error
            print("POSE_CONTROL_FALLBACK",job["id"],repr(error),flush=True)
    # Try a bounded local edit only if the previous rejected attempt has an
    # immutable, SHA-verified source and an independently grounded region.
    # Otherwise the existing full-generation graph is retained unchanged.
    if kind in ("scene","sprite","local_cg") and not is_animation:
        if apply_inpaint_graph(job,graph,vae_ref,upload_to_comfy):
            print("LOCAL_REPAIR_GRAPH",job["id"],retry_plan(job)["category"],flush=True)
    if is_animation and kind=="scene":
        # SDXL scene inpainting is incompatible with this model architecture.
        # The image is text-rendered as one coherent frame instead.
        print("ANIMA_SCENE_FRESH_COMPOSITION",job["id"],flush=True)
    return graph, background

def video_graph(job):
    graph={
      "37":{"class_type":"UNETLoader","inputs":{"unet_name":"wan2.2_ti2v_5B_fp16.safetensors","weight_dtype":"default"}},
      "38":{"class_type":"CLIPLoader","inputs":{"clip_name":"umt5_xxl_fp8_e4m3fn_scaled.safetensors","type":"wan","device":"default"}},
      "39":{"class_type":"VAELoader","inputs":{"vae_name":"wan2.2_vae.safetensors"}},
      "48":{"class_type":"ModelSamplingSD3","inputs":{"model":["37",0],"shift":8}},
      "6":{"class_type":"CLIPTextEncode","inputs":{"clip":["38",0],"text":job["prompt"]}},
      "7":{"class_type":"CLIPTextEncode","inputs":{"clip":["38",0],"text":"blurry, static, flicker, motion artifacts, text, watermark, child, underage"}},
      "55":{"class_type":"Wan22ImageToVideoLatent","inputs":{"vae":["39",0],"width":512,"height":288,"length":17,"batch_size":1}},
      "3":{"class_type":"KSampler","inputs":{"model":["48",0],"positive":["6",0],"negative":["7",0],
        "latent_image":["55",0],"seed":int.from_bytes(os.urandom(6),"big"),"steps":8,
        "cfg":5,"sampler_name":"uni_pc","scheduler":"simple","denoise":1}},
      "8":{"class_type":"VAEDecode","inputs":{"samples":["3",0],"vae":["39",0]}},
      "57":{"class_type":"CreateVideo","inputs":{"images":["8",0],"fps":8}},
      "58":{"class_type":"SaveVideo","inputs":{"video":["57",0],"filename_prefix":"mcp_vn_"+job["id"],
         "format":"mp4","codec":"h264"}}
    }
    spec=job.get("spec") or {}
    if spec.get("video_start_asset"):
        if spec.get("video_source_verified") is not True:
            raise ValueError("Video source has not passed independent scene verification")
        still=fetch_asset(spec["video_start_asset"])
        if still is None:raise ValueError("Story video needs the accepted starting CG")
        frame=ImageOps.fit(still.convert("RGB"),(512,288),
            method=Image.Resampling.LANCZOS)
        filename=upload_to_comfy(pil_png(frame),
            "mcp_vn_story_video_start_"+job["id"]+".png")
        graph["70"]={"class_type":"LoadImage","inputs":{"image":filename}}
        graph["55"]["inputs"]["start_image"]=["70",0]
    return graph

def cutout(image):
    global SESSION
    from rembg import new_session, remove
    if SESSION is None:
        with SESSION_LOCK:
            if SESSION is None:
                SESSION=new_session("isnet-general-use",providers=["CPUExecutionProvider"])
    cut=remove(image.convert("RGB"),session=SESSION,alpha_matting=False)
    return cut.convert("RGBA")

def harmonize(sprite,background):
    if background is None:return sprite
    context,rgb=background_context(background)
    src_rgb=sprite.convert("RGB")
    m=sprite.getchannel("A")
    if m.getbbox() is None:return sprite
    sr,sg,sb=ImageStat.Stat(src_rgb,mask=m).mean
    def lum(r,g,b):return .2126*r+.7152*g+.0722*b
    scene_lum=lum(*rgb)
    subject_lum=lum(sr,sg,sb)
    gain=max(.78,min(1.14,((max(40,scene_lum)/max(40,subject_lum))**.28)))
    changed=ImageEnhance.Brightness(sprite.convert("RGB")).enhance(gain)
    # Weak color grading aligns light temperature without replacing facial identity.
    delta=max(-7,min(7,(rgb[0]-rgb[2])*0.09))
    r,g,b=changed.split()
    r=r.point(lambda v: max(0,min(255,int(v+delta))))
    b=b.point(lambda v: max(0,min(255,int(v-delta))))
    return Image.merge("RGBA",(r,g,b,m))

def head_crop(sprite):
    """Match the immutable server-side crop geometry for face likeness QA."""
    im=sprite.convert("RGBA")
    mask=im.getchannel("A")
    bbox=mask.point(lambda a:255 if a>90 else 0).getbbox()
    if not bbox:raise ValueError("Sprite has no head")
    x0,y0,x1,y1=bbox
    side=max(32,min(im.width,im.height,round(min((x1-x0)*.82,(y1-y0)*.24))))
    cx=(x0+x1)//2
    cy=int(y0+side*.49)
    matte=Image.new("RGBA",im.size,(128,128,128,255))
    matte.alpha_composite(im)
    x=int(cx-side/2);y=int(cy-side/2)
    # Boundaries rarely crop; edge extension keeps the reference geometry.
    clipped=ImageOps.expand(matte,border=side,fill=(128,128,128,255))
    return clipped.crop((x+side,y+side,x+side*2,y+side*2)).convert("RGB")

def assess(job,raw,background):
    assess_t0=time.monotonic()
    kind=job["kind"]
    reasons=[]
    metrics={}
    if kind=="video":
        return raw,{"passed":raw[4:8]==b"ftyp","reasons":([] if raw[4:8]==b"ftyp" else ["Not MP4"]),
                    "metrics":{"bytes":len(raw)},"semantic_status":"not_requested"}
    with Image.open(io.BytesIO(raw)) as source:
        source.load()
        image=ImageOps.exif_transpose(source).convert("RGBA")
    width,height=image.size
    expected=tuple((job.get("spec") or {}).get("resolution") or ((832,1216) if kind=="sprite" else (1216,704)))
    if (width,height)!=expected:
        reasons.append(f"Wrong size {width}x{height}, expected {expected[0]}x{expected[1]}")
    metrics.update({"width":width,"height":height,"bytes":len(raw)})
    metrics["retry_category"]=retry_plan(job)["category"]
    if kind=="scene" and (job.get("spec") or {}).get("composition")=="neural_story":
        metrics["visual_action_contract"]=resolve_scene_action(
            job.get("spec") or {},job.get("prompt") or (job.get("spec") or {}).get("prompt"))
    spec=job.get("spec") or {}
    if kind in ("scene","local_cg") and spec.get("composition")=="neural_story":
        # Cheap structural QA before both GPU pose geometry and CPU VLM.
        # A screenshot-like multi-panel layout is not an accepted single CG.
        panels=detect_four_panel_collage(image)
        metrics["panel_seam_x"]=panels["seam_x_ratio"]
        metrics["panel_seam_y"]=panels["seam_y_ratio"]
        metrics["panel_repeat_left"]=panels["repeat_left"]
        metrics["panel_repeat_right"]=panels["repeat_right"]
        metrics["panel_collage_detected"]=panels["detected"]
        if panels["detected"]:
            reasons.append("CG multi-panel collage: expected one continuous scene")
    if kind=="sprite":
        image=cutout(image)
        image=harmonize(image,background)
        alpha=image.getchannel("A")
        hist=alpha.histogram()
        total=width*height
        transparent=sum(hist[:24])/total
        opaque=sum(hist[220:])/total
        mask=alpha.point(lambda v:255 if v>80 else 0)
        bbox=mask.getbbox()
        metrics.update({"transparent_fraction":round(transparent,3),"opaque_fraction":round(opaque,3),
                        "foreground_fraction":round(1-transparent,3)})
        if transparent<.12:reasons.append("Insufficient transparent background")
        if opaque<.045:reasons.append("Too little visible foreground")
        if not bbox:
            reasons.append("Empty subject")
        else:
            left,top,right,bottom=bbox
            metrics.update({"bbox_top":round(top/height,3),"bbox_bottom":round(bottom/height,3),
                "bbox_width":round((right-left)/width,3)})
            if right-left<width*.19 or bottom-top<height*.38:
                reasons.append("Subject too small or cropped")
            if top>height*.34 or bottom<height*.65:
                reasons.append("Full-body subject not inside frame")
    if kind=="local_cg":
        try:
            # Compare against the ORIGINAL canonical characters, not the
            # newly generated private sprite variants composing this shot.
            canonical_job={**job,"kind":"scene","spec":{
                **(job.get("spec") or {}),"local_sprite_assets":[]}}
            base,_=compose_cg(canonical_job,fetch_asset)
            old=base.resize(image.size).convert("RGB")
            delta=ImageChops.difference(image.convert("RGB"),old)
            score=sum(ImageStat.Stat(delta).mean)/3
            metrics["visual_delta_mae"]=round(score,2)
            if score<5.5:
                reasons.append("CG unchanged: neural re-render did not change visual composition")
        except Exception as error:
            reasons.append("Cannot validate new CG against original: "+str(error)[:90])
    output=pil_png(image)
    metrics["result_bytes"]=len(output)
    semantic="unavailable"
    warnings=[]
    qa_t0=time.monotonic()
    # This span includes image decode, matte/cutout and final PNG encode,
    # which happen before the existing QA stopwatch starts.
    metrics["qa_presemantic_ms"]=round(max(0,(qa_t0-assess_t0)*1000),3)
    # Cheap DWPose geometry before expensive CPU VLM: mismatched poses are
    # rejected without spending ~25s asking the VLM to describe other details.
    spec=job.get("spec") or {}
    if not reasons and kind=="scene" and wall_brace_required({**spec,"prompt":job.get("prompt") or spec.get("prompt")}):
        ref,ref_reason=choose_approved_reference(str(job.get("prompt") or spec.get("prompt") or ""),spec=spec)
        if not ref:
            warnings.append("Pose QA unobservable: "+str(ref_reason)[:80])
            metrics["pose_geometry"]={"verified":False,"verdict":"unobservable",
                                      "reason":ref_reason}
        else:
            try:
                geometry=verify_with_comfy(job,output,ref,COMFY,OUTPUT,request,upload_to_comfy)
                metrics["pose_geometry"]=geometry
                contact_roi=geometry.get("contact_roi") or {}
                if contact_roi.get("verdict")=="violated":
                    reasons.append("CG hands are spatially separated from required contact surface")
                if contact_roi:
                    metrics["contact_roi_verdict"]=str(contact_roi.get("verdict","unobservable"))
                    metrics["contact_roi_reason"]=str(contact_roi.get("reason",""))
                if not geometry.get("verified"):
                    pose_reason=str(geometry.get("reason","unknown"))
                    # Geometry alone is not semantic evidence of an incorrect
                    # action, especially with occluded joints or rear views.
                    # Strong physical-contact violations remain independent
                    # hard reasons above, and visual scene gates still run.
                    geometry["verdict"]="unobservable"
                    warnings.append("DWPose could not confirm principal pose: "+pose_reason[:90])
                    metrics["pose_qa_inconclusive"]=True
            except (OSError,ValueError,KeyError,HTTPError,URLError,TimeoutError) as err:
                metrics["pose_geometry"]={"verified":False,"reason":"verification_unavailable",
                    "details":str(err)[:140]}
                warnings.append("CG pose geometry verification unavailable")
    # Profile the geometry gate within this exact attempt, including any
    # Comfy verification wait. Never infer it from unpaired job percentiles.
    metrics["qa_pose_geometry_ms"]=round(
        max(0,(time.monotonic()-qa_t0)*1000),3)
    if reasons and metrics.get("panel_collage_detected"):
        semantic="failed"
        metrics["vlm_skipped_reason"]="panel_layout_failed"
    elif reasons and "pose_geometry" in metrics:
        semantic="failed"
        metrics["vlm_skipped_reason"]="pose_geometry_failed"
    if not reasons and os.environ.get("VN_VISION_QA","1").lower() not in ("0","false","off"):
        vision_started=time.monotonic()
        try:
            payload={"kind":"scene" if kind=="local_cg" else kind,
                     "quality":(job.get("spec") or {}).get("quality","standard"),
                     "spec":{**(job.get("spec") or {}),
                             "prompt":job.get("prompt") or (job.get("spec") or {}).get("prompt")},
                     "image_b64":base64.b64encode(output).decode("ascii")}
            if kind=="sprite" and (job.get("spec") or {}).get("face_asset"):
                try:
                    ref=fetch_asset(job["spec"]["face_asset"])
                    payload["identity_b64"]=base64.b64encode(pil_png(ref)).decode("ascii")
                    payload["candidate_face_b64"]=base64.b64encode(pil_png(head_crop(image))).decode("ascii")
                except Exception as identity_err:
                    metrics["identity_check_error"]=str(identity_err)[:100]
                    raise ValueError("Mandatory sprite face reference unavailable") from identity_err
            metrics["qa_vision_prepare_ms"]=round(
                max(0,(time.monotonic()-vision_started)*1000),3)
            http_started=time.monotonic()
            try:
                validation=request(VISION,"/judge","POST",payload,timeout=90)
            finally:
                metrics["qa_vision_http_ms"]=round(
                    max(0,(time.monotonic()-http_started)*1000),3)
            # Server times are advisory, not evidence for an acceptance verdict.
            # Monotonic durations from this ONE request must also be mutually
            # possible: nested decode+lock+model fit before-send; before-send
            # fits the client HTTP roundtrip; caption inference fits model.
            # Invalid server timings are discarded AS A GROUP to avoid a
            # seemingly credible but impossible partial timing breakdown.
            stage_data=validation.get("qa_stage_ms")
            stage_fields=("input_decode","lock_wait","model_analyze","handler_before_send")
            def finite_stage(value):
                return (float(value) if type(value) in (int,float)
                        and value==value and 0<=value<=300000 else None)
            stage_values=({field:finite_stage(stage_data.get(field))
                           for field in stage_fields}
                          if isinstance(stage_data,dict) else {})
            caption_raw=validation.get("vlm_caption_ms")
            caption_ms=finite_stage(caption_raw)
            # Cross-process monotonic clocks have unrelated epochs. Compare
            # durations only, with 2ms headroom for per-span rounding.
            stage_tolerance_ms=2.0
            stage_reason=None
            if not isinstance(stage_data,dict):
                stage_reason="missing_server_stages"
            elif any(stage_values[field] is None for field in stage_fields):
                stage_reason="invalid_server_stages"
            elif stage_values["handler_before_send"] > metrics["qa_vision_http_ms"]+stage_tolerance_ms:
                stage_reason="handler_exceeds_http"
            elif (stage_values["input_decode"]+stage_values["lock_wait"]+
                  stage_values["model_analyze"] >
                  stage_values["handler_before_send"]+stage_tolerance_ms):
                stage_reason="nested_spans_exceed_handler"
            elif caption_ms is None:
                stage_reason="invalid_or_missing_caption"
            elif caption_ms > stage_values["model_analyze"]+stage_tolerance_ms:
                stage_reason="caption_exceeds_analyze"
            if stage_reason:
                metrics["qa_vision_server_stage_ms"]={}
                metrics["qa_vision_stage_integrity"]="unavailable" if stage_reason=="missing_server_stages" else "untrusted"
                metrics["qa_vision_stage_integrity_reason"]=stage_reason
            else:
                metrics["qa_vision_server_stage_ms"]={
                    field:round(stage_values[field],3) for field in stage_fields}
                metrics["qa_vision_caption_ms"]=round(caption_ms,3)
                metrics["qa_vision_stage_integrity"]="consistent"
            semantic=validation.get("status","unavailable")
            if semantic not in ("passed","failed","unavailable"):semantic="unavailable"
            metrics["vlm_caption"]=str(validation.get("caption",""))[:145]
            metrics["vlm_seconds"]=float(validation.get("duration_seconds",0))
            if validation.get("environment"):
                metrics["environment_predicted"]=validation["environment"]
            if validation.get("identity_similarity") is not None:
                metrics["identity_similarity"]=float(validation["identity_similarity"])
            if validation.get("identity_face_visibility"):
                metrics["identity_face_visibility"]=str(validation["identity_face_visibility"])
            # Independent visual-grounding measurements are retained in the
            # server job record. A generic VLM answer is not proof of the cast.
            for field in ("scene_action_observation","scene_action_evidence",
                          "scene_count_verified","scene_location_verified",
                          "scene_count_confidence","scene_location_confidence",
                          "scene_solo_score","scene_pair_score",
                          "scene_action_contrast","scene_action_verified"):
                if validation.get(field) is not None:
                    metrics[field]=validation[field]
            warnings.extend(str(x)[:180] for x in validation.get("warnings",[])[:4])
            if semantic=="failed":
                reasons.extend(str(x)[:170] for x in validation.get("reasons",[])[:4])
                if not validation.get("reasons"):
                    reasons.append("Semantic QA rejected image without specific reasons")
            elif semantic=="unavailable":
                metrics["vlm_error"]=str(validation.get("reason","VLM unavailable"))[:140]
        except (OSError,ValueError,TimeoutError,URLError,HTTPError) as error:
            semantic="unavailable"
            metrics["vlm_error"]=str(error)[:140]
        finally:
            metrics["qa_vision_attempt_ms"]=round(
                max(0,(time.monotonic()-vision_started)*1000),3)
    # Never trust a generic "passed" verdict if a required action was not
    # affirmatively verified by vision. This check is independent of QA's
    # status field so future VLM changes cannot accidentally bypass it.
    action_spec={**(job.get("spec") or {}),
                 "prompt":job.get("prompt") or (job.get("spec") or {}).get("prompt")}
    if kind=="scene" and wall_brace_required(action_spec) and not reasons:
        if metrics.get("scene_action_verified") is not True:
            # For an explicitly required physical action, unknown evidence is
            # NOT permission to publish. Keep the prior accepted frame and
            # let the retry policy target this exact missing contact.
            reasons.append("Mandatory CG wall contact not independently verified")
            if metrics.get("pose_geometry",{}).get("verified") is True:
                warnings.append("DWPose skeleton match is not proof of surface contact")
    # Location validation is critical: never replace the canonical background
    # with an unchecked room or an unrelated building if vision daemon is offline.
    spec=job.get("spec") or {}
    environment=(spec.get("environment") or {}).get("id","unclassified")
    # Default to fail-closed whenever the image requires semantic QA. Avoid
    # marking technical-only sprite checks as independently verified. Fully
    # deterministic composites with known accepted inputs remain unchanged.
    semantic_required=(kind=="sprite" or kind=="local_cg" or
        (kind=="scene" and spec.get("composition")=="neural_story") or
        (kind=="background" and environment!="unclassified") or
        (kind=="scene" and environment!="unclassified" and
         spec.get("composition")!="anchored_composite"))
    if semantic_required and semantic=="unavailable":
        reasons.append("Semantic QA unavailable: keeping last accepted asset")
    if (kind in ("scene","local_cg") and
        spec.get("composition")=="neural_story" and environment!="unclassified"
        and semantic=="passed" and
        metrics.get("scene_location_verified") is not True):
        # Location unknown is not permission to publish a wrong landscape.
        reasons.append("Required CG location not independently verified")
    # Versioned, bounded evidence is persisted separately from scalar metrics.
    def verdict(value,violation=False):
        return "verified" if value is True else ("violated" if violation else "unobservable")
    evidence={"version":1}
    if kind in ("scene","local_cg"):
        evidence["count"]={"verdict":verdict(metrics.get("scene_count_verified")),
                           "confidence":metrics.get("scene_count_confidence")}
    if kind in ("background","scene","local_cg"):
        evidence["location"]={"verdict":verdict(metrics.get("scene_location_verified")),
                              "confidence":metrics.get("scene_location_confidence")}
    if kind=="sprite":
        sim=metrics.get("identity_similarity")
        visibility=metrics.get("identity_face_visibility")
        evidence["identity"]={"verdict":"unobservable" if visibility=="unobservable" else
            "violated" if sim is not None and sim<.80 else
            "verified" if sim is not None and sim>=.86 else "unobservable",
            "confidence":sim if visibility!="unobservable" else None,
            "reason":"face_occluded" if visibility=="unobservable" else "face_similarity"}
        if spec.get("face_asset") and evidence["identity"]["verdict"]!="verified":
            reasons.append("Mandatory sprite identity is "+evidence["identity"]["verdict"])
    if kind=="scene" and wall_brace_required(action_spec):
        features=metrics.get("scene_action_evidence")
        features=features if isinstance(features,dict) else {}
        evidence["action"]={"verdict":verdict(metrics.get("scene_action_verified"),
                              features.get("ground_pose") is True),
                            "features":features}
    qa_t1=time.monotonic()
    qa_ms=(qa_t1-qa_t0)*1000
    metrics["qa_assess_total_ms"]=round(max(0,(qa_t1-assess_t0)*1000),3)
    # Explicit unattributed residue: do not call it network or CLIP time.
    metrics["qa_remaining_ms"]=round(max(0,qa_ms-
        metrics.get("qa_pose_geometry_ms",0)-
        metrics.get("qa_vision_attempt_ms",0)),3)

    return output,{"passed":not reasons,"reasons":reasons,"warnings":warnings,
                   "metrics":metrics,"evidence":evidence,"semantic_status":semantic,
                   "timings":{"qa_ms":qa_ms}}

def run_comfy(job,graph):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    saved=load_manifest(job)
    attempt=int(job.get("attempts") or 1)
    reuse=(saved and (saved["attempt"]==attempt or
            (saved["attempt"]==attempt-1 and not job.get("error"))))
    if reuse:
        pid=saved["prompt_id"]
        print("RESUMING_COMFY",job["id"],pid,flush=True)
    else:
        result=request(COMFY,"/prompt","POST",{"prompt":graph,
            "client_id":"mcp-vn-"+job["id"]})
        pid=result["prompt_id"]
        persist_manifest(job,pid,workflow_digest(graph))
        print("SUBMITTED",job["id"],pid,job["kind"],job.get("style"),flush=True)
    timeout=time.monotonic()+(2400 if job["kind"]=="video" else 900)
    while time.monotonic()<timeout:
        time.sleep(POLL)
        hist=request(COMFY,"/history/"+pid)
        if pid not in hist:continue
        status=hist[pid].get("status",{})
        if status.get("status_str")!="success":
            raise RuntimeError("ComfyUI "+str(status)[:700])
        prefix="mcp_vn_"+job["id"]
        ext=".mp4" if job["kind"]=="video" else ".png"
        outputs=hist[pid].get("outputs") or {}
        node="58" if job["kind"]=="video" else "7"
        result=outputs.get(node) or {}
        files=result.get("images") or result.get("gifs") or result.get("videos") or []
        if files and isinstance(files[0],dict):
            info=files[0]
            filename=str(info.get("filename") or "")
            subfolder=str(info.get("subfolder") or "")
            selected=(OUTPUT/subfolder/filename).resolve()
            if not (filename.startswith(prefix) and filename.endswith(ext) and
                    selected.is_relative_to(OUTPUT.resolve())):
                raise RuntimeError("Unsafe or unexpected ComfyUI output location")
        elif job["kind"]=="video":
            files=sorted(OUTPUT.glob(prefix+"_*"+ext),key=lambda x:x.stat().st_mtime)
            if not files:raise RuntimeError("ComfyUI video output not found")
            selected=files[-1]
        else:
            raise RuntimeError("ComfyUI image history lacks output file reference")
        raw=selected.read_bytes()
        if len(raw)>100_000_000:raise RuntimeError("Output too large")
        return raw,ext
    raise TimeoutError("Generation timed out")

def stage(job,step,timings=None):
    try:
        request(SERVER,"/worker/stage/"+job["id"],"POST",
            {"stage":step,"timings":timings or {}},timeout=8)
    except Exception as exc:
        print("STAGE_ERROR",job["id"],step,str(exc)[:120],flush=True)

def fail(job,error):
    print("JOB_ERROR",job["id"],repr(error),flush=True)
    terminal=permanent_render_failure(error)
    try:request(SERVER,"/worker/fail/"+job["id"],"POST",
                {"error":str(error),"permanent":terminal},timeout=20)
    except Exception as exc:print("REPORT_ERROR",job["id"],repr(exc),flush=True)

def finalize(job,raw,background,generation_ms=0,composition_metrics=None):
    try:
        stage(job,"postprocess",{"generation_ms":generation_ms})
        started=time.monotonic()
        final,report=assess(job,raw,background)
        post_ms=max(0,(time.monotonic()-started)*1000-report.get("timings",{}).get("qa_ms",0))
        report.setdefault("timings",{}).update(
           {"generation_ms":generation_ms,"postprocess_ms":post_ms})
        if composition_metrics:
            report.setdefault("metrics",{}).update(composition_metrics)
        if not report["passed"]:
            retry=retry_plan({**job,"attempts":int(job.get("attempts",1))+1,
                         "error":"; ".join(report.get("reasons") or [])})
            archived=archive_rejected_candidate(job,final,
                report.get("reasons") or [],retry["category"])
            if archived:report.setdefault("metrics",{})["repair_candidate_saved"]=True
        else:
            cleanup_repair(job)
        if job.get("kind")=="local_cg":
            report.setdefault("metrics",{})["checkpoint_name"]=(
                os.environ.get("VN_LOCAL_CG_CHECKPOINT") or
                STYLES[job["style"]][0])[:110]
        stage(job,"publishing",report["timings"])
        if (job.get("spec") or {}).get("spec_version",0)>=4:
            response=request(SERVER,"/worker/qa/"+job["id"],"POST",report,timeout=30)
            if response["job"]["status"]!="working":
                # A failed QA verdict must never be rewritten as passed.
                # The game server owns retries and preserves all failure evidence.
                if response["job"]["status"]!="queued":
                    cleanup_repair(job)
                print("QUALITY_REJECTED",job["id"],report.get("reasons"),flush=True)
                return
        mime="video/mp4" if job["kind"]=="video" else "image/png"
        published=request(SERVER,"/worker/complete/"+job["id"],"POST",final,
                          {"Content-Type":mime},timeout=90)
        status=published["job"]
        cleanup_repair(job)
        print("PUBLISHED",job["id"],"applied",status.get("applied"),
              "quality",status.get("quality_status"),"timings",status.get("timings"),flush=True)
    except Exception as error:
        fail(job,error)

def generate_gpu(job):
    stage(job,"preparing")
    t0=time.monotonic()
    if job["kind"]=="video":
        graph=video_graph(job);background=None
    else:
        graph,background=image_graph(job)
    sampler=(graph.get("5") if job["kind"]!="video" else graph.get("3")) or {}
    settings=sampler.get("inputs") or {}
    positive=(graph.get("3",{}).get("inputs",{}).get("text") or "")
    negative=(graph.get("4",{}).get("inputs",{}).get("text") or "")
    checkpoint=graph.get("1",{}).get("inputs",{}).get("ckpt_name") or ""
    fingerprint=lambda value:hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
    trace={"render_seed":settings.get("seed",0),
        "render_model":checkpoint[:110],
        "render_retry":retry_plan(job)["category"],
        "prompt_positive_sha":fingerprint(positive),
        "prompt_negative_sha":fingerprint(negative),
        "render_pose_strength":(graph.get("25") or {}).get("inputs",{}).get("strength",0)}
    print("RENDER_GRAPH_TRACE",job["id"],job["kind"],trace,flush=True)
    prep_ms=(time.monotonic()-t0)*1000
    stage(job,"generating",{"prepare_ms":prep_ms})
    t1=time.monotonic()
    raw,_=run_comfy(job,graph)
    elapsed=(time.monotonic()-t1)*1000
    stage(job,"generated",{"prepare_ms":prep_ms,"generation_ms":elapsed})
    return raw,background,elapsed,trace

def cpu_scene(job):
    try:
        stage(job,"preparing")
        t=time.monotonic()
        image,metadata=compose_cg(job,fetch_asset)
        raw=pil_png(image)
        elapsed=(time.monotonic()-t)*1000
        stage(job,"generated",{"compose_ms":elapsed})
        finalize(job,raw,None,0,metadata)
    except Exception as error:
        fail(job,error)

def main():
    print("mcp-vn worker v5, GPU:1 CPU:",CPU_THREADS,SERVER,COMFY,flush=True)
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=CPU_THREADS,thread_name_prefix="vn-cpu")
    # Bounded CPU backlog: no unbounded memory queue even if several generations finish.
    slots=threading.BoundedSemaphore(CPU_THREADS)
    def submit(fn,*args):
        slots.acquire()
        future=pool.submit(fn,*args)
        future.add_done_callback(lambda f:slots.release())
    def cpu_loop():
        while True:
            try:
                row=request(SERVER,"/worker/next?pool=cpu")
                if row.get("job"):
                    submit(cpu_scene,row["job"])
                else:time.sleep(1.5)
            except Exception as err:
                print("CPU_LOOP_ERROR",repr(err),flush=True);time.sleep(5)
    threading.Thread(target=cpu_loop,daemon=True,name="vn-cpu-scheduler").start()
    while True:
        try:
            row=request(SERVER,"/worker/next?pool=gpu")
            if row.get("job"):
                job=row["job"]
                try:
                    raw,bg,ms,trace=generate_gpu(job)
                    submit(finalize,job,raw,bg,ms,trace)
                except Exception as err:fail(job,err)
            else:time.sleep(1.5)
        except (HTTPError,URLError,TimeoutError,KeyError) as err:
            print("CONNECTION_ERROR",repr(err),flush=True);time.sleep(7)
        except Exception as err:
            print("WORKER_ERROR",repr(err),flush=True);time.sleep(6)

if __name__=="__main__":
    main()
