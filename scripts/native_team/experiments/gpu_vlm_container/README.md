# Ready private container CPU/GPU VLM pair — Lab owns execution

No environment installation is needed. Reuse immutable Comfy image
`48d333170aa767164d97102b08db925d7bc0c922dce220b9445ba5e878779c43`
in TWO fresh disposable containers, CPU then CUDA, never the active Comfy container.
Both use the same image/vendor/weights/source/threads/case. Production CPU timings
from Python3.14/Transformers4.57 are separate references, not this paired baseline.

Root-observed image: Python3.12.3, torch2.11.0+rocm7.2, transformers4.55.0.
No timm install is added. Real CPU startup verifies existing imports; any missing
dependency stops before CUDA, with private logs. There is no fallback/retry/install.

The daemon comes from PR140 HEAD906d0ee800c1146450e6350538c36bb940f44daf.
Its private compatibility overlay uses `torch_dtype=torch.float32`, the argument
consumed by Transformers4.55, plus explicit offline cached CLIP/SmolVLM revisions.
This same overlay is used in both arms; eager/weights/thresholds/decoding stay fixed.
The reused PR140 assess helper only adds private full `/judge` response capture.

## Native Lab invocation

First use the existing exclusive workflow to establish no active game claims or
postprocess/publish jobs, pause known submitters safely, and check GPU memory.
The production worker does not necessarily obey the GPU lock. This runner DOES
NOT pause/restart services: it requires worker `inactive` and Comfy queue0/0 before
and after each arm. It does not certify other submitters or game claims for Lab.

Use the EXISTING lock FD already held by the Lab wrapper as `--lock-fd 9`.
If not yet opened, open the known existing file WITHOUT creating it, then flock:

```bash
test -f /home/Xavok/.local/share/web-vn-native-team/gpu-exclusive-lab.lock
exec 9</home/Xavok/.local/share/web-vn-native-team/gpu-exclusive-lab.lock
flock -n 9
```

Runner verifies FD inode37:13447465 and nonblocking exclusive ownership. No nested
lock is created. Keep the FD until both owned containers stop. An existing output
directory is refused; inspect partial records before any later justified attempt.

Set QA_BUNDLE to this staged directory; QA_SOURCE_TREE to a frozen source snapshot
with installed vision sibling *.py and qa-environments.json in its worker/ folder
(a full Git checkout is unnecessary); QA_WORKER and QA_DEPENDENCY_DIR to exact paired
production worker/siblings pinned by the real case; QA_OUTPUT to a new private path
whose parent already exists. The known H3 case may be supplied without rewriting
its kind/spec/prompt. Only vision_url is retargeted to port19312, identically for
both arms, and both original/new case digests are recorded.

```bash
python3 "$QA_BUNDLE/run_pair.py" --execute --lock-fd 9 \
  --source-tree "$QA_SOURCE_TREE" --worker "$QA_WORKER" \
  --dependency-dir "$QA_DEPENDENCY_DIR" --case "$QA_CASE" \
  --output-root "$QA_OUTPUT" --threads 5 --port 19312 \
  --assessor-python /home/Xavok/.local/share/mcp-vn/venv/bin/python \
  --vendor /home/Xavok/.local/share/mcp-vn-comfy/vendor-python \
  --hf-hub /home/Xavok/.cache/huggingface/hub
```

Omit `--execute` to print the two exact container commands without touching runtime.
Use the normal bounded Lab job mechanism for execution; do not hold a long SSH tool
call open. Startup cap120s per arm, assess cap180s; no automatic repeated attempts.

Containers bind only127.0.0.1:19312 using host networking because the existing
daemon binds loopback; there is no LAN publish. Source/vendor/cache are readonly,
rootfs readonly, /tmp private. Application XDG/Torch/Triton/MIOpen caches are created
under /tmp/qa-cache; HOME is unchanged. Only CUDA arm gets /dev/kfd,/dev/dri,keep-groups;
security baseline remains no-new-privileges,label=disable,shm2g,gfx1201 flags.
No production env/source, Comfy container, cached weights or active saves are changed.
The runner inspects its exact recorded container IDs even if the attached CLI exited,
stops running containers and verifies absent/stopped state. On unknown cleanup the
Lab wrapper must retain its borrowed GPU lease and reconcile; do not restore or
admit another GPU task merely because the runner exited. Lab restores any services
it paused through its existing exclusive workflow, including after runner failure.

Read pair-result.json plus private per-arm result.json/judge-response.json and logs.
Compare complete assess, nested caption/model/HTTP and startup separately; GPU
residency/load/transition time still matters for later render-to-ready E2E. This
first H3 pair is a device smoke, not proof for the 77s production CG or G2/<=20s.
Paired worker/source/input/case/final hashes must match before marking comparable.
Acceptance regression vs CPU is reported as such, not a Golden false-accept label.
Any acceptance regression or backend/cleanup failure prevents promotion.

Prepared locally only: no container startup/model/GPU execution. Focused offline
controls validate command isolation/admission/compatibility; runtime remains unknown.
