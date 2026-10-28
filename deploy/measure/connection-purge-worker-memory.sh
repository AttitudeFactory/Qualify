#!/usr/bin/env bash
# Measure the real connection-purge worker under its production memory cap (m-24789547).
#
# Usage: deploy/measure/connection-purge-worker-memory.sh [IMAGE]
# IMAGE defaults to qualify-memtest:deps; build with:
#   docker build -f deploy/Dockerfile --target deps -t qualify-memtest:deps .
#
# Creates only a unique internal network and throwaway PostgreSQL container. The measured
# process has only the dedicated purge DSN, talks to a local synthetic R2 server, and has no
# route to external services. Existing containers are never stopped or removed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
  HOST_ROOT="$(cygpath -m "$ROOT")"
  export MSYS_NO_PATHCONV=1
else
  HOST_ROOT="$ROOT"
fi
IMAGE="${1:-qualify-memtest:deps}"
P="qualify-connection-purge-memtest-$$"
NET="$P-net"
LIMIT="${MEM_LIMIT:-$(awk '/^  connection-purge-worker:/{f=1} f&&/mem_limit:/{print $2; exit}' \
  "$ROOT/deploy/docker-compose.prod.yml")}"
PW=measure-only-password-0000

if [[ -z "${LIMIT// /}" ]]; then
  LIMIT="$(awk '/^  connection-purge:/{f=1} f&&/mem_limit:/{print $2; exit}' \
    "$ROOT/deploy/docker-compose.prod.yml")"
fi
if [[ -z "$LIMIT" ]]; then
  echo "could not read connection-purge memory cap from production compose" >&2
  exit 1
fi

cleanup() {
  docker rm -f "$P-pg" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create --internal "$NET" >/dev/null
docker run -d --name "$P-pg" --network "$NET" --network-alias postgres \
  -e POSTGRES_DB=qualify -e POSTGRES_USER=qualify_owner -e POSTGRES_PASSWORD="$PW" \
  postgres:16 >/dev/null

ready=0
for ((attempt=0; attempt<60; attempt++)); do
  if docker exec "$P-pg" pg_isready -U qualify_owner -d qualify >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ $ready == 1 ]] || { echo "throwaway PostgreSQL did not become ready" >&2; exit 1; }

dsn() { echo "postgresql+psycopg://$1:$PW@postgres:5432/qualify"; }
COMMON=(
  -e QUALIFY_DEPLOY_ENV=production
  -e PYTHONPATH=/app/packages/models/src
  -v "$HOST_ROOT/packages:/app/packages:ro"
  -v "$HOST_ROOT/migrations:/app/migrations:ro"
  -v "$HOST_ROOT/deploy/bootstrap_db_roles.py:/app/deploy/bootstrap_db_roles.py:ro"
  -v "$HOST_ROOT/deploy/measure:/measure:ro"
)

echo "==> migrate and bootstrap isolated DB roles ($IMAGE)"
docker run --rm --network "$NET" "${COMMON[@]}" \
  -e QUALIFY_MIGRATION_DSN="$(dsn qualify_owner)" \
  -e QUALIFY_APP_DSN="$(dsn qualify_app)" -e QUALIFY_ADMIN_DSN="$(dsn qualify_admin)" \
  -e QUALIFY_CREDENTIAL_DSN="$(dsn qualify_credential)" \
  -e QUALIFY_CONNECTION_PURGE_DSN="$(dsn qualify_connection_purge)" \
  -e QUALIFY_DB_APP_PASSWORD="$PW" -e QUALIFY_DB_ADMIN_PASSWORD="$PW" \
  -e QUALIFY_DB_CREDENTIAL_PASSWORD="$PW" -e QUALIFY_DB_CONNECTION_PURGE_PASSWORD="$PW" \
  -e QUALIFY_DB_WEBHOOK_PASSWORD="$PW" \
  -e QUALIFY_DB_WEBHOOK_WORKER_PASSWORD="$PW" \
  "$IMAGE" sh -c 'alembic upgrade head >/dev/null && python deploy/bootstrap_db_roles.py'

echo "==> seed one synthetic manual request through app/admin doors"
FIXTURE="$(docker run --rm --network "$NET" "${COMMON[@]}" \
  -e QUALIFY_MIGRATION_DSN="$(dsn qualify_owner)" \
  -e QUALIFY_APP_DSN="$(dsn qualify_app)" -e QUALIFY_ADMIN_DSN="$(dsn qualify_admin)" \
  -e QUALIFY_CONNECTION_PURGE_DSN="$(dsn qualify_connection_purge)" \
  -e QUALIFY_WEBHOOK_WORKER_DSN="$(dsn qualify_webhook_worker)" \
  -e QUALIFY_DB_APP_PASSWORD="$PW" -e QUALIFY_DB_ADMIN_PASSWORD="$PW" \
  -e QUALIFY_DB_CREDENTIAL_PASSWORD="$PW" -e QUALIFY_DB_CONNECTION_PURGE_PASSWORD="$PW" \
  -e QUALIFY_DB_WEBHOOK_PASSWORD="$PW" \
  -e QUALIFY_DB_WEBHOOK_WORKER_PASSWORD="$PW" \
  "$IMAGE" python /measure/connection-purge-worker-memory.py --seed)"
read -r TENANT CONNECTION <<<"$FIXTURE"
[[ -n "$TENANT" && -n "$CONNECTION" ]] || { echo "fixture seed returned no tenant/connection ids" >&2; exit 1; }

echo "==> measure: mem_limit=$LIMIT memswap_limit=$LIMIT; no-egress DB + local fake R2"
set +e
docker run --rm --network "$NET" --memory "$LIMIT" --memory-swap "$LIMIT" "${COMMON[@]}" \
  -e QUALIFY_CONNECTION_PURGE_DSN="$(dsn qualify_connection_purge)" \
  "$IMAGE" python /measure/connection-purge-worker-memory.py --tenant "$TENANT" --connection "$CONNECTION"
status=$?
set -e
[[ $status -eq 137 ]] && echo "==> OOM-killed at mem_limit=$LIMIT (exit 137)"
exit "$status"
