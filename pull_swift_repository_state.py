#!/usr/bin/env python3
"""
Crime Clarity -- generalized SWIFT Repository pipeline

Several states run their public NIBRS arrest-reporting portal on the same
"SWIFT Repository" platform (Optimum Technology Inc.), confirmed so far for:
    - Idaho    (nibrs.isp.idaho.gov, path prefix /CrimeInIdaho)
    - Texas    (txucr.nibrs.com)
    - Illinois (ilucr.nibrs.com)

These sites share identical URL paths, form fields, and API structure --
this script works against any of them by domain alone. Race category names
and counts are read dynamically from each response (not hardcoded), since
different states expose different numbers of race categories (Idaho has 5,
Texas/Illinois have 6, including Native Hawaiian/Pacific Islander).

Usage:
    python pull_swift_repository_state.py --domain nibrs.isp.idaho.gov --path-prefix /CrimeInIdaho --state Idaho --out data/idaho.json
    python pull_swift_repository_state.py --domain txucr.nibrs.com --state Texas --out data/texas.json
    python pull_swift_repository_state.py --domain ilucr.nibrs.com --state Illinois --out data/illinois.json
"""

import json
import re
import sys
import argparse
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

ETHNICITY_KEYS = {
    "Hispanic or Latino": "hispanic",
    "Not Hispanic or Latino": "not_hispanic",
    "Unknown": "unknown",
    "Not Reported": "not_reported",
}


def parse_category_label(label):
    return re.sub(r"\s*\(.*\)$", "", label).strip()


def parse_entity_response(raw_json):
    data = json.loads(raw_json)
    entities = data.get("entity", [])
    result = {}

    for ent in entities:
        drill = ent.get("drilldown", {})
        race_name = drill.get("name")
        if not race_name:
            continue
        total = ent.get("y", 0)
        cats = drill.get("categories", [])
        vals = drill.get("data", [])

        breakdown = {"hispanic": 0, "not_hispanic": 0, "unknown": 0, "not_reported": 0}
        for cat_label, val in zip(cats, vals):
            clean_label = parse_category_label(cat_label)
            key = ETHNICITY_KEYS.get(clean_label)
            if key:
                breakdown[key] = val
            else:
                print(f"  WARNING: unrecognized ethnicity label '{clean_label}'", file=sys.stderr)

        parts_sum = sum(breakdown.values())
        if parts_sum != total:
            print(f"  WARNING: {race_name} parts sum to {parts_sum} but total is {total}", file=sys.stderr)

        result[race_name] = {"total": total, **breakdown}

    return result


def get_county_list(page):
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
        name = re.sub(r"^\d+\s*-\s*", "", label)
        name = re.sub(r"\s*County$", "", name).strip()
        counties.append((val, name))
    return counties


def pull_report(page, base_url, report_ids, start_date, end_date, path_prefix=""):
    url = (
        f"https://{base_url}{path_prefix}/DrillDownReport/GetDistributionBreakdownByCategory"
        f"?startDate={start_date}&endDate={end_date}"
        f"&OffenseIDs=-1&ReportType=County&ReportIDs={report_ids}"
        f"&DrillDownReportIDs=&IsGroupAOffense=false"
        f"&distributionBy=Race&distributionCategoryBy=Ethnicity&ageCategory=6"
    )
    resp = page.request.get(url)
    if resp.status != 200:
        raise RuntimeError(f"HTTP {resp.status} for ReportIDs={report_ids}: {resp.text()[:300]}")
    return parse_entity_response(resp.text())


def run(domain, state_name, start_date, end_date, out_path, pull_counties=True, path_prefix=""):
    report_page = f"https://{domain}{path_prefix}/Report/ArrestDrillDown"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        page.goto(report_page, wait_until="networkidle", timeout=30000)

        print(f"[{state_name}] Pulling statewide totals ({start_date} to {end_date})...", file=sys.stderr)
        statewide = pull_report(page, domain, -1, start_date, end_date, path_prefix)

        county_results = {}
        if pull_counties:
            counties = get_county_list(page)
            print(f"[{state_name}] Found {len(counties)} counties. Pulling each...", file=sys.stderr)
            for report_id, name in counties:
                print(f"  {name}...", file=sys.stderr)
                county_results[name] = pull_report(page, domain, report_id, start_date, end_date, path_prefix)

        ctx.close()
        browser.close()

    discrepancies = []
    if pull_counties:
        all_races = set(statewide.keys())
        for races in county_results.values():
            all_races |= set(races.keys())

        check_totals = {r: {"total": 0, "hispanic": 0, "not_hispanic": 0, "unknown": 0, "not_reported": 0} for r in all_races}
        for races in county_results.values():
            for race, vals in races.items():
                for k in ("total", "hispanic", "not_hispanic", "unknown", "not_reported"):
                    check_totals[race][k] += vals.get(k, 0)

        for race in all_races:
            sw = statewide.get(race, {})
            ck = check_totals.get(race, {})
            for k in ("total", "hispanic", "not_hispanic", "unknown", "not_reported"):
                diff = ck.get(k, 0) - sw.get(k, 0)
                if diff != 0:
                    discrepancies.append({"race": race, "field": k, "county_sum": ck.get(k, 0),
                                           "statewide": sw.get(k, 0), "diff": diff})

    output = {
        "state": state_name,
        "domain": domain,
        "pulled_at": date.today().isoformat(),
        "date_range": {"start": start_date, "end": end_date},
        "source": f"{state_name} NIBRS Repository ({domain})",
        "methodology": "FBI NIBRS Data Element 49 (Race of Arrestee) x Data Element 50 (Ethnicity of Arrestee)",
        "classification": "hides_it",
        "statewide": statewide,
        "counties": county_results,
        "validation": {
            "counties_pulled": len(county_results),
            "discrepancies": discrepancies,
            "reconciled": len(discrepancies) == 0,
        } if pull_counties else {"skipped": True},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))

    print(f"\n[{state_name}] Done. Wrote {out_path}", file=sys.stderr)
    if pull_counties:
        print(f"[{state_name}] Counties pulled: {len(county_results)}", file=sys.stderr)
        if discrepancies:
            print(f"[{state_name}] !! {len(discrepancies)} reconciliation discrepancies found !!", file=sys.stderr)
        else:
            print(f"[{state_name}] Reconciliation OK.", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--start", default="01/01/" + str(date.today().year))
    ap.add_argument("--end", default=date.today().strftime("%m/%d/%Y"))
    ap.add_argument("--out", default="data/state_race_ethnicity.json")
    ap.add_argument("--no-counties", action="store_true")
    ap.add_argument("--path-prefix", default="")
    args = ap.parse_args()
    run(args.domain, args.state, args.start, args.end, Path(args.out),
        pull_counties=not args.no_counties, path_prefix=args.path_prefix)
