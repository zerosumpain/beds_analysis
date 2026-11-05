# beds_analysis — Bedfordshire Labour & Skills Evidence Base

An open-data evidence base and business case engine for labour supply, skills and
training in Bedfordshire (Bedford, Central Bedfordshire and Luton). It supports
the skills case for the proposed resort and leisure development at Kempston Hardwick.

Live at **https://beds.strangeramblings.com** (public; it uses published aggregate
statistics only and holds no personal data).

## What it does

- **Summary**: the brief, what could and could not be met, lineage at a glance,
  risks and issues, opportunities and the recommended minimum dataset.
- **Map explorer**: LSOA choropleths for every small-area indicator. Layers for
  schools and colleges, GCSE attainment, Census commuting flows and constituencies.
  Distance rings and a catchment calculator total each cohort within a radius of the site.
- **Cohort pages** (16-19, 18-24, inactive 25+): every indicator compared across
  the three authorities, East of England and England. Each shows confidence
  intervals, trends and breakdowns, and can be downloaded as CSV.
- **Business case engine**: cohort sizes come from the data. Demand by phase,
  conversion rates, costs, deadweight and displacement are editable. Outputs
  include a Green Book style BCR, a tornado sensitivity chart, shareable scenario
  URLs and a CSV export.
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
scripts/refresh-data.sh          # clears data/raw cache and re-fetches all feeds
git add -A && git commit -m "Refresh data"
scripts/deploy.sh                # porkserv only: /srv/apps/beds (home-app lane)
```

Local preview: `PORT=5661 HOST=<bind address> node server.mjs`, then open
`http://<bind address>:5661/`.

## Design notes

GOV.UK Design System patterns and the Analysis Function colour palette are used.
The GOV.UK crown and the GDS Transport font are not, because this is not a GOV.UK
service. Charts show 95% confidence intervals for survey data. Suppressed cells
stay empty and are never imputed. Bedfordshire totals are created only by summing
counts; rates are never averaged.
