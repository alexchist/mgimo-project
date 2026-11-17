#!/usr/bin/env python3
"""Count coded interview fields without interpreting prevalence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--method", required=True)
    args = parser.parse_args()

    source = Path(args.input)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = ["past_behavior", "privacy_barrier", "willingness_to_pay_tested"]
    counts = {field: dict(sorted(Counter(row[field] for row in rows).items())) for field in fields}
    result = {
        "input": args.input,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "row_count": len(rows),
        "counts": counts,
        "source_locators": [f"row:{number}" for number in range(2, len(rows) + 2)],
        "limitations": [
            "Counts describe only the four coded rows and do not estimate population prevalence.",
            "The file gives no sampling method or link to the separate 12-person convenience sample.",
        ],
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.method).write_text(
        "# Метод подсчёта кодов\n\n"
        f"Вход: `{args.input}`; SHA-256 `{result['sha256']}`.\n\n"
        "Для каждого из трёх кодовых полей посчитано точное число строк по каждому значению. "
        "Подсчёты описывают только четыре записи и не являются оценкой распространённости. "
        "Связь этих записей с отдельной удобной выборкой из 12 человек не задана.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
