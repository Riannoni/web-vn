import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import datetime as dt

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/e2e/qa-attempt-cohort.py"
spec=importlib.util.spec_from_file_location("qa_attempt_cohort", SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def job(job_id="j", qa=(1000,2000), vlm=1.9, status="failed"):
    return {"id":job_id,"status":status,
            "attempt_history":[{"number":i+1,"timings":{"qa_ms":q},"outcome":"failed"} for i,q in enumerate(qa)],
            "timings":{"qa_ms":sum(qa)},
            "qa":{"metrics":{"vlm_seconds":vlm}}}


class CohortTests(unittest.TestCase):
    def test_prior_retries_count_separately_from_last_vlm(self):
        row=module.summarize_job(job())
        self.assertEqual((row["cumulative_qa_ms"],row["previous_qa_ms"],row["latest_qa_ms"]),(3000,1000,2000))
        self.assertEqual(row["latest_result_vlm_ms"],1900)
        self.assertEqual(row["latest_qa_minus_latest_vlm_ms"],100)

    def test_single_attempt_and_missing_vlm(self):
        single=job(qa=(1000,),vlm=None)
        row=module.summarize_job(single)
        self.assertEqual(row["previous_qa_ms"],0)
        self.assertIsNone(row["latest_result_vlm_ms"])
        self.assertIsNone(row["latest_qa_minus_latest_vlm_ms"])

    def test_bad_attempts_fail_closed(self):
        for invalid in (True,float("nan"),-1,"1000"):
            bad=job()
            bad["attempt_history"][0]["timings"]["qa_ms"]=invalid
            with self.assertRaises(module.AuditError): module.summarize_job(bad)
        bad=job();bad["attempt_history"][0]["number"]=2
        with self.assertRaisesRegex(module.AuditError,"attempt_number_not_contiguous"):module.summarize_job(bad)
        bad=job();bad["timings"]["qa_ms"]=9999
        with self.assertRaisesRegex(module.AuditError,"attempt_job_qa_inconsistent"):module.summarize_job(bad)

    def test_latest_vlm_cannot_exceed_latest_attempt_qa(self):
        with self.assertRaisesRegex(module.AuditError,"latest_vlm_exceeds_latest_qa"):
            module.summarize_job(job(vlm=100))

    def test_nonterminal_is_not_published_or_measured(self):
        with self.assertRaisesRegex(module.AuditError,"nonterminal_job"):
            module.summarize_job(job(status="running"))

    def test_audit_includes_failures_excludes_duplicates_and_no_private_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            records=[job("a",(1000,2000)),job("b",(1000,),vlm=0.8),job("a",(1000,2000))]
            records[0]["secret_prompt"]="super-private-story-do-not-output"
            as_of=dt.datetime(2026,10,31,17,tzinfo=dt.timezone.utc)
            for index,record in enumerate(records):
                path=d/f"input-{index}.json"
                path.write_text(json.dumps(record))
                os.utime(path,(as_of.timestamp()-20,as_of.timestamp()-20))
            result=module.audit_directory(d,as_of,48)
            self.assertEqual(result["valid_job_count"],2)
            self.assertEqual(result["raw_file_count"],3)
            self.assertEqual(result["excluded_by_reason"],{"duplicate_job_identity":1})
            self.assertEqual(result["attempt_count"],3)
            self.assertEqual(result["qa_totals_ms"]["all_attempts"],4000)
            self.assertEqual(result["qa_totals_ms"]["previous_attempt_share_pct"],25)
            self.assertEqual(result["authenticated_stages"]["gpu_only"],{"status":"NOT_MEASURED","n":0})
            self.assertEqual(result["publish_eligible_20s"]["passed"],None)
            text=json.dumps(result)
            self.assertNotIn("super-private",text)
            self.assertNotIn("input-",text)
            self.assertNotIn('"id"',text)

    def test_fixed_window_and_missing_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            p=d/"j.json";p.write_text(json.dumps(job()))
            as_of=dt.datetime(2026,10,31,17,tzinfo=dt.timezone.utc)
            os.utime(p,(as_of.timestamp()-49*3600,as_of.timestamp()-49*3600))
            result=module.audit_directory(d,as_of,48)
            self.assertEqual(result["raw_file_count"],0)
            self.assertEqual(result["source_reported_percentiles"]["cumulative_qa_ms"]["n"],0)
            os.utime(p,(as_of.timestamp()+1,as_of.timestamp()+1))
            self.assertEqual(module.audit_directory(d,as_of,48)["raw_file_count"],0)

    def test_timezone_and_bounds(self):
        with self.assertRaises(module.AuditError):module.parse_utc("2026-10-31T17:00:00")
        with tempfile.TemporaryDirectory() as tmp:
            for hours in (0,-1,721,float("nan")):
                with self.assertRaises(module.AuditError):module.audit_directory(Path(tmp),module.parse_utc("2026-10-31T17:00:00Z"),hours)

    def test_linear_interpolated_percentiles(self):
        self.assertEqual(module.percentiles([10,20,30]),{"n":3,"p50_ms":20,"p90_ms":28})


if __name__=="__main__":unittest.main()
