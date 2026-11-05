"""Collect every dataset's meta block into site/data/catalogue.json, and publish the
research files (sources and assessment) next to it for the site."""
import json
from common import OUT, ROOT

for name in ("sources", "assessment", "unit_costs", "local_hire_benchmarks"):
    src = ROOT / "research" / f"{name}.json"
    if src.exists():
        doc = json.loads(src.read_text())
        if name == "sources":  # fold in additions_*.json written by individual fetchers
            ids = {s.get("id") for s in doc}
            for extra in sorted((ROOT / "research").glob("additions_*.json")):
                for s in json.loads(extra.read_text()):
                    if s.get("id") not in ids:
                        doc.append(s)
                        ids.add(s.get("id"))
        (OUT / f"research_{name}.json").write_text(json.dumps(doc, indent=1))

metas = []
for p in sorted(OUT.glob("*.json")):
    if p.name == "catalogue.json" or p.name.startswith("research_") or p.parent.name == "geo":
        continue
    doc = json.loads(p.read_text())
    if isinstance(doc, dict) and "meta" in doc:
        metas.append(doc["meta"])
(OUT / "catalogue.json").write_text(json.dumps(metas, indent=1))
print(f"catalogue: {len(metas)} datasets")
