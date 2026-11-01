import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import Mock, patch
import run_pair


class ContainerPlan(unittest.TestCase):
    def test_same_image_readonly_bindings_and_gpu_only_device_grants(self):
        args = SimpleNamespace(source_tree=Path('/source'), vendor=Path('/vendor'),
                               hf_hub=Path('/hub'), port=19312, threads=5)
        cpu = run_pair.command(args, 'cpu', 'owned-cpu', Path('/output/cpu.cid'))
        gpu = run_pair.command(args, 'cuda', 'owned-cuda', Path('/output/cuda.cid'))
        for cmd in (cpu, gpu):
            self.assertIn(run_pair.IMAGE, cmd)
            self.assertIn('--read-only', cmd)
            self.assertIn('--pull=never', cmd)
            self.assertNotIn('--privileged', cmd)
            self.assertTrue(all(x.endswith(',ro') for x in cmd if x.startswith('type=bind,')))
            self.assertIn('VN_CLIP_REVISION=' + run_pair.CLIP_REV, cmd)
            self.assertIn('VN_VLM_REVISION=' + run_pair.VLM_REV, cmd)
            self.assertIn('MIOPEN_CUSTOM_CACHE_DIR=/tmp/qa-cache/miopen-kernels', cmd)
            self.assertFalse(any(x.startswith('HOME=') for x in cmd))
        self.assertFalse(any(x.startswith('--device') for x in cpu))
        self.assertIn('--device=/dev/kfd', gpu)
        self.assertIn('--device=/dev/dri', gpu)
        self.assertIn('--group-add=keep-groups', gpu)

    def test_active_worker_rejects_before_queue_or_container_action(self):
        with patch.object(run_pair.subprocess, 'run', return_value=SimpleNamespace(stdout='active')), \
             patch.object(run_pair.urllib.request, 'urlopen') as query:
            with self.assertRaises(RuntimeError):
                run_pair.assert_idle()
            query.assert_not_called()

    def test_busy_or_unknown_queue_rejects(self):
        for queue in ({'queue_running': [1], 'queue_pending': []}, {}):
            with patch.object(run_pair.subprocess, 'run', return_value=SimpleNamespace(stdout='inactive')), \
                 patch.object(run_pair.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(queue).encode())):
                with self.assertRaises(RuntimeError):
                    run_pair.assert_idle()

    def test_known_idle_admission_is_only_read_checks(self):
        with patch.object(run_pair.subprocess, 'run', return_value=SimpleNamespace(stdout='inactive')) as service, \
             patch.object(run_pair.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"queue_running":[],"queue_pending":[]}')):
            run_pair.assert_idle()
            self.assertEqual(service.call_args.args[0], ['systemctl', '--user', 'is-active', 'mcp-vn-worker'])

    def test_transformers455_fp32_compatibility_and_private_judge_capture(self):
        folder = Path(__file__).parent
        vision = (folder / 'vision_daemon.py').read_text()
        self.assertIn('torch_dtype=torch.float32', vision)
        self.assertNotIn('VLM_ID,dtype=', vision)
        self.assertEqual(vision.count('local_files_only=True'), 4)
        self.assertIn('save("judge-response.json", payload)', (folder / 'sprite_assess_once.py').read_text())

    def test_cleanup_inspects_running_owned_container_without_cli_state_assumption(self):
        with tempfile.TemporaryDirectory() as d:
            cid = Path(d) / 'owned.cid'
            cid.write_text('a' * 64)
            responses = [SimpleNamespace(returncode=0, stdout=json.dumps({'Running': True, 'Status': 'running'})),
                         SimpleNamespace(returncode=0),
                         SimpleNamespace(returncode=0, stdout=json.dumps({'Running': False, 'Status': 'exited'}))]
            with patch.object(run_pair.subprocess, 'run', side_effect=responses) as commands:
                self.assertEqual(run_pair.cleanup_owned(cid)['state'], 'exited')
                self.assertEqual(commands.call_args_list[1].args[0],
                                 ['podman', 'stop', '--time', '5', 'a' * 64])

    def test_cleanup_unknown_state_is_not_clean_shutdown(self):
        with tempfile.TemporaryDirectory() as d:
            cid = Path(d) / 'owned.cid'
            cid.write_text('a' * 64)
            with patch.object(run_pair.subprocess, 'run',
                              return_value=SimpleNamespace(returncode=125)):
                with self.assertRaises(RuntimeError):
                    run_pair.cleanup_owned(cid)

    def test_different_paired_hashes_cannot_be_reported_comparable(self):
        fields = ('worker_sha256', 'source_job_sha256', 'original_sha256', 'case_sha256', 'final_sha256')
        same = {field: 'a' * 64 for field in fields}
        run_pair.assert_comparable({'cpu': same, 'cuda': dict(same)})
        for field in fields:
            with self.assertRaises(RuntimeError):
                run_pair.assert_comparable({'cpu': same, 'cuda': {**same, field: 'b' * 64}})


if __name__ == '__main__':
    unittest.main()
