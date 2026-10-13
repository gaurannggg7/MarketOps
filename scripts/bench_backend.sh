#!/usr/bin/env bash
# Isolated benchmark backend: fresh `marketops_bench` DB, seed (200 instruments by default),
# 100k synthetic historical events, port 8002. Usage: scripts/bench_backend.sh [instruments]
set -euo pipefail
cd "$(dirname "$0")/../backend"
INSTRUMENTS="${1:-200}"
ADMIN_URL="${MARKETOPS_BENCH_ADMIN_DSN:-postgresql://marketops:marketops-local-only@localhost:55432/postgres}"
.venv/bin/python - "$ADMIN_URL" <<'PY'
import sys, psycopg
with psycopg.connect(sys.argv[1], autocommit=True) as c:
    c.execute('DROP DATABASE IF EXISTS "marketops_bench" WITH (FORCE)')
    c.execute('CREATE DATABASE "marketops_bench"')
PY
export MARKETOPS_DATABASE_URL="postgresql+psycopg://marketops:marketops-local-only@localhost:55432/marketops_bench"
export MARKETOPS_ALLOWED_ORIGINS="${MARKETOPS_ALLOWED_ORIGINS:-[\"http://localhost:8002\",\"http://localhost:5175\"]}"
export MARKETOPS_LOG_LEVEL=WARNING
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed --instruments "$INSTRUMENTS"
.venv/bin/python -m app.seed events --count 100000
.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from app.config import get_settings
from app.db import make_engine
async def main():
    e = make_engine(get_settings().database_url, null_pool=True)
    async with e.begin() as c:
        await c.execute(text("ANALYZE"))
    await e.dispose()
asyncio.run(main())
PY
exec .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002 --log-level warning
