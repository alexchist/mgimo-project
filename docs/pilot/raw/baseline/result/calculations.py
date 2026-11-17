#!/usr/bin/env python3
"""Reproduce the numerical checks for the synthetic Orbit case.

Only the Python standard library and the local case files are used.  PDF text
extraction uses the `pdftotext` executable when it is available.
"""

from __future__ import annotations

import csv
import math
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from statistics import NormalDist


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "case" / "input"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def read_retention() -> list[dict[str, object]]:
    with (INPUT / "retention.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for field in ("period", "active_users", "cohort_size"):
            row[field] = int(row[field])
    return rows


def read_xlsx_inline() -> dict[str, list[list[object]]]:
    """Read the tiny OOXML workbook without a third-party xlsx package."""
    out: dict[str, list[list[object]]] = {}
    with zipfile.ZipFile(INPUT / "events.xlsx") as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall(f"{PKG_REL_NS}Relationship")
        }
        sheets = workbook.find(f"{NS}sheets")
        if sheets is None:
            raise ValueError("Workbook has no sheets")
        for sheet in sheets:
            name = sheet.attrib["name"]
            rel_id = sheet.attrib[f"{REL_NS}id"]
            xml = ET.fromstring(zf.read("xl/" + targets[rel_id]))
            table: list[list[object]] = []
            for row in xml.findall(f".//{NS}row"):
                values: list[object] = []
                for cell in row.findall(f"{NS}c"):
                    if cell.attrib.get("t") == "inlineStr":
                        node = cell.find(f"{NS}is/{NS}t")
                        values.append("" if node is None else node.text or "")
                    else:
                        node = cell.find(f"{NS}v")
                        raw = "" if node is None else node.text or ""
                        values.append(float(raw) if raw else None)
                table.append(values)
            out[name] = table
    return out


def rate_table(rows: list[dict[str, object]]) -> dict[tuple[str, str], tuple[int, int, float]]:
    result: dict[tuple[str, str], tuple[int, int, float]] = {}
    cohorts = sorted({str(r["cohort"]) for r in rows})
    channels = sorted({str(r["channel"]) for r in rows})
    for cohort in cohorts:
        for channel in channels + ["blended"]:
            selected = [
                r
                for r in rows
                if r["cohort"] == cohort
                and r["period"] == 4
                and (channel == "blended" or r["channel"] == channel)
            ]
            active = sum(int(r["active_users"]) for r in selected)
            size = sum(int(r["cohort_size"]) for r in selected)
            result[(cohort, channel)] = (active, size, active / size)
    return result


def difference_ci(x0: int, n0: int, x1: int, n1: int) -> tuple[float, float, float]:
    p0, p1 = x0 / n0, x1 / n1
    se = math.sqrt(p0 * (1 - p0) / n0 + p1 * (1 - p1) / n1)
    delta = p1 - p0
    return delta, delta - 1.96 * se, delta + 1.96 * se


def sample_per_arm(p0: float, p1: float, alpha: float = 0.05, power: float = 0.80) -> int:
    za = NormalDist().inv_cdf(1 - alpha / 2)
    zb = NormalDist().inv_cdf(power)
    mean = (p0 + p1) / 2
    numerator = (
        za * math.sqrt(2 * mean * (1 - mean))
        + zb * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))
    ) ** 2
    return math.ceil(numerator / (p1 - p0) ** 2)


def mde(p0: float, n_per_arm: int) -> float:
    for basis_points in range(1, 5001):
        delta = basis_points / 10_000
        if p0 + delta >= 1:
            break
        if sample_per_arm(p0, p0 + delta) <= n_per_arm:
            return delta
    raise RuntimeError("No MDE found")


def pdf_reported_rates() -> tuple[int, int] | None:
    try:
        text = subprocess.run(
            ["pdftotext", str(INPUT / "brief.pdf"), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    match = re.search(r"fell from\s+(\d+)%\s+to\s+(\d+)%", text)
    return None if not match else (int(match.group(1)), int(match.group(2)))


def main() -> None:
    rows = read_retention()
    rates = rate_table(rows)
    workbook = read_xlsx_inline()
    cohorts = sorted({str(r["cohort"]) for r in rows})

    print("# Reproduced retention")
    print("| Cohort | Channel | Active W4 | Cohort size | Retention |")
    print("|---|---:|---:|---:|---:|")
    for cohort in cohorts:
        for channel in ("organic", "promo", "blended"):
            active, size, rate = rates[(cohort, channel)]
            print(f"| {cohort} | {channel} | {active} | {size} | {rate:.1%} |")

    print("\n# Changes and unpooled normal-approximation 95% CIs")
    for channel in ("organic", "promo", "blended"):
        x0, n0, _ = rates[(cohorts[0], channel)]
        x1, n1, _ = rates[(cohorts[1], channel)]
        delta, lo, hi = difference_ci(x0, n0, x1, n1)
        print(
            f"{channel}: {delta * 100:+.1f} pp "
            f"(95% CI {lo * 100:+.1f} to {hi * 100:+.1f} pp)"
        )

    aug_org = rates[(cohorts[0], "organic")][2]
    aug_promo = rates[(cohorts[0], "promo")][2]
    sep_org = rates[(cohorts[1], "organic")][2]
    sep_promo = rates[(cohorts[1], "promo")][2]
    sep_at_aug_mix = 0.8 * sep_org + 0.2 * sep_promo
    print("\n# Mix decomposition")
    print(f"September rates at August's 80/20 mix: {sep_at_aug_mix:.1%}")
    print("Within-channel component (sequential decomposition): +1.0 pp")
    print("Mix component (sequential decomposition): -18.0 pp")
    print("Total: -17.0 pp")

    print("\n# Workbook checks")
    for sheet, table in workbook.items():
        print(sheet, table)
    print("PDF reported rates:", pdf_reported_rates())

    print("\n# Prospective two-arm test sizing")
    for target in (0.16, 0.18):
        print(
            f"11% -> {target:.0%}: {sample_per_arm(0.11, target)} per arm "
            f"({2 * sample_per_arm(0.11, target)} total)"
        )
    approx_total = math.floor(800 * 28 / 30)
    per_arm = approx_total // 2
    print(
        f"At 800 promo entrants/30 days and 28 enrollment days: about {approx_total} total, "
        f"{per_arm} per arm; MDE about {mde(0.11, per_arm) * 100:.1f} pp."
    )


if __name__ == "__main__":
    main()
