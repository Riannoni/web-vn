"""Focused CPU-only worker.assess mandatory sprite identity gate regression.

Synthetic pixels/model response only; real original+face paired measurement lives privately.
"""
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

ROOT = Path(os.environ.get("QA_SOURCE_TREE", Path(__file__).resolve().parents[1]))
os.environ.setdefault("VN_WORKER_TOKEN", "synthetic-identity-gate-test")
sys.path.insert(0, str(ROOT / "worker"))
import worker


class SpriteIdentityEligibility(unittest.TestCase):
    def assess(self, similarity, face_visibility, *, required_face=True):
        im = Image.new("RGBA", (128, 192), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((36, 10, 91, 181), fill=(100, 80, 60, 255))
        encoded = io.BytesIO()
        im.save(encoded, "PNG")
        spec = {"resolution": [128, 192], "quality": "standard",
                "variant": {"pose": "standing", "outfit": "unspecified"}}
        if required_face:
            spec["face_asset"] = "synthetic-face"
        job = {"id": "identity-gate-test", "kind": "sprite", "attempts": 1,
               "spec": spec, "prompt": ""}
        response = {"status": "passed", "reasons": [],
                    "identity_similarity": similarity,
                    "identity_face_visibility": face_visibility,
                    "duration_seconds": 0}
        with patch.dict(os.environ, {"VN_VISION_QA": "1"}), \
             patch.object(worker, "cutout", side_effect=lambda src: src), \
             patch.object(worker, "harmonize", side_effect=lambda src, bg: src), \
             patch.object(worker, "fetch_asset", return_value=im), \
             patch.object(worker, "request", return_value=response):
            _, result = worker.assess(job, encoded.getvalue(), None)
        return result

    def test_borderline_identity_unobservable_rejects(self):
        result = self.assess(0.8175, "unobservable")
        self.assertEqual(result["evidence"]["identity"]["verdict"], "unobservable")
        self.assertFalse(result["passed"])

    def test_low_similarity_even_if_daemon_passed_rejects(self):
        result = self.assess(0.79, "violated")
        self.assertEqual(result["evidence"]["identity"]["verdict"], "violated")
        self.assertFalse(result["passed"])

    def test_hidden_face_even_with_high_similarity_rejects(self):
        result = self.assess(0.91, "unobservable")
        self.assertEqual(result["evidence"]["identity"]["verdict"], "unobservable")
        self.assertFalse(result["passed"])

    def test_verified_face_positive_control_preserved(self):
        result = self.assess(0.91, "verified")
        self.assertEqual(result["evidence"]["identity"]["verdict"], "verified")
        self.assertTrue(result["passed"])

    def test_no_required_reference_keeps_existing_behavior(self):
        result = self.assess(None, None, required_face=False)
        self.assertEqual(result["evidence"]["identity"]["verdict"], "unobservable")
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
