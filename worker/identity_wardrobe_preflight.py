"""Offline source-only identity/wardrobe contract, NEVER a G2 verdict.

The caller supplies face_sha256_by_asset from an independently verified
private immutable reference ledger. This module never opens or hashes files,
does not run Comfy, and cannot attest the ledger's origin.
"""
import re
from scene_contract import scene_contract

_SHA=re.compile(r"^[a-f0-9]{64}$",re.I)
_ASSET=re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.(?:png|jpe?g|webp)$",re.I)

class ContractBlocked(ValueError):
    pass

def _outfit(value):
    if not isinstance(value, str):
        raise ContractBlocked("Current outfit must be a string")
    s=" ".join(value.split())
    if not s or s.lower() in ("default","unknown","unspecified") or len(s)>320:
        raise ContractBlocked("Current outfit is not explicitly bound")
    return s

def _region(v):
    return (isinstance(v,(list,tuple)) and len(v)==4
        and all(type(n) in (int,float) and 0<=n<=1 for n in v)
        and v[2]>0 and v[3]>0 and v[0]+v[2]<=1.00001
        and v[1]+v[3]<=1.00001)

def preflight(job, *, backend, conditioning, face_sha256_by_asset, body_seed=None):
    """Passes SOURCE_INTENT only; requires real independent PNG/contract G2."""
    if backend=="zimage":
        raise ContractBlocked("Native Z-Image canonical face conditioning unproven")
    if backend!="sdxl" or conditioning!="sdxl_ipadapter_face":
        raise ContractBlocked("Only the source-described SDXL face adapter is supported")
    spec=job.get("spec") if isinstance(job,dict) else None
    if not isinstance(spec,dict):
        raise ContractBlocked("Creation-time job spec missing")
    kind=job.get("kind")
    actors=[]
    if kind=="sprite":
        actors=[{"name":spec.get("character") or job.get("character"),
                 "outfit":(spec.get("variant") or {}).get("outfit"),
                 "anchor_face_asset":spec.get("face_asset")}]
    elif kind=="scene" and spec.get("composition")=="neural_story":
        typed=scene_contract(spec)
        source=spec.get("characters")
        if typed is None or not isinstance(source,list) or not 1<=len(source)<=4:
            raise ContractBlocked("Neural CG needs typed 1-4 principal source contract")
        principals=typed.get("principals") or []
        if len(principals)!=len(source):
            raise ContractBlocked("Source/typed cast cardinality mismatch")
        for actor,principal in zip(source,principals):
            if not isinstance(actor,dict) or not isinstance(principal,dict):
                raise ContractBlocked("Malformed principal")
            if actor.get("name")!=principal.get("name"):
                raise ContractBlocked("Source/typed actor mismatch")
            if _outfit(actor.get("outfit"))!=_outfit(principal.get("outfit")):
                raise ContractBlocked("Current outfit disagrees with frozen scene")
            if actor.get("anchor_face_asset")!=principal.get("anchor_face_asset"):
                raise ContractBlocked("Canonical face swapped after scene freeze")
            if len(source)>1 and (not _region(actor.get("actor_region")) or
                list(actor["actor_region"])!=principal.get("region")):
                raise ContractBlocked("Multi-actor face regions are not source-bound")
        actors=source
    else:
        raise ContractBlocked("Only canonical sprite or neural CG is supported")
    if not isinstance(face_sha256_by_asset,dict):
        raise ContractBlocked("Independent private face checksum ledger required")
    found=[];names=set();assets=set()
    for actor in actors:
        name=str(actor.get("name") or "").strip()
        asset=actor.get("anchor_face_asset")
        if not name or name.casefold() in names:
            raise ContractBlocked("Missing/duplicate actor")
        if not isinstance(asset,str) or not _ASSET.fullmatch(asset) or asset in assets:
            raise ContractBlocked("Face-only canonical reference absent/reused")
        sha=face_sha256_by_asset.get(asset)
        if not isinstance(sha,str) or not _SHA.fullmatch(sha):
            raise ContractBlocked("Canonical face checksum missing")
        found.append({"name":name,"outfit":_outfit(actor.get("outfit")),
                      "face_asset":asset,"face_sha256":sha.lower()})
        names.add(name.casefold());assets.add(asset)
    if body_seed is not None:
        if kind!="sprite" or not isinstance(body_seed,dict):
            raise ContractBlocked("Only a sprite may supply a full-body seed")
        if _outfit(body_seed.get("outfit"))!=found[0]["outfit"]:
            raise ContractBlocked("Stale full-body reference wardrobe")
        if not _SHA.fullmatch(str(body_seed.get("sha256") or "")):
            raise ContractBlocked("Full-body seed SHA not bound")
    return {"status":"SOURCE_INTENT_CONSISTENT_NOT_G2","actors":found,
            "next":"Independent source+graph review, bounded GPU, original-pixel G2"}
