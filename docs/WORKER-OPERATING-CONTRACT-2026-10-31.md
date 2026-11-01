# Native worker contract — process reset 2026-11-01

This is the operative contract for all 15 existing ordinary OpenAI Scheduled workers. The owner explicitly ordered faster real experiments after an overnight interval with zero new GPU outputs. It replaces the previous serial source-approval, Chief-decision and receipt-completion requirements **for private diagnostic experiments**. Historical task plans and old prompt checkpoints do not override it.

Versioned saved prompts remain `scripts/native_team/ops/worker-prompts.json`: full prompt = common_prompt + "\n\n" + role_prompt. Official automation reads establish actual rollout and execution. Preserve all 15 IDs, enabled states and hourly schedules; do not revive paused reporter/pilot records or replace development workers with Codex, Work, an external API or local LLM.

## 1. Product result and honest timing

Goal: background + required canonical RGBA sprites + three distinct complex sequential story CGs, correct on their first actual attempt, each **enqueue to publication eligibility <=20 seconds**. Include queue, preparation, GPU, postprocess and every mandatory QA stage. Publication waits count if they actually block eligibility. Record GPU-only, offline development Golden review and narrator/browser-turn durations separately. Do not add unrelated percentiles or report a partial pipeline as complete.

The original 31 October 23:59 Asia/Novosibirsk deadline was missed. The historical first-shot pack remains a historical result. Development trials, repairs and selected best-of-N outputs never become first attempts. Once a route works, freeze a fresh held-out acceptance pack before generation. The separate 30-human-labelled G3 release suite is not a prerequisite for a small engineering comparison.

## 2. Two active work streams; one accountable executor each

**A — actual render:** Renderer owns the executable experiment; GPU Lab owns execution and shared GPU runtime. Identity and Source supply actual private face/actor/outfit inputs; Pose works on defects visible in a current output. Golden independently inspects originals and sends its findings directly to Renderer/Lab and the relevant fixer.

**B — full QA time:** Reliability owns one runnable CPU QA candidate and paired baseline; E2E owns same-attempt timing and comparison. Golden supplies a small authentic positive/negative case set from existing exact originals, with explicit limitations. Installing already tested instrumentation or using an isolated instrumented service must end in a measured request, not another preparation-only report.

Only one active hypothesis in each stream. Support roles attach to one concrete blocking artifact or review; they do not create extra streams to remain busy. No simultaneous edits to the same files. Chief resolves ownership conflicts and allocates a specific blocked step; an available unowned step inside an existing stream needs no new Chief permission.

**Parked by default:** universal production broker/hardening, HMAC/signer rollout, broad adversarial receipt/schema research, new dashboards/schedulers, unrelated refactors, 30-scene release expansion, narration/import/UI scope. Existing work is preserved, not falsely marked complete. Resume only if a reproduced current experiment or eventual publication needs it. A hypothetical attack on an unused production route is not a blocker for a private local experiment.

## 3. Direct authority to run a disposable experiment

The user has already authorized this work. GPU Lab may admit a bounded private no-publish diagnostic itself. It checks:

1. A concrete hypothesis and actual local source: known save/actor, face/reference and current outfit when required. Copy once to an immutable private fixture; verify the copied bytes and decoded image. Record what is known or missing. A production HMAC/signature is not required to test an honestly identified fixture.
2. Exact graph, source/script, model, seed, dimensions and changed factor, with an initial baseline and bounded candidate. A compatibility bundle is allowed when declared; never call multiple coupled changes a single-component result.
3. Exclusive GPU ownership using the installed lock plus temporary quiescence of known competing dev submitters; inspect actual queue/history and unresolved submissions. No foreign/unknown GPU job or duplicate submit. Resolve the actual installed lock once: the legacy dispatcher derives it from root.parent.parent / gpu-exclusive-lab.lock. A new diagnostic directory must use that same explicit lock, not derive a different one.
4. Private output only, fresh output names, no active-save/accepted-asset replacement, before/after integrity of relevant protected inputs, sufficient disk/RAM/VRAM, reversible runtime changes.
5. A minimal local smoke of the code/graph being exercised. No unrelated full CI or production integration gate.

**Not admission requirements:** Chief/Decision/Integration sign-off, merged main, production broker, creation-time HMAC issuer, canonical production receipt schema, broad negative-test completeness, a new infrastructure PR. These are not waived for production; they are out of scope for this diagnostic.

If the legacy dispatcher only supports prompt_text/native_pose, **do not extend that whole production chain before learning whether SDXL works**. A separate private script may use existing installed Comfy nodes/API and the same exclusive GPU lock. It records its own exact prompt and output; it must not pretend to be a supported dispatcher factor. Existing running/review_pending markers and unknown-outcome records remain intact. The new route first reconciles any legacy running job. See LAB-EXCLUSIVE-FAST-PATH.

GPU Lab also has standing authority for a narrow reversible installation/restart needed by these experiments, including tested telemetry, after empty-queue/ownership/backup checks. Reliability prepares CPU changes and rollback; Lab coordinates shared-service activation. No new owner/Chief permission is required. An isolated port/environment is preferred when it gives the measurement without touching the live service.

## 4. Short experimental loop

- At entry consume the latest relevant result, identify the next executable test and act. Actual inspection of the exact previous pixels is required before an adaptive follow-up; inaccessible pixels do not license a blind next variant. Preparation budget: about 10 active minutes before either a runnable test or one concrete missing artifact with a named resolver. Large essential downloads may exceed this, but do not block independent CPU preparation.
- Freeze baseline and candidate. Default budget: baseline plus one candidate; at most three actual GPU submissions for one hypothesis if justified in advance, including known terminal failures without a usable PNG. Execute serially on the GPU. Do not reroll an unchanged failed case.
- Producer inspects the exact known output promptly to identify one observed failure. Golden reviews in parallel and sends original-pixel findings directly to the fixer. Independent review is mandatory for G2/publication, not a serial permission hop before every private diagnostic. On the new diagnostic route at most **two outputs may await independent review**; when that cap is reached, stop generating and resolve the review bottleneck. Never delete the legacy review fence to implement this rule. The three-submission hypothesis budget and two-unreviewed cap are recorded in the private experiment manifest and persist across runs, workers and renamed variants.
- The stream owner may choose the next bounded test from a known result without Chief/Decision approval. After two or three failed repairs of the same defect, change the hypothesis/approach rather than trying a fourth cosmetic patch.
- A known visual FAIL or failed timing comparison is useful evidence. Unknown GPU outcome, actual resource fault, conflicting owner or protected-data integrity failure stops the affected runtime work. Preserve unrelated authorized CPU work.
- Target while runnable work exists: a new useful measured experiment or independent pixel result roughly every 20–30 minutes. This is an operational objective, not a cloud scheduling guarantee. More than 30 minutes with no new evidence triggers Chief to remove the specific dependency or simplify the experiment; do not request another general architecture report.
- Every two hours Chief reports real outputs/reviews, observed defect changes, full timing, GPU idle duration and one next experiment. Issue20 keeps the current two-stream plan. Keep existing hourly Chief schedule; an unchanged hour need not generate another long report.

## 5. Role outputs

| Existing role | Immediate output |
|---|---|
| Chief | One runnable next experiment per stream; remove concrete idle cause; concise evidence-based owner update. No serial test approval. |
| Renderer | Existing-model executable graph + actual fixture + one causal change. Deliver a runnable script/plan, not only source guards. |
| GPU Lab | Actual prompt/output IDs, durations, final/private artifact and restored known services. Sole GPU/shared-runtime operator. |
| Golden | Independent exact-original/ref review; direct actionable defects; review backlog <=2. No demand for production signatures to inspect diagnostic pixels. |
| Reliability/QA | Paired complete-QA baseline/candidate and one observed bottleneck fix; CPU staging and rollback ready for Lab activation. |
| E2E/Latency | Real same-attempt trace/table; reuse merged instrumentation; no new receipt framework before measurement. |
| Identity/Wardrobe | Actual face/current-outfit fixture and conditioning fixes justified by the latest image. |
| Source/Provenance | Read-only snapshot/copy of real source and refs, paths/hashes/meaning for the current test. Production signer work parked. |
| Pose | Exact control input for the current visible pose/contact defect; verify actual graph consumption. No disconnected geometry research. |
| Golden Evidence | Verify current prompt→original→final mapping and first-attempt accounting; package review inputs. General receipt adversarial work parked. |
| Integration Reviewer | One narrow review/smoke of the imminent experiment or rollout; report execution blockers separately from production issues. |
| Decision Authority | Rapid merge/rollback decision on a useful tested change. Never a prerequisite for an authorized diagnostic. |
| GPU Broker Engineer | Reuse the installed single-GPU lock/quiescence for the experiment; repair only observed contention/ownership defects. Broad broker work parked. |
| Broker Reviewer | One runtime-ownership sanity check when the experiment changes that code; otherwise targeted experiment support. No new unrelated hardening branch. |
| Dispatcher | Deliver the exact ready input/result to its executor, reconcile official run state, surface actual idle blockage. Handoff bookkeeping cannot block other authorized work. |

A support role with no concrete useful task should finish briefly. Do not manufacture work or self-disable a continuing role.

## 6. Reading, handoffs and native execution

On first entry/changed policy read AGENTS, DEVELOPMENT and this contract; otherwise reuse already-read unchanged versions. Read the current issue20 sprint block and latest relevant handoff, not the complete historical thread or every old P0. Inspect only affected runtime/source and ownership; Dispatcher owns all-15 inventory.

Use existing controller delivery where available, with one event bound to new real evidence. Batch related facts into one handoff. Consume/reconcile at entry and once before exit, without busy polling. A peer's missing ACK is not permission to fabricate delivery, nor a reason to stop independent preparation.

For additional official wakes retain installed deduplication/reservation/cooldown limits (currently 3/target/hour, 240s target cooldown, 45 global/hour; verify installed behavior). Peek enabled/current run first. An active peer receives the persisted handoff, not a duplicate wake. Reserve once, call official run_now once, record only observed requested/started/completed/unknown outcomes. Unknown requests are never blindly retried. Only the recipient ACKs actual consumption. Operator setup may use requestor operator, without impersonating a Scheduled worker.

If a native handoff is unavailable or rejects its data, preserve one compact redacted GitHub handoff with exact evidence and owner. Do not build another queue or block the whole experiment on receipt formatting. A real platform denial is not evaded through another role/route; the GitHub handoff only records the limitation and supports unaffected work.

Keep all 15 native workers and their schedules. New local application/tool models, dependencies and separate environments are owner-authorized. Pin official source/license/artifact, reuse existing downloads and avoid unreviewed remote install scripts. GPU loads/shared-runtime changes remain Lab-only. No new paid accounts, external development agents, permission changes or assumed model entitlement.

## 7. SSH and runtime boundaries

Use the documented SSH-MCP route; confirm target and affected services. Auth/transport failures allow at most three read-only diagnostic retries per run with actual waits 10/30/60s (no wait >60s), stopping on recovery. User-confirmed authentication repair allows a fresh diagnostic. A generic permission error is not automatically an auth failure. Safety/approval denials are distinct and must be honored; do not repeat the denied action through another agent or route.

After recovery reconcile any prior mutation before retry. Never resubmit an unknown GPU job or run_now. Use one deduplicated incident for the same operation/context; a timestamp is not new evidence. Continue authorized independent work. Current queue/lease checks are required for GPU work, not every unrelated source read.

Protect active saves, published assets and other workers' dirty trees. Known inputs are privately copied/read-only. No private images, story, refs, prompts, credentials or model weights in GitHub. Do not weaken platform controls, public service authentication or the production QA/publish path.

## 8. Review and acceptance

Diagnostic artifacts can receive findings before a signed production contract exists. Golden compares actual copied references and mandatory facts and states missing evidence honestly. Findings are not a fabricated G2 pass. A real G2 PASS requires complete authentic applicable facts, independent original/final-pixel inspection and correct attribution. True N/A is distinct from unknown.

For the legacy LAB route, retain its real terminal-review writer and reconcile its review_pending marker normally. For a separate diagnostic route, a concise private independent review bound to exact originals/refs is sufficient; do not invent a trusted legacy receipt or modify its writer to manufacture acceptance. Production/G3 remains separate.

A candidate faster than 20s but wrong is a failure. A correct candidate slower than 20s demonstrates quality only. A partial QA call does not demonstrate complete eligibility. Once both work together, perform the fresh held-out first-shot pack through the actual complete path.

## 9. A compact result, not another status essay

One handoff: experiment/owner + exact input/config/output IDs; observed pixels and measured durations; conclusion CONFIRMED/REFUTED/INCONCLUSIVE/BLOCKED; next concrete test and owner. Keep the full parameter ledger privately in one existing manifest. Public reports normally <=250 words plus a small result table. Do not repeat all historical hashes, G3 counters and unchanged blockers in every comment.

If a run ends with only another HOLD report and no new artifact, test, measurement or resolved current-test blocker, say so and change the next action. PRs, commits, wakes, synthetic assertions and copied inventories are not the product scoreboard.
