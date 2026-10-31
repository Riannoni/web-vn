"""#76: RED-first contract tests for evidence-only Golden work.

All bytes in this module are synthetic private fixtures. Synthetic PASS is
not real G2 approval; no image/job/GPU is produced or changed by these tests.
"""
import base64
import contextlib
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))
import golden_evidence as ge
spec = importlib.util.spec_from_file_location("native_team_cli_golden", SRC / "teamctl.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAOazJf0AAAAASUVORK5CYII="
)
PID = "7b3b344b-fd8c-4068-8bd6-e541266ec174"
TASK = "G-12"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, text=True,
                          capture_output=True, check=True, timeout=12).stdout.strip()


class GoldenEvidenceTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name) / "team"
        self.root.mkdir()
        self.private = Path(t.name) / "private"
        self.private.mkdir(mode=0o700)
        saved = (m.ROOT, m.DB, ge.ROOT, ge.PRIVATE_ROOT)
        self.addCleanup(lambda: self.restore(saved))
        m.ROOT = ge.ROOT = self.root
        m.DB = self.root / "state/team.sqlite3"
        ge.PRIVATE_ROOT = self.private
        for lane in m.LANES.values():
            work = self.root / ("lane-" + lane)
            work.mkdir()
            git(work, "init", "-q")
            git(work, "config", "user.name", "Test Worker")
            git(work, "config", "user.email", "test@example.invalid")
            (work / "docs").mkdir()
            (work / "AGENTS.md").write_text("Rules")
            (work / "docs/DEVELOPMENT-AND-TESTING.md").write_text("Rules")
            git(work, "add", ".")
            git(work, "commit", "-qm", "synthetic initial checkout")
        m.initialize()
        self.db = m.open_db()
        self.addCleanup(self.db.close)
        self.evidence_dir = self.root / "evidence/golden"
        self.evidence_dir.mkdir(parents=True, mode=0o700)
        self.artifacts = {}
        self.write_artifact("original_png", "case/original.png", PNG)
        self.write_artifact("canonical_ref", "case/canonical.png", PNG + b"reference")
        self.write_artifact("source_save", "case/save.json",
                            b'{"save_version":13,"scene_fingerprint":"stable"}')
        self.write_artifact("scene_contract", "case/contract.json",
                            json.dumps({"schema": "typed_scene_v1", "case_id": "CG-03",
                                        "canonical_sha256": self.artifacts["canonical_ref"]["sha256"],
                                        "source_save_sha256": self.artifacts["source_save"]["sha256"],
                                        "mandatory_checks": ["environment", "identity", "contact"]}).encode())
        original = self.artifacts["original_png"]
        self.write_artifact("gpu_receipt", "case/gpu-result.json", json.dumps({
            "status": "GPU_FINISHED_REVIEW_REQUIRED",
            "prompt_id": PID,
            "case": "CG-03",
            "original_png_path": original["path"],
            "png_sha256": original["sha256"]
        }).encode())
        self.spec = {"schema": "golden_evidence_v1", "task_id": TASK,
                     "goal": "Independently audit original pixels of a bounded candidate",
                     "generator_owner": "renderer-a", "case_id": "CG-03",
                     "prompt_id": PID, "priority": 200,
                     "dependencies": [], "artifacts": dict(self.artifacts)}

    def restore(self, saved):
        m.ROOT, m.DB, ge.ROOT, ge.PRIVATE_ROOT = saved

    def write_artifact(self, key, path, data):
        f = self.private / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        f.chmod(0o600)
        self.artifacts[key] = {"path": str(f), "sha256": sha(data)}

    def enqueue(self, spec=None):
        return ge.enqueue(self.db, self.spec if spec is None else spec)

    def claim(self, owner="golden-worker"):
        self.enqueue()
        claimed = m.claim(self.db, "G", owner)
        self.assertTrue(claimed["claimed"], claimed)
        self.assertEqual(claimed["id"], TASK)
        self.assertEqual(claimed["paths"], [])
        return claimed

    def receipt(self, claim, mandatory=None, requested_g2="FAIL", **overrides):
        checks = mandatory if mandatory is not None else {
            "environment": {"verdict": "verified",
                            "observation": "The synthetic scene has an environment observation"},
            "identity": {"verdict": "unobservable",
                         "observation": "The synthetic character face is not visible"},
            "contact": {"verdict": "violated",
                        "observation": "The synthetic palms do not touch the source wall"}
        }
        receipt = {"schema": "golden_visual_receipt_v1", "task_id": TASK,
                   "owner": claim["owner"], "fence": claim["fence"],
                   "generator_owner": "renderer-a",
                   "prompt_id": PID, "original_png_sha256": self.artifacts["original_png"]["sha256"],
                   "scene_contract_sha256": self.artifacts["scene_contract"]["sha256"],
                   "canonical_sha256": self.artifacts["canonical_ref"]["sha256"],
                   "source_save_sha256": self.artifacts["source_save"]["sha256"],
                   "gpu_receipt_sha256": self.artifacts["gpu_receipt"]["sha256"],
                   "original_pixels_reviewed": True,
                   "mandatory": checks, "requested_g2": requested_g2,
                   "observations": "Synthetic test observation only; not real visual acceptance."}
        receipt.update(overrides)
        path = self.evidence_dir / "candidate-review.json"
        path.write_text(json.dumps(receipt))
        path.chmod(0o600)
        return path

    def test_fail_receipt_accepted_without_any_git_change(self):
        before = git(self.root/"lane-golden", "rev-parse", "HEAD")
        x = self.claim()
        result = ge.submit(self.db, TASK, x["owner"], x["fence"], self.receipt(x))
        self.assertTrue(result["accepted"], result)
        self.assertEqual(result["g2"], "FAIL")
        self.assertEqual(self.db.execute("SELECT state FROM task WHERE id=?",
                                         (TASK,)).fetchone()["state"], "review_pending")
        self.assertEqual(git(self.root/"lane-golden", "rev-parse", "HEAD"), before)
        verdict = ge.review(self.db, TASK, "chief-reviewer", True,
                            "Independent review reproduces this synthetic negative",
                            self.artifacts["original_png"]["sha256"])
        self.assertTrue(verdict["approved"], verdict)
        self.assertEqual(verdict["g2"], "FAIL")
        self.assertEqual(self.db.execute("SELECT state FROM task WHERE id=?",
                                         (TASK,)).fetchone()["state"], "done")
        self.assertEqual(git(self.root/"lane-golden", "rev-parse", "HEAD"), before)

    def test_mandatory_unobservable_cannot_be_pass(self):
        x = self.claim()
        p = self.receipt(x, requested_g2="PASS")
        with self.assertRaisesRegex(ValueError, "g2|verdict|PASS"):
            ge.submit(self.db, TASK, x["owner"], x["fence"], p)

    def test_mandatory_violated_cannot_be_pass(self):
        x = self.claim()
        p = self.receipt(x, mandatory={
            "environment":{"verdict":"verified","observation":"Environment seems correctly present"},
            "identity":{"verdict":"verified","observation":"A canonical face is clearly observable"},
            "contact":{"verdict":"violated","observation":"Actual wall contact is not demonstrated"}
        }, requested_g2="PASS")
        with self.assertRaises(ValueError):
            ge.submit(self.db, TASK, x["owner"], x["fence"], p)

    def test_mandatory_not_applicable_or_missing_fails_closed(self):
        x = self.claim()
        for checks in (
            {"environment":{"verdict":"verified","observation":"Original context shows a stone wall"}},
            {"environment":{"verdict":"verified","observation":"Original context shows a stone wall"},
             "identity":{"verdict":"not_applicable","observation":"No face can be observed currently"},
             "contact":{"verdict":"verified","observation":"Both palms touch the masonry surface"}}
        ):
            with self.subTest(checks=checks), self.assertRaises(ValueError):
                ge.submit(self.db, TASK, x["owner"], x["fence"],
                          self.receipt(x, mandatory=checks))

    def test_all_verified_is_only_a_synthetic_structural_pass(self):
        x = self.claim()
        checks = {key: {"verdict":"verified", "observation":"Synthetic checked statement on original bytes"}
                  for key in ["environment", "identity", "contact"]}
        ans = ge.submit(self.db, TASK, x["owner"], x["fence"],
                        self.receipt(x, mandatory=checks, requested_g2="PASS"))
        self.assertEqual(ans["g2"], "PASS")
        with self.assertRaisesRegex(ValueError, "reviewer|independent"):
            ge.review(self.db, TASK, x["owner"], True,
                      "Self approval is forbidden even in synthetic fixtures",
                      self.artifacts["original_png"]["sha256"])
        with self.assertRaises(ValueError):
            ge.review(self.db, TASK, "renderer-a", True,
                      "Generator cannot certify own original pixels in test",
                      self.artifacts["original_png"]["sha256"])
        with self.assertRaises(ValueError):
            ge.review(self.db, TASK, "chief-reviewer", True,
                      "Independent but verified SHA not supplied correctly", "0"*64)

    def test_sha_and_prompt_forgery_rejected(self):
        x = self.claim()
        for field, value in (
            ("original_png_sha256", "f"*64),
            ("prompt_id", "11111111-1111-4111-8111-111111111111"),
            ("scene_contract_sha256", "f"*64),
            ("canonical_sha256", "f"*64),
            ("gpu_receipt_sha256", "f"*64),
            ("source_save_sha256", "f"*64)
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                ge.submit(self.db, TASK, x["owner"], x["fence"],
                          self.receipt(x, **{field:value}))

    def test_stale_fence_owner_and_replay(self):
        x = self.claim()
        p = self.receipt(x)
        for owner,fence in (("not-owner",x["fence"]), (x["owner"],"wrong-fence")):
            with self.assertRaises(ValueError):
                ge.submit(self.db, TASK, owner, fence, p)
        with self.assertRaises(ValueError):
            ge.submit(self.db, TASK, x["owner"], "bogus",
                      self.receipt(x, fence="bogus"))
        self.assertTrue(ge.submit(self.db,TASK,x["owner"],x["fence"],self.receipt(x))["accepted"])
        with self.assertRaises(ValueError):
            ge.submit(self.db,TASK,x["owner"],x["fence"],self.receipt(x))
        with self.assertRaises(ValueError):
            self.enqueue()

    def test_missing_png_and_changed_png_bytes_rejected(self):
        x = self.claim()
        p = self.receipt(x)
        png = Path(self.artifacts["original_png"]["path"])
        png.unlink()
        with self.assertRaises(ValueError):
            ge.submit(self.db,TASK,x["owner"],x["fence"],p)
        png.write_bytes(PNG+b"changed")
        with self.assertRaises(ValueError):
            ge.submit(self.db,TASK,x["owner"],x["fence"],p)

    def test_stale_save_during_submit_and_review(self):
        x = self.claim()
        p = self.receipt(x)
        save = Path(self.artifacts["source_save"]["path"])
        save.write_bytes(b"unexpected canonical state")
        with self.assertRaises(ValueError):
            ge.submit(self.db,TASK,x["owner"],x["fence"],p)
        save.write_bytes(b'{"save_version":13,"scene_fingerprint":"stable"}')
        ge.submit(self.db,TASK,x["owner"],x["fence"],self.receipt(x))
        save.write_bytes(b"mutation after submit")
        with self.assertRaises(ValueError):
            ge.review(self.db,TASK,"chief-reviewer",True,
                      "Must reject stale save at actual independent review",
                      self.artifacts["original_png"]["sha256"])

    def test_review_refuses_tampered_immutable_receipt(self):
        x=self.claim()
        p=self.receipt(x)
        ge.submit(self.db,TASK,x["owner"],x["fence"],p)
        doc=json.loads(self.db.execute("SELECT result FROM task WHERE id=?",(TASK,)).fetchone()["result"])
        immutable=self.root/doc["path"]
        self.assertNotEqual(p,immutable)
        self.assertEqual(immutable.read_bytes(),p.read_bytes())
        immutable.write_text(immutable.read_text()+" ")
        with self.assertRaises(ValueError):
            ge.review(self.db,TASK,"chief-reviewer",True,
                      "Immutable receipt has changed after fenced submission",
                      self.artifacts["original_png"]["sha256"])

    def test_immutable_copy_does_not_follow_mutated_input_receipt(self):
        x=self.claim()
        p=self.receipt(x)
        ge.submit(self.db,TASK,x["owner"],x["fence"],p)
        p.write_text(p.read_text()+" mutated after copy")
        ans=ge.review(self.db,TASK,"chief-reviewer",True,
                      "Independent reviewer checks immutable original snapshot",
                      self.artifacts["original_png"]["sha256"])
        self.assertTrue(ans["approved"])

    def test_missing_provenance_or_mismatched_job(self):
        bad = json.loads(Path(self.artifacts["gpu_receipt"]["path"]).read_text())
        bad["prompt_id"]="11111111-1111-4111-8111-111111111111"
        self.write_artifact("gpu_receipt","case/gpu-result.json",json.dumps(bad).encode())
        self.spec["artifacts"]=dict(self.artifacts)
        with self.assertRaises(ValueError):
            self.enqueue()

    def test_source_submit_remains_strict_and_unchanged(self):
        source=m.claim(self.db,"R","source-worker")
        self.assertTrue(source["claimed"])
        e=self.root/"evidence/renderer/source.json"
        e.parent.mkdir(parents=True,exist_ok=True)
        e.write_text(json.dumps({"source_status":"tested_isolated","g2":"UNVERIFIED",
                                 "g3":"NO_GO","tests":["offline pass"],
                                 "changed_paths":[]}))
        with self.assertRaises(ValueError):
            m.submit(self.db,"R",source["owner"],source["fence"],source["id"],e)

    def test_symlink_and_out_of_root_paths_rejected(self):
        s=json.loads(json.dumps(self.spec))
        s["artifacts"]["original_png"]["path"]="/etc/passwd"
        with self.assertRaises(ValueError):
            self.enqueue(s)
        target=Path(self.artifacts["original_png"]["path"])
        link=target.parent/"linked.png"
        link.symlink_to(target)
        s=json.loads(json.dumps(self.spec))
        s["artifacts"]["original_png"]["path"]=str(link)
        with self.assertRaises(ValueError):
            self.enqueue(s)

    def test_contract_source_reference_mixture_is_rejected(self):
        contract=json.loads(Path(self.artifacts["scene_contract"]["path"]).read_text())
        for key,value in (("canonical_sha256","a"*64),
                          ("source_save_sha256","b"*64),
                          ("case_id","CG-OTHER")):
            with self.subTest(key=key):
                wrong=dict(contract)
                wrong[key]=value
                self.write_artifact("scene_contract","case/contract.json",json.dumps(wrong).encode())
                spec=json.loads(json.dumps(self.spec))
                spec["artifacts"]=dict(self.artifacts)
                with self.assertRaises(ValueError):
                    self.enqueue(spec)

    def test_same_gpu_job_cannot_be_enqueued_with_new_task_id(self):
        self.enqueue()
        again=json.loads(json.dumps(self.spec))
        again["task_id"]="G-13"
        with self.assertRaisesRegex(ValueError,"replay"):
            self.enqueue(again)

    def test_cli_routes_visual_only_without_source_diff(self):
        def cli(*args):
            output=io.StringIO()
            with patch.object(sys,"argv",["teamctl.py",*args]),contextlib.redirect_stdout(output):
                self.assertEqual(m.main(),0)
            return json.loads(output.getvalue())

        spec_path=self.private/"case/task-spec.json"
        spec_path.write_text(json.dumps(self.spec))
        spec_path.chmod(0o600)
        self.assertEqual(cli("enqueue-visual","--spec",str(spec_path))["enqueued"],TASK)
        x=m.claim(self.db,"G","golden-cli")
        self.assertTrue(x["claimed"])
        p=self.receipt(x)
        self.assertEqual(cli("submit-visual","--task",TASK,
                             "--owner",x["owner"],"--fence",x["fence"],
                             "--evidence",str(p))["g2"],"FAIL")
        with self.assertRaisesRegex(ValueError,"review-visual"):
            m.review(self.db,TASK,True,"Source review command is wrong",None)
        review=cli("review-visual","--task",TASK,"--reviewer","chief-cli",
                   "--approve","--verified-png-sha",
                   self.artifacts["original_png"]["sha256"],
                   "--note","Actual independent verification of synthetic negative receipt")
        self.assertTrue(review["approved"])
        note=self.db.execute("SELECT note FROM visual_review WHERE task_id=?",
                             (TASK,)).fetchone()["note"]
        self.assertIn("independent verification",note)

    def test_approved_review_rehashes_canonical_bytes_again(self):
        x=self.claim()
        ge.submit(self.db,TASK,x["owner"],x["fence"],self.receipt(x))
        ref=Path(self.artifacts["canonical_ref"]["path"])
        ref.write_bytes(PNG+b"tampered canonical")
        with self.assertRaises(ValueError):
            ge.review(self.db,TASK,"chief-independent",True,
                      "Canonical bytes changed after original receipt submission",
                      self.artifacts["original_png"]["sha256"])

    def test_only_golden_visual_task_and_no_code_paths(self):
        s=json.loads(json.dumps(self.spec))
        s["task_id"]="Q-12"
        with self.assertRaises(ValueError):
            self.enqueue(s)
        s=json.loads(json.dumps(self.spec))
        s["changed_paths"]=["scripts/native_team/teamctl.py"]
        with self.assertRaises(ValueError):
            self.enqueue(s)


if __name__=="__main__":
    unittest.main()
