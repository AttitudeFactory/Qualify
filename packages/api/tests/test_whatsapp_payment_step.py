"""m-24955648 part 2 — the payment step, offline: the engine, the handler and the sender,
the payment status of a chat, the owner's «Pago recibido», and the chat picker's card.

No DB, no network. Copy is the UX spec's (`docs/ux-paso-de-pago.md` §3–§5).
"""

from __future__ import annotations

import copy
import dataclasses
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image

from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp.attachments import (
    AttachmentRefused,
    ChatAttachmentService,
    MemoryAttachmentReads,
    MemoryBlobStore,
)
from qualify_api.whatsapp.chats import ChatService, MemoryChatRepository, WindowClosed
from qualify_api.whatsapp.client import WhatsAppApiError
from qualify_api.whatsapp.handler import PublishedMenu, whatsapp_messages_handler
from qualify_api.whatsapp.menus.engine import (
    CTX_ORDER,
    CTX_ORDER_CONFIRMED,
    CTX_PAYMENT,
    PAYMENT_NODE_ID,
    Handoff,
    Inbound,
    PaymentOption,
    SendButtons,
    SendList,
    SendPaymentCard,
    SendText,
    ThreadMenuState,
    payment_card_caption,
    step,
)
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.schema import MenuDefinition
from qualify_api.whatsapp.optins import MemoryOptInRepository, OptInService
from qualify_api.whatsapp.outbox import MemoryOutboxRepository, OutboxSender
from qualify_api.whatsapp.payment_status import (
    CONFIRM_TEXT,
    CTX_PAYMENT_RECORD,
    MemoryPaymentStatusStore,
    NoPendingPayment,
    PaymentStatusService,
    read_payment,
)
from qualify_api.whatsapp.payments import PaymentMethod
from qualify_api.whatsapp.repository import MemoryWhatsAppInboxRepository
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

NOW = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-000000955650")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-000000955650")
BRAND = UUID("c0000000-0000-4000-8000-000000955650")
CONN = UUID("d0000000-0000-4000-8000-000000955650")
PHONE_ROW = UUID("d1000000-0000-4000-8000-000000955650")
USER = UUID("e0000000-0000-4000-8000-000000955650")
WA_ID = "584240000000"

ORDER = [{"product_id": "p1", "name": "Shawarma mixto", "qty": 2, "price": "9", "currency": "USD"}]
QR_KEY = f"t/{TENANT}/whatsapp/payments/{BRAND}/{'a' * 32}.png"

PAGO_MOVIL = PaymentOption(
    id="m1",
    name="Pago móvil",
    currency="VES",
    instructions="Banco de Venezuela (0102) · V-12345678 · 0414-1234567",
    qr_media_key=QR_KEY,
    brand_id=str(BRAND),
)
BINANCE = PaymentOption(id="m2", name="Binance", currency="USD", instructions="Pay ID: 123")
EFECTIVO = PaymentOption(id="m3", name="Efectivo", pay_on_delivery=True)
ZELLE = PaymentOption(id="m4", name="Zelle", currency="USD", instructions="zelle@bianki.co")
BREB = PaymentOption(id="m5", name="Bre-B", currency="COP", instructions="Llave: bianki")


def _at_address(definition: MenuDefinition = BIANKI_DEMO_MENU) -> ThreadMenuState:
    return ThreadMenuState(
        node_id="direccion",
        context={CTX_ORDER: [dict(line) for line in ORDER], CTX_ORDER_CONFIRMED: True},
    )


def _pickup_menu() -> MenuDefinition:
    data = BIANKI_DEMO_MENU.model_dump(mode="json")
    data["nodes"]["resumen"]["confirm_next"] = "pedido_confirmado"
    return MenuDefinition.model_validate(data)


def _ask(options: tuple[PaymentOption, ...]):
    return step(
        BIANKI_DEMO_MENU, _at_address(), Inbound.text("Calle 5 #12"), payment_methods=options
    )


# --- engine: when the step appears -------------------------------------------------------


GOLDEN = Path(__file__).parent / "fixtures" / "whatsapp_payment_step_golden_no_methods.json"


def _as_json(result) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            {
                "actions": [
                    {"type": type(a).__name__, **dataclasses.asdict(a)} for a in result.actions
                ],
                "state": dataclasses.asdict(result.state),
                "handed_off": result.handed_off,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    )


@pytest.mark.parametrize(
    ("case", "state", "inbound"),
    [
        ("address_then_handoff", _at_address(), Inbound.text("Calle 5 #12")),
        (
            "confirm_then_address",
            ThreadMenuState(node_id="resumen", context={CTX_ORDER: [dict(ORDER[0])]}),
            Inbound.button_reply("confirm"),
        ),
    ],
)
def test_without_methods_the_flow_is_mains_byte_for_byte(case, state, inbound) -> None:
    """The fixture is what `origin/main`'s engine (174dd8d1, before the payment step)
    returned for these inputs: produced once by running a short script that imports
    `qualify_api.whatsapp.menus.engine` from `git archive origin/main packages/api/src
    packages/shared/src packages/creative/src` (`python -I`, PYTHONPATH on that tree
    only) and dumps `step(BIANKI_DEMO_MENU, state, inbound)` as below."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))[case]
    assert _as_json(step(BIANKI_DEMO_MENU, state, inbound)) == golden
    assert _as_json(step(BIANKI_DEMO_MENU, state, inbound, payment_methods=())) == golden


def test_after_the_address_the_customer_is_asked_how_to_pay() -> None:
    result = _ask((PAGO_MOVIL, BINANCE))
    assert not result.handed_off
    assert result.state.node_id == PAYMENT_NODE_ID and not result.state.paused
    question = result.actions[0]
    assert isinstance(question, SendButtons)
    assert question.body == "¿Cómo quieres pagar? Total: USD 18"
    assert [(b.id, b.title) for b in question.buttons] == [
        ("pay:m1", "Pago móvil"),
        ("pay:m2", "Binance"),
        ("pay:other", "Otra forma"),
    ]
    assert result.state.context["collected"] == {"direccion": "Calle 5 #12"}


def test_three_methods_are_buttons_without_another_way() -> None:
    question = _ask((PAGO_MOVIL, BINANCE, EFECTIVO)).actions[0]
    assert isinstance(question, SendButtons)
    assert [b.title for b in question.buttons] == ["Pago móvil", "Binance", "Efectivo"]


def test_five_methods_are_a_list_with_currencies_and_another_way() -> None:
    question = _ask((PAGO_MOVIL, BINANCE, EFECTIVO, ZELLE, BREB)).actions[0]
    assert isinstance(question, SendList) and question.button_label == "Elegir"
    rows = [(r.id, r.title, r.description) for r in question.rows]
    assert rows == [
        ("pay:m1", "Pago móvil", "En bolívares"),
        ("pay:m2", "Binance", "En dólares"),
        ("pay:m3", "Efectivo", "Al recibir"),
        ("pay:m4", "Zelle", "En dólares"),
        ("pay:m5", "Bre-B", "En pesos"),
        ("pay:other", "Otra forma de pago", "Te escribe una persona del equipo"),
    ]


def test_a_pickup_order_is_asked_too() -> None:
    state = ThreadMenuState(node_id="resumen", context={CTX_ORDER: [dict(ORDER[0])]})
    result = step(
        _pickup_menu(), state, Inbound.button_reply("confirm"), payment_methods=(PAGO_MOVIL,)
    )
    assert result.state.node_id == PAYMENT_NODE_ID
    question = result.actions[0]
    assert isinstance(question, SendButtons)
    assert [b.title for b in question.buttons] == ["Pago móvil", "Otra forma"]


def test_an_unconfirmed_handoff_is_never_held() -> None:
    state = ThreadMenuState(node_id="inicio")
    result = step(
        BIANKI_DEMO_MENU, state, Inbound.button_reply("persona"), payment_methods=(PAGO_MOVIL,)
    )
    assert result.handed_off


# --- engine: the answer ------------------------------------------------------------------


def _waiting(options: tuple[PaymentOption, ...]) -> ThreadMenuState:
    return _ask(options).state


def test_picking_a_method_sends_one_card_then_hands_over() -> None:
    options = (PAGO_MOVIL, BINANCE)
    result = step(
        BIANKI_DEMO_MENU, _waiting(options), Inbound.button_reply("pay:m1"), payment_methods=options
    )
    assert result.handed_off and result.state.paused
    # UX review: the card is the last message; the handoff text is not sent after it.
    assert not any(isinstance(a, SendText) for a in result.actions)
    card, handoff = result.actions[0], result.actions[1]
    assert isinstance(card, SendPaymentCard) and card.qr_media_key == QR_KEY
    assert card.caption == (
        "Banco de Venezuela (0102) · V-12345678 · 0414-1234567\n\n"
        "Total: USD 18\n"
        "Te confirmamos el monto en bolívares.\n\n"
        "Cuando pagues, envíanos el comprobante o el número de referencia por aquí. Una persona "
        "del equipo lo revisa y te confirma."
    )
    assert isinstance(handoff, Handoff) and handoff.summary["order_confirmed"] is True
    assert handoff.summary["payment"] == {
        "choice": "method",
        "method_id": "m1",
        "name": "Pago móvil",
        "currency": "VES",
        "pay_on_delivery": False,
    }
    assert sum(isinstance(a, SendPaymentCard) for a in result.actions) == 1


def test_the_same_currency_needs_no_confirmation_line() -> None:
    caption = payment_card_caption(BINANCE, total=Decimal("18"), order_currency="USD")
    assert "Te confirmamos el monto" not in caption and "Total: USD 18" in caption


def test_pay_on_delivery_asks_for_no_receipt() -> None:
    caption = payment_card_caption(EFECTIVO, total=Decimal("18"), order_currency="USD")
    assert caption == (
        "Total: USD 18\n\n"
        "Pagas al recibir tu pedido. Una persona del equipo te confirma en un momento."
    )


def test_a_method_without_qr_is_a_text_card() -> None:
    options = (BINANCE,)
    result = step(
        BIANKI_DEMO_MENU, _waiting(options), Inbound.text("Binance"), payment_methods=options
    )
    card = result.actions[0]
    assert isinstance(card, SendPaymentCard) and card.qr_media_key is None
    assert card.caption.startswith("Pay ID: 123\n\nTotal: USD 18")


def test_a_long_caption_never_passes_1024() -> None:
    long = PaymentOption(id="x", name="X", currency="VES", instructions="y" * 900)
    assert (
        len(payment_card_caption(long, total=Decimal("1234567.89"), order_currency="USD")) <= 1024
    )


def test_free_text_asks_once_more_then_hands_over_as_not_chosen() -> None:
    options = (PAGO_MOVIL, BINANCE)
    once = step(
        BIANKI_DEMO_MENU,
        _waiting(options),
        Inbound.text("¿aceptan dólares?"),
        payment_methods=options,
    )
    assert not once.handed_off and once.state.node_id == PAYMENT_NODE_ID
    assert isinstance(once.actions[0], SendButtons)
    assert once.actions[0].body.startswith("Elige una de las opciones para seguir.")
    twice = step(BIANKI_DEMO_MENU, once.state, Inbound.text("hola?"), payment_methods=options)
    assert twice.handed_off
    handoff = next(a for a in twice.actions if isinstance(a, Handoff))
    assert handoff.summary["payment"] == {"choice": "none"}
    assert not any(isinstance(a, SendPaymentCard) for a in twice.actions)


def test_a_stale_choice_asks_again() -> None:
    options = (PAGO_MOVIL, BINANCE)
    stale = step(
        BIANKI_DEMO_MENU,
        _waiting(options),
        Inbound.button_reply("pay:gone"),
        payment_methods=options,
    )
    assert stale.state.node_id == PAYMENT_NODE_ID and not stale.handed_off


def test_another_way_hands_over_at_once() -> None:
    options = (PAGO_MOVIL,)
    result = step(
        BIANKI_DEMO_MENU,
        _waiting(options),
        Inbound.button_reply("pay:other"),
        payment_methods=options,
    )
    handoff = next(a for a in result.actions if isinstance(a, Handoff))
    assert handoff.summary["payment"] == {"choice": "other"}


def test_methods_turned_off_while_choosing_hand_over() -> None:
    waiting = _waiting((PAGO_MOVIL,))
    result = step(BIANKI_DEMO_MENU, waiting, Inbound.button_reply("pay:m1"), payment_methods=())
    assert result.handed_off
    assert next(a for a in result.actions if isinstance(a, Handoff)).summary["payment"] == {
        "choice": "none"
    }


# --- handler: one row with the attachment; the record; review ----------------------------


def _event(*messages: dict[str, Any]) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="whatsapp_business_account",
        entry_id="waba",
        field="messages",
        value={
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "1555", "phone_number_id": "pn"},
            "contacts": [{"profile": {"name": "María"}, "wa_id": WA_ID}],
            "messages": list(messages),
        },
        attempts=1,
    )


def _text(body: str, wamid: str) -> dict[str, Any]:
    return {
        "from": WA_ID,
        "id": wamid,
        "timestamp": "1791953700",
        "type": "text",
        "text": {"body": body},
    }


def _reply(reply_id: str, wamid: str) -> dict[str, Any]:
    return {
        "from": WA_ID,
        "id": wamid,
        "timestamp": "1791953700",
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": reply_id, "title": "x"}},
    }


def _image(wamid: str) -> dict[str, Any]:
    return {
        "from": WA_ID,
        "id": wamid,
        "timestamp": "1791953700",
        "type": "image",
        "image": {"id": "media-9", "mime_type": "image/jpeg"},
    }


class Handler:
    def __init__(self, options: tuple[PaymentOption, ...]) -> None:
        self.repo = MemoryWhatsAppInboxRepository()
        self.loads = 0

        def payments(phone_row_id: UUID) -> tuple[PaymentOption, ...]:
            self.loads += 1
            return options

        self.handle = whatsapp_messages_handler(
            resolve=lambda pn: PhoneResolution(
                outcome=PhoneResolutionOutcome.RESOLVED,
                tenant_id=TENANT,
                connection_id=CONN,
                phone_row_id=PHONE_ROW,
            ),
            repo=self.repo,
            menu_loader=lambda row: PublishedMenu(BIANKI_DEMO_MENU, version_id=None),
            payment_loader=payments,
            clock=lambda: NOW,
        )

    def thread_id(self) -> UUID:
        return self.repo.threads[(CONN, "whatsapp", WA_ID)]["id"]

    def at_address(self) -> None:
        """Seed the thread at the address step with a confirmed order."""
        self.repo.upsert_thread(tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID, inbound_at=NOW)
        from qualify_api.whatsapp.repository import StoredThreadState

        state = _at_address()
        self.repo.save_thread_state(
            thread_id=self.thread_id(),
            tenant_id=TENANT,
            state=StoredThreadState(node_id=state.node_id, context=dict(state.context)),
        )

    def context(self) -> dict[str, Any]:
        return self.repo.get_thread_state(self.thread_id()).context


async def test_the_handler_queues_one_card_with_its_attachment_and_records_the_choice() -> None:
    h = Handler((PAGO_MOVIL, BINANCE))
    h.at_address()
    await h.handle(_event(_text("Calle 5 #12", "wamid.addr")))
    assert h.repo.outbox[-1]["payload"]["type"] == "interactive"
    assert h.repo.get_thread_state(h.thread_id()).node_id == PAYMENT_NODE_ID

    await h.handle(_event(_reply("pay:m1", "wamid.pick")))
    cards = [row for row in h.repo.outbox if row["attachment"] is not None]
    assert len(cards) == 1
    card = cards[0]
    assert card["kind"] == "automation" and card["payload"]["type"] == "image"
    assert "id" not in card["payload"]["image"] and "link" not in card["payload"]["image"]
    assert card["payload"]["image"]["caption"].startswith("Banco de Venezuela")
    assert card["attachment"] == {
        "kind": "payment_method",
        "method_id": "m1",
        "brand_id": str(BRAND),
        "object_key": QR_KEY,
        "content_type": "image/png",
        "filename": "qr.png",
        "media_id": None,
        "pipeline": "wa-payment-card-1",
    }
    payment = read_payment(h.context())
    assert payment is not None
    assert (payment.status, payment.label, payment.method_name) == (
        "awaiting",
        "Esperando el pago",
        "Pago móvil",
    )
    assert payment.order_total == Decimal("18.00") and payment.order_currency == "USD"
    assert h.context()[CTX_PAYMENT_RECORD]["order_message_id"] == "wamid.pick"
    assert CTX_PAYMENT not in h.context()
    # A replay of the same delivery queues nothing twice.
    rows = len(h.repo.outbox)
    await h.handle(_event(_reply("pay:m1", "wamid.pick")))
    assert len(h.repo.outbox) == rows


async def test_a_text_method_card_is_a_text_row_without_attachment() -> None:
    h = Handler((BINANCE,))
    h.at_address()
    await h.handle(_event(_text("Calle 5 #12", "wamid.addr")))
    await h.handle(_event(_reply("pay:m2", "wamid.pick")))
    texts = [
        row["payload"]["text"]["body"] for row in h.repo.outbox if row["payload"]["type"] == "text"
    ]
    assert any(body.startswith("Pay ID: 123") for body in texts)
    assert all(row["attachment"] is None for row in h.repo.outbox)


async def test_the_next_customer_message_marks_the_payment_for_review_and_gets_no_answer() -> None:
    h = Handler((PAGO_MOVIL,))
    h.at_address()
    await h.handle(_event(_text("Calle 5 #12", "wamid.addr")))
    await h.handle(_event(_reply("pay:m1", "wamid.pick")))
    rows = len(h.repo.outbox)

    await h.handle(_event(_image("wamid.receipt")))

    payment = read_payment(h.context())
    assert (payment.status, payment.label) == ("review", "Pago por revisar")
    assert h.context()[CTX_PAYMENT_RECORD]["review_message_id"] == "wamid.receipt"
    assert len(h.repo.outbox) == rows  # the automation does not answer it
    # A second message keeps the first review stamp.
    await h.handle(_event(_text("Ref 00987654", "wamid.ref")))
    assert h.context()[CTX_PAYMENT_RECORD]["review_message_id"] == "wamid.receipt"


async def test_pay_on_delivery_is_not_waiting_for_a_receipt() -> None:
    h = Handler((EFECTIVO,))
    h.at_address()
    await h.handle(_event(_text("Calle 5 #12", "wamid.addr")))
    await h.handle(_event(_reply("pay:m3", "wamid.pick")))
    await h.handle(_event(_text("ok gracias", "wamid.after")))
    payment = read_payment(h.context())
    assert (payment.status, payment.label) == ("on_delivery", "Paga al recibir")


async def test_steps_far_from_the_payment_never_read_the_methods() -> None:
    h = Handler((PAGO_MOVIL,))
    await h.handle(_event(_text("Hola", "wamid.1")))
    assert h.loads == 0


# --- sender: the card's QR is uploaded once, whatever the retries -------------------------


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (32, 32)).save(out, format="PNG")
    return out.getvalue()


class UploadingClient:
    def __init__(self, *outcomes: str | Exception) -> None:
        self._outcomes = list(outcomes)
        self.uploads = 0
        self.payloads: list[dict[str, Any]] = []

    async def upload_media(self, content: bytes, content_type: str, filename: str) -> str:
        self.uploads += 1
        return f"media-{self.uploads}"

    async def send_payload(self, payload: dict[str, Any]) -> str:
        self.payloads.append(payload)
        outcome = self._outcomes.pop(0) if self._outcomes else f"wamid.{uuid4().hex}"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_an_automation_card_uploads_its_qr_once_across_retries() -> None:
    from qualify_api.whatsapp.handler import payment_card_outbox

    clock = {"now": NOW}
    outbox = MemoryOutboxRepository(clock=lambda: clock["now"])
    thread_id = uuid4()
    outbox.threads[thread_id] = NOW - timedelta(minutes=5)
    card = SendPaymentCard(
        method_id="m1", caption="Paga aquí", qr_media_key=QR_KEY, brand_id=str(BRAND)
    )
    payload, attachment = payment_card_outbox(card, to=WA_ID)
    item_id = outbox.enqueue(
        tenant_id=TENANT,
        connection_id=CONN,
        thread_id=thread_id,
        kind="automation",
        payload=payload,
        created_by_user_id=None,
        attachment=attachment,
    )
    client = UploadingClient(WhatsAppApiError("boom", is_transport=True), "wamid.ok")
    reads: list[str] = []

    class Source:
        def read(self, tenant_id: UUID, object_key: str) -> bytes:
            reads.append(object_key)
            return _png()

    async def factory(**_: Any) -> UploadingClient:
        return client

    sender = OutboxSender(
        outbox,
        factory,
        lambda **_: None,
        worker_id="t",
        opt_ins=OptInService(MemoryOptInRepository(), clock=lambda: clock["now"]),
        clock=lambda: clock["now"],
        attachments=Source(),
    )
    assert (await sender.run_once(TENANT)).retried == 1
    clock["now"] = NOW + timedelta(minutes=5)
    assert (await sender.run_once(TENANT)).sent == 1
    assert client.uploads == 1 and reads == [QR_KEY]
    assert [p["image"]["id"] for p in client.payloads] == ["media-1", "media-1"]
    assert outbox.rows[item_id].attachment["media_id"] == "media-1"


# --- the owner's «Pago recibido» ---------------------------------------------------------


class Chat:
    def __init__(self, *, inbound_ago: timedelta = timedelta(hours=1)) -> None:
        self.repo = MemoryChatRepository()
        self.outbox = MemoryOutboxRepository(clock=lambda: NOW)
        self.chats = ChatService(self.repo, self.outbox, clock=lambda: NOW)
        self.store = MemoryPaymentStatusStore(self.repo)
        self.payments = PaymentStatusService(self.chats, self.store, clock=lambda: NOW)
        self.thread_id = self.repo.add_thread(tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID)
        self.repo.add_message(
            thread_id=self.thread_id,
            direction="inbound",
            text_value="Ref 123",
            posted_at=NOW - inbound_ago,
        )
        self.repo.pause_automation(tenant_id=TENANT, thread_id=self.thread_id, user_id=USER, at=NOW)

    def with_payment(self, status: str = "review") -> None:
        self.repo.states[self.thread_id].context[CTX_PAYMENT_RECORD] = {
            "choice": "method",
            "method_id": "m1",
            "name": "Pago móvil",
            "currency": "VES",
            "status": status,
        }

    def record(self) -> dict[str, Any]:
        return self.repo.states[self.thread_id].context[CTX_PAYMENT_RECORD]


def test_confirm_payment_sends_the_owners_message_and_records_who() -> None:
    chat = Chat()
    chat.with_payment()
    outbox_id = chat.payments.confirm_payment(TENANT, chat.thread_id, USER, CONFIRM_TEXT)
    row = chat.outbox.rows[outbox_id]
    assert row.kind == "reply" and row.payload["text"]["body"] == CONFIRM_TEXT
    record = chat.record()
    assert (record["status"], record["confirmed_by"], record["notified"]) == (
        "received",
        str(USER),
        True,
    )
    payment = chat.payments.payment_for(TENANT, chat.thread_id)
    assert payment.label == "Pago recibido" and payment.confirmed_at == NOW
    with pytest.raises(NoPendingPayment):  # never twice
        chat.payments.confirm_payment(TENANT, chat.thread_id, USER, CONFIRM_TEXT)


def test_confirm_payment_outside_the_window_sends_and_marks_nothing() -> None:
    chat = Chat(inbound_ago=timedelta(hours=25))
    chat.with_payment()
    with pytest.raises(WindowClosed):
        chat.payments.confirm_payment(TENANT, chat.thread_id, USER, CONFIRM_TEXT)
    assert chat.outbox.rows == {} and chat.record()["status"] == "review"
    # «Marcar pagado sin avisar»: recorded, nothing sent.
    chat.payments.mark_paid_without_message(TENANT, chat.thread_id, USER)
    assert chat.record()["status"] == "received" and chat.record()["notified"] is False
    assert chat.outbox.rows == {}


def test_without_a_payment_record_nothing_can_be_confirmed() -> None:
    chat = Chat()
    with pytest.raises(NoPendingPayment):
        chat.payments.confirm_payment(TENANT, chat.thread_id, USER, CONFIRM_TEXT)
    with pytest.raises(NoPendingPayment):
        chat.payments.mark_paid_without_message(TENANT, chat.thread_id, USER)


def test_another_tenant_cannot_see_or_confirm_the_payment() -> None:
    chat = Chat()
    chat.with_payment()
    assert chat.payments.payment_for(OTHER_TENANT, chat.thread_id) is None
    assert chat.payments.payments_for(OTHER_TENANT, [chat.thread_id]) == {}
    with pytest.raises(NoPendingPayment):
        chat.payments.mark_paid_without_message(OTHER_TENANT, chat.thread_id, USER)
    assert chat.record()["status"] == "review"


# --- the chat picker's «Formas de pago» ---------------------------------------------------


def _method(**kw: Any) -> PaymentMethod:
    base = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "brand_id": BRAND,
        "name": "Pago móvil",
        "name_key": "pago movil",
        "currency": "VES",
        "instructions": "Banco de Venezuela · 0414-1234567",
        "qr_media_key": QR_KEY,
        "active": True,
    }
    return PaymentMethod(**{**base, **kw})


class Picker:
    def __init__(self, methods: list[PaymentMethod]) -> None:
        self.chat = Chat()
        self.reads = MemoryAttachmentReads()
        self.reads.brands[(TENANT, CONN)] = BRAND
        self.blobs = MemoryBlobStore()
        self.blobs.objects[(TENANT, QR_KEY)] = _png()
        self.service = ChatAttachmentService(
            self.chat.chats,
            self.reads,
            self.blobs,
            payment_methods=lambda tenant, brand: [
                m for m in methods if m.tenant_id == tenant and m.brand_id == brand
            ],
            payment_store=self.chat.store,
            clock=lambda: NOW,
        )
        # The chat was taken over; resume it so the pause can be observed.
        self.chat.repo.resume_automation(tenant_id=TENANT, thread_id=self.chat.thread_id)


def test_the_picker_sends_the_same_card_and_pauses_the_automation() -> None:
    pago = _method()
    picker = Picker([pago])
    state = picker.chat.repo.states[picker.chat.thread_id]
    state.context["_order"] = {
        "items": [
            {"product_id": "p1", "name": "Shawarma", "qty": 2, "unit_price": "9", "currency": "USD"}
        ],
        "total": "18",
        "currency": "USD",
        "source_message_id": "wamid.order",
    }
    picks = picker.service.list_payment_methods_for_chat(TENANT, BRAND)
    assert [(p.name, p.currency_label, p.has_qr) for p in picks] == [
        ("Pago móvil", "En bolívares", True)
    ]

    picker.service.send_payment_method(TENANT, picker.chat.thread_id, USER, pago.id)

    (row,) = picker.chat.outbox.rows.values()
    assert row.kind == "reply" and row.payload["type"] == "image"
    assert row.payload["image"]["caption"] == payment_card_caption(
        PaymentOption(
            id=str(pago.id),
            name=pago.name,
            currency="VES",
            instructions=pago.instructions,
            qr_media_key=QR_KEY,
        ),
        total=Decimal("18"),
        order_currency="USD",
    )
    assert row.attachment["kind"] == "payment_method" and row.attachment["source_key"] == QR_KEY
    assert state.automation_paused_at == NOW and state.paused_by_user_id == USER
    payment = read_payment(state.context)
    assert (payment.status, payment.method_name) == ("awaiting", "Pago móvil")


def test_the_picker_card_without_an_order_has_no_total_and_marks_nothing() -> None:
    efectivo = _method(name="Efectivo", qr_media_key=None, instructions="", pay_on_delivery=True)
    picker = Picker([efectivo])
    picker.service.send_payment_method(TENANT, picker.chat.thread_id, USER, efectivo.id)
    (row,) = picker.chat.outbox.rows.values()
    assert row.payload["text"]["body"] == (
        "Pagas al recibir tu pedido. Una persona del equipo te confirma en un momento."
    )
    assert CTX_PAYMENT_RECORD not in picker.chat.repo.states[picker.chat.thread_id].context


def test_the_picker_refuses_another_business_method_or_a_number_without_brand() -> None:
    from qualify_api.whatsapp.payments import PaymentMethodNotFound

    foreign = _method(brand_id=uuid4())
    picker = Picker([foreign])
    with pytest.raises(PaymentMethodNotFound):
        picker.service.send_payment_method(TENANT, picker.chat.thread_id, USER, foreign.id)
    del picker.reads.brands[(TENANT, CONN)]
    with pytest.raises(AttachmentRefused) as refused:
        picker.service.send_payment_method(TENANT, picker.chat.thread_id, USER, foreign.id)
    assert refused.value.reason == "no_brand"
    assert picker.chat.outbox.rows == {}


def test_the_default_confirmation_fits_the_order() -> None:
    from qualify_api.whatsapp.payment_status import CONFIRM_ON_DELIVERY_TEXT

    before = read_payment({CTX_PAYMENT_RECORD: {"status": "review", "pay_on_delivery": False}})
    on_delivery = read_payment(
        {CTX_PAYMENT_RECORD: {"status": "on_delivery", "pay_on_delivery": True}}
    )
    assert before.confirm_text == CONFIRM_TEXT
    assert (
        on_delivery.confirm_text
        == CONFIRM_ON_DELIVERY_TEXT
        == ("¡Pago recibido, gracias por tu compra!")
    )


# --- review fixes (code + UX review of 20e49f2a) ------------------------------------------


async def _card_sent(h: Handler) -> None:
    h.at_address()
    await h.handle(_event(_text("Calle 5 #12", "wamid.addr")))
    await h.handle(_event(_reply("pay:m1", "wamid.pick")))


async def test_a_tap_or_a_menu_keyword_is_not_something_to_review() -> None:
    h = Handler((PAGO_MOVIL,))
    await _card_sent(h)
    await h.handle(_event(_reply("pay:m1", "wamid.again")))  # a second tap
    await h.handle(_event(_text("menú", "wamid.kw")))  # a menu keyword
    assert read_payment(h.context()).status == "awaiting"
    await h.handle(_event(_text("Ref 00987654", "wamid.ref")))
    assert read_payment(h.context()).status == "review"


async def test_a_resumed_thread_keeps_its_review_after_the_engine_runs() -> None:
    """The handler's own save must not put «awaiting» back over the review (nor drop
    its fields): the thread was handed back to the menu («Tu menú») and steps again."""
    h = Handler((PAGO_MOVIL,))
    await _card_sent(h)
    state = h.repo.states[h.thread_id()][1]
    h.repo.states[h.thread_id()] = (TENANT, replace(state, paused_at=None))  # resumed

    await h.handle(_event(_text("Ya pagué, ref 123", "wamid.ref")))

    record = h.context()[CTX_PAYMENT_RECORD]
    assert (record["status"], record["review_message_id"]) == ("review", "wamid.ref")
    assert h.repo.outbox[-1]["payload"]["type"] in ("text", "interactive")  # the menu answered


async def test_an_owners_received_written_meanwhile_is_never_undone() -> None:
    h = Handler((PAGO_MOVIL,))
    await _card_sent(h)
    thread_id = h.thread_id()
    tenant, state = h.repo.states[thread_id]
    stale = replace(state, paused_at=None, context=copy.deepcopy(state.context))
    # The owner confirms in the app while the worker holds the stale read.
    state.context[CTX_PAYMENT_RECORD]["status"] = "received"
    h.repo.states[thread_id] = (tenant, replace(state, paused_at=None))
    real_get = h.repo.get_thread_state
    h.repo.get_thread_state = lambda tid: stale if tid == thread_id else real_get(tid)  # type: ignore[method-assign]

    await h.handle(_event(_text("hola", "wamid.late")))

    assert h.repo.states[thread_id][1].context[CTX_PAYMENT_RECORD]["status"] == "received"


def test_a_resend_never_regresses_a_reviewed_or_received_payment() -> None:
    pago = _method()
    picker = Picker([pago])
    state = picker.chat.repo.states[picker.chat.thread_id]
    state.context["_order"] = {
        "items": [
            {"product_id": "p1", "name": "S", "qty": 1, "unit_price": "9", "currency": "USD"}
        ],
        "total": "9",
        "currency": "USD",
        "source_message_id": "wamid.order",
    }
    picker.service.send_payment_method(TENANT, picker.chat.thread_id, USER, pago.id)
    state.context[CTX_PAYMENT_RECORD]["status"] = "review"
    picker.service.send_payment_method(TENANT, picker.chat.thread_id, USER, pago.id)
    assert state.context[CTX_PAYMENT_RECORD]["status"] == "review"
    state.context[CTX_PAYMENT_RECORD]["status"] = "received"
    picker.service.send_payment_method(
        TENANT, picker.chat.thread_id, USER, pago.id, request_key="tap-1"
    )
    picker.service.send_payment_method(  # a replay: nothing prepared, nothing recorded
        TENANT, picker.chat.thread_id, USER, pago.id, request_key="tap-1"
    )
    assert state.context[CTX_PAYMENT_RECORD]["status"] == "received"


def _card_row(outbox: MemoryOutboxRepository, *, key: str = QR_KEY, brand: str = str(BRAND)):
    from qualify_api.whatsapp.handler import payment_card_outbox

    thread_id = uuid4()
    outbox.threads[thread_id] = NOW - timedelta(minutes=5)
    card = SendPaymentCard(method_id="m1", caption="Paga aquí", qr_media_key=key, brand_id=brand)
    payload, attachment = payment_card_outbox(card, to=WA_ID)
    return outbox.enqueue(
        tenant_id=TENANT,
        connection_id=CONN,
        thread_id=thread_id,
        kind="automation",
        payload=payload,
        created_by_user_id=None,
        attachment=attachment,
    )


def _sender(outbox, client, objects: dict[str, bytes], current: str | None):
    class Source:
        def __init__(self) -> None:
            self.reads: list[str] = []

        def read(self, tenant_id: UUID, object_key: str) -> bytes:
            self.reads.append(object_key)
            from qualify_shared.objects.gate import ObjectNotFound

            if object_key not in objects:
                raise ObjectNotFound(object_key)
            return objects[object_key]

    async def factory(**_: Any) -> UploadingClient:
        return client

    source = Source()
    sender = OutboxSender(
        outbox,
        factory,
        lambda **_: None,
        worker_id="t",
        opt_ins=OptInService(MemoryOptInRepository(), clock=lambda: NOW),
        clock=lambda: NOW,
        attachments=source,
        payment_qr=lambda *, tenant_id, method_id, brand_id: current,
    )
    return sender, source


async def test_a_replaced_qr_sends_the_methods_current_one() -> None:
    outbox = MemoryOutboxRepository(clock=lambda: NOW)
    item_id = _card_row(outbox)
    new_key = f"t/{TENANT}/whatsapp/payments/{BRAND}/{'b' * 32}.jpg"
    client = UploadingClient("wamid.ok")
    sender, source = _sender(outbox, client, {new_key: _png()}, current=new_key)
    report = await sender.run_once(TENANT)
    assert report.sent == 1 and source.reads == [QR_KEY, new_key]
    assert client.uploads == 1 and client.payloads[0]["image"]["id"] == "media-1"
    assert outbox.rows[item_id].status == "sent"


async def test_a_removed_qr_sends_the_instructions_as_text() -> None:
    outbox = MemoryOutboxRepository(clock=lambda: NOW)
    item_id = _card_row(outbox)
    client = UploadingClient("wamid.ok")
    sender, _ = _sender(outbox, client, {}, current=None)
    assert (await sender.run_once(TENANT)).sent == 1
    assert client.uploads == 0
    assert client.payloads[0]["type"] == "text"
    assert client.payloads[0]["text"]["body"] == "Paga aquí"
    assert outbox.rows[item_id].status == "sent"


async def test_a_card_key_outside_its_business_folder_is_refused() -> None:
    outbox = MemoryOutboxRepository(clock=lambda: NOW)
    item_id = _card_row(outbox, brand=str(uuid4()))  # QR_KEY is under BRAND, not this one
    client = UploadingClient()
    sender, source = _sender(outbox, client, {QR_KEY: _png()}, current=None)
    assert (await sender.run_once(TENANT)).failed == 1
    assert outbox.rows[item_id].error_code == "attachment_refused"
    assert source.reads == [] and client.payloads == []


def test_the_previous_qr_comes_from_the_locked_row() -> None:
    from qualify_api.whatsapp.payments import (
        MemoryPaymentMethodRepository,
        MemoryQrStore,
        PaymentMethodService,
        QrChange,
    )

    repo, qr = MemoryPaymentMethodRepository(), MemoryQrStore()
    service = PaymentMethodService(repo, qr)
    method = service.create_payment_method(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, name="Pago móvil", instructions="Así."
    )
    first = service.set_qr_image(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=method.id,
        user_id=USER,
        content=_png(),
        content_type="image/png",
    )
    stale = repo.rows[method.id]
    second = service.set_qr_image(  # another tab replaces it meanwhile
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=method.id,
        user_id=USER,
        content=_png(),
        content_type="image/png",
    )
    service._method = lambda *a: stale  # type: ignore[method-assign]  # the read before the lock
    third = service.save_payment_method(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=method.id,
        user_id=USER,
        qr=QrChange.image(_png(), "image/png"),
    )
    assert qr.deleted == [first.qr_media_key, second.qr_media_key]  # no orphan left
    assert set(k for _, k in qr.objects) == {third.qr_media_key}


def test_the_editor_knows_whether_the_stored_text_has_a_gap() -> None:
    from qualify_api.whatsapp.menus.starter import (
        PAYMENT_ANSWER_UNSET,
        PAYMENT_TEXT,
        StarterFacts,
        build_starter_menu,
        payment_answer,
    )

    answer = payment_answer(build_starter_menu(StarterFacts()), ())
    assert answer.stored_text == PAYMENT_TEXT and answer.stored_has_gap is True
    assert (
        PAYMENT_ANSWER_UNSET == "Al terminar tu pedido, una persona del equipo te dice cómo pagar."
    )


# --- re-review: the chat-sent card goes out; stickers are not proofs ---------------------


def _chat_card_queued():
    pago = _method()
    picker = Picker([pago])
    picker.service.send_payment_method(TENANT, picker.chat.thread_id, USER, pago.id)
    (row,) = picker.chat.outbox.rows.values()
    picker.chat.outbox.threads[picker.chat.thread_id] = NOW - timedelta(minutes=5)
    return picker, row


async def test_a_card_sent_from_the_chat_is_uploaded_and_sent() -> None:
    picker, row = _chat_card_queued()
    assert row.attachment["object_key"].startswith(f"t/{TENANT}/whatsapp/outbound/")
    assert row.attachment["source_key"] == QR_KEY and row.attachment["brand_id"] == str(BRAND)
    objects = {k: v for (_, k), v in picker.blobs.objects.items()}
    client = UploadingClient("wamid.ok")
    sender, source = _sender(picker.chat.outbox, client, objects, current=None)
    report = await sender.run_once(TENANT)
    assert report.sent == 1 and client.uploads == 1
    assert client.payloads[0]["type"] == "image" and client.payloads[0]["image"]["id"] == "media-1"
    assert source.reads == [row.attachment["object_key"]]


@pytest.mark.parametrize("crafted", ["object_key", "source_key"])
async def test_a_chat_card_with_a_crafted_key_is_refused(crafted: str) -> None:
    picker, row = _chat_card_queued()
    other_brand = f"t/{TENANT}/whatsapp/payments/{uuid4()}/{'c' * 32}.png"
    row.attachment[crafted] = other_brand
    objects = {k: v for (_, k), v in picker.blobs.objects.items()} | {other_brand: _png()}
    client = UploadingClient()
    sender, source = _sender(picker.chat.outbox, client, objects, current=None)
    assert (await sender.run_once(TENANT)).failed == 1
    assert row.error_code == "attachment_refused" and client.payloads == []


async def test_a_sticker_is_not_a_payment_proof() -> None:
    h = Handler((PAGO_MOVIL,))
    await _card_sent(h)
    sticker = {
        "from": WA_ID,
        "id": "wamid.sticker",
        "timestamp": "1791953700",
        "type": "sticker",
        "sticker": {"id": "media-7", "mime_type": "image/webp"},
    }
    await h.handle(_event(sticker))
    assert read_payment(h.context()).status == "awaiting"


@pytest.mark.parametrize("pipeline", [None, "", "wa-something-else"])
async def test_a_payment_card_of_an_unknown_pipeline_is_refused(pipeline) -> None:
    picker, row = _chat_card_queued()
    if pipeline is None:
        del row.attachment["pipeline"]
    else:
        row.attachment["pipeline"] = pipeline
    objects = {k: v for (_, k), v in picker.blobs.objects.items()}
    client = UploadingClient()
    sender, source = _sender(picker.chat.outbox, client, objects, current=None)
    assert (await sender.run_once(TENANT)).failed == 1
    assert row.error_code == "attachment_refused"
    assert source.reads == [] and client.payloads == []


def test_the_chat_pipeline_stamp_is_the_attachments_one() -> None:
    from qualify_api.whatsapp.attachments import ATTACHMENT_PIPELINE
    from qualify_api.whatsapp.outbox import CHAT_CARD_PIPELINE

    assert CHAT_CARD_PIPELINE == ATTACHMENT_PIPELINE
