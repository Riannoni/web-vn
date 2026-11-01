// Source-truth preflight for REAL canonical game scenes (not a prompt-derived
// reconstruction). This module has no filesystem/network/GPU side effects.
// R-10's producer HMAC must sign the resulting artSnapshot spec at enqueue;
// R-11's worker HMAC separately binds graph -> prompt -> original bytes.
// The checks below cannot establish semantic G2 or independent Comfy history.
import crypto from "node:crypto";
import {PNG} from "pngjs";
import {buildSceneContract} from "./scene-contract.mjs";
import {sceneIntentFingerprint} from "./visual-state.mjs";

const HEX=/^[0-9a-f]{64}$/;
const ASSET=/^[0-9a-f-]{36}\.(?:png|jpg|webp)$/i;
const UUID=/^[0-9a-f-]{36}$/;
const ACTIONS=new Set(["touch","hold","support","lean_on"]);
const digest=x=>crypto.createHash("sha256").update(x).digest("hex");
const fail=reason=>{throw Error("Canonical source provenance: "+reason)};
const requireTrue=(condition,reason)=>{if(!condition)fail(reason)};
const norm=value=>String(value??"").trim().replace(/\s+/g," ");
const bytesAsset=url=>{
 if(typeof url!=="string")return "";
 try{
  const file=new URL(url).pathname.split("/").at(-1)||"";
  return ASSET.test(file)?file:"";
 }catch{return ""}
};
function canonicalIdentity(game,name){
 const entries=Object.entries(game?.identities||{}).filter(([key,value])=>
  key.toLowerCase()===name.toLowerCase()||
  norm(value?.name).toLowerCase()===name.toLowerCase());
 requireTrue(entries.length===1,"ambiguous or missing canonical identity for named actor");
 requireTrue(norm(entries[0][1]?.name).toLowerCase()===name.toLowerCase(),
  "canonical identity record does not match named actor");
 return entries[0][1];
}
function ensureRealScene(game,spec){
 requireTrue(game&&typeof game==="object"&&spec&&typeof spec==="object",
  "game/save or art spec absent");
 requireTrue(typeof game.id==="string"&&game.id.length>0&&
  Number.isSafeInteger(game.version)&&game.version>=1,
  "canonical save ID/version missing");
 requireTrue(spec.kind==="scene"&&spec.composition==="neural_story",
  "not a canonical neural scene");
 const scene=game.scene;
 requireTrue(scene&&typeof scene==="object"&&
  Array.isArray(scene.sprites)&&scene.sprites.length>0,
  "canonical scene or named actors missing");
 requireTrue(spec.expected_location===scene.location&&
  spec.location===norm(scene.location)&&
  spec.style===game.art_style&&spec.background_style===scene.background_style&&
  scene.background_dirty!==true,
  "canonical scene/location/background/style mismatch");
 const background=bytesAsset(scene.background_url);
 requireTrue(background&&spec.background_asset===background,
  "canonical background asset missing or mismatched");
 requireTrue(spec.cg_basis_snapshot===sceneIntentFingerprint(scene),
  "scene intent is stale or fabricated");
 const characters=spec.characters;
 const contract=spec.visual_contract;
 requireTrue(Array.isArray(characters)&&characters.length===scene.sprites.length&&
  characters.length<=12&&contract?.version===1&&
  contract.scene_kind==="scene"&&Array.isArray(contract.principals)&&
  contract.principals.length===scene.sprites.length,
  "typed Scene Contract cast missing or truncated");
 const names=new Set(),canonicalActors=[];
 for(let i=0;i<scene.sprites.length;i++){
  const source=scene.sprites[i],actor=characters[i],typed=contract.principals[i];
  const name=norm(source?.name),key=name.toLowerCase();
  requireTrue(name&&name.length<=100&&!names.has(key),
   "duplicate or empty named principal");
  names.add(key);
  const identity=canonicalIdentity(game,name);
  const face=bytesAsset(identity.face_url),body=bytesAsset(identity.base_sprite_url);
  requireTrue(face,"canonical face reference missing");
  requireTrue(actor?.name===name&&typed?.id===name&&typed?.name===name,
   "source actor identity and typed principal mismatch");
  requireTrue(actor.anchor_face_asset===face&&typed.anchor_face_asset===face&&
   actor.anchor_asset===(body||"")&&typed.anchor_asset===(body||""),
   "canonical face/body reference mismatch");
  requireTrue(actor.outfit===norm(source.outfit||"default")&&
   typed.outfit===actor.outfit&&actor.pose===norm(source.pose||"standing")&&
   typed.pose===actor.pose&&typed.emotion===actor.emotion,
   "canonical wardrobe/pose/emotion source mismatch");
  canonicalActors.push({id:name,face_asset:face,body_asset:body||null,
   outfit:actor.outfit,pose:actor.pose,
   identity_origin:"game.identities",wardrobe_origin:"game.scene.sprites"});
 }
 const contacts=scene.contacts??[];
 requireTrue(Array.isArray(contacts)&&contacts.length<=12,"source action list invalid");
 for(const item of contacts){
  requireTrue(item&&typeof item==="object"&&!Array.isArray(item)&&
   names.has(norm(item.actor).toLowerCase())&&
   norm(item.actor)&&norm(item.target)&&ACTIONS.has(norm(item.kind))&&
   norm(item.body_part),"source contact/action actor, target, kind or body_part missing");
  requireTrue(norm(item.actor).length<=100&&norm(item.target).length<=100&&
   norm(item.body_part).length<=40,"source action would be truncated");
 }
 const expected=buildSceneContract({kind:"scene",environment:spec.environment,
  location:scene.location,characters,scene});
 requireTrue(expected.contacts.length===contacts.length&&
  JSON.stringify(expected)===JSON.stringify(contract),
  "typed contract omits or forges canonical cast/camera/contacts");
 const camera=scene.camera||scene.visual_direction||"";
 requireTrue(norm(camera).length<=180,
  "camera instruction would be silently truncated in typed Scene Contract");
 return {scene,contract,canonicalActors,contacts};
}

// ArtSnapshot calls this synchronously at the first creation boundary.
// The returned object is deterministic, bounded and intentionally unsigned:
// only the R-10 enqueue HMAC makes it tamper-evident. Not a visual PASS.
export function deriveNarrativeSourceProvenance(game,spec){
 const {scene,contract,canonicalActors,contacts}=ensureRealScene(game,spec);
 const messages=Array.isArray(game.messages)?game.messages:[];
 const nIndex=messages.findLastIndex(m=>m?.role==="narrator"&&
  typeof m.text==="string"&&m.text.trim());
 const pIndex=messages.findLastIndex(m=>m?.role==="player"&&
  typeof m.text==="string"&&m.text.trim());
 const last=nIndex<0?null:messages[nIndex];
 const action=pIndex<0?null:messages[pIndex];
 const prompt=scene.image_prompts?.cg;
 const storedPrompt=typeof prompt==="string"&&prompt.trim()?prompt:null;
 const hasNarrator=typeof last?.id==="string"&&last.id.length>0;
 const actionId=game.turn_metrics?.last?.action_id;
 const sameCommittedTurn=hasNarrator&&typeof action?.id==="string"&&
  action.id===actionId&&pIndex>=0&&nIndex>pIndex&&
  game.awaiting_narrator!==true;
 // Never certify a fallback or mismatched prompt as narrator-authored.
 // Legacy image preview requests remain enqueueable, but their source origin
 // is explicitly UNVERIFIED and R-10/R-11 provenance approval rejects it.
 const authoredPrompt=spec.narrator_prompt===true&&storedPrompt&&
  norm(spec.prompt)===norm(storedPrompt);
 return {
  schema:"web_vn_canonical_source_v1",
  source_phase:"game_store_art_snapshot_before_enqueue",
  game_id:game.id,game_version:game.version,
  scene_revision:Number.isSafeInteger(scene.cg_revision)?scene.cg_revision:0,
  scene_intent_sha256:digest(sceneIntentFingerprint(scene)),
  typed_contract_sha256:digest(JSON.stringify(contract)),
  action_id:sameCommittedTurn?action.id:null,
  action_message_sha256:sameCommittedTurn?digest(JSON.stringify({
   id:action.id,at:action.at??null,text:action.text})):null,
  narrative_message_id:hasNarrator?last.id:null,
  narrative_message_sha256:hasNarrator?digest(JSON.stringify({
   id:last.id,at:last.at??null,speaker:last.speaker??null,text:last.text})):null,
  narrator_cg_prompt_sha256:storedPrompt?digest(storedPrompt):null,
  narrative_origin:sameCommittedTurn&&authoredPrompt?
   "canonical_narration_and_scene_cg_prompt":"incomplete_not_narrative_verified",
  canonical_actors:canonicalActors,source_contacts_count:contacts.length,
  explicit_contacts_sha256:digest(JSON.stringify(contacts)),
  camera_origin:scene.camera?"scene.camera":
   scene.visual_direction?"scene.visual_direction":"unspecified_not_proven",
  crowd_policy_origin:["none","ambient","crowd"].includes(scene.crowd_policy)?
   "canonical_scene_explicit":"inferred_or_unspecified",
  source_qa_scope:"source_intent_only_not_pixel_qa"
 };
}
export function verifyNarrativeSourceProvenance(game,spec){
 const observed=spec?.source_provenance_v1;
 requireTrue(observed&&typeof observed==="object","signed-intent source snapshot missing");
 const rebuilt=deriveNarrativeSourceProvenance(game,spec);
 requireTrue(JSON.stringify(observed)===JSON.stringify(rebuilt),
  "stale game version, forged source or cross-scene source snapshot");
 return {verified:true,scope:"canonical_source_structure_only",
  signature_verified:false,g2:"NOT_REVIEWED",g3:"NO_GO"};
}

function hmac(payload,key){
 return crypto.createHmac("sha256",key).update(JSON.stringify(payload)).digest("hex");
}
function validatedKey(value,role){
 requireTrue(typeof value==="string"&&HEX.test(value),
  role+" HMAC trusted signer key absent or malformed");
 return Buffer.from(value,"hex");
}
function equalHex(actual,expected,reason){
 requireTrue(typeof actual==="string"&&HEX.test(actual)&&
  crypto.timingSafeEqual(Buffer.from(actual,"hex"),Buffer.from(expected,"hex")),reason);
}
function verifyProducer(job,producerKey){
 const receipt=job?.creation_receipt_v1,source=job?.spec?.source_provenance_v1;
 requireTrue(receipt&&typeof receipt==="object"&&source?.schema==="web_vn_canonical_source_v1",
  "trusted source receipt or real canonical source missing");
 const {signature,...payload}=receipt;
 equalHex(signature,hmac(payload,producerKey),"producer signature mismatch");
 requireTrue(payload.schema==="web_vn_creation_receipt_v1"&&
  payload.producer==="src/jobs.mjs:enqueue"&&
  payload.job_id===job.id&&payload.game_id===job.game_id&&
  payload.game_version===source.game_version&&
  payload.scene_revision===source.scene_revision&&
  source.narrative_origin==="canonical_narration_and_scene_cg_prompt"&&
  payload.spec_sha256===digest(JSON.stringify(job.spec))&&
  payload.visual_contract_sha256===digest(JSON.stringify(job.spec.visual_contract))&&
  payload.scene_fingerprint_sha256===digest(job.spec.cg_basis_snapshot)&&
  payload.prompt_sha256===digest(job.prompt)&&
  payload.model_sha256===digest(job.model)&&
  payload.graph_sha256===null&&payload.comfy_prompt_id===null&&
  payload.result_sha256===null&&payload.output_binding==="pending_not_verified",
  "source receipt job/spec/save/scene/prompt no longer matches trusted creation");
 const assets=payload.source_assets;
 // All signed sources must belong to the named canonical scene. A valid HMAC
 // over extra actor references is NOT scene attribution or identity evidence.
 requireTrue(Array.isArray(source.canonical_actors)&&
  source.canonical_actors.length>0&&source.canonical_actors.length<=12,
  "canonical source named actor set missing or invalid");
 const expectedAssetCount=1+source.canonical_actors.length+
  source.canonical_actors.filter(actor=>!!actor.body_asset).length;
 requireTrue(Array.isArray(assets)&&assets.length===expectedAssetCount,
  "canonical source asset count mismatch: unexpected or missing source reference");
 const match=(role,name,actor)=>Array.isArray(assets)&&assets.some(x=>
  x?.role===role&&x.asset===name&&(actor===undefined||x.actor===actor)&&HEX.test(x.sha256));
 requireTrue(match("background",job.spec.background_asset),
  "source background asset bytes not bound");
 for(const actor of source.canonical_actors){
  requireTrue(match("actor_face",actor.face_asset,actor.id),
   "canonical face reference bytes not bound");
  if(actor.body_asset)requireTrue(match("actor_anchor",actor.body_asset,actor.id),
   "canonical body reference bytes not bound");
 }
 return signature;
}
// Golden/source reviewers MUST re-read actual private canonical bytes from
// the attributed local asset store. Signed filenames/hashes alone do not prove
// those references are still present, unmodified or from the same scene.
// The caller must independently obtain these Buffers; this auditor never
// accepts asserted SHA strings in place of source bytes.
function verifyCreationSourceBytes(signedAssets,sourceAssetBytes){
 requireTrue(Array.isArray(signedAssets)&&signedAssets.length>=2&&signedAssets.length<=25,
  "canonical source receipt asset set missing or invalid");
 requireTrue(Array.isArray(sourceAssetBytes)&&sourceAssetBytes.length===signedAssets.length,
  "canonical source bytes missing or extra source supplied");
 const seen=new Set();
 for(let i=0;i<signedAssets.length;i++){
  const ref=signedAssets[i],observed=sourceAssetBytes[i];
  const actor=ref?.actor??null;
  const identity=JSON.stringify([ref?.role,actor,ref?.asset]);
  requireTrue(typeof ref?.role==="string"&&ASSET.test(ref?.asset??"")&&
   !seen.has(identity),"canonical source receipt duplicated or invalid");
  seen.add(identity);
  requireTrue(observed&&observed.role===ref.role&&
   (observed.actor??null)===actor&&observed.asset===ref.asset,
   "canonical source actor/asset attribution or scene mismatch");
  requireTrue(Buffer.isBuffer(observed.bytes)&&observed.bytes.length>0&&
   observed.bytes.length<=64*1024*1024,
   "canonical source bytes missing or invalid");
  equalHex(ref.sha256,digest(observed.bytes),
   "canonical source SHA256 mismatch with signed creation receipt");
 }
 return signedAssets.length;
}
const PNG_SIGNATURE=Buffer.from([137,80,78,71,13,10,26,10]);
function requireDecodableOriginalPng(bytes){
 requireTrue(Buffer.isBuffer(bytes)&&bytes.length>=57&&
  bytes.length<=64*1024*1024&&bytes.subarray(0,8).equals(PNG_SIGNATURE),
  "original PNG signature or size invalid");
 let offset=8,seenIHDR=false,seenIDAT=false,seenIEND=false;
 let width=0,height=0,chunkCount=0;
 while(offset+12<=bytes.length){
  requireTrue(++chunkCount<=100000,"original PNG excessive chunks");
  const length=bytes.readUInt32BE(offset);
  requireTrue(length<=bytes.length-offset-12,"original PNG truncated chunk");
  const type=bytes.toString("ascii",offset+4,offset+8);
  if(!seenIHDR)requireTrue(type==="IHDR","original PNG missing first IHDR");
  if(type==="IHDR"){
   requireTrue(!seenIHDR&&length===13,"original PNG duplicate/invalid IHDR");
   seenIHDR=true;
   width=bytes.readUInt32BE(offset+8);
   height=bytes.readUInt32BE(offset+12);
   requireTrue(width>0&&height>0&&width<=8192&&height<=8192&&
    width*height<=16*1024*1024,"original PNG dimensions outside limit");
  }
  if(type==="IDAT")seenIDAT=true;
  if(type==="IEND"){
   requireTrue(length===0&&seenIDAT&&
    offset+12===bytes.length,"original PNG truncated or trailing bytes after IEND");
   seenIEND=true;
   break;
  }
  offset+=length+12;
 }
 requireTrue(seenIHDR&&seenIDAT&&seenIEND,"original PNG missing IDAT/IEND");
 try{
  // CRC-correct corrupt IDAT is still rejected by full inflate/pixel decode.
  const decoded=PNG.sync.read(bytes,{checkCRC:true});
  requireTrue(decoded.width===width&&decoded.height===height&&
   Buffer.isBuffer(decoded.data)&&decoded.data.length>0,
   "original PNG decoded pixels/dimensions mismatch");
 }catch{
  fail("original PNG full decode/CRC/IDAT invalid");
 }
}
const sorted=payload=>Object.fromEntries(Object.keys(payload).sort().map(k=>[k,payload[k]]));
const PHASES=["intent","dispatch","result","final"];

// Offline, byte-level auditor intended for a private Golden evidence path.
// It requires distinct trusted producer/worker signing keys from approved
// secret storage and independently re-read canonical source Buffers. It does
// not read/print private prompts or images itself.
// Actual worker/result phase is implemented by R-11 and must be deployed
// separately; this is an independent check, NOT a Comfy/G2 attestation.
export function verifyOriginalImageChain({job,binding,originalBytes,sourceAssetBytes,
 expectedPromptId,producerKeyHex,resultKeyHex}={}){
 const producerKey=validatedKey(producerKeyHex,"producer");
 const workerKey=validatedKey(resultKeyHex,"result");
 requireTrue(producerKeyHex!==resultKeyHex,"producer/result signer keys must be independent");
 requireTrue(Buffer.isBuffer(originalBytes)&&originalBytes.length>0,
  "exact original PNG bytes missing");
 requireTrue(UUID.test(job?.id||"")&&Number.isSafeInteger(job?.attempts)&&job.attempts>0,
  "source job ID or attempt invalid");
 const sourceSignature=verifyProducer(job,producerKey);
 const sourceAssetsCount=verifyCreationSourceBytes(
  job.creation_receipt_v1.source_assets,sourceAssetBytes);
 requireTrue(binding&&typeof binding==="object"&&UUID.test(expectedPromptId||""),
  "worker result binding or expected Comfy prompt ID missing");
 let graph=null,prompt=null;
 for(const phase of PHASES){
  const event=binding[phase];
  requireTrue(event&&typeof event==="object"&&!Array.isArray(event),
   phase+" event missing");
  const {signature,...payload}=event;
  equalHex(signature,hmac(sorted(payload),workerKey),
   phase+" signed worker event mismatch");
  requireTrue(payload.schema==="web_vn_result_binding_v1"&&
   payload.phase===phase&&payload.job_id===job.id&&
   payload.attempt===job.attempts&&payload.source_signature===sourceSignature&&
   HEX.test(payload.graph_sha256||""),
   phase+" job/attempt/source/graph mismatch");
  graph??=payload.graph_sha256;
  requireTrue(graph===payload.graph_sha256,"workflow graph changed between worker phases");
  if(phase==="intent"){
   requireTrue(!("comfy_prompt_id" in payload)&&
    !("original_sha256" in payload)&&!("final_sha256" in payload),
    "pre-submit intent contains posthoc result");
   continue;
  }
  requireTrue(UUID.test(payload.comfy_prompt_id||"")&&
   payload.comfy_prompt_id===expectedPromptId,
   "Comfy prompt ID mismatch or cross-scene prompt");
  prompt??=payload.comfy_prompt_id;
  requireTrue(prompt===payload.comfy_prompt_id,"cross-phase prompt mismatch");
  if(phase==="dispatch"){
   requireTrue(payload.intent_signature===binding.intent.signature&&
    !("original_sha256" in payload)&&!("final_sha256" in payload),
    "worker dispatch chain includes posthoc result");
  }else if(phase==="result"){
   requireTrue(payload.dispatch_signature===binding.dispatch.signature&&
    HEX.test(payload.original_sha256||"")&&!("final_sha256" in payload),
    "worker result chain or original digest missing");
  }else{
   requireTrue(payload.result_signature===binding.result.signature&&
    payload.original_sha256===binding.result.original_sha256&&
    HEX.test(payload.final_sha256||""),
    "final worker result chain not linked to original");
  }
 }
 const originalSha=digest(originalBytes);
 requireTrue(binding.result.original_sha256===originalSha,
  "original PNG SHA256 does not match signed Comfy result");
 requireDecodableOriginalPng(originalBytes);
 return {verified:true,scope:"trusted_worker_signed_source_to_decodable_original_png",
  source_signature:sourceSignature,source_assets_count:sourceAssetsCount,
  original_sha256:originalSha,
  graph_sha256:graph,comfy_prompt_id:prompt,g2:"NOT_REVIEWED",g3:"NO_GO",
  requires_independent_comfy_history:true};
}
