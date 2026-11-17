# Протокол локальной проверки

Дата: 17.11.2026. Среда: Linux, Python 3.12.7, `pdftotext`/`pdfinfo` доступны. Платные API не использовались. Cursor runtime не квалифицирован. После авторского прохода координатор выполнил независимые consumer/baseline и cold-прогоны; ниже их отдельная граница доказательств.

## Команды

```bash
python3 -m py_compile tools/strategist.py tools/generate_fixtures.py tools/tests/test_strategist.py
TMPDIR=/tmp python3 -m unittest discover -s tools/tests -p 'test_*.py' -q
python3 tools/strategist.py check examples/web-smoke
python3 tools/strategist.py doctor
git diff --check
```

Родитель повторил финальный набор v0.3 после критики: **21/21 tests OK, 28.616 s** (новые проверки неизвестной schema_version и Markdown-import). Авторский предыдущий прогон: 18/18, 22.520 s; шесть `SKILL.md` прошли `quick_validate`, `doctor` видел Python 3.12.7 и `pdftotext`. Версия CLI — 0.3.0. Отдельный smoke-init создал schema 1.1 с `decision-memo.md`, после чего `check` вернул `ok: true` без warnings. Legacy schema 1.0 примеры `web-smoke` и `demo` остались валидны; их содержимое не менялось. `git diff --check` прошёл. Ранее два последовательных запуска `generate_fixtures.py` дали одинаковые SHA-256 всех case files; fixtures в v0.3 не менялись. Время зависит от машины и не является benchmark модели.

## Что непосредственно проверяют тесты

1. DOCX/XLSX являются настоящими OOXML ZIP packages; PDF имеют text layer; все case README явно называют inputs синтетическими.
2. Mixed ingest выдаёт `page`, `paragraph`, CSV row/column, XLSX sheet/cell и HTML element locators; formula без cached value и границы extraction становятся gaps.
3. Quoted multiline CSV не склеивает слова, short rows явно учитываются как missing, ingest/profile/retention понимают один detected delimiter. Duplicate/empty headers отклоняются; profile/retention не принимают extra cells, а retention — header-only input.
4. Retention строки и взвешенная cohort summary воспроизводят 0.40/0.11 и 0.34/0.17.
5. Отсутствующие канонические файлы (включая `decision-memo.md` для schema 1.1), пустые/дублирующиеся ID, неполное accepted decision и commitment на simulated decision ломают integrity.
6. Изменение оригинала или extract ломает hash integrity; source-qualified locator проверяется по сохранённому extract.
7. Static HTML берёт текст из `div`, `text/plain` не разбирается как HTML, query identity сохраняется с явной redaction, Windows drive path не принимается за URL.
8. Failed ingest записывается отдельно без orphan source; pending ingest/revision обнаруживается и явно восстанавливается. Batch precheck отказывается от recovery без частичных изменений, если staged/final или before/after файл изменён позже; base64 manifest сохраняет точные байты revision.
9. Interrupted operation становится `outcome_unknown`; повторное finish запрещено, а проверка исхода добавляется отдельной resolution-строкой.
10. Revision требует новые citations либо обоснованный reuse для факта, помечает связанные выводы/решения/обязательства и не меняет историческое решение.
11. HTTP/private и неразрешённый HTTPS host отклоняются.

Дополнительно все четыре generated DOCX/XLSX успешно открыты LibreOffice 25.2.6 в headless режиме и экспортированы в PDF; эти PDF были только временной проверкой и в репозиторий не входят.

## HTTPS smoke

`https://example.com/` был явно allowlisted и фактически загружен. Сохранены final sanitized URL, retrieval time, SHA-256 `25ddf2c883e0d1958ea971d279a7e4f0fd446724ee3db7db19dadabd4a62e484`, исходник и `title[1]`/`p[1]` в `examples/web-smoke/`. Стоимость операции — `not_applicable`, human time — 1 minute. Это проверка capability, не регулярный мониторинг; сама страница просит не полагаться на домен как сервис.

## Независимые потребительские прогоны

После авторского прохода координатор повторил 18 тестов на /usr/bin/python3: PASS (31.491 с в этом запуске). Выполнены три свежие Codex-сессии на отдельных копиях, один baseline без папочного ядра и cold continuation в каталоге с пробелом. Исходники, ошибки и несопоставимые условия проверки раскрыты в [pilot/README.md](pilot/README.md); превосходство не установлено.

[Cold report](../examples/demo/cold-run-report.md): новый сеанс не повторил старые imports, сохранил точные байты прежнего решения/обязательства/стратегии, импортировал уточнение и GOV.UK, построил impact до K-001 и снял обещание отсутствующего Q&A. Финальный CLI проверен координатором: errors 0, warnings 18 (legacy locators, extraction gaps, unknown costs), human decision false. Это учебный сценарий, не решение владельца.

Остаются: Cursor и другая ОС/IDE, официальный конкурсный бриф и запись на нём, реальные пользовательские проверки, публикация/подача. Локальный архив проходит отдельный clean-copy check; он не доказывает запуск на другой машине.
