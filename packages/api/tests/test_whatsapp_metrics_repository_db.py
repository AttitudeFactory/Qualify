"""WA-17 — `PostgresMetricsRepository` (and the service over it) against the real database.

What only Postgres can prove: the first-inbound lateral, the outbound sender through the
`whatsapp_outbox (connection_id, wamid)` join, the `[since, until + horizon)` window,
the outbox-failure count, the published menu's entry config read through
`whatsapp_phone_numbers`, and that RLS hides another tenant's connection (404, not zeros).

Seeding follows `test_whatsapp_chat_repository_db.py`: tenants/users/app via
`admin_session`, everything else through `tenant_session`. Every run makes a fresh
connection and reads only it — the app role cannot DELETE, so earlier runs' rows stay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.social.wa_shapes import SHAPE_VERSION
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.menus.repository import PostgresMenuRepository
from qualify_api.whatsapp.metrics import (
    ConnectionNotFound,
    ConversationMetricsService,
    EntryCount,
    PostgresMetricsRepository,
)
from qualify_api.whatsapp.models import (
    WhatsAppMenuVersion,
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)
from qualify_api.whatsapp.orders import order_record_from_handoff

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000b7")
OTHER_TENANT = UUID("a0000000-0000-4000-8000-0000000000b8")
UNTIL = datetime.now(UTC).replace(microsecond=0)
SINCE = UNTIL - timedelta(days=7)


def _ensure_tenant(session: Session, tenant_id: UUID, name: str) -> None:
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


def _connection(tenant_id: UUID, app_id: UUID, user_id: UUID) -> UUID:
    with tenant_session(tenant_id) as session:
        connection = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"pn-{uuid4().hex[:12]}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        phone = WhatsAppPhoneNumber(
            tenant_id=tenant_id,
            connection_id=connection.id,
            waba_id="waba-wa17",
            phone_number_id=f"pn-{uuid4()}",
            display_phone_number="+57 300 000 0017",
        )
        session.add(phone)
        session.flush()
        connection_id, phone_id = connection.id, phone.id
    menus = PostgresMenuRepository()
    menu = menus.create_menu(tenant_id=tenant_id, phone_number_row_id=phone_id, name="Principal")
    version = menus.save_version(
        tenant_id=tenant_id,
        menu_id=menu.id,
        definition={
            "entry": {
                "keywords": {"Menú": "hi"},
                "commands": [{"name": "pedido", "hint": "Hacer un pedido", "node": "hi"}],
            },
            "nodes": {"hi": {"kind": "text", "body": "Hola"}},
            "start_node": "hi",
        },
    )
    menus.publish_version(
        tenant_id=tenant_id, menu_id=menu.id, version_id=version.id, user_id=user_id
    )
    return connection_id


def _thread(tenant_id: UUID, connection_id: UUID) -> UUID:
    with tenant_session(tenant_id) as session:
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="whatsapp",
            external_thread_id=f"57{uuid4().int % 10**10:010d}",
            status="open",
        )
        session.add(thread)
        session.flush()
        return thread.id


def _message(
    tenant_id: UUID,
    connection_id: UUID,
    thread_id: UUID,
    *,
    direction: str,
    at: datetime,
    text_value: str | None = None,
    outbox_kind: str | None = None,
    delivery_status: str | None = None,
) -> None:
    wamid = f"wamid.{uuid4().hex}"
    with tenant_session(tenant_id) as session:
        if outbox_kind is not None:
            session.add(
                WhatsAppOutboxItem(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    thread_id=thread_id,
                    kind=outbox_kind,
                    payload={"type": "text", "text": {"body": "x"}},
                    status="sent",
                    wamid=wamid,
                    sent_at=at,
                )
            )
        session.add(
            Message(
                tenant_id=tenant_id,
                thread_id=thread_id,
                connection_id=connection_id,
                external_message_id=wamid,
                direction=direction,
                text=text_value,
                posted_at=at,
                shape_version=SHAPE_VERSION,
                delivery_status=delivery_status,
            )
        )


def _state(tenant_id: UUID, thread_id: UUID, context: dict, *, automated: bool) -> None:
    with tenant_session(tenant_id) as session:
        version_id = None
        if automated:
            # Any version of this tenant (RLS-scoped): only "a menu ran here" matters.
            version_id = session.scalar(select(WhatsAppMenuVersion.id).limit(1))
        session.add(
            WhatsAppThreadState(
                thread_id=thread_id,
                tenant_id=tenant_id,
                menu_version_id=version_id,
                context=context,
            )
        )


def _failed_outbox(tenant_id: UUID, connection_id: UUID, status: str) -> None:
    with tenant_session(tenant_id) as session:
        session.add(
            WhatsAppOutboxItem(
                tenant_id=tenant_id,
                connection_id=connection_id,
                kind="reply",
                payload={"type": "text"},
                status=status,
                error_code="131047",
            )
        )


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        _ensure_tenant(session, TENANT, "t-wa17")
        _ensure_tenant(session, OTHER_TENANT, "t-wa17-other")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa17.co", display_name="U")
        stranger = User(tenant_id=OTHER_TENANT, email=f"s-{uuid4()}@wa17.co", display_name="S")
        session.add_all([app, user, stranger])
        session.flush()
        ids = {"app": app.id, "user": user.id, "stranger": stranger.id}
    ids["connection"] = _connection(TENANT, ids["app"], ids["user"])
    ids["other_connection"] = _connection(OTHER_TENANT, ids["app"], ids["stranger"])
    return ids


def test_metrics_over_postgres(seeded: dict[str, UUID]) -> None:
    conn = seeded["connection"]
    day = SINCE + timedelta(days=1)

    # Never automated, entered by command, answered by a person 10 minutes later.
    direct = _thread(TENANT, conn)
    _message(TENANT, conn, direct, direction="inbound", at=day, text_value="/pedido")
    _message(
        TENANT,
        conn,
        direct,
        direction="outbound",
        at=day + timedelta(minutes=10),
        outbox_kind="reply",
        delivery_status="read",
    )

    # Automated, entered by keyword, menu answered, handed off with a confirmed order.
    handed = _thread(TENANT, conn)
    t0 = day + timedelta(hours=2)
    _message(TENANT, conn, handed, direction="inbound", at=t0, text_value="MENU")
    _message(
        TENANT,
        conn,
        handed,
        direction="outbound",
        at=t0 + timedelta(seconds=1),
        outbox_kind="automation",
        delivery_status="failed",
    )
    _message(TENANT, conn, handed, direction="inbound", at=t0 + timedelta(minutes=1))
    handoff_at = t0 + timedelta(minutes=1, seconds=2)
    order = order_record_from_handoff(
        {
            "order_confirmed": True,
            "order": [{"product_id": "p1", "name": "Combo", "qty": 2, "price": "17500"}],
            "total": "35000",
            "currency": "COP",
        },
        confirmed_at=handoff_at,
        source_message_id="wamid.x",
    )
    _state(
        TENANT,
        handed,
        {
            "_handoff": {"reason": "order", "summary": {}, "at": handoff_at.isoformat()},
            "_order": order,
        },
        automated=True,
    )
    _message(
        TENANT,
        conn,
        handed,
        direction="outbound",
        at=t0 + timedelta(minutes=4),
        outbox_kind="reply",
    )

    # Opened before the range: active, not opened.
    old = _thread(TENANT, conn)
    _message(TENANT, conn, old, direction="inbound", at=SINCE - timedelta(days=2), text_value="hi")
    _message(TENANT, conn, old, direction="inbound", at=day)

    service = ConversationMetricsService(PostgresMetricsRepository(), clock=lambda: UNTIL)
    result = service.compute(TENANT, conn, since=SINCE, until=UNTIL)

    assert result.threads_opened == 2
    assert set(result.threads_opened_by_entry) == {
        EntryCount("command", "pedido", 1),
        EntryCount("keyword", "menu", 1),
    }
    assert result.orders_confirmed == 1
    assert str(result.orders_total["COP"]) == "35000"
    assert result.handoffs_by_reason == {"order": 1}
    # 600 s (direct) and 180 s (from the triggering inbound at t0 + 1 min).
    assert result.first_human_responses == 2
    assert result.median_first_human_response_seconds == 390.0
    assert result.messages_in == 4
    assert result.messages_out_automation == 1
    assert result.messages_out_human == 2
    assert result.delivery_failed == 1


def test_another_tenants_connection_is_not_found(seeded: dict[str, UUID]) -> None:
    service = ConversationMetricsService(PostgresMetricsRepository(), clock=lambda: UNTIL)
    with pytest.raises(ConnectionNotFound):
        service.compute(TENANT, seeded["other_connection"], since=SINCE, until=UNTIL)
    with pytest.raises(ConnectionNotFound):
        service.compute(TENANT, uuid4(), since=SINCE, until=UNTIL)


def test_send_failures_counted_by_creation_instant(seeded: dict[str, UUID]) -> None:
    conn = seeded["connection"]
    _failed_outbox(TENANT, conn, "failed")
    _failed_outbox(TENANT, conn, "dead")
    _failed_outbox(TENANT, conn, "pending")  # not a failure
    now = datetime.now(UTC)
    service = ConversationMetricsService(PostgresMetricsRepository(), clock=lambda: now)
    result = service.compute(
        TENANT, conn, since=now - timedelta(hours=1), until=now + timedelta(hours=1)
    )
    assert result.send_failed == 2
