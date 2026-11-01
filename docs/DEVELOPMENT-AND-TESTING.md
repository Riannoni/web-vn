# DEVELOPMENT-AND-TESTING — обязательные правила web-vn

> **V19 laboratory-specific clarification (owner directive, 2026-10-31):** The single-GPU-owner invariant applies equally to disposable experiments. **Production game jobs require technical broker admission**, but a one-shot **disposable GPU lab experiment** may proceed via the tested reversible `lab_exclusive.py` wrapper that temporarily stops known competing development submitters, confirms empty/attributed Comfy queue, enforces a single fenced candidate and restores services after known completion. This is not an assertion of security against arbitrary unknown local clients: an unknown prompt/job stops the run without retry. A 2D `experimental_unapproved` guide with immutable source and one-factor hypothesis may be TESTED, but cannot be called a signed production reference, nor can it prove actual wall contact before the rendered original is visually inspected. Do not use PR #78's unfinished universal broker as a blanket justification to halt all independent LAB tests. More details in [LAB-EXCLUSIVE-FAST-PATH-2026-10-31.md](LAB-EXCLUSIVE-FAST-PATH-2026-10-31.md). No G2/G3 gate is relaxed.

> **Статус: нормативный документ для всех AI-агентов и разработчиков.** Точка входа [../AGENTS.md](../AGENTS.md). Действует при первом запуске, в новом чате, после таймаута и при восстановлении полного отсутствия контекста.
>
> Этот файл отвечает на вопрос **КАК работать и доказывать результат**. [ROADMAP.md](ROADMAP.md), [issue #20](https://github.com/Riannoni/web-vn/issues/20) и связанные issues отвечают **ЧТО ЕЩЁ НЕ ГОТОВО**. Факт наличия регламента не означает готовность рендера.

## 1. Цель: не больше попыток, а верный кадр

До начала работы разграничивай:

| Уровень | Правильное утверждение | Недопустимый вывод |
| --- | --- | --- |
| G1 Technical | job выполнился, граф отработал, файл получен и валиден | значит изображение соответствует сцене |
| G2 Visual/semantic | реальный оригинал PNG независимо сверен с обязательными условиями сцены и reference | значит все иные сцены/seed тоже верны |
| G3 System/release | E2E и размеченный набор доказывают надёжность, корректные отказы, rollback, сохранение канона | значит любая будущая генерация гарантированно верна |

Всякий вывод должен ссылаться на фактическое доказательство соответствующего уровня. `qa.passed=true`, `CI green`, идеальный smoke test, низкое время diffusion, хороший CLIP score или удачный thumbnail не заменяют G2. Успех G2 на одном seed не заменяет G3. Не закрывать render-v1 по одному smoke.

**Главная задача P0:** правильный Sprite/CG внутри работающей браузерной VN с надёжным fail-closed QA, без потери активной игры, при приемлемой для интерактивного использования задержке.

## 2. Первые действия агента, который не помнит ничего

1. При первом входе, потере контекста или изменении версии полностью прочитать [../AGENTS.md](../AGENTS.md), этот файл и действующий worker contract. Уже прочитанные и сохранённые в контексте неизменённые версии повторно не читать.
2. Прочитать текущий блок спринта в [issue #20](https://github.com/Riannoni/web-vn/issues/20), свой последний относящийся handoff и необходимую спецификацию затронутого слоя. Не обходить исторический roadmap, все P0 и все PR перед каждым действием.
3. Проверить реальную **голову main**, актуальную ветку/worktree, pending PR, рабочие незакоммиченные изменения других агентов.
4. Для runtime-зависимого действия сверить затронутые GitHub/source/runtime/model версии и очередь. CPU-only работу не задерживать полным аудитом всех узлов. Не предполагать, что merge автоматически попал на ПК.
5. Перед GPU/shared-runtime действием определить владельца очереди и проверить незавершённые jobs. Потерянный контекст/таймаут ≠ разрешение повторно отправить job.
6. Для проблемного кейса получить private canonical state и typed Scene Contract; точные job ID и Comfy prompt ID, входные reference и оригинал PNG; собрать Stage QA и временные метрики.
7. Сформулировать **одну** проверяемую гипотезу, минимальный эксперимент, критерии опровержения и ограничения ресурса. До этого — только read-only, без исправления «на глаз».

Проверенные раннее hostnames, модель, пути и версии можно использовать как **ориентиры**, но их актуальность надо подтвердить. Предпочитать existing GitHub + SSH-MCP (VPS → home → игровой ПК), не создавать новый gateway ради доступа к артефактам; не раскрывать содержимое ключей и токенов.

## 3. Безопасность и конкурирующие чаты

- **Живое сохранение — неприкосновенно**. Создавать одноразовый game/save с новым UUID и сравнивать source-state hash до/после. Не переписывать published CG и sprites. Непрошедший candidate остаётся private/unpublished.
- Одновременная работа нескольких AI: допустимы параллельный research, отдельные рабочие ветки и read-only review, но **один активный владелец GPU job queue и live deployment**. Не перезапускать ComfyUI и worker, пока чужая задача не выяснена.
- Перед любой мутацией на сервере: целевой host, scope, состояние очереди, ожидаемые побочные эффекты, rollback. Сообразно запросу владельца — отдельное согласование при опасном/необратимом действии.
- Переносы моделей, установка Comfy nodes, очистка временных файлов, обслуживание базы и обновления службы — не «безобидное чтение». Проверять лицензию, compatibility, модельные hashes, VRAM, влияние на остальные процессы.
- Не выводить secrets/ключи в отчёты; не добавлять в GitHub приватные CG, референсы, save snapshots, непубличные реплики, prompts с личным содержимым, model weights. В публичном issue/PR — только обезличенный индекс и измерения.
- При таймауте сначала `status` и анализ уже отправленного prompt/job ID. **Никакого автоматического повторного submit**, force-push, рестарта и восстановления «с того же места» по предположению.
- Прямой commit в main только при соответствующей явной задаче, с проверкой актуальной головы и без перезаписи чужих коммитов; не использовать force-push.

## 4. Расследование до изменения кода

Каждый дефект отнести минимум к одному из классов:

| Класс | Наблюдение | Правильное направление |
| --- | --- | --- |
| Generator defect | PNG реально не содержит нужный объект/позицию/лицо | исходный graph, conditioning, reference, ROI, guidance |
| False accept | кадр неверный, QA говорит PASS | требования к проверке, evidence, обоснованные negative examples |
| False reject | кадр верный, QA говорит FAIL | attribution, observability, доказательства, калибровка |
| Plumbing/state | опубликован не тот job/PNG/сцена | job→prompt→file mapping, version fence, idempotency |
| Structural/unobservable | невозможно проверить обязательное условие | новый способ измерения/другой ракурс; **не подменять PASS** |
| GPU/runtime | restart, ROCm page fault, OOM | модель/граф/размер/память; STOP before further rerolls |

**Проверить через реальную цепочку данных**: canonical actor/story → Scene Contract → composed prompts → workflow+conditioning → Comfy prompt history → original PNG → QA details → publish decision → browser. Найти **первый** этап, на котором истина была потеряна. Не лечить QA-проблему ещё одним негативным prompt, не лечить generator-problem снижением QA.

Формулировка гипотезы:

> «Причина X вероятна из-за наблюдения Y. Если изменить **только фактор Z**, при неизменных входах/seed/модели/workflow я ожидаю measurable A. Если произойдёт B, гипотеза опровергнута. Бюджет — N запусков».

Если seed не гарантирует детерминизм, это указать и применять одинаковые наборы seed в A/B, а не выдавать случайный удачный кадр за улучшение.

## 5. Лимиты, STOP, архитектурная проверка

**Стандарт:** один чёткий baseline и один кандидат на гипотезу, расширять серии только с обоснованием. Записать ограничение времени, количества Comfy jobs, VRAM и возможных restart. Учитывать одну AMD GPU и нагрузку CPU VLM.

- Нет слепых «rerender until pass».
- Нет параллельной смены prompt, checkpoint, resolution, ControlNet, QA threshold и mask в одном A/B; каждое изменение отдельно либо явно многофакторный план.
- Нет ослабления проверок, глобального `accept anyway`, замены `unknown` на `verified`, отключения mandatory evidence, подгонки порогов по одному example.
- **После 2–3 неудачных исправлений ОДНОГО дефекта: STOP**. Не делать четвёртое изменение по инерции; изучить контракты, реальные PNG и архитектуру. Сформировать новую альтернативную гипотезу и независимый тест.
- При ROCm page fault, повторной OOM или рестарте ComfyUI остановить запланированную серию, прежде чем менять checkpoint или размер.
- Если `ambiguous_foreground_people`, `unobservable` и `geometry_mismatch` смешаны, это отдельный дефект observability/retry classification. Не усиливать pose-conditioning, если mismatch не доказан.


## Эффективность агентной работы без потери качества

Для уже доказанно независимых read-only проверок в Code Mode группируй вызовы в один `exec` и `Promise.allSettled`; зависимые и изменяющие действия выполняй по очереди. Показывай модели только нужную выборку и ссылки на полные локальные журналы; избегай повторного чтения неизменённых файлов, гигантских выводов и коротких циклов ожидания. Сохраняй полную проверяемость каждого теста и G1/G2/G3. Cached input тоже может влиять на квоту. Обоснование и локальные измерения: [NIGHT-AGENT-QUOTA-RESEARCH-2026-10-31.md](NIGHT-AGENT-QUOTA-RESEARCH-2026-10-31.md).

## 6. Typed Scene Contract — обязательные независимые проверки

Нельзя утверждать, что CG соответствует сцене, лишь потому что narrator prompt перечислял нужные объекты. Для каждого кадра сверять:

| Признак | Проверять по реальным пикселям | Примеры провалов |
| --- | --- | --- |
| Environment | нужная локация и характерные признаки, continuity background | портрет на сером студийном фоне вместо рыночной площади |
| Named principals | точный состав/привязка героев, separate ambient extras, no clones | фоновые фигуры спутаны с героями или клонируют главного |
| Identity | canonical face только при видимой достаточной ROI; корректный actor ID | красивый, но иной человек; спина ошибочно засчитана за проверенное лицо |
| Wardrobe | актуальная одежда **каждого** actor: цвет, фасон, состояние/закрытость | старый плащ после смены одежды; чужая одежда в групповом CG |
| Props | точный обязательный объект и фактическое взаимодействие | корзина фруктов вместо сложенной карты |
| Landmarks | именно заявленная архитектура, видимая в кадре | отсутствующая каменная арка |
| Pose | exact-view, наклон корпуса, кисти, ноги, ориентация камеры | сидит вместо стояния; слишком общий approved pose |
| Physical contact | конкретная рука касается нужной поверхности/предмета | запястье рядом со стеной, но контакта нет |
| Composition | правильная камера/кадрирование, связная сцена, отсутствие коллажа | дубли, срезанные конечности |
| Sprite alpha | RGBA, валидная прозрачность, силуэт/полный рост, anchor | непрозрачный фон или обрезанный герой |

Для каждого applicable пункта использовать **`verified` / `violated` / `unobservable`**, иначе `not_applicable`. Каждому verdict — наблюдение/ROI/метод и при необходимости ограничение. Mandatory `violated` или `unobservable` = нельзя заявлять полноценный PASS. Если лицо скрыто, точное identity *не наблюдается*; не выдавать CLIP или DWPose за доказательство. DWPose skeleton и геометрическая близость кистей **не доказывают физический контакт**.

Прямая визуальная проверка: получить **точный PNG конкретного job**, private reference и contract с игрового ПК через разрешённый SSH-MCP; для первого обзора возможна preview копия, для итоговых мелких деталей — оригинал/кроп. Просмотреть реально, а не только прочитать подпись нейросети. Спорные сцены — человек или независимый reviewer. Если невозможно увидеть доказательство, записать **NOT REVIEWED** / **UNOBSERVABLE**, не выдумывать оценку.

**Публикация** только после полного предусмотренного Scene Contract QA, действующего scene fingerprint/version fence и проверки, что canonical game state не менялся. После неудачи оставить уже принятый кадр.

## 7. Гипотеза поэтапной управляемой сборки — НЕ готовый обязательный pipeline

После диагностики можно **сравнивать** текущую реализацию с staged workflow:

1. Отдельно утвердить environment plate (без named principals) и зафиксировать пространственный контекст.
2. Держать каноническую face identity отдельно от старого full-body seed/outfit; задавать текущую одежду на каждого actor, не переносить исторический костюм.
3. Применять exact-view pose guide для требуемого действия. В диагностике разрешён честно помеченный experimental guide с известными bytes; его влияние проверяется по выходу. Production approval не предшествует первому исследованию.
4. Использовать grounded actor ROI, target ROI и проверенные spatial masks; нельзя придумывать ROI, чтобы принудительно пройти QA.
5. Для локально исправимого дефекта — bounded masked inpainting с сохранением остальных пикселей, затем **полная повторная QA финального композита**.
6. Визуально сравнить тот же contract/seed с baseline; измерить first-attempt, retries, latency, VRAM, G2.

**Это тестовая архитектурная гипотеза, а не приказ переписать генератор.** Части уже реализованы. Новые checkpoints/ControlNet/IPAdapter требуют нативной совместимости (SDXL ≠ Z-Image), лицензий и тестов на целевом ROCm, а не умозрительного переноса CUDA бенчмарков.

## 8. Два разных уровня приёмки

### A. Первое доказательство работоспособности, ещё НЕ релиз

В одноразовой приватной игре на фиксированном source state:

- **1 Sprite после существенной смены одежды:** canonical face при видимости, правильная новая одежда, нужная поза, полная фигура и рабочая прозрачность.
- **2 последовательных CG:** корректная локация, continuity того же героя и актуальной одежды, named required props/landmarks и relations, отсутствие клонированного героя, соответствие ракурса.
- Сложное физическое действие/hand-on-wall в отдельной точной сцене с проверенным exact-view reference/guide, если это mandatory текущего issue.
- Если acceptance требует **first attempt**, каждый кадр берётся с первой GPU генерации, нельзя выбрать красивую попытку номер 5.
- Для всех — конкретные private PNG, Scene Contract, QA, фактический визуальный осмотр и integrity check исходного save. **Неверен хотя бы один обязательный факт → FAIL**, даже если Comfy 3/3 и CI green.

### B. Release gate render-v1

После пункта A — **не менее 30 независимо human-labeled позитивных и негативных сцен** (#2), разных миров/ракурсов/массовок/видимости лиц/смен одежды/обязательных предметов/отношений и контактов. Явные метрики false accepts, false rejects, unobservable, confusion matrix, P50/P90 **полного хода** и частей (queue/preflight/Comfy/postprocess/QA/repair/publish). E2E retry/fail-closed/publishing/restart/rollback + безопасность сохранений. Не выдумывать новые числовые пороги, отсутствующие в issue: предлагать и утверждать отдельно.

Разница критична: один хороший sample ≠ «render-v1 завершён». Не закрывать #20 и related P0 по самому факту PR, passing tests или одному удачному CG.

## 9. Приватный журнал эксперимента

Все приватные bytes остаются на локальном диске. Следующий полный шаблон — поля одного приватного manifest, не обязательный длинный публичный отчёт каждого worker. В issue обычно достаточно до 250 слов: эксперимент/выход, наблюдения/время, вывод, следующий шаг и владелец. Не копировать повторно неизменные исторические статусы.

```text
CASE / UTC / owner:
Issue / observation / hypothesis / falsifying test / STOP budget:
GitHub main SHA / experiment SHA / home deployed SHA / PC worker SHA:
Disposable game/save ID (private) + baseline canonical checksum:
Scene ID / contract hash / actor IDs redacted / must-have facts:
References (private) + hashes / source snapshot hash:
Model, checkpoint hash, ROCm/GPU, ComfyUI, custom node versions & licenses:
Workflow graph digest / resolution / CFG / seed(s) / approved guides:
Job ID / prompt ID / exact PNG SHA + private artifact path:
What ONE variable changed? What was held equal? Exceptions:
Timings: queue / GPU / postprocess / QA / full turn, CPU/GPU/VRAM:
G1 technical: PASS|FAIL|NOT MEASURED, evidence:
G2 independently inspected original pixels:
  location / cast / identity / wardrobe / props / landmarks /
  pose / contact / camera / alpha:
  verified|violated|unobservable|not_applicable + evidence/ROI for each
Automated QA verdict / independent verdict / false accept or reject:
G3 other seeds / regression / restart / P50 P90 (or NOT MEASURED):
Source save and published old asset intact? hashes before/after:
Decision: CONFIRMED|REFUTED|INCONCLUSIVE|BLOCKED:
Source status vs merged vs deployed vs E2E verified:
Rollback revision / remaining unknowns / ONE next experiment:
```

Статусы **NOT MEASURED**, **NOT REVIEWED**, **NOT DEPLOYED**, **BLOCKED** — честные и допустимые. Прятать пробелы нельзя. Отдельно сохраняй отрицательные результаты, иначе benchmark смещён.

## 10. Code review, CI, релизы и предотвращение регрессий

До исправления ошибки воспроизвести конкретный дефект реальным изображением/замером или минимальным отрицательным тестом. Затем исправить причину, выполнить относящиеся проверки и реальный повторный эксперимент. Перед merge/production rollout — `git diff --check`, необходимые тесты и review затронутых слоёв. Полный посторонний CI/security review не является условием первого private diagnostic; обратимый конфигурационный эксперимент не требует отдельного synthetic test ради формальности.

**Разные статусы, не смешивать:**
- `SOURCE READY` — код написан;
- `TESTED ISOLATED` — тесты прошли на независимой копии;
- `VISUALLY ACCEPTED` — реальный PNG просмотрен и все mandatory facts проверены;
- `MERGED` — изменения в Git;
- `DEPLOYED` — проверена рабочая версия на фактических узлах;
- `E2E VERIFIED` — реальная игра прошла требуемые проверки после rollout.

Перед деплоем: backup/rollback, git SHA, проверка очереди, save protection, plan health. После: отдельный disposable E2E, независимый осмотр output, проверка актуальных version fence и сервисов. Не публиковать секреты/частные кадры. Если пользователь просит только документацию или анализ, **не разворачивать production**.

## 11. Известные опасные ложные выводы web-vn

В roadmap/issues уже описаны наблюдавшиеся отказы:
- `qa.passed` у кадра без карты, каменной арки или нужной одежды;
- студийный портрет принят за рынок;
- ложное срабатывание числа людей из-за props/массовки;
- blind retries на `ambiguous_foreground_people` как будто это доказанный `geometry_mismatch`;
- история старой одежды проникала через full-body seed; усиление denoise меняло одежду, но портило лицо;
- SDXL face inpaint ухудшал canonical similarity;
- Z-Image compact технически успешно генерировал изображения, но **не доказал** canonical identity, exact contact и стабильность production resolution; имел место GPU page fault.

Нельзя считать решение одного дефекта доказательством исправления другого. Если новое исследование обнаруживает лучшие OSS workflows, оценивай их на фиксированных входах, целевом ROCm, с измерением VRAM, time и отдельной оценкой первых попыток.

## 12. Handoff — обязанность при передаче задачи или таймауте

Перед завершением даже частично успешной работы обнови относящийся issue/PR **обезличенным** итогом или подготовь итог пользователю, если запись не разрешена:

```text
HANDOFF — web-vn
Goal / issue / owner / status (IN PROGRESS, BLOCKED, VERIFIED):
main SHA / branch+SHA / PR / home+PC deployed SHA:
Exactly proven facts (CI, tests, artifact hashes, prompt/job IDs):
Exact unproven assumptions and unresolved visual defects:
Active GPU job/queue owner/task ID or IDLE/UNKNOWN:
Source saves and old accepted assets integrity:
Experiments already tried and why they FAILED (do not repeat):
Changed files, rollout status, rollback path:
ONE next minimal hypothesis and STOP condition:
Read AGENTS.md + docs/DEVELOPMENT-AND-TESTING.md first.
```

Получив handoff, нельзя слепо продолжать. Сначала проверить настоящий live state, git heads, GPU tasks и ссылки на evidence. Память чата и комментарий «у меня всё работает» сами по себе не служат проверкой.

## 13. Чек-лист самопроверки перед словом «готово»

- [ ] Знаю действующие AGENTS/worker contract и затронутые правила, текущую задачу и её реальные входы.
- [ ] Знаю настоящий SHA работающего кода и наличие конкурирующих GPU jobs.
- [ ] Source game state и принятые assets не менялись; integrity доказана.
- [ ] Назвал дефект, единственную гипотезу и фальсифицирующий тест.
- [ ] Взял именно оригинальный PNG нужного job, а не thumbnail или latest glob.
- [ ] Сравнил все mandatory условия сцены и face/outfit references.
- [ ] Разделил verified, violated, unobservable и not applicable; не ослаблял QA.
- [ ] Сохранил timings, seed, graph, ошибки, false accept/reject, приватный manifest.
- [ ] Не назвал MERGED состояние DEPLOYED и не назвал DONE состояние VISUALLY ACCEPTED.
- [ ] Оставил самодостаточный handoff, позволяющий повторить работу без чата.

**Короткая памятка:** всегда начинать с `AGENTS.md`; полные правила разработки, диагностики и тестирования — в `docs/DEVELOPMENT-AND-TESTING.md`.
