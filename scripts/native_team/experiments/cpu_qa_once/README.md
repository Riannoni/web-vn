# One CPU smoke, then a real wardrobe candidate

Prepared 2026-11-01. Local helper only; no remote/model/GPU run was performed.
Target main confirmed by root: `ec165c1eacb2def7dcf6d82f7c6d082d4f351bad`.
This includes merged PR135's missing-face fail-closed change; preserve actual
face-reference availability when interpreting the smoke result.
[PR134](https://github.com/Riannoni/web-vn/pull/134) is already merged. Its
failed-with-empty-reasons fix cannot repair a semantic PASS on wrong clothing.
Run **one current-main smoke**, not a PR134 base/head pair.

## Actual private inputs

Known directory, with basenames still to be resolved by its owner:
`/home/Xavok/.local/share/web-vn-native-team/first-shot-lab-20261031/diagnostic-sdxl-sprite-20261101-1108`.

Required: original PNG, actual effective job JSON, every used face/background
asset, the actual background argument, and existing `isnet-general-use.onnx`.
Pin absolute paths and SHA256 in a private case. Original PNG SHA256:
`d357709466e8d52107edb8df7fc5d7ea1934fadbd45e75398d253aa6a7291544`.
Independent label: **DIAGNOSTIC_G2_FAIL_NOT_CANONICAL**, from the existing
[original-pixel Golden review](https://github.com/Riannoni/web-vn/issues/31#issuecomment-6553434593).
Its reported receipt SHA is
`f3695f67577cd1e8efae2a2922f7e32ab5bf5e2b2e3243de6977d70889c11d2e`.
A local review file is optional; if supplied, it must match. No receipt is invented.

The original source was scene; the old diagnostic's effective job was sprite.
Preserve an actual source file separately if available. Do not silently change
kind or substitute H2. If the historical effective job cannot be confirmed,
identify the chosen real diagnostic job and report a new smoke, not a historical
reproduction. Pinning bytes alone does not prove historical provenance.

Case schema (documentation only; populate real paths/digests and actual assets):

```json
{
  "original_png": {"path": "ACTUAL_ABSOLUTE_PATH", "sha256": "ACTUAL_DIGEST"},
  "effective_job": {"path": "ACTUAL_ABSOLUTE_PATH", "sha256": "ACTUAL_DIGEST"},
  "effective_job_origin": "unconfirmed",
  "job_provenance_note": "Actual archive/source evidence, or explicitly unknown",
  "assets": {},
  "background_asset": null,
  "matte_model": {"path": "ACTUAL_ABSOLUTE_PATH", "sha256": "ACTUAL_DIGEST"}
}
```

Populate `assets` by actual asset ID with pinned-file records. Background null is
valid only when the real call uses None; do not guess. Optional `source_job` and
`golden_review` use the same file schema. Origin labels are `unconfirmed`,
`archived_job`, `diagnostic_job`; these record the owner's account. The runner
never claims historical fidelity, and rechecks input bytes after assessment.

## One isolated attempt under existing authority and normal tool review

Standing owner authority covers this bounded private CPU smoke; no new chat or
root permission is required for each attempt. Actual platform review still
applies. A materially safer constrained action may be submitted through normal
tool review with its concrete risk reduction explained; do not replay or merely
reword a denied operation, or bypass its review through another role or route.

Resolve `QA_REPO`, `QA_PYTHON` (existing environment), `QA_CASE`, `QA_TOOL`,
`QA_ROOT` (fresh private directory), and `QA_THREADS` to actual values. Preserve
existing model cache/snapshot revisions and threads. No installs, new models,
eager/SDPA comparison or setup scripts. Missing cache/dependencies stop this smoke.
Stage the full tree because worker and vision import sibling modules:

```bash
set -euo pipefail
umask 077
QA_MAIN=ec165c1eacb2def7dcf6d82f7c6d082d4f351bad
mkdir -m 700 "$QA_ROOT"
mkdir "$QA_ROOT/main"
git -C "$QA_REPO" archive "$QA_MAIN" | tar -x -C "$QA_ROOT/main"
```

Check loopback port 19312 is free. Start the existing eager CPU implementation;
do not source production credentials or use live port 9312. Record own PID,
commit, model revisions, package versions and startup time.

```bash
env CUDA_VISIBLE_DEVICES= HIP_VISIBLE_DEVICES= ROCR_VISIBLE_DEVICES= \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 \
  VN_VISION_PORT=19312 VN_VISION_THREADS="$QA_THREADS" \
  "$QA_PYTHON" "$QA_ROOT/main/worker/vision_daemon.py" \
  >"$QA_ROOT/vision-main.log" 2>&1 &
QA_VISION_PID=$!
trap 'kill "$QA_VISION_PID" 2>/dev/null || true' EXIT INT TERM
```

Verify this PID owns the listener. Allow at most 120 seconds for startup; query
`http://127.0.0.1:19312/healthz` with a 2-second timeout. Stop on port collision,
memory pressure, missing cache, import failure or an actual approval denial.
Record actual worker and case SHA256 as `QA_WORKER_SHA` and `QA_CASE_SHA`:

```bash
timeout --kill-after=5s 210s "$QA_PYTHON" "$QA_TOOL" \
  --worker-dir "$QA_ROOT/main/worker" --worker-sha256 "$QA_WORKER_SHA" \
  --case "$QA_CASE" --case-sha256 "$QA_CASE_SHA" \
  --vision-url http://127.0.0.1:19312 --output "$QA_ROOT/result-main"
```

One attempt, no adaptive retries. Internal assess budget: 180 seconds; HTTP: at
most 90 seconds. Outer timeout covers import overhead. Only isolated `/judge`
HTTP is allowed; refs are local, token is dummy, matte provider is CPU. Comfy
geometry or game publication aborts, never returns a fabricated geometry PASS.
This is a bounded trusted-code harness, not a general security sandbox.

## Results, real candidate and rollback

`result.json` preserves actual assess acceptance/reasons/evidence/telemetry.
`judge_responses.json` privately retains full raw UTF-8 response bodies and hashes,
including wardrobe details and untruncated captions. No private bytes are printed.
Interpret `known_negative_accepted` alongside the recorded job provenance.

Telemetry admission requires an actual judge response and
`qa_vision_stage_integrity == "consistent"`, with client/server spans present.
A precheck that skips VLM is a real result, but does not test vision telemetry.
Compare same-attempt spans only; caption is nested in model analysis. Missing
fields stay NOT_MEASURED. `replay_wall_ms` includes wrapper/background preparation;
`metrics.qa_assess_total_ms` is the actual assess span. Label cold matte/model
startup. This is no new G2, historical 12.0278-second equivalence, asset E2E or
latency distribution. Caption-only `qa-shadow-benchmark.py` is not a substitute.

After that result, obtain actual wardrobe v3 bytes/provenance. Reported patch SHA:
`278bf599ed3cbd2957c907f051c0276a9450d57b2a7285713584f2e9cd7f846a`.
Its 25 lexical tests are not PNG evidence. Apply only that real patch to a separate
full candidate tree; inspect the diff. Preserve model/cache/threads/case/refs/PNG.

**Restart the owned isolated daemon from the candidate tree before its one attempt.**
Wardrobe imports occur at startup; replacing only `--worker-dir` with the old
daemon does not apply the candidate. Stop and wait for the exact owned baseline
PID, verify port release, start candidate daemon and record its new PID. Use a
fresh result directory. Never load both daemons simultaneously or touch production.

Rollback: stop only the currently owned isolated daemon PID, retain private
results and remove the trap after cleanup. No systemd/install/game/GPU changes.
Never kill by a broad process name. Local validation: 9 boundary tests with fake
workers/temporary bytes, including optional receipt, raw judge capture and honest
job/source scope; no real-model or quality claim follows from these tests.
