#!/usr/bin/env python3
"""Reproduce contribution calculations from the synthetic XLSX without third-party packages."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def cell_value(cell: ET.Element) -> str:
    inline = cell.find("x:is/x:t", NS)
    if inline is not None:
        return inline.text or ""
    value = cell.find("x:v", NS)
    return "" if value is None else value.text or ""


def read_sheet(archive: zipfile.ZipFile, member: str) -> list[list[str]]:
    root = ET.fromstring(archive.read(member))
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", NS):
        rows.append([cell_value(cell) for cell in row.findall("x:c", NS)])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--method", required=True)
    args = parser.parse_args()

    source = Path(args.input).resolve()
    with zipfile.ZipFile(source) as archive:
        scenario_rows = read_sheet(archive, "xl/worksheets/sheet1.xml")
        assumption_rows = read_sheet(archive, "xl/worksheets/sheet2.xml")

    header = scenario_rows[0]
    scenarios = []
    for row_number, values in enumerate(scenario_rows[1:], start=2):
        record = dict(zip(header, values, strict=True))
        price = int(record["monthly_price_rub"])
        variable = int(record["variable_cost_rub"])
        support = int(record["support_cost_rub"])
        users = int(record["users"])
        contribution_per_user = price - variable - support
        scenarios.append(
            {
                **record,
                "contribution_per_user_rub_month": contribution_per_user,
                "contribution_total_rub_month": contribution_per_user * users,
                "source_locator": f"scenario!A{row_number}:E{row_number}",
            }
        )

    assumptions = [dict(zip(assumption_rows[0], row, strict=True)) for row in assumption_rows[1:]]
    result = {
        "input": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "unit": "RUB/month",
        "scenarios": scenarios,
        "assumptions": assumptions,
        "limitations": [
            "users is treated as paying active users; the source does not define this field.",
            "Contribution excludes acquisition, fixed product costs, taxes, refunds and payment fees.",
            "Paid conversion and monthly churn are unknown, so this is not LTV or a forecast.",
        ],
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.method).write_text(
        "# Метод расчёта экономики\n\n"
        f"Вход: `{source}`; SHA-256 `{result['sha256']}`.\n\n"
        "Для каждой строки листа `scenario`: `contribution_per_user = monthly_price_rub - "
        "variable_cost_rub - support_cost_rub`; `contribution_total = contribution_per_user × users`. "
        "Вычисления целочисленные, единица — рубли в месяц. Поле `users` условно трактуется как платящие "
        "активные пользователи; источник этого не определяет. Это вклад до фиксированных затрат, привлечения, "
        "налогов, возвратов и платёжных комиссий, а не прибыль, LTV или прогноз.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
