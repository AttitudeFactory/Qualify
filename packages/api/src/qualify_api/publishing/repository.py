"""Persistence for publish attempts (A4, layer L2) — the write-ahead record.

The contract, in one line: **if it is not written, the platform call does not happen.**
`start_attempt` INSERTs before anything touches Meta; a crash at any later point leaves a
row that reconciliation can resolve by `creation_id`, never an absence that forces
guessing.

Two invariants are the database's, not this code's, and this module's job is to TRANSLATE
them, not to re-implement or dodge them:

- **Idempotency** is `uq_attempt_idempotency (connection_id, idempotency_key)`. A
  duplicate `start_attempt` returns the EXISTING row (`created=False`) — no second row,
  and the caller knows not to fire a second publish.
- **Settle-once** is the `publish_attempts_settle_once` trigger. Deliberately NO
  `UPDATE ... WHERE settled_at IS NULL` here — the migration bans converting the conflict
  into a silent no-op (0003:50-53). The trigger raises `check_violation`; this module
  catches exactly that and raises `AlreadySettled`, which the service treats as the
  idempotent outcome of a retry, not as a 500. The smoke run of 2026-08-07 saw this for
  real: a timed-out `media_publish` that HAD published — the retry that would have
  double-posted is the one this translation stops.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.publishing.models import PublishAttempt

# Terminal statuses — the only two `settle` accepts, because
# `ck_attempt_settled_matches_status` requires `settled_at` and a terminal status to be
# written as one fact.
TERMINAL_STATUSES = frozenset({"published", "failed"})

_CHECK_VIOLATION = "23514"  # the trigger raises USING ERRCODE = 'check_violation'


class AlreadySettled(Exception):
    """The row is terminal. For a retry this is SUCCESS-shaped, not an error: the outcome
    already exists — read it, do not overwrite it and do not publish again."""


@dataclass(frozen=True)
class AttemptRecord:
    """The attempt as the service reasons about it. A snapshot, not a live row."""

    id: UUID
    tenant_id: UUID
    connection_id: UUID
    idempotency_key: str
    media_product_type: str
    adapter_version: str
    status: str
    creation_id: str | None
    platform_error_code: str | None
    retriable: bool | None
    published_media_id: str | None
    started_at: datetime
    settled_at: datetime | None

    @property
    def is_settled(self) -> bool:
        return self.settled_at is not None


@dataclass(frozen=True)
class AttemptStart:
    """`created=False` means the idempotency key already named an attempt — the caller
    must return that outcome instead of publishing again."""

    record: AttemptRecord
    created: bool


class PublishAttemptRepository(Protocol):
    def start_attempt(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
        media_product_type: str,
        adapter_version: str,
        scheduled_post_id: UUID | None = None,
    ) -> AttemptStart: ...

    def record_creation_id(
        self, *, tenant_id: UUID, attempt_id: UUID, creation_id: str
    ) -> None: ...

    def advance_status(self, *, tenant_id: UUID, attempt_id: UUID, status: str) -> None: ...

    def settle(
        self,
        *,
        tenant_id: UUID,
        attempt_id: UUID,
        status: str,
        published_media_id: str | None = None,
        platform_error_code: str | None = None,
        retriable: bool | None = None,
    ) -> None: ...

    def record_publish_sent(self, *, tenant_id: UUID, attempt_id: UUID, marker: str) -> None: ...

    def get_attempt(self, *, tenant_id: UUID, attempt_id: UUID) -> AttemptRecord | None: ...

    def find_by_idempotency_key(
        self, *, tenant_id: UUID, connection_id: UUID, idempotency_key: str
    ) -> AttemptRecord | None: ...


def _snapshot(row: PublishAttempt) -> AttemptRecord:
    return AttemptRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        connection_id=row.connection_id,
        idempotency_key=row.idempotency_key,
        media_product_type=row.media_product_type,
        adapter_version=row.adapter_version,
        status=row.status,
        creation_id=row.creation_id,
        platform_error_code=row.platform_error_code,
        retriable=row.retriable,
        published_media_id=row.published_media_id,
        started_at=row.started_at,
        settled_at=row.settled_at,
    )


def _is_settle_once_violation(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == _CHECK_VIOLATION


class MemoryPublishAttemptRepository:
    """In-memory implementation mirroring the two database-owned invariants — duplicate
    keys return the existing attempt, and a settled row refuses every update. Lives in
    production code for the same reason `InMemoryEventPublisher` does: the offline suite
    and the in-process dev path both need it, and two copies would drift."""

    def __init__(self) -> None:
        self.rows: dict[UUID, AttemptRecord] = {}

    def start_attempt(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
        media_product_type: str,
        adapter_version: str,
        scheduled_post_id: UUID | None = None,
    ) -> AttemptStart:
        existing = self.find_by_idempotency_key(
            tenant_id=tenant_id, connection_id=connection_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            return AttemptStart(record=existing, created=False)
        record = AttemptRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
            media_product_type=media_product_type,
            adapter_version=adapter_version,
            status="pending",
            creation_id=None,
            platform_error_code=None,
            retriable=None,
            published_media_id=None,
            started_at=datetime.now(UTC),
            settled_at=None,
        )
        self.rows[record.id] = record
        return AttemptStart(record=record, created=True)

    def record_creation_id(self, *, tenant_id: UUID, attempt_id: UUID, creation_id: str) -> None:
        self._mutate(attempt_id, creation_id=creation_id)

    def advance_status(self, *, tenant_id: UUID, attempt_id: UUID, status: str) -> None:
        if status in TERMINAL_STATUSES:
            raise ValueError(f"terminal status {status!r} must go through settle()")
        self._mutate(attempt_id, status=status)

    def settle(
        self,
        *,
        tenant_id: UUID,
        attempt_id: UUID,
        status: str,
        published_media_id: str | None = None,
        platform_error_code: str | None = None,
        retriable: bool | None = None,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"settle() requires a terminal status, got {status!r}")
        self._mutate(
            attempt_id,
            status=status,
            settled_at=datetime.now(UTC),
            published_media_id=published_media_id,
            platform_error_code=platform_error_code,
            retriable=retriable,
        )

    def record_publish_sent(self, *, tenant_id: UUID, attempt_id: UUID, marker: str) -> None:
        self._mutate(attempt_id, platform_error_code=marker)

    def get_attempt(self, *, tenant_id: UUID, attempt_id: UUID) -> AttemptRecord | None:
        record = self.rows.get(attempt_id)
        return record if record is not None and record.tenant_id == tenant_id else None

    def find_by_idempotency_key(
        self, *, tenant_id: UUID, connection_id: UUID, idempotency_key: str
    ) -> AttemptRecord | None:
        for record in self.rows.values():
            if record.connection_id == connection_id and record.idempotency_key == idempotency_key:
                return record
        return None

    def _mutate(self, attempt_id: UUID, **changes: object) -> None:
        record = self.rows[attempt_id]
        if record.settled_at is not None:  # the in-memory settle_once trigger
            raise AlreadySettled(str(attempt_id))
        self.rows[attempt_id] = replace(record, **changes)  # type: ignore[arg-type]


class PostgresPublishAttemptRepository:
    """All access through `tenant_session` — RLS scopes every statement, and the composite
    FK keeps a row's tenant agreeing with its connection's."""

    def start_attempt(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
        media_product_type: str,
        adapter_version: str,
        scheduled_post_id: UUID | None = None,
    ) -> AttemptStart:
        try:
            with tenant_session(tenant_id) as session:
                row = PublishAttempt(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    scheduled_post_id=scheduled_post_id,
                    idempotency_key=idempotency_key,
                    media_product_type=media_product_type,
                    adapter_version=adapter_version,
                    status="pending",
                )
                session.add(row)
                session.flush()
                return AttemptStart(record=_snapshot(row), created=True)
        except IntegrityError:
            # `uq_attempt_idempotency`: the operation already exists. Return it — the
            # caller must NOT publish again.
            existing = self.find_by_idempotency_key(
                tenant_id=tenant_id, connection_id=connection_id, idempotency_key=idempotency_key
            )
            if existing is None:  # pragma: no cover — the row that just conflicted vanished
                raise
            return AttemptStart(record=existing, created=False)

    def record_creation_id(self, *, tenant_id: UUID, attempt_id: UUID, creation_id: str) -> None:
        self._update(tenant_id, attempt_id, {"creation_id": creation_id})

    def advance_status(self, *, tenant_id: UUID, attempt_id: UUID, status: str) -> None:
        if status in TERMINAL_STATUSES:
            # `ck_attempt_settled_matches_status` would reject it anyway; failing here
            # names the actual mistake instead of surfacing a constraint string.
            raise ValueError(f"terminal status {status!r} must go through settle()")
        self._update(tenant_id, attempt_id, {"status": status})

    def settle(
        self,
        *,
        tenant_id: UUID,
        attempt_id: UUID,
        status: str,
        published_media_id: str | None = None,
        platform_error_code: str | None = None,
        retriable: bool | None = None,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"settle() requires a terminal status, got {status!r}")
        # `settled_at` and the terminal status land in ONE statement — the CHECK demands
        # they agree, and two statements would open a window where they do not.
        self._update(
            tenant_id,
            attempt_id,
            {
                "status": status,
                "settled_at": datetime.now().astimezone(),
                "published_media_id": published_media_id,
                "platform_error_code": platform_error_code,
                "retriable": retriable,
            },
        )

    def record_publish_sent(self, *, tenant_id: UUID, attempt_id: UUID, marker: str) -> None:
        """A6-min: written BEFORE `publish_container` goes out — the write-ahead of the
        send itself. Mark after sending and a crash in between resurrects the double-post."""
        self._update(tenant_id, attempt_id, {"platform_error_code": marker})

    def get_attempt(self, *, tenant_id: UUID, attempt_id: UUID) -> AttemptRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(PublishAttempt, attempt_id)
            return _snapshot(row) if row is not None else None

    def find_by_idempotency_key(
        self, *, tenant_id: UUID, connection_id: UUID, idempotency_key: str
    ) -> AttemptRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(PublishAttempt).where(
                    PublishAttempt.connection_id == connection_id,
                    PublishAttempt.idempotency_key == idempotency_key,
                )
            )
            return _snapshot(row) if row is not None else None

    def _update(self, tenant_id: UUID, attempt_id: UUID, values: dict[str, object]) -> None:
        """One UPDATE, no `WHERE settled_at IS NULL` — the trigger is the arbiter of
        settledness and its refusal is translated, never pre-empted (0003:50-53)."""
        try:
            with tenant_session(tenant_id) as session:
                row = session.get(PublishAttempt, attempt_id)
                if row is None:
                    raise KeyError(f"no publish_attempt {attempt_id} visible in this tenant")
                for column, value in values.items():
                    setattr(row, column, value)
                session.flush()
        except DBAPIError as exc:
            if _is_settle_once_violation(exc):
                raise AlreadySettled(str(attempt_id)) from None
            raise
