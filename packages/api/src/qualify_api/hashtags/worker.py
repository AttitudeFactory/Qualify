"""CLI of the weekly TikTok read per rubro hashtag (m-25026378; `qualify_api.hashtags.
weekly` is the pass, this module adds WHEN and FOR WHOM).

    python -m qualify_api.hashtags.worker --tenant <uuid> [--tenant <uuid> ...] --once
    python -m qualify_api.hashtags.worker --all-tenants [--interval 3600]

Scope is MANDATORY and explicit, like every worker here:
- `--tenant <uuid>` (repeatable): exactly those businesses. Use it locally — with
  `QUALIFY_HASHTAG_WEEKLY_READ=1` a pass PAYS ScrapeCreators FOR REAL (one credit per
  hashtag read; `QUALIFY_SCRAPECREATORS_PAID=0` makes the gate refuse every read).
- `--all-tenants`: the production scope — while the pilot allowlist exists (D3,
  `hashtags.pilot`), «all tenants» means «all LISTED tenants»: only the businesses in
  `QUALIFY_HASHTAG_WEEKLY_TENANTS`, and an empty list reads nobody. The same list the
  reels worker reads, so running this by hand inside `reels-worker` cannot widen it.

Modes: `--once` runs one pass and exits (0, or 1 when a business failed, the vendor key
is missing or a global gate refusal stopped the pass); by default a pass every
`--interval` seconds (3600) until SIGTERM / Ctrl+C. Passing often is safe and free: a
hashtag with a kept answer from this week is never read again, and a business is
attempted at most once a day (`weekly` module docstring). With a switch off or no key
every pass returns at once, booking nothing.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from uuid import UUID

from qualify_api.hashtags import pilot, weekly

logger = logging.getLogger("qualify_api.hashtags.worker")

DEFAULT_INTERVAL_SECONDS = 3600.0
MIN_INTERVAL_SECONDS = 60.0

Tick = Callable[[Sequence[UUID] | None], weekly.TickReport]


def run_loop(
    tick: Tick,
    scope: Sequence[UUID] | None,
    *,
    once: bool,
    interval: float,
    stop: threading.Event,
) -> int:
    while True:
        report: weekly.TickReport | None = None
        try:
            report = tick(scope)
        except Exception:  # noqa: BLE001 - logged; the loop goes on
            logger.exception("hashtags.worker.pass_failed")
        if once:
            # a switch turned off on purpose, an empty pilot list or a stop is not a
            # failure; a missing key or a gate refusal (floor, 402) is
            deliberate = (None, "switch_off", "paid_off", pilot.NO_PILOT_TENANTS, weekly.STOPPING)
            failed = report is None or report.errors > 0 or report.stopped not in deliberate
            return 1 if failed else 0
        if stop.wait(interval):
            return 0


def _load_dotenv() -> None:
    """The repo-root `.env`, never overriding the environment (same as the other CLIs)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.hashtags.worker",
        description="Weekly TikTok read per rubro hashtag (m-25026378).",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--tenant",
        dest="tenants",
        action="append",
        type=UUID,
        metavar="UUID",
        help="Only this tenant (repeatable). Use this locally.",
    )
    scope.add_argument(
        "--all-tenants",
        action="store_true",
        help=f"Every tenant listed in {pilot.TENANTS_ENV} (production pilot; empty = nobody).",
    )
    parser.add_argument("--once", action="store_true", help="Run one pass and exit.")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between passes (default {DEFAULT_INTERVAL_SECONDS:g}, "
        f"minimum {MIN_INTERVAL_SECONDS:g}).",
    )
    return parser


def default_tick(stop: threading.Event) -> Tick:
    """`--tenant` ids go straight to `weekly.run_tick`; `--all-tenants` (None) reads the
    pilot allowlist (`pilot.run_pilot`): empty = nobody."""

    def tick(ids: Sequence[UUID] | None) -> weekly.TickReport:
        if ids is None:
            return pilot.run_pilot(datetime.now(UTC), should_stop=stop.is_set)
        return weekly.run_tick(ids, should_stop=stop.is_set)

    return tick


def main(argv: Sequence[str] | None = None, *, tick: Tick | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be at least {MIN_INTERVAL_SECONDS:g} seconds")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    scope = None if args.all_tenants else list(dict.fromkeys(args.tenants))
    stop = threading.Event()

    def handler(signum: int, frame: FrameType | None) -> None:
        stop.set()

    if tick is None:  # a test passes its own tick and keeps its signal handlers
        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)
    logger.info(
        "hashtags.worker.start scope=%s mode=%s interval=%ss",
        "all-tenants" if scope is None else ",".join(str(t) for t in scope),
        "once" if args.once else "loop",
        args.interval,
    )
    code = run_loop(
        tick or default_tick(stop),
        scope,
        once=args.once,
        interval=args.interval,
        stop=stop,
    )
    logger.info("hashtags.worker.stopped code=%d", code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
