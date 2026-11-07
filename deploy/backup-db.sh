#!/usr/bin/env bash
# Nightly Postgres backup, run ON THE SERVER (cron installed by bootstrap-server.sh, or by
# hand: `deploy/deploy.sh backup <target>`). Writes two files per run to
# /opt/qualify/backups and deletes those older than QUALIFY_BACKUP_KEEP_DAYS (default 14):
#
#   qualify-<UTC>.dump        pg_dump -Fc of the `qualify` database (schema + data)
#   globals-<UTC>.sql         pg_dumpall --roles-only (the 4 roles + their password hashes;
#                             roles are cluster-global, so pg_dump alone does not carry them)
#
# Restore: docs/despliegue-hetzner.md, "Restaurar un respaldo".
# These copies live on the SAME disk as the database, so the run ends with the off-site copy
# (deploy/backup-offsite.sh, m-24824122): both files plus the `uploads` volume, encrypted
# with age, to R2. Its failure makes this script exit non-zero AFTER the local dump is
# complete; QUALIFY_BACKUP_OFFSITE=off (cron environment) skips it.
set -euo pipefail

BACKUP_DIR=${QUALIFY_BACKUP_DIR:-/opt/qualify/backups}
KEEP_DAYS=${QUALIFY_BACKUP_KEEP_DAYS:-14}
PROJECT=${COMPOSE_PROJECT_NAME:-qualify-prod}

container=$(docker ps -q \
  --filter "label=com.docker.compose.project=$PROJECT" \
  --filter "label=com.docker.compose.service=postgres")
[[ -n "$container" ]] || { echo "backup-db: postgres container of $PROJECT is not running" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dump="$BACKUP_DIR/qualify-$stamp.dump"
globals="$BACKUP_DIR/globals-$stamp.sql"

# Write to a temp name first: a half-written dump must never look like a good one.
docker exec "$container" pg_dump -U qualify_owner -d qualify -Fc >"$dump.partial"
mv "$dump.partial" "$dump"
docker exec "$container" pg_dumpall -U qualify_owner --roles-only >"$globals.partial"
mv "$globals.partial" "$globals"
chmod 600 "$dump" "$globals"

find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'qualify-*.dump' -o -name 'globals-*.sql' \) \
  -mtime +"$KEEP_DAYS" -delete

echo "backup-db: $(du -h "$dump" | cut -f1) -> $dump"

offsite="$(dirname "${BASH_SOURCE[0]}")/backup-offsite.sh"
if [[ "${QUALIFY_BACKUP_OFFSITE:-on}" == off ]]; then
  echo "backup-db: off-site copy skipped (QUALIFY_BACKUP_OFFSITE=off)"
elif [[ ! -x "$offsite" ]]; then
  echo "backup-db: $offsite missing: NO off-site copy tonight" >&2
  exit 1
else
  "$offsite" "$dump" "$globals"
fi
