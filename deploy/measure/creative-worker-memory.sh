#!/usr/bin/env bash
# Current-source creative-worker memory under its production cap (512 MiB).
# Uses production deps image + read-only current packages/migrations, synthetic vendor
# boundaries and a throwaway PostgreSQL/Redis on --internal network (no route out).
# No host environment file/credentials/ports are passed. Exit137=OOM; exit1=>=95% cap.
# Usage: deploy/measure/creative-worker-memory.sh [IMAGE] [-- --download-mib 40]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${1:-qualify-memtest:deps}"
shift || true
[[ "${1:-}" == "--" ]] && shift
P=qualify-creative-memtest-$$
NET="$P-net"
LIMIT="${MEM_LIMIT:-$(awk '/^  creative-worker:/{f=1} f&&/mem_limit:/{print $2; exit}' \
  "$ROOT/deploy/docker-compose.prod.yml")}"
PW=measure-only-password-0000   # throwaway database, never a real one

cleanup() {
  docker rm -f "$P-pg" "$P-redis" "$P-r2" "$P-worker" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker network create --internal "$NET" >/dev/null
docker run -d --name "$P-pg" --network "$NET" --network-alias postgres \
  -e POSTGRES_DB=qualify -e POSTGRES_USER=qualify_owner -e POSTGRES_PASSWORD="$PW" \
  pgvector/pgvector:pg16 >/dev/null
docker run -d --name "$P-redis" --network "$NET" --network-alias redis redis:7-alpine >/dev/null
ready=0
for ((attempt=0; attempt<60; attempt++)); do
  if docker exec "$P-pg" pg_isready -U qualify_owner -d qualify >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ $ready == 1 ]] || { echo "throwaway PostgreSQL did not become ready" >&2; exit 1; }
sleep 2

dsn() { echo "postgresql+psycopg://$1:$PW@postgres:5432/qualify"; }
ENV=(
  -e QUALIFY_APP_DSN="$(dsn qualify_app)"
  -e QUALIFY_ADMIN_DSN="$(dsn qualify_admin)"
  -e QUALIFY_CREDENTIAL_DSN="$(dsn qualify_credential)"
  -e QUALIFY_WEBHOOK_DSN="$(dsn qualify_webhook)"
  -e QUALIFY_WEBHOOK_WORKER_DSN="$(dsn qualify_webhook_worker)"
  -e QUALIFY_CREATIVE_WORKER_DSN="$(dsn qualify_creative_worker)"
  -e QUALIFY_REDIS_URL=redis://redis:6379/0
  -e QUALIFY_DEPLOY_ENV=production
)

docker image inspect "$IMAGE" --format 'MEASURE-IMAGE {{.Id}} {{.Created}}'
echo "==> migrate ($IMAGE)"
docker run --rm --network "$NET" "${ENV[@]}" \
  -e QUALIFY_MIGRATION_DSN="$(dsn qualify_owner)" \
  -e QUALIFY_DB_APP_PASSWORD="$PW" -e QUALIFY_DB_ADMIN_PASSWORD="$PW" \
  -e QUALIFY_DB_CREDENTIAL_PASSWORD="$PW" -e QUALIFY_DB_WEBHOOK_PASSWORD="$PW" \
  -e QUALIFY_DB_WEBHOOK_WORKER_PASSWORD="$PW" -e QUALIFY_DB_CREATIVE_WORKER_PASSWORD="$PW" \
  -v "$ROOT/packages:/app/packages:ro" -v "$ROOT/migrations:/app/migrations:ro" \
  -v "$ROOT/deploy/bootstrap_db_roles.py:/app/deploy/bootstrap_db_roles.py:ro" \
  "$IMAGE" sh -c 'alembic upgrade head >/dev/null && python deploy/bootstrap_db_roles.py'

docker run -d --name "$P-r2" --network "$NET" --network-alias fake-r2 \
  -v "$ROOT/deploy/measure:/measure:ro" "$IMAGE" \
  python /measure/creative_worker_memory.py --serve-r2 >/dev/null

echo "==> measure: mem_limit=$LIMIT memswap_limit=$LIMIT"
set +e
docker run --name "$P-worker" --network "$NET" --memory "$LIMIT" --memory-swap "$LIMIT" "${ENV[@]}" \
  -e QUALIFY_R2_ENDPOINT_URL=http://fake-r2:8080 \
  -e QUALIFY_CREATIVE_DISPATCHER=queue -e QUALIFY_CREATIONS_QUOTA=off \
  -e QUALIFY_ANTHROPIC_API_KEY=sk-ant-measure -e QUALIFY_BYTEPLUS_ARK_API_KEY=measure \
  -e LANGFUSE_PUBLIC_KEY= -e LANGFUSE_SECRET_KEY= \
  -e PYTHONPATH=/app/packages/api/src:/app/packages/shared/src:/app/packages/creative/src:/app/packages/models/src:/app/packages/scraper/src \
  -v "$ROOT/packages:/app/packages:ro" \
  -v "$ROOT/deploy/measure:/measure:ro" \
  "$IMAGE" python /measure/creative_worker_memory.py "$@"
status=$?
set -e
docker inspect "$P-worker" --format 'MEASURE-CONTAINER {"oom_killed":{{.State.OOMKilled}},"exit":{{.State.ExitCode}},"memory":{{.HostConfig.Memory}}}'
[[ $status -eq 137 ]] && echo "==> OOM-killed at mem_limit=$LIMIT (exit 137)"
exit $status
