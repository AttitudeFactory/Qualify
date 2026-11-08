#!/usr/bin/env bash
# Current-source creative-worker memory under its production cap (`mem_limit` of `creative-worker` in docker-compose.prod.yml).
# Uses production deps image + read-only current packages/migrations, synthetic vendor
# boundaries and a throwaway PostgreSQL/Redis on --internal network (no route out).
# No host environment file/credentials/ports are passed. Exit137=OOM; exit1=>=95% cap.
# Usage: deploy/measure/creative-worker-memory.sh [IMAGE] [-- --download-mib 40]
#
# VE-10a: the run ends with a video by parts' `join` phase (the real PipelinePreparation)
# over JOIN_PARTS synthetic 1080p parts (default 6 x JOIN_SECONDS=10 s), made by
# join_memory.py in a SEPARATE container so their encoding is not counted. The join is
# encoded at `-- --join-size WxH`: 1080x1920 by default (VE-10b's final join, the worst
# case), 480x854 for the real preview. JOIN_PARTS=0 skips the phase. The synthetic
# brand has a logo, laid over the join as in production; `-- --no-join-logo` omits it.
# Two figures: the WHOLE worker process (carousel, downloads, then the join) and, with
# JOIN_FRESH=1 (default), the join alone in a FRESH worker container (`--only-join`).
# Each prints MEASURE-CONTAINER; the join's own peak is MEASURE-JOIN (or
# MEASURE-JOIN-FAILED, and the last MEASURE-JOIN-PROGRESS before an OOM kill).
# VE-10b: JOIN_FINAL=1 measures the parent's `join_final` phase instead (the whole video
# approved through the real approve_parts, each part's raw 1080p final = a synthetic
# 10-bit H.265 part, JOIN_CODEC=hevc10 by default; joined at 1080x1920 with the logo
# once). Its MEASURE-JOIN line carries "phase": "join_final".
#   JOIN_FINAL=1 MEM_LIMIT=768m deploy/measure/creative-worker-memory.sh qualify-memtest:deps
# PLATFORM=linux/arm64 runs the image-based containers as production's arm64 (on an
# amd64 host Docker emulates it with QEMU: memory is comparable, time is not). Build the
# image for that platform first:
#   docker build --platform linux/arm64 -f deploy/Dockerfile --target deps \
#     -t qualify-memtest:deps-arm64 .
#   PLATFORM=linux/arm64 deploy/measure/creative-worker-memory.sh qualify-memtest:deps-arm64
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
JOIN_PARTS="${JOIN_PARTS:-6}"
JOIN_SECONDS="${JOIN_SECONDS:-10}"
JOIN_FRESH="${JOIN_FRESH:-1}"
JOIN_FINAL="${JOIN_FINAL:-0}"
if [[ $JOIN_FINAL == 1 ]]; then
  JOIN_CODEC="${JOIN_CODEC:-hevc10}"
  FINAL_ARGS=(--join-final)
else
  JOIN_CODEC="${JOIN_CODEC:-h264}"
  FINAL_ARGS=()
fi
ON=()
[[ -n "${PLATFORM:-}" ]] && ON=(--platform "$PLATFORM")

cleanup() {
  docker rm -f "$P-pg" "$P-redis" "$P-r2" "$P-worker" "$P-worker-join" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker volume rm "$P-parts" >/dev/null 2>&1 || true
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

docker image inspect "$IMAGE" \
  --format 'MEASURE-IMAGE {{.Id}} {{.Created}} {{.Os}}/{{.Architecture}}'
echo "==> migrate ($IMAGE)"
docker run --rm "${ON[@]}" --network "$NET" "${ENV[@]}" \
  -e QUALIFY_MIGRATION_DSN="$(dsn qualify_owner)" \
  -e QUALIFY_DB_APP_PASSWORD="$PW" -e QUALIFY_DB_ADMIN_PASSWORD="$PW" \
  -e QUALIFY_DB_CREDENTIAL_PASSWORD="$PW" -e QUALIFY_DB_WEBHOOK_PASSWORD="$PW" \
  -e QUALIFY_DB_WEBHOOK_WORKER_PASSWORD="$PW" -e QUALIFY_DB_CREATIVE_WORKER_PASSWORD="$PW" \
  -v "$ROOT/packages:/app/packages:ro" -v "$ROOT/migrations:/app/migrations:ro" \
  -v "$ROOT/deploy/bootstrap_db_roles.py:/app/deploy/bootstrap_db_roles.py:ro" \
  "$IMAGE" sh -c 'alembic upgrade head >/dev/null && python deploy/bootstrap_db_roles.py'

docker volume create "$P-parts" >/dev/null
if [[ $JOIN_PARTS -gt 0 ]]; then
  echo "==> $JOIN_PARTS synthetic 1080p $JOIN_CODEC parts of ${JOIN_SECONDS}s (own container, not measured)"
  docker run --rm "${ON[@]}" --network none -v "$P-parts:/parts" \
    -v "$ROOT/deploy/measure:/measure:ro" "$IMAGE" \
    python /measure/join_memory.py make /parts --parts "$JOIN_PARTS" --seconds "$JOIN_SECONDS" \
      --codec "$JOIN_CODEC"
fi

docker run -d "${ON[@]}" --name "$P-r2" --network "$NET" --network-alias fake-r2 \
  -v "$ROOT/deploy/measure:/measure:ro" "$IMAGE" \
  python /measure/creative_worker_memory.py --serve-r2 >/dev/null

WORKER_ENV=(
  -e QUALIFY_R2_ENDPOINT_URL=http://fake-r2:8080
  -e QUALIFY_CREATIVE_DISPATCHER=queue -e QUALIFY_CREATIONS_QUOTA=off
  -e QUALIFY_ANTHROPIC_API_KEY=sk-ant-measure -e QUALIFY_BYTEPLUS_ARK_API_KEY=measure
  -e LANGFUSE_PUBLIC_KEY= -e LANGFUSE_SECRET_KEY=
  -e PYTHONPATH=/app/packages/api/src:/app/packages/shared/src:/app/packages/creative/src:/app/packages/models/src:/app/packages/scraper/src
)

# measure NAME ARGS... — one worker container under the cap; its exit status in $status
measure() {
  local name="$1"
  shift
  set +e
  docker run "${ON[@]}" --name "$name" --network "$NET" \
    --memory "$LIMIT" --memory-swap "$LIMIT" "${ENV[@]}" "${WORKER_ENV[@]}" \
    -v "$ROOT/packages:/app/packages:ro" \
    -v "$ROOT/deploy/measure:/measure:ro" -v "$P-parts:/parts:ro" \
    "$IMAGE" python /measure/creative_worker_memory.py --join-parts "$JOIN_PARTS" \
      ${FINAL_ARGS[@]+"${FINAL_ARGS[@]}"} "$@"
  status=$?
  set -e
  docker inspect "$name" --format 'MEASURE-CONTAINER {"oom_killed":{{.State.OOMKilled}},"exit":{{.State.ExitCode}},"memory":{{.HostConfig.Memory}}}'
  [[ $status -eq 137 ]] && echo "==> OOM-killed at mem_limit=$LIMIT (exit 137)"
  return 0
}

echo "==> measure (whole process): mem_limit=$LIMIT memswap_limit=$LIMIT platform=${PLATFORM:-native}"
measure "$P-worker" "$@"
verdict=$status
if [[ $JOIN_PARTS -gt 0 && $JOIN_FRESH == 1 ]]; then
  echo "==> measure (join alone, fresh worker): mem_limit=$LIMIT platform=${PLATFORM:-native}"
  measure "$P-worker-join" --only-join "$@"
  [[ $verdict -eq 0 ]] && verdict=$status
fi
exit $verdict
