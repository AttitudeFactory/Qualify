"""m-25017844 (BU-A2): one chat row for WhatsApp → Chats and Conversaciones (Instagram).

The VM decides everything the row says — the one pill, the waiting dot, the fallback
name, the accessible name — and both pages draw the same `chat_row`.
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import timedelta

from qualify_api.whatsapp.chats import WindowView

from . import chat_row as chat_row_view
from . import conversations_page, whatsapp_tab_chats
from .chat_row_vm import (
    CHANNEL_INSTAGRAM,
    CHANNEL_WHATSAPP,
    PAYMENT_REVIEW_PILL,
    WANTS_TO_BUY_PILL,
    ChatRowVM,
    accessible_name,
    attention_pill,
    build_chat_row,
    minutes_left,
    reply_soon_pill,
    unknown_contact,
)
from .conversations_vm import UNKNOWN_PERSON, ThreadExtra, counterpart_title
from .conversations_vm import as_chat_row as ig_chat_row
from .conversations_vm import build_thread_row as ig_build
from .replies_vm import COMMERCIAL_BADGE
from .test_conversations_vm import NOW as IG_NOW
from .test_conversations_vm import ZONE as IG_ZONE
from .test_conversations_vm import _thread as ig_thread
from .test_conversations_vm import _view as ig_view
from .test_whatsapp_chats import NOW as WA_NOW
from .test_whatsapp_chats import ZONE as WA_ZONE
from .test_whatsapp_chats import _thread as wa_thread
from .whatsapp_chats_vm import OUTBOUND_PREFIX
from .whatsapp_chats_vm import as_chat_row as wa_chat_row
from .whatsapp_chats_vm import build_thread_row as wa_build

# --- the one pill --------------------------------------------------------------------------


def test_payment_beats_the_window_and_the_intent() -> None:
    """Ticket criterion: payment to check + window closing + intent → only «Pago por
    revisar»."""
    assert attention_pill(payment_review=True, reply_within_minutes=12, wants_to_buy=True) == (
        "Pago por revisar",
        "warn",
    )
    row = build_chat_row(
        thread_id="t",
        channel=CHANNEL_WHATSAPP,
        title="Laura",
        second_line="+573001234567",
        preview="Ya te pagué",
        time_label="ahora",
        waiting=True,
        initials="L",
        payment_review=True,
        reply_within_minutes=12,
        wants_to_buy=True,
    )
    assert (row.pill_label, row.pill_tone) == (PAYMENT_REVIEW_PILL, "warn")


def test_the_window_beats_the_intent_and_nothing_means_no_pill() -> None:
    assert attention_pill(payment_review=False, reply_within_minutes=12, wants_to_buy=True) == (
        "Responde en 12 min",
        "warn",
    )
    assert attention_pill(payment_review=False, reply_within_minutes=0, wants_to_buy=True) == (
        "Quiere comprar",
        "info",
    )
    assert attention_pill(payment_review=False, reply_within_minutes=0, wants_to_buy=False) == (
        "",
        "neutral",
    )
    assert WANTS_TO_BUY_PILL == COMMERCIAL_BADGE  # the reply drafts' own words
    assert reply_soon_pill(0) == "Responde en 1 min"


def test_minutes_left_only_under_an_hour() -> None:
    now = WA_NOW
    assert minutes_left(True, now + timedelta(minutes=41, seconds=10), now) == 42
    assert minutes_left(True, now + timedelta(seconds=5), now) == 1
    assert minutes_left(True, now + timedelta(hours=1), now) == 0
    assert minutes_left(True, now - timedelta(minutes=1), now) == 0
    assert minutes_left(False, now + timedelta(minutes=5), now) == 0
    assert minutes_left(True, None, now) == 0


# --- names -----------------------------------------------------------------------------------


def test_the_fallback_names_the_channel() -> None:
    """m-25017852: nothing known → «Cliente de Instagram» (was «Persona sin nombre»);
    only the handle known → «@usuario», in the row and in the header (same title)."""
    assert unknown_contact(CHANNEL_INSTAGRAM) == "Cliente de Instagram"
    assert unknown_contact(CHANNEL_WHATSAPP) == "Cliente de WhatsApp"
    assert UNKNOWN_PERSON == "Cliente de Instagram"
    assert counterpart_title("", "17841400000123456") == "Cliente de Instagram"
    nobody = ig_chat_row(ig_build(ig_view(ig_thread()), None, now=IG_NOW, zone=IG_ZONE))
    assert nobody.title == "Cliente de Instagram" and nobody.second_line == ""
    handle_only = dataclasses.replace(ig_thread(), counterpart_username="yesii_roa")
    row = ig_build(ig_view(handle_only), None, now=IG_NOW, zone=IG_ZONE)
    assert row.title == "@yesii_roa"
    shared = ig_chat_row(row)
    assert shared.title == "@yesii_roa" and shared.second_line == ""
    assert build_chat_row(
        thread_id="t",
        channel=CHANNEL_WHATSAPP,
        title="  ",
        second_line="",
        preview="",
        time_label="",
        waiting=False,
        initials="",
    ).title == ("Cliente de WhatsApp")


def test_the_accessible_name_always_says_the_channel() -> None:
    assert accessible_name("Ana", CHANNEL_WHATSAPP, waiting=True, pill="Pago por revisar") == (
        "Ana, por WhatsApp, sin responder, Pago por revisar"
    )
    assert accessible_name("@ana", CHANNEL_INSTAGRAM, waiting=False, pill="") == (
        "@ana, por Instagram"
    )


# --- WhatsApp → shared row ------------------------------------------------------------------


def test_whatsapp_row_in_the_shared_shape() -> None:
    row = wa_chat_row(wa_build(wa_thread(), now=WA_NOW, zone=WA_ZONE))
    assert isinstance(row, ChatRowVM)
    assert row.channel == CHANNEL_WHATSAPP
    assert (row.title, row.second_line, row.initials) == ("Laura Gómez", "+573001234567", "LG")
    assert row.preview == "¿Tienen domicilio?" and row.time_label == "hace 5 min"
    assert row.waiting  # two unread → the dot
    assert row.pill_label == ""  # window comfortably open, no payment: no pill
    assert row.aria_label == "Laura Gómez, por WhatsApp, sin responder"


def test_whatsapp_row_drops_mode_and_closed_and_keeps_one_pill() -> None:
    closing = WindowView(open=True, closes_at=WA_NOW + timedelta(minutes=30))
    vm = wa_build(
        wa_thread(
            contact_name=None,
            unread_count=0,
            status="closed",
            automation_paused=True,
            last_message_direction="outbound",
            last_message_preview="Ya va en camino",
            window=closing,
        ),
        now=WA_NOW,
        zone=WA_ZONE,
    )
    row = wa_chat_row(vm)
    assert (row.title, row.second_line, row.initials) == ("+573001234567", "", "7")
    assert row.preview == OUTBOUND_PREFIX + "Ya va en camino"
    assert not row.waiting
    assert (row.pill_label, row.pill_tone) == ("Responde en 30 min", "warn")
    paid = wa_chat_row(dataclasses.replace(vm, payment_review=True, payment_label="x"))
    assert paid.pill_label == PAYMENT_REVIEW_PILL  # payment beats the window
    for gone in ("Cerrado", "Responde el menú", "Respondes tú"):
        assert gone not in (row.pill_label, row.aria_label)


def test_whatsapp_assigned_agent_stays_on_the_row() -> None:
    vm = dataclasses.replace(
        wa_build(wa_thread(), now=WA_NOW, zone=WA_ZONE), agent_initials="YR", agent_name="Yesika"
    )
    row = wa_chat_row(vm)
    assert (row.agent_initials, row.agent_name) == ("YR", "Yesika")


# --- Instagram → shared row -----------------------------------------------------------------


def test_instagram_row_in_the_shared_shape() -> None:
    thread = dataclasses.replace(
        ig_thread(),
        counterpart_name="Yesika Roa",
        counterpart_username="yesii_roa",
        counterpart_avatar_url="https://cdn/pic.jpg",
    )
    vm = ig_build(
        ig_view(thread),
        ThreadExtra(preview="claro", preview_direction="outbound", preview_media_type=None),
        now=IG_NOW,
        zone=IG_ZONE,
        fresh=True,
    )
    row = ig_chat_row(vm)
    assert row.channel == CHANNEL_INSTAGRAM
    assert (row.title, row.second_line, row.initials) == ("Yesika Roa", "@yesii_roa", "YR")
    assert row.avatar_url == "https://cdn/pic.jpg" and row.fresh
    assert row.preview == "Tú: claro"
    assert row.pill_label == ""  # «Pendiente» / «Leída» / «Respondida» left the row


def test_instagram_waiting_dot_and_window_pill() -> None:
    thread = ig_thread(inbound=IG_NOW - timedelta(hours=23, minutes=20))
    vm = ig_build(ig_view(thread), ThreadExtra(preview="hola"), now=IG_NOW, zone=IG_ZONE)
    row = ig_chat_row(vm)
    assert vm.attention == "pending" and row.waiting
    assert (row.pill_label, row.pill_tone) == ("Responde en 40 min", "warn")
    read = ig_thread(inbound=IG_NOW - timedelta(hours=2), read=IG_NOW - timedelta(hours=1))
    assert not ig_chat_row(ig_build(ig_view(read), None, now=IG_NOW, zone=IG_ZONE)).waiting


def test_instagram_media_preview_keeps_its_icon() -> None:
    vm = ig_build(
        ig_view(ig_thread()), ThreadExtra(preview_media_type="image"), now=IG_NOW, zone=IG_ZONE
    )
    row = ig_chat_row(vm)
    assert (row.preview, row.preview_icon) == ("Foto", "image")


# --- both pages draw the same row -----------------------------------------------------------


def test_both_lists_render_the_shared_row() -> None:
    for page in (whatsapp_tab_chats, conversations_page):
        source = inspect.getsource(page)
        assert "rx.foreach(S.visible_chat_rows, _thread_row)" in source
        assert "return chat_row(" in inspect.getsource(page._thread_row)
        assert "rx.foreach(S.visible_rows, _thread_row)" not in source


def test_the_rendered_row_has_glyph_dot_one_pill_line_and_a_44px_target() -> None:
    rendered = str(whatsapp_tab_chats.chats_tab().render()) + str(
        conversations_page.conversations_index().render()
    )
    assert "visible_chat_rows" in rendered
    view = inspect.getsource(chat_row_view)
    for needle in (
        "q-chat-channel--whatsapp",
        "q-chat-channel--instagram",
        "q-conv-unread",
        "min_height=_TAP_MIN",
        "aria_label=row.aria_label",
    ):
        assert needle in view
    assert chat_row_view._TAP_MIN == "2.75rem"
    # No «Cerrado», no mode pill, no wrapping second line of labels on the row.
    assert '"Cerrado"' not in view and "flex_wrap" not in view
    assert 'color="white"' not in view


def test_the_row_paints_with_tokens_and_stops_moving_on_request() -> None:
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify-inbox.css").read_text()
    start = css.index(".q-conv-channel.q-chat-channel--whatsapp")
    block = css[start : css.index(".q-conv-avatar-wrap--lg .q-conv-channel", start)]
    assert "var(--green-9)" in block and "var(--pink-9)" in block
    assert "hsl(" not in block and "white" not in block and "#" not in block
    reduced = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert ".q-conv-row--fresh" in reduced and ".q-conv-unread" in reduced
