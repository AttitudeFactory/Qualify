"""m-25027371 (BU-A5): one chat thread for WhatsApp and Instagram — the shared view model,
the one rule set in `assets/qualify-inbox.css`, and both pages drawing the same pieces."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from . import chat_thread, conversations_page, whatsapp_tab_chats
from .chat_thread_vm import (
    BUBBLE_LINK_HIGH_CONTRAST,
    CLOSE_LABEL,
    MORE_ACTIONS_LABEL,
    REOPEN_LABEL,
    SETTINGS_LABEL,
    day_label,
    mark_days,
    order_strip_label,
    show_assign,
    thread_style,
    window_line,
)
from .test_whatsapp_chats_payments import gw  # noqa: F401 — the fake gateway fixture
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import (
    WINDOW_CLOSED_PILL,
    AgentVM,
    OrderCardVM,
    PaymentVM,
    UnsentItem,
    build_conversation,
)

_CSS = Path(__file__).resolve().parent.parent / "assets" / "qualify-inbox.css"
ZONE = ZoneInfo("America/Bogota")
# 2026-11-14 12:00 in Bogotá
NOW = datetime(2026, 11, 14, 17, 0, tzinfo=UTC)


# --- «⋯»: «Asignar» only with a team ------------------------------------------------------


@pytest.mark.parametrize(("people", "shown"), [(0, False), (1, False), (2, True), (5, True)])
def test_assign_shows_only_when_more_than_one_person_has_access(people: int, shown: bool) -> None:
    assert show_assign(people) is shown


def test_the_state_counts_the_people_with_access() -> None:
    state = WhatsAppChatsState()
    state.agents = [AgentVM(user_id="u1", name="Ana", initials="A")]
    assert state.show_assign is False
    state.agents = [*state.agents, AgentVM(user_id="u2", name="Luis", initials="L")]
    assert state.show_assign is True


def test_the_menu_keeps_todays_words() -> None:
    """m-25026457 chose «Cerrar» / «Reabrir»; the ticket's «Cerrar chat» is not applied."""
    assert (CLOSE_LABEL, REOPEN_LABEL) == ("Cerrar", "Reabrir")
    assert SETTINGS_LABEL == "Ajustes de este canal"


# --- the header's window line ---------------------------------------------------------------


def test_window_line_says_until_when_today() -> None:
    text, tone = window_line(True, NOW + timedelta(hours=5), NOW, ZONE)
    assert (text, tone) == ("Puedes escribirle hasta las 17:00", "ok")


def test_window_line_says_tomorrow_when_it_closes_another_day() -> None:
    text, tone = window_line(True, NOW + timedelta(hours=20), NOW, ZONE)
    assert text == "Puedes escribirle hasta mañana a las 08:00" and tone == "ok"


def test_window_line_uses_the_rows_words_under_an_hour() -> None:
    assert window_line(True, NOW + timedelta(minutes=12, seconds=30), NOW, ZONE) == (
        "Quedan 12 min para responder",
        "warn",
    )


def test_window_line_closed_is_what_the_channel_says() -> None:
    assert window_line(False, None, NOW, ZONE) == ("", "neutral")
    assert window_line(True, NOW - timedelta(minutes=1), NOW, ZONE, closed_text="x") == (
        "x",
        "neutral",
    )


# --- day separators ------------------------------------------------------------------------


def test_day_labels_in_the_tenants_calendar() -> None:
    assert day_label(NOW, ZONE, NOW) == "Hoy"
    assert day_label(NOW - timedelta(days=1), ZONE, NOW) == "Ayer"
    assert day_label(NOW - timedelta(days=9), ZONE, NOW) == "5 nov"
    assert day_label(datetime(2025, 3, 2, 15, tzinfo=UTC), ZONE, NOW) == "2 mar 2025"


@dataclass(frozen=True)
class _Vm:
    n: int
    day: str = ""


def test_mark_days_labels_only_the_first_message_of_each_day() -> None:
    items = [
        (NOW - timedelta(days=1), _Vm(1)),
        (NOW - timedelta(days=1, minutes=-5), _Vm(2)),
        (NOW, _Vm(3)),
    ]
    out = mark_days(items, ZONE, NOW, lambda vm, label: replace(vm, day=label))
    assert [v.day for v in out] == ["Ayer", "", "Hoy"]


@dataclass
class _Msg:
    id: str
    direction: str
    text: str
    posted_at: datetime
    media_kind: str | None = None
    delivery_status: str | None = None
    delivery_error_code: str | None = None
    has_media: bool = False
    external_message_id: str = ""


def test_whatsapp_gets_day_separators_and_clock_only_bubbles() -> None:
    yesterday = NOW - timedelta(days=1)
    vms = build_conversation(
        [
            _Msg("a", "inbound", "Hola", yesterday),
            _Msg("b", "outbound", "Buenas", yesterday + timedelta(minutes=2), None, "read"),
        ],
        [UnsentItem(id="q1", text="¿Algo más?", status="pending", created_at=NOW, error_code=None)],
        now=NOW,
        zone=ZONE,
    )
    assert [v.day_label for v in vms] == ["Ayer", "", "Hoy"]
    assert vms[0].time_label == "12:00" and vms[1].time_label == "12:02"
    assert vms[1].tick == "read" and vms[2].tick == "queued"


# --- the order strip -----------------------------------------------------------------------


def test_order_strip_label_reads_items_total_and_payment() -> None:
    assert (
        order_strip_label("3 productos", "COP 45.000", "Pago por revisar")
        == "Pedido · 3 productos · COP 45.000 · Pago por revisar"
    )
    assert order_strip_label("1 producto", "COP 9.000") == "Pedido · 1 producto · COP 9.000"


def test_the_state_folds_the_order_with_its_payment() -> None:
    state = WhatsAppChatsState()
    state.order = OrderCardVM(present=True, items_label="2 productos", total_label="COP 20.000")
    state.payment = PaymentVM(present=True, label="Pago recibido", tone="ok")
    assert state.order_strip_label == "Pedido · 2 productos · COP 20.000 · Pago recibido"


def test_the_order_card_opens_inside_the_strip_unchanged() -> None:
    rendered = str(whatsapp_tab_chats._order_card())
    assert "q-chat-order" in rendered and "order_strip_label" in rendered
    for text in ("Pedido listo", "Total", "send_order_ready", "LucideShoppingBag"):
        assert text in rendered, text


# --- the colour: one rule set from the channel's scale ------------------------------------------


def test_the_channel_colour_comes_from_the_platform_scale() -> None:
    assert thread_style("whatsapp")["--q-chat-tint-4"] == "var(--green-a4)"
    assert thread_style("instagram")["--q-chat-tint-4"] == "var(--pink-a4)"
    assert thread_style("instagram")["--q-chat-tint-5"] == "var(--pink-a5)"


def test_no_channel_specific_bubble_rules_remain() -> None:
    css = re.sub(r"/\*.*?\*/", "", _CSS.read_text(), flags=re.S)  # rules, not comments
    assert not re.search(r"purple-9.*pink-9.*orange-9", css, flags=re.S)
    assert ".q-wa-msg--glass" not in css and ".q-wa-card" not in css
    assert "q-conv-card" not in css and "white" not in css.replace("white-space", "")
    assert "rgb(" not in css and "hsl(" not in css


def test_the_business_bubble_is_the_measured_tint() -> None:
    css = _CSS.read_text()
    rule = css[css.index(".q-chat-msg--out .q-bubble--out {") :]
    rule = rule[: rule.index("}")]
    assert "linear-gradient(160deg, var(--q-chat-tint-4), var(--q-chat-tint-3))" in rule
    assert "var(--q-control-fill)" in rule and "inset 0 0 0 1px var(--q-chat-tint-5)" in rule
    assert "color: var(--gray-12)" in rule


def test_the_wash_lives_in_the_header_and_the_ux_proposals_flip_in_one_line() -> None:
    css = _CSS.read_text()
    head = css[css.index(".q-chat-head {") :]
    assert "var(--q-chat-tint-3)" in head[: head.index("}")]
    thread = css[css.index(".q-chat-thread {") :]
    thread = thread[: thread.index("}")]
    for var in (
        "--q-chat-scroll-wash: none",
        "--q-chat-out-meta: var(--gray-12)",
        "--q-chat-out-error: var(--tomato-12)",
        "--q-chat-in-meta: var(--gray-11)",
    ):
        assert var in thread, var
    assert BUBBLE_LINK_HIGH_CONTRAST is True


def test_the_phone_fixes_of_m24984052_still_hold() -> None:
    css = _CSS.read_text()
    assert "padding-bottom: max(0.25rem, env(safe-area-inset-bottom))" in css
    assert ".q-chat-thread .q-wa-composer .rt-Button" in css
    wrap = css[css.index(".q-chat-msg .q-bubble {") :]
    assert "overflow-wrap: anywhere" in wrap[: wrap.index("}")]
    motion = css[css.rindex("@media (prefers-reduced-motion: reduce)") :]
    assert ".q-chat-msg" in motion and "animation: none" in motion


# --- both pages draw the same thread ---------------------------------------------------------


def test_both_chats_use_the_shared_thread() -> None:
    wa = str(whatsapp_tab_chats._conversation())
    ig = str(conversations_page._conversation())
    for page in (wa, ig):
        for piece in ("q-chat-thread", "q-chat-head", "q-chat-scroll", "q-chat-more"):
            assert piece in page, piece
    assert "--green-a4" in wa and "--pink-a4" in ig
    assert "Asignar" in wa and "show_assign" in wa
    assert "Asignar" not in ig  # Instagram chats cannot be assigned
    assert "change_chat_status" in ig  # the compare-and-set close stays
    assert "Tomar el control" in wa


def test_the_status_mark_has_its_word_and_no_inline_colour() -> None:
    import reflex as rx

    rendered = str(chat_thread.status_mark(rx.Var.create("read"), rx.Var.create("Seen")))
    assert '"aria-label":"Seen"' in rendered or 'ariaLabel:"Seen"' in rendered
    assert 'role:"img"' in rendered and "q-chat-tick" in rendered
    assert "color" not in rendered  # the sheet colours it (measured tokens)
    assert MORE_ACTIONS_LABEL == "Más acciones de este chat"


def test_no_channel_says_window_closed_twice() -> None:
    assert WINDOW_CLOSED_PILL == "Solo con mensaje aprobado"


# --- the business's zone reaches a chat opened by its address ------------------------------


async def test_a_chat_loaded_before_the_zone_is_redrawn_in_it(gw, monkeypatch) -> None:  # noqa: ANN001, F811
    """Seen in the browser (m-25027371): a chat opened from «Por responder» can load
    before the first list read knows the business's zone, and drew the UTC clock. The
    list read redraws it: bubbles, separators, the order and the payment lines."""
    from qualify_api.whatsapp.orders import OrderLine, OrderSummary

    from .test_whatsapp_chats import _message, _thread
    from .test_whatsapp_chats_payments import CONN, THREAD, _status

    noon = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    at = datetime(2026, 11, 14, 3, 30, tzinfo=UTC)  # 2026-11-13 22:30 in Bogotá
    monkeypatch.setattr(WhatsAppChatsState, "_now", lambda self: noon)
    monkeypatch.setattr(gw, "timezone", lambda t: "America/Bogota", raising=False)
    monkeypatch.setattr(gw, "agents", lambda t: [], raising=False)
    monkeypatch.setattr(gw, "threads", lambda t, c: [_thread(id=UUID(THREAD))], raising=False)
    state = WhatsAppChatsState()
    state._connection_id = CONN
    state.open_thread_id = THREAD
    state.conv_loaded_for = THREAD
    state._records = [_message(posted_at=at)]
    state._order_raw = OrderSummary(
        lines=(OrderLine(product_id="p", name="Shawarma", qty=1),),
        total=Decimal("25000"),
        currency="COP",
        confirmed_at=at,
    )
    state._payment_raw = _status("received", confirmed_at=at + timedelta(minutes=10))
    state._render_conversation()  # before the zone: UTC
    assert state.messages[0].time_label == "03:30" and state.messages[0].day_label == "Hoy"

    assert await WhatsAppChatsState._read_list(state, silent=False)
    assert state.messages[0].time_label == "22:30" and state.messages[0].day_label == "Ayer"
    assert "22:30" in state.order.confirmed_label
    assert "22:40" in state.payment.confirmed_line
