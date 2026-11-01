"""Synthetic CPU-only regression for required sprite identity and VLM status.

No real identities, images, Comfy, server, network inference or live saves.
A positive internal QA report is *not* independent original-pixel G2.
"""
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

os.environ.setdefault("VN_WORKER_TOKEN", "synthetic-qa-test-only")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
import worker


class SpriteIdentityFailClosed(unittest.TestCase):
    def run_case(self, response, *, reference=False, fetch_error=False):
        image = Image.new("RGBA", (128, 192), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((30, 10, 96, 182), fill=(75, 65, 55, 255))
        raw = io.BytesIO()
        image.save(raw, "PNG")
        spec = {
            "resolution": [128, 192],
            "quality": "standard",
            "environment": {"id": "unclassified"},
            "variant": {"pose": "standing front", "outfit": "test outfit"},
        }
        if reference:
            spec["face_asset"] = "synthetic-immutable-reference.png"
        job = {"kind": "sprite", "attempts": 1, "spec": spec,
               "prompt": "generic synthetic silhouette"}
        ref = Image.new("RGB", (128, 128), (120, 110, 90))
        def get_asset(_name):
            if fetch_error:
                raise OSError("synthetic reference unavailable")
            return ref
        with patch.dict(os.environ, {"VN_VISION_QA": "1"}), \
             patch.object(worker, "cutout", side_effect=lambda image: image), \
             patch.object(worker, "harmonize", side_effect=lambda image, _bg: image), \
             patch.object(worker, "fetch_asset", side_effect=get_asset), \
             patch.object(worker, "request", return_value=response) as request:
            _, report = worker.assess(job, raw.getvalue(), None)
            request.assert_called_once()
        return report

    def test_no_reference_and_no_similarity_rejected(self):
        report = self.run_case({"status": "passed"})
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_no_reference_cannot_use_spoofed_high_score(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .95,
                                "identity_face_visibility": "verified"})
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_unreadable_reference_rejected(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .95,
                                "identity_face_visibility": "verified"},
                               reference=True, fetch_error=True)
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_reference_but_missing_similarity_rejected(self):
        report = self.run_case({"status": "passed"}, reference=True)
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_bad_identity_score_rejected(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .65,
                                "identity_face_visibility": "violated"}, reference=True)
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "violated")

    def test_hidden_face_not_promoted_by_high_score(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .95,
                                "identity_face_visibility": "unobservable"}, reference=True)
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_missing_observability_not_a_verification(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .95}, reference=True)
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_nonfinite_similarity_not_verification(self):
        for raw in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(raw=raw):
                report = self.run_case({"status": "passed",
                                        "identity_similarity": raw,
                                        "identity_face_visibility": "verified"}, reference=True)
                self.assertFalse(report["passed"], report)
                self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_wrongly_typed_or_out_of_range_similarity_is_unobservable(self):
        for score in (True, "0.91", 10**400, 1.2, -1.2):
            with self.subTest(kind=type(score).__name__):
                report = self.run_case({"status": "passed",
                                        "identity_similarity": score,
                                        "identity_face_visibility": "verified"}, reference=True)
                self.assertFalse(report["passed"], report)
                self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_contradictory_vision_identity_result_rejected(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .95,
                                "identity_face_visibility": "violated"}, reference=True)
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "violated")

    def test_borderline_similarity_is_unobservable(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .84,
                                "identity_face_visibility": "verified"}, reference=True)
        self.assertFalse(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "unobservable")

    def test_failed_semantic_without_reasons_still_rejected(self):
        report = self.run_case({"status": "failed", "reasons": [],
                                "identity_similarity": .91,
                                "identity_face_visibility": "verified"}, reference=True)
        self.assertFalse(report["passed"], report)

    def test_reference_visible_high_similarity_can_pass_internal_gate(self):
        report = self.run_case({"status": "passed",
                                "identity_similarity": .91,
                                "identity_face_visibility": "verified"}, reference=True)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["evidence"]["identity"]["verdict"], "verified")
        self.assertEqual(report["semantic_status"], "passed")


if __name__ == "__main__":
    unittest.main()
