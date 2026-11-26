#!/usr/bin/env bash
# Off-site copy of tonight's backup to R2, encrypted with age (m-24824122). Run ON THE SERVER
# by deploy/backup-db.sh right after the local pg_dump, so it rides the existing nightly cron
# (03:15 UTC) and `just deploy-backup`; never on its own schedule.
#
#   backup-offsite.sh <qualify-UTC.dump> <globals-UTC.sql>
#
# Uploads to backups/<YYYYMMDDTHHMMSSZ>/ (a new snapshot per run, never an overwrite) of the
# app's R2 bucket, outside the tenants' t/ space:
#   qualify.dump.age   the pg_dump -Fc just written
#   globals.sql.age    the roles dump just written
#   uploads.tar.age    a tar of the `uploads` volume (catalog photos/clips, generator uploads,
#                      brand documents), read through the api container's own mount
#   MANIFEST.json      written last: a snapshot without it is incomplete
# then prunes to 14 daily + 8 weekly (deploy/offsite_backup.py has the rule).
#
# Everything runs through `docker exec` in the api container of THIS compose project (label
# filter), which already holds the R2 credentials, the uploads mount and `age`: the script
# never lists, mounts or reads another project's containers or volumes (Pedidos).
#
# Fails loudly: non-zero exit, a FAILED line in backup.log and one message to the team channel
# (QUALIFY_SUPPORT_WEBHOOK_URL). On success it touches $BACKUP_DIR/offsite.ok, which
# deploy/healthcheck.sh reports. The local dump is already safe on disk before this starts.
set -Eeuo pipefail

PROJECT=${COMPOSE_PROJECT_NAME:-qualify-prod}
BACKUP_DIR=${QUALIFY_BACKUP_DIR:-/opt/qualify/backups}
SERVICE=${QUALIFY_BACKUP_EXEC_SERVICE:-api}
UPLOADS_DIR=/data/uploaded_files
TOOL=/app/deploy/offsite_backup.py

dump=${1:?usage: backup-offsite.sh <dump> <globals>}
globals=${2:?usage: backup-offsite.sh <dump> <globals>}
snap=$(date -u +%Y%m%dT%H%M%SZ)
stage="start"
api=""

log() { echo "backup-offsite: $*"; }

tool() { docker exec -i "$api" python "$TOOL" "$@"; }

fail() {
  local code=$?
  log "FAILED at '$stage' (exit $code); the local dump in $BACKUP_DIR is intact" >&2
  if [[ -n "$api" ]]; then
    tool alert "Respaldo fuera del servidor FALLÓ en '$stage' ($PROJECT, $snap). La copia local de Postgres está bien. Qué hacer: docs/respaldos-fuera-del-servidor.md §4. Registro: $BACKUP_DIR/backup.log." >&2 || true
  fi
  exit "$code"
}
trap fail ERR

for file in "$dump" "$globals"; do
  [[ -s "$file" ]] || { stage="input"; log "missing or empty $file" >&2; false; }
done

stage="locate $SERVICE"
api=$(docker ps -q \
  --filter "label=com.docker.compose.project=$PROJECT" \
  --filter "label=com.docker.compose.service=$SERVICE")
if [[ -z "$api" || "$api" == *$'\n'* ]]; then
  log "expected one running $SERVICE container of $PROJECT, found: ${api:-none}" >&2
  api=""
  false
fi

stage="check"
tool check

stage="put qualify.dump"
tool put "$snap" qualify.dump <"$dump"
stage="put globals.sql"
tool put "$snap" globals.sql <"$globals"

# GNU tar exits 1 when a file changed while it was read (an upload in flight): the archive is
# still valid, so 1 is a warning, anything else a failure. `tool put` must exit 0. The ERR
# trap fires on a failed pipeline even under `set +e`, so it is lifted around this one and
# the statuses are judged by hand below.
stage="put uploads.tar"
trap - ERR
set +e +o pipefail
docker exec "$api" tar -C "$UPLOADS_DIR" -cf - . | tool put "$snap" uploads.tar
status=("${PIPESTATUS[@]}")
set -e -o pipefail
trap fail ERR
if (( status[0] > 1 )); then log "tar of $UPLOADS_DIR exited ${status[0]}" >&2; false; fi
(( status[0] == 1 )) && log "warning: a file changed while the uploads were archived"
if (( status[1] != 0 )); then (exit "${status[1]}"); fi

stage="finish"
tool finish "$snap" qualify.dump globals.sql uploads.tar

touch "$BACKUP_DIR/offsite.ok"
log "ok -> backups/$snap/"
