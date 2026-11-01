import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {decodeScreenshotPng,captureDisposableBrowserAsset} from "../scripts/e2e/browser-asset-capture.mjs";

const PNG_MAGIC=Buffer.from([137,80,78,71,13,10,26,10]);
const clean=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGklEQVR4nGP4JSfyX2SLxn8mFa59DJfkGBgAQFoF+XpJfe8AAAAASUVORK5CYII=","base64");
const crcTable=Uint32Array.from({length:256},(_,n)=>{let c=n;for(let i=0;i<8;i++)c=c&1?0xedb88320^(c>>>1):c>>>1;return c>>>0});
function crc32(b){let c=0xffffffff;for(const x of b)c=crcTable[(c^x)&255]^(c>>>8);return (c^0xffffffff)>>>0}
function makeChunk(type,data=Buffer.alloc(0)){
 const t=Buffer.from(type,"ascii"),h=Buffer.alloc(8),c=Buffer.alloc(4);
 h.writeUInt32BE(data.length,0);t.copy(h,4);
 c.writeUInt32BE(crc32(Buffer.concat([t,data])),0);
 return Buffer.concat([h,data,c]);
}
function parseChunks(buffer){
 const out=[];let offset=8;
 while(offset<buffer.length){
  const n=buffer.readUInt32BE(offset),last=offset+n+12;
  out.push(buffer.subarray(offset,last));
  offset=last;
 }
 assert.equal(offset,buffer.length);return out;
}
const [ihdr,idat,iend]=parseChunks(clean);
const png=chunks=>Buffer.concat([PNG_MAGIC,...chunks]);
const palette=makeChunk("PLTE",Buffer.from([0,0,0]));
const malformed={
 duplicate_plte:png([ihdr,palette,makeChunk("PLTE",Buffer.from([255,0,0])),idat,iend]),
 invalid_chunk_name:png([ihdr,makeChunk("a1aA",Buffer.from([1])),idat,iend]),
 rgba_trns:png([ihdr,makeChunk("tRNS",Buffer.from([1,2,3,4,5,6])),idat,iend]),
 invalid_gama_length:png([ihdr,makeChunk("gAMA",Buffer.from([0,0,1])),idat,iend])
};
test("baseline decodable 2x2 RGBA control",()=>{assert.deepEqual([decodeScreenshotPng(clean).width,decodeScreenshotPng(clean).height],[2,2])});
test("valid bounded PNG metadata remains supported",()=>{
 const valid=png([ihdr,makeChunk("gAMA",Buffer.from([0,0,177,143])),
  makeChunk("sRGB",Buffer.from([0])),palette,
  makeChunk("pHYs",Buffer.from([0,0,11,19,0,0,11,19,1])),idat,iend]);
 assert.deepEqual([decodeScreenshotPng(valid).width,decodeScreenshotPng(valid).height],[2,2]);
});
for(const [name,bytes] of Object.entries(malformed)){
 test("rejects malformed PNG metadata "+name,()=>{
  assert.throws(()=>decodeScreenshotPng(bytes),/not a fully decoded PNG/);
 });
}
test("capture never persists invalid-metadata PNG",async()=>{
 const id="11111111-1111-4111-8111-111111111111";
 const asset="22222222-2222-4222-8222-222222222222";
 const binding={game_id:id,action_id:id,job_id:id,prompt_id:id,original_png_sha256:"a".repeat(64),contract_sha256:"b".repeat(64),kind:"scene",asset_url:"/assets/"+asset+".png"};
 const page={
  url:async()=>"http://localhost:8190/vn/",
  evaluate:async()=>({ok:true,epoch_ms:1,performance_ms:1,browser_time_origin_ms:1000}),
  locator:()=>({screenshot:async()=>malformed.duplicate_plte})
 };
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),"e2e-metadata-negative-"));
 const dst=path.join(dir,"should-not-exist.png");
 try{
  await assert.rejects(captureDisposableBrowserAsset(page,binding,{capture_path:dst}),/not a fully decoded PNG/);
  await assert.rejects(fs.stat(dst),{code:"ENOENT"});
 }finally{await fs.rm(dir,{recursive:true,force:true})}
});
