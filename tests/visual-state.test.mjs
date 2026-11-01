import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {PNG} from "pngjs";
const root=await fs.mkdtemp(path.join(os.tmpdir(),"vn-visual-state-"));
process.env.VN_DATA_DIR=root;
process.env.VN_ASSET_SECRET="test-secret";
// Disposable source-attestation signer; production credentials are never used.
process.env.VN_CREATION_RECEIPT_HMAC_KEY="5".repeat(64);
const store=await import("../src/game-store.mjs");
const jobs=await import("../src/jobs.mjs");
const {variantKey,normalizeSprite}=await import("../src/visual-state.mjs");

function image(w,h,alpha=false){
 const png=new PNG({width:w,height:h,colorType:6});
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  const at=(y*w+x)*4,on=!alpha||(x>w*.18&&x<w*.82&&y>h*.03&&y<h*.96);
  png.data[at]=85;png.data[at+1]=125;png.data[at+2]=85;png.data[at+3]=on?255:0;
 }
 return PNG.sync.write(png);
}
async function publish(job){
 assert.equal((await jobs.nextJob(job.kind==="scene"?"cpu":"gpu")).id,job.id);
 await jobs.reportQA(job.id,{passed:true,reasons:[],semantic_status:"passed"});
 return jobs.completeJob(job.id,image(job.kind==="sprite"?832:1216,job.kind==="sprite"?1216:704,job.kind==="sprite"),"image/png","https://example.org/vn");
}
async function startReady(){
 const g=await store.gameStart();
 const bg=await jobs.enqueue({game_id:g.id,kind:"background",prompt:"town square"});
 await publish(bg);
 const sprite=await jobs.enqueue({game_id:g.id,kind:"sprite",character:"Мира",prompt:"guide"});
 const made=await publish(sprite);
 return {gid:g.id,base:made.asset_url};
}
async function narrative(gid,values){
 const old=await store.gameGet(gid);
 await store.gameAction(gid,"Change visual state",old.version);
 return store.gameNarrate({game_id:gid,messages:[{speaker:"Narrator",text:"The character changes appearance."}],
   scene:{sprites:[{name:"Мира",image_url:old.scene.sprites[0].image_url,
     outfit:values.outfit||"default",emotion:values.emotion||"neutral",
     pose:values.pose||"standing"}]}});
}
// Commit a real test player action and narrator-authored CG prompt through
// game-store, so neural source receipts are not reconstructed from caller text.
async function commitAuthenticCgPrompt(gid,prompt){
 const current=await store.gameGet(gid);
 await store.gameAction(gid,"One disposable scene action",current.version);
 return store.gameNarrate({game_id:gid,
  messages:[{speaker:"Narrator",text:"The scene follows the committed action."}],
  scene:{image_prompts:{cg:prompt}}});
}
test("requested wardrobe changes keep old PNG but mark it stale and invalidate CG",async()=>{
 const {gid,base}=await startReady();
 const cg=await jobs.enqueue({game_id:gid,kind:"scene",prompt:"same square"});
 await publish(cg);
 assert.equal((await store.gameGet(gid)).scene.mode,"cg");
 await narrative(gid,{outfit:"evening cloak",emotion:"skeptical"});
 const now=await store.gameGet(gid);
 const s=now.scene.sprites[0];
 assert.equal(s.image_url,base);
 assert.equal(s.outfit,"evening cloak");
 assert.equal(s.rendered_variant_key,"realistic|default|standing|neutral");
 assert.equal(s.desired_variant_key,"realistic|evening cloak|standing|skeptical");
 assert.equal(s.visual_dirty,true);
 assert.equal(now.scene.cg_dirty,true);
 assert.equal(now.scene.mode,"layered");
 await assert.rejects(()=>jobs.enqueue({game_id:gid,kind:"scene",prompt:"not yet"}),/visually up-to-date/i);
});
test("accepted matching sprite marks rendered state ready and permits fresh CG",async()=>{
 const {gid}=await startReady();
 await narrative(gid,{outfit:"winter coat",emotion:"smile"});
 const j=await jobs.enqueue({game_id:gid,kind:"sprite",character:"Мира",
   outfit:"winter coat",emotion:"smile",prompt:"new winter coat",force:true});
 const out=await publish(j);
 assert.equal(out.applied,true);
 const g=await store.gameGet(gid),s=g.scene.sprites[0];
 assert.equal(s.visual_dirty,false);
 assert.equal(s.desired_variant_key,s.rendered_variant_key);
 assert.equal(s.rendered_variant_key,"realistic|winter coat|standing|smile");
 const cg=await jobs.enqueue({game_id:gid,kind:"scene",prompt:"same two people"});
 const ready=await publish(cg);
 assert.equal(ready.applied,true);
 assert.equal((await store.gameGet(gid)).scene.cg_dirty,false);
});
test("late generation cannot revert a more recent desired state",async()=>{
 const {gid}=await startReady();
 await narrative(gid,{outfit:"winter coat"});
 const late=await jobs.enqueue({game_id:gid,kind:"sprite",character:"Мира",
   outfit:"winter coat",prompt:"coat",force:true});
 assert.equal((await jobs.nextJob("gpu")).id,late.id);
 await narrative(gid,{outfit:"summer dress"});
 await jobs.reportQA(late.id,{passed:true,reasons:[],semantic_status:"passed"});
 const result=await jobs.completeJob(late.id,image(832,1216,true),"image/png","https://example.org/vn");
 assert.equal(result.applied,false);
 const s=(await store.gameGet(gid)).scene.sprites[0];
 assert.equal(s.outfit,"summer dress");
 assert.equal(s.visual_dirty,true);
});
test("neural CG claims and publishes even when its separate sprite is stale",async()=>{
 const {gid}=await startReady();
 await narrative(gid,{outfit:"updated scene wardrobe",pose:"leaning"});
 const before=await store.gameGet(gid);
 assert.equal(before.scene.sprites[0].visual_dirty,true);
 const prompt="Story beat with canonical face and new camera angle";
 await commitAuthenticCgPrompt(gid,prompt);
 const j=await jobs.enqueue({game_id:gid,kind:"scene",
  prompt,
  neural_scene:true,narrator_prompt:true});
 assert.equal(j.spec.composition,"neural_story");
 const claim=await jobs.nextJob("gpu");
 assert.equal(claim?.id,j.id);
 assert.equal(claim.status,"working");
 await jobs.reportQA(j.id,{passed:true,reasons:[],
  semantic_status:"passed"});
 const result=await jobs.completeJob(j.id,image(1216,704),"image/png",
  "https://example.org/vn");
 assert.equal(result.status,"done");
 assert.equal(result.applied,true);
 const current=await store.gameGet(gid);
 assert.equal(current.scene.cg_composition,"neural_story");
 assert.equal(current.scene.cg_dirty,false);
 assert.equal(current.scene.mode,"cg");
 assert.equal(current.scene.sprites[0].visual_dirty,true);
});
test("explicit forced neural CG regeneration queues without updating transparent sprites",async()=>{
 const {gid}=await startReady();
 await commitAuthenticCgPrompt(gid,"Current narrator-authored composition");
 const first=await jobs.enqueue({game_id:gid,kind:"scene",force:true,
  neural_scene:true,narrator_prompt:true,prompt:"Current narrator-authored composition"});
 assert.equal(first.spec.composition,"neural_story");
 assert.equal(first.spec.force,true);
 const second=await jobs.enqueue({game_id:gid,kind:"scene",force:true,
  neural_scene:true,narrator_prompt:true,prompt:"Current narrator-authored composition"});
 assert.equal(second.id,first.id);
 assert.equal(second.deduplicated,true);
});
test("repeated unchanged neural-CG refresh deduplicates rather than superseding queued work",async()=>{
 const {gid}=await startReady();
 const req={game_id:gid,kind:"scene",quality:"standard",
  prompt:"One original scene with exactly one canonical character",neural_scene:true,
  narrator_prompt:true};
 await commitAuthenticCgPrompt(gid,req.prompt);
 const first=await jobs.enqueue(req);
 const second=await jobs.enqueue(req);
 assert.equal(second.id,first.id);
 assert.equal(second.deduplicated,true);
 // A second browser refresh may vary harmless metadata or the wording of
 // its positive prompt; the requested scene intent is still the same.
 const refreshed=await jobs.enqueue({...req,prompt:"A clearer instruction for the same narrative shot"});
 assert.equal(refreshed.id,first.id);
 assert.equal(refreshed.deduplicated,true);
 assert.equal((await jobs.getJob(first.id)).status,"queued");
});
test("visual variants are reused only for matching background",async()=>{
 const {gid}=await startReady();
 const cached=await jobs.enqueue({game_id:gid,kind:"sprite",character:"Мира",prompt:"same"});
 assert.equal(cached.cache_hit,true);
 const bg2=await jobs.enqueue({game_id:gid,kind:"background",prompt:"another part of town"});
 await publish(bg2);
 const s=(await store.gameGet(gid)).scene.sprites[0];
 assert.equal(s.visual_dirty,true);
 const newJob=await jobs.enqueue({game_id:gid,kind:"sprite",character:"Мира",prompt:"new lighting"});
 assert.equal(newJob.status,"queued");
 assert.notEqual(newJob.id,"cached");
});
test("legacy asset with unknown provenance cannot silently be assumed correct",()=>{
 const s=normalizeSprite({name:"Unknown",image_url:"https://example.org/x.png",
    art_style:"realistic",outfit:"formal",transparent:true},{},"https://example.org/bg.png");
 assert.equal(s.visual_dirty,true);
 assert.equal(s.rendered_variant_key,"");
 assert.equal(variantKey(s),"realistic|formal|standing|neutral");
});
test.after(async()=>fs.rm(root,{recursive:true,force:true}));
