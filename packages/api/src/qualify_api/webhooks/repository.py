"""The intake queue and its retention purge (QUA-147) — `qualify_webhook_worker` only.

Everything here runs OUTSIDE the HTTP request, through `webhook_worker_session()`, whose
grants (migration 0050) allow exactly: reading every intake column except `raw_body`/
`signature_header`, updating the queue columns of `meta_webhook_events`, and deleting.

**Queue.** `claim` takes due rows with `FOR UPDATE SKIP LOCKED` (two processors never
take the same change) and counts the attempt AT CLAIM TIME, so a process that dies
mid-change still spends an attempt. A `processing` row whose lock is older than
`STALE_AFTER` is reclaimed — or, if its attempts are spent, settled `dead`. Every
settlement is a compare-and-set on `(status='processing', locked_by=<me>)`: a worker that
lost its lock cannot overwrite whoever reclaimed the row.

**Retention** (founder decision 2026-10-12, QUA-127's "≤30 días"): every settled or
failed change older than `RETENTION` (29 days, so a purge at least every 24 h keeps the
worst case at 30) is deleted; `pending`/`processing` rows are NEVER deleted by age —
losing an unprocessed event is worse than keeping it. A delivery goes once it is older
than the cutoff and no change still references it. `purge_by_entry_id` deletes one
account's changes in ANY state, and every delivery whose body mentions it, at once — the
hook QUA-127 will call on disconnection. Changes of OTHER accounts that shared such a
delivery survive (the FK is `ON DELETE SET NULL`). Both purges are dry-run unless
`execute=True`, and refuse a retention shorter than `MIN_RETENTION`.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import text
from sqlalchemy.orm import Session

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_PROCESSED = "processed"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ORPHAN = "orphan"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"

# Settled outcomes a handler may report (`failed`/`dead` go through `fail`).
SETTLED_STATUSES = frozenset(
    {STATUS_PROCESSED, STATUS_UNSUPPORTED, STATUS_ORPHAN, STATUS_AMBIGUOUS, STATUS_DEAD}
)
# What the age purge may delete: everything but the two in-flight states.
PURGEABLE_STATUSES = (
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    STATUS_ORPHAN,
    STATUS_AMBIGUOUS,
    STATUS_FAILED,
    STATUS_DEAD,
)

MAX_ATTEMPTS = 6
# Wait after the Nth failed attempt (N = 1..5); the 6th failure is `dead`.
BACKOFF: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
)
STALE_AFTER = timedelta(minutes=10)
RETENTION = timedelta(days=29)
MIN_RETENTION = timedelta(days=1)

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class ClaimedEvent:
    id: UUID
    delivery_id: UUID | None
    object: str
    entry_id: str
    field: str
    value: Any
    attempts: int  # including this claim


@dataclass(frozen=True)
class PurgeReport:
    events: int
    deliveries: int
    executed: bool  # False = dry run: counts of what WOULD be deleted, nothing deleted


def backoff_for(attempts: int) -> timedelta:
    """Wait before the next try after `attempts` failed ones (1-based)."""
    return BACKOFF[min(attempts, len(BACKOFF)) - 1]


class WebhookQueue:
    """The processor's view of `meta_webhook_events`. `session_factory` defaults to the
    real `qualify_webhook_worker` door; tests may pass it explicitly."""

    def __init__(self, session_factory: SessionFactory = webhook_worker_session) -> None:
        self._session = session_factory

    def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]:
        stale_cutoff = now - STALE_AFTER
        with self._session() as session:
            # A stale lock with no attempts left is not reclaimed: it is settled `dead`.
            session.execute(
                text(
                    """
                    UPDATE meta_webhook_events
                       SET status = 'dead', processed_at = :now,
                           last_error = 'stale_lock_attempts_exhausted',
                           locked_at = NULL, locked_by = NULL
                     WHERE status = 'processing' AND locked_at < :stale
                       AND attempts >= :max
                    """
                ),
                {"now": now, "stale": stale_cutoff, "max": MAX_ATTEMPTS},
            )
            rows = session.execute(
                text(
                    """
                    UPDATE meta_webhook_events
                       SET status = 'processing', locked_at = :now, locked_by = :worker,
                           attempts = attempts + 1
                     WHERE id IN (
                        SELECT id FROM meta_webhook_events
                         WHERE (status IN ('pending', 'failed') AND next_attempt_at <= :now)
                            OR (status = 'processing' AND locked_at < :stale)
                         ORDER BY received_at, change_index
                         LIMIT :limit
                         FOR UPDATE SKIP LOCKED)
                    RETURNING id, delivery_id, object, entry_id, field, value, attempts,
                              received_at, change_index
                    """
                ),
                {"now": now, "worker": worker_id, "stale": stale_cutoff, "limit": limit},
            ).all()
        rows = sorted(rows, key=lambda r: (r.received_at, r.change_index))
        return [
            ClaimedEvent(
                id=r.id,
                delivery_id=r.delivery_id,
                object=r.object,
                entry_id=r.entry_id,
                field=r.field,
                value=r.value,
                attempts=r.attempts,
            )
            for r in rows
        ]

    def settle(
        self,
        *,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        status: str,
        error: str | None = None,
    ) -> bool:
        """Final outcome for a claimed change. False = this worker no longer holds it
        (reclaimed after going stale): nothing was written."""
        if status not in SETTLED_STATUSES:
            raise ValueError(f"not a settled status: {status!r}")
        with self._session() as session:
            return (
                session.execute(
                    text(
                        """
                        UPDATE meta_webhook_events
                           SET status = :status, processed_at = :now, last_error = :error,
                               locked_at = NULL, locked_by = NULL
                         WHERE id = :id AND status = 'processing' AND locked_by = :worker
                        """
                    ),
                    {
                        "status": status,
                        "now": now,
                        "error": error,
                        "id": event_id,
                        "worker": worker_id,
                    },
                ).rowcount
                == 1
            )

    def fail(
        self, *, event_id: UUID, worker_id: str, now: datetime, attempts: int, error: str
    ) -> str | None:
        """A retryable failure: `failed` with the next backoff, or `dead` once
        `MAX_ATTEMPTS` are spent. Returns the status written, or None if this worker no
        longer holds the row."""
        exhausted = attempts >= MAX_ATTEMPTS
        status = STATUS_DEAD if exhausted else STATUS_FAILED
        next_at = now if exhausted else now + backoff_for(attempts)
        with self._session() as session:
            written = session.execute(
                text(
                    """
                    UPDATE meta_webhook_events
                       SET status = :status, next_attempt_at = :next_at,
                           last_error = :error,
                           processed_at = CASE WHEN :dead THEN CAST(:now AS timestamptz)
                                               ELSE NULL END,
                           locked_at = NULL, locked_by = NULL
                     WHERE id = :id AND status = 'processing' AND locked_by = :worker
                    """
                ),
                {
                    "status": status,
                    "next_at": next_at,
                    "error": error,
                    "dead": exhausted,
                    "now": now,
                    "id": event_id,
                    "worker": worker_id,
                },
            ).rowcount
        return status if written == 1 else None

    # -- retention -------------------------------------------------------------------

    def purge_expired(
        self, *, now: datetime, older_than: timedelta = RETENTION, execute: bool = False
    ) -> PurgeReport:
        """Age purge. Dry run unless `execute`. Never touches `pending`/`processing`."""
        if older_than < MIN_RETENTION:
            raise ValueError(f"refusing a retention shorter than {MIN_RETENTION}")
        params = {"cutoff": now - older_than, "statuses": list(PURGEABLE_STATUSES)}
        expired_events = "status = ANY(:statuses) AND received_at < :cutoff"
        # A delivery goes when it is old AND every change still pointing at it is itself
        # going in this same purge — one predicate for the dry run and the real run.
        expired_deliveries = """
            d.received_at < :cutoff AND NOT EXISTS (
                SELECT 1 FROM meta_webhook_events e
                 WHERE e.delivery_id = d.id
                   AND NOT (e.status = ANY(:statuses) AND e.received_at < :cutoff)
            )
        """
        with self._session() as session:
            if not execute:
                events = session.execute(
                    text(f"SELECT count(*) FROM meta_webhook_events WHERE {expired_events}"),
                    params,
                ).scalar_one()
                deliveries = session.execute(
                    text(
                        f"SELECT count(*) FROM meta_webhook_deliveries d WHERE {expired_deliveries}"
                    ),
                    params,
                ).scalar_one()
                return PurgeReport(events=events, deliveries=deliveries, executed=False)
            events = session.execute(
                text(f"DELETE FROM meta_webhook_events WHERE {expired_events}"), params
            ).rowcount
            deliveries = session.execute(
                text(f"DELETE FROM meta_webhook_deliveries d WHERE {expired_deliveries}"),
                params,
            ).rowcount
        return PurgeReport(events=events, deliveries=deliveries, executed=True)

    def purge_by_entry_id(self, *, entry_id: str, execute: bool = False) -> PurgeReport:
        """Everything recorded for one account, whatever its state or age (QUA-127).
        Other accounts' changes in a shared delivery survive, unlinked."""
        if not entry_id or not entry_id.strip():
            raise ValueError("entry_id is required")
        params = {"entry_id": entry_id}
        with self._session() as session:
            if not execute:
                events = session.execute(
                    text("SELECT count(*) FROM meta_webhook_events WHERE entry_id = :entry_id"),
                    params,
                ).scalar_one()
                deliveries = session.execute(
                    text(
                        "SELECT count(*) FROM meta_webhook_deliveries "
                        "WHERE :entry_id = ANY(entry_ids)"
                    ),
                    params,
                ).scalar_one()
                return PurgeReport(events=events, deliveries=deliveries, executed=False)
            events = session.execute(
                text("DELETE FROM meta_webhook_events WHERE entry_id = :entry_id"), params
            ).rowcount
            deliveries = session.execute(
                text("DELETE FROM meta_webhook_deliveries WHERE :entry_id = ANY(entry_ids)"),
                params,
            ).rowcount
        return PurgeReport(events=events, deliveries=deliveries, executed=True)
