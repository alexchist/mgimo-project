#!/usr/bin/env python3
"""Reproduce revised three-month economics and decision thresholds."""

import csv
import sys
from decimal import Decimal


MONTHS = Decimal("3")


def number(value: Decimal) -> str:
    return f"{value:.6f}"


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
    total_fixed = setup + fixed * MONTHS
    scenario_result = margin * accounts * MONTHS - total_fixed
    break_even_accounts = total_fixed / (margin * MONTHS)
    result[option] = {
        "price": price,
        "variable": variable,
        "margin": margin,
        "total_fixed": total_fixed,
        "accounts": accounts,
        "scenario_result": scenario_result,
        "break_even_accounts": break_even_accounts,
    }

paid = result["paid_pilot"]
manual = result["manual_service"]
margin_delta = paid["margin"] - manual["margin"]
fixed_delta = paid["total_fixed"] - manual["total_fixed"]

if margin_delta <= 0 and fixed_delta >= 0:
    same_account_switch = "none_nonnegative_paid_is_dominated"
else:
    same_account_switch = number(fixed_delta / (margin_delta * MONTHS))

paid_required_margin_at_scenario = paid["total_fixed"] / (paid["accounts"] * MONTHS)
paid_price_break_even_at_scenario = paid["variable"] + paid_required_margin_at_scenario
paid_variable_max_break_even_at_scenario = paid["price"] - paid_required_margin_at_scenario

manual_at_paid_accounts = (
    manual["margin"] * paid["accounts"] * MONTHS - manual["total_fixed"]
)
paid_required_margin_to_match_manual = (
    manual_at_paid_accounts + paid["total_fixed"]
) / (paid["accounts"] * MONTHS)
paid_price_to_match_manual = paid["variable"] + paid_required_margin_to_match_manual
paid_variable_max_to_match_manual = paid["price"] - paid_required_margin_to_match_manual

print("metric,value,unit")
for option in ("paid_pilot", "manual_service"):
    print(f"{option}_margin_per_account_month,{result[option]['margin']},RUB")
    print(f"{option}_three_month_scenario_result,{result[option]['scenario_result']},RUB")
    print(f"{option}_break_even_accounts_exact,{number(result[option]['break_even_accounts'])},accounts")
print(f"same_account_count_switch_paid_vs_manual,{same_account_switch},accounts")
print(f"paid_price_break_even_at_30_accounts_exact,{number(paid_price_break_even_at_scenario)},RUB_per_account_month")
print(f"paid_variable_cost_max_break_even_at_30_accounts_exact,{number(paid_variable_max_break_even_at_scenario)},RUB_per_account_month")
print(f"paid_price_to_match_manual_at_30_accounts_exact,{number(paid_price_to_match_manual)},RUB_per_account_month")
print(f"paid_variable_cost_max_to_match_manual_at_30_accounts_exact,{number(paid_variable_max_to_match_manual)},RUB_per_account_month")
