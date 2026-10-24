"""`read_results_counts` against the real database (m-24843003, RESULTADOS-5): the counts
respect RLS — two tenants, each sees only its own.

Fresh tenant ids per run: the app role cannot DELETE `threads`/`messages`, so reusing
fixed ids would let earlier runs leak into the exact counts asserted here. Same fixtures
as `test_home_summary_db.py` (Inicio), kept local so each file runs alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.home import read_results_counts
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)

_THREAD = text(
    """
    INSERT INTO threads (id, tenant_id, connection_id, channel, external_thread_id, status,
                         last_message_at, last_inbound_at)
    VALUES (:id, :tenant_id, :connection_id, :channel, :ext, 'open', :at, :at)
    """
)
_MESSAGE = text(
    """
    INSERT INTO messages (id, tenant_id, thread_id, connection_id, external_message_id,
                          direction, text, posted_at, shape_version)
    VALUES (:id, :tenant_id, :thread_id, :connection_id, :ext, 'inbound', 'hola', :at,
            'test')
    """
)


def _tenant_with_connection(name: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"results-{name}-{tenant_id.hex[:6]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@results.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(tenant_id) as session:
        connection = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
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
        return tenant_id, connection.id


def _thread_with_messages(
    tenant_id: UUID, connection_id: UUID, *, channel: str = "dm", messages: int = 1
) -> None:
    """One conversation with `messages` inbound messages from the last hour."""
    thread_id = uuid4()
    at = NOW - timedelta(hours=1)
    with tenant_session(tenant_id) as session:
        session.execute(
            _THREAD,
            {
                "id": thread_id,
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "channel": channel,
                "ext": uuid4().hex,
                "at": at,
            },
        )
        for _ in range(messages):
            session.execute(
                _MESSAGE,
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "connection_id": connection_id,
                    "ext": uuid4().hex,
                    "at": at,
                },
            )


def test_each_tenant_counts_only_its_own() -> None:
    tenant_a, conn_a = _tenant_with_connection("a")
    tenant_b, conn_b = _tenant_with_connection("b")
    _thread_with_messages(tenant_a, conn_a)
    # One person who wrote three times, and another who wrote once.
    _thread_with_messages(tenant_b, conn_b, messages=3)
    _thread_with_messages(tenant_b, conn_b)
    _thread_with_messages(tenant_b, conn_b, channel="whatsapp")

    a = read_results_counts(tenant_a, now=NOW)
    b = read_results_counts(tenant_b, now=NOW)

    assert (a.messages_week_dm, a.people_week_dm, a.messages_week_whatsapp) == (1, 1, 0)
    assert (b.messages_week_dm, b.people_week_dm) == (4, 2)
    assert (b.messages_week_whatsapp, b.people_week_whatsapp) == (1, 1)
    assert a.instagram_connected and b.instagram_connected
    assert a.published_week == b.published_week == 0
    assert not a.whatsapp_connected and not b.whatsapp_connected
