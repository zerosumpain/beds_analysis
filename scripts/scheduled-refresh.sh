#!/usr/bin/env bash
# Weekly unattended refresh (cron on porkserv): re-fetch every feed, refuse to publish if the
# checks fail, and when anything substantive changed commit, tag data-YYYY-MM-DD, push and deploy.
# Journey times (OpenTripPlanner) are NOT re-run here: run scripts/refresh-data.sh --travel by hand.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${HOME}/.local/state/beds-refresh.log"; mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date -Is) scheduled refresh"
if [ -n "$(git status --porcelain)" ]; then echo "working tree dirty: someone is mid-change, skipping"; exit 0; fi
restore() { git checkout -- site/data research; git clean -fdq site/data; }
if ! scripts/refresh-data.sh; then echo "FAILED: fetch"; restore; exit 1; fi
if ! out=$(cd pipeline && python3 check_data.py --record); then echo "$out"; echo "FAILED: checks, nothing published"; restore; exit 1; fi
echo "$out"
if [ "$(echo "$out" | tail -1)" = "UNCHANGED" ]; then echo "no substantive change"; restore; exit 0; fi
TAG="data-$(date +%F)"
git add -A site/data
git commit -qm "Refresh data $(date +%F)" -m "$(echo "$out" | grep -v CHANGED)"
git tag -f "$TAG"
git push -q origin HEAD:main && git push -qf origin "$TAG"
scripts/deploy.sh
echo "published $TAG"
