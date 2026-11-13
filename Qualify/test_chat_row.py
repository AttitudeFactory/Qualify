"""m-25017844 (BU-A2): one chat row for WhatsApp → Chats and Conversaciones (Instagram).

The VM decides everything the row says — the one pill, the waiting dot, the initials,
the fallback name, the accessible name — and both pages draw the same `chat_row`.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import timedelta
from pathlib import Path

import reflex as rx
from qualify_api.whatsapp.chats import WindowView
from qualify_api.whatsapp.payment_status import STATUS_LABELS

from . import inbox_list_page, whatsapp_tab_chats
from .chat_row import ROW_KEY_HANDLER, chat_row
from .chat_row_vm import (
    AWAITING_PAYMENT_PILL,
    CHANNEL_INSTAGRAM,
    CHANNEL_WHATSAPP,
    EXPIRED_PILL,
    PAYMENT_REVIEW_PILL,
    REPLY_SOON_TEMPLATE,
    WANTS_TO_BUY_PILL,
    ChatRowVM,
    accessible_name,
    attention_pill,
    build_chat_row,
    letter_initials,
    minutes_left,
    reply_soon_pill,
    unknown_contact,
)
from .conversations_vm import UNKNOWN_PERSON, counterpart_title, window_words
from .inbox_list_vm import as_chat_row as inbox_chat_row
from .replies_vm import COMMERCIAL_BADGE
from .test_inbox_list import NOW as IG_NOW
from .test_inbox_list import ZONE as IG_ZONE
from .test_inbox_list import ig_row
from .test_whatsapp_chats import NOW as WA_NOW
from .test_whatsapp_chats import ZONE as WA_ZONE
from .test_whatsapp_chats import _thread as wa_thread
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import AWAITING_FILTER_LABEL, FILTER_UNREAD, OUTBOUND_PREFIX, window_pill
from .whatsapp_chats_vm import FILTERS as WA_FILTERS
from .whatsapp_chats_vm import as_chat_row as wa_chat_row
from .whatsapp_chats_vm import build_thread_row as wa_build
from .whatsapp_chats_vm import filter_threads as wa_filter

_CSS = Path(__file__).resolve().parent.parent / "assets" / "qualify-inbox.css"


def _row(**overrides: object) -> ChatRowVM:
    values: dict[str, object] = {
        "thread_id": "t",
        "channel": CHANNEL_WHATSAPP,
        "title": "Laura",
        "preview": "Ya te pagué",
        "time_label": "ahora",
        "waiting": True,
        "initials_from": "Laura",
    }
    values.update(overrides)
    return build_chat_row(**values)  # type: ignore[arg-type]


def _rendered(row: ChatRowVM, *, is_open: bool = False) -> str:
    return str(
        chat_row(
            rx.Var.create(row),  # type: ignore[arg-type]
            is_open=rx.Var.create(is_open),
            on_open=rx.console_log("open"),
        )
    )


def _css_block(selector_text: str) -> str:
    """The `@media`/rule block that contains `selector_text`, braces matched."""
    css = _CSS.read_text()
    at = css.index(selector_text)
    start = css.rfind("@media", 0, at)
    depth, i = 0, css.index("{", start)
    for i in range(css.index("{", start), len(css)):
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        if depth == 0:
            break
    return css[start : i + 1]


# --- the one pill --------------------------------------------------------------------------


def test_payment_beats_the_window_and_the_intent() -> None:
    """Ticket criterion: payment to check + window closing + intent → only «Pago por
    revisar»."""
    row = _row(
        payment_review=True, payment_awaiting=True, reply_within_minutes=12, wants_to_buy=True
    )
    assert (row.pill_label, row.pill_tone) == (PAYMENT_REVIEW_PILL, "warn")


def test_the_priority_order_of_the_one_pill() -> None:
    """«Pago por revisar» › «Respóndele desde la app de Instagram» › «Quiere comprar» ›
    «Quedan N min para responder» › «Esperando el pago»."""

    def pill(**kw: object) -> tuple[str, str]:
        base = {"payment_review": False, "reply_within_minutes": 0}
        return attention_pill(**{**base, **kw})  # type: ignore[arg-type]

    assert pill(wants_to_buy=True, payment_awaiting=True, reply_within_minutes=5) == (
        "Quiere comprar",
        "info",
    )
    # Awaiting payment AND the window about to close → the window pill wins.
    assert pill(payment_awaiting=True, reply_within_minutes=5) == (
        "Quedan 5 min para responder",
        "warn",
    )
    assert pill(payment_awaiting=True) == ("Esperando el pago", "neutral")
    assert pill(reply_within_minutes=5) == ("Quedan 5 min para responder", "warn")
    assert pill() == ("", "neutral")
    # m-25017859: expired unanswered — below the payment, above everything else, neutral.
    assert pill(expired=True, wants_to_buy=True) == (EXPIRED_PILL, "neutral")
    assert pill(expired=True, payment_review=True) == (PAYMENT_REVIEW_PILL, "warn")
    # The words are the product's own: the payment states and the reply drafts' badge.
    assert AWAITING_PAYMENT_PILL == STATUS_LABELS["awaiting"]
    assert PAYMENT_REVIEW_PILL == STATUS_LABELS["review"]
    assert WANTS_TO_BUY_PILL == COMMERCIAL_BADGE
    # Founder decision 2026-11-13: «Quedan {N} min para responder».
    assert REPLY_SOON_TEMPLATE.format(minutes=7) == reply_soon_pill(7)
    assert reply_soon_pill(7) == "Quedan 7 min para responder"


def test_the_pills_against_one_line_at_360_px() -> None:
    """At 360 px the row's text column is ~244 px (360 − 2×16 gutter − 2×16 row padding
    − 40 avatar − 12 gap); a size-1 pill (12 px type, ~6.6 px per character + ~20 px of
    dot, gap and padding) fits about 34 characters. Every pill fits but the founder's
    «Respóndele desde la app de Instagram» (36, 2026-11-13): an estimate of ~258 px —
    reported to the coordinator, not shortened. This pins the known lengths."""
    fitting = (reply_soon_pill(59), PAYMENT_REVIEW_PILL, AWAITING_PAYMENT_PILL)
    assert max(len(p) for p in fitting) <= 31
    assert len(EXPIRED_PILL) == 36


def test_minutes_round_down_with_a_floor_of_one() -> None:
    now = WA_NOW
    assert minutes_left(True, now + timedelta(minutes=59, seconds=59), now) == 59
    assert minutes_left(True, now + timedelta(seconds=30), now) == 1
    assert minutes_left(True, now + timedelta(minutes=40), now) == 40
    assert minutes_left(True, now + timedelta(minutes=39, seconds=30), now) == 39
    assert minutes_left(True, now + timedelta(hours=1), now) == 0
    assert minutes_left(True, now - timedelta(minutes=1), now) == 0
    assert minutes_left(False, now + timedelta(minutes=5), now) == 0
    assert minutes_left(True, None, now) == 0


def test_row_and_chat_header_say_the_same_minutes() -> None:
    for left, said in (
        (timedelta(minutes=59, seconds=59), 59),
        (timedelta(seconds=30), 1),
        (timedelta(minutes=40), 40),
        (timedelta(minutes=39, seconds=30), 39),
    ):
        ig = inbox_chat_row(ig_row(window_closes_at=IG_NOW + left), now=IG_NOW, zone=IG_ZONE)
        assert ig is not None
        header, _tone = window_words(True, IG_NOW + left, IG_NOW, IG_ZONE)
        assert ig.pill_label == f"Quedan {said} min para responder"
        assert header.startswith(f"Te quedan {said} min para responder")
        wa_row = wa_chat_row(
            wa_build(
                wa_thread(window=WindowView(open=True, closes_at=WA_NOW + left)),
                now=WA_NOW,
                zone=WA_ZONE,
            )
        )
        wa_header, _ = window_pill(True, WA_NOW + left, WA_NOW, WA_ZONE)
        assert wa_row.pill_label == f"Quedan {said} min para responder"
        expected = (
            "Responde en el próximo minuto" if said == 1 else f"Responde en los próximos {said} min"
        )
        assert wa_header == expected


# --- names and initials ---------------------------------------------------------------------


def test_initials_come_from_letters_only() -> None:
    assert letter_initials("Laura Gómez") == "LG"
    assert letter_initials("🇨🇴 Laura") == "L"
    assert letter_initials("~Juan") == "J"
    assert letter_initials("@yesii_roa") == "YR"
    assert letter_initials("Ángela 😀 Ruiz") == "ÁR"
    assert letter_initials("+573001234567") == ""
    assert letter_initials("😀 🎉") == ""
    assert letter_initials("") == ""


def test_whatsapp_profile_names_never_give_a_symbol_as_initial() -> None:
    def initials(name: str | None) -> str:
        return wa_chat_row(
            wa_build(wa_thread(contact_name=name), now=WA_NOW, zone=WA_ZONE)
        ).initials

    assert initials("🇨🇴 Laura") == "L"
    assert initials("~Juan") == "J"
    assert initials("+573001234567") == ""  # the name IS the number → person icon
    assert initials(None) == ""  # number only → person icon, never its last digit


def test_the_fallback_names_the_channel() -> None:
    """m-25017852: nothing known → «Cliente de Instagram» (was «Persona sin nombre»);
    only the handle known → «@usuario», in the row and in the header (same title)."""
    assert unknown_contact(CHANNEL_INSTAGRAM) == UNKNOWN_PERSON == "Cliente de Instagram"
    assert counterpart_title("", "17841400000123456") == "Cliente de Instagram"
    nobody = inbox_chat_row(ig_row(counterpart_username=None), now=IG_NOW, zone=IG_ZONE)
    assert nobody is not None and nobody.title == "Cliente de Instagram"
    assert nobody.initials == ""  # person icon, not «CI» nor a digit of the id
    shared = inbox_chat_row(ig_row(), now=IG_NOW, zone=IG_ZONE)
    assert shared is not None and shared.title == counterpart_title("yesii_roa", "")
    assert shared.initials == "YR"


def test_a_whatsapp_chat_with_neither_name_nor_number() -> None:
    row = wa_chat_row(wa_build(wa_thread(contact_name=None, wa_id=""), now=WA_NOW, zone=WA_ZONE))
    assert row.title == "Cliente de WhatsApp" and row.initials == ""


def test_the_accessible_name_says_the_channel_and_the_one_rule() -> None:
    """m-25017859: one «Por responder» rule on both channels, so one word for the dot;
    a closed chat says «cerrado» (never only its muted colour)."""
    assert accessible_name("Ana", CHANNEL_WHATSAPP, waiting=True, pill="Pago por revisar") == (
        "Ana, por WhatsApp, por responder, Pago por revisar"
    )
    assert accessible_name("@ana", CHANNEL_INSTAGRAM, waiting=True, pill="") == (
        "@ana, por Instagram, por responder"
    )
    assert accessible_name("Ana", CHANNEL_WHATSAPP, waiting=False, pill="", closed=True) == (
        "Ana, por WhatsApp, cerrado"
    )
    assert accessible_name("@ana", CHANNEL_INSTAGRAM, waiting=False, pill="") == (
        "@ana, por Instagram"
    )


# --- WhatsApp → shared row ------------------------------------------------------------------


def test_whatsapp_row_in_the_shared_shape() -> None:
    row = wa_chat_row(wa_build(wa_thread(), now=WA_NOW, zone=WA_ZONE))
    assert row.channel == CHANNEL_WHATSAPP
    assert (row.title, row.initials) == ("Laura Gómez", "LG")
    # No second line (UX doc §2): the phone is not on the row nor in its accessible name.
    assert not hasattr(row, "second_line") and "+57" not in row.aria_label
    assert row.preview == "¿Tienen domicilio?" and row.time_label == "hace 5 min"
    assert row.waiting  # m-25017859: the rule's verdict → the dot
    assert row.pill_label == ""  # window comfortably open, no payment: no pill
    assert row.aria_label == "Laura Gómez, por WhatsApp, por responder"
    # Read but unanswered still waits; answered (whatever the unread count) does not.
    read = wa_chat_row(wa_build(wa_thread(unread_count=0), now=WA_NOW, zone=WA_ZONE))
    assert read.waiting
    answered = wa_build(wa_thread(unread_count=3, awaiting_reply=False), now=WA_NOW, zone=WA_ZONE)
    assert not wa_chat_row(answered).waiting


def test_whatsapp_row_drops_mode_and_closed_and_keeps_one_pill() -> None:
    closing = WindowView(open=True, closes_at=WA_NOW + timedelta(minutes=30))
    vm = wa_build(
        wa_thread(
            unread_count=0,
            awaiting_reply=False,
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
    assert row.preview == OUTBOUND_PREFIX + "Ya va en camino" and not row.waiting
    assert (row.pill_label, row.pill_tone) == ("Quedan 30 min para responder", "warn")
    assert row.closed  # muted where a chip mixes open and closed chats
    awaiting = wa_chat_row(dataclasses.replace(vm, payment_awaiting=True))
    assert awaiting.pill_label == "Quedan 30 min para responder"  # the closing window wins
    calm = wa_chat_row(dataclasses.replace(vm, payment_awaiting=True, window_minutes=0))
    assert (calm.pill_label, calm.pill_tone) == ("Esperando el pago", "neutral")
    review = wa_chat_row(dataclasses.replace(vm, payment_review=True, payment_awaiting=True))
    assert review.pill_label == PAYMENT_REVIEW_PILL
    for gone in ("Cerrado", "Responde el menú", "Respondes tú"):
        assert gone not in (row.pill_label, row.aria_label)
    assert row.aria_label.endswith(", cerrado, Quedan 30 min para responder")


def test_whatsapp_assigned_agent_stays_on_the_row() -> None:
    vm = dataclasses.replace(
        wa_build(wa_thread(), now=WA_NOW, zone=WA_ZONE), agent_initials="YR", agent_name="Yesika"
    )
    assert (wa_chat_row(vm).agent_initials, wa_chat_row(vm).agent_name) == ("YR", "Yesika")


# --- the states: the chat rows follow the lists ---------------------------------------------


def test_whatsapp_state_chat_rows_follow_filter_and_refresh() -> None:
    state = WhatsAppChatsState()
    rows = [
        wa_build(
            wa_thread(id=f"00000000-0000-0000-0000-00000000000{i}", **kw), now=WA_NOW, zone=WA_ZONE
        )
        for i, kw in enumerate(
            (
                {},
                {"unread_count": 0, "awaiting_reply": False},
                {"status": "closed", "unread_count": 3, "awaiting_reply": False},
            ),
            start=1,
        )
    ]
    rows[1] = dataclasses.replace(rows[1], payment_review=True)
    state.rows = rows
    for key, _label in WA_FILTERS:
        state.filter_key = key
        assert [r.thread_id for r in state.visible_chat_rows] == [
            r.thread_id for r in wa_filter(state.rows, key)
        ]
    # m-25017859: the chip the badge opens lists by the rule, not by the unread count —
    # the closed chat with 3 unread is not there; its label is ONE constant.
    state.filter_key = FILTER_UNREAD
    assert [r.thread_id for r in state.visible_chat_rows] == [rows[0].thread_id]
    assert state.filter_unread_label == f"{AWAITING_FILTER_LABEL} · 1"
    assert AWAITING_FILTER_LABEL == "Por responder"
    state.filter_key = WA_FILTERS[0][0]
    state.rows = rows[:1]  # a refresh
    assert [r.thread_id for r in state.visible_chat_rows] == [rows[0].thread_id]
    assert state.visible_chat_rows[0] == wa_chat_row(rows[0])


def test_whatsapp_window_closed_while_choosing_clears_the_minutes() -> None:
    state = WhatsAppChatsState()
    closing = wa_build(
        wa_thread(window=WindowView(open=True, closes_at=WA_NOW + timedelta(minutes=5))),
        now=WA_NOW,
        zone=WA_ZONE,
    )
    state.rows = [closing]
    assert state.visible_chat_rows[0].pill_label == "Quedan 5 min para responder"
    state._mark_window_closed(closing.thread_id)
    marked = state.rows[0]
    assert (marked.window_open, marked.window_tone, marked.window_minutes) == (
        False,
        "neutral",
        0,
    )
    assert state.visible_chat_rows[0].pill_label == ""


# --- the rendered row -----------------------------------------------------------------------


def test_both_lists_render_the_shared_row() -> None:
    wa = str(whatsapp_tab_chats.chats_tab())
    assert "visible_chat_rows" in wa and "visible_rows" not in wa
    assert ROW_KEY_HANDLER._js_expr in wa  # the shared row, keyboard and all
    single = str(inbox_list_page.inbox_list_pane())
    assert "inbox_list_state" in single and ROW_KEY_HANDLER._js_expr in single
    from . import conversations_page

    assert conversations_page._tone_pill is whatsapp_tab_chats._tone_pill  # one helper


def test_the_rows_are_equally_tall_on_both_channels() -> None:
    """m-25017859: who attends a chat sits on the name line, so a WhatsApp row with a
    team has the same lines as an Instagram row (102 px vs 78 px before); only the one
    pill adds the third line, the same on both channels."""
    import inspect

    from . import chat_row as view

    source = inspect.getsource(view.chat_row)
    name_line = source[source.index("row.title") : source.index("row.time_label")]
    assert "_agent_chip(row)" in name_line
    third = source[source.index("ONE line of labels") :]
    assert "_agent_chip" not in third and 'row.pill_label != ""' in third


def test_the_rendered_row_anatomy() -> None:
    rendered = _rendered(_row(payment_review=True, agent_initials="YR", agent_name="Yesika"))
    assert "q-chat-channel--whatsapp" in rendered and "q-chat-channel--instagram" in rendered
    assert "q-conv-unread" in rendered  # the waiting dot
    assert '["minHeight"] : "2.75rem"' in rendered  # one 44 px target
    assert 'role:"button"' in rendered and "tabIndex:0" in rendered
    assert '"aria-label"' in rendered and '"aria-current"' in rendered
    assert "LucideUserRound" in rendered  # the person icon when there is no letter
    assert "Cerrado" not in rendered and "flexWrap" not in rendered
    assert 'color:"white"' not in rendered


def test_enter_and_space_click_the_row_itself() -> None:
    js = ROW_KEY_HANDLER._js_expr
    assert "e.key === 'Enter'" in js and "e.key === ' '" in js
    assert "e.target === e.currentTarget" in js  # only the row itself, never a child
    assert "!e.repeat" in js  # a held key opens the chat once
    assert "e.preventDefault()" in js and "e.currentTarget.click()" in js
    assert "window." not in js and "document." not in js  # no global handler
    rendered = _rendered(_row())
    assert re.search(r"onKeyDown:\(\(e\) =>", rendered)
    assert "onClick:" in rendered


def test_the_row_paints_with_tokens() -> None:
    css = _CSS.read_text()
    start = css.index(".q-conv-channel.q-chat-channel--whatsapp")
    rules = css[start : css.index(".q-conv-avatar-wrap--lg .q-conv-channel", start)]
    assert "var(--green-9)" in rules and "var(--pink-9)" in rules
    assert "var(--accent-a4)" in rules
    assert "hsl(" not in rules and "white" not in rules and "#" not in rules


def test_the_dot_and_the_pulse_stop_under_reduced_motion() -> None:
    block = _css_block(".q-conv-row--fresh, .q-conv-unread")
    assert block.startswith("@media (prefers-reduced-motion: reduce)")
    rule = block[block.index(".q-conv-msg, .q-conv-row--fresh, .q-conv-unread") :]
    assert "animation: none" in rule[: rule.index("}")]


def test_a_picture_without_letters_keeps_the_avatar_fallback() -> None:
    """Picture + no letters → the Radix avatar over the person icon (an expired picture
    reveals the icon, never a broken image); no picture → the bare icon."""
    from . import chat_row as view

    with_picture = str(view._avatar(rx.Var.create(_row(initials_from="", avatar_url="https://x"))))  # type: ignore[arg-type]
    assert "q-chat-avatar__over" in with_picture
    assert "RadixThemesAvatar" in with_picture and "LucideUserRound" in with_picture
    assert 'fallback:""' in with_picture  # the over-avatar's fallback is empty
    css = _CSS.read_text()
    rule = css[css.index(".q-chat-avatar .q-chat-avatar__over .rt-AvatarRoot") :]
    assert "background: transparent" in rule[: rule.index("}")]
    assert ".q-chat-avatar__over {" in css and "position: absolute" in css
