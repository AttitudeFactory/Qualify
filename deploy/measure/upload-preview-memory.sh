#!/usr/bin/env bash
# m-25026643 (ED-09): the generator upload's 480p copy (`upload_preview`) — memory and time
# under the MEDIA-WORKER's production cap (its `mem_limit` and `cpus`, read from
# docker-compose.prod.yml). No database, no network; synthetic sources only
# (upload_preview_memory.py says which). Same image and volume as
# local-normalize-memory.sh (run its `make` first: this one derives the 112 s sources).
#
#   deploy/measure/upload-preview-memory.sh make            # the 112 s sources
#   deploy/measure/upload-preview-memory.sh run SOURCE      # capped, fresh container
#
# `run` prints `PREVIEW-RESULT {json}` (exit 137 = OOM, printed as `PREVIEW-OOM`).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
  HOST_ROOT="$(cygpath -m "$ROOT")"
  export MSYS_NO_PATHCONV=1
else
  HOST_ROOT="$ROOT"
fi
STEP="${1:-}"
shift || true
IMAGE="${IMAGE:-qualify-memtest:ffmpeg}"
VOL="${NORM_VOLUME:-norm-clips}"
read_media_worker() {
  awk -v key="$1" '/^  media-worker:/{f=1} f&&$1==key":"{print $2; exit}' \
    "$ROOT/deploy/docker-compose.prod.yml"
}
LIMIT="${MEM_LIMIT:-$(read_media_worker mem_limit)}"
CPUS="${CPUS:-$(read_media_worker cpus)}"
PY=(-e PYTHONPATH=/app/packages/api/src:/app/packages/shared/src:/app/packages/creative/src
  -e QUALIFY_DEPLOY_ENV=production -e LANGFUSE_PUBLIC_KEY= -e LANGFUSE_SECRET_KEY=
  -v "$HOST_ROOT/packages:/app/packages:ro" -v "$HOST_ROOT/deploy/measure:/measure:ro")
SCRIPT=/measure/upload_preview_memory.py

case "$STEP" in
  make)
    docker run --rm --network none -v "$VOL:/clips" "${PY[@]}" "$IMAGE" python "$SCRIPT" make /clips
    ;;
  run)
    echo "==> $*: mem_limit=$LIMIT cpus=$CPUS"
    set +e
    docker run --rm --network none --memory "$LIMIT" --memory-swap "$LIMIT" --cpus "$CPUS" \
      -v "$VOL:/clips" "${PY[@]}" "$IMAGE" python "$SCRIPT" run /clips "$@"
    status=$?
    set -e
    if [[ $status -eq 137 ]]; then
      echo "PREVIEW-OOM $* (exit 137)"
    elif [[ $status -ne 0 ]]; then
      echo "PREVIEW-FAILED $* exit=$status"
    fi
    exit "$status"
    ;;
  *)
    echo "usage: $0 make|run [SOURCE]" >&2
    exit 2
    ;;
esac
