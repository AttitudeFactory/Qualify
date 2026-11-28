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
    signal_pill,
    skeleton_rows,
    tone_badge,
)
from .ui import tokens as T
from .whatsapp_chats_vm import (
    ADD_PHOTOS_LABEL,
    ADD_PRODUCT_LABEL,
    ALL_WITHOUT_PHOTO,
    CAPTION_LABEL,
    CAPTION_SHORTENED,
    DIRECTIONS_COMPLETE,
    DIRECTIONS_EMPTY,
    DIRECTIONS_NO_POINT,
    DIRECTIONS_PUT_ON_MAP,
    DRAFTS_ROUTE,
    NO_PHOTO_PILL,
    NO_PRODUCTS_EMPTY,
    OFFER_BADGE,
    OFFER_CHANGE,
    OFFER_EMPTY,
    OFFER_GO,
    OFFER_GONE,
    PAYMENTS_ADD,
    PAYMENTS_EMPTY_TEXT,
    PAYMENTS_EMPTY_TITLE,
    PICK_OFFER,
    PICK_PIECES,
    PRODUCTS_NO_MATCH,
    PRODUCTS_ROUTE,
    PRODUCTS_SEARCH,
    PRODUCTS_SHOW_ALL,
    RETRY_LABEL,
    TEXT_ONLY_LABEL,
    PaymentCardVM,
    ProductCardVM,
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


# --- «Tus productos» (m-25143229, slice b) ---------------------------------------------


def product_src(card: ProductCardVM) -> rx.Var:
    """A public URL as it comes, else the upload-store key through `rx.get_upload_url`."""
    return rx.cond(
        card.thumb_url != "",
        card.thumb_url,
        rx.cond(card.thumb_key != "", rx.get_upload_url(card.thumb_key), ""),
    )


def product_card(S: Any, card: ProductCardVM) -> rx.Component:  # noqa: N803
    return choice_card(
        rx.vstack(
            media_thumb(
                product_src(card),
                size=None,
                width="100%",
                height="7.5rem",
                alt=card.alt,
                icon="package",
                has=card.has_photo,
            ),
            rx.text(card.name, weight="medium", size="2", text_align="left"),
            rx.hstack(
                rx.text(card.price_label, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
                rx.cond(~card.has_photo, signal_pill(NO_PHOTO_PILL, "neutral")),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        selected=S.pick_selected == card.id,
        on_select=S.choose_product(card.id),
        padding="0.5rem",
        width="100%",
        min_height=TAP_MIN,
    )


def pick_products(S: Any, *, search_id: str) -> rx.Component:  # noqa: N803
    """«¿Qué producto?»: the grid (with search past a few), or the empty state that
    leads to the catalog."""
    title, line = NO_PRODUCTS_EMPTY
    grid = rx.vstack(
        rx.cond(
            S.pick_all_without_photo,
            rx.vstack(
                callout(ALL_WITHOUT_PHOTO, "info"),
                link_button(ADD_PHOTOS_LABEL, "image-plus", PRODUCTS_ROUTE),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            S.pick_show_search,
            rx.vstack(
                rx.el.label(
                    rx.text(PRODUCTS_SEARCH, size="2", weight="medium"),
                    html_for=search_id,
                ),
                rx.input(
                    rx.input.slot(rx.icon("search", size=T.ICON_SM)),
                    id=search_id,
                    value=S.pick_query,
                    on_change=S.set_pick_query,
                    size="3",
                    width="100%",
                ),
                spacing="1",
                width="100%",
            ),
        ),
        rx.cond(
            S.pick_visible_products.length() > 0,
            rx.grid(
                rx.foreach(S.pick_visible_products, lambda card: product_card(S, card)),
                columns="2",
                spacing="2",
                width="100%",
            ),
            rx.hstack(
                rx.text(PRODUCTS_NO_MATCH, size="2", color=T.TEXT_MUTED),
                rx.button(
                    PRODUCTS_SHOW_ALL,
                    on_click=S.clear_pick_query,
                    variant="soft",
                    size="3",
                    min_height=TAP_MIN,
                    **T.tone_scheme("neutral"),
                ),
                spacing="3",
                align="center",
                wrap="wrap",
            ),
        ),
        spacing="3",
        width="100%",
    )
    return pick_list(
        S,
        rx.cond(
            S.pick_products.length() == 0,
            empty_state(
                "package",
                title,
                line,
                # U3: with the way back to the chat (`?volver=`)
                link_button(ADD_PRODUCT_LABEL, "plus", S.products_add_href),
            ),
            grid,
        ),
    )


def video_mark() -> rx.Component:
    """The ▶ over a video's poster: a still picture, nothing plays in the grid
    (m-24945889 §4)."""
    return rx.center(
        rx.icon("play", size=T.ICON_MD, aria_hidden="true"),
        class_name="q-pick-play",
        position="absolute",
        top="50%",
        left="50%",
        transform="translate(-50%, -50%)",
        width="2.5rem",
        height="2.5rem",
        border_radius="9999px",
        background="rgba(0, 0, 0, 0.55)",
        color="white",
        pointer_events="none",
    )


# --- the text of the review --------------------------------------------------------------


def caption_editor(
    S: Any,  # noqa: N803
    label: str | None = None,
    *,
    caption_id: str,
    count_id: str,
    shortened_notice: bool = True,
) -> rx.Component:
    """The text of the review. `label` names it (Instagram: «Texto del mensaje», it goes
    as its own message); `shortened_notice`: «Acortamos el texto para que quepa en
    WhatsApp.» — WhatsApp only."""
    return rx.vstack(
        rx.vstack(
            rx.hstack(
                rx.el.label(
                    rx.text(
                        label or rx.cond(S.pick_as_text, TEXT_ONLY_LABEL, CAPTION_LABEL),
                        size="2",
                        weight="medium",
                    ),
                    html_for=caption_id,
                ),
                rx.spacer(),
                rx.text(
                    S.pick_caption_count,
                    size="1",
                    color=rx.cond(
                        S.pick_caption_error != "", T.tone_color("error", 11), T.TEXT_MUTED
                    ),
                    class_name="q-nums",
                    id=count_id,
                ),
                width="100%",
                align="center",
            ),
            rx.text_area(
                id=caption_id,
                value=S.pick_caption,
                on_change=S.set_pick_caption,
                rows="4",
                resize="vertical",
                width="100%",
                size="3",
                custom_attrs={"aria-describedby": count_id},
            ),
            rx.cond(
                S.pick_caption_error != "",
                rx.text(S.pick_caption_error, size="1", color=T.tone_color("error", 11)),
            ),
            rx.cond(
                ((S.pick_source == PICK_PIECES) | (S.pick_source == PICK_OFFER))
                & S.pick_selected_piece.shortened,
                rx.text(CAPTION_SHORTENED, size="1", color=T.TEXT_MUTED),
            )
            if shortened_notice
            else rx.fragment(),
            spacing="1",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


# --- «Tu oferta» -------------------------------------------------------------------------


def pick_offer(S: Any, review: rx.Component) -> rx.Component:  # noqa: N803
    """«Tu oferta»: one step — the marked piece, how long ago it was marked, a soft
    «¿Sigue vigente?» past 14 days (never blocking), and the screen's own `review`."""
    offer = S.pick_offer
    empty_title, empty_line = OFFER_EMPTY
    gone_title, gone_line = OFFER_GONE
    go = link_button(OFFER_GO, "tag", DRAFTS_ROUTE)
    return pick_list(
        S,
        rx.cond(
            ~offer.present,
            pick_grid_skeleton(),
            rx.cond(
                ~offer.marked,
                empty_state("tag", empty_title, empty_line, go),
                rx.cond(
                    offer.gone,
                    empty_state("tag", gone_title, gone_line, go),
                    rx.vstack(
                        rx.hstack(
                            tone_badge(OFFER_BADGE, "info", icon="tag"),
                            rx.text(offer.marked_label, size="2", color=T.TEXT_MUTED),
                            spacing="2",
                            align="center",
                            wrap="wrap",
                        ),
                        rx.cond(
                            offer.stale_note != "",
                            rx.vstack(
                                callout(offer.stale_note, "warn"),
                                rx.link(OFFER_CHANGE, href=DRAFTS_ROUTE, size="2"),
                                spacing="1",
                                width="100%",
                            ),
                        ),
                        review,
                        spacing="3",
                        width="100%",
                    ),
                ),
            ),
        ),
    )
