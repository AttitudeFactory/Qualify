"""Import and compile the whole Reflex app in memory, as `reflex export` does in deploy.yml.

m-24971869: the offline pytest suite never imports `Qualify/Qualify.py`, so a broken import
(#483 + #485 → hotfix #489) or a page that fails while its body is evaluated passed CI and
broke every deploy. This runs `App._compile(dry_run=True)` directly: same import + page
evaluation as `reflex compile --dry`, but without the CLI's `needs_reinit()` step, which on a
fresh checkout (no `.web/`) would install bun and download the frontend template. No bun, no
Node, no network. It writes only `.web/styles` and `.web/backend` (gitignored).

Usage: `uv run python .github/scripts/reflex_compile_check.py` from the repo root
(`just ci-compile`).
"""

from __future__ import annotations

import os
import sys
import time
import traceback


def main() -> int:
    os.environ.setdefault("REFLEX_TELEMETRY_ENABLED", "false")
    started = time.monotonic()
    try:
        from reflex.utils import prerequisites

        # use_rich=True: off a TTY, rich draws one final progress line; the plain progress
        # printer would log one "Progress: n/97" line per page.
        prerequisites.get_compiled_app(dry_run=True, use_rich=True)
    except Exception as exc:  # any failure here is the finding
        first_line = (str(exc).splitlines() or [""])[0]
        print(f"::error::Reflex compile failed: {type(exc).__name__}: {first_line}", flush=True)
        traceback.print_exc()
        return 1
    print(f"Reflex app imported and compiled (dry) in {time.monotonic() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
