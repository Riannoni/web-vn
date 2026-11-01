import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {captureDisposableBrowserAsset,validateAssetBinding} from "../scripts/e2e/browser-asset-capture.mjs";
const id="11111111-1111-4111-8111-111111111111";
const png="22222222-2222-4222-8222-222222222222";
const binding={game_id:id,action_id:id,job_id:id,prompt_id:id,
 original_png_sha256:"a".repeat(64),contract_sha256:"b".repeat(64),
 kind:"scene",asset_url:"/assets/"+png+".png?sig="+"c".repeat(64)};
const base="http://localhost:8190";
// 2x2 license-free synthetic RGBA image, with IHDR/IDAT/IEND, CRC and pixels.
const screenshot=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGklEQVR4nGP4JSfyX2SLxn8mFa59DJfkGBgAQFoF+XpJfe8AAAAASUVORK5CYII=","base64");
const magicOnly=Buffer.concat([screenshot.subarray(0,8),Buffer.alloc(32)]);
// All chunk CRCs are recomputed: these bytes test inflate/filter, not only CRC.
const corruptZlib=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGklEQVR5nGP4JSfyX2SLxn8mFa59DJfkGBgAQFoF+Z1U23gAAAAASUVORK5CYII=","base64");
const corruptFilter=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGklEQVR4nGP9JSfyX2SLxn8mFa59DJfkGBgAQLQF/tx+XqEAAAAASUVORK5CYII=","base64");
const shortRaster=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGElEQVR4nGP4JSfyX2SLxn8mFa59DJfkADRoBfmlorDSAAAAAElFTkSuQmCC","base64");
const page=(obs={ok:true,epoch_ms:10,performance_ms:5,browser_time_origin_ms:1000},bytes=screenshot)=>({
 url:async()=>base+"/vn/",
 evaluate:async (_fn,args)=>{assert.equal(args.gameId,id);assert.equal(args.expected,base+binding.asset_url);return obs},
 locator:selector=>{assert.equal(selector,"#scene-cg");return {screenshot:async()=>bytes}}
});
test("rejects missing causal identity, original PNG and canonical contract",()=>{
 for(const key of ["game_id","action_id","job_id","prompt_id","original_png_sha256","contract_sha256"]){
  const broken={...binding,[key]:""};assert.ok(validateAssetBinding(broken).length>0,key);
 }
 assert.deepEqual(validateAssetBinding(binding),[]);
 assert.ok(validateAssetBinding({...binding,kind:"sprite"}).includes("invalid_sprite_index"));
});
test("cannot capture cross-origin, non-project asset URLs or hidden/changed scenes",async()=>{
 const f=path.join(os.tmpdir(),"capture-should-not-exist-"+process.pid+".png");
 await assert.rejects(captureDisposableBrowserAsset(page(),{...binding,asset_url:"https://outside.invalid/img.png"},{capture_path:f}),/Cross-origin/);
 await assert.rejects(captureDisposableBrowserAsset(page(),{...binding,asset_url:"/api/anything"},{capture_path:f}),/project PNG/);
 for(const reason of ["different_save","decode_failed","asset_url_mismatch","image_not_displayed","changed_before_capture"])
  await assert.rejects(captureDisposableBrowserAsset(page({ok:false,reason}),binding,{capture_path:f}),new RegExp(reason));
 await assert.rejects(fs.stat(f),{code:"ENOENT"});
});
test("screenshot requires real PNG bytes and cannot overwrite",async()=>{
 const d=await fs.mkdtemp(path.join(os.tmpdir(),"e2e-capture-"));
 const f=path.join(d,"private.png");
 try{
  for(const bytes of [Buffer.from("notpng"),magicOnly,corruptZlib,corruptFilter,shortRaster]){
   await assert.rejects(captureDisposableBrowserAsset(page(undefined,bytes),binding,{capture_path:f}),/not a fully decoded PNG/);
   await assert.rejects(fs.stat(f),{code:"ENOENT"});
  }
  const damagedCrc=Buffer.from(screenshot);damagedCrc[50]^=1;
  await assert.rejects(captureDisposableBrowserAsset(page(undefined,damagedCrc),binding,{capture_path:f}),/chunk_crc/);
  await assert.rejects(fs.stat(f),{code:"ENOENT"});
  const result=await captureDisposableBrowserAsset(page(),binding,{capture_path:f});
  assert.equal(result.status,"SCREENSHOT_CAPTURED_UNVERIFIED");
  assert.equal(result.full_turn,"NOT_MEASURED");
  assert.equal(result.g2,"NOT_REVIEWED");
  assert.equal(result.original_pixels_reviewed,false);
  assert.equal(result.browser_visible_verified,false);
  assert.match(result.screenshot_sha256,/^[a-f0-9]{64}$/);
  assert.equal(result.screenshot_width,2);
  assert.equal(result.screenshot_height,2);
  assert.match(result.screenshot_decoded_pixels_sha256,/^[a-f0-9]{64}$/);
  assert.equal((await fs.stat(f)).mode&0o777,0o600);
  await assert.rejects(captureDisposableBrowserAsset(page(),binding,{capture_path:f}),{code:"EEXIST"});
 }finally{await fs.rm(d,{recursive:true,force:true})}
});
test("missing authorized browser and private destination are fail-closed",async()=>{
 await assert.rejects(captureDisposableBrowserAsset(null,binding,{capture_path:"/tmp/x.png"}),/Playwright Page/);
 await assert.rejects(captureDisposableBrowserAsset(page(),binding,{}),/Private PNG capture path/);
});
