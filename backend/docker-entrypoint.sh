#!/bin/sh
set -eu
# Forward-only, backward-compatible migrations run before the app starts. Downgrades are never
# run automatically (see docs/runbook.md). Set MARKETOPS_SKIP_MIGRATIONS=1 to run them separately.
if [ "${MARKETOPS_SKIP_MIGRATIONS:-0}" != "1" ]; then
  alembic upgrade head
fi
exec "$@"
