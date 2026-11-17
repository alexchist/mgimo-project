# Метод расчёта экономики

- Вход: `materials/economics.csv`, SHA-256 `09e105efef94ef9e0e83969da9e389df610fe79cd52dbe1db35c23f3ef65b67e` (`S-001`).
- Период: три календарных месяца; единица — аккаунт-месяц; валюта — RUB.
- Команда профиля: `python3 tools/strategist.py profile materials/economics.csv --output results/analysis/economics-profile.json`.
- Команда расчёта: `python3 results/analysis/economics.py materials/economics.csv`.
- Проверка сохранённого результата: `diff -u results/analysis/economics-results.csv <(python3 results/analysis/economics.py materials/economics.csv)`.

Формулы:

- маржа аккаунт-месяца = цена − переменные затраты;
- результат 3 месяцев = маржа × аккаунты × 3 − setup − fixed × 3;
- безубыточные аккаунты = (setup + fixed × 3) / (маржа × 3);
- точка равенства при одинаковом числе аккаунтов = разница полных фиксированных затрат / ((маржа paid − маржа manual) × 3).

Ограничения: строки — сценарии `forecast_not_demand`, а не наблюдаемый спрос. Не заданы CAC, налоги, возвраты, ставка времени, отток, стоимость вывода и распределение инженерной поддержки. Поэтому расчёт — чувствительность, не прогноз фактической прибыли и не LTV.
