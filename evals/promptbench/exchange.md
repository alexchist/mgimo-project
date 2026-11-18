# Подключить другую модель без изменения проверок

`exchange.py` — **офлайн** обмен JSONL. Например, из корня:

```sh
python evals/promptbench/exchange.py export MODEL_ID > requests.jsonl
# Отправьте каждый payload своему chat API, сохраните results.jsonl.
python evals/promptbench/exchange.py import requests.jsonl results.jsonl /tmp/bench-import-new
python evals/promptbench/benchmark.py score /tmp/bench-import-new
```

На вход модели идут **только** `payload.messages` (system, user), заявленные настройки и выбранный model ID. Каждый запрос — новый диалог без инструментов и истории. `id`, `case`, `rep`, `arm` — данные координатора, не часть сообщения. Клиент обрабатывает строки по порядку. В импорте ключи `id` — строки, как в экспорте; `status=ok` только для завершённого непустого ответа, иначе `incomplete` / `api_error`; `seconds` — длительность, `finish=stop` для нормально завершённого, `served` — фактическая версия, `answer` — дословный текст. `usage={prompt_tokens,completion_tokens,total_tokens,precached_prompt_tokens}` — числовые счётчики, отсутствие/`null` означает «неизвестно». Если провайдер не поддерживает какую-либо настройку или меняет системное сообщение, запишите это в отдельном отчёте: это уже другой режим. Не передавайте ключи, заголовки и account ID в файлах. Неприсланные результаты не дополняются нулями. Сохранённые строки — свидетельство клиента, не автоматическое удостоверение провайдера.

Для свободных записок создайте два отдельных набора: `python evals/promptbench/blind.py prepare /tmp/bench-import-new /tmp/reader1` (повторите с `/tmp/reader2`). Каждый читатель получает **только свой `packet.json`**, не `mapping.json` или папку результатов. Разберите его JSON с `bits/risk/why` после фиксации: `python evals/promptbench/blind.py join /tmp/bench-import-new /tmp/reader1/mapping.json marks1.json`. Другие читатели и протокол раскрытия могут менять свободные оценки; записывайте их отдельно от детерминированных баллов.

Этот обмен проверен offline через повторный импорт всех сохранённых ответов первой серии; он **не является проверенной live-интеграцией** с иным API. Из бесплатных операций в смысле отсутствия вызовов моделей: `prompt`, `score`, `export`, `import`, `prepare`, `join`. Сама генерация и отдельные модельные судьи могут расходовать токены/лимиты.
