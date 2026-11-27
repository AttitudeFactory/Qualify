"""The «+» steps both chats share (m-25143229): «Formas de pago» and «Cómo llegar».

Extracted from `whatsapp_tab_chats.py` so WhatsApp and Instagram draw the SAME step from
the same code — a composition of design-system pieces (`choice_card`, `media_thumb`,
`chat_bubble`, `empty_state`, `callout`, `skeleton_rows`), not a new component.

Each function takes the screen's state class `S`, which must carry the picker's names:
`pick_loading`, `pick_error`, `retry_pick_list`, `pick_selected`, and per step
`pick_payments` / `choose_payment` / `payments_change_href` or `pick_directions` /
`pick_profile_href`. WhatsApp passes `WhatsAppChatsState`, Instagram
`InstagramPickState` (`conversations_pick_state.py`); the compiled page of WhatsApp is
the same as before the extraction.
"""

from __future__ import annotations

from typing import Any

import reflex as rx

from .chat_thread import TAP_MIN
from .ui import (
    callout,
    chat_bubble,
    choice_card,
    empty_state,
    media_thumb,
    skeleton_rows,
)
from .ui import tokens as T
from .whatsapp_chats_vm import (
    DIRECTIONS_COMPLETE,
    DIRECTIONS_EMPTY,
    DIRECTIONS_NO_POINT,
    DIRECTIONS_PUT_ON_MAP,
    PAYMENTS_ADD,
    PAYMENTS_EMPTY_TEXT,
    PAYMENTS_EMPTY_TITLE,
    RETRY_LABEL,
    PaymentCardVM,
)


def link_button(label: str, icon: str, href: str | rx.Var[str]) -> rx.Component:
    return rx.link(
        rx.button(
            rx.icon(icon, size=T.ICON_SM),
            label,
            variant="soft",
            size="3",
            min_height=TAP_MIN,
            width="100%",
        ),
        href=href,
        width=rx.breakpoints(initial="100%", sm="auto"),
    )


def pick_grid_skeleton() -> rx.Component:
    return rx.grid(
        *[skeleton_rows(1, height="10rem", radius=T.RADIUS_CARD) for _ in range(4)],
        columns="2",
        spacing="2",
        width="100%",
    )


def pick_load_error(S: Any) -> rx.Component:  # noqa: N803 — the screen's state class
    return rx.vstack(
        callout(S.pick_error, "error"),
        rx.button(
            rx.icon("refresh-cw", size=T.ICON_SM),
            RETRY_LABEL,
            on_click=S.retry_pick_list,
            variant="soft",
            size="3",
            min_height=TAP_MIN,
            **T.tone_scheme("neutral"),
        ),
        spacing="2",
        width="100%",
    )


def pick_list(S: Any, body: rx.Component) -> rx.Component:  # noqa: N803
    """Loading (skeleton) → error («Reintentar») → the step's body."""
    return rx.cond(
        S.pick_loading,
        pick_grid_skeleton(),
        rx.cond(S.pick_error != "", pick_load_error(S), body),
    )


# --- «Formas de pago» ------------------------------------------------------------------


def payment_card(S: Any, card_vm: PaymentCardVM) -> rx.Component:  # noqa: N803
    return choice_card(
        rx.hstack(
            media_thumb(
                card_vm.thumb_url,
                size="48px",
                icon="banknote",
                alt=card_vm.alt,
                has=card_vm.thumb_url != "",
            ),
            rx.vstack(
                rx.text(card_vm.name, weight="medium", size="2"),
                rx.cond(
                    card_vm.currency_label != "",
                    rx.text(card_vm.currency_label, size="1", color=T.TEXT_MUTED),
                ),
                rx.text(card_vm.updated_label, size="1", color=T.TEXT_MUTED),
                spacing="0",
                align_items="start",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=S.pick_selected == card_vm.id,
        on_select=S.choose_payment(card_vm.id),
        padding="0.5rem 0.75rem",
        width="100%",
        min_height=TAP_MIN,
    )


def pick_payments(S: Any) -> rx.Component:  # noqa: N803
    """«¿Cuál forma de pago?»: the business's active methods, or the empty state that
    leads to Formas de pago."""
    return pick_list(
        S,
        rx.cond(
            S.pick_payments.length() > 0,
            rx.vstack(
                rx.foreach(S.pick_payments, lambda card: payment_card(S, card)),
                spacing="2",
                width="100%",
                role="radiogroup",
            ),
            empty_state(
                "wallet",
                PAYMENTS_EMPTY_TITLE,
                PAYMENTS_EMPTY_TEXT,
                link_button(PAYMENTS_ADD, "plus", S.payments_change_href),
            ),
        ),
    )


# --- «Cómo llegar» ---------------------------------------------------------------------


def directions_bubble(S: Any) -> rx.Component:  # noqa: N803
    d = S.pick_directions
    return chat_bubble(
        rx.cond(
            d.has_point,
            rx.hstack(
                rx.center(
                    rx.icon("map-pin", size=T.ICON_MD, aria_hidden="true"),
                    width="2.75rem",
                    height="2.75rem",
                    min_width="2.75rem",
                    border_radius=T.RADIUS_CONTROL,
                    **T.tone_scheme("info"),
                ),
                rx.vstack(
                    rx.cond(d.name != "", rx.text(d.name, size="2", weight="bold")),
                    rx.cond(d.address != "", rx.text(d.address, size="2")),
                    spacing="0",
                    align_items="start",
                ),
                spacing="3",
                align="center",
            ),
            rx.text(d.text, size="2", white_space="pre-wrap", word_break="break-word"),
        ),
        direction="out",
        max_width="20rem",
        align_self="flex-end",
    )


def pick_directions(S: Any, *, point_hint: bool = True) -> rx.Component:  # noqa: N803
    """«Cómo llegar»: one step — what goes out (a map pin, or the address with a maps
    link) or the empty state that leads to where the address is written.

    `point_hint`: «Si pones tu local en el mapa, le llega el mapa con la ruta.» — only
    where a point changes what arrives (WhatsApp's pin). Instagram gets a text with a
    link either way, so it does not draw it."""
    d = S.pick_directions
    empty_title, empty_line = DIRECTIONS_EMPTY
    hint = (
        rx.cond(
            ~d.has_point,
            rx.vstack(
                callout(DIRECTIONS_NO_POINT, "info"),
                link_button(DIRECTIONS_PUT_ON_MAP, "map-pin", S.pick_profile_href),
                spacing="2",
                width="100%",
            ),
        )
        if point_hint
        else rx.fragment()
    )
    return pick_list(
        S,
        rx.cond(
            ~d.present,
            skeleton_rows(rows=2, height="3rem"),
            rx.cond(
                d.empty,
                empty_state(
                    "map-pin",
                    empty_title,
                    empty_line,
                    link_button(DIRECTIONS_COMPLETE, "pencil", S.pick_profile_href),
                ),
                rx.vstack(
                    directions_bubble(S),
                    hint,
                    spacing="3",
                    width="100%",
                ),
            ),
        ),
    )
