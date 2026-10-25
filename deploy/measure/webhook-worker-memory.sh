#!/usr/bin/env bash
# Peak memory of webhook-worker under its production cap (m-24852538).
#
#   deploy/measure/webhook-worker-memory.sh [IMAGE] [-- extra args for the python script]
#   just mem-webhook-worker [IMAGE]
#
# IMAGE defaults to `qualify-memtest:deps`, built from this tree with
#   docker build -f deploy/Dockerfile --target deps -t qualify-memtest:deps .
# (`deps` holds exactly the venv, sources and robertuito weights `app` copies; the `app`
# stage adds only the Reflex frontend export). A CI image works too:
# ghcr.io/attitudefactory/qualify-app:<sha>.
#
# What it does, all on a throwaway docker project `qualify-memtest` (own network, no
# published ports — never collides with the dev compose on 5432):
#   1. an `--internal` network (no route to the internet: nothing can reach a vendor,
#      Meta or Meegle), pgvector pg16 + redis 7 on it;
#   2. the production migration (`alembic upgrade head` + deploy/bootstrap_db_roles.py);
#   3. deploy/measure/webhook_worker_memory.py in the image with the SAME cap as
#      deploy/docker-compose.prod.yml (MEM_LIMIT, default read from that file), printing
#      one MEASURE line per phase; an OOM kill shows as exit 137;
#   4. removes everything it created.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${1:-qualify-memtest:deps}"
shift || true
[[ "${1:-}" == "--" ]] && shift
P=qualify-memtest
NET="$P-net"
LIMIT="${MEM_LIMIT:-$(awk '/^  webhook-worker:/{f=1} f&&/mem_limit:/{print $2; exit}' \
  "$ROOT/deploy/docker-compose.prod.yml")}"
PW=measure-only-password-0000   # throwaway database, never a real one

cleanup() {
  docker rm -f "$P-pg" "$P-redis" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker network create --internal "$NET" >/dev/null
docker run -d --name "$P-pg" --network "$NET" --network-alias postgres \
  -e POSTGRES_DB=qualify -e POSTGRES_USER=qualify_owner -e POSTGRES_PASSWORD="$PW" \
  pgvector/pgvector:pg16 >/dev/null
docker run -d --name "$P-redis" --network "$NET" --network-alias redis redis:7-alpine >/dev/null
until docker exec "$P-pg" pg_isready -U qualify_owner -d qualify >/dev/null 2>&1; do sleep 1; done
sleep 2

dsn() { echo "postgresql+psycopg://$1:$PW@postgres:5432/qualify"; }
ENV=(
  -e QUALIFY_APP_DSN="$(dsn qualify_app)"
  -e QUALIFY_ADMIN_DSN="$(dsn qualify_admin)"
  -e QUALIFY_CREDENTIAL_DSN="$(dsn qualify_credential)"
  -e QUALIFY_WEBHOOK_DSN="$(dsn qualify_webhook)"
  -e QUALIFY_WEBHOOK_WORKER_DSN="$(dsn qualify_webhook_worker)"
  -e QUALIFY_REDIS_URL=redis://redis:6379/0
  -e QUALIFY_DEPLOY_ENV=production
)

echo "==> migrate ($IMAGE)"
docker run --rm --network "$NET" "${ENV[@]}" \
  -e QUALIFY_MIGRATION_DSN="$(dsn qualify_owner)" \
  -e QUALIFY_DB_APP_PASSWORD="$PW" -e QUALIFY_DB_ADMIN_PASSWORD="$PW" \
  -e QUALIFY_DB_CREDENTIAL_PASSWORD="$PW" -e QUALIFY_DB_WEBHOOK_PASSWORD="$PW" \
  -e QUALIFY_DB_WEBHOOK_WORKER_PASSWORD="$PW" \
  "$IMAGE" sh -c 'alembic upgrade head >/dev/null && python deploy/bootstrap_db_roles.py'

echo "==> measure: mem_limit=$LIMIT memswap_limit=$LIMIT"
set +e
docker run --rm --network "$NET" --memory "$LIMIT" --memory-swap "$LIMIT" "${ENV[@]}" \
  -e QUALIFY_MEEGLE_PLUGIN_ID=measure -e QUALIFY_MEEGLE_PLUGIN_SECRET=measure \
  -e QUALIFY_MEEGLE_CALLBACK_TOKEN=measure -e QUALIFY_MEEGLE_PROJECT_KEY=measure \
  -e QUALIFY_MEEGLE_WORK_ITEM_TYPE=measure -e QUALIFY_MEEGLE_USER_KEY=measure \
  -e QUALIFY_MEEGLE_BASE_URL=http://meegle.invalid \
  -e QUALIFY_ALTA_PREFILL_ENABLED=1 -e QUALIFY_ALTA_PREFILL_MAX_USD=1 \
  -e QUALIFY_ANTHROPIC_API_KEY=sk-ant-measure -e SCRAPECREATORS_API_KEY=sk-measure \
  -e LANGFUSE_PUBLIC_KEY= -e LANGFUSE_SECRET_KEY= \
  -e MEASURE_FIXTURES=/fixtures \
  -v "$ROOT/deploy/measure:/measure:ro" \
  -v "$ROOT/packages/api/tests/fixtures/scrapecreators:/fixtures:ro" \
  "$IMAGE" python /measure/webhook_worker_memory.py "$@"
status=$?
set -e
[[ $status -eq 137 ]] && echo "==> OOM-killed at mem_limit=$LIMIT (exit 137)"
exit $status
