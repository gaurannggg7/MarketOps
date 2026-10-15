#!/usr/bin/env bash
# Deploy or update a specific git revision on the server (run on the server).
#   deploy/deploy.sh <git-ref>      e.g. deploy/deploy.sh v1.1.0
# Builds images tagged with MARKETOPS_VERSION, runs forward-only migrations (container
# entrypoint), seeds idempotently, and waits for health checks.
set -euo pipefail
REF="${1:?usage: deploy.sh <git ref>}"
cd "$(dirname "$0")/.."
git fetch --tags origin
git checkout --detach "$REF"
cd deploy
DC="docker compose -f docker-compose.prod.yml --env-file .env.production"
$DC build
$DC up -d --wait db
# Migrate + seed before the backend serves, so the runtime starts with the full catalog.
$DC run --rm --no-deps backend python -m app.seed
$DC up -d --wait
$DC ps
echo "deployed $(git rev-parse --short HEAD)"
