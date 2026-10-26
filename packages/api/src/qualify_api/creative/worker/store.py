"""The worker's queue store: each step through the right database door (m-24852163).

`docs/seguridad-creative-worker.md` §2–3, step by step:

- `recover`, `claim_fair`, `renew`, `release`, `hand_back` → `creative_worker_session`:
  order and slots, the queue columns of every business and nothing else.
- `load`, `record_submission`, `settle`, `defer` → `tenant_session(claim.tenant_id)`: the
  job's content and its result, one business, RLS. (`defer` then hands the job back
  through the worker door.)

Every method is ONE short transaction; no session outlives it or is shared between jobs.
The `tenant_id` of a tenant step comes from the claimed row only (`ClaimedJob`).
`QueueStore` is the seam the worker loop is tested through (`tests/…creative_worker.py`
use an in-memory store with the same rules).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_shared.db.creative_worker import creative_worker_session
from qualify_shared.db.session import tenant_session

from qualify_api.creative import job_queue as q
from qualify_api.creative.worker import lanes


class QueueStore(Protocol):
    def recover(self, *, now: datetime, tenant_ids: Sequence[UUID] | None) -> q.Recovery: ...

    def claim_fair(
        self,
        *,
        vendor_model: str,
        size: int,
        worker_id: str,
        lease: timedelta,
        now: datetime,
        tenant_ids: Sequence[UUID] | None,
    ) -> q.ClaimedJob | None: ...

    def load(self, claim: q.ClaimedJob) -> q.JobRow | None: ...

    def record_submission(
        self, claim: q.ClaimedJob, *, vendor_task_id: str, now: datetime
    ) -> bool: ...

    def renew(self, claim: q.ClaimedJob, *, lease: timedelta, now: datetime) -> bool: ...

    def settle(
        self, claim: q.ClaimedJob, *, status: str, now: datetime, last_error: str | None
    ) -> bool: ...

    def release(self, claim: q.ClaimedJob, *, now: datetime) -> bool: ...

    def defer(self, claim: q.ClaimedJob, *, until: datetime, now: datetime) -> bool: ...

    def hand_back(self, claim: q.ClaimedJob, *, now: datetime) -> bool: ...


class PostgresQueueStore:
    """The production store: `job_queue` through the two doors."""

    def recover(self, *, now: datetime, tenant_ids: Sequence[UUID] | None) -> q.Recovery:
        with creative_worker_session() as session:
            return q.recover_expired(session, now=now, tenant_ids=tenant_ids)

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
        """Snapshot → fair pick (`lanes.pick_next`) → claim, in one transaction under the
        pool's advisory lock: what was decided is still true when it is claimed."""
        with creative_worker_session() as session:
            q.lock_pool(session, vendor_model)
            waiting, in_flight = q.queue_snapshot(
                session,
                vendor_model=vendor_model,
                now=now,
                now_priority=lanes.NOW_PRIORITY,
                tenant_ids=tenant_ids,
            )
            pick = lanes.pick_next(waiting, in_flight, size=size, now=now)
            if pick is None:
                return None
            return q.claim_job(
                session,
                job_id=pick.job_id,
                vendor_model=vendor_model,
                size=size,
                worker_id=worker_id,
                lease=lease,
                now=now,
            )

    def load(self, claim: q.ClaimedJob) -> q.JobRow | None:
        with tenant_session(claim.tenant_id) as session:
            return q.load_job(session, claim.job_id)

    def record_submission(self, claim: q.ClaimedJob, *, vendor_task_id: str, now: datetime) -> bool:
        with tenant_session(claim.tenant_id) as session:
            return q.record_submission(
                session,
                job_id=claim.job_id,
                claim_token=claim.claim_token,
                vendor_task_id=vendor_task_id,
                now=now,
            )

    def renew(self, claim: q.ClaimedJob, *, lease: timedelta, now: datetime) -> bool:
        with creative_worker_session() as session:
            return q.renew_lease(
                session, job_id=claim.job_id, claim_token=claim.claim_token, lease=lease, now=now
            )

    def settle(
        self, claim: q.ClaimedJob, *, status: str, now: datetime, last_error: str | None
    ) -> bool:
        with tenant_session(claim.tenant_id) as session:
            return q.settle_job(
                session,
                job_id=claim.job_id,
                claim_token=claim.claim_token,
                status=status,
                now=now,
                last_error=last_error,
            )

    def release(self, claim: q.ClaimedJob, *, now: datetime) -> bool:
        with creative_worker_session() as session:
            return q.release_slot(session, job_id=claim.job_id, now=now)

    def defer(self, claim: q.ClaimedJob, *, until: datetime, now: datetime) -> bool:
        with tenant_session(claim.tenant_id) as session:
            deferred = q.defer_job(
                session, job_id=claim.job_id, claim_token=claim.claim_token, until=until
            )
        if not deferred:
            return False
        with creative_worker_session() as session:
            return q.hand_back(
                session,
                job_id=claim.job_id,
                claim_token=claim.claim_token,
                now=now,
                count_attempt=False,
            )

    def hand_back(self, claim: q.ClaimedJob, *, now: datetime) -> bool:
        with creative_worker_session() as session:
            return q.hand_back(session, job_id=claim.job_id, claim_token=claim.claim_token, now=now)
