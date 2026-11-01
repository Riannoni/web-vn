import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {captureDisposableBrowserAsset} from "../scripts/e2e/browser-asset-capture.mjs";
const id="11111111-1111-4111-8111-111111111111";
const binding={game_id:id,action_id:id,job_id:id,prompt_id:id,
 original_png_sha256:"a".repeat(64),contract_sha256:"b".repeat(64),
 kind:"scene",asset_url:"/assets/22222222-2222-4222-8222-222222222222.png"};
const png=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGklEQVR4nGP4JSfyX2SLxn8mFa59DJfkGBgAQFoF+XpJfe8AAAAASUVORK5CYII=","base64");
test("no screenshot receipt when scene changes between pre-observation and capture",async()=>{
 let evaluated=0;
 const page={
  url:async()=>"http://localhost:8190/vn/",
  evaluate:async()=>++evaluated===1?
   {ok:true,epoch_ms:100,performance_ms:50,browser_time_origin_ms:50}:
   {ok:false,reason:"asset_url_mismatch"},
  locator:()=>({screenshot:async()=>png})
 };
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),"e2e-race-neg-"));
 const dest=path.join(dir,"private.png");
 try{
  await assert.rejects(captureDisposableBrowserAsset(page,binding,{capture_path:dest}),/changed_after_capture|asset_url_mismatch/);
  assert.ok(evaluated>=2,"must validate scene again AFTER screenshot bytes");
  await assert.rejects(fs.stat(dest),{code:"ENOENT"});
 }finally{await fs.rm(dir,{recursive:true,force:true})}
});
test("navigation after screenshot cannot persist a stale scene",async()=>{
 let calls=0;
 const page={
  url:async()=>++calls===1?"http://localhost:8190/vn/":"http://localhost:8190/other",
  evaluate:async()=>({ok:true,epoch_ms:120,performance_ms:55,browser_time_origin_ms:65}),
  locator:()=>({screenshot:async()=>png})
 };
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),"e2e-race-nav-"));
 const dest=path.join(dir,"private.png");
 try{
  await assert.rejects(captureDisposableBrowserAsset(page,binding,{capture_path:dest}),/navigated_after_capture/);
  await assert.rejects(fs.stat(dest),{code:"ENOENT"});
 }finally{await fs.rm(dir,{recursive:true,force:true})}
});
test("bounds screenshot by pre/post browser observations without claiming paint",async()=>{
 let n=0;
 const page={
  url:async()=>"http://localhost:8190/vn/",
  evaluate:async()=>({ok:true,epoch_ms:++n===1?100:125,
   performance_ms:n===1?50:75,browser_time_origin_ms:50}),
  locator:()=>({screenshot:async()=>png})
 };
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),"e2e-race-bounds-"));
 const dest=path.join(dir,"private.png");
 try{
  const result=await captureDisposableBrowserAsset(page,binding,{capture_path:dest});
  assert.equal(result.pre_capture_observed_epoch_ms,100);
  assert.equal(result.post_capture_observed_epoch_ms,125);
  assert.equal(result.browser_visible_verified,false);
  assert.equal(result.full_turn,"NOT_MEASURED");
  assert.ok(!("screenshot_epoch_ms" in result),"pre-capture time must not masquerade as screenshot time");
 }finally{await fs.rm(dir,{recursive:true,force:true})}
});
