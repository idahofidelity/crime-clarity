# Crime Clarity — Idaho Data Pipeline

Automated pipeline pulling Arrestee Race x Ethnicity data (FBI NIBRS Data
Elements 49/50) for all 44 Idaho counties from the Idaho State Police's
public NIBRS repository (nibrs.isp.idaho.gov), for the Idaho Fidelity
Foundation's Crime Clarity project.

## Files
- `pull_idaho_data.py` — the pipeline. Loads the ISP report page once (for
  a session cookie), then calls the underlying data endpoint directly per
  county. Includes automatic reconciliation validation (county sums vs.
  statewide total).
- `crime-clarity.html` — the published page. Loads `data/idaho_race_ethnicity.json`
  at runtime via `fetch()` — must be served over http(s), will NOT work if
  opened directly as a `file://` (browser CORS blocks local fetch). Test
  locally with `python3 -m http.server` from this directory.
- `data/idaho_race_ethnicity.json` — latest pull output.
- `.github/workflows/pull-data.yml` — runs the pipeline monthly (3rd of the
  month, 09:00 UTC) and commits the updated data file automatically.

## Setup
```
pip install playwright
python3 -m playwright install chromium
python3 pull_idaho_data.py                 # current year to date
python3 pull_idaho_data.py --start 01/01/2025 --end 12/31/2025   # specific range
```

## Known open issue
ISP's report tool returns different statewide totals depending on whether
you query "by County" (what this pipeline uses) or "by Agency" — a
~3.6% difference on the White total alone, larger for smaller race
categories. White/Hispanic (the site's core claim) reconciles cleanly
under the County method. Emailed ISP's UCR program (iducr@isp.idaho.gov)
for clarification — pending response.
