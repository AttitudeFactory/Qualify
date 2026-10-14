"""Network- and Postgres-free tests for `whatsapp_chats_provider` (WA-11).

The real `ChatService` runs over the backend's own in-memory repositories
(`MemoryChatRepository` / `MemoryOutboxRepository`) and a fake `ChatsStore`, so these
pin the gateway's behaviour, not a re-implementation of it:

- number scoping: a thread of another number of the same tenant reads as missing;
- every send pauses the automation server-side and lands in the outbox, never inline;
- a closed window refuses before anything is written;
- «Pedido listo» builds its text from the stored order, never from the browser;
- structural guarantee: Postgres only through `tenant_session`.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.whatsapp.chats import (
    ChatService,
    MemoryChatRepository,
    ThreadNotFound,
    UnknownAgent,
    WindowClosed,
)
from qualify_api.whatsapp.orders import order_ready_text, read_order
from qualify_api.whatsapp.outbox import MemoryOutboxRepository

from . import whatsapp_chats_provider
from .whatsapp_chats_provider import ChatsGateway, NoOrder
from .whatsapp_chats_vm import MESSAGES_PAGE, AgentVM, UnsentItem

NOW = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
TENANT = UUID("00000000-0000-0000-0000-0000000000aa")
OTHER_TENANT = UUID("00000000-0000-0000-0000-0000000000ab")
NUMBER = UUID("00000000-0000-0000-0000-0000000000bb")
OTHER_NUMBER = UUID("00000000-0000-0000-0000-0000000000bc")
USER = UUID("00000000-0000-0000-0000-0000000000cc")

ORDER_CONTEXT = {
    "_order": {
        "items": [
            {"product_id": "p1", "name": "Hamburguesa", "qty": 2, "unit_price": "12500"},
        ],
        "total": "25000",
        "currency": "COP",
        "confirmed_at": "2026-10-14T16:30:00+00:00",
        "collected": {"direccion": "Calle 10 # 5-20"},
    }
}


class FakeStore:
    def __init__(self) -> None:
        self.contexts: dict[UUID, dict[str, Any]] = {}
        self.unsent_rows: dict[UUID, list[UnsentItem]] = {}
        self.users = {"laura@bianki.co": USER}

    def agents(self, tenant_id: UUID) -> list[AgentVM]:
        return [AgentVM(user_id=str(USER), name="Laura", initials="L")]

    def user_id_for_email(self, tenant_id: UUID, email: str) -> UUID | None:
        return self.users.get(email.strip().lower())

    def thread_context(self, tenant_id: UUID, thread_id: UUID) -> dict[str, Any]:
        return self.contexts.get(thread_id, {})

    def unsent(self, tenant_id: UUID, thread_id: UUID, now: datetime) -> list[UnsentItem]:
        return self.unsent_rows.get(thread_id, [])

    def timezone(self, tenant_id: UUID) -> str:
        return "America/Bogota"


class World:
    def __init__(self) -> None:
        self.repo = MemoryChatRepository()
        self.outbox = MemoryOutboxRepository(clock=lambda: NOW)
        self.store = FakeStore()
        self.service = ChatService(self.repo, self.outbox, clock=lambda: NOW)
        self.gateway = ChatsGateway(service=self.service, store=self.store, clock=lambda: NOW)
        self.repo.add_user(tenant_id=TENANT, user_id=USER)

    def thread(
        self, *, number: UUID = NUMBER, tenant: UUID = TENANT, inbound_ago: timedelta
    ) -> UUID:
        thread_id = self.repo.add_thread(tenant_id=tenant, connection_id=number, wa_id="5730012")
        self.repo.add_message(
            thread_id=thread_id,
            direction="inbound",
            text_value="Hola, quiero pedir",
            posted_at=NOW - inbound_ago,
            author_username="Laura Gómez",
        )
        return thread_id


@pytest.fixture
def world() -> World:
    return World()


def test_threads_are_scoped_to_the_number(world: World) -> None:
    mine = world.thread(inbound_ago=timedelta(minutes=5))
    world.thread(number=OTHER_NUMBER, inbound_ago=timedelta(minutes=5))
    world.thread(tenant=OTHER_TENANT, inbound_ago=timedelta(minutes=5))
    rows = world.gateway.threads(TENANT, NUMBER)
    assert [r.id for r in rows] == [mine]
    assert rows[0].contact_name == "Laura Gómez"
    assert rows[0].window.open


def test_threads_list_both_statuses(world: World) -> None:
    a = world.thread(inbound_ago=timedelta(minutes=5))
    world.service.close(TENANT, a)
    world.thread(inbound_ago=timedelta(minutes=1))
    assert {r.status for r in world.gateway.threads(TENANT, NUMBER)} == {"open", "closed"}


def test_conversation_of_another_number_reads_as_missing(world: World) -> None:
    foreign = world.thread(number=OTHER_NUMBER, inbound_ago=timedelta(minutes=5))
    with pytest.raises(ThreadNotFound):
        world.gateway.conversation(TENANT, NUMBER, foreign)
    with pytest.raises(ThreadNotFound):
        world.gateway.send_text(TENANT, NUMBER, foreign, USER, "hola")
    assert world.outbox.rows == {}


def test_conversation_carries_messages_unsent_and_order(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(minutes=5))
    world.store.contexts[thread_id] = ORDER_CONTEXT
    pending = UnsentItem(id="o1", status="pending", text="Ya va", created_at=NOW)
    world.store.unsent_rows[thread_id] = [pending]
    conv = world.gateway.conversation(TENANT, NUMBER, thread_id)
    assert [m.text for m in conv.messages] == ["Hola, quiero pedir"]
    assert conv.unsent == [pending]
    assert conv.order is not None and conv.order.total == 25000
    assert conv.has_more is False


def test_older_pages_with_before(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(hours=10))
    for i in range(MESSAGES_PAGE + 5):
        world.repo.add_message(
            thread_id=thread_id,
            direction="inbound",
            text_value=f"m{i}",
            posted_at=NOW - timedelta(hours=9) + timedelta(minutes=i),
        )
    conv = world.gateway.conversation(TENANT, NUMBER, thread_id)
    assert conv.has_more
    older = world.gateway.older(TENANT, NUMBER, thread_id, conv.messages[0].posted_at)
    assert [m.text for m in older.messages][-1] == "m4"
    assert older.has_more is False


def test_send_text_pauses_automation_and_queues(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(minutes=5))
    outbox_id = world.gateway.send_text(TENANT, NUMBER, thread_id, USER, "  Hola Laura  ")
    row = world.outbox.rows[outbox_id]
    assert (row.kind, row.payload["text"]["body"]) == ("reply", "Hola Laura")
    assert row.created_by_user_id == USER
    assert world.gateway.threads(TENANT, NUMBER)[0].automation_paused is True


def test_send_buttons_and_image_bodies(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(minutes=5))
    b = world.gateway.send_buttons(TENANT, NUMBER, thread_id, USER, "¿Confirmas?", ["Sí", "", "No"])
    buttons = world.outbox.rows[b].payload["interactive"]["action"]["buttons"]
    assert [x["reply"]["title"] for x in buttons] == ["Sí", "No"]
    assert [x["reply"]["id"] for x in buttons] == ["btn_1", "btn_2"]
    i = world.gateway.send_image(
        TENANT, NUMBER, thread_id, USER, "https://cdn.example.com/menu.jpg", "Menú"
    )
    image = world.outbox.rows[i].payload["image"]
    assert (image["link"], image["caption"]) == ("https://cdn.example.com/menu.jpg", "Menú")


def test_meta_limits_surface_as_value_error(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(minutes=5))
    with pytest.raises(ValueError):
        world.gateway.send_buttons(TENANT, NUMBER, thread_id, USER, "x", ["y" * 21])
    with pytest.raises(ValueError):
        world.gateway.send_image(TENANT, NUMBER, thread_id, USER, "not a url", "")
    assert world.outbox.rows == {}


def test_closed_window_refuses_before_writing(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(hours=25))
    with pytest.raises(WindowClosed):
        world.gateway.send_text(TENANT, NUMBER, thread_id, USER, "hola")
    assert world.outbox.rows == {}
    assert world.gateway.threads(TENANT, NUMBER)[0].automation_paused is False


def test_order_ready_uses_the_stored_order(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(minutes=5))
    with pytest.raises(NoOrder):
        world.gateway.send_order_ready(TENANT, NUMBER, thread_id, USER)
    world.store.contexts[thread_id] = ORDER_CONTEXT
    outbox_id = world.gateway.send_order_ready(TENANT, NUMBER, thread_id, USER)
    expected = order_ready_text(read_order(ORDER_CONTEXT))  # type: ignore[arg-type]
    assert world.outbox.rows[outbox_id].payload["text"]["body"] == expected


def test_actions_assign_close_reopen_takeover_resume(world: World) -> None:
    thread_id = world.thread(inbound_ago=timedelta(minutes=5))
    gw = world.gateway
    gw.assign(TENANT, NUMBER, thread_id, USER)
    assert gw.threads(TENANT, NUMBER)[0].assigned_agent_id == USER
    with pytest.raises(UnknownAgent):
        gw.assign(TENANT, NUMBER, thread_id, uuid4())
    gw.assign(TENANT, NUMBER, thread_id, None)
    assert gw.threads(TENANT, NUMBER)[0].assigned_agent_id is None
    gw.close(TENANT, NUMBER, thread_id)
    assert gw.threads(TENANT, NUMBER)[0].status == "closed"
    gw.reopen(TENANT, NUMBER, thread_id)
    assert gw.threads(TENANT, NUMBER)[0].status == "open"
    gw.takeover(TENANT, NUMBER, thread_id, USER)
    assert gw.threads(TENANT, NUMBER)[0].automation_paused is True
    gw.resume(TENANT, NUMBER, thread_id)
    assert gw.threads(TENANT, NUMBER)[0].automation_paused is False


def test_acting_user_and_agents_come_from_the_store(world: World) -> None:
    assert world.gateway.acting_user(TENANT, " Laura@Bianki.co ") == USER
    assert world.gateway.acting_user(TENANT, "nadie@x.co") is None
    assert [a.name for a in world.gateway.agents(TENANT)] == ["Laura"]
    assert world.gateway.timezone(TENANT) == "America/Bogota"


def test_postgres_only_through_tenant_session() -> None:
    source = inspect.getsource(whatsapp_chats_provider)
    assert "create_engine" not in source
    assert "admin_session" not in source
    assert "credential_session" not in source
    for name in ("agents", "user_id_for_email", "thread_context", "unsent", "timezone"):
        method = getattr(whatsapp_chats_provider.PostgresChatsStore, name)
        assert "tenant_session(tenant_id)" in inspect.getsource(method), name
