# Метод расчёта

Вход: `projects/shifts/sources/originals/S-002__retention.csv` (sha256 `4cd873adc331fc5a57d4bebaf244851c2f616bce25b918ff1a337e1898cb782a`), delimiter `,`.

Детально: `retention_rate = active_users / cohort_size` для каждой строки. Сводка по cohort+period: `sum(active_users) / sum(cohort_size)`, то есть взвешенная доля, а не среднее процентов. Единица результата — доля, не процент. Скрипт не делает причинных или стратегических выводов.
