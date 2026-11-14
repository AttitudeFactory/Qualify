"""The chat dispatcher against Postgres (m-25027372, BU-A6).

What only the database can prove: the channel is read from `threads` under RLS
(`tenant_session`), so with two businesses, B acting on A's chats gets `ThreadNotFound`
for every action and A's outboxes and threads are untouched; a send reaches the real
outbox of its channel (`whatsapp_outbox` / `conversation_outbox`) with the body each
channel builds today and the person who approved it; close/reopen move `threads.status`
through the channel's own door; assign on Instagram is refused without a write.

Seeding follows `test_inbox_unified_db.py`: tenant/app/user via `admin_session`, the rest
through `tenant_session`. Fresh tenants per test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.assisted.approval import HumanApproval
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.contracts import CHANNEL_DM, ChannelRegistry, RemoteMessage
from qualify_api.conversations.instagram_source import InstagramDirectSender
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import PostgresConversationOutboxRepository
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.conversations.service import ConversationService
from qualify_api.inbox.channels import UnknownChannel
from qualify_api.inbox.dispatch import (
    ActionNotSupported,
    ChatDispatcher,
    PostgresThreadChannels,
    ThreadNotFound,
)
from qualify_api.inbox.models import Thread
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.whatsapp.chats import ChatService, PostgresChatRepository
from qualify_api.whatsapp.client import build_text_body
from qualify_api.whatsapp.outbox import PostgresOutboxRepository

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)
INBOUND = NOW - timedelta(hours=1)
GRAPH = "https://graph.facebook.com/v21.0"


async def _no_client(*_: Any, **__: Any) -> Any:  # the sender never calls Meta here
    raise AssertionError("the dispatcher must not reach Meta")


INSTAGRAM_SENDER = InstagramDirectSender(client_factory=_no_client, graph_url=GRAPH)


@dataclass(frozen=True)
class _Biz:
    tenant_id: UUID
    user_id: UUID
    ig_thread: UUID
    wa_thread: UUID
    comment_thread: UUID
    igsid: str
    wa_id: str


def _connection(tenant_id: UUID, app_id: UUID, brand_id: UUID, user_id: UUID, platform: str):
    whatsapp = platform == "whatsapp"
    return SocialConnection(
        tenant_id=tenant_id,
        platform_app_id=app_id,
        brand_id=brand_id,
        platform=platform,
        account_type="waba_phone_number" if whatsapp else "business",
        external_account_id=f"{platform}-{uuid4().hex[:12]}",
        linked_page_id=None if whatsapp else "page-1",
        granted_scopes=(
            ["whatsapp_business_messaging"] if whatsapp else ["instagram_manage_messages"]
        ),
        status="active",
        access_posture="development",
        current_credential_version=0,
        connected_by_user_id=user_id,
    )


def _business() -> _Biz:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"t-despacho-{tenant_id.hex[:8]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@despacho.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    igsid, wa_id = f"igsid-{uuid4().hex[:10]}", f"57300{uuid4().int % 10**7:07d}"
    with tenant_session(tenant_id) as session:
        brand = Brand(tenant_id=tenant_id, name="Bianki")
        session.add(brand)
        session.flush()
        ig = _connection(tenant_id, app_id, brand.id, user_id, "instagram")
        wa = _connection(tenant_id, app_id, brand.id, user_id, "whatsapp")
        session.add_all([ig, wa])
        session.flush()
        wa_thread = Thread(
            tenant_id=tenant_id,
            connection_id=wa.id,
            channel="whatsapp",
            external_thread_id=wa_id,
            status="open",
            last_message_at=INBOUND,
            last_inbound_at=INBOUND,
        )
        comment_thread = Thread(
            tenant_id=tenant_id,
            connection_id=ig.id,
            channel="comment",
            external_thread_id=f"media-{uuid4().hex[:10]}",
            status="open",
        )
        session.add_all([wa_thread, comment_thread])
        session.flush()
        ig_id, wa_thread_id, comment_id = ig.id, wa_thread.id, comment_thread.id
    stored = PostgresConversationRepository().store_message(
        tenant_id=tenant_id,
        connection_id=ig_id,
        channel=CHANNEL_DM,
        counterpart_external_id=igsid,
        external_conversation_id=None,
        message=RemoteMessage(
            external_message_id=f"mid.{uuid4().hex}",
            direction="inbound",
            text="hola",
            posted_at=INBOUND,
            shape_version=SHAPE_VERSION_MEMORY,
            author_external_id=igsid,
        ),
        at=INBOUND,
    )
    assert stored.thread_id is not None
    return _Biz(tenant_id, user_id, stored.thread_id, wa_thread_id, comment_id, igsid, wa_id)


def _dispatcher() -> ChatDispatcher:
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=INSTAGRAM_SENDER)
    return ChatDispatcher(
        channels=PostgresThreadChannels(),
        instagram_service=ConversationService(
            repository=PostgresConversationRepository(),
            outbox=PostgresConversationOutboxRepository(),
            registry=registry,
        ),
        whatsapp_service=ChatService(PostgresChatRepository(), PostgresOutboxRepository()),
    )


def _approval(biz: _Biz) -> HumanApproval:
    return HumanApproval(user_id=biz.user_id, approved_at=NOW)


def _rows(biz: _Biz, sql: str) -> list[Any]:
    with tenant_session(biz.tenant_id) as session:
        return list(session.execute(text(sql)).mappings())


def _state(biz: _Biz) -> tuple[Any, ...]:
    """Everything an action could write for this business."""
    return (
        _rows(biz, "SELECT id, thread_id, payload FROM whatsapp_outbox ORDER BY id"),
        _rows(biz, "SELECT id, thread_id, payload FROM conversation_outbox ORDER BY id"),
        _rows(biz, "SELECT id, status, assigned_agent_id FROM threads ORDER BY id"),
        _rows(biz, "SELECT thread_id, automation_paused_at FROM whatsapp_thread_state"),
    )


def test_each_send_lands_in_its_own_channels_outbox_in_todays_shape() -> None:
    biz, dispatcher = _business(), _dispatcher()

    (wa_id,) = dispatcher.send_text(
        tenant_id=biz.tenant_id, thread_id=biz.wa_thread, text="Sí hay", approval=_approval(biz)
    )
    (wa_row,) = _rows(
        biz, "SELECT id, thread_id, kind, payload, created_by_user_id, status FROM whatsapp_outbox"
    )
    assert wa_row["id"] == wa_id and wa_row["thread_id"] == biz.wa_thread
    assert (wa_row["kind"], wa_row["status"]) == ("reply", "pending")
    assert wa_row["payload"] == build_text_body(biz.wa_id, "Sí hay", False)
    assert wa_row["created_by_user_id"] == biz.user_id
    assert _rows(biz, "SELECT id FROM conversation_outbox") == []

    (ig_id,) = dispatcher.send_text(
        tenant_id=biz.tenant_id, thread_id=biz.ig_thread, text="Sí hay", approval=_approval(biz)
    )
    (ig_row,) = _rows(
        biz,
        "SELECT id, thread_id, channel, payload, approved_by_user_id, approved_at "
        "FROM conversation_outbox",
    )
    assert ig_row["id"] == ig_id and ig_row["thread_id"] == biz.ig_thread
    assert ig_row["channel"] == "dm"
    assert ig_row["payload"] == INSTAGRAM_SENDER.build_payload(
        recipient_external_id=biz.igsid, text="Sí hay"
    )
    assert (ig_row["approved_by_user_id"], ig_row["approved_at"]) == (biz.user_id, NOW)
    assert len(_rows(biz, "SELECT id FROM whatsapp_outbox")) == 1


def test_another_business_cannot_act_on_a_chat_and_nothing_is_written() -> None:
    a, b, dispatcher = _business(), _business(), _dispatcher()
    before_a, before_b = _state(a), _state(b)
    for thread in (a.ig_thread, a.wa_thread, a.comment_thread):
        actions = [
            lambda t=thread: dispatcher.send_text(
                tenant_id=b.tenant_id, thread_id=t, text="hola", approval=_approval(b)
            ),
            lambda t=thread: dispatcher.close(
                tenant_id=b.tenant_id, thread_id=t, seen_last_inbound_at=INBOUND
            ),
            lambda t=thread: dispatcher.reopen(tenant_id=b.tenant_id, thread_id=t),
            lambda t=thread: dispatcher.assign(
                tenant_id=b.tenant_id, thread_id=t, agent_user_id=b.user_id
            ),
        ]
        for action in actions:
            with pytest.raises(ThreadNotFound):
                action()
    assert _state(a) == before_a and _state(b) == before_b


def test_close_and_reopen_move_the_status_through_each_channel() -> None:
    biz, dispatcher = _business(), _dispatcher()
    status = "SELECT id, status FROM threads WHERE channel <> 'comment'"

    dispatcher.close(tenant_id=biz.tenant_id, thread_id=biz.wa_thread, seen_last_inbound_at=None)
    dispatcher.close(tenant_id=biz.tenant_id, thread_id=biz.ig_thread, seen_last_inbound_at=INBOUND)
    assert {r["id"]: r["status"] for r in _rows(biz, status)} == {
        biz.wa_thread: "closed",
        biz.ig_thread: "closed",
    }

    dispatcher.reopen(tenant_id=biz.tenant_id, thread_id=biz.wa_thread)
    dispatcher.reopen(tenant_id=biz.tenant_id, thread_id=biz.ig_thread)
    assert {r["status"] for r in _rows(biz, status)} == {"open"}


def test_assign_is_whatsapp_only_and_instagram_writes_nothing() -> None:
    biz, dispatcher = _business(), _dispatcher()
    before = _state(biz)
    with pytest.raises(ActionNotSupported):
        dispatcher.assign(
            tenant_id=biz.tenant_id, thread_id=biz.ig_thread, agent_user_id=biz.user_id
        )
    assert _state(biz) == before

    dispatcher.assign(tenant_id=biz.tenant_id, thread_id=biz.wa_thread, agent_user_id=biz.user_id)
    (row,) = _rows(biz, "SELECT assigned_agent_id FROM threads WHERE channel = 'whatsapp'")
    assert row["assigned_agent_id"] == biz.user_id


def test_a_comment_thread_is_not_a_chat_and_nothing_is_written() -> None:
    biz, dispatcher = _business(), _dispatcher()
    before = _state(biz)
    with pytest.raises(UnknownChannel):
        dispatcher.send_text(
            tenant_id=biz.tenant_id,
            thread_id=biz.comment_thread,
            text="hola",
            approval=_approval(biz),
        )
    with pytest.raises(UnknownChannel):
        dispatcher.reopen(tenant_id=biz.tenant_id, thread_id=biz.comment_thread)
    assert _state(biz) == before
