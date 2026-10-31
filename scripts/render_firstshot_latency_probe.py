#!/usr/bin/env python3
"""Read-only, fail-closed join of first-shot and live render timing evidence.

This does not submit GPU work, call APIs, infer missing stages, or certify G2/G3.
Production worker 'generation_ms' is Comfy roundtrip (possibly queue wait),
not independently measured GPU execution. QA is not necessarily CPU VLM time.

Input --events is private JSONL of exact worker/stage receipts:
  {"kind":"worker_timings","job_id":"...","prompt_id":"...",
   "timings":{"prepare_ms":120,"generation_ms":23000,"qa_ms":70000,
              "postprocess_ms":310}}
  {"kind":"stage","job_id":"...","prompt_id":"...","stage":"cpu_vlm",
   "started_at":"2026-10-31T10:00:00Z","completed_at":"..."}
  {"kind":"full_turn","job_id":"...","started_at":"...","completed_at":"..."}
Only explicit stage receipts with two timestamps count as stage wall time.
No server logs are synthesized; no full-turn metric from adding components.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
import sys

STAGES = (
    "queue_wait", "preflight", "graph_prepare", "comfy_roundtrip", "gpu",
    "submit_to_png", "postprocess", "cpu_vlm", "qa", "retry", "publish", "full_turn",
)
WORKER_MAP = {
    "prepare_ms": "graph_prepare",
    "generation_ms": "comfy_roundtrip",
    "postprocess_ms": "postprocess",
    "qa_ms": "qa",
}
LAB_STAGES = set(STAGES)


class EvidenceError(ValueError):
    """Missing, ambiguous or contradictory timing/provenance evidence."""


def _finite_nonnegative(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(f"{field}: numeric measurement required")
    if not math.isfinite(value) or value < 0:
        raise EvidenceError(f"{field}: non-finite or negative duration")
    return round(float(value), 6)


def _timestamp(value, field):
    if not isinstance(value, str):
        raise EvidenceError(f"{field}: timestamp required")
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{field}: invalid timestamp") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise EvidenceError(f"{field}: timezone required")
    return t


def _duration(start, end, name):
    a = _timestamp(start, name + ".started_at")
    b = _timestamp(end, name + ".completed_at")
    return _finite_nonnegative((b - a).total_seconds(), name)


def _sha(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(
        c not in "0123456789abcdef" for c in value
    ):
        raise EvidenceError(f"{field}: SHA256 hex required")
    return value


def _new_row(case=None, prompt_id=None, job_id=None, png_sha256=None):
    return {
        "case": case, "prompt_id": prompt_id, "job_id": job_id,
        "png_sha256": png_sha256, "g1": None, "g2": "NOT_REVIEWED",
        "human_label": False, "original_png_sha_verified": None,
        "stages_s": {s: None for s in STAGES},
        "evidence": [],
    }


def _put(row, stage, seconds, source):
    if stage not in STAGES:
        raise EvidenceError(f"unsupported stage: {stage}")
    val = _finite_nonnegative(seconds, stage)
    prior = row["stages_s"][stage]
    if prior is not None and abs(prior - val) > 0.000001:
        raise EvidenceError(f"conflicting {stage} receipts for same job/prompt")
    row["stages_s"][stage] = val
    if source not in row["evidence"]:
        row["evidence"].append(source)


def _lab_rows(lab_dir, verify_png):
    rows, by_prompt = [], {}
    if lab_dir is None:
        return rows, by_prompt
    lab_dir = Path(lab_dir)
    if not lab_dir.is_dir():
        raise EvidenceError("lab directory unavailable")
    for path in sorted(lab_dir.glob("*-result.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        case = d.get("case")
        prompt = d.get("prompt_id")
        if not isinstance(case, str) or not case or not isinstance(prompt, str) or not prompt:
            raise EvidenceError("lab case and prompt_id required")
        if prompt in by_prompt or any(r["case"] == case for r in rows):
            raise EvidenceError("duplicate lab case or prompt_id")
        sha = _sha(d.get("png_sha256"), "lab.png_sha256")
        row = _new_row(case=case, prompt_id=prompt, png_sha256=sha)
        row["g1"] = d.get("g1")
        row["first_attempt"] = (d.get("first_attempt") is True or (type(d.get("first_attempt")) is int and d["first_attempt"] == 1))
        if row["g1"] != "PASS" or not row["first_attempt"]:
            raise EvidenceError("lab G1/first_attempt provenance missing")
        if verify_png:
            original = d.get("original_png_path")
            if not isinstance(original, str) or not original:
                raise EvidenceError("original PNG path missing")
            image = Path(original)
            if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != sha:
                raise EvidenceError("original PNG bytes do not match exact SHA")
            row["original_png_sha_verified"] = True
        measured = _finite_nonnegative(d.get("total_submit_to_output_seconds"), "submit_to_png")
        clock = _duration(d.get("started_at"), d.get("completed_at"), "lab")
        if abs(measured - clock) > 0.25:
            raise EvidenceError("lab wall clock contradicts submit_to_png receipt")
        _put(row, "submit_to_png", measured, "lab_result_wall_clock")
        if d.get("submit_seconds") is not None:
            row["submit_api_s"] = _finite_nonnegative(d["submit_seconds"], "submit_api_s")
        review_path = lab_dir / f"{case}-pixel-review.json"
        if review_path.exists():
            rev = json.loads(review_path.read_text(encoding="utf-8"))
            if (rev.get("case"), rev.get("prompt_id"), rev.get("png_sha256")) != (
                case, prompt, sha
            ):
                raise EvidenceError("review mismatches exact case/prompt/PNG SHA")
            mandatory, checks = rev.get("mandatory"), rev.get("checks")
            if not isinstance(mandatory, list) or not mandatory or not isinstance(checks, dict):
                raise EvidenceError("review missing mandatory checks")
            if len(mandatory) != len(set(mandatory)):
                raise EvidenceError("duplicate mandatory visual checks")
            valid = {"verified", "violated", "unobservable", "not_applicable"}
            if any(checks.get(k) not in valid for k in mandatory):
                raise EvidenceError("invalid or missing mandatory visual verdict")
            reviewed = rev.get("original_pixels_reviewed") is True
            reviewer_type = rev.get("reviewer_type")
            independent = (isinstance(reviewer_type, str)
                           and reviewer_type.startswith("independent_"))
            positive_claim = (reviewed and independent
                              and all(checks[k] == "verified" for k in mandatory))
            # A reviewed metadata JSON is NOT a verified original pixel receipt
            # when the optional synthetic-test-only --skip-png-hash flag was used.
            # Never let this pathway manufacture a G2 PASS or human label.
            row["g2"] = (
                ("PASS" if row["original_png_sha_verified"] is True
                 else "NOT_REVIEWED") if positive_claim else "FAIL"
            )
            row["human_label"] = (row["g2"] == "PASS"
                                  and rev.get("human_label") is True
                                  and isinstance(reviewer_type, str)
                                  and reviewer_type.startswith("independent_human"))
            row["mandatory_failed"] = [
                k for k in mandatory if checks[k] != "verified"
            ]
            row["evidence"].append(
                "sha_bound_pixel_review" if row["original_png_sha_verified"] is True
                else "unverified_review_metadata"
            )
        rows.append(row)
        by_prompt[prompt] = row
    if not rows:
        raise EvidenceError("lab directory contains no result receipts")
    return rows, by_prompt


def _join_events(events, by_prompt):
    live_by_job = {}
    prompt_owner = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise EvidenceError(f"event {index}: object required")
        kind = event.get("kind")
        job_id = event.get("job_id")
        prompt = event.get("prompt_id")
        if not isinstance(job_id, str) or not job_id:
            raise EvidenceError(f"event {index}: nonempty job_id required")
        if prompt is not None and (not isinstance(prompt, str) or not prompt):
            raise EvidenceError("invalid prompt_id")
        if prompt:
            previous = prompt_owner.setdefault(prompt, job_id)
            if previous != job_id:
                raise EvidenceError("same prompt_id attributed to multiple jobs")
        if prompt in by_prompt:
            row = by_prompt[prompt]
            if row["job_id"] is not None and row["job_id"] != job_id:
                raise EvidenceError("lab prompt mapped to multiple jobs")
            row["job_id"] = job_id
            if event.get("png_sha256") and event["png_sha256"] != row["png_sha256"]:
                raise EvidenceError("event PNG SHA differs from lab original")
        else:
            row = live_by_job.get(job_id)
            if row is None:
                row = _new_row(job_id=job_id, prompt_id=prompt)
                live_by_job[job_id] = row
            elif prompt and row["prompt_id"] not in (None, prompt):
                raise EvidenceError("live job has conflicting prompt_id")
            if prompt:
                row["prompt_id"] = prompt
            if event.get("png_sha256"):
                sha = _sha(event["png_sha256"], "event.png_sha256")
                if row["png_sha256"] not in (None, sha):
                    raise EvidenceError("conflicting live PNG SHA")
                row["png_sha256"] = sha
        if kind == "worker_timings":
            times = event.get("timings")
            if not isinstance(times, dict) or not times:
                raise EvidenceError("worker timings object required")
            for key, value in times.items():
                if key in WORKER_MAP:
                    _put(row, WORKER_MAP[key], _finite_nonnegative(value, key) / 1000,
                         "worker_reported_" + key)
            if not any(k in WORKER_MAP for k in times):
                raise EvidenceError("worker timings lack recognized measured stage")
        elif kind in ("stage", "full_turn"):
            stage = event.get("stage") if kind == "stage" else "full_turn"
            if stage not in STAGES:
                raise EvidenceError("unsupported stage event")
            if "started_at" not in event or "completed_at" not in event:
                raise EvidenceError("stage needs explicit start and end timestamps")
            _put(row, stage, _duration(event["started_at"], event["completed_at"], stage),
                 "timestamped_" + kind)
        else:
            raise EvidenceError(f"unrecognized event kind: {kind}")
    return list(live_by_job.values())


def percentiles(values):
    values = sorted(_finite_nonnegative(x, "percentile_input") for x in values)
    if not values:
        return {"n": 0, "p50": None, "p90": None, "min": None, "max": None}
    def p(q):
        position = (len(values) - 1) * q
        low = math.floor(position)
        high = math.ceil(position)
        return round(values[low] + (values[high] - values[low]) * (position - low), 6)
    return {"n": len(values), "p50": p(.5), "p90": p(.9),
            "min": values[0], "max": values[-1]}


def _summarize(rows):
    return {s: percentiles([
        row["stages_s"][s] for row in rows if row["stages_s"][s] is not None
    ]) for s in STAGES}


def build_report(lab_dir, events, verify_png=True):
    lab, by_prompt = _lab_rows(lab_dir, verify_png)
    live = _join_events(events, by_prompt)
    all_rows = lab + live
    return {
        "schema": "web-vn-firstshot-latency-evidence-v1",
        "lab": lab, "live": live,
        "summary": _summarize(all_rows),
        "cohorts": {"lab": _summarize(lab), "live": _summarize(live)},
        "limitations": [
            "Unknown stages remain null and excluded from percentiles.",
            "Comfy roundtrip includes potential queue/poll overhead; not GPU execution.",
            "Worker QA duration is not independently CPU-VLM-only.",
            "No full-turn metric without explicit full-turn timestamps.",
            "Empty Comfy queue does not prove exclusive admission.",
            "No GPU two-way concurrency approval without monitored A/B.",
            "AI pixel reviews are not human labels; G3 remains NO_GO.",
            "External stage receipts require independent source authentication; this parser cannot certify their origin.",
        ],
        "g3": "NO_GO",
    }


def _load_events(path):
    if path is None:
        return []
    events = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"invalid JSONL at line {i}") from exc
    return events


def _load_worker_log(path):
    """Parse real worker PUBLISHED receipts; never expose raw private log text.

    These receipts lack prompt_id and do not prove PNG linkage, queue wait,
    GPU execution time or full-turn. A malformed PUBLISHED line is an error.
    """
    if path is None:
        return []
    events = []
    pattern = re.compile(
        r"^PUBLISHED ([A-Za-z0-9_-]{1,128}) applied (?:True|False|None) "
        r"quality [A-Za-z0-9_-]+ timings (\{.*\})$"
    )
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if "PUBLISHED " not in raw:
            continue
        line = "PUBLISHED " + raw.split("PUBLISHED ", 1)[1]
        match = pattern.fullmatch(line.strip())
        if not match:
            raise EvidenceError(f"worker PUBLISHED receipt malformed at line {number}")
        try:
            timings = ast.literal_eval(match.group(2))
        except (SyntaxError, ValueError, TypeError) as exc:
            raise EvidenceError(f"worker timings malformed at line {number}") from exc
        events.append({"kind": "worker_timings", "job_id": match.group(1),
                       "timings": timings})
    return events


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-dir", type=Path)
    parser.add_argument("--events", type=Path, help="Private normalized receipts, not raw prompts")
    parser.add_argument("--worker-log", type=Path, help="Private real worker PUBLISHED log")
    parser.add_argument("--output", type=Path, help="Private report; omit for stdout")
    parser.add_argument("--skip-png-hash", action="store_true",
                        help="Only for synthetic tests; not acceptable as original-pixel evidence")
    args = parser.parse_args(argv)
    if args.lab_dir is None and args.events is None and args.worker_log is None:
        print("EVIDENCE_BLOCKED: at least one real evidence source required", file=sys.stderr)
        return 2
    try:
        report = build_report(args.lab_dir, _load_events(args.events) + _load_worker_log(args.worker_log),
                              verify_png=not args.skip_png_hash)
    except (EvidenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"EVIDENCE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    result = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        if args.output.exists():
            print("EVIDENCE_BLOCKED: refusing overwrite", file=sys.stderr)
            return 2
        args.output.write_text(result, encoding="utf-8")
        args.output.chmod(0o600)
        print(json.dumps({"lab_count": len(report["lab"]), "live_count": len(report["live"]),
                          "submit_to_png": report["summary"]["submit_to_png"],
                          "full_turn": report["summary"]["full_turn"],
                          "output_written": True}))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
