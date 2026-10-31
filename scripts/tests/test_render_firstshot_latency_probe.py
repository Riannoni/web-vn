"""S-13 negative regression tests for source-only, fail-closed latency evidence."""
import json
import math
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import render_firstshot_latency_probe as probe


class LatencyProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.lab = self.root / "lab"
        self.lab.mkdir()

    def case(self, name="BG-01", prompt="p1", elapsed=11.04):
        d = {
            "case": name, "prompt_id": prompt, "png_sha256": "a" * 64,
            "g1": "PASS", "first_attempt": True,
            "started_at": "2026-10-31T10:00:00+00:00",
            "completed_at": "2026-10-31T10:00:11.040+00:00",
            "total_submit_to_output_seconds": elapsed,
            "submit_seconds": 0.001, "original_png_path": str(self.root / "no-png")
        }
        (self.lab / f"{name}-result.json").write_text(json.dumps(d))
        return d

    def test_firstshot_does_not_invent_gpu_or_fullturn(self):
        self.case()
        out = probe.build_report(self.lab, [], verify_png=False)
        row = out["lab"][0]
        self.assertEqual(row["stages_s"]["submit_to_png"], 11.04)
        for stage in ("queue_wait", "preflight", "gpu", "postprocess", "cpu_vlm", "qa", "retry", "publish", "full_turn"):
            self.assertIsNone(row["stages_s"][stage], stage)
        self.assertEqual(out["summary"]["submit_to_png"]["n"], 1)

    def test_integer_first_attempt_receipt_is_accepted(self):
        d = self.case()
        d["first_attempt"] = 1
        (self.lab / "BG-01-result.json").write_text(json.dumps(d))
        self.assertTrue(probe.build_report(self.lab, [], verify_png=False)["lab"][0]["first_attempt"])

    def test_worker_generation_is_comfy_roundtrip_not_gpu(self):
        events = [{"kind": "worker_timings", "job_id": "j1", "prompt_id": "p1",
                   "timings": {"prepare_ms": 120, "generation_ms": 23000,
                               "postprocess_ms": 310, "qa_ms": 70000}}]
        out = probe.build_report(None, events, verify_png=False)
        row = out["live"][0]
        self.assertEqual(row["stages_s"]["comfy_roundtrip"], 23)
        self.assertEqual(row["stages_s"]["qa"], 70)
        self.assertEqual(row["stages_s"]["graph_prepare"], .12)
        self.assertIsNone(row["stages_s"]["gpu"])
        self.assertIsNone(row["stages_s"]["full_turn"])

    def test_full_turn_requires_explicit_timestamps(self):
        events = [{"kind": "full_turn", "job_id": "j1",
                   "started_at": "2026-10-31T10:00:00Z",
                   "completed_at": "2026-10-31T10:01:43Z"}]
        out = probe.build_report(None, events, verify_png=False)
        self.assertEqual(out["live"][0]["stages_s"]["full_turn"], 103)
        self.assertIsNone(out["live"][0]["stages_s"]["qa"])

    def test_missing_timestamps_fail_closed(self):
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [{"kind": "full_turn", "job_id": "j1",
                                           "duration_seconds": 103}], verify_png=False)

    def test_duplicate_conflicting_stage_rejected(self):
        events = [
            {"kind": "stage", "job_id": "j1", "stage": "cpu_vlm",
             "started_at": "2026-10-31T10:00:00Z", "completed_at": "2026-10-31T10:00:10Z"},
            {"kind": "stage", "job_id": "j1", "stage": "cpu_vlm",
             "started_at": "2026-10-31T10:00:00Z", "completed_at": "2026-10-31T10:00:20Z"},
        ]
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, events, verify_png=False)

    def test_negative_nan_and_inverted_timestamps_rejected(self):
        for bad in (-1, float("nan"), float("inf")):
            with self.subTest(bad=bad), self.assertRaises(probe.EvidenceError):
                probe.build_report(self.lab, [{"kind": "worker_timings", "job_id": "j",
                    "timings": {"qa_ms": bad}}], verify_png=False)
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [{"kind": "stage", "job_id": "j", "stage": "queue_wait",
                "started_at": "2026-10-31T10:00:10Z", "completed_at": "2026-10-31T10:00:00Z"}],
                verify_png=False)

    def test_skipping_png_hash_cannot_create_visual_or_human_pass(self):
        self.case()
        review = {"case": "BG-01", "prompt_id": "p1", "png_sha256": "a" * 64,
                  "original_pixels_reviewed": True, "mandatory": ["environment"],
                  "checks": {"environment": "verified"},
                  "reviewer_type": "independent_human", "human_label": True}
        (self.lab / "BG-01-pixel-review.json").write_text(json.dumps(review))
        row = probe.build_report(self.lab, [], verify_png=False)["lab"][0]
        self.assertEqual(row["g2"], "NOT_REVIEWED")
        self.assertFalse(row["human_label"])
        self.assertNotIn("sha_bound_pixel_review", row["evidence"])

    def test_verified_original_png_can_pass_independent_review(self):
        import hashlib
        data = b"real checked bytes, not a generated image"
        png = self.root / "original.png"
        png.write_bytes(data)
        d = self.case()
        d["png_sha256"] = hashlib.sha256(data).hexdigest()
        d["original_png_path"] = str(png)
        (self.lab / "BG-01-result.json").write_text(json.dumps(d))
        review = {"case": "BG-01", "prompt_id": "p1",
                  "png_sha256": d["png_sha256"], "original_pixels_reviewed": True,
                  "mandatory": ["environment"],
                  "checks": {"environment": "verified"},
                  "reviewer_type": "independent_reviewer", "human_label": False}
        (self.lab / "BG-01-pixel-review.json").write_text(json.dumps(review))
        row = probe.build_report(self.lab, [], verify_png=True)["lab"][0]
        self.assertEqual(row["g2"], "PASS")
        self.assertTrue(row["original_png_sha_verified"])
        self.assertIn("sha_bound_pixel_review", row["evidence"])

    def test_sha_and_review_prompt_mismatch_rejected(self):
        self.case()
        review = {"case": "BG-01", "prompt_id": "different", "png_sha256": "a" * 64,
                  "original_pixels_reviewed": True, "mandatory": ["environment"],
                  "checks": {"environment": "verified"}, "human_label": False}
        (self.lab / "BG-01-pixel-review.json").write_text(json.dumps(review))
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [], verify_png=False)

    def test_review_mandatory_unknown_not_pass(self):
        self.case()
        review = {"case": "BG-01", "prompt_id": "p1", "png_sha256": "a" * 64,
                  "original_pixels_reviewed": True, "mandatory": ["environment"],
                  "checks": {"environment": "unobservable"}, "human_label": False}
        (self.lab / "BG-01-pixel-review.json").write_text(json.dumps(review))
        row = probe.build_report(self.lab, [], verify_png=False)["lab"][0]
        self.assertEqual(row["g2"], "FAIL")
        self.assertFalse(row["human_label"])

    def test_unattributed_visual_review_cannot_pass(self):
        self.case()
        review = {"case": "BG-01", "prompt_id": "p1", "png_sha256": "a" * 64,
                  "original_pixels_reviewed": True, "mandatory": ["environment"],
                  "checks": {"environment": "verified"}, "human_label": True}
        (self.lab / "BG-01-pixel-review.json").write_text(json.dumps(review))
        row = probe.build_report(self.lab, [], verify_png=False)["lab"][0]
        self.assertEqual(row["g2"], "FAIL")
        self.assertFalse(row["human_label"])

    def test_duplicate_prompt_across_jobs_rejected(self):
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [
                {"kind": "worker_timings", "job_id": "j1", "prompt_id": "p", "timings": {"qa_ms": 10}},
                {"kind": "worker_timings", "job_id": "j2", "prompt_id": "p", "timings": {"qa_ms": 20}}
            ], verify_png=False)

    def test_percentiles_are_observed_only(self):
        self.assertEqual(probe.percentiles([5.05, 6.024, 6.028, 7.029, 11.04])["p50"], 6.028)
        self.assertAlmostEqual(probe.percentiles([5.05, 6.024, 6.028, 7.029, 11.04])["p90"], 9.4356)
        self.assertIsNone(probe.percentiles([])["p90"])

    def test_empty_lab_directory_is_not_success(self):
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [], verify_png=False)

    def test_non_first_attempt_rejected(self):
        d = self.case()
        d["first_attempt"] = 2
        (self.lab / "BG-01-result.json").write_text(json.dumps(d))
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [], verify_png=False)

    def test_missing_original_png_rejected_by_default(self):
        self.case()
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [])

    def test_lab_join_rejects_wrong_png_sha(self):
        self.case()
        with self.assertRaises(probe.EvidenceError):
            probe.build_report(self.lab, [{"kind": "worker_timings", "job_id": "j1",
                "prompt_id": "p1", "png_sha256": "b" * 64,
                "timings": {"qa_ms": 20}}], verify_png=False)

    def test_actual_worker_published_log_parsing(self):
        log = self.root / "worker.log"
        log.write_text("2026-10-31T10:00Z python: PUBLISHED j-42 applied True quality passed timings " + json.dumps({"generation_ms": 12000, "qa_ms": 61000, "postprocess_ms": 100}) + "\n")
        events = probe._load_worker_log(log)
        row = probe.build_report(None, events)["live"][0]
        self.assertEqual(row["job_id"], "j-42")
        self.assertEqual(row["stages_s"]["comfy_roundtrip"], 12)
        self.assertEqual(row["stages_s"]["qa"], 61)
        self.assertIsNone(row["stages_s"]["gpu"])
        self.assertIsNone(row["stages_s"]["full_turn"])

    def test_malformed_worker_published_log_rejected(self):
        log = self.root / "worker.log"
        log.write_text("PUBLISHED j-42 invalid/private-data\n")
        with self.assertRaises(probe.EvidenceError):
            probe._load_worker_log(log)

    def test_private_png_paths_never_exported(self):
        self.case()
        report = probe.build_report(self.lab, [], verify_png=False)
        self.assertNotIn(str(self.root), json.dumps(report))


if __name__ == "__main__":
    unittest.main()
