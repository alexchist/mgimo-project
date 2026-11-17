# Метод расчёта

Вход: `/home/alexchist/strategist-evals-ce7897fb/adversarial/results/sources/originals/S-001__metrics.csv` (sha256 `8f891a8fe323942da09e0afe676ecc2797f22bf987a4d605a8c687b1b448b70e`), delimiter `,`.

Детально: `retention_rate = numerator / denominator` для каждой строки. Сводка по cohort+period: `sum(numerator) / sum(denominator)`, то есть взвешенная доля, а не среднее процентов. Единица результата — доля, не процент. Скрипт не делает причинных или стратегических выводов.
