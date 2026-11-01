# web-vn — 15 native workers, current roles 2026-11-01

Owner-directed experiment-first reset. Read [AGENTS](../AGENTS.md), [DEVELOPMENT](DEVELOPMENT-AND-TESTING.md) and the current [worker contract](WORKER-OPERATING-CONTRACT-2026-10-31.md) on first entry/policy change; reuse retained unchanged reads. The prompt source is scripts/native_team/ops/worker-prompts.json. Saved configurations, official starts and actual outcomes must be verified separately.

Keep the existing 15 ordinary OpenAI Scheduled roles and hourly phases in Asia/Novosibirsk. No Codex/Work/replacement development LLM. Historical reporter/pilots remain paused. Completing an issue does not disable a continuing role.

| Role | Existing automation ID | Minute | Current output |
|---|---|---:|---|
| broker | `6ae5d49054d48191ba1a0c2f2ba55816` | :00 | Исполнение существующего GPU-lock/quiescence; только конкретный runtime-блокер теста |
| decision | `6ae5e8a59f2c8191a29d40c1c12712f0` | :02 | Быстрое решение по полезному протестированному merge/rollback; без допуска к diagnostic |
| broker_reviewer | `6ae5dcb9fb3c8191935b5ef13fab8f5b` | :05 | Проверка затронутого исполнения/владения, без отдельной программы hardening |
| chief | `6ae57ba332a48191923e7f51ccfe7dd5` | :10 | Два направления, один следующий тест на каждое, устранение простоя |
| integration | `6ae5dcbce2c481919e6cd302c223c279` | :15 | Узкий smoke/review ближайшего эксперимента или установки |
| renderer | `6ae57b3727688191ab20279ff8fba0af` | :20 | Исполнимый граф/runner и один проверяемый фактор |
| gpu_lab | `6ae5e8a91cfc8191bb938957f214f8c3` | :22 | Единственный GPU-исполнитель; реальные prompt/output, время и runtime |
| golden | `6ae57b3d794c8191aff21eac865b780b` | :25 | Независимый просмотр originals/refs, прямой дефект исполнителю |
| golden_evidence | `6ae5dcacb7908191b72d98510a3db5b6` | :28 | Точная связь вход→prompt→original→final и пакет для Golden |
| dispatcher | `6ae5e8ac2e58819188b5f87aa17d0f97` | :30 | Передача готового входа ответственному, фактическое состояние запусков |
| pose | `6ae5dcafbf7c8191aaf823beed911ff2` | :35 | Conditioning для видимого дефекта конкретного текущего изображения |
| identity | `6ae5dcb38de4819193cccf1a9c5954d2` | :40 | Настоящие face/current outfit и проверяемое conditioning |
| provenance | `6ae5dd11d4748191adb005926b42c083` | :45 | Приватная копия реального source/ref с происхождением и хешами |
| reliability | `6ae57b40434c8191857969a577627d2f` | :50 | Измеренный baseline/candidate полного CPU QA и исправление задержки |
| e2e | `6ae5dcb6f8c88191b2cc46a83f64d8da` | :55 | Фактический same-attempt trace и сравнение; без нового evidence framework |

## Work allocation

Only two active outcome streams: **canonical rendering** (Renderer + GPU Lab) and **mandatory QA latency** (Reliability + E2E). Identity, Source and Pose supply the next real render input/fix. Golden reviews actual outputs; Golden Evidence packages the exact originals and checks attribution. Review/control roles remove a concrete current blocker or finish briefly with no new work.

GPU Lab has direct owner authority for isolated private diagnostics after real input/queue/lock/resource/protected-state checks. Chief, Decision and Integration are not serial admission gates. Production signing/broker/combined-source CI work stays separate. Broad broker hardening, receipt/schema research, dashboards and unrelated scope are parked unless demonstrably needed for a current test.

A known result goes directly to its fixer. Producer inspects exact pixels before an adaptive follow-up; Golden may review concurrently. The new diagnostic route permits at most two unreviewed outputs and three GPU submissions per hypothesis, persisted across runs. The legacy runner keeps its existing review_pending behavior. All routes acquire the same actual GPU lock and preserve unknown outcomes; no output is auto-published.

## Execution and reporting

Use the existing native defer/reserve/run_now/outcome mechanism when available, preserving deduplication, cooldowns and unknown-wake handling. Missing ACK or unsupported handoff data does not block independently authorized work. A real safety denial is honored, never delegated for replay. Schedules and provider admission are not a nonstop SLA.

Target useful observed evidence every 20–30 minutes while executable work exists. Chief investigates >30 minutes of unexplained idle, simplifying or removing the actual dependency. Count new images, independent findings, fixed visible defects and full timing. Do not count reviews/PRs/comments/wakes as delivered assets.

One short handoff to the actual consumer; one private parameter/result manifest. Do not repeat an all-role audit or historical failure inventory in every specialist run. Current source, installation, G1, G2 and E2E remain distinct. The historical failed pack and missed October31 deadline are preserved.

Project-local tools/models may be installed and tested without additional per-download approval. GPU/shared-runtime activation is Lab-only; paid accounts, permissions and replacing the OpenAI development team remain outside scope.
