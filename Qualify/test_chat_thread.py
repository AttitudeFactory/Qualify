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
from qualify_api.whatsapp.chats import WindowView

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
    WINDOW_CLOSED_LINE,
    AgentVM,
    OrderCardVM,
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
    """m-25026457 chose «Cerrar» / «Reabrir»; the ticket's «Cerrar chat» is not applied.
    Both menus draw them, and «Ajustes de este canal»."""
    assert (CLOSE_LABEL, REOPEN_LABEL) == ("Cerrar", "Reabrir")
    for menu in (whatsapp_tab_chats._more_menu(), conversations_page._more_menu()):
        rendered = str(menu)
        assert '"Cerrar"' in rendered and '"Reabrir"' in rendered
        assert "Cerrar chat" not in rendered
        assert SETTINGS_LABEL in rendered


def test_channel_settings_go_to_ajustes_de_chats() -> None:
    """m-25017861 (D1): «⋯» › «Ajustes de este canal» opens «Ajustes de chats» — on
    WhatsApp «Tu menú de bienvenida», on Instagram the hub with that account's
    «Preguntas iniciales» open (the page appends the account id)."""
    from .chat_settings_vm import instagram_settings_href
    from .chat_thread_vm import INSTAGRAM_SETTINGS_PREFIX, WHATSAPP_SETTINGS_HREF

    assert WHATSAPP_SETTINGS_HREF == "/chats/ajustes/whatsapp"
    assert INSTAGRAM_SETTINGS_PREFIX == "/chats/ajustes/instagram?cuenta="
    account = "00000000-0000-4000-8000-0000000000aa"
    assert instagram_settings_href(account) == INSTAGRAM_SETTINGS_PREFIX + account
    page = (Path(__file__).parent / "conversations_page.py").read_text(encoding="utf-8")
    assert 'rx.redirect(f"{INSTAGRAM_SETTINGS_PREFIX}{S.selected_connection_id}")' in page
    chats = (Path(__file__).parent / "whatsapp_tab_chats.py").read_text(encoding="utf-8")
    assert "rx.redirect(WHATSAPP_SETTINGS_HREF)" in chats


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


def test_order_strip_label_reads_items_total_and_what_the_channel_adds() -> None:
    assert order_strip_label("1 producto", "COP 9.000") == "Pedido · 1 producto · COP 9.000"
    assert (
        order_strip_label("2 productos", "COP 20.000", "Forma de pago: quiere otra")
        == "Pedido · 2 productos · COP 20.000 · Forma de pago: quiere otra"
    )


_EARLIER = NOW - timedelta(days=2)
_NO_METHOD = {"method_id": None, "method_name": None}


@pytest.mark.parametrize(
    ("status", "kw", "header", "strip"),
    [
        # a pill in the header right above: the strip does not repeat it
        ("review", {}, "Pago por revisar", ""),
        ("awaiting", {}, "Esperando el pago", ""),
        ("on_delivery", {"pay_on_delivery": True}, "Paga al recibir", ""),
        ("received", {"confirmed_at": NOW - timedelta(hours=1)}, "Pago recibido", ""),
        # received on an earlier day: information only, nothing waits behind the fold
        ("received", {"confirmed_at": _EARLIER}, "", ""),
        # no status yet: «Pago recibido» / «No lo encuentro» wait behind the fold and
        # the header has no pill, so the strip says the card's own line
        (None, {"choice": "other", **_NO_METHOD}, "", "Forma de pago: quiere otra"),
        (None, {"choice": "none", **_NO_METHOD}, "", "Forma de pago: no eligió"),
    ],
)
def test_the_strip_names_the_payment_only_when_the_header_does_not(
    status: str | None, kw: dict, header: str, strip: str
) -> None:
    from .test_whatsapp_chats_payments import _status
    from .whatsapp_chats_vm import build_payment, strip_payment_part

    payment = build_payment(_status(status, **kw), now=NOW, zone=ZONE)
    assert payment.label == header
    assert strip_payment_part(payment) == strip
    state = WhatsAppChatsState()
    state.order = OrderCardVM(present=True, items_label="2 productos", total_label="COP 20.000")
    state.payment = payment
    expected = "Pedido · 2 productos · COP 20.000" + (f" · {strip}" if strip else "")
    assert state.order_strip_label == expected


def test_no_payment_no_payment_part() -> None:
    from .whatsapp_chats_vm import EMPTY_PAYMENT, strip_payment_part

    assert strip_payment_part(EMPTY_PAYMENT) == ""


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
    # m-25027374: the header is two blocks (the top one pins on a phone); both wear it.
    head = css[css.index(".q-chat-head__top,\n.q-chat-head__rest {") :]
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
    # m-25027374: both channels' reply box; its controls are ≥ 44 px by `.q-reply-box`
    assert ".q-chat-thread .q-chat-scroll .rt-Button" in css
    assert ".q-reply-box .rt-BaseButton" in css
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


def test_the_header_window_line_once_closed() -> None:
    """WhatsApp's header says what is left (an approved message, by WhatsApp) — its
    composer callout says it too, until the composer story removes that duplicate;
    Instagram's header line says nothing — its pill and its composer already do."""
    from .conversations_vm import build_thread_row as ig_build
    from .test_conversations_vm import NOW as IG_NOW
    from .test_conversations_vm import ZONE as IG_ZONE
    from .test_conversations_vm import _thread as ig_thread
    from .test_conversations_vm import _view as ig_view
    from .test_whatsapp_chats import _thread as wa_thread
    from .whatsapp_chats_vm import build_thread_row as wa_build

    closed = WindowView(open=False, closes_at=None)
    wa = wa_build(wa_thread(window=closed), now=NOW, zone=ZONE)
    assert (wa.window_line, wa.window_line_tone) == (WINDOW_CLOSED_LINE, "neutral")
    assert WINDOW_CLOSED_LINE.endswith("aprobado por WhatsApp")
    old = ig_thread(inbound=IG_NOW - timedelta(days=2), outbound=None)
    ig = ig_build(ig_view(old), None, now=IG_NOW, zone=IG_ZONE)
    # m-25027374: Instagram's closed window is said in the header (no box below it)
    from .chat_thread_vm import INSTAGRAM_WINDOW_CLOSED_LINE

    assert not ig.window_open and ig.window_line == INSTAGRAM_WINDOW_CLOSED_LINE
    # no message of the person left (m-25018661): no window to state either
    gone = ig_thread(inbound=None, outbound=IG_NOW - timedelta(hours=1))
    assert ig_build(ig_view(gone), None, now=IG_NOW, zone=IG_ZONE).window_line == ""


# --- the business's zone reaches a chat opened by its address ------------------------------


async def test_the_first_chat_reads_the_zone_and_draws_in_it(gw, monkeypatch) -> None:  # noqa: ANN001, F811
    """Seen in the browser (m-25027371): a chat opened from «Por responder» drew the UTC
    clock until the business's zone was known. m-25029799: no number list reads it any
    more — the first conversation read does, before it draws: bubbles, separators, the
    order and the payment lines, and the header's row (`thread_row`) from the chat."""
    from types import SimpleNamespace

    from qualify_api.whatsapp.orders import OrderLine, OrderSummary

    from .test_whatsapp_chats import _message, _thread
    from .test_whatsapp_chats_payments import CONN, THREAD, _status

    noon = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    at = datetime(2026, 11, 14, 3, 30, tzinfo=UTC)  # 2026-11-13 22:30 in Bogotá
    reads: list[str] = []

    def zone(_tenant: object) -> str:
        reads.append("zone")
        return "America/Bogota"

    order = OrderSummary(
        lines=(OrderLine(product_id="p", name="Shawarma", qty=1),),
        total=Decimal("25000"),
        currency="COP",
        confirmed_at=at,
    )
    conv = SimpleNamespace(
        summary=_thread(id=UUID(THREAD), contact_name="Laura Gómez"),
        messages=[_message(posted_at=at)],
        has_more=False,
        unsent=[],
        order=order,
        previous_orders=(),
        cart_ids=frozenset(),
    )
    monkeypatch.setattr(WhatsAppChatsState, "_now", lambda self: noon)
    monkeypatch.setattr(gw, "timezone", zone, raising=False)
    owner = AgentVM(user_id=str(UUID(int=7)), name="Ana", initials="A")
    monkeypatch.setattr(gw, "agents", lambda t: [owner], raising=False)
    monkeypatch.setattr(gw, "conversation", lambda t, c, th: conv, raising=False)
    monkeypatch.setattr(
        gw,
        "payment_status",
        lambda t, c, th: _status("received", confirmed_at=at + timedelta(minutes=10)),
        raising=False,
    )
    state = WhatsAppChatsState()
    state._connection_id = CONN
    state.open_thread_id = THREAD
    await state._read_conversation(silent=False)
    assert state.messages[0].time_label == "22:30" and state.messages[0].day_label == "Ayer"
    assert "22:30" in state.order.confirmed_label
    assert "22:40" in state.payment.confirmed_line
    assert state.open_thread.title == "Laura Gómez"  # the header's row came with the chat
    await state._read_conversation(silent=True)  # a refresh
    assert reads == ["zone"]  # read once, not on every refresh


def test_a_chat_drawn_before_its_row_states_no_window() -> None:
    """A chat opened by its address draws its header before its first read brings its
    row: no window line, never a false «Pasaron 24 h»."""
    from .conversations_state import ConversationsState

    wa = WhatsAppChatsState()
    wa.open_thread_id = "not-in-rows"
    assert wa.open_thread.window_line == ""
    ig = ConversationsState()
    ig.open_thread_id = "not-in-rows"
    assert ig.open_thread.window_line == ""


async def test_another_business_in_the_same_session_reads_its_own_zone_and_members(
    gw,  # noqa: ANN001, F811
    monkeypatch,  # noqa: ANN001
) -> None:
    """m-25029799 review (C1): a business switch keeps this state, so the zone and the
    members are re-read for the new business — «Asignar» never lists A's members on a
    chat of B, and B's clock is B's own."""
    from types import SimpleNamespace

    from . import whatsapp_chats_state as state_module
    from .test_whatsapp_chats import _message, _thread
    from .test_whatsapp_chats_payments import CONN, THREAD

    business = {"tenant": UUID(int=1)}
    zones = {UUID(int=1): "America/Bogota", UUID(int=2): "America/Caracas"}
    members = {
        UUID(int=1): [AgentVM(user_id="a", name="Ana (A)", initials="A")],
        UUID(int=2): [AgentVM(user_id="b", name="Beto (B)", initials="B")],
    }
    conv = SimpleNamespace(
        summary=_thread(id=UUID(THREAD)),
        messages=[_message()],
        has_more=False,
        unsent=[],
        order=None,
        previous_orders=(),
        cart_ids=frozenset(),
    )

    async def tenant(self: object) -> UUID:
        return business["tenant"]

    monkeypatch.setattr(WhatsAppChatsState, "_tenant", tenant)
    monkeypatch.setattr(gw, "timezone", lambda t: zones[t], raising=False)
    monkeypatch.setattr(gw, "agents", lambda t: members[t], raising=False)
    monkeypatch.setattr(gw, "conversation", lambda t, c, th: conv, raising=False)
    monkeypatch.setattr(gw, "payment_status", lambda t, c, th: None, raising=False)
    assert state_module.gateway() is gw
    state = WhatsAppChatsState()
    state._connection_id = CONN
    state.open_thread_id = THREAD
    await state._read_conversation(silent=False)
    assert [a.name for a in state.agents] == ["Ana (A)"]
    assert state._zone_name == "America/Bogota"
    business["tenant"] = UUID(int=2)  # the owner switched business in this session
    state.conv_loaded_for = ""
    await state._read_conversation(silent=False)
    assert [a.name for a in state.agents] == ["Beto (B)"]
    assert state._zone_name == "America/Caracas"
