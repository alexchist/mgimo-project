# Метод расчёта

Вход: `/home/alexchist/strategist-evaluation-50043d69/retention/projects/retention-run/sources/originals/S-002__retention.csv` (sha256 `331d2cc26af1106a52d236cfce63ebcddbb8e019496f6ceae1bda628975d2cbc`).

Детально: `retention_rate = active_users / cohort_size` для каждой строки. Сводка по cohort+period: `sum(active_users) / sum(cohort_size)`, то есть взвешенная доля, а не среднее процентов. Единица результата — доля, не процент. Скрипт не делает причинных или стратегических выводов.
