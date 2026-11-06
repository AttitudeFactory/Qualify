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


def main() -> int:
    os.environ.setdefault("REFLEX_TELEMETRY_ENABLED", "false")
    from reflex.utils import prerequisites

    started = time.monotonic()
    prerequisites.get_compiled_app(dry_run=True, use_rich=False)
    print(f"Reflex app imported and compiled (dry) in {time.monotonic() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
