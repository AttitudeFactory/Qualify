#!/usr/bin/env bash
# EF-15 (m-25026575): memory, CPU and wall time of the LOCAL video assembly (EF-06,
# `render_local_part`) under the creative-worker's production cap. No database, no Redis,
# no network: each case is `render_local_part` called straight in a FRESH container with
# --memory = --memory-swap = the creative-worker's `mem_limit` (768m), sources read from a
# volume made beforehand in a separate container (its encoding is not measured).
#
#   deploy/measure/local-video-memory.sh make  [IMAGE]           # sources into ef15-clips
#   deploy/measure/local-video-memory.sh run   [IMAGE] [CASE...] # all cases by default
#   deploy/measure/local-video-memory.sh clean                   # drop the ef15-clips volume
#
# Each case prints `EF15-RESULT {json}` (exit 137 = OOM, printed as `EF15-OOM <case>`).
# Tabulate: python deploy/measure/local_video_memory.py table <log>.
# PLATFORM=linux/arm64 emulates production's arm64 with QEMU (memory comparable, time
# NOT); build the image first, as creative-worker-memory.sh says:
#   docker build --platform linux/arm64 -f deploy/Dockerfile --target deps \
#     -t qualify-memtest:deps-arm64 .
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
VOL="${EF15_VOLUME:-ef15-clips}"
LIMIT="${MEM_LIMIT:-$(awk '/^  creative-worker:/{f=1} f&&/mem_limit:/{print $2; exit}' \
  "$ROOT/deploy/docker-compose.prod.yml")}"
ON=()
[[ -n "${PLATFORM:-}" ]] && ON=(--platform "$PLATFORM")
# m-25114465: CPUS=1 caps the run's CPU as the worker's (`--cpus`); unset = no cap
CPU=()
[[ -n "${CPUS:-}" ]] && CPU=(--cpus "$CPUS")
NAME="ef15-run-$$"
trap 'docker rm -f "$NAME" "ef15-make-$$" >/dev/null 2>&1 || true' EXIT
PY=(-e PYTHONPATH=/app/packages/api/src:/app/packages/shared/src:/app/packages/creative/src
  -e QUALIFY_DEPLOY_ENV=production -e LANGFUSE_PUBLIC_KEY= -e LANGFUSE_SECRET_KEY=
  -v "$HOST_ROOT/packages:/app/packages:ro" -v "$HOST_ROOT/deploy/measure:/measure:ro")

case "$STEP" in
  make)
    docker volume create "$VOL" >/dev/null
    docker run --rm "${ON[@]}" --name "ef15-make-$$" --network none -v "$VOL:/clips" \
      "${PY[@]}" "$IMAGE" python /measure/local_video_memory.py make /clips "$@"
    ;;
  run)
    if [[ $# -eq 0 ]]; then
      mapfile -t CASES < <(docker run --rm --network none "${PY[@]}" "$IMAGE" \
        python /measure/local_video_memory.py cases | tr -d '\r')
    else
      CASES=("$@")
    fi
    for c in "${CASES[@]}"; do
      echo "==> $c: mem_limit=$LIMIT memswap_limit=$LIMIT cpus=${CPUS:-none} platform=${PLATFORM:-native}"
      set +e
      docker run --rm "${ON[@]}" "${CPU[@]}" --name "$NAME" --network none \
        --memory "$LIMIT" --memory-swap "$LIMIT" -v "$VOL:/clips:ro" "${PY[@]}" \
        "$IMAGE" python /measure/local_video_memory.py run /clips "$c"
      status=$?
      set -e
      [[ $status -eq 137 ]] && echo "EF15-OOM $c ${PLATFORM:-native} (exit 137)"
      [[ $status -ne 0 && $status -ne 137 ]] && echo "EF15-FAILED $c exit=$status"
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
