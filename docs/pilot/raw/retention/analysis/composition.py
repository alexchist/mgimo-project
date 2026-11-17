#!/usr/bin/env python3
"""Reproduce channel and blended week-4 retention decomposition."""

import csv
import sys
from collections import defaultdict
from pathlib import Path


def read_week4(path: Path):
    cells = defaultdict(dict)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), start=2):
            key = (row["cohort"], row["channel"])
            cells[key][int(row["period"])] = {
                "active": int(row["active_users"]),
                "size": int(row["cohort_size"]),
                "row": row_number,
            }
    return cells


def main():
    source = Path(sys.argv[1])
    cells = read_week4(source)
    cohorts = sorted({key[0] for key in cells})
    channels = sorted({key[1] for key in cells})

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        [
            "record_type",
            "cohort",
            "channel",
            "active_week4",
            "cohort_size",
            "retention_rate",
            "channel_share",
            "source_rows",
        ]
    )
    rates = {}
    shares = {}
    for cohort in cohorts:
        total_size = sum(cells[(cohort, channel)][0]["size"] for channel in channels)
        total_active = sum(cells[(cohort, channel)][4]["active"] for channel in channels)
        for channel in channels:
            base = cells[(cohort, channel)][0]
            week4 = cells[(cohort, channel)][4]
            rate = week4["active"] / base["size"]
            share = base["size"] / total_size
            rates[(cohort, channel)] = rate
            shares[(cohort, channel)] = share
            writer.writerow(
                [
                    "channel",
                    cohort,
                    channel,
                    week4["active"],
                    base["size"],
                    f"{rate:.6f}",
                    f"{share:.6f}",
                    f"row:{base['row']};row:{week4['row']}",
                ]
            )
        writer.writerow(
            [
                "blended",
                cohort,
                "all",
                total_active,
                total_size,
                f"{total_active / total_size:.6f}",
                "1.000000",
                ";".join(
                    f"row:{cells[(cohort, channel)][0]['row']};row:{cells[(cohort, channel)][4]['row']}"
                    for channel in channels
                ),
            ]
        )

    old, new = cohorts
    old_rates_new_mix = sum(rates[(old, c)] * shares[(new, c)] for c in channels)
    new_rates_old_mix = sum(rates[(new, c)] * shares[(old, c)] for c in channels)
    writer.writerow(["counterfactual", f"{old}_rates", f"{new}_mix", "", "", f"{old_rates_new_mix:.6f}", "", "derived"])
    writer.writerow(["counterfactual", f"{new}_rates", f"{old}_mix", "", "", f"{new_rates_old_mix:.6f}", "", "derived"])


if __name__ == "__main__":
    main()
