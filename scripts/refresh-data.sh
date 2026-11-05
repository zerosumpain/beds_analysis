#!/usr/bin/env bash
# Re-fetch every feed (clearing the raw cache), rebuild the catalogue and validate JSON.
# Usage: scripts/refresh-data.sh [--keep-cache]
set -euo pipefail
cd "$(dirname "$0")/.."
[ "${1:-}" = "--keep-cache" ] || rm -rf data/raw
cd pipeline
for f in fetch_geo.py fetch_nomis_la.py fetch_small_area.py fetch_dfe_post16.py fetch_dfe_schools.py; do
  [ -f "$f" ] || continue
  echo "== $f"; python3 "$f"
done
python3 build_catalogue.py
cd ..
for j in site/data/*.json site/data/geo/*.json; do python3 -m json.tool "$j" >/dev/null || { echo "invalid JSON: $j" >&2; exit 1; }; done
echo "refresh OK: $(ls site/data/*.json | wc -l) files"
