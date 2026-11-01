"""CPU-only proof of paired /judge, lock and worker QA stage timings.

Loads only the tiny AST helper from vision_daemon: never loads CLIP/SmolVLM.
All images and VLM responses are synthetic, no network or GPU calls.
"""
import ast
import io
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("VN_WORKER_TOKEN", "qa-timing-synthetic")
sys.path.insert(0, str(ROOT / "worker"))
import worker


class FakeLock:
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


class Clock:
    def __init__(self, ticks):
        self.ticks = iter(ticks)
    def monotonic(self):
        return next(self.ticks)


class QATiming(unittest.TestCase):
    def test_daemon_lock_wait_is_not_hidden_in_model_time(self):
        source = ast.parse((ROOT / "worker" / "vision_daemon.py").read_text())
        fn = next(x for x in source.body
                  if isinstance(x, ast.FunctionDef) and x.name == "timed_analyze")
        ns = {"time": Clock([1.0, 1.2, 1.6]),
              "lock": FakeLock(),
              "analyze": lambda *args: {"status": "passed", "duration_seconds": .4}}
        exec(compile(ast.Module(body=[fn], type_ignores=[]),
                     "<isolated-daemon-helper>", "exec"), ns)
        response = ns["timed_analyze"]("sprite", None, {}, "standard", None, None)
        self.assertEqual(response["qa_stage_ms"]["lock_wait"], 200.0)
        self.assertEqual(response["qa_stage_ms"]["model_analyze"], 400.0)
        self.assertEqual(response["status"], "passed")

    def run_synthetic(self, response=None, *, error=None, expected=(128, 192), delay_seconds=0):
        image = Image.new("RGBA", (128, 192), (0, 0, 0, 0))
        for x in range(36, 92):
            for y in range(10, 182):
                image.putpixel((x, y), (100, 80, 60, 255))
        buf = io.BytesIO()
        image.save(buf, "PNG")
        job = {"id": "qa-timing-synthetic", "kind": "sprite", "attempts": 1,
               "spec": {"resolution": list(expected), "quality": "standard",
                        "environment": {"id": "unclassified"},
                        "variant": {"pose": "standing", "outfit": "synthetic coat"}}}
        def fake_request(*_args, **_kwargs):
            if error:
                raise OSError("synthetic /judge unavailable")
            if delay_seconds:
                time.sleep(delay_seconds)
            return response
        with patch.dict(os.environ, {"VN_VISION_QA": "1"}), \
             patch.object(worker, "cutout", side_effect=lambda img: img), \
             patch.object(worker, "harmonize", side_effect=lambda img, bg: img), \
             patch.object(worker, "request", side_effect=fake_request):
            return worker.assess(job, buf.getvalue(), None)[1]

    def test_same_attempt_server_and_client_spans_are_preserved(self):
        report = self.run_synthetic({
            "status": "passed", "duration_seconds": 0.4,
            "qa_stage_ms": {"input_decode": 1.0, "lock_wait": 2.0,
                            "model_analyze": 3.0, "handler_before_send": 8.0},
            "vlm_caption_ms": 1.5,
        }, delay_seconds=0.025)
        metrics = report["metrics"]
        self.assertEqual(metrics["qa_vision_server_stage_ms"]["lock_wait"], 2.0)
        self.assertEqual(metrics["qa_vision_server_stage_ms"]["model_analyze"], 3.0)
        self.assertEqual(metrics["qa_vision_caption_ms"], 1.5)
        self.assertGreaterEqual(metrics["qa_vision_http_ms"], 0)
        self.assertGreaterEqual(metrics["qa_vision_prepare_ms"], 0)
        self.assertIn("qa_pose_geometry_ms", metrics)
        self.assertIn("qa_ms", report["timings"])
        self.assertEqual(report["semantic_status"], "passed")

    def test_impossible_remote_handler_exceeds_local_http_span_is_untrusted(self):
        report = self.run_synthetic({
            "status": "failed", "reasons": ["synthetic mandatory rejection"],
            "qa_stage_ms": {"input_decode": 1, "lock_wait": 120000,
                            "model_analyze": 120000,
                            "handler_before_send": 240000},
            "vlm_caption_ms": 100000,
        })
        m = report["metrics"]
        self.assertFalse(report["passed"])
        self.assertEqual(m["qa_vision_server_stage_ms"], {})
        self.assertNotIn("qa_vision_caption_ms", m)
        self.assertEqual(m["qa_vision_stage_integrity"], "untrusted")
        self.assertEqual(m["qa_vision_stage_integrity_reason"], "handler_exceeds_http")

    def test_nested_server_spans_must_fit_handler(self):
        report = self.run_synthetic({
            "status": "failed", "reasons": ["synthetic mandatory rejection"],
            "qa_stage_ms": {"input_decode": 10, "lock_wait": 20,
                            "model_analyze": 30, "handler_before_send": 5},
            "vlm_caption_ms": 2,
        }, delay_seconds=0.025)
        m = report["metrics"]
        self.assertEqual(m["qa_vision_server_stage_ms"], {})
        self.assertNotIn("qa_vision_caption_ms", m)
        self.assertEqual(m["qa_vision_stage_integrity_reason"], "nested_spans_exceed_handler")

    def test_caption_cannot_exceed_analyze(self):
        report = self.run_synthetic({
            "status": "failed", "reasons": ["synthetic mandatory rejection"],
            "qa_stage_ms": {"input_decode": 1, "lock_wait": 2,
                            "model_analyze": 3, "handler_before_send": 8},
            "vlm_caption_ms": 200,
        }, delay_seconds=0.025)
        m = report["metrics"]
        self.assertEqual(m["qa_vision_server_stage_ms"], {})
        self.assertNotIn("qa_vision_caption_ms", m)
        self.assertEqual(m["qa_vision_stage_integrity_reason"], "caption_exceeds_analyze")

    def test_invalid_remote_timings_are_not_trusted(self):
        report = self.run_synthetic({
            "status": "failed", "reasons": ["synthetic rejection"],
            "qa_stage_ms": {"lock_wait": -1, "model_analyze": float("nan"),
                            "input_decode": True, "handler_before_send": 2e12},
            "vlm_caption_ms": "300"})
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"].get("qa_vision_server_stage_ms"), {})
        self.assertNotIn("qa_vision_caption_ms", report["metrics"])

    def test_judge_transport_failure_keeps_elapsed_and_fail_closed(self):
        report = self.run_synthetic(error=True)
        self.assertFalse(report["passed"])
        self.assertEqual(report["semantic_status"], "unavailable")
        self.assertIn("qa_vision_http_ms", report["metrics"])
        self.assertGreaterEqual(report["metrics"]["qa_vision_http_ms"], 0)

    def test_existing_geometry_or_image_failure_never_promoted_by_timer(self):
        report = self.run_synthetic(expected=(130, 192))
        self.assertFalse(report["passed"])
        self.assertNotIn("qa_vision_http_ms", report["metrics"])
        self.assertIn("qa_pose_geometry_ms", report["metrics"])


if __name__ == "__main__":
    unittest.main()
