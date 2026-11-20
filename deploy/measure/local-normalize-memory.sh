#!/usr/bin/env bash
# m-25071265: the local-source normalizer (`normalize_local`, m-25042483) per x264 setting —
# memory and CPU under the MEDIA-WORKER's production cap (its `mem_limit` and `cpus`, read
# from docker-compose.prod.yml), then SSIM/PSNR of the copy and of the published video.
# No database, no network; synthetic sources only (local_normalize_memory.py says which).
#
# The image is EF-15's `qualify-memtest:deps` plus Debian's ffmpeg (what the app image
# installs, m-24957792):
#   printf 'FROM qualify-memtest:deps\nRUN apt-get update && apt-get install -y \
#     --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*\n' \
#     | docker build -t qualify-memtest:ffmpeg -
#
#   deploy/measure/local-normalize-memory.sh make                       # sources
#   deploy/measure/local-normalize-memory.sh run SOURCE VARIANT          # capped, fresh container
#   deploy/measure/local-normalize-memory.sh quality SOURCE VARIANT      # uncapped
#   deploy/measure/local-normalize-memory.sh publish SOURCE VARIANT|original
#   deploy/measure/local-normalize-memory.sh compare SOURCE VARIANT
#   deploy/measure/local-normalize-memory.sh clean
#
# `run` prints `NORM-RESULT {json}` (exit 137 = OOM, printed as `NORM-OOM`).
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
SCRIPT=/measure/local_normalize_memory.py

case "$STEP" in
  make)
    docker volume create "$VOL" >/dev/null
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
      echo "NORM-OOM $* (exit 137)"
    elif [[ $status -ne 0 ]]; then
      echo "NORM-FAILED $* exit=$status"
    fi
    exit "$status"
    ;;
  quality|publish|compare)
    docker run --rm --network none -v "$VOL:/clips" "${PY[@]}" "$IMAGE" \
      python "$SCRIPT" "$STEP" /clips "$@"
    ;;
  clean)
    docker volume rm "$VOL" >/dev/null 2>&1 || true
    ;;
  *)
    echo "usage: $0 make|run|quality|publish|compare|clean [SOURCE VARIANT]" >&2
    exit 2
    ;;
esac
