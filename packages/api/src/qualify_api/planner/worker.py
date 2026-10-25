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

Piece retention (m-24828907): in loop mode the worker also runs the piece purge
(`creative.retention_job`) at start and every 24 h, over the same scope — it really
deletes, unless `QUALIFY_PIECE_PURGE_EXECUTE=0` (kill switch: log only). `--purge-pieces
[--execute]` runs it once and exits — a dry run without `--execute` —
(`just piece-purge …`), without ticking.

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

from qualify_api.planner.heartbeat import (
    HeartbeatStore,
    production_heartbeat_store,
    record_beat,
)
from qualify_api.planner.tick import TickReport

logger = logging.getLogger("qualify_api.planner.worker")

DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 30
#: m-24852492: the recovery pass of billed BytePlus videos (`creative.vendor_recovery`).
RECOVERY_EVERY_SECONDS = 60


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
        "--purge-pieces",
        action="store_true",
        help="m-24828907: run the piece purge once for the scope and exit (no tick). "
        "Dry run unless --execute.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="With --purge-pieces: really delete the files of expired pieces from R2.",
    )
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
    on_tick: Callable[[TickReport | None], None] | None = None,
    chore: Callable[[], object] | None = None,
    chore_every: float = 24 * 60 * 60,
    sidecar: Callable[[], object] | None = None,
    sidecar_every: float = 60.0,
) -> int:
    """Tick, then wait until `interval` seconds after that tick STARTED, then tick again.
    The runner is built once, after `.env` is loaded. `max_ticks` exists for tests;
    `should_stop` lets an embedding host (`planner.embedded`) end the loop between ticks;
    `on_tick` gets each tick's report (None when the tick raised) — the heartbeat.

    `chore` (m-24828907: the piece purge) runs before the first tick of the loop and then
    every `chore_every` seconds, in a thread so the event loop is not blocked, and a
    failing chore is logged and never stops the ticks. Never in `--once` mode: a cron
    calling `--once` every minute must not purge every minute.

    `sidecar` (m-24852492: the recovery of billed BytePlus videos) runs in a thread
    BESIDE the ticks — never awaited by them, so a slow pass (a resumed run downloading
    a video) delays no publication. At most one pass is in flight; a new one starts at
    the first tick start `sidecar_every` seconds after the previous one started and
    after it ended. In `--once` mode it runs once, after the tick. A failing pass is
    logged and the next one runs."""
    runner = make_runner()
    ticks = 0
    next_chore = clock()
    next_sidecar = clock()
    in_flight: asyncio.Task[object] | None = None
    try:
        while not should_stop():
            started = clock()
            if sidecar is not None and not once and started >= next_sidecar:
                if in_flight is None or in_flight.done():
                    in_flight = asyncio.create_task(asyncio.to_thread(_guarded, sidecar))
                    next_sidecar = started + sidecar_every
                    await asyncio.sleep(0)  # let the thread start before the tick
            code = await _tick(runner, once, chore, next_chore, started, on_tick)
            if chore is not None and not once and started >= next_chore:
                next_chore = started + chore_every
            ticks += 1
            if once:
                if sidecar is not None:
                    await asyncio.to_thread(_guarded, sidecar)
                return code
            if max_ticks is not None and ticks >= max_ticks:
                return 0
            await sleep(max(0.0, interval - (clock() - started)))
        return 0
    finally:
        if in_flight is not None and not in_flight.done():
            await in_flight


def _guarded(job: Callable[[], object]) -> object:
    try:
        return job()
    except Exception:
        logger.exception("calendar.worker.sidecar_failed")
        return None


async def _tick(
    runner: _Runner,
    once: bool,
    chore: Callable[[], object] | None,
    next_chore: float,
    started: float,
    on_tick: Callable[[TickReport | None], None] | None,
) -> int:
    """The chore when due, then one tick; the `--once` exit code (0 / 1)."""
    if chore is not None and not once and started >= next_chore:
        try:
            await asyncio.to_thread(chore)
        except Exception:
            logger.exception("calendar.worker.chore_failed")
    report: TickReport | None = None
    try:
        report = await runner.run_once()
        _log_report(report)
    except Exception:
        logger.exception("calendar.worker.tick_failed")
    if on_tick is not None:
        on_tick(report)
    return 0 if report is not None and not report.error else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    scoped: Callable[[Iterable[UUID]], _Runner] | None = None,
    production: Callable[[], _Runner] | None = None,
    heartbeat: HeartbeatStore | None = None,
    purge: Callable[[list[UUID] | None, bool], object] | None = None,
    chore: Callable[[], object] | None = None,
    recovery: Callable[[], object] | None = None,
) -> int:
    """`purge(tenant_ids | None, execute)`, `chore` and `recovery` exist for tests; by
    default they are `retention_job.run_piece_purge`, `retention_job.daily_chore` and —
    only with the production wiring — `creative.vendor_recovery.recovery_chore`
    (m-24852492: billed BytePlus videos recovered without a screen read, every
    `RECOVERY_EVERY_SECONDS`, over the same scope as the ticks)."""
    args = build_parser().parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        build_parser().error(f"--interval must be at least {MIN_INTERVAL_SECONDS} seconds")
    if args.execute and not args.purge_pieces:
        build_parser().error("--execute only applies to --purge-pieces")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    scope_ids: list[UUID] | None = None if args.all_tenants else list(dict.fromkeys(args.tenants))
    if args.purge_pieces:
        if purge is None:
            from qualify_api.creative.retention_job import run_piece_purge  # noqa: PLC0415

            purge = lambda ids, execute: run_piece_purge(ids, execute=execute)  # noqa: E731
        try:
            purge(scope_ids, args.execute)
        except Exception:
            logger.exception("calendar.worker.purge_failed")
            return 1
        return 0
    if chore is None and not args.once:
        from qualify_api.creative.retention_job import daily_chore  # noqa: PLC0415

        chore = daily_chore(scope_ids)
    if scoped is None or production is None:
        from qualify_api.planner.composition import (  # noqa: PLC0415 — after .env
            production_tick_runner,
            scoped_tick_runner,
        )

        if recovery is None:
            from qualify_api.creative.vendor_recovery import (  # noqa: PLC0415 — lazy
                recovery_chore,
            )

            recovery = recovery_chore(scope_ids)

        scoped = scoped or scoped_tick_runner
        production = production or production_tick_runner
        heartbeat = heartbeat or production_heartbeat_store()

    tenant_ids: list[UUID] = []
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

    def beat(report: TickReport | None) -> None:
        # The Planificador reads this to say whether automatic publishing is on (heartbeat.py).
        record_beat(
            heartbeat,
            all_tenants=args.all_tenants,
            tenant_ids=tenant_ids,
            interval=args.interval,
            error="tick_failed" if report is None else report.error,
        )

    try:
        return asyncio.run(
            run_worker(
                make_runner,
                once=args.once,
                interval=args.interval,
                on_tick=beat,
                chore=chore,
                sidecar=recovery,
                sidecar_every=RECOVERY_EVERY_SECONDS,
            )
        )
    except KeyboardInterrupt:
        logger.info("calendar.worker.stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
