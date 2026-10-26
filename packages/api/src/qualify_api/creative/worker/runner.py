"""The `creative-worker` loop: claim fairly, submit once, poll by id, settle (m-24852163).

ADR 41 §2.3, per round:

1. **Recover** (`store.recover`): jobs whose lease ran out go back to the queue; a job
   that already has a BytePlus task keeps its slot and is only polled again.
2. **Claim** per pool that has an executor, as long as a slot is free: the fair pick of
   `lanes.pick_next` (lanes, 3 reserved slots, 2 per business, aging), claimed with its
   slot in one transaction (`store.claim_fair`).
3. **Process** every claimed job in its own thread (`process`), through
   `tenant_session(claim.tenant_id)` for everything about its content:
   read the job → submit (only when it has no `vendor_task_id`) → write the task id
   BEFORE waiting → poll by id, renewing the lease → `finish` (the download holds the
   `DownloadGate`) → settle → release the slot.

Guarantees:

- **Never sent twice, never paid twice:** a job with a `vendor_task_id` is never
  submitted again, only polled — after a crash, a restart, a lost lease or a deploy. The
  id is write-once in the database (trigger of 0096).
- **429 is not a failure:** `VendorBusy` → `store.defer` (the job waits
  `retry_after_seconds`, its attempt is not counted) and the slot is freed.
- **A lost claim writes nothing:** every write carries the claim token; the worker stops
  working on a job as soon as a renewal fails.
- **Shutdown** (SIGTERM on deploy): jobs not yet sent go back to the queue at once; jobs
  already sent are handed back keeping their slot, and the next worker polls them.

Beside the rounds, the worker runs the recovery of billed BytePlus videos of m-24852492
(`creative.vendor_recovery`, drafts whose thread went quiet), moved here from the calendar
worker: in its own thread, at most one pass at a time, every `RECOVERY_EVERY_SECONDS`.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import VendorBusy
from sqlalchemy.exc import OperationalError

from qualify_api.creative import job_queue as q
from qualify_api.creative.queue_dispatch import SubmissionUncertain
from qualify_api.creative.vendor_timings import utcnow
from qualify_api.creative.worker import lanes
from qualify_api.creative.worker.downloads import DownloadGate
from qualify_api.creative.worker.executor import SUCCEEDED, JobContext, JobExecutor
from qualify_api.creative.worker.store import QueueStore

logger = logging.getLogger("qualify_api.creative.worker")

#: A claim lives this long without a renewal; the worker renews on every poll (≤ 60 s).
LEASE = timedelta(minutes=5)
#: Seconds between rounds (claims are cheap: one indexed query per pool).
DEFAULT_INTERVAL_SECONDS = 2.0
#: Lease recovery and the m-24852492 recovery pass.
RECOVER_EVERY_SECONDS = 30.0
RECOVERY_EVERY_SECONDS = 60.0
#: Polling errors in a row before the job is handed back for a later claim.
MAX_POLL_ERRORS = 10
POLL_ERROR_WAIT_SECONDS = 10.0
#: Claims of one job whose `finish` keeps failing before it is settled as failed.
MAX_FINISH_ATTEMPTS = 6

SUCCEEDED_OUTCOME = "succeeded"
FAILED_OUTCOME = "failed"
DEFERRED = "deferred"  # BytePlus busy: back in the queue for later, not a failure
LOST = "lost"  # another claim took over: nothing written
INTERRUPTED = "interrupted"  # shutdown or repeated polling errors: handed back
FINISH_ERROR = "finish_error"  # the result could not be stored yet: retried by recovery
MISSING = "missing"  # the claimed row is not visible to its own business


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass(frozen=True)
class WorkerConfig:
    pools: Mapping[str, int]  # pool -> configured slots (`job_queue.parse_vendor_pools`)
    tenant_ids: Sequence[UUID] | None  # None = every business (production)
    worker_id: str = field(default_factory=default_worker_id)
    lease: timedelta = LEASE


class CreativeWorker:
    """The synchronous parts of the worker; `run_loop` adds the threads and the cadence."""

    def __init__(
        self,
        store: QueueStore,
        executors: Mapping[str, JobExecutor],
        config: WorkerConfig,
        *,
        downloads: DownloadGate,
        clock: Callable[[], datetime] = utcnow,
        stop: threading.Event | None = None,
    ) -> None:
        self.store = store
        self.executors = dict(executors)
        self.config = config
        self.downloads = downloads
        self.clock = clock
        self.stop = stop or threading.Event()

    # -- recovery and claims -------------------------------------------------------------

    def recover(self) -> q.Recovery:
        recovery = self.store.recover(now=self.clock(), tenant_ids=self.config.tenant_ids)
        if recovery.requeued or recovery.released_slots:
            logger.info(
                "creative.worker.recovered requeued=%s released_slots=%s kept_slots=%s",
                len(recovery.requeued),
                recovery.released_slots,
                recovery.kept_slots,
            )
        return recovery

    def claim_round(self, capacity: int) -> list[q.ClaimedJob]:
        """Claim up to `capacity` jobs over the pools this worker has an executor for."""
        claims: list[q.ClaimedJob] = []
        for pool, size in self.config.pools.items():
            if pool not in self.executors or size <= 0:
                continue
            while len(claims) < capacity and not self.stop.is_set():
                claim = self.store.claim_fair(
                    vendor_model=pool,
                    size=size,
                    worker_id=self.config.worker_id,
                    lease=self.config.lease,
                    now=self.clock(),
                    tenant_ids=self.config.tenant_ids,
                )
                if claim is None:
                    break
                logger.info(
                    "creative.worker.claimed job_id=%s tenant_id=%s pool=%s slot=%s",
                    claim.job_id,
                    claim.tenant_id,
                    pool,
                    claim.slot_no,
                )
                claims.append(claim)
        return claims

    # -- one job --------------------------------------------------------------------------

    def process(self, claim: q.ClaimedJob) -> str:
        """Carry one claimed job as far as it goes; returns the outcome (constants above).
        Logs ids, pool, status and times only — never a prompt nor a vendor answer."""
        row = self.store.load(claim)
        if row is None or row.tenant_id != claim.tenant_id:
            # RLS hides it from its own business (or it is gone): fail closed, hand back.
            logger.error("creative.worker.job_not_visible job_id=%s", claim.job_id)
            self.store.hand_back(claim, now=self.clock())
            return MISSING
        if row.claim_token != claim.claim_token:
            return LOST
        executor = self.executors[row.vendor_model]
        now = self.clock()
        lane = lanes.effective_lane(_as_queue_row(row), now)
        ctx = JobContext(
            job_id=row.job_id,
            tenant_id=row.tenant_id,
            draft_id=row.draft_id,
            kind=row.kind,
            revision=row.revision,
            position=row.position,
            vendor_model=row.vendor_model,
            lane=lane,
            vendor_priority=lanes.VENDOR_PRIORITY[lane],
            deadline=row.deadline,
            claim_token=claim.claim_token,
        )

        task_id = row.vendor_task_id
        if task_id is None:
            try:
                task_id = executor.submit(ctx)
            except VendorBusy as busy:
                until = self.clock() + timedelta(seconds=max(1.0, busy.retry_after_seconds))
                self.store.defer(claim, until=until, now=self.clock())
                logger.info(
                    "creative.worker.vendor_busy job_id=%s retry_after=%.0fs",
                    claim.job_id,
                    busy.retry_after_seconds,
                )
                return DEFERRED
            except SubmissionUncertain:
                logger.error("creative.worker.submission_uncertain job_id=%s", claim.job_id)
                # Durable pre-POST not_before retains the slot across expired leases.
                self.store.hand_back(claim, now=self.clock())
                return INTERRUPTED
            except Exception as exc:  # a local validation failure, before paid submission
                logger.error(
                    "creative.worker.submit_failed job_id=%s error_type=%s",
                    claim.job_id,
                    type(exc).__name__,
                )
                return self._end(claim, executor, ctx, None, "failed", error=type(exc).__name__)
            if not self.store.record_submission(claim, vendor_task_id=task_id, now=self.clock()):
                # The claim was lost while submitting: the task is paid but not on this
                # row. Logged with its id for the reconciliation (`just vendor-reconcile`).
                logger.error(
                    "creative.worker.orphan_task job_id=%s vendor_task_id=%s",
                    claim.job_id,
                    task_id,
                )
                return LOST
            logger.info(
                "creative.worker.submitted job_id=%s lane=%s vendor_priority=%s",
                claim.job_id,
                lane,
                ctx.vendor_priority,
            )
        else:
            logger.info("creative.worker.resumed job_id=%s (polling by id)", claim.job_id)

        status = self._wait(claim, executor, ctx, task_id)
        if status in (LOST, INTERRUPTED):
            return status
        return self._end(claim, executor, ctx, task_id, status, attempts_hint=row)

    def _wait(
        self, claim: q.ClaimedJob, executor: JobExecutor, ctx: JobContext, task_id: str
    ) -> str:
        """Poll by id until BytePlus says the task ended; the task's terminal status, or
        `LOST` / `INTERRUPTED`."""
        errors = 0
        while True:
            if self.stop.is_set():
                self.store.hand_back(claim, now=self.clock())
                return INTERRUPTED
            try:
                poll = executor.poll(ctx, task_id)
            except Exception:
                errors += 1
                logger.warning(
                    "creative.worker.poll_failed job_id=%s errors=%s", claim.job_id, errors
                )
                if errors >= MAX_POLL_ERRORS:
                    self.store.hand_back(claim, now=self.clock())
                    return INTERRUPTED
                delay = POLL_ERROR_WAIT_SECONDS
            else:
                errors = 0
                if poll.terminal:
                    return poll.status
                delay = poll.next_poll_seconds
            if not self.store.renew(claim, lease=self.config.lease, now=self.clock()):
                logger.warning("creative.worker.claim_lost job_id=%s", claim.job_id)
                return LOST
            self.stop.wait(delay)

    def _end(
        self,
        claim: q.ClaimedJob,
        executor: JobExecutor,
        ctx: JobContext,
        task_id: str | None,
        status: str,
        *,
        error: str | None = None,
        attempts_hint: q.JobRow | None = None,
    ) -> str:
        ok = status == SUCCEEDED
        try:
            if ok:
                with self.downloads.hold():
                    executor.finish(ctx, task_id, status)
            else:
                executor.finish(ctx, task_id, status)
        except Exception as exc:
            logger.error(
                "creative.worker.finish_failed job_id=%s error_type=%s",
                claim.job_id,
                type(exc).__name__,
            )
            attempts = attempts_hint.attempts if attempts_hint is not None else 0
            if attempts < MAX_FINISH_ATTEMPTS:
                # Left claimed: the lease runs out, recovery requeues it (keeping the slot
                # when it has a task) and the next claim polls and finishes it again.
                return FINISH_ERROR
            ok, error = False, "finish_failed"
        settled = self.store.settle(
            claim,
            status=q.SUCCEEDED if ok else q.FAILED,
            now=self.clock(),
            last_error=None if ok else (error or status),
        )
        if not settled:
            return LOST
        self.store.release(claim, now=self.clock())
        logger.info(
            "creative.worker.settled job_id=%s status=%s", claim.job_id, "ok" if ok else status
        )
        return SUCCEEDED_OUTCOME if ok else FAILED_OUTCOME


def _as_queue_row(row: q.JobRow) -> q.QueueRow:
    return q.QueueRow(
        job_id=row.job_id,
        tenant_id=row.tenant_id,
        kind=row.kind,
        lane=row.lane,
        priority=row.priority,
        queued_at=row.queued_at,
        status=row.status,
        holds_slot=True,
    )


# -- the loop --------------------------------------------------------------------------------


def run_loop(
    worker: CreativeWorker,
    *,
    once: bool,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    sidecar: Callable[[], object] | None = None,
    preparation: Callable[[], object] | None = None,
    sidecar_every: float = RECOVERY_EVERY_SECONDS,
    recover_every: float = RECOVER_EVERY_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    max_rounds: int | None = None,
) -> int:
    """Rounds every `interval` seconds until `worker.stop` is set (SIGTERM / Ctrl+C), or
    one round with `once` (waits for its jobs and runs the sidecar once). Returns 0."""
    capacity = max(1, sum(s for p, s in worker.config.pools.items() if p in worker.executors))
    pool = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="creative-job")
    active: set[Future[str]] = set()
    sidecar_thread: threading.Thread | None = None
    next_recover = next_sidecar = monotonic()
    door_down_logged = 0.0
    rounds = 0
    try:
        while not worker.stop.is_set():
            started = monotonic()
            if sidecar is not None and not once and started >= next_sidecar:
                if sidecar_thread is None or not sidecar_thread.is_alive():
                    sidecar_thread = threading.Thread(
                        target=_guarded, args=(sidecar,), name="vendor-recovery", daemon=True
                    )
                    sidecar_thread.start()
                    next_sidecar = started + sidecar_every
            active = {f for f in active if not f.done()}
            try:
                if preparation is not None:
                    preparation()
                if started >= next_recover:
                    worker.recover()
                    next_recover = started + recover_every
                for claim in worker.claim_round(capacity - len(active)):
                    active.add(pool.submit(_guarded_process, worker, claim))
            except OperationalError:
                # The queue door cannot connect (e.g. its password is not set yet): the
                # recovery sidecar keeps running; say so once a minute, never crash-loop.
                if started - door_down_logged >= 60 or door_down_logged == 0.0:
                    logger.error("creative.worker.queue_door_unavailable", exc_info=True)
                    door_down_logged = started
            except Exception as exc:
                logger.error("creative.worker.round_failed error_type=%s", type(exc).__name__)
            rounds += 1
            if once:
                for future in list(active):
                    future.result()
                if sidecar is not None:
                    _guarded(sidecar)
                return 0
            if max_rounds is not None and rounds >= max_rounds:
                return 0
            worker.stop.wait(max(0.0, interval - (monotonic() - started)))
        return 0
    finally:
        worker.stop.set()  # in-flight jobs hand themselves back at their next poll
        pool.shutdown(wait=True)
        if sidecar_thread is not None and sidecar_thread.is_alive():
            sidecar_thread.join(timeout=30)


def _guarded(job: Callable[[], object]) -> object:
    try:
        return job()
    except Exception as exc:
        logger.error("creative.worker.sidecar_failed error_type=%s", type(exc).__name__)
        return None


def _guarded_process(worker: CreativeWorker, claim: q.ClaimedJob) -> str:
    try:
        return worker.process(claim)
    except Exception as exc:
        logger.error(
            "creative.worker.process_failed job_id=%s error_type=%s",
            claim.job_id,
            type(exc).__name__,
        )
        return INTERRUPTED
