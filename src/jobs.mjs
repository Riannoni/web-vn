import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import {PNG} from "pngjs";
import {dataRoot,attachImage,gameGet,storeCharacterVariant,storeBackgroundVariant} from "./game-store.mjs";
import {artSnapshot,currentSceneMatches,assetName} from "./art-spec.mjs";
import {deriveNarrativeSourceProvenance} from "./source-canonical-provenance.mjs";
import {sceneKey} from "./scene-cache.mjs";
import {claimAttempt,recordStage,finishAttempt,aggregateTimings} from "./job-timing.mjs";
import {pushGameEvent} from "./live-events.mjs";
import {isLocalGpuReserved} from "./gpu-coordinator.mjs";
const root=path.join(dataRoot,"jobs");
let lock=Promise.resolve();
const exclusive=fn=>{const p=lock.then(fn);lock=p.catch(()=>{});return p};
const ID=/^[a-f0-9-]{36}$/;
const jfile=id=>{if(!ID.test(id))throw Error("Invalid job ID");return path.join(root,id+".json")};
const read=id=>fs.readFile(jfile(id),"utf8").then(JSON.parse);
const save=async j=>{
 await fs.mkdir(root,{recursive:true});
 const tmp=jfile(j.id)+"."+crypto.randomUUID()+".tmp";
 await fs.writeFile(tmp,JSON.stringify(j),{mode:0o600});
 await fs.rename(tmp,jfile(j.id));
 pushGameEvent(j.game_id,"job",{id:j.id,kind:j.kind,character:j.character||"",
   status:j.status,stage:j.stage||"",attempts:j.attempts||0,applied:!!j.applied});
};
const all=async()=>{
 await fs.mkdir(root,{recursive:true});
 return Promise.all((await fs.readdir(root)).filter(x=>x.endsWith(".json")).map(x=>read(x.slice(0,-5))));
};
const styles={anime:"waiIllustriousSDXL_v170.safetensors",
 semireal:"CyberRealisticPony_V18.0_F16.safetensors",
 realistic:"CyberRealisticPony_V18.0_F16.safetensors",
 poster:"CyberRealisticPony_V18.0_F16.safetensors",
 animation:"BASNSFWBetterAnimeStyleForNSFWHentai_baseV10.safetensors"};
export function styleList(){return Object.keys(styles)}
export async function enqueue({game_id,prompt,kind="background",style,character="",
 quality="standard",force=false,outfit,pose,emotion,priority,preview_only=false,library_only=false,
 target_location="",target_time_of_day="",target_weather="",
 local_shot="",local_variant_jobs=[],
 local_visual_state=null,local_basis_asset="",local_basis_job_id="",
 local_basis_verified=false,local_fresh_composition=false,
 video_start_asset="",video_source_verified=false,neural_scene=false,narrator_prompt=false}){
 const game=await gameGet(game_id);
 if(!["background","sprite","scene","video","local_cg"].includes(kind))throw Error("Invalid kind");
 if(style!==undefined&&style!==game.art_style)
  throw Error("Art style is locked to "+game.art_style+" for this playthrough; choose a new game for a different style.");
 style=game.art_style;
 if(!styles[style])throw Error("Invalid game style");
 if(preview_only&&!["local_cg","video"].includes(kind)&&quality!=="fast")quality="fast";
 if(library_only&&!["sprite","background"].includes(kind))throw Error("Only sprite/background library jobs supported");
 if(library_only&&preview_only)throw Error("Library and preview are mutually exclusive");
 if(library_only&&kind==="sprite"){
  const canonical=game.identities?.[character];
  if(!canonical?.base_sprite_url)throw Error("Create the canonical sprite before warming variants");
  if(!(game.scene?.sprites||[]).some(s=>s.name===character))throw Error("Character must be visible");
 }
 if(target_location&&!(library_only&&kind==="background"))
  throw Error("Target location requires a library background job");
 if(typeof prompt!=="string"||!prompt.trim()||prompt.length>4000)throw Error("Invalid prompt");
 if(kind==="sprite"&&(!character||!String(character).trim()))throw Error("Character required");
 const spec=artSnapshot(game,{kind,style,character,prompt,quality,force,outfit,pose,emotion,
  preview_only,library_only,target_location,target_time_of_day,target_weather,
  local_shot,local_variant_jobs,local_visual_state,
  local_basis_asset,local_basis_job_id,local_basis_verified,local_fresh_composition,
  video_start_asset,video_source_verified,neural_scene,narrator_prompt});
 if(kind==="scene"||kind==="local_cg"){
  if(kind==="scene"&&game.scene?.background_dirty)
   throw Error("CG requires the background to match the game's locked art style");
  if(kind==="scene"&&!spec.background_asset)
   throw Error("CG needs a valid scene background. Generate the background first.");
  if(kind==="scene"&&spec.characters.length===0)
   throw Error("CG needs characters present on the scene");
  if(kind==="scene"&&spec.composition!=="neural_story"&&
     spec.ready_count!==spec.characters.length)
   throw Error("Layered CG requires visually up-to-date accepted sprites; refresh the characters first.");
  if(kind==="scene"&&spec.composition==="neural_story"&&
     spec.characters.some(x=>!x.anchor_face_asset&&!x.anchor_asset))
   throw Error("Neural CG requires established canonical character references.");
  // Local CG can compose a complete separate scene from the persistent
  // local story state, even if a canonical sprite has become obsolete.
  if(kind==="local_cg"&&!local_visual_state?.characters?.length)
   throw Error("Local CG requires characters in the local visual state");
 }
 // Only the real canonical game enqueue may issue this source record.
 // R-10 must HMAC-sign the resulting complete spec *after* this preflight;
 // R-11 separately binds the Comfy graph/prompt/original PNG.
 if(kind==="scene"&&spec.composition==="neural_story")
  spec.source_provenance_v1=deriveNarrativeSourceProvenance(game,spec);
 const defaultPriority={background:90,sprite:80,scene:50,video:20,local_cg:65};
 const prio=priority===undefined?defaultPriority[kind]:Number(priority);
 if(!Number.isFinite(prio)||prio<0||prio>100)throw Error("Priority must be 0..100");
 return exclusive(async()=>{
  // Explicit exact-variant reuse, while a manual regenerate (force=true) bypasses cache.
  const id=game.identities?.[character];
  const key=[style,spec.variant.outfit,spec.variant.pose,spec.variant.emotion].join("|");
  const candidate=kind==="sprite"&&!force&&!preview_only?id?.variants?.[key]:null;
  // Background-specific color grading is part of the visual contract.
  // Legacy variants without recorded provenance cannot be trusted for reuse.
  const currentBackground=assetName(game.scene?.background_url);
  const cached=candidate&&id?.variant_backgrounds?.[key]===currentBackground?candidate:null;
  if(cached){
   if(library_only)return {id:"cached",game_id,kind,style,status:"done",
     applied:false,library_only:true,cache_hit:true,asset_url:cached};
   const applied=await attachImage(game_id,{kind:"sprite",character,url:cached,style,
     expected_location:spec.expected_location,variant:spec.variant});
   return {id:"cached",game_id,kind,style,status:"done",applied:applied.applied,cache_hit:true,
     asset_url:cached,quality_status:"cached"};
  }
  const existing=await all();
  const sameTarget=j=>j.game_id===game_id&&j.kind===kind&&
    j.character===String(character).slice(0,100)&&
    !!j.spec?.preview_only===!!preview_only&&
    !!j.spec?.library_only===!!library_only&&
    (!library_only||j.spec?.expected_variant_key===spec.expected_variant_key)&&
    ["queued","working"].includes(j.status);
  // Identical requests coalesce, including rapid repeated clicks with force=true.
  const fingerprint=j=>JSON.stringify([j.kind,j.style,j.spec?.quality,
    !!j.spec?.preview_only,!!j.spec?.library_only,j.spec?.expected_location,
    j.spec?.target_time_of_day,j.spec?.target_weather,j.spec?.background_asset,
    j.spec?.expected_variant_key,j.prompt]);
  const requestFingerprint=JSON.stringify([kind,style,quality,!!preview_only,!!library_only,
    spec.expected_location,spec.target_time_of_day,spec.target_weather,
    spec.background_asset,spec.expected_variant_key,prompt.trim()]);
  const identical=existing.find(j=>sameTarget(j)&&fingerprint(j)===requestFingerprint);
  if(identical)return {...identical,deduplicated:true};
  // Automatic neural CG is keyed to its immutable story-shot fingerprint.
  // Do not let secondary request metadata changes supersede an identical
  // queued/working frame. Otherwise a 4s UI poll can starve the GPU forever.
  // An explicit force=true request is still able to replace the old job.
  if(kind==="scene"&&spec.composition==="neural_story"&&!force){
   const pending=existing.find(j=>sameTarget(j)&&
     j.spec?.composition==="neural_story"&&
     j.spec?.cg_basis_snapshot===spec.cg_basis_snapshot&&
     j.spec?.expected_location===spec.expected_location&&
     j.spec?.background_asset===spec.background_asset&&
     !j.superseded_by);
   if(pending)return {...pending,deduplicated:true};
  }
  // A new intent supersedes queued work for this target. Running GPU work may
  // finish physically, but its result will never be attached to the game.
  for(const stale of existing.filter(sameTarget)){
    stale.superseded_by="pending_replacement";
    if(stale.status==="queued"){
      stale.status="superseded";stale.stage="superseded";
      stale.finished_at=new Date().toISOString();
      stale.not_applied_reason="Replaced by a newer art request";
      aggregateTimings(stale);
    }
    await save(stale);
  }
  if(kind==="scene"){
    if(existing.some(j=>j.game_id===game_id&&["background","sprite"].includes(j.kind)&&
       ["queued","working"].includes(j.status)&&!j.superseded_by))
      throw Error("Wait until the active background and sprites finish before composing CG.");
  }
  const j={id:crypto.randomUUID(),game_id,kind,style,character:String(character).slice(0,100),
   prompt:prompt.trim(),model:styles[style],spec,quality_status:"waiting",
   status:"queued",priority:prio,progress:0,attempts:0,created_at:new Date().toISOString(),
   timings:{},attempt_history:[],stage:"queued"};
  await save(j);return j;
 });
}
export async function warmCharacterVariants(gameId,{characters=[],emotions=["smile","concerned"],quality="standard"}={}){
 const g=await gameGet(gameId);
 const visible=(g.scene?.sprites||[]).filter(s=>s.transparent&&!s.visual_dirty&&
   g.identities?.[s.name]?.base_sprite_url);
 const named=Array.isArray(characters)&&characters.length?
   visible.filter(s=>characters.includes(s.name)):visible;
 if(!g.scene?.background_url||g.scene?.background_dirty)throw Error("Complete the current background first");
 const prepared=[],skipped=[];
 const selectedEmotions=[...new Set((Array.isArray(emotions)?emotions:[]).map(x=>String(x).slice(0,40)))].slice(0,3);
 for(const s of named.slice(0,4)){
  for(const emotion of selectedEmotions){
   if(!emotion||emotion===s.emotion)continue;
   const desired=[g.art_style,s.outfit||"default",s.pose||"standing",emotion].join("|");
   const identity=g.identities[s.name];
   if(identity?.variants?.[desired]&&
      identity?.variant_backgrounds?.[desired]===assetName(g.scene.background_url)){
     skipped.push({character:s.name,emotion,reason:"already cached"});continue;
   }
   const j=await enqueue({game_id:gameId,kind:"sprite",character:s.name,quality,priority:12,
     library_only:true,force:false,outfit:s.outfit||"default",pose:s.pose||"standing",
     emotion,prompt:"Prebuild a consistent adult fantasy visual novel character sprite for "+
      s.name+". Preserve the same canonical identity, body proportions and current wardrobe. "+
      "Pose: "+(s.pose||"standing")+", facial expression: "+emotion+
      ". One subject, natural lighting, neutral cutout backdrop."});
   if(j.cache_hit)skipped.push({character:s.name,emotion,reason:"cached"});
   else prepared.push({character:s.name,emotion,job_id:j.id,deduplicated:!!j.deduplicated});
  }
 }
 return {game_id:gameId,queued:prepared,skipped};
}
export async function warmNextLocations(gameId,scenes=[]){
 const game=await gameGet(gameId),queued=[],skipped=[];
 for(const raw of (Array.isArray(scenes)?scenes:[]).slice(0,2)){
  const location=String(raw?.location||"").trim().slice(0,160);
  const time_of_day=String(raw?.time_of_day||"").trim().slice(0,40);
  const weather=String(raw?.weather||"").trim().slice(0,40);
  if(!location)continue;
  const key=sceneKey(game.art_style,{location,time_of_day,weather});
  if(game.scene_catalog?.[key]){
   skipped.push({location,reason:"background cached"});continue;
  }
  const description=String(raw?.description||"").trim().slice(0,750);
  const job=await enqueue({game_id:gameId,kind:"background",quality:"standard",
   priority:8,library_only:true,force:false,target_location:location,
   target_time_of_day:time_of_day,target_weather:weather,
   prompt:"Generate a canonical establishing image of this plausible next location for "+
     "the user's original visual novel: "+location+". "+description+
     ". Match the world's established visual style. Do not depict named characters."});
  queued.push({location,job_id:job.id,status:job.status,deduplicated:!!job.deduplicated});
 }
 return {game_id:gameId,queued,skipped};
}
export async function getJob(id){return read(id)}
export async function jobsForGame(gameId){
 const jobs=(await all()).filter(x=>x.game_id===gameId);
 return jobs.sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,35);
}
const isCpuJob=j=>(j.kind==="scene"&&j.spec?.composition!=="neural_story")||
 (j.kind==="local_cg"&&j.spec?.composition!=="neural_story");
export async function activeGpuJobs(){
 const now=Date.now();
 return (await all()).filter(x=>x.status==="working"&&
   !isCpuJob(x)&&Date.parse(x.lease_until||"")>now);
}
export async function nextJob(pool="any"){
 return exclusive(async()=>{
  const rows=(await all()).sort((a,b)=>a.created_at.localeCompare(b.created_at));
  const now=Date.now();
  for(const j of rows){
   if(j.status==="working"&&Date.parse(j.lease_until||"")<now){
    finishAttempt(j,"timed_out");
    if(j.superseded_by){
      j.status="superseded";j.stage="superseded";
    }else if(j.attempts>=(j.spec?.max_attempts||3)){
      j.status="failed";j.error="Worker lease expired after maximum retries";j.stage="failed";
    }else{
      j.status="queued";j.stage="queued";
    }
    if(j.status!=="queued")j.finished_at=new Date().toISOString();
    aggregateTimings(j);
    await save(j);
   }
  }
  const wanted=j=>(pool==="any"||(pool==="cpu"?isCpuJob(j):!isCpuJob(j)))&&
    (!isLocalGpuReserved()||isCpuJob(j));
  const candidates=rows.filter(j=>j.status==="queued"&&wanted(j)).sort((a,b)=>
    (Number(b.priority||0)-Number(a.priority||0))||
    a.created_at.localeCompare(b.created_at));
  for(const j of candidates){
    // A locally composed CG depends on independently generated, identity-
    // validated sprite previews. Never claim it until both are accepted.
    if(j.kind==="local_cg"&&(j.spec?.local_variant_jobs||[]).length){
      const deps=j.spec?.local_variant_jobs||[];
      const members=j.spec?.characters||[];
      if(deps.length!==members.length||!members.length){
        j.status="failed";j.stage="failed";j.error="Missing local character previews";
        j.finished_at=new Date().toISOString();await save(j);continue;
      }
      const sources=deps.map(d=>rows.find(x=>x.id===d.job_id));
      if(sources.some(x=>!x||["failed","superseded"].includes(x.status))){
        j.status="failed";j.stage="failed";
        j.error="A character preview failed. Request a new local CG.";
        j.finished_at=new Date().toISOString();await save(j);continue;
      }
      if(sources.some(x=>x.status!=="done"))continue;
      if(sources.some((x,i)=>!x.file||x.kind!=="sprite"||
           !x.spec?.preview_only||x.character!==members[i].name||
           x.game_id!==j.game_id)){
        j.status="failed";j.stage="failed";j.error="Invalid local character preview source";
        j.finished_at=new Date().toISOString();await save(j);continue;
      }
      j.spec.local_sprite_assets=sources.map(x=>x.file);
    }
    let valid=false;
    try{
      const game=await gameGet(j.game_id);
      valid=!j.superseded_by&&currentSceneMatches(game,j.spec);
      // Neural CG is conditioned on immutable face references, not on the
      // transparent sprite. Reject stale sprites only for layered composites.
      if(j.kind==="scene"&&
         (game.scene?.background_dirty||
          (j.spec?.composition!=="neural_story"&&
           game.scene?.sprites?.some(s=>s.visual_dirty))))
        valid=false;
    }catch{}
    if(!valid){
      j.status="superseded";j.stage="superseded";
      j.finished_at=new Date().toISOString();
      j.not_applied_reason="Visual state or scene changed before generation started";
      aggregateTimings(j);
      await save(j);
      continue;
    }
    j.status="working";j.qa=null;j.quality_status="checking";j.stage="claimed";
    claimAttempt(j,new Date(now));
    j.lease_until=new Date(now+(j.kind==="video"?60:25)*60*1000).toISOString();
    j.stage_updated_at=new Date(now).toISOString();
    await save(j);return j;
  }
  return null;
 });
}
export async function stageJob(id,{stage,timings={}}){
 const permitted=new Set(["preparing","generating","generated","postprocess","validating","publishing"]);
 if(!permitted.has(stage))throw Error("Invalid stage");
 return exclusive(async()=>{
  const j=await read(id);
  if(j.status!=="working")return j;
  const now=new Date();
  if(stage==="postprocess"&&j.stage==="generated"&&j.stage_updated_at){
    recordStage(j,{cpu_wait_ms:Math.max(0,now.getTime()-Date.parse(j.stage_updated_at))});
  }
  j.stage=stage;
  j.stage_updated_at=now.toISOString();
  recordStage(j,timings);
  await save(j);return j;
 });
}
function boundedQaEvidence(evidence){
 if(!evidence||typeof evidence!=="object"||Array.isArray(evidence))return null;
 const result={version:1};
 for(const key of ["count","location","identity","action"]){
  const src=evidence[key];
  if(!src||typeof src!=="object"||Array.isArray(src))continue;
  const out={};
  if(["verified","violated","unobservable"].includes(src.verdict))out.verdict=src.verdict;
  if(typeof src.confidence==="number"&&Number.isFinite(src.confidence)&&src.confidence>=0&&src.confidence<=1)
   out.confidence=Math.round(src.confidence*1e4)/1e4;
  if(typeof src.reason==="string")out.reason=src.reason.slice(0,160);
  if(key==="action"&&src.features&&typeof src.features==="object"){
   const f={};
   for(const field of ["wall_touch","both_hands","weight_on_feet","forward_lean","ground_pose","uncertain"])
    if(typeof src.features[field]==="boolean")f[field]=src.features[field];
   if(Object.keys(f).length)out.features=f;
  }
  if(Object.keys(out).length)result[key]=out;
 }
 return Object.keys(result).length>1?result:null;
}
export async function reportQA(id,report){
 return exclusive(async()=>{
  const j=await read(id);
  if(j.status!=="working")throw Error("Job is not in progress");
  if(typeof report!=="object"||report===null||typeof report.passed!=="boolean")
    throw Error("Invalid quality report");
  const safeReasons=Array.isArray(report.reasons)?report.reasons.slice(0,8).map(s=>String(s).slice(0,200)):[];
  const safeWarnings=Array.isArray(report.warnings)?report.warnings.slice(0,8).map(s=>String(s).slice(0,200)):[];
  const metrics=report.metrics&&typeof report.metrics==="object"?report.metrics:{};
  const safeMetrics={};
  // Critical evidence cannot be displaced by 32 earlier metrics.
  const priority=["scene_count_verified","scene_location_verified","scene_action_verified",
   "scene_count_confidence","scene_location_confidence","identity_similarity",
   "scene_solo_score","scene_pair_score","scene_action_contrast","vlm_seconds","vlm_error","vlm_caption"];
  for(const k of new Set([...priority,...Object.keys(metrics)])){
    if(Object.keys(safeMetrics).length>=32)break;
    const v=metrics[k];
    if(/^[a-z_]{1,32}$/.test(k)&&(["string","number","boolean"].includes(typeof v))&&
       (typeof v!=="number"||Number.isFinite(v)))
      safeMetrics[k]=typeof v==="string"?v.slice(0,150):v;
  }
  recordStage(j,report.timings||{});
  j.stage="validated";
  j.qa={passed:report.passed,reasons:safeReasons,warnings:safeWarnings,metrics:safeMetrics,
        evidence:boundedQaEvidence(report.evidence),
        semantic_status:["passed","failed","unavailable","not_requested"].includes(report.semantic_status)?
          report.semantic_status:"unavailable", checked_at:new Date().toISOString()};
  j.quality_status=report.passed?(j.qa.semantic_status==="unavailable"?"technical_pass":"passed"):"rejected";
  if(report.passed)delete j.error;
  if(!report.passed||j.superseded_by){
   j.error=j.superseded_by?"Superseded by a newer request":
     safeReasons.join("; ").slice(0,400)||"Quality validation failed";
   j.status=j.superseded_by?"superseded":
     j.attempts>=(j.spec?.max_attempts||3)?"failed":"queued";
   j.stage=j.status;j.progress=0;j.lease_until=null;
   finishAttempt(j,j.status==="queued"?"rejected":j.status);
   if(j.status!=="queued")j.finished_at=new Date().toISOString();
  }
  aggregateTimings(j);
  await save(j);return j;
 });
}
function dimensions(bytes,mime){
 if(mime==="image/png"){
  if(bytes.length<26||!bytes.subarray(0,8).equals(Buffer.from("89504e470d0a1a0a","hex")))
    throw Error("Not PNG");
  if(bytes.toString("ascii",12,16)!=="IHDR")throw Error("PNG header missing");
  return {width:bytes.readUInt32BE(16),height:bytes.readUInt32BE(20),alpha:[4,6].includes(bytes[25])};
 }
 if(mime==="video/mp4"){
  if(bytes.toString("latin1",4,8)!=="ftyp")throw Error("Not MP4");
  return null;
 }
 // Existing image types are retained for legacy jobs, but v4 jobs use PNG.
 if(!["image/jpeg","image/webp"].includes(mime))throw Error("Unsupported media type");
 return null;
}
export async function completeJob(id,bytes,mime,baseUrl){
 // Lock is only held for synchronous write/validation, never for the worker's generation.
 return exclusive(async()=>{
  const publishingStarted=Date.now();
  const j=await read(id);
  if(j.status!=="working")throw Error("Job is not in progress");
  if(j.superseded_by)throw Error("Art job superseded by newer request");
  if(j.spec?.spec_version>=4&&!j.qa?.passed)throw Error("Quality report required before publishing");
  const ext={"image/png":"png","image/jpeg":"jpg","image/webp":"webp","video/mp4":"mp4"}[mime];
  if(!ext)throw Error("Unsupported media type");
  if(!Buffer.isBuffer(bytes)||!bytes.length||bytes.length>100*1024*1024)throw Error("Invalid payload size");
  if(j.kind==="sprite"&&mime!=="image/png")throw Error("Sprites must be PNG with transparency");
  if(j.kind==="video"&&mime!=="video/mp4")throw Error("Video must be MP4");
  if(j.kind!=="video"&&mime==="video/mp4")throw Error("Unexpected video");
  const dims=dimensions(bytes,mime);
  if(dims&&(dims.width<32||dims.height<32||dims.width>4096||dims.height>4096))throw Error("Invalid image dimensions");
  if(j.kind==="sprite"&&!dims?.alpha)throw Error("Sprite is missing alpha channel");
  if(j.kind==="sprite"){
   // Verify actual alpha pixels independently of the worker report, not merely PNG color type.
   const parsed=PNG.sync.read(bytes,{checkCRC:true});
   const pixels=parsed.width*parsed.height;
   let transparent=0,opaque=0;
   for(let i=3;i<parsed.data.length;i+=4){
    const alpha=parsed.data[i];
    if(alpha<24)transparent++;
    if(alpha>220)opaque++;
   }
   if(transparent/pixels<0.12||opaque/pixels<0.045)
    throw Error("Alpha quality rejected: sprite is not a plausible transparent character");
   j.qa.server_alpha_ratio=Math.round(transparent/pixels*1000)/1000;
  }
  if(j.spec?.spec_version>=4&&dims){
   const [w,h]=j.spec.resolution;
   if(Math.abs(dims.width-w)>8||Math.abs(dims.height-h)>8)
    throw Error("Unexpected image size: "+dims.width+"x"+dims.height+" expected "+w+"x"+h);
  }
  const name=crypto.randomUUID()+"."+ext,dir=path.join(dataRoot,"assets");
  await fs.mkdir(dir,{recursive:true});
  await fs.writeFile(path.join(dir,name),bytes,{flag:"wx",mode:0o600});
  j.file=name;j.progress=100;j.stage="done";
  j.asset_url=baseUrl.replace(/\/$/,"")+"/assets/"+name+"?sig="+assetSignature(name);
  j.status="done";j.applied=false;
  if(j.kind==="sprite"&&j.spec?.spec_version>=5&&!j.spec?.preview_only){
   try{
    const face=extractHeadCrop(bytes);
    const faceName=crypto.randomUUID()+".png";
    await fs.writeFile(path.join(dir,faceName),face,{flag:"wx",mode:0o600});
    j.face_url=baseUrl.replace(/\/$/,"")+"/assets/"+faceName+"?sig="+assetSignature(faceName);
   }catch(e){j.face_error=String(e.message).slice(0,150)}
  }
  if(j.spec?.preview_only){
    j.not_applied_reason="Preview only — choose final render to apply";
  }else{
    try{
     const match=currentSceneMatches(await gameGet(j.game_id),j.spec);
     if(match){
      const applied=j.spec?.library_only?
        (j.kind==="background"?
          await storeBackgroundVariant(j.game_id,{location:j.spec.location,style:j.style,
            url:j.asset_url,time_of_day:j.spec.target_time_of_day,
            weather:j.spec.target_weather}):
          await storeCharacterVariant(j.game_id,{character:j.character,style:j.style,
            variant:j.spec.variant,url:j.asset_url,background_asset:j.spec.background_asset})):
        await attachImage(j.game_id,{kind:j.kind,character:j.character,url:j.asset_url,
          style:j.style,expected_location:j.spec?.expected_location||null,
          variant:j.spec?.variant,face_url:j.face_url||"",
          composition:j.spec?.composition||""});
      j.applied=applied?.applied!==false;
      if(j.spec.library_only)j.library_stored=true;
     }else j.not_applied_reason="Scene or character state changed while generating";
    }catch(e){j.not_applied_reason=String(e.message).slice(0,300)}
  }
  recordStage(j,{publish_ms:Date.now()-publishingStarted});
  j.finished_at=new Date().toISOString();
  finishAttempt(j,"done");
  aggregateTimings(j);
  await save(j);return j;
 });
}
function extractHeadCrop(bytes){
 const image=PNG.sync.read(bytes);
 const {width:w,height:h,data}=image;
 let minX=w,minY=h,maxX=0,maxY=0;
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  if(data[(y*w+x)*4+3]>90){
   minX=Math.min(x,minX);maxX=Math.max(x,maxX);
   minY=Math.min(y,minY);maxY=Math.max(y,maxY);
  }
 }
 if(minY>=maxY)throw Error("Missing silhouette");
 const bodyWidth=maxX-minX+1,bodyHeight=maxY-minY+1;
 // The head lives in the upper quarter of a conventional full-body portrait.
 const faceSide=Math.max(32,Math.min(w,h,Math.round(Math.min(bodyWidth*.82,bodyHeight*.24))));
 const cx=Math.round((minX+maxX)/2),cy=Math.round(minY+faceSide*.49);
 const out=new PNG({width:faceSide,height:faceSide,colorType:6});
 for(let y=0;y<faceSide;y++)for(let x=0;x<faceSide;x++){
  const ix=Math.max(0,Math.min(w-1,cx-Math.floor(faceSide/2)+x));
  const iy=Math.max(0,Math.min(h-1,cy-Math.floor(faceSide/2)+y));
  const a=(iy*w+ix)*4,b=(y*faceSide+x)*4;
  // Soft gray background supports CLIPVision image encoder.
  const alpha=data[a+3]/255;
  for(let c=0;c<3;c++)out.data[b+c]=Math.round(data[a+c]*alpha+128*(1-alpha));
  out.data[b+3]=255;
 }
 return PNG.sync.write(out);
}
export async function failJob(id,error,{permanent=false}={}){
 return exclusive(async()=>{
  const j=await read(id);
  if(j.status!=="working")return j;
  j.status=j.superseded_by?"superseded":
    (permanent===true||j.attempts>=(j.spec?.max_attempts||3))?"failed":"queued";
  j.error=j.superseded_by?"Superseded by newer art request":String(error||"Generation failed").slice(0,400);
  j.quality_status="failed";j.stage=j.status;j.progress=0;j.lease_until=null;
  finishAttempt(j,j.status==="queued"?"retry":j.status);
  if(j.status!=="queued")j.finished_at=new Date().toISOString();
  aggregateTimings(j);
  await save(j);return j;
 });
}
export async function ensureCharacterAnchors(gameId,baseUrl){
 const original=await gameGet(gameId);
 const seeded=[];
 for(const s of original.scene?.sprites||[]){
  if(!s.name||!s.image_url||!s.transparent||original.identities?.[s.name]?.base_sprite_url)continue;
  const file=assetName(s.image_url);
  if(!file||!file.endsWith(".png"))continue;
  let bytes;
  try{bytes=await fs.readFile(await assetFile(file))}
  catch{continue}
  let faceUrl="";
  try{
   const crop=extractHeadCrop(bytes);
   const filename=crypto.randomUUID()+".png";
   await fs.writeFile(path.join(dataRoot,"assets",filename),crop,{flag:"wx",mode:0o600});
   faceUrl=baseUrl.replace(/\/$/,"")+"/assets/"+filename+"?sig="+assetSignature(filename);
  }catch{}
  const accepted=await attachImage(gameId,{kind:"sprite",character:s.name,
    url:s.image_url,style:s.art_style||"realistic",face_url:faceUrl,
    expected_location:original.scene.location,preserve_mode:true,
    variant:{emotion:s.emotion||"neutral",pose:s.pose||"standing",outfit:s.outfit||"default"}});
  if(accepted.applied)seeded.push(s.name);
 }
 return {seeded,identities:(await gameGet(gameId)).identities||{}};
}
export async function assetFile(name){
 if(!/^[a-f0-9-]{36}\.(png|jpg|webp|mp4)$/.test(name))throw Error("Invalid asset name");
 return path.join(dataRoot,"assets",name);
}
export function assetSignature(name){
 const secret=process.env.VN_ASSET_SECRET;
 if(!secret)throw Error("VN_ASSET_SECRET required");
 return crypto.createHmac("sha256",secret).update(name).digest("hex");
}
