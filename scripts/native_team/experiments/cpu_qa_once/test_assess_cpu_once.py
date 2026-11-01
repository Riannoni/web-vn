import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class CPUReplayBoundaryTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name('assess_cpu_once.py')
        if not path.exists():
            self.fail('CPU replay runner does not exist yet')
        spec = importlib.util.spec_from_file_location('replay', path)
        self.replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.replay)

    def test_only_separate_loopback_vision_endpoint_is_allowed(self):
        for url in ('http://127.0.0.1:8188', 'http://127.0.0.1:9312',
                    'http://127.0.0.1:3100', 'https://example.com:19312',
                    'http://127.0.0.1:19312/other'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.replay.validate_endpoint(url)
        self.assertEqual(self.replay.validate_endpoint('http://127.0.0.1:19312'),
                         'http://127.0.0.1:19312')

    def test_geometry_cannot_submit_or_be_misreported_as_unavailable(self):
        module = SimpleNamespace()
        def assess(job, raw, background):
            try:
                module.verify_with_comfy()
            except Exception:
                return b'bad', {'passed': True}
        module.assess = assess
        with self.assertRaises(self.replay.CPUOnlyBoundary):
            self.replay.execute(module, {}, b'input', {}, None,
                                'http://127.0.0.1:19312')

    def test_game_publication_is_not_an_allowed_http_request(self):
        module = SimpleNamespace()
        def assess(job, raw, background):
            module.request('http://127.0.0.1:3100', '/worker/complete/id',
                           'POST', b'private')
        module.assess = assess
        with self.assertRaises(self.replay.CPUOnlyBoundary):
            self.replay.execute(module, {}, b'input', {}, None,
                                'http://127.0.0.1:19312')

    def test_exact_job_and_a_false_pass_are_preserved_not_relabelled(self):
        job = {'kind': 'sprite', 'spec': {'kind': 'sprite'}}
        def assess(actual, raw, background):
            self.assertEqual(actual, job)
            self.assertEqual(raw, b'original')
            self.assertIsNone(background)
            return b'final', {'passed': True, 'semantic_status': 'passed'}
        result = self.replay.execute(SimpleNamespace(assess=assess), job,
            b'original', {}, None, 'http://127.0.0.1:19312')
        self.assertTrue(result[1]['passed'])
        self.assertEqual(job['kind'], 'sprite')

    def test_changed_fixture_bytes_stop_before_assessment(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'input.json'
            p.write_text(json.dumps({'kind': 'scene'}))
            with self.assertRaises(ValueError):
                self.replay.read_pinned({'path': str(p), 'sha256': '0' * 64})

    def test_label_is_grounded_in_existing_review_without_requiring_receipt_file(self):
        label = self.replay.load_label({})
        self.assertEqual(label['source_url'], self.replay.GOLDEN_REVIEW_URL)
        self.assertFalse(label['local_review_file_verified'])
        self.assertEqual(label['verdict'], 'DIAGNOSTIC_G2_FAIL_NOT_CANONICAL')

    def test_optional_receipt_when_supplied_must_be_real_pinned_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'review.json'
            p.write_text('{}')
            with self.assertRaises(ValueError):
                self.replay.load_label({'golden_review': {
                    'path': str(p), 'sha256': self.replay.GOLDEN_REVIEW}})

    def test_missing_source_or_origin_never_claims_historical_reproduction(self):
        job = {'kind': 'sprite'}
        scope = self.replay.job_scope({}, job, None)
        self.assertIsNone(scope['source_kind'])
        self.assertIsNone(scope['kind_mismatch_preserved'])
        self.assertEqual(scope['effective_job_origin'], 'unconfirmed')
        self.assertFalse(scope['historical_reproduction_claimed'])
        scope = self.replay.job_scope({'effective_job_origin': 'archived_job'},
                                     job, {'kind': 'scene'})
        self.assertTrue(scope['kind_mismatch_preserved'])
        self.assertFalse(scope['historical_reproduction_claimed'])
        self.assertEqual(job, {'kind': 'sprite'})

    def test_full_judge_response_is_captured_privately_without_changing_verdict(self):
        body = json.dumps({'status': 'passed', 'caption': 'x' * 300,
                           'wardrobe': {'verdict': 'violated'}}).encode()
        module = SimpleNamespace()
        def assess(job, raw, background):
            response = module.request(module.VISION, '/judge', 'POST',
                                      {'kind': 'sprite'}, timeout=90)
            return b'final', {'passed': response['status'] == 'passed'}
        module.assess = assess
        trace = []
        opener = SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(body))
        with patch.object(self.replay, 'build_opener', return_value=opener):
            final, report = self.replay.execute(module, {}, b'input', {}, None,
                                               'http://127.0.0.1:19312', trace)
        self.assertTrue(report['passed'])
        self.assertEqual(trace[0]['response_body_utf8'], body.decode())
        self.assertEqual(json.loads(trace[0]['response_body_utf8'])['wardrobe'],
                         {'verdict': 'violated'})


if __name__ == '__main__':
    unittest.main()
