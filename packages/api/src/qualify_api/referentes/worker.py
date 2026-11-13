"""CLI of the `reels-worker` (ADR 42 §4; slice R8, m-24854855). A pass is
`reel_worker.ReelsWorker.pass_once` (schedule, recover, retry, purge, analyses, run);
this module adds WHEN and FOR WHOM.

    python -m qualify_api.referentes.worker --tenant <uuid> [--tenant <uuid> ...] [--once]
    python -m qualify_api.referentes.worker --all-tenants [--interval 5]
    python -m qualify_api.referentes.worker --tenant <uuid> --dry-run

(`just reels-tick …` runs one pass, `just reels-worker …` keeps running.)

Scope is MANDATORY and explicit, like every worker here:
- `--tenant <uuid>` (repeatable): exactly those businesses — their brands are scheduled,
  their runs recovered and run, and the door reads nothing of anyone else. Use it
  locally: a run pays ScrapeCreators and Claude FOR REAL (the gate's
  `QUALIFY_SCRAPECREATORS_PAID=0` makes it read nothing).
- `--all-tenants`: the production service. Only it also does what belongs to no
  business: an `ok` run's ideas get their covers copied to R2 (`reel_covers`, R12) and go
  to the shared analysis (`analyze_run_ideas`), the analysis queue is drained
  (`reel_analysis_worker.drain_once`, as `just reel-analysis-tick`: downloads from the
  networks' CDNs into R2, no paid call) and the 30-day purge of what it stored — sources,
  frames and covers — runs daily (`reel_retention.purge_all`). With `--tenant` none of it
  happens: a local run writes no global analysis row and no public R2 object.

Modes:
- `--once`: one pass — the weekly scheduling forced, the recovery, at most `--batch`
  runs — then exit 0 (1 when a step failed or a run raised).
- default: a pass every `--interval` seconds (5), and at once again after a pass that
  ran a run or drained an analysis, until both queues are empty. The weekly scheduling
  runs at start and then every `--schedule-every` seconds (900).
- `--dry-run`: one read-only pass — logs the weekly runs a pass would enqueue now; writes
  nothing, runs nothing.

SIGTERM (a deploy) and SIGINT (Ctrl+C) stop the loop. Idle, it exits at once. With a run
in flight, the handler raises `reel_runs.RunInterrupted` into it: the run goes back to
`queued` — at once during the Claude check, whose answers in flight are stored when they
arrive; after the transcripts in flight (at most two 45 s phases) during that step — and
the process exits within the compose service's `stop_grace_period` (120 s). A run cut
short by a SIGKILL anyway stays `running` and is recovered after `reel_runs.STALE_AFTER`.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Protocol
from uuid import UUID

from qualify_api.referentes import reel_runs
from qualify_api.referentes.reel_queue import PostgresReelQueue
from qualify_api.referentes.reel_worker import (
    SCHEDULE_EVERY,
    PassReport,
    ReelsWorker,
    production_drain,
    production_run,
    scoped_run,
)

logger = logging.getLogger("qualify_api.referentes.worker")

DEFAULT_INTERVAL_SECONDS = 5.0
MIN_INTERVAL_SECONDS = 1.0
MIN_SCHEDULE_EVERY_SECONDS = 60


class _Worker(Protocol):
    in_run: bool

    def pass_once(self, *, force_schedule: bool = False, dry_run: bool = False) -> PassReport: ...


class WorkerFactory(Protocol):
    def __call__(
        self,
        tenant_ids: Sequence[UUID] | None,
        *,
        batch: int,
        schedule_every: timedelta,
        should_stop: Callable[[], bool],
    ) -> _Worker: ...


def production_worker(
    tenant_ids: Sequence[UUID] | None,
    *,
    batch: int,
    schedule_every: timedelta,
    should_stop: Callable[[], bool],
) -> ReelsWorker:
    """The real worker. `tenant_ids` None = every business (`--all-tenants`): the one
    place the production scope is switched on — never against a database of test
    tenants. Only that service touches what belongs to no business: it copies its runs'
    idea covers to R2 and hands the ideas to the shared analysis, drains that queue and
    purges the stored reel sources and covers, deleting for real only with
    `QUALIFY_REEL_PURGE_EXECUTE`. A `--tenant` worker runs `scoped_run`: no analysis row,
    no R2 object."""
    every = tenant_ids is None
    return ReelsWorker(
        PostgresReelQueue(tenants=tenant_ids),
        reel_runs.default_store(),
        run=production_run if every else scoped_run,
        batch=batch,
        schedule_every=schedule_every,
        should_stop=should_stop,
        purge=_production_purge if every else None,
        drain=production_drain if every else None,
    )


def _production_purge(now: datetime) -> object:
    """F9's sources and frames and R12's covers, in one pass under one flag."""
    from qualify_api.referentes import reel_retention  # noqa: PLC0415 — R2 settings on use

    return reel_retention.purge_all(
        reel_retention.production_gate(), now, reel_retention.execute_from_env()
    )


# --- the loop -----------------------------------------------------------------------------


def _log_report(report: PassReport) -> None:
    plan = report.plan
    if plan is not None and (plan.due or plan.bad_timezone or report.dry_run):
        logger.info(
            "reels.worker.schedule due=%d enqueued=%d not_ready=%d not_due=%d inactive=%d "
            "bad_timezone=%d dry_run=%s",
            len(plan.due),
            len(report.enqueued),
            report.not_ready,
            plan.not_due,
            plan.inactive,
            len(plan.bad_timezone),
            report.dry_run,
        )
    if report.dry_run:
        for due in report.enqueued:
            logger.info(
                "reels.worker.would_enqueue tenant_id=%s brand_id=%s run_date=%s",
                due.tenant_id,
                due.brand_id,
                due.run_date,
            )
    for outcome in report.outcomes:
        logger.info(
            "reels.worker.ran run_id=%s status=%s ran=%s recorded=%s credits=%d ideas=%d",
            outcome.run_id,
            outcome.status,
            outcome.ran,
            outcome.recorded,
            outcome.credits,
            outcome.ideas,
        )


def run_loop(
    worker: _Worker,
    *,
    once: bool,
    interval: float,
    stop: threading.Event,
    dry_run: bool = False,
) -> int:
    """Pass; wait `interval` unless the pass ran a run or drained an analysis; pass again
    — until `stop`, or a `RunInterrupted` (the run in flight went back to the queue)."""
    first = True
    while True:
        report: PassReport | None = None
        try:
            report = worker.pass_once(force_schedule=first, dry_run=dry_run)
            _log_report(report)
        except reel_runs.RunInterrupted:
            logger.info("reels.worker.interrupted the run in flight went back to the queue")
            return 0
        except Exception:  # noqa: BLE001 — logged; the loop goes on
            logger.exception("reels.worker.pass_failed")
        first = False
        if once or dry_run:
            failed = report is None or bool(report.errors) or report.run_errors > 0
            return 1 if failed else 0
        if stop.is_set():
            return 0
        busy = report is not None and (any(o.ran for o in report.outcomes) or bool(report.analyses))
        if not busy and stop.wait(interval):
            return 0


# --- CLI ----------------------------------------------------------------------------------


def _load_dotenv() -> None:
    """The repo-root `.env`, never overriding the environment (same as the other CLIs)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.referentes.worker",
        description="Run the reels worker (ADR 42 R8): the weekly runs and the run queue.",
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
    scope.add_argument("--all-tenants", action="store_true", help="Every tenant (production).")
    parser.add_argument("--once", action="store_true", help="Run one pass and exit.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="One read-only pass: log the weekly runs that would be enqueued; write nothing.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between passes when idle (default {DEFAULT_INTERVAL_SECONDS:g}, "
        f"minimum {MIN_INTERVAL_SECONDS:g}).",
    )
    parser.add_argument(
        "--schedule-every",
        type=int,
        default=int(SCHEDULE_EVERY.total_seconds()),
        help=f"Seconds between weekly scheduling passes (default "
        f"{int(SCHEDULE_EVERY.total_seconds())}, minimum {MIN_SCHEDULE_EVERY_SECONDS}).",
    )
    parser.add_argument("--batch", type=int, default=1, help="Runs started per pass (default 1).")
    return parser


def install_signals(stop: threading.Event, worker: _Worker) -> None:
    """SIGTERM / SIGINT: stop the loop; with a run in flight, raise `RunInterrupted` into
    it (once) so it goes back to the queue instead of being cut by the SIGKILL."""

    def handler(signum: int, frame: FrameType | None) -> None:
        first = not stop.is_set()
        stop.set()
        logger.info("reels.worker.stopping signal=%s in_run=%s", signum, worker.in_run)
        if first and worker.in_run:
            raise reel_runs.RunInterrupted(f"signal {signum}")

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def main(
    argv: Sequence[str] | None = None,
    *,
    make_worker: WorkerFactory | None = None,
    install_handlers: bool = True,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be at least {MIN_INTERVAL_SECONDS:g} second(s)")
    if args.schedule_every < MIN_SCHEDULE_EVERY_SECONDS:
        parser.error(f"--schedule-every must be at least {MIN_SCHEDULE_EVERY_SECONDS} seconds")
    if args.batch < 1:
        parser.error("--batch must be at least 1")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    scope_ids = None if args.all_tenants else list(dict.fromkeys(args.tenants))
    stop = threading.Event()
    worker = (make_worker or production_worker)(
        scope_ids,
        batch=args.batch,
        schedule_every=timedelta(seconds=args.schedule_every),
        should_stop=stop.is_set,
    )
    if install_handlers:
        install_signals(stop, worker)
    logger.info(
        "reels.worker.start scope=%s mode=%s interval=%ss schedule_every=%ss batch=%d",
        "all-tenants" if scope_ids is None else ",".join(str(t) for t in scope_ids),
        "dry-run" if args.dry_run else "once" if args.once else "loop",
        args.interval,
        args.schedule_every,
        args.batch,
    )
    code = run_loop(worker, once=args.once, interval=args.interval, stop=stop, dry_run=args.dry_run)
    logger.info("reels.worker.stopped code=%d", code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
