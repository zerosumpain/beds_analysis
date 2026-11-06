"""Compare freshly fetched site/data against the last commit before anything is published.

Fails (exit 1) when a refresh looks broken: a dataset vanished, lost >30% of its rows or
an indicator, or its latest period went backwards. Otherwise prints CHANGED or UNCHANGED
(timestamps alone do not count) and, with --record, prepends an entry to
site/data/changes.json describing what moved.
"""
import datetime as dt
import json
import re
import subprocess
import sys

from common import OUT, ROOT

MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def period_key(p):
    p = str(p or "")
    ay = re.search(r"(20\d\d)/(\d\d)", p)
    if ay:
        return int(ay.group(1)) * 100 + 13
    years = re.findall(r"(?:19|20)\d\d", p)
    y = int(years[-1]) if years else 0
    low, m = p.lower(), 0
    for i, mm in enumerate(MONTHS):
        k = low.rfind(mm)
        if k >= 0 and k > len(low) - 12:
            m = max(m, i + 1)
    return y * 100 + m


def head_meta(name):
    try:
        txt = subprocess.run(["git", "show", f"HEAD:site/data/{name}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None
    doc = json.loads(txt)
    return doc.get("meta") if isinstance(doc, dict) else None


def main():
    record = "--record" in sys.argv
    errors, changes = [], []
    now = {}
    for p in sorted(OUT.glob("*.json")):
        doc = json.loads(p.read_text())
        if isinstance(doc, dict) and "meta" in doc and "rows" in doc:
            now[p.name] = doc["meta"]
    tracked = subprocess.run(["git", "ls-files", "site/data/*.json"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    for path in tracked:
        name = path.split("/")[-1]
        old = head_meta(name)
        if not old or "row_count" not in old:
            continue
        new = now.get(name)
        if not new:
            errors.append(f"{name}: dataset missing after refresh")
            continue
        lost = {i["id"] for i in old.get("indicators", [])} - {i["id"] for i in new.get("indicators", [])}
        if lost:
            errors.append(f"{name}: indicators disappeared: {', '.join(sorted(lost))}")
        if new["row_count"] < 0.7 * old["row_count"]:
            errors.append(f"{name}: rows fell from {old['row_count']} to {new['row_count']}")
        op, np_ = old.get("latest_period") or old.get("period"), new.get("latest_period") or new.get("period")
        if period_key(np_) < period_key(op):
            errors.append(f"{name}: latest period went backwards ({op} -> {np_})")
        if new.get("sha256") != old.get("sha256"):
            kind = "new period" if np_ != op else "revised"
            changes.append({"id": new["id"], "title": new.get("title"), "change": kind, "from_period": op, "to_period": np_,
                            "rows_before": old["row_count"], "rows_after": new["row_count"]})
    for name, new in now.items():
        if name not in {t.split("/")[-1] for t in tracked}:
            changes.append({"id": new["id"], "title": new.get("title"), "change": "new dataset", "to_period": new.get("latest_period") or new.get("period"), "rows_after": new["row_count"]})
    pp = OUT / "research_provenance.json"
    known = set(json.loads(pp.read_text()).get("indicators", {})) if pp.exists() else set()
    for name, new in now.items():
        missing = [i["id"] for i in new.get("indicators", []) if i["id"] not in known]
        if missing:  # shown on the site as "not yet classified"; add them to research/provenance_*.json
            print(f"WARNING {name}: no provenance recorded for {', '.join(missing)}")
    for e in errors:
        print("ERROR", e)
    if errors:
        sys.exit(1)
    for c in changes:
        print(f"  {c['change']:12} {c['id']}: {c.get('from_period') or ''} -> {c.get('to_period')}")
    print("CHANGED" if changes else "UNCHANGED")
    if record and changes:
        path = OUT / "changes.json"
        log = json.loads(path.read_text()) if path.exists() else []
        log.insert(0, {"date": dt.date.today().isoformat(), "tag": f"data-{dt.date.today().isoformat()}", "datasets": changes})
        path.write_text(json.dumps(log[:100], indent=1))


if __name__ == "__main__":
    main()
