"""Synthetic CPU-only regression: pre-semantic sprite work must be accounted.

No real scene, save, asset, backend request, VLM or GPU process is used.
"""
import io
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("VN_WORKER_TOKEN", "synthetic-regression-only")
sys.path.insert(0, str(ROOT / "worker"))
import worker


class PresemanticAccounting(unittest.TestCase):
    def run_synthetic_sprite(self, cutout_seconds):
        image = Image.new("RGBA", (128, 192), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((36, 10, 91, 181), fill=(70, 60, 50, 255))
        stream = io.BytesIO()
        image.save(stream, "PNG")
        job = {"id": "synthetic-qa-presemantic", "kind": "sprite", "attempts": 1,
               "spec": {"resolution": [128, 192], "quality": "standard",
                        "variant": {"outfit": "fictional coat", "pose": "standing"}}}
        def slow_cutout(img):
            time.sleep(cutout_seconds)
            return img
        with patch.dict(os.environ, {"VN_VISION_QA": "1"}), \
             patch.object(worker, "cutout", side_effect=slow_cutout), \
             patch.object(worker, "harmonize", side_effect=lambda img, bg: img), \
             patch.object(worker, "request", return_value={
                 "status": "unavailable", "reason": "synthetic VLM unavailable"}):
            started = time.monotonic()
            _, report = worker.assess(job, stream.getvalue(), None)
            elapsed = (time.monotonic() - started) * 1000
        return report, elapsed

    def test_slow_sprite_matte_is_accounted_before_semantic_QA(self):
        report, elapsed = self.run_synthetic_sprite(0.065)
        pre = report["metrics"]["qa_presemantic_ms"]
        self.assertGreaterEqual(pre, 55)
        self.assertLessEqual(pre, elapsed + 2)
        self.assertFalse(report["passed"])
        self.assertEqual(report["semantic_status"], "unavailable")

    def test_total_assess_is_sum_of_presemantic_and_existing_qa(self):
        report, elapsed = self.run_synthetic_sprite(0)
        m = report["metrics"]
        total = m["qa_assess_total_ms"]
        self.assertGreaterEqual(total, report["timings"]["qa_ms"])
        self.assertAlmostEqual(total, m["qa_presemantic_ms"] + report["timings"]["qa_ms"],
                               delta=7.0)
        self.assertLessEqual(total, elapsed + 5)

    def test_original_fail_closed_rule_is_unchanged(self):
        report, _ = self.run_synthetic_sprite(0)
        self.assertFalse(report["passed"])
        self.assertIn("Semantic QA unavailable", " ".join(report["reasons"]))


if __name__ == "__main__":
    unittest.main()
