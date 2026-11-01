# One real sprite QA call

Run in the existing CPU worker environment with Pillow, rembg/ONNX and the already
cached `isnet-general-use.onnx`. The explicitly named vision daemon must already
be running in its recorded configuration; this runner neither starts nor
reconfigures it. CPU rembg in this process does not establish the daemon's device:
record the actual external vision model/device separately. The current baseline
uses the existing CPU daemon; any external GPU/CUDA judge comparison and its
shared-runtime activation remain exclusively owned by Lab. This runner does not
load or activate that GPU model. Use only an independently permitted operation. No GPU generation,
remote API, model installation, game publication or denied-operation fallback.

Private case JSON (all files absolute; use actual SHA256 values):

```json
{
  "worker_sha256": "<exact staged worker hash>",
  "original": {"path": "/private/original.png", "sha256": "<actual>"},
  "source_job": {"path": "/private/source-job.json", "sha256": "<actual>"},
  "face": {"path": "/private/face-original.bytes", "sha256": "<actual>"},
  "background": "NONE",
  "u2net_home": "/absolute/existing/rembg-cache",
  "vision_url": "http://127.0.0.1:9312"
}
```

`source_job` must genuinely be a sprite job; its kind, spec and prompt are not
rewritten. If `spec.face_asset` exists, bind its authentic face bytes; otherwise
omit `face`. A background is either explicit `"NONE"` or another `{path, sha256}`
binding. Do not replace an original scene job with a sprite label. A reconstructed
diagnostic job must be declared as such in the private experiment evidence, never
claimed as an archived original effective job.

```bash
python3 scripts/native_team/experiments/sprite_assess_once.py \
  --worker /absolute/public-staging/worker.py \
  --dependency-dir /absolute/matching/worker-modules \
  --case /absolute/private/case.json \
  --output-root /absolute/private/new-qa-attempt
```

The output parent must exist; the output directory must not exist. It is claimed
once with mode 0700. Pins are checked before worker import, and `started.json`
persists before import/assessment. Existing output is refused even if empty or
partial: reconcile its records; never blindly replay an unknown call under a new
directory. Do not run concurrent requests against a busy shared vision service.

The real worker `assess()` runs once, including its actual CPU rembg, harmonization
and mandatory QA. Only POST to the exact loopback vision `/judge` is permitted,
with a maximum 45-second socket timeout and no redirect/retry. A timed-out server
request may still be running: this client does not cancel it or authorize replay.
The source-reviewed worker uses `CPUExecutionProvider` for rembg; sibling modules
must come from its matching trusted source. This is a narrow trusted-code runner,
not a general-purpose sandbox for arbitrary Python.

`result.json` keeps the unmodified QA result, full `assess` wall time, runner time,
input/source hashes and final PNG hash/length. `final.png` is retained privately
in the same protected output directory for independent Golden inspection; it is
never exported or published. This helper does not claim independent G2.
Full result text remains private; stdout is a short
status/path. An assessment FAIL is a completed measurement, not a runner failure.
`error.json` records the exception type and bounded private error if execution fails; preserve the
started record and inspect the operation before another separately justified run.

No performance or image-quality result is claimed by this helper's source check.
