#!/usr/bin/env python3
"""Reproduce three-month unit economics and comparison thresholds."""

import csv
import sys
from decimal import Decimal


MONTHS = Decimal("3")


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("1")))


with open(sys.argv[1], newline="", encoding="utf-8") as handle:
    rows = {row["option"]: row for row in csv.DictReader(handle)}

result = {}
for option, row in rows.items():
    price = Decimal(row["monthly_price_rub"])
    variable = Decimal(row["variable_cost_per_account_month_rub"])
    setup = Decimal(row["setup_cost_rub"])
    fixed = Decimal(row["monthly_fixed_cost_rub"])
    accounts = Decimal(row["accounts_scenario"])
    margin = price - variable
    three_month_result = margin * accounts * MONTHS - setup - fixed * MONTHS
    break_even_accounts = (setup + fixed * MONTHS) / (margin * MONTHS)
    result[option] = {
        "margin_per_account_month_rub": money(margin),
        "three_month_scenario_result_rub": money(three_month_result),
        "break_even_accounts_exact": f"{break_even_accounts:.6f}",
    }

paid = rows["paid_pilot"]
manual = rows["manual_service"]
paid_margin = Decimal(paid["monthly_price_rub"]) - Decimal(paid["variable_cost_per_account_month_rub"])
manual_margin = Decimal(manual["monthly_price_rub"]) - Decimal(manual["variable_cost_per_account_month_rub"])
cost_delta = (
    Decimal(paid["setup_cost_rub"]) + Decimal(paid["monthly_fixed_cost_rub"]) * MONTHS
    - Decimal(manual["setup_cost_rub"]) - Decimal(manual["monthly_fixed_cost_rub"]) * MONTHS
)
same_account_switch = cost_delta / ((paid_margin - manual_margin) * MONTHS)

print("metric,value,unit")
for option in ("paid_pilot", "manual_service"):
    print(f"{option}_margin_per_account_month,{result[option]['margin_per_account_month_rub']},RUB")
    print(f"{option}_three_month_scenario_result,{result[option]['three_month_scenario_result_rub']},RUB")
    print(f"{option}_break_even_accounts_exact,{result[option]['break_even_accounts_exact']},accounts")
print(f"same_account_count_switch_paid_vs_manual_exact,{same_account_switch:.6f},accounts")
