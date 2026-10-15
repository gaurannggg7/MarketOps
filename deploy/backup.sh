#!/usr/bin/env bash
# Logical backup of the production database (run on the server; suitable for a daily cron).
#   0 3 * * * /opt/marketops/deploy/backup.sh >> /var/log/marketops-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
DEST="${BACKUP_DIR:-/var/backups/marketops}"
KEEP="${BACKUP_KEEP:-7}"
mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$DEST/marketops-$STAMP.dump"
ls -1t "$DEST"/marketops-*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "$(date -u) backup ok: $DEST/marketops-$STAMP.dump"
