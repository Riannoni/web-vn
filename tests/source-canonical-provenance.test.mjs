import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import {artSnapshot} from "../src/art-spec.mjs";
import {deriveNarrativeSourceProvenance,verifyNarrativeSourceProvenance,verifyOriginalImageChain} from "../src/source-canonical-provenance.mjs";

const url=id=>"https://example.invalid/assets/"+id+".png?sig=disposable";
const id=n=>String(n).padStart(8,"0")+"-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const clone=structuredClone;
const sha=x=>crypto.createHash("sha256").update(x).digest("hex");
const producerKey="1".repeat(64),resultKey="2".repeat(64);
const hmac=(payload,key)=>crypto.createHmac("sha256",Buffer.from(key,"hex"))
 .update(JSON.stringify(payload)).digest("hex");
const sorted=p=>Object.fromEntries(Object.keys(p).sort().map(k=>[k,p[k]]));
function fixture(){
 const face=id(11),body=id(12),bg=id(13);
 return {
  id:"disposable_provenance_test",version:8,art_style:"realistic",story_id:"test",
  story:{summary:"Fixture only",qa_profile:"fantasy-medieval-v1"},
  hero:{name:"Other",description:""},
  identities:{Mira:{name:"Mira",face_url:url(face),base_sprite_url:url(body),base_style:"realistic"}},
  turn_metrics:{last:{action_id:"player-1"}},
  awaiting_narrator:false,
  messages:[{id:"player-1",role:"player",speaker:"Player",
   text:"Mira reaches the wall.",at:"2026-10-30T23:59:58Z"},
   {id:"narrator-1",role:"narrator",speaker:"Narrator",
   text:"Mira braces her left palm against the wall.",at:"2026-10-31T00:00:00Z"}],
  scene:{location:"Private courtyard",background_url:url(bg),background_style:"realistic",
   cg_revision:7,visual_direction:"rear three-quarter, full body, visible boots",
   image_prompts:{cg:"Private scene prompt grounded in the narrator turn"},
   crowd_policy:"none",
   contacts:[{actor:"Mira",target:"wall",kind:"touch",body_part:"left_palm",
     target_region:[0.8,0.1,0.15,0.7]}],
   sprites:[{name:"Mira",outfit:"closed navy jacket",pose:"forward leaning",
    emotion:"determined",actor_region:[0.12,0.1,0.65,0.85]}]}
 };
}
function snapshot(g){
 const spec=artSnapshot(g,{kind:"scene",style:"realistic",character:"",
  prompt:g.scene.image_prompts?.cg||"Non-narrator fallback image prompt",
  neural_scene:true,narrator_prompt:!!g.scene.image_prompts?.cg});
 spec.source_provenance_v1=deriveNarrativeSourceProvenance(g,spec);
 return spec;
}
test("neural CG creation pins canonical narrator, face, outfit, action and scene source",()=>{
 const game=fixture(),spec=snapshot(game),p=spec.source_provenance_v1;
 assert.equal(p.schema,"web_vn_canonical_source_v1");
 assert.equal(p.game_version,8);
 assert.equal(p.scene_revision,7);
 assert.equal(p.canonical_actors.length,1);
 assert.equal(p.canonical_actors[0].face_asset,id(11)+".png");
 assert.equal(p.canonical_actors[0].outfit,"closed navy jacket");
 assert.equal(p.source_contacts_count,1);
 assert.equal(p.narrative_origin,"canonical_narration_and_scene_cg_prompt");
 assert.equal(p.source_qa_scope,"source_intent_only_not_pixel_qa");
 assert.equal(verifyNarrativeSourceProvenance(game,spec).verified,true);
});
test("missing canonical face fails at creation, not after GPU",()=>{
 const game=fixture();delete game.identities.Mira.face_url;
 assert.throws(()=>snapshot(game),/canonical.*face|face.*reference|identity/i);
});
test("invented actor reference or old wardrobe is rejected",()=>{
 const game=fixture(),spec=snapshot(game);
 spec.characters[0].anchor_face_asset=id(44)+".png";
 assert.throws(()=>verifyNarrativeSourceProvenance(game,spec),/reference|face|source|actor/i);
 const next=snapshot(game);
 next.visual_contract.principals[0].outfit="outdated cloak";
 assert.throws(()=>verifyNarrativeSourceProvenance(game,next),/wardrobe|outfit|contract|source/i);
});
test("silent action discard from wrong actor must not become signed source truth",()=>{
 const game=fixture();game.scene.contacts[0].actor="Imaginary person";
 assert.throws(()=>snapshot(game),/actor|contact|action|source/i);
});
test("missing contact body_part cannot silently certify physical action",()=>{
 const game=fixture();game.scene.contacts[0].body_part="";
 assert.throws(()=>snapshot(game),/body_part|contact|action/i);
});
test("stale version and cross-scene typed contract are rejected",()=>{
 const game=fixture(),spec=snapshot(game);
 const stale=clone(game);stale.version++;
 assert.throws(()=>verifyNarrativeSourceProvenance(stale,spec),/version|stale|source/i);
 const other=clone(game);other.scene.location="Different courtyard";
 assert.throws(()=>verifyNarrativeSourceProvenance(other,spec),/scene|source|location/i);
});
test("forged narrator prompt fails provenance certification, without breaking preview queue",()=>{
 const game=fixture();
 const spec=artSnapshot(game,{kind:"scene",style:"realistic",
  prompt:"unrelated synthetic prompt",neural_scene:true,narrator_prompt:true});
 const provenance=deriveNarrativeSourceProvenance(game,spec);
 assert.equal(provenance.narrative_origin,"incomplete_not_narrative_verified");
});
test("prior-turn narrator without a linked player action is not certified",()=>{
 const game=fixture();game.turn_metrics.last.action_id="different-action";
 const spec=snapshot(game);
 assert.equal(spec.source_provenance_v1.narrative_origin,"incomplete_not_narrative_verified");
});
test("absent narrator text or scene cg prompt is labeled unproven, not fabricated",()=>{
 const game=fixture();game.messages=[];delete game.scene.image_prompts;
 const p=snapshot(game).source_provenance_v1;
 assert.equal(p.narrative_origin,"incomplete_not_narrative_verified");
 assert.equal(p.narrative_message_sha256,null);
 assert.equal(p.narrator_cg_prompt_sha256,null);
});
function sourceJob(){
 const game=fixture(),spec=snapshot(game);
 const job={id:id(90),game_id:game.id,attempts:1,kind:"scene",spec,
  prompt:game.scene.image_prompts.cg,model:"disposable-model"};
 const payload={schema:"web_vn_creation_receipt_v1",producer:"src/jobs.mjs:enqueue",
  job_id:job.id,game_id:game.id,job_kind:"scene",job_style:"realistic",
  job_character:"",game_version:game.version,scene_revision:7,issued_at:"2026-10-31T00:00:00Z",
  save_snapshot_sha256:sha("game bytes"),scene_snapshot_sha256:sha("scene bytes"),
  scene_fingerprint_sha256:sha(spec.cg_basis_snapshot),
  visual_contract_sha256:sha(JSON.stringify(spec.visual_contract)),
  spec_sha256:sha(JSON.stringify(spec)),prompt_sha256:sha(job.prompt),
  model_sha256:sha(job.model),source_assets:[
   {role:"background",asset:spec.background_asset,sha256:sha("background source bytes")},
   {role:"actor_face",actor:"Mira",asset:spec.characters[0].anchor_face_asset,
    sha256:sha("canonical face bytes")},
   {role:"actor_anchor",actor:"Mira",asset:spec.characters[0].anchor_asset,
    sha256:sha("canonical body bytes")}],
  graph_sha256:null,comfy_prompt_id:null,result_sha256:null,output_binding:"pending_not_verified"};
 job.creation_receipt_v1={...payload,signature:hmac(payload,producerKey)};
 return job;
}
function resultChain(job,png,output=png){
 const base={schema:"web_vn_result_binding_v1",job_id:job.id,attempt:1,
  source_signature:job.creation_receipt_v1.signature,graph_sha256:sha("workflow")};
 const sign=p=>({...p,signature:hmac(sorted(p),resultKey)});
 const intent=sign({...base,phase:"intent"});
 const prompt=id(91),dispatch=sign({...base,phase:"dispatch",comfy_prompt_id:prompt,
  intent_signature:intent.signature});
 const result=sign({...base,phase:"result",comfy_prompt_id:prompt,
  original_sha256:sha(png),dispatch_signature:dispatch.signature});
 const final=sign({...base,phase:"final",comfy_prompt_id:prompt,
  original_sha256:sha(png),final_sha256:sha(output),result_signature:result.signature});
 return {intent,dispatch,result,final};
}
function audit(job,binding,originalBytes,expectedPromptId=id(91)){
 return verifyOriginalImageChain({job,binding,originalBytes,expectedPromptId,
  producerKeyHex:producerKey,resultKeyHex:resultKey});
}
test("signed source to workflow/prompt/original PNG is byte-bound but NOT G2",()=>{
 const job=sourceJob(),png=Buffer.from("exact private original bytes");
 const result=audit(job,resultChain(job,png),png);
 assert.equal(result.verified,true);
 assert.equal(result.g2,"NOT_REVIEWED");
 assert.equal(result.original_sha256,sha(png));
});
test("cross-scene PNG or prompt cannot inherit another signed chain",()=>{
 const job=sourceJob(),png=Buffer.from("scene A original");
 const chain=resultChain(job,png);
 assert.throws(()=>audit(job,chain,Buffer.from("scene B original")),/original|sha|png|image/i);
 assert.throws(()=>audit(job,chain,png,id(92)),/prompt|scene|job/i);
 const other=sourceJob();other.id=id(93);
 assert.throws(()=>audit(other,chain,png),/job|source|signature/i);
});
test("forged source receipt, missing pre-submit intent, stale attempt fail closed",()=>{
 const job=sourceJob(),png=Buffer.from("exact private bytes"),chain=resultChain(job,png);
 const forged=clone(job);forged.spec.source_provenance_v1.game_version=123;
 assert.throws(()=>audit(forged,chain,png),/spec|source|signature|receipt/i);
 const missing=clone(chain);delete missing.intent;
 assert.throws(()=>audit(job,missing,png),/intent|phase|chain/i);
 const stale=clone(job);stale.attempts=2;
 assert.throws(()=>audit(stale,chain,png),/attempt|stale/i);
});
test("unsigned producer/result and placeholder keys cannot authenticate pixels",()=>{
 const job=sourceJob(),png=Buffer.from("bytes"),chain=resultChain(job,png);
 assert.throws(()=>verifyOriginalImageChain({job,binding:chain,originalBytes:png,
  expectedPromptId:id(91),producerKeyHex:"",resultKeyHex:resultKey}),/key|signer/i);
 const altered=clone(chain);altered.final.final_sha256="f".repeat(64);
 assert.throws(()=>audit(job,altered,png),/signed|signature|chain|hash/i);
});
