#!/usr/bin/env python3
"""CPU-only protocol/race/fault tests. Fake Comfy; NEVER submit to a GPU."""
import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import uuid

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

PATH = Path(__file__).resolve().parents[1] / "scripts/comfy_broker/broker.py"
spec = importlib.util.spec_from_file_location("comfy_broker", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TEST_EXTERNAL_TOKEN = "fixture-only-broker-lease-token-abcdef0123456789"


class FakeComfy:
    def __init__(self):
        self.running = []
        self.history = {}
        self.posts = []
        self.free_posts = []
        self.history_broken = False
        self.post_delay = 0
        self.submit_mode = None
        self.queue_malformed = False
        self.ws_queries = []
        self.app = web.Application()
        self.app.router.add_get("/queue", self.queue)
        self.app.router.add_post("/prompt", self.submit)
        self.app.router.add_get("/history/{pid}", self.get_history)
        self.app.router.add_post("/upload/image", self.upload)
        self.app.router.add_post("/api/upload/image", self.upload)
        self.app.router.add_post("/free", self.free)
        self.app.router.add_post("/api/free", self.free)
        self.app.router.add_get("/view", self.view)
        self.app.router.add_get("/ws", self.ws)
        self.app.router.add_get("/api/ws", self.ws)

    async def queue(self, request):
        if self.queue_malformed:
            return web.json_response({"queue_running": "not-an-array"})
        return web.json_response({
            "queue_running": [[i, pid, {}] for i, pid in enumerate(self.running)],
            "queue_pending": []})

    async def submit(self, request):
        data = await request.json()
        if self.post_delay:
            await asyncio.sleep(self.post_delay)
        pid = data["prompt_id"]
        if self.submit_mode == "reject":
            return web.json_response({"error": "invalid_graph"}, status=400)
        if self.submit_mode == "unaccepted_500":
            return web.json_response({"error": "backend_fault"}, status=500)
        self.posts.append(pid)
        self.running.append(pid)
        if self.submit_mode == "accepted_500":
            return web.json_response({"error": "response_lost"}, status=500)
        return web.json_response({"prompt_id": pid, "number": len(self.posts), "node_errors": {}})

    async def get_history(self, request):
        if self.history_broken:
            raise web.HTTPInternalServerError()
        pid = request.match_info["pid"]
        return web.json_response({pid: self.history[pid]} if pid in self.history else {})

    async def free(self, request):
        self.free_posts.append({"authorization": request.headers.get("Authorization"),
                                "lease": request.headers.get("X-GPU-Lease-ID")})
        return web.json_response({"freed": True})

    async def upload(self, request):
        if request.content_type.startswith("multipart/"):
            reader = await request.multipart()
            field = await reader.next()
            data = await field.read()
            return web.json_response({"filename": field.filename, "size": len(data)})
        return web.Response(body=await request.read(), content_type="application/octet-stream")

    async def view(self, request):
        return web.Response(body=b"\x89PNG\r\n\x1a\nfake", content_type="image/png")

    async def ws(self, request):
        self.ws_queries.append(request.query_string)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await ws.send_str("echo:" + msg.data)
            elif msg.type == WSMsgType.BINARY:
                await ws.send_bytes(msg.data)
        return ws

    def finish(self, pid, state="success"):
        self.running.remove(pid)
        self.history[pid] = {"status": {"status_str": state,
                                        "completed": state == "success"},
                             "outputs": {}}


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeComfy()
        self.backend_server = TestServer(self.fake.app)
        await self.backend_server.start_server()
        await self.start_broker()

    async def asyncTearDown(self):
        await self.stop_broker()
        await self.backend_server.close()
        self.tmp.cleanup()

    async def start_broker(self, wait=2):
        self.broker = m.Broker(self.tmp.name, str(self.backend_server.make_url("/")).rstrip("/"),
                               wait_seconds=wait, poll_seconds=.02, backend_timeout=.4,
                               external_auth_digest=hashlib.sha256(
                                   TEST_EXTERNAL_TOKEN.encode()).hexdigest())
        self.server = TestServer(m.make_app(self.broker))
        self.client = TestClient(self.server)
        await self.client.start_server()
        await self.until(lambda: self.broker.last_poll > 0)

    async def stop_broker(self):
        await self.client.close()

    async def until(self, predicate, timeout=2):
        end = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() > end:
                self.fail("condition_not_reached")
            await asyncio.sleep(.015)

    def body(self, n):
        return {"prompt": {"1": {"class_type": "Test", "inputs": {"seed": n}}},
                "client_id": "test-client"}

    async def post(self, n, headers=None):
        # Each test n denotes a stable logical action, not a graph-derived identity.
        headers = {"Idempotency-Key": "test-action-" + str(n), **(headers or {})}
        response = await self.client.post("/prompt", json=self.body(n), headers=headers)
        return response.status, await response.json()

    async def test_two_submitters_never_overlap(self):
        first = asyncio.create_task(self.post(1))
        await self.until(lambda: len(self.fake.posts) == 1)
        second = asyncio.create_task(self.post(2))
        await asyncio.sleep(.1)
        self.assertEqual(len(self.fake.posts), 1)
        pid1 = self.fake.posts[0]
        self.fake.finish(pid1)
        await self.until(lambda: len(self.fake.posts) == 2)
        self.assertNotEqual(pid1, self.fake.posts[1])
        self.assertEqual((await first)[0], 200)
        self.assertEqual((await second)[0], 200)
        self.fake.finish(self.fake.posts[1])
        await self.until(lambda: self.broker.owner() is None)

    async def test_duplicate_retries_reuse_prompt_id(self):
        first = asyncio.create_task(self.post(1))
        second = asyncio.create_task(self.post(1))
        a, b = await asyncio.gather(first, second)
        self.assertEqual(a, b)
        await self.until(lambda: len(self.fake.posts) == 1)
        self.fake.finish(a[1]["prompt_id"])
        await self.until(lambda: self.broker.owner() is None)
        self.assertEqual((await self.post(1))[1]["prompt_id"], a[1]["prompt_id"])
        self.assertEqual(len(self.fake.posts), 1)

    async def test_explicit_new_run_key_does_not_reuse_terminal_same_graph(self):
        # Same frozen prompt/seed can be a NEW, deliberately authorized lab run.
        # Implicit payload hash alone would silently replay the old image.
        a_status,a = await self.post(17,headers={"Idempotency-Key":"first-shot-run-A"})
        self.assertEqual(a_status,200)
        pid_a=a["prompt_id"]
        await self.until(lambda: len(self.fake.posts)==1)
        self.fake.finish(pid_a)
        await self.until(lambda: self.broker.owner() is None)
        b_status,b = await self.post(17,headers={"Idempotency-Key":"first-shot-run-B"})
        self.assertEqual(b_status,200)
        pid_b=b["prompt_id"]
        self.assertNotEqual(pid_a,pid_b)
        await self.until(lambda: len(self.fake.posts)==2)
        self.assertEqual(self.fake.posts,[pid_a,pid_b])
        self.fake.finish(pid_b)
        await self.until(lambda: self.broker.owner() is None)
        retry_status,retry = await self.post(17,headers={"Idempotency-Key":"first-shot-run-A"})
        self.assertEqual(retry_status,200)
        self.assertEqual(retry["prompt_id"],pid_a)
        self.assertEqual(len(self.fake.posts),2)

    async def test_unkeyed_action_is_rejected_before_backend_submit(self):
        # Unkeyed Comfy, browser or custom clients cannot accidentally replay a
        # completed other game's terminal image. Neither alias is exempt.
        for path in ("/prompt", "/api/prompt"):
            body = self.body(42)
            body["client_id"] = "different-game"
            body["prompt_id"] = str(uuid.uuid4())
            async with self.client.post(path, json=body) as response:
                self.assertEqual(response.status, 428)
                self.assertEqual((await response.json())["error"], "logical_action_id_required")
        self.assertEqual(self.fake.posts, [])
        self.assertEqual(self.broker.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    async def test_cross_game_identical_graph_distinct_action_and_same_key_reconnect(self):
        first = self.body(29)
        first["client_id"] = "GAME_A"
        first["prompt_id"] = str(uuid.uuid4())
        async with self.client.post("/api/prompt", json=first,
                                    headers={"Idempotency-Key": "game:A:turn:1"}) as response:
            self.assertEqual(response.status, 200)
            pid_a = (await response.json())["prompt_id"]
        await self.until(lambda: len(self.fake.posts) == 1)
        self.fake.finish(pid_a)
        await self.until(lambda: self.broker.owner() is None)

        second = self.body(29)
        second["client_id"] = "GAME_B"
        second["prompt_id"] = str(uuid.uuid4())
        async with self.client.post("/prompt", json=second,
                                    headers={"Idempotency-Key": "game:B:turn:1"}) as response:
            self.assertEqual(response.status, 200)
            pid_b = (await response.json())["prompt_id"]
        self.assertNotEqual(pid_a, pid_b)
        await self.until(lambda: len(self.fake.posts) == 2)
        self.fake.finish(pid_b)
        await self.until(lambda: self.broker.owner() is None)

        second["client_id"] = "GAME_B_reconnect"
        second["prompt_id"] = str(uuid.uuid4())
        async with self.client.post("/api/prompt", json=second,
                                    headers={"Idempotency-Key": "game:B:turn:1"}) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["prompt_id"], pid_b)
        self.assertEqual(self.fake.posts, [pid_a, pid_b])

    async def test_crash_restart_active_recovers_no_resubmit(self):
        status, data = await self.post(1)
        self.assertEqual(status, 200)
        pid = data["prompt_id"]
        await self.until(lambda: len(self.fake.posts) == 1)
        await self.stop_broker()
        await self.start_broker()
        self.assertEqual(self.broker.owner(), pid)
        self.assertEqual(len(self.fake.posts), 1)
        self.fake.finish(pid)
        await self.until(lambda: self.broker.owner() is None)
        self.assertEqual((await self.post(1))[1]["prompt_id"], pid)
        self.assertEqual(len(self.fake.posts), 1)
        self.assertEqual((await self.post(2))[0], 200)
        await self.until(lambda: len(self.fake.posts) == 2)
        self.assertEqual(len(self.fake.posts), 2)

    async def test_crash_between_reservation_and_post_is_fail_closed(self):
        await self.stop_broker()
        offline = m.Broker(self.tmp.name, str(self.backend_server.make_url("/")))
        row, error = offline.enqueue("manual", "hash", self.body(5))
        self.assertIsNone(error)
        self.assertTrue(offline.claim(row["prompt_id"]))
        await offline.stop()
        await self.start_broker()
        await self.until(lambda: self.broker.row("manual")["state"] == "UNCERTAIN")
        self.assertEqual(self.broker.owner(), row["prompt_id"])
        self.assertEqual(len(self.fake.posts), 0)
        task = asyncio.create_task(self.post(9))
        await asyncio.sleep(.1)
        self.assertEqual(len(self.fake.posts), 0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_foreign_queue_blocks_until_terminal_history(self):
        foreign = str(uuid.uuid4())
        self.fake.running.append(foreign)
        await self.until(lambda: self.broker.status()["foreign_jobs"] == 1)
        task = asyncio.create_task(self.post(3))
        await asyncio.sleep(.1)
        self.assertEqual(len(self.fake.posts), 0)
        self.fake.finish(foreign)
        await self.until(lambda: len(self.fake.posts) == 1)
        self.assertEqual((await task)[0], 200)

    async def test_foreign_disappearance_without_history_stays_blocked(self):
        foreign = str(uuid.uuid4())
        self.fake.running.append(foreign)
        await self.until(lambda: self.broker.status()["foreign_jobs"] == 1)
        self.fake.running.remove(foreign)
        await asyncio.sleep(.1)
        self.assertEqual(self.broker.status()["foreign_jobs"], 1)
        self.assertFalse(self.broker.status()["ready"])

    async def test_incomplete_success_history_cannot_release_gpu_owner(self):
        # RED: status_str=success without completed=true is not terminal.
        status, first = await self.post(91)
        self.assertEqual(status, 200)
        pid = first["prompt_id"]
        await self.until(lambda: len(self.fake.posts) == 1)
        async with self.broker.guard:
            self.fake.running.remove(pid)
            self.fake.history[pid] = {
                "status": {"status_str": "success", "completed": False},
                "outputs": {}}
            with self.assertRaisesRegex(ValueError, "success_history_not_completed"):
                await self.broker.reconcile()
            self.assertEqual(self.broker.owner(), pid)
        status, second = await self.post(92)
        self.assertEqual(status, 200)
        await asyncio.sleep(.1)
        self.assertEqual(self.fake.posts, [pid])
        self.assertEqual(self.broker.owner(), pid)
        self.fake.history[pid]["status"]["completed"] = True
        await self.until(lambda: len(self.fake.posts) == 2)
        self.assertEqual(self.fake.posts[1], second["prompt_id"])

    async def test_history_500_holds_owner_and_blocks_next(self):
        first = await self.post(1)
        pid = first[1]["prompt_id"]
        await self.until(lambda: len(self.fake.posts) == 1)
        self.fake.history_broken = True
        second = asyncio.create_task(self.post(2))
        await asyncio.sleep(.1)
        self.assertEqual(len(self.fake.posts), 1)
        self.assertEqual(self.broker.owner(), pid)
        self.assertIsNotNone(self.broker.status()["fault"])
        self.fake.history_broken = False
        self.fake.finish(pid, "error")
        await self.until(lambda: len(self.fake.posts) == 2)
        self.assertEqual((await second)[0], 200)

    async def test_queue_timeout_never_submits_late(self):
        await self.stop_broker()
        await self.start_broker(wait=.25)
        await self.post(1)
        await self.until(lambda: len(self.fake.posts) == 1)
        response = await self.post(2)
        self.assertEqual(response[0], 200)
        self.assertTrue(response[1]["broker_queued"])
        pid2 = response[1]["prompt_id"]
        await self.until(lambda: self.broker.db.execute(
            "SELECT state FROM jobs WHERE prompt_id=?", (pid2,)).fetchone()[0] == "EXPIRED")
        async with self.client.get("/history/" + pid2) as result:
            self.assertEqual((await result.json())[pid2]["status"]["status_str"], "error")
        self.fake.finish(self.fake.posts[0])
        await self.until(lambda: self.broker.owner() is None)
        await asyncio.sleep(.1)
        self.assertEqual(len(self.fake.posts), 1)

    async def test_idempotency_header_payload_conflict(self):
        first = await self.post(1, {"Idempotency-Key": "key1"})
        self.assertEqual(first[0], 200)
        other = await self.post(2, {"Idempotency-Key": "key1"})
        self.assertEqual(other[0], 409)
        await self.until(lambda: len(self.fake.posts) == 1)
        self.assertEqual(len(self.fake.posts), 1)

    async def test_websocket_text_binary_and_query(self):
        async with self.client.ws_connect("/ws?clientId=one") as ws:
            await ws.send_str("hello")
            self.assertEqual((await ws.receive()).data, "echo:hello")
            await ws.send_bytes(b"\x00\x01")
            self.assertEqual((await ws.receive()).data, b"\x00\x01")
        self.assertIn("clientId=one", self.fake.ws_queries)

    async def test_upload_view_history_and_mutation_guard(self):
        async with self.client.post("/upload/image", data=b"testbytes") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), b"testbytes")
        async with self.client.get("/view?filename=one.png") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), b"\x89PNG\r\n\x1a\nfake")
        async with self.client.get("/history/none") as response:
            self.assertEqual(await response.json(), {})
        for path in ("/queue", "/interrupt", "/free", "/history"):
            async with self.client.post(path, json={}) as response:
                self.assertEqual(response.status, 401 if path == "/free" else 403)

    async def test_health_metrics_and_job_status(self):
        response = await self.post(1)
        pid = response[1]["prompt_id"]
        await self.until(lambda: len(self.fake.posts) == 1)
        async with self.client.get("/broker/jobs/" + pid) as result:
            self.assertEqual((await result.json())["state"], "ACTIVE")
        async with self.client.get("/broker/metrics") as result:
            self.assertIn("comfy_broker_owner_active 1", await result.text())
        self.fake.finish(pid)
        await self.until(lambda: self.broker.owner() is None)
        async with self.client.get("/broker/health") as result:
            self.assertTrue((await result.json())["ready"])

    async def test_api_alias_cannot_bypass_and_queue_visible(self):
        first = await self.post(1)
        await self.until(lambda: len(self.fake.posts) == 1)
        async with self.client.post("/api/prompt", json=self.body(3),
                                    headers={"Idempotency-Key": "test-alias-3"}) as response:
            self.assertEqual(response.status, 200)
            queued = await response.json()
        self.assertEqual(len(self.fake.posts), 1)
        async with self.client.get("/api/queue") as response:
            data = await response.json()
            self.assertIn(queued["prompt_id"],
                          [entry[1] for entry in data["queue_pending"]])
        async with self.client.get("/api/history/" + queued["prompt_id"]) as response:
            self.assertEqual(await response.json(), {})
        async with self.client.post("/api/interrupt", json={}) as response:
            self.assertEqual(response.status, 403)
        self.fake.finish(first[1]["prompt_id"])
        await self.until(lambda: len(self.fake.posts) == 2)

    async def test_unknown_extension_gpu_submit_is_default_denied(self):
        # A future custom-node POST must not bypass the broker owner queue.
        status, first = await self.post(1)
        self.assertEqual(status, 200)
        await self.until(lambda: len(self.fake.posts) == 1)
        async with self.client.post("/thirdparty_submit", json=self.body(2)) as resp:
            self.assertEqual(resp.status, 403)
            self.assertEqual((await resp.json())["error"], "unaudited_mutating_endpoint_denied")
        self.assertEqual(len(self.fake.posts), 1)
        async with self.client.delete("/api/history", json={}) as resp:
            self.assertEqual(resp.status, 403)
        async with self.client.post("/api/upload/model", json={}) as resp:
            self.assertEqual(resp.status, 403)
        self.fake.finish(first["prompt_id"])
        await self.until(lambda: self.broker.owner() is None)

    @staticmethod
    def external_headers():
        return {"Authorization": "Bearer " + TEST_EXTERNAL_TOKEN}

    async def test_external_credential_is_required_even_when_header_present(self):
        # Missing broker-side provisioning must fail closed, not trust headers.
        previous = self.broker.external_auth_digest
        try:
            self.broker.external_auth_digest = None
            async with self.client.post("/broker/external/acquire",
                                        json={"client": "kobold-gateway"},
                                        headers=self.external_headers()) as response:
                self.assertEqual(response.status, 401)
            self.assertIsNone(self.broker.external()["lease_id"])
        finally:
            self.broker.external_auth_digest = previous

    async def test_state_dir_swap_after_validation_cannot_redirect_durable_files(self):
        # Deterministic interleaving at the first fchmod(root_fd): the name
        # changes after O_NOFOLLOW validation, before lock/SQLite creation.
        # No GPU, network backend or real application state is involved.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = base / "state"
            displaced = base / "original-state"
            attacker = base / "redirect-target"
            state.mkdir()
            attacker.mkdir()
            actual_fchmod = m.os.fchmod
            switched = False

            def interleave(fd, mode):
                nonlocal switched
                result = actual_fchmod(fd, mode)
                if not switched:
                    state.rename(displaced)
                    state.symlink_to(attacker, target_is_directory=True)
                    switched = True
                return result

            candidate = None
            try:
                with mock.patch.object(m.os, "fchmod", side_effect=interleave):
                    candidate = m.Broker(state, "http://127.0.0.1:9")
                self.assertTrue(switched)
                self.assertTrue((displaced / "broker.lock").is_file())
                self.assertTrue((displaced / "broker.sqlite3").is_file())
                self.assertFalse((attacker / "broker.lock").exists())
                self.assertFalse((attacker / "broker.sqlite3").exists())
            finally:
                if candidate is not None:
                    await candidate.stop()

            # Pinned original state remains recoverable under its new name.
            recovered = m.Broker(displaced, "http://127.0.0.1:9")
            await recovered.stop()

    async def _assert_sqlite_main_file_alias_rejected(self, alias_type):
        # Disposable CPU-only fixture. Broker must reject an external DB
        # alias BEFORE SQLite switches that unrelated file to WAL mode.
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = base / "state"
            other = base / "other"
            state.mkdir()
            other.mkdir()
            outside = other / "untouched.sqlite3"
            connection = sqlite3.connect(outside)
            connection.execute("CREATE TABLE existing(k INTEGER)")
            connection.execute("INSERT INTO existing VALUES(1)")
            connection.commit()
            connection.close()
            before = hashlib.sha256(outside.read_bytes()).hexdigest()
            alias = state / "broker.sqlite3"
            if alias_type == "symlink":
                alias.symlink_to(outside)
            elif alias_type == "hardlink":
                alias.hardlink_to(outside)
            else:
                raise AssertionError("unknown fixture alias")

            candidate = None
            try:
                with self.assertRaisesRegex(ValueError, "unsafe_broker_sqlite_file"):
                    candidate = m.Broker(state, "http://127.0.0.1:9")
            finally:
                if candidate is not None:
                    await candidate.stop()
            self.assertEqual(hashlib.sha256(outside.read_bytes()).hexdigest(), before)

    async def test_sqlite_main_symlink_rejected_before_external_mutation(self):
        await self._assert_sqlite_main_file_alias_rejected("symlink")

    async def test_sqlite_main_hardlink_rejected_before_external_mutation(self):
        await self._assert_sqlite_main_file_alias_rejected("hardlink")

    async def _assert_unsafe_existing_lock_rejected(self, variant):
        # Private, disposable recovery fixture; no real Comfy or GPU.
        with tempfile.TemporaryDirectory(prefix="broker-lock-alias-") as directory:
            base = Path(directory)
            state = base / "state"
            state.mkdir()
            lock = state / "broker.lock"
            outside = base / "external.lock"
            if variant == "hardlink":
                outside.write_bytes(b"outside-unchanged")
                lock.hardlink_to(outside)
            elif variant == "permissive":
                lock.write_bytes(b"outside-unchanged")
                lock.chmod(0o644)
            elif variant == "fifo":
                os.mkfifo(lock, 0o600)
            else:
                raise AssertionError("unexpected fixture")

            candidate = None
            try:
                with self.assertRaisesRegex(ValueError, "unsafe_broker_lock_file"):
                    candidate = m.Broker(state, "http://127.0.0.1:9")
            finally:
                if candidate is not None:
                    await candidate.stop()
            if variant == "hardlink":
                self.assertEqual(outside.read_bytes(), b"outside-unchanged")

    async def test_existing_broker_lock_hardlink_rejected(self):
        await self._assert_unsafe_existing_lock_rejected("hardlink")

    async def test_existing_broker_lock_permissive_mode_rejected(self):
        await self._assert_unsafe_existing_lock_rejected("permissive")

    async def test_existing_broker_lock_fifo_rejected(self):
        await self._assert_unsafe_existing_lock_rejected("fifo")

    async def test_symlink_state_dir_must_not_change_target_or_create_db(self):
        # Disposable state only: an alias to a real directory must fail
        # before broker chmod/lock/SQLite can touch the referenced target.
        real = Path(self.tmp.name) / "aliased-state-target"
        real.mkdir()
        real.chmod(0o750)
        alias = Path(self.tmp.name) / "broker-state-alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "broker_state_dir_symlink"):
            m.Broker(alias, "http://127.0.0.1:9")
        self.assertEqual(real.stat().st_mode & 0o777, 0o750)
        self.assertFalse((real / "broker.sqlite3").exists())

    async def test_external_digest_file_rejects_world_access_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lease.sha256"
            data = hashlib.sha256(TEST_EXTERNAL_TOKEN.encode()).hexdigest()
            path.write_text(data + "\n")
            path.chmod(0o600)
            self.assertEqual(m.load_external_auth_digest(path), data)
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "insecure_external_auth_digest_file"):
                m.load_external_auth_digest(path)
            path.chmod(0o600)
            path.write_text("not-a-digest")
            with self.assertRaisesRegex(ValueError, "invalid_external_auth_digest_file"):
                m.load_external_auth_digest(path)
            link = Path(directory) / "alias.sha256"
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "insecure_external_auth_digest_file"):
                m.load_external_auth_digest(link)

    async def test_anonymous_external_lease_spoof_is_denied(self):
        # RED: mere client-name knowledge must never create a GPU owner.
        await self.until(lambda: self.broker.fault is None)
        async with self.client.post("/broker/external/acquire",
                                    json={"client": "kobold-gateway"}) as response:
            self.assertEqual(response.status, 401)
        self.assertIsNone(self.broker.external()["lease_id"])
        self.assertEqual(len(self.fake.posts), 0)

    async def test_wrong_token_cannot_acquire_or_release_gpu_lease(self):
        await self.until(lambda: self.broker.fault is None)
        for value in ("Bearer wrong-but-long-token-0123456789abcdef", ""):
            async with self.client.post("/broker/external/acquire",
                                        json={"client": "kobold-gateway"},
                                        headers={"Authorization": value}) as response:
                self.assertEqual(response.status, 401)
        self.assertIsNone(self.broker.external()["lease_id"])
        async with self.client.post("/broker/external/acquire",
                                    json={"client": "kobold-gateway"},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 200)
            lease = (await response.json())["lease_id"]
        for headers in ({}, {"Authorization": "Bearer wrong-but-long-token-0123456789abcdef"}):
            async with self.client.post("/broker/external/release",
                                        json={"lease_id": lease}, headers=headers) as response:
                self.assertEqual(response.status, 401)
            self.assertEqual(self.broker.external()["lease_id"], lease)
        async with self.client.post("/broker/external/release",
                                    json={"lease_id": lease},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 200)
        self.assertIsNone(self.broker.external()["lease_id"])

    async def test_free_with_known_lease_id_still_requires_external_credential(self):
        # RED: possession of a lease UUID alone cannot authorize GPU memory eviction.
        await self.until(lambda: self.broker.fault is None)
        async with self.client.post("/broker/external/acquire",
                                    json={"client": "kobold-gateway"},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 200)
            lease = (await response.json())["lease_id"]
        for path in ("/free", "/api/free"):
            for token in (None, "Bearer wrong-but-long-token-0123456789abcdef"):
                headers = {"X-GPU-Lease-ID": lease}
                if token is not None:
                    headers["Authorization"] = token
                async with self.client.post(path, json={"unload_models": True},
                                            headers=headers) as response:
                    self.assertEqual(response.status, 401)
                self.assertEqual(self.broker.external_free_state(), "IDLE")
                self.assertEqual(self.fake.free_posts, [])
        async with self.client.post("/api/free", json={"unload_models": True},
                                    headers={**self.external_headers(),
                                             "X-GPU-Lease-ID": lease}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(len(self.fake.free_posts), 1)
        self.assertIsNone(self.fake.free_posts[0]["authorization"])
        async with self.client.post("/broker/external/release",
                                    json={"lease_id": lease},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 200)

    async def test_external_gpu_lease_blocks_comfy_and_guards_free(self):
        async with self.client.post("/broker/external/acquire",
                                    json={"client": "kobold-gateway"},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 200)
            lease = (await response.json())["lease_id"]
        async with self.client.post("/free", json={"unload_models": True}) as response:
            self.assertEqual(response.status, 401)
        async with self.client.post("/free", json={"unload_models": True},
                                    headers={**self.external_headers(), "X-GPU-Lease-ID": lease}) as response:
            self.assertEqual(response.status, 200)
        queued = await self.post(77)
        self.assertEqual(queued[0], 200)
        await asyncio.sleep(.08)
        self.assertEqual(self.fake.posts, [])
        async with self.client.get("/queue") as response:
            self.assertIn("external-gpu-lease",
                          [e[1] for e in (await response.json())["queue_pending"]])
        async with self.client.post("/broker/external/release",
                                    json={"lease_id": str(uuid.uuid4())},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 409)
        async with self.client.post("/broker/external/release",
                                    json={"lease_id": lease},
                                    headers=self.external_headers()) as response:
            self.assertEqual((await response.json())["released"], True)
        await self.until(lambda: len(self.fake.posts) == 1)

    async def test_external_lease_survives_broker_restart(self):
        async with self.client.post("/broker/external/acquire",
                                    json={"client": "kobold-gateway"},
                                    headers=self.external_headers()) as response:
            lease = (await response.json())["lease_id"]
        await self.stop_broker()
        await self.start_broker()
        self.assertEqual(self.broker.status()["external_owner"], "kobold-gateway")
        await self.post(9)
        await asyncio.sleep(.08)
        self.assertEqual(self.fake.posts, [])
        async with self.client.post("/broker/external/release",
                                    json={"lease_id": lease},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 200)
        await self.until(lambda: len(self.fake.posts) == 1)

    async def test_invalid_comfy_prompt_yields_terminal_error_history(self):
        self.fake.submit_mode = "reject"
        receipt = await self.post(1)
        pid = receipt[1]["prompt_id"]
        await self.until(lambda: self.broker.db.execute(
            "SELECT state FROM jobs WHERE prompt_id=?", (pid,)).fetchone()[0] == "REJECTED")
        async with self.client.get("/history/" + pid) as response:
            self.assertEqual((await response.json())[pid]["status"]["status_str"], "error")
        self.assertIsNone(self.broker.owner())
        self.fake.submit_mode = None
        await self.post(2)
        await self.until(lambda: len(self.fake.posts) == 1)

    async def test_backend_500_after_accept_never_resubmits(self):
        self.fake.submit_mode = "accepted_500"
        receipt = await self.post(1)
        pid = receipt[1]["prompt_id"]
        await self.until(lambda: len(self.fake.posts) == 1)
        await self.until(lambda: self.broker.db.execute(
            "SELECT state FROM jobs WHERE prompt_id=?", (pid,)).fetchone()[0] in ("UNCERTAIN", "ACTIVE"))
        self.fake.submit_mode = None
        await self.post(2)
        await asyncio.sleep(.08)
        self.assertEqual(len(self.fake.posts), 1)
        self.fake.finish(pid)
        await self.until(lambda: len(self.fake.posts) == 2)
        self.assertEqual(self.fake.posts.count(pid), 1)

    async def test_backend_500_without_accept_is_unknown_fail_closed(self):
        self.fake.submit_mode = "unaccepted_500"
        receipt = await self.post(1)
        pid = receipt[1]["prompt_id"]
        await self.until(lambda: self.broker.owner() == pid and
                         self.broker.db.execute(
                             "SELECT state FROM jobs WHERE prompt_id=?", (pid,)).fetchone()[0] == "UNCERTAIN")
        self.fake.submit_mode = None
        await self.post(2)
        await asyncio.sleep(.1)
        self.assertEqual(len(self.fake.posts), 0)
        self.assertEqual(self.broker.owner(), pid)

    async def test_malformed_queue_is_fail_closed(self):
        self.fake.queue_malformed = True
        await self.until(lambda: self.broker.status()["fault"] is not None)
        await self.post(4)
        await asyncio.sleep(.08)
        self.assertEqual(self.fake.posts, [])
        self.fake.queue_malformed = False
        await self.until(lambda: len(self.fake.posts) == 1)

    async def test_expired_diagnostic_lease_never_allows_takeover(self):
        first = await self.post(1)
        await self.until(lambda: len(self.fake.posts) == 1)
        self.broker.db.execute("UPDATE owner SET lease_until=0 WHERE singleton=1")
        self.assertTrue(self.broker.status()["owner_lease_expired"])
        await self.post(2)
        await asyncio.sleep(.08)
        self.assertEqual(len(self.fake.posts), 1)
        self.fake.finish(first[1]["prompt_id"])
        await self.until(lambda: len(self.fake.posts) == 2)

    async def test_external_acquire_refused_with_comfy_owner(self):
        await self.post(1)
        await self.until(lambda: len(self.fake.posts) == 1)
        async with self.client.post("/broker/external/acquire",
                                    json={"client": "kobold-gateway"},
                                    headers=self.external_headers()) as response:
            self.assertEqual(response.status, 409)

    async def test_websocket_api_alias(self):
        async with self.client.ws_connect("/api/ws?clientId=alias") as ws:
            await ws.send_str("alias")
            self.assertEqual((await ws.receive()).data, "echo:alias")

    async def test_queue_capacity_bounded(self):
        await self.stop_broker()
        self.broker = m.Broker(self.tmp.name, str(self.backend_server.make_url("/")).rstrip("/"),
                               wait_seconds=2, poll_seconds=.02, max_queue=1)
        self.server = TestServer(m.make_app(self.broker))
        self.client = TestClient(self.server)
        await self.client.start_server()
        await self.until(lambda: self.broker.last_poll > 0)
        await self.post(1)
        await self.until(lambda: len(self.fake.posts) == 1)
        self.assertEqual((await self.post(2))[0], 200)
        self.assertEqual((await self.post(3))[0], 503)

    async def test_retry_with_new_client_id_and_prompt_id_deduplicates(self):
        original = self.body(4)
        original["prompt_id"] = str(uuid.uuid4())
        async with self.client.post("/prompt", json=original,
                                    headers={"Idempotency-Key": "test-reconnect-4"}) as response:
            first = await response.json()
        retry = self.body(4)
        retry["client_id"] = "reconnected-client"
        retry["prompt_id"] = str(uuid.uuid4())
        async with self.client.post("/api/prompt", json=retry,
                                    headers={"Idempotency-Key": "test-reconnect-4"}) as response:
            second = await response.json()
        self.assertEqual(first["prompt_id"], second["prompt_id"])
        await self.until(lambda: len(self.fake.posts) == 1)
        self.assertEqual(self.fake.posts, [first["prompt_id"]])

    async def test_preexisting_backend_prompt_id_never_reused(self):
        pid = str(uuid.uuid4())
        self.fake.history[pid] = {"status": {"status_str": "success", "completed": True},
                                  "outputs": {}}
        body = self.body(5)
        body["prompt_id"] = pid
        async with self.client.post("/prompt", json=body,
                                    headers={"Idempotency-Key": "test-pid-reservation"}) as response:
            self.assertEqual((await response.json())["prompt_id"], pid)
        await self.until(lambda: self.broker.db.execute(
            "SELECT state FROM jobs WHERE prompt_id=?", (pid,)).fetchone()[0] == "REJECTED")
        self.assertEqual(self.fake.posts, [])
        async with self.client.get("/history/" + pid) as response:
            self.assertEqual((await response.json())[pid]["status"]["status_str"], "error")

    async def test_per_client_queue_wait_is_bounded(self):
        await self.post(1)
        await self.until(lambda: len(self.fake.posts) == 1)
        async with self.client.post("/prompt", json=self.body(2),
                                    headers={"X-Broker-Queue-Wait-Seconds": "1",
                                             "Idempotency-Key": "test-wait-2"}) as response:
            self.assertEqual(response.status, 200)
            pid = (await response.json())["prompt_id"]
        await self.until(lambda: self.broker.db.execute(
            "SELECT state FROM jobs WHERE prompt_id=?", (pid,)).fetchone()[0] == "EXPIRED",
            timeout=1.8)
        self.assertEqual(len(self.fake.posts), 1)
        async with self.client.post("/prompt", json=self.body(3),
                                    headers={"X-Broker-Queue-Wait-Seconds": "999",
                                             "Idempotency-Key": "test-wait-3"}) as response:
            self.assertEqual(response.status, 400)
        async with self.client.post("/prompt", json=self.body(3),
                                    headers={"X-Broker-Queue-Wait-Seconds": "NaN",
                                             "Idempotency-Key": "test-wait-3"}) as response:
            self.assertEqual(response.status, 400)

    async def test_rejected_idempotent_reconnect_is_explicitly_terminal(self):
        # RED: a backend-rejected graph cannot be admitted again through a
        # success-shaped 200 response on either prompt alias.
        self.fake.submit_mode = "reject"
        status, first = await self.post(72)
        self.assertEqual(status, 200)  # immediate durable queued receipt
        pid = first["prompt_id"]
        await self.until(lambda: self.broker.db.execute(
            "SELECT state FROM jobs WHERE prompt_id=?", (pid,)).fetchone()[0] == "REJECTED")
        self.assertIsNone(self.broker.owner())
        self.fake.submit_mode = None
        for route in ("/prompt", "/api/prompt"):
            async with self.client.post(route, json=self.body(72),
                                        headers={"Idempotency-Key": "test-action-72"}) as response:
                self.assertEqual(response.status, 409)
                answer = await response.json()
                self.assertEqual(answer["error"], "broker_job_rejected")
                self.assertEqual(answer["reason"], "comfy_validation_rejected")
                self.assertEqual(answer["prompt_id"], pid)
                self.assertIs(answer["retry_safe"], False)
        self.assertEqual(self.fake.posts, [])
        self.assertEqual(self.broker.db.execute(
            "SELECT COUNT(*) FROM jobs WHERE key=?", ("explicit:test-action-72",)).fetchone()[0], 1)

    async def test_expired_idempotent_reconnect_is_explicitly_terminal(self):
        # RED: a durable EXPIRED action must not be reported as a fresh 200
        # receipt, because no GPU job can ever run for that action key.
        body = self.body(71)
        key = "explicit:expired-action"
        digest = hashlib.sha256(m.canonical({"prompt": body["prompt"]}).encode()).hexdigest()
        async with self.broker.guard:
            row, error = self.broker.enqueue(key, digest, body)
            self.assertIsNone(error)
            self.broker.expire(row["prompt_id"])
        for route in ("/prompt", "/api/prompt"):
            async with self.client.post(route, json=body,
                                        headers={"Idempotency-Key": "expired-action"}) as response:
                self.assertEqual(response.status, 410)
                answer = await response.json()
                self.assertEqual(answer["error"], "queue_wait_expired")
                self.assertEqual(answer["prompt_id"], row["prompt_id"])
                self.assertIs(answer["retry_safe"], False)
        self.assertEqual(self.fake.posts, [])
        self.assertEqual(self.broker.db.execute(
            "SELECT COUNT(*) FROM jobs WHERE key=?", (key,)).fetchone()[0], 1)

    async def test_real_multipart_upload_passes_through_alias(self):
        from aiohttp import FormData
        form = FormData()
        form.add_field("image", b"\x89PNG\r\n\x1a\nfake", filename="test.png",
                       content_type="image/png")
        async with self.client.post("/api/upload/image", data=form) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(),
                             {"filename": "test.png", "size": 12})

    def test_duplicate_backend_queue_ids_are_malformed(self):
        pid = str(uuid.uuid4())
        for running, pending in (([[0, pid, {}], [1, pid, {}]], []),
                                 ([[0, pid, {}]], [[1, pid, {}]])):
            with self.subTest(running=running, pending=pending):
                with self.assertRaisesRegex(ValueError, "duplicate_queue_prompt_id"):
                    m.queue_ids({"queue_running": running, "queue_pending": pending})

    async def test_duplicate_owner_prompt_in_backend_queue_fences_dispatch(self):
        status, first = await self.post(88)
        self.assertEqual(status, 200)
        pid = first["prompt_id"]
        await self.until(lambda: pid in self.fake.running)
        # Reproduces backend queue ambiguity without submitting a GPU job.
        self.fake.running.append(pid)
        await self.until(lambda: self.broker.status()["fault"] == "reconcile_ValueError")
        self.assertEqual(self.broker.owner(), pid)
        self.assertEqual(len(self.fake.posts), 1)
        status, second = await self.post(89)
        await asyncio.sleep(.08)
        self.assertEqual(len(self.fake.posts), 1)
        self.assertEqual(self.broker.owner(), pid)

    async def test_second_broker_same_state_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "another_broker"):
            m.Broker(self.tmp.name, str(self.backend_server.make_url("/")))


if __name__ == "__main__":
    unittest.main()
