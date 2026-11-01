#!/usr/bin/env python3
"""One private CPU assess() smoke; no generation, publication or guessed refs.

Use an actual pinned effective job, recording its provenance honestly. An
archived source job is optional. A diagnostic smoke never proves historical fidelity.
This tool preserves a known-negative acceptance as evidence, never a new G2.
The caller must supply a separately started, isolated CPU vision daemon.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

NEGATIVE_PNG = 'd357709466e8d52107edb8df7fc5d7ea1934fadbd45e75398d253aa6a7291544'
GOLDEN_REVIEW = 'f3695f67577cd1e8efae2a2922f7e32ab5bf5e2b2e3243de6977d70889c11d2e'
GOLDEN_REVIEW_URL = 'https://github.com/Riannoni/web-vn/issues/31#issuecomment-6553434593'


class CPUOnlyBoundary(BaseException):
    """Cannot be swallowed by worker's ordinary unavailable/error fallback."""


def validate_endpoint(url):
    p = urlsplit(url)
    if (p.scheme != 'http' or p.hostname != '127.0.0.1' or
        p.username or p.password or p.path or p.query or p.fragment or
        p.port is None or p.port < 1024 or p.port in (3100, 8188, 9312)):
        raise ValueError('Use a separate loopback-only CPU vision port')
    return url


def read_pinned(item):
    path = Path(item['path'])
    if not path.is_absolute():
        raise ValueError('Fixture paths must be absolute')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise ValueError('Pinned fixture digest mismatch')
    return raw


def image_from_bytes(raw):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        return im.convert('RGBA')


def load_label(case):
    """Known independent label; its local receipt is optional, never invented."""
    receipt = case.get('golden_review')
    if receipt is not None:
        if receipt['sha256'] != GOLDEN_REVIEW:
            raise ValueError('Unexpected independent review digest')
        read_pinned(receipt)
    return {'source_url': GOLDEN_REVIEW_URL,
            'verdict': 'DIAGNOSTIC_G2_FAIL_NOT_CANONICAL',
            'reported_review_sha256': GOLDEN_REVIEW,
            'local_review_file_verified': receipt is not None}


def job_scope(case, job, source):
    origin = case.get('effective_job_origin', 'unconfirmed')
    if origin not in ('unconfirmed', 'archived_job', 'diagnostic_job'):
        raise ValueError('Unknown effective_job_origin')
    return {'source_kind': source.get('kind') if source is not None else None,
            'effective_kind': job.get('kind'),
            'kind_mismatch_preserved': (source.get('kind') != job.get('kind')
                                       if source is not None else None),
            'effective_job_origin': origin,
            'job_provenance_note': case.get('job_provenance_note'),
            'historical_reproduction_claimed': False}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CPUOnlyBoundary('Vision redirect is outside CPU replay scope')


def execute(module, job, raw, assets, background_id, endpoint, vision_trace=None):
    endpoint = validate_endpoint(endpoint)
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def forbidden(*args, **kwargs):
        raise CPUOnlyBoundary('GPU/game mutation required: no valid CPU-only sample')

    def fetch(asset_id):
        if asset_id not in assets:
            raise CPUOnlyBoundary('A referenced real asset is absent from the fixture')
        return image_from_bytes(assets[asset_id])

    def request(base, path, method='GET', data=None, headers=None, timeout=15):
        if base != endpoint or path != '/judge' or method != 'POST':
            forbidden()
        req = Request(endpoint + '/judge', json.dumps(data).encode(),
                      {'Content-Type': 'application/json'}, method='POST')
        with opener.open(req, timeout=min(timeout, 90)) as response:
            body = response.read()
            if vision_trace is not None:
                vision_trace.append({'response_body_utf8': body.decode('utf-8', errors='replace'),
                    'response_sha256': hashlib.sha256(body).hexdigest()})
            return json.loads(body)

    module.VISION = endpoint
    module.request = request
    module.fetch_asset = fetch
    for name in ('verify_with_comfy', 'upload_to_comfy', 'run_comfy',
                 'generate_gpu', 'finalize', 'stage', 'fail'):
        setattr(module, name, forbidden)
    return module.assess(job, raw, fetch(background_id) if background_id else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-dir', type=Path, required=True)
    parser.add_argument('--worker-sha256', required=True)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--case-sha256', required=True)
    parser.add_argument('--vision-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    endpoint = validate_endpoint(args.vision_url)
    case_raw = read_pinned({'path': str(args.case.resolve()), 'sha256': args.case_sha256})
    case = json.loads(case_raw)
    if case['original_png']['sha256'] != NEGATIVE_PNG:
        raise ValueError('This bounded replay is only for the recorded Golden negative')
    original = read_pinned(case['original_png'])
    label = load_label(case)
    source = (json.loads(read_pinned(case['source_job']))
              if case.get('source_job') is not None else None)
    job = json.loads(read_pinned(case['effective_job']))
    scope = job_scope(case, job, source)
    # No kind, resolution, outfit or identity is manufactured here.
    assets = {key: read_pinned(value) for key, value in case['assets'].items()}
    background_id = case['background_asset']  # explicit null when historical call used None
    face_id = (job.get('spec') or {}).get('face_asset')
    for asset_id in (background_id, face_id):
        if asset_id and asset_id not in assets:
            raise ValueError('Required actual reference bytes are missing')
    model = case['matte_model']
    if Path(model['path']).name != 'isnet-general-use.onnx':
        raise ValueError('Expected the existing CPU matte model')
    read_pinned(model)
    worker_dir = args.worker_dir.resolve()
    worker_path = worker_dir / 'worker.py'
    read_pinned({'path': str(worker_path), 'sha256': args.worker_sha256})
    args.output.mkdir(mode=0o700)  # fresh result only; never overwrite an earlier attempt
    os.umask(0o077)
    os.environ.update(VN_WORKER_TOKEN='isolated-no-game-credentials',
        VN_VISION_URL=endpoint, VN_VISION_QA='1', HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='',
        ROCR_VISIBLE_DEVICES='', U2NET_HOME=str(Path(model['path']).parent))
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(worker_dir))
    spec = importlib.util.spec_from_file_location('private_qa_worker', worker_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def expired(*_):
        raise CPUOnlyBoundary('CPU replay exceeded 180-second process budget')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(180)
    started = time.monotonic()
    vision_trace = []
    try:
        final, report = execute(module, job, original, assets, background_id, endpoint,
                                vision_trace)
    except CPUOnlyBoundary:
        (args.output / 'blocked.json').write_text(json.dumps({
            'status': 'BLOCKED_CPU_SCOPE_OR_BUDGET', 'valid_assessment': False}))
        raise
    finally:
        signal.alarm(0)
        (args.output / 'judge_responses.json').write_text(json.dumps(vision_trace, indent=2))
    elapsed_ms = (time.monotonic() - started) * 1000
    # Re-read immutable inputs after execution; a change invalidates the sample.
    for field in ('original_png', 'golden_review', 'source_job', 'effective_job', 'matte_model'):
        if case.get(field) is not None:
            read_pinned(case[field])
    for item in case['assets'].values():
        read_pinned(item)
    result = {'scope': 'offline_known_negative_cpu_smoke',
        'worker_sha256': args.worker_sha256, 'case_sha256': args.case_sha256,
        **scope, 'independent_label': label,
        'original_sha256': NEGATIVE_PNG,
        'face_reference_supplied': bool(face_id), 'replay_wall_ms': elapsed_ms,
        'vision_responses_captured': len(vision_trace),
        'final_sha256': hashlib.sha256(final).hexdigest(),
        'known_negative_accepted': report.get('passed') is True,
        'publish_eligible': False, 'new_g2': False, 'asset_e2e': 'NOT_MEASURED',
        'report': report}
    (args.output / 'result.json').write_text(json.dumps(result, indent=2))
    (args.output / 'final.png').write_bytes(final)
    print(json.dumps({key: result[key] for key in (
        'scope', 'replay_wall_ms', 'known_negative_accepted', 'new_g2', 'asset_e2e')}))


if __name__ == '__main__':
    main()
