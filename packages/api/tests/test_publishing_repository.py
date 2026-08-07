"""A4 — the write-ahead publish-attempt repository.

Split the way the backlog orders it: the idempotency and settle-once invariants are
exercised against an in-memory double offline, AND against the real `uq_attempt_idempotency`
constraint and `publish_attempts_settle_once` trigger under the `db` marker — because the
double asserting a behaviour is only worth something if the real database demonstrably
behaves the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.publishing.repository import (
    TERMINAL_STATUSES,
    AlreadySettled,
    AttemptRecord,
    AttemptStart,
    PostgresPublishAttemptRepository,
)
from qualify_api.tenancy.models import Tenant, User

TENANT_P = UUID("e0000000-0000-4000-8000-0000000000f1")
OTHER_TENANT = UUID("e0000000-0000-4000-8000-0000000000b2")


# --------------------------------------------------------------------------------------
# In-memory double — same observable invariants as the real thing
# --------------------------------------------------------------------------------------


@dataclass
class MemoryPublishAttemptRepository:
    """Mirrors the two database-owned invariants so service tests can run offline:
    duplicate keys return the existing attempt, and a settled row refuses every update."""

    rows: dict[UUID, AttemptRecord] = field(default_factory=dict)

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

    def find_by_idempotency_key(
        self, *, tenant_id: UUID, connection_id: UUID, idempotency_key: str
    ) -> AttemptRecord | None:
        for record in self.rows.values():
            if record.connection_id == connection_id and record.idempotency_key == idempotency_key:
                return record
        return None

    def _mutate(self, attempt_id: UUID, **changes: object) -> None:
        record = self.rows[attempt_id]
        if record.settled_at is not None:  # the double's settle_once trigger
            raise AlreadySettled(str(attempt_id))
        self.rows[attempt_id] = replace(record, **changes)  # type: ignore[arg-type]


def _start(repo: MemoryPublishAttemptRepository, key: str = "op-1") -> AttemptStart:
    return repo.start_attempt(
        tenant_id=TENANT_P,
        connection_id=UUID("22222222-2222-4222-8222-222222222222"),
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )


def test_double_duplicate_key_returns_existing_and_creates_nothing() -> None:
    repo = MemoryPublishAttemptRepository()
    first = _start(repo)
    second = _start(repo)
    assert first.created and not second.created
    assert second.record.id == first.record.id
    assert len(repo.rows) == 1


def test_double_settled_row_refuses_every_update() -> None:
    repo = MemoryPublishAttemptRepository()
    attempt = _start(repo).record
    repo.settle(
        tenant_id=TENANT_P, attempt_id=attempt.id, status="published", published_media_id="m-1"
    )
    with pytest.raises(AlreadySettled):
        repo.settle(tenant_id=TENANT_P, attempt_id=attempt.id, status="failed")
    with pytest.raises(AlreadySettled):
        repo.advance_status(tenant_id=TENANT_P, attempt_id=attempt.id, status="processing")


def test_terminal_vocabulary_guards_hold_without_a_database() -> None:
    """The guards fire BEFORE any session opens, on the real class too — a terminal status
    through advance_status (or a non-terminal through settle) names the actual mistake
    instead of surfacing a constraint string."""
    real = PostgresPublishAttemptRepository()
    with pytest.raises(ValueError, match="settle"):
        real.advance_status(tenant_id=TENANT_P, attempt_id=uuid4(), status="published")
    with pytest.raises(ValueError, match="terminal"):
        real.settle(tenant_id=TENANT_P, attempt_id=uuid4(), status="uploading")


# --------------------------------------------------------------------------------------
# The real constraint and the real trigger (compose Postgres)
# --------------------------------------------------------------------------------------


@pytest.fixture
def seeded_connection() -> tuple[UUID, UUID]:
    """(tenant_id, connection_id) — same two-door split as the schema tests."""
    with admin_session() as session:
        if session.get(Tenant, TENANT_P) is None:
            session.add(
                Tenant(
                    id=TENANT_P,
                    name="t-publishing",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_P, email=f"u-{uuid4()}@p.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT_P) as session:
        conn = SocialConnection(
            tenant_id=TENANT_P,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id
    return TENANT_P, connection_id


@pytest.mark.db
def test_start_attempt_is_the_write_ahead_record(seeded_connection: tuple[UUID, UUID]) -> None:
    """The row exists in 'pending' with creation_id NULL before anything touches Meta —
    a crash before the container call leaves this row, never an absence."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()

    start = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=f"op-{uuid4()}",
        media_product_type="REELS",
        adapter_version="v1",
    )

    assert start.created
    assert start.record.status == "pending"
    assert start.record.creation_id is None
    assert start.record.settled_at is None


@pytest.mark.db
def test_real_unique_constraint_makes_duplicates_return_the_existing_attempt(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    key = f"op-{uuid4()}"

    first = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )
    second = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )

    assert first.created and not second.created
    assert second.record.id == first.record.id
    with tenant_session(tenant_id) as session:
        count = session.scalar(
            text("SELECT count(*) FROM publish_attempts WHERE idempotency_key = :k"),
            {"k": key},
        )
    assert count == 1


@pytest.mark.db
def test_real_trigger_translates_to_already_settled(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Settle lands terminal status + settled_at in one statement (the CHECK demands it);
    the trigger's refusal of ANY later update arrives as AlreadySettled — the idempotent
    retry path, not a 500."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    attempt = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=f"op-{uuid4()}",
        media_product_type="REELS",
        adapter_version="v1",
    ).record

    repo.record_creation_id(tenant_id=tenant_id, attempt_id=attempt.id, creation_id="c-1")
    repo.advance_status(tenant_id=tenant_id, attempt_id=attempt.id, status="processing")
    repo.settle(
        tenant_id=tenant_id, attempt_id=attempt.id, status="published", published_media_id="m-1"
    )

    settled = repo.find_by_idempotency_key(
        tenant_id=tenant_id, connection_id=connection_id, idempotency_key=attempt.idempotency_key
    )
    assert settled is not None and settled.is_settled
    assert settled.status == "published"
    assert settled.published_media_id == "m-1"

    with pytest.raises(AlreadySettled):
        repo.settle(tenant_id=tenant_id, attempt_id=attempt.id, status="failed")
    with pytest.raises(AlreadySettled):
        repo.advance_status(tenant_id=tenant_id, attempt_id=attempt.id, status="processing")


@pytest.mark.db
def test_rls_makes_another_tenants_attempt_invisible(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Invisible at the database, not filtered in Python: the same query under another
    tenant's session simply returns nothing."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    key = f"op-{uuid4()}"
    repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )

    assert (
        repo.find_by_idempotency_key(
            tenant_id=OTHER_TENANT, connection_id=connection_id, idempotency_key=key
        )
        is None
    )
