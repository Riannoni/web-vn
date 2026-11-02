// Stable per-shot contract: never infer identities, object contact, or actor
// regions from vague narration. Normalized, bounded and independent of game lore.
const clean=(x,n=160)=>String(x??"").trim().replace(/\s+/g," ").slice(0,n);
const validRegion=r=>Array.isArray(r)&&r.length===4&&r.every(x=>
 typeof x==="number"&&Number.isFinite(x))&&r[0]>=0&&r[1]>=0&&r[2]>0&&
 r[3]>0&&r[0]+r[2]<=1.00001&&r[1]+r[3]<=1.00001;
const CROWD=new Set(["none","ambient","crowd","unspecified"]);
function policy(source,id){
 const given=clean(source?.crowd_policy,30).toLowerCase();
 if(CROWD.has(given)&&given!=="unspecified")return given;
 // Public areas may contain unnamed extras; never count them as principals.
 if(["outdoor_market_square","outdoor_street"].includes(id))return "ambient";
 return "unspecified";
}
export function buildSceneContract({kind,environment,location,characters=[],state=null,scene={}}){
 const id=clean(environment?.id||"unclassified",80);
 const local=kind==="local_cg"&&state&&typeof state==="object";
 const actors=local&&Array.isArray(state.characters)?state.characters:characters;
 const canonical=new Map(characters.map(c=>[clean(c.name,100).toLowerCase(),c]));
 const principalNames=new Set();
 const principals=[];
 for(const source of actors.slice(0,12)){
  const name=clean(source?.name,100);
  if(!name||principalNames.has(name.toLowerCase()))continue;
  principalNames.add(name.toLowerCase());
  const ref=canonical.get(name.toLowerCase())||{};
  const region=validRegion(source?.actor_region)?source.actor_region:
               validRegion(ref.actor_region)?ref.actor_region:null;
  principals.push({id:name,name,region,
   // The local director accepts 350 characters; retain its current wardrobe.
   pose:clean(source?.pose,280),outfit:clean(source?.outfit,local?350:160),
   emotion:clean(source?.emotion||source?.expression,80),
   anchor_face_asset:clean(ref.anchor_face_asset,64),
   anchor_asset:clean(ref.anchor_asset,64)});
 }
 const contacts=[];
 const explicit=local?state.contacts:scene.contacts;
 for(const c of (Array.isArray(explicit)?explicit:[]).slice(0,12)){
  const actor=clean(c?.actor,100),target=clean(c?.target,100);
  if(!principalNames.has(actor.toLowerCase())||!target)continue;
  const part=clean(c?.body_part,40),kind=clean(c?.kind,30);
  if(!["touch","hold","support","lean_on"].includes(kind))continue;
  contacts.push({actor,target,body_part:part,kind,
   target_region:validRegion(c?.target_region)?c.target_region:null});
 }
 return {version:1,scene_kind:kind,setting:{id,location:clean(location,180)},
  camera:clean(local?state.camera:(scene.camera||scene.visual_direction),180),
  crowd:{policy:policy(local?state:scene,id),principal_count:principals.length},
  principals,contacts};
}
