"""The consumption daily-sync worker (m-24823681): posts each «Alta de cliente»
item's consumption summary back to Meegle.

    python -m qualify_api.consumption.worker --once
    python -m qualify_api.consumption.worker [--interval 86400]

(`just consumption-tick` runs one pass, `just consumption-worker …` keeps running.)

The primary trigger is node completion — `meegle.handlers` calls
`sync_consumption_to_meegle` when «Kit de marca listo» is completed. This worker is the
catch-up: it re-syncs every item that has ledger rows, so an item completed before the
wiring (or that accrued consumption after it) still gets its summary. Run it daily, not
hourly — Meegle accepts a repeated comment, so idempotency is not the concern, only the
API budget (500 calls/day on the Free plan).

This module adds only WHEN: it never reads the ledger or posts to Meegle by itself.
`daily_consumption_sync()` does both, cross-tenant via the `admin_session`
(BYPASSRLS) — there is no `--tenant` scope here, unlike the other workers, because a
work item's rows belong to one tenant and the catch-up is about every item at once.
The node-completion path stays the source of truth; this is a safety net.

Errors and restarts: a failing item is logged and the next one runs. A crash or restart
loses nothing — the ledger rows are the record, and a re-sync re-posts.
"""

from __future__ import annotations

import argparse
import logging
import time

from qualify_api.consumption import daily_consumption_sync

logger = logging.getLogger("qualify_api.consumption.worker")

#: One pass per day by default (the node-completion path is the primary trigger; this is
#: the catch-up). Meegle accepts a repeated comment, so a shorter interval is safe but
#: burns the API budget for no new data.
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
MIN_INTERVAL_SECONDS = 60


def _run_once() -> int:
    report = daily_consumption_sync()
    synced = report.get("synced", 0)
    failed = report.get("meegle_failed", 0)
    logger.info("consumption daily sync done: %s", report)
    # Exit 0 on success or nothing-to-do; 1 only if something failed to post — the
    # node-completion path covers the steady state, so a failed daily pass is a
    # yellow alarm, not a red one.
    return 1 if failed and not synced else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between passes (default {DEFAULT_INTERVAL_SECONDS}; "
        f"min {MIN_INTERVAL_SECONDS})",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be >= {MIN_INTERVAL_SECONDS}")
    if args.once:
        return _run_once()
    while True:
        start = time.monotonic()
        try:
            _run_once()
        except Exception:  # noqa: BLE001 — a failed pass must not kill the loop
            logger.exception("consumption daily sync pass failed")
        elapsed = time.monotonic() - start
        time.sleep(max(args.interval - elapsed, 0.0))


if __name__ == "__main__":
    raise SystemExit(main())
