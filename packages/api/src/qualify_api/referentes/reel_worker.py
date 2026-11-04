"""One pass of the `reels-worker` (ADR 42 §4; slice R8, m-24854855). The CLI loop that
repeats it is `qualify_api.referentes.worker`.

A pass, in order:

1. **Schedule** — at most every `SCHEDULE_EVERY` (15 min; the first pass always): the
   weekly run of every brand opened in the 14 days before its Monday 06:00 local, while
   that Monday's 24 h window is open (`reel_schedule.plan_weekly`), enqueued through
   `reel_runs.enqueue_run` with the LOCAL Monday as `run_date` unless it already exists.
   Idempotent twice over: the pass skips the `(brand, run_date)` that exist, and
   `UNIQUE (brand_id, trigger, run_date)` absorbs a race between two workers.
2. **Recover** — a run `running` for longer than `reel_runs.STALE_AFTER` (30 min) was left
   by a process that died: it goes back to `queued`, or ends `error` once it was claimed
   `reel_runs.MAX_ATTEMPTS` (3) times. Both writes are fenced on the claim's `started_at`,
   through `tenant_session`.
3. **Run** — up to `batch` runs, one at a time: the next run (`manual` before `weekly`,
   then the oldest), then `reel_runs.run`, which claims it and is the only door that pays.

There is no switch of its own (architect, 2026-11-04): the screen reads only what the
runs store, so with the worker off every screen would stay empty. The kill switch is the
metered gate's (`QUALIFY_SCRAPECREATORS_PAID`, ADR 42 R2): with it off a run reads nothing
and ends `budget_stopped`. A run costs at most ~88 credits (12 accounts × 4 pages + 40
transcripts), under R5's 150 a day.

`reel_runs.RunInterrupted` (the SIGTERM of a deploy, raised by the CLI's signal handler
while a run is in flight) is never caught here: `run` releases its run to the queue and
the exception stops the loop. Anything else that fails is logged and the pass goes on;
one brand or one run that fails never stops the others.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_api.referentes import reel_runs
from qualify_api.referentes.reel_queue import ReelQueue, StaleRun
from qualify_api.referentes.reel_schedule import (
    DUE_FOR,
    INACTIVE_AFTER,
    WeeklyDue,
    WeeklyPlan,
    plan_weekly,
)
from qualify_api.referentes.reel_store import (
    STATUS_ERROR,
    STATUS_QUEUED,
    TRIGGER_WEEKLY,
    ReelRunStore,
)

logger = logging.getLogger("qualify_api.referentes.worker")

#: ADR 42 §4: the overdue weekly runs are enqueued every 15 min.
SCHEDULE_EVERY = timedelta(minutes=15)
#: A step that keeps failing the same way (the door's password not set yet, the database
#: away) is logged with its traceback at most this often, not on every 5-second pass.
LOG_FAILURE_EVERY_SECONDS = 60.0

RunFn = Callable[[UUID, UUID], reel_runs.RunOutcome]


def production_run(tenant_id: UUID, run_id: UUID) -> reel_runs.RunOutcome:
    """The real run: the vendor and Claude for real, through `tenant_session(tenant_id)`."""
    return reel_runs.run(tenant_id, run_id)


@dataclass(frozen=True)
class RecoveredRun:
    run_id: UUID
    tenant_id: UUID
    #: `queued` (back in line) or `error` (its attempts were spent).
    status: str


@dataclass
class PassReport:
    started_at: datetime
    dry_run: bool = False
    #: Set when this pass scheduled (at most every `SCHEDULE_EVERY`).
    plan: WeeklyPlan | None = None
    #: The weekly runs this pass enqueued (with `dry_run`: would have enqueued).
    enqueued: list[WeeklyDue] = field(default_factory=list)
    recovered: list[RecoveredRun] = field(default_factory=list)
    outcomes: list[reel_runs.RunOutcome] = field(default_factory=list)
    #: Runs whose `run` raised (it ends its own failures `error`; this is what escaped
    #: it, e.g. the database going away — the run stays `running` until recovered).
    run_errors: int = 0
    #: The steps that failed outright (`schedule`, `recover`, `next`).
    errors: list[str] = field(default_factory=list)

    @property
    def started(self) -> int:
        """Runs this pass tried to start."""
        return len(self.outcomes) + self.run_errors


class ReelsWorker:
    """Everything a pass touches is injected; `clock` returns an aware UTC `datetime`."""

    def __init__(
        self,
        queue: ReelQueue,
        store: ReelRunStore,
        *,
        run: RunFn = production_run,
        batch: int = 1,
        schedule_every: timedelta = SCHEDULE_EVERY,
        stale_after: timedelta = reel_runs.STALE_AFTER,
        max_attempts: int = reel_runs.MAX_ATTEMPTS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        should_stop: Callable[[], bool] = lambda: False,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch < 1:
            raise ValueError("batch must be at least 1")
        self.queue = queue
        self.store = store
        self._run = run
        self.batch = batch
        self.schedule_every = schedule_every
        self.stale_after = stale_after
        self.max_attempts = max_attempts
        self._clock = clock
        self._should_stop = should_stop
        self._monotonic = monotonic
        self._next_schedule: datetime | None = None
        self._failure_logged: dict[str, float] = {}
        #: True while `reel_runs.run` is in flight: the CLI's signal handler raises
        #: `RunInterrupted` into it only then.
        self.in_run = False

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("the reels worker's clock must be timezone-aware")
        return now

    def _failed(self, step: str, report: PassReport, exc: Exception) -> None:
        report.errors.append(f"{step}:{type(exc).__name__}")
        moment = self._monotonic()
        last = self._failure_logged.get(step)
        if last is None or moment - last >= LOG_FAILURE_EVERY_SECONDS:
            self._failure_logged[step] = moment
            logger.exception("reels.worker.%s_failed", step)
        else:
            logger.debug("reels.worker.%s_failed again: %s", step, type(exc).__name__)

    # -- a pass ----------------------------------------------------------------------

    def pass_once(self, *, force_schedule: bool = False, dry_run: bool = False) -> PassReport:
        """One pass. `dry_run`: only the scheduling, read-only — what would be enqueued."""
        now = self._now()
        report = PassReport(started_at=now, dry_run=dry_run)
        if dry_run:
            self._schedule(now, report)
            return report
        if force_schedule or self._next_schedule is None or now >= self._next_schedule:
            self._next_schedule = now + self.schedule_every
            self._schedule(now, report)
        self._recover(now, report)
        self._start_runs(report)
        return report

    # -- 1. schedule -------------------------------------------------------------------

    def _schedule(self, now: datetime, report: PassReport) -> None:
        try:
            # every brand that can be active in an open window: opened since 14 days
            # before the earliest Monday 06:00 whose window is still open
            brands = self.queue.opened_brands(since=now - DUE_FOR - INACTIVE_AFTER)
            plan = plan_weekly(brands, now)
            existing = self.queue.existing_weekly(plan.due)
        except Exception as exc:  # noqa: BLE001 — logged; the pass goes on
            self._failed("schedule", report, exc)
            return
        report.plan = plan
        for brand in plan.bad_timezone:
            logger.warning(
                "reels.worker.bad_timezone tenant_id=%s brand_id=%s timezone=%r",
                brand.tenant_id,
                brand.brand_id,
                brand.timezone,
            )
        for due in plan.due:
            if (due.brand_id, due.run_date) in existing:
                continue
            if report.dry_run:
                report.enqueued.append(due)
                continue
            try:
                reel_runs.enqueue_run(
                    due.tenant_id,
                    due.brand_id,
                    TRIGGER_WEEKLY,
                    run_date=due.run_date,
                    store=self.store,
                    clock=now.timestamp,
                )
            except Exception:  # noqa: BLE001 — one brand must not stop the others
                logger.exception(
                    "reels.worker.enqueue_failed tenant_id=%s brand_id=%s run_date=%s",
                    due.tenant_id,
                    due.brand_id,
                    due.run_date,
                )
                continue
            report.enqueued.append(due)

    # -- 2. recover --------------------------------------------------------------------

    def _recover(self, now: datetime, report: PassReport) -> None:
        try:
            stale = self.queue.stale_runs(started_before=now - self.stale_after)
        except Exception as exc:  # noqa: BLE001 — logged; the pass goes on
            self._failed("recover", report, exc)
            return
        for item in stale:
            try:
                status = self._recover_one(item, now)
            except Exception:  # noqa: BLE001 — one run must not stop the others
                logger.exception("reels.worker.recover_failed run_id=%s", item.run_id)
                continue
            if status is None:
                continue  # it moved meanwhile (finished, or recovered by another worker)
            report.recovered.append(RecoveredRun(item.run_id, item.tenant_id, status))
            logger.warning(
                "reels.worker.recovered run_id=%s tenant_id=%s attempts=%d status=%s",
                item.run_id,
                item.tenant_id,
                item.attempts,
                status,
            )

    def _recover_one(self, item: StaleRun, now: datetime) -> str | None:
        if item.attempts >= self.max_attempts:
            done = self.store.abandon(
                item.tenant_id, item.run_id, started_at=item.started_at, now=now
            )
            return STATUS_ERROR if done else None
        done = self.store.release(item.tenant_id, item.run_id, started_at=item.started_at)
        return STATUS_QUEUED if done else None

    # -- 3. run --------------------------------------------------------------------------

    def _start_runs(self, report: PassReport) -> None:
        tried: set[UUID] = set()
        for _ in range(self.batch):
            if self._should_stop():
                return
            try:
                nxt = self.queue.next_run()
            except Exception as exc:  # noqa: BLE001 — logged; the next pass retries
                self._failed("next", report, exc)
                return
            if nxt is None or nxt.run_id in tried:
                return  # nothing queued, or a run that could not even be claimed
            tried.add(nxt.run_id)
            try:
                self.in_run = True
                report.outcomes.append(self._run(nxt.tenant_id, nxt.run_id))
            except Exception:  # noqa: BLE001 — one run must not stop the others
                # `run` finishes its own failures; what escaped it left the run
                # `running`, and the recovery takes it back after `STALE_AFTER`.
                logger.exception(
                    "reels.worker.run_failed run_id=%s tenant_id=%s", nxt.run_id, nxt.tenant_id
                )
                report.run_errors += 1
            finally:
                self.in_run = False


__all__ = [
    "LOG_FAILURE_EVERY_SECONDS",
    "SCHEDULE_EVERY",
    "PassReport",
    "RecoveredRun",
    "ReelsWorker",
    "RunFn",
    "production_run",
]
