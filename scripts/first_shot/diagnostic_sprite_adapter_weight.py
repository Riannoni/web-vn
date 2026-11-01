#!/usr/bin/env python3
"""Prepare a private, no-submit SDXL/Pony one-factor IPAdapter-weight diagnostic.

Renderer CPU-only preparation. GPU Lab alone owns the existing shared GPU lock,
queue, admission, Comfy submission, original-PNG inspection and service restoration.
Never print/commit a graph, prompt, face reference or private source contents.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

BASE_SOURCE_SHA = '0bb1a6c953f3000f0a60b228015e48374e31e378c5e6810f8d3922bbee1a8231'
BASE_GRAPH_SHA = 'b94bece3abbc38cad860c1bd9d93e2efdefb8c10e1745d44c9d929a3275b3d08'
BASE_ORIGINAL_SHA = 'd357709466e8d52107edb8df7fc5d7ea1934fadbd45e75398d253aa6a7291544'
WEIGHT_MULTIPLIER = 0.75
HEX = re.compile(r'^[a-f0-9]{64}$')
PREFIX = re.compile(r'^private_renderer_diag_[A-Za-z0-9_-]{8,70}$')
PNG_MAGIC = bytes.fromhex('89504e470d0a1a0a')


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(v: object) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def require_digest(v: str) -> str:
    if not HEX.fullmatch(v):
        raise ValueError('invalid_sha256')
    return v


def read_pinned(path: Path, expected: str, max_bytes: int = 12_000_000) -> bytes:
    require_digest(expected)
    if path.is_symlink():
        raise ValueError('symlink_fixture_refused')
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes or st.st_nlink != 1:
        raise ValueError('unsafe_or_oversize_fixture')
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError('fixture_sha_mismatch')
    return raw


def nodes(graph: dict, class_type: str) -> list[tuple[str, dict]]:
    return [(n, x) for n, x in graph.items() if isinstance(x, dict) and x.get('class_type') == class_type]


def one(graph: dict, class_type: str) -> tuple[str, dict]:
    selected = nodes(graph, class_type)
    if len(selected) != 1:
        raise ValueError('expected_one_' + class_type)
    n, node = selected[0]
    if not isinstance(node.get('inputs'), dict):
        raise ValueError('invalid_inputs_' + class_type)
    return n, node['inputs']


def linked_to(link: object, node_id: str) -> bool:
    return (isinstance(link, list) and len(link) == 2 and
            str(link[0]) == node_id and type(link[1]) is int and link[1] == 0)


def prepare_candidate(graph: dict, prefix: str) -> tuple[dict, dict]:
    """One causal change: IPAdapterAdvanced.weight *= 0.75; filename is routing."""
    if not isinstance(graph, dict) or not PREFIX.fullmatch(prefix):
        raise ValueError('graph_or_private_output_prefix_invalid')
    checkpoint_id, checkpoint = one(graph, 'CheckpointLoaderSimple')
    if 'pony' not in str(checkpoint.get('ckpt_name', '')).lower():
        raise ValueError('not_expected_pony_checkpoint')
    adapter_id, adapter = one(graph, 'IPAdapterAdvanced')
    sampler_id, sampler = one(graph, 'KSampler')
    latent_id, latent = one(graph, 'EmptyLatentImage')
    save_id, save = one(graph, 'SaveImage')
    decode_id, decode = one(graph, 'VAEDecode')
    if not linked_to(sampler.get('model'), adapter_id):
        raise ValueError('face_adapter_not_consumed_by_sampler')
    if not linked_to(sampler.get('latent_image'), latent_id):
        raise ValueError('body_seed_or_unknown_latent')
    if not linked_to(decode.get('samples'), sampler_id) or not linked_to(save.get('images'), decode_id):
        raise ValueError('output_not_from_sampler')
    if not isinstance(adapter.get('image'), list) or len(adapter['image']) != 2:
        raise ValueError('missing_face_image_input')
    face_id = str(adapter['image'][0])
    if graph.get(face_id, {}).get('class_type') != 'LoadImage':
        raise ValueError('face_image_not_from_installed_loadimage')
    if not nodes(graph, 'IPAdapterModelLoader') or not nodes(graph, 'CLIPVisionLoader'):
        raise ValueError('face_adapter_dependencies_missing')
    if (type(latent.get('width')) is not int or type(latent.get('height')) is not int or
            type(latent.get('batch_size')) is not int or latent['batch_size'] != 1 or
            latent['width'] * latent['height'] > 832 * 1216 or
            min(latent['width'], latent['height']) < 256):
        raise ValueError('unbounded_canvas')
    if type(sampler.get('seed')) is not int or sampler.get('denoise') != 1.0:
        raise ValueError('not_fresh_latent_or_fixed_seed')
    w = adapter.get('weight')
    if type(w) not in (float, int) or not (0.05 < w <= 1.5):
        raise ValueError('unexpected_adapter_weight')
    new_w = round(float(w) * WEIGHT_MULTIPLIER, 5)
    if new_w == w:
        raise ValueError('no_effective_weight_change')
    out = copy.deepcopy(graph)
    out[adapter_id]['inputs']['weight'] = new_w
    out[save_id]['inputs']['filename_prefix'] = prefix
    control = copy.deepcopy(out)
    control[adapter_id]['inputs']['weight'] = w
    control[save_id]['inputs']['filename_prefix'] = save.get('filename_prefix')
    if control != graph:
        raise ValueError('multiple_causal_factors_changed')
    info = dict(hypothesis='Less late face-adapter pressure may permit accurate current outfit',
                changed_factor=f'{adapter_id}.inputs.weight', baseline_weight=w,
                candidate_weight=new_w, multiplier=WEIGHT_MULTIPLIER,
                output_filename_prefix=prefix, seed=sampler['seed'],
                width=latent['width'], height=latent['height'],
                checkpoint_filename=checkpoint['ckpt_name'],
                graph_has_face_adapter=True, graph_uses_fresh_latent=True,
                publication_eligible=False, g2='NOT_REVIEWED')
    return out, info


def create_private_file(path: Path, b: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(b)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline-graph', type=Path, required=True)
    ap.add_argument('--source-snapshot', type=Path, required=True)
    ap.add_argument('--face-png', type=Path, required=True)
    ap.add_argument('--face-sha256', required=True)
    ap.add_argument('--baseline-sha256', default=BASE_GRAPH_SHA)
    ap.add_argument('--source-sha256', default=BASE_SOURCE_SHA)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    source_bytes = read_pinned(args.source_snapshot, args.source_sha256)
    face_bytes = read_pinned(args.face_png, args.face_sha256)
    if not face_bytes.startswith(PNG_MAGIC):
        raise ValueError('face_fixture_not_png')
    raw = args.baseline_graph.read_bytes()
    graph = json.loads(raw)
    if not isinstance(graph, dict):
        raise ValueError('baseline_graph_not_object')
    sha = require_digest(args.baseline_sha256)
    if sha not in (digest(raw), digest(canon(graph))):
        raise ValueError('exact_baseline_graph_sha_mismatch')
    candidate, info = prepare_candidate(graph, args.output_prefix)
    candidate_bytes = canon(candidate)
    manifest = dict(schema='renderer_private_sprite_weight_ab_v1',
                    source_sha256=digest(source_bytes), face_png_sha256=digest(face_bytes),
                    baseline_original_sha256=BASE_ORIGINAL_SHA,
                    baseline_graph_sha256=sha, candidate_graph_sha256=digest(candidate_bytes),
                    gpu_submissions_consumed_before_candidate=1,
                    max_gpu_submissions_per_hypothesis=3,
                    max_unreviewed_diagnostic_outputs=2,
                    constraints='NO_SUBMIT. Lab confirms GPU lock, review backlog, queue/history, protected fixture and services.',
                    **info)
    out = args.output_dir
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        create_private_file(out / 'candidate_graph.json', candidate_bytes)
        create_private_file(out / 'candidate_manifest.json', canon(manifest))
    except Exception:
        for n in ('candidate_graph.json', 'candidate_manifest.json'):
            (out / n).unlink(missing_ok=True)
        out.rmdir()
        raise
    print(json.dumps({'candidate_graph_sha256': digest(candidate_bytes),
                      'manifest_sha256': digest(canon(manifest)),
                      'baseline_graph_sha256': sha,
                      'status': 'CPU_PREPARED_NO_GPU'}, sort_keys=True))


if __name__ == '__main__':
    main()
