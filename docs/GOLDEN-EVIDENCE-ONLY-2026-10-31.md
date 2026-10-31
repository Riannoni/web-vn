# P0 #76 — native Golden evidence-only task (source-isolated, 2026-10-31)

**DRAFT / never a G2 or G3 certification by itself.** Read [AGENTS.md](../AGENTS.md) and [DEVELOPMENT-AND-TESTING.md](DEVELOPMENT-AND-TESTING.md) first. This implements a **separate** `visual_evidence` task kind for the native SQLite team, not a relaxation of source-code review. It is intended for independent original-pixel receipts that **do not change any Git file**. Independent Chief acceptance and deployment approval are still required.

## Why

A real original image from R-13 was independently reviewed by G-10 (prompt UUID and original PNG SHA verified; geometry/contact failed). The historical `G-10` source-only task remained `BLOCKED` because ordinary `teamctl submit` requires a non-empty committed source diff. That failure was in the task schema, **not** evidence that pixels had passed or that the reviewer never saw the image. This feature allows a **new** `G-n` evidence-only task, without recycling, rewriting or falsely completing historical G-10.

## Trust contract

Before an evidence task can be enqueued, a Chief-scoped private task specification must bind **five actual files by both absolute path and SHA-256**, under the PC user's `~/.local/share` private root:

- Original full-resolution PNG from the exact GPU prompt (not thumbnail or latest glob).
- Normalized **original typed Scene Contract** JSON, `schema=typed_scene_v1`, with a non-empty `mandatory_checks` list. This contract also binds the `case_id`, canonical-reference hash and source-save hash; these cannot be independently swapped.
- Original canonical reference, with its SHA matching the Scene Contract.
- The actual disposable source save / canonical source-state file, with a fixed SHA. Both submission and independent review re-read the bytes; stale source state fails closed.
- Immutable GPU job provenance receipt, `status=GPU_FINISHED_REVIEW_REQUIRED`, matching **the same prompt UUID, case ID, PNG filename and PNG SHA**. This can be the existing first-shot dispatcher `runs/<id>/result.json` if all required fields exist. The native evidence handler never sends `/prompt`.

The visual spec has exactly `schema, task_id, goal, generator_owner, case_id, prompt_id, priority, dependencies, artifacts`. Its task ID must be a **fresh** `G-<number>`, with `artifacts` exactly `original_png, scene_contract, canonical_ref, source_save, gpu_receipt`. Each artifact descriptor is `{"path":"<absolute private path>","sha256":"<64 lowercase hex>"}`. `dependencies` must exist and be completed before claim. The spec and its hash are stored in an additive `visual_task` SQLite table: there is **no source `changed_paths`**.

**The authoritative Scene Contract must come from the actual frozen game source and reference, not from the same model inventing an easier contract after seeing the pixels.** The normalized typed sidecar needs a source provenance trail in the owner's private manifest. Even perfect hashes cannot certify that a contract was originally truthful.

## Task lifecycle and commands

These commands run only against a **separate isolated PC team control checkout** until the Chief signs off. Put full spec and visual receipt JSON only in mode-0600 files in the private lab, never GitHub.

```bash
root="$HOME/.local/share/web-vn-native-team/run-20261031-full"
# Only once a trusted private spec and original files exist:
python3 "$root/control/teamctl.py" enqueue-visual --spec "$PRIVATE_SPEC_JSON"
python3 "$root/control/teamctl.py" claim --lane G --owner golden-reviewer-unique
# The claim returns an immutable task ID, owner and fresh fence.
# Review original pixels; write a private evidence/golden/*.json receipt.
python3 "$root/control/teamctl.py" submit-visual \
  --task "$TASK_ID" --owner "$CLAIM_OWNER" --fence "$FENCE" \
  --evidence "$PRIVATE_VISUAL_RECEIPT"
# Chief must independently verify the exact PNG, contract and observations:
python3 "$root/control/teamctl.py" review-visual \
  --task "$TASK_ID" --reviewer "$INDEPENDENT_CHIEF" --approve \
  --verified-png-sha "$EXACT_ORIGINAL_PNG_SHA256" \
  --note "Independent full-resolution contract and source verification completed"
```

The full evidence receipt is `schema=golden_visual_receipt_v1` and contains **exact** `task_id, owner, fence, generator_owner, prompt_id`, the five artifact digest fields (`original_png_sha256`, `scene_contract_sha256`, `canonical_sha256`, `source_save_sha256`, `gpu_receipt_sha256`), `original_pixels_reviewed=true`, a nonempty detailed `observations` string, `mandatory` mapping **every single** source-contract required check to `{"verdict":"verified|violated|unobservable","observation":"specific source-pixel evidence"}`, and `requested_g2`.

Task receipts derive the only possible label mechanically: any mandatory `violated` → **FAIL**; otherwise any mandatory `unobservable` → **UNVERIFIED**; `PASS` only when every mandatory condition is `verified`. `not_applicable` is not a legal response to a mandatory field. The submitted `requested_g2` must exactly equal this derived label; false `PASS` is rejected. The original image, provenance, contract, canonical and source-save bytes are rehashed on **both** submit and review. An exclusive, fenced, mode-0600 immutable copy of receipt bytes plus SHA is retained in the private `evidence/golden/immutable` directory, and the independent decision is recorded separately in `visual_review` and audit events.

The **ordinary source-only `submit` and `review` are unchanged**: empty `changed_paths`/diff still fail, exact commit SHA still required, and only `review-visual` can approve `visual_evidence`. A `DONE` visual receipt with `g2=FAIL` means **the truthful negative assessment is independently accepted**, not that the PNG is accepted for publishing. No published or source game assets are touched.

## Failure modes covered by offline negative-first tests

The isolated PC native-team suite tests: wrong GPU prompt UUID; fake original PNG digest; wrong contract/canonical/job digest; changed or deleted original PNG; stale save before submit and after submit; mismatched case/canonical/save digests inside the typed contract; missing/unobservable/violated mandatory evidence; invalid `not_applicable`; fake PASS; wrong owner/fence; reused task ID or receipt; Golden self-review or Renderer self-approval; reviewer without exact PNG SHA; symlink/out-of-root paths; incomplete/non-Golden tasks; and continued source-only rejection of an empty diff.

**RED:** before implementation, the new suite failed importing the nonexistent `golden_evidence` module. **GREEN:** all 90 native-team tests on the actual PC under an **isolated fresh checkout** passed for independently checked branch SHA `ab195d9b715f347cb9452a46a37c8575a8bb6cf2` (2026-10-31). No GPU job was submitted, no active save altered and no VN production unit restarted. Final PR SHA and CI must be rerun before any deployment.

## Remaining limits and integration requirements

The controller verifies **bytes, state, role separation, source linkage and procedural evidence**, not semantic correctness by code alone. Actual G2 requires an independent observer to **see** original pixels and reference, and any true human-label requirement is separate from agent review. Logical `owner`/`reviewer` names are **not cryptographic user authentication**: the PC account still has broad local file/SSH access. This work also does not enforce the single-writer GPU broker (separate PR #78), repair exact poses, restore identity, or measure complete browser E2E. Keep **G3 NO_GO** until real game/release gates.

**Deployment:** Chief reviews exact PR SHA and independent negatives in a fresh isolated checkout, verifies existing team DB and clean active lanes, backs up control files and DB, installs only control-plane Python modules, rehearses a synthetic `G-new` task in a separate database, and checks existing source-only submit/review remains unchanged. After review, any live migration must be performed separately with an explicit rollback and unchanged old `G-10 BLOCKED` status. On failure, restore backed-up control modules/DB; never reset production saves or rerun R-13.
