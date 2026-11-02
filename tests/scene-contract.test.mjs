import test from "node:test";
import assert from "node:assert/strict";
import {buildSceneContract} from "../src/scene-contract.mjs";
import {artSnapshot} from "../src/art-spec.mjs";
import {parseDirectorPlan} from "../src/local-director.mjs";
const actor=(name,region=null)=>({name,actor_region:region,outfit:"green cloak",pose:"standing"});
test("public market includes optional extras without inventing third protagonist",()=>{
 const c=buildSceneContract({kind:"scene",environment:{id:"outdoor_market_square"},
  location:"Tirren market",characters:[actor("Mira"),actor("Devon")]});
 assert.equal(c.principals.length,2);
 assert.equal(c.crowd.policy,"ambient");
 assert.deepEqual(c.principals.map(x=>x.region),[null,null]);
 assert.deepEqual(c.contacts,[]);
});
test("explicit normalized blocking and contact must name an existing actor",()=>{
 const c=buildSceneContract({kind:"local_cg",location:"Room",environment:{id:"indoor_room"},
  characters:[actor("Mira",[.1,.1,.3,.75])],
  state:{characters:[{name:"Mira",pose:"standing",outfit:"blue cape"}],
    camera:"left three-quarter",crowd_policy:"none",contacts:[
     {actor:"Mira",target:"stone wall",kind:"touch",body_part:"hands",target_region:[.4,.1,.2,.5]},
     {actor:"Ghost",target:"stone wall",kind:"hold"}]}});
 assert.equal(c.contacts.length,1);
 assert.equal(c.contacts[0].actor,"Mira");
 assert.deepEqual(c.principals[0].region,[.1,.1,.3,.75]);
 assert.equal(c.crowd.policy,"none");
});
test("narrator cannot smuggle invalid actor regions or bogus crowd policy",()=>{
 const c=buildSceneContract({kind:"scene",environment:{id:"outdoor_forest"},
  characters:[actor("Mira",[.9,.9,.3,.5])],scene:{crowd_policy:"EVERYONE"}});
 assert.equal(c.principals[0].region,null);
 assert.equal(c.crowd.policy,"unspecified");
});
test("actor state changes are part of authoritative CG intent fingerprint",async()=>{
 const {sceneIntentFingerprint}=await import("../src/visual-state.mjs");
 const scene={location:"street",sprites:[{name:"Ada",outfit:"cloak",pose:"standing"}]};
 const baseline=sceneIntentFingerprint(scene);
 scene.sprites[0].actor_region=[.1,.15,.3,.7];
 assert.notEqual(sceneIntentFingerprint(scene),baseline);
 const withRegion=sceneIntentFingerprint(scene);
 scene.crowd_policy="none";
 assert.notEqual(sceneIntentFingerprint(scene),withRegion);
});
test("local CG contract preserves the entire accepted director wardrobe",()=>{
 const outfit="A closed navy wool vest over a high-collared cream cotton shirt, plain fitted sleeves, dark leather ankle boots, a narrow brown belt with a simple brass buckle, matching cuffs and stitched side seams, practical travel clothes with no decoration, no armor, and no loose outer layers; keep both legs covered in black trousers and wear no cape.";
 // A valid director field with required clothing beyond the old contract cutoff.
 assert.ok(outfit.length<=350&&outfit.indexOf("no cape")>320);
 const game={art_style:"semireal",hero:{name:"Ada",description:"Adult traveler"},
  local_scene:{mode:"local",session_id:"wardrobe-regression"},
  scene:{location:"Market square",sprites:[actor("Ada")]}};
 const {plan,warning}=parseDirectorPlan(JSON.stringify({
   characters:[{name:"Ada",outfit}],render:true}),{game});
 assert.equal(warning,"");
 assert.equal(plan.characters[0].outfit,outfit);
 const spec=artSnapshot(game,{kind:"local_cg",style:"semireal",
   preview_only:true,local_visual_state:plan});
 assert.equal(spec.local_visual_state.characters[0].outfit,outfit);
 assert.equal(spec.visual_contract.principals[0].outfit,outfit);
 assert.equal(spec.characters[0].outfit,"green cloak");
});
