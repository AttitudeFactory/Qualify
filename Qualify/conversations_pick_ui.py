"""Instagram's «+» panel (m-25143229): the `drawer` its rows open.

The steps are WhatsApp's own (`chat_plus_picks.py`: «¿Cuál forma de pago?», «Así le
llega tu ubicación»); only the review of a payment method differs, because Instagram
cannot put a text under an image: the QR arrives as one message and its text as the
next, so the review shows the two bubbles exactly as they will arrive. Nothing leaves
without «Enviar». A composition of design-system pieces, no new component.
"""

from __future__ import annotations

import reflex as rx

from .chat_plus_picks import (
    caption_editor,
    link_button,
    pick_directions,
    pick_list,
    pick_offer,
    pick_payments,
    pick_products,
    video_mark,
)
from .chat_thread import TAP_MIN
from .conversations_pick_state import IG_PICK_FLOW
from .conversations_pick_state import InstagramPickState as P
from .conversations_state import ConversationsState
from .conversations_vm import VIDEO_TOO_LARGE_TEXT
from .ui import callout, chat_bubble, drawer, media_thumb, skeleton_rows
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.steps import step_progress
from .whatsapp_chats_vm import (
    NO_PHOTO_NOTICE,
    PAYMENTS_CHANGE,
    PICK_BACK,
    PICK_BACK_TO_CHAT,
    PICK_DIRECTIONS,
    PICK_OFFER,
    PICK_PAYMENTS,
    PICK_PRODUCTS,
    RETRY_LABEL,
    TEXT_ONLY_LABEL,
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


_SEARCH_ID = "ig-pick-search"
_CAPTION_ID = "ig-pick-caption"
_CAPTION_COUNT_ID = "ig-pick-caption-count"


def _media_review() -> rx.Component:
    """«Revisa y envía» of a product or the offer: on Instagram a picture carries no
    text, so what arrives is two messages — the picture (or the video's first frame,
    with ▶), then the text — shown as two bubbles; the text is edited under them.
    Without a picture Instagram takes, the text alone (WhatsApp's own notice)."""
    piece = P.pick_selected_piece
    return rx.vstack(
        rx.cond(
            P.pick_as_text & (P.pick_source == PICK_PRODUCTS), callout(NO_PHOTO_NOTICE, "info")
        ),
        # C1: a video over Instagram's limit — the composer's own words; «Enviar» is off
        rx.cond(
            (P.pick_source == PICK_OFFER) & P.pick_offer_too_large,
            callout(VIDEO_TOO_LARGE_TEXT, "warn"),
        ),
        rx.cond(
            P.pick_media_src != "",
            chat_bubble(
                rx.box(
                    media_thumb(
                        P.pick_media_src,
                        size=None,
                        width="100%",
                        height="12rem",
                        alt=rx.cond(
                            P.pick_source == PICK_PRODUCTS, P.pick_selected_product.alt, piece.alt
                        ),
                        icon="image",
                    ),
                    rx.cond((P.pick_source == PICK_OFFER) & piece.is_video, video_mark()),
                    position="relative",
                    width="100%",
                ),
                direction="out",
                max_width="20rem",
                align_self="flex-end",
            ),
        ),
        rx.cond(
            P.pick_preview_text != "",
            chat_bubble(
                rx.text(P.pick_preview_text, size="2", white_space="pre-wrap"),
                direction="out",
                max_width="20rem",
                align_self="flex-end",
            ),
        ),
        # U1: on Instagram the text is its own message; U2: no WhatsApp notice here
        caption_editor(
            P,
            TEXT_ONLY_LABEL,
            caption_id=_CAPTION_ID,
            count_id=_CAPTION_COUNT_ID,
            shortened_notice=False,
        ),
        spacing="3",
        width="100%",
    )


def _body() -> rx.Component:
    return rx.match(
        P.pick_source,
        (
            PICK_PRODUCTS,
            rx.cond(P.pick_reviewing, _media_review(), pick_products(P, search_id=_SEARCH_ID)),
        ),
        (PICK_OFFER, pick_offer(P, _media_review())),
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
        # U2: the phone's «atrás» steps back / closes, as in WhatsApp (`?flujo=`)
        flow_sync(IG_PICK_FLOW, P.pick_step, ready=P.pick_open),
        _body(),
        open=P.pick_open & (ConversationsState.open_thread_id == P.pick_thread),
        on_open_change=P.set_picker_open,
        title=P.pick_title,
        step=rx.cond(P.pick_show_progress, step_progress(P.pick_step, P.pick_total)),
        description=P.pick_help,
        footer=_footer(),
        icon="send",
    )
