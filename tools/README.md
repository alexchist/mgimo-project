# Локальные инструменты

`strategist.py` — один stdlib CLI. Он не вызывает LLM и не принимает стратегических решений.

| Команда | Назначение |
|---|---|
| `doctor` | версии и наличие `pdftotext` |
| `init` | чистое состояние кейса из template |
| `ingest` | копия исходника, hash, source record, locators/gaps |
| `ingest-recover` | явно завершить или удалить обнаруженный pending ingest |
| `profile` | missing/distinct/numeric summary CSV |
| `retention` | `active_users / cohort_size`, взвешенная cohort summary + method card |
| `operation` | started/result/cost/human time; `resolve` добавляет проверку unknown, не переписывая историю |
| `recover` | interrupted → outcome_unknown без повтора |
| `revise` | статус claim, evidence policy, revision event, impact до commitments и памятка смыслового пересчёта |
| `revision-recover` | явно завершить или откатить обнаруженный частичный revision |
| `check` | канонические файлы, hashes, точные ID/locators, состояния и pending recovery |

Markdown (`.md`/`.markdown`) и TXT читаются построчно с оригиналом/hash/locator: разметка, ссылки и вложенные media не исполняются. `check` поддерживает только строковые schema `1.0` и `1.1`, неизвестные версии не объявляет валидными.

PDF требует внешний `pdftotext`. OCR не является fallback. DOCX/XLSX читаются напрямую как OOXML; это снижает зависимости, но границы перечислены в `docs/limitations.md`. Новые проекты schema 1.1 включают `decision-memo.md`; старые schema 1.0 остаются проверяемыми без переписывания истории.

Новый проверяемый locator записывается с источником: `S-001#page:2,line:7` или `S-001#row:2,column:variant;S-002#paragraph:4`. Старые и сложные locator сохраняются, но `check` выдаёт предупреждение и не притворяется, что проверил их. `check ok` означает только структурную целостность на объявленной стадии `artifact_stage`; смысловую поддержку тезиса, различность вариантов и качество стратегии нужно проверить агенту и человеку.

CSV должен иметь непустые уникальные заголовки после удаления краевых пробелов. `profile` и `retention` отказываются продолжать строку с лишними ячейками; короткая строка остаётся в профиле с явным missing. `retention` не создаёт результат для файла без строк данных. Extract сохраняет extra cells как отдельные locators и gap, не скрывая нарушение схемы.

Recovery рассчитан на одного writer. Перед `complete`, `rollback` или `discard` команда проверяет все относящиеся к операции файлы: для нового revision manifest — точное совпадение байтов с retained before/after, для ingest — SHA-256 из pending manifest. Если хотя бы один файл изменён позже, recovery отказывается от всей партии до первой записи или удаления; pending manifest остаётся для ручного разбора. Старый текстовый revision manifest поддерживается как UTF-8, но не может восстановить байты, которые не были в нём сохранены, например исходные CRLF после прежней нормализации.

Регенерация синтетических fixtures:

```bash
python3 tools/generate_fixtures.py
TMPDIR=/tmp python3 -m unittest discover -s tools/tests -v
```

Генератор детерминирован, включая фиксированные ZIP metadata; evaluator keys не используются генератором и остаются отдельными.
