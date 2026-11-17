Model-authored review, gpt-5.6-sol medium. Not a human or panel PASS.

# Answer

Статический аудит выявил несколько технических дефектов, влияющих именно на проверяемость оснований, человеческие решения и холодное продолжение. Скрипты проекта и тесты я не запускал; `tests/` и `evals/evaluator_only/` не читал.

## Приоритетные дефекты

### P0 — `check` даёт ложный green при повреждённой доказательной цепочке

[`command_check`](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:604) проверяет hash оригинала, существование путей и часть ссылок, но не проверяет:

- формат и непустоту большинства ID, хотя `ID_RE` объявлен в [строке 35](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:35), но нигде не используется;
- уникальность `conclusion_id`;
- обязательные поля выводов, решений и ревизий;
- существование locator внутри соответствующего extract;
- hash или воспроизводимость extract-файла;
- согласованность `state.md`, `project.json` и последних операций/решений;
- наличие и состояние обязательных артефактов.

Активному факту достаточно любой непустой строки locator ([строки 638–643](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:638)). Extract после импорта можно изменить, сохранив green: hash проверяется только для `stored_path` ([строки 613–627](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:613)). Это расходится с обещанием точного provenance в [requirements.md:9](/home/alexchist/Ouroboros/projects/mgimo-project/docs/requirements.md:9) и «обязательных полей» в [tools/README.md:15](/home/alexchist/Ouroboros/projects/mgimo-project/tools/README.md:15).

Дефект уже виден в поставленном примере: документация сообщает `integrity ok` ([verification.md:14](/home/alexchist/Ouroboros/projects/mgimo-project/docs/verification.md:14)), хотя его [state.md:5](/home/alexchist/Ouroboros/projects/mgimo-project/examples/web-smoke/state.md:5) утверждает, что подтверждённых операций нет, а `operations.csv` содержит успешную операцию.

Fix scope: расширить существующий checker — применить `ID_RE`, проверять все схемы и обязательные поля, дубликаты выводов, locator по конкретному extract, hash extract либо детерминированную регенерацию, а также выдавать отдельный `checkpoint_stale` при расхождении state с реестрами. Не смешивать это с семантической оценкой стратегии.

### P0 — честность человеческого решения проверяется недостаточно

Для `accepted` сейчас обязательны только непустой `decider` и `decision_kind=human` ([строки 652–669](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:652)). Green возможен без `recorded_at`, `chosen_option`, оснований и условия пересмотра. Подтверждённое обязательство может ссылаться на simulated, rejected или recommendation decision: checker проверяет лишь существование `decision_id` ([строки 670–683](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:670)). `project.json.business_decision_status` вообще не сверяется с журналом.

Это ломает более сильное обещание «рекомендация не равна решению» из [AGENTS.md:16](/home/alexchist/Ouroboros/projects/mgimo-project/AGENTS.md:16), даже если модель следует инструкции неидеально.

Fix scope: для human accepted требовать timestamp, decider, выбранный вариант и основания либо явную запись об их отсутствии; запрещать confirmed commitments для simulated/non-accepted решений; проверять текущий статус проекта по последнему действующему человеческому решению.

### P1 — recovery не имеет поддерживаемого выхода из `outcome_unknown`

`recover` переводит незавершённую операцию в `outcome_unknown` ([строки 533–547](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:533)). Но `operation finish/fail/unknown` разрешён только для `in_progress`; любой другой статус отвергается ([строки 515–527](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:515)). Поэтому после проверки фактического результата CLI не позволяет записать, что неизвестный исход разрешён. Предупреждение остаётся навсегда, а повторная операция теряет явную связь с проверкой.

Fix scope: добавить append-only действие `resolve`/`verify` с результатом, временем, проверенным артефактом и optional replacement operation ID. Не переписывать исходное событие recovery.

### P1 — ревизия может создать новое «основание» со старым источником

При `revise --new-statement` отсутствующие `source_ids` и locator автоматически наследуются от старого утверждения ([строки 565–570](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:565)). Новая формулировка поэтому может получить активный статус и выглядеть доказанной прежним фрагментом, который её не поддерживает. CLI не требует нового источника или явного подтверждения, что старый locator по-прежнему применим.

Fix scope: для replacement требовать явные `source_ids` и locator либо отдельный флаг `--reuse-evidence` с записанной причиной. Перед записью валидировать новый claim теми же правилами, что и `check`.

### P1 — ревизия не транзакционна и карта влияния обрывается до обязательств

`revise` сначала перезаписывает claims ([строка 572](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:572)), затем conclusions, затем revision log и Markdown report. Сбой между стадиями оставит частично применённую ревизию без события или отчёта.

Кроме того, closure заканчивается на decisions ([строки 573–599](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:573)). Связанные commitments не попадают в impact report и не получают review marker, хотя архитектура обещает цепочку `revision → impact → new decision → commitments` в [architecture.md:10–14](/home/alexchist/Ouroboros/projects/mgimo-project/docs/architecture.md:10).

Fix scope: сначала вычислить и провалидировать полный change-set, записать временные версии всех затронутых реестров, затем заменить их как единый recoverable batch или вести небольшой journal. Добавить affected commitments по затронутым decision IDs и предупреждение checker до человеческого пересмотра.

### P1 — `init` гарантированно оставляет пустой `created_at`

Шаблон содержит `"created_at": ""` ([project.json:5](/home/alexchist/Ouroboros/projects/mgimo-project/templates/project/project.json:5)). Инициализация использует `metadata.get("created_at", now())` ([строки 132–134](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:132)); существующая пустая строка поэтому сохраняется. Тот же дефект виден в [web-smoke/project.json:5](/home/alexchist/Ouroboros/projects/mgimo-project/examples/web-smoke/project.json:5).

Fix scope: `metadata.get("created_at") or now()` и обязательная проверка timestamp в `check`.

### P1 — web provenance теряет query, определяющий документ

`sanitized_url` полностью удаляет query и fragment ([строки 362–367](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:362)), а именно эта строка сохраняется как `origin` ([строки 391–399](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:391)). Для URL вида `/report?id=123` реестр укажет `/report`, который может быть другим документом или вообще не воспроизводиться.

Fix scope: сохранять canonical final URL с query; потенциально чувствительные параметры редактировать по явной политике, сохраняя hash исходного URL или перечень удалённых ключей. Fragment можно удалять отдельно.

### P1 — CSV, принятый ingest, может быть неверно профилирован

`extract_csv` определяет запятую, `;` и tab ([строки 181–201](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:181)). `profile` использует обычный `csv.DictReader` без определения dialect ([строки 447–460](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:447)). Поэтому корректный `;`/tab CSV успешно импортируется, но профиль превращает всю строку в одну колонку без ошибки.

Fix scope: единая функция dialect/header validation для ingest, profile и retention; сохранять выбранный dialect в method card; предупреждать о дублирующихся/пустых заголовках и аномальном числе колонок.

### P2 — динамический HTML не всегда получает обещанный gap

Документация утверждает, что неполнота динамической страницы сохраняется как gap ([architecture.md:41](/home/alexchist/Ouroboros/projects/mgimo-project/docs/architecture.md:41)). Реально gap появляется только если не найдено вообще ни одной поддерживаемой записи ([строки 174–178](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:174)). SPA-shell с `<title>` или одним статическим `<p>` будет считаться извлечённым без gap, хотя основное содержимое загружается JavaScript.

Fix scope: при наличии script-heavy shell, framework roots или очень малого отношения extracted text к HTML добавлять консервативный gap `possible_dynamic_content`; не пытаться объявлять полноту автоматически.

Общая неподдержка JS-rendered web уже честно раскрыта в [limitations.md:17](/home/alexchist/Ouroboros/projects/mgimo-project/docs/limitations.md:17). Дефект здесь — не отсутствие браузера, а противоречащее документации отсутствие gap.

### P2 — XLSX теряет типы дат и не сообщает об этом

Extractor выводит сырое `<v>` без анализа styles/number formats ([строки 246–289](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:246)). Дата может стать числом вроде `45292`, процент — десятичной дробью без форматного контекста. Это особенно опасно для периода и единицы evidence. В известных ограничениях перечислены формулы, диаграммы и hidden sheets, но не потеря типов дат/форматов ([limitations.md:16](/home/alexchist/Ouroboros/projects/mgimo-project/docs/limitations.md:16)).

Fix scope: минимально читать `styles.xml` и помечать date/percentage/currency formats либо добавлять per-cell gap о неинтерпретированном style ID. Формулы вычислять не требуется.

## Раскрытые ограничения, не дефекты обещания

- OCR, сканы, изображения и сложная PDF-вёрстка явно не заявлены: [limitations.md:15](/home/alexchist/Ouroboros/projects/mgimo-project/docs/limitations.md:15).
- Формулы XLSX намеренно не вычисляются: [architecture.md:38](/home/alexchist/Ouroboros/projects/mgimo-project/docs/architecture.md:38).
- JS-rendering, логины, crawling и DNS-pinning не заявлены: [limitations.md:17](/home/alexchist/Ouroboros/projects/mgimo-project/docs/limitations.md:17).
- Cursor и non-Linux consumer portability ещё не проверены: [limitations.md:20](/home/alexchist/Ouroboros/projects/mgimo-project/docs/limitations.md:20), [requirements.md:25](/home/alexchist/Ouroboros/projects/mgimo-project/docs/requirements.md:25). Это честный verification gap, хотя Windows-пути дополнительно потребуют внимания: проверка `urlparse(...).scheme` в [строке 391](/home/alexchist/Ouroboros/projects/mgimo-project/tools/strategist.py:391) примет `C:\...` за URL.
- Семантическая поддержка цитаты кодом не доказывается и правильно оставлена ручной проверке: [limitations.md:25](/home/alexchist/Ouroboros/projects/mgimo-project/docs/limitations.md:25).

Итог: архитектурное разделение источников, claims, решений и истории разумно, но текущий integrity/recovery слой пока не обеспечивает наиболее важное обещание папки: после холодного старта нельзя надёжно отличить актуальное, проверенное состояние от структурно правдоподобного, но повреждённого или устаревшего.
