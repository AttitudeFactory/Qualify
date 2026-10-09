"""`db`-marked tests for the inbox sync seam against REAL Postgres + RLS (B8).

`test_inbox_composition.py` proves the wiring with the visibility readers monkeypatched;
this file proves what those fakes stand in for: that the tenant the CRM session hands
`composition.sync_comments` is the ONLY tenant whose connections it can reach. Nothing
here reaches Meta — every case is refused before credentials are resolved, which is
itself part of what is being pinned.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox import composition
from qualify_api.inbox.composition import InboxConnectionInactive, UnknownInboxConnection
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_OWNER = UUID("e0000000-0000-4000-8000-0000000000b8")
TENANT_OTHER = UUID("e0000000-0000-4000-8000-0000000000b9")


def _ensure_tenant(session: object, tenant_id: UUID, name: str) -> None:
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


def _seed_connection(*, status: str) -> UUID:
    """A fresh connection owned by `TENANT_OWNER`; `TENANT_OTHER` exists but owns none."""
    with admin_session() as session:
        _ensure_tenant(session, TENANT_OWNER, "t-inbox-b8-owner")
        _ensure_tenant(session, TENANT_OTHER, "t-inbox-b8-other")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_OWNER, email=f"u-{uuid4()}@b8.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT_OWNER) as session:
        conn = SocialConnection(
            tenant_id=TENANT_OWNER,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["instagram_basic", "instagram_manage_comments"],
            status=status,
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        return conn.id


def test_the_owner_tenant_reads_its_connection_status() -> None:
    connection_id = _seed_connection(status="active")

    status = composition.production_connection_status_for(
        tenant_id=TENANT_OWNER, connection_id=connection_id
    )

    assert status == "active"


def test_another_tenant_cannot_see_the_connection_at_all() -> None:
    """RLS, not application code, hides the row: both readers the seam runs first
    answer "not visible" for a tenant that does not own it."""
    connection_id = _seed_connection(status="active")

    with pytest.raises(UnknownInboxConnection):
        composition.production_connection_status_for(
            tenant_id=TENANT_OTHER, connection_id=connection_id
        )
    with pytest.raises(UnknownInboxConnection):
        composition.production_ig_user_id_for(tenant_id=TENANT_OTHER, connection_id=connection_id)


@pytest.mark.asyncio
async def test_another_tenant_cannot_sync_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    connection_id = _seed_connection(status="active")
    built: list[UUID] = []

    async def must_not_build(*, tenant_id: UUID, connection_id: UUID) -> object:
        built.append(connection_id)
        raise AssertionError("credentials must never be resolved for another tenant")

    monkeypatch.setattr(composition, "production_inbox_service_for", must_not_build)

    with pytest.raises(UnknownInboxConnection):
        await composition.sync_comments(tenant_id=TENANT_OTHER, connection_id=connection_id)

    assert built == []


@pytest.mark.asyncio
async def test_a_revoked_connection_is_refused_before_its_credential_is_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = _seed_connection(status="revoked")

    async def must_not_build(*, tenant_id: UUID, connection_id: UUID) -> object:
        raise AssertionError("a revoked connection's credential must not be resolved")

    monkeypatch.setattr(composition, "production_inbox_service_for", must_not_build)

    with pytest.raises(InboxConnectionInactive) as excinfo:
        await composition.sync_comments(tenant_id=TENANT_OWNER, connection_id=connection_id)

    assert excinfo.value.status == "revoked"
