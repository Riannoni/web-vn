"""Source-only coordinator invariant tests. No live model/GPU/network needed."""
import importlib.util
import pathlib
import tempfile
import unittest

FILE = pathlib.Path(__file__).resolve().parents[1] / "coordinator.py"
sp=importlib.util.spec_from_file_location("pilot",FILE)
m=importlib.util.module_from_spec(sp)
sp.loader.exec_module(m)

class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=m.database(pathlib.Path(self.temp.name)/"tasks.db")
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()
    def add(self,id="t1",paths=None,deps=()):
        m.add(self.db,id,"source_inventory",paths or ["docs"],deps)
    def test_independent_two_claims(self):
        self.add("a",["docs"])
        self.add("b",["scripts"])
        x=m.claim(self.db,"w1",now=100)
        y=m.claim(self.db,"w2",now=100)
        self.assertEqual({x["id"],y["id"]},{"a","b"})
        self.assertIsNone(m.claim(self.db,"w3",now=100))
    def test_overlapping_paths_dont_claim(self):
        self.add("a",["docs"])
        self.add("b",["docs/AGENTS.md"])
        x=m.claim(self.db,"w1",now=100)
        self.assertIsNone(m.claim(self.db,"w2",now=100))
    def test_dependency_waits_for_verified_result(self):
        self.add("a",["docs"])
        self.add("b",["scripts"],["a"])
        x=m.claim(self.db,"w1",now=100)
        self.assertIsNone(m.claim(self.db,"w2",now=100))
        evidence={"sha256":"a"*64}
        self.assertTrue(m.complete(self.db,x["id"],"w1",x["fence"],evidence,now=101))
        self.assertIsNone(m.claim(self.db,"w2",now=102))
        self.db.execute("UPDATE task SET state='done' WHERE id='a'")
        self.assertEqual(m.claim(self.db,"w2",now=103)["id"],"b")
    def test_expired_lease_fenced(self):
        self.add()
        x=m.claim(self.db,"w1",ttl=5,now=100)
        y=m.claim(self.db,"w2",ttl=5,now=106)
        self.assertIsNone(y)
        self.assertFalse(m.complete(self.db,"t1","w1",x["fence"],{"sha256":"f"},now=107))
        self.assertEqual(self.db.execute("SELECT state FROM task WHERE id='t1'").fetchone()[0],"blocked")
    def test_two_failed_attempts_block(self):
        self.add()
        x=m.claim(self.db,"w1",ttl=5,now=100)
        y=m.claim(self.db,"w2",ttl=5,now=106)
        self.assertIsNone(m.claim(self.db,"w3",now=112))
        row=self.db.execute("SELECT state FROM task WHERE id='t1'").fetchone()
        self.assertEqual(row["state"],"blocked")
    def test_worker_failure_blocks_without_automatic_retry(self):
        self.add()
        lease=m.claim(self.db,"worker",now=100)
        self.assertTrue(m.complete(self.db,"t1","worker",lease["fence"],
                                    {"sha256":"x"*64},now=101,passed=False))
        state=self.db.execute("SELECT state FROM task WHERE id='t1'").fetchone()["state"]
        self.assertEqual(state,"blocked")
        self.assertIsNone(m.claim(self.db,"next",now=102))

    def test_wrong_owner_cannot_heartbeat_or_complete(self):
        self.add()
        x=m.claim(self.db,"w1",ttl=5,now=100)
        self.assertFalse(m.heartbeat(self.db,"t1","wrong",x["fence"],now=101))
        self.assertFalse(m.complete(self.db,"t1","wrong",x["fence"],{"sha256":"x"},now=101))
    def test_invalid_scope_rejected(self):
        for path in ("/etc", "../secrets", "docs/../../file"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.add("bad",[path])
    def test_stale_worker_cannot_replace_new_attempt_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            folder=pathlib.Path(td)
            self.add()
            first=m.claim(self.db,"old",ttl=5,now=100)
            self.assertIsNone(m.claim(self.db,"new",ttl=5,now=106))
            self.db.execute("UPDATE task SET state='pending' WHERE id='t1'")
            second=m.claim(self.db,"new",ttl=5,now=107)
            fresh=b'{"result":"new"}'
            fresh_path=m.persist_evidence(folder,"t1",second["fence"],fresh)
            digest=__import__("hashlib").sha256(fresh).hexdigest()
            self.assertTrue(m.complete(self.db,"t1","new",second["fence"],
                {"sha256":digest,"path":fresh_path.name},now=108))
            old_path=m.persist_evidence(folder,"t1",first["fence"],b'{"result":"old"}')
            self.assertFalse(m.complete(self.db,"t1","old",first["fence"],
                {"sha256":"bad","path":old_path.name},now=109))
            self.assertNotEqual(fresh_path,old_path)
            self.assertEqual(fresh_path.read_bytes(),fresh)
            self.assertEqual(self.db.execute("SELECT state FROM task WHERE id='t1'").fetchone()[0],"review_pending")

    def test_evidence_file_is_exclusive_and_private(self):
        import stat
        with tempfile.TemporaryDirectory() as td:
            folder=pathlib.Path(td)
            path=m.persist_evidence(folder,"../malicious","fence1",b"proof")
            self.assertEqual(path.parent,folder)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            with self.assertRaises(FileExistsError):
                m.persist_evidence(folder,"../malicious","fence1",b"overwrite")
            self.assertEqual(path.read_bytes(),b"proof")

    def test_legacy_source_worker_cannot_accidentally_consume_golden_visual_job(self):
        m.add(self.db, "G-99", "visual_evidence", [], goal="Original pixel evidence")
        self.assertIsNone(m.claim(self.db,"legacy-source",now=100,
                                  allowed_actions={"source_inventory","source_compile"}))
        x=m.claim(self.db,"golden-worker",now=100,lane="G")
        self.assertEqual(x["id"],"G-99")
        self.assertEqual(x["action"],"visual_evidence")

    def test_evidence_is_required(self):
        self.add()
        x=m.claim(self.db,"w1",now=100)
        with self.assertRaises(ValueError):
            m.complete(self.db,"t1","w1",x["fence"],{},now=101)
    def test_status_has_no_secret(self):
        self.add()
        x=m.claim(self.db,"w1",now=100)
        d=m.snapshot(self.db)
        self.assertEqual(d["max_parallel"],4)
        self.assertNotIn("fence",str(d))
        self.assertEqual(d["tasks"][0]["owner"],"w1")

if __name__=="__main__":
    unittest.main()
