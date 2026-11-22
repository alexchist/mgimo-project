import csv
from math import sqrt, ceil
from statistics import NormalDist
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with (root / "sources/originals/S-005__shadow.csv").open(encoding="utf-8", newline="") as stream:
    rows = list(csv.DictReader(stream))
fam = [int(r["new_unique_eligible_families"]) for r in rows]
ev = [int(r["trigger_events"]) for r in rows]
weeks, target, plan_flow, plan_weeks = len(fam), 3600, 400, 9
total = sum(fam)
flow = total / weeks
print(f"Недель наблюдения: {weeks}. Уникальных подходящих семей: {total} (по неделям {fam}).")
print(f"Средний поток: {flow:g} в неделю; план {plan_flow}; доля от плана {flow/plan_flow:.0%}; диапазон {min(fam)}-{max(fam)}.")
print(f"События с повторами: {sum(ev)} (по неделям {ev}); это не семьи, в расчёт набора не входят.")
n9 = flow * plan_weeks
print(f"За {plan_weeks} недель при таком потоке: {n9:g} семей, {n9/2:g} на ветвь, {n9/target:.0%} цели {target}.")
print(f"Недель для {target} семей при таком потоке: {target/flow:g}; плюс неделя на исход.")
print(f"Поток, нужный для цели за {plan_weeks} недель: {target/plan_weeks:g} в неделю, то есть в {target/plan_weeks/flow:.1f} раза выше наблюдаемого.")
p1, p2 = .12, .09
z = NormalDist()


def power(n):
    se = sqrt(p1 * (1 - p1) / n + p2 * (1 - p2) / n)
    return 1 - z.cdf(z.inv_cdf(.975) - (p1 - p2) / se)


need = ceil((z.inv_cdf(.975) + z.inv_cdf(.8)) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p1 - p2) ** 2)
print(f"Сценарий 12%->9%, двусторонний α=0,05, нормальное приближение. Мощность при {n9/2:g} на ветвь: {power(n9/2):.0%}; при 1800 на ветвь: {power(1800):.0%}.")
print(f"Для мощности 80% нужно около {need} на ветвь, {2*need} всего, то есть {2*need/flow:.0f} недель при таком потоке.")
