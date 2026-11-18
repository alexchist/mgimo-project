# Заранее зафиксированный опыт: перенос правил Стратега на ProductJudge-Bench

Одна серия: все 24 публичные задачи [ProductJudge-Bench, Christian Ciabattoni](https://github.com/opheleon/ProductJudge-Bench/tree/3732c9a05080e8a6d0de424a626beb8fd4b149d9), commit `3732c9a05080e8a6d0de424a626beb8fd4b149d9`, и неизменённые инструкции Стратега из `ea6de6b`. Цель — проверить, помогает ли небольшой пакет инструкций применять явно заданную продуктовую политику. Это не тест выбора собственной стратегии, IDE, чтения файлов, памяти или работы человека.

**A:** только дословный английский `pjbench.prompt.build_prompt`. **B:** тот же user + фиксированный system: оговорка о приоритете задачи/JSON, полные `BIBLE.md` и `skills/compare-options/SKILL.md`, без адаптации по задачам. Обе стороны: GigaChat-3-Ultra, одна свежая история на задачу, температура 0,2, максимум 2048 токенов, без инструментов и настройки reasoning effort. Один повтор; порядок задач перемешан с seed 18024; поочерёдно AB/BA. Запросы и ответы других задач не попадают в диалог. Только если штатный парсер отверг ответ, допускается одна штатная попытка исправить формат (в обоих плечах). Ошибка API или неожиданная модель — остановка без пересылки; незапущенное не оцениваем как ошибочный ответ. Стоимость неизвестна. Английская задача и русские инструкции, добавленная длина и содержание в B не отделены. Набор и его авторские разборы публичны, не hidden holdout.

**До результата:** главные показатели — `overall`, `decision` штатного `pjbench grade` отдельно, без своей переоценки; дополнительно — ветвь, формат, исправление, парные изменения по каждому случаю, токены; не считать варианты независимой выборкой. Ни одна ветвь не видит ключей или baseline. Нужны `validate` 24/24, локальный oracle 100% и сопоставление с лучшими простыми алгоритмами именно этого commit. Не переносить сравнение на другие модели/настройки или таблицу лидеров автора.

## Повторить (Python 3.11+, пример Bash из корня Стратега)

```bash
ROOT=$PWD; W=$(mktemp -d); git clone -q https://github.com/opheleon/ProductJudge-Bench.git "$W/upstream"
git -C "$W/upstream" checkout -q 3732c9a05080e8a6d0de424a626beb8fd4b149d9
python3 -m venv "$W/venv"; PY="$W/venv/bin/python"
"$PY" -m pip install 'pydantic==2.14.3' 'PyYAML==6.0.3' 'gigachat==0.2.3'
SRC="$W/upstream/src"; SPLIT="$W/upstream/scenarios/public"; RUN="$W/run"
pj() { PYTHONPATH="$SRC" "$PY" -m pjbench.cli "$@"; }
bridge() { PYTHONPATH="$SRC" "$PY" "$ROOT/evals/productjudge/bridge.py" "$1" "$SPLIT" "$RUN"; }
pj validate --scenarios "$SPLIT"
pj baseline --scenarios "$SPLIT" --out "$W/baselines.jsonl"
pj grade "$W/baselines.jsonl" --scenarios "$SPLIT" --out "$W/baseline-scores.json"
bridge prepare
# Только collect использует секреты GIGACHAT_CREDENTIALS/GIGACHAT_SCOPE в окружении.
# При необходимости добавить --ca /path/to/trusted.pem. Не отключать TLS.
"$PY" evals/productjudge/collect.py "$RUN/prepare.json" --max-calls 48
bridge repairs
"$PY" evals/productjudge/collect.py "$RUN/repairs.json" --max-calls 48
bridge assemble
pj grade "$RUN/predictions.jsonl" --scenarios "$SPLIT" --out "$RUN/scores.json"
pj report "$RUN/scores.json"
```

Штатный `run` не имеет нативного провайдера GigaChat: адаптер меняет транспорт; рендер, разбор JSON, формулировка исправления, проверка связности предсказаний, оценка и отчёт — из неизменённого upstream. `bridge assemble` воспроизводит сохранённые ответы через его `run_scenario`, проверяет хеш фактически отправленных сообщений, не просит модель снова. В формате upstream стоимость по умолчанию 0; это техническое значение, **не цена**. Для бесплатной перепроверки опубликованных predictions нужны только `pj grade` и `pj report`. Не перезапускать сбор в уже начатом каталоге. Код upstream MIT; публичные сценарии CC BY 4.0, вывод модели по ним — не новый собственный датасет.
