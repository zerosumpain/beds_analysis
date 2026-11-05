#!/usr/bin/env bash
# Build the image at the current commit and roll app-beds onto it (porkserv home-app lane).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "commit first: working tree is dirty" >&2; exit 1; }
SHA=$(git rev-parse --short=12 HEAD)
docker build --build-arg VERSION=$SHA -t beds-analysis:$SHA .
cp /srv/apps/beds/images.env "/srv/apps/beds/images.env.before-$SHA" 2>/dev/null || true
echo "APP_IMAGE=beds-analysis:$SHA" > /srv/apps/beds/images.env
cd /srv/apps/beds && docker compose --env-file images.env up -d --wait
curl -fsS http://127.0.0.1:5660/health && echo " deployed beds-analysis:$SHA"
