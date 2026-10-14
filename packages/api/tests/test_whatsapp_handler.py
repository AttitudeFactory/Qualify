"""`qualify_api.whatsapp.handler` (WA-07) against the in-memory repository — offline.

Drives the handler with the two shared fixtures: the LIVE `statuses` payload
(`whatsapp_status_read_live_2026-10-14.json`) and the SYNTHETIC inbound one (text +
list reply + image). Pins: exact threads/messages, a replay writes nothing twice and
never steps the menu twice, an unknown number is `orphan` and writes nothing, a
published menu turns into outbox rows with built `POST /messages` bodies, an
off-contract value is `dead`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.social.wa_shapes import SHAPE_VERSION

from qualify_api.webhooks.processor import Processor
from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp.handler import (
    CTX_ATTEMPTS,
    CTX_HANDOFF,
    WHATSAPP_MESSAGES_HANDLER_KEY,
    PublishedMenu,
    menu_state_from_stored,
    stored_context,
    whatsapp_messages_handler,
)
from qualify_api.whatsapp.menus.engine import CatalogItem, ThreadMenuState
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.repository import (
    MemoryWhatsAppInboxRepository,
    StoredThreadState,
)
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fixtures"
LIVE_STATUS = FIXTURES / "whatsapp_status_read_live_2026-10-14.json"
SYNTHETIC_INBOUND = FIXTURES / "whatsapp_inbound_synthetic.json"

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
TENANT = UUID("77777777-7777-4777-8777-777777777777")
CONNECTION = UUID("88888888-8888-4888-8888-888888888888")
PHONE_ROW = UUID("99999999-9999-4999-8999-999999999999")
MENU_VERSION = UUID("66666666-6666-4666-8666-666666666666")
PHONE_NUMBER_ID = "1393787420477981"
WA_ID = "584240000000"
LIVE_WAMID = "wamid.HBgMNTg0MjQ3MDAwMjkxFQIAERgSQzUwREJGQjc1M0Y1QzEwOTU3AA=="

RESOLVED = PhoneResolution(
    outcome=PhoneResolutionOutcome.RESOLVED,
    tenant_id=TENANT,
    connection_id=CONNECTION,
    phone_row_id=PHONE_ROW,
)
ORPHAN = PhoneResolution(outcome=PhoneResolutionOutcome.ORPHAN)


def _messages_value(path: Path) -> dict[str, Any]:
    body = json.loads(path.read_text(encoding="utf-8"))
    change = next(c for c in body["entry"][0]["changes"] if c["field"] == "messages")
    return change["value"]


def _event(value: Any, *, field: str = "messages") -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="whatsapp_business_account",
        entry_id="2338576026889338",
        field=field,
        value=value,
        attempts=1,
    )


class Resolver:
    def __init__(self, resolution: PhoneResolution = RESOLVED) -> None:
        self.calls: list[str] = []
        self._resolution = resolution

    def __call__(self, phone_number_id: str) -> PhoneResolution:
        self.calls.append(phone_number_id)
        return self._resolution


class MenuCounter:
    """A menu loader that counts how many times the handler asked for a menu."""

    def __init__(self, menu: PublishedMenu | None) -> None:
        self.calls: list[UUID] = []
        self._menu = menu

    def __call__(self, phone_row_id: UUID) -> PublishedMenu | None:
        self.calls.append(phone_row_id)
        return self._menu


def _handler(
    repo: MemoryWhatsAppInboxRepository,
    *,
    resolver: Resolver | None = None,
    menu_loader: MenuCounter | None = None,
    catalog: Sequence[CatalogItem] = (),
):
    kwargs: dict[str, Any] = {"resolve": resolver or Resolver(), "repo": repo, "clock": lambda: NOW}
    if menu_loader is not None:
        kwargs["menu_loader"] = menu_loader
    if catalog:
        kwargs["catalog_loader"] = lambda phone_row_id: catalog
    return whatsapp_messages_handler(**kwargs)


# --- statuses (the live fixture) ----------------------------------------------------------


async def test_the_live_read_receipt_lands_on_the_outbound_row() -> None:
    repo = MemoryWhatsAppInboxRepository()
    repo.seed_outbound_message(
        tenant_id=TENANT, thread_id=uuid4(), connection_id=CONNECTION, wamid=LIVE_WAMID
    )
    resolver = Resolver()
    handle = _handler(repo, resolver=resolver)

    outcome = await handle(_event(_messages_value(LIVE_STATUS)))

    assert outcome.status == "processed"
    assert resolver.calls == [PHONE_NUMBER_ID]
    row = repo.messages[(CONNECTION, LIVE_WAMID)]
    assert row["delivery_status"] == "read"
    assert row["delivery_error_code"] is None
    assert repo.threads == {} and repo.outbox == []  # a receipt opens no thread, sends nothing


async def test_a_receipt_for_an_unknown_wamid_is_ignored_not_failed() -> None:
    repo = MemoryWhatsAppInboxRepository()

    outcome = await _handler(repo)(_event(_messages_value(LIVE_STATUS)))

    assert outcome.status == "processed"
    assert repo.messages == {}


async def test_receipts_never_regress_and_failed_keeps_its_code() -> None:
    repo = MemoryWhatsAppInboxRepository()
    repo.seed_outbound_message(
        tenant_id=TENANT, thread_id=uuid4(), connection_id=CONNECTION, wamid="wamid.X"
    )
    handle = _handler(repo)
    base = _messages_value(LIVE_STATUS)

    def _status(status: str, **extra: Any) -> dict[str, Any]:
        return {
            **base,
            "statuses": [
                {
                    "id": "wamid.X",
                    "status": status,
                    "timestamp": "1",
                    "recipient_id": WA_ID,
                    **extra,
                }
            ],
        }

    await handle(_event(_status("read")))
    await handle(_event(_status("delivered")))  # arrived late: must not win
    assert repo.messages[(CONNECTION, "wamid.X")]["delivery_status"] == "read"

    await handle(_event(_status("failed", errors=[{"code": 131047, "title": "Re-engagement"}])))
    row = repo.messages[(CONNECTION, "wamid.X")]
    assert (row["delivery_status"], row["delivery_error_code"]) == ("failed", "131047")

    outcome = await handle(_event(_status("deleted")))  # not a delivery status: ignored
    assert outcome.status == "processed"
    assert repo.messages[(CONNECTION, "wamid.X")]["delivery_status"] == "failed"


# --- inbound messages (the synthetic fixture) --------------------------------------------


async def test_three_inbound_messages_become_one_thread_and_three_rows() -> None:
    repo = MemoryWhatsAppInboxRepository()
    menu_loader = MenuCounter(None)

    outcome = await _handler(repo, menu_loader=menu_loader)(
        _event(_messages_value(SYNTHETIC_INBOUND))
    )

    assert outcome.status == "processed"
    assert list(repo.threads) == [(CONNECTION, "whatsapp", WA_ID)]
    thread = repo.threads[(CONNECTION, "whatsapp", WA_ID)]
    assert thread["tenant_id"] == TENANT
    assert thread["status"] == "open"
    assert thread["last_inbound_at"] == datetime.fromtimestamp(1791953790, UTC)
    assert thread["last_message_at"] == thread["last_inbound_at"]

    rows = {m["external_message_id"]: m for m in repo.messages.values()}
    assert set(rows) == {
        "wamid.SYNTHETIC_TEXT_0001",
        "wamid.SYNTHETIC_LIST_0002",
        "wamid.SYNTHETIC_IMAGE_0003",
    }
    assert rows["wamid.SYNTHETIC_TEXT_0001"]["text"] == "Hola, quiero hacer un pedido"
    assert rows["wamid.SYNTHETIC_LIST_0002"]["text"] == "Hacer un pedido"  # the reply title
    assert rows["wamid.SYNTHETIC_IMAGE_0003"]["text"] is None
    for row in rows.values():
        assert row["tenant_id"] == TENANT
        assert row["thread_id"] == thread["id"]
        assert row["direction"] == "inbound"
        assert row["author_external_id"] == WA_ID
        assert row["author_username"] == "Cliente de prueba"
        assert row["shape_version"] == SHAPE_VERSION
        assert row["delivery_status"] is None
    assert rows["wamid.SYNTHETIC_TEXT_0001"]["posted_at"] == datetime.fromtimestamp(1791953700, UTC)
    # Without a published menu nothing is stepped, stored or sent.
    assert menu_loader.calls == [PHONE_ROW]
    assert repo.states == {} and repo.outbox == []


async def test_a_replayed_change_writes_nothing_twice_and_never_steps_the_menu_again() -> None:
    repo = MemoryWhatsAppInboxRepository()
    menu_loader = MenuCounter(PublishedMenu(BIANKI_DEMO_MENU, version_id=MENU_VERSION))
    handle = _handler(repo, menu_loader=menu_loader)
    event = _event(_messages_value(SYNTHETIC_INBOUND))

    await handle(event)
    threads_after_first = {k: dict(v) for k, v in repo.threads.items()}
    messages_after_first = len(repo.messages)
    outbox_after_first = len(repo.outbox)
    state_after_first = repo.states[next(iter(repo.threads.values()))["id"]]
    assert outbox_after_first > 0

    outcome = await handle(event)

    assert outcome.status == "processed"
    assert {k: dict(v) for k, v in repo.threads.items()} == threads_after_first
    assert len(repo.messages) == messages_after_first
    assert len(repo.outbox) == outbox_after_first
    assert repo.states[next(iter(repo.threads.values()))["id"]] == state_after_first


async def test_an_orphan_number_is_orphan_and_writes_nothing() -> None:
    repo = MemoryWhatsAppInboxRepository()
    menu_loader = MenuCounter(PublishedMenu(BIANKI_DEMO_MENU))

    outcome = await _handler(repo, resolver=Resolver(ORPHAN), menu_loader=menu_loader)(
        _event(_messages_value(SYNTHETIC_INBOUND))
    )

    assert outcome.status == "orphan"
    assert repo.threads == {} and repo.messages == {} and repo.states == {} and repo.outbox == []
    assert menu_loader.calls == []


async def test_an_off_contract_value_is_dead_without_resolving() -> None:
    repo = MemoryWhatsAppInboxRepository()
    resolver = Resolver()

    outcome = await _handler(repo, resolver=resolver)(_event({"messaging_product": "sms"}))

    assert (outcome.status, outcome.error) == ("dead", "contract_violation")
    assert resolver.calls == []
    assert repo.threads == {}


# --- the menu --------------------------------------------------------------------------


def _text_message(body: str, wamid: str, *, timestamp: str = "1791953700") -> dict[str, Any]:
    return {
        "from": WA_ID,
        "id": wamid,
        "timestamp": timestamp,
        "type": "text",
        "text": {"body": body},
    }


def _reply_message(reply_id: str, title: str, wamid: str, *, kind: str = "button_reply") -> dict:
    return {
        "from": WA_ID,
        "id": wamid,
        "timestamp": "1791953800",
        "type": "interactive",
        "interactive": {"type": kind, kind: {"id": reply_id, "title": title}},
    }


def _value(*messages: dict[str, Any]) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15556336018", "phone_number_id": PHONE_NUMBER_ID},
        "contacts": [{"profile": {"name": "Cliente de prueba"}, "wa_id": WA_ID}],
        "messages": list(messages),
    }


async def test_a_published_menu_answers_the_first_message_with_built_bodies() -> None:
    repo = MemoryWhatsAppInboxRepository()
    menu_loader = MenuCounter(PublishedMenu(BIANKI_DEMO_MENU, version_id=MENU_VERSION))
    handle = _handler(repo, menu_loader=menu_loader)

    await handle(_event(_value(_text_message("Hola", "wamid.1"))))

    thread_id = repo.threads[(CONNECTION, "whatsapp", WA_ID)]["id"]
    # Welcome text, then the start node's buttons — two outbox rows, in order.
    kinds = [(row["kind"], row["payload"]["type"]) for row in repo.outbox]
    assert kinds == [("automation", "text"), ("automation", "interactive")]
    welcome, buttons = repo.outbox
    for row in (welcome, buttons):
        assert row["tenant_id"] == TENANT
        assert row["connection_id"] == CONNECTION
        assert row["thread_id"] == thread_id
        assert row["status"] == "pending"
        assert row["payload"]["messaging_product"] == "whatsapp"
        assert row["payload"]["to"] == WA_ID
    assert welcome["payload"]["text"]["body"] == BIANKI_DEMO_MENU.entry.welcome
    assert buttons["payload"]["interactive"]["type"] == "button"
    assert [b["reply"]["id"] for b in buttons["payload"]["interactive"]["action"]["buttons"]] == [
        "ver_menu",
        "info",
        "persona",
    ]

    tenant_id, state = repo.states[thread_id]
    assert tenant_id == TENANT
    assert state.menu_version_id == MENU_VERSION
    assert state.node_id == "inicio"
    assert state.paused_at is None
    assert CTX_ATTEMPTS not in state.context
    assert menu_loader.calls == [PHONE_ROW]  # loaded once per change


async def test_a_button_reply_advances_the_stored_cursor() -> None:
    repo = MemoryWhatsAppInboxRepository()
    handle = _handler(repo, menu_loader=MenuCounter(PublishedMenu(BIANKI_DEMO_MENU, MENU_VERSION)))
    await handle(_event(_value(_text_message("Hola", "wamid.1"))))
    thread_id = repo.threads[(CONNECTION, "whatsapp", WA_ID)]["id"]

    await handle(_event(_value(_reply_message("info", "Horario y ubicación", "wamid.2"))))

    _, state = repo.states[thread_id]
    assert state.node_id == "info"
    assert repo.outbox[-1]["payload"]["interactive"]["type"] == "button"
    assert repo.outbox[-1]["payload"]["interactive"]["body"]["text"] == (
        BIANKI_DEMO_MENU.nodes["info"].body
    )


async def test_a_products_list_is_built_from_the_catalog() -> None:
    repo = MemoryWhatsAppInboxRepository()
    catalog = (
        CatalogItem("p1", "Hamburguesa clásica", category="Hamburguesas"),
        CatalogItem("p2", "Papas", category="Acompañantes"),
    )
    handle = _handler(
        repo,
        menu_loader=MenuCounter(PublishedMenu(BIANKI_DEMO_MENU, MENU_VERSION)),
        catalog=catalog,
    )

    await handle(_event(_value(_text_message("/menu", "wamid.1"))))

    sent = [row["payload"] for row in repo.outbox]
    lists = [p for p in sent if p["type"] == "interactive" and p["interactive"]["type"] == "list"]
    assert len(lists) == 1
    rows = [r["id"] for s in lists[0]["interactive"]["action"]["sections"] for r in s["rows"]]
    assert rows == ["prod:p1", "prod:p2"]


async def test_a_handoff_pauses_the_thread_and_keeps_the_summary_in_context() -> None:
    repo = MemoryWhatsAppInboxRepository()
    handle = _handler(repo, menu_loader=MenuCounter(PublishedMenu(BIANKI_DEMO_MENU, MENU_VERSION)))

    await handle(_event(_value(_text_message("persona", "wamid.1"))))
    thread_id = repo.threads[(CONNECTION, "whatsapp", WA_ID)]["id"]
    _, state = repo.states[thread_id]
    assert state.paused_at == NOW
    assert state.node_id is None
    assert state.context[CTX_HANDOFF]["reason"] == BIANKI_DEMO_MENU.nodes["persona"].reason
    assert state.context[CTX_HANDOFF]["summary"]["engine_version"]
    sends_before = len(repo.outbox)
    assert sends_before >= 1

    # A paused thread is inert: the next message is stored, nothing is sent or re-stepped.
    await handle(_event(_value(_text_message("hola?", "wamid.2"))))
    assert len(repo.outbox) == sends_before
    assert len(repo.messages) == 2
    assert repo.states[thread_id][1] == state


async def test_unknown_input_attempts_travel_inside_context_until_0058() -> None:
    repo = MemoryWhatsAppInboxRepository()
    handle = _handler(repo, menu_loader=MenuCounter(PublishedMenu(BIANKI_DEMO_MENU, MENU_VERSION)))
    await handle(_event(_value(_text_message("Hola", "wamid.1"))))
    thread_id = repo.threads[(CONNECTION, "whatsapp", WA_ID)]["id"]

    await handle(_event(_value(_text_message("asdfgh", "wamid.2"))))

    _, state = repo.states[thread_id]
    assert state.context[CTX_ATTEMPTS] == 1
    assert menu_state_from_stored(state).attempts == 1


async def test_a_menu_version_change_resets_the_cursor_but_keeps_the_context() -> None:
    repo = MemoryWhatsAppInboxRepository()
    thread_id = repo.upsert_thread(
        tenant_id=TENANT, connection_id=CONNECTION, wa_id=WA_ID, inbound_at=NOW
    ).thread_id
    repo.save_thread_state(
        thread_id=thread_id,
        tenant_id=TENANT,
        state=StoredThreadState(
            menu_version_id=uuid4(),  # an older version
            node_id="info",
            context={"order": [{"product_id": "p1", "name": "X", "qty": 1}]},
        ),
    )
    handle = _handler(repo, menu_loader=MenuCounter(PublishedMenu(BIANKI_DEMO_MENU, MENU_VERSION)))

    await handle(_event(_value(_text_message("qué?", "wamid.1"))))

    _, state = repo.states[thread_id]
    assert state.menu_version_id == MENU_VERSION
    assert state.node_id == "inicio"  # idle re-entry at the start node, not `info`
    assert state.context["order"] == [{"product_id": "p1", "name": "X", "qty": 1}]


# --- through the processor ------------------------------------------------------------


async def test_the_processor_routes_whatsapp_messages_to_this_handler_only() -> None:
    repo = MemoryWhatsAppInboxRepository()
    settled: dict[UUID, str] = {}

    class Queue:
        def __init__(self, events: list[ClaimedEvent]) -> None:
            self.events = events

        def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]:
            batch, self.events = self.events, []
            return batch

        def settle(self, *, event_id, worker_id, now, status, error=None) -> bool:
            settled[event_id] = status
            return True

        def fail(self, *, event_id, worker_id, now, attempts, error) -> str | None:
            raise AssertionError(f"unexpected failure {error}")

    wa = _event(_messages_value(SYNTHETIC_INBOUND))
    ig = ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="instagram",
        entry_id="1",
        field="messages",
        value={"anything": True},
        attempts=1,
    )
    processor = Processor(
        queue=Queue([wa, ig]),
        handlers={WHATSAPP_MESSAGES_HANDLER_KEY: _handler(repo)},
        worker_id="w1",
        clock=lambda: NOW,
    )

    report = await processor.run_once()

    assert settled == {wa.id: "processed", ig.id: "unsupported"}
    assert report.outcomes == {"processed": 1, "unsupported": 1}
    assert len(repo.messages) == 3


# --- the state bridge ---------------------------------------------------------------


def test_stored_context_round_trips_attempts() -> None:
    state = ThreadMenuState(node_id="n", context={"order": []}, attempts=2)
    stored = StoredThreadState(node_id="n", context=stored_context(state))
    assert stored.context == {"order": [], CTX_ATTEMPTS: 2}
    assert menu_state_from_stored(stored) == ThreadMenuState(
        node_id="n", context={"order": [], CTX_ATTEMPTS: 2}, attempts=2
    )
    assert CTX_ATTEMPTS not in stored_context(ThreadMenuState(context={CTX_ATTEMPTS: 3}))


@pytest.mark.parametrize("paused_at", [None, NOW])
def test_menu_state_reads_paused_from_the_timestamp(paused_at: datetime | None) -> None:
    state = menu_state_from_stored(StoredThreadState(paused_at=paused_at))
    assert state.paused is (paused_at is not None)
