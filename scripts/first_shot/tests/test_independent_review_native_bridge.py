"""Synthetic CPU integration of native #76 receipt -> LAB review fence (no pixels judged)."""
import hashlib
from contextlib import closing
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("g777_review", SOURCE / "independent_review.py")
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


def blob(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def png(rgba=False):
    im = Image.new("RGBA" if rgba else "RGB", (15, 23),
                   (30, 60, 90, 255) if rgba else (30, 60, 90))
    if rgba:
        im.putpixel((0, 0), (0, 0, 0, 0))
    buffer = io.BytesIO()
    im.save(buffer, format="PNG")
    return buffer.getvalue()


class NativeOriginalReceiptBridge(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.private = self.base / ".local/share"
        self.private.mkdir(parents=True)
        self.native = self.private / "web-vn-native-team/run-20261031-full"
        for d in ("state", "evidence/golden/immutable"):
            (self.native / d).mkdir(parents=True)
        self.lab = self.base / "lab"
        self.name = "SPRITE_CANONICAL_G777"
        self.rundir = self.lab / "runs" / self.name
        for d in (self.rundir, self.lab / "review_pending", self.lab / "reviewed"):
            d.mkdir(parents=True)
        (self.lab / "review_pending" / (self.name + ".json")).write_text("{}")
        self.prompt_id = "11111111-2222-3333-4444-555555555555"
        self.task_id = "G-777"
        self.original = self.private / "original.png"
        self.original.write_bytes(png())
        original_sha = sha(self.original.read_bytes())
        self.derived = self.rundir / "sprite-rgba-candidate.png"
        self.derived.write_bytes(png(rgba=True))
        run_st, file_st = self.rundir.stat(), self.derived.stat()
        self.inode_binding = {
            "derived_rgba_run_dev": run_st.st_dev,
            "derived_rgba_run_ino": run_st.st_ino,
            "derived_rgba_file_dev": file_st.st_dev,
            "derived_rgba_file_ino": file_st.st_ino,
        }
        self.candidate = {
            "id": self.name, "case": "SPRITE-CANONICAL",
            "factor": "sdxl_sprite_body_source",
            "status": "GPU_FINISHED_REVIEW_REQUIRED", "prompt_id": self.prompt_id,
            "png_sha256": original_sha, "original_png_path": str(self.original),
            "original_png_sha256": original_sha,
            "derived_rgba_path": str(self.derived),
            "derived_rgba_sha256": sha(self.derived.read_bytes()),
            "g2": "NOT_REVIEWED", "published": False,
            **self.inode_binding,
        }
        self.review = {
            "experiment_id": self.name, "reviewer_task": self.task_id,
            "prompt_id": self.prompt_id, "png_sha256": original_sha,
            "original_pixels_reviewed": True,
            "mandatory": {"identity": "violated", "sprite_alpha": "verified"},
            "observations": "The synthetic fixture deliberately reports identity violated and alpha observed."
        }
        self.desc = {
            "original_png": self.artifact("original.png", self.original.read_bytes()),
            "canonical_ref": self.artifact("reference.bin", b"synthetic immutable canonical ref"),
            "source_save": self.artifact("save.bin", b"synthetic version-fenced save"),
        }
        contract = {
            "schema": "typed_scene_v1", "case_id": self.candidate["case"],
            "mandatory_checks": ["identity", "sprite_alpha"],
            "canonical_sha256": self.desc["canonical_ref"]["sha256"],
            "source_save_sha256": self.desc["source_save"]["sha256"]
        }
        self.desc["scene_contract"] = self.artifact("scene.json", blob(contract))
        source = {
            "status": "GPU_FINISHED_REVIEW_REQUIRED", "prompt_id": self.prompt_id,
            "case": self.candidate["case"], "png_sha256": original_sha,
            "original_png_path": str(self.original),
            "derived_rgba_path": str(self.derived),
            "derived_rgba_sha256": self.candidate["derived_rgba_sha256"],
            **self.inode_binding,
        }
        self.desc["gpu_receipt"] = self.artifact("gpu.json", blob(source))
        self.spec = {
            "schema": "golden_evidence_v1", "task_id": self.task_id,
            "goal": "Independently verify the exact private original and derived canonical sprite",
            "generator_owner": "renderer", "case_id": self.candidate["case"],
            "prompt_id": self.prompt_id, "priority": 100,
            "dependencies": [], "artifacts": self.desc
        }
        self.native_receipt = {
            "schema": "golden_visual_receipt_v1", "task_id": self.task_id,
            "owner": "golden-pixel", "fence": "synthetic-fence",
            "generator_owner": "renderer", "prompt_id": self.prompt_id,
            "original_png_sha256": original_sha,
            "scene_contract_sha256": self.desc["scene_contract"]["sha256"],
            "canonical_sha256": self.desc["canonical_ref"]["sha256"],
            "source_save_sha256": self.desc["source_save"]["sha256"],
            "gpu_receipt_sha256": self.desc["gpu_receipt"]["sha256"],
            "original_pixels_reviewed": True,
            "mandatory": {
                "identity": {"verdict": "violated",
                             "observation": "Original synthetic subject identity is not authentic."},
                "sprite_alpha": {"verdict": "verified",
                                 "observation": "Derived synthetic RGBA has transparent background."}
            },
            "requested_g2": "FAIL", "observations": self.review["observations"]
        }
        self.chief_reviewer = "chief-independent"
        self.native_status = "done"
        self.native_approved = 1
        self.rf = self.base / "golden-review.json"
        self.p1 = patch.object(reviewer, "NATIVE_ROOT", self.native)
        self.p2 = patch.object(reviewer.native_golden, "PRIVATE_ROOT", self.private)
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p2.stop); self.addCleanup(self.p1.stop)
        self.save()

    def artifact(self, filename, data):
        p = self.private / filename
        p.write_bytes(data)
        return {"path": str(p), "sha256": sha(data)}

    def save(self):
        self.rf.write_bytes(blob(self.review))
        (self.rundir / "result.json").write_bytes(blob(self.candidate))
        native_bytes = blob(self.native_receipt)
        trusted = self.native / "evidence/golden/immutable" / (sha(native_bytes) + ".json")
        trusted.write_bytes(native_bytes)
        spec_text = json.dumps(self.spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        spec_hash = sha(spec_text.encode())
        record = {
            "status": "visual-evidence-only", "lane": "G",
            "task_id": self.task_id, "spec_sha256": spec_hash,
            "sha256": sha(native_bytes), "path": str(trusted.relative_to(self.native)),
            "submitted_by": "golden-pixel", "generator_owner": "renderer",
            "prompt_id": self.prompt_id, "png_sha256": self.candidate["png_sha256"],
            "g2": "FAIL", "g3": "NO_GO"
        }
        with closing(sqlite3.connect(self.native / "state/team.sqlite3")) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS task (id TEXT PRIMARY KEY, action TEXT, state TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS visual_task (task_id TEXT PRIMARY KEY, spec_sha256 TEXT, spec_json TEXT);
                CREATE TABLE IF NOT EXISTS visual_review (task_id TEXT PRIMARY KEY, reviewer TEXT, approved INTEGER, g2 TEXT, png_sha256 TEXT);
            """)
            for table in ("task", "visual_task", "visual_review"):
                db.execute("DELETE FROM " + table)
            db.execute("INSERT INTO task VALUES(?,?,?,?)",
                       (self.task_id, "visual_evidence", self.native_status, json.dumps(record)))
            db.execute("INSERT INTO visual_task VALUES(?,?,?)",
                       (self.task_id, spec_hash, spec_text))
            db.execute("INSERT INTO visual_review VALUES(?,?,?,?,?)",
                       (self.task_id, self.chief_reviewer, self.native_approved, "FAIL", self.candidate["png_sha256"]))
            db.commit()

    def assert_denied_without_transition(self, expected):
        with self.assertRaisesRegex(ValueError, expected):
            reviewer.audit(self.lab, self.rf)
        self.assertTrue((self.lab / "review_pending" / (self.name + ".json")).exists())
        self.assertFalse((self.lab / "reviewed" / (self.name + ".json")).exists())
        self.assertFalse((self.rundir / "golden-review.json").exists())

    def test_accepted_native_receipt_terminal_fail_then_replay_denied(self):
        actual = reviewer.audit(self.lab, self.rf)
        self.assertEqual(actual["g2"], "FAIL")
        self.assertEqual(json.loads((self.rundir / "result.json").read_text())["g2"], "FAIL")
        self.assertTrue((self.lab / "reviewed" / (self.name + ".json")).is_file())
        with self.assertRaisesRegex(ValueError, "candidate_not_waiting_review"):
            reviewer.audit(self.lab, self.rf)

    def test_missing_native_independent_review_keeps_candidate_held(self):
        self.native_approved = 0
        self.save()
        self.assert_denied_without_transition("trusted_visual_review_not_independently_approved")

    def test_self_approved_native_receipt_keeps_candidate_held(self):
        self.chief_reviewer = "golden-pixel"
        self.save()
        self.assert_denied_without_transition("trusted_visual_self_approval")

    def test_reduced_mandatory_set_keeps_candidate_held(self):
        self.review["mandatory"] = {"identity": "violated"}
        self.rf.write_bytes(blob(self.review))
        self.assert_denied_without_transition("trusted_visual_mandatory_reduced")

    def test_forged_positive_verdict_disagrees_with_native(self):
        self.review["mandatory"]["identity"] = "verified"
        self.rf.write_bytes(blob(self.review))
        self.assert_denied_without_transition("trusted_visual_verdict_not_from_reviewer")

    def test_changed_save_bytes_keeps_candidate_held(self):
        (self.private / "save.bin").write_bytes(b"changed source save")
        self.assert_denied_without_transition("original private artifact sha256 mismatch")

    def test_missing_derived_rgba_keeps_candidate_held(self):
        self.derived.unlink()
        self.assert_denied_without_transition("derived_rgba_path_rebound")

    def test_valid_but_substituted_rgba_sha_not_bound_to_native_review(self):
        # The replacement is a technically sound RGBA, not a corrupt file.
        # A review of the ORIGINAL alone must not approve arbitrary derivatives.
        im = Image.new("RGBA", (15, 23), (220, 110, 40, 255))
        im.putpixel((0, 0), (0, 0, 0, 0))
        stream = io.BytesIO()
        im.save(stream, format="PNG")
        changed = stream.getvalue()
        self.derived.write_bytes(changed)
        self.candidate["derived_rgba_sha256"] = sha(changed)
        self.save()  # native GPU/source receipt deliberately still binds the old derivative
        self.assert_denied_without_transition("trusted_sprite_derivative_not_in_native_gpu_receipt")

    def test_repinning_mutable_inode_cannot_override_native_gpu_receipt(self):
        # The replacement contains IDENTICAL bytes; immutable GPU receipt
        # still pins the original run and final-file inode identities.
        displaced = self.lab / "displaced-original-run"
        self.rundir.rename(displaced)
        self.rundir.mkdir()
        moved_bytes = (displaced / "sprite-rgba-candidate.png").read_bytes()
        (self.rundir / "sprite-rgba-candidate.png").write_bytes(moved_bytes)
        r, f = self.rundir.stat(), (self.rundir / "sprite-rgba-candidate.png").stat()
        self.candidate.update({
            "derived_rgba_run_dev": r.st_dev,
            "derived_rgba_run_ino": r.st_ino,
            "derived_rgba_file_dev": f.st_dev,
            "derived_rgba_file_ino": f.st_ino,
        })
        self.save()
        self.assert_denied_without_transition("trusted_sprite_inode_binding_mismatch")

    def test_native_sprite_factor_spoof_cannot_skip_missing_final_rgba(self):
        # Native typed contract and GPU receipt still require sprite_alpha/RGBA;
        # the mutable LAB result may NOT recast it as a non-sprite experiment.
        self.candidate["factor"] = "native_pose"
        self.candidate.pop("derived_rgba_path")
        self.candidate.pop("derived_rgba_sha256")
        self.derived.unlink()
        self.save()
        self.assert_denied_without_transition("trusted_sprite_factor_mismatch")

    def test_native_sprite_factor_spoof_rejected_even_with_rgba_present(self):
        self.candidate["factor"] = "native_pose"
        self.save()
        self.assert_denied_without_transition("trusted_sprite_factor_mismatch")

    def test_absent_native_task_id_does_not_accept_claim(self):
        self.review["reviewer_task"] = "G-999"
        self.rf.write_bytes(blob(self.review))
        self.assert_denied_without_transition("trusted_visual_review_not_independently_approved")

    def test_exact_original_png_changed_keeps_candidate_held(self):
        self.original.write_bytes(png(rgba=True))
        self.assert_denied_without_transition("original_png_missing_or_changed")


if __name__ == "__main__":
    unittest.main()
