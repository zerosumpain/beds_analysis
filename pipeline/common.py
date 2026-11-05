"""Shared helpers for the beds_analysis data pipeline.

Every fetcher writes one JSON file per dataset to site/data/<id>.json with a
`meta` block (lineage) and `rows`. build_catalogue.py assembles every meta block
into site/data/catalogue.json, which drives the lineage pages.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import pathlib
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
RAW = ROOT / "data" / "raw"
UA = "beds-analysis/0.1 (open-data workforce evidence base)"

# Bedfordshire's three unitary authorities (2023 codes) plus comparators.
LAS = {
    "E06000055": "Bedford",
    "E06000056": "Central Bedfordshire",
    "E06000032": "Luton",
}
COMPARATORS = {"E12000006": "East of England", "E92000001": "England"}
# Pre-2009 Bedfordshire county code, sometimes used by DfE / LEPs.
SITE = {"name": "Kempston Hardwick (proposed resort site)", "lat": 52.0870, "lon": -0.5160}


def fetch(url, cache_name=None, retries=3, timeout=120):
    """GET a URL (with a small on-disk cache in data/raw) and return bytes."""
    RAW.mkdir(parents=True, exist_ok=True)
    if cache_name:
        p = RAW / cache_name
        if p.exists():
            return p.read_bytes()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            if cache_name:
                (RAW / cache_name).write_bytes(body)
            return body
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


def fetch_csv(url, cache_name=None):
    text = fetch(url, cache_name).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def save(dataset_id, meta, rows, extra=None):
    """Write site/data/<id>.json. meta keys (all strings unless noted):
    title, publisher, source_url (human page), api_url (exact URL fetched),
    geography (e.g. "LA", "LSOA21"), cohort, period, frequency, next_update,
    access ("API"|"CSV download"|"Dashboard only"), quality, limitations, licence.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps(rows, sort_keys=True).encode()
    meta = dict(meta)
    meta["id"] = dataset_id
    meta["retrieved_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    meta["row_count"] = len(rows)
    meta["sha256"] = hashlib.sha256(body).hexdigest()[:16]
    meta.setdefault("licence", "Open Government Licence v3.0")
    doc = {"meta": meta, "rows": rows}
    if extra:
        doc.update(extra)
    (OUT / f"{dataset_id}.json").write_text(json.dumps(doc, separators=(",", ":")))
    print(f"saved {dataset_id}: {len(rows)} rows")
    return meta
