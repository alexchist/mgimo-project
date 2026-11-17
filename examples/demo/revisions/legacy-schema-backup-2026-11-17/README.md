# Legacy schema backup

Создано перед cold continuation 17.11.2026. Это резервные копии метаданных до минимальной миграции под текущий CLI, а не новые доказательства.

- `project.json`: добавляется только `artifact_stage=decision_draft`; исходный SHA-256 `6b4b63a714259e89f729fbae52627ce17eb2bf3a1bde05491f13d6ec77144056`.
- `sources-index.json`: к существующим S-001…S-004 добавляются вычисленные из уже сохранённых extract-файлов `extract_sha256`; оригиналы и извлечения не меняются; исходный SHA-256 `39ad0b74c00966a3a00c1ba7b7ab941c64cc50a3dd34c19431f7dcd6ac3eebe6`.
- `operations.csv`: текущий CLI добавляет пустые служебные колонки `related_operation_id` и `resolution`, сохраняя 20 прежних строк; исходный SHA-256 `7cda7f9cbbf00e620e574b91c0d7011fb98093fe8ae7b7d37c3cf3186bc4e78e`.
- `revision-log.csv`: текущий CLI добавляет поля `evidence_action` и `affected_commitments`; до пересмотра реестр был пуст; исходный SHA-256 `9f36fb402eac6ca813981d9adaf6ffe7dc348258d008a3da262381484ade533b`.
- `runs/ingest-failures.csv` отсутствовал и создан с каноническим заголовком; исторические failed ingest не выдумывались.

Снимок прежней стратегии сохранён отдельно как `../pre-product-update-strategy.md`, SHA-256 `42aa9a903ce5cf504b8921f57ad4ab9e0f4b9d0a8fc9bcc614d4eca49688dfe1`.
