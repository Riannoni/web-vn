import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {decodeScreenshotPng,captureDisposableBrowserAsset} from "../scripts/e2e/browser-asset-capture.mjs";
const magic=Buffer.from([137,80,78,71,13,10,26,10]);
const clean=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGklEQVR4nGP4JSfyX2SLxn8mFa59DJfkGBgAQFoF+XpJfe8AAAAASUVORK5CYII=","base64");
function chunks(b){let p=8;const arr=[];while(p<b.length){const n=b.readUInt32BE(p);arr.push(b.subarray(p,p+n+12));p+=n+12}assert.equal(p,b.length);return arr}
const [ihdr,idat,iend]=chunks(clean);
const table=Uint32Array.from({length:256},(_,i)=>{let v=i;for(let j=0;j<8;j++)v=(v&1)?0xedb88320^(v>>>1):v>>>1;return v>>>0});
function crc(bytes){let c=0xffffffff;for(const byte of bytes)c=table[(c^byte)&255]^(c>>>8);return(c^0xffffffff)>>>0}
function ck(name,data){const n=Buffer.alloc(8),type=Buffer.from(name,"ascii"),sum=Buffer.alloc(4);n.writeUInt32BE(data.length);type.copy(n,4);sum.writeUInt32BE(crc(Buffer.concat([type,data])));return Buffer.concat([n,data,sum])}
const u32=n=>{const v=Buffer.alloc(4);v.writeUInt32BE(n);return v};
const srgb=ck("sRGB",Buffer.from([0]));
const gamma=n=>ck("gAMA",u32(n));
const standard=[31270,32900,64000,33000,30000,60000,15000,6000];
const chrm=items=>ck("cHRM",Buffer.concat(items.map(u32)));
const png=parts=>Buffer.concat([magic,ihdr,...parts,idat,iend]);
const fixtures={
 bad_gamma:png([gamma(60000),srgb]),
 bad_chrm:png([srgb,gamma(45455),chrm([31270,32900,63999,33000,30000,60000,15000,6000])]),
 bad_gamma_after_srgb:png([srgb,gamma(45000)]),
 valid_srgb_with_standard_gamma_chrm:png([gamma(45455),chrm(standard),srgb]),
 valid_gamma_without_srgb:png([gamma(60000)]),
 // Screenshot-only color admission: no unreviewed custom cHRM primaries,
 // even when the PNG omits the sRGB chunk.
 impossible_standalone_chrm:png([chrm([0xffffffff,32900,64000,33000,30000,60000,15000,6000])]),
 unsupported_custom_standalone_chrm:png([chrm([31271,32900,64000,33000,30000,60000,15000,6000])]),
 valid_standalone_standard_chrm:png([chrm(standard)])
};
test("W3C PNG sRGB+gAMA compatibility values reject conflicts regardless of order",()=>{
 assert.throws(()=>decodeScreenshotPng(fixtures.bad_gamma),/not a fully decoded PNG/);
 assert.throws(()=>decodeScreenshotPng(fixtures.bad_gamma_after_srgb),/not a fully decoded PNG/);
});
test("W3C PNG sRGB+cHRM compatibility values reject forged chromaticities",()=>{
 assert.throws(()=>decodeScreenshotPng(fixtures.bad_chrm),/not a fully decoded PNG/);
});
test("valid compatible sRGB+gAMA+cHRM stays decodable, standalone other gAMA permitted",()=>{
 for(const v of [fixtures.valid_srgb_with_standard_gamma_chrm,fixtures.valid_gamma_without_srgb]){
  const got=decodeScreenshotPng(v);assert.equal(got.width,2);assert.equal(got.height,2);
 }
});
test("unsupported standalone cHRM is refused by the bounded screenshot profile",()=>{
 for(const bytes of [fixtures.impossible_standalone_chrm,fixtures.unsupported_custom_standalone_chrm])
  assert.throws(()=>decodeScreenshotPng(bytes),/not a fully decoded PNG/);
});
test("standalone canonical sRGB chromaticities remain supported",()=>{
 const got=decodeScreenshotPng(fixtures.valid_standalone_standard_chrm);
 assert.deepEqual([got.width,got.height],[2,2]);
});
test("invalid color profile screenshot never persists file",async()=>{
 const uuid="11111111-1111-4111-8111-111111111111";
 const binding={game_id:uuid,action_id:uuid,job_id:uuid,prompt_id:uuid,
 original_png_sha256:"a".repeat(64),contract_sha256:"b".repeat(64),
 kind:"scene",asset_url:"/assets/22222222-2222-4222-8222-222222222222.png"};
 const page={url:async()=>"http://localhost:8190/vn/",
  evaluate:async()=>({ok:true,epoch_ms:100,performance_ms:50,browser_time_origin_ms:50}),
  locator:()=>({screenshot:async()=>fixtures.bad_chrm})};
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),"e2e-srgb-profile-")),f=path.join(dir,"private.png");
 try{
  for(const bytes of [fixtures.bad_chrm,fixtures.impossible_standalone_chrm]){
   page.locator=()=>({screenshot:async()=>bytes});
   await assert.rejects(captureDisposableBrowserAsset(page,binding,{capture_path:f}),/not a fully decoded PNG/);
   await assert.rejects(fs.stat(f),{code:"ENOENT"});
  }
 }finally{await fs.rm(dir,{recursive:true,force:true})}
});
