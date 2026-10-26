"""m-24852163 — the `creative-worker` loop, offline.

An in-memory `QueueStore` with the same rules as `job_queue` + migration 0096 (claim
token, write-once `vendor_task_id`, slots kept by a job with a vendor task, RLS as «a
business only sees its own rows») and a fake executor that counts what BytePlus would
bill. The SQL itself is pinned against Postgres in `test_creative_worker_db.py`.

Acceptance criteria covered here: a crash mid-job resumes by `vendor_task_id` without a
second submit nor a second charge; a 429 never fails the piece; downloads at once never
pass the gate (platform-engineer's verdict); the worker refuses a job its own business
cannot see.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.adapters.byteplus_ark import VendorBusy

from qualify_api.creative import job_queue as q
from qualify_api.creative.worker import lanes, runner
from qualify_api.creative.worker.downloads import DownloadGate
from qualify_api.creative.worker.executor import JobContext, TaskPoll
from qualify_api.creative.worker.runner import CreativeWorker, WorkerConfig, run_loop

POOL = "byteplus:seedance-2-5"
A = UUID("a0000000-0000-4000-8000-00000000000a")
B = UUID("b0000000-0000-4000-8000-00000000000b")
T0 = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.now

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self.now += delta


@dataclass
class Job:
    job_id: UUID
    tenant_id: UUID
    draft_id: UUID
    kind: str = q.KIND_PREVIEW
    lane: str = q.LANE_IMMEDIATE
    priority: int = 0
    vendor_model: str = POOL
    status: str = q.QUEUED
    claim_token: int = 0
    claimed_by: str | None = None
    lease_until: datetime | None = None
    attempts: int = 0
    vendor_task_id: str | None = None
    queued_at: datetime = T0
    not_before: datetime = T0
    last_error: str | None = None


@dataclass
class MemoryStore:
    """`job_queue`'s rules in memory; thread-safe like the database."""

    sizes: dict[str, int] = field(default_factory=lambda: {POOL: 10})
    jobs: dict[UUID, Job] = field(default_factory=dict)
    slots: dict[tuple[str, int], UUID | None] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        for pool, size in self.sizes.items():
            for n in range(1, size + 1):
                self.slots[(pool, n)] = None

    def add(self, tenant: UUID, **kw: Any) -> UUID:
        job = Job(job_id=uuid4(), tenant_id=tenant, draft_id=uuid4(), **kw)
        self.jobs[job.job_id] = job
        return job.job_id

    def slot_of(self, job_id: UUID) -> int | None:
        return next((n for (p, n), h in self.slots.items() if h == job_id), None)

    def _free_slot(self, job_id: UUID) -> None:
        for key, holder in self.slots.items():
            if holder == job_id:
                self.slots[key] = None

    # -- QueueStore ------------------------------------------------------------------------

    def recover(self, *, now: datetime, tenant_ids: Sequence[UUID] | None) -> q.Recovery:
        with self.lock:
            requeued = []
            for job in self.jobs.values():
                if tenant_ids is not None and job.tenant_id not in tenant_ids:
                    continue
                if job.status in q.IN_FLIGHT and job.lease_until and job.lease_until < now:
                    job.status, job.claimed_by, job.lease_until = q.QUEUED, None, None
                    job.claim_token += 1
                    requeued.append(job.job_id)
                    if job.vendor_task_id is None:
                        self._free_slot(job.job_id)
            return q.Recovery(requeued=tuple(requeued), released_slots=0, kept_slots=0)

    def _row(self, job: Job) -> q.QueueRow:
        return q.QueueRow(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            kind=job.kind,
            lane=job.lane,
            priority=job.priority,
            queued_at=job.queued_at,
            status=job.status,
            holds_slot=self.slot_of(job.job_id) is not None,
        )

    def claim_fair(
        self,
        *,
        vendor_model: str,
        size: int,
        worker_id: str,
        lease: timedelta,
        now: datetime,
        tenant_ids: Sequence[UUID] | None,
    ) -> q.ClaimedJob | None:
        with self.lock:
            pool_jobs = [j for j in self.jobs.values() if j.vendor_model == vendor_model]
            in_flight = [
                self._row(j)
                for j in pool_jobs
                if j.status in q.IN_FLIGHT or (j.status == q.QUEUED and self.slot_of(j.job_id))
            ]
            waiting = [
                self._row(j)
                for j in pool_jobs
                if j.status == q.QUEUED
                and j.not_before <= now
                and (tenant_ids is None or j.tenant_id in tenant_ids)
            ]
            pick = lanes.pick_next(waiting, in_flight, size=size, now=now)
            if pick is None:
                return None
            job = self.jobs[pick.job_id]
            slot = self.slot_of(job.job_id)
            if slot is None:
                free = [
                    n
                    for (p, n), h in sorted(self.slots.items())
                    if p == vendor_model and n <= size and h is None
                ]
                if not free:
                    return None
                slot = free[0]
                self.slots[(vendor_model, slot)] = job.job_id
            job.status, job.claimed_by = q.CLAIMED, worker_id
            job.claim_token += 1
            job.lease_until = now + lease
            job.attempts += 1
            return q.ClaimedJob(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                claim_token=job.claim_token,
                slot_no=slot,
            )

    def load(self, claim: q.ClaimedJob) -> q.JobRow | None:
        with self.lock:
            job = self.jobs.get(claim.job_id)
            if job is None or job.tenant_id != claim.tenant_id:  # RLS
                return None
            return q.JobRow(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                draft_id=job.draft_id,
                kind=job.kind,
                revision=1,
                position=0,
                vendor_model=job.vendor_model,
                lane=job.lane,
                priority=job.priority,
                status=job.status,
                claim_token=job.claim_token,
                vendor_task_id=job.vendor_task_id,
                queued_at=job.queued_at,
                deadline=None,
                attempts=job.attempts,
            )

    def _held(self, claim: q.ClaimedJob, statuses: frozenset[str]) -> Job | None:
        job = self.jobs.get(claim.job_id)
        if job and job.claim_token == claim.claim_token and job.status in statuses:
            return job
        return None

    def record_submission(self, claim: q.ClaimedJob, *, vendor_task_id: str, now: datetime) -> bool:
        with self.lock:
            job = self._held(claim, frozenset({q.CLAIMED}))
            if job is None or job.vendor_task_id is not None:
                return False
            job.vendor_task_id, job.status = vendor_task_id, q.SUBMITTED
            return True

    def renew(self, claim: q.ClaimedJob, *, lease: timedelta, now: datetime) -> bool:
        with self.lock:
            job = self._held(claim, q.IN_FLIGHT)
            if job is None:
                return False
            job.lease_until = now + lease
            return True

    def settle(
        self, claim: q.ClaimedJob, *, status: str, now: datetime, last_error: str | None
    ) -> bool:
        with self.lock:
            job = self._held(claim, q.IN_FLIGHT)
            if job is None:
                return False
            job.status, job.last_error = status, last_error
            return True

    def release(self, claim: q.ClaimedJob, *, now: datetime) -> bool:
        with self.lock:
            job = self.jobs[claim.job_id]
            if job.status not in q.TERMINAL:
                return False
            self._free_slot(job.job_id)
            job.lease_until = None
            return True

    def defer(self, claim: q.ClaimedJob, *, until: datetime, now: datetime) -> bool:
        with self.lock:
            job = self._held(claim, frozenset({q.CLAIMED}))
            if job is None or job.vendor_task_id is not None:
                return False
            job.not_before = until
            return self._hand_back(job, count_attempt=False)

    def hand_back(self, claim: q.ClaimedJob, *, now: datetime) -> bool:
        with self.lock:
            job = self._held(claim, q.IN_FLIGHT)
            return job is not None and self._hand_back(job, count_attempt=True)

    def _hand_back(self, job: Job, *, count_attempt: bool) -> bool:
        job.status, job.claimed_by, job.lease_until = q.QUEUED, None, None
        job.claim_token += 1
        if not count_attempt:
            job.attempts = max(job.attempts - 1, 0)
        if job.vendor_task_id is None:
            self._free_slot(job.job_id)
        return True


class Crash(BaseException):
    """The process dies (not an `Exception`: nothing in the worker catches it)."""


@dataclass
class FakeBytePlus:
    """Counts what BytePlus would bill: one charge per accepted submit."""

    polls_until_done: int = 1
    final_status: str = "succeeded"
    busy: int = 0  # the first N submits answer 429
    fail_submit: bool = False
    crash_on_poll: bool = False
    finish_sleep: float = 0.0
    finish_raises: bool = False
    submits: list[UUID] = field(default_factory=list)
    finished: list[tuple[UUID, str | None, str]] = field(default_factory=list)
    contexts: list[JobContext] = field(default_factory=list)
    _polls: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def submit(self, job: JobContext) -> str:
        with self._lock:
            self.contexts.append(job)
            if self.busy:
                self.busy -= 1
                raise VendorBusy(429, "QuotaExceeded", "busy", retry_after_seconds=60.0)
            if self.fail_submit:
                raise RuntimeError("bad request")
            self.submits.append(job.job_id)
            return f"cgt-{len(self.submits)}"

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll:
        if self.crash_on_poll:
            raise Crash
        with self._lock:
            seen = self._polls[vendor_task_id] = self._polls.get(vendor_task_id, 0) + 1
        if seen >= self.polls_until_done:
            return TaskPoll(self.final_status)
        return TaskPoll("running", next_poll_seconds=0)

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        if self.finish_raises:
            raise RuntimeError("R2 down")
        if self.finish_sleep:
            time.sleep(self.finish_sleep)
        with self._lock:
            self.finished.append((job.job_id, vendor_task_id, status))


def make_worker(
    store: MemoryStore,
    vendor: FakeBytePlus,
    clock: Clock,
    *,
    downloads: int = 2,
    tenants: Sequence[UUID] | None = None,
) -> CreativeWorker:
    return CreativeWorker(
        store,
        {POOL: vendor},
        WorkerConfig(pools=dict(store.sizes), tenant_ids=tenants, worker_id="w-test"),
        downloads=DownloadGate(downloads),
        clock=clock,
    )


def one(worker: CreativeWorker) -> q.ClaimedJob:
    claims = worker.claim_round(1)
    assert len(claims) == 1
    return claims[0]


# -- the happy path ------------------------------------------------------------------------


def test_a_job_is_submitted_once_polled_finished_settled_and_released() -> None:
    store, vendor, clock = MemoryStore(), FakeBytePlus(polls_until_done=3), Clock()
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)
    claim = one(worker)

    assert worker.process(claim) == runner.SUCCEEDED_OUTCOME
    job = store.jobs[job_id]
    assert (job.status, job.vendor_task_id, job.attempts) == (q.SUCCEEDED, "cgt-1", 1)
    assert vendor.submits == [job_id]
    assert vendor.finished == [(job_id, "cgt-1", "succeeded")]
    assert store.slot_of(job_id) is None
    ctx = vendor.contexts[0]
    assert (ctx.lane, ctx.vendor_priority) == (lanes.STANDARD, lanes.VENDOR_PRIORITY["standard"])


def test_a_failed_task_fails_the_job_and_frees_the_slot() -> None:
    store, vendor, clock = MemoryStore(), FakeBytePlus(final_status="expired"), Clock()
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)
    assert worker.process(one(worker)) == runner.FAILED_OUTCOME
    assert store.jobs[job_id].status == q.FAILED
    assert store.jobs[job_id].last_error == "expired"
    assert vendor.finished == [(job_id, "cgt-1", "expired")]
    assert store.slot_of(job_id) is None


def test_a_rejected_submit_is_not_billed_and_fails_the_piece() -> None:
    store, vendor, clock = MemoryStore(), FakeBytePlus(fail_submit=True), Clock()
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)
    assert worker.process(one(worker)) == runner.FAILED_OUTCOME
    assert vendor.submits == []
    assert vendor.finished == [(job_id, None, "failed")]
    assert store.jobs[job_id].last_error == "RuntimeError"


# -- acceptance criteria -----------------------------------------------------------------


def test_ac_a_crash_mid_job_resumes_by_vendor_task_id_without_paying_twice() -> None:
    store, clock = MemoryStore(), Clock()
    vendor = FakeBytePlus(crash_on_poll=True)
    job_id = store.add(A)
    first = make_worker(store, vendor, clock)
    claim = one(first)
    with pytest.raises(Crash):
        first.process(claim)  # submitted, task id recorded, then the process died
    assert store.jobs[job_id].vendor_task_id == "cgt-1"
    assert store.slot_of(job_id) is not None

    # the lease runs out; a new worker recovers it — the job keeps its slot
    clock.advance(runner.LEASE + timedelta(seconds=1))
    vendor.crash_on_poll = False
    second = make_worker(store, vendor, clock)
    second.recover()
    assert store.jobs[job_id].status == q.QUEUED and store.slot_of(job_id) is not None

    assert second.process(one(second)) == runner.SUCCEEDED_OUTCOME
    assert vendor.submits == [job_id]  # one submit, one charge
    assert vendor.finished == [(job_id, "cgt-1", "succeeded")]
    assert store.jobs[job_id].status == q.SUCCEEDED


def test_ac_a_429_puts_the_job_back_without_failing_the_piece() -> None:
    store, vendor, clock = MemoryStore(), FakeBytePlus(busy=1), Clock()
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)

    assert worker.process(one(worker)) == runner.DEFERRED
    job = store.jobs[job_id]
    assert job.status == q.QUEUED and job.status != q.FAILED
    assert job.attempts == 0  # a 429 is not an attempt
    assert job.not_before == T0 + timedelta(seconds=60)
    assert store.slot_of(job_id) is None
    assert vendor.finished == []  # the piece was never failed
    assert worker.claim_round(1) == []  # not before the vendor's suggested wait

    clock.advance(timedelta(seconds=61))
    assert worker.process(one(worker)) == runner.SUCCEEDED_OUTCOME
    assert vendor.submits == [job_id]


def test_ac_downloads_at_once_never_pass_the_gate() -> None:
    """Platform-engineer's verdict: ten tasks ending together download two at a time."""
    store, clock = MemoryStore(), Clock()
    vendor = FakeBytePlus(finish_sleep=0.05)
    tenants = [uuid4() for _ in range(10)]
    for tenant in tenants:
        store.add(tenant, kind=q.KIND_FINAL)  # finals: 10 at once (reserved + standard)
    worker = make_worker(store, vendor, clock, downloads=2)

    assert run_loop(worker, once=True) == 0
    assert len(vendor.finished) == 10
    assert worker.downloads.peak == 2


def test_the_worker_refuses_a_job_its_own_business_cannot_see() -> None:
    """Security review threat #1: a claim handed to the wrong business's session finds
    nothing (RLS) and the worker fails closed — no submit, the job goes back."""
    store, vendor, clock = MemoryStore(), FakeBytePlus(), Clock()
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)
    claim = one(worker)
    forged = q.ClaimedJob(
        job_id=claim.job_id, tenant_id=B, claim_token=claim.claim_token, slot_no=claim.slot_no
    )
    assert worker.process(forged) == runner.MISSING
    assert vendor.submits == [] and vendor.finished == []
    assert store.jobs[job_id].status == q.QUEUED  # handed back for a proper claim
    assert store.slot_of(job_id) is None


def test_a_scoped_worker_only_claims_its_tenants() -> None:
    store, vendor, clock = MemoryStore(), FakeBytePlus(), Clock()
    store.add(B)
    mine = store.add(A)
    worker = make_worker(store, vendor, clock, tenants=[A])
    claims = worker.claim_round(10)
    assert [c.job_id for c in claims] == [mine]


# -- claims lost, shutdown, finish errors ------------------------------------------------


def test_a_lost_claim_stops_the_worker_without_writing() -> None:
    store, clock = MemoryStore(), Clock()
    vendor = FakeBytePlus(polls_until_done=5)
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)
    claim = one(worker)
    original_poll = vendor.poll

    def poll_and_steal(job: JobContext, task: str) -> TaskPoll:
        store.jobs[job_id].claim_token += 1  # another worker took over
        return original_poll(job, task)

    vendor.poll = poll_and_steal  # type: ignore[method-assign]
    assert worker.process(claim) == runner.LOST
    assert store.jobs[job_id].status == q.SUBMITTED
    assert vendor.finished == []


def test_shutdown_hands_back_a_submitted_job_keeping_its_slot() -> None:
    store, clock = MemoryStore(), Clock()
    vendor = FakeBytePlus(polls_until_done=1000)
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)
    claim = one(worker)
    original_poll = vendor.poll

    def poll_then_stop(job: JobContext, task: str) -> TaskPoll:
        worker.stop.set()
        return original_poll(job, task)

    vendor.poll = poll_then_stop  # type: ignore[method-assign]
    assert worker.process(claim) == runner.INTERRUPTED
    job = store.jobs[job_id]
    assert job.status == q.QUEUED and job.vendor_task_id == "cgt-1"
    assert store.slot_of(job_id) is not None  # BytePlus still counts the task


def test_a_failing_finish_leaves_the_job_for_recovery() -> None:
    store, vendor, clock = MemoryStore(), FakeBytePlus(finish_raises=True), Clock()
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)
    assert worker.process(one(worker)) == runner.FINISH_ERROR
    assert store.jobs[job_id].status == q.SUBMITTED  # lease runs out → requeued → re-polled

    clock.advance(runner.LEASE + timedelta(seconds=1))
    worker.recover()
    vendor.finish_raises = False
    assert worker.process(one(worker)) == runner.SUCCEEDED_OUTCOME
    assert vendor.submits == [job_id]


def test_a_finish_that_keeps_failing_is_settled_failed_eventually() -> None:
    store, vendor, clock = MemoryStore(), FakeBytePlus(finish_raises=True), Clock()
    job_id = store.add(A, attempts=runner.MAX_FINISH_ATTEMPTS)
    worker = make_worker(store, vendor, clock)
    assert worker.process(one(worker)) == runner.FAILED_OUTCOME
    assert store.jobs[job_id].last_error == "finish_failed"
    assert store.slot_of(job_id) is None


def test_polling_errors_hand_the_job_back_after_a_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "POLL_ERROR_WAIT_SECONDS", 0)
    store, vendor, clock = MemoryStore(), FakeBytePlus(), Clock()
    job_id = store.add(A)
    worker = make_worker(store, vendor, clock)

    def broken(job: JobContext, task: str) -> TaskPoll:
        raise ConnectionError("network")

    vendor.poll = broken  # type: ignore[method-assign]
    assert worker.process(one(worker)) == runner.INTERRUPTED
    assert store.jobs[job_id].status == q.QUEUED
    assert store.slot_of(job_id) is not None
    assert vendor.submits == [job_id]


# -- the loop --------------------------------------------------------------------------


def test_the_loop_runs_the_recovery_sidecar_and_never_claims_without_an_executor() -> None:
    store, clock = MemoryStore(), Clock()
    store.add(A)
    passes: list[int] = []
    worker = CreativeWorker(
        store,
        {},
        WorkerConfig(pools=dict(store.sizes), tenant_ids=None, worker_id="w"),
        downloads=DownloadGate(2),
        clock=clock,
    )
    assert run_loop(worker, once=True, sidecar=lambda: passes.append(1)) == 0
    assert passes == [1]
    assert all(job.status == q.QUEUED for job in store.jobs.values())


def test_the_loop_survives_a_queue_door_that_cannot_connect() -> None:
    from sqlalchemy.exc import OperationalError

    class DoorDown(MemoryStore):
        def recover(self, **kw: Any) -> q.Recovery:  # type: ignore[override]
            raise OperationalError("SELECT 1", {}, Exception("role is not permitted to log in"))

    store, clock = DoorDown(), Clock()
    passes: list[int] = []
    worker = make_worker(store, FakeBytePlus(), clock)
    assert run_loop(worker, once=True, sidecar=lambda: passes.append(1)) == 0
    assert passes == [1]  # the m-24852492 recovery still runs


def test_the_cli_runs_one_round_with_a_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative.worker import __main__ as cli

    monkeypatch.delenv(q.POOLS_ENV, raising=False)
    store = MemoryStore()
    past = datetime.now(UTC) - timedelta(minutes=1)  # the CLI runs on the real clock
    store.add(A, queued_at=past, not_before=past)
    passes: list[int] = []
    code = cli.main(
        ["--tenant", str(A), "--once"],
        store=store,
        executors={POOL: FakeBytePlus()},
        recovery=lambda: passes.append(1),
        install_signals=False,
    )
    assert code == 0 and passes == [1]
    assert [job.status for job in store.jobs.values()] == [q.SUCCEEDED]


def test_the_cli_requires_a_scope() -> None:
    from qualify_api.creative.worker import __main__ as cli

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_the_cli_refuses_a_malformed_pool_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative.worker import __main__ as cli

    monkeypatch.setenv(q.POOLS_ENV, "byteplus:seedance-2-5")
    assert (
        cli.main(
            ["--all-tenants", "--once"],
            store=MemoryStore(),
            executors={},
            recovery=lambda: None,
            install_signals=False,
        )
        == 2
    )


def test_production_registers_real_executors_for_both_vendor_pools() -> None:
    from qualify_api.creative.worker import __main__ as cli
    from qualify_api.creative.worker.pipeline import PipelineExecutor

    executors = cli.production_executors()
    assert set(executors) == set(q.DEFAULT_POOL_SIZES)
    assert all(isinstance(executor, PipelineExecutor) for executor in executors.values())
