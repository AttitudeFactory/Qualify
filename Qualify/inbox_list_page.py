"""The single chat list of «Por responder» › «Mensajes» (m-25017859, BU-A3).

The left pane of the tab (`conversations_page.messages_tab` puts the open chat of
either channel at its right, m-25029798): the channel filter (only with chats on two or
more channels), the number choice (only with two or more WhatsApp numbers, m-25029799:
WhatsApp's own list is gone), the chips, the «… ya no se pueden responder aquí» notice,
the shared rows
(`chat_row.chat_row`) and «Ver más». Design-system pieces only (buttons as chips like the
screens before it, `callout`, `empty_state`, `skeleton_rows`); every count and word comes
from `inbox_list_vm` through `InboxListState`.
"""

from __future__ import annotations

import reflex as rx

from .chat_row import chat_row
from .chat_row_vm import CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP, ChatRowVM
from .conversations_state import ConversationsState
from .inbox_list_state import LIST_DOM_ID, InboxListState
from .inbox_list_vm import (
    CHANNELS_ARIA,
    EMPTY_BACK,
    EMPTY_QR_ACTION,
    EMPTY_QR_HREF,
    EMPTY_QR_LABEL,
    EXPLAINER_ACTION,
    EXPLAINER_TEXT,
    FILTERS_ARIA,
    MORE_LABEL,
    NOTHING_CONNECTED_ACTION,
    NOTHING_CONNECTED_BODY,
    NOTHING_CONNECTED_HREF,
    NOTHING_CONNECTED_TITLE,
    NOTICE_ACTION,
    NOTICE_DISMISS,
    NUMBERS_ARIA,
    ChipVM,
    NumberVM,
)
from .next_steps_vm import CREATE_LABEL, CREATE_ROUTE
from .ui import callout, card, empty_state, skeleton_rows
from .ui import tokens as T
from .whatsapp_chats_state import WhatsAppChatsState

L = InboxListState

#: The chips' group, where «Entendido» hands the focus (`inbox_list_state`).
CHIPS_CLASS = "q-inbox-chips"

#: Same cadence as both channels' screens: 15 s, client-side, gone with the tab.
_REFRESH_MS = 15_000
#: N12: every chip a thumb hits is at least 44 px tall.
_TARGET = "44px"


def heartbeat() -> rx.Component:
    return rx.moment(interval=_REFRESH_MS, on_change=lambda _tick: L.refresh, display="none")


def _chip(chip: ChipVM, on_pick: rx.event.EventHandler) -> rx.Component:
    return rx.button(
        chip.label,
        on_click=on_pick(chip.key),
        variant=rx.cond(chip.pressed, "solid", "soft"),
        size="2",
        min_height=_TARGET,
        type="button",
        aria_pressed=rx.cond(chip.pressed, "true", "false"),
        class_name="q-conv-filter",
        **T.tone_scheme("neutral"),
    )


def _channel_filter() -> rx.Component:
    """[Todos] [Instagram] [WhatsApp], only with chats on two or more channels."""
    return rx.cond(
        L.show_channels,
        rx.flex(
            rx.foreach(L.channel_options, lambda c: _chip(c, L.set_channel)),
            wrap="wrap",
            gap="0.4rem",
            width="100%",
            class_name="q-conv-filters",
            role="group",
            aria_label=CHANNELS_ARIA,
        ),
        rx.fragment(),
    )


def _number_option(number: NumberVM) -> rx.Component:
    return rx.select.item(number.label, value=number.connection_id)


def _number_filter() -> rx.Component:
    """m-25029799: WhatsApp's «Elige un número», only for a business with two or more
    numbers and not on the Instagram view. One line — the same select `/whatsapp`'s
    header uses (UX review: chips pushed the chats off a phone's screen) — the column's
    width, 44 px tall; «Todos los números» first."""
    return rx.cond(
        L.show_numbers,
        rx.select.root(
            rx.select.trigger(
                width="100%", min_height=_TARGET, aria_label=NUMBERS_ARIA, title=NUMBERS_ARIA
            ),
            rx.select.content(rx.foreach(L.number_choices, _number_option)),
            value=L.number_value,
            on_change=L.set_number,
        ),
        rx.fragment(),
    )


def _filters() -> rx.Component:
    """Chips that wrap at 360 px instead of a segmented control that overflows."""
    return rx.flex(
        rx.foreach(L.chips, lambda c: _chip(c, L.set_filter)),
        wrap="wrap",
        gap="0.4rem",
        width="100%",
        class_name=f"q-conv-filters {CHIPS_CLASS}",
        role="group",
        aria_label=FILTERS_ARIA,
    )


def _explainer() -> rx.Component:
    """The one-time explanation (founder, 2026-11-14; ends `EXPLAINER_UNTIL`): the
    design system's info `callout` (role «status», announced politely), compact — one
    text, one 44 px «Entendido» that wraps under it at 360 px."""
    return rx.cond(
        L.explainer_open,
        callout(
            rx.flex(
                rx.text(EXPLAINER_TEXT, size="2", flex="1", min_width="12rem"),
                rx.button(
                    EXPLAINER_ACTION,
                    on_click=L.dismiss_explainer,
                    variant="soft",
                    size="2",
                    min_height=_TARGET,
                    type="button",
                    **T.tone_scheme("info"),
                ),
                align="center",
                wrap="wrap",
                gap="0.5rem",
                width="100%",
            ),
            "info",
            aria_live="polite",
            size="1",
        ),
        rx.fragment(),
    )


def _notice() -> rx.Component:
    """«N chats de Instagram ya no se pueden responder aquí · Ver»: one line inside «Por
    responder», not part of its number; «Ocultar este aviso» until the number grows."""
    return rx.cond(
        L.notice_visible,
        card(
            rx.flex(
                rx.icon("clock-alert", size=T.ICON_SM, color=T.TEXT_MUTED, flex_shrink="0"),
                rx.text(L.notice_label, size="2", flex="1", min_width="0"),
                rx.button(
                    NOTICE_ACTION,
                    on_click=L.open_expired,
                    variant="soft",
                    size="2",
                    min_height=_TARGET,
                    type="button",
                    aria_label=L.notice_label + ": ver esos chats",
                    **T.tone_scheme("accent"),
                ),
                rx.icon_button(
                    rx.icon("x", size=T.ICON_SM),
                    on_click=L.dismiss_notice,
                    variant="ghost",
                    size="2",
                    min_height=_TARGET,
                    min_width=_TARGET,
                    type="button",
                    aria_label=NOTICE_DISMISS,
                    title=NOTICE_DISMISS,
                    **T.tone_scheme("neutral"),
                ),
                align="center",
                gap="0.5rem",
                width="100%",
            ),
            padding="0.5rem 0.75rem",
            role="status",
        ),
        rx.fragment(),
    )


def _chat_open() -> rx.Var[bool]:
    """A chat of either channel is open beside this list."""
    return ConversationsState.has_open_thread | WhatsAppChatsState.has_open_thread


def _row(row: ChatRowVM) -> rx.Component:
    """m-25029798: a row of either channel opens its chat beside this list; the open
    one is marked whatever its channel."""
    return chat_row(
        row,
        is_open=(
            (row.channel == CHANNEL_INSTAGRAM)
            & (row.thread_id == ConversationsState.open_thread_id)
        )
        | (
            (row.channel == CHANNEL_WHATSAPP) & (row.thread_id == WhatsAppChatsState.open_thread_id)
        ),
        on_open=L.open_row(row.thread_id),
    )


def _create_link() -> rx.Component:
    return rx.link(
        rx.button(rx.icon("wand-sparkles", size=T.ICON_SM), CREATE_LABEL, size="3"),
        href=CREATE_ROUTE,
    )


def _qr_link() -> rx.Component:
    """m-25029799 (UX review): an empty WhatsApp view — a QR code is how customers start
    writing (`/whatsapp` › Tu número › Códigos QR)."""
    return rx.link(
        rx.button(rx.icon("qr-code", size=T.ICON_SM), EMPTY_QR_LABEL, size="3"),
        href=EMPTY_QR_HREF,
    )


def _empty() -> rx.Component:
    empty = L.empty
    return rx.match(
        empty.action,
        ("create", empty_state("circle-check", empty.title, empty.body, action=_create_link())),
        (EMPTY_QR_ACTION, empty_state("circle-check", empty.title, empty.body, action=_qr_link())),
        rx.vstack(
            rx.text(empty.body, size="2", color=T.TEXT_MUTED),
            rx.button(
                EMPTY_BACK,
                on_click=L.show_awaiting,
                variant="soft",
                size="2",
                min_height=_TARGET,
                type="button",
                **T.tone_scheme("neutral"),
            ),
            spacing="2",
            padding="1rem 0.25rem",
            align_items="start",
        ),
    )


def _nothing_connected() -> rx.Component:
    return empty_state(
        "messages-square",
        NOTHING_CONNECTED_TITLE,
        NOTHING_CONNECTED_BODY,
        action=rx.link(
            rx.button(rx.icon("link", size=T.ICON_SM), NOTHING_CONNECTED_ACTION, size="3"),
            href=NOTHING_CONNECTED_HREF,
        ),
    )


def _more() -> rx.Component:
    return rx.vstack(
        rx.cond(L.more_error != "", callout(L.more_error, "error"), rx.fragment()),
        rx.cond(
            L.has_more,
            rx.button(
                MORE_LABEL,
                on_click=L.load_more,
                loading=L.loading_more,
                variant="soft",
                size="2",
                min_height=_TARGET,
                width="100%",
                type="button",
                **T.tone_scheme("neutral"),
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
    )


def _body() -> rx.Component:
    return rx.cond(
        L.error != "",
        rx.vstack(
            callout(L.error, "error"),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                "Reintentar",
                on_click=L.load,
                variant="soft",
                size="2",
                min_height=_TARGET,
                **T.tone_scheme("neutral"),
            ),
            width="100%",
            spacing="3",
        ),
        rx.cond(
            L.show_skeleton,
            skeleton_rows(6, height="4.75rem", radius=T.RADIUS_CARD),
            rx.cond(
                L.nothing_connected,
                _nothing_connected(),
                rx.cond(
                    L.is_empty,
                    _empty(),
                    rx.vstack(
                        rx.vstack(
                            rx.foreach(L.rows, _row),
                            spacing="2",
                            width="100%",
                            id=LIST_DOM_ID,
                            class_name="q-wa-scroll q-wa-scroll--list q-conv-list",
                        ),
                        _more(),
                        spacing="2",
                        width="100%",
                    ),
                ),
            ),
        ),
    )


def inbox_list_pane() -> rx.Component:
    """The list column of `.q-wa-chats` (hidden on a phone while a chat is open). The
    chips sit right above the first row; the expired notice goes BELOW the rows, so on
    a phone the first chat is not pushed under the fold (UX review of m-25017859)."""
    return rx.vstack(
        heartbeat(),
        # U4 (UX review of m-25029798): with a chat open, the explanation steps aside
        # so the list and the chat move up; it comes back when the chat closes.
        rx.cond(_chat_open(), rx.fragment(), _explainer()),
        # The chips paint with the first loaded list, together with the explanation
        # above them, so neither pushes the other once it appears.
        rx.cond(
            L.counts_loaded,
            rx.vstack(_channel_filter(), _number_filter(), _filters(), spacing="3", width="100%"),
        ),
        _body(),
        _notice(),
        spacing="3",
        width="100%",
        class_name="q-wa-chats__list",
    )
