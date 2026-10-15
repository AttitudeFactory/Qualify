"""WA-10 — `PostgresChatRepository` (and `ChatService` over it) against the real database.

What only Postgres can prove: the listing SQL (latest-inbound contact name, unread =
inbound after the last outbound, the outbound media preview through the
`whatsapp_outbox.wamid` join), chronological paging, the thread-state upsert/resume
under the `qualify_app` grants, and that RLS makes another tenant's thread and users
invisible.

Seeding follows `test_whatsapp_outbox_repository_db.py`: tenants/users/app via
`admin_session`, connection/threads/messages through `tenant_session`. Every run makes a
fresh connection and filters by it — the app role cannot DELETE, so earlier runs' rows
stay and must not leak into the assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.social.wa_shapes import SHAPE_VERSION
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.chats import ChatService, PostgresChatRepository, TextSend
from qualify_api.whatsapp.client import build_media_body
from qualify_api.whatsapp.models import WhatsAppOutboxItem, WhatsAppThreadState
from qualify_api.whatsapp.outbox import PostgresOutboxRepository

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000a9")
OTHER_TENANT = UUID("a0000000-0000-4000-8000-0000000000aa")
NOW = datetime.now(UTC).replace(microsecond=0)


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
        return connection.id


def _thread(tenant_id: UUID, connection_id: UUID, *, last_at: datetime | None) -> UUID:
    with tenant_session(tenant_id) as session:
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="whatsapp",
            external_thread_id=f"57{uuid4().int % 10**10:010d}",
            status="open",
            last_message_at=last_at,
            last_inbound_at=None,
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
    text_value: str | None,
    author: str | None = None,
    wamid: str | None = None,
) -> str:
    wamid = wamid or f"wamid.{uuid4().hex}"
    with tenant_session(tenant_id) as session:
        session.add(
            Message(
                tenant_id=tenant_id,
                thread_id=thread_id,
                connection_id=connection_id,
                external_message_id=wamid,
                direction=direction,
                author_external_id="573000000000" if direction == "inbound" else None,
                author_username=author,
                text=text_value,
                posted_at=at,
                shape_version=SHAPE_VERSION,
                delivery_status="sent" if direction == "outbound" else None,
            )
        )
        if direction == "inbound":
            session.execute(
                update(Thread)
                .where(Thread.id == thread_id)
                .values(last_inbound_at=at, last_message_at=at)
            )
    return wamid


def _sent_image(tenant_id: UUID, connection_id: UUID, thread_id: UUID, *, at: datetime) -> None:
    """What WA-08's `mark_sent` leaves behind for an image: the outbox row (with its
    body) and the outbound message row with `text = NULL`, sharing the `wamid`."""
    wamid = f"wamid.{uuid4().hex}"
    with tenant_session(tenant_id) as session:
        session.add(
            WhatsAppOutboxItem(
                tenant_id=tenant_id,
                connection_id=connection_id,
                thread_id=thread_id,
                kind="reply",
                payload=build_media_body(
                    "573000000000",
                    "image",
                    media_id=None,
                    link="https://x.example/a.png",
                    caption=None,
                    filename=None,
                ),
                status="sent",
                wamid=wamid,
                sent_at=at,
            )
        )
    _message(
        tenant_id,
        connection_id,
        thread_id,
        direction="outbound",
        at=at,
        text_value=None,
        wamid=wamid,
    )


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        _ensure_tenant(session, TENANT, "t-wa10")
        _ensure_tenant(session, OTHER_TENANT, "t-wa10-other")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa10.co", display_name="U")
        agent = User(tenant_id=TENANT, email=f"a-{uuid4()}@wa10.co", display_name="A")
        stranger = User(tenant_id=OTHER_TENANT, email=f"s-{uuid4()}@wa10.co", display_name="S")
        session.add_all([app, user, agent, stranger])
        session.flush()
        ids = {"app": app.id, "user": user.id, "agent": agent.id, "stranger": stranger.id}
    ids["connection"] = _connection(TENANT, ids["app"], ids["user"])
    ids["other_connection"] = _connection(OTHER_TENANT, ids["app"], ids["stranger"])
    return ids


def test_listing_computes_contact_preview_unread_and_window(seeded: dict[str, UUID]) -> None:
    conn = seeded["connection"]
    busy = _thread(TENANT, conn, last_at=None)
    _message(
        TENANT,
        conn,
        busy,
        direction="inbound",
        at=NOW - timedelta(hours=3),
        text_value="hola",
        author="Ana",
    )
    _sent_image(TENANT, conn, busy, at=NOW - timedelta(hours=2))
    _message(
        TENANT,
        conn,
        busy,
        direction="inbound",
        at=NOW - timedelta(hours=1),
        text_value=None,
        author="Ana María",
    )
    _message(
        TENANT, conn, busy, direction="inbound", at=NOW - timedelta(minutes=30), text_value=None
    )
    quiet = _thread(TENANT, conn, last_at=None)
    _message(
        TENANT, conn, quiet, direction="inbound", at=NOW - timedelta(hours=30), text_value="hey"
    )
    _sent_image(TENANT, conn, quiet, at=NOW - timedelta(hours=29))
    with tenant_session(TENANT) as session:
        session.execute(
            update(Thread)
            .where(Thread.id == quiet)
            .values(last_message_at=NOW - timedelta(hours=29))
        )

    service = ChatService(PostgresChatRepository(), PostgresOutboxRepository(), clock=lambda: NOW)
    summaries = service.list_threads(TENANT, connection_id=conn)

    assert [s.id for s in summaries] == [busy, quiet]
    first, second = summaries
    assert first.contact_name == "Ana María"
    assert first.last_message_preview == "[mensaje]"
    assert first.last_message_direction == "inbound"
    assert first.unread_count == 2
    assert first.window.open is True
    assert first.window.closes_at == NOW - timedelta(minutes=30) + timedelta(hours=24)
    assert second.last_message_preview == "[imagen]"
    assert second.last_message_direction == "outbound"
    assert second.unread_count == 0
    assert second.window.open is False

    assert [s.id for s in service.list_threads(TENANT, connection_id=conn, limit=1)] == [busy]
    older = service.list_threads(TENANT, connection_id=conn, before=first.last_message_at)
    assert [s.id for s in older] == [quiet]


def test_messages_page_chronologically_with_outbound_media_kind(seeded: dict[str, UUID]) -> None:
    conn = seeded["connection"]
    thread_id = _thread(TENANT, conn, last_at=None)
    for hours, label in ((4, "m4"), (3, "m3")):
        _message(
            TENANT,
            conn,
            thread_id,
            direction="inbound",
            at=NOW - timedelta(hours=hours),
            text_value=label,
        )
    _sent_image(TENANT, conn, thread_id, at=NOW - timedelta(hours=2))
    repo = PostgresChatRepository()

    page = repo.list_messages(tenant_id=TENANT, thread_id=thread_id, before=None, limit=2)
    assert [(m.direction, m.text, m.media_kind) for m in page] == [
        ("inbound", "m3", None),
        ("outbound", None, "image"),
    ]
    older = repo.list_messages(
        tenant_id=TENANT, thread_id=thread_id, before=page[0].posted_at, limit=2
    )
    assert [m.text for m in older] == ["m4"]


def test_send_queues_a_reply_and_pauses_then_resume_keeps_context(
    seeded: dict[str, UUID],
) -> None:
    conn = seeded["connection"]
    thread_id = _thread(TENANT, conn, last_at=None)
    _message(
        TENANT,
        conn,
        thread_id,
        direction="inbound",
        at=NOW - timedelta(minutes=5),
        text_value="hola",
    )
    service = ChatService(PostgresChatRepository(), PostgresOutboxRepository(), clock=lambda: NOW)

    outbox_id = service.send(TENANT, thread_id, seeded["user"], TextSend(text="ya voy"))

    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppOutboxItem, outbox_id)
        assert row is not None
        assert (row.kind, row.status, row.thread_id) == ("reply", "pending", thread_id)
        assert row.created_by_user_id == seeded["user"]
        state = session.get(WhatsAppThreadState, thread_id)
        assert state is not None
        assert state.automation_paused_at == NOW
        assert state.paused_by_user_id == seeded["user"]
        state.node_id = "products"
        state.attempts = 2
        state.context = {"order": [{"product_id": "p1", "qty": 1}]}

    service.resume(TENANT, thread_id)

    with tenant_session(TENANT) as session:
        state = session.get(WhatsAppThreadState, thread_id)
        assert state is not None
        assert state.automation_paused_at is None
        assert state.paused_by_user_id is None
        assert (state.node_id, state.attempts) == (None, 0)
        assert state.context == {"order": [{"product_id": "p1", "qty": 1}]}
    assert service.get_thread_summary(TENANT, thread_id).automation_paused is False


def test_assign_close_reopen(seeded: dict[str, UUID]) -> None:
    thread_id = _thread(TENANT, seeded["connection"], last_at=NOW)
    service = ChatService(PostgresChatRepository(), PostgresOutboxRepository(), clock=lambda: NOW)

    service.assign(TENANT, thread_id, seeded["agent"])
    service.close(TENANT, thread_id)
    summary = service.get_thread_summary(TENANT, thread_id)
    assert (summary.assigned_agent_id, summary.status) == (seeded["agent"], "closed")

    service.reopen(TENANT, thread_id)
    service.assign(TENANT, thread_id, None)
    summary = service.get_thread_summary(TENANT, thread_id)
    assert (summary.assigned_agent_id, summary.status) == (None, "open")


def test_rls_hides_other_tenants_threads_and_users(seeded: dict[str, UUID]) -> None:
    theirs = _thread(OTHER_TENANT, seeded["other_connection"], last_at=NOW)
    repo = PostgresChatRepository()

    assert repo.get_thread(tenant_id=TENANT, thread_id=theirs) is None
    assert (
        repo.list_threads(
            tenant_id=TENANT,
            connection_id=seeded["other_connection"],
            status=None,
            limit=50,
            before=None,
        )
        == []
    )
    assert repo.user_in_tenant(tenant_id=TENANT, user_id=seeded["stranger"]) is False
    assert repo.user_in_tenant(tenant_id=TENANT, user_id=seeded["agent"]) is True

    # A write aimed at the foreign thread touches nothing.
    repo.set_status(tenant_id=TENANT, thread_id=theirs, status="closed")
    with tenant_session(OTHER_TENANT) as session:
        assert session.scalar(select(Thread.status).where(Thread.id == theirs)) == "open"
