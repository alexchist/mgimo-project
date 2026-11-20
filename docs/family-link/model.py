"""Учебный сценарий по Примеру брифа, не данные абонентов. Python 3, без пакетов."""
from math import ceil, sqrt

# Два канала атрибутированы без пересечения. Кортеж: аудитория, создано,
# подключено, активировано за 14 дней, подключилось бы обычно, стоимость.
CHANNELS = [(8000,1600,1200,880,800,80000),(2000,600,450,360,250,40000)]
EXTRA = sum(connected - usual for _, _, connected, _, usual, _ in CHANNELS)
SCENARIOS = {
    # month of first access: unique index numbers in intervention, one per family (not controls)
    'основной': ({4: 600, 5: 600, 6: 600, 8: 1200, 10: 1800}, .98, [20000, 90000, 90000, 140000], 2500+EXTRA, 1000-100, .65, 600*.45+600*.63, 1200),
    'слабый': ({4: 150, 5: 150, 6: 150}, .971, [20000, 70000, 20000, 0], 2500, 1000, .625, 540, 1200),
}

def estimate(row):
    cohorts, survive, direct, new, left, active_share, activated, created = row
    paid = [sum(n * (survive ** (m - j) - .97 ** (m - j)) for j, n in cohorts.items() if m >= j) for m in range(1, 13)]
    q_paid = [sum(paid[i:i+3]) for i in range(0, 12, 3)]
    delta = [500 * x - c for x, c in zip(q_paid, direct)]
    connected = 6500 + new - left
    return dict(monthly=paid, q_paid=q_paid, q_delta=delta, total=279_000_000+sum(delta), gap=6_000_000-sum(delta), months_needed=(6_000_000+sum(direct))/500, connected=connected, active=connected*active_share, owners=800+300-100, activation=activated/created, cap=max(0, sum(delta)))

if __name__ == '__main__':
    for name, row in SCENARIOS.items():
        out = estimate(row)
        for k, v in out.items(): print(name, k, [round(x,2) for x in v] if isinstance(v,list) else round(v,3))
    p0, p1 = .12, .09
    p = (p0 + p1)/2
    n = ceil(((1.96 * sqrt(2*p*(1-p)) + .84162 * sqrt(p0*(1-p0)+p1*(1-p1)))/(p0-p1))**2)
    print('n per arm, no loss:', n, 'planned per arm with 9% missing:', ceil(n/.91))
