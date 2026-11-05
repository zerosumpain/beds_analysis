# beds_analysis — Bedfordshire Labour & Skills Evidence Base

An open-data evidence base and business case engine for labour supply, skills and
training in Bedfordshire (Bedford, Central Bedfordshire and Luton). It supports
the skills case for the proposed resort and leisure development at Kempston Hardwick.

Live at **https://beds.strangeramblings.com** (public; it uses published aggregate
statistics only and holds no personal data).

## What it does

- **Summary**: key findings computed from the latest data, then the brief, what could
  and could not be met, lineage at a glance, risks, opportunities and the minimum dataset.
- **Labour balance**: each cohort from population → can reach a shift (journey times per
  neighbourhood) → engaged → trained → into work, against local jobs by level; competing
  sectors; local-hire benchmarks from comparable developments.
- **Area profiles**: printable profile for any LSOA, MSOA, ward, constituency or authority,
  searchable by place or postcode.
- **Map explorer**: LSOA choropleths for every small-area indicator. Layers for
  schools and colleges, GCSE attainment, Census commuting flows and constituencies.
  Catchments by distance or by journey time (public transport, cycle, car, or mixed by
  household car access) total each cohort that can reach the site. Map state is in the URL
  and every view has a table alternative.
- **Cohort pages** (16-19, 18-24, inactive 25+): every indicator compared across
  the three authorities, East of England and England. Each shows confidence
  intervals, trends and breakdowns, and can be downloaded as CSV.
- **Business case engine**: cohort sizes come from the data. Demand by phase,
  conversion rates, costs, deadweight and displacement are editable. Outputs
  include a Green Book style BCR with per-cohort fiscal values from the GMCA Unit Cost
  Database, a year-by-year profile, a tornado chart, a 1,500-run Monte Carlo range,
  side-by-side saved scenarios, shareable URLs and a CSV export.
- **Downloads and changes**: every dataset as CSV plus a zip (built at image build time),
  and a log of what changed at each weekly refresh.
- **Sources**: the researched catalogue of 45+ sources, including those not
  integrated, with access route, granularity and limitations.
- **Data lineage**: one record for each feed, with publisher, the exact URL
  fetched, retrieval time, a SHA-256, quality, limitations and the indicators
  it produces.

## Layout

| Path | Contents |
|---|---|
| `pipeline/` | One stdlib-only Python fetcher per publisher. See `pipeline/CONTRACT.md` for the data contract |
| `research/` | `sources.json` and `assessment.json`: desk research, gaps, linkage, minimum dataset |
| `site/` | Static app (GOV.UK Frontend CSS, Chart.js, Leaflet, all vendored) and `site/data/*.json` |
| `server.mjs` | Dependency-free static server with `/health` and security headers |
| `scripts/refresh-data.sh` | Re-fetch every feed, rebuild the catalogue, validate the JSON |
| `scripts/deploy.sh` | Build `beds-analysis:<sha>` and roll `app-beds` on porkserv |

## Refresh and deploy

```bash
scripts/refresh-data.sh          # clears data/raw cache (except travel) and re-fetches all feeds
scripts/refresh-data.sh --travel # also re-runs the OpenTripPlanner journey-time batch (Docker)
(cd pipeline && python3 check_data.py)   # refuses broken refreshes; prints CHANGED/UNCHANGED
git add -A && git commit -m "Refresh data"
scripts/deploy.sh                # porkserv only: /srv/apps/beds (home-app lane)
```

`scripts/scheduled-refresh.sh` runs weekly from cron on porkserv (Tuesday 07:15). It refreshes,
runs the checks, and only when something substantive changed commits, tags `data-YYYY-MM-DD`,
pushes and deploys. Log: `~/.local/state/beds-refresh.log`.

Universal Credit by conditionality (DWP Stat-Xplore) switches on once a free API key is saved to
`~/.config/beds/statxplore.key`; see `pipeline/fetch_dwp_uc.py`.

Local preview: `PORT=5661 HOST=<bind address> node server.mjs`, then open
`http://<bind address>:5661/`.

## Design notes

GOV.UK Design System patterns and the Analysis Function colour palette are used.
The GOV.UK crown and the GDS Transport font are not, because this is not a GOV.UK
service. Charts show 95% confidence intervals for survey data. Suppressed cells
stay empty and are never imputed. Bedfordshire totals are created only by summing
counts; rates are never averaged.
