"""Instagram's «+» panel (m-25143229): the `drawer` its rows open.

The steps are WhatsApp's own (`chat_plus_picks.py`: «¿Cuál forma de pago?», «Así le
llega tu ubicación»); only the review of a payment method differs, because Instagram
cannot put a text under an image: the QR arrives as one message and its text as the
next, so the review shows the two bubbles exactly as they will arrive. Nothing leaves
without «Enviar». A composition of design-system pieces, no new component.
"""

from __future__ import annotations

import reflex as rx

from .chat_plus_picks import link_button, pick_directions, pick_list, pick_payments
from .chat_thread import TAP_MIN
from .conversations_pick_state import InstagramPickState as P
from .conversations_state import ConversationsState
from .ui import callout, chat_bubble, drawer, media_thumb, skeleton_rows
from .ui import tokens as T
from .ui.steps import step_progress
from .whatsapp_chats_vm import (
    PAYMENTS_CHANGE,
    PICK_BACK,
    PICK_BACK_TO_CHAT,
    PICK_DIRECTIONS,
    PICK_PAYMENTS,
    RETRY_LABEL,
)


def _payment_review() -> rx.Component:
    """«Revisa y envía»: the QR (when the method has one) and then the text — the
    method's data is changed in Formas de pago, never here."""
    chosen = P.pick_selected_payment
    return pick_list(
        P,
        rx.vstack(
            rx.cond(
                P.pick_payment_loading,
                skeleton_rows(rows=2, height="1.25rem"),
                rx.vstack(
                    rx.cond(
                        P.pick_payment_qr != "",
                        chat_bubble(
                            media_thumb(
                                P.pick_payment_qr,
                                size=None,
                                width="100%",
                                height="12rem",
                                alt=chosen.alt,
                                icon="image",
                            ),
                            direction="out",
                            max_width="20rem",
                            align_self="flex-end",
                        ),
                    ),
                    rx.cond(
                        P.pick_payment_text != "",
                        chat_bubble(
                            rx.text(P.pick_payment_text, size="2", white_space="pre-wrap"),
                            direction="out",
                            max_width="20rem",
                            align_self="flex-end",
                        ),
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            link_button(PAYMENTS_CHANGE, "pencil", P.payments_change_href),
            spacing="3",
            width="100%",
        ),
    )


def _body() -> rx.Component:
    return rx.match(
        P.pick_source,
        (PICK_PAYMENTS, rx.cond(P.pick_reviewing, _payment_review(), pick_payments(P))),
        # Instagram gets a text with a link either way: no «ponlo en el mapa» hint
        (PICK_DIRECTIONS, pick_directions(P, point_hint=False)),
        rx.fragment(),
    )


def _footer() -> rx.Component:
    return rx.vstack(
        rx.cond(P.pick_send_error != "", callout(P.pick_send_error, "error")),
        rx.hstack(
            rx.button(
                rx.icon(rx.cond(P.pick_step <= 1, "chevron-left", "arrow-left"), size=T.ICON_SM),
                rx.cond(P.pick_step <= 1, PICK_BACK_TO_CHAT, PICK_BACK),
                on_click=P.pick_back,
                variant="soft",
                size="3",
                min_height=TAP_MIN,
                **T.tone_scheme("neutral"),
            ),
            rx.spacer(),
            rx.cond(
                P.pick_reviewing,
                rx.button(
                    rx.icon("send", size=T.ICON_SM),
                    rx.cond(
                        (P.pick_send_error != "") & ~P.pick_sending, RETRY_LABEL, P.pick_send_label
                    ),
                    on_click=P.send_pick,
                    disabled=~P.pick_can_send,
                    aria_busy=rx.cond(P.pick_sending, "true", "false"),
                    size="3",
                    min_height=TAP_MIN,
                ),
            ),
            width="100%",
            align="center",
        ),
        spacing="2",
        width="100%",
    )


def instagram_pick_drawer() -> rx.Component:
    """Open only while the chat it opened on is the open one."""
    return drawer(
        _body(),
        open=P.pick_open & (ConversationsState.open_thread_id == P.pick_thread),
        on_open_change=P.set_picker_open,
        title=P.pick_title,
        step=rx.cond(P.pick_show_progress, step_progress(P.pick_step, P.pick_total)),
        description=P.pick_help,
        footer=_footer(),
        icon="send",
    )
