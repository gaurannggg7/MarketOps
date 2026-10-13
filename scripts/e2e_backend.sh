#!/usr/bin/env bash
# Start an isolated backend for Playwright: fresh `marketops_e2e` database, migrations, seed with
# test-only passwords, short warm-up, port 8001. Invoked by frontend/playwright.config.ts.
set -euo pipefail
cd "$(dirname "$0")/../backend"
ADMIN_URL="${MARKETOPS_E2E_ADMIN_DSN:-postgresql://marketops:marketops-local-only@localhost:55432/postgres}"
DB_URL="${MARKETOPS_E2E_DATABASE_URL:-postgresql+psycopg://marketops:marketops-local-only@localhost:55432/marketops_e2e}"
.venv/bin/python - "$ADMIN_URL" <<'PY'
import sys, psycopg
with psycopg.connect(sys.argv[1], autocommit=True) as c:
    c.execute('DROP DATABASE IF EXISTS "marketops_e2e" WITH (FORCE)')
    c.execute('CREATE DATABASE "marketops_e2e"')
PY
export MARKETOPS_DATABASE_URL="$DB_URL"
export MARKETOPS_ENVIRONMENT=test
export MARKETOPS_ALLOWED_ORIGINS='["http://localhost:5174","http://127.0.0.1:5174"]'
export MARKETOPS_WARMUP_SECONDS=3
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed
exec .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001
