#!/usr/bin/env bash
# Restore a pg_dump custom-format file into the production database. DESTRUCTIVE for the
# objects it restores (--clean). Stops the backend first so no writes race the restore.
#   deploy/restore.sh /var/backups/marketops/marketops-<stamp>.dump
set -euo pipefail
cd "$(dirname "$0")"
FILE="${1:?usage: restore.sh <dump file>}"
read -r -p "Restore $FILE over the live database? Type RESTORE: " ok
[ "$ok" = "RESTORE" ] || { echo aborted; exit 1; }
DC="docker compose -f docker-compose.prod.yml --env-file .env.production"
$DC stop backend
$DC exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$FILE"
$DC start backend
echo "restored; check: curl -s https://\$MARKETOPS_DOMAIN/api/v1/health/ready"
