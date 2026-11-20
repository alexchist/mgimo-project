import csv
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "sources/originals/S-003__design.csv"
with source.open(encoding="utf-8", newline="") as stream:
    inputs = {}
    for row in csv.DictReader(stream):
        parameter = row["parameter"]
        if parameter in inputs:
            raise ValueError(f"Повтор параметра {parameter}")
        inputs[parameter] = int(row["value"])

weeks = inputs["recruitment_window"]
target = inputs["sample_target"]
flow = inputs["weekly_flow"]
print(f"Недель набора: {weeks}. Последний исход через {weeks + 1} недель от начала набора.")
print(f"Цель: {target} семей, по {target // 2} в ветви при равном распределении.")
print(f"Средний поток для цели: {target / weeks:g} назначаемых семей в неделю.")
for scenario_flow in (flow * 9 // 10, flow, flow * 11 // 10):
    recruited = scenario_flow * weeks
    print(f"Сценарий {scenario_flow}/нед.: {recruited} семей, отклонение {recruited - target:+d}.")
base = inputs["base_outcome"]
alternative = inputs["alternative_outcome"]
print(f"Сценарий {base}% → {alternative}%: снижение на {base - alternative} п. п. "
      f"({(base - alternative) / base:.0%} относительно контроля).")
