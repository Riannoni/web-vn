#!/usr/bin/env python3
"""Local warm visual QA; CPU default, optional explicit SmolVLM-only GPU experiment."""
import base64
import io
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
from scene_qa_rules import principal_count_evidence, scene_location_evidence
from visual_contract import action_contrast_captions
from wardrobe_contract import wants_unclothed as outfit_requires_bare, clothing_alignment,requested_outerwear_color
from scene_caption_contract import scene_caption_conflicts, scene_action_conflicts, insufficient_scene_caption, caption_asserts_single_person
from identity_observation import face_observability,face_similarity_decision
from qa_profiles import load_profiles
from scene_action_contract import wall_brace_required, check_wall_action

HOST="127.0.0.1"
PORT=int(os.environ.get("VN_VISION_PORT","9312"))
lock=threading.Lock()
THREADS=max(1,min(8,int(os.environ.get("VN_VISION_THREADS","5"))))
import torch
from transformers import CLIPModel,CLIPProcessor,AutoProcessor,AutoModelForImageTextToText
torch.set_num_threads(THREADS)
def requested_vlm_device():
 device=os.environ.get("VN_VLM_DEVICE","cpu")
 if device not in ("cpu","cuda"):
  raise ValueError("VN_VLM_DEVICE must be cpu or cuda")
 if device=="cuda" and not torch.cuda.is_available():
  raise RuntimeError("VN_VLM_DEVICE=cuda requested but CUDA/ROCm is unavailable")
 return device
VLM_DEVICE=requested_vlm_device()
CLIP_ID="openai/clip-vit-base-patch32"
VLM_ID="HuggingFaceTB/SmolVLM2-500M-Video-Instruct"

LABELS=[
 ("outdoor_market_square","an outdoor medieval European open-air public market square with cobblestones, storefronts, market stalls and sky"),
 ("outdoor_street","an outdoor medieval city street with sky, stone pavement and shop fronts"),
 ("outdoor_forest","an outdoor forest landscape with trees and natural ground"),
 ("outdoor_courtyard","an outdoor courtyard surrounded by building facades, under the sky"),
 ("indoor_room","inside a furnished room or office with walls, a ceiling, windows and chairs"),
 ("indoor_tavern","inside a medieval tavern with tables, ceiling, candles and wooden walls"),
 ("underground_cave","inside an underground dark stone cave or dungeon")
]
QA_DEFAULT_PROFILE,QA_PROFILE_LABELS=load_profiles()
if dict(LABELS)!=QA_PROFILE_LABELS[QA_DEFAULT_PROFILE]:
 raise RuntimeError("QA default profile labels changed from baseline")
OUTDOOR={k for k,v in LABELS if k.startswith("outdoor_")}
INDOOR={k for k,v in LABELS if k.startswith("indoor_") or k=="underground_cave"}
COUNT_LABELS=[
 ("no_people","a scenic landscape with no people visible"),
 ("solo_portrait","a close up portrait photo of exactly one adult person"),
 ("solo_person","a photo with exactly one person alone, and no other person"),
 ("solo_woman","a photograph of one adult woman alone"),
 ("pair_people","a photo of exactly two adult people, both clearly visible"),
 ("pair_interaction","a photo showing two adult people interacting together"),
 ("pair_mixed","a photo showing an adult man and a woman together"),
 ("group_three","a photo of three adult people together"),
 ("group_many","a photo of a group of four or more adults")
]
print("VLM_DAEMON loading CLIP",flush=True)
clip_processor=CLIPProcessor.from_pretrained(CLIP_ID)
clip=CLIPModel.from_pretrained(CLIP_ID).eval()
with torch.inference_mode():
 text_inputs=clip_processor(text=[v for _,v in LABELS],return_tensors="pt",padding=True)
 text_feats=clip.get_text_features(**text_inputs)
 if hasattr(text_feats,"pooler_output"):text_feats=text_feats.pooler_output
 text_feats=torch.nn.functional.normalize(text_feats,dim=-1)
QA_TEXT_FEATURES={QA_DEFAULT_PROFILE:text_feats}
with torch.inference_mode():
 for profile,labels in QA_PROFILE_LABELS.items():
  if profile==QA_DEFAULT_PROFILE:continue
  values=clip_processor(text=[labels[name] for name,_ in LABELS],
                        return_tensors="pt",padding=True)
  features=clip.get_text_features(**values)
  if hasattr(features,"pooler_output"):features=features.pooler_output
  QA_TEXT_FEATURES[profile]=torch.nn.functional.normalize(features,dim=-1)
with torch.inference_mode():
 count_inputs=clip_processor(text=[v for _,v in COUNT_LABELS],
   return_tensors="pt",padding=True)
 count_feats=clip.get_text_features(**count_inputs)
 if hasattr(count_feats,"pooler_output"):count_feats=count_feats.pooler_output
 count_feats=torch.nn.functional.normalize(count_feats,dim=-1)
print("VLM_DAEMON loading SmolVLM",flush=True)
vlm_processor=AutoProcessor.from_pretrained(VLM_ID)
vlm=AutoModelForImageTextToText.from_pretrained(
 VLM_ID,dtype=torch.float32,attn_implementation="eager").eval()
if VLM_DEVICE=="cuda":
 vlm=vlm.to("cuda")
print("VLM_DAEMON ready port",PORT,flush=True)

def summarize(image,prompt,max_new_tokens=62):
 resized=image.copy();resized.thumbnail((560,560),Image.Resampling.LANCZOS)
 messages=[{"role":"user","content":[{"type":"image","image":resized},
       {"type":"text","text":prompt}]}]
 inputs=vlm_processor.apply_chat_template(messages,add_generation_prompt=True,
   tokenize=True,return_dict=True,return_tensors="pt")
 if VLM_DEVICE=="cuda":
  inputs=inputs.to("cuda")
 with torch.inference_mode():
  result=vlm.generate(**inputs,max_new_tokens=max_new_tokens,do_sample=False,repetition_penalty=1.15)
 suffix=result[:,inputs["input_ids"].shape[1]:]
 if VLM_DEVICE=="cuda":
  suffix=suffix.cpu()
 return vlm_processor.batch_decode(suffix,skip_special_tokens=True)[0].strip()[:420]

def image_embedding(image):
 # Compute one normalized image representation for all CLIP label banks.
 inputs=clip_processor(images=image,return_tensors="pt")
 with torch.inference_mode():
  emb=clip.get_image_features(**inputs)
  if hasattr(emb,"pooler_output"):emb=emb.pooler_output
  return torch.nn.functional.normalize(emb,dim=-1)

def score_environment(image,embedding=None,profile=None):
 emb=embedding if embedding is not None else image_embedding(image)
 with torch.inference_mode():
  bank=QA_TEXT_FEATURES.get(profile or QA_DEFAULT_PROFILE,
                             QA_TEXT_FEATURES[QA_DEFAULT_PROFILE])
  probs=torch.softmax((emb@bank.T)*30,dim=1).squeeze(0).tolist()
 return {name:round(float(p),4) for (name,_),p in zip(LABELS,probs)}

def score_principal_people(image,embedding=None):
 emb=embedding if embedding is not None else image_embedding(image)
 with torch.inference_mode():
  scores=torch.softmax((emb@count_feats.T)*30,dim=1).squeeze(0).tolist()
 return {name:round(float(p),4) for (name,_),p in zip(COUNT_LABELS,scores)}

def score_action_contrast(image,spec,embedding=None):
 labels=action_contrast_captions(spec)
 if not labels:return None
 emb=embedding if embedding is not None else image_embedding(image)
 txt=clip_processor(text=list(labels),return_tensors="pt",padding=True)
 with torch.inference_mode():
  t=clip.get_text_features(**txt)
  if hasattr(t,"pooler_output"):t=t.pooler_output
  t=torch.nn.functional.normalize(t,dim=-1)
  relative=torch.softmax((emb@t.T)*30,dim=1).squeeze(0).tolist()
 return round(float(relative[0]),4)

def analyze(kind,image,spec,quality,identity_ref=None,candidate_face=None):
 t0=time.monotonic()
 vlm_caption_ms=0.0
 def timed_caption(*args,**kwargs):
  nonlocal vlm_caption_ms
  caption_t0=time.monotonic()
  try:return summarize(*args,**kwargs)
  finally:vlm_caption_ms+=(time.monotonic()-caption_t0)*1000
 env=spec.get("environment") or {}
 expected=env.get("id","unclassified")
 probs={}
 reasons=[];warnings=[]
 image=image.convert("RGB")
 neural_story=kind=="scene" and spec.get("composition")=="neural_story"
 scene_count_verified=False;scene_location_verified=False
 scene_count_confidence=0.0;scene_location_confidence=0.0
 people_scores={}
 scene_action_contrast=None
 scene_action_verified=None
 scene_action_observation=""
 scene_action_evidence={}
 # Reuse one image encoding for all CLIP comparisons; no verdict changes.
 clip_embedding=image_embedding(image) if kind in ("background","scene") else None
 # Always use CLIP for environment; helps catch very obvious indoors/outdoors.
 if kind in ("background","scene"):
  probs=score_environment(image,clip_embedding,spec.get("qa_profile"))
  indoor=sum(probs[k] for k in INDOOR)
  outdoor=sum(probs[k] for k in OUTDOOR)
  # Confidence needs calibration against real generated examples. Use a strong margin.
  if expected in OUTDOOR and indoor>0.67:
   reasons.append(f"Expected {expected} outdoors; CLIP strongly detects indoor ({indoor:.2f})")
  elif expected in INDOOR and outdoor>0.80:
   reasons.append(f"Expected {expected} indoors; CLIP strongly detects outdoors ({outdoor:.2f})")
  if expected=="outdoor_market_square":
   if probs.get("indoor_room",0)>0.42:
    reasons.append("Market square resembles an interior furnished room")
   elif probs.get("outdoor_market_square",0)<.14:
    warnings.append("Market square details weak or ambiguous")
 if kind=="background" and expected in (OUTDOOR|INDOOR):
  # Consistent with scene QA: a strongly conflicting indoor/outdoor label
  # is a rejection, not a technically-passed background.
  _,bg_conflicts,_=scene_location_evidence(expected,probs)
  reasons.extend(bg_conflicts)
 if neural_story:
  expected_count=int(spec.get("visible_count") or len(spec.get("characters") or []))
  people_scores=score_principal_people(image,clip_embedding)
  scene_count_verified,count_reasons,scene_count_confidence=principal_count_evidence(
    expected_count,people_scores,
    ((spec.get("visual_contract") or {}).get("crowd") or {}).get("policy","none"))
  scene_location_verified,location_reasons,scene_location_confidence=scene_location_evidence(
    expected,probs)
  reasons.extend(count_reasons)
  reasons.extend(location_reasons)
  # This is advisory evidence against the common "static portrait" failure.
  # It is not an exact action/pose verifier and never blocks a valid category.
  scene_action_contrast=score_action_contrast(image,spec,clip_embedding)
  if scene_action_contrast is not None and scene_action_contrast<0.24:
   warnings.append("Action appears less aligned than a generic posed portrait")
 caption=""
 # Cascaded QA: the deterministic CG compositor cannot invent missing
 # characters, and a confident outdoor/indoor CLIP verdict does not need
 # a slow generative caption. Reserve VLM for uncertain backgrounds, new
 # identity anchors, major outfit revisions and cinematic-grade CG.
 indoor=sum(probs.get(k,0) for k in INDOOR)
 outdoor=sum(probs.get(k,0) for k in OUTDOOR)
 unclear_environment=expected not in (OUTDOOR|INDOOR) or (
   expected in OUTDOOR and outdoor<.78 and indoor<.67) or (
   expected in INDOOR and indoor<.78 and outdoor<.80)
 first_anchor=kind=="sprite" and not spec.get("anchor_asset")
 outfit_change=kind=="sprite" and spec.get("variant",{}).get("outfit","default")!="default"
 pose_change=kind=="sprite" and spec.get("variant",{}).get("pose","standing")!="standing"
 requires_bare=kind=="sprite" and outfit_requires_bare(spec.get("variant",{}).get("outfit",""))
 # A compound outfit can describe carried clothes, not worn garments.
 wants_unclothed=requires_bare
 trusted_composite=(kind=="scene" and spec.get("composition")=="anchored_composite"
   and int(spec.get("visible_count") or 0)>0
   and int(spec.get("ready_count") or -1)==int(spec.get("visible_count") or 0))
 wants_vlm=(wants_unclothed or quality=="cinematic" or
   (kind=="scene" and spec.get("composition")=="neural_story") or
   (kind=="background" and unclear_environment) or
   (kind=="scene" and unclear_environment and not trusted_composite) or
   (kind=="sprite" and (first_anchor or outfit_change or pose_change) and quality!="fast"))
 if wants_vlm:
  prompts={
   "background":"Describe the architecture and objects visible. Is this indoors or outdoors? Is any person visible? One factual sentence.",
   "sprite":"Count people visible; briefly describe their face, hair, clothing and visible background in a sentence.",
   "scene":"Count the people visible (one, two or more), describe their appearance and whether they stand indoors or outdoors. One factual sentence."
  }
  if kind=="scene" and spec.get("composition")=="neural_story":
   prompts["scene"]=(
     "Describe the actual image in TWO COMPLETE factual sentences, not a number. "
     "Describe the foreground adult people and their distinct body positions, "
     "visible clothes, physical objects and indoor/outdoor setting. "
     "If identical people appear twice in different places, mention both. "
     "Do not invent anything not visible.")
  if wants_unclothed:
   prompts["sprite"]=("Describe factually whether the clearly adult person wears any garments "
     "or accessories. Name visible items of clothing, or say 'no clothes visible' if none. "
     "Avoid assumptions. Answer in one brief sentence.")
  caption=timed_caption(image,prompts.get(kind,prompts["background"]))
  if neural_story and insufficient_scene_caption(caption):
   # SmolVLM2 occasionally returned only "Two.". Re-prompt with
   # descriptive captioning instead of a pure counting question.
   alt=timed_caption(image,
     "Start with 'The image shows'. Describe the entire picture in two "
     "full English sentences including foreground subjects, their positions, "
     "physical objects and background. Do not answer with a count alone.")
   if not insufficient_scene_caption(alt):caption=alt
  # The generic scene caption is not proof of requested physical contact.
  # Ask a separate observation question and require affirmative evidence.
  if neural_story and wall_brace_required(spec):
   action_prompt=(
     "Describe ONLY the visible physical pose in factual sentences: "
     "where are BOTH of the person's hands, what exact surface do they touch, "
     "what supports the knees or feet, and does the torso lean forward "
     "toward a vertical wall? If any part is not visible or unclear, say so. "
     "Do not infer the story or imagine hidden surfaces."
   )
   # Generic captions often describe only the location and therefore
   # cannot confirm the mandatory action. Use them when affirmative; only
   # ask a targeted follow-up when the first observation is inconclusive.
   # This avoids an extra CPU VLM pass for already-readable contact.
   generic_verified=check_wall_action(caption,spec)[0] is True
   scene_action_observation=(caption if generic_verified else
                             timed_caption(image,action_prompt,max_new_tokens=92))
   scene_action_verified,pose_reasons,scene_action_evidence=check_wall_action(
       scene_action_observation,spec)
   if scene_action_evidence.get("ground_pose") is True:
    reasons.extend(pose_reasons)
   elif pose_reasons:
    warnings.extend(pose_reasons)
  desc=caption.lower()
  if expected in OUTDOOR and re.search(r"\b(?:inside|indoors|bedroom|interior room|living room|office|hallway)\b",desc):
   warnings.append("VLM describes an interior while an outdoor location is requested")
   if kind=="background" and expected=="outdoor_market_square":
    reasons.append("VLM sees an interior instead of an outdoor market square")
  if kind=="scene":
   if neural_story:
    reasons.extend(scene_caption_conflicts(spec.get("characters") or [],caption))
    reasons.extend(scene_action_conflicts(spec.get("characters") or [],caption,spec.get("prompt","")))
   expected_count=int(spec.get("visible_count") or len(spec.get("characters") or []))
   # Never infer a SOLO image from mentions of "a man"/"a woman":
   # captions frequently describe a man WITH a woman. Strong count
   # contradictions only; independent CLIP count remains mandatory.
   if expected_count>=2 and caption_asserts_single_person(desc):
    reasons.append(f"CG missing characters: expected {expected_count}, VLM explicitly identified only one")
   if expected_count==1 and re.search(r"\b(?:no people|nobody|no one)\b",desc):
    reasons.append("CG missing expected character")
  if kind=="sprite":
   if re.search(r"\b(?:two people|multiple people|three people|two men|two women)\b",desc):
    reasons.append("Sprite shows several people")
   if re.search(r"\b(?:no people|nobody)\b",desc):
    reasons.append("Sprite has no visible character")
   outfit=str(spec.get("variant",{}).get("outfit","")).lower()
   if wants_unclothed:
    # Only an explicit contradictory clothing description blocks publication.
    # An uncertain caption must not masquerade as positive proof or failure.
    verdict=clothing_alignment(desc)
    if verdict=="failed":
     reasons.append("Required wardrobe state not met: VLM detects clothing on the character")
   # Strong wardrobe constraints are handled as warnings when VLM is unsure.
   expected_color=requested_outerwear_color(outfit)
   if expected_color and not wants_unclothed:
    same_color=expected_color in desc or (expected_color in ("grey","gray") and ("gray" in desc or "grey" in desc))
    observed=re.search(r"\b(black|white|green|red|blue|brown|purple|yellow|gray|grey)\s+"
       r"(?:\w+\s+){0,2}(?:cloak|coat|robe|jacket|dress|shirt)\b",desc)
    if observed and not same_color:
     if any(x in outfit for x in ("cloak","coat","robe","dress","shirt")):
      reasons.append(f"Wardrobe color incorrect: requested {expected_color}, image shows {observed.group(1)}")
     else:warnings.append(f"Possible wardrobe color mismatch: {expected_color} vs {observed.group(1)}")
    elif not same_color:
     warnings.append(f"QA could not verify wardrobe color {expected_color}")
 similarity=None
 face_visibility=face_observability(spec) if kind=="sprite" else {}
 if kind=="sprite" and face_visibility.get("verdict")=="unobservable":
  warnings.append("Facial identity is not observable from the requested rear/occluded pose")
 if kind=="sprite" and identity_ref is not None and candidate_face is not None:
  pair=clip_processor(images=[identity_ref.convert("RGB"),candidate_face.convert("RGB")],return_tensors="pt")
  with torch.inference_mode():
   embed=clip.get_image_features(**pair)
   if hasattr(embed,"pooler_output"):embed=embed.pooler_output
   embed=torch.nn.functional.normalize(embed,dim=-1)
   similarity=round(float((embed[0]*embed[1]).sum()),4)
  # In the observed regression 0.77 was passed with only a warning,
  # despite a visibly different face. Do not publish such a variant.
  decision=face_similarity_decision(spec,similarity,caption)
  if decision["verdict"]=="violated":
   reasons.append(f"Character identity differs from canonical anchor (CLIP face similarity {similarity:.2f}, required 0.80)")
  elif decision["reason"]=="face_similarity_borderline":
   warnings.append(f"Character resemblance is borderline (similarity {similarity:.2f})")
 scores={k:round(float(v),3) for k,v in probs.items()}
 return {"status":"failed" if reasons else "passed","reasons":reasons[:8],
   "warnings":warnings[:8],"caption":caption,
   "class_scores":scores,"environment":max(scores,key=scores.get) if scores else "not_checked",
   "identity_similarity":similarity,
   "identity_face_visibility":(face_similarity_decision(spec,similarity,caption)["verdict"]
       if kind=="sprite" else "not_checked"),
   "identity_decision_reason":(face_similarity_decision(spec,similarity,caption)["reason"]
       if kind=="sprite" else "not_checked"),
   "scene_count_verified":scene_count_verified,
   "scene_location_verified":scene_location_verified,
   "scene_count_confidence":scene_count_confidence,
   "scene_location_confidence":scene_location_confidence,
   "scene_solo_score":round(sum(people_scores.get(k,0) for k in (
     "solo_portrait","solo_person","solo_woman")),4),
   "scene_pair_score":round(sum(people_scores.get(k,0) for k in (
     "pair_people","pair_interaction","pair_mixed")),4),
   "scene_action_contrast":scene_action_contrast,
   "scene_action_verified":scene_action_verified,
   "scene_action_observation":scene_action_observation[:420],
   "scene_action_evidence":scene_action_evidence,
   "duration_seconds":round(time.monotonic()-t0,2),
   "vlm_caption_ms":round(max(0,vlm_caption_ms),3)}

def timed_analyze(kind,image,spec,quality,reference,candidate):
 """Paired monotonic spans; CPU model analysis never hides lock contention."""
 lock_requested=time.monotonic()
 with lock:
  lock_acquired=time.monotonic()
  result=analyze(kind,image,spec,quality,reference,candidate)
  analyzed_at=time.monotonic()
 if not isinstance(result,dict):
  raise TypeError("Vision analyzer response must be a mapping")
 result["qa_stage_ms"]={
  "lock_wait":round(max(0,(lock_acquired-lock_requested)*1000),3),
  "model_analyze":round(max(0,(analyzed_at-lock_acquired)*1000),3)}
 return result


class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):return
 def do_GET(self):
  if self.path!="/healthz":
   self.send_error(404);return
  self.response(200,{"ok":True,"model":VLM_ID,"clip":CLIP_ID,
   "vlm_device":str(vlm.device),"vlm_dtype":str(vlm.dtype),"clip_device":str(clip.device)})
 def do_POST(self):
  if self.path!="/judge":
   self.send_error(404);return
  try:
   handler_t0=time.monotonic()
   n=int(self.headers.get("Content-Length","0"))
   if n<1 or n>14*1024*1024:raise ValueError("Invalid request size")
   data=json.loads(self.rfile.read(n))
   raw=base64.b64decode(data["image_b64"],validate=True)
   img=Image.open(io.BytesIO(raw)).convert("RGB")
   reference=None;candidate=None
   if data.get("identity_b64") and data.get("candidate_face_b64"):
    reference=Image.open(io.BytesIO(base64.b64decode(data["identity_b64"],validate=True))).convert("RGB")
    candidate=Image.open(io.BytesIO(base64.b64decode(data["candidate_face_b64"],validate=True))).convert("RGB")
   decoded_at=time.monotonic()
   response=timed_analyze(data.get("kind","background"),img,data.get("spec") or {},
                          data.get("quality","standard"),reference,candidate)
   response["qa_stage_ms"]["input_decode"]=round(
       max(0,(decoded_at-handler_t0)*1000),3)
   response["qa_stage_ms"]["handler_before_send"]=round(
       max(0,(time.monotonic()-handler_t0)*1000),3)
   self.response(200,response)
  except Exception as error:
   self.response(200,{"status":"unavailable","reason":str(error)[:240]})
 def response(self,status,payload):
  encoded=json.dumps(payload,ensure_ascii=False).encode()
  self.send_response(status)
  self.send_header("Content-Type","application/json; charset=utf-8")
  self.send_header("Content-Length",str(len(encoded)))
  self.send_header("Cache-Control","no-store")
  self.end_headers();self.wfile.write(encoded)

if __name__=="__main__":
 server=ThreadingHTTPServer((HOST,PORT),Handler)
 server.daemon_threads=True
 server.serve_forever()
