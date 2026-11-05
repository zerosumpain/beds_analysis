# Data contract (every fetcher MUST follow this)

Use `pipeline/common.py` (`fetch`, `fetch_csv`, `save`, `LAS`, `COMPARATORS`). Python 3 stdlib only
(no pandas). Run scripts from `pipeline/` (`cd pipeline && python3 fetch_x.py`). Raw downloads are
cached in `data/raw/` (gitignored); outputs go to `site/data/<dataset_id>.json` via `save()`.

## Dataset file = `{"meta": {...}, "rows": [...]}`

`meta` (strings unless noted) — this is the lineage record shown to users, so be accurate:
- `title`, `publisher`, `source_url` (human landing page), `api_url` (exact URL(s) fetched; list ok)
- `geography`: which levels are in rows, e.g. `"LA, region, England"` or `"LSOA21"`
- `cohort`: e.g. "16-19", "18-24", "25+ inactive", "context", "all" (string; may list several)
- `period`: latest period covered, e.g. "Jul 2024-Jun 2025", "mid-2024", "2023/24", "Census 2021"
- `frequency`: "Monthly", "Quarterly", "Annual", "Decennial", "Ad hoc"
- `next_update`: best known date/month or "Unknown"
- `access`: "API" | "CSV download" | "Excel download" | "Dashboard only"
- `quality`: one or two sentences: official/national statistics status, survey sample size, CI, revisions
- `limitations`: suppression, disclosure control, rounding, coverage gaps — be specific
- `licence`: default OGL v3 (set otherwise)
- `indicators`: LIST of `{"id","label","unit","cohort","polarity","description"}` where
  unit ∈ count|percent|rate|score|rank|decile|gbp|ratio, polarity ∈ higher_is_worse|higher_is_better|neutral.
  Indicator ids are globally unique across datasets: prefix with dataset short name, e.g. `aps_inact_rate_16_64`.

## Row (long format, one value per row)

```json
{"code":"E06000055","name":"Bedford","level":"LA","indicator":"aps_inact_rate_16_64",
 "value":21.3,"period":"Jul 2024-Jun 2025","ci":2.9,"num":null,"den":null,"breakdown":null}
```
- `level` ∈ `LA` | `region` | `country` | `LSOA` | `MSOA` | `ward` | `PCON` | `provider` | `point`
- Always include the 3 Bedfordshire LAs (`LAS`); for LA-level data ALSO include East of England
  (E12000006) and England (E92000001) comparators where the source has them, plus a synthetic
  Bedfordshire total with code `BEDS` / name `Bedfordshire (3 UAs)` / level `county` when the
  measure is a count you can sum (sum the counts; for rates recompute from summed num/den only if
  you have them, otherwise omit — NEVER average rates).
- `value` numeric or null (null for suppressed; then set `"suppressed": true`).
- Optional: `ci` (± 95% CI half-width), `num`/`den`, `breakdown` (string like "age 16-17", "female",
  "Level 3"), `series` for time series rows (use `period` per row and keep latest-period rows too).
- Time series: include up to ~5 years (or 24 months for monthly) of history in the same file, with
  the `period` field varying; set `meta.latest_period`.
- `level: "point"` rows (e.g. colleges) carry `lat`, `lon`, plus any attributes in `attrs` (object).

Keep each file < 3 MB. For LSOA data only rows for LSOAs in the three LAs (prefix the LSOA list from
`site/data/geo/lsoa.geojson` if it exists, otherwise filter by LA code via lookup).
Print a short summary at the end of each script; then `python3 build_catalogue.py`.
