# Native ChatGPT engineering team — operational design and rollout (2026-10-31)

> **HISTORICAL RECORD — not an operating procedure after the owner's 2026-11-01 reset.** Old role counts, approval chains, model restrictions, task priorities and restart requirements below are archived evidence only. Use current [AGENTS](../AGENTS.md), [worker contract](WORKER-OPERATING-CONTRACT-2026-10-31.md) and [LAB scope](LAB-EXCLUSIVE-FAST-PATH-2026-10-31.md). Do not resume old tasks from this document.


> **DRAFT / source-only commissioning.** Read [../../AGENTS.md](../../AGENTS.md), [../DEVELOPMENT-AND-TESTING.md](../DEVELOPMENT-AND-TESTING.md), [../RENDER-HANDOFF-2026-10-31.md](../RENDER-HANDOFF-2026-10-31.md) before touching any source, model, image or game. No merge to main, GPU or production deployment is implied.

## Desired outcome, not a proxy metric

The owner expects **a reliable, playable Ash Gate browser VN**, with the actual characters and visuals matching the canonical story. The present P0 [master issue #20](https://github.com/Riannoni/web-vn/issues/20) requires a first-attempt changed-outfit Sprite and **three sequential constrained CG** with exactly correct identity, outfit, world, required prop/landmark, pose and contact. The first-acceptance sequence must be independently inspected at the original PNG pixels. Release-level `render-v1` further needs **30+ real independently human-labeled scenes**, false accept/reject/unobservable, P50/P90 total turn and stage timings, restart/retry/rollback/save preservation, and real version-fenced integration into the browser game. Source unit tests and synthetic 30-scene manifests are **not** G2/G3. Story-package imports/Kagesekai catalog are later phases, not this milestone.

**As of installation:** G2 UNVERIFIED; G3 NO-GO. No unattended agent can promote a visual gate by reading its own test results.

## Five independent responsibilities

| Team member | Cloud execution | Local checkout / focus | Current task queue |
| --- | --- | --- | --- |
| **Renderer** | Scheduled ChatGPT, hourly | `lane-renderer`: actor-prop geometry, staged masks, source grounding; reference draft PR #47 | R-01, R-02 |
| **Semantic QA** | Scheduled ChatGPT, hourly | `lane-qa`: frame/scene/actor/object/contact provenance, fail closed; base PR #49 | Q-01, Q-02 |
| **Golden benchmark** | Scheduled ChatGPT, hourly | `lane-golden`: real-vs-synthetic golden-label contract and QA metrics; base previous local B commit | G-01, G-02 |
| **E2E reliability** | Scheduled ChatGPT, hourly | `lane-reliability`: source fingerprint, idempotent publish, restart/rollback contracts; base main | S-01, S-02 |
| **Chief orchestrator/reviewer** | Separate Scheduled ChatGPT, hourly | Read all four worktrees/evidence/issue/PR; independently replay tests, accept or reject `review_pending`, replenish meaningful backlog, publish hourly status | Lead, review and incident response |

Cloud task IDs are managed through ChatGPT Scheduled UI and should be recorded with their scheduling state in the private PC run manifest (not hard-coded into production code). Technical scheduler tasks are not the same as a Codex CLI daemon.

**Persistent PC checkout root:** `~/.local/share/web-vn-native-team/run-20261031-full/`. It contains `source/` (independent Git objects), four `lane-*/` worktrees with distinct local `native-team/20261031-*` branches, `control/`, `state/team.sqlite3`, private `evidence/<lane>/`, and `logs/`. The old Codex night-runner and the previous two-worker experiment remain untouched.

## Deterministic control plane

The installed local control plane derives from the separately tested SQLite coordinator in [draft PR #51](https://github.com/Riannoni/web-vn/pull/51). The deployed evolution in this branch is `scripts/native_team/coordinator.py` plus `scripts/native_team/teamctl.py`.

- **SQLite WAL atomic claims** with 4 global active leases, one task per lane at a time, path-scope conflicts rejected, unique per-attempt fence, heartbeat and ~45-minute lease.
- **No blind retry:** an expired lease moves to BLOCKED; a new agent cannot assume the previous model/tool action did not change the checkout. Strict path scope and clean checkout preflight prevent overwriting another worker.
- **Separated evidence:** worker writes a private JSON with changed paths, red→green tests, source status, `g2=UNVERIFIED` and `g3=NO_GO`, commits locally, then calls `submit`. Result becomes `review_pending`, **not** `done`.
- **Independent review:** cloud orchestrator verifies Git diff/commit, branch lineage, source-only scope, re-runs actual negative/positive tests and validates evidence digest before `review --approve`. Rejected code is blocked, not silently accepted.
- **Bounded backlog:** eight prioritized starter jobs, separate scopes. Once work is done, same scheduled worker may claim another queued job within its turn. Hourly chief checks latest issue/PRs, dependencies and prior failures, then enqueues the next falsifiable nonduplicate task. A local process cannot invent a new high-quality research hypothesis without a model.
- **Local watchdog:** a systemd user timer runs the deterministic check around **every minute**, recording stale leases, blocked/idle lanes and a sanitized quota snapshot. It is not an LLM worker or a way to launch a new ChatGPT turn ahead of schedule.
- **Quota:** `~/.local/bin/vn-proxy-quota --provider codex --json` is read-only, and `state/quota-timeline.jsonl` records 5-hour/7-day percentages. This instrument **does not measure ChatGPT plan usage**. The first prototype showed parallel ChatGPT sessions without a visible rise in the rounded Codex gauge, not unlimited capacity.

## State diagram / lifecycle

```text
issue #20, actual SHA, current heldout evidence
                |
        chief creates task spec
                |
  [QUEUED] --atomic lane claim--> [LEASED]
      ^                            |
      |                  controlled source tests, commit,
      |                     fenced evidence submit
      |                            |
      +-- new meaningful task   [REVIEW_PENDING]
                                   |
                        independent test + diff review
                               /         \
                            DONE         BLOCKED
                              |             |
                    draft PR only      reconcile/stop,
                                      no blind resubmit

Production/GPU/image release:
  isolated GPU lease (not yet implemented)
  -> original-PNG review (G2)
  -> >=30 real human labels + E2E/restart/rollback (G3)
  -> explicitly reviewed deployment and verification
```

`DONE` here refers to one **source** task, not the master issue or a visual gate. A task may be blocked due to missing human visual evidence: do not game the gate.

## Operating commands on Xavok-PC

```bash
root="$HOME/.local/share/web-vn-native-team/run-20261031-full"
python3 "$root/control/teamctl.py" status
cat "$root/state/watchdog-latest.json"
tail -n 10 "$root/state/quota-timeline.jsonl"
systemctl --user status vn-native-team-watchdog.timer
journalctl --user -u vn-native-team-watchdog.service -n 30 --no-pager
```

All workers must use the `claim`, `heartbeat`, `submit` path in `teamctl.py`; never write task table state directly. The chief uses `review` and `enqueue` only after independent evidence. Only the owner can authorize a final merge, service restart or irreversible action.

**Stop procedure** (when explicitly requested): pause the five ChatGPT Scheduled Tasks using the Automations UI/tool; run `python3 "$root/control/teamctl.py" stop --reason 'owner request'` on PC and `systemctl --user disable --now vn-native-team-watchdog.timer`; retain all worktrees, SQLite and evidence for review. Never delete or reset another agent's dirty worktree. Old `vn-night` remains stopped independently.

## Limitations and on-call policy

The **local watchdog is continuous**, but native ChatGPT Scheduled Tasks are **hourly** and finite individual executions, not perpetual streams. Multiple open ChatGPT tasks do not establish separate quotas. A task can pause for service/platform limits, app authorization, quota or network; report PAUSED/BLOCKED and why. A stalled task with unsaved changes cannot be automatically recovered safely by declaring it complete. The chief can do reversible known safe repairs, but resource-intensive GPU/no-publish render validation needs exclusive GPU permission and actual pixel review; current implementation does **not** yet contain a GPU governor.

The full-time engineering loop is therefore **persistent, self-monitoring and hourly model-driven**, not guaranteed uninterrupted model inference until the product is good. Progress is tracked by independently reviewable artifacts, accepted G2/G3 evidence and working browser E2E, not tokens, number of commits or an unbounded count of tasks.

## First full four-lane cloud cycle — verified 2026-10-31 12:35 Asia/Novosibirsk

**Execution:** Four separate native ChatGPT Scheduled Tasks completed concurrent runs, working on **four independent local PC Git worktrees** via SSH-MCP. Local user-systemd minute watchdog remained active, old Codex night agent inactive. Four lanes developed two source-only tasks each (R-01/02, Q-01/02, G-01/02, S-01/02). Each created a local commit and private evidence (no GitHub pushes).

**Independent chief review:** a fifth scheduled native ChatGPT task was run immediately and independently reviewed all **8/8** source-only outputs, re-ran an aggregate **165 targeted Python tests** on the PC, checked commit SHA/path scope and accepted each as source task DONE in SQLite; original red regressions verified for at least R-01/Q-01/G-01. The reviewer then enqueued **R-03, Q-03, G-03, S-03** based on actual heldout blockers. Thus the first complete workflow **claim → actual source changes → local testing → review_pending → independent review → DONE → next meaningful task** is evidence-backed. Final check 12:35 showed **4 pending, 0 leased, 0 blocked**. The next model work starts on the next hourly ChatGPT schedule, while watchdog remains one-minute. Beware the wider historical reliability test suite still has **1 unrelated failing test** (`test_bounded_retry_moves_on`), not considered fixed by the targeted 31/31.

| Lane | Latest local SHA | Independent source tests | Next milestone |
| --- | --- | --- | --- |
| Renderer | `46977a1` | 50/50 targeted | R-03 bind proposed hand plan to immutable source PNG |
| QA | `8f38189` | 49/49 targeted | Q-03 exact PNG SHA shadow evidence |
| Golden | `064b999` | 35/35 targeted | G-03 P50/P90 complete turn and stages |
| Reliability | `f8d9ab7` | 31/31 targeted | S-03 exclusive GPU preflight, source-only |

**Runtime:** GitHub `main` `5e4e0bf`; production game worker/vision/Comfy and existing proxy remain active, LAN game HTTP 200 at last chief check, Comfy queue idle. No accepted live image replaced, no GPU commands issued, no deployment or merge. The previously documented held-out wooden box had independently measured width/shoulder ratio **1.0668 > 1.0**, so **G2 remains UNVERIFIED and G3 NO-GO**. Source-only approval is never release acceptance.

**Quota:** During four parallel native ChatGPT sessions the whole-percent Codex OAuth gauge after its natural 5-hour reset remained **0% / 36%** (5h used / 7d used). This gauge cannot track actual ChatGPT plan usage, and no unlimited capacity claim is justified.

**Five cloud schedules** currently active (all recurring hourly):
- Renderer `6ae57b3727688191ab20279ff8fba0af`
- QA `6ae57b3a03a48191889e3b0073c8e359`
- Golden `6ae57b3d794c8191aff21eac865b780b`
- Reliability `6ae57b40434c8191857969a577627d2f`
- Chief `6ae57ba332a48191923e7f51ccfe7dd5`

These use five of the available scheduled-task slots. Cloud execution depends on plan quota, connected SSH/GitHub app availability and platform delivery. If any task fails, the chief must state the exact failure; local minute watchdog cannot summon another model turn. All source code remains local PC worktrees and this coordination draft PR; production release still requires separately verified real first-shot G2 and multi-scene G3.


## 2026-10-31 independent architecture audit and hardening

The owner explicitly requested an independent effectiveness/scale review of the full running system. The **current production goal remains render-v1 G2/G3**, not increasing raw task volume. The four coding lanes and fifth chief are retained deliberately: 8 source tasks/first cloud batch, 8/8 approved via independent review, 165 targeted source tests, one additional historical wider-suite failure, **no independently accepted new original PNG**. A sixth source-only worker would increase backlog and ChatGPT-plan consumption rather than address the real critical path. The next optional specialization is a **visual acceptance/GPU-integrator**, activated only after a verified exclusive GPU governor, actual original-PNG transport and owner/human acceptance workflow; it should not replace the current source review gate.

**Observed weaknesses found and corrected in running control plane** ([this draft PR #60](https://github.com/Riannoni/web-vn/pull/60)):

1. **Moving-head review risk:** old `submit` and `review` were not cryptographically bound to the **specific** worker commit. Now a submitted source result must have a clean Git worktree, exact permitted changed paths, a descendant SHA from the task's original baseline, no symlinks/submodules, a passing `git diff --check`, an immutable evidence digest and `baseline_sha`/`commit_sha` in the SQLite task result. The reviewer must explicitly supply `--verified-commit FULL_SHA` and test that exact Git snapshot in an independent detached review checkout, not the lane's later moving HEAD. Review decision and audit event are one SQLite transaction.
2. **Unsafe ambiguity on timeout/failure:** expired leases and failed source attempts are now **BLOCKED**, not silently scheduled again; future work requires reconciling Git, evidence, and external job state before a fresh task. Uncommitted sources and escaping path scopes are refused.
3. **Unbounded task factory / false-positive health noise:** at most **two pending tasks per lane**; the minute watchdog logs a new audit event only when its warning state changes. Its regularly updated `watchdog-latest.json` and `team-latest.json` still provide minute-by-minute liveness evidence.
4. **Chief/worker overlap:** chief was shifted from approximately **:31 to :42 local Asia/Novosibirsk** after the four approximately **:24** worker starts. This gives longer-running code tests time to finish before independent verification, while preserving one owner-facing consolidated hourly report. Chief prompt requires the exact `--verified-commit` argument and a separate review worktree.
5. **Self-tests and deployment:** reviewed source v3 **24/24** tests passed in a fresh GitHub clone on the real PC; installed running `control/` modules have additionally passed **35/35** tests including old and new suites. Existing SQLite DB, four worktrees and previously `done`/pending states were preserved, and the watchdog stayed active. Backups `control/teamctl.before-v2.py`, `control/coordinator.before-v2.py` plus earlier copies are retained; no game service was restarted.

**Scope/safety caveats:** Workers are trusted cloud agents using the owner's existing SSH-MCP route as the PC user. File-scope checks in our **task broker** are fail-closed, but SSH-MCP still has broader privileges if a worker bypasses the broker. This is **not** an OS-enforced per-agent security boundary. True least-privilege execution requires dedicated restricted SSH credentials/accounts or a sandboxed command gateway, explicit user-approved rollout, and independent validation; do not silently modify home/PC authentication while the owner is playing. Similarly, automatic GitHub publication of each reviewed source branch, GPU single-owner locking, real PNG visual inspection, release metrics and final browser E2E still need their own verified gates.

**Performance decisions:** keep **4 developer lanes + 1 chief**, single persistent local watchdog and source tasks bounded to **2 per lane per chat run**. Avoid more workers or changing roles until the first true, held-out G2 visual assessment is available. Prefer cross-functional integration and actual original image evidence to writing more synthetic QA tests. Quantify future improvement by first-shot Sprite/CG acceptance, false accept/reject/unobservable, number of human-labeled independent cases, review turnaround, P50/P90 full-turn latency and stability—not tasks completed/hour. ChatGPT plan usage is still not exposed by the Codex OAuth quota gauge; check platform allowance separately and pause on limits.

**Rollback of control-plane only:** pause the five Scheduled Tasks before replacing code; copy back the verified `control/*.before-audit-v2-20261031.py` backups under the same module names; run isolated control tests, check SQLite and watchdog state, then re-enable the schedules. Never roll back or reset dirty worker source trees or user game state. A separate owner-approved gate is required before deployment or GPU writes.

**Final role adjustment after audit:** the Golden worker's active Scheduled Task prompt was updated to prioritize **real PNG evidence, independent human labels, abstention/error calibration and release metrics**, not further synthetic dataset inflation. It first completes already queued G-03 latency tests, then asks the chief for evidence-backed G2 tasks. This uses the existing fourth lane, not a sixth scheduled cloud agent. Chief report remains hourly at approximately **13:42 Asia/Novosibirsk** after the four approximately **13:24** worker starts.


## 2026-10-31: minimize cloud worker idle time — guarded on-demand wake

**Proof, not a promise:** at approximately 12:58–13:00 Asia/Novosibirsk, the owner explicitly authorized and a chat operator invoked official `Automations.run_now` for the *existing* four worker schedules. The returned status initially meant only "requested", but **all four distinct native ChatGPT runs later entered `in_progress`** and corresponding local PC SQLite jobs R-03, Q-03, G-03, S-03 were really claimed via SSH-MCP. Worker R-03 entered `review_pending` around 13:01; other workers proceeded independently. This demonstrated a supported **on-demand** wake path in addition to hourly scheduled wakeups. It did not create extra ChatGPT accounts, make Codex API calls or bypass plan limits.

**Implemented guarded dispatch architecture:**

- PC-only `scripts/native_team/ops/wake_guard.py`, installed as `control/wake_guard.py`: read-only eligibility scan (team active, lane clean, no active lease, no `review_pending` or `blocked`, completed dependency closure, global file-scope disjointness, at least one ready pending job). Its `--reserve` option atomically stores a *single* candidate `wake_reservation` in SQLite with **3600-second cooldown**, so concurrent supervisors cannot endlessly request the same task. A reservation **never** runs a model.
- PC-only `control/wake-scan.py`, invoked by existing one-minute user watchdog, records `state/wake-ready.json` with honest lane status/reason. This is strictly advisory; no web requests or ChatGPT invocation and no credential access. Existing heartbeat/quota/watchdog data remain intact; diagnostics failures do not bring down the main watchdog.
- The **Chief Scheduled Task** prompt now contains exact worker automation IDs and instructs it to check completed independent review and meaningful backlog, read current cloud `Automations.peek` status, ensure it is not already running and next regular schedule is more than 10 minutes away, then **reserve** via local SQLite and call the first-party `Automations.run_now` once if that action is genuinely present in its tool set. It must distinguish `run_now requested` from `worker started`, avoid repeats, respect plan quotas and report inability when this task execution has no Automations action. This **cloud-Chief-to-worker triggering is configured but not yet empirically confirmed**; do not claim it works until the next chief run actually shows tool execution and subsequent SQLite claims.
- The ordinary recurring four hourly worker schedules and a single hourly chief report remain **enabled** and unchanged. Workers already use bounded multi-task loop (up to 2 independent source tasks in one cloud invocation); local watchdog does not fabricate work. Never create meaningless queued tasks just for high utilization.

Operational read-only canary from PC:

```bash
root="$HOME/.local/share/web-vn-native-team/run-20261031-full"
cat "$root/state/wake-ready.json"
python3 "$root/control/wake_guard.py" --root "$root" --lane R
```

Only an authorized human or cloud chief with supported Automations tools may reserve/issue a wake. Reservation, if used, is `--reserve --requestor chief`; successful reservation is **not** proof that the model ran. A failed run request remains under cooldown to prevent storms; the next chief reviews the platform error and retries no sooner than permitted.

**Why not add more workers?** Four source tasks normally completed in ~1–3 minutes each in the first experiment, leaving substantial idle time because ChatGPT Scheduled Tasks are not continuously running processes. On-demand wakes improve utilization *when the platform permits and independently useful tasks are queued*, but can increase ChatGPT plan usage. The one-GPU, G2 original pixel QA and reviewer throughput remain the real bottlenecks. Scaling to 5–8 coding workers before independently accepted real CGs would increase review and context overhead, not solve first-shot render quality. Even successful on-demand runs cannot guarantee continuous 24/7 model inference: quotas, tool permissions, scheduled-task limits, backlog dependencies, reviews and safety blocks still apply.

**Validation:** isolated GitHub checkout tests of the full native-team suite **32/32 PASS**, including 8 new wake cooldown/readiness/blocker cases. Installed wake scanner returned correctly differentiated `worker_busy` and `review_pending` during real concurrent ChatGPT activity. No production game/Comfy restart, GPU job, auto merge, public private-artifact upload or old Codex reactivation.


### 2026-10-31 on-demand wake concurrency hardening

A final race regression launches **four simultaneous** `wake_guard.check(...reserve=True)` calls against a throwaway SQLite database; exactly **one** succeeds and the other three observe `wake_cooldown`. The full checked-in isolated native-team suite now passes **33/33** in a fresh PC clone. The installed guard and minute scanner were run on the actual PC during four live cloud workers; statuses correctly differentiated `worker_busy` from `review_pending`. No local model triggering was implemented.

The user-approved one-off cloud Chief `run_now` was requested around 13:06 Asia/Novosibirsk specifically to review the four new source submissions before the next regular 13:24 worker cycle. Its extra result is **not** proof of automated Chief-to-worker waking until verified from `Automations` run history and local SQLite `wake_reservation` records. The Chief skip-wake window was conservatively increased to **25 minutes** before the next scheduled worker start to avoid redundant nearby scheduled and on-demand jobs. Normal chief hourly status delivery remains enabled.


### First measured idle-time improvement

From source-only SQLite `task.started_at/completed_at` data (not estimated from chat messages), gaps between completion of R/Q/G/S task 02 and start of the extra task 03 were **31.9 / 32.5 / 33.1 / 29.4 minutes** respectively. With only the original regular next ~13:24 Novosibirsk wake, those tasks would have waited roughly **another 22–26 minutes** to start. This one controlled, user-requested on-demand test therefore established a measurable reduction in idle time. It does **not** show zero idle, automatic chief-driven wake capability, or an unlimited number of runs. Next useful experiment: measure chief review-to-run request latency and rolling availability/quota in a normal hourly cycle, with no extra report spam.


### Controlled off-cycle Chief review and next-schedule preservation (13:06–13:10 Novosibirsk)

The user-requested single **immediate** Chief task was accepted and began at **06:06:48Z** (not a new recurring schedule). On the real PC, its independent reviewer verified and approved the four extra source-only jobs `R-03/Q-03/G-03/S-03` at about **06:08:54Z**, with per-task SHA and actual scoped test evidence in SQLite. By **06:10Z** it had generated four meaningful next tasks `R-04/Q-04/G-04/S-04` as `pending`. A direct local `wake_guard.py` read-only check showed all four lanes `eligible=true`, no active leases and no missing dependencies. Since the next **regular hourly worker starts were approximately 06:24Z**, the Chief's new 25-minute skip-wake safety margin was intentionally designed to avoid an immediate duplicate model run. This protects ChatGPT allowance while reducing the chance of all four regular runs finding an empty backlog.

**Important measurement boundary:** the prior R/Q/G/S `run_now` requests and resulting model starts are confirmed; *automatic Chief-initiated* `Automations.run_now` remains unverified until an eligible time window opens, the action is available to the scheduled chief, a reservation is recorded and a subsequent worker start is observed. No local code tries to call the cloud model itself.


## 31 October 2026 — review-to-dispatch latency audit (target: 5–10 min when practical)

The owner asked explicitly to minimize real **idle-to-next-source-task-start** latency, not simply keep the SQLite watchdog alive. A read-only audit at **06:21:36Z** found four clean idle worktrees, R-04/Q-04/G-04/S-04 ready and **no blocked jobs**; the local `wake-ready.json` was 24 s fresh. However the cloud workers had been inactive since 06:01–06:05Z and the chief's previous off-cycle run completed 06:12:57Z. The legacy one-per-hour extra wake cooldown and chief `:42` schedule did **not** satisfy a 5–10 minute latency objective.

Implemented and verified in the separate **draft operations branch / PR #60**:

1. **Move chief regular hourly schedule to ~:32 Novosibirsk**, shortly after four worker :24 starts (previously :42). This accelerates independent SHA-fenced review by approximately 10 min in a typical 4–6 minute worker run. If the workers are still running, the chief must review only immutable submitted tasks and leave leased work alone.
2. **Event-driven review advisory:** `wake_guard.py --chief-review` reports readiness when evidence is `review_pending` and, for up to 2 min, permits sibling active workers to finish. It can atomically reserve a single Chief wake request, with cooldown and budget; it never invokes ChatGPT itself. Four simultaneous reservation attempts yield **one** grant. The existing minute systemd watchdog records `chief_review` alongside the four lane reasons in `state/wake-ready.json`.
3. **Cloud worker V4 prompt:** after fenced submit, and only if the official `Automations.peek/run_now` actions are available to the cloud run, check that Chief is enabled and idle, next scheduled Chief >10 min away, reserve via local SQLite, and issue **one** official Chief `run_now`. Never invoke ChatGPT from PC/SSH/browser/API, bypass a denial or run on an unclear lease. A **worker-triggered Chief run is configured but not yet demonstrated**; report this limitation until a concrete run ID and Git event prove it.
4. **Wake guard rate cap:** local worker dispatch cooldown reduced from 3600 s to **600 s**, subject to **max 2 EXTRA worker run requests per lane / 1 h** and **8 extra worker requests globally / 1 h**; Chief limited to **2 EXTRA run requests / 1 h**, also 600 s cooldown. A reservation is not a successful cloud run, and the platform's usage/rate limits always take priority. No automatic infinite model loop. Checked-in isolated tests **39/39 PASS**, including hostile retries and race cases; installed on the real PC after a clean Git checkout with backups of prior guard and scanner.
5. **Cloud Chief V5:** first review by exact checked SHA, replenish at most two *meaningful*, independent, authorized queued source tasks per lane, then optionally invoke the first-party `run_now` for enabled idle workers when the next planned regular start is more than 25 min away. On-demand Chief runs write a short technical handoff, while the scheduled full user report remains hourly.

**Additional real execution caveat:** at around **06:29Z**, Q-04/G-04 were ready and their official `Automations.run_now` requests were both **accepted**, but their new `in_progress` records had **not yet appeared by 06:30Z**. Do not label either as running from an accepted request alone, and do not issue repeated unbounded calls. R-04 and S-04 did complete actual cloud-backed tasks and advanced to `review_pending`. Chief was observed `in_progress` at 06:30Z using the revised schedule. Thus 5–10 min is **an operational target, not a guaranteed SLO** for ordinary ChatGPT Scheduled Tasks: the scheduler cannot recur more often than hourly, on-demand starts have variable delay and run budgets are not documented as unbounded. Any missing tool, quota, pending review, unsafe GPU or absent useful backlog must fail closed.

To measure properly, record for each task: predecessor `completed_at` → independent reviewer decision → next task `claimed_at`, plus `Automations` cloud run state. Report the **p50/p90 and maximum actionable idle gap**, count of queued-ready lanes, actual starts versus wake requests, and exclusions due to legitimately blocked/dependency-limited work. A running watchdog or a synthetic queue entry is not productive model execution. Prefer reducing per-turn context and preparing two nonduplicative independent tasks where real issue evidence permits, over adding more idle workers.

The image quality gates remain **G2 UNVERIFIED / G3 NO-GO**; none of this deploys renderer/QA code or touches saved games, published sprites or GPU jobs.


### Measured utilization and review-to-worker cycle (31 Oct, 13:33 Novosibirsk)

Additional **read-only**, one-minute metrics are now installed on PC: `control/idle_metrics.py` with `control/wake-scan.py` logs `state/wake-ready.json.latency` for all four lanes. It distinguishes elapsed time since a previous source completion from the **actionable ready-queue** wait, records sampled p50/p90 historical gap between distinct source tasks, and reports `sla_violations` only where pending, not leased/review-blocked. Its alerts do not generate new cloud model requests. A clean clone of the updated full native-team suite passed **44/44** Python tests on the PC; the installed minute watchdog was exercised and remained active.

At **06:33:49Z**, the actual local `wake-ready.json` reported R/S had newly enqueued work waiting only **56 s / 55 s** respectively, while Q/G were leased and working. There were **zero *current* ready-queue >10m alerts** at that instant. Historical per-lane gap p90 values were **R 1822 s, Q 1887 s, G 1912 s, S 1641 s** (~27–32 min), proving the owner-requested *sustained* 5–10-minute idle SLO has NOT yet been reached. This source-only dashboard measures only PC task claims, not model reasoning latency, browser gameplay or usage credits.

Official on-demand Q/G cloud runs: request was accepted around **06:29Z**; their new ChatGPT `in_progress` records appeared approximately **06:30:39–06:30:47Z** and G-04/Q-04 were both actually leased in the SQLite ledger. Chief's newly advanced regular schedule also started around **06:30Z**. These are concrete improvements but not proof that *autonomous* worker→Chief wake worked; we still require an observed `wake_reservation('C')`, the matching official cloud run and subsequent source review. No unsafe automation has been deployed on the PC.

**Safety-budget update:** the official `Automations.run_now` trigger remains a cloud action only. Local `wake_guard.py` can advise/reserve atomically, with **600-second cooldown**, at most **two extra wake requests per lane per rolling hour**, **eight across worker lanes**, and **two extra Chief review wake requests/hour**. Platform limits override these local maxima. Workers' V4 prompts now attempt to wake an idle Chief after fenced submit (only where their cloud tool permits, not with SSH/browser/HTTP), while Chief V5 reviews actual commits, creates meaningful work and may dispatch otherwise-idle workers. No promise of continuous model execution and no synthetic busywork to satisfy an arbitrary SLA.

**Next validation:** collect several real source-task cycles and report p50/p90/max actionable idle and independent review latency. If Cloud Task scheduled requests are delayed or `run_now` is unavailable, report capacity-limited; do not fake a 5-minute SLA. Maintain G2 UNVERIFIED and G3 NO-GO until original PNG/human QA/E2E.


## 31 October 2026, 15:25–15:35 Novosibirsk — power-outage recovery incident

The owner reported a power outage and requested restoration plus a strict 5-minute target / 10-minute maximum actionable worker idle. **Observed, not inferred:**
- Home server `xavoks-server` reboot time **2026-10-31 08:15:45Z**; PC `xavok-pc` reboot time **15:21:32 Asia/Novosibirsk**. SSH-MCP → home → PC now works. Home Docker/SSH were active; PC game Worker/ComfyUI/Vision/CLIProxyAPI and the *enabled* minute `vn-native-team-watchdog.timer` were active. Local Comfy HTTP queue reported **0 running, 0 pending**; source worktrees clean. Night-runner timers remained deliberately inactive.
- SQLite `PRAGMA quick_check` returned **ok** and all four worktrees had no uncommitted code. No originally active stale lease remained at first inspection. **R-05 and S-05 were `done`, Q-05/G-05 `pending`**. Minute-old telemetry was fresh.
- During the earlier outage all five cloud Scheduled ChatGPT tasks correctly reported SSH/VPN inability and stopped without fabricating claims, tests or GPU work. Local minute watchdog restored on PC startup but **cannot make external ChatGPT start**.
- At **08:25Z** Q-05 and G-05 ready-queue telemetry measured **6491 s** (~108 min), including inaccessible downtime. This decisively **breaches** the desired 5–10-minute elapsed idle objective; outage/offline intervals should be reported separately rather than hidden. Their independent cloud tasks were safely reserved and their official `Automations.run_now` requests accepted, followed by **real ChatGPT starts at 08:26:40–43Z** and SQLite leases; Q-05/G-05 completed source-only and entered `review_pending`. Chief later started at 08:34Z for actual independent review.
- R-05/S-05 had no remaining queued task despite independent approval. Based on their *actual* private handoffs, two bounded source-only tasks were **explicitly enqueued**, R-06: trusted immutable staged source-job/PNG attestation (must never forge missing legacy provenance); S-06: negative queue TOCTOU test (no real Comfy submit). The approved worker automation IDs were triggered once through official `run_now`, and real cloud runs began at 08:30:47–48Z, delivering R-06/S-06 to `review_pending` by ~08:34Z. No production game, GPU, private saves or published accepted image was changed.
- **Power-safe claim protocol hardening:** in this PR, `teamctl.watchdog` now compares a locally persisted Linux boot ID with `/proc/sys/kernel/random/boot_id`. On changed boot it atomically fences all interrupted `leased` tasks to `blocked` *immediately*, clears owners/fences, emits audit evidence and requires independent reconciliation rather than waiting 2700 s for TTL. `claim/heartbeat/submit` refuse an unmatched boot before watchdog reconciliation, and an existing `blocked` lane cannot automatically claim further tasks. On initial migration it only establishes baseline, preserving live jobs. Added negative tests for actual reboot simulation, stale submit and unchanged boot. **48/48 tests PASS** on an isolated PC GitHub clone. Until this modified `teamctl.py` is copied into the live `control/`, this is source-only readiness, not a deployed recovery feature.
- **Availability != coding SLA:** scheduled ChatGPT tasks recur hourly; on-demand `run_now` has nondeterministic start timing and task limits. Therefore strict max 5–10 minutes between model executions cannot be guaranteed solely with 4 native Scheduled Tasks. The current 5-minute figure is an *engineering target*, not a verified SLA. A genuinely firm upper bound requires a **persistent supported model backend** (e.g. quota-limited official Codex CLI/Responses API or explicitly provisioned local coding model) and a durable queue; this consumes different quota or hardware capacity, and must not silently restart the older Codex night-runner, incur paid API charges or compete with game GPU. Ask for explicit model/budget preference before launching that separate inference plane.


### Final restoration verification (2026-10-31 ~15:40 Novosibirsk)

Home `xavoks-server` returned through SSH-MCP; Home Assistant, MariaDB, Mosquitto, Zigbee2MQTT, Jellyfin, Sonarr, Radarr, Prowlarr, Portainer, Caddy and the other expected Docker containers all reported running. The old one-shot `sonoff-dongle-flasher` exited zero months earlier, not part of the blackout. `systemctl --failed` reported 0 failed home units. Comfy's localhost `/queue` had 0 active/pending jobs, Worker/Comfy/Vision reported active/running with 0 restarts. Home root disk ~43% used, SSD media volume ~16% used. CLIProxyAPI and the local user `vn-native-team-watchdog.timer` were active; the two old night-agent timers remain intentionally inactive. The isolated team SQLite passed `PRAGMA quick_check=ok`.

The reboot-identity lease fencing feature was **installed on the real PC** as `control/teamctl.py` with retained backup `control/teamctl.before-boot-recovery-20261031.py`; its first local watchdog pass successfully persisted the current boot ID in SQLite, and the entire associated **48/48** offline unit test suite had passed before installation. It must still be proven against the next *real* interrupted lease; synthetic boot transition tests are the current negative evidence.

After the operator's direct recovery interventions, the four cloud workers actually ran source tasks `Q-05/G-05/R-06/S-06` through SSH-MCP, all producing `review_pending` without production edits or GPU submissions. The scheduled Chief launched at **08:34:30Z**, independently approved them, and by **08:40:24Z** SQLite showed **22 DONE** total and new `Q-06/R-07/S-07` pending. No source claim should be treated as G2/G3. Golden's next step requires real independent human visual evidence, so an empty queue there should not be filled with fake synthetic work.

The monitoring defect where `no_backlog` was invisible to idle alerts has been repaired in the ops PR code: `planning_deficit_seconds`, alerts at 5/10 minutes, and tests. The checked-in entire test suite passed **49/49** on a clean PC clone. **The latest scanner replacement was blocked by the connected tool safety layer and was NOT installed**, so the new planning-deficit alert remains source-only; the older minute scanner and reboot-safe live coordinator continue operating. No attempt to bypass the safety block should be made.

Strict 5/10-minute **model** idle guarantee is not achievable with only hourly ChatGPT Scheduled Tasks and optional `run_now`; read-only local polling every minute is not model inference. Official OpenAI documentation permits hourly recurring tasks and supports event-triggered tasks for some Work-connected GitHub events, but this session's event-source discovery action returned `NOT_FOUND`; no event-triggered dispatcher has been installed. A persistent, supported inference runner would be necessary for an enforced hard upper bound, with explicit quota/resource budget and preserved single-GPU / source-only constraints.


### Autonomous Chief-to-worker wake empirically confirmed after blackout

The restored Chief native ChatGPT run (UTC **08:34:30–08:42:52**) independently reviewed all four recovery outputs and generated next source tasks. In PC SQLite, Chief recorded `wake_reservation` for **R-07** and **S-07** (not an unbounded set of requests). Subsequent first-party ChatGPT task histories independently showed Renderer **in_progress at 08:41:38Z** and Reliability **in_progress at 08:41:35Z**; PC SQLite confirmed both task leases. This is the first **fully evidenced cloud Chief → official cloud worker wake → real PC claim** in this project, not merely a request. The cloud lead's review/replenish/dispatch cycle took roughly **7 minutes** to restart these lanes, longer than the owner's **5-minute target**; review parallelization instructions were subsequently added for future runs. Q-06 was also requested by the conversation operator through official `run_now`, and its ChatGPT task showed **in_progress at 08:42:37Z** (SQLite claim still pending at 08:43:12Z). A Chief run completed does not imply next task already claimed; measure both.

**Planning metrics correction:** the old `no_backlog` state did not raise a 5/10-minute planning alert, even when model workers had no job for hours. `ops/idle_metrics.py` and `ops/wake-scan.py` in this draft PR now separately report `planning_deficit_seconds` and thresholds while preserving a distinct category for ready-but-not-claimed wait. The full combined test suite **49/49 PASS** on a clean local PC clone. Installation of the *last scanner update* was blocked by tool safety checks, so this new planning-deficit feature is **not yet active in the PC minute watchdog**. The running local boot-fencing supervisor and earlier idle scanner are active.

**Absolute-SLO boundary:** recurring native ChatGPT Scheduled Tasks are no more frequent than hourly, and official on-demand `run_now` has no promised delivery latency. A strict continuous 5-minute coding idle cap is therefore not enforceable with this five-Scheduled-Task-only architecture, even though event-driven cloud-to-cloud requests were proven. Achieving a hard bound requires a persistent supported coding-inference service with separately approved quota/cost (Codex via existing OAuth quota or a local model) or eligible Work event-triggered tasks linked to supported GitHub events. Do not silently restart the old quota-consuming Codex night-runner or claim event-trigger configuration has been deployed.
