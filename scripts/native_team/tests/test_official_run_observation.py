"""Exercise the existing mesh CLI/SQLite, without network, model or GPU calls."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import scheduled_wake_mesh as m

RUN = "01234567-89ab-4cde-8fab-0123456789ab"
OLD_RUN = "11234567-89ab-4cde-8fab-0123456789ab"
RECEIPT = "a" * 64


def official(text, run_id=RUN, started="2026-11-01T07:00:00Z"):
    return {
        "id": m.TARGETS["e2e"], "is_enabled": True,
        "run_details": {
            "last_run": {
                "id": run_id, "recorded_status": "completed",
                "scheduled_for": started, "started_at": started,
                "completed_at": "2026-11-01T07:04:00Z", "chat_ref": None,
            },
            "latest_result": {
                "run_id": run_id, "content_text": text, "content_truncated": False,
                "is_failure_message": False, "requires_user_action": False,
                "created_at": "2026-11-01T07:04:00Z",
                "completed_at": "2026-11-01T07:04:00Z",
                "scheduled_for": started, "chat_ref": None,
            },
        },
    }


class OfficialRunObservationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "state").mkdir()
        self.script = Path(m.__file__)
        m.status(self.root)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), "--root", str(self.root), *args],
            capture_output=True, text=True, timeout=10,
        )

    def record(self, observation, requestor="dispatcher"):
        source = self.root / "official.json"
        source.write_text(json.dumps(observation), encoding="utf-8")
        result = self.cli("--record-run", str(source), "--target", "e2e",
                          "--requestor", requestor)
        self.assertEqual(result.returncode, 0, result.stderr[-700:])
        return json.loads(result.stdout)

    def test_completed_false_flags_cannot_hide_a_reported_safety_block(self):
        result = self.record(official(
            "BLOCKED: This tool call was blocked by OpenAI's safety checks. "
            "No new QA measurement; private PNG unavailable."))
        self.assertEqual(result["observation"]["cloud_status"], "completed")
        self.assertEqual(result["observation"]["operation_state"], "blocker_reported")
        self.assertEqual(result["observation"]["blocker_kinds"], ["safety_denial"])
        self.assertEqual(result["observation"]["product_result"], "unverified")
        self.assertEqual(result["observation"]["next_action"], "honor_denial_no_replay")
        self.assertFalse(result["automations_invoked"])
        self.assertFalse(result["automatic_retry"])
        status = json.loads(self.cli("--status", "--target", "e2e").stdout)
        self.assertEqual(status["run_observations"][0]["run_id"], RUN)
        self.assertEqual(status["pending_total"], 0)
        self.assertNotIn("content_text", status["run_observations"][0])

    def test_operator_can_record_actual_run_but_cannot_acknowledge_recipient(self):
        event = "b" * 40
        m.check(self.root, "e2e", "operation_blocked", event,
                "chief", reserve=True, now=100)
        result = self.record(official("BLOCKED: input unavailable"), "operator")
        self.assertTrue(result["recorded"])
        self.assertNotIn("operator", m.OBSERVERS)
        self.assertNotIn("operator", m.TARGETS)
        with self.assertRaisesRegex(ValueError, "only the recipient"):
            m.acknowledge(self.root, "e2e", "operation_blocked", event,
                          "operator", RECEIPT, RUN, now=101)
        pending = m.status(self.root, target="e2e")["pending"][0]
        self.assertIsNone(pending["consumed_at"])
        self.assertEqual(pending["delivery"]["status"], "reserved")

    def test_only_complete_transport_report_has_bounded_diagnostic_retry_plan(self):
        report = official("Connection timed out")
        summary = self.record(report)["observation"]
        plan = summary["diagnostic_retry_plan"]
        self.assertEqual(plan["operation"], "read_only_health_check")
        self.assertEqual(plan["max_retries"], 3)
        self.assertEqual(plan["delays_seconds"], [10, 30, 60])
        self.assertFalse(plan["automatic"])
        self.assertFalse(plan["replay_original_operation"])
        partial = official("Connection timed out", OLD_RUN)
        partial["run_details"]["latest_result"]["content_truncated"] = True
        self.assertIsNone(self.record(partial)["observation"]["diagnostic_retry_plan"])

    def test_recovery_classification_never_replays_an_operation(self):
        cases = [
            ("Connection timed out", ["transport"], "fresh_read_only_health_diagnostic"),
            ("Permission denied (publickey)", ["authentication"], "verify_authentication"),
            ("BLOCKED: fixture missing", ["other_blocker"], "inspect_reported_blocker"),
            ("Unknown GPU submission after connection timed out",
             ["unknown_submission", "transport"], "reconcile_unknown_no_replay"),
            ("Connection timed out; safety-denied",
             ["safety_denial", "transport"], "honor_denial_no_replay"),
        ]
        for text, kinds, action in cases:
            with self.subTest(text=text):
                result = self.record(official(text))
                self.assertEqual(result["observation"]["blocker_kinds"], kinds)
                self.assertEqual(result["observation"]["next_action"], action)
                self.assertFalse(result["automatic_retry"])
                if kinds != ["transport"]:
                    self.assertIsNone(result["observation"]["diagnostic_retry_plan"])
        with sqlite3.connect(self.root / "state/scheduled-wake-history.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wake_attempt").fetchone()[0], 0)

    def test_previous_result_is_not_attributed_to_a_new_in_progress_run(self):
        data = official("This tool call was blocked by OpenAI's safety checks.")
        data["run_details"]["last_run"]["id"] = OLD_RUN
        data["run_details"]["last_run"]["recorded_status"] = "in_progress"
        result = self.record(data)["observation"]
        self.assertFalse(result["result_matches_run"])
        self.assertEqual(result["operation_state"], "not_observed")
        self.assertEqual(result["blocker_kinds"], [])
        self.assertEqual(result["product_result"], "unverified")

    def test_russian_completed_report_with_unavailable_inputs_stays_blocked(self):
        data = official("Нового измерения CPU QA нет: приватный PNG и кандидат "
                        "недоступны в локальном окружении; ранее запрещённую "
                        "SSH-операцию не повторял.")
        result = self.record(data)["observation"]
        self.assertEqual(result["cloud_status"], "completed")
        self.assertEqual(result["operation_state"], "blocker_reported")
        self.assertEqual(result["blocker_kinds"], ["other_blocker"])
        self.assertEqual(result["product_result"], "unverified")

    def test_green_or_truncated_prose_never_establishes_product_acceptance(self):
        for truncated in (False, True):
            data = official("Completed. Unit tests passed.",
                            OLD_RUN if truncated else RUN)
            data["run_details"]["latest_result"]["content_truncated"] = truncated
            result = self.record(data)["observation"]
            self.assertEqual(result["product_result"], "unverified")
            self.assertEqual(result["operation_state"], "not_observed" if truncated
                             else "no_blocker_reported")
            self.assertFalse(result["requires_user_action"])

    def test_import_never_releases_unknown_wake_or_acknowledges_event(self):
        event = "b" * 40
        token = m.check(self.root, "e2e", "operation_blocked", event,
                        "chief", reserve=True, now=100)["reservation_id"]
        m.record_outcome(self.root, "e2e", "operation_blocked", event, "chief",
                         token, "unknown", RECEIPT, now=101)
        self.record(official("Completed. Tests passed."))
        pending = m.status(self.root, target="e2e")["pending"][0]
        self.assertIsNone(pending["consumed_at"])
        self.assertEqual(pending["delivery"]["status"], "unknown")
        self.assertFalse(m.check(self.root, "e2e", "operation_blocked", event,
                                "chief", reserve=True, now=10000)["eligible"])

    def test_late_import_of_older_run_cannot_hide_newer_observation(self):
        self.record(official("BLOCKED: private input unavailable"))
        self.record(official("Completed", OLD_RUN, "2026-11-01T06:00:00Z"))
        results = m.status(self.root, target="e2e")["run_observations"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], RUN)
        self.assertEqual(results[0]["operation_state"], "blocker_reported")

    def test_wrong_automation_identity_is_rejected_without_recording(self):
        data = official("Completed")
        data["id"] = m.TARGETS["reliability"]
        source = self.root / "wrong.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        result = self.cli("--record-run", str(source), "--target", "e2e",
                          "--requestor", "dispatcher")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(m.status(self.root).get("run_observations", []), [])

    def test_stale_in_progress_snapshot_cannot_erase_completed_blocker(self):
        self.record(official("BLOCKED: missing original"))
        older = official("Completed")
        older["run_details"]["last_run"]["recorded_status"] = "in_progress"
        older["run_details"]["latest_result"] = None
        result = self.record(older)
        self.assertFalse(result["recorded"])
        self.assertEqual(m.status(self.root)["run_observations"][0]["operation_state"],
                         "blocker_reported")

    def test_truncated_reimport_cannot_erase_full_blocker_evidence(self):
        self.record(official("This tool call was blocked by OpenAI's safety checks."))
        partial = official("Completed")
        partial["run_details"]["latest_result"]["content_truncated"] = True
        result = self.record(partial)
        self.assertFalse(result["recorded"])
        self.assertEqual(m.status(self.root)["run_observations"][0]["blocker_kinds"],
                         ["safety_denial"])


if __name__ == "__main__":
    unittest.main()
