#!/usr/bin/env bash
# Import/heartbeat baseline only. No network, database, credentials or real worker tick.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
  HOST_ROOT="$(cygpath -m "$ROOT")"
  export MSYS_NO_PATHCONV=1
else
  HOST_ROOT="$ROOT"
fi
docker run --rm --network none --memory 128m --memory-swap 128m \
  -e PYTHONPATH=/app/packages/api/src:/app/packages/shared/src \
  -v "$HOST_ROOT/packages:/app/packages:ro" \
  -v "$HOST_ROOT/deploy/measure:/measure:ro" \
  "${1:-qualify-memtest:deps}" python /measure/ads_reads_import_memory.py
