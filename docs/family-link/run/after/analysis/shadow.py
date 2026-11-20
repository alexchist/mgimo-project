import csv
from pathlib import Path

originals = Path(__file__).resolve().parents[1] / "sources/originals"
with (originals / "S-003__design.csv").open(encoding="utf-8", newline="") as stream:
    design = {row["parameter"]: int(row["value"]) for row in csv.DictReader(stream)}
with (originals / "S-005__shadow.csv").open(encoding="utf-8", newline="") as stream:
    weeks = list(csv.DictReader(stream))

week_numbers = [int(row["week"]) for row in weeks]
families = [int(row["new_unique_eligible_families"]) for row in weeks]
events = [int(row["trigger_events"]) for row in weeks]
if week_numbers != list(range(1, 5)) or any(
    not 0 <= unique <= total for unique, total in zip(families, events)
):
    raise ValueError("Ожидаются четыре последовательные недели и корректные счётчики.")

recruitment_weeks = design["recruitment_window"]
target = design["sample_target"]
mean_flow = sum(families) / len(weeks)
projected = mean_flow * recruitment_weeks
weeks_to_target = target / mean_flow
print(f"За четыре недели: {sum(families)} новых семей, {sum(events)} событий.")
print(f"Среднее за неделю: {mean_flow:g} новых семей, {sum(events) / len(weeks):g} событий.")
print(f"Целевой поток: {target / recruitment_weeks:g} назначаемых семей в неделю.")
print(f"При сохранении потока за {recruitment_weeks} недель: {projected:g} подходящих семей.")
print(f"Если назначить всех: {projected / 2:g} на ветвь; {projected / target:.0%} цели; недобор {target - projected:g}.")
print(f"Если средний поток равен минимуму/максимуму четырёх недель: "
      f"{min(families) * recruitment_weeks}–{max(families) * recruitment_weeks} подходящих семей.")
print(f"До цели при назначении всех: {weeks_to_target:g} недель набора, "
      f"{weeks_to_target + 1:g} недель до последнего исхода, затем анализ.")
