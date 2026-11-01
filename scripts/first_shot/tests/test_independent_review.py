"""Offline negative tests for independent exact-original review receipts."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import io
from contextlib import closing
import sqlite3
from unittest.mock import patch
from PIL import Image

p=Path(__file__).resolve().parents[1]/"independent_review.py"
spec=importlib.util.spec_from_file_location("independent_review",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class GoldenReviewTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        # Legacy unit tests exercise only historical hash/replay behavior;
        # separate tests below exercise the real mandatory native trust gate.
        trust=patch.object(m, "_trusted_original_review", return_value=["pose","contact"])
        rgba=patch.object(m, "_trusted_sprite_derivative", return_value=None)
        trust.start(); rgba.start()
        self.addCleanup(rgba.stop); self.addCleanup(trust.stop)
        for d in ("runs/CG03_LEAN_V2","review_pending","reviewed"):
            (self.root/d).mkdir(parents=True,exist_ok=True)
        self.png=self.root/"image.png"
        self.png.write_bytes(b"\x89PNG\r\n\x1a\n"+b"fake data only for SHA test")
        self.sha=hashlib.sha256(self.png.read_bytes()).hexdigest()
        self.result=dict(status="GPU_FINISHED_REVIEW_REQUIRED",
                         prompt_id="uuid-placeholder",png_sha256=self.sha,
                         original_png_path=str(self.png))
        self.review=dict(experiment_id="CG03_LEAN_V2",reviewer_task="G-10",
                         prompt_id=self.result["prompt_id"],png_sha256=self.sha,
                         original_pixels_reviewed=True,mandatory={"pose":"violated","contact":"verified"},
                         observations="The torso has insufficient forward angle; hands appear near stone.")
        self.rf=self.root/"review.json"
        self.save()
        (self.root/"review_pending/CG03_LEAN_V2.json").write_text("{}")
    def save(self):
        self.rf.write_text(json.dumps(self.review))
        (self.root/"runs/CG03_LEAN_V2/result.json").write_text(json.dumps(self.result))
    def test_failing_candidate_releases_one_review_fence(self):
        self.assertEqual(m.audit(self.root,self.rf)["g2"],"FAIL")
        self.assertTrue((self.root/"reviewed/CG03_LEAN_V2.json").exists())
        with self.assertRaises(ValueError):m.audit(self.root,self.rf)
    def test_wrong_hash_never_releases(self):
        self.review["png_sha256"]="0"*64;self.save()
        with self.assertRaises(ValueError):m.audit(self.root,self.rf)
    def test_no_real_pixels_never_passes(self):
        self.review["original_pixels_reviewed"]=False;self.save()
        with self.assertRaises(ValueError):m.audit(self.root,self.rf)
    def test_other_lane_cannot_self_review(self):
        self.review["reviewer_task"]="R-12";self.save()
        with self.assertRaises(ValueError):m.audit(self.root,self.rf)
    def test_missing_original_cannot_be_reviewed(self):
        self.png.unlink()
        with self.assertRaises(ValueError):m.audit(self.root,self.rf)
    def test_no_canonical_reference_cannot_mark_g2_pass(self):
        self.review["mandatory"]={"pose":"verified","contact":"verified"};self.save()
        self.assertEqual(m.audit(self.root,self.rf)["g2"],"UNVERIFIED")


class GoldenTrustBoundaryTests(unittest.TestCase):
    """Negative-first G-777 scenarios must leave the review_pending fence intact."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.lab = self.root / "lab"
        self.name = "SPRITE_G777_A1"
        self.run = self.lab / "runs" / self.name
        for dir in (self.run, self.lab / "review_pending", self.lab / "reviewed"):
            dir.mkdir(parents=True)
        img = Image.new("RGB", (12, 17), (100, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self.original = self.run / "original.png"
        self.original.write_bytes(buf.getvalue())
        sha = hashlib.sha256(buf.getvalue()).hexdigest()
        self.candidate = {
            "id": self.name, "case": "SPRITE-CANONICAL",
            "factor": "sdxl_sprite_body_source",
            "status": "GPU_FINISHED_REVIEW_REQUIRED",
            "prompt_id": "11111111-2222-3333-4444-555555555555",
            "png_sha256": sha, "original_png_sha256": sha,
            "original_png_path": str(self.original), "g2": "NOT_REVIEWED",
        }
        self.review = {
            "experiment_id": self.name, "reviewer_task": "G-999",
            "prompt_id": self.candidate["prompt_id"], "png_sha256": sha,
            "original_pixels_reviewed": True,
            "mandatory": {"identity": "verified"},
            "observations": "This self-asserted reviewer claims to have seen pixels, without any independent receipt.",
        }
        self.rf = self.root / "review.json"
        self.native = self.root / "native"
        (self.native / "state").mkdir(parents=True)
        self.save()
        (self.lab / "review_pending" / (self.name + ".json")).write_text("{}")

    def save(self):
        self.rf.write_text(json.dumps(self.review))
        (self.run / "result.json").write_text(json.dumps(self.candidate))

    def bind_derivative(self, path):
        run_stat = path.parent.stat()
        file_stat = path.stat()
        self.candidate.update({
            "derived_rgba_run_dev": run_stat.st_dev,
            "derived_rgba_run_ino": run_stat.st_ino,
            "derived_rgba_file_dev": file_stat.st_dev,
            "derived_rgba_file_ino": file_stat.st_ino,
        })

    def blocked(self, pattern):
        with patch.object(m, "NATIVE_ROOT", self.native):
            with self.assertRaisesRegex(ValueError, pattern):
                m.audit(self.lab, self.rf)
        self.assertTrue((self.lab / "review_pending" / (self.name + ".json")).exists())
        self.assertFalse((self.lab / "reviewed" / (self.name + ".json")).exists())
        self.assertFalse((self.run / "golden-review.json").exists())

    def test_forged_g999_reviewer_never_releases_review(self):
        self.blocked("trusted_visual_review_database_missing")

    def test_forged_native_approval_with_no_original_source_contract_fails(self):
        with closing(sqlite3.connect(self.native / "state/team.sqlite3")) as db:
            db.executescript("""
                CREATE TABLE task(id TEXT, action TEXT, state TEXT, result TEXT);
                CREATE TABLE visual_task(task_id TEXT, spec_sha256 TEXT, spec_json TEXT);
                CREATE TABLE visual_review(task_id TEXT, reviewer TEXT, approved INT, g2 TEXT, png_sha256 TEXT);
            """)
            db.execute("INSERT INTO task VALUES (?,?,?,?)",
                       ("G-999", "visual_evidence", "done", json.dumps({"g2":"PASS"})))
            db.execute("INSERT INTO visual_task VALUES (?,?,?)",
                       ("G-999", hashlib.sha256(b"{}").hexdigest(), "{}"))
            db.execute("INSERT INTO visual_review VALUES (?,?,?,?,?)",
                       ("G-999", "self-asserted", 1, "PASS", self.candidate["png_sha256"]))
            db.commit()
        self.blocked("invalid Golden visual task schema")

    def test_native_task_not_approved_fails_closed(self):
        with closing(sqlite3.connect(self.native / "state/team.sqlite3")) as db:
            db.executescript("""
                CREATE TABLE task(id TEXT, action TEXT, state TEXT, result TEXT);
                CREATE TABLE visual_task(task_id TEXT, spec_sha256 TEXT, spec_json TEXT);
                CREATE TABLE visual_review(task_id TEXT, reviewer TEXT, approved INT, g2 TEXT, png_sha256 TEXT);
            """)
            db.execute("INSERT INTO task VALUES (?,?,?,?)",
                       ("G-999", "visual_evidence", "done", "{}"))
            db.execute("INSERT INTO visual_task VALUES (?,?,?)",
                       ("G-999", hashlib.sha256(b"{}").hexdigest(), "{}"))
            db.execute("INSERT INTO visual_review VALUES (?,?,?,?,?)",
                       ("G-999", "other-reviewer", 0, "FAIL", self.candidate["png_sha256"]))
            db.commit()
        self.blocked("trusted_visual_review_not_independently_approved")

    def test_missing_derived_rgba_fails_before_any_release(self):
        self.candidate["derived_rgba_path"] = str(self.run / "missing.png")
        self.candidate["derived_rgba_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "derived_rgba_path_rebound"):
            m._trusted_sprite_derivative(self.lab, self.name, self.candidate)

    def test_rgba_without_transparency_cannot_pass_technical_validation(self):
        alpha = Image.new("RGBA", (12, 17), (20, 30, 40, 255))
        buf = io.BytesIO()
        alpha.save(buf, format="PNG")
        derived = self.run / "sprite-rgba-candidate.png"
        derived.write_bytes(buf.getvalue())
        self.candidate["derived_rgba_path"] = str(derived)
        self.candidate["derived_rgba_sha256"] = hashlib.sha256(buf.getvalue()).hexdigest()
        self.bind_derivative(derived)
        with self.assertRaisesRegex(ValueError, "derived_rgba_pixels_invalid"):
            m._trusted_sprite_derivative(self.lab, self.name, self.candidate)

    def test_substituted_derived_bytes_never_pass(self):
        derived = self.run / "sprite-rgba-candidate.png"
        derived.write_bytes(self.original.read_bytes())
        self.candidate["derived_rgba_path"] = str(derived)
        self.candidate["derived_rgba_sha256"] = "0" * 64
        self.bind_derivative(derived)
        with self.assertRaisesRegex(ValueError, "derived_rgba_path_sha_mismatch"):
            m._trusted_sprite_derivative(self.lab, self.name, self.candidate)

    def test_original_png_corrupt_idat_is_not_decoded(self):
        with self.assertRaises(ValueError):
            m._full_png(b"\x89PNG\r\n\x1a\n" + b"broken bytes")

if __name__=="__main__": unittest.main()
