"""m-24955648 part 2 — the payment in Chats, offline (`docs/ux-paso-de-pago.md` §4–§5).

A real `WhatsAppChatsState` over a fake gateway: the list's pills from ONE
`payment_statuses` read, the order card's «Pago recibido» (the exact message shown
before it goes; a closed window offers «Marcar pagado sin avisar»; nothing is sent
without the owner's tap; a late result after switching chat is dropped), «No lo
encuentro» (sends nothing), and «Foto o menú» → «Formas de pago».
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from qualify_api.whatsapp.chats import WindowClosed
from qualify_api.whatsapp.payment_status import (
    CONFIRM_TEXT,
    NOT_FOUND_TEXT,
    STATUS_LABELS,
    NoPendingPayment,
    PaymentStatus,
)
from qualify_api.whatsapp.payments import PaymentMethodNotFound

from . import whatsapp_chats_state as state_module
from . import whatsapp_tab_chats
from .whatsapp_chats_provider import PickerScope
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import (
    EMPTY_THREAD,
    PAYMENT_ALREADY,
    PAYMENT_GONE,
    PAYMENT_PAID_SILENT_TOAST,
    PAYMENT_PAID_TOAST,
    PAYMENT_WINDOW_CLOSED,
    PAYMENTS_EMPTY_TITLE,
    PICK_PAYMENTS,
    AgentVM,
    build_payment,
    payment_confirm_title,
    payment_pill,
    pick_step_title,
    with_payment_pills,
)

TENANT = UUID("a0000000-0000-4000-8000-000000955648")
BRAND = UUID("c0000000-0000-4000-8000-000000955648")
CONN = "d0000000-0000-4000-8000-000000955648"
THREAD = "f0000000-0000-4000-8000-000000955648"
OTHER = "f1000000-0000-4000-8000-000000955648"
USER = UUID("e0000000-0000-4000-8000-000000955648")
PAGO_MOVIL = "30000000-0000-4000-8000-000000000001"
EFECTIVO = "30000000-0000-4000-8000-000000000002"
UTC_ZONE = ZoneInfo("UTC")
NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def _status(status: str | None, **kw: Any) -> PaymentStatus:
    base: dict[str, Any] = {
        "status": status,
        "label": STATUS_LABELS.get(status or "", ""),
        "choice": "method",
        "method_id": PAGO_MOVIL,
        "method_name": "Pago móvil",
        "currency": "VES",
        "pay_on_delivery": False,
        "order_total": Decimal("18"),
        "order_currency": "USD",
    }
    base.update(kw)
    return PaymentStatus(**base)


@dataclass(frozen=True)
class _Pick:
    id: str
    name: str
    currency: str = "VES"
    currency_label: str = "En bolívares"
    pay_on_delivery: bool = False
    has_qr: bool = True
    thumb_url: str = "https://media/qr.png"
    updated_at: datetime = NOW


@dataclass
class FakeGateway:
    methods: list[_Pick] = field(default_factory=list)
    fail: BaseException | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def picker_scope(self, tenant_id: UUID, connection_id: UUID) -> PickerScope:
        return PickerScope(brand_id=BRAND, sector="food_drink", rubro="")

    def list_payment_methods_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[_Pick]:
        self.calls.append(("list", brand_id))
        return list(self.methods)

    def payment_card_preview(self, tenant, connection, thread, method_id) -> str:
        self.calls.append(("preview", str(method_id)))
        if self.fail is not None:
            raise self.fail
        return "Banco 0102 · RIF J-1\nTotal: USD 18\nCuando pagues, envíanos el comprobante."

    def send_payment_method(self, tenant, connection, thread, user, method_id, request_key):
        self.calls.append(("send", (str(thread), str(method_id), request_key)))
        return UUID(int=1)

    def confirm_payment(self, tenant, connection, thread, user, message, request_key):
        self.calls.append(("confirm", (str(thread), message, request_key)))
        if self.fail is not None:
            raise self.fail
        return UUID(int=2)

    def mark_paid_without_message(self, tenant, connection, thread, user) -> None:
        self.calls.append(("silent", str(thread)))

    def payment_statuses(self, tenant_id, thread_ids):
        self.calls.append(("statuses", list(thread_ids)))
        return {UUID(THREAD): _status("review")}


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    fake = FakeGateway(methods=[_Pick(PAGO_MOVIL, "Pago móvil"), _Pick(EFECTIVO, "Efectivo")])
    monkeypatch.setattr(state_module, "gateway", lambda: fake)

    async def tenant(self: WhatsAppChatsState) -> UUID:
        return TENANT

    async def acting(self: WhatsAppChatsState, tenant_id: UUID) -> UUID:
        return USER

    monkeypatch.setattr(WhatsAppChatsState, "_tenant", tenant)
    monkeypatch.setattr(WhatsAppChatsState, "_acting_user", acting)
    return fake


def _row(thread_id: str = THREAD, *, open_window: bool = True) -> Any:
    return dataclasses.replace(
        EMPTY_THREAD,
        thread_id=thread_id,
        title="María G.",
        window_open=open_window,
        window_label="Puedes escribirle",
        window_tone="ok" if open_window else "neutral",
    )


def _state(payment: PaymentStatus | None = None, *, open_window: bool = True) -> Any:
    state = WhatsAppChatsState()
    state._connection_id = CONN
    state.rows = [_row(open_window=open_window), _row(OTHER)]
    state.open_thread_id = THREAD
    state._payment_raw = payment
    state._render_conversation()
    return state


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


def _text(events: Any) -> str:
    return json.dumps(str(events), ensure_ascii=False)


# --- the view model -------------------------------------------------------------------


def test_pills_ask_for_attention_only_on_review_and_received_only_that_day() -> None:
    assert payment_pill("review", "Pago por revisar", None, NOW, UTC_ZONE) == (
        "Pago por revisar",
        "warn",
    )
    assert payment_pill("awaiting", "Esperando el pago", None, NOW, UTC_ZONE)[1] == "neutral"
    today = payment_pill("received", "Pago recibido", NOW, NOW, UTC_ZONE)
    assert today == ("Pago recibido", "ok")
    yesterday = NOW - timedelta(days=1)
    assert payment_pill("received", "Pago recibido", yesterday, NOW, UTC_ZONE) == ("", "neutral")
    assert payment_pill(None, "", None, NOW, UTC_ZONE) == ("", "neutral")


def test_the_card_says_how_they_pay_and_who_confirmed() -> None:
    vm = build_payment(_status("awaiting"), now=NOW, zone=UTC_ZONE)
    assert vm.method_line == "Paga con: Pago móvil (en bolívares)" and vm.can_confirm
    cash = build_payment(
        _status("on_delivery", method_name="Efectivo", pay_on_delivery=True, currency=""),
        now=NOW,
        zone=UTC_ZONE,
    )
    assert cash.method_line == "Paga con: Efectivo (al recibir)"
    other = build_payment(_status(None, choice="other", method_name=None), now=NOW, zone=UTC_ZONE)
    assert other.method_line == "Forma de pago: quiere otra" and other.can_confirm
    done = build_payment(
        _status("received", confirmed_by=USER, confirmed_at=NOW),
        now=NOW,
        zone=UTC_ZONE,
        agents={str(USER): AgentVM(user_id=str(USER), name="Ana", initials="A")},
    )
    assert not done.can_confirm
    assert done.confirmed_line == "Pago recibido · lo confirmó Ana · 15:00"
    assert payment_confirm_title("María G.") == "¿Ya te llegó el pago de María G.?"


def test_the_list_gets_its_pills_from_one_read(gw) -> None:
    rows = with_payment_pills([_row(), _row(OTHER)], {THREAD: _status("review")}, NOW, UTC_ZONE)
    assert (rows[0].payment_label, rows[0].payment_tone) == ("Pago por revisar", "warn")
    assert rows[1].payment_label == ""
    statuses = state_module._payment_statuses(gw, TENANT, [UUID(THREAD), UUID(OTHER)])
    assert [c for c in gw.calls if c[0] == "statuses"] == [
        ("statuses", [UUID(THREAD), UUID(OTHER)])
    ]  # one call for the whole list
    assert set(statuses) == {THREAD}
    assert state_module._payment_statuses(gw, TENANT, []) == {}


def test_a_failing_status_read_never_breaks_the_list() -> None:
    class Broken:
        def payment_statuses(self, *a: Any) -> Any:
            raise RuntimeError("db")

    assert state_module._payment_statuses(Broken(), TENANT, [UUID(THREAD)]) == {}


# --- «Pago recibido» ------------------------------------------------------------------


async def test_pago_recibido_shows_the_message_then_sends_it_on_the_owners_tap(gw) -> None:
    state = _state(_status("review"))
    state.open_payment_confirm()
    assert state.pay_confirm_open and state.pay_message == CONFIRM_TEXT
    assert gw.calls == []  # opening the sheet sends nothing
    state.set_pay_message("¡Recibido, gracias María!")
    events = await _drain(state._pay(silent=False))
    assert gw.calls[0][0] == "confirm"
    assert gw.calls[0][1][1] == "¡Recibido, gracias María!"
    assert not state.pay_confirm_open and PAYMENT_PAID_TOAST in _text(events)
    assert state.rows[0].automation_paused  # a person's message pauses the automation


async def test_a_closed_window_offers_marking_it_without_a_message(gw) -> None:
    state = _state(_status("review"), open_window=False)
    state.open_payment_confirm()
    assert state.pay_window_closed and state.pay_error == PAYMENT_WINDOW_CLOSED
    assert await _drain(state._pay(silent=False)) == [] and gw.calls == []  # never sent
    events = await _drain(state._pay(silent=True))
    assert ("silent", THREAD) in gw.calls and PAYMENT_PAID_SILENT_TOAST in _text(events)


async def test_window_closed_from_the_server_marks_nothing_and_offers_the_way_out(gw) -> None:
    state = _state(_status("awaiting"))
    state.open_payment_confirm()
    gw.fail = WindowClosed("closed")
    await _drain(state._pay(silent=False))
    assert state.pay_confirm_open and state.pay_window_closed
    assert state.pay_error == PAYMENT_WINDOW_CLOSED
    assert not any(c[0] == "silent" for c in gw.calls)


async def test_already_received_is_said_plainly(gw) -> None:
    state = _state(_status("awaiting"))
    state.open_payment_confirm()
    gw.fail = NoPendingPayment("x")
    await _drain(state._pay(silent=False))
    assert state.pay_error == PAYMENT_ALREADY


async def test_a_late_result_after_switching_chat_is_dropped(gw) -> None:
    state = _state(_status("review"))
    state.open_payment_confirm()

    original = gw.confirm_payment

    def switch_then_confirm(*args: Any) -> UUID:
        state.open_thread_id = OTHER  # the owner opened another chat meanwhile
        return original(*args)

    gw.confirm_payment = switch_then_confirm  # type: ignore[method-assign]
    events = await _drain(state._pay(silent=False))
    assert events == [] and not state.rows[0].automation_paused


def test_no_lo_encuentro_only_fills_the_composer(gw) -> None:
    state = _state(_status("review"))
    state.payment_not_found()
    assert state.draft_text == NOT_FOUND_TEXT and gw.calls == []


# --- «Foto o menú» → «Formas de pago» -------------------------------------------------


async def test_the_picker_lists_the_offered_methods_and_sends_the_card(gw) -> None:
    state = _state()
    state.open_picker()
    events = state.choose_pick_source(PICK_PAYMENTS)
    assert events and pick_step_title(2, PICK_PAYMENTS, "") == "¿Cuál forma de pago?"
    await _drain(WhatsAppChatsState.load_pick_payments.fn(state))
    assert [c.name for c in state.pick_payments] == ["Pago móvil", "Efectivo"]
    assert state.pick_payments[0].updated_label == "Actualizado el 6 nov"
    state.choose_payment(PAGO_MOVIL)
    assert state.pick_step == 3 and not state.pick_can_send  # the caption is not read yet
    await WhatsAppChatsState.load_payment_preview.fn(state)
    assert state.pick_preview_text.startswith("Banco 0102") and state.pick_can_send
    await _drain(state._send_pick())
    sent = [c for c in gw.calls if c[0] == "send"]
    assert sent and sent[0][1][:2] == (THREAD, PAGO_MOVIL)
    assert not state.pick_open


async def test_one_offered_method_goes_straight_to_the_review(gw) -> None:
    gw.methods = [_Pick(PAGO_MOVIL, "Pago móvil")]
    state = _state()
    state.open_picker()
    state.choose_pick_source(PICK_PAYMENTS)
    events = await _drain(WhatsAppChatsState.load_pick_payments.fn(state))
    assert state.pick_step == 3 and state.pick_selected == PAGO_MOVIL
    assert "load_payment_preview" in str(events)


async def test_a_method_switched_off_meanwhile_is_said_plainly(gw) -> None:
    state = _state()
    state.open_picker()
    state.choose_pick_source(PICK_PAYMENTS)
    await _drain(WhatsAppChatsState.load_pick_payments.fn(state))
    state.choose_payment(EFECTIVO)
    gw.fail = PaymentMethodNotFound("x")
    await WhatsAppChatsState.load_payment_preview.fn(state)
    assert state.pick_error == PAYMENT_GONE and not state.pick_can_send


async def test_no_methods_shows_the_way_to_add_them(gw) -> None:
    gw.methods = []
    state = _state()
    state.open_picker()
    state.choose_pick_source(PICK_PAYMENTS)
    await _drain(WhatsAppChatsState.load_pick_payments.fn(state))
    assert state.pick_payments == [] and state.pick_step == 2
    rendered = str(whatsapp_tab_chats.chats_tab())
    for words in (PAYMENTS_EMPTY_TITLE, "tab=numero&sub=pagos", "Formas de pago"):
        assert json.dumps(words)[1:-1] in rendered, words


def test_the_chat_carries_the_payment_actions() -> None:
    rendered = str(whatsapp_tab_chats.chats_tab())
    for words in (
        "Pago recibido",
        "No lo encuentro",
        "Enviar y marcar pagado",
        "Todavía no",
        "Marcar pagado sin avisar",
        "Busca la referencia en tu banco antes de confirmar.",
        "Cambiar estos datos",
    ):
        assert json.dumps(words)[1:-1] in rendered, words


# --- §6(a): Respuesta automática, step 3 ----------------------------------------------


def test_the_menu_invites_to_add_payment_methods_only_when_there_are_none(monkeypatch) -> None:
    from . import whatsapp_menu_state as menu_module
    from . import whatsapp_payments_provider as payments_provider
    from . import whatsapp_tab_menu
    from .whatsapp_menu_vm import PAYMENTS_INVITE, PAYMENTS_INVITE_BUTTON

    monkeypatch.undo()  # drop the conftest stub: the real helper is under test here
    offered = menu_module._offered_payments
    monkeypatch.setattr(
        payments_provider,
        "list_methods",
        lambda t, b: [{"active": True}, {"active": False}, {"active": True}],
    )
    assert offered(TENANT, BRAND) == 2
    assert offered(TENANT, None) == 0

    def boom(t: UUID, b: UUID) -> Any:
        raise RuntimeError("db")

    monkeypatch.setattr(payments_provider, "list_methods", boom)
    assert offered(TENANT, BRAND) == -1  # unknown: the notice does not show on a guess
    rendered = str(whatsapp_tab_menu.menu_tab())
    for words in (PAYMENTS_INVITE, PAYMENTS_INVITE_BUTTON, "save_and_open_payments"):
        assert json.dumps(words)[1:-1] in rendered, words
    assert menu_module.PAYMENTS_HREF == "/whatsapp?tab=numero&sub=pagos"
