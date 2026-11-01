import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

const root=await fs.mkdtemp(path.join(os.tmpdir(),"web-vn-source-enqueue-test-"));
process.env.VN_DATA_DIR=root;
// Fake test-only signers allow this test to run with the independently
// reviewed R-10/R-11 source/worker receipt changes when they merge.
process.env.VN_CREATION_RECEIPT_HMAC_KEY="3".repeat(64);
process.env.VN_RESULT_RECEIPT_HMAC_KEY="4".repeat(64);
const store=await import("../src/game-store.mjs");
const jobs=await import("../src/jobs.mjs");
const {verifyNarrativeSourceProvenance}=await import("../src/source-canonical-provenance.mjs");
const asset=()=>crypto.randomUUID()+".png";
const url=id=>"https://example.invalid/assets/"+id+"?sig=fixture";
const cgPrompt="Canonical narrator scene prompt for disposable provenance test";

async function fixture(){
 const game=await store.gameStart("ash-gate","Fixture Hero","","realistic");
 const background=asset(),body=asset(),face=asset();
 for(const [file,bytes] of [[background,"test-background"],[body,"test-body"],[face,"test-face"]])
  await fs.writeFile(path.join(root,"assets",file),Buffer.from(bytes));
 game.scene={location:"Isolated courtyard",background_url:url(background),
  background_style:"realistic",cg_revision:1,auto_cg_requested:true,
  image_prompts:{cg:cgPrompt},visual_direction:"rear three-quarter full body",
  crowd_policy:"none",
  contacts:[{actor:"Mira",target:"wall",kind:"touch",body_part:"left_palm"}],
  sprites:[{name:"Mira",outfit:"buttoned navy jacket",pose:"lean against wall",
   emotion:"focused",image_url:url(body),transparent:true}]};
 game.identities={Mira:{name:"Mira",face_url:url(face),base_sprite_url:url(body),
  base_style:"realistic",variants:{}}};
 game.turn_metrics={last:{action_id:"fixture-action-1"}};
 game.messages=[{id:"fixture-action-1",role:"player",speaker:"Fixture Hero",
  text:"Approach the wall",at:"2026-10-31T00:00:00Z"},
  {id:"fixture-narrator-1",role:"narrator",speaker:"Narrator",
   text:"Mira braces the wall with her palm.",at:"2026-10-31T00:00:01Z"}];
 game.awaiting_narrator=false;
 game.version=7;
 await fs.writeFile(path.join(root,"games",game.id+".json"),JSON.stringify(game));
 return {game,face,background};
}
async function enqueue(game){
 return jobs.enqueue({game_id:game.id,kind:"scene",style:"realistic",neural_scene:true,
  narrator_prompt:true,prompt:cgPrompt});
}
test("actual canonical enqueue binds existing game version, face, outfit and action",async()=>{
 const {game,face}=await fixture(),j=await enqueue(game);
 const p=j.spec?.source_provenance_v1;
 assert.equal(p.schema,"web_vn_canonical_source_v1");
 assert.equal(p.game_id,game.id);
 assert.equal(p.game_version,7);
 assert.equal(p.canonical_actors[0].face_asset,face);
 assert.equal(p.canonical_actors[0].outfit,"buttoned navy jacket");
 assert.equal(p.source_contacts_count,1);
 assert.equal(p.narrative_origin,"canonical_narration_and_scene_cg_prompt");
 assert.equal(verifyNarrativeSourceProvenance(await store.gameGet(game.id),j.spec).verified,true);
 const other=structuredClone(game);other.version=8;
 assert.throws(()=>verifyNarrativeSourceProvenance(other,j.spec),/version|source|stale/i);
});
test("bad canonical face fails before mutation of game job queue",async()=>{
 const {game}=await fixture();
 delete game.identities.Mira.face_url;
 await fs.writeFile(path.join(root,"games",game.id+".json"),JSON.stringify(game));
 const before=(await fs.readdir(path.join(root,"jobs"))).filter(x=>x.endsWith(".json")).length;
 await assert.rejects(()=>enqueue(game),/canonical.*face|face.*reference/i);
 const after=(await fs.readdir(path.join(root,"jobs"))).filter(x=>x.endsWith(".json")).length;
 assert.equal(after,before);
});
test("missing canonical face asset bytes reject neural CG before queue mutation",async()=>{
 const {game,face}=await fixture();
 // A canonical face URL and scene fingerprint do not establish source bytes.
 await fs.unlink(path.join(root,"assets",face));
 const jobDir=path.join(root,"jobs");
 const before=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 await assert.rejects(()=>enqueue(game),/canonical.*face|face.*bytes|source.*asset|ENOENT/i);
 const after=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 assert.equal(after,before,"missing canonical face bytes must not enqueue a job");
});
test("wrong actor contact cannot vanish from signed Scene Contract",async()=>{
 const {game}=await fixture();
 game.scene.contacts[0].actor="Unknown actor";
 await fs.writeFile(path.join(root,"games",game.id+".json"),JSON.stringify(game));
 await assert.rejects(()=>enqueue(game),/source contact|action actor|source provenance/i);
});
test("missing canonical source plate bytes reject neural CG before a job is queued",async()=>{
 const {game,background}=await fixture();
 // A valid-looking URL/fingerprint is not proof that canonical plate bytes exist.
 await fs.unlink(path.join(root,"assets",background));
 const jobDir=path.join(root,"jobs");
 const before=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 await assert.rejects(()=>enqueue(game),/source|plate|background|asset|ENOENT|bytes/i);
 const after=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 assert.equal(after,before,"missing source bytes must not mutate the job queue");
});
test("symlinked canonical face bytes reject neural CG before queue mutation",async()=>{
 const {game,face,background}=await fixture();
 const facePath=path.join(root,"assets",face);
 await fs.unlink(facePath);
 await fs.symlink(background,facePath);
 const jobDir=path.join(root,"jobs");
 const before=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 await assert.rejects(()=>enqueue(game),/ELOOP|symlink|canonical|source.*asset/i);
 const after=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 assert.equal(after,before,"symlinked face must not mutate queue");
});
test("source save version changed during byte preflight must reject before queue mutation",async()=>{
 const {game,background}=await fixture();
 const gamePath=path.join(root,"games",game.id+".json");
 const jobDir=path.join(root,"jobs");
 const before=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 const originalOpen=fs.open;
 let mutated=false;
 fs.open=async (...args)=>{
  if(!mutated&&String(args[0]).endsWith(background)){
   mutated=true;
   await fs.writeFile(gamePath,JSON.stringify({...game,version:game.version+1}));
  }
  return originalOpen(...args);
 };
 try{
  await assert.rejects(()=>enqueue(game),/stale|version|source|scene|changed/i);
 }finally{fs.open=originalOpen}
 assert.equal(mutated,true,"source file preflight must have been reached");
 const after=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 assert.equal(after,before,"stale save must not create a queued job");
});
test("source plate swapped after successful byte preflight must reject job",async()=>{
 const {game,face,background}=await fixture();
 const platePath=path.join(root,"assets",background),jobDir=path.join(root,"jobs");
 const before=(await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length;
 const originalOpen=fs.open;let swapped=false;
 fs.open=async (...args)=>{
  if(!swapped&&String(args[0]).endsWith(face)){
   swapped=true;
   await fs.writeFile(platePath,Buffer.from("substituted-canonical-source-plate"));
  }
  return originalOpen(...args);
 };
 try{
  await assert.rejects(()=>enqueue(game),/canonical.*source|source.*changed|source.*bytes|mismatch|substitut/i);
 }finally{fs.open=originalOpen}
 assert.equal(swapped,true,"the source swap must occur after original plate preflight");
 assert.equal((await fs.readdir(jobDir)).filter(x=>x.endsWith(".json")).length,before);
});

test("creation receipt HMAC binds actual canonical face, body and source plate at enqueue",async()=>{
 const {game,face,background}=await fixture();
 const job=await enqueue(game);
 const receipt=job.creation_receipt_v1;
 assert.ok(receipt?.signature,"creation-time HMAC receipt must be persisted on the queued job");
 assert.equal(receipt.schema,"web_vn_creation_receipt_v1");
 const dig=bytes=>crypto.createHash("sha256").update(bytes).digest("hex");
 const entries=receipt.source_assets;
 for(const [role,file] of [["background",background],["actor_face",face]]){
  const matched=entries.find(x=>x.role===role&&x.asset===file);
  assert.ok(matched,"missing signed source bytes for "+role);
  assert.equal(matched.sha256,dig(await fs.readFile(path.join(root,"assets",file))));
 }
 assert.equal(receipt.game_id,game.id);
 assert.equal(receipt.game_version,game.version);
 assert.equal(receipt.spec_sha256,dig(JSON.stringify(job.spec)));
 assert.equal((await jobs.verifyCreationReceipt(job)).scope,"creation_source_only");
});
test("signed canonical receipt rejects replayed cross-game or re-pinned wardrobe",async()=>{
 const {game}=await fixture(),other=(await fixture()).game;
 const job=await enqueue(game);
 const cross=structuredClone(job);cross.game_id=other.id;
 await assert.rejects(()=>jobs.verifyCreationReceipt(cross),/receipt|scene|game|signature/i);
 const wardrobe=structuredClone(job);
 wardrobe.spec.characters[0].outfit="wrong historical coat";
 await assert.rejects(()=>jobs.verifyCreationReceipt(wardrobe),/receipt|scene|source|signature|outfit/i);
 const forged=structuredClone(job);
 forged.creation_receipt_v1.source_assets.find(x=>x.role==="actor_face").sha256="0".repeat(64);
 await assert.rejects(()=>jobs.verifyCreationReceipt(forged),/receipt|source|signature|mismatch/i);
});
test("signed source face byte mutation after enqueue rejects old receipt",async()=>{
 const {game,face}=await fixture(),job=await enqueue(game);
 await fs.writeFile(path.join(root,"assets",face),Buffer.from("substituted-face-bytes"));
 await assert.rejects(()=>jobs.verifyCreationReceipt(job),/receipt|asset|source|mismatch/i);
});

test("producer refuses to sign narrator CG prompt not authored by the current committed turn",async()=>{
 const {game}=await fixture();
 game.scene.image_prompts.cg="unrelated story CG request";
 await fs.writeFile(path.join(root,"games",game.id+".json"),JSON.stringify(game));
 const before=(await fs.readdir(path.join(root,"jobs"))).filter(x=>x.endsWith(".json")).length;
 await assert.rejects(()=>enqueue(game),/narrator|prompt|canonical.*origin|creation.*receipt/i);
 assert.equal((await fs.readdir(path.join(root,"jobs"))).filter(x=>x.endsWith(".json")).length,before);
});
test("producer refuses to sign a stale unlinked narrator/player action",async()=>{
 const {game}=await fixture();
 game.turn_metrics.last.action_id="wrong-player-action";
 await fs.writeFile(path.join(root,"games",game.id+".json"),JSON.stringify(game));
 await assert.rejects(()=>enqueue(game),/narrator|action|canonical.*origin|creation.*receipt/i);
});
test.after(async()=>fs.rm(root,{recursive:true,force:true}));
