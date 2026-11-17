# Метод пересчёта экономики

- Исходные основания: неизменённые поля `S-001` и заменяющая поправка переменной стоимости `S-005#line:2`.
- Производный вход: `analysis/economics-revised-input.csv`, SHA-256 `a6e454fc67eb66ba1b2273f7a031629caac42fca984a31ae60b8d23dc6e5d005`. Старые вход и результат не изменены.
- Период: три календарных месяца; единица — аккаунт-месяц; валюта — RUB.
- Команда профиля: `python3 tools/strategist.py profile results/analysis/economics-revised-input.csv --output results/analysis/economics-revised-profile.json`.
- Команда расчёта: `python3 results/analysis/economics-revised.py results/analysis/economics-revised-input.csv`.
- Проверка сохранённого результа: `diff -u results/analysis/economics-revised-results.csv <(python3 results/analysis/economics-revised.py results/analysis/economics-revised-input.csv)`.

Формулы:

- маржа аккаунт-месяца = цена − переменные затраты;
- результат 3 месяцев = маржа × аккаунты × 3 − setup − fixed × 3;
- безубыточные аккаунты = (setup + fixed × 3) / (маржа × 3);
- порог цены/затрат при 30 аккаунтах получен обратным решением той же формулы;
- при равном числе аккаунтов `paid_pilot` не имеет неотрицательной точки переключения: его маржа 1200 ниже 1300 у `manual_service`, а трёхмесячные фиксированные затраты 240000 выше 30000 RUB.

Ограничения: все цифры синтетические, поправка — оценка, а не договор. Объёмы — `forecast_not_demand`. Не заданы CAC, налоги, возвраты, ставка времени, отток, стоимость вывода и полная поддержка. Расчёт — чувствительность, не прогноз прибыли и не доказательство спроса.
