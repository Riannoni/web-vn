#!/usr/bin/env python3
"""Offline, descriptive QA-attempt latency audit for private web-vn job JSON.

Never prints job IDs, prompts, story, paths, QA text or asset bytes. Results
are source-reported only: editable job files do not authenticate producers,
G1/G2, GPU time, all mandatory QA or a publish-eligible/browser endpoint.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import stat
from collections import Counter
from pathlib import Path
import sys

COMPLETED = frozenset(("done", "failed", "superseded"))
MISSING_AUTHENTICATED = (
    "queue_wait", "preflight", "gpu_only", "postprocess",
    "all_mandatory_qa", "publish_eligible", "narrator", "browser_visible",
    "full_browser_turn",
)


class AuditError(ValueError):
    pass


def milliseconds(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuditError(label + "_missing_or_nonnumeric")
    if not math.isfinite(value) or value < 0:
        raise AuditError(label + "_invalid_duration")
    return float(value)


def finite_seconds(value, label: str) -> float:
    return 1000.0 * milliseconds(value, label)


def percentiles(values: list[float]) -> dict:
    values = sorted(values)
    if not values:
        return {"n": 0, "p50_ms": None, "p90_ms": None}
    def p(frac: float) -> float:
        position = (len(values)-1)*frac
        low, high = math.floor(position), math.ceil(position)
        return round(values[low] + (values[high]-values[low])*(position-low), 3)
    return {"n": len(values), "p50_ms": p(0.5), "p90_ms": p(0.9)}


def checked_timestamp(value: object, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise AuditError(label + "_missing_or_invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditError(label + "_missing_or_invalid") from exc
    if parsed.utcoffset() is None:
        raise AuditError(label + "_missing_or_invalid")
    return parsed


def summarize_job(job: object) -> dict:
    if not isinstance(job, dict):
        raise AuditError("job_not_object")
    job_id = job.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise AuditError("job_identity_missing")
    status = job.get("status")
    if not isinstance(status, str) or status not in COMPLETED:
        raise AuditError("nonterminal_job")
    attempts = job.get("attempt_history")
    if not isinstance(attempts, list) or not attempts:
        raise AuditError("attempt_history_missing")
    values = []
    prior_finished = None
    for index, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict) or type(attempt.get("number")) is not int or attempt["number"] != index:
            raise AuditError("attempt_number_not_contiguous")
        claimed = checked_timestamp(attempt.get("claimed_at"), "attempt_claimed_at")
        finished = checked_timestamp(attempt.get("finished_at"), "attempt_finished_at")
        if finished < claimed or (prior_finished is not None and claimed < prior_finished):
            raise AuditError("attempt_timestamp_order_invalid")
        prior_finished = finished
        outcome = attempt.get("outcome")
        if not isinstance(outcome, str) or outcome not in (
            "done", "failed", "superseded", "timed_out", "rejected", "retry"
        ):
            raise AuditError("attempt_outcome_nonterminal")
        if index < len(attempts) and outcome not in ("rejected", "retry", "timed_out"):
            raise AuditError("prior_attempt_not_retryable")
        if index == len(attempts):
            expected = {
                "done": frozenset(("done",)),
                "failed": frozenset(("failed", "timed_out")),
                "superseded": frozenset(("superseded", "timed_out")),
            }[status]
            if outcome not in expected:
                raise AuditError("terminal_attempt_outcome_mismatch")
        times = attempt.get("timings")
        if not isinstance(times, dict):
            raise AuditError("attempt_timings_missing")
        values.append(milliseconds(times.get("qa_ms"), "attempt_qa_ms"))
    recorded_attempts = job.get("attempts")
    if recorded_attempts is not None and (
        type(recorded_attempts) is not int or recorded_attempts != len(attempts)
    ):
        raise AuditError("attempt_count_inconsistent")
    if not isinstance(job.get("timings"), dict):
        raise AuditError("job_timings_missing")
    cumulative = milliseconds(job["timings"].get("qa_ms"), "job_qa_ms")
    if abs(sum(values) - cumulative) > 1.0:
        raise AuditError("attempt_job_qa_inconsistent")
    previous = sum(values[:-1])
    vision = None
    qa = job.get("qa")
    if isinstance(qa, dict) and isinstance(qa.get("metrics"), dict):
        raw = qa["metrics"].get("vlm_seconds")
        if raw is not None:
            vision = finite_seconds(raw, "latest_vlm_seconds")
    residual = None
    if vision is not None:
        if vision > values[-1] + 1:
            raise AuditError("latest_vlm_exceeds_latest_qa")
        residual = max(0.0, values[-1]-vision)
    return {"id": job_id, "attempts": len(values), "cumulative_qa_ms": cumulative,
            "previous_qa_ms": previous, "latest_qa_ms": values[-1],
            "latest_result_vlm_ms": vision, "latest_qa_minus_latest_vlm_ms": residual}


def audit_directory(directory: Path, as_of: dt.datetime, lookback_hours: float) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise AuditError("jobs_directory_unavailable")
    if as_of.utcoffset() is None:
        raise AuditError("as_of_timezone_required")
    if not math.isfinite(lookback_hours) or not 0 < lookback_hours <= 720:
        raise AuditError("lookback_hours_out_of_bounds")
    end = as_of.timestamp()
    start = end - lookback_hours*3600
    hashes, candidates, reasons = [], [], {}
    for f in sorted(directory.glob("*.json")):
        # Never follow candidate symlinks, including ones outside the mtime window.
        if f.is_symlink():
            raise AuditError("job_symlink_unsupported")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(f, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise AuditError("job_not_regular")
            if not start <= info.st_mtime <= end:
                continue
            with os.fdopen(fd, "rb") as source:
                fd = -1
                content = source.read()
        finally:
            if fd >= 0:
                os.close(fd)
        hashes.append(hashlib.sha256(content).hexdigest())
        try:
            job = json.loads(content)
            identifier = job.get("id") if isinstance(job, dict) else None
            identifier = identifier if isinstance(identifier, str) and identifier else None
            row = summarize_job(job)
            candidates.append((identifier, row, None))
        except AuditError as exc:
            candidates.append((identifier if "identifier" in locals() else None, None, str(exc)))
        except (ValueError, UnicodeDecodeError):
            candidates.append((None, None, "invalid_json"))
        finally:
            # A failed JSON decode must not inherit an ID from the previous file.
            if "identifier" in locals():
                del identifier
    counts = Counter(identifier for identifier, _, _ in candidates if identifier is not None)
    rows = []
    for identifier, row, error in candidates:
        if identifier is not None and counts[identifier] > 1:
            reason = "ambiguous_duplicate_job_identity"
        else:
            reason = error
        if reason is None:
            rows.append(row)
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
    cumulative = sum(row["cumulative_qa_ms"] for row in rows)
    previous = sum(row["previous_qa_ms"] for row in rows)
    stats = {key: percentiles([row[key] for row in rows if row[key] is not None])
             for key in ("cumulative_qa_ms", "previous_qa_ms", "latest_qa_ms",
                         "latest_result_vlm_ms", "latest_qa_minus_latest_vlm_ms")}
    return {
        "schema": "web-vn-descriptive-qa-attempt-cohort-v1",
        "source": "private_editable_job_files_UNAUTHENTICATED",
        "as_of_utc": as_of.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "lookback_hours": lookback_hours,
        "sample_selection": "file_mtime_window_including_failed_and_superseded",
        "raw_file_count": len(hashes), "valid_job_count": len(rows),
        "excluded_job_count": len(hashes)-len(rows), "excluded_by_reason": dict(sorted(reasons.items())),
        "raw_file_sha256_manifest": hashlib.sha256("\n".join(sorted(hashes)).encode()).hexdigest(),
        "attempt_count": sum(r["attempts"] for r in rows),
        "retried_job_count": sum(r["attempts"] > 1 for r in rows),
        "qa_totals_ms": {"all_attempts": round(cumulative, 3),
                         "previous_attempts": round(previous, 3),
                         "previous_attempt_share_pct": round(100*previous/cumulative, 3) if cumulative else None},
        "source_reported_percentiles": stats,
        "qa_vlm_pairing": "LAST_RESULT_INFERRED_NOT_ATTEMPT_AUTHENTICATED",
        "authenticated_stages": {name: {"status": "NOT_MEASURED", "n": 0} for name in MISSING_AUTHENTICATED},
        "publish_eligible_20s": {"status": "NOT_MEASURED", "n": 0, "passed": None},
        "g2": "NOT_ASSESSED", "human_labels": 0,
        "limitations": [
            "Raw job JSON and file mtime can be edited; manifest SHA only fixes this audit's input bytes.",
            "Each earlier QA attempt counts in job-level QA, but per-attempt VLM histories are absent.",
            "Latest QA and latest result's VLM are descriptive pairing candidates, not signed attempt receipts.",
            "The QA minus VLM residual cannot be assigned to lock, geometry, network or loading.",
            "No GPU-only, preflight, all-mandatory-QA, publish eligibility, narrator or browser clock spans are attested.",
            "Failed and unobservable mandatory results have no successful publish-eligible endpoint.",
        ],
    }


def parse_utc(value: str) -> dt.datetime:
    try:
        time = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditError("invalid_as_of") from exc
    if time.utcoffset() is None:
        raise AuditError("as_of_timezone_required")
    return time


def main(argv=None) -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-dir", type=Path, required=True)
    ap.add_argument("--as-of", required=True, help="Explicit offset-aware ISO UTC audit cutoff")
    ap.add_argument("--lookback-hours", type=float, default=48.0)
    args=ap.parse_args(argv)
    try:
        result=audit_directory(args.jobs_dir,parse_utc(args.as_of),args.lookback_hours)
    except AuditError as exc:
        print("EVIDENCE_BLOCKED: "+str(exc),file=sys.stderr)
        return 2
    except OSError:
        print("EVIDENCE_BLOCKED: filesystem_access_error",file=sys.stderr)
        return 2
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
