# Private GPU experiments — direct authority, 2026-11-01

The owner authorizes a short **test → inspect → fix → retest** loop. GPU Lab alone operates the GPU and shared Comfy runtime. This document separates private diagnostic execution from production publication; the latter retains complete QA, scene-version and release controls.

## Admission to an experiment

A real local source is identified and copied read-only into a private immutable fixture. Pin the source/face/outfit/contract, graph, model, seed, dimensions and one changed factor. Clearly mark source limitations. A known copied reference can be tested without a production HMAC/creation-time issuer. Unknown origin cannot establish canonical correctness.

Verify exclusive ownership, sufficient resources, empty/attributed queue and absence of unresolved submissions. Temporarily quiesce known competing dev submitters and preserve their previous states. Existing GPU locks are reused; do not create an independent conflicting GPU owner. Active saves and accepted assets are untouched; outputs use new private paths.

**No additional Chief, Decision or Integration approval is required** for this bounded diagnostic. Merged main, universal broker, full unrelated CI, signed publication receipts and completed production integration are not admission requirements. A minimal smoke of the actual runner/graph is required. Do not weaken real connector/platform approvals.

## Two honest execution paths

### Existing legacy LAB

The installed minute timer calls lab_exclusive.py around autonomous_dispatch.py. This dispatcher only understands its declared factors. Its existing running/review_pending fences and previous experiment identities are preserved; Golden records terminal legacy reviews with its existing writer. Do not disguise SDXL as prompt_text, delete markers, or call a queued legacy candidate accepted without evidence.

### Separate private diagnostic runner

When the legacy dispatcher cannot express an installed SDXL/Face-IPAdapter experiment, Lab may use a small isolated runner and existing Comfy nodes/API. No new production-dispatcher architecture is necessary. It must:

- reconcile legacy running/unknown jobs and acquire the **same installed GPU ownership lock (legacy root.parent.parent / gpu-exclusive-lab.lock; use that explicit verified path, never a new root-derived lock)**; stop if its exact lock cannot be established;
- stop known competing dev submitters, verify inactivity and queue before submission;
- accept only the frozen private experiment, use private image upload/LoadImage where needed, preserve decoded opacity/face identity truth and avoid private PNG bytes in public logs/GitHub;
- write a pre-submit manifest and exact prompt ID immediately, preserve unknown submissions without resend, and bind the original/final PNG by actual history and hash;
- record wall/stage durations, return known terminal state, and restore only previously active services after queue/ownership reconciliation;
- keep a distinct private experiment directory/IDs and never overwrite or clear legacy pending/running/review_pending records.

This is an authorized diagnostic route, not a workaround for a denied tool operation and not production broker protection. Unknown local GPU clients remain an explicit limitation; any foreign job stops the sequence.

## Budget and feedback

Baseline plus one candidate is the default; at most three actual GPU submissions per hypothesis with declared controls, including known terminal failures without usable PNGs. Every next trial follows a known outcome and stated causal change. Producer promptly inspects the exact output; Golden independently reviews in parallel. At most two new diagnostic outputs may await independent review. Record these limits in the private experiment manifest: they persist across Scheduled runs, worker changes and renamed variants. An adaptive follow-up requires actual inspection of the exact prior pixels; unavailable pixels do not justify another attempt. Reaching that cap pauses further generation, not unrelated CPU work.

Independent review is required for G2/publication, not a mandatory Chief/Decision approval before each diagnostic. A visual FAIL is actionable evidence; after two or three failed repairs of one defect choose a different hypothesis, not another cosmetic reroll. Missing exact output/unknown submission/resource fault/conflicting owner/protected-data damage stops the GPU lane.

Do not compare diagnostic trials as fresh first-shot successes. Freeze a new held-out acceptance pack later. No output is auto-published.

## Runtime activation and rollback

The existing owner authorization includes a narrow reversible experiment installation and needed service restart by GPU Lab, including already-reviewed telemetry. Preserve old files/service states; inspect queue/lease, apply only the intended component, verify actual loaded version and health, run the measurement, restore if incompatible. An isolated CPU service/port is preferable when sufficient. An unrelated production-hardening PR is not a prerequisite.

The known legacy wrapper snapshots services in autonomous/service-state.json and restores them only after known terminal completion and empty queue. Unknown submissions remain quiesced for reconciliation. Do not restart over a foreign job, reset another owner's lease or pretend an install took place because source merged.

Report actual prompt/output IDs, new original-pixel findings, full/partial timing with limits, retained input integrity and the next test. Never count the timer's NO_APPROVED_WORK, a downloaded model or a source-only PR as a GPU experiment.
