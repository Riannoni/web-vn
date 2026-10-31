#!/usr/bin/env python3
"""Four-lane source-only coordinator prototype for web-vn.

No ChatGPT/browser transport, inference, GPU, production access or deploy actions.
All workers have detached git worktrees and write only evidence in pilot directory.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS task(
  id TEXT PRIMARY KEY, goal TEXT NOT NULL, action TEXT NOT NULL,
  deps TEXT NOT NULL DEFAULT '[]', paths TEXT NOT NULL DEFAULT '[]',
  priority INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending',
  owner TEXT, fence TEXT, attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 2, lease_until REAL NOT NULL DEFAULT 0,
  started_at REAL, completed_at REAL, result TEXT
);
CREATE TABLE IF NOT EXISTS event(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  task_id TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL
);
"""
ALLOWED_ACTIONS = {"source_inventory", "source_compile", "visual_evidence"}
MAX_CONCURRENT = 4


def stamp(epoch=None):
    return dt.datetime.fromtimestamp(time.time() if epoch is None else epoch, dt.timezone.utc).isoformat()


def database(path):
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    return conn


def emit(db, task_id, kind, detail=""):
    db.execute("INSERT INTO event(ts,task_id,kind,detail) VALUES(?,?,?,?)",
               (time.time(), task_id, kind, str(detail)[:400]))


def add(db, task_id, action, paths, deps=(), goal="render-v1 #20", priority=0):
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unapproved action")
    if not isinstance(paths, (list, tuple)):
        raise ValueError("Invalid scope type")
    if action == "visual_evidence":
        if not isinstance(task_id, str) or not task_id.startswith("G-"):
            raise ValueError("Golden visual evidence is restricted to G lane")
        if list(paths):
            raise ValueError("Visual evidence task cannot declare source write scope")
    elif not paths:
        raise ValueError("Must declare read/write scope")
    if any(not isinstance(p, str) or p.startswith("/") or ".." in p.split("/")
           for p in paths):
        raise ValueError("Only relative paths allowed")
    db.execute("INSERT INTO task(id,goal,action,deps,paths,priority) VALUES(?,?,?,?,?,?)",
               (task_id, goal, action, json.dumps(list(deps)),
                json.dumps(list(paths)), priority))
    emit(db, task_id, "enqueued")


def _expire(db, now):
    expired = db.execute(
        "SELECT id,attempt,max_attempts FROM task WHERE state='leased' AND lease_until<=?",
        (now,)).fetchall()
    for t in expired:
        state = "blocked"
        db.execute(
            "UPDATE task SET state=?,owner=NULL,fence=NULL,lease_until=0 WHERE id=?",
            (state, t["id"]))
        emit(db, t["id"], "lease_expired", state)


def _paths_conflict(a, b):
    # Task ownership includes directory subtrees, not merely identical file strings.
    return any(x == y or x.startswith(y.rstrip("/") + "/") or y.startswith(x.rstrip("/") + "/")
               for x in a for y in b)


def claim(db, owner, ttl=120, now=None, lane=None, allowed_actions=None):
    if not owner or len(owner) > 100 or ttl < 5 or ttl > 3600:
        raise ValueError("Invalid lease")
    now = time.time() if now is None else now
    db.execute("BEGIN IMMEDIATE")
    try:
        _expire(db, now)
        active = db.execute(
            "SELECT id,paths FROM task WHERE state='leased' AND lease_until>?",
            (now,)).fetchall()
        if len(active) >= MAX_CONCURRENT:
            db.execute("COMMIT")
            return None
        succeeded = {x["id"] for x in db.execute("SELECT id FROM task WHERE state='done'")}
        candidates = db.execute(
            "SELECT * FROM task WHERE state='pending' ORDER BY priority DESC,id ASC").fetchall()
        parked = [x for x in db.execute("SELECT id,paths,state FROM task WHERE state IN ('blocked','review_pending')")]
        for row in candidates:
            if lane is not None and not row["id"].startswith(lane+"-"):
                continue
            if allowed_actions is not None and row["action"] not in allowed_actions:
                continue
            # Visual tasks have no source paths: preserve at most one Golden
            # active lease even though ordinary path-conflict checks see [].
            if row["id"].startswith("G-") and any(
                active_item["id"].startswith("G-") for active_item in active
            ):
                continue
            if not set(json.loads(row["deps"])).issubset(succeeded):
                continue
            p = json.loads(row["paths"])
            if any(_paths_conflict(p, json.loads(a["paths"])) for a in active):
                continue
            # Review/failed work is a fence on overlapping source, not every
            # unrelated P0 task. Dependency success is still mandatory.
            if any(_paths_conflict(p,json.loads(a["paths"])) for a in parked
                   if a["id"] != row["id"]):
                continue
            fence = uuid.uuid4().hex
            db.execute(
                "UPDATE task SET state='leased', owner=?,fence=?,attempt=attempt+1,"
                " lease_until=?,started_at=? WHERE id=? AND state='pending'",
                (owner, fence, now + ttl, now, row["id"]))
            emit(db, row["id"], "claimed", "owner=" + owner)
            db.execute("COMMIT")
            return {"id": row["id"], "action": row["action"],
                    "fence": fence, "owner": owner, "attempt": row["attempt"] + 1,
                    "lease_until": now + ttl}
        db.execute("COMMIT")
        return None
    except Exception:
        db.execute("ROLLBACK")
        raise


def heartbeat(db, task_id, owner, fence, ttl=120, now=None):
    now = time.time() if now is None else now
    cur = db.execute(
        "UPDATE task SET lease_until=? WHERE id=? AND state='leased' "
        "AND owner=? AND fence=? AND lease_until>?",
        (now + ttl, task_id, owner, fence, now))
    return cur.rowcount == 1


def complete(db, task_id, owner, fence, evidence, now=None, passed=True):
    now = time.time() if now is None else now
    if not isinstance(evidence, dict) or not evidence.get("sha256"):
        raise ValueError("Signed evidence digest is mandatory")
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
        if row is None or row["state"] != "leased" or row["owner"] != owner or (
            row["fence"] != fence or row["lease_until"] <= now
        ):
            db.execute("ROLLBACK")
            return False
        # A failed or uncertain attempt is NOT safe for automatic retry:
        # the agent may have modified files or submitted external jobs.
        state = "review_pending" if passed else "blocked"
        db.execute(
            "UPDATE task SET state=?,result=?,completed_at=?,owner=NULL,fence=NULL,"
            " lease_until=0 WHERE id=?",
            (state, json.dumps(evidence), now, task_id))
        emit(db, task_id, "completed" if passed else "failed", state)
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


def snapshot(db):
    tasks = []
    for x in db.execute(
        "SELECT id,goal,action,state,owner,attempt,lease_until,completed_at "
        "FROM task ORDER BY priority DESC,id ASC"
    ):
        y = dict(x)
        y["heartbeat_due"] = stamp(y["lease_until"]) if y["state"] == "leased" else None
        tasks.append(y)
    return {"at": stamp(), "max_parallel": MAX_CONCURRENT, "tasks": tasks,
            "events": db.execute("SELECT COUNT(*) FROM event").fetchone()[0]}


def do_task(action, workspace, task_id):
    if not (workspace / "AGENTS.md").is_file() or not (
        workspace / "docs/DEVELOPMENT-AND-TESTING.md").is_file():
        raise RuntimeError("Mandatory source rules not present")
    # These tasks are intentionally read-only and can run without a model account.
    if action == "source_inventory":
        r = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15, check=True)
        status = subprocess.run(
            ["git", "-C", str(workspace), "status", "--porcelain"],
            capture_output=True, text=True, timeout=15, check=True)
        return {"source_sha": r.stdout.strip(), "is_clean": not bool(status.stdout.strip()),
                "rule_files": 2, "status": "inspected"}
    if action == "source_compile":
        # No tests writes: syntax-check selected checked-in Python files via ast.parse.
        import ast
        paths = sorted((workspace / "scripts").rglob("*.py"))[:20]
        checked = 0
        for p in paths:
            if p.is_file():
                ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
                checked += 1
        if checked == 0:
            raise RuntimeError("No checked-in source files found")
        return {"files_parsed": checked, "status": "syntax_only", "note": "not G2/G3"}
    raise ValueError("Action not in allowlist")


def persist_evidence(outdir, task_id, fence, blob):
    """Write immutable per-attempt evidence, never overwrite another worker."""
    if not isinstance(blob, bytes):
        raise TypeError("Evidence content must be bytes")
    outdir = Path(outdir)
    if not outdir.is_dir():
        raise FileNotFoundError("Evidence directory not found")
    # Hash task name and fencing token to avoid traversal and ambiguous filenames.
    filename = hashlib.sha256(
        (task_id + "\0" + fence).encode("utf-8")
    ).hexdigest() + ".json"
    path = outdir / filename
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def worker(dbpath, workspace, outdir, owner, task_id=None):
    db = database(dbpath)
    lease = claim(db, owner, ttl=60,
                  allowed_actions={"source_inventory", "source_compile"})
    if not lease:
        return 3
    if task_id is not None and lease["id"] != task_id:
        raise RuntimeError("Unexpected task scheduled")
    success = False
    try:
        result = do_task(lease["action"], workspace, lease["id"])
        # Keep two independent processes active long enough for a concurrency canary.
        time.sleep(0.7)
        blob = json.dumps(result, sort_keys=True).encode()
        evidence_path = persist_evidence(outdir, lease["id"], lease["fence"], blob)
        evidence = {"sha256": hashlib.sha256(blob).hexdigest(),
                    "path": evidence_path.name,
                    "result_type": "source_only",
                    "test_status": result["status"]}
        success = complete(db, lease["id"], owner, lease["fence"], evidence)
    except Exception as exc:
        error = {"sha256": hashlib.sha256(type(exc).__name__.encode()).hexdigest(),
                 "error_type": type(exc).__name__, "result_type": "blocked"}
        complete(db, lease["id"], owner, lease["fence"], error, passed=False)
    finally:
        db.close()
    return 0 if success else 1


def demo(root, base):
    if root.exists():
        raise RuntimeError("Existing pilot directory must never be overwritten")
    root.mkdir(parents=True, mode=0o700)
    (root / "evidence").mkdir(mode=0o700)
    dbpath = root / "tasks.sqlite3"
    db = database(dbpath)
    add(db, "source-inventory", "source_inventory", ["docs"], priority=10)
    add(db, "syntax-audit", "source_compile", ["scripts"], priority=10)
    db.close()
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks",
                    "--no-checkout", str(base), str(root / "source")], check=True, timeout=60)
    source = root / "source"
    sha = subprocess.run(["git", "-C", str(base), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    worktrees = []
    for i in (1, 2):
        location = root / ("worker-" + str(i))
        subprocess.run(["git", "-C", str(source), "worktree", "add",
                        "--quiet", "--detach", str(location), sha],
                       check=True, timeout=45)
        worktrees.append(location)
    started = time.monotonic()
    processes = [
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker",
                          "--db", str(dbpath), "--workspace", str(worktrees[i]),
                          "--evidence-dir", str(root / "evidence"), "--owner", f"pilot-{i+1}"])
        for i in range(2)
    ]
    codes = [p.wait(timeout=90) for p in processes]
    db = database(dbpath)
    data = snapshot(db)
    data["elapsed_s"] = round(time.monotonic() - started, 3)
    data["workers_exit"] = codes
    (root / "status.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps(data, ensure_ascii=False))
    db.close()
    return 0 if codes == [0, 0] and all(
        t["state"] == "review_pending" for t in data["tasks"]) else 1


def main():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="action", required=True)
    x = subs.add_parser("demo")
    x.add_argument("--root", type=Path, required=True)
    x.add_argument("--base", type=Path, required=True)
    y = subs.add_parser("worker")
    y.add_argument("--db", type=Path, required=True)
    y.add_argument("--workspace", type=Path, required=True)
    y.add_argument("--evidence-dir", type=Path, required=True)
    y.add_argument("--owner", required=True)
    z = subs.add_parser("status")
    z.add_argument("--db", type=Path, required=True)
    args = p.parse_args()
    if args.action == "demo":
        return demo(args.root, args.base)
    if args.action == "worker":
        return worker(args.db, args.workspace, args.evidence_dir, args.owner)
    if args.action == "status":
        db = database(args.db)
        print(json.dumps(snapshot(db), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
