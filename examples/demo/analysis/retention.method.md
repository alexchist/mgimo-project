# Метод расчёта удержания и состава

- Вход: `sources/originals/S-002__retention.csv`, SHA-256 `331d2cc26af1106a52d236cfce63ebcddbb8e019496f6ceae1bda628975d2cbc`.
- Период: когорты `2026-08` и `2026-09`; гранулярность — когорта × канал × период 0/4.
- Числитель W4: `active_users` при `period=4`. Знаменатель: `cohort_size` соответствующей пары когорта × канал при `period=0`.
- Определение активности из S-003: не менее одного завершённого урока в дни 22–28, часовой пояс UTC+3.
- Команды:
  - `/usr/bin/python3 tools/strategist.py profile projects/retention-run/sources/originals/S-002__retention.csv --output projects/retention-run/analysis/retention-profile.json`
  - `/usr/bin/python3 tools/strategist.py retention projects/retention-run/sources/originals/S-002__retention.csv --output projects/retention-run/analysis/retention-calculated.csv`
  - `/usr/bin/python3 projects/retention-run/analysis/composition.py projects/retention-run/sources/originals/S-002__retention.csv > projects/retention-run/analysis/retention-by-channel.csv`
- `retention` CLI корректно считает долю каждой исходной строки, но не переносит `channel` в выход. Поэтому канал восстанавливается только по `source_locator`; отдельный скрипт сохраняет канал явно и считает blended/counterfactual значения.
- Контрфактуал `old_rates × new_mix` изолирует сдвиг состава при старых канальных ставках; `new_rates × old_mix` показывает новые ставки при старом составе. Это декомпозиция, не причинная оценка.
- Ограничения: нет user-level данных, случайного назначения и определения acquisition/оплаты; `missing_completion_events_pct` дан на уровне событий, а не пользователей, поэтому корректировать им retention арифметически нельзя.
