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
6. Для проблемного кейса получить private canonical state и typed Scene Contract; точные job ID и Comfy prompt ID, входные reference и оригинал PNG; собрать относящийся Stage QA и уже имеющиеся timings; новый latency benchmark не является prerequisite текущего pack.
7. Сформулировать **одну** проверяемую гипотезу, минимальный эксперимент, критерии опровержения и ограничения ресурса. До этого — только read-only, без исправления «на глаз».

Проверенные раннее hostnames, модель, пути и версии можно использовать как **ориентиры**, но их актуальность надо подтвердить. Предпочитать existing GitHub + SSH-MCP (VPS → home → игровой ПК). После первого подтверждённого transport/unavailable сбоя или явно истёкшей авторизации SSH-коннектора использовать уже авторизованный HA-MCP по [REMOTE-ACCESS](REMOTE-ACCESS.md), не ждать всей серии diagnostics. Сохранять target/user/операцию и её guards; при UNKNOWN сначала read-only reconciliation, без повтора мутации. Safety/approval/access-control denial и host-key mismatch не разрешают fallback. После успешного primary probe возвращаться на SSH для следующей новой операции. Не создавать gateway и не раскрывать ключи/токены.

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

Нужное условие в final submitted prompt доказывает его подачу, но не правильное число героев, identity или позу на выходе. Проверять действительные staged bytes и эффективный путь каждого text/ref/mask input к используемому encoder/model/sampler/output, включая веса и диапазон действия conditioning; правильный node без рабочей связи или влияния недостаточен. Если условие дошло, но не исполнено, допустима одна grounded правка prompt под конкретную модель и наблюдаемый дефект. Frozen brief сохраняет требования/каноны/storyboard, не неизменность неэффективного текста. Отдельно различать ошибку проводки, неэффективную формулировку и предел выбранного метода.

Формулировка гипотезы:

> «Причина X вероятна из-за наблюдения Y. Если изменить **только фактор Z**, сохранив baseline и остальные совместимые входы/seed/параметры, я ожидаю measurable A. Если произойдёт B, гипотеза опровергнута. Бюджет — N запусков; необходимые сопутствующие отличия перечислены».

Если seed не гарантирует детерминизм, это указать и сравнивать закреплённый seed или уже используемый набор в A/B. Не выдавать случайный удачный кадр за улучшение и не добавлять seed sweep как обычный gate текущего pack.

## 5. Лимиты, STOP, архитектурная проверка

**Стандарт:** один чёткий baseline и один кандидат на гипотезу, расширять серии только с обоснованием. Записать ограничение времени, количества Comfy jobs, VRAM и возможных restart. Учитывать одну AMD GPU и нагрузку CPU VLM.

В рамках прежнего run/attempt budget продолжать короткий цикл **осмотр → один дефект → одна правка → проверка effective graph → Lab render → осмотр** в том же run. Не ждать следующего расписания для доступной причинной правки. При scoped block сохранить его и следующий input/owner, затем выбрать независимо разрешённый полезный asset, если он доступен в оставшемся бюджете; это не даёт retry denied/unknown операции. GPU/shared-runtime остаётся только у Lab, independent acceptance — у Golden.

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

## 7. Выбор управляемого пути по наблюдаемому дефекту

Выбирать минимально достаточный путь под asset и проверять его реальное действие:

1. Для трёх обычных сцен повторно использовать **один и тот же background asset/bytes** и нужные RGBA sprites через CPU-композицию; не генерировать фон заново на каждый beat.
2. Для sprites сохранить каноническую face identity отдельно от старого full-body outfit; явно задать текущую одежду. Face IP-Adapter использует image-reference conditioning через свой действующий model path. Это не img2img: последний инициализирует sampler латентами исходного изображения через VAEEncode или эквивалентный encoder path с выбранным denoise. Подача лица в IP-Adapter не доказывает такую инициализацию; конкретное имя node не является gate. Denoise не задаёт процент изменённых пикселей. Fresh latent либо img2img выбирать по задаче/дефекту, без требования fresh latent для всех sprites.
3. CG остаётся цельной согласованной сценой. Использовать подходящие background/composition/pose/view refs согласно заданной камере; прежний кадр не универсален для другого ракурса или действия. Не вводить обязательную previous-frame цепочку или обязательный BG img2img для всех CG.
4. Только для наблюдаемого pose/depth/contact/composition дефекта пробовать совместимый ControlNet или иной подходящий spatial guide. Experimental guide допустим с неизменяемыми bytes и явной маркировкой; его влияние надо проверить по pixels. Использовать grounded actor/target ROI и проверенные masks, не выдумывать ROI ради QA. Ни skeleton, ни depth сами не доказывают identity/contact.
5. Для локально исправимого дефекта допустим bounded masked inpaint; если нужна точная сохранность остальных пикселей, обеспечить её итоговым compositing с оригиналом, не предполагать её от одного VAE round-trip. Затем проверить весь final по применимому Scene Contract. Смена модели допустима как отдельная обоснованная гипотеза по обнаруженному ограничению, не обязательная подготовка pack.
6. Сравнивать новые exact pixels с сохранённым baseline при том же contract/seed и сравнимых параметрах; отметить выбранный фактор и необходимые исключения. Сохранить уже полученные timings/attempts, без дополнительного latency benchmark, seed sweep или G3 gate для обычной итерации.

Это варианты исправления подтверждённого дефекта, не приказ переписать генератор или установить всё сразу. Переиспользовать рабочие части. Новые checkpoints/ControlNet/IPAdapter требуют нативной совместимости (SDXL ≠ Z-Image), лицензий и относящейся проверки на целевом ROCm; загрузку и shared-runtime изменения выполняет Lab под прежним общим GPU-lock.

## 8. Два разных уровня приёмки

### A. Текущее диагностическое доказательство Mira/Max, ещё НЕ релиз

Текущий owner goal задают AGENTS и worker contract. Уточнение владельца от 2 ноября 2026 00:15 Asia/Novosibirsk: стремиться получить проверенный pack к утру 2 ноября, без обещания результата или ослабления приёмки. Только нейтральные сцены с одетыми Мирой и Максом. В приватном изолированном кейсе на закреплённом source state проверить:

- **1 повторно используемый фон** и **6 канонических RGBA sprites**: по три эмоции/позы Миры и Макса, включая базовые варианты.
- **3 обычные повествовательные сцены**, собранные на CPU из того же самого background asset/bytes и предусмотренных sprite-вариантов.
- **3 настоящих CG:** два с Мирой одной и одно взаимодействие Миры/Макса, с реальным соответствием frozen storyboard/refs.
- Для каждого — точные private original/final PNG, действительные inputs/graph, относящийся QA, фактический pixel review и защита исходного save. Фатальные cast/anatomy/identity/wardrobe/composition дефекты проверяются до alpha/detail polish. Непроверенное остаётся NOT REVIEWED/UNOBSERVABLE; неверный mandatory факт означает FAIL.
- Все попытки сохраняются. **Утренний ориентир, 20s, first-shot rate, старый wall-stress case, новый latency benchmark, дополнительный seed sweep, G3 и показ в ModelLab не являются gates текущего pack.** Поздняя попытка не переименовывается в первую. Бюджеты гипотез/альтернатив и неизвестные исходы сохраняются по worker contract.

Подтверждённые совместимые исправления доставляются по готовности, не ожидая полного pack. Один scoped production smoke проверяет реально затронутый путь; сам по себе он не доказывает качество всех изображений, browser playback или G3.

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
Actual final prompt binding / effective init, reference, conditioning and mask paths:
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

Перед деплоем: backup/rollback, git SHA, проверка очереди, save protection, plan health. После: один disposable smoke реально затронутого production scope, независимый осмотр относящегося output, проверка применимых version fences и сервисов. Для worker/vision-only изменений существующий нормально аутентифицированный backend game-job path с Lab-owned GPU даёт PRODUCTION_RENDER_SMOKE; direct diagnostic graph его не заменяет. Browser login/playback нужен только при затронутом UI и иначе остаётся отдельно UNVERIFIED; отсутствие browser session не блокирует доступный разрешённый backend smoke. Новые credentials/session не изобретать и auth не обходить. Не публиковать секреты/частные кадры. Если пользователь просит только документацию или анализ, **не разворачивать production**.

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
