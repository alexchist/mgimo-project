#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(CDPATH= cd -- "$script_dir/.." && pwd)"
base="$project_dir/materials/economics.csv"
update="$project_dir/new-materials/supplier-update.md"

paid_variable_cost="$(sed -nE 's/.*она составляет ([0-9]+) RUB.*/\1/p' "$update")"
if [[ ! "$paid_variable_cost" =~ ^[0-9]+$ ]]; then
  echo "cannot extract exactly one paid_pilot replacement cost from $update" >&2
  exit 1
fi
if ! grep -q 'полный заменяющий показатель' "$update"; then
  echo "update does not explicitly declare replacement semantics" >&2
  exit 1
fi

LC_ALL=C awk -F, -v paid_variable_cost="$paid_variable_cost" '
  NR == 1 { next }
  $1 == "paid_pilot" {
    paid_price = $2
    paid_setup = $4
    paid_fixed = $5
  }
  $1 == "manual_service" {
    manual_price = $2
    manual_variable = $3
    manual_setup = $4
    manual_fixed = $5
  }
  END {
    count = split("1 3 5 8 10 18 20 22 30 67", accounts, " ")
    label[1] = "sensitivity"
    label[3] = "proposed_lower_learning_gate"
    label[5] = "proposed_upper_small_pilot"
    label[8] = "manual_break_even_integer"
    label[10] = "sensitivity"
    label[18] = "former_paid_break_even_now_invalid"
    label[20] = "manual_source_scenario_account_count"
    label[22] = "former_crossover_now_invalid"
    label[30] = "paid_source_scenario_account_count"
    label[67] = "revised_paid_break_even_integer"

    print "accounts,paid_pilot_3m_result_rub,manual_service_3m_result_rub,interpretation"
    for (i = 1; i <= count; i++) {
      n = accounts[i]
      paid = 3 * (paid_price - paid_variable_cost) * n - paid_setup - 3 * paid_fixed
      manual = 3 * (manual_price - manual_variable) * n - manual_setup - 3 * manual_fixed
      printf "%d,%.0f,%.0f,%s\n", n, paid, manual, label[n]
    }
  }
' "$base"
