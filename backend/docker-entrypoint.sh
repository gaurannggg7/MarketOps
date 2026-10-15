#!/bin/sh
set -eu
# Forward-only, backward-compatible migrations run before the app starts. Downgrades are never
# run automatically (see docs/runbook.md). Set MARKETOPS_SKIP_MIGRATIONS=1 to run them separately.
# MARKETOPS_STARTUP_BOOTSTRAP=1 does both inside the app process instead (faster on tiny CPUs).
if [ "${MARKETOPS_STARTUP_BOOTSTRAP:-0}" = "1" ]; then
  MARKETOPS_SKIP_MIGRATIONS=1
  MARKETOPS_SEED_ON_START=0
fi
if [ "${MARKETOPS_SKIP_MIGRATIONS:-0}" != "1" ]; then
  alembic upgrade head
fi
# Hosts without a shell/one-off jobs (e.g. Render Free) can seed on start; the seed is
# idempotent and only re-hashes demo passwords that are set in the environment.
if [ "${MARKETOPS_SEED_ON_START:-0}" = "1" ]; then
  python -m app.seed
fi
if [ "$#" -eq 0 ]; then
  # Exactly one worker (ADR 0002). PORT is provided by platforms such as Render.
  set -- uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
    --proxy-headers --forwarded-allow-ips "*"
fi
exec "$@"
