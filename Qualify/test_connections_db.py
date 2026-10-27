"""Postgres-backed tests for the connections screen (C-06), marked `db`.

Run with the local docker-compose stack up (`just dev`):

    uv run pytest Qualify/test_connections_db.py

These exercise the acceptance criterion that cannot be proven offline: a session
scoped to tenant A never yields tenant B's connections, through the same
`tenant_session` path the screen uses. `test_connections.py` holds the pure tests.

Both this file and `test_connections.py` ARE collected by the root `uv run pytest` now
(the `db` marker is what keeps these out of the offline run, not the path).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from qualify_api.connections import ConnectionNotFound
from qualify_api.connections.models import ConnectionEvent, PlatformApp, SocialConnection
from qualify_api.connections.page_subscription import (
    EVENT_PAGE_UNSUBSCRIBED,
    GraphPageSubscriptionClient,
    SubscriptionResult,
)
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .connections_provider import acting_user_id, connections_for, disconnect
from .inbox_access import InboxAccessVM
from .inbox_provider import connection_access, instagram_connections

pytestmark = pytest.mark.db

# Fixed ids so re-running against a persistent dev database is a no-op.
UI_TENANT_A = UUID("e0000000-0000-4000-8000-0000000000a1")
UI_TENANT_B = UUID("e0000000-0000-4000-8000-0000000000b2")
CONNECTION_A = UUID("e1000000-0000-4000-8000-0000000000a1")
CONNECTION_B = UUID("e1000000-0000-4000-8000-0000000000b2")
PLATFORM_APP = UUID("e2000000-0000-4000-8000-000000000001")

_SCOPES_A = [
    "instagram_business_basic",
    "instagram_business_manage_comments",
    "instagram_business_manage_insights",
]
_SCOPES_B = ["instagram_business_basic"]


def _provision_tenant(tenant_id: UUID, name: str) -> UUID:
    """Tenant + owner + brand via the BYPASSRLS admin door. Returns the owner id."""
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=name,
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        email = f"ui-owner@{name}.test"
        owner = session.scalar(select(User).where(User.tenant_id == tenant_id, User.email == email))
        if owner is None:
            owner = User(tenant_id=tenant_id, email=email, display_name=f"{name} owner")
            session.add(owner)
            session.flush()
        # The owner membership is what `acting_user_id` resolves the OAuth actor from.
        membership = session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id, TenantMember.user_id == owner.id
            )
        )
        if membership is None:
            session.add(TenantMember(tenant_id=tenant_id, user_id=owner.id, role="owner"))
            session.flush()
        if session.scalar(select(Brand).where(Brand.tenant_id == tenant_id)) is None:
            session.add(Brand(tenant_id=tenant_id, name=f"marca-{name}"))
            session.flush()
        return owner.id


def _ensure_platform_app() -> None:
    with admin_session() as session:
        if session.get(PlatformApp, PLATFORM_APP) is None:
            session.add(
                PlatformApp(
                    id=PLATFORM_APP,
                    app_id="ui-test-app",
                    secret_ref="env:UI_TEST_APP_SECRET",
                    api_version="v23.0",
                )
            )


def _ensure_connection(
    *,
    connection_id: UUID,
    tenant_id: UUID,
    owner_id: UUID,
    username: str,
    status: str,
    scopes: list[str],
) -> None:
    """Insert through `tenant_session`: `qualify_admin` has no INSERT on
    `social_connections` by design, so even the fixture writes in-tenant."""
    with tenant_session(tenant_id) as session:
        existing = session.get(SocialConnection, connection_id)
        if existing is not None:
            existing.status = status
            existing.disconnected_at = None
            return
        brand = session.scalar(select(Brand).where(Brand.tenant_id == tenant_id))
        session.add(
            SocialConnection(
                id=connection_id,
                tenant_id=tenant_id,
                brand_id=brand.id if brand else None,
                platform_app_id=PLATFORM_APP,
                platform="instagram",
                account_type="business",
                external_account_id=f"ext-{connection_id}",
                external_username=username,
                linked_page_id=f"page-{connection_id}",
                granted_scopes=scopes,
                status=status,
                access_posture="development",  # ADR 22a — customer zero runs unaudited
                current_credential_version=1,
                connected_by_user_id=owner_id,
            )
        )


def _event_types_by_id(tenant_id: UUID, connection_id: UUID) -> dict[UUID, str]:
    """`connection_events` rows for one connection, read through the tenant's own door."""
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(ConnectionEvent.id, ConnectionEvent.event_type).where(
                ConnectionEvent.connection_id == connection_id
            )
        ).all()
    return {row.id: row.event_type for row in rows}


@pytest.fixture(autouse=True)
def graph_unsubscribe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Tests stay offline: since m-24789549 a revoke also asks Graph to unsubscribe the
    Page from the app's webhooks. Stubbed on the class, so the cached production service
    picks it up too. Returns the page ids it was asked to unsubscribe."""
    calls: list[str] = []

    def unsubscribe(self: GraphPageSubscriptionClient, *, page_id: str) -> SubscriptionResult:
        calls.append(page_id)
        return SubscriptionResult(ok=True)

    monkeypatch.setattr(GraphPageSubscriptionClient, "unsubscribe", unsubscribe)
    return calls


@pytest.fixture
def two_connected_tenants() -> tuple[UUID, UUID]:
    """Two tenants, one Instagram connection each, with disjoint grants."""
    _ensure_platform_app()
    owner_a = _provision_tenant(UI_TENANT_A, "ui-a")
    owner_b = _provision_tenant(UI_TENANT_B, "ui-b")
    _ensure_connection(
        connection_id=CONNECTION_A,
        tenant_id=UI_TENANT_A,
        owner_id=owner_a,
        username="@ui_tenant_a",
        status="active",
        scopes=_SCOPES_A,
    )
    _ensure_connection(
        connection_id=CONNECTION_B,
        tenant_id=UI_TENANT_B,
        owner_id=owner_b,
        username="@ui_tenant_b",
        status="degraded",
        scopes=_SCOPES_B,
    )
    return UI_TENANT_A, UI_TENANT_B


def test_screen_never_paints_another_tenants_connections(
    two_connected_tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = two_connected_tenants
    a = connections_for(tenant_a)
    b = connections_for(tenant_b)
    assert {c.id for c in a} == {str(CONNECTION_A)}
    assert {c.id for c in b} == {str(CONNECTION_B)}
    assert {c.external_username for c in a}.isdisjoint({c.external_username for c in b})


def test_capabilities_reflect_the_real_granted_scopes(
    two_connected_tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = two_connected_tenants
    (a,) = connections_for(tenant_a)
    (b,) = connections_for(tenant_b)
    # A granted comments -> reading is enabled; B granted only basic -> it is not.
    assert "Comentarios" in a.granted_scopes
    assert {c.label for c in a.enabled_capabilities} > {c.label for c in b.enabled_capabilities}
    assert b.disabled_capabilities, "a basic-only grant must show disabled capabilities"
    assert all(c.reason for c in b.disabled_capabilities)


def test_disconnect_revokes_in_tenant_and_is_idempotent(
    two_connected_tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, _ = two_connected_tenants
    assert disconnect(tenant_a, CONNECTION_A) is True, "the first revoke must change the row"
    (revoked,) = connections_for(tenant_a)
    assert revoked.status == "revoked"
    # Second click: a legitimate no-op, not an error and not a second audit row.
    assert disconnect(tenant_a, CONNECTION_A) is False
    (still_revoked,) = connections_for(tenant_a)
    assert still_revoked.status == "revoked"


def test_disconnect_writes_the_audit_row_the_ui_workaround_never_announced(
    two_connected_tenants: tuple[UUID, UUID],
    graph_unsubscribe: list[str],
) -> None:
    """Proof the screen now goes through the real service.

    The pre-C-04 workaround drove the FSM with `next_status` and hand-wrote an event
    with the LONG vocabulary (`connection.revoked`). The service uses the repository's
    short form.

    Asserted as a DIFF around the call, not as a property of the whole table: a
    persistent dev database still carries `connection.revoked` rows written by the old
    workaround, and this test is about what the code writes NOW. Filtering by
    `connection_id` rather than trusting RLS alone keeps it re-runnable.
    """
    tenant_a, _ = two_connected_tenants
    before = _event_types_by_id(tenant_a, CONNECTION_A)
    disconnect(tenant_a, CONNECTION_A)
    after = _event_types_by_id(tenant_a, CONNECTION_A)

    written = sorted(event_type for event_id, event_type in after.items() if event_id not in before)
    # The revoke in the repository's short vocabulary, plus the Page's webhook
    # unsubscription (m-24789549) — best effort, recorded as its own row.
    assert written == sorted(["revoked", EVENT_PAGE_UNSUBSCRIBED]), (
        "the revoke must land exactly one `revoked` row and one Page-unsubscription row, "
        f"in the repository's short vocabulary — got {written}"
    )
    assert graph_unsubscribe == [f"page-{CONNECTION_A}"]


def test_disconnecting_another_tenants_connection_raises_not_found(
    two_connected_tenants: tuple[UUID, UUID],
) -> None:
    """The behavior C-04 changed, against a real database.

    RLS hides B's row from A's session, so the service reads exactly what it would read
    for a nonexistent id — the two cases are indistinguishable ON PURPOSE. What must
    never happen is the old silent `return`, which reported success to A.
    """
    tenant_a, tenant_b = two_connected_tenants
    with pytest.raises(ConnectionNotFound):
        disconnect(tenant_a, CONNECTION_B)
    (b,) = connections_for(tenant_b)
    assert b.status == "degraded", "tenant A must not be able to revoke tenant B's connection"


def test_acting_user_resolves_to_the_tenants_own_owner(
    two_connected_tenants: tuple[UUID, UUID],
) -> None:
    """`user_id` is signed into the OAuth `state`, so it must never cross tenants."""
    tenant_a, tenant_b = two_connected_tenants
    owner_a = _provision_tenant(tenant_a, "ui-a")
    owner_b = _provision_tenant(tenant_b, "ui-b")
    assert acting_user_id(tenant_a) == owner_a
    assert acting_user_id(tenant_b) == owner_b
    assert owner_a != owner_b


def test_comments_keep_disconnected_accounts_inside_their_own_tenant(
    two_connected_tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = two_connected_tenants
    assert {row.id for row in instagram_connections(tenant_a)} == {str(CONNECTION_A)}
    (disconnected,) = instagram_connections(tenant_b)
    assert disconnected.id == str(CONNECTION_B)
    assert disconnected.label == "@ui_tenant_b · Desconectada"
    assert connection_access(tenant_a, CONNECTION_B) == InboxAccessVM()
    own_access = connection_access(tenant_b, CONNECTION_B)
    assert own_access.needs_reconnect
    assert "@ui_tenant_b" in own_access.title


def test_comments_read_the_outage_audit_in_the_business_timezone(
    two_connected_tenants: tuple[UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    from . import inbox_provider

    tenant_a, tenant_b = two_connected_tenants
    with tenant_session(tenant_b) as session:
        row = session.get(SocialConnection, CONNECTION_B)
        row.reconnect_reason = "auth_expired"
        session.add(
            ConnectionEvent(
                tenant_id=tenant_b,
                connection_id=CONNECTION_B,
                credential_version=row.current_credential_version,
                event_type="auth_error",
                actor="system",
                occurred_at=datetime(2026, 10, 27, 20, 40, tzinfo=UTC),
            )
        )
    monkeypatch.setattr(inbox_provider, "tenant_zone", lambda _: ZoneInfo("America/Bogota"))
    assert connection_access(tenant_a, CONNECTION_B) == InboxAccessVM()
    assert connection_access(tenant_b, CONNECTION_B).detail == (
        "No llegan comentarios nuevos desde el martes 3:40 p. m. Los que ya tenías siguen aquí."
    )
