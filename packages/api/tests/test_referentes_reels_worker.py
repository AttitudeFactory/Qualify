"""The `reels-worker` (ADR 42 R8, m-24854855) offline, under a fake clock: `ReelsWorker`
over `MemoryReelQueue` + `MemoryReelRunStore`, and the CLI loop. Nothing here can reach
ScrapeCreators or Anthropic: the runs either never start (a recording fake) or are R4's
real `run` with no brief, which ends `check_failed` before any paid call — and a vendor
fake that fails the test if it is ever called.

The ticket's acceptance criteria:
1. at Monday 06:00 in America/Bogota a pass enqueues one weekly run per active brand and
   none for an inactive one (and none at 05:59);
2. a second pass does not duplicate — the pass skips what exists, and
   `UNIQUE (brand_id, trigger, run_date)` absorbs a race;
3. a run left `running` by a dead process goes back to the queue after 30 min (and runs
   again), and ends `error` after 3 attempts;
plus: manual runs start before weekly ones, SIGTERM puts the run in flight back in the
queue, `--dry-run` writes nothing, `--tenant` touches no one else."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes import worker as cli
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_store import (
    STATUS_CHECK_FAILED,
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_RUNNING,
    MemoryReelRunStore,
    RunRecord,
)
from qualify_api.referentes.reel_worker import PassReport, ReelsWorker

BOGOTA = "America/Bogota"
MONDAY = date(2026, 11, 9)
#: Monday 2026-11-09 06:00 in Bogotá (UTC-5).
SIX_AM = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000b2")


class Clock:
    def __init__(self, now: datetime = SIX_AM) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def epoch(self) -> float:
        return self.now.timestamp()


class Runs:
    """Records the runs the worker starts, without running them."""

    def __init__(self) -> None:
        self.started: list[tuple[UUID, UUID]] = []

    def __call__(self, tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        self.started.append((tenant_id, run_id))
        return rr.RunOutcome(run_id=run_id, status=STATUS_QUEUED, ran=False)


def _no_vendor(*_: Any, **__: Any) -> Any:
    raise AssertionError("the vendor must never be called here")


def real_run(store: MemoryReelRunStore, clock: Clock) -> Callable[[UUID, UUID], rr.RunOutcome]:
    """R4's real `run`, with no brief: it claims, ends `check_failed`, pays nothing."""

    def go(tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        return rr.run(
            tenant_id,
            run_id,
            store=store,
            brief=lambda tenant, brand: None,
            fetch=_no_vendor,
            transcribe_fetch=_no_vendor,
            review=_no_vendor,
            clock=clock.epoch,
            sleep=lambda seconds: None,
        )

    return go


def _opened(store: MemoryReelRunStore, tenant: UUID, *, days_ago: float) -> UUID:
    brand = uuid4()
    store.timezones[tenant] = BOGOTA
    store.activity[brand] = (tenant, SIX_AM - timedelta(days=days_ago))
    return brand


def _worker(
    store: MemoryReelRunStore,
    clock: Clock,
    *,
    run: Callable[[UUID, UUID], rr.RunOutcome] | None = None,
    tenants: list[UUID] | None = None,
    **kwargs: Any,
) -> ReelsWorker:
    return ReelsWorker(
        MemoryReelQueue(store, tenants=tenants),
        store,
        run=run or Runs(),
        clock=clock,
        **kwargs,
    )


def _weekly(store: MemoryReelRunStore) -> list[RunRecord]:
    return sorted(
        (r for r in store.runs.values() if r.trigger == "weekly"), key=lambda r: str(r.brand_id)
    )


# --------------------------------------------------------------------------------------
# criterion 1 — Monday 06:00 in America/Bogota
# --------------------------------------------------------------------------------------


def test_at_monday_six_in_bogota_one_run_per_active_brand_and_none_for_an_inactive_one() -> None:
    store, clock = MemoryReelRunStore(), Clock(SIX_AM - timedelta(minutes=1))
    active_a = _opened(store, TENANT_A, days_ago=2)
    active_b = _opened(store, TENANT_B, days_ago=13)
    _opened(store, TENANT_A, days_ago=14.5)  # inactive: just past the 14 days
    _opened(store, TENANT_B, days_ago=20)  # inactive: not even read
    # (a brand never opened has no activity row at all: it is not listed either)
    worker = _worker(store, clock)

    early = worker.pass_once()  # 05:59 local: nothing is due yet
    assert early.enqueued == [] and store.runs == {}

    clock.now = SIX_AM
    report = worker.pass_once(force_schedule=True)
    runs = _weekly(store)
    assert {(r.tenant_id, r.brand_id) for r in runs} == {
        (TENANT_A, active_a),
        (TENANT_B, active_b),
    }
    assert {r.run_date for r in runs} == {MONDAY}  # the LOCAL Monday, never the UTC date
    assert all(r.status == STATUS_QUEUED and r.days == 30 for r in runs)
    assert len(report.enqueued) == 2 and report.plan is not None and report.plan.inactive == 1


def test_a_worker_down_at_six_catches_up_within_the_day_but_not_later() -> None:
    store, clock = MemoryReelRunStore(), Clock(SIX_AM + timedelta(hours=23))
    _opened(store, TENANT_A, days_ago=1)
    assert len(_worker(store, clock).pass_once().enqueued) == 1

    late_store, late = MemoryReelRunStore(), Clock(SIX_AM + timedelta(hours=24))
    _opened(late_store, TENANT_A, days_ago=1)
    assert _worker(late_store, late).pass_once().enqueued == []


# --------------------------------------------------------------------------------------
# criterion 2 — a second pass does not duplicate
# --------------------------------------------------------------------------------------


def test_a_second_pass_does_not_duplicate() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    brand = _opened(store, TENANT_A, days_ago=1)
    worker = _worker(store, clock)
    assert len(worker.pass_once().enqueued) == 1
    clock.now += timedelta(minutes=20)  # past the 15-minute cadence: it schedules again
    second = worker.pass_once()
    assert second.plan is not None and len(second.plan.due) == 1  # still due...
    assert second.enqueued == []  # ...and already there
    assert [r.brand_id for r in _weekly(store)] == [brand]


def test_the_unique_row_absorbs_a_race_between_two_workers() -> None:
    """Two workers that both decide the run is missing make one row, not two."""

    class Blind(MemoryReelQueue):
        def existing_weekly(self, due: Any) -> set[tuple[UUID, date]]:
            return set()  # as if another worker inserted it right after this read

    store, clock = MemoryReelRunStore(), Clock()
    brand = _opened(store, TENANT_A, days_ago=1)
    for _ in range(2):
        ReelsWorker(Blind(store), store, run=Runs(), clock=clock).pass_once()
    assert [r.brand_id for r in _weekly(store)] == [brand]


def test_the_cadence_is_fifteen_minutes() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    _opened(store, TENANT_A, days_ago=1)
    worker = _worker(store, clock)
    assert worker.pass_once().plan is not None
    clock.now += timedelta(minutes=14)
    assert worker.pass_once().plan is None
    clock.now += timedelta(minutes=1)
    assert worker.pass_once().plan is not None


# --------------------------------------------------------------------------------------
# criterion 3 — a run left `running` by a dead process recovers by itself
# --------------------------------------------------------------------------------------


def _claimed_and_abandoned(store: MemoryReelRunStore, clock: Clock) -> RunRecord:
    """A queued run that a process claimed and then died with (never finished)."""
    queued = rr.enqueue_run(TENANT_A, uuid4(), "manual", store=store, clock=clock.epoch)
    claimed = store.claim(TENANT_A, queued.id, now=clock.now)
    assert claimed is not None and claimed.attempts == 1
    return claimed


def test_a_run_left_running_goes_back_to_the_queue_after_thirty_minutes() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    dead = _claimed_and_abandoned(store, clock)
    worker = _worker(store, clock, run=real_run(store, clock))

    clock.now += timedelta(minutes=29)
    report = worker.pass_once()
    assert report.recovered == [] and store.runs[dead.id].status == STATUS_RUNNING

    clock.now += timedelta(minutes=2)  # 31 min after its claim
    report = worker.pass_once()
    assert [(r.run_id, r.status) for r in report.recovered] == [(dead.id, STATUS_QUEUED)]
    # ...and the same pass started it again: claimed a second time, then ended
    assert [o.run_id for o in report.outcomes] == [dead.id]
    record = store.runs[dead.id]
    assert record.status == STATUS_CHECK_FAILED and record.attempts == 2
    assert record.queued_at == dead.queued_at  # its place in line and its age are kept


def test_after_three_attempts_a_stale_run_ends_error_and_never_runs_again() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    dead = _claimed_and_abandoned(store, clock)
    store.runs[dead.id] = replace(store.runs[dead.id], attempts=3)
    runs = Runs()
    clock.now += timedelta(minutes=31)
    report = _worker(store, clock, run=runs).pass_once()
    assert [(r.run_id, r.status) for r in report.recovered] == [(dead.id, STATUS_ERROR)]
    record = store.runs[dead.id]
    assert record.status == STATUS_ERROR and record.finished_at == clock.now
    assert runs.started == []  # nothing left in the queue


def test_a_stale_run_that_moved_meanwhile_is_left_alone() -> None:
    """The recovery is fenced on the claim's `started_at`: a run another worker already
    recovered and claimed again is not touched."""
    store, clock = MemoryReelRunStore(), Clock()
    dead = _claimed_and_abandoned(store, clock)
    clock.now += timedelta(minutes=31)
    assert store.release(TENANT_A, dead.id, started_at=dead.started_at)  # another worker
    again = store.claim(TENANT_A, dead.id, now=clock.now)
    assert again is not None
    assert store.release(TENANT_A, dead.id, started_at=dead.started_at) is False
    assert store.abandon(TENANT_A, dead.id, started_at=dead.started_at, now=clock.now) is False
    assert store.runs[dead.id].status == STATUS_RUNNING and store.runs[dead.id].attempts == 2


# --------------------------------------------------------------------------------------
# which run first, and the stop
# --------------------------------------------------------------------------------------


def test_manual_runs_start_before_weekly_ones() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    weekly = rr.enqueue_run(
        TENANT_A, uuid4(), "weekly", run_date=MONDAY, store=store, clock=clock.epoch
    )
    clock.now += timedelta(minutes=5)
    manual = rr.enqueue_run(TENANT_B, uuid4(), "manual", store=store, clock=clock.epoch)
    runs = Runs()
    _worker(store, clock, run=runs, batch=2).pass_once()
    assert [run_id for _, run_id in runs.started] == [manual.id]  # the fake leaves it
    # queued, so the pass stops instead of trying it twice
    store.runs[manual.id] = replace(store.runs[manual.id], status=STATUS_CHECK_FAILED)
    _worker(store, clock, run=runs).pass_once()
    assert [run_id for _, run_id in runs.started] == [manual.id, weekly.id]


def test_sigterm_puts_the_run_in_flight_back_in_the_queue_and_stops_the_loop() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    queued = rr.enqueue_run(TENANT_A, uuid4(), "manual", store=store, clock=clock.epoch)

    def interrupted(tenant_id: UUID, brand_id: UUID) -> Any:
        raise rr.RunInterrupted("signal 15")  # what the handler raises mid-run

    def run(tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        return rr.run(tenant_id, run_id, store=store, brief=interrupted, clock=clock.epoch)

    worker = _worker(store, clock, run=run)
    with pytest.raises(rr.RunInterrupted):
        worker.pass_once()
    record = store.runs[queued.id]
    assert record.status == STATUS_QUEUED and record.started_at is None
    assert record.attempts == 1 and worker.in_run is False
    # the CLI loop treats it as a clean stop
    assert cli.run_loop(worker, once=False, interval=1, stop=threading.Event()) == 0


def test_the_signal_handler_interrupts_only_a_run_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: dict[int, Any] = {}
    monkeypatch.setattr(signal, "signal", lambda num, handler: installed.update({num: handler}))
    worker = _worker(MemoryReelRunStore(), Clock())
    stop = threading.Event()
    cli.install_signals(stop, worker)
    handler = installed[signal.SIGTERM]

    handler(signal.SIGTERM, None)  # idle: only stops the loop
    assert stop.is_set()

    stop.clear()
    worker.in_run = True
    with pytest.raises(rr.RunInterrupted):
        handler(signal.SIGTERM, None)
    handler(signal.SIGTERM, None)  # a second signal never raises during the release


# --------------------------------------------------------------------------------------
# dry run and scope
# --------------------------------------------------------------------------------------


def test_dry_run_reports_what_it_would_enqueue_and_writes_nothing() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    brand = _opened(store, TENANT_A, days_ago=1)
    dead = _claimed_and_abandoned(store, clock)
    clock.now += timedelta(hours=1)
    writes = store.writes
    runs = Runs()
    report = _worker(store, clock, run=runs).pass_once(dry_run=True)
    assert [d.brand_id for d in report.enqueued] == [brand] and report.dry_run
    assert store.writes == writes and runs.started == []  # no enqueue, no recovery, no run
    assert store.runs[dead.id].status == STATUS_RUNNING


def test_a_scoped_worker_never_touches_another_tenant() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    _opened(store, TENANT_B, days_ago=1)
    other = rr.enqueue_run(TENANT_B, uuid4(), "manual", store=store, clock=clock.epoch)
    stale = store.claim(TENANT_B, other.id, now=clock.now)
    assert stale is not None
    clock.now += timedelta(hours=1)
    runs = Runs()
    report = _worker(store, clock, run=runs, tenants=[TENANT_A]).pass_once()
    assert report.enqueued == [] and report.recovered == [] and runs.started == []
    assert store.runs[other.id].status == STATUS_RUNNING


# --------------------------------------------------------------------------------------
# failures and the CLI
# --------------------------------------------------------------------------------------


def test_a_failing_step_is_reported_and_the_pass_goes_on() -> None:
    class Broken(MemoryReelQueue):
        def opened_brands(self, *, since: datetime) -> list[Any]:
            raise ConnectionError("door down")

    store, clock = MemoryReelRunStore(), Clock()
    queued = rr.enqueue_run(TENANT_A, uuid4(), "manual", store=store, clock=clock.epoch)
    runs = Runs()
    report = ReelsWorker(Broken(store), store, run=runs, clock=clock).pass_once()
    assert report.errors == ["schedule:ConnectionError"]
    assert runs.started == [(TENANT_A, queued.id)]  # the queue still ran


def test_a_run_that_raises_is_counted_and_the_loop_waits() -> None:
    store, clock = MemoryReelRunStore(), Clock()
    rr.enqueue_run(TENANT_A, uuid4(), "manual", store=store, clock=clock.epoch)

    def boom(tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        raise RuntimeError("database went away")

    worker = _worker(store, clock, run=boom, batch=3)
    report = worker.pass_once()
    assert report.run_errors == 1 and worker.in_run is False  # tried once, not three times
    assert cli.run_loop(worker, once=True, interval=1, stop=threading.Event()) == 1


class FakeWorker:
    """Stands in for `ReelsWorker` in the loop and the CLI."""

    def __init__(self, reports: list[PassReport], stop: threading.Event | None = None) -> None:
        self.reports = reports
        self.calls: list[tuple[bool, bool]] = []
        self.stop = stop
        self.in_run = False

    def pass_once(self, *, force_schedule: bool = False, dry_run: bool = False) -> PassReport:
        self.calls.append((force_schedule, dry_run))
        report = self.reports.pop(0)
        if not self.reports and self.stop is not None:
            self.stop.set()
        return report


def _ran(n: int = 1) -> PassReport:
    report = PassReport(started_at=SIX_AM)
    report.outcomes = [rr.RunOutcome(run_id=uuid4(), status="ok") for _ in range(n)]
    return report


def test_the_loop_goes_on_at_once_after_a_run_and_waits_when_idle() -> None:
    waits: list[float] = []

    class Stop(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            waits.append(timeout or 0)
            return len(waits) >= 1

    stop = Stop()
    worker = FakeWorker([_ran(), PassReport(started_at=SIX_AM)])
    assert cli.run_loop(worker, once=False, interval=5, stop=stop) == 0
    assert worker.calls == [(True, False), (False, False)]  # the first pass forced
    assert waits == [5]  # no wait after the run, one after the idle pass


def test_main_requires_a_scope_and_runs_one_pass_with_once() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--once"])
    with pytest.raises(SystemExit):
        cli.main(["--all-tenants", "--interval", "0.5"])
    built: list[tuple[Any, ...]] = []

    def make(tenant_ids: Any, **kwargs: Any) -> FakeWorker:
        built.append((tenant_ids, kwargs["batch"], kwargs["schedule_every"]))
        return FakeWorker([PassReport(started_at=SIX_AM)])

    code = cli.main(
        ["--tenant", str(TENANT_A), "--once", "--batch", "2"],
        make_worker=make,
        install_handlers=False,
    )
    assert code == 0
    assert built == [([TENANT_A], 2, timedelta(minutes=15))]


def test_main_dry_run_is_one_read_only_pass() -> None:
    worker = FakeWorker([PassReport(started_at=SIX_AM, dry_run=True)])
    code = cli.main(
        ["--all-tenants", "--dry-run"],
        make_worker=lambda tenant_ids, **_: worker,
        install_handlers=False,
    )
    assert code == 0 and worker.calls == [(True, True)]
