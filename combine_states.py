#!/usr/bin/env python3
"""
Crime Clarity -- combine individual state pull files into one national
scorecard.json that the site loads. Reads every *_race_ethnicity.json
in data/ and produces a unified summary per state.
"""
import json
import glob
from pathlib import Path
from datetime import date

STATE_META = {
    "Idaho": {"lean": "Red", "size": "Small"},
    "Texas": {"lean": "Red", "size": "Large"},
    "Illinois": {"lean": "Blue", "size": "Large"},
    "California": {"lean": "Blue", "size": "Large"},
    "Pennsylvania": {"lean": "Swing", "size": "Large"},
    "Rhode Island": {"lean": "Blue", "size": "Small"},
    "South Dakota": {"lean": "Red", "size": "Small"},
}

def load_state_file(path):
    data = json.loads(Path(path).read_text())
    return data

def summarize(data):
    state = data.get("state")
    classification = data.get("classification")
    statewide = data.get("statewide", {})

    if classification == "corrects_it":
        # California-style: statewide is {race: total_int}
        white_total = statewide.get("White")
        hispanic_total = statewide.get("Hispanic")
        all_total = statewide.get("All")
        pct = None  # not applicable -- Hispanic is separate, not folded in
        return {
            "state": state,
            "classification": classification,
            "date_range": data.get("date_range", {"start": None, "end": str(data.get("year"))}),
            "pulled_at": data.get("pulled_at"),
            "white_total": white_total,
            "hispanic_total": hispanic_total,
            "hispanic_pct_of_white": None,
            "grand_total": all_total,
            "source": data.get("source"),
        }
    else:
        # SWIFT Repository style: statewide is {race: {total,hispanic,...}}
        white = statewide.get("White", {})
        white_total = white.get("total", 0)
        hispanic_in_white = white.get("hispanic", 0)
        pct = round((hispanic_in_white / white_total) * 100, 1) if white_total else None
        grand_total = sum(r.get("total", 0) for r in statewide.values())
        return {
            "state": state,
            "classification": classification,
            "date_range": data.get("date_range"),
            "pulled_at": data.get("pulled_at"),
            "white_total": white_total,
            "hispanic_total": hispanic_in_white,
            "hispanic_pct_of_white": pct,
            "grand_total": grand_total,
            "source": data.get("source"),
        }

def main():
    files = glob.glob("data/*_race_ethnicity.json")
    states = []
    for f in files:
        data = load_state_file(f)
        summary = summarize(data)
        meta = STATE_META.get(summary["state"], {"lean": "Unknown", "size": "Unknown"})
        summary["lean"] = meta["lean"]
        summary["size"] = meta["size"]
        states.append(summary)

    # Sort: hides_it states by pct descending, then corrects_it at the end
    hides = sorted([s for s in states if s["classification"] == "hides_it"],
                    key=lambda s: s["hispanic_pct_of_white"] or 0, reverse=True)
    corrects = [s for s in states if s["classification"] == "corrects_it"]

    output = {
        "generated_at": date.today().isoformat(),
        "states": hides + corrects,
        "summary": {
            "total_states": len(states),
            "hides_it_count": len(hides),
            "corrects_it_count": len(corrects),
        }
    }

    Path("data/scorecard.json").write_text(json.dumps(output, indent=2))
    print(f"Wrote data/scorecard.json with {len(states)} states")
    for s in output["states"]:
        pct_str = f"{s['hispanic_pct_of_white']}%" if s['hispanic_pct_of_white'] is not None else "N/A (separate)"
        print(f"  {s['state']} ({s['lean']}, {s['size']}) -- {s['classification']} -- {pct_str}")

if __name__ == "__main__":
    main()
