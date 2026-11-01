#!/usr/bin/env python3
"""Fail-closed, durable single-GPU ComfyUI HTTP/WebSocket broker.

Stable client endpoint: 127.0.0.1:8188. Private backend: 127.0.0.1:8189.
A dedicated OS UID plus host OUTPUT firewall rule MUST guard 8189 before cutover.
No GPU work is started by installation or tests.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sqlite3
import time
import uuid

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web

TERMINAL = {"success", "error", "interrupted"}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate",
               "proxy-authorization", "te", "trailer", "transfer-encoding",
               "upgrade", "host", "content-length"}
# Comfy custom-node extensions may expose arbitrary GPU queue insertion routes.
# Fail-closed for every unknown mutating endpoint, not just known Comfy paths.
SAFE_MUTATING_UPLOADS = {"/upload/image", "/upload/mask"}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def queue_ids(data):
    if not isinstance(data, dict):
        raise ValueError("malformed_queue")
    result = set()
    for name in ("queue_running", "queue_pending"):
        entries = data.get(name)
        if not isinstance(entries, list):
            raise ValueError("malformed_queue_" + name)
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2 or not isinstance(entry[1], str):
                raise ValueError("unknown_queue_entry")
            prompt_id = entry[1]
            # Two queued executions with one UUID cannot be reconciled as
            # a single durable owner. Never collapse this ambiguity into a set.
            if prompt_id in result:
                raise ValueError("duplicate_queue_prompt_id")
            result.add(prompt_id)
    return result


def terminal_history(data, prompt_id):
    if not isinstance(data, dict):
        raise ValueError("malformed_history")
    item = data.get(prompt_id)
    if item is None:
        return False
    if not isinstance(item, dict) or not isinstance(item.get("status"), dict):
        raise ValueError("history_without_terminal_status")
    state = item["status"].get("status_str")
    if state not in TERMINAL:
        raise ValueError("unrecognized_history_status")
    # A success label without completed=true is not a terminal proof.
    # Never release the GPU owner and admit another job on partial history.
    if state == "success" and item["status"].get("completed") is not True:
        raise ValueError("success_history_not_completed")
    return True


class Broker:
    def __init__(self, state_dir, backend, wait_seconds=120, poll_seconds=0.25,
                 backend_timeout=8, lease_seconds=15, max_queue=64,
                 external_auth_digest=None):
        # Disable external leases unless provisioned with an exact SHA-256
        # digest of a private capability (no cleartext credential in SQLite).
        if external_auth_digest is not None and not re.fullmatch(
                r"[0-9a-f]{64}", external_auth_digest):
            raise ValueError("invalid_external_auth_digest")
        self.external_auth_digest = external_auth_digest
        self.root = Path(state_dir)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never re-resolve the mutable state-root pathname after validation.
        # Keep a Linux directory descriptor pinned through SQLite/WAL operations.
        with ExitStack() as ownership:
            try:
                root_fd = os.open(
                    self.root, os.O_RDONLY | os.O_DIRECTORY |
                    os.O_NOFOLLOW | os.O_CLOEXEC)
            except OSError as exc:
                raise ValueError("broker_state_dir_symlink_or_unsafe_directory") from exc
            ownership.callback(os.close, root_fd)
            os.fchmod(root_fd, 0o700)
            lock_fd = os.open(
                "broker.lock", os.O_RDWR | os.O_APPEND | os.O_CREAT |
                os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
            try:
                lock_file = os.fdopen(lock_fd, "a+")
            except BaseException:
                os.close(lock_fd)
                raise
            ownership.callback(lock_file.close)
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("another_broker_owns_state_directory") from exc
            # sqlite3.connect has no dir_fd. /proc/self/fd/N is anchored to
            # our held inode even if the configured pathname gets swapped.
            # This service already requires Linux (systemd + nftables).
            db = sqlite3.connect(
                f"/proc/self/fd/{root_fd}/broker.sqlite3", isolation_level=None)
            ownership.callback(db.close)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            os.chmod("broker.sqlite3", 0o600, dir_fd=root_fd,
                     follow_symlinks=False)
            db.executescript("""
          CREATE TABLE IF NOT EXISTS jobs (
            key TEXT PRIMARY KEY, digest TEXT NOT NULL,
            prompt_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
            state TEXT NOT NULL, response TEXT, error TEXT,
            created REAL NOT NULL, deadline REAL NOT NULL, updated REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS owner (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            prompt_id TEXT, lease_until REAL
          );
          INSERT OR IGNORE INTO owner(singleton,prompt_id,lease_until) VALUES(1,NULL,NULL);
          CREATE TABLE IF NOT EXISTS foreign_jobs (
            prompt_id TEXT PRIMARY KEY, discovered REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS external_lease (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            lease_id TEXT, client TEXT, created REAL
          );
          INSERT OR IGNORE INTO external_lease(singleton,lease_id,client,created)
            VALUES(1,NULL,NULL,NULL);
          CREATE TABLE IF NOT EXISTS external_free (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            state TEXT NOT NULL CHECK(state IN ('IDLE','IN_FLIGHT','UNKNOWN')),
            updated REAL
          );
          INSERT OR IGNORE INTO external_free(singleton,state,updated)
            VALUES(1,'IDLE',NULL);
        """)
            self.root_fd = root_fd
            self.lock_file = lock_file
            self.db = db
            ownership.pop_all()
        self.backend = backend.rstrip("/")
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds
        self.backend_timeout = backend_timeout
        self.lease_seconds = lease_seconds
        self.max_queue = max_queue
        self.session = None
        self.task = None
        self.fault = "startup_reconciliation_pending"
        self.last_poll = 0.0
        self._stopping = False
        self.guard = asyncio.Lock()

    def row(self, key):
        return self.db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()

    def owner(self):
        return self.db.execute("SELECT prompt_id FROM owner WHERE singleton=1").fetchone()[0]

    def external(self):
        return self.db.execute(
            "SELECT lease_id,client,created FROM external_lease WHERE singleton=1").fetchone()

    def external_free_state(self):
        return self.db.execute(
            "SELECT state FROM external_free WHERE singleton=1").fetchone()[0]

    def set_external_free_state(self, state):
        if state not in ("IDLE", "IN_FLIGHT", "UNKNOWN"):
            raise ValueError("invalid_free_state")
        self.transaction(lambda: self.db.execute(
            "UPDATE external_free SET state=?,updated=? WHERE singleton=1",
            (state, time.time())))

    def transaction(self, callback):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
            self.db.execute("COMMIT")
            return value
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def enqueue(self, key, digest, payload, wait_seconds=None):
        now = time.time()
        def insert():
            row = self.row(key)
            if row is not None:
                if row["digest"] != digest:
                    return None, "idempotency_key_payload_conflict"
                return row, None
            if self.db.execute("SELECT COUNT(*) FROM jobs WHERE state='QUEUED'").fetchone()[0] >= self.max_queue:
                return None, "queue_capacity_exceeded"
            supplied = payload.get("prompt_id")
            if supplied is not None:
                try:
                    prompt_id = str(uuid.UUID(supplied))
                except (ValueError, AttributeError, TypeError):
                    return None, "invalid_prompt_id"
            else:
                prompt_id = str(uuid.uuid4())
            if self.db.execute("SELECT 1 FROM jobs WHERE prompt_id=?", (prompt_id,)).fetchone():
                return None, "prompt_id_already_reserved"
            self.db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                (key, digest, prompt_id, canonical(payload), "QUEUED",
                 None, None, now, now + (wait_seconds or self.wait_seconds), now))
            return self.row(key), None
        return self.transaction(insert)

    def change(self, prompt_id, state, response=None, error=None, release=False):
        now = time.time()
        def update():
            self.db.execute(
                "UPDATE jobs SET state=?,response=COALESCE(?,response),"
                "error=?,updated=? WHERE prompt_id=?",
                (state, canonical(response) if response is not None else None,
                 error, now, prompt_id))
            if release:
                self.db.execute(
                    "UPDATE owner SET prompt_id=NULL,lease_until=NULL "
                    "WHERE singleton=1 AND prompt_id=?", (prompt_id,))
        self.transaction(update)

    def claim(self, prompt_id):
        def update():
            if self.owner() is not None:
                return False
            row = self.db.execute("SELECT state FROM jobs WHERE prompt_id=?", (prompt_id,)).fetchone()
            if row is None or row["state"] != "QUEUED":
                return False
            self.db.execute(
                "UPDATE owner SET prompt_id=?,lease_until=? WHERE singleton=1 AND prompt_id IS NULL",
                (prompt_id, time.time() + self.lease_seconds))
            self.db.execute(
                "UPDATE jobs SET state='SUBMITTING',updated=? WHERE prompt_id=?",
                (time.time(), prompt_id))
            return True
        return self.transaction(update)

    def expire(self, prompt_id):
        def update():
            self.db.execute(
                "UPDATE jobs SET state='EXPIRED',error='queue_wait_timeout',updated=? "
                "WHERE prompt_id=? AND state='QUEUED'",
                (time.time(), prompt_id))
        self.transaction(update)

    async def get_json(self, path):
        async with self.session.get(self.backend + path,
                                    timeout=ClientTimeout(total=self.backend_timeout)) as response:
            response.raise_for_status()
            return await response.json()

    async def reconcile(self):
        qids = queue_ids(await self.get_json("/queue"))
        now = time.time()
        # Expiry is independent of the current owner; never dispatch stale work.
        self.db.execute(
            "UPDATE jobs SET state='EXPIRED',error='queue_wait_timeout',updated=? "
            "WHERE state='QUEUED' AND deadline<=?", (now, now))
        owner = self.owner()
        if owner and self.external()["lease_id"]:
            raise ValueError("overlapping_comfy_and_external_gpu_owners")
        for prompt_id in qids:
            if prompt_id != owner:
                self.db.execute(
                    "INSERT OR IGNORE INTO foreign_jobs VALUES(?,?)", (prompt_id, now))
        # Foreign jobs are never dismissed by a merely empty queue: require terminal history.
        foreign = [r[0] for r in self.db.execute("SELECT prompt_id FROM foreign_jobs")]
        for prompt_id in foreign:
            if prompt_id in qids:
                continue
            if terminal_history(await self.get_json("/history/" + prompt_id), prompt_id):
                self.db.execute("DELETE FROM foreign_jobs WHERE prompt_id=?", (prompt_id,))
        foreign = [r[0] for r in self.db.execute("SELECT prompt_id FROM foreign_jobs")]
        if owner:
            row = self.db.execute("SELECT * FROM jobs WHERE prompt_id=?", (owner,)).fetchone()
            if row is None:
                raise ValueError("owner_without_durable_job")
            history = await self.get_json("/history/" + owner)
            if terminal_history(history, owner):
                if owner in qids:
                    raise ValueError("terminal_history_but_still_queued")
                self.change(owner, "TERMINAL", response=json.loads(row["response"]) if row["response"]
                            else {"prompt_id": owner, "node_errors": {}}, release=True)
            elif owner in qids:
                if row["state"] in ("SUBMITTING", "UNCERTAIN"):
                    self.change(owner, "ACTIVE", response=json.loads(row["response"]) if row["response"]
                                else {"prompt_id": owner, "node_errors": {}})
                self.db.execute("UPDATE owner SET lease_until=? WHERE singleton=1",
                                (now + self.lease_seconds,))
            else:
                # Crash between durable reservation and POST is ambiguous.
                # A missing active job/history is NEVER evidence it was not submitted.
                if row["state"] == "SUBMITTING":
                    self.change(owner, "UNCERTAIN", error="submission_outcome_unknown")
                self.db.execute("UPDATE owner SET lease_until=? WHERE singleton=1",
                                (now + self.lease_seconds,))
                self.fault = "owner_missing_from_queue_and_history"
                return
            if self.owner() is not None:
                self.fault = "foreign_queue_detected" if foreign else None
                return
        if foreign:
            self.fault = "foreign_queue_requires_terminal_history"
            return
        if self.external()["lease_id"] or self.external_free_state() != "IDLE":
            self.fault = "free_uncertain_requires_operator" if self.external_free_state() != "IDLE" else None
            return
        if qids:
            self.fault = "unrecognized_queue_entries"
            return
        self.fault = None
        # Cancel expired proposals before choosing a new owner.
        self.db.execute(
            "UPDATE jobs SET state='EXPIRED',error='queue_wait_timeout',updated=? "
            "WHERE state='QUEUED' AND deadline<=?", (now, now))
        job = self.db.execute(
            "SELECT * FROM jobs WHERE state='QUEUED' ORDER BY created,key LIMIT 1").fetchone()
        if job is None:
            return
        pid = job["prompt_id"]
        # Never reuse a prompt UUID already present in backend history, even
        # if it came from a pre-broker or privileged foreign submitter.
        prior = await self.get_json("/history/" + pid)
        if terminal_history(prior, pid):
            self.change(pid, "REJECTED", error="prompt_id_preexisting_history")
            return
        if not self.claim(pid):
            return
        # Second preflight closes the check/claim gap against a newly arrived foreign job.
        try:
            second = queue_ids(await self.get_json("/queue"))
            if second:
                for other in second:
                    self.db.execute("INSERT OR IGNORE INTO foreign_jobs VALUES(?,?)", (other, now))
                self.change(pid, "QUEUED", release=True)
                self.fault = "queue_changed_before_submit"
                return
        except (ClientError, asyncio.TimeoutError, ValueError):
            # No POST was attempted; safely restore the queued state.
            self.change(pid, "QUEUED", release=True)
            raise
        body = json.loads(job["payload"])
        body["prompt_id"] = pid
        try:
            async with self.session.post(
                self.backend + "/prompt", json=body,
                timeout=ClientTimeout(total=self.backend_timeout)) as response:
                data = await response.json()
                if response.status == 400:
                    # Explicit validation rejection from Comfy: no enqueue.
                    self.change(pid, "REJECTED", response=data, error="comfy_validation_rejected",
                                release=True)
                    return
                if response.status != 200 or data.get("prompt_id") != pid:
                    self.change(pid, "UNCERTAIN", error="untrusted_submit_response")
                    self.fault = "submit_outcome_unknown"
                    return
                self.change(pid, "ACTIVE", response=data)
        except (ClientError, asyncio.TimeoutError, ValueError, TypeError):
            self.change(pid, "UNCERTAIN", error="submit_transport_ambiguous")
            self.fault = "submit_outcome_unknown"

    async def poll(self):
        while not self._stopping:
            try:
                async with self.guard:
                    await self.reconcile()
                self.last_poll = time.time()
            except Exception as exc:
                self.fault = "reconcile_" + type(exc).__name__
            await asyncio.sleep(self.poll_seconds)

    async def start(self):
        self.session = ClientSession(auto_decompress=False)
        self.task = asyncio.create_task(self.poll())

    async def stop(self):
        self._stopping = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.session:
            await self.session.close()
        self.db.close()
        fcntl.flock(self.lock_file, fcntl.LOCK_UN)
        self.lock_file.close()
        os.close(self.root_fd)

    def status(self):
        counts = dict(self.db.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state").fetchall())
        owner = self.owner()
        foreign = self.db.execute("SELECT COUNT(*) FROM foreign_jobs").fetchone()[0]
        external = self.external()
        return {"ready": self.fault is None and owner is None and foreign == 0
                and not external["lease_id"],
                "external_owner": external["client"],
                "external_lease_age_seconds": round(time.time()-external["created"], 1)
                    if external["lease_id"] else None,
                "fault": self.fault, "owner_prompt_id": owner,
                "owner_lease_expired": bool(owner and
                    self.db.execute("SELECT lease_until FROM owner WHERE singleton=1").fetchone()[0] < time.time()),
                "foreign_jobs": foreign, "jobs": counts,
                "external_free_state": self.external_free_state(),
                "queue_depth": counts.get("QUEUED", 0), "last_poll_unix": self.last_poll}


BROKER_KEY = web.AppKey("broker", Broker)


async def submit(request):
    broker = request.app[BROKER_KEY]
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict) or not isinstance(body.get("prompt"), dict):
        return web.json_response({"error": "invalid_prompt_shape"}, status=400)
    # A graph/seed is *not* an action ID. Two authorized games can submit the
    # same graph, while a reconnect must reuse precisely one logical action.
    # Never fall back to payload equality: it replays a completed other game.
    # client_id routes WebSocket events; prompt_id is a transport UUID only.
    explicit = request.headers.get("Idempotency-Key")
    if explicit is None:
        return web.json_response({"error": "logical_action_id_required"}, status=428)
    if not (1 <= len(explicit) <= 200):
        return web.json_response({"error": "invalid_idempotency_key"}, status=400)
    fingerprint = {k: v for k, v in body.items() if k not in ("client_id", "prompt_id")}
    digest = hashlib.sha256(canonical(fingerprint).encode()).hexdigest()
    key = "explicit:" + explicit
    requested_wait = request.headers.get("X-Broker-Queue-Wait-Seconds")
    wait = None
    if requested_wait is not None:
        try:
            wait = float(requested_wait)
        except ValueError:
            return web.json_response({"error": "invalid_queue_wait"}, status=400)
        if not 1 <= wait <= broker.wait_seconds:
            return web.json_response({"error": "queue_wait_out_of_bounds"}, status=400)
    row, error = broker.enqueue(key, digest, body, wait_seconds=wait)
    if error:
        return web.json_response({"error": error}, status=503 if error == "queue_capacity_exceeded" else
                                 409 if "conflict" in error or "reserved" in error else 400)
    pid = row["prompt_id"]
    if row["state"] == "UNCERTAIN":
        return web.json_response({"error": "submission_outcome_unknown", "prompt_id": pid,
                                  "retry_safe": False}, status=503)
    if row["state"] == "REJECTED":
        return web.json_response({"error": "broker_job_rejected",
                                  "reason": row["error"] or "job_rejected",
                                  "prompt_id": pid, "retry_safe": False}, status=409)
    if row["state"] == "EXPIRED":
        # An idempotent reconnect cannot revive a timed-out logical action.
        # Do not return a success-shaped receipt for a job that will never run.
        return web.json_response({"error": "queue_wait_expired", "prompt_id": pid,
                                  "retry_safe": False}, status=410)
    # Durable receipt immediately; the actual Comfy POST is serialized later.
    # Legacy clients can safely poll /history/{prompt_id} while QUEUED.
    if row["response"] and row["state"] in ("ACTIVE", "TERMINAL"):
        return web.json_response(json.loads(row["response"]))
    return web.json_response({"prompt_id": pid, "number": -1, "node_errors": {},
                              "broker_queued": row["state"] == "QUEUED"})


def external_authorized(request, broker):
    # Client name and source IP are not credentials. Loopback is shared by
    # unrelated applications; protect both acquire and release.
    header = request.headers.get("Authorization", "")
    if not broker.external_auth_digest or not header.startswith("Bearer "):
        return False
    token = header[len("Bearer "):]
    if not (32 <= len(token) <= 128) or any(c.isspace() for c in token):
        return False
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual, broker.external_auth_digest)


async def external_acquire(request):
    broker = request.app[BROKER_KEY]
    if not external_authorized(request, broker):
        return web.json_response({"error": "external_client_auth_required"}, status=401)
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict) or body.get("client") != "kobold-gateway":
        return web.json_response({"error": "unsupported_external_client"}, status=403)
    async with broker.guard:
        if (broker.fault is not None or broker.owner() or broker.external()["lease_id"]
                or broker.external_free_state() != "IDLE"):
            return web.json_response({"error": "gpu_owner_busy"}, status=409)
        try:
            if queue_ids(await broker.get_json("/queue")):
                return web.json_response({"error": "backend_queue_busy"}, status=409)
        except (ClientError, asyncio.TimeoutError, ValueError):
            return web.json_response({"error": "backend_unavailable"}, status=503)
        def acquire():
            if broker.db.execute("SELECT 1 FROM jobs WHERE state='QUEUED' LIMIT 1").fetchone():
                return None
            lease_id = str(uuid.uuid4())
            broker.db.execute(
                "UPDATE external_lease SET lease_id=?,client=?,created=? "
                "WHERE singleton=1 AND lease_id IS NULL",
                (lease_id, "kobold-gateway", time.time()))
            return lease_id
        lease_id = broker.transaction(acquire)
        if not lease_id:
            return web.json_response({"error": "broker_queue_busy"}, status=409)
        return web.json_response({"lease_id": lease_id})


async def external_release(request):
    broker = request.app[BROKER_KEY]
    if not external_authorized(request, broker):
        return web.json_response({"error": "external_client_auth_required"}, status=401)
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid_json"}, status=400)
    lease_id = body.get("lease_id") if isinstance(body, dict) else None
    if not isinstance(lease_id, str):
        return web.json_response({"error": "lease_id_required"}, status=400)
    async with broker.guard:
        if broker.external_free_state() != "IDLE":
            return web.json_response({"error": "free_inflight_or_uncertain"}, status=409)
        def release():
            current = broker.external()
            if not current["lease_id"] or not hmac.compare_digest(current["lease_id"], lease_id):
                return False
            broker.db.execute(
                "UPDATE external_lease SET lease_id=NULL,client=NULL,created=NULL WHERE singleton=1")
            return True
        if not broker.transaction(release):
            return web.json_response({"error": "lease_mismatch"}, status=409)
    return web.json_response({"released": True})


async def status(request):
    return web.json_response(request.app[BROKER_KEY].status())


async def metrics(request):
    s = request.app[BROKER_KEY].status()
    lines = [
        "# TYPE comfy_broker_queue_depth gauge",
        "comfy_broker_queue_depth " + str(s["queue_depth"]),
        "# TYPE comfy_broker_owner_active gauge",
        "comfy_broker_owner_active " + str(int(bool(s["owner_prompt_id"]))),
        "# TYPE comfy_broker_foreign_jobs gauge",
        "comfy_broker_foreign_jobs " + str(s["foreign_jobs"]),
        "comfy_broker_external_owner_active " + str(int(bool(s["external_owner"]))),
        "# TYPE comfy_broker_fail_closed gauge",
        "comfy_broker_fail_closed " + str(int(s["fault"] is not None)),
    ]
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")


async def job_status(request):
    broker = request.app[BROKER_KEY]
    row = broker.db.execute(
        "SELECT prompt_id,state,error,created,updated FROM jobs WHERE prompt_id=?",
        (request.match_info["prompt_id"],)).fetchone()
    if row is None:
        raise web.HTTPNotFound()
    return web.json_response(dict(row))


async def websocket(request):
    broker = request.app[BROKER_KEY]
    upstream = broker.backend.replace("http://", "ws://").replace("https://", "wss://")
    upstream += str(request.rel_url)
    async with broker.session.ws_connect(upstream, autoping=False) as backend_ws:
        client_ws = web.WebSocketResponse(autoping=False)
        await client_ws.prepare(request)

        async def forward(src, dst):
            async for msg in src:
                if msg.type == WSMsgType.TEXT:
                    await dst.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await dst.send_bytes(msg.data)
                elif msg.type == WSMsgType.PING:
                    await dst.ping(msg.data)
                elif msg.type == WSMsgType.PONG:
                    await dst.pong(msg.data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

        tasks = [asyncio.create_task(forward(client_ws, backend_ws)),
                 asyncio.create_task(forward(backend_ws, client_ws))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client_ws.close()
        return client_ws


async def passthrough(request):
    broker = request.app[BROKER_KEY]
    canonical_path = request.path[4:] if request.path.startswith("/api/") else request.path
    if request.method == "POST" and canonical_path == "/free":
        # Lease UUID is routing metadata, never a peer credential. Require
        # the same file-backed capability used for lease acquire/release.
        if not external_authorized(request, broker):
            return web.json_response({"error": "external_client_auth_required"}, status=401)
        # /free is a GPU mutation. Keep the same guard for its COMPLETE
        # upstream round-trip, and persist the in-flight fence BEFORE I/O.
        # A crash or transport timeout leaves UNKNOWN (no unsafe lease release).
        async with broker.guard:
            lease = broker.external()
            if (broker.fault is not None or broker.owner() or not lease["lease_id"]
                    or broker.external_free_state() != "IDLE" or not hmac.compare_digest(
                        request.headers.get("X-GPU-Lease-ID", ""), lease["lease_id"])):
                return web.json_response({"error": "external_gpu_lease_required"}, status=403)
            broker.set_external_free_state("IN_FLIGHT")
            try:
                answer = await forward_read_or_upload(request, broker, canonical_path)
                broker.set_external_free_state("IDLE" if answer.status == 200 else "UNKNOWN")
                return answer
            except BaseException:
                broker.set_external_free_state("UNKNOWN")
                raise
    if request.method not in ("GET", "HEAD", "OPTIONS") and not (
            request.method == "POST" and canonical_path in SAFE_MUTATING_UPLOADS):
        return web.json_response({"error": "unaudited_mutating_endpoint_denied"}, status=403)
    return await forward_read_or_upload(request, broker, canonical_path)


async def forward_read_or_upload(request, broker, canonical_path):
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    # This capability authenticates *to broker*, not to ComfyUI; do not
    # expose it to the backend or plugins handling GPU memory release.
    if request.method == "POST" and canonical_path == "/free":
        headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
    if request.method == "GET" and canonical_path == "/queue":
        try:
            data = await broker.get_json("/queue")
            queue_ids(data)
            rows = broker.db.execute(
                "SELECT prompt_id,payload FROM jobs WHERE state IN "
                "('QUEUED','SUBMITTING','UNCERTAIN','ACTIVE') ORDER BY created,key").fetchall()
            backend_ids = queue_ids(data)
            for number, row in enumerate(rows):
                if row["prompt_id"] in backend_ids:
                    continue
                payload = json.loads(row["payload"])
                data["queue_pending"].append([number, row["prompt_id"],
                    payload["prompt"], {"client_id": payload.get("client_id")}, []])
            if broker.external()["lease_id"]:
                data["queue_pending"].append([0, "external-gpu-lease", {},
                    {"client_id": broker.external()["client"]}, []])
            return web.json_response(data)
        except (ClientError, asyncio.TimeoutError, ValueError):
            return web.json_response({"error": "queue_unavailable"}, status=502)
    if request.method == "GET" and canonical_path.startswith("/history/"):
        pid = canonical_path[len("/history/"):]
        row = broker.db.execute("SELECT state,error FROM jobs WHERE prompt_id=?", (pid,)).fetchone()
        if row and row["state"] in ("REJECTED", "EXPIRED"):
            return web.json_response({pid: {"status": {"status_str": "error",
                "completed": False, "messages": [["execution_error", {"exception_message":
                row["error"] or row["state"]}]]}, "outputs": {}}})
        if row and row["state"] in ("QUEUED", "SUBMITTING", "UNCERTAIN"):
            return web.json_response({})
    body = await request.read()
    try:
        async with broker.session.request(
            request.method, broker.backend + str(request.rel_url), data=body,
            headers=headers, timeout=ClientTimeout(total=120)) as upstream:
            response_headers = {k: v for k, v in upstream.headers.items()
                                if k.lower() not in HOP_HEADERS}
            downstream = web.StreamResponse(status=upstream.status, headers=response_headers)
            await downstream.prepare(request)
            async for chunk in upstream.content.iter_chunked(65536):
                await downstream.write(chunk)
            await downstream.write_eof()
            return downstream
    except (ClientError, asyncio.TimeoutError):
        return web.json_response({"error": "comfy_backend_unavailable"}, status=502)


def make_app(broker):
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app[BROKER_KEY] = broker
    app.router.add_post("/prompt", submit)
    app.router.add_post("/api/prompt", submit)
    app.router.add_post("/broker/external/acquire", external_acquire)
    app.router.add_post("/broker/external/release", external_release)
    app.router.add_get("/broker/health", status)
    app.router.add_get("/broker/metrics", metrics)
    app.router.add_get("/broker/jobs/{prompt_id}", job_status)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/api/ws", websocket)
    app.router.add_route("*", "/{tail:.*}", passthrough)

    async def startup(_):
        await broker.start()

    async def cleanup(_):
        await broker.stop()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


def load_external_auth_digest(path):
    # The digest is not a bearer secret, but treat it as privileged config.
    # Refuse symlinks, world-readable or group-writable configuration.
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o027:
        raise ValueError("insecure_external_auth_digest_file")
    if info.st_uid not in (0, os.geteuid()):
        raise ValueError("untrusted_external_auth_digest_owner")
    digest = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid_external_auth_digest_file")
    return digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--backend", default="http://127.0.0.1:8189")
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/comfy-broker"))
    parser.add_argument("--queue-wait", type=float, default=120)
    parser.add_argument("--backend-timeout", type=float, default=30)
    parser.add_argument("--external-auth-sha256-file", type=Path, required=True,
                        help="root-provisioned SHA-256 of Kobold external lease token")
    args = parser.parse_args()
    os.umask(0o077)
    broker = Broker(args.state_dir, args.backend, wait_seconds=args.queue_wait,
                    backend_timeout=args.backend_timeout,
                    external_auth_digest=load_external_auth_digest(
                        args.external_auth_sha256_file))
    web.run_app(make_app(broker), host=args.listen, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
