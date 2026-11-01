#!/usr/bin/env python3
"""Local bounded GPU candidate executor for worker-authored one-factor proposals.

Never generates prompts or G2 verdicts. No model/API billing.
Use --tick from a one-minute systemd timer; no GPU work without an explicit
worker-proposed, frozen, SHA-checked, queued hypothesis.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "worker"))
sys.path.insert(0, str(HERE))
import zimage_backend as z
import run_one as r

ID = re.compile(r"^[A-Z][A-Z0-9_-]{5,55}$")
ALLOWED = {"prompt_text", "native_pose", "sdxl_sprite_body_source"}
STATES = ("pending", "running", "review_pending", "blocked", "reviewed")
MAX_WALL_SECONDS = 90


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def base_sha(case_id):
    c = r.load_case(case_id)
    return sha(json.dumps(c, sort_keys=True, separators=(",", ":")).encode())


def validate(p, *, root=None):
    if not isinstance(p, dict) or set(p) != {
        "schema", "id", "case", "base_case_sha256", "factor",
        "new_value", "hypothesis", "falsifier", "author_task"
    }:
        raise ValueError("unrecognized_plan_schema")
    if p["schema"] != "firstshot_one_factor_v1" or not isinstance(p["id"], str) or not ID.fullmatch(p["id"]):
        raise ValueError("invalid_id")
    if p["factor"] not in ALLOWED:
        raise ValueError("unverified_multi_factor_or_control_graph")
    is_sdxl_sprite = p["factor"] == "sdxl_sprite_body_source"
    if is_sdxl_sprite:
        import sdxl_sprite_factor as sprite
        if p["case"] != sprite.CASE or p["new_value"] != sprite.VALUE:
            raise ValueError("unapproved_sdxl_sprite_factor")
        if root is None:
            raise ValueError("private_sdxl_source_root_required")
        sprite.read_source(root, p["base_case_sha256"])
    elif p["base_case_sha256"] != base_sha(p["case"]):
        raise ValueError("baseline_case_changed")
    if not isinstance(p["author_task"], str) or not re.fullmatch(r"R-[0-9]{1,4}", p["author_task"]):
        raise ValueError("not_renderer_authored")
    if not isinstance(p["hypothesis"], str) or not 30 <= len(p["hypothesis"]) <= 700:
        raise ValueError("hypothesis_not_falsifiable")
    if not isinstance(p["falsifier"], str) or not 30 <= len(p["falsifier"]) <= 700:
        raise ValueError("no_explicit_falsifier")
    value = p["new_value"]
    if p["factor"] == "sdxl_sprite_body_source":
        pass  # Private baseline and typed factor verified above.
    elif p["factor"] == "native_pose":
        from pose_graph_native import POSE_GUIDE_SHA256
        if p["case"] != "CG-03" or value != POSE_GUIDE_SHA256:
            raise ValueError("unapproved_native_pose_factor_or_hash")
    else:
        if not isinstance(value, str) or not 10 <= len(value) <= 5000 or "\x00" in value:
            raise ValueError("invalid_prompt")
        if value == r.load_case(p["case"])["prompt"]:
            raise ValueError("no_actual_changed_factor")
    return p


def setup(root):
    root = Path(root).expanduser().resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    for stage in STATES:
        (root / stage).mkdir(mode=0o700, exist_ok=True)
    return root


def queue(root, p):
    root = setup(root)
    p = validate(p, root=root)
    # G2 review must finish before next hypothesis to avoid blind rerender.
    if list((root / "running").glob("*.json")) or list((root / "review_pending").glob("*.json")):
        return {"enqueued": False, "reason": "one_candidate_requires_review"}
    if any((root / stage / (p["id"] + ".json")).exists() for stage in STATES):
        return {"enqueued": False, "reason": "experiment_id_already_used"}
    if list((root / "pending").glob("*.json")):
        return {"enqueued": False, "reason": "pending_candidate_exists"}
    atomic(root / "pending" / (p["id"] + ".json"), p)
    return {"enqueued": True, "id": p["id"]}


def build_graph_for_plan(p, case, prefix, *, root=None):
    """Build frozen baseline; for CG-03 add only SHA-pinned native pose patch.

    Caller must hold the lab GPU lock, and lab_exclusive must have stopped all
    known competing dev /prompt writers before the first GPU submission.
    This helper itself cannot submit, publish or claim G2.
    """
    if p["factor"] == "sdxl_sprite_body_source":
        import sdxl_sprite_factor as sprite
        if root is None:
            raise ValueError("private_sdxl_source_root_required")
        return sprite.build(root, p, prefix)
    is_pose = p["factor"] == "native_pose"
    graph = z.create_graph(
        case["prompt"] if is_pose else p["new_value"],
        seed=case["seed"], prefix=prefix, width=case["canvas"][0],
        height=case["canvas"][1], private_unanchored=True)
    if not is_pose:
        return graph, {}

    import pose_graph_native as pose
    # Source is an existing private lab-only guide in the Comfy mount, not an
    # arbitrary plan-supplied path. The pinned hash, not its filename, is trust.
    input_dir = Path.home() / ".local/share/mcp-vn-comfy/input"
    source = input_dir / "wall_push_rear_oblique_01.png"
    pose.verify_private_guide(source, expected_sha=p["new_value"])
    info = r.api("/object_info", timeout=8)
    pose.validate_native_nodes(info)
    staged_name = "vn_pose_probe_" + p["id"].lower() + ".png"
    graph = pose.add_native_pose_to_frozen_cg03(
        graph, case, staged_guide_name=staged_name, object_info=info)
    raw = source.read_bytes()
    if sha(raw) != p["new_value"]:
        raise ValueError("pose_guide_changed_during_preflight")
    if not input_dir.is_dir() or input_dir.is_symlink():
        raise ValueError("comfy_input_directory_untrusted")
    staged = input_dir / staged_name
    # Exclusive creation: never overwrite another request's guide. A crash
    # leaves a blocked unique candidate rather than an automatic resend.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(staged, flags, 0o600)
    with os.fdopen(fd, "wb") as dst:
        dst.write(raw)
        dst.flush()
        os.fsync(dst.fileno())
    if sha(staged.read_bytes()) != p["new_value"]:
        raise ValueError("staged_pose_guide_integrity_failed")
    return graph, {
        "pose_guide_sha256": p["new_value"],
        "staged_pose_filename": staged_name,
        "native_union_patch": pose.POSE_PATCH_NAME,
        "pose_approval": "LAB_ONLY_experimental_unapproved",
    }


def tick(root):
    root = setup(root)
    with (root.parent.parent / "gpu-exclusive-lab.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "GPU_OWNER_LOCK_BUSY"}
        pending_review = sorted((root / "review_pending").glob("*.json"))
        if pending_review:
            return {"status": "WAIT_INDEPENDENT_ORIGINAL_PIXEL_REVIEW",
                    "id": pending_review[0].stem}
        incomplete = sorted((root / "running").glob("*.json"))
        if incomplete:
            return {"status": "STOP_UNKNOWN_PREVIOUS_SUBMISSION",
                    "id": incomplete[0].stem}
        todo = sorted((root / "pending").glob("*.json"))
        if not todo:
            return {"status": "NO_APPROVED_WORK"}
        path = todo[0]
        try:
            p = validate(json.loads(path.read_text()), root=root)
        except Exception as exc:
            path.replace(root / "blocked" / path.name)
            return {"status": "BLOCKED_INVALID_PLAN", "detail": type(exc).__name__}
        if not r.queue_empty():
            return {"status": "GPU_QUEUE_BUSY_DEFER", "id": p["id"]}
        is_sprite = p["factor"] == "sdxl_sprite_body_source"
        case = None if is_sprite else r.load_case(p["case"])
        prefix = ("vn_sdxl_sprite_ab_" if is_sprite else "vn_zimage_probe_ab_") + p["id"].lower() + "_"
        try:
            graph, pose_evidence = build_graph_for_plan(p, case, prefix, root=root)
        except Exception as exc:
            # PRE-SUBMIT refusal: no Comfy prompt was sent. The known-blocked
            # result lets lab_exclusive restore stopped dev services safely.
            path.replace(root / "blocked" / path.name)
            return {"status": "BLOCKED_INVALID_PLAN", "detail": type(exc).__name__}
        graph_sha = sha(json.dumps(graph, sort_keys=True).encode())
        record = dict(p)
        record.update(status="PREPARED_NOT_SUBMITTED",
                      started_utc=datetime.now(timezone.utc).isoformat(),
                      source_pack_case_sha256=None if is_sprite else base_sha(p["case"]),
                      graph_sha256=graph_sha,
                      first_attempt=None if is_sprite else (3 if p["factor"] == "native_pose" else 2),
                      experiment_class=("disposable_canonical_sprite_body_source_not_pack_first_shot"
                                        if is_sprite else "disposable_AB_not_pack_first_shot"),
                      frozen_seed=None if is_sprite else case["seed"],
                      frozen_prompt_sha256=None if is_sprite else sha(case["prompt"].encode()),
                      g1="NOT_MEASURED", g2="NOT_REVIEWED",
                      changed_factors=[p["factor"]], published=False)
        record.update(pose_evidence)
        work = root / "runs" / p["id"]
        if work.exists():
            path.replace(root / "blocked" / path.name)
            return {"status": "BLOCKED_RUN_ALREADY_EXISTS"}
        work.mkdir(mode=0o700, parents=True)
        atomic(work / "graph-private.json", graph)
        atomic(work / "result.json", record)
        path.replace(root / "running" / path.name)
        if not r.queue_empty():
            record["status"] = "STOP_QUEUE_CHANGED_BEFORE_SUBMIT"
            atomic(work / "result.json", record)
            return {"status": record["status"]}
        t = time.monotonic()
        try:
            answer = r.api("/prompt", {"prompt": graph, "client_id": "firstshot-autonomous-lab"}, timeout=12)
            pid = answer.get("prompt_id")
            if not isinstance(pid, str) or len(pid) < 8:
                raise RuntimeError("untrusted_comfy_prompt_id")
            record["prompt_id"] = pid
            record["status"] = "SUBMITTED"
            atomic(work / "result.json", record)
            history = None
            while time.monotonic() - t < MAX_WALL_SECONDS:
                h = r.api("/history/" + pid, timeout=8)
                if pid in h:
                    history = h[pid]
                    break
                time.sleep(1)
            if history is None:
                raise RuntimeError("TIMEOUT_UNKNOWN_GPU_JOB_NO_RETRY")
            if history.get("status", {}).get("status_str") == "error":
                raise RuntimeError("COMFY_REPORTED_ERROR")
            outputs = [item for node in history.get("outputs", {}).values()
                       for item in node.get("images", []) if isinstance(item, dict)]
            matched = [x for x in outputs if isinstance(x.get("filename"), str)
                       and x["filename"].startswith(prefix)
                       and x.get("type", "output") == "output" and not x.get("subfolder")]
            if len(matched) != 1:
                raise RuntimeError("not_exactly_one_original_png")
            output_root = Path.home() / ".local/share/mcp-vn-comfy/output"
            png = (output_root / matched[0]["filename"]).resolve()
            if not png.is_relative_to(output_root.resolve()):
                raise RuntimeError("nonlocal_output_path")
            raw = png.read_bytes()
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("invalid_png")
            # Fully decode the exact original Comfy bytes. PNG signature and
            # chunk verification alone can admit CRC-valid, undecodable IDAT.
            import io
            from PIL import Image, ImageFile
            if ImageFile.LOAD_TRUNCATED_IMAGES:
                raise RuntimeError("unsafe_truncated_png_decoder_policy")
            with Image.open(io.BytesIO(raw)) as im:
                if im.format != "PNG":
                    raise RuntimeError("not_exact_original_png")
                size = list(im.size)
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
            # GPU submit->PNG ends BEFORE CPU RGBA matte. This is NOT
            # asset-enqueue->publish-eligible, and remains unmeasured here.
            original_sha = sha(raw)
            record.update(g1="PASS", png_sha256=original_sha,
                          original_png_path=str(png), canvas=size,
                          gpu_submit_to_png_seconds=round(time.monotonic()-t, 3),
                          publish_eligible=False,
                          asset_enqueue_to_publish_eligible_seconds=None)
            if is_sprite:
                import sdxl_sprite_factor as sprite
                try:
                    matte_evidence = sprite.derive_rgba_candidate(
                        root, p["id"], png, original_sha)
                except Exception as exc:
                    # Comfy history is known and the original PNG was decoded:
                    # terminal *postprocessing* failure, not an unknown GPU
                    # submission. Preserve original for independent review,
                    # never retry or publish. Review-pending stays fenced.
                    record.update(
                        # lab_exclusive.py has a strict terminal status
                        # allowlist. An attributed completed GPU original
                        # remains review-required even if optional matte
                        # extraction was unsafe; do NOT return a novel status
                        # that would strand the stopped dev submitters.
                        status="GPU_FINISHED_REVIEW_REQUIRED",
                        postprocess_status="BLOCKED_UNSAFE",
                        alpha_status="POSTPROCESS_BLOCKED",
                        postprocess_error_type=type(exc).__name__,
                        g2="NOT_REVIEWED", published=False,
                        completed_utc=datetime.now(timezone.utc).isoformat())
                    atomic(work / "result.json", record)
                    (root / "running" / path.name).replace(
                        root / "review_pending" / path.name)
                    return {"status": record["status"], "id": p["id"],
                            "postprocess_status": record["postprocess_status"],
                            "prompt_id": pid, "png_sha256": original_sha,
                            "submit_to_png_seconds": record["gpu_submit_to_png_seconds"]}
                record.update(matte_evidence)
            record.update(status="GPU_FINISHED_REVIEW_REQUIRED",
                          completed_utc=datetime.now(timezone.utc).isoformat())
            atomic(work / "result.json", record)
            (root / "running" / path.name).replace(root / "review_pending" / path.name)
            return {"status": record["status"], "id": p["id"],
                    "prompt_id": pid, "png_sha256": record["png_sha256"],
                    "submit_to_png_seconds": record["gpu_submit_to_png_seconds"]}
        except BaseException as exc:
            record["status"] = "STOP_UNKNOWN_OR_FAILED_NO_RETRY"
            record["error_type"] = type(exc).__name__
            # Keep original in running: an unknown externally submitted job
            # must never be automatically re-executed or silently released.
            atomic(work / "result.json", record)
            raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["queue", "tick"])
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--plan", type=Path)
    args = ap.parse_args()
    if args.action == "queue":
        if not args.plan:
            ap.error("--plan required")
        out = queue(args.root, json.loads(args.plan.read_text()))
    else:
        out = tick(args.root)
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
