#!/usr/bin/env bash
# Re-fetch every feed (clearing the raw cache), rebuild the catalogue and validate JSON.
# Usage: scripts/refresh-data.sh [--keep-cache] [--travel]
#   --travel also re-runs the OpenTripPlanner journey-time batch (slow; needs Docker).
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP=0; TRAVEL=0
for a in "$@"; do case "$a" in --keep-cache) KEEP=1 ;; --travel) TRAVEL=1 ;; esac; done
# Keep the travel cache (OSM, GTFS, OTP graph) unless travel is being re-run.
if [ "$KEEP" = 0 ]; then find data/raw -mindepth 1 -maxdepth 1 ! -name travel -exec rm -rf {} + 2>/dev/null || true; fi
cd pipeline
for f in fetch_geo.py fetch_nomis_la.py fetch_small_area.py fetch_dfe_post16.py fetch_dfe_schools.py \
         fetch_census_barriers.py fetch_context_gov.py fetch_dwp_uc.py; do
  [ -f "$f" ] || continue
  echo "== $f"; python3 "$f"
done
if [ "$TRAVEL" = 1 ] && [ -f fetch_travel.py ]; then echo "== fetch_travel.py"; python3 fetch_travel.py; fi
python3 build_catalogue.py
cd ..
for j in site/data/*.json site/data/geo/*.json; do python3 -m json.tool "$j" >/dev/null || { echo "invalid JSON: $j" >&2; exit 1; }; done
echo "refresh OK: $(ls site/data/*.json | wc -l) files"
