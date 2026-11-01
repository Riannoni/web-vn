"""Queue continuity: deterministic planner, quarantine scopes and atomic claims."""
import datetime
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import coordinator as c
import teamctl as m

TASK_CATALOG=ROOT/"task_catalog.py"
spec=importlib.util.spec_from_file_location("catalog_test",TASK_CATALOG)
catalog=importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

def git(path,*cmd):
    subprocess.run(["git","-C",str(path),*cmd],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.old=(m.ROOT,m.DB)
        self.addCleanup(self.restore)
        m.ROOT=self.root
        m.DB=self.root/"state/team.sqlite3"
        m.DB.parent.mkdir()
        for lane in m.LANES.values():
            wt=self.root/("lane-"+lane)
            wt.mkdir()
            git(wt,"init","-q")
            git(wt,"-c","user.name=Test","-c","user.email=invalid@example.invalid","commit","--allow-empty","-qm","start")
        db=c.database(m.DB)
        db.execute("CREATE TABLE team_meta(k TEXT PRIMARY KEY,v TEXT NOT NULL)")
        db.execute("CREATE TABLE claim_baselines(task_id TEXT PRIMARY KEY, head TEXT NOT NULL)")
        db.execute("INSERT INTO team_meta VALUES ('state','active')")
        c.add(db,"Q-06","source_inventory",["worker/base.py"],goal="test")
        db.execute("UPDATE task SET state='done' WHERE id='Q-06'")
        c.add(db,"R-07","source_inventory",["worker/staged_source_job_hook.py"],goal="test")
        db.execute("UPDATE task SET state='blocked' WHERE id='R-07'")
        db.close()
    def restore(self):
        m.ROOT,m.DB=self.old
    def write(self,items):
        p=self.root/"catalog.json"
        p.write_text(json.dumps(items))
        return p
    def item(self,id,dep=None,paths=None):
        return dict(id=id,lane=id[0],goal="render-v1 #20 typed source test",
                    instructions="Isolated source-only causal negative regression and no GPU production or private data operations.",
                    paths=paths or ["worker/test_"+id+".py"],
                    dependencies=[dep] if dep else [],priority=80)
    def test_empty_catalog_preserves_existing_tasks_leases_and_history(self):
        with m.open_db() as db:
            for tid, state in (("Q-91", "pending"), ("G-91", "review_pending"),
                               ("R-91", "leased"), ("S-91", "blocked")):
                c.add(db, tid, "source_inventory", ["worker/existing.py"], goal="existing")
                db.execute("UPDATE task SET state=?,owner=?,fence=?,attempt=1,lease_until=1,result=? WHERE id=?",
                           (state, "existing-owner", "existing-fence", '{"submission":"unknown"}', tid))
                c.emit(db, tid, "existing_evidence", "preserve unknown submission")
            db.execute("INSERT INTO claim_baselines VALUES ('R-91','existing-source-sha')")
            before = list(db.iterdump())
        empty = self.write([])
        for _ in range(2):
            self.assertEqual(catalog.replenish(self.root, empty), {"state": "active", "enqueued": []})
        with m.open_db() as db:
            self.assertEqual(list(db.iterdump()), before)

    def test_atomic_idempotent_and_prequeued_dependency(self):
        f=self.write([self.item("Q-07","Q-06"),self.item("Q-08","Q-07")])
        self.assertEqual(catalog.replenish(self.root,f)["enqueued"],["Q-07","Q-08"])
        self.assertEqual(catalog.replenish(self.root,f)["enqueued"],[])
        with m.open_db() as db:
            self.assertEqual(db.execute("SELECT state FROM task WHERE id='Q-08'").fetchone()[0],"pending")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM event WHERE kind='enqueued' AND task_id='Q-07'").fetchone()[0],1)
        claimed=m.claim(m.open_db(),"Q","owner1")
        self.assertTrue(claimed["claimed"])
        self.assertEqual(claimed["id"],"Q-07")
    def test_unrelated_blocked_lane_can_progress(self):
        f=self.write([self.item("R-08",paths=["worker/producer_audit.py"])])
        self.assertEqual(catalog.replenish(self.root,f)["enqueued"],["R-08"])
        with m.open_db() as db:
            task=m.claim(db,"R","owner2")
            self.assertTrue(task["claimed"])
            self.assertEqual(task["id"],"R-08")
    def test_same_scope_blocked_task_still_fences(self):
        f=self.write([self.item("R-08",paths=["worker/staged_source_job_hook.py"])])
        catalog.replenish(self.root,f)
        with m.open_db() as db:
            task=m.claim(db,"R","owner3")
            self.assertFalse(task["claimed"])
    def test_invalid_path_rolls_back(self):
        bad=self.item("Q-07","Q-06",["../escape.py"])
        with self.assertRaises(ValueError):
            catalog.replenish(self.root,self.write([self.item("R-08"),bad]))
        with m.open_db() as db:
            self.assertIsNone(db.execute("SELECT id FROM task WHERE id='R-08'").fetchone())
    def test_blocked_dependency_not_autostaged(self):
        self.assertEqual(catalog.replenish(self.root,self.write([self.item("R-08","R-07")]))["enqueued"],[])
if __name__=="__main__":unittest.main()
