#!/usr/bin/env python3
"""Atomic *advisory* cross-wake reservation for native ChatGPT Scheduled Tasks.

This NEVER calls OpenAI or a model. Each caller MUST first verify a genuinely
new exact source/PNG SHA, check official Automations.peek that the target is
enabled and not in_progress, and only then reserve + issue ONE official run_now.
The platform decides actual availability and rate limits. No Codex quota read.

Read-only inspection: --status [--target ROLE] [--limit 1..200]
  [--cursor NEXT_CURSOR]. Cursor fixes an initial rowid high-water; pages use a
  deterministic keyset, so earlier ACKs do not skip entries. New arrivals are
  intentionally excluded until a fresh --status call without --cursor.
  Status/selection does not acknowledge, dispatch or alter wake outcomes.

Dispatcher ingestion: save the actual single automation object returned by
official peek, then --record-run PRIVATE_JSON --target ROLE --requestor dispatcher.
Existing --status returns its latest run_observations, independently of delivery
and consumption. Reported blockers are clues for review, never retry authority.
"""
import argparse
import base64
import binascii
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

TARGETS = {
    "broker": "6ae5d49054d48191ba1a0c2f2ba55816",
    "broker_reviewer": "6ae5dcb9fb3c8191935b5ef13fab8f5b",
    "chief": "6ae57ba332a48191923e7f51ccfe7dd5",
    "integration": "6ae5dcbce2c481919e6cd302c223c279",
    "renderer": "6ae57b3727688191ab20279ff8fba0af",
    "golden": "6ae57b3d794c8191aff21eac865b780b",
    "golden_evidence": "6ae5dcacb7908191b72d98510a3db5b6",
    "pose": "6ae5dcafbf7c8191aaf823beed911ff2",
    "identity": "6ae5dcb38de4819193cccf1a9c5954d2",
    "provenance": "6ae5dd11d4748191adb005926b42c083",
    "reliability": "6ae57b40434c8191857969a577627d2f",
    "e2e": "6ae5dcb6f8c88191b2cc46a83f64d8da",
    "dispatcher": "6ae5e8ac2e58819188b5f87aa17d0f97",
    "decision": "6ae5e8a59f2c8191a29d40c1c12712f0",
    "gpu_lab": "6ae5e8a91cfc8191bb938957f214f8c3",
}
# Owner-authorized setup/review can emit a handoff without impersonating a
# Scheduled worker. It is never a wake target or a recipient acknowledgement.
REQUESTORS = set(TARGETS) | {"operator"}
KINDS = {"source_pr_ready", "review_accepted", "visual_candidate_ready",
         "blocker_cleared", "contract_verified", "integration_ready",
         "visual_review_completed", "operation_blocked"}
SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MIN_SECONDS_BETWEEN_TARGET_WAKES = 240
MAX_TARGET_WAKES_PER_HOUR = 3
# Keep the aggregate guard without starving roles below their own allowance.
MAX_GLOBAL_WAKES_PER_HOUR = MAX_TARGET_WAKES_PER_HOUR * len(TARGETS)
OUTCOMES = {"requested", "started", "completed", "not_dispatched", "unknown", "blocked"}
OBSERVERS = {"chief", "dispatcher", "decision"}


def _validate(target, kind, evidence_sha, requestor):
    if target not in TARGETS or requestor not in REQUESTORS:
        raise ValueError("unknown cloud role")
    if kind not in KINDS or not isinstance(evidence_sha, str) or not SHA.fullmatch(evidence_sha):
        raise ValueError("unverified event type or source hash")


@contextmanager
def _database(root):
    """Migrate old reservations conservatively; no timeout authorizes a retry."""
    root = Path(root).expanduser().resolve()
    state = root / "state"
    if not state.is_dir():
        raise FileNotFoundError("native team state missing")
    path = state / "scheduled-wake-history.sqlite3"
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        if path.is_file():
            os.chmod(path, 0o600)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS wake_signal ("
                   "target TEXT NOT NULL,event_kind TEXT NOT NULL,"
                   "evidence_sha TEXT NOT NULL,requestor TEXT NOT NULL,"
                   "requested_at REAL NOT NULL,"
                   "PRIMARY KEY(target,event_kind,evidence_sha))")
        db.execute("CREATE TABLE IF NOT EXISTS wake_attempt ("
                   "reservation_id TEXT PRIMARY KEY,target TEXT NOT NULL,event_kind TEXT NOT NULL,"
                   "evidence_sha TEXT NOT NULL,requestor TEXT NOT NULL,reserved_at REAL NOT NULL,"
                   "status TEXT NOT NULL,updated_at REAL NOT NULL,receipt_sha TEXT,run_id TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS pending_signal ("
                   "target TEXT NOT NULL,event_kind TEXT NOT NULL,evidence_sha TEXT NOT NULL,"
                   "requestor TEXT NOT NULL,created_at REAL NOT NULL,reason TEXT NOT NULL,"
                   "consumed_at REAL,receipt_sha TEXT,run_id TEXT,"
                   "PRIMARY KEY(target,event_kind,evidence_sha))")
        db.execute("CREATE TABLE IF NOT EXISTS wake_outcome ("
                   "id INTEGER PRIMARY KEY AUTOINCREMENT,reservation_id TEXT NOT NULL,"
                   "status TEXT NOT NULL,observed_by TEXT NOT NULL,observed_at REAL NOT NULL,"
                   "receipt_sha TEXT NOT NULL,run_id TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS run_observation ("
                   "target TEXT NOT NULL,run_id TEXT NOT NULL,started_at REAL NOT NULL,"
                   "observed_at REAL NOT NULL,summary TEXT NOT NULL,"
                   "PRIMARY KEY(target,run_id))")
        # Legacy rows prove only a reservation, not whether run_now was called.
        legacy = db.execute("SELECT s.* FROM wake_signal s WHERE NOT EXISTS ("
                            "SELECT 1 FROM wake_attempt a WHERE a.target=s.target AND "
                            "a.event_kind=s.event_kind AND a.evidence_sha=s.evidence_sha)").fetchall()
        for row in legacy:
            key = (row["target"], row["event_kind"], row["evidence_sha"])
            token = "legacy-" + hashlib.sha256("|".join(key).encode()).hexdigest()
            db.execute("INSERT INTO wake_attempt VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (token, *key, row["requestor"], row["requested_at"], "unknown",
                        row["requested_at"], None, None))
            _pending(db, key, row["requestor"], row["requested_at"], "legacy_request_unknown")
        db.execute("COMMIT")
        yield db
    finally:
        if db.in_transaction:
            db.execute("ROLLBACK")
        db.close()


def _pending(db, key, requestor, instant, reason):
    db.execute("INSERT OR IGNORE INTO pending_signal "
               "(target,event_kind,evidence_sha,requestor,created_at,reason) VALUES (?,?,?,?,?,?)",
               (*key, requestor, instant, reason))


def _latest(db, key):
    return db.execute("SELECT * FROM wake_attempt WHERE target=? AND event_kind=? AND evidence_sha=? "
                      "ORDER BY reserved_at DESC,rowid DESC LIMIT 1", key).fetchone()


def check(root, target, kind, evidence_sha, requestor, reserve=False, now=None):
    _validate(target, kind, evidence_sha, requestor)
    if requestor == target:
        return {"eligible": False, "reason": "self_wake_not_needed", "target": target}
    instant = time.time() if now is None else now
    key = (target, kind, evidence_sha)
    with _database(root) as db:
        if reserve:
            db.execute("BEGIN IMMEDIATE")
            # A rate/cooldown refusal postpones dispatch, not the real event.
            _pending(db, key, requestor, instant, "awaiting_event_consumption")
        pending = db.execute("SELECT consumed_at FROM pending_signal WHERE "
                             "target=? AND event_kind=? AND evidence_sha=?", key).fetchone()
        previous = _latest(db, key)
        if pending is not None and pending["consumed_at"] is not None:
            result = {"eligible": False, "reason": "already_consumed_exact_evidence"}
        elif previous is not None and previous["status"] != "not_dispatched":
            result = {"eligible": False, "reason": "already_requested_for_exact_evidence",
                      "delivery_status": previous["status"],
                      "reservation_id": previous["reservation_id"]}
        else:
            latest = db.execute("SELECT MAX(reserved_at) FROM wake_attempt WHERE target=?", (target,)).fetchone()[0]
            lane_count = db.execute(
                "SELECT COUNT(*) FROM wake_attempt WHERE target=? AND reserved_at>?",
                (target, instant-3600)).fetchone()[0]
            global_count = db.execute(
                "SELECT COUNT(*) FROM wake_attempt WHERE reserved_at>?",
                (instant-3600,)).fetchone()[0]
            if lane_count >= MAX_TARGET_WAKES_PER_HOUR:
                result = {"eligible":False, "reason":"per_target_hourly_budget"}
            elif global_count >= MAX_GLOBAL_WAKES_PER_HOUR:
                result = {"eligible":False, "reason":"global_hourly_budget"}
            elif latest is not None and instant-latest < MIN_SECONDS_BETWEEN_TARGET_WAKES:
                result = {"eligible":False,"reason":"target_wake_cooldown",
                          "retry_after_seconds":round(MIN_SECONDS_BETWEEN_TARGET_WAKES-(instant-latest))}
            else:
                result = {"eligible":True,"reason":"verified_event_requires_native_run_now"}
        result.update({"target":target,"automation_id":TARGETS[target],
                       "event_kind":kind,"evidence_sha":evidence_sha})
        if reserve and result["eligible"]:
            token = uuid.uuid4().hex
            db.execute("INSERT INTO wake_signal VALUES (?,?,?,?,?) ON CONFLICT(target,event_kind,evidence_sha) "
                       "DO UPDATE SET requestor=excluded.requestor,requested_at=excluded.requested_at",
                       (target,kind,evidence_sha,requestor,instant))
            db.execute("INSERT INTO wake_attempt VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (token, *key, requestor, instant, "reserved", instant, None, None))
            _pending(db, key, requestor, instant, "awaiting_event_consumption")
            result["reserved"] = True
            result["reservation_id"] = token
            result["delivery_status"] = "reserved"
            result["note"] = "Use official Automations.run_now. Reservation is not a launch."
        if reserve:
            db.execute("COMMIT")
        return result


def defer(root, target, kind, evidence_sha, requestor, reason="target_busy", now=None):
    """Keep a real event while its target is busy; never reserve a cloud call."""
    _validate(target, kind, evidence_sha, requestor)
    if requestor == target or not isinstance(reason, str) or not 3 <= len(reason) <= 200:
        raise ValueError("invalid deferred handoff")
    with _database(root) as db:
        _pending(db, (target, kind, evidence_sha), requestor,
                 time.time() if now is None else now, reason)
    return {"deferred": True, "target": target, "evidence_sha": evidence_sha,
            "note": "Pending consumption is not a request, start or visual approval."}


def _receipt(receipt_sha, run_id=None, require_run=False):
    if not isinstance(receipt_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt_sha):
        raise ValueError("exact receipt SHA256 required")
    if require_run and not run_id:
        raise ValueError("observed official run ID required")
    if run_id is not None:
        try:
            uuid.UUID(run_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid official run ID") from exc


def record_outcome(root, target, kind, evidence_sha, requestor, reservation_id,
                   outcome, receipt_sha, run_id=None, now=None):
    """Record tool evidence, not a model call. Denial/unknown NEVER unlock retries.

    Only the reserving role can attest it never invoked run_now. A timed-out,
    refused or accepted invocation cannot be reclassified as not_dispatched.
    Trusted control roles may reconcile positively observed platform run IDs.
    """
    _validate(target, kind, evidence_sha, requestor)
    if outcome not in OUTCOMES:
        raise ValueError("invalid delivery outcome")
    _receipt(receipt_sha, run_id, require_run=outcome in {"started", "completed"})
    transitions = {
        # A caller may have died after run_now but before recording requested.
        # Official positive evidence can reconcile that gap; elapsed time cannot.
        "reserved": {"requested", "started", "completed", "not_dispatched", "unknown", "blocked"},
        "requested": {"started", "completed", "unknown", "blocked"},
        "unknown": {"started", "completed", "blocked"},
        "started": {"completed", "unknown", "blocked"},
    }
    instant = time.time() if now is None else now
    with _database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = _latest(db, (target, kind, evidence_sha))
        if row is None or row["reservation_id"] != reservation_id:
            raise ValueError("stale or missing reservation token")
        if requestor != row["requestor"] and requestor not in OBSERVERS:
            raise ValueError("unrelated role cannot record delivery")
        if outcome == "not_dispatched" and requestor != row["requestor"]:
            raise ValueError("only the reserver can attest no call was made")
        if row["status"] == outcome and row["receipt_sha"] == receipt_sha and row["run_id"] == run_id:
            db.execute("COMMIT")
            return {"recorded": True, "status": outcome, "replayed": True}
        if outcome not in transitions.get(row["status"], set()):
            raise ValueError("unsafe delivery transition")
        if row["run_id"] and run_id != row["run_id"]:
            raise ValueError("official run ID cannot change")
        db.execute("UPDATE wake_attempt SET status=?,updated_at=?,receipt_sha=?,run_id=? "
                   "WHERE reservation_id=?", (outcome, instant, receipt_sha, run_id, reservation_id))
        db.execute("INSERT INTO wake_outcome(reservation_id,status,observed_by,observed_at,receipt_sha,run_id) "
                   "VALUES(?,?,?,?,?,?)", (reservation_id, outcome, requestor, instant, receipt_sha, run_id))
        db.execute("COMMIT")
    return {"recorded": True, "status": outcome, "reservation_id": reservation_id,
            "note": "Delivery state is separate from consuming evidence and passing G2."}


def acknowledge(root, target, kind, evidence_sha, requestor, receipt_sha, run_id, now=None):
    """The recipient records consuming exact evidence, including a negative result."""
    _validate(target, kind, evidence_sha, requestor)
    _receipt(receipt_sha, run_id, require_run=True)
    if requestor != target:
        raise ValueError("only the recipient can acknowledge consumption")
    key = (target, kind, evidence_sha)
    with _database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM pending_signal WHERE target=? AND event_kind=? AND evidence_sha=?", key).fetchone()
        if row is None:
            raise ValueError("missing pending event")
        if row["consumed_at"] is not None:
            if (row["receipt_sha"], row["run_id"]) != (receipt_sha, run_id):
                raise ValueError("consumption receipt is immutable")
        else:
            db.execute("UPDATE pending_signal SET consumed_at=?,receipt_sha=?,run_id=? "
                       "WHERE target=? AND event_kind=? AND evidence_sha=?",
                       (time.time() if now is None else now, receipt_sha, run_id, *key))
        db.execute("COMMIT")
    return {"acknowledged": True, "target": target, "evidence_sha": evidence_sha}


def _reported_blockers(text):
    """Conservative text signals, not proof of scope, permission or current health.

    Historical mentions need scoped review, not a stop on unrelated work. Absence
    of a match never proves success. Raw/private prose is not copied into status.
    """
    patterns = [
        ("safety_denial", r"\bPLATFORM_DENIAL\b|blocked by openai.s safety checks|safety[- ]denied|"
         r"(?:policy|approval|safety) denial|"
         r"(?:отказ|заблокирован)[^\n.]{0,100}(?:safety|безопасност)"),
        ("unknown_submission", r"(?:unknown|uncertain)[^\n.]{0,35}(?:gpu|submi|dispatch|run_now)|"
         r"(?:submission|run_now)[^\n.]{0,35}(?:unknown|uncertain)|"
         r"неизвестн[^\n.]{0,35}(?:отправ|gpu|run_now)"),
        ("authentication", r"permission denied \(publickey\)|authentication failed|"
         r"(?:expired|invalid) (?:connector )?(?:auth|credential)|"
         r"ошибк[^\n.]{0,30}аутентификац"),
        ("transport", r"connection (?:timed out|timeout|reset|refused)|"
         r"network is unreachable|could not resolve host|econnreset|etimedout|"
         r"таймаут (?:соединения|подключения)|сброс соединения"),
    ]
    found = [kind for kind, pattern in patterns if re.search(pattern, text, re.I)]
    if not found and re.search(
            r"\b(?:blocked|hold|permission denied)\b|заблокир|недоступн|"
            r"нового измерения[^\n.]{0,30}нет", text, re.I):
        found.append("other_blocker")
    return found


def record_run(root, target, requestor, observation, now=None):
    """Ingest official run/result evidence; NEVER mutate wake/ACK/job state.

    A completed cloud turn and two false platform flags do not establish a
    product result. Even a positive narrative needs independent artifact evidence.
    Text classification is advisory and cannot authorize replay or fallback.
    """
    if target not in TARGETS or requestor not in OBSERVERS | {target, "operator"}:
        raise ValueError("only the recipient, an existing observer or operator can record a run")
    if not isinstance(observation, dict) or observation.get("id") != TARGETS[target]:
        raise ValueError("automation identity does not match target")
    details = observation.get("run_details") or {}
    run = details.get("last_run") or {}
    result = details.get("latest_result")
    run_id, cloud = run.get("id"), run.get("recorded_status")
    receipt_sha = hashlib.sha256(json.dumps(
        observation, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    _receipt(receipt_sha, run_id, require_run=True)
    if cloud not in {"in_progress", "completed", "failed", "no_update"}:
        raise ValueError("observed official cloud status required")
    try:
        started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
        if started.tzinfo is None:
            raise ValueError("timezone missing")
        started_at = started.timestamp()
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("official timezone-aware started_at required") from exc
    matches = isinstance(result, dict) and result.get("run_id") == run_id
    result = result if matches else {}
    text = result.get("content_text")
    text = text if isinstance(text, str) else ""
    kinds = _reported_blockers(text) if matches else []
    if cloud == "failed" or result.get("is_failure_message") is True:
        kinds.append("platform_failure")
    if result.get("requires_user_action") is True:
        kinds.append("user_action_required")
    complete_text = bool(matches and text and result.get("content_truncated") is False)
    operation = ("blocker_reported" if kinds else
                 "no_blocker_reported" if complete_text else "not_observed")
    if "safety_denial" in kinds:
        action = "honor_denial_no_replay"
    elif "unknown_submission" in kinds:
        action = "reconcile_unknown_no_replay"
    elif "authentication" in kinds:
        action = "verify_authentication"
    elif kinds == ["transport"]:
        # Recheck health only; no original operation, wake or submit retry.
        action = "fresh_read_only_health_diagnostic"
    else:
        action = "inspect_reported_blocker" if kinds else "verify_product_evidence"
    diagnostic_plan = None
    if kinds == ["transport"] and complete_text:
        diagnostic_plan = {
            "operation": "read_only_health_check", "automatic": False,
            "max_retries": 3, "delays_seconds": [10, 30, 60],
            "scope": "current_transient_episode_within_current_run",
            "requires": ["fresh_transient_transport_failure", "available_timer"],
            "stop_on": ["health_restored", "any_non_transport_failure", "budget_exhausted"],
            "replay_original_operation": False,
        }
    summary = {
        "target": target, "run_id": run_id, "cloud_status": cloud,
        "started_at": run["started_at"], "result_matches_run": matches,
        "operation_state": operation, "blocker_kinds": kinds,
        "product_result": "unverified", "next_action": action,
        "diagnostic_retry_plan": diagnostic_plan,
        "is_failure_message": result.get("is_failure_message"),
        "requires_user_action": result.get("requires_user_action"),
        "content_truncated": result.get("content_truncated"),
        "receipt_sha": receipt_sha,
    }
    with _database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT summary FROM run_observation WHERE target=? AND run_id=?",
                              (target, run_id)).fetchone()
        if previous:
            old = json.loads(previous["summary"])
            if ((old["cloud_status"] != "in_progress" and cloud == "in_progress")
                    or (old["result_matches_run"] and not matches)
                    or (old["content_truncated"] is False
                        and summary["content_truncated"] is not False)):
                db.execute("COMMIT")
                return {"recorded": False, "reason": "stale_run_observation",
                        "observation": old, "automations_invoked": False,
                        "automatic_retry": False}
        db.execute("INSERT INTO run_observation VALUES (?,?,?,?,?) "
                   "ON CONFLICT(target,run_id) DO UPDATE SET "
                   "observed_at=excluded.observed_at,summary=excluded.summary",
                   (target, run_id, started_at, time.time() if now is None else now,
                    json.dumps(summary, sort_keys=True)))
        db.execute("COMMIT")
    return {"recorded": True, "observation": summary,
            "automations_invoked": False, "automatic_retry": False}


STATUS_MAX_PAGE = 200


def _status_cursor(payload):
    """Canonical opaque keyset position, not a cloud delivery authorization."""
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _parse_status_cursor(cursor, target, limit):
    if not isinstance(cursor, str) or not 8 <= len(cursor) <= 1024:
        raise ValueError("malformed status cursor")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4),
                               altchars=b"-_", validate=True)
        data = json.loads(raw)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError("malformed status cursor") from exc
    if not isinstance(data, dict) or set(data) != {
        "v", "target", "limit", "high_water", "after"
    } or _status_cursor(data) != cursor:
        raise ValueError("malformed status cursor")
    if (type(data["v"]) is not int or data["v"] != 1
        or data["target"] != target or type(data["limit"]) is not int
        or data["limit"] != limit):
        raise ValueError("incompatible status cursor filter or limit")
    high_water = data["high_water"]
    after = data["after"]
    if (type(high_water) is not int or not 0 <= high_water < 2**63
        or not isinstance(after, list) or len(after) != 4
        or type(after[0]) not in (int, float)
        or not math.isfinite(after[0]) or after[0] < 0
        or not isinstance(after[1], str) or after[1] not in TARGETS
        or not isinstance(after[2], str) or after[2] not in KINDS
        or not isinstance(after[3], str) or not SHA.fullmatch(after[3])):
        raise ValueError("malformed status cursor values")
    return high_water, after


def status(root, target=None, limit=STATUS_MAX_PAGE, cursor=None):
    """Read-only lifecycle inventory: target-filtered, stable keyset pages.

    Initial page freezes the maximum SQLite rowid. Later new arrivals are not
    included even when their created_at is backdated; restart without a cursor
    for a fresh scan. Consumption/ACK of an earlier page never shifts offsets.
    All existing no-filter response fields keep their original meaning.
    """
    if target is not None and target not in TARGETS:
        raise ValueError("unknown status target")
    if type(limit) is not int or not 1 <= limit <= STATUS_MAX_PAGE:
        raise ValueError("invalid status page size")
    decoded = _parse_status_cursor(cursor, target, limit) if cursor is not None else None
    with _database(root) as db:
        db.execute("BEGIN")
        try:
            global_total = db.execute(
                "SELECT COUNT(*) FROM pending_signal WHERE consumed_at IS NULL").fetchone()[0]
            if target is None:
                filtered_total = global_total
            else:
                filtered_total = db.execute(
                    "SELECT COUNT(*) FROM pending_signal "
                    "WHERE consumed_at IS NULL AND target=?", (target,)).fetchone()[0]
            high_water = decoded[0] if decoded else (
                db.execute("SELECT COALESCE(MAX(rowid),0) FROM pending_signal").fetchone()[0])
            conditions = ["consumed_at IS NULL", "rowid <= ?"]
            params = [high_water]
            if target is not None:
                conditions.append("target = ?")
                params.append(target)
            if decoded is not None:
                conditions.append("(created_at,target,event_kind,evidence_sha) > (?,?,?,?)")
                params.extend(decoded[1])
            rows = db.execute(
                "SELECT * FROM pending_signal WHERE " + " AND ".join(conditions) +
                " ORDER BY created_at,target,event_kind,evidence_sha LIMIT ?",
                (*params, limit+1)).fetchall()
            has_more = len(rows) > limit
            pending = [dict(row) for row in rows[:limit]]
            for event in pending:
                attempt = _latest(db, (event["target"], event["event_kind"], event["evidence_sha"]))
                event["delivery"] = dict(attempt) if attempt else None
            next_cursor = None
            if has_more:
                last = pending[-1]
                next_cursor = _status_cursor({
                    "v": 1, "target": target, "limit": limit,
                    "high_water": high_water,
                    "after": [last["created_at"], last["target"],
                              last["event_kind"], last["evidence_sha"]]
                })
            observations = db.execute(
                "SELECT summary FROM (SELECT target,summary,ROW_NUMBER() OVER ("
                "PARTITION BY target ORDER BY started_at DESC,observed_at DESC,run_id DESC) rank "
                "FROM run_observation WHERE (? IS NULL OR target=?)) "
                "WHERE rank=1 ORDER BY target", (target, target)).fetchall()
            run_observations = [json.loads(row["summary"]) for row in observations]
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return {"pending": pending, "pending_total": global_total,
            "filtered_total": filtered_total, "global_total": global_total,
            "truncated": has_more, "next_cursor": next_cursor,
            "page_limit": limit, "automations_invoked": False,
            "run_observations": run_observations}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--target", choices=sorted(TARGETS))
    p.add_argument("--event-kind", choices=sorted(KINDS))
    p.add_argument("--evidence-sha")
    p.add_argument("--requestor", choices=sorted(REQUESTORS))
    actions = p.add_mutually_exclusive_group()
    actions.add_argument("--reserve", action="store_true")
    actions.add_argument("--defer", action="store_true")
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--acknowledge", action="store_true")
    actions.add_argument("--record-outcome", choices=sorted(OUTCOMES))
    actions.add_argument("--record-run", metavar="PRIVATE_JSON",
                         help="record one official peek automation object; never dispatch")
    p.add_argument("--reason", default="target_busy")
    p.add_argument("--reservation-id")
    p.add_argument("--receipt-sha")
    p.add_argument("--run-id")
    p.add_argument("--limit", type=int, default=STATUS_MAX_PAGE,
                   help="status page size, 1..200")
    p.add_argument("--cursor",
                   help="opaque next_cursor from preceding status page")
    args = p.parse_args()
    if args.status:
        result = status(args.root, target=args.target,
                        limit=args.limit, cursor=args.cursor)
    elif args.record_run:
        if not args.target or not args.requestor:
            p.error("target and requestor are required")
        if args.cursor is not None or args.limit != STATUS_MAX_PAGE:
            p.error("--limit and --cursor are status-only")
        result = record_run(args.root, args.target, args.requestor,
                            json.loads(Path(args.record_run).read_text(encoding="utf-8")))
    else:
        if args.cursor is not None or args.limit != STATUS_MAX_PAGE:
            p.error("--limit and --cursor are status-only")
        if not all((args.target,args.event_kind,args.evidence_sha,args.requestor)):
            p.error("target, event-kind, evidence-sha and requestor are required")
        common = (args.root,args.target,args.event_kind,args.evidence_sha,args.requestor)
        if args.defer:
            result = defer(*common,reason=args.reason)
        elif args.acknowledge:
            result = acknowledge(*common,args.receipt_sha,args.run_id)
        elif args.record_outcome:
            result = record_outcome(*common,args.reservation_id,args.record_outcome,
                                    args.receipt_sha,run_id=args.run_id)
        else:
            result = check(*common,reserve=args.reserve)
    print(json.dumps(result,sort_keys=True))


if __name__ == "__main__":
    main()
