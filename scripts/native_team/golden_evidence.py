#!/usr/bin/env python3
"""#76: Golden original-pixel evidence is NOT a source code change.

An immutable task specification binds a disposable visual review to existing
GPU provenance, exact original bytes, a typed Scene Contract, canonical
reference and unchanged source save. Only an independent reviewer can
approve the receipt. This module never submits a GPU job or publishes assets.

The G2 label is a *claim verified procedurally* by an independent human/agent
viewing original pixels; hashes cannot independently prove semantic quality.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import time
import uuid

import coordinator as c

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOT = Path.home() / ".local/share"
SPEC_SCHEMA = "golden_evidence_v1"
RECEIPT_SCHEMA = "golden_visual_receipt_v1"
KIND = "visual_evidence"
ARTIFACTS = ("original_png", "scene_contract", "canonical_ref",
             "source_save", "gpu_receipt")
SHA = re.compile(r"^[a-f0-9]{64}$")
G_TASK = re.compile(r"^G-[0-9]{1,4}$")
CHECKS = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
VERDICTS = frozenset(("verified", "violated", "unobservable"))
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def ensure_schema(db):
    """Additive schema; existing source-only task rows remain unchanged."""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS visual_task(
        task_id TEXT PRIMARY KEY REFERENCES task(id),
        spec_sha256 TEXT NOT NULL,
        spec_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS visual_review(
        task_id TEXT PRIMARY KEY REFERENCES task(id),
        reviewer TEXT NOT NULL,
        approved INTEGER NOT NULL,
        g2 TEXT NOT NULL,
        png_sha256 TEXT NOT NULL,
        note_sha256 TEXT NOT NULL,
        note TEXT NOT NULL,
        reviewed_at REAL NOT NULL
    );
    """)


def _name(value):
    if not isinstance(value, str) or not 3 <= len(value) <= 100 or not value.strip():
        raise ValueError("invalid owner/reviewer name")
    return value


def _hex(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("invalid sha256")
    return value


def _private_file(desc, kind):
    if not isinstance(desc, dict) or set(desc) != {"path", "sha256"}:
        raise ValueError("incomplete private artifact descriptor")
    wanted = _hex(desc["sha256"])
    if not isinstance(desc["path"], str) or "\x00" in desc["path"]:
        raise ValueError("invalid private artifact path")
    p = Path(desc["path"])
    root = PRIVATE_ROOT.expanduser().resolve()
    if not p.is_absolute():
        raise ValueError("private artifact path must be absolute")
    try:
        relative = p.relative_to(root)
    except ValueError as exc:
        raise ValueError("private artifact outside trusted root") from exc
    if not relative.parts or any(part in (".", "..") for part in relative.parts):
        raise ValueError("invalid private artifact traversal")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("symlink private artifact forbidden")
    try:
        file = p.resolve(strict=True)
        st = file.stat()
    except (OSError, RuntimeError) as exc:
        raise ValueError("original private artifact missing") from exc
    if not file.is_relative_to(root) or not stat.S_ISREG(st.st_mode):
        raise ValueError("not a regular private artifact")
    maximum = 64 * 1024 * 1024 if kind in ("original_png", "canonical_ref") else 2 * 1024 * 1024
    if st.st_size <= 0 or st.st_size > maximum:
        raise ValueError("unsafe private artifact size")
    raw = file.read_bytes()
    if len(raw) != st.st_size or digest(raw) != wanted:
        raise ValueError("original private artifact sha256 mismatch")
    if kind == "original_png":
        if len(raw) < 24 or not raw.startswith(PNG_MAGIC) or raw[12:16] != b"IHDR":
            raise ValueError("original image is not a PNG")
    return raw


def _spec(spec):
    if not isinstance(spec, dict) or set(spec) != {
        "schema", "task_id", "goal", "generator_owner", "case_id",
        "prompt_id", "priority", "dependencies", "artifacts"
    }:
        raise ValueError("invalid Golden visual task schema")
    if spec["schema"] != SPEC_SCHEMA or not isinstance(spec["task_id"], str) or (
        not G_TASK.fullmatch(spec["task_id"])
    ):
        raise ValueError("visual tasks restricted to G-n")
    if not isinstance(spec["goal"], str) or not 20 <= len(spec["goal"]) <= 500:
        raise ValueError("missing visual task goal")
    _name(spec["generator_owner"])
    if not isinstance(spec["case_id"], str) or not 2 <= len(spec["case_id"]) <= 100:
        raise ValueError("invalid case ID")
    try:
        if str(uuid.UUID(spec["prompt_id"])) != spec["prompt_id"]:
            raise ValueError("non-canonical prompt ID")
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("invalid original GPU prompt ID") from exc
    if type(spec["priority"]) is not int or not 1 <= spec["priority"] <= 500:
        raise ValueError("invalid visual task priority")
    deps = spec["dependencies"]
    if not isinstance(deps, list) or len(deps) > 12 or (
        any(not isinstance(x, str) or not x or x == spec["task_id"] for x in deps)
        or len(set(deps)) != len(deps)
    ):
        raise ValueError("invalid dependencies")
    if not isinstance(spec["artifacts"], dict) or set(spec["artifacts"]) != set(ARTIFACTS):
        raise ValueError("all five original artifacts are mandatory")
    return spec


def _verified_spec(spec):
    _spec(spec)
    artifacts = {key: _private_file(spec["artifacts"][key], key) for key in ARTIFACTS}
    try:
        contract = json.loads(artifacts["scene_contract"])
        source = json.loads(artifacts["gpu_receipt"])
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid source contract or GPU provenance JSON") from exc
    mandatory = contract.get("mandatory_checks") if isinstance(contract, dict) else None
    if not isinstance(contract, dict) or contract.get("schema") != "typed_scene_v1" or (
        not isinstance(mandatory, list) or not mandatory
        or len(mandatory) != len(set(mandatory))
        or any(not isinstance(k, str) or not CHECKS.fullmatch(k) for k in mandatory)
    ):
        raise ValueError("original typed Scene Contract has no valid mandatory checks")
    if contract.get("case_id") != spec["case_id"] or (
        contract.get("canonical_sha256") != spec["artifacts"]["canonical_ref"]["sha256"]
        or contract.get("source_save_sha256") != spec["artifacts"]["source_save"]["sha256"]
    ):
        raise ValueError("Scene Contract not bound to exact canonical reference and save")
    if not isinstance(source, dict) or source.get("status") != "GPU_FINISHED_REVIEW_REQUIRED":
        raise ValueError("no confirmed original GPU receipt")
    if source.get("prompt_id") != spec["prompt_id"] or source.get("case") != spec["case_id"] or (
        source.get("png_sha256") != spec["artifacts"]["original_png"]["sha256"]
        or source.get("original_png_path") != spec["artifacts"]["original_png"]["path"]
    ):
        raise ValueError("GPU receipt prompt/output provenance mismatch")
    return mandatory


def _task(db, task_id):
    row = db.execute(
        "SELECT t.*,v.spec_sha256,v.spec_json FROM task t JOIN visual_task v "
        "ON v.task_id=t.id WHERE t.id=?", (task_id,)
    ).fetchone()
    if row is None or row["action"] != KIND:
        raise ValueError("not an evidence-only Golden task")
    if digest(row["spec_json"].encode("utf-8")) != row["spec_sha256"]:
        raise ValueError("visual task source specification tampered")
    spec = json.loads(row["spec_json"])
    if spec.get("task_id") != task_id:
        raise ValueError("visual task mismatch")
    return row, spec


def enqueue(db, spec):
    """Chief enqueues only a genuine, immutable pre-existing candidate."""
    ensure_schema(db)
    _verified_spec(spec)
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT 1 FROM task WHERE id=?", (spec["task_id"],)).fetchone():
            raise ValueError("visual task ID replay forbidden")
        for previous in db.execute("SELECT spec_json FROM visual_task"):
            old = json.loads(previous["spec_json"])
            if old["prompt_id"] == spec["prompt_id"] or (
                old["artifacts"]["original_png"]["sha256"] ==
                spec["artifacts"]["original_png"]["sha256"]
            ):
                raise ValueError("visual GPU output/prompt replay forbidden")
        for dep in spec["dependencies"]:
            if db.execute("SELECT 1 FROM task WHERE id=?", (dep,)).fetchone() is None:
                raise ValueError("missing dependency")
        waiting = db.execute(
            "SELECT COUNT(*) FROM task WHERE id LIKE 'G-%' AND action=? AND state='pending'",
            (KIND,)
        ).fetchone()[0]
        if waiting >= 2:
            raise ValueError("Golden evidence queue full")
        c.add(db, spec["task_id"], KIND, [], spec["dependencies"],
              goal=spec["goal"], priority=spec["priority"])
        packed = canonical(spec).decode("utf-8")
        db.execute(
            "INSERT INTO visual_task(task_id,spec_sha256,spec_json) VALUES(?,?,?)",
            (spec["task_id"], digest(packed.encode("utf-8")), packed)
        )
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    return {"enqueued": spec["task_id"], "action": KIND, "source_changed_paths": []}


def _receipt_file(path):
    f = Path(path)
    if f.is_symlink():
        raise ValueError("symlink evidence is forbidden")
    allowed = (ROOT / "evidence/golden").resolve()
    try:
        resolved = f.resolve(strict=True)
        s = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise ValueError("Golden receipt missing") from exc
    if not resolved.is_relative_to(allowed) or not stat.S_ISREG(s.st_mode) or (
        not 0 < s.st_size <= 16000
    ):
        raise ValueError("Golden receipt not a private bounded file")
    if stat.S_IMODE(s.st_mode) & 0o077:
        raise ValueError("Golden receipt must be owner-private (0600)")
    raw = resolved.read_bytes()
    return raw, resolved


def _validated_receipt(receipt, spec, owner, fence, mandatory):
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema", "task_id", "owner", "fence", "generator_owner",
        "prompt_id", "original_png_sha256", "scene_contract_sha256",
        "canonical_sha256", "source_save_sha256", "gpu_receipt_sha256",
        "original_pixels_reviewed", "mandatory", "requested_g2", "observations"
    }:
        raise ValueError("invalid Golden receipt schema")
    if receipt["schema"] != RECEIPT_SCHEMA or receipt["task_id"] != spec["task_id"] or (
        receipt["owner"] != owner or receipt["fence"] != fence
        or receipt["generator_owner"] != spec["generator_owner"]
        or receipt["prompt_id"] != spec["prompt_id"]
    ):
        raise ValueError("Golden task/owner/fence/prompt mismatch")
    if owner == spec["generator_owner"]:
        raise ValueError("generator cannot review own candidate")
    for key, origin in (
        ("original_png_sha256", "original_png"),
        ("scene_contract_sha256", "scene_contract"),
        ("canonical_sha256", "canonical_ref"),
        ("source_save_sha256", "source_save"),
        ("gpu_receipt_sha256", "gpu_receipt")
    ):
        if receipt[key] != spec["artifacts"][origin]["sha256"]:
            raise ValueError("Golden receipt artifact sha256 mismatch")
    if receipt["original_pixels_reviewed"] is not True:
        raise ValueError("original full-resolution pixels not reviewed")
    checks = receipt["mandatory"]
    if not isinstance(checks, dict) or set(checks) != set(mandatory):
        raise ValueError("missing or surplus original mandatory checks")
    verdicts = []
    for name, check in checks.items():
        if not isinstance(check, dict) or set(check) != {"verdict", "observation"} or (
            check["verdict"] not in VERDICTS
        ) or not isinstance(check["observation"], str) or len(check["observation"].strip()) < 16:
            raise ValueError("missing actual pixel observation or invalid verdict")
        verdicts.append(check["verdict"])
    if not isinstance(receipt["observations"], str) or (
        len(receipt["observations"].strip()) < 35
    ):
        raise ValueError("missing human-readable original pixel notes")
    label = "FAIL" if "violated" in verdicts else (
        "UNVERIFIED" if "unobservable" in verdicts else "PASS"
    )
    if receipt["requested_g2"] != label:
        raise ValueError("G2 requested PASS conflicts with mandatory visual verdicts")
    return label


def submit(db, task_id, owner, fence, evidence):
    """Golden submits read-only original-pixel evidence without a Git diff."""
    _name(owner)
    if not isinstance(fence, str) or not fence:
        raise ValueError("invalid task fence")
    row, spec = _task(db, task_id)
    if row["state"] != "leased" or row["owner"] != owner or (
        row["fence"] != fence or row["lease_until"] <= time.time()
    ):
        raise ValueError("Golden submit requires current fenced lease")
    mandatory = _verified_spec(spec)
    raw, path = _receipt_file(evidence)
    try:
        receipt = json.loads(raw)
    except ValueError as exc:
        raise ValueError("invalid Golden receipt JSON") from exc
    label = _validated_receipt(receipt, spec, owner, fence, mandatory)
    # The worker-supplied file is not immutable. Take an exclusive, fenced,
    # 0600 content-addressed private snapshot before completing the lease.
    immutable_dir = ROOT / "evidence/golden/immutable"
    immutable_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    immutable = c.persist_evidence(immutable_dir, task_id, fence, raw)
    record = {
        "status": "visual-evidence-only", "lane": "G", "task_id": task_id,
        "spec_sha256": row["spec_sha256"], "sha256": digest(raw),
        "path": str(immutable.relative_to(ROOT.resolve())),
        "submitted_by": owner, "generator_owner": spec["generator_owner"],
        "prompt_id": spec["prompt_id"],
        "png_sha256": spec["artifacts"]["original_png"]["sha256"],
        "g2": label, "g3": "NO_GO"
    }
    accepted = c.complete(db, task_id, owner, fence, record, passed=True)
    if not accepted:
        raise ValueError("Golden lease changed while submitting")
    return {"accepted": True, "task": task_id, "g2": label,
            "status": "REVIEW_PENDING", "source_changed_paths": []}


def review(db, task_id, reviewer, approve, note, verified_png_sha=None):
    """Independent chief rehashes original artifacts and receipt before CAS."""
    _name(reviewer)
    if not isinstance(note, str) or not 20 <= len(note.strip()) <= 1500:
        raise ValueError("independent visual review note required")
    row, spec = _task(db, task_id)
    if row["state"] != "review_pending":
        return {"approved": False, "reason": "not pending"}
    record = json.loads(row["result"])
    if reviewer in (record.get("submitted_by"), spec["generator_owner"]):
        raise ValueError("independent reviewer cannot self-approve")
    if record.get("status") != "visual-evidence-only" or record.get("task_id") != task_id or (
        record.get("spec_sha256") != row["spec_sha256"]
    ):
        raise ValueError("invalid visual receipt provenance")
    if approve:
        if verified_png_sha != record["png_sha256"]:
            raise ValueError("independent reviewer must acknowledge exact original PNG SHA")
        mandatory = _verified_spec(spec)
        evidence = (ROOT / record["path"]).resolve()
        raw, _ = _receipt_file(evidence)
        if digest(raw) != record["sha256"]:
            raise ValueError("Golden receipt mutated since fenced submission")
        receipt = json.loads(raw)
        label = _validated_receipt(receipt, spec, record["submitted_by"],
                                   receipt["fence"], mandatory)
        if label != record["g2"] or record["png_sha256"] != (
            spec["artifacts"]["original_png"]["sha256"]
        ):
            raise ValueError("visual verdict changed after submission")
    else:
        label = record.get("g2", "UNVERIFIED")
    db.execute("BEGIN IMMEDIATE")
    try:
        current = db.execute(
            "SELECT state,result FROM task WHERE id=?", (task_id,)
        ).fetchone()
        if current is None or current["state"] != "review_pending" or (
            current["result"] != row["result"]
        ):
            db.execute("ROLLBACK")
            return {"approved": False, "reason": "review CAS changed"}
        db.execute(
            "INSERT INTO visual_review(task_id,reviewer,approved,g2,png_sha256,note_sha256,note,reviewed_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (task_id, reviewer, int(bool(approve)), label, record["png_sha256"],
             digest(note.encode("utf-8")), note, time.time())
        )
        changed = db.execute(
            "UPDATE task SET state=? WHERE id=? AND state='review_pending'",
            ("done" if approve else "blocked", task_id)
        )
        if changed.rowcount != 1:
            raise ValueError("review CAS lost")
        c.emit(db, task_id, "visual_receipt_reviewed" if approve else "visual_receipt_blocked",
               "g2=" + label + "; reviewer=" + reviewer[:45])
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    return {"approved": bool(approve), "task": task_id,
            "g2": label if approve else "UNVERIFIED",
            "reviewer": reviewer, "source_changed_paths": []}
