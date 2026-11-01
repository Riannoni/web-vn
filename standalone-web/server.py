#!/usr/bin/env python3
"""Private LAN playground for installed ComfyUI text-to-image models."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import shlex
import urllib.error
import queue
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import vn_web
from pack_preview import PackPreview, PreviewError

HOST, PORT = "192.168.50.27", 8190
COMFY = "http://127.0.0.1:8188"
ROOT = Path.home() / ".local/share/mcp-vn-model-lab"
OUTPUT = ROOT / "outputs"
WEB = ROOT / "web"
CONFIG = Path.home() / ".config/mcp-vn-model-lab/credentials.json"
MODELDIR = Path.home() / ".local/share/mcp-vn-comfy/models"
LAN = ipaddress.ip_network("192.168.50.0/24")
LLM_IDS = ("cydonia:24b-v4.3-iq4_xs",)
ROUTER = "http://192.168.50.27:11434"
ROUTER_ENV = Path.home() / ".config/mcp-vn/worker.env"
MODELS = {
 "pony": ("CyberRealistic Pony v18 · Реализм / 2.5D", "SDXL · realistic / semireal", ["checkpoints/CyberRealisticPony_V18.0_F16.safetensors"], True),
 "wai": ("WAI-Illustrious SDXL v17 · Аниме", "SDXL · Japanese anime", ["checkpoints/waiIllustriousSDXL_v170.safetensors"], True),
 "anima": ("Anima BAS:NSFW v1.0 · Анимационная", "Anima · 2D animation", ["diffusion_models/BASNSFWBetterAnimeStyleForNSFWHentai_baseV10.safetensors","text_encoders/qwen_3_06b_base.safetensors","vae/qwen_image_vae.safetensors"], False),
 "cyberz": ("CyberRealistic Z-Image v4 Q8 · Эксперимент", "Z-Image · experimental", ["diffusion_models/CyberRealistic_zit_v4.0-Q8_0.gguf","text_encoders/qwen_3_4b_fp4_mixed.safetensors","vae/ae.safetensors"], False),
}
SIZES = {(1024,768),(768,1024),(1024,1024),(768,768),(896,512),(1216,704)}
def scan_models():
    """Return available models by scanning checkpoints dir."""
    known_files = {v[2][0].split("/")[-1]: k for k,v in MODELS.items()}
    ckpt_dir = MODELDIR / "checkpoints"
    result = dict(MODELS)
    if ckpt_dir.exists():
        for f in ckpt_dir.glob("*.safetensors"):
            if f.name in known_files:
                continue  # already in MODELS with proper label
            key = f.stem.lower().replace("_","").replace("-","")[:20]
            if key not in result:
                result[key] = (f.stem, f"SDXL · {f.stem}", [f"checkpoints/{f.name}"], True)
    return result
def load(path, default=None):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default
def write_json(path, obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix=".lab-",dir=path.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump(obj,f,ensure_ascii=False)
  os.chmod(tmp,0o600);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def setup(reset=False):
 CONFIG.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 if CONFIG.exists() and not reset:
  print("Already initialized. Use --reset-password.");return
 pwd=secrets.token_urlsafe(18)
 salt=secrets.token_bytes(16)
 write_json(CONFIG,{"salt":salt.hex(),"digest":hashlib.pbkdf2_hmac("sha256",pwd.encode(),salt,270000).hex(),
                    "session_secret":secrets.token_hex(32)})
 print("MODEL_LAB_USER=lab\nMODEL_LAB_PASSWORD="+pwd)
def verify_password(pwd):
 c=load(CONFIG)
 if not c:return False
 return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256",pwd.encode(),bytes.fromhex(c["salt"]),270000).hex(),c["digest"])
def new_cookie():
 expiry=str(int(time.time()+2592000))
 sig=hmac.new(bytes.fromhex(load(CONFIG)["session_secret"]),expiry.encode(),"sha256").hexdigest()
 return "vn_lab="+expiry+"."+sig+"; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict"
def authed(raw):
 try:
  cookies=SimpleCookie();cookies.load(raw or "")
  expiry,sig=cookies["vn_lab"].value.split(".",1)
  if int(expiry)<time.time():return False
  target=hmac.new(bytes.fromhex(load(CONFIG)["session_secret"]),expiry.encode(),"sha256").hexdigest()
  return hmac.compare_digest(sig,target)
 except (KeyError,ValueError,TypeError):return False
def node(kind,**kwargs):return {"class_type":kind,"inputs":kwargs}
def graph(model,prompt,negative,w,h,seed,ident):
 """Dedicated graph for each model family, no cross-architecture checkpoint swaps."""
 positive=prompt
 if model=="pony":positive="score_9, score_8_up, score_7_up, "+prompt
 if model=="wai":positive="masterpiece, best quality, amazing quality, "+prompt
 sdxl={
  "pony":("CyberRealisticPony_V18.0_F16.safetensors",32,5,True),
  "wai":("waiIllustriousSDXL_v170.safetensors",24,6,True)}
 if model in sdxl:
  ckpt,steps,cfg,skip=sdxl[model]
  clip=["8",0] if skip else ["1",1]
  g={"1":node("CheckpointLoaderSimple",ckpt_name=ckpt),
     "2":node("EmptyLatentImage",width=w,height=h,batch_size=1),
     "3":node("CLIPTextEncode",clip=clip,text=positive),
     "4":node("CLIPTextEncode",clip=clip,text=negative),
     "5":node("KSampler",model=["1",0],positive=["3",0],negative=["4",0],
              latent_image=["2",0],seed=seed,steps=steps,cfg=cfg,
              sampler_name=("euler_ancestral" if model=="wai" else "dpmpp_2m"),
              scheduler=("normal" if model=="wai" else "karras"),denoise=1),
     "6":node("VAEDecode",samples=["5",0],vae=["1",2])}
  if skip:g["8"]=node("CLIPSetLastLayer",clip=["1",1],stop_at_clip_layer=-2)
  source=["6",0]
 elif model=="anima":
  g={"1":node("UNETLoader",unet_name="BASNSFWBetterAnimeStyleForNSFWHentai_baseV10.safetensors",weight_dtype="default"),
     "2":node("CLIPLoader",clip_name="qwen_3_06b_base.safetensors",type="stable_diffusion",device="default"),
     "3":node("VAELoader",vae_name="qwen_image_vae.safetensors"),
     "4":node("EmptyLatentImage",width=w,height=h,batch_size=1),
     "5":node("CLIPTextEncode",clip=["2",0],text=positive),
     "6":node("CLIPTextEncode",clip=["2",0],text=negative),
     "7":node("KSampler",model=["1",0],positive=["5",0],negative=["6",0],
              latent_image=["4",0],seed=seed,steps=8,cfg=1,
              sampler_name="euler",scheduler="sgm_uniform",denoise=1),
     "8":node("VAEDecode",samples=["7",0],vae=["3",0])}
  source=["8",0]
 elif model=="cyberz":
  checkpoint="CyberRealistic_zit_v4.0-Q8_0.gguf"
  g={"1":node("UnetLoaderGGUF",unet_name=checkpoint),
     "2":node("CLIPLoader",clip_name="qwen_3_4b_fp4_mixed.safetensors",type="lumina2",device="default"),
     "3":node("VAELoader",vae_name="ae.safetensors"),
     "4":node("EmptySD3LatentImage",width=w,height=h,batch_size=1),
     "5":node("CLIPTextEncode",clip=["2",0],text=positive),
     "6":node("ConditioningZeroOut",conditioning=["5",0]),
     "7":node("ModelSamplingAuraFlow",model=["1",0],shift=3),
     "8":node("KSampler",model=["7",0],positive=["5",0],negative=["6",0],
              latent_image=["4",0],seed=seed,steps=8,cfg=1,
              sampler_name="res_multistep",scheduler="simple",denoise=1),
     "9":node("VAEDecode",samples=["8",0],vae=["3",0])}
  source=["9",0]
 else:raise ValueError("Unknown model")
 g["98"]=node("SaveImage",images=source,filename_prefix="vn_model_lab_"+ident)
 return g
def summarize_comfy_failure(status):
 """Short actionable error instead of a truncated Python traceback in the gallery."""
 for event,details in status.get("messages",[]):
  if event!="execution_error":continue
  kind=str(details.get("exception_type") or "unknown error")
  msg=str(details.get("exception_message") or "")
  node_type=str(details.get("node_type") or details.get("node_id") or "unknown")
  if "out of memory" in msg.lower():
   return ("Недостаточно видеопамяти в ComfyUI ("+node_type+"). "+
           "Попробуй 768×768 и дождись завершения других GPU-задач. "+
           "Если повторяется — перезапусти ComfyUI или обратись к диагностике.")
  return "ComfyUI ("+node_type+", "+kind+"): "+(msg[:300] or "ошибка выполнения")
 return "ComfyUI не смог завершить генерацию; смотри журнал ComfyUI."

def comfy(path,data=None,timeout=18):
 b=json.dumps(data).encode() if data is not None else None
 r=urllib.request.Request(COMFY+path,data=b,headers={"Content-Type":"application/json"},
                          method="POST" if b is not None else "GET")
 with urllib.request.urlopen(r,timeout=timeout) as res:return json.loads(res.read(2_000_000))
def router_token():
 """Read the local user service token without exposing it to clients or logs."""
 values={}
 for line in ROUTER_ENV.read_text().splitlines():
  if not line.strip() or line.strip().startswith("#") or "=" not in line:continue
  key,value=line.split("=",1)
  key=key.strip()
  if key.startswith("export "):key=key[7:]
  if key not in ("VN_LOCAL_ROUTER_TOKEN","VN_WORKER_TOKEN"):continue
  parsed=shlex.split(value,comments=False)
  if parsed:values[key]=parsed[0]
 token=values.get("VN_LOCAL_ROUTER_TOKEN") or values.get("VN_WORKER_TOKEN")
 if not token:raise RuntimeError("Private local gateway token is not configured")
 return token

def local_llm_gateway(path,data=None,timeout=8):
 body=None if data is None else json.dumps(data,ensure_ascii=False).encode()
 req=urllib.request.Request(ROUTER+path,data=body,
  headers={"Authorization":"Bearer "+router_token(),"Content-Type":"application/json"},
  method="POST" if body is not None else "GET")
 try:
  with urllib.request.urlopen(req,timeout=timeout) as response:
   return json.load(response)
 except urllib.error.HTTPError as err:
  try:
   details=json.loads(err.read(4096).decode())
   problem=str(details.get("error") or err.reason)
  except Exception:problem=str(err.reason)
  raise RuntimeError("Локальная LLM: "+problem[:180]) from None

def generate_llm_test(data,art_busy=None):
 model=data.get("model")
 if model not in LLM_IDS:raise ValueError("Неизвестная языковая модель")
 messages=data.get("messages")
 if not isinstance(messages,list) or not 1<=len(messages)<=12:
  raise ValueError("Разрешено 1–12 сообщений контекста")
 clean=[]
 for msg in messages:
  if not isinstance(msg,dict) or msg.get("role") not in ("user","assistant","system"):
   raise ValueError("Некорректная роль сообщения")
  value=msg.get("content")
  if not isinstance(value,str) or not 1<=len(value.strip())<=2500:
   raise ValueError("Сообщение должно содержать 1–2500 символов")
  clean.append({"role":msg["role"],"content":value.strip()})
 if clean[-1]["role"]!="user":raise ValueError("Последнее сообщение должно быть от пользователя")
 if art_busy is not None and art_busy:
  raise RuntimeError("Генерация изображения ещё выполняется — дождитесь её завершения")
 job_queue=comfy("/queue",timeout=6)
 if job_queue.get("queue_running") or job_queue.get("queue_pending"):
  raise RuntimeError("В ComfyUI есть активная GPU-задача")
 return local_llm_gateway("/api/chat",
  {"model":model,"messages":clean,
   "options":{"num_predict":min(512,max(64,int(data.get("max_tokens",240)))),
              "temperature":min(1.4,max(0.1,float(data.get("temperature",0.8))))}},
  timeout=270)

class Store:
 def __init__(self):
  ROOT.mkdir(parents=True,exist_ok=True);OUTPUT.mkdir(parents=True,exist_ok=True,mode=0o700)
  self.path=ROOT/"jobs.json";self.lock=threading.RLock();self.jobs=load(self.path,[]) or []
  for j in self.jobs:
   if j["status"] in ("queued","working"):
    j.update(status="interrupted",error="Сервис перезапустился; повторите генерацию.")
  self.save();self.q=queue.Queue(maxsize=30)
  threading.Thread(target=self.worker,daemon=True,name="lab-job-worker").start()
 def save(self):write_json(self.path,self.jobs[-250:])
 def get(self,ident):
  with self.lock:
   j=next((j for j in self.jobs if j["id"]==ident),None)
   return dict(j) if j else None
 def list(self):
  with self.lock:return [dict(j) for j in reversed(self.jobs[-150:])]
 def update(self,ident,**values):
  with self.lock:
   j=next((j for j in self.jobs if j["id"]==ident),None)
   if j:j.update(values,updated=time.time());self.save()
 def submit(self,models,prompt,negative,w,h,seed):
  if self.q.qsize()+len(models)>20:raise ValueError("Очередь заполнена.")
  for m in models:
   if any(not (MODELDIR/f).exists() for f in MODELS[m][2]):
    raise ValueError("Файлы модели отсутствуют: "+MODELS[m][0])
  group=secrets.token_hex(8) if len(models)>1 else ""
  ids=[]
  with self.lock:
   for m in models:
    ident=secrets.token_hex(16);ids.append(ident)
    self.jobs.append(dict(id=ident,model=m,model_name=MODELS[m][0],group=group,prompt=prompt,negative=negative,
                          width=w,height=h,seed=seed,status="queued",stage="В очереди",
                          created=time.time(),updated=time.time(),duration=None,
                          error="",file="",comfy_id=""))
   self.save()
  for ident in ids:self.q.put(ident)
  return ids
 def cancel(self,ident):
  with self.lock:
   j=self.get(ident)
   if not j or j["status"]!="queued":return False
   self.update(ident,status="canceled",stage="Отменено");return True
 def delete(self,ident):
  with self.lock:
   j=self.get(ident)
   if not j or j["status"] in ("queued","working"):return False
   self.jobs=[x for x in self.jobs if x["id"]!=ident];self.save()
   (OUTPUT/(ident+".png")).unlink(missing_ok=True);return True
 def worker(self):
  while True:
   ident=self.q.get()
   try:
    j=self.get(ident)
    if not j or j["status"]!="queued":continue
    self.update(ident,status="working",stage="Подготовка")
    t=time.monotonic()
    g=graph(j["model"],j["prompt"],j["negative"],j["width"],j["height"],j["seed"],ident)
    result=comfy("/prompt",{"prompt":g,"client_id":"vn-model-lab"},30)
    pid=result.get("prompt_id")
    if not pid:raise RuntimeError("ComfyUI отклонил задачу: "+str(result)[:220])
    self.update(ident,stage="Генерация на GPU",comfy_id=pid)
    while time.monotonic()-t<600:
     time.sleep(1.5)
     history=comfy("/history/"+pid,timeout=15)
     if pid not in history:continue
     report=history[pid]
     if report.get("status",{}).get("status_str")!="success":
      raise RuntimeError(summarize_comfy_failure(report.get("status",{})))
     images=report.get("outputs",{}).get("98",{}).get("images",[])
     if not images:raise RuntimeError("ComfyUI не вернул PNG")
     metadata=images[0];name=str(metadata.get("filename",""))
     if not name.startswith("vn_model_lab_"+ident+"_") or not name.endswith(".png") or "/" in name or "\\" in name:
      raise RuntimeError("Некорректный файл ComfyUI")
     params=urllib.parse.urlencode({"filename":name,"type":"output","subfolder":metadata.get("subfolder","")})
     with urllib.request.urlopen(COMFY+"/view?"+params,timeout=30) as resp:image=resp.read(24_000_001)
     if len(image)>24_000_000 or not image.startswith(b"\x89PNG\r\n\x1a\n"):
      raise RuntimeError("Слишком большой или некорректный PNG")
     with open(OUTPUT/(ident+".png"),"wb") as f:
      os.chmod(OUTPUT/(ident+".png"),0o600);f.write(image)
     self.update(ident,status="done",stage="Готово",file=ident+".png",
                 duration=round(time.monotonic()-t,1))
     break
    else:raise TimeoutError("Лимит времени генерации: 10 минут")
   except Exception as exc:
    self.update(ident,status="error",stage="Ошибка",error=str(exc)[:450])
    print("GENERATION_ERROR",ident,type(exc).__name__,str(exc)[:120],flush=True)
   finally:self.q.task_done()
STORE=None
MIRA_PREVIEW=PackPreview()
FAILED={}
FAIL_LOCK=threading.Lock()
class Handler(BaseHTTPRequestHandler):
 server_version="ModelLab/1";sys_version=""
 def log_message(self,fmt,*args):pass
 def headers_secure(self):
  for k,v in {"Cache-Control":"no-store","X-Frame-Options":"DENY",
    "X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer",
    "Content-Security-Policy":"default-src 'self'; connect-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; media-src 'self'"}.items():self.send_header(k,v)
 def send_data(self,status,data,mime,extras=()):
  self.send_response(status);self.headers_secure()
  self.send_header("Content-Type",mime);self.send_header("Content-Length",str(len(data)))
  for k,v in extras:self.send_header(k,v)
  self.end_headers()
  try:self.wfile.write(data)
  except (BrokenPipeError,ConnectionResetError):pass
 def send_json(self,status,data,extras=()):
  self.send_data(status,json.dumps(data,ensure_ascii=False).encode(),"application/json; charset=utf-8",extras)
 def allowed(self):
  try:
   addr=ipaddress.ip_address(self.client_address[0])
   return addr.is_loopback or addr in LAN
  except ValueError:return False
 def authorized(self):return authed(self.headers.get("Cookie"))
 def body(self):
  try:n=int(self.headers.get("Content-Length","0"))
  except ValueError:raise ValueError("Invalid Content-Length")
  if n<1 or n>25000:raise ValueError("Некорректный размер запроса")
  x=json.loads(self.rfile.read(n))
  if not isinstance(x,dict):raise ValueError("JSON-объект обязателен")
  return x
 def do_GET(self):
  if not self.allowed():return self.send_json(403,{"error":"LAN only"})
  path=urllib.parse.urlsplit(self.path).path
  if path=="/api/session":return self.send_json(200,{"authenticated":self.authorized()})
  if path in {"/vn","/vn/","/vn/index.html","/vn/app.js","/vn/commands.js","/vn/style.css"}:
   name=path.rsplit("/",1)[-1] or "index.html"
   mime="text/html" if name.endswith("html") else "text/css" if name.endswith("css") else "text/javascript"
   f=WEB/"vn"/name
   return self.send_data(200,f.read_bytes(),mime+"; charset=utf-8") if f.is_file() else self.send_json(404,{"error":"Not found"})
  if path in {"/","/index.html","/app.js","/style.css"}:
   name=path.lstrip("/") or "index.html"
   mime=("text/html" if name.endswith("html") else "text/css" if name.endswith("css") else "text/javascript")
   f=WEB/name
   if not f.exists():return self.send_json(404,{"error":"No static file"})
   return self.send_data(200,f.read_bytes(),mime+"; charset=utf-8")
  if not self.authorized():return self.send_json(401,{"error":"Авторизуйтесь"})
  if path=="/api/mira-pack":
   try:return self.send_json(200,{"assets":[{"id":id_,"review":"PROVISIONAL / NOT REVIEWED"} for id_ in MIRA_PREVIEW.visible_ids()]})
   except PreviewError as exc:return self.send_json(exc.status,{"error":"Private pack view unavailable"})
  if path.startswith("/api/mira-pack/"):
   try:return self.send_data(200,MIRA_PREVIEW.image_bytes(path.removeprefix("/api/mira-pack/")),"image/png")
   except PreviewError as exc:return self.send_json(exc.status,{"error":"Private pack view unavailable"})
  if path.startswith("/api/vn/"):
   try:
    if path.startswith("/api/vn/assets/"):
     asset_name=path.removeprefix("/api/vn/assets/")
     payload,mime=vn_web.asset_bytes(asset_name)
     return self.send_data(200,payload,mime)
    if path=="/api/vn/visual-jobs":
     game_id=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id",[""])[0]
     return self.send_json(200,vn_web.visual_jobs(game_id))
    if path in ("/api/vn/memory","/api/vn/performance"):
     game_id=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id",[""])[0]
     response=(vn_web.game_memory(game_id) if path.endswith("/memory") else
       vn_web.game_performance(game_id))
     return self.send_json(200,response)
    if path=="/api/vn/games":return self.send_json(200,vn_web.games())
    if path=="/api/vn/game":
     game_id=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id",[""])[0]
     return self.send_json(200,vn_web.game(game_id))
    if path=="/api/vn/local-status":
     game_id=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id",[""])[0]
     return self.send_json(200,vn_web.local_status(game_id))
    if path=="/api/vn/models":return self.send_json(200,vn_web.models())
    if path=="/api/vn/oauth/status":return self.send_json(200,vn_web.login_status())
    return self.send_json(404,{"error":"Unknown VN route"})
   except vn_web.VNError as e:return self.send_json(e.status,{"error":str(e)})
  if path=="/api/models":
   return self.send_json(200,{"models":[dict(id=k,name=v[0],family=v[1],negative=v[3],
     ready=all((MODELDIR/f).exists() for f in v[2])) for k,v in scan_models().items()]})
  if path=="/api/jobs":return self.send_json(200,{"jobs":STORE.list()})
  if path=="/api/llm-models":
   try:
    data=local_llm_gateway("/api/tags",timeout=5)
    details={x.get("name",""):x for x in data.get("models",[])}
   except Exception:details={}
   models=[]
   for name,info in details.items():
    if "qwen" in name.lower(): continue
    models.append({"id":name,"name":name,"ready":True,
      "backend":info.get("backend","unknown")})
   return self.send_json(200,{"models":models})
  if path=="/api/health":
   try:
    q=comfy("/queue",timeout=4)
    return self.send_json(200,{"online":True,"running":len(q.get("queue_running",[])),
      "queued":len(q.get("queue_pending",[]))})
   except Exception:return self.send_json(200,{"online":False,"running":0,"queued":0})
  if path.startswith("/api/image/") or path.startswith("/api/download/"):
   ident=path.rsplit("/",1)[-1];j=STORE.get(ident)
   if not j or j["status"]!="done":return self.send_json(404,{"error":"Изображение не найдено"})
   f=OUTPUT/(ident+".png")
   if not f.is_file():return self.send_json(404,{"error":"PNG отсутствует"})
   download=path.startswith("/api/download/")
   headers=[("Content-Disposition","attachment; filename=lab-"+j["model"]+"-"+ident[:8]+".png")] if download else []
   return self.send_data(200,f.read_bytes(),"image/png",headers)
  return self.send_json(404,{"error":"Не найдено"})
 def do_POST(self):
  if not self.allowed():return self.send_json(403,{"error":"LAN only"})
  origin=self.headers.get("Origin")
  if origin and origin not in (f"http://{HOST}:{PORT}",f"http://127.0.0.1:{PORT}"):
   return self.send_json(403,{"error":"Origin denied"})
  path=urllib.parse.urlsplit(self.path).path
  try:
   x=self.body()
   if path=="/api/login":
    address=self.client_address[0]
    with FAIL_LOCK:
     f=FAILED.get(address,{"fail":0,"blocked":0})
     if f["blocked"]>time.time():return self.send_json(429,{"error":"Слишком много попыток"})
    if x.get("username")!="lab" or not verify_password(str(x.get("password",""))):
     with FAIL_LOCK:
      f["fail"]+=1
      if f["fail"]>=6:f={"fail":0,"blocked":time.time()+120}
      FAILED[address]=f
     return self.send_json(401,{"error":"Неверный пароль"})
    with FAIL_LOCK:FAILED.pop(address,None)
    return self.send_json(200,{"ok":True},[("Set-Cookie",new_cookie())])
   if not self.authorized():return self.send_json(401,{"error":"Авторизуйтесь"})
   if path=="/api/logout":
    return self.send_json(200,{"ok":True},[("Set-Cookie","vn_lab=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")])
   if path.startswith("/api/vn/"):
    try:
     if path=="/api/vn/command":
      return self.send_json(200,vn_web.command(
       str(x.get("game_id","")),str(x.get("model","")),x.get("action"),
       x.get("expected_version"),str(x.get("reasoning_effort","auto")),
       x.get("confirmed") is True,x.get("auto_visual") is not False))
     if path=="/api/vn/turn":
      return self.send_json(200,vn_web.turn(
       str(x.get("game_id","")),str(x.get("model","")),x.get("action"),
       x.get("expected_version"),str(x.get("reasoning_effort","auto")),
       x.get("auto_visual") is not False))
     if path=="/api/vn/local-turn":
      return self.send_json(202,vn_web.local_turn(
       str(x.get("game_id","")),str(x.get("model","")),
       x.get("action"),x.get("expected_version")))
     if path=="/api/vn/resume":
      return self.send_json(200,vn_web.turn(
       str(x.get("game_id","")),str(x.get("model","")),
       reasoning_effort=str(x.get("reasoning_effort","auto")),
       auto_visual=x.get("auto_visual") is not False))
     if path=="/api/vn/visual-refresh":
      return self.send_json(200,vn_web.visual_refresh(
       str(x.get("game_id","")),x.get("retry") is True))
     if path=="/api/vn/visual-cg-regenerate":
      return self.send_json(202,vn_web.regenerate_cg(
       str(x.get("game_id","")),x.get("expected_version")))
     if path=="/api/vn/visual-cg":
      return self.send_json(202,vn_web.manual_cg(
       str(x.get("game_id","")),x.get("expected_version")))
     if path=="/api/vn/undo":
      return self.send_json(200,vn_web.game_undo(
       str(x.get("game_id","")),x.get("expected_version")))
     if path=="/api/vn/local-exit":
      return self.send_json(200,vn_web.local_exit(
       str(x.get("game_id","")),x.get("expected_version")))
     if path=="/api/vn/oauth/start":
      return self.send_json(202,vn_web.start_login(str(x.get("provider",""))))
     if path=="/api/vn/oauth/cancel":
      return self.send_json(200,vn_web.cancel_login())
     return self.send_json(404,{"error":"Unknown VN route"})
    except vn_web.VNError as e:return self.send_json(e.status,{"error":str(e)})
   if path=="/api/llm-chat":
    try:
     active=any(j["status"] in ("working","queued") for j in STORE.list())
     result=generate_llm_test(x,art_busy=active)
     return self.send_json(200,{"model":result.get("model"),
      "backend":result.get("backend","unknown"),
      "text":result.get("message",{}).get("content",""),
      "load_seconds":round(result.get("load_duration",0)/1e9,2),
      "total_seconds":round(result.get("total_duration",0)/1e9,2),
      "output_tokens":result.get("eval_count",0)})
    except RuntimeError as e:
     return self.send_json(503,{"error":str(e)[:260]})
   if path=="/api/generate":
    models=x.get("models",[x.get("model")])
    if not isinstance(models,list) or not 1<=len(models)<=8 or len(set(map(str,models)))!=len(models) or any(m not in MODELS for m in models):
     raise ValueError("Неизвестная модель")
    prompt=x.get("prompt","");negative=x.get("negative","")
    if not isinstance(prompt,str) or not 2<=len(prompt.strip())<=3000:raise ValueError("Промпт: 2–3000 символов")
    if not isinstance(negative,str) or len(negative)>1500:raise ValueError("Негативный промпт слишком длинный")
    w,h=int(x.get("width",1024)),int(x.get("height",768))
    if (w,h) not in SIZES:raise ValueError("Недопустимый размер")
    s=x.get("seed")
    seed=secrets.randbelow(2**31) if s in (None,"","random") else int(s)
    if seed<0 or seed>2**53-1:raise ValueError("Недопустимый seed")
    ids=STORE.submit(models,prompt.strip(),negative.strip(),w,h,seed)
    return self.send_json(202,{"jobs":ids,"seed":seed})
   if path=="/api/cancel":return self.send_json(200,{"ok":STORE.cancel(str(x.get("id","")))})
   if path=="/api/delete":return self.send_json(200,{"ok":STORE.delete(str(x.get("id","")))})
   return self.send_json(404,{"error":"Не найдено"})
  except (ValueError,TypeError,json.JSONDecodeError) as e:return self.send_json(400,{"error":str(e)[:150]})
  except Exception as e:
   print("REQUEST_ERROR",type(e).__name__,str(e)[:90],flush=True)
   return self.send_json(500,{"error":"Ошибка сервера"})
class Server(ThreadingHTTPServer):
 daemon_threads=True;allow_reuse_address=True
if __name__=="__main__":
 if "--init" in sys.argv or "--reset-password" in sys.argv:
  setup("--reset-password" in sys.argv);sys.exit(0)
 if not CONFIG.exists():
  print("Run --init before starting",file=sys.stderr);sys.exit(2)
 STORE=Store()
 app=Server((HOST,PORT),Handler)
 print("MODEL_LAB_READY http://"+HOST+":"+str(PORT),flush=True)
 try:app.serve_forever()
 except KeyboardInterrupt:app.server_close()
