# Метод расчёта экономики

Вход: `/home/alexchist/strategist-evaluation-50043d69/new-service/projects/new-service-run/sources/originals/S-002__economics.xlsx`; SHA-256 `757e6b6bddeabac1ea3184453b02675e7bc4d0b49cd0ed466399a24535cbefb4`.

Для каждой строки листа `scenario`: `contribution_per_user = monthly_price_rub - variable_cost_rub - support_cost_rub`; `contribution_total = contribution_per_user × users`. Вычисления целочисленные, единица — рубли в месяц. Поле `users` условно трактуется как платящие активные пользователи; источник этого не определяет. Это вклад до фиксированных затрат, привлечения, налогов, возвратов и платёжных комиссий, а не прибыль, LTV или прогноз.
