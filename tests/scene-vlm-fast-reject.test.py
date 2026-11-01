"""Current-source CPU controls for mandatory scene rejection before VLM.

Execute actual analyze/assess function bodies with isolated model, image and
geometry dependencies. No archived source fixtures, models, network or GPU.
"""
import ast
import re
import io
import base64
from urllib.error import HTTPError, URLError
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, MagicMock

WORKER_DIR = Path(__file__).resolve().parents[1] / "worker"
FULL = "One adult stands outdoors on a market street in a blue coat."
ACTION = "Both hands touch the wall while standing on both feet and leaning forward."

def load(rejection=None, kind="scene", required_wall=False, location_unknown=False, environment="outdoor_market_square"):
    tree = ast.parse((WORKER_DIR / "vision_daemon.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "analyze")
    count = (False, ["count_rejected"], .1) if rejection == "count" else (True, [], .9)
    location = (False, ["location_rejected"], .1) if rejection == "location" else (True, [], .9)
    if location_unknown:
        location = (False, [], .2599)
    summarize = Mock(return_value=FULL)
    ns = dict(time=SimpleNamespace(monotonic=lambda: 0.0), re=re,
              image_embedding=lambda image: object(),
              score_environment=lambda *a: {"outdoor_market_square": .9, "indoor_room": .1},
              score_principal_people=lambda *a: {},
              principal_count_evidence=lambda *a: count,
              scene_location_evidence=lambda *a: location,
              score_action_contrast=lambda *a: None,
              OUTDOOR={"outdoor_market_square"}, INDOOR={"indoor_room"},
              outfit_requires_bare=lambda *a: False,
              summarize=summarize,
              insufficient_scene_caption=lambda s: len(s.split()) < 8,
              wall_brace_required=lambda spec: required_wall,
              check_wall_action=lambda caption, spec:
                  (caption == ACTION, [], {"required": True, "ground_pose": False}),
              scene_caption_conflicts=lambda *a: [],
              scene_action_conflicts=lambda *a: [],
              caption_asserts_single_person=lambda *a: False,
              face_observability=lambda spec: {},
              face_similarity_decision=lambda *a: {"verdict": "unobservable", "reason": "missing"},
              requested_outerwear_color=lambda *a: None)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<real-analyze>", "exec"), ns)
    spec = {"composition": "neural_story", "environment": {"id": environment},
            "characters": [{"name": "fixture"}], "variant": {"outfit": "default"}}
    return lambda: ns["analyze"](kind, Mock(), spec, "cinematic"), summarize

def composed_assess(validation, environment="outdoor_market_square", required_wall=False):
    """Whole actual assess function with only image/model/geometry dependencies isolated."""
    tree = ast.parse((WORKER_DIR / "worker.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "assess")
    im = Mock()
    im.size = (1216, 704)
    im.convert.return_value = im
    source = MagicMock()
    geometry = Mock(side_effect=AssertionError("control must not invoke Comfy"))
    ns = dict(time=SimpleNamespace(monotonic=lambda: 0.0), io=io, base64=base64,
              Image=SimpleNamespace(open=lambda stream: source),
              ImageOps=SimpleNamespace(exif_transpose=lambda image: im),
              retry_plan=lambda job: {"category": "scene"},
              resolve_scene_action=lambda *a: {"required": required_wall},
              detect_four_panel_collage=lambda image: dict(seam_x_ratio=0, seam_y_ratio=0,
                  repeat_left=0, repeat_right=0, detected=False),
              pil_png=lambda image: b"fixture_png", wall_brace_required=lambda spec: required_wall,
              choose_approved_reference=lambda *a, **kw: (None, "unobservable_fixture"),
              verify_with_comfy=geometry,
              os=SimpleNamespace(environ={}), VISION="loopback-fixture", 
              request=lambda *a, **kw: validation,
              HTTPError=HTTPError, URLError=URLError)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<real-assess>", "exec"), ns)
    job = {"kind": "scene", "spec": {"composition": "neural_story",
           "environment": {"id": environment}, "characters": [{"name": "fixture"}]}}
    result = ns["assess"](job, b"fixture_png", None)[1]
    geometry.assert_not_called()
    return result

class FailFastTests(unittest.TestCase):
    def test_mandatory_location_rejection_skips_only_vlm(self):
        run, caption = load(rejection="location")
        result = run()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reasons"], ["location_rejected"])
        self.assertFalse(result["scene_location_verified"])
        self.assertEqual(result["scene_location_confidence"], .1)
        self.assertEqual(result["caption"], "")
        self.assertEqual(result["vlm_caption_ms"], 0.0)
        self.assertEqual(result["vlm_skipped_reason"], "pre_vlm_mandatory_reject")
        self.assertIsNone(result["scene_action_verified"])
        caption.assert_not_called()

    def test_count_rejection_retains_reject_evidence(self):
        run, caption = load(rejection="count")
        result = run()
        qa = composed_assess(result)
        self.assertEqual(result["reasons"], ["count_rejected"])
        self.assertFalse(result["scene_count_verified"])
        self.assertEqual(result["scene_count_confidence"], .1)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(qa["passed"])
        self.assertEqual(qa["reasons"], ["count_rejected"])
        self.assertEqual(qa["metrics"]["vlm_skipped_reason"], "pre_vlm_mandatory_reject")
        caption.assert_not_called()

    def test_no_prior_rejection_keeps_normal_caption(self):
        run, caption = load()
        result = run()
        self.assertEqual(caption.call_count, 1)
        self.assertEqual(result["caption"], FULL)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["reasons"], [])
        self.assertIsNone(result["vlm_skipped_reason"])

    def test_caption_retry_and_mandatory_action_question_preserved(self):
        run, caption = load(required_wall=True)
        caption.side_effect = ["Two.", FULL, ACTION]
        result = run()
        qa = composed_assess(result, required_wall=True)
        self.assertEqual(caption.call_count, 3)
        self.assertTrue(result["scene_action_verified"])
        self.assertEqual(result["caption"], FULL)
        self.assertEqual(result["scene_action_observation"], ACTION)
        self.assertIsNone(result["vlm_skipped_reason"])
        self.assertTrue(qa["passed"])
        self.assertEqual(qa["evidence"]["action"]["verdict"], "verified")

    def test_sprite_path_is_not_short_circuited(self):
        run, caption = load(kind="sprite")
        result = run()
        self.assertEqual(caption.call_count, 1)
        self.assertEqual(result["caption"], FULL)
        self.assertEqual(result["status"], "passed")
        self.assertIsNone(result["vlm_skipped_reason"])

    def test_background_path_is_not_short_circuited(self):
        run, caption = load(rejection="location", kind="background")
        result = run()
        self.assertEqual(caption.call_count, 1)
        self.assertEqual(result["caption"], FULL)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reasons"], ["location_rejected"])
        self.assertIsNone(result["vlm_skipped_reason"])

    def test_location_unknown_preserves_whole_assess_failure_and_unknown_action(self):
        run, caption = load(location_unknown=True, required_wall=True)
        result = run()
        qa = composed_assess(result, required_wall=True)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(qa["passed"])
        self.assertEqual(qa["reasons"], ["Required CG location not independently verified"])
        self.assertEqual(qa["semantic_status"], "failed")
        self.assertEqual(qa["evidence"]["location"],
                         {"verdict": "unobservable", "confidence": .2599})
        self.assertEqual(qa["evidence"]["count"],
                         {"verdict": "verified", "confidence": .9})
        self.assertEqual(qa["evidence"]["action"],
                         {"verdict": "unobservable", "features": {}})
        self.assertEqual(qa["metrics"]["vlm_skipped_reason"], "mandatory_location_unverified")
        self.assertNotIn("scene_action_verified", qa["metrics"])
        self.assertEqual(result["caption"], "")
        self.assertEqual(result["vlm_caption_ms"], 0.0)
        caption.assert_not_called()

    def test_verified_location_accepted_case_is_not_skipped(self):
        for required_wall in (False, True):
            with self.subTest(required_wall=required_wall):
                run, caption = load(required_wall=required_wall)
                if required_wall:
                    caption.return_value = ACTION
                result = run()
                qa = composed_assess(result, required_wall=required_wall)
                self.assertTrue(qa["passed"])
                self.assertEqual(qa["reasons"], [])
                self.assertEqual(qa["semantic_status"], "passed")
                self.assertEqual(qa["evidence"]["location"]["verdict"], "verified")
                self.assertEqual(caption.call_count, 1)
                self.assertIsNone(result["vlm_skipped_reason"])
                self.assertNotIn("vlm_skipped_reason", qa["metrics"])

    def test_unclassified_environment_unknown_location_is_not_skipped(self):
        run, caption = load(location_unknown=True, environment="unclassified")
        result = run()
        qa = composed_assess(result, environment="unclassified")
        self.assertTrue(qa["passed"])
        self.assertEqual(qa["reasons"], [])
        self.assertEqual(qa["evidence"]["location"]["verdict"], "unobservable")
        self.assertEqual(caption.call_count, 1)
        self.assertIsNone(result["vlm_skipped_reason"])
        self.assertNotIn("vlm_skipped_reason", qa["metrics"])


if __name__ == "__main__":
    unittest.main()
