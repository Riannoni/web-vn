"""Synthetic, networkless negative tests for experimental pose proposal only."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab_pose_reference import LabPoseError, build_proposal


class LabPoseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        for name in ("refs", "guides", "extractions"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (160, 140), "white").save(self.root / "refs" / "a.jpg")
        Image.new("RGB", (1216, 704), "black").save(self.root / "guides" / "a.png")
        points = [[50.0, 20.0, 1.0] for _ in range(18)]
        overrides = {
            1: (60, 30), 2: (70, 30), 3: (60, 40), 4: (35, 37),
            5: (50, 31), 6: (40, 40), 7: (25, 40),
            8: (83, 67), 9: (100, 90), 10: (112, 113),
            11: (75, 68), 12: (92, 95), 13: (110, 118),
        }
        for idx, (x, y) in overrides.items():
            points[idx] = [x, y, 1.0]
        self.points = points
        self._write_points()
        self.item = {
            "id": "wall_push_rear_oblique_01",
            "status": "draft", "approved": False,
            "camera": "rear", "action": "palms_on_wall",
            "usage_scope": "private_local_pose_review_no_photo_redistribution",
            "source_license": "unverified_external_evaluation_only",
            "extraction_status": "generated", "body_joints_confident": 18,
            "reference": "refs/a.jpg", "guide": "guides/a.png",
            "keypoints": "extractions/a.json", "dimensions": [160, 140],
            "reference_sha256": self._sha("refs/a.jpg"),
            "guide_sha256": self._sha("guides/a.png"),
        }
        self._write_manifest()
        self.pack = self.root / "pack.json"
        self.pack.write_text(json.dumps({
            "mode": "first_attempt_only",
            "cases": [{
                "id": "CG-03", "type": "cg", "canvas": [1024, 592],
                "seed": 202610310105,
                "prompt": ("Cinematic three-quarter rear view, both open hands "
                           "on stone wall, boots fully visible"),
                "expected": ["both palms on stone wall", "forward body lean"],
            }],
        }))
        self.observation = {
            "reviewer": "lab-photo-observer", "reviewed_at": "2026-10-31T12:00:00Z",
            "rear_three_quarter": True, "vertical_wall": True,
            "both_palms_visible_on_wall": True, "forward_lean": True,
            "both_feet_visible": True,
        }
        self.trusted_hashes = {
            "reference": self._sha("refs/a.jpg"),
            "guide": self._sha("guides/a.png"),
            "extraction": self._sha("extractions/a.json"),
            "pack": self._sha("pack.json"),
        }
        self.observation["reference_sha256"] = self.trusted_hashes["reference"]

    def _sha(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def _write_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps([self.item]))

    def _write_points(self):
        (self.root / "extractions" / "a.json").write_text(json.dumps([
            {"people": [{"pose_keypoints_2d": [
                number for point in self.points for number in point
            ]}]}
        ]))

    def _build(self):
        return build_proposal(self.root, self.pack, "wall_push_rear_oblique_01",
                              self.observation, self.trusted_hashes)

    def _reject(self, code):
        with self.assertRaisesRegex(LabPoseError, code):
            self._build()

    def test_proposal_is_not_gpu_or_production_approval(self):
        before = (self.root / "manifest.json").read_bytes()
        result = self._build()
        self.assertEqual(result["status"], "experimental_unapproved")
        self.assertFalse(result["gpu_authorized"])
        self.assertFalse(result["production_approved"])
        self.assertEqual(result["broker_enforcement"], "NOT_VERIFIED")
        self.assertEqual(result["generated_image_g2"], "NOT_REVIEWED")
        self.assertEqual(result["scene_seed"], 202610310105)
        self.assertTrue(result["source_footwear_not_target_wardrobe_proof"])
        self.assertIn("both_feet_visible", result["source_photo_observation"]["checks"])
        self.assertEqual(result["source_photo_observation"]["reference_sha256"],
                         self.trusted_hashes["reference"])
        self.assertNotIn("both_boots_visible", result["source_photo_observation"]["checks"])
        self.assertEqual(before, (self.root / "manifest.json").read_bytes())

    def test_side_camera_cannot_substitute(self):
        self.item["camera"] = "side"
        self._write_manifest()
        self._reject("wrong_camera_or_action")

    def test_missing_one_wrist_rejected(self):
        self.points[4][2] = 0.0
        self._write_points()
        self._reject("missing_required_joint")

    def test_cropped_ankle_rejected(self):
        self.points[13][1] = 139
        self._write_points()
        self._reject("ankles_cropped_or_not_below_hips")

    def test_too_upright_rejected(self):
        self.points[8][0] = 62
        self.points[11][0] = 58
        self._write_points()
        self._reject("insufficient_or_extreme_projected_lean")

    def test_unobservable_second_palm_rejected(self):
        self.observation["both_palms_visible_on_wall"] = False
        self._reject("source_photo_not_observable")

    def test_wrong_view_contract_rejected(self):
        pack = json.loads(self.pack.read_text())
        pack["cases"][0]["prompt"] = pack["cases"][0]["prompt"].replace(
            "three-quarter rear", "side")
        self.pack.write_text(json.dumps(pack))
        self._reject("camera_contact_or_boots_not_in_contract")

    def test_missing_expected_contact_rejected(self):
        pack = json.loads(self.pack.read_text())
        pack["cases"][0]["expected"] = ["forward body lean"]
        self.pack.write_text(json.dumps(pack))
        self._reject("mandatory_expected_missing")

    def test_tampered_guide_rejected(self):
        with (self.root / "guides" / "a.png").open("ab") as stream:
            stream.write(b"modified")
        self._reject("guide_hash_mismatch")

    def test_path_traversal_rejected(self):
        self.item["guide"] = "../../escape.png"
        self._write_manifest()
        self._reject("missing_or_escaping_file")

    def test_approved_guide_is_not_this_experimental_path(self):
        self.item["approved"] = True
        self.item["status"] = "approved"
        self._write_manifest()
        self._reject("not_an_unapproved_draft")

    def test_first_attempt_pack_required(self):
        pack = json.loads(self.pack.read_text())
        pack["mode"] = "best_of_many"
        self.pack.write_text(json.dumps(pack))
        self._reject("pack_not_first_attempt")

    def test_observer_photo_is_bound_to_exact_source_sha(self):
        self.observation["reference_sha256"] = "0" * 64
        self._reject("source_photo_observation_hash_mismatch")

    def test_source_and_manifest_cannot_be_changed_together(self):
        Image.new("RGB", (160, 140), "purple").save(self.root / "refs" / "a.jpg")
        self.item["reference_sha256"] = self._sha("refs/a.jpg")
        self._write_manifest()
        self.observation["reference_sha256"] = self.item["reference_sha256"]
        self._reject("pinned_reference_hash_mismatch")

    def test_guide_and_manifest_cannot_be_changed_together(self):
        Image.new("RGB", (1216, 704), "yellow").save(self.root / "guides" / "a.png")
        self.item["guide_sha256"] = self._sha("guides/a.png")
        self._write_manifest()
        self._reject("pinned_guide_hash_mismatch")

    def test_extraction_coordinates_are_frozen(self):
        self.points[9][0] += 3
        self._write_points()
        self._reject("pinned_extraction_hash_mismatch")

    def test_seed_cannot_change_silently_in_frozen_pack(self):
        pack = json.loads(self.pack.read_text())
        pack["cases"][0]["seed"] += 1
        self.pack.write_text(json.dumps(pack))
        self._reject("pinned_pack_hash_mismatch")

    def test_untrusted_usage_scope_rejected(self):
        self.item["usage_scope"] = "redistribute_photo"
        self._write_manifest()
        self._reject("unsafe_reference_scope")


if __name__ == "__main__":
    unittest.main()
