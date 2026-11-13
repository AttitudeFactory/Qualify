"""`PostgresPendingCounts` against the real database (m-24842990): what only Postgres can
prove — the Instagram-messages count follows `attention_state` (pending, not read, not
answered) and RLS keeps another tenant's people out of the counts.

Seeding follows `test_followups_schema_db.py`: tenants/user/app via `admin_session`, the
connection and the rows through `tenant_session`. Fresh tenants per test, so exact counts
hold on re-runs without cleanup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session

from qualify_api.attention import PostgresPendingCounts
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


def _tenant() -> tuple[UUID, UUID, UUID]:
    """A fresh tenant with one Instagram connection → (tenant, connection, user)."""
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"t-attention-{tenant_id.hex[:8]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@attention.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(tenant_id) as session:
        brand = Brand(tenant_id=tenant_id, name="Bianki")
        session.add(brand)
        session.flush()
        connection = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            brand_id=brand.id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4().hex[:12]}",
            linked_page_id="page-1",
            granted_scopes=["instagram_manage_messages"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        return tenant_id, connection.id, user_id


def _dm(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    read: bool = False,
    answered: bool = False,
) -> None:
    """One Instagram conversation with an inbound message at NOW."""
    with tenant_session(tenant_id) as session:
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="dm",
            external_thread_id=f"igsid-{uuid4().hex[:10]}",
            status="open",
            last_message_at=NOW,
            last_inbound_at=NOW,
            last_read_at=NOW + timedelta(minutes=1) if read else None,
        )
        session.add(thread)
        session.flush()
        rows = [
            Message(
                tenant_id=tenant_id,
                thread_id=thread.id,
                connection_id=connection_id,
                external_message_id=f"mid-{uuid4().hex[:10]}",
                direction="inbound",
                text="¿tienen domicilio?",
                posted_at=NOW,
                shape_version="test",
            )
        ]
        if answered:
            rows.append(
                Message(
                    tenant_id=tenant_id,
                    thread_id=thread.id,
                    connection_id=connection_id,
                    external_message_id=f"mid-{uuid4().hex[:10]}",
                    direction="outbound",
                    text="Sí, hasta las 9",
                    posted_at=NOW + timedelta(minutes=2),
                    shape_version="test",
                )
            )
        session.add_all(rows)
        session.flush()


def test_messages_count_only_pending_conversations() -> None:
    tenant_id, connection_id, _user = _tenant()
    _dm(tenant_id, connection_id)
    _dm(tenant_id, connection_id)
    _dm(tenant_id, connection_id, read=True)
    _dm(tenant_id, connection_id, answered=True)

    counts = PostgresPendingCounts().read(tenant_id)

    assert counts.messages == 2
    assert (counts.buyers, counts.comments, counts.whatsapp) == (0, 0, 0)


def test_rls_keeps_another_tenants_people_out() -> None:
    mine, my_connection, _ = _tenant()
    other, other_connection, _ = _tenant()
    _dm(mine, my_connection)
    for _ in range(3):
        _dm(other, other_connection)

    assert PostgresPendingCounts().read(mine).messages == 1
    assert PostgresPendingCounts().read(other).messages == 3
