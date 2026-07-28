"""`db`-marked tests for `PostgresRevocationRepository` (C-04.5), against live Postgres.

The offline suite proves the decision tree against a fake repository. What only a real
database can prove is the half the fake cannot fake: that the write goes through the
RLS-scoped door, that another tenant's connection is invisible rather than merely
unqueried, and that the audit row actually lands with the credential version that was live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.events import DomainEventName, InMemoryEventPublisher
from qualify_api.connections.fsm import ConnectionStatus
from qualify_api.connections.models import ConnectionEvent, PlatformApp, SocialConnection
from qualify_api.connections.revoke import (
    ConnectionNotFound,
    PostgresRevocationRepository,
    RevokeService,
)
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("e0000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("f0000000-0000-4000-8000-00000000000b")


@pytest.fixture
def revocable_connection() -> tuple[UUID, UUID]:
    """An `active` connection of tenant A, at credential version 2.

    Same door split as `test_connections_schema.seeded_connection` (R8): provisioning rows
    via `admin_session`, the connection itself via `tenant_session` — the door C-04 really
    uses, so a grant or policy defect surfaces here instead of being masked by BYPASSRLS.
    """
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        app = PlatformApp(app_id="app-revoke", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_A, email=f"u-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT_A) as session:
        connection = SocialConnection(
            tenant_id=TENANT_A,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=2,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        connection_id = connection.id
    return TENANT_A, connection_id


def _service() -> tuple[RevokeService, InMemoryEventPublisher]:
    publisher = InMemoryEventPublisher()
    return RevokeService(repository=PostgresRevocationRepository(), publisher=publisher), publisher


def test_revocation_persists_status_and_disconnected_at(
    revocable_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = revocable_connection
    service, publisher = _service()
    now = datetime.now(UTC)

    result = service.revoke(tenant_id=tenant_id, connection_id=connection_id, now=now)

    assert result.status is ConnectionStatus.REVOKED
    assert result.changed is True
    assert publisher.names() == [DomainEventName.REVOKED]

    with tenant_session(tenant_id) as session:
        row = session.get(SocialConnection, connection_id)
        assert row is not None
        assert row.status == "revoked"
        assert row.disconnected_at is not None


def test_revocation_writes_one_audit_row_with_the_live_credential_version(
    revocable_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = revocable_connection
    service, _ = _service()

    service.revoke(tenant_id=tenant_id, connection_id=connection_id, actor="user")

    with tenant_session(tenant_id) as session:
        events = session.scalars(
            select(ConnectionEvent).where(ConnectionEvent.connection_id == connection_id)
        ).all()
    revoked = [event for event in events if event.event_type == "revoked"]
    assert len(revoked) == 1
    assert revoked[0].credential_version == 2  # the version that was live when it went away
    assert revoked[0].actor == "user"
    assert revoked[0].tenant_id == tenant_id


def test_second_revocation_writes_no_second_audit_row(
    revocable_connection: tuple[UUID, UUID],
) -> None:
    """Idempotency, proven where it matters: against the real table, not a dict."""
    tenant_id, connection_id = revocable_connection
    service, publisher = _service()

    service.revoke(tenant_id=tenant_id, connection_id=connection_id)
    second = service.revoke(tenant_id=tenant_id, connection_id=connection_id)

    assert second.changed is False
    assert publisher.names() == [DomainEventName.REVOKED]  # still exactly one
    with tenant_session(tenant_id) as session:
        events = session.scalars(
            select(ConnectionEvent).where(
                ConnectionEvent.connection_id == connection_id,
                ConnectionEvent.event_type == "revoked",
            )
        ).all()
    assert len(events) == 1


def test_another_tenant_cannot_revoke_this_connection(
    revocable_connection: tuple[UUID, UUID],
) -> None:
    """RLS, not a `WHERE` clause, is what makes the row invisible to tenant B."""
    _, connection_id = revocable_connection
    service, publisher = _service()

    with pytest.raises(ConnectionNotFound):
        service.revoke(tenant_id=TENANT_B, connection_id=connection_id)

    assert publisher.events == []
    with tenant_session(TENANT_A) as session:
        row = session.get(SocialConnection, connection_id)
        assert row is not None
        assert row.status == "active"  # untouched by the foreign attempt
