#!/usr/bin/env bash
# EF-14 (m-25026592): memory, CPU and wall time of the compose over a Seedance clip (its
# 1080p final composed again with the preview's recipe) under the creative-worker's
# production cap. No database, no Redis, no network, no vendor: each case runs
# `recompose_memory.py run` in a FRESH container with --memory = --memory-swap = the
# creative-worker's `mem_limit`, sources made beforehand in a separate container.
#
#   deploy/measure/recompose-memory.sh make  [IMAGE]           # sources into ef14-clips
#   deploy/measure/recompose-memory.sh run   [IMAGE] [CASE...] # all cases by default
#   deploy/measure/recompose-memory.sh clean                   # drop the ef14-clips volume
#
# Each case prints `EF14-RESULT {json}` (exit 137 = OOM, printed as `EF14-OOM <case>`).
# Image: docker build -f deploy/Dockerfile --target deps -t qualify-memtest:deps .
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
  HOST_ROOT="$(cygpath -m "$ROOT")"
  export MSYS_NO_PATHCONV=1
else
  HOST_ROOT="$ROOT"
fi
STEP="${1:-run}"
shift || true
IMAGE="${1:-qualify-memtest:deps}"
shift || true
VOL="${EF14_VOLUME:-ef14-clips}"
LIMIT="${MEM_LIMIT:-$(awk '/^  creative-worker:/{f=1} f&&/mem_limit:/{print $2; exit}' \
  "$ROOT/deploy/docker-compose.prod.yml")}"
ON=()
[[ -n "${PLATFORM:-}" ]] && ON=(--platform "$PLATFORM")
NAME="ef14-run-$$"
trap 'docker rm -f "$NAME" "ef14-make-$$" >/dev/null 2>&1 || true' EXIT
PY=(-e PYTHONPATH=/app/packages/api/src:/app/packages/shared/src:/app/packages/creative/src
  -e QUALIFY_DEPLOY_ENV=production -e LANGFUSE_PUBLIC_KEY= -e LANGFUSE_SECRET_KEY=
  -e "EF14_DECODE=${EF14_DECODE:-}"
  -v "$HOST_ROOT/packages:/app/packages:ro" -v "$HOST_ROOT/deploy/measure:/measure:ro")

case "$STEP" in
  make)
    docker volume create "$VOL" >/dev/null
    docker run --rm "${ON[@]}" --name "ef14-make-$$" --network none -v "$VOL:/clips" \
      "${PY[@]}" "$IMAGE" python /measure/recompose_memory.py make /clips
    ;;
  run)
    if [[ $# -eq 0 ]]; then
      mapfile -t CASES < <(docker run --rm --network none "${PY[@]}" "$IMAGE" \
        python /measure/recompose_memory.py cases | tr -d '\r')
    else
      CASES=("$@")
    fi
    for c in "${CASES[@]}"; do
      echo "==> $c: mem_limit=$LIMIT memswap_limit=$LIMIT platform=${PLATFORM:-native}"
      set +e
      docker run --rm "${ON[@]}" --name "$NAME" --network none \
        --memory "$LIMIT" --memory-swap "$LIMIT" -v "$VOL:/clips:ro" "${PY[@]}" \
        "$IMAGE" python /measure/recompose_memory.py run /clips "$c"
      status=$?
      set -e
      [[ $status -eq 137 ]] && echo "EF14-OOM $c ${PLATFORM:-native} (exit 137)"
      [[ $status -ne 0 && $status -ne 137 ]] && echo "EF14-FAILED $c exit=$status"
    done
    ;;
  clean)
    docker volume rm "$VOL" >/dev/null 2>&1 || true
    ;;
  *)
    echo "usage: $0 make|run|clean [IMAGE] [CASE...]" >&2
    exit 2
    ;;
esac
