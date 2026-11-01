"""Status-only keyset pager regressions. Local disposable SQLite, never a cloud wake."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import scheduled_wake_mesh as m

RECEIPT = "a" * 64
RUN_ID = "01234567-89ab-4cde-8fab-0123456789ab"


class WakeStatusPages(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "state").mkdir()

    def add(self, target, number, at=50.0):
        sha = hashlib.sha256(f"{target}:{number}".encode()).hexdigest()
        m.defer(self.root, target, "source_pr_ready", sha,
                "operator", reason="synthetic_pending_event", now=at)
        return sha

    def scan(self, target="renderer", limit=31):
        cursor = None
        seen = []
        for _ in range(30):
            page = m.status(self.root, target=target, limit=limit, cursor=cursor)
            seen.extend(page["pending"])
            cursor = page["next_cursor"]
            if not cursor:
                return seen
        self.fail("unbounded pagination")

    def test_filter_before_limit_preserves_recent_role_event(self):
        for i in range(205):
            self.add("chief", i, at=float(i))
        sha = self.add("renderer", 700, at=900.0)
        global_page = m.status(self.root)
        self.assertEqual(len(global_page["pending"]), 200)
        self.assertTrue(global_page["truncated"])
        self.assertEqual(global_page["pending_total"], 206)
        r = m.status(self.root, target="renderer")
        self.assertEqual([x["evidence_sha"] for x in r["pending"]], [sha])
        self.assertEqual((r["filtered_total"], r["global_total"]), (1, 206))

    def test_equal_timestamps_never_skip_or_repeat(self):
        expected = {self.add("renderer", i, at=100.0) for i in range(239)}
        rows = self.scan(limit=27)
        self.assertEqual(len(rows), 239)
        self.assertEqual({x["evidence_sha"] for x in rows}, expected)
        self.assertEqual(len(set(x["evidence_sha"] for x in rows)), len(rows))

    def test_acknowledge_previous_page_does_not_skip(self):
        expected = [self.add("renderer", i, at=100.0) for i in range(80)]
        page = m.status(self.root, target="renderer", limit=17)
        old = page["pending"][0]
        m.acknowledge(self.root, "renderer", old["event_kind"],
                      old["evidence_sha"], "renderer", RECEIPT, RUN_ID, now=111)
        cursor = page["next_cursor"]
        after = []
        while cursor:
            response = m.status(self.root, target="renderer", limit=17, cursor=cursor)
            after.extend(x["evidence_sha"] for x in response["pending"])
            cursor = response["next_cursor"]
        self.assertEqual(len(page["pending"])+len(after), 80)
        self.assertEqual(len(set(x["evidence_sha"] for x in page["pending"]+[
                         {"evidence_sha": a} for a in after])), 80)
        self.assertEqual(set(x["evidence_sha"] for x in page["pending"]) | set(after),
                         set(expected))

    def test_new_arrivals_require_fresh_scan(self):
        for i in range(54):
            self.add("renderer", i, at=float(i))
        first = m.status(self.root, target="renderer", limit=19)
        newcomer = self.add("renderer", 10000, at=1.5)
        cursor = first["next_cursor"]
        rest = []
        while cursor:
            page = m.status(self.root, target="renderer", limit=19, cursor=cursor)
            rest.extend(x["evidence_sha"] for x in page["pending"])
            cursor = page["next_cursor"]
        self.assertNotIn(newcomer, rest)
        self.assertIn(newcomer, [x["evidence_sha"] for x in self.scan(limit=19)])

    def test_bad_cursors_filters_and_limits_fail(self):
        for i in range(4):
            self.add("renderer", i, at=float(i))
        first = m.status(self.root, target="renderer", limit=2)
        cursor = first["next_cursor"]
        self.assertTrue(cursor)
        for bad in ("@bad", "e30", "A"*2000, "Z"*9, "____") :
            with self.subTest(bad=bad[:12]), self.assertRaises(ValueError):
                m.status(self.root, target="renderer", limit=2, cursor=bad)
        bad_data = m._parse_status_cursor(cursor, "renderer", 2)
        self.assertTrue(bad_data)
        import base64
        import json
        payload = json.loads(base64.urlsafe_b64decode(cursor+"="*(-len(cursor)%4)))
        payload["after"][1] = ["invalid", "role"]
        with self.assertRaises(ValueError):
            m.status(self.root, target="renderer", limit=2,
                     cursor=m._status_cursor(payload))
        with self.assertRaises(ValueError):
            m.status(self.root, target="chief", limit=2, cursor=cursor)
        with self.assertRaises(ValueError):
            m.status(self.root, target="renderer", limit=3, cursor=cursor)
        for bad in (-1, 0, 201, True, "two"):
            with self.subTest(limit=bad), self.assertRaises(ValueError):
                m.status(self.root, target="renderer", limit=bad)
        with self.assertRaises(ValueError):
            m.status(self.root, target="bad_role")

    def test_repeat_status_never_changes_receipts_or_consumption(self):
        sha = self.add("renderer", 1)
        res = m.check(self.root, "renderer", "source_pr_ready", sha, "operator",
                      reserve=True, now=100)
        m.record_outcome(self.root, "renderer", "source_pr_ready", sha,
                         "operator", res["reservation_id"], "unknown", RECEIPT, now=102)
        dbp = self.root / "state" / "scheduled-wake-history.sqlite3"
        def snapshot():
            with sqlite3.connect(dbp) as db:
                return tuple(tuple(db.execute("SELECT * FROM "+table+" ORDER BY rowid"))
                             for table in ("pending_signal", "wake_attempt", "wake_outcome", "wake_signal"))
        before = snapshot()
        for _ in range(3):
            page = m.status(self.root, target="renderer", limit=1)
            self.assertEqual(page["pending"][0]["delivery"]["status"], "unknown")
        self.assertEqual(snapshot(), before)

    def test_cli_status_role_and_cursor(self):
        for i in range(3):
            self.add("renderer", i)
        path = Path(m.__file__)
        cmd = [sys.executable, str(path), "--root", str(self.root),
               "--status", "--target", "renderer", "--limit", "2"]
        first = json.loads(subprocess.check_output(cmd, text=True))
        self.assertEqual(len(first["pending"]), 2)
        cmd += ["--cursor", first["next_cursor"]]
        last = json.loads(subprocess.check_output(cmd, text=True))
        self.assertEqual(len(last["pending"]), 1)
        self.assertIsNone(last["next_cursor"])


if __name__ == "__main__":
    unittest.main()
