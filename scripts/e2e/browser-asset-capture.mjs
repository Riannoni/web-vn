// Disposable, authenticated-browser diagnostic. A screenshot is NOT G2 or a
// trusted enqueue->publish receipt; source attribution must be verified elsewhere.
import crypto from "node:crypto";
import fs from "node:fs/promises";
import {inflateSync} from "node:zlib";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SHA256=/^[0-9a-f]{64}$/i;
const KINDS=new Set(["background","sprite","scene"]);
const PNG_MAGIC=Buffer.from([137,80,78,71,13,10,26,10]);

const PNG_LIMIT_BYTES=24*1024*1024;
const PNG_LIMIT_PIXELS=16_000_000;
const CRC_TABLE=Uint32Array.from({length:256},(_,n)=>{
 let c=n;
 for(let i=0;i<8;i++)c=c&1?0xedb88320^(c>>>1):c>>>1;
 return c>>>0;
});
function crc32(bytes){
 let crc=0xffffffff;
 for(const byte of bytes)crc=CRC_TABLE[(crc^byte)&255]^(crc>>>8);
 return (crc^0xffffffff)>>>0;
}
// Strict, bounded pixel decoding for the non-interlaced RGB/RGBA PNGs emitted
// by Chromium screenshots. Fail closed for unsupported layouts; do not infer
// that valid screenshot bytes authenticate their producer or prove browser paint.
export function decodeScreenshotPng(bytes){
 const invalid=reason=>{throw Error("Screenshot is not a fully decoded PNG: "+reason)};
 if(!Buffer.isBuffer(bytes)||bytes.length<57||bytes.length>PNG_LIMIT_BYTES||
    !bytes.subarray(0,PNG_MAGIC.length).equals(PNG_MAGIC))invalid("signature_or_size");
 let p=PNG_MAGIC.length,ihdr=false,idat=false,endedIdat=false,iend=false;
 let width=0,height=0,bpp=0,seenPalette=false;
 const seenMetadata=new Set();
 let declaredGamma=null,declaredChromaticities=null;
 const compressed=[];
 while(p<bytes.length){
  if(bytes.length-p<12)invalid("truncated_chunk");
  const len=bytes.readUInt32BE(p),start=p+8;
  if(len>bytes.length-start-4)invalid("chunk_bounds");
  const end=start+len,type=bytes.subarray(p+4,p+8);
  // PNG chunk types are exactly four ASCII letters; the third (reserved)
  // letter must be uppercase. Never decode invalid bytes as harmless metadata.
  if(type.length!==4||!Array.from(type).every(c=>(c>=65&&c<=90)||(c>=97&&c<=122))||
     (type[2]&32)!==0)invalid("invalid_chunk_type");
  const kind=type.toString("ascii");
  if(crc32(bytes.subarray(p+4,end))!==bytes.readUInt32BE(end))invalid("chunk_crc");
  if(!ihdr&&kind!=="IHDR")invalid("missing_first_ihdr");
  if(idat&&kind!=="IDAT")endedIdat=true;
  if(kind==="IHDR"){
   if(ihdr||p!==PNG_MAGIC.length||len!==13)invalid("duplicate_or_invalid_ihdr");
   width=bytes.readUInt32BE(start);height=bytes.readUInt32BE(start+4);
   const depth=bytes[start+8],color=bytes[start+9];
   if(!width||!height||width>8192||height>8192||width*height>PNG_LIMIT_PIXELS)
    invalid("dimensions");
   if(depth!==8||(color!==2&&color!==6)||bytes[start+10]!==0||
      bytes[start+11]!==0||bytes[start+12]!==0)invalid("unsupported_png_layout");
   bpp=color===6?4:3;ihdr=true;
  }else if(kind==="IDAT"){
   if(!ihdr||endedIdat||iend)invalid("idat_order");
   idat=true;compressed.push(bytes.subarray(start,end));
  }else if(kind==="IEND"){
   if(!idat||iend||len!==0||end+4!==bytes.length)invalid("invalid_iend");
   iend=true;
  }else if(kind==="PLTE"){
   // Optional suggested palette for truecolor/RGBA may occur only once.
   if(idat||seenPalette||len===0||len>768||len%3!==0)invalid("invalid_plte");
   seenPalette=true;
  }else if(kind==="gAMA"||kind==="sRGB"||kind==="cHRM"||kind==="pHYs"){
   // These known metadata chunks have fixed formats and ordering.
   // Reject every other ancillary chunk rather than accepting unchecked
   // metadata with arbitrary structure as screenshot evidence.
   if(idat||seenMetadata.has(kind))invalid("invalid_metadata_order_or_duplicate");
   if((kind==="gAMA"&&(len!==4||bytes.readUInt32BE(start)===0))||
      (kind==="sRGB"&&(len!==1||bytes[start]>3))||
      (kind==="cHRM"&&len!==32)||
      (kind==="pHYs"&&(len!==9||bytes[start+8]>1||
         bytes.readUInt32BE(start)===0||bytes.readUInt32BE(start+4)===0)))
    invalid("invalid_metadata_shape");
   if((kind==="gAMA"||kind==="sRGB"||kind==="cHRM")&&seenPalette)
    invalid("invalid_metadata_after_palette");
   // W3C PNG sRGB compatibility: a legacy gAMA/cHRM declaration
   // must agree with the sRGB profile, regardless of chunk ordering.
   // Otherwise the PNG does not carry a coherent color-space claim.
   if(kind==="gAMA")declaredGamma=bytes.readUInt32BE(start);
   if(kind==="cHRM")
    declaredChromaticities=Array.from({length:8},(_,i)=>bytes.readUInt32BE(start+4*i));
   seenMetadata.add(kind);
  }else if(kind==="tRNS"){
   // This decoder accepts only truecolor and RGBA. tRNS is invalid in RGBA,
   // and transparency for RGB is deliberately unsupported here.
   invalid("unsupported_transparency_chunk");
  }else{
   invalid("unsupported_chunk");
  }
  p=end+4;
  if(iend)break;
 }
 if(!ihdr||!idat||!iend||p!==bytes.length)invalid("incomplete_png");
 // Deliberately support the bounded Chromium screenshot color profile,
 // not arbitrary PNG/CIE colorimetry. Even a standalone cHRM must have the
 // standard sRGB primaries: accepting unknown custom primaries would require
 // a separately reviewed full color-space parser. Fail closed instead.
 const expectedChromaticities=[31270,32900,64000,33000,30000,60000,15000,6000];
 if(declaredChromaticities!==null&&
    !declaredChromaticities.every((v,i)=>v===expectedChromaticities[i]))
  invalid("unsupported_screenshot_chromaticities");
 if(seenMetadata.has("sRGB")&&declaredGamma!==null&&declaredGamma!==45455)
  invalid("srgb_gamma_conflict");
 const rowBytes=width*bpp,expected=(rowBytes+1)*height;
 let inflated;
 try{
  const input=Buffer.concat(compressed);
  const result=inflateSync(input,{info:true,maxOutputLength:expected});
  if(result.engine.bytesWritten!==input.length)invalid("trailing_idat_data");
  inflated=result.buffer;
 }catch(e){invalid("idat_inflate_"+(e.message.includes("trailing_idat_data")?"trailing":"failed"))}
 if(inflated.length!==expected)invalid("pixel_count");
 const pixelHash=crypto.createHash("sha256");
 let previous=Buffer.alloc(rowBytes);
 for(let y=0;y<height;y++){
  const offset=y*(rowBytes+1),filter=inflated[offset];
  if(filter>4)invalid("invalid_scanline_filter");
  const current=Buffer.allocUnsafe(rowBytes);
  for(let x=0;x<rowBytes;x++){
   const left=x>=bpp?current[x-bpp]:0,up=previous[x];
   const upperLeft=x>=bpp?previous[x-bpp]:0;
   let predict=0;
   if(filter===1)predict=left;
   else if(filter===2)predict=up;
   else if(filter===3)predict=Math.floor((left+up)/2);
   else if(filter===4){
    const p=left+up-upperLeft;
    const a=Math.abs(p-left),b=Math.abs(p-up),c=Math.abs(p-upperLeft);
    predict=a<=b&&a<=c?left:b<=c?up:upperLeft;
   }
   current[x]=(inflated[offset+1+x]+predict)&255;
  }
  pixelHash.update(current);previous=current;
 }
 return {width,height,decoded_pixels_sha256:pixelHash.digest("hex")};
}


export function validateAssetBinding(binding){
 const errors=[];
 if(!binding||typeof binding!=="object"||Array.isArray(binding))
  return ["binding_missing"];
 for(const field of ["game_id","action_id","job_id","prompt_id"])
  if(!UUID.test(binding[field]||""))errors.push("invalid_"+field);
 for(const field of ["original_png_sha256","contract_sha256"])
  if(!SHA256.test(binding[field]||""))errors.push("invalid_"+field);
 if(!KINDS.has(binding.kind))errors.push("invalid_kind");
 if(binding.kind==="sprite"&&(!Number.isInteger(binding.sprite_index)||binding.sprite_index<1||binding.sprite_index>5))
  errors.push("invalid_sprite_index");
 if(typeof binding.asset_url!=="string"||!binding.asset_url.trim())errors.push("asset_url_missing");
 return errors;
}

function selectorFor(binding){
 if(binding.kind==="background")return "#scene-background";
 if(binding.kind==="scene")return "#scene-cg";
 return "#scene-sprites img:nth-child("+binding.sprite_index+")";
}

// Requires an ALREADY authenticated Playwright Page on an explicitly disposable
// game. Does not click, submit, login, enqueue, publish, or call model endpoints.
// No result of this function can establish independent G2 or a full-turn E2E.
export async function captureDisposableBrowserAsset(page,binding,{capture_path}={}){
 const bad=validateAssetBinding(binding);
 if(bad.length)throw Error("Unbound asset: "+bad.join(","));
 if(typeof capture_path!=="string"||!capture_path.endsWith(".png"))throw Error("Private PNG capture path required");
 if(!page||typeof page.url!=="function"||typeof page.evaluate!=="function"||
    typeof page.locator!=="function")throw Error("Authenticated Playwright Page required");
 const origin=new URL(await page.url());
 if(!/^https?:$/.test(origin.protocol))throw Error("Unsupported page protocol");
 const asset=new URL(binding.asset_url,origin);
 if(asset.origin!==origin.origin)throw Error("Cross-origin asset refused");
 if(!/^\/assets\/[0-9a-f-]{36}\.png$/i.test(asset.pathname))
  throw Error("Asset is not a project PNG path");
 const selector=selectorFor(binding);
 const expected=asset.href;
 const observeScene=()=>page.evaluate(async ({selector,expected,gameId,kind})=>{
  const fail=reason=>({ok:false,reason});
  const app=document.getElementById("app");
  if(!app||app.hidden||document.visibilityState!=="visible")return fail("document_not_visible");
  if(document.getElementById("save")?.value!==gameId)return fail("different_save");
  const element=document.querySelector(selector);
  if(!element||!element.isConnected)return fail("image_missing");
  const visible=()=>{
   if(element.hidden||document.getElementById("app")?.hidden)return false;
   const s=getComputedStyle(element),r=element.getBoundingClientRect();
   return s.display!=="none"&&s.visibility==="visible"&&Number(s.opacity)>0&&r.width>0&&r.height>0;
  };
  const source=()=>{
   if(kind!=="background")return element.currentSrc||element.src||"";
   const css=getComputedStyle(element).backgroundImage;
   if(!css.startsWith("url(")||!css.endsWith(")"))return "";
   return css.slice(4,-1).trim().replace(/^["']|["']$/g,"");
  };
  const matches=()=>{
   try{return new URL(source(),location.href).href===expected}
   catch{return false}
  };
  if(!visible())return fail("image_not_displayed");
  if(!matches())return fail("asset_url_mismatch");
  try{
   if(kind==="background"){
    const probe=new Image();probe.src=expected;await probe.decode();
    if(!probe.naturalWidth||!probe.naturalHeight)return fail("background_decode_empty");
   }else{
    await element.decode();
    if(!element.complete||!element.naturalWidth||!element.naturalHeight)return fail("image_decode_empty");
   }
  }catch{return fail("decode_failed")}
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  if(!visible()||!matches()||document.visibilityState!=="visible"||
     document.getElementById("save")?.value!==gameId)return fail("changed_before_capture");
  return {ok:true,epoch_ms:Date.now(),performance_ms:performance.now(),
   browser_time_origin_ms:performance.timeOrigin};
 },{selector,expected,gameId:binding.game_id,kind:binding.kind});
 const observation=await observeScene();
 if(!observation?.ok)throw Error("Browser capture refused: "+(observation?.reason||"unknown"));
 const shot=await page.locator(selector).screenshot({timeout:5000,animations:"disabled"});
 // Screenshot is a separate browser command: its target/save may change after
 // the pre-check. Fail closed if it has changed before persisting evidence.
 const after=await observeScene();
 if(!after?.ok)throw Error("Browser capture refused: changed_after_capture:"+
    (after?.reason||"unknown"));
 if(await page.url()!==origin.href)
  throw Error("Browser capture refused: navigated_after_capture");
 const decoded=decodeScreenshotPng(shot);
 // Never overwrite an existing screenshot, particularly a canonical/private one.
 await fs.writeFile(capture_path,shot,{flag:"wx",mode:0o600});
 return {
  status:"SCREENSHOT_CAPTURED_UNVERIFIED",original_pixels_reviewed:false,
  browser_visible_verified:false,g2:"NOT_REVIEWED",full_turn:"NOT_MEASURED",
  game_id:binding.game_id,action_id:binding.action_id,job_id:binding.job_id,
  prompt_id:binding.prompt_id,contract_sha256:binding.contract_sha256,
  claimed_original_png_sha256:binding.original_png_sha256.toLowerCase(),
  screenshot_sha256:crypto.createHash("sha256").update(shot).digest("hex"),
  screenshot_width:decoded.width,screenshot_height:decoded.height,
  screenshot_decoded_pixels_sha256:decoded.decoded_pixels_sha256,
  asset_url_sha256:crypto.createHash("sha256").update(expected).digest("hex"),
  pre_capture_observed_epoch_ms:observation.epoch_ms,
  post_capture_observed_epoch_ms:after.epoch_ms,
  pre_capture_browser_performance_ms:observation.performance_ms,
  post_capture_browser_performance_ms:after.performance_ms,
  browser_time_origin_ms:observation.browser_time_origin_ms,
  limitations:["producer_lineage_not_authenticated","screenshot_pixels_not_independently_reviewed",
   "capture_is_not_enqueue_to_eligible","browser_paint_not_proven_by_raf",
   "pre_post_observation_not_atomic_source_attribution"]
 };
}
