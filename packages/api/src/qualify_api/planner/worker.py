"""The calendar worker (QUA-111): the process that runs the executor's tick periodically.

    python -m qualify_api.planner.worker --tenant <uuid> [--tenant <uuid> ...] [--once]
    python -m qualify_api.planner.worker --all-tenants [--once] [--interval 60]

(`just calendar-tick …` runs one tick, `just calendar-worker …` keeps running.)

Each tick is `TickRunner.run_once()` — claim → publishable POST → PublishService →
advance → settle, with every guarantee the executor already carries (claim CAS, event
and attempt advisory locks, the publisher's idempotency key, settlement CAS). This module
adds only WHEN: it never publishes, claims or settles by itself.

Scope is MANDATORY and explicit — there is no default that means "everyone":
- `--tenant <uuid>` (repeatable): `scoped_tick_runner`, only those tenants, no
  cross-tenant read. Use it locally: a development database holds test tenants a
  production tick would act on.
- `--all-tenants`: `production_tick_runner`, the production discovery.

Modes:
- `--once`: one tick, then exit (0, or 1 if the tick could not even list its tenants).
  For an external scheduler (cron / a platform job) calling every minute.
- default: a tick every `--interval` seconds (60 by default, Meta's poll cadence; at
  least 30), measured start-to-start, until SIGINT/Ctrl+C. The wait happens HERE, between
  ticks — `run_once()` never sleeps.

Errors and restarts: a failing tick is logged and the next one runs. A crash or restart
loses nothing — all state is in Postgres (events, attempts), advisory locks die with the
process's connections, and the next tick resumes whatever was in flight. Two workers (or
a worker plus a cron) running at once are safe: the claim, the locks and the idempotency
key make every action happen once.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from qualify_api.planner.tick import TickReport

logger = logging.getLogger("qualify_api.planner.worker")

DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 30


class _Runner(Protocol):
    async def run_once(self) -> TickReport: ...


def _load_dotenv() -> None:
    """Same convention as the repo's other CLIs (`Qualify/classify_hashtags.py`): the
    repo-root `.env`, never overriding what the environment already sets."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.planner.worker",
        description="Run the calendar executor (QUA-111) once or periodically.",
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
        help="Every tenant with calendar work (production discovery).",
    )
    parser.add_argument("--once", action="store_true", help="Run one tick and exit.")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between tick starts (default {DEFAULT_INTERVAL_SECONDS}, "
        f"minimum {MIN_INTERVAL_SECONDS}).",
    )
    return parser


def _log_report(report: TickReport) -> None:
    for tenant in report.tenants:
        logger.info(
            "calendar.worker.tenant tenant_id=%s advanced=%s resumed=%s executed=%s errors=%s",
            tenant.tenant_id,
            len(tenant.advanced),
            len(tenant.resumed),
            len(tenant.executed),
            len(tenant.errors),
        )
    logger.info(
        "calendar.worker.tick tenants=%s operations=%s errors=%s tick_error=%s",
        len(report.tenants),
        sum(t.operations for t in report.tenants),
        sum(len(t.errors) for t in report.tenants),
        report.error or "none",
    )


async def run_worker(
    make_runner: Callable[[], _Runner],
    *,
    once: bool,
    interval: int = DEFAULT_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    max_ticks: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    """Tick, then wait until `interval` seconds after that tick STARTED, then tick again.
    The runner is built once, after `.env` is loaded. `max_ticks` exists for tests;
    `should_stop` lets an embedding host (`planner.embedded`) end the loop between ticks."""
    runner = make_runner()
    ticks = 0
    while not should_stop():
        started = clock()
        report: TickReport | None = None
        try:
            report = await runner.run_once()
            _log_report(report)
        except Exception:
            logger.exception("calendar.worker.tick_failed")
        ticks += 1
        if once:
            return 0 if report is not None and not report.error else 1
        if max_ticks is not None and ticks >= max_ticks:
            return 0
        await sleep(max(0.0, interval - (clock() - started)))
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    scoped: Callable[[Iterable[UUID]], _Runner] | None = None,
    production: Callable[[], _Runner] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        build_parser().error(f"--interval must be at least {MIN_INTERVAL_SECONDS} seconds")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if scoped is None or production is None:
        from qualify_api.planner.composition import (  # noqa: PLC0415 — after .env
            production_tick_runner,
            scoped_tick_runner,
        )

        scoped = scoped or scoped_tick_runner
        production = production or production_tick_runner

    if args.all_tenants:
        make_runner: Callable[[], _Runner] = production
        scope = "all-tenants"
    else:
        tenant_ids = list(dict.fromkeys(args.tenants))
        make_runner = lambda: scoped(tenant_ids)  # noqa: E731
        scope = ",".join(str(t) for t in tenant_ids)
    logger.info(
        "calendar.worker.start scope=%s mode=%s interval=%ss",
        scope,
        "once" if args.once else "loop",
        args.interval,
    )
    try:
        return asyncio.run(run_worker(make_runner, once=args.once, interval=args.interval))
    except KeyboardInterrupt:
        logger.info("calendar.worker.stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
