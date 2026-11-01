#!/usr/bin/env python3
"""One private container CPU/CUDA QA pair. Native GPU Lab admission required."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.request
import uuid

IMAGE = 'sha256:48d333170aa767164d97102b08db925d7bc0c922dce220b9445ba5e878779c43'
CLIP_REV = '3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268'
VLM_REV = '7b375e1b73b11138ff12fe22c8f2822d8fe03467'
BUNDLE = Path(__file__).resolve().parent


def assert_idle():
    state = subprocess.run(['systemctl', '--user', 'is-active', 'mcp-vn-worker'],
                           capture_output=True, text=True, timeout=5).stdout.strip()
    if state != 'inactive':
        raise RuntimeError('Lab must establish safe claims/submitter quiescence; worker is not inactive')
    with urllib.request.urlopen('http://127.0.0.1:8188/queue', timeout=3) as response:
        queue = json.load(response)
    if queue.get('queue_running') != [] or queue.get('queue_pending') != []:
        raise RuntimeError('Comfy queue is not known empty; no device experiment admitted')


def cleanup_owned(cidfile):
    if not cidfile.exists():
        raise RuntimeError('Container ID missing: retain Lab lease and reconcile owned command')
    cid = cidfile.read_text().strip()
    if not re.fullmatch(r'[0-9a-f]{64}', cid):
        raise RuntimeError('Malformed owned container ID; retain Lab lease')
    def state():
        read = subprocess.run(['podman', 'inspect', '--format', '{{json .State}}', cid],
                              capture_output=True, text=True, timeout=10)
        if read.returncode == 0:
            return json.loads(read.stdout)
        exists = subprocess.run(['podman', 'container', 'exists', cid],
                                capture_output=True, timeout=10)
        if exists.returncode == 1:
            return None
        raise RuntimeError('Owned container state unknown; retain Lab lease')
    observed = state()
    if observed is not None and (observed.get('Running') or observed.get('Paused')
            or observed.get('Status') in ('running', 'paused', 'stopping', 'restarting')):
        subprocess.run(['podman', 'stop', '--time', '5', cid], check=True, timeout=15,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    observed = state()
    if observed is not None and (observed.get('Running') is not False
            or observed.get('Paused') is True
            or observed.get('Status') not in ('exited', 'stopped', 'configured', 'created')):
        raise RuntimeError('Owned container not confirmed stopped; retain Lab lease')
    return {'container_id': cid, 'state': 'absent' if observed is None else observed['Status']}


def assert_comparable(results):
    fields = ('worker_sha256', 'source_job_sha256', 'original_sha256',
              'case_sha256', 'final_sha256')
    for field in fields:
        if results['cpu'][field] != results['cuda'][field]:
            raise RuntimeError('CPU/GPU pair not comparable: ' + field)


def command(args, arm, name, cidfile):
    cmd = ['podman', 'run', '--rm', '--pull=never', '--read-only',
           '--network=host', '--name', name, '--cidfile', str(cidfile),
           '--tmpfs', '/tmp:rw,nosuid,size=1g', '--shm-size=2g',
           '--security-opt=no-new-privileges', '--security-opt=label=disable']
    if arm == 'cuda':
        cmd += ['--device=/dev/kfd', '--device=/dev/dri', '--group-add=keep-groups']
    for source, target in [(args.source_tree, '/qa-source'), (BUNDLE, '/qa-bundle'),
                           (args.vendor, '/data/vendor-python'), (args.hf_hub, '/qa-hub')]:
        if ',' in str(source) or '\n' in str(source):
            raise ValueError('Unsupported mount path')
        cmd += ['--mount', f'type=bind,source={source},destination={target},ro']
    env = {'PYTHONPATH': '/qa-source/worker:/data/vendor-python',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
           'HF_HOME': '/tmp/qa-hf', 'HF_HUB_CACHE': '/qa-hub',
           'XDG_CACHE_HOME': '/tmp/qa-cache/xdg', 'TORCH_HOME': '/tmp/qa-cache/torch',
           'TRITON_CACHE_DIR': '/tmp/qa-cache/triton',
           'MIOPEN_USER_DB_PATH': '/tmp/qa-cache/miopen-db',
           'MIOPEN_CUSTOM_CACHE_DIR': '/tmp/qa-cache/miopen-kernels',
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
           'HF_HUB_DISABLE_TELEMETRY': '1', 'VN_VISION_PORT': str(args.port),
           'VN_VISION_THREADS': str(args.threads), 'VN_VLM_DEVICE': arm,
           'VN_CLIP_REVISION': CLIP_REV, 'VN_VLM_REVISION': VLM_REV,
           'HCC_AMDGPU_TARGET': 'gfx1201', 'HIP_ARCHITECTURES': 'gfx1201',
           'PYTORCH_ROCM_ARCH': 'gfx1201'}
    for k, v in env.items():
        cmd += ['--env', f'{k}={v}']
    return cmd + ['--entrypoint', 'python3', IMAGE, '/qa-bundle/container_entry.py']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('source-tree', 'worker', 'dependency-dir', 'case', 'output-root',
                 'assessor-python', 'vendor', 'hf-hub'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--threads', type=int, default=5)
    ap.add_argument('--port', type=int, default=19312)
    ap.add_argument('--lock-fd', type=int, required=True)
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    for name in ('source_tree', 'worker', 'dependency_dir', 'case', 'output_root',
                 'assessor_python', 'vendor', 'hf_hub'):
        setattr(args, name, getattr(args, name).resolve())
    if not 1024 <= args.port <= 65535 or args.port in (3100, 8188, 8190, 9312):
        raise ValueError('Separate loopback port required')
    if not 1 <= args.threads <= 8:
        raise ValueError('Expected existing 1..8 thread setting')
    if not args.execute:
        print(json.dumps({'status': 'PLAN_ONLY', 'image': IMAGE,
                          'cpu': command(args, 'cpu', 'PLAN-cpu', Path('/private/cpu.cid')),
                          'cuda': command(args, 'cuda', 'PLAN-cuda', Path('/private/cuda.cid'))}))
        return
    # Existing descriptor only: never create or resolve a nested namesake lock.
    lock = os.fstat(args.lock_fd)
    if (lock.st_dev, lock.st_ino) != (37, 13447465):
        raise RuntimeError('Expected existing shared GPU lock inode 37:13447465')
    fcntl.flock(args.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    image_id = subprocess.check_output(['podman', 'image', 'inspect', IMAGE,
                                       '--format', '{{.Id}}'], text=True, timeout=10).strip()
    if image_id.removeprefix('sha256:') != IMAGE.removeprefix('sha256:'):
        raise RuntimeError('Image identity mismatch')
    for directory in (args.source_tree / 'worker', args.dependency_dir, args.vendor, args.hf_hub):
        if not directory.is_dir():
            raise ValueError('Required existing directory absent: ' + str(directory))
    for model, rev in [('openai--clip-vit-base-patch32', CLIP_REV),
                       ('HuggingFaceTB--SmolVLM2-500M-Video-Instruct', VLM_REV)]:
        if not (args.hf_hub / ('models--' + model) / 'snapshots' / rev).is_dir():
            raise ValueError('Required cached snapshot absent')
    original_case = args.case.read_bytes()
    case = json.loads(original_case)
    if hashlib.sha256(args.worker.read_bytes()).hexdigest() != case['worker_sha256']:
        raise ValueError('Worker does not match the case pin')
    os.umask(0o077)
    args.output_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    def save(name, value):
        with (args.output_root / name).open('x') as f:
            json.dump(value, f, indent=2)
    # Only the judge endpoint changes; both arms read this exact same case.
    case['vision_url'] = f'http://127.0.0.1:{args.port}'
    case_path = args.output_root / 'paired-case.json'
    case_path.write_text(json.dumps(case, indent=2))
    token = uuid.uuid4().hex[:12]
    save('started.json', {'image': IMAGE, 'clip_revision': CLIP_REV, 'vlm_revision': VLM_REV,
         'original_case_sha256': hashlib.sha256(original_case).hexdigest(),
         'paired_case_sha256': hashlib.sha256(case_path.read_bytes()).hexdigest(),
         'scope': 'same_container_cpu_vs_vlm_cuda', 'pid': os.getpid(), 'started': time.time()})
    results = {}
    try:
        for arm in ('cpu', 'cuda'):
            assert_idle()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', args.port))
            cidfile = args.output_root / f'{arm}.cid'
            cmd = command(args, arm, f'vn-qa-{token}-{arm}', cidfile)
            save(f'{arm}-command.json', cmd)
            t0 = time.monotonic()
            with (args.output_root / f'{arm}-daemon.log').open('x') as log:
                process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 120
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(arm + ' daemon exited; inspect private log')
                        try:
                            with urllib.request.urlopen(case['vision_url'] + '/healthz', timeout=1) as r:
                                health = json.load(r)
                            break
                        except (OSError, ValueError):
                            if time.monotonic() >= deadline:
                                raise TimeoutError(arm + ' startup deadline')
                            time.sleep(0.25)
                    expected = 'cpu' if arm == 'cpu' else 'cuda'
                    if (not str(health.get('vlm_device', '')).startswith(expected)
                            or health.get('vlm_dtype') != 'torch.float32'
                            or health.get('clip_device') != 'cpu'):
                        raise RuntimeError('Actual device/dtype differs from requested experiment')
                    save(f'{arm}-health.json', {'health': health,
                         'startup_wall_seconds': time.monotonic() - t0})
                    arm_root = args.output_root / arm
                    subprocess.run([str(args.assessor_python), '-B',
                        str(BUNDLE / 'sprite_assess_once.py'), '--worker', str(args.worker),
                        '--dependency-dir', str(args.dependency_dir), '--case', str(case_path),
                        '--output-root', str(arm_root)], check=True, timeout=180,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    result = json.loads((arm_root / 'result.json').read_text())
                    judge = json.loads((arm_root / 'judge-response.json').read_text())
                    if judge.get('status') not in ('passed', 'failed'):
                        raise RuntimeError('No valid mandatory judge result')
                    results[arm] = {'assess_wall_seconds': result['assess_wall_seconds'],
                        'qa_passed': result['qa'].get('passed'), 'final_sha256': result['final_sha256'],
                        **{key: result[key] for key in ('worker_sha256', 'source_job_sha256',
                                                       'original_sha256', 'case_sha256')},
                        'judge_status': judge['status'], 'judge_stages': judge.get('qa_stage_ms'),
                        'caption_ms': judge.get('vlm_caption_ms')}
                finally:
                    save(f'{arm}-cleanup.json', cleanup_owned(cidfile))
                    process.wait(timeout=15)
            # Any failure above stops before the next arm; no automatic retry.
            assert_idle()
        assert_comparable(results)
        save('pair-result.json', {'status': 'completed', 'comparable': True, 'arms': results,
             'acceptance_regression_vs_cpu': not results['cpu']['qa_passed'] and results['cuda']['qa_passed'],
             'g2': 'NOT_REVIEWED', 'asset_e2e': 'NOT_MEASURED'})
        print(json.dumps({'status': 'completed', 'result': str(args.output_root / 'pair-result.json')}))
    except Exception as error:
        save('error.json', {'status': 'failed_or_partial', 'type': type(error).__name__,
                           'error': str(error)[:1500], 'completed_arms': results})
        raise


if __name__ == '__main__':
    main()
