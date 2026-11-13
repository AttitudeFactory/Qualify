"""No-network import/heartbeat baseline, NOT a full worker capacity acceptance test.

Execute inside an isolated Linux container with --network none --memory 128m
--memory-swap 128m. No tenant selector, DB connection, or Meta call is executed.
Full due-account/results load and live host headroom must be measured separately.
"""

from __future__ import annotations

import json
import resource
from pathlib import Path

from qualify_api.ads import reads_cli


def main() -> None:
    reads_cli.heartbeat()
    if not reads_cli.healthy():
        raise RuntimeError("local heartbeat failed")
    cgroup = Path("/sys/fs/cgroup")
    result = {
        "phase": "import_and_heartbeat_only",
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        "full_load_validated": False,
    }
    for name in ("memory.current", "memory.peak", "memory.max"):
        path = cgroup / name
        if path.exists():
            raw = path.read_text().strip()
            result[name] = raw if raw == "max" else int(raw)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
