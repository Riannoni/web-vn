import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/e2e/qa-attempt-cohort.py"
spec = importlib.util.spec_from_file_location("qa_attempt_cohort", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
AS_OF = dt.datetime(2026, 10, 31, 17, tzinfo=dt.timezone.utc)


def job(job_id="j", qa=(1000, 2000), vlm=1.9, status="failed"):
    base = dt.datetime(2026, 10, 30, 12, tzinfo=dt.timezone.utc)
    attempts = []
    for i, q in enumerate(qa):
        claimed = base + dt.timedelta(minutes=2 * i)
        finished = claimed + dt.timedelta(minutes=1)
        outcome = "rejected" if i < len(qa) - 1 else status
        attempts.append({
            "number": i + 1, "timings": {"qa_ms": q}, "outcome": outcome,
            "claimed_at": claimed.isoformat(), "finished_at": finished.isoformat(),
        })
    return {
        "id": job_id, "status": status, "attempts": len(qa),
        "attempt_history": attempts, "timings": {"qa_ms": sum(qa)},
        "qa": {"metrics": {"vlm_seconds": vlm}},
    }


def write_job(folder, filename, data, seconds_before=20):
    path = folder / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    os.utime(path, (AS_OF.timestamp() - seconds_before,) * 2)
    return path


class CohortTests(unittest.TestCase):
    def test_prior_retries_count_separately_from_last_vlm(self):
        row = module.summarize_job(job())
        self.assertEqual(
            (row["cumulative_qa_ms"], row["previous_qa_ms"], row["latest_qa_ms"]),
            (3000, 1000, 2000))
        self.assertEqual(row["latest_result_vlm_ms"], 1900)
        self.assertEqual(row["latest_qa_minus_latest_vlm_ms"], 100)

    def test_single_attempt_and_missing_vlm(self):
        row = module.summarize_job(job(qa=(1000,), vlm=None))
        self.assertEqual(row["previous_qa_ms"], 0)
        self.assertIsNone(row["latest_result_vlm_ms"])
        self.assertIsNone(row["latest_qa_minus_latest_vlm_ms"])

    def test_bad_attempts_fail_closed(self):
        for invalid in (True, float("nan"), -1, "1000"):
            bad = job()
            bad["attempt_history"][0]["timings"]["qa_ms"] = invalid
            with self.assertRaises(module.AuditError):
                module.summarize_job(bad)
        for invalid in (2, True, 1.0, "1"):
            bad = job()
            bad["attempt_history"][0]["number"] = invalid
            with self.assertRaisesRegex(module.AuditError, "attempt_number_not_contiguous"):
                module.summarize_job(bad)
        bad = job()
        bad["timings"]["qa_ms"] = 9999
        with self.assertRaisesRegex(module.AuditError, "attempt_job_qa_inconsistent"):
            module.summarize_job(bad)

    def test_latest_vlm_cannot_exceed_latest_attempt_qa(self):
        with self.assertRaisesRegex(module.AuditError, "latest_vlm_exceeds_latest_qa"):
            module.summarize_job(job(vlm=100))

    def test_nonterminal_or_malformed_status(self):
        for status in ("running", [], {}, None, 5):
            with self.assertRaisesRegex(module.AuditError, "nonterminal_job"):
                module.summarize_job(job(status=status))

    def test_terminal_outcomes_and_times_are_required(self):
        bad = job(status="done")
        bad["attempt_history"][-1]["outcome"] = "working"
        with self.assertRaisesRegex(module.AuditError, "attempt_outcome_nonterminal"):
            module.summarize_job(bad)
        bad["attempt_history"][-1]["outcome"] = "failed"
        with self.assertRaisesRegex(module.AuditError, "terminal_attempt_outcome_mismatch"):
            module.summarize_job(bad)
        for field in ("claimed_at", "finished_at"):
            bad = job()
            bad["attempt_history"][-1].pop(field)
            with self.assertRaises(module.AuditError):
                module.summarize_job(bad)
        bad = job()
        bad["attempt_history"][0]["finished_at"] = "2026-10-29T00:00:00Z"
        with self.assertRaisesRegex(module.AuditError, "attempt_timestamp_order_invalid"):
            module.summarize_job(bad)
        bad = job()
        bad["attempts"] = 3
        with self.assertRaisesRegex(module.AuditError, "attempt_count_inconsistent"):
            module.summarize_job(bad)

    def test_duplicate_identity_excludes_every_conflicting_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            a = job("duplicate", (1000,), vlm=0.8)
            b = job("duplicate", (9000,), vlm=0.8)
            c = job("unique", (2000,), vlm=1.8)
            write_job(d, "a.json", a)
            write_job(d, "b.json", b)
            write_job(d, "c.json", c)
            one = module.audit_directory(d, AS_OF, 48)
            write_job(d, "a.json", b)
            write_job(d, "b.json", a)
            two = module.audit_directory(d, AS_OF, 48)
            for result in (one, two):
                self.assertEqual(result["valid_job_count"], 1)
                self.assertEqual(result["excluded_by_reason"],
                                 {"ambiguous_duplicate_job_identity": 2})
                self.assertEqual(result["qa_totals_ms"]["all_attempts"], 2000)
            self.assertEqual(one["raw_file_sha256_manifest"], two["raw_file_sha256_manifest"])

    def test_aggregate_excludes_ambiguous_and_private_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            a = job("a", (1000, 2000))
            a["secret_prompt"] = "super-private-story-do-not-output"
            write_job(d, "input-0.json", a)
            write_job(d, "input-1.json", job("b", (1000,), vlm=0.8))
            write_job(d, "input-2.json", a)
            result = module.audit_directory(d, AS_OF, 48)
            self.assertEqual((result["raw_file_count"], result["valid_job_count"]), (3, 1))
            self.assertEqual(result["excluded_job_count"], 2)
            self.assertEqual(result["attempt_count"], 1)
            self.assertEqual(result["qa_totals_ms"]["all_attempts"], 1000)
            self.assertEqual(result["qa_totals_ms"]["previous_attempt_share_pct"], 0)
            self.assertEqual(result["authenticated_stages"]["gpu_only"],
                             {"status": "NOT_MEASURED", "n": 0})
            self.assertIsNone(result["publish_eligible_20s"]["passed"])
            output = json.dumps(result)
            for forbidden in ("super-private", "input-", '"id"', '"a"'):
                self.assertNotIn(forbidden, output)

    def test_outside_symlink_fails_before_cohort_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "jobs"
            d.mkdir()
            outside = write_job(root, "external.json", job("external"))
            (d / "input.json").symlink_to(outside)
            with self.assertRaisesRegex(module.AuditError, "job_symlink_unsupported"):
                module.audit_directory(d, AS_OF, 48)

    def test_permission_denied_cli_does_not_disclose_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_job(d, "hidden-source.json", job())
            stream = io.StringIO()
            with mock.patch.object(module.os, "open", side_effect=PermissionError(
                13, "Permission denied", "/private/hidden-source.json"
            )), contextlib.redirect_stderr(stream):
                code = module.main([
                    "--jobs-dir", str(d), "--as-of", "2026-10-31T17:00:00Z"
                ])
            self.assertEqual(code, 2)
            self.assertEqual(stream.getvalue().strip(),
                             "EVIDENCE_BLOCKED: filesystem_access_error")
            self.assertNotIn("hidden-source", stream.getvalue())
            self.assertNotIn("/private/", stream.getvalue())

    def test_invalid_file_stays_excluded_without_aborting_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_job(d, "bad.json", dict(job("bad"), status=[]))
            write_job(d, "valid.json", job("good"))
            result = module.audit_directory(d, AS_OF, 48)
            self.assertEqual(result["valid_job_count"], 1)
            self.assertEqual(result["excluded_by_reason"], {"nonterminal_job": 1})

    def test_fixed_window_and_missing_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            p = write_job(d, "j.json", job(), seconds_before=49 * 3600)
            result = module.audit_directory(d, AS_OF, 48)
            self.assertEqual(result["raw_file_count"], 0)
            self.assertEqual(result["source_reported_percentiles"]["cumulative_qa_ms"]["n"], 0)
            os.utime(p, (AS_OF.timestamp() + 1,) * 2)
            self.assertEqual(module.audit_directory(d, AS_OF, 48)["raw_file_count"], 0)

    def test_timezone_and_bounds(self):
        with self.assertRaises(module.AuditError):
            module.parse_utc("2026-10-31T17:00:00")
        with tempfile.TemporaryDirectory() as tmp:
            for hours in (0, -1, 721, float("nan")):
                with self.assertRaises(module.AuditError):
                    module.audit_directory(Path(tmp),
                                           module.parse_utc("2026-10-31T17:00:00Z"),
                                           hours)

    def test_linear_interpolated_percentiles(self):
        self.assertEqual(module.percentiles([10, 20, 30]),
                         {"n": 3, "p50_ms": 20, "p90_ms": 28})


if __name__ == "__main__":
    unittest.main()
