# web-vn ordinary ChatGPT Scheduled team — 31 October 2026

Read `AGENTS.md`, full `docs/DEVELOPMENT-AND-TESTING.md`, then the current [WORKER-OPERATING-CONTRACT-2026-10-31.md](WORKER-OPERATING-CONTRACT-2026-10-31.md). Reviewed role prompts live in `scripts/native_team/ops/worker-prompts.json`. This document records roles and handoffs; official `Automations.peek` establishes the actual enabled/running/name/schedule state. The [autonomous cycle](AUTONOMOUS-FIRST-SHOT-CYCLE-2026-10-31.md) describes rendering execution. No documentation count proves runtime admission, G2, deployment or game readiness.

## Goal and account boundary

The owner's deadline is **23:59 on 31 October 2026, Asia/Novosibirsk (16:59 UTC)**: background, the required canonical transparent sprite set and **three different sequential story CGs**, each first attempt, all mandatory G2 verified, with **generation→ready-to-publish ≤20 seconds per asset including queue, preparation, GPU, postprocess and mandatory QA**. GPU submit→PNG and narrator/full-turn clocks are separate. Offline independent development review time is also reported separately; an actual runtime wait that blocks publication remains part of end-to-end latency. The goal has not been demonstrated; neither five fast synthetic images nor source PRs establish it.

The project has **15 Scheduled role records**, all included in the current operating contract. The first audit found 14 enabled because Golden Evidence Engineer had self-paused after #76 delivery. The owner's follow-up explicitly identified this omitted role; resume that existing worker for ongoing evidence-integrity work at :28, with actual enabled/start state established by official receipts. Independent Golden pixel review remains a distinct duty. Old standalone reporter and QA-only records remain paused. Do not recreate a role merely because an old document lists fewer slots. Native task capacity does not imply GPU parallelism, unlimited model usage or a guaranteed start time.

**Use ordinary ChatGPT Scheduled workers, GitHub and SSH-MCP for development reasoning. Replacement development inference via Codex CLI, ChatGPT Work, paid API and CLIProxyAPI model requests is forbidden.** The owner now authorizes reversible project-local installation and testing of tools, dependencies and local LLM/VLM/image models, and experimental pipeline changes, without another owner/Chief confirmation for each download, isolated install or CPU test. This includes alternative local application/tool models, not replacement development workers. Follow the operating contract: prepare in isolated private directories, pin source/artifacts, then let GPU Lab alone activate GPU/shared-runtime changes under the existing experiment and rollback gates. Existing authorized external application routes may still be tested; new paid accounts, subscriptions or billing changes remain outside this authority. Do not restart the previous local Codex audit or night agents. Codex OAuth usage is a different provider meter and cannot be used to admit or reject native Scheduled runs. The official platform enforces Scheduled limits. Model/effort identity is `MODEL_UNVERIFIED` unless runtime metadata proves it; prompt wording does not create an entitlement. No Dot, new plugin or interactive user session is a prerequisite.

## Role roster

| Duty | Scheduled record ID | Owned output / gate |
|---|---|---|
| Chief | `6ae57ba332a48191923e7f51ccfe7dd5` | evidence-based priorities, exact task ownership, independent acceptance, downstream handoff and hourly owner report |
| Renderer | `6ae57b3727688191ab20279ff8fba0af` | executable source-bound one-factor graph/plan, fixed controls and causal hypothesis; coordinate the sole GPU Lab owner |
| Golden independent pixel review | `6ae57b3d794c8191aff21eac865b780b` | authentic full-resolution original/final pixels with canonical references and complete mandatory G2 verdict; no GPU submit |
| Reliability + QA | `6ae57b40434c8191857969a577627d2f` | controller/runtime failures, measured CPU QA and matte integration, distinct scopes and no acceptance bypass |
| GPU Broker Engineer | `6ae5d49054d48191ba1a0c2f2ba55816` | production single-owner broker, cross-client idempotency, bypass prevention and reversible cutover |
| Golden Evidence Engineer | `6ae5dcacb7908191b72d98510a3db5b6` | continuing CPU evidence-integrity and adversarial receipt validation; #76 remains delivered; no duplicate E2E edits or pixel verdict |
| Exact Pose Researcher | `6ae5dcafbf7c8191aaf823beed911ff2` | exact original reference and guide/source SHA, correct camera; experimental versus production approval |
| Identity and Wardrobe Engineer | `6ae5dcb38de4819193cccf1a9c5954d2` | authentic canonical face/current outfit plus actual graph conditioning; executable installed-reference experiment |
| E2E and Latency Engineer | `6ae5dcb6f8c88191b2cc46a83f64d8da` | generation→ready and full browser stage receipts, trusted acceptance evidence, actual P50/P90; no synthetic E2E success |
| Broker Independent Reviewer | `6ae5dcb9fb3c8191935b5ef13fab8f5b` | exact-head adversarial review of production broker and cutover blockers; no self-deployment |
| Release/Integration Reviewer | `6ae5dcbce2c481919e6cd302c223c279` | independent combined-source/provenance/negative checks, explicit source versus installed versus E2E status |
| Source Contract/Provenance Engineer | `6ae5dd11d4748191adb005926b42c083` | genuine scene/save/actor/outfit/face/workflow/prompt/original PNG binding, not caller-authored receipt shapes |
| P0 Decision Authority | `6ae5e8a59f2c8191a29d40c1c12712f0` | accept/reject the exact reviewed result or return one concrete minimal fix; authorized merge/cutover decisions |
| GPU Lab Worker | `6ae5e8a91cfc8191bb938957f214f8c3` | sole bounded disposable GPU owner, source-pinned candidate, actual original PNG and stage timings |
| Autonomous Handoff Dispatcher — target name | `6ae5e8ac2e58819188b5f87aa17d0f97` | reconcile supported peer status, meaningful evidence-ready handoffs, durable wake receipts and failed-run recovery; no GPU or creative hypothesis substitution |

The dispatcher record's requested rename is **Autonomous Handoff Dispatcher** and its requested schedule is **hourly at :30 Asia/Novosibirsk**, replacing the former :42 slot. This is a proposed configuration until an official post-update `peek` confirms it; this documentation commit does not assert application. The old name “Autonomous 5-Minute Dispatcher” never meant that this particular task ran every five minutes. The rollout owner must record the actual name, timezone, recurrence and resulting enabled state.

All roles execute no more frequently than the native recurrence allows. Different hourly phase offsets and supported extra `run_now` requests can reduce waiting; they do not guarantee five-minute or ten-minute startup for any worker. Chief provides hourly owner reports; there is no need for another reporter.

## Ownership and useful autonomy

Every worker first reconciles its official run, real local claim/fence, branch/worktree and pending evidence. Each specialist owns a disjoint source scope. The legacy R/Q/G/S SQLite controller is not automatically a fifteen-lane scheduler: do not invent a lane, claim a second task over an active same-lane lease, clear another owner's block or edit its working tree. A different Scheduled role may review a separate immutable source snapshot without becoming the producer. Use the installed controller's verified capabilities and the canonical operating contract.

A worker should complete the next bounded useful transition when evidence and authorization are present. Source author hands off exact SHA; reviewer accepts/rejects that SHA; GPU Lab produces exact original; Golden gives terminal pixel evidence; Chief selects the next causal action and Decision Authority independently accepts or rejects its implementation. If a task cannot move, report the concrete missing artifact or unsafe state and advance genuinely independent authorized work. Reopening the user's chat is not a normal dependency.

## Supported handoff and quota rules

1. Establish a real new event: exact source approval/PR SHA, original PNG SHA, contract/reference digest or corrected blocker. Repeated unchanged evidence and speculative readiness are not wake reasons.
2. Check the target with official `Automations.peek`: enabled state, current run and relevant completion. A running specialist is not double-woken.
3. Use the canonical operating contract and the installed, version-verified `scripts/native_team/ops/scheduled_wake_mesh.py` interface for an atomic reservation. Reconcile reservation, official request receipt and actual startup; a reserved event without a delivered request must not permanently suppress valid work. Never infer startup from local SQLite alone.
4. Invoke only official `Automations.run_now` after a successful eligible reservation. Record its actual result. On timeout/unknown outcome, reconcile status before any retry; do not silently issue a duplicate.
5. Distinguish `REQUESTED`, cloud `STARTED`, local `CLAIMED`, artifact submitted and independent review complete. A successful HTTP/API receipt is not completed work.

The native platform governs Scheduled quota. Missing/exhausted `vn-proxy-quota --provider codex` data must not block a native Scheduled handoff, and cannot authorize prohibited Codex/Work/API use. Preserve concurrency, cooldown, evidence deduplication, dependency and rate limits; use exact reviewed helper/runtime behavior rather than stale numeric thresholds copied into prose.

Ready-task idle ≤10 minutes remains a measured objective, not a provider SLA. Report actual ready/requested/started/claimed/evidence/review timestamps and breaches. Idle is legitimate with no meaningful ready work, blocked dependency, unresolved ownership or a platform refusal. Invented backlog and repeated source-only tasks are not progress.

## GPU LAB and production are distinct authorization scopes

Production requires technical broker admission and tested denial of direct `/prompt` bypass. Broker Engineer and its independent reviewer own that project; an empty queue or lab lock is not production exclusivity.

The owner separately authorized a **single disposable LAB candidate** through [lab_exclusive.py](LAB-EXCLUSIVE-FAST-PATH-2026-10-31.md): immutable input, temporary quiescence of known dev submitters, attributed/empty queue checks, one dispatcher execution, restoration only after known completion, STOP on unknown job without resend. The wrapper does not exclude arbitrary unknown clients and is not presented as a universal broker. Production PR #78 is therefore not a blanket prerequisite for all independent laboratory work.

Exact-view `experimental_unapproved` sources may be tested in that lab with pinned provenance. They remain unapproved for production. DWPose or a source photograph cannot prove contact in a later generated image; Golden reviews the actual original. No actor identity, mandatory scene fact, save protection or release requirement is weakened.

## Current critical path and historical evidence

The current fast Z-Image T2I/pose lab does not implement canonical identity, and the dispatcher cannot yet execute the proposed SDXL canonical sprite experiment. Identity, Source/Provenance and Renderer should therefore produce a real source/face/current-outfit-bound **installed SDXL Face-IPAdapter graph** and a narrow executable lab-dispatch route. GPU Lab then tests one candidate through the authorized wrapper. Include reviewed CPU matte, mandatory QA and full generation→ready timing. A standalone validator with no execution path is supporting work, not completion.

The frozen v1 pack remains G1 5/5 and G2 1/5, synthetic background only. Its 5.050–11.040s timings end at PNG and omit later QA. R-13 attempt 2 failed original-pixel G2. R-15 attempt 3 produced a new native-pose original at about 14:10 UTC in 8.019s; the [original receipt](https://github.com/Riannoni/web-vn/issues/20#issuecomment-6544519370) was followed by Golden's terminal **G2 FAIL at 14:26:19 UTC**, with review recorded and candidate moved to reviewed. Palms improved, but legs/full boots and required 40° lean were not proved; canonical identity remained UNOBSERVABLE. Read newer evidence before planning; never replay these IDs or relabel an A/B as a first shot.

Earlier blockers have distinct dispositions:

- **#76 delivered:** [merged and control-plane installed at 13:23 UTC](https://github.com/Riannoni/web-vn/issues/76#issuecomment-6543925935). Golden Evidence Engineer's subsequent self-pause is superseded by its continuing evidence-integrity assignment; historical G-10 remains blocked while its genuine negative review remains valid. Do not rebuild that fix.
- **#77 laboratory circularity removed:** [accepted source and lab decision](https://github.com/Riannoni/web-vn/issues/77#issuecomment-6543834539). Native pose was subsequently executed in R-15; do not ask for a new R-15 simply because an old handoff does.
- **Identity/latency unresolved:** no accepted canonical five-frame pack or ≤20-second generation→ready route is demonstrated. Independent QA/pixel evidence is mandatory; source tests, SHA equality and self-authored JSON are not visual acceptance.
- **Old five-/twelve-role allocations and Codex audit:** historical setup/incident evidence only. They do not authorize local agents or determine current Scheduled limits.

## Evidence and stop conditions

For each candidate preserve source/contract/face/outfit/graph/seed hashes, exact prompt/original/final PNG mapping, first-attempt index, one-factor hypothesis, truthful stage and generation→ready/full-turn clocks, VRAM, before/after save and accepted-asset integrity, independent mandatory G2 observations and separate source/merged/installed/E2E status. Keep private imagery, story text and secrets out of GitHub.

Stop on unknown GPU submission, foreign/overlapping owners, ROCm fault/OOM, source/save corruption, untrusted provenance or repeated causally identical failures. Do not weaken QA to pass 20 seconds, fabricate human labels or publish rejected assets. G3 still requires at least 30 independently human-labeled scenes plus measured E2E/retry/restart/rollback. More workers or more passing source tests do not satisfy that release gate.
