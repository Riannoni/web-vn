# Native Team continuity — 31 October 2026

> **HISTORICAL RECORD — not an operating procedure after the owner's 2026-11-01 reset.** Old role counts, approval chains, model restrictions, task priorities and restart requirements below are archived evidence only. Use current [AGENTS](../AGENTS.md), [worker contract](WORKER-OPERATING-CONTRACT-2026-10-31.md) and [LAB scope](LAB-EXCLUSIVE-FAST-PATH-2026-10-31.md). Do not resume old tasks from this document.


## Current goal and operating authority

Read `AGENTS.md`, full `docs/DEVELOPMENT-AND-TESTING.md`, then [WORKER-OPERATING-CONTRACT-2026-10-31.md](WORKER-OPERATING-CONTRACT-2026-10-31.md). The reviewed prompt source is `scripts/native_team/ops/worker-prompts.json`; [the roster](PRO-NATIVE-AUTONOMOUS-TEAM-2026-10-31.md) describes the 15 project role records, 14 enabled, with Golden Evidence Engineer paused after #76 delivery. Official `peek` and actual controller/claim state establish current liveness. A document or a Scheduled request is not a running worker.

Today's objective is **background + canonical RGBA sprite + three different story CGs**, first attempt, independent mandatory G2, by **23:59 31 October Asia/Novosibirsk (16:59 UTC)**. Generation→ready-to-publish must be **≤20 seconds per asset including queue, preparation, GPU, postprocess and mandatory QA**. Measure GPU submit→PNG, narrator/full-turn and offline independent development-review duration separately. Any actual runtime publication-blocking wait still belongs to end-to-end latency. The target is not yet demonstrated. Source-only throughput and a five-second unanchored image do not complete it.

Actionable ready-to-claim idle ≤600 seconds, aspirational ≤300 seconds, is a **measured SLO, not a platform SLA**. Hourly schedules and official extra `run_now` have no guaranteed startup. Idle can be legitimate for no meaningful ready work, unresolved dependency/ownership, missing original-pixel evidence or a platform refusal. Do not fabricate backlog or repeatedly create helpers to avoid reporting idle.

**Replacement development-agent inference via Codex CLI, ChatGPT Work, paid API and CLIProxyAPI model calls is forbidden.** The existing application's already-authorized Comfy/QA/narrator runtime can be tested boundedly after checking the established owner-authorized route/config; do not add a new model/account/billing route. Do not restart prior local agents. Codex OAuth is not Scheduled Tasks quota and must not block or authorize a Scheduled wake. Native Scheduled admission is determined by its official platform; deterministic local watchdogs and SQLite are not model workers.

## Control-plane architecture and ownership

- Existing control root: `~/.local/share/web-vn-native-team/run-20261031-full`. Read actual installed file hashes and current DB schema before assuming source changes are deployed.
- The one-minute `systemd --user` watchdog uses SQLite WAL and deterministic Python; it does not create model hypotheses or invoke LLMs/GPU itself. The separate authorized lab timer may execute an already approved immutable candidate through the V19 wrapper; it is not cloud orchestration.
- `control/task_catalog.py` and its reviewed catalog carry scoped specs, path allowlists, explicit dependencies and idempotent task IDs. Transactional enqueue prevents half-populated tasks. New specs must follow a real issue/evidence gap, not a desire to fill uptime.
- The source controller's R/Q/G/S lanes are distinct from Scheduled role records. Before claiming, reconcile current owner/fence, lane lease, pending review and worktree. Do not take a second same-lane lease, overwrite another active tree or mark an unapproved dependency done. Use the exact verified controller semantics; a merged fix is not an installed one.
- Owner-fenced `lease_recovery.py` can quarantine a definitively ended failed task after its official run and external effects are reconciled. Unknown jobs, reboot/expired leases and an idle cloud status are not permission to replay. Historical blocked IDs remain historical.
- Idle metrics distinguish actionable ready time, review wait and planning deficit. A blocked/conflicting scope is not a runnable task. An empty backlog is not automatically an SLO breach.
- Chief and independent reviewers inspect exact SHA and negative evidence in disjoint read-only worktrees. Approval writes remain serialized/fenced. Golden independently reviews original pixels through the deployed evidence-only path; source author cannot self-approve G2.

## Supported wake and crash reconciliation

Use the canonical operating contract and version-verified `scheduled_wake_mesh.py` with official `Automations.peek`/`run_now`. A meaningful new source/approval/PNG/contract SHA must make the target actionable; check enabled/current-run state first. Keep atomic reservation, scope, dependency, concurrency, cooldown and rate limits. Reconcile an interrupted reservation with its actual official request/result before retrying or treating it as delivered. No raw task database edits or unsupported platform endpoints.

Record separate ready, reserved, requested, cloud started, local claimed, artifact and independent-review timestamps. A local reservation is not delivery; a successful `run_now` is not startup; a cloud run is not a local lease. Already-running peers are not double-woken. Missing/full Codex OAuth samples are irrelevant to Scheduled provider quota. Platform refusals and unknown request outcomes remain explicit.

The requested dispatcher name is **Autonomous Handoff Dispatcher**, with a planned hourly **:30 Asia/Novosibirsk** schedule replacing :42. Until the rollout owner confirms a post-update official `peek`, treat name/time as proposed, not applied. Neither the former “5-Minute Dispatcher” name nor phase-staggered hourly jobs guarantees a five-minute run.

## Rendering handoff and safety boundary

Production Comfy traffic requires technical broker admission and bypass prevention. The separately owner-authorized [V19 disposable lab wrapper](LAB-EXCLUSIVE-FAST-PATH-2026-10-31.md) permits one immutable lab experiment while known development submitters are quiesced, actual GPU ownership is known, and services are restored only after terminal completion/empty queue. Unknown/foreign job means STOP without resend. Do not use the unfinished universal broker to halt every independent LAB task, and do not claim the LAB wrapper provides production security.

An unreviewed original goes to Golden before another candidate. The next architectural work is an executable canonical SDXL face-reference sprite route with authentic current-outfit/source inputs; the current fast Z-Image graph has no canonical identity path. Keep quality/latency evidence separate and reject missing/violated/unobservable mandatory facts. New held-out pack cases are frozen before their first attempt; old retries cannot improve the frozen v1 score.

## Historical rollout evidence — not current task commands

The earlier V8 controller rollout installed only native control-plane files, not the game renderer. It preserved these observations:

- R-07 was quarantined after its cloud session had ended, its handoff said BLOCKED and its worktree was clean; it was not replayed.
- Chief independently approved Q-06, S-07, S-08 and S-09 during that continuation; R-08/Q-07 reached review-pending and G-06 took a real lease. These are historical transitions, not tasks to recreate.
- One S-08 enqueue→claim took 347 seconds; it does not establish a 24/7 600-second upper bound.
- The original branch's native-team suite passed 70 tests on 31 October, with fixture ResourceWarnings. That result does not verify later source or installed runtime.
- #76 was subsequently [merged and control-plane deployed at 13:23 UTC](https://github.com/Riannoni/web-vn/issues/76#issuecomment-6543925935), with additive visual evidence tables, 102/102 source tests and watchdog smoke. Preserve historical G-10 blocked status and its real negative visual review; the implementation is not outstanding work.
- R-15 produced a genuine new native-pose original about 14:10 UTC; the [original receipt](https://github.com/Riannoni/web-vn/issues/20#issuecomment-6544519370) was followed by Golden's **14:26:19 UTC terminal G2 FAIL**, review recorded and candidate moved to reviewed: palm contact improved, but full boots/legs and required lean were not proved; canonical identity UNOBSERVABLE. It was research attempt 3, not v1 first-shot success. Read newer terminal evidence before acting.

The old 75% Codex OAuth gate and Codex/Work execution options belong to superseded planning. They do not apply to ordinary Scheduled task admission. No such model-agent executor is authorized now.

## Incident diagnosis and rollback

1. Read official peer status, current `teamctl.py status`, wake request/reservation receipts, catalog/idle state, SQLite `quick_check`, installed source hashes and watchdog/lab service state. Do not use a quota file from another provider as a Scheduled readiness gate.
2. For a lease whose cloud run ended, reconcile exact owner/fence, original evidence and any external Comfy prompt before owner-fenced quarantine. Unknown state stays under investigation; never blindly reclaim or resubmit.
3. For accumulated review-pending work, have the independent reviewer evaluate the exact submitted SHA/provenance/negative tests or original PNG. The producer's source claim is not a visual receipt. Existing approval CAS and one-owner safety remain enforced.
4. Distinguish blocked dependency, no meaningful backlog, platform refusal, reservation not delivered and actually running work. Assign the smallest concrete recovery within current authorization; do not make the user's interactive return a normal dependency.
5. Before control-plane rollback, snapshot current files and DB and confirm active ownership. Stop only the relevant controller timer, restore the verified compatible control revision, preserve newer task/evidence records, then smoke before resuming. Never revert accepted product assets, game saves or unknown GPU work to debug dispatch.

G3 remains separate: at least 30 independently human-labeled scenes, calibrated positive/negative QA, actual E2E and restart/retry/rollback. Merged source, active timers, requested wakes and fast PNGs do not prove completion.
