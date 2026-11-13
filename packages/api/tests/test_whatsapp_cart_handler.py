"""m-25018684: the inbound handler turns a WhatsApp catalog cart into the thread's order —
offline, against the in-memory repository, with the fixture built from Meta's own
`messages` › `order` reference example (`whatsapp_order_doc.json`).

Pins: the order is recorded and the thread handed to a person; ZERO outbox rows and the
menu never consulted; a duplicate delivery changes nothing; an orphan number writes
nothing; lines link only through the lookup of the receiving number's brand.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Collection, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp.handler import (
    CART_HANDOFF_REASON,
    CTX_HANDOFF,
    PublishedMenu,
    whatsapp_messages_handler,
)
from qualify_api.whatsapp.menus.engine import CTX_ORDER, CTX_ORDER_CONFIRMED
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.orders import (
    CART_ENGINE_VERSION,
    CTX_ORDER_RECORD,
    CartProduct,
    read_order,
    read_previous_orders,
)
from qualify_api.whatsapp.payment_status import CTX_PAYMENT_RECORD
from qualify_api.whatsapp.repository import MemoryWhatsAppInboxRepository, StoredThreadState
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "shared"
    / "tests"
    / "fixtures"
    / "whatsapp_order_doc.json"
)
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-000025018684")
CONN = UUID("b0000000-0000-4000-8000-000025018684")
PHONE_ROW = UUID("c0000000-0000-4000-8000-000025018684")
PRODUCT = UUID("d0000000-0000-4000-8000-000025018684")
WAMID = "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQzQUFERjg0NDEzNDdFODU3MUMxMAA="
WA_ID = "16505551234"
MESSAGE_AT = datetime.fromtimestamp(1750096325, UTC)

RESOLVED = PhoneResolution(
    outcome=PhoneResolutionOutcome.RESOLVED,
    tenant_id=TENANT,
    connection_id=CONN,
    phone_row_id=PHONE_ROW,
)


def _value(*, retailer_ids: tuple[str, str] | None = None) -> dict[str, Any]:
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value = copy.deepcopy(body["entry"][0]["changes"][0]["value"])
    if retailer_ids is not None:
        for item, rid in zip(value["messages"][0]["order"]["product_items"], retailer_ids):
            item["product_retailer_id"] = rid
    return value


def _event(value: dict[str, Any]) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="whatsapp_business_account",
        entry_id="102290129340398",
        field="messages",
        value=value,
        attempts=1,
    )


class World:
    def __init__(
        self,
        *,
        resolution: PhoneResolution = RESOLVED,
        products: Mapping[str, CartProduct] | None = None,
    ) -> None:
        self.repo = MemoryWhatsAppInboxRepository()
        self.menu_calls: list[UUID] = []
        self.lookups: list[tuple[UUID, tuple[UUID, ...]]] = []
        self._products = dict(products or {})

        def menu_loader(phone_row_id: UUID) -> PublishedMenu:
            self.menu_calls.append(phone_row_id)
            return PublishedMenu(BIANKI_DEMO_MENU, version_id=None)

        def cart_products(phone_row_id: UUID, ids: Collection[UUID]) -> Mapping[str, CartProduct]:
            self.lookups.append((phone_row_id, tuple(ids)))
            return {k: v for k, v in self._products.items() if UUID(k) in set(ids)}

        self.handle = whatsapp_messages_handler(
            resolve=lambda pn: resolution,
            repo=self.repo,
            menu_loader=menu_loader,
            cart_product_loader=cart_products,
            clock=lambda: NOW,
        )

    def thread_id(self) -> UUID:
        return self.repo.threads[(CONN, "whatsapp", WA_ID)]["id"]

    def state(self) -> StoredThreadState:
        state = self.repo.get_thread_state(self.thread_id())
        assert state is not None
        return state


async def test_the_meta_doc_cart_becomes_the_order_and_goes_to_a_person() -> None:
    world = World()

    outcome = await world.handle(_event(_value()))

    assert outcome.status == "processed"
    message = world.repo.messages[(CONN, WAMID)]
    assert message["media_type"] == "order" and message["text"] is None  # 0061 lists it
    state = world.state()
    order = read_order(state.context)
    assert order is not None and order.is_cart
    assert [(line.product_id, line.name, line.qty, line.linked) for line in order.lines] == [
        ("di9ozbzfi4", "", 2, False),
        ("nqryix03ez", "", 1, False),
    ]
    assert (order.total, order.currency, order.note) == (Decimal("85"), "USD", "Love these!")
    assert order.confirmed_at == MESSAGE_AT and order.source_message_id == WAMID
    assert state.context[CTX_ORDER_RECORD]["engine_version"] == CART_ENGINE_VERSION
    # Handed to a person exactly as a confirmed menu order: paused, `_handoff` written.
    assert state.paused_at == NOW and state.node_id is None and state.attempts == 0
    assert state.context[CTX_HANDOFF]["reason"] == CART_HANDOFF_REASON
    assert state.context[CTX_HANDOFF]["at"] == NOW.isoformat()
    # Assisted, never autonomous: nothing queued, the menu never consulted.
    assert world.repo.outbox == []
    assert world.menu_calls == []
    assert world.lookups == []  # no UUID retailer id: nothing to look up


async def test_galeria_ids_link_through_one_lookup_of_the_receiving_number() -> None:
    product = CartProduct(str(PRODUCT), "Shawarma mixto", Decimal("30"), "USD")
    world = World(products={str(PRODUCT): product})

    await world.handle(_event(_value(retailer_ids=(str(PRODUCT), str(uuid4())))))

    (lookup,) = world.lookups
    assert lookup[0] == PHONE_ROW and PRODUCT in lookup[1] and len(lookup[1]) == 2
    order = read_order(world.state().context)
    assert order is not None
    linked, foreign = order.lines
    assert (linked.product_id, linked.name, linked.linked, linked.price_mismatch) == (
        str(PRODUCT),
        "Shawarma mixto",
        True,
        False,
    )
    assert (foreign.name, foreign.linked) == ("", False)


async def test_a_duplicate_delivery_keeps_the_first_record_and_sends_nothing() -> None:
    world = World()
    await world.handle(_event(_value()))
    first = copy.deepcopy(world.state().context)

    outcome = await world.handle(_event(_value()))

    assert outcome.status == "processed"
    assert world.state().context == first
    assert world.repo.outbox == [] and world.menu_calls == []
    assert len(world.repo.messages) == 1


async def test_a_replay_after_a_person_resumed_the_chat_changes_nothing() -> None:
    world = World()
    value = _value()
    value["messages"][0]["order"]["product_items"] = [{"product_retailer_id": "x", "quantity": 0}]
    await world.handle(_event(value))  # no readable line: handed over, no order
    state = world.state()
    # A person resumes the automation.
    world.repo.states[world.thread_id()] = (TENANT, replace(state, paused_at=None))

    await world.handle(_event(value))  # Meta delivers the same cart again

    again = world.state()
    assert again.paused_at is None
    assert again.context == state.context
    assert world.repo.outbox == [] and world.menu_calls == []


async def test_an_orphan_number_writes_nothing() -> None:
    world = World(resolution=PhoneResolution(outcome=PhoneResolutionOutcome.ORPHAN))

    outcome = await world.handle(_event(_value()))

    assert outcome.status == "orphan"
    assert world.repo.threads == {} and world.repo.messages == {} and world.repo.states == {}


async def test_a_cart_mid_menu_closes_the_engines_working_order() -> None:
    world = World()
    world.repo.upsert_thread(tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID, inbound_at=NOW)
    world.repo.save_thread_state(
        thread_id=world.thread_id(),
        tenant_id=TENANT,
        state=StoredThreadState(
            node_id="productos",
            context={CTX_ORDER: [{"product_id": "p", "qty": 1}], CTX_ORDER_CONFIRMED: False},
            attempts=2,
        ),
    )

    await world.handle(_event(_value()))

    context = world.state().context
    assert CTX_ORDER not in context and CTX_ORDER_CONFIRMED not in context
    assert world.state().node_id is None and world.repo.outbox == []


async def test_a_cart_without_valid_lines_records_nothing_but_still_goes_to_a_person() -> None:
    world = World()
    value = _value()
    value["messages"][0]["order"]["product_items"] = [{"product_retailer_id": "x", "quantity": 0}]

    await world.handle(_event(value))

    state = world.state()
    assert read_order(state.context) is None
    assert (
        state.paused_at == NOW and state.context[CTX_HANDOFF]["summary"]["order_recorded"] is False
    )
    assert world.repo.outbox == []


async def test_a_cart_replacing_an_order_archives_it_and_its_payment() -> None:
    world = World()
    world.repo.upsert_thread(tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID, inbound_at=NOW)
    previous_order = {
        "items": [
            {"product_id": "p1", "name": "Combo", "qty": 1, "unit_price": "9", "currency": "USD"}
        ],
        "total": "9",
        "currency": "USD",
        "confirmed_at": NOW.isoformat(),
        "collected": {},
        "source_message_id": "wamid.menu",
        "engine_version": "wa-menu-engine-0.1.0",
    }
    payment = {
        "choice": "method",
        "name": "Pago móvil",
        "status": "awaiting",
        "order_message_id": "wamid.menu",
    }
    world.repo.save_thread_state(
        thread_id=world.thread_id(),
        tenant_id=TENANT,
        state=StoredThreadState(
            context={CTX_ORDER_RECORD: previous_order, CTX_PAYMENT_RECORD: payment}
        ),
    )

    await world.handle(_event(_value()))

    context = world.state().context
    assert CTX_PAYMENT_RECORD not in context  # the cart never shows the old payment
    (previous,) = read_previous_orders(context)
    assert previous.order.source_message_id == "wamid.menu"
    assert previous.payment is not None and previous.payment.status == "awaiting"

    # A proof the customer sends afterwards for the OLD order: a plain message, nothing
    # moves, nothing is answered.
    proof = _value()
    proof["messages"] = [
        {
            "from": WA_ID,
            "id": "wamid.proof",
            "timestamp": "1750096400",
            "type": "image",
            "image": {"id": "media-1", "mime_type": "image/jpeg"},
        }
    ]
    await world.handle(_event(proof))
    context = world.state().context
    assert CTX_PAYMENT_RECORD not in context
    assert read_previous_orders(context)[0].payment.status == "awaiting"  # type: ignore[union-attr]
    assert (CONN, "wamid.proof") in world.repo.messages
    assert world.repo.outbox == []


async def test_a_first_cart_drops_a_stray_payment_through_the_guarded_save() -> None:
    world = World()
    world.repo.upsert_thread(tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID, inbound_at=NOW)
    world.repo.save_thread_state(
        thread_id=world.thread_id(),
        tenant_id=TENANT,
        state=StoredThreadState(context={CTX_PAYMENT_RECORD: {"status": "awaiting"}}),
    )
    await world.handle(_event(_value()))
    context = world.state().context
    assert CTX_PAYMENT_RECORD not in context and read_order(context) is not None
    assert read_previous_orders(context) == ()


async def _bad_change(field: str, value: Any, *, in_item: bool) -> World:
    world = World()
    change = _value()
    cart = change["messages"][0]
    if in_item:
        cart["order"]["product_items"][0][field] = value
    else:
        cart["order"][field] = value
    text_message = {
        "from": WA_ID,
        "id": "wamid.text-same-change",
        "timestamp": "1750096330",
        "type": "text",
        "text": {"body": "hola"},
    }
    change["messages"].append(text_message)
    outcome = await world.handle(_event(change))
    assert outcome.status == "processed"
    return world


@pytest.mark.parametrize(
    ("field", "value", "in_item"),
    [
        ("product_retailer_id", 1.5, True),
        ("product_retailer_id", {"x": 1}, True),
        ("currency", 840, True),
        ("currency", ["USD"], True),
        ("catalog_id", 123, False),
        ("catalog_id", {"id": 1}, False),
        ("text", ["x"], False),
        ("text", 7, False),
    ],
)
async def test_a_wrongly_typed_field_never_drops_the_change(
    field: str, value: Any, in_item: bool
) -> None:
    world = await _bad_change(field, value, in_item=in_item)
    assert (CONN, WAMID) in world.repo.messages
    assert (CONN, "wamid.text-same-change") in world.repo.messages
    assert read_order(world.state().context) is not None  # the other line still counts
