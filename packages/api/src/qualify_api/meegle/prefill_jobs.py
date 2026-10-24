"""The queue of Alta prefill jobs (`alta_prefill_jobs`, migration 0092; PB-4, m-24852198).

One row per (Meegle item, network, username): the idempotency key. Every write and every
claim runs through `tenant_session(draft tenant)`, so RLS scopes it; the one cross-tenant
read is the worker's discovery of which tenants have due jobs (`admin_session`, tenant
ids only — `qualify_admin` holds SELECT and nothing else on the table).

Lifecycle (`status`): `pending` → `running` (claimed) → `commenting` (the prefill ran, its
outcome is stored, the Meegle comment is due) → `done`. A transient read failure goes back
to `pending` once (`retry`). The claim counts the attempt — `attempts` while the prefill
has no outcome yet, `comment_attempts` after — so a worker that dies mid-run still spends
one, and a `running` row whose lock is older than `STALE_AFTER` is reclaimed — flagged
`reclaimed`, so the runner closes it instead of running the vendor again (its spend was
never recorded: a rerun could exceed the cap). Every settlement is a compare-and-set on
`(status = 'running', locked_by = <me>)`.

`InMemoryPrefillJobs` is the offline fake with the same contract.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMMENTING = "commenting"
STATUS_DONE = "done"

#: A `running` row older than this lost its worker (crash, deploy): it is reclaimed. It
#: must exceed the slowest possible run: `prefill.MAX_RUN_SECONDS` (~21 min with the
#: bounded Claude client) — a test pins the margin.
STALE_AFTER = timedelta(minutes=30)


@dataclass(frozen=True)
class NewPrefillJob:
    tenant_id: UUID
    brand_id: UUID
    meegle_work_item_id: int
    network: str
    handle: str
    max_usd: Decimal
    pipeline_version: str
    #: Set for a job that needs no prefill, only its comment (an Alta without an
    #: account: `handle == ""`, outcome `no_handle`): enqueued straight to `commenting`.
    outcome: str | None = None


@dataclass(frozen=True)
class PrefillJob:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    meegle_work_item_id: int
    network: str
    handle: str
    attempts: int  # prefill runs, this claim included while `outcome` is None
    comment_attempts: int  # comment tries, this claim included once `outcome` is set
    outcome: str | None
    proposal_written: bool
    max_usd: Decimal
    spent_usd: Decimal
    runs: tuple[Mapping[str, Any], ...] = ()
    #: This claim took the row back from a worker whose lock went stale (it crashed, or
    #: failed to settle): whatever that worker was doing may have happened.
    reclaimed: bool = False

    @property
    def needs_prefill(self) -> bool:
        return self.outcome is None


class PrefillJobs(Protocol):
    def enqueue(self, job: NewPrefillJob) -> bool:
        """Insert; False when that (item, network, handle) is already queued (any state)."""
        ...

    def due_tenants(self, *, now: datetime) -> list[UUID]: ...

    def claim(
        self, tenant_id: UUID, *, now: datetime, worker_id: str, limit: int
    ) -> list[PrefillJob]: ...

    def retry(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        next_at: datetime,
        spent_usd: Decimal,
        run: Mapping[str, Any],
    ) -> bool: ...

    def finish_prefill(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        outcome: str,
        written: bool,
        spent_usd: Decimal,
        run: Mapping[str, Any] | None,
        comment: bool,
    ) -> bool:
        """Store the outcome: `commenting` when a comment is due, else `done`."""
        ...

    def comment_posted(self, job: PrefillJob, *, worker_id: str, now: datetime) -> bool: ...

    def comment_failed(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        next_at: datetime | None,
        error: str,
    ) -> bool:
        """Back to `commenting` at `next_at`; `next_at=None` gives up (`done`, error kept)."""
        ...


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------

TenantSessionFactory = Callable[[UUID], AbstractContextManager[Session]]
AdminSessionFactory = Callable[[], AbstractContextManager[Session]]

_COLUMNS = """
    id, tenant_id, brand_id, meegle_work_item_id, network, handle, attempts,
    comment_attempts, outcome, proposal_written, max_usd, spent_usd, runs
"""

_DUE = """
    (status IN ('pending', 'commenting') AND next_attempt_at <= :now)
    OR (status = 'running' AND locked_at < :stale)
"""

_HELD = "id = :id AND status = 'running' AND locked_by = :worker"
_RETURNING = ", ".join(f"j.{c.strip()}" for c in _COLUMNS.split(","))


def _job(row: Any) -> PrefillJob:
    runs = row.runs if isinstance(row.runs, list) else json.loads(row.runs or "[]")
    return PrefillJob(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        meegle_work_item_id=int(row.meegle_work_item_id),
        network=row.network,
        handle=row.handle,
        attempts=int(row.attempts),
        comment_attempts=int(row.comment_attempts),
        outcome=row.outcome,
        proposal_written=bool(row.proposal_written),
        max_usd=Decimal(row.max_usd),
        spent_usd=Decimal(row.spent_usd),
        runs=tuple(runs),
        reclaimed=bool(getattr(row, "reclaimed", False)),
    )


def _run_json(run: Mapping[str, Any] | None) -> str:
    return json.dumps([dict(run)] if run else [], default=str, ensure_ascii=False)


class PostgresPrefillJobs:
    """`alta_prefill_jobs` through the sanctioned doors. Factories are for tests."""

    def __init__(
        self,
        tenant_session_factory: TenantSessionFactory | None = None,
        admin_session_factory: AdminSessionFactory | None = None,
    ) -> None:
        if tenant_session_factory is None:
            from qualify_shared.db.session import tenant_session  # noqa: PLC0415

            tenant_session_factory = tenant_session
        if admin_session_factory is None:
            from qualify_shared.db.admin import admin_session  # noqa: PLC0415

            admin_session_factory = admin_session
        self._tenant = tenant_session_factory
        self._admin = admin_session_factory

    def enqueue(self, job: NewPrefillJob) -> bool:
        with self._tenant(job.tenant_id) as session:
            return (
                session.execute(
                    text(
                        """
                        INSERT INTO alta_prefill_jobs
                            (tenant_id, brand_id, meegle_work_item_id, network, handle,
                             max_usd, pipeline_version, outcome, status)
                        VALUES (:tenant_id, :brand_id, :item, :network, :handle,
                                :max_usd, :pipeline_version, :outcome,
                                CASE WHEN CAST(:outcome AS text) IS NULL THEN 'pending'
                                     ELSE 'commenting' END)
                        ON CONFLICT ON CONSTRAINT uq_alta_prefill_jobs_key DO NOTHING
                        """
                    ),
                    {
                        "tenant_id": job.tenant_id,
                        "brand_id": job.brand_id,
                        "item": job.meegle_work_item_id,
                        "network": job.network,
                        "handle": job.handle,
                        "max_usd": job.max_usd,
                        "pipeline_version": job.pipeline_version,
                        "outcome": job.outcome,
                    },
                ).rowcount
                == 1
            )

    def due_tenants(self, *, now: datetime) -> list[UUID]:
        with self._admin() as session:
            rows = session.execute(
                text(f"SELECT DISTINCT tenant_id FROM alta_prefill_jobs WHERE {_DUE}"),
                {"now": now, "stale": now - STALE_AFTER},
            ).all()
        return [r.tenant_id for r in rows]

    def claim(
        self, tenant_id: UUID, *, now: datetime, worker_id: str, limit: int
    ) -> list[PrefillJob]:
        with self._tenant(tenant_id) as session:
            rows = session.execute(
                text(
                    f"""
                    WITH due AS (
                        SELECT id, status AS prior_status FROM alta_prefill_jobs
                         WHERE tenant_id = :tenant AND ({_DUE})
                         ORDER BY next_attempt_at
                         LIMIT :limit
                         FOR UPDATE SKIP LOCKED)
                    UPDATE alta_prefill_jobs j
                       SET status = 'running', locked_at = :now, locked_by = :worker,
                           updated_at = :now,
                           attempts = CASE WHEN j.outcome IS NULL THEN j.attempts + 1
                                           ELSE j.attempts END,
                           comment_attempts = CASE WHEN j.outcome IS NULL
                                                   THEN j.comment_attempts
                                                   ELSE j.comment_attempts + 1 END
                      FROM due
                     WHERE j.id = due.id
                    RETURNING {_RETURNING}, due.prior_status = 'running' AS reclaimed
                    """
                ),
                {
                    "now": now,
                    "stale": now - STALE_AFTER,
                    "worker": worker_id,
                    "tenant": tenant_id,
                    "limit": limit,
                },
            ).all()
        return [_job(r) for r in rows]

    def _settle(self, job: PrefillJob, worker_id: str, sets: str, params: dict[str, Any]) -> bool:
        with self._tenant(job.tenant_id) as session:
            return (
                session.execute(
                    text(
                        f"""
                        UPDATE alta_prefill_jobs
                           SET {sets}, locked_at = NULL, locked_by = NULL, updated_at = :now
                         WHERE {_HELD}
                        """
                    ),
                    {"id": job.id, "worker": worker_id, **params},
                ).rowcount
                == 1
            )

    def retry(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        next_at: datetime,
        spent_usd: Decimal,
        run: Mapping[str, Any],
    ) -> bool:
        return self._settle(
            job,
            worker_id,
            "status = 'pending', next_attempt_at = :next_at, spent_usd = :spent, "
            "runs = runs || CAST(:run AS jsonb)",
            {"now": now, "next_at": next_at, "spent": spent_usd, "run": _run_json(run)},
        )

    def finish_prefill(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        outcome: str,
        written: bool,
        spent_usd: Decimal,
        run: Mapping[str, Any] | None,
        comment: bool,
    ) -> bool:
        return self._settle(
            job,
            worker_id,
            "status = :status, outcome = :outcome, proposal_written = :written, "
            "spent_usd = :spent, runs = runs || CAST(:run AS jsonb), next_attempt_at = :now, "
            "finished_at = CASE WHEN :done THEN CAST(:now AS timestamptz) ELSE NULL END",
            {
                "now": now,
                "status": STATUS_COMMENTING if comment else STATUS_DONE,
                "done": not comment,
                "outcome": outcome,
                "written": written,
                "spent": spent_usd,
                "run": _run_json(run),
            },
        )

    def comment_posted(self, job: PrefillJob, *, worker_id: str, now: datetime) -> bool:
        return self._settle(
            job,
            worker_id,
            "status = 'done', comment_posted_at = :now, finished_at = :now, last_error = NULL",
            {"now": now},
        )

    def comment_failed(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        next_at: datetime | None,
        error: str,
    ) -> bool:
        if next_at is None:
            return self._settle(
                job,
                worker_id,
                "status = 'done', finished_at = :now, last_error = :error",
                {"now": now, "error": error[:200]},
            )
        return self._settle(
            job,
            worker_id,
            "status = 'commenting', next_attempt_at = :next_at, last_error = :error",
            {"now": now, "next_at": next_at, "error": error[:200]},
        )


# --------------------------------------------------------------------------------------
# In memory (tests)
# --------------------------------------------------------------------------------------


@dataclass
class _Row:
    job: PrefillJob
    status: str = STATUS_PENDING
    next_attempt_at: datetime | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    comment_posted_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    pipeline_version: str = ""


@dataclass
class InMemoryPrefillJobs:
    """The `PrefillJobs` contract in a dict — the fake for offline tests."""

    rows: dict[UUID, _Row] = field(default_factory=dict)

    def enqueue(self, job: NewPrefillJob) -> bool:
        key = (job.meegle_work_item_id, job.network, job.handle)
        if any(
            (r.job.meegle_work_item_id, r.job.network, r.job.handle) == key
            for r in self.rows.values()
        ):
            return False
        new = PrefillJob(
            id=uuid4(),
            tenant_id=job.tenant_id,
            brand_id=job.brand_id,
            meegle_work_item_id=job.meegle_work_item_id,
            network=job.network,
            handle=job.handle,
            attempts=0,
            comment_attempts=0,
            outcome=None,
            proposal_written=False,
            max_usd=job.max_usd,
            spent_usd=Decimal("0"),
        )
        if job.outcome is not None:
            new = replace(new, outcome=job.outcome)
        self.rows[new.id] = _Row(
            job=new,
            status=STATUS_COMMENTING if job.outcome is not None else STATUS_PENDING,
            pipeline_version=job.pipeline_version,
        )
        return True

    def _due(self, row: _Row, now: datetime) -> bool:
        if row.status in (STATUS_PENDING, STATUS_COMMENTING):
            return row.next_attempt_at is None or row.next_attempt_at <= now
        return (
            row.status == STATUS_RUNNING
            and row.locked_at is not None
            and row.locked_at < now - STALE_AFTER
        )

    def due_tenants(self, *, now: datetime) -> list[UUID]:
        return list(dict.fromkeys(r.job.tenant_id for r in self.rows.values() if self._due(r, now)))

    def claim(
        self, tenant_id: UUID, *, now: datetime, worker_id: str, limit: int
    ) -> list[PrefillJob]:
        out: list[PrefillJob] = []
        for row in self.rows.values():
            if len(out) >= limit:
                break
            if row.job.tenant_id != tenant_id or not self._due(row, now):
                continue
            reclaimed = row.status == STATUS_RUNNING
            if row.job.outcome is None:
                row.job = replace(row.job, attempts=row.job.attempts + 1, reclaimed=reclaimed)
            else:
                row.job = replace(
                    row.job, comment_attempts=row.job.comment_attempts + 1, reclaimed=reclaimed
                )
            row.status, row.locked_at, row.locked_by = STATUS_RUNNING, now, worker_id
            out.append(row.job)
        return out

    def _held(self, job: PrefillJob, worker_id: str) -> _Row | None:
        row = self.rows.get(job.id)
        if row is None or row.status != STATUS_RUNNING or row.locked_by != worker_id:
            return None
        row.locked_at = row.locked_by = None
        return row

    def retry(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        next_at: datetime,
        spent_usd: Decimal,
        run: Mapping[str, Any],
    ) -> bool:
        row = self._held(job, worker_id)
        if row is None:
            return False
        row.status, row.next_attempt_at = STATUS_PENDING, next_at
        row.job = replace(row.job, spent_usd=spent_usd, runs=(*row.job.runs, dict(run)))
        return True

    def finish_prefill(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        outcome: str,
        written: bool,
        spent_usd: Decimal,
        run: Mapping[str, Any] | None,
        comment: bool,
    ) -> bool:
        row = self._held(job, worker_id)
        if row is None:
            return False
        row.status = STATUS_COMMENTING if comment else STATUS_DONE
        row.next_attempt_at = now
        row.finished_at = None if comment else now
        runs = (*row.job.runs, dict(run)) if run else row.job.runs
        row.job = replace(
            row.job, outcome=outcome, proposal_written=written, spent_usd=spent_usd, runs=runs
        )
        return True

    def comment_posted(self, job: PrefillJob, *, worker_id: str, now: datetime) -> bool:
        row = self._held(job, worker_id)
        if row is None:
            return False
        row.status, row.comment_posted_at, row.finished_at = STATUS_DONE, now, now
        row.last_error = None
        return True

    def comment_failed(
        self,
        job: PrefillJob,
        *,
        worker_id: str,
        now: datetime,
        next_at: datetime | None,
        error: str,
    ) -> bool:
        row = self._held(job, worker_id)
        if row is None:
            return False
        row.last_error = error[:200]
        if next_at is None:
            row.status, row.finished_at = STATUS_DONE, now
        else:
            row.status, row.next_attempt_at = STATUS_COMMENTING, next_at
        return True


__all__ = [
    "STALE_AFTER",
    "STATUS_COMMENTING",
    "STATUS_DONE",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "InMemoryPrefillJobs",
    "NewPrefillJob",
    "PostgresPrefillJobs",
    "PrefillJob",
    "PrefillJobs",
]
