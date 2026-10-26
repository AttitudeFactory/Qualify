"""The generation queue's repository (ADR 41, m-24852160): `creative_jobs` + `vendor_slots`.

Two halves, split by which database door their caller holds (migration 0096,
`docs/seguridad-creative-worker.md`):

- **Tenant side** — the Session comes from `tenant_session(tenant_id)`, so RLS confines
  every statement to one business: `enqueue_job` (the owner's request INSERTs the job in
  the same transaction that changes the piece — outbox), `cancel_job`, `record_submission`
  (writes the vendor task id ONCE, before waiting) and `settle_job`.
- **Worker side** — the Session comes from `creative_worker_session()` (role
  `qualify_creative_worker`, queue columns only): `claim_next` (`FOR UPDATE SKIP LOCKED`
  on the job AND on a free slot, in one transaction), `renew_lease`, `release_slot` and
  `recover_expired`. A claim leaves this half as `(job_id, tenant_id, claim_token)` only;
  the job's content is read again under `tenant_session(job.tenant_id)`.

Nothing here opens a session: every function takes the caller's, so the door is chosen
where it is visible (only `qualify_api.creative.worker` may import the worker door —
`test_creative_worker_door_sanctity.py`).

**Exclusion.** `claim_token` grows on every claim and on every recovery; every write
after a claim carries `WHERE claim_token = :token`, so a worker that lost its lease (slow,
not dead) writes nothing. **Idempotency.** The natural key `(tenant_id, draft_id, kind,
revision, position)` makes a double enqueue a no-op; a job with `vendor_task_id` is never
submitted again — recovery requeues it holding its slot, and the next claim polls it.
**The cap.** A job is claimed only together with a slot of its pool whose `slot_no` is
within the configured size (`QUALIFY_VENDOR_POOLS`), so the jobs in flight never exceed
it; a slot is released only when its job is terminal or never reached BytePlus.

Fair share between businesses and the lanes are decided by the worker
(`creative/worker/lanes.py`, m-24852163) over `queue_snapshot`; this module only gives it
the snapshot, the per-pool lock (`lock_pool`) and the claim of the chosen job (`claim_job`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from qualify_api.creative.final_deadline import deadline_for_preview

# --- vocabularies (the CHECK constraints of 0096 pin the same sets) ---------------------

KIND_PREVIEW = "preview"
KIND_FINAL = "final"
KIND_PRESENTER = "presenter"
KIND_CAROUSEL_SCENE = "carousel_scene"
KINDS: frozenset[str] = frozenset({KIND_PREVIEW, KIND_FINAL, KIND_PRESENTER, KIND_CAROUSEL_SCENE})

LANE_IMMEDIATE = "immediate"
LANE_NIGHTLY = "nightly"
LANES: frozenset[str] = frozenset({LANE_IMMEDIATE, LANE_NIGHTLY})

QUEUED = "queued"
CLAIMED = "claimed"
SUBMITTED = "submitted"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
STATUSES: frozenset[str] = frozenset({QUEUED, CLAIMED, SUBMITTED, SUCCEEDED, FAILED, CANCELLED})
TERMINAL: frozenset[str] = frozenset({SUCCEEDED, FAILED, CANCELLED})
IN_FLIGHT: frozenset[str] = frozenset({CLAIMED, SUBMITTED})

# --- vendor pools ----------------------------------------------------------------------

SEEDANCE_POOL = "byteplus:seedance-2-5"
OMNIHUMAN_POOL = "byteplus:omnihuman-1-5"
#: BytePlus's per-account caps (ADR 41 §1.1): 10 Seedance 2.5 tasks, 1 OmniHuman task.
DEFAULT_POOL_SIZES: Mapping[str, int] = {SEEDANCE_POOL: 10, OMNIHUMAN_POOL: 1}
#: Any other pool, until configured (ticket m-24852160: «por defecto 10»).
DEFAULT_POOL_SIZE = 10
#: Rows 0096 seeds per pool: the size can be raised up to this by configuration alone.
SEEDED_SLOTS: Mapping[str, int] = {SEEDANCE_POOL: 50, OMNIHUMAN_POOL: 10}
POOLS_ENV = "QUALIFY_VENDOR_POOLS"


class VendorPoolsConfigError(ValueError):
    """`QUALIFY_VENDOR_POOLS` is malformed — fail loudly instead of guessing a cap."""


def parse_vendor_pools(raw: str | None) -> dict[str, int]:
    """`byteplus:seedance-2-5=10,byteplus:omnihuman-1-5=1` -> sizes, over the defaults.

    A size of 0 is allowed (it pauses that pool); a size above the seeded rows is accepted
    but only the seeded slots exist, so the effective cap is the smaller of the two."""
    sizes = dict(DEFAULT_POOL_SIZES)
    if not raw or not raw.strip():
        return sizes
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        pool, sep, size = entry.rpartition("=")
        pool = pool.strip()
        if not sep or not pool:
            raise VendorPoolsConfigError(f"{POOLS_ENV}: «{entry}» is not pool=size")
        try:
            value = int(size.strip())
        except ValueError as exc:
            raise VendorPoolsConfigError(f"{POOLS_ENV}: size of «{pool}» is not a number") from exc
        if value < 0:
            raise VendorPoolsConfigError(f"{POOLS_ENV}: size of «{pool}» is negative")
        sizes[pool] = value
    return sizes


def pool_size(pool: str, env: Mapping[str, str] | None = None) -> int:
    """The configured number of slots of `pool` (env `QUALIFY_VENDOR_POOLS`)."""
    source = os.environ if env is None else env
    return parse_vendor_pools(source.get(POOLS_ENV)).get(pool, DEFAULT_POOL_SIZE)


# --- results -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Enqueued:
    job_id: UUID
    created: bool  # False: the same step of the same piece was already queued


@dataclass(frozen=True)
class ClaimedJob:
    """All a claim hands over (security review §3.1): the rest is read again under
    `tenant_session(tenant_id)`."""

    job_id: UUID
    tenant_id: UUID
    claim_token: int
    slot_no: int


@dataclass(frozen=True)
class Recovery:
    requeued: tuple[UUID, ...]  # jobs whose lease ran out, back to `queued`
    released_slots: int  # slots freed (their job never reached BytePlus, or is over)
    kept_slots: int  # slots kept: their job has a vendor task still to be polled


# --- tenant side (tenant_session) ---------------------------------------------------------


def enqueue_job(
    session: Session,
    *,
    tenant_id: UUID,
    draft_id: UUID,
    kind: str,
    revision: int,
    vendor_model: str,
    lane: str,
    position: int = 0,
    priority: int = 0,
    not_before: datetime | None = None,
    deadline: datetime | None = None,
    preview_created_at: float | datetime | None = None,
    charge_id: UUID | None = None,
    pricing_version: str | None = None,
    pipeline_version: str | None = None,
) -> Enqueued:
    """Queue one paid vendor call of a piece, once. Call it inside the transaction that
    changes the piece. A second call for the same step returns the existing job."""
    if preview_created_at is not None:
        if kind != KIND_FINAL:
            raise ValueError("preview_created_at only applies to a final")
        preview_deadline = deadline_for_preview(preview_created_at)
        deadline = min(deadline, preview_deadline) if deadline is not None else preview_deadline
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    if lane not in LANES:
        raise ValueError(f"unknown lane {lane!r}")
    params = {
        "tenant_id": tenant_id,
        "draft_id": draft_id,
        "kind": kind,
        "revision": revision,
        "position": position,
    }
    created = session.execute(
        text(
            """
            INSERT INTO creative_jobs (
                tenant_id, draft_id, kind, revision, position, vendor_model, lane, priority,
                not_before, deadline, charge_id, pricing_version, pipeline_version
            ) VALUES (
                :tenant_id, :draft_id, :kind, :revision, :position, :vendor_model, :lane,
                :priority, COALESCE(:not_before, now()), :deadline, :charge_id,
                :pricing_version, :pipeline_version
            )
            ON CONFLICT ON CONSTRAINT uq_creative_jobs_step DO NOTHING
            RETURNING id
            """
        ),
        {
            **params,
            "vendor_model": vendor_model,
            "lane": lane,
            "priority": priority,
            "not_before": not_before,
            "deadline": deadline,
            "charge_id": charge_id,
            "pricing_version": pricing_version,
            "pipeline_version": pipeline_version,
        },
    ).scalar_one_or_none()
    if created is not None:
        return Enqueued(job_id=created, created=True)
    existing = session.execute(
        text(
            """
            SELECT id FROM creative_jobs
            WHERE tenant_id = :tenant_id AND draft_id = :draft_id AND kind = :kind
              AND revision = :revision AND position = :position
            """
        ),
        params,
    ).scalar_one()
    return Enqueued(job_id=existing, created=False)


def cancel_job(session: Session, job_id: UUID) -> bool:
    """Cancel a job still waiting. A job already sent to BytePlus (it has a vendor task id)
    or claimed is not cancellable: the task is paid and its result is still collected."""
    return (
        session.execute(
            text(
                """
                UPDATE creative_jobs SET status = 'cancelled', finished_at = now()
                WHERE id = :id AND status = 'queued' AND vendor_task_id IS NULL
                RETURNING id
                """
            ),
            {"id": job_id},
        ).scalar_one_or_none()
        is not None
    )


def record_submission(
    session: Session, *, job_id: UUID, claim_token: int, vendor_task_id: str, now: datetime
) -> bool:
    """Write the vendor task id right after BytePlus accepts it and BEFORE waiting. False
    when the claim was lost or the job already has a task (it is never overwritten)."""
    return (
        session.execute(
            text(
                """
                UPDATE creative_jobs
                SET vendor_task_id = :vendor_task_id, status = 'submitted', submitted_at = :now,
                    not_before = :now
                WHERE id = :id AND claim_token = :token AND status = 'claimed'
                  AND vendor_task_id IS NULL
                RETURNING id
                """
            ),
            {"id": job_id, "token": claim_token, "vendor_task_id": vendor_task_id, "now": now},
        ).scalar_one_or_none()
        is not None
    )


def settle_job(
    session: Session,
    *,
    job_id: UUID,
    claim_token: int,
    status: str,
    now: datetime,
    last_error: str | None = None,
) -> bool:
    """Record the terminal outcome (succeeded / failed) under the current claim. The slot
    is released afterwards by the worker door (`release_slot`)."""
    if status not in (SUCCEEDED, FAILED):
        raise ValueError(f"settle_job takes succeeded or failed, not {status!r}")
    return (
        session.execute(
            text(
                """
                UPDATE creative_jobs
                SET status = :status, finished_at = :now, last_error = :last_error
                WHERE id = :id AND claim_token = :token AND status IN ('claimed','submitted')
                RETURNING id
                """
            ),
            {
                "id": job_id,
                "token": claim_token,
                "status": status,
                "now": now,
                "last_error": last_error,
            },
        ).scalar_one_or_none()
        is not None
    )


# --- worker side (creative_worker_session) ------------------------------------------------


def claim_next(
    session: Session,
    *,
    vendor_model: str,
    size: int,
    worker_id: str,
    lease: timedelta,
    now: datetime,
) -> ClaimedJob | None:
    """Claim the next queued job of `vendor_model` together with a slot, or nothing.

    A job that already holds a slot (requeued by `recover_expired` with its vendor task
    still to poll) goes first and keeps its slot; any other job needs a free slot with
    `slot_no <= size`. Both rows are locked `FOR UPDATE SKIP LOCKED`, so concurrent
    claimers never take the same job nor the same slot, and never more than `size`.
    (Plain FIFO by priority: the worker's fair order is `claim_job`, m-24852163.)"""
    job = session.execute(
        text(
            """
            SELECT id, tenant_id FROM creative_jobs
            WHERE status = 'queued' AND vendor_model = :pool AND not_before <= :now
            ORDER BY (vendor_task_id IS NOT NULL) DESC,
                     (kind = 'final' AND deadline < :now + interval '24 hours') DESC
                         NULLS LAST,
                     priority DESC, deadline NULLS LAST, queued_at, id
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"pool": vendor_model, "now": now},
    ).one_or_none()
    if job is None:
        return None
    return _claim_with_slot(
        session,
        job_id=job.id,
        tenant_id=job.tenant_id,
        vendor_model=vendor_model,
        size=size,
        worker_id=worker_id,
        lease=lease,
        now=now,
    )


def claim_job(
    session: Session,
    *,
    job_id: UUID,
    vendor_model: str,
    size: int,
    worker_id: str,
    lease: timedelta,
    now: datetime,
) -> ClaimedJob | None:
    """Claim ONE chosen job (the worker's fair pick, m-24852163) with a slot, or nothing:
    it is no longer queued, not due yet, locked by another claimer, or the pool is full.
    Same slot rules as `claim_next`."""
    job = session.execute(
        text(
            """
            SELECT id, tenant_id FROM creative_jobs
            WHERE id = :id AND status = 'queued' AND vendor_model = :pool
              AND not_before <= :now
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"id": job_id, "pool": vendor_model, "now": now},
    ).one_or_none()
    if job is None:
        return None
    return _claim_with_slot(
        session,
        job_id=job.id,
        tenant_id=job.tenant_id,
        vendor_model=vendor_model,
        size=size,
        worker_id=worker_id,
        lease=lease,
        now=now,
    )


def _claim_with_slot(
    session: Session,
    *,
    job_id: UUID,
    tenant_id: UUID,
    vendor_model: str,
    size: int,
    worker_id: str,
    lease: timedelta,
    now: datetime,
) -> ClaimedJob | None:
    """The job row is already locked: keep the slot it holds, or take a free one."""
    slot_no = session.execute(
        text("SELECT slot_no FROM vendor_slots WHERE holder_job_id = :job FOR UPDATE"),
        {"job": job_id},
    ).scalar_one_or_none()
    if slot_no is None:
        slot_no = session.execute(
            text(
                """
                SELECT slot_no FROM vendor_slots
                WHERE vendor_model = :pool AND slot_no <= :size AND holder_job_id IS NULL
                ORDER BY slot_no
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"pool": vendor_model, "size": size},
        ).scalar_one_or_none()
        if slot_no is None:
            return None  # the pool is full; the job stays queued (its lock ends here)
    lease_until = now + lease
    session.execute(
        text(
            """
            UPDATE vendor_slots SET holder_job_id = :job, lease_until = :lease, updated_at = :now
            WHERE vendor_model = :pool AND slot_no = :slot
            """
        ),
        {"job": job_id, "lease": lease_until, "now": now, "pool": vendor_model, "slot": slot_no},
    )
    token = session.execute(
        text(
            """
            UPDATE creative_jobs
            SET status = 'claimed', claimed_by = :worker, claim_token = claim_token + 1,
                lease_until = :lease, attempts = attempts + 1
            WHERE id = :job
            RETURNING claim_token
            """
        ),
        {"job": job_id, "worker": worker_id, "lease": lease_until},
    ).scalar_one()
    return ClaimedJob(job_id=job_id, tenant_id=tenant_id, claim_token=token, slot_no=slot_no)


def renew_lease(
    session: Session, *, job_id: UUID, claim_token: int, lease: timedelta, now: datetime
) -> bool:
    """Extend a live claim and its slot (the worker's heartbeat while it polls). False when
    the claim was lost — the caller must stop working on the job."""
    lease_until = now + lease
    renewed = session.execute(
        text(
            """
            UPDATE creative_jobs SET lease_until = :lease
            WHERE id = :job AND claim_token = :token AND status IN ('claimed','submitted')
            RETURNING id
            """
        ),
        {"job": job_id, "token": claim_token, "lease": lease_until},
    ).scalar_one_or_none()
    if renewed is None:
        return False
    session.execute(
        text(
            "UPDATE vendor_slots SET lease_until = :lease, updated_at = :now "
            "WHERE holder_job_id = :job"
        ),
        {"job": job_id, "lease": lease_until, "now": now},
    )
    return True


def release_slot(session: Session, *, job_id: UUID, now: datetime) -> bool:
    """Free the job's slot once the job is over (succeeded, failed, cancelled). Never while
    it is still in flight: BytePlus is still counting that task against the cap."""
    released = session.execute(
        text(
            """
            UPDATE vendor_slots AS s
            SET holder_job_id = NULL, lease_until = NULL, updated_at = :now
            FROM creative_jobs AS j
            WHERE s.holder_job_id = j.id AND j.id = :job
              AND j.status IN ('succeeded','failed','cancelled')
            RETURNING s.slot_no
            """
        ),
        {"job": job_id, "now": now},
    ).scalar_one_or_none()
    if released is None:
        return False
    session.execute(
        text("UPDATE creative_jobs SET lease_until = NULL WHERE id = :job"), {"job": job_id}
    )
    return True


def recover_expired(
    session: Session, *, now: datetime, tenant_ids: Sequence[UUID] | None = None
) -> Recovery:
    """Hand back what a dead (or stalled) worker left behind.

    1. Every claimed/submitted job whose lease ran out goes back to `queued`, with a new
       `claim_token` (the old holder can no longer write). A job that never reached
       BytePlus frees its slot; a job WITH a vendor task keeps it — BytePlus still counts
       that task — and the next claim takes the job first and polls it, never resubmits.
    2. Every slot whose lease ran out is freed unless its job has a vendor task and is not
       over yet.

    `tenant_ids` (a worker run with `--tenant`, m-24852163) limits both steps to those
    businesses' jobs; `None` is the production pass over every job."""
    scope = _scope(tenant_ids)
    rows = session.execute(
        text(
            """
            UPDATE creative_jobs
            SET status = 'queued', claimed_by = NULL, lease_until = NULL,
                claim_token = claim_token + 1
            WHERE id IN (
                SELECT id FROM creative_jobs
                WHERE status IN ('claimed','submitted') AND lease_until < :now
                  AND (NOT :scoped OR tenant_id = ANY(CAST(:tenants AS uuid[])))
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
            """
        ),
        {"now": now, **scope},
    ).all()
    requeued = tuple(row.id for row in rows)

    released = session.execute(
        text(
            """
            UPDATE vendor_slots AS s
            SET holder_job_id = NULL, lease_until = NULL, updated_at = :now
            WHERE s.holder_job_id IS NOT NULL
              AND (
                    s.lease_until < :now
                 OR s.holder_job_id = ANY(CAST(:requeued AS uuid[]))
              )
              AND NOT EXISTS (
                    SELECT 1 FROM creative_jobs AS j
                    WHERE j.id = s.holder_job_id
                      AND (j.vendor_task_id IS NOT NULL OR j.not_before > :now)
                      AND j.status NOT IN ('succeeded','failed','cancelled')
              )
              AND (
                    NOT :scoped
                 OR EXISTS (
                        SELECT 1 FROM creative_jobs AS o
                        WHERE o.id = s.holder_job_id
                          AND o.tenant_id = ANY(CAST(:tenants AS uuid[]))
                    )
              )
            RETURNING s.slot_no
            """
        ),
        {"now": now, "requeued": [str(job_id) for job_id in requeued], **scope},
    ).all()
    kept = session.execute(
        text(
            """
            SELECT count(*) FROM vendor_slots AS s
            JOIN creative_jobs AS j ON j.id = s.holder_job_id
            WHERE j.vendor_task_id IS NOT NULL AND j.status = 'queued'
            """
        )
    ).scalar_one()
    return Recovery(requeued=requeued, released_slots=len(released), kept_slots=int(kept))


def slots_in_use(session: Session, vendor_model: str) -> int:
    """How many slots of a pool are held right now (worker door; an aggregate, no ids)."""
    return int(
        session.execute(
            text(
                "SELECT count(*) FROM vendor_slots "
                "WHERE vendor_model = :pool AND holder_job_id IS NOT NULL"
            ),
            {"pool": vendor_model},
        ).scalar_one()
    )


# --- the worker's fair claim (m-24852163) -------------------------------------------------


@dataclass(frozen=True)
class QueueRow:
    """What the worker door may see of one job to decide the order (queue columns only)."""

    job_id: UUID
    tenant_id: UUID
    kind: str
    lane: str
    priority: int
    queued_at: datetime
    status: str
    holds_slot: bool  # requeued with a vendor task still to poll: it keeps its slot
    deadline: datetime | None = None


def _scope(tenant_ids: Sequence[UUID] | None) -> dict[str, object]:
    return {
        "scoped": tenant_ids is not None,
        "tenants": [str(t) for t in (tenant_ids or ())],
    }


def _queue_row(row: Any) -> QueueRow:
    return QueueRow(
        job_id=row.id,
        tenant_id=row.tenant_id,
        kind=row.kind,
        lane=row.lane,
        priority=int(row.priority),
        queued_at=row.queued_at,
        status=row.status,
        holds_slot=bool(row.holds_slot),
        deadline=row.deadline,
    )


def lock_pool(session: Session, vendor_model: str) -> None:
    """Serialise the fair claims of one pool for the rest of this transaction (a
    transaction-level advisory lock): the snapshot the worker decides on stays true until
    it claims, so two workers never both give a business its third slot."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"creative_jobs:{vendor_model}"},
    )


def queue_snapshot(
    session: Session,
    *,
    vendor_model: str,
    now: datetime,
    now_priority: int,
    tenant_ids: Sequence[UUID] | None = None,
    heads: int = 3,
) -> tuple[list[QueueRow], list[QueueRow]]:
    """`(waiting, in_flight)` of one pool, for the worker's fair pick.

    - `in_flight`: every job holding a slot or claimed — of EVERY business, even in a
      scoped run, because the cap and the reserved slots belong to the vendor account.
    - `waiting`: the due queued jobs of the scope, but only the `heads` oldest of each
      business and class (lane × final × «now» priority) plus every job holding a slot:
      the fair pick only ever looks at a business's oldest jobs of a class, so a business
      with 500 jobs queued does not make the snapshot 500 rows."""
    scope = _scope(tenant_ids)
    in_flight = session.execute(
        text(
            """
            SELECT j.id, j.tenant_id, j.kind, j.lane, j.priority, j.queued_at, j.status, j.deadline,
                   (s.slot_no IS NOT NULL) AS holds_slot
            FROM creative_jobs AS j
            LEFT JOIN vendor_slots AS s ON s.holder_job_id = j.id
            WHERE j.vendor_model = :pool
              AND (j.status IN ('claimed','submitted')
                   OR (j.status = 'queued' AND s.slot_no IS NOT NULL))
            """
        ),
        {"pool": vendor_model},
    ).all()
    waiting = session.execute(
        text(
            """
            SELECT id, tenant_id, kind, lane, priority, queued_at, status, holds_slot, deadline
            FROM (
                SELECT j.id, j.tenant_id, j.kind, j.lane, j.priority, j.queued_at, j.status,
                       j.deadline,
                       (s.slot_no IS NOT NULL) AS holds_slot,
                       row_number() OVER (
                           PARTITION BY j.tenant_id, j.lane, (j.kind = 'final'),
                                        (j.priority >= :now_priority),
                                        (j.kind = 'final' AND
                                         j.deadline < :now + interval '24 hours')
                           ORDER BY j.deadline NULLS LAST, j.queued_at, j.id
                       ) AS rn
                FROM creative_jobs AS j
                LEFT JOIN vendor_slots AS s ON s.holder_job_id = j.id
                WHERE j.status = 'queued' AND j.vendor_model = :pool AND j.not_before <= :now
                  AND (NOT :scoped OR j.tenant_id = ANY(CAST(:tenants AS uuid[])))
            ) AS c
            WHERE c.rn <= :heads OR c.holds_slot
            ORDER BY c.queued_at, c.id
            """
        ),
        {"pool": vendor_model, "now": now, "now_priority": now_priority, "heads": heads, **scope},
    ).all()
    return [_queue_row(r) for r in waiting], [_queue_row(r) for r in in_flight]


def hand_back(
    session: Session, *, job_id: UUID, claim_token: int, now: datetime, count_attempt: bool = True
) -> bool:
    """Put a job this worker holds back in the queue (worker door): BytePlus was busy
    (`count_attempt=False`: a 429 is not an attempt), the worker is shutting down, or it
    cannot go on with it. A new `claim_token` ends this claim. A job that never reached
    BytePlus frees its slot; a job WITH a vendor task keeps it, and the next claim polls
    it — never resubmits. False when the claim was already lost."""
    row = session.execute(
        text(
            """
            UPDATE creative_jobs
            SET status = 'queued', claimed_by = NULL, lease_until = NULL,
                claim_token = claim_token + 1,
                attempts = CASE WHEN :count THEN attempts ELSE GREATEST(attempts - 1, 0) END
            WHERE id = :job AND claim_token = :token AND status IN ('claimed','submitted')
            RETURNING vendor_task_id, not_before
            """
        ),
        {"job": job_id, "token": claim_token, "count": count_attempt, "now": now},
    ).one_or_none()
    if row is None:
        return False
    if row.vendor_task_id is None and (not count_attempt or row.not_before <= now):
        session.execute(
            text(
                "UPDATE vendor_slots SET holder_job_id = NULL, lease_until = NULL, "
                "updated_at = :now WHERE holder_job_id = :job"
            ),
            {"job": job_id, "now": now},
        )
    return True


# --- the worker's tenant-side steps (tenant_session, m-24852163) ---------------------------


@dataclass(frozen=True)
class JobRow:
    """The whole job, read again under `tenant_session(claim.tenant_id)` (security review
    §3.2): RLS hides it from any other business."""

    job_id: UUID
    tenant_id: UUID
    draft_id: UUID
    kind: str
    revision: int
    position: int
    vendor_model: str
    lane: str
    priority: int
    status: str
    claim_token: int
    vendor_task_id: str | None
    queued_at: datetime
    deadline: datetime | None
    attempts: int


def load_job(session: Session, job_id: UUID) -> JobRow | None:
    """The job by id inside the caller's tenant session, or None (RLS: another business)."""
    row = session.execute(
        text(
            """
            SELECT id, tenant_id, draft_id, kind, revision, position, vendor_model, lane,
                   priority, status, claim_token, vendor_task_id, queued_at, deadline,
                   attempts
            FROM creative_jobs WHERE id = :id
            """
        ),
        {"id": job_id},
    ).one_or_none()
    if row is None:
        return None
    return JobRow(
        job_id=row.id,
        tenant_id=row.tenant_id,
        draft_id=row.draft_id,
        kind=row.kind,
        revision=int(row.revision),
        position=int(row.position),
        vendor_model=row.vendor_model,
        lane=row.lane,
        priority=int(row.priority),
        status=row.status,
        claim_token=int(row.claim_token),
        vendor_task_id=row.vendor_task_id,
        queued_at=row.queued_at,
        deadline=row.deadline,
        attempts=int(row.attempts),
    )


def defer_job(session: Session, *, job_id: UUID, claim_token: int, until: datetime) -> bool:
    """BytePlus answered «busy» (429): nothing was created nor billed. Push the job's
    `not_before` so no claim takes it before `until`; the worker door then hands it back
    (`hand_back(count_attempt=False)`). Only a job that never reached BytePlus."""
    return (
        session.execute(
            text(
                """
                UPDATE creative_jobs SET not_before = :until
                WHERE id = :id AND claim_token = :token AND status = 'claimed'
                  AND vendor_task_id IS NULL
                RETURNING id
                """
            ),
            {"id": job_id, "token": claim_token, "until": until},
        ).scalar_one_or_none()
        is not None
    )
