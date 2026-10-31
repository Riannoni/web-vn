"""LAB-only typed SDXL/Pony sprite body-source A/B, never a G2 verdict.

Consumes an independently staged PRIVATE creation-time source record and its
preexisting SDXL face-IPAdapter img2img graph. Changes exactly the body latent
policy: old full-body VAEEncode plus denoise -> fresh EmptyLatent plus denoise=1.
This coupled change is disclosed as ONE body-source policy factor, not a claim
that a Z-Image baseline is comparable. No Comfy/API calls or input uploads here.
The private receipt's *origin* still needs independent Source/Decision review.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import secrets
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "worker"))
from identity_graph_contract import validate_sdxl_identity_graph, IdentityGraphBlocked
from identity_wardrobe_preflight import preflight
from identity_face_upload_pixels import verify_sprite_face_upload

SHA = re.compile(r"^[a-f0-9]{64}$")
CHECKPOINT = "CyberRealisticPony_V18.0_F16.safetensors"
FACTOR = "sdxl_sprite_body_source"
VALUE = "fresh_empty_latent"
CASE = "SPRITE-CANONICAL"
MAX_PRIVATE_IMAGE = 12_000_000


def digest(value):
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _require_sha(s, label):
    if not isinstance(s, str) or not SHA.fullmatch(s):
        raise ValueError(label + "_invalid_sha")
    return s


def _read_pinned(path, sha, *, max_bytes=8_000_000):
    """Read exact hash-pinned bytes without following *any* path component.

    O_NOFOLLOW only on the leaf is insufficient: a mutable private_sources,
    creation_receipts or private_assets ancestor can redirect a read. Open
    directories from / using dirfd + O_DIRECTORY|O_NOFOLLOW and then read the
    regular leaf by its already-open file descriptor.
    """
    _require_sha(sha, "pinned")
    path = Path(path)
    parts = path.parts
    if (not path.is_absolute() or len(parts) < 2 or
            any(part in ("", ".", "..") for part in parts[1:]) or
            not isinstance(max_bytes, int) or max_bytes < 1):
        raise ValueError("missing_or_unsafe_private_source")
    dirflags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    leaf_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        directory_fd = os.open("/", dirflags)
        try:
            for component in parts[1:-1]:
                next_fd = os.open(component, dirflags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            file_fd = os.open(parts[-1], leaf_flags, dir_fd=directory_fd)
            try:
                st = os.fstat(file_fd)
                if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
                    raise ValueError("missing_or_unsafe_private_source")
                pieces = []
                remaining = max_bytes + 1
                while remaining:
                    piece = os.read(file_fd, min(65536, remaining))
                    if not piece:
                        break
                    pieces.append(piece)
                    remaining -= len(piece)
                raw = b"".join(pieces)
                if len(raw) > max_bytes:
                    raise ValueError("missing_or_unsafe_private_source")
            finally:
                os.close(file_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ValueError("missing_or_unsafe_private_source") from exc
    if digest(raw) != sha:
        raise ValueError("private_source_sha_changed")
    return raw


def _image_at(path, sha):
    raw = _read_pinned(path, sha, max_bytes=MAX_PRIVATE_IMAGE)
    if not raw.startswith(bytes.fromhex("89504e470d0a1a0a")):
        raise ValueError("not_original_png")
    from PIL import Image, ImageFile
    # Validate the *same pinned bytes* used by the hash fence, avoiding a
    # filesystem re-open race. PNG CRC verification alone does not decompress
    # IDAT and may pass an image that Comfy cannot decode.
    try:
        if ImageFile.LOAD_TRUNCATED_IMAGES:
            raise ValueError("unsafe_truncated_png_decoder_policy")
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if (image.format != "PNG" or width < 1 or height < 1
                    or width > 4096 or height > 4096
                    or width * height > 16_777_216):
                raise ValueError("invalid_png_dimensions_or_format")
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError("invalid_png_pixels") from exc
    return sha


def _node(graph, number, cls):
    n = graph.get(str(number))
    if not isinstance(n, dict) or n.get("class_type") != cls or not isinstance(n.get("inputs"), dict):
        raise ValueError("baseline_required_" + cls)
    return n["inputs"]


def read_source(root, source_sha, *, comfy_input=None):
    """Read and inspect the frozen private source. No network/GPU/job write."""
    root = Path(root).expanduser().resolve()
    source_sha = _require_sha(source_sha, "source_case")
    raw = _read_pinned(root / "private_sources" / (source_sha + ".json"), source_sha)
    src = json.loads(raw)
    if not isinstance(src, dict) or src.get("schema") != "canonical_sdxl_sprite_baseline_v1":
        raise ValueError("unknown_canonical_source_schema")

    job, graph = src.get("job"), src.get("baseline_graph")
    if not isinstance(job, dict) or job.get("kind") != "sprite" or not isinstance(graph, dict):
        raise ValueError("canonical_sprite_job_or_graph_missing")
    if digest(job) != _require_sha(src.get("source_job_sha256"), "source_job"):
        raise ValueError("source_job_changed")
    if digest(graph) != _require_sha(src.get("baseline_graph_sha256"), "baseline_graph"):
        raise ValueError("baseline_graph_changed")
    spec = job.get("spec")
    variant = spec.get("variant") if isinstance(spec, dict) else None
    outfit = variant.get("outfit") if isinstance(variant, dict) else None
    if not isinstance(outfit, str) or not outfit.strip() or outfit.strip().lower() in ("default","unknown"):
        raise ValueError("authentic_current_outfit_missing")
    if digest(outfit) != _require_sha(src.get("outfit_revision_sha256"), "outfit_revision"):
        raise ValueError("current_outfit_sha_mismatch")
    version = src.get("save_version")
    if type(version) is not int or version < 1:
        raise ValueError("source_save_version_missing")
    for k in ("scene_contract_sha256", "face_original_sha256", "checkpoint_sha256",
              "adapter_sha256", "clipvision_sha256"):
        _require_sha(src.get(k), k)

    receipt_sha = _require_sha(src.get("creation_receipt_sha256"), "creation_receipt")
    receipt = json.loads(_read_pinned(root / "creation_receipts" / (receipt_sha + ".json"), receipt_sha))
    expected = {
        "schema": "creation_bound_sprite_v1",
        "source_job_sha256": src["source_job_sha256"],
        "scene_contract_sha256": src["scene_contract_sha256"],
        "outfit_revision_sha256": src["outfit_revision_sha256"],
        "face_original_sha256": src["face_original_sha256"],
        "save_version": version,
    }
    if not isinstance(receipt, dict) or any(receipt.get(k) != v for k,v in expected.items()):
        raise ValueError("creation_receipt_binding_mismatch")

    actor = spec.get("character") or job.get("character")
    face_asset = spec.get("face_asset")
    ledger = {face_asset: src["face_original_sha256"]}
    intent = preflight(job, backend="sdxl", conditioning="sdxl_ipadapter_face",
                       face_sha256_by_asset=ledger)
    if len(intent["actors"]) != 1 or intent["actors"][0]["name"] != actor:
        raise ValueError("unexpected_sprite_principals")

    if comfy_input is None:
        comfy_input = Path.home() / ".local/share/mcp-vn-comfy/input"
    comfy_input = Path(comfy_input).expanduser().resolve()
    face_original = root / "private_assets" / (src["face_original_sha256"] + ".png")
    _image_at(face_original, src["face_original_sha256"])
    uploads = src.get("face_uploads")
    upload = uploads.get(actor) if isinstance(uploads, dict) else None
    if not isinstance(upload, dict) or upload.get("source_sha256") != src["face_original_sha256"]:
        raise ValueError("face_original_upload_not_bound")
    fname = upload.get("image")
    if not isinstance(fname, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,239}[.]png", fname):
        raise ValueError("unsafe_face_upload_name")
    face_uploaded_sha = _require_sha(upload.get("upload_sha256"), "face_upload")
    upload_path = comfy_input / fname
    _image_at(upload_path, face_uploaded_sha)
    # The merged #111 CPU boundary replays the installed worker's exact
    # original-face -> 512x512 Comfy upload transform. A matching, newly
    # recomputed transport hash alone does not prove matching pixels.
    # Frozen actor/asset/outfit fields are taken from the separately pinned
    # creation receipt, not reflected back from the current job as "trust".
    # Source-origin authentication still requires independent attestation.
    verify_sprite_face_upload(
        canonical_bytes=_read_pinned(face_original, src["face_original_sha256"],
                                     max_bytes=MAX_PRIVATE_IMAGE),
        uploaded_bytes=_read_pinned(upload_path, face_uploaded_sha,
                                   max_bytes=MAX_PRIVATE_IMAGE),
        canonical_sha256=src["face_original_sha256"],
        uploaded_sha256=face_uploaded_sha,
        actor_id=actor,
        frozen_actor_id=receipt.get("frozen_actor_id"),
        face_asset=face_asset,
        frozen_face_asset=receipt.get("frozen_face_asset"),
        current_outfit=outfit,
        frozen_outfit=receipt.get("frozen_current_outfit"),
    )

    if _node(graph, "1", "CheckpointLoaderSimple").get("ckpt_name") != CHECKPOINT:
        raise ValueError("model_family_or_checkpoint_changed")
    dimensions = _node(graph, "2", "EmptyLatentImage")
    if (dimensions.get("width"), dimensions.get("height"), dimensions.get("batch_size")) != (832,1216,1):
        raise ValueError("canvas_or_batch_changed")
    sampler = _node(graph, "5", "KSampler")
    if type(sampler.get("seed")) is not int or sampler["seed"] != src.get("seed"):
        raise ValueError("baseline_seed_changed")
    if sampler.get("latent_image") != ["11",0] or not (0 < float(sampler.get("denoise",0)) < 1):
        raise ValueError("body_source_baseline_not_img2img")
    original = _node(graph, "10", "LoadImage")
    encode = _node(graph, "11", "VAEEncode")
    if encode.get("pixels") != ["10",0]:
        raise ValueError("body_seed_encoder_disconnected")
    body = src.get("body_seed")
    if not isinstance(body, dict) or body.get("outfit") == outfit or not isinstance(body.get("outfit"), str):
        raise ValueError("historical_body_outfit_not_distinct")
    if original.get("image") != body.get("image"):
        raise ValueError("body_seed_graph_mismatch")
    body_sha = _require_sha(body.get("upload_sha256"), "body_upload")
    body_file = body["image"]
    if not isinstance(body_file, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,239}[.]png",body_file):
        raise ValueError("unsafe_body_upload_name")
    _image_at(comfy_input / body_file, body_sha)
    # A correctly conditioned sampler is insufficient if the exported PNG
    # instead points at a stale LoadImage / body seed. Enforce its COMPLETE
    # output ancestry and prohibit any parallel output sink.
    if sum(node.get("class_type") == "SaveImage"
           for node in graph.values() if isinstance(node, dict)) != 1:
        raise ValueError("unexpected_extra_output_sink")
    decoded = _node(graph, "6", "VAEDecode")
    saved = _node(graph, "7", "SaveImage")
    if (decoded.get("samples") != ["5", 0]
            or decoded.get("vae") != ["1", 2]
            or saved.get("images") != ["6", 0]):
        raise ValueError("sprite_output_not_from_sampler")
    positive = _node(graph, "3", "CLIPTextEncode")
    negative = _node(graph, "4", "CLIPTextEncode")
    if not isinstance(positive.get("text"), str) or not isinstance(negative.get("text"), str):
        raise ValueError("frozen_prompt_missing")
    if digest([positive["text"],negative["text"]]) != src.get("prompt_pair_sha256"):
        raise ValueError("frozen_prompt_changed")
    candidate = copy.deepcopy(graph)
    candidate["5"]["inputs"]["latent_image"] = ["2",0]
    candidate["5"]["inputs"]["denoise"] = 1.0
    # Validated Identity module from PR #92 MUST be installed and live here.
    validate_sdxl_identity_graph(job, candidate, intent,
                                 checkpoint=CHECKPOINT, face_uploads=uploads,
                                 body_source=None)
    return src, candidate


def build(root, p, prefix, *, comfy_input=None):
    if p.get("case") != CASE or p.get("factor") != FACTOR or p.get("new_value") != VALUE:
        raise ValueError("unexpected_typed_sdxl_factor")
    src, graph = read_source(root, p["base_case_sha256"], comfy_input=comfy_input)
    # Only output filename differs for attribution, not an image-generation factor.
    graph["7"]["inputs"]["filename_prefix"] = prefix
    return graph, {
        "source_snapshot_sha256": p["base_case_sha256"],
        "source_job_sha256": src["source_job_sha256"],
        "scene_contract_sha256": src["scene_contract_sha256"],
        "creation_receipt_sha256": src["creation_receipt_sha256"],
        "canonical_face_sha256": src["face_original_sha256"],
        "face_upload_sha256": src["face_uploads"][src["job"]["spec"]["character"]]["upload_sha256"],
        "canonical_face_upload_pixels_match_cpu": True,
        "origin_authenticated": False,
        "outfit_revision_sha256": src["outfit_revision_sha256"],
        "source_save_version": src["save_version"],
        # These digests are only claimed by the source manifest; verifying
        # installed model bytes and creation-time provenance is a separate
        # mandatory admission gate owned by Provenance/Decision.
        "checkpoint_sha256_claimed": src["checkpoint_sha256"],
        "adapter_sha256_claimed": src["adapter_sha256"],
        "clipvision_sha256_claimed": src["clipvision_sha256"],
        "frozen_seed": src["seed"],
        "frozen_prompt_sha256": src["prompt_pair_sha256"],
        "body_source_factor": "historical_img2img_to_fresh_latent_with_coupled_denoise",
        "producer_trust": "SHA_BOUND_REQUIRES_INDEPENDENT_ORIGIN_REVIEW",
        "alpha_status": "NOT_PROVIDED_BY_NATIVE_VAE_GRAPH",
        "publish_eligible": False,
        "g2": "NOT_REVIEWED",
        "published": False,
    }


def _open_nofollow_run_directory(run_dir):
    """Pin the actual output directory fd; reject symlinks in every ancestor."""
    path = Path(run_dir).expanduser()
    parts = path.parts
    if not path.is_absolute() or any(x in ("", ".", "..") for x in parts[1:]):
        raise ValueError("missing_private_sprite_run")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except OSError as exc:
        os.close(fd)
        raise ValueError("missing_private_sprite_run") from exc
    except BaseException:
        os.close(fd)
        raise


def derive_rgba_candidate(root, experiment_id, original_png_path, original_sha256):
    """Generate a private, nonpublishable RGBA from pinned original bytes.

    Both filesystem boundaries are fd-pinned: every original-file ancestor
    must be a genuine directory, and the exclusive output is created via
    the already-open private runs/<id> directory descriptor. No path-based
    reopen between validation and write. GPU Lab remains the sole caller
    after exact Comfy output attribution; Golden reviews both pixel sources.
    """
    from firstshot_source_matte import extract_matte
    from PIL import Image, ImageFile

    if not isinstance(experiment_id, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{5,55}", experiment_id):
        raise ValueError("invalid_sprite_experiment_id")
    _require_sha(original_sha256, "comfy_original")
    root = Path(root).expanduser().absolute()
    run_dir = root / "runs" / experiment_id
    run_fd = _open_nofollow_run_directory(run_dir)
    try:
        name = "sprite-rgba-candidate.png"
        try:
            os.stat(name, dir_fd=run_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("derived_sprite_output_exists_no_overwrite")
        if ImageFile.LOAD_TRUNCATED_IMAGES:
            raise ValueError("unsafe_truncated_png_decoder_policy")
        started = time.perf_counter()
        original_path = Path(original_png_path).expanduser().absolute()
        try:
            original_bytes = _read_pinned(
                original_path, original_sha256, max_bytes=MAX_PRIVATE_IMAGE)
        except ValueError as exc:
            if str(exc) == "private_source_sha_changed":
                raise ValueError("frozen source SHA256 mismatch") from exc
            raise
        # The matte consumes the same immutable SHA-checked original bytes;
        # PIL must fully decode them. No second path read or TOCTOU window.
        with Image.open(io.BytesIO(original_bytes)) as original:
            if original.format != "PNG":
                raise ValueError("not_original_png")
            original.load()
            rgba, report = extract_matte(original)
        if (report.get("stage0") != "PASS" or report.get("stage1") != "PASS"
                or report.get("g2") != "UNVERIFIED" or report.get("publishable") is not False
                or report.get("canonical_identity_verified") is not False
                or report.get("wardrobe_verified") is not False):
            raise ValueError("matte_report_must_not_claim_visual_approval")
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        raw = buf.getvalue()
        derived_sha = digest(raw)
        try:
            with Image.open(io.BytesIO(raw)) as im:
                if im.format != "PNG" or im.mode != "RGBA" or list(im.size) != report.get("size"):
                    raise ValueError("derived_sprite_format_or_canvas_invalid")
                im.load()
                if im.getchannel("A").getextrema() != (0, 255):
                    raise ValueError("derived_sprite_has_no_full_alpha_range")
        except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise ValueError("invalid_derived_sprite_png_pixels") from exc

        # Temporary and final entries are created under the PINNED directory
        # fd: changing a parent path cannot redirect the actual write.
        scratch = ".rgba-" + secrets.token_hex(16) + ".tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        output_fd = os.open(scratch, flags, 0o600, dir_fd=run_fd)
        try:
            with os.fdopen(output_fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(scratch, name, src_dir_fd=run_fd,
                        dst_dir_fd=run_fd, follow_symlinks=False)
            except FileExistsError as exc:
                raise ValueError("derived_sprite_output_exists_no_overwrite") from exc
        finally:
            os.unlink(scratch, dir_fd=run_fd)

        return {
            "original_png_sha256": original_sha256,
            "derived_rgba_sha256": derived_sha,
            "derived_rgba_path": str(run_dir / name),
            "rgba_postprocess_seconds": round(time.perf_counter() - started, 3),
            "rgba_stage0": "PASS",
            "rgba_stage1": "PASS",
            "rgba_stage2": "INDEPENDENT_ORIGINAL_AND_DERIVED_PIXEL_REVIEW_REQUIRED",
            "alpha_status": "DERIVED_RGBA_CANDIDATE_G2_UNVERIFIED",
            "publish_eligible": False,
            "g2": "NOT_REVIEWED",
            "published": False,
            "human_labeled": False,
        }
    finally:
        os.close(run_fd)
