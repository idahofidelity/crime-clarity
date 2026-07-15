#!/usr/bin/env python3
"""
Crime Clarity — Idaho data pipeline
Pulls Arrestee Race x Ethnicity data for all 44 Idaho counties (plus statewide)
from the Idaho State Police NIBRS repository, for the current year to date.

Source: https://nibrs.isp.idaho.gov/CrimeInIdaho/Report/ArrestDrillDown
Data Elements: FBI NIBRS 49 (Race of Arrestee) / 50 (Ethnicity of Arrestee)

Usage:
    python3 pull_idaho_data.py                       # current year, Jan 1 - today
    python3 pull_idaho_data.py --start 01/01/2025 --end 12/31/2025
"""

import json
import re
import sys
import argparse
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://nibrs.isp.idaho.gov/CrimeInIdaho"
REPORT_PAGE = f"{BASE_URL}/Report/ArrestDrillDown"
DATA_ENDPOINT = f"{BASE_URL}/DrillDownReport/GetDistributionBreakdownByCategory"

ETHNICITY_KEYS = {
    "Hispanic or Latino": "hispanic",
    "Not Hispanic or Latino": "not_hispanic",
    "Unknown": "unknown",
    "Not Reported": "not_reported",
}

RACE_ORDER = ["White", "Black or African American", "American Indian or Alaska Native", "Asian", "Unknown"]


def parse_category_label(label):
    """'Hispanic or Latino (7,073)' -> 'Hispanic or Latino'"""
    return re.sub(r"\s*\(.*\)$", "", label).strip()


def parse_entity_response(raw_json):
    """
    Parse the GetDistributionBreakdownByCategory response into a clean structure.
    Zero-count ethnicity categories are OMITTED by the API entirely (confirmed
    empirically) -- so every known category defaults to 0 unless present.
    """
    data = json.loads(raw_json)
    entities = data.get("entity", [])
    result = {}

    for i, ent in enumerate(entities):
        race_name = RACE_ORDER[i] if i < len(RACE_ORDER) else ent.get("drilldown", {}).get("name", f"race_{i}")
        total = ent.get("y", 0)
        drill = ent.get("drilldown", {})
        cats = drill.get("categories", [])
        vals = drill.get("data", [])

        breakdown = {"hispanic": 0, "not_hispanic": 0, "unknown": 0, "not_reported": 0}
        for cat_label, val in zip(cats, vals):
            clean_label = parse_category_label(cat_label)
            key = ETHNICITY_KEYS.get(clean_label)
            if key:
                breakdown[key] = val
            else:
                print(f"  WARNING: unrecognized ethnicity label '{clean_label}' (raw: '{cat_label}')", file=sys.stderr)

        # Internal consistency check: parts should sum to the race total
        parts_sum = sum(breakdown.values())
        if parts_sum != total:
            print(f"  WARNING: {race_name} parts sum to {parts_sum} but total is {total}", file=sys.stderr)

        result[race_name] = {"total": total, **breakdown}

    return result


def get_county_list(page):
    """Switch report mode to County and read all county options (excludes 'ALL')."""
    page.evaluate("""() => {
        const el = document.querySelector('#NIBRSReportBy');
        el.value = 'County';
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }""")
    page.wait_for_timeout(1200)
    opts = page.eval_on_selector_all(
        "#AgencyByReportBy option",
        "els => els.map(e => [e.value, e.textContent.trim()])"
    )
    counties = []
    for val, label in opts:
        if val == "-1":
            continue
        # label format: "055 - Kootenai County" -> "Kootenai"
        name = re.sub(r"^\d+\s*-\s*", "", label)
        name = re.sub(r"\s*County$", "", name).strip()
        counties.append((val, name))
    return counties


def pull_report(page, report_ids, start_date, end_date):
    url = (
        f"{DATA_ENDPOINT}?startDate={start_date}&endDate={end_date}"
        f"&OffenseIDs=-1&ReportType=County&ReportIDs={report_ids}"
        f"&DrillDownReportIDs=&IsGroupAOffense=false"
        f"&distributionBy=Race&distributionCategoryBy=Ethnicity&ageCategory=6"
    )
    resp = page.request.get(url)
    if resp.status != 200:
        raise RuntimeError(f"HTTP {resp.status} for ReportIDs={report_ids}: {resp.text()[:300]}")
    return parse_entity_response(resp.text())


def run(start_date, end_date, out_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        page.goto(REPORT_PAGE, wait_until="networkidle", timeout=30000)

        print(f"Pulling statewide totals ({start_date} to {end_date})...", file=sys.stderr)
        statewide = pull_report(page, -1, start_date, end_date)

        counties = get_county_list(page)
        print(f"Found {len(counties)} counties. Pulling each...", file=sys.stderr)

        county_results = {}
        for report_id, name in counties:
            print(f"  {name}...", file=sys.stderr)
            county_results[name] = pull_report(page, report_id, start_date, end_date)

        ctx.close()
        browser.close()

    # Validation: sum of counties should equal statewide "All" pull, per race/field
    check_totals = {}
    for race in RACE_ORDER:
        check_totals[race] = {"total": 0, "hispanic": 0, "not_hispanic": 0, "unknown": 0, "not_reported": 0}
    for name, races in county_results.items():
        for race, vals in races.items():
            if race not in check_totals:
                check_totals[race] = {"total": 0, "hispanic": 0, "not_hispanic": 0, "unknown": 0, "not_reported": 0}
            for k in ("total", "hispanic", "not_hispanic", "unknown", "not_reported"):
                check_totals[race][k] += vals.get(k, 0)

    discrepancies = []
    for race in set(list(statewide.keys()) + list(check_totals.keys())):
        sw = statewide.get(race, {})
        ck = check_totals.get(race, {})
        for k in ("total", "hispanic", "not_hispanic", "unknown", "not_reported"):
            diff = ck.get(k, 0) - sw.get(k, 0)
            if diff != 0:
                discrepancies.append({"race": race, "field": k, "county_sum": ck.get(k, 0),
                                       "statewide": sw.get(k, 0), "diff": diff})

    output = {
        "pulled_at": date.today().isoformat(),
        "date_range": {"start": start_date, "end": end_date},
        "source": "Idaho State Police NIBRS Repository (nibrs.isp.idaho.gov)",
        "methodology": "FBI NIBRS Data Element 49 (Race of Arrestee) x Data Element 50 (Ethnicity of Arrestee)",
        "statewide": statewide,
        "counties": county_results,
        "validation": {
            "counties_pulled": len(county_results),
            "discrepancies": discrepancies,
            "reconciled": len(discrepancies) == 0,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))

    print(f"\nDone. Wrote {out_path}", file=sys.stderr)
    print(f"Counties pulled: {len(county_results)}", file=sys.stderr)
    if discrepancies:
        print(f"!! {len(discrepancies)} reconciliation discrepancies found (see validation.discrepancies) !!", file=sys.stderr)
    else:
        print("Reconciliation OK: county sums match statewide totals exactly.", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="01/01/" + str(date.today().year))
    ap.add_argument("--end", default=date.today().strftime("%m/%d/%Y"))
    ap.add_argument("--out", default="data/idaho_race_ethnicity.json")
    args = ap.parse_args()
    run(args.start, args.end, Path(args.out))
