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

Fair share between businesses, lanes and the nightly window are the worker's
(m-24852163), not this module's.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

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
    charge_id: UUID | None = None,
    pricing_version: str | None = None,
    pipeline_version: str | None = None,
) -> Enqueued:
    """Queue one paid vendor call of a piece, once. Call it inside the transaction that
    changes the piece. A second call for the same step returns the existing job."""
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
                SET vendor_task_id = :vendor_task_id, status = 'submitted', submitted_at = :now
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
    claimers never take the same job nor the same slot, and never more than `size`."""
    job = session.execute(
        text(
            """
            SELECT id, tenant_id, claim_token FROM creative_jobs
            WHERE status = 'queued' AND vendor_model = :pool AND not_before <= :now
            ORDER BY (vendor_task_id IS NOT NULL) DESC, priority DESC, queued_at, id
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"pool": vendor_model, "now": now},
    ).one_or_none()
    if job is None:
        return None
    slot_no = session.execute(
        text("SELECT slot_no FROM vendor_slots WHERE holder_job_id = :job FOR UPDATE"),
        {"job": job.id},
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
        {"job": job.id, "lease": lease_until, "now": now, "pool": vendor_model, "slot": slot_no},
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
        {"job": job.id, "worker": worker_id, "lease": lease_until},
    ).scalar_one()
    return ClaimedJob(job_id=job.id, tenant_id=job.tenant_id, claim_token=token, slot_no=slot_no)


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


def recover_expired(session: Session, *, now: datetime) -> Recovery:
    """Hand back what a dead (or stalled) worker left behind.

    1. Every claimed/submitted job whose lease ran out goes back to `queued`, with a new
       `claim_token` (the old holder can no longer write). A job that never reached
       BytePlus frees its slot; a job WITH a vendor task keeps it — BytePlus still counts
       that task — and the next claim takes the job first and polls it, never resubmits.
    2. Every slot whose lease ran out is freed unless its job has a vendor task and is not
       over yet."""
    rows = session.execute(
        text(
            """
            UPDATE creative_jobs
            SET status = 'queued', claimed_by = NULL, lease_until = NULL,
                claim_token = claim_token + 1
            WHERE id IN (
                SELECT id FROM creative_jobs
                WHERE status IN ('claimed','submitted') AND lease_until < :now
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
            """
        ),
        {"now": now},
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
                    WHERE j.id = s.holder_job_id AND j.vendor_task_id IS NOT NULL
                      AND j.status NOT IN ('succeeded','failed','cancelled')
              )
            RETURNING s.slot_no
            """
        ),
        {"now": now, "requeued": [str(job_id) for job_id in requeued]},
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
