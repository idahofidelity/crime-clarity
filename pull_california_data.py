#!/usr/bin/env python3
"""
Crime Clarity -- California data pipeline

Unlike Idaho/Texas/Illinois, California's own reporting ALREADY separates
Hispanic from White as mutually exclusive categories (no "hidden in White"
problem to correct for) -- this pipeline pulls California's numbers as a
verified POSITIVE example.

Source: CA DOJ OpenJustice (openjustice.doj.ca.gov/exploration/crime-statistics/arrests)
Underlying API: data-openjustice.doj.ca.gov/filter-queries/get-cjsc-data.php
No session/auth required -- confirmed public, stateless endpoint.

Usage:
    python pull_california_data.py
    python pull_california_data.py --year 2023
"""

import json
import sys
import argparse
import urllib.request
from datetime import date
from pathlib import Path

API_URL = "https://data-openjustice.doj.ca.gov/filter-queries/get-cjsc-data.php"
RACE_CATEGORIES = ["White", "Black", "Hispanic", "Other"]


def query_race(race, year):
    data = (
        f"q=get-arrests-for-all-offenses&ipl=N&county%5B%5D=All"
        f"&stats_year_range={year}&offense_class%5B%5D=&age%5B%5D=All"
        f"&gender=All&race%5B%5D={race}"
    )
    req = urllib.request.Request(
        API_URL,
        data=data.encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read())
    row = next((r for r in rows if r.get("year") == year), None)
    if row is None:
        raise RuntimeError(f"No data returned for race={race}, year={year}")
    total = row.get("F_TOTAL", 0) + row.get("M_TOTAL", 0) + row.get("S_TOTAL", 0)
    return {"total": total, "raw": row}


def run(year, out_path):
    print(f"Pulling California arrests by race/ethnicity, {year}...", file=sys.stderr)

    results = {}
    for race in ["All"] + RACE_CATEGORIES:
        print(f"  {race}...", file=sys.stderr)
        results[race] = query_race(race, year)

    all_total = results["All"]["total"]
    parts_sum = sum(results[r]["total"] for r in RACE_CATEGORIES)
    diff = all_total - parts_sum

    output = {
        "state": "California",
        "pulled_at": date.today().isoformat(),
        "year": year,
        "source": "California DOJ OpenJustice (openjustice.doj.ca.gov)",
        "methodology": (
            "California's race/ethnicity categories (White, Black, Hispanic, Other) "
            "are mutually exclusive -- Hispanic arrestees of any race are counted "
            "only in the Hispanic category, never folded into White."
        ),
        "classification": "corrects_it",
        "statewide": {race: results[race]["total"] for race in ["All"] + RACE_CATEGORIES},
        "validation": {
            "all_total": all_total,
            "sum_of_parts": parts_sum,
            "diff": diff,
            "reconciled": diff == 0,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))

    print(f"\nDone. Wrote {out_path}", file=sys.stderr)
    if diff == 0:
        print("Reconciliation OK.", file=sys.stderr)
    else:
        print(f"!! Reconciliation mismatch: diff={diff} !!", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=date.today().year - 1)
    ap.add_argument("--out", default="data/california_race_ethnicity.json")
    args = ap.parse_args()
    run(args.year, Path(args.out))
