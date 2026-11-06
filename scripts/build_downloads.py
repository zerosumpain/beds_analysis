"""Build site/data/downloads/: one CSV per dataset, an indicator dictionary and a zip of
everything. Runs at Docker build time (see Dockerfile) so generated files never enter git."""
import csv
import io
import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent)
DATA = ROOT / "site" / "data"
OUT = DATA / "downloads"
COLS = ["code", "name", "level", "indicator", "breakdown", "period", "value", "ci", "num", "den", "suppressed", "lat", "lon", "attrs"]

README = """Bedfordshire Labour and Skills Evidence Base: data download
https://beds.strangeramblings.com/  ·  source: https://github.com/zerosumpain/beds_analysis

Every CSV in csv/ is one dataset in long format, one value per row:
  code, name, level   area code (ONS GSS, BEDS for the 3-UA Bedfordshire total, or a provider id),
                      name and level (LA, county, region, country, LSOA, MSOA, PCON, point)
  indicator           indicator id; labels, units, polarity and provenance are in indicators.csv
                      (provenance: published = as released; calculated = arithmetic by this site,
                      method given; modelled = this site's model, e.g. journey times)
  breakdown           e.g. "age 16-17"; blank for the headline value
  period, value       reference period and value (blank value = suppressed or not available)
  ci                  ± half-width of the 95% confidence interval (survey sources)
  num, den            numerator and denominator where the source publishes them
  attrs               extra attributes as JSON (points, flows)
catalogue.json holds the full lineage record for each dataset: publisher, exact URLs fetched,
retrieval time, checksum, quality and limitations. Aggregate published statistics only.
Contains public sector information licensed under the Open Government Licence v3.0; journey
times use OpenStreetMap data (ODbL). See catalogue.json for each dataset's licence.
"""


def main():
    (OUT / "csv").mkdir(parents=True, exist_ok=True)
    datasets, inds = [], []
    prov_path = DATA / "research_provenance.json"
    prov = json.loads(prov_path.read_text()) if prov_path.exists() else {"datasets": {}, "indicators": {}}
    for p in sorted(DATA.glob("*.json")):
        doc = json.loads(p.read_text())
        if not (isinstance(doc, dict) and "meta" in doc and "rows" in doc):
            continue
        m = doc["meta"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(COLS)
        for r in doc["rows"]:
            w.writerow(["" if r.get(c) is None else json.dumps(r[c]) if c == "attrs" else r[c] for c in COLS])
        (OUT / "csv" / f"{m['id']}.csv").write_text(buf.getvalue())
        datasets.append(m["id"])
        for i in m.get("indicators", []):
            pv = prov["indicators"].get(i["id"], {})
            dv = prov["datasets"].get(m["id"], {})
            inds.append({"dataset": m["id"], **{k: i.get(k, "") for k in ("id", "label", "unit", "cohort", "polarity", "description")},
                         "provenance": pv.get("class") or dv.get("class", ""), "provenance_method": pv.get("method", ""),
                         "bedfordshire_total": pv.get("beds") or (dv.get("levels") or {}).get("BEDS", "")})
    buf = io.StringIO()
    w = csv.DictWriter(buf, ["dataset", "id", "label", "unit", "cohort", "polarity", "description", "provenance", "provenance_method", "bedfordshire_total"])
    w.writeheader()
    w.writerows(inds)
    (OUT / "indicators.csv").write_text(buf.getvalue())
    with zipfile.ZipFile(OUT / "bedfordshire-evidence-base.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README)
        z.write(OUT / "indicators.csv", "indicators.csv")
        for f in ("catalogue.json", "research_sources.json", "research_provenance.json", "changes.json"):
            if (DATA / f).exists():
                z.write(DATA / f, f)
        for d in datasets:
            z.write(OUT / "csv" / f"{d}.csv", f"csv/{d}.csv")
    print(f"downloads: {len(datasets)} datasets, {len(inds)} indicators, zip {(OUT / 'bedfordshire-evidence-base.zip').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
