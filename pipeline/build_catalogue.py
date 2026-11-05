"""Collect every dataset's meta block into site/data/catalogue.json, and publish the
research files (sources and assessment) next to it for the site."""
import json
import shutil
from common import OUT, ROOT

for name in ("sources", "assessment"):
    src = ROOT / "research" / f"{name}.json"
    if src.exists():
        json.loads(src.read_text())  # refuse to publish invalid JSON
        shutil.copy(src, OUT / f"research_{name}.json")

metas = []
for p in sorted(OUT.glob("*.json")):
    if p.name == "catalogue.json" or p.name.startswith("research_") or p.parent.name == "geo":
        continue
    doc = json.loads(p.read_text())
    if isinstance(doc, dict) and "meta" in doc:
        metas.append(doc["meta"])
(OUT / "catalogue.json").write_text(json.dumps(metas, indent=1))
print(f"catalogue: {len(metas)} datasets")
