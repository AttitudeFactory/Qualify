"""«Tu producto en sticker» (m-25017912): the start card next to «Crear para esta temporada»
in Tu marca, and the five-step drawer (product → drawing → messages → movement → review).
Design-system pieces only (`card`, `drawer`, `step_progress`, `choice_card`,
`choice_card_check`, `media_thumb`, `signal_pill`, `callout`, `empty_state`,
`skeleton_rows`). The cost is said in creaciones, from the backend's own words."""

from __future__ import annotations

import reflex as rx

from .product_sticker_state import ProductStickerState
from .product_sticker_vm import (
    ADD_PHOTOS_LABEL,
    ANIMATED_LINE,
    ANIMATED_TITLE,
    ASKING_LABEL,
    BACK_LABEL,
    CANCEL_LABEL,
    CATALOG_HREF,
    DISCARD_LABEL,
    DISCARD_TEXT,
    DISCARD_TITLE,
    DISCARD_YES,
    DRAWING_BUSY_LABEL,
    DRAWING_FAILED_PILL,
    DRAWING_HELP,
    DRAWING_PENDING,
    DRAWING_USED_PILL,
    DRAWING_WAIT,
    FLOW_STEPS,
    FREE_LINE,
    GO_CATALOG_LABEL,
    MESSAGE_AS_IS,
    MESSAGE_HELP,
    MOTION_HELP,
    NEXT_LABEL,
    NO_COST,
    NO_DRAWING_YET,
    NO_MATCH,
    NO_PHOTO_TEXT,
    NO_PHOTO_TITLE,
    OWN_MESSAGE,
    OWN_MESSAGE_HINT,
    OWN_MESSAGE_LABEL,
    PREPARING_LABEL,
    PRODUCT_HELP,
    RETRY_LABEL,
    SEARCH_LABEL,
    SEASON_INSTEAD_LABEL,
    START_BUTTON,
    START_LINE,
    START_TITLE,
    STEP_DRAWING,
    STEP_MESSAGE,
    STEP_MOTION,
    STEP_PRODUCT,
    STEP_TITLES,
    STILL_LINE,
    STILL_TITLE,
    TRUST_LINE,
    DrawingVM,
    ProductVM,
)
from .r2_media import BACKEND_BASE
from .seasonal_state import SeasonalState
from .ui import (
    callout,
    card,
    choice_card,
    choice_card_check,
    drawer,
    empty_state,
    media_thumb,
    signal_pill,
    skeleton_rows,
)
from .ui import tokens as T
from .ui.steps import step_progress

P = ProductStickerState
_TAP = "44px"
_OWN_ID = "product-sticker-own"
_OWN_COUNT_ID = "product-sticker-own-count"
_OWN_ERROR_ID = "product-sticker-own-error"
_SEARCH_ID = "product-sticker-search"


def _button(label, on_click, *, icon: str | None = None, solid: bool = False, **props):
    kids = [rx.icon(icon, size=T.ICON_SM)] if icon else []
    return rx.button(
        *kids,
        label,
        on_click=on_click,
        variant="solid" if solid else "soft",
        size="2",
        min_height=_TAP,
        **({} if solid else T.tone_scheme("neutral")),
        **props,
    )


def _link_button(label: str, href: str, icon: str) -> rx.Component:
    return rx.button(
        rx.link(rx.icon(icon, size=T.ICON_SM), label, href=href, underline="none"),
        as_child=True,
        variant="soft",
        size="2",
        min_height=_TAP,
        **T.tone_scheme("neutral"),
    )


# ======================================================================================
# The start cards in Tu marca
# ======================================================================================


def start_card(title, line, cost, button: rx.Component, *, icon: str) -> rx.Component:
    """One way to start, with its benefit and its price in sight (UX doc §1)."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=T.ICON_MD, aria_hidden="true", color=T.tone_color("info", 11)),
                rx.heading(title, size="3", as_="h3"),
                spacing="2",
                align="center",
            ),
            rx.text(line, size="2", color=T.TEXT_MUTED),
            rx.cond(cost != "", rx.text(cost, size="2", weight="medium")),
            button,
            spacing="2",
            align_items="start",
            width="100%",
        ),
        padding="1rem",
        width="100%",
    )


def product_start_card() -> rx.Component:
    return start_card(
        START_TITLE,
        START_LINE,
        P.start_cost,
        rx.vstack(
            rx.cond(P.start_blocked != "", callout(P.start_blocked, "warn")),
            _button(START_BUTTON, P.open_flow, icon="sparkles", solid=True),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        icon="smile",
    )


# ======================================================================================
# Step 1 — ¿Qué producto dibujamos?
# ======================================================================================


def _product_tile(product: ProductVM) -> rx.Component:
    chosen = P.product_id == product.id
    return choice_card(
        rx.box(
            media_thumb(
                rx.cond(product.src != "", BACKEND_BASE + product.src, ""),
                size=None,
                width="100%",
                height="5.5rem",
                icon="package",
            ),
            rx.cond(
                chosen,
                rx.box(choice_card_check(), position="absolute", top="0.3rem", right="0.3rem"),
            ),
            position="relative",
            width="100%",
        ),
        rx.text(product.name, size="1", weight="medium", text_align="left", width="100%"),
        selected=chosen,
        on_select=P.choose_product(product.id),
        padding="0.4rem",
        width="100%",
        min_height=_TAP,
        display="flex",
        flex_direction="column",
        gap="0.35rem",
        aria_label=product.name,
    )


def _step_product() -> rx.Component:
    return rx.cond(
        P.no_products,
        empty_state(
            "image-plus",
            NO_PHOTO_TITLE,
            NO_PHOTO_TEXT,
            _link_button(GO_CATALOG_LABEL, CATALOG_HREF, "package"),
        ),
        rx.vstack(
            rx.text(PRODUCT_HELP, size="2", color=T.TEXT_MUTED),
            rx.cond(
                P.show_search,
                rx.vstack(
                    rx.el.label(
                        rx.text(SEARCH_LABEL, size="2", weight="medium"), html_for=_SEARCH_ID
                    ),
                    rx.input(
                        id=_SEARCH_ID,
                        value=P.product_query,
                        on_change=P.set_product_query,
                        type="search",
                        size="3",
                        width="100%",
                    ),
                    spacing="1",
                    width="100%",
                ),
            ),
            rx.cond(
                P.shown_products.length() > 0,
                rx.grid(
                    rx.foreach(P.shown_products, _product_tile),
                    columns="3",
                    spacing="2",
                    width="100%",
                    role="radiogroup",
                    aria_label=STEP_TITLES[STEP_PRODUCT],
                ),
                rx.text(NO_MATCH, size="2", color=T.TEXT_MUTED),
            ),
            rx.cond(
                P.without_photo_text != "",
                rx.hstack(
                    rx.text(P.without_photo_text, size="1", color=T.TEXT_MUTED),
                    rx.link(ADD_PHOTOS_LABEL, href=CATALOG_HREF, size="1"),
                    spacing="2",
                    wrap="wrap",
                    align="center",
                ),
            ),
            spacing="3",
            width="100%",
        ),
    )


# ======================================================================================
# Step 2 — Elige el dibujo (create · ask for another · pick one)
# ======================================================================================


def _drawing_face(drawing: DrawingVM) -> rx.Component:
    return rx.box(
        rx.cond(
            drawing.pending,
            rx.center(
                rx.vstack(
                    rx.icon("loader", size=T.ICON_MD, aria_hidden="true"),
                    rx.text(DRAWING_PENDING, size="1", color=T.TEXT_MUTED),
                    align="center",
                    spacing="1",
                ),
                width="100%",
                height="100%",
            ),
            rx.cond(
                drawing.failed,
                rx.center(
                    rx.icon("image-off", size=T.ICON_MD, color=T.TEXT_FAINT, aria_hidden="true"),
                    width="100%",
                    height="100%",
                ),
                rx.image(
                    src=BACKEND_BASE + drawing.src,
                    alt=drawing.alt,
                    loading="lazy",
                    width="100%",
                    height="100%",
                    object_fit="contain",
                ),
            ),
        ),
        width="100%",
        aspect_ratio="1 / 1",
        border_radius=T.RADIUS_CONTROL,
        overflow="hidden",
        background=T.tone_color("neutral", 3),
    )


def _drawing_card(drawing: DrawingVM) -> rx.Component:
    chosen = P.drawing_id == drawing.id
    busy = P.discarding.contains(drawing.id)
    return rx.vstack(
        choice_card(
            rx.box(
                _drawing_face(drawing),
                rx.cond(
                    chosen,
                    rx.box(choice_card_check(), position="absolute", top="0.3rem", right="0.3rem"),
                ),
                position="relative",
                width="100%",
            ),
            rx.cond(drawing.failed, signal_pill(DRAWING_FAILED_PILL, "warn")),
            rx.cond(drawing.approved, signal_pill(DRAWING_USED_PILL, "ok")),
            rx.cond(
                drawing.failure_text != "",
                rx.text(drawing.failure_text, size="1", text_align="left"),
            ),
            selected=chosen,
            on_select=P.pick_drawing(drawing.id),
            disabled=~drawing.usable,
            padding="0.4rem",
            width="100%",
            display="flex",
            flex_direction="column",
            align_items="start",
            gap="0.35rem",
            aria_label=rx.cond(drawing.pending, DRAWING_PENDING, drawing.alt),
        ),
        rx.cond(~drawing.pending, _discard_action(drawing, busy)),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _discard_action(drawing: DrawingVM, busy: rx.Var[bool]) -> rx.Component:
    """«Quitar este dibujo»: a paid drawing leaves only after a question with the same verb
    on the title and the button (docs/design-system.md §6.2)."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                DISCARD_LABEL,
                variant="ghost",
                size="1",
                min_height=_TAP,
                disabled=busy,
                aria_label=DISCARD_LABEL + ": " + drawing.alt,
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title(DISCARD_TITLE),
            rx.alert_dialog.description(DISCARD_TEXT, size="2"),
            rx.flex(
                rx.alert_dialog.cancel(_button(CANCEL_LABEL, rx.noop())),
                rx.alert_dialog.action(
                    rx.button(
                        DISCARD_YES,
                        on_click=P.discard_drawing(drawing.id),
                        variant="solid",
                        size="2",
                        min_height=_TAP,
                        **T.tone_scheme("error"),
                    ),
                ),
                gap="2",
                justify="end",
                margin_top="1rem",
                wrap="wrap",
            ),
            max_width="26rem",
        ),
    )


def _ask_block() -> rx.Component:
    """The drawing's cost in creaciones — always before the button that spends it."""
    return rx.vstack(
        rx.cond(
            P.cost_known,
            rx.cond(
                P.cost_can_pay,
                callout(P.cost_line, "neutral", icon="sparkles"),
                rx.vstack(
                    callout(P.cost_message, "warn"),
                    # a way out, not just a stop: the season's stickers are free
                    _button(
                        SEASON_INSTEAD_LABEL,
                        [P.close_for_season, SeasonalState.open_flow],
                        icon="calendar-heart",
                    ),
                    spacing="2",
                    width="100%",
                    align_items="start",
                ),
            ),
            callout(NO_COST, "warn"),
        ),
        rx.cond(
            P.cost_known & P.cost_can_pay,
            rx.button(
                rx.cond(
                    P.asking,
                    ASKING_LABEL,
                    rx.cond(P.any_drawing_pending, DRAWING_BUSY_LABEL, P.drawing_button),
                ),
                on_click=P.ask_drawing,
                # the main action while there is no drawing to use; secondary after that
                variant=rx.cond(P.has_usable_drawing, "soft", "solid"),
                color_scheme=rx.cond(P.has_usable_drawing, "gray", "teal"),
                size="2",
                min_height=_TAP,
                disabled=~P.can_ask_drawing,
                aria_busy=rx.cond(P.asking, "true", "false"),
                white_space="nowrap",
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _step_drawing() -> rx.Component:
    return rx.vstack(
        rx.text(DRAWING_HELP, size="2", color=T.TEXT_MUTED),
        rx.cond(
            P.drawings_loading & (P.drawings.length() == 0),
            skeleton_rows(2, height="8rem"),
            rx.cond(
                P.drawings.length() > 0,
                rx.grid(
                    rx.foreach(P.drawings, _drawing_card),
                    columns=rx.breakpoints(initial="2", sm="3"),
                    spacing="2",
                    width="100%",
                    role="radiogroup",
                    aria_label="Tus dibujos de " + P.product_name,
                ),
                # «Toca Crear dibujo» only when there is a button to touch
                rx.cond(P.cost_can_pay, rx.text(NO_DRAWING_YET, size="2")),
            ),
        ),
        rx.cond(P.any_drawing_pending, rx.text(DRAWING_WAIT, size="1", color=T.TEXT_MUTED)),
        _ask_block(),
        spacing="3",
        width="100%",
    )


# ======================================================================================
# Step 3 — ¿Qué dice el sticker?
# ======================================================================================


def _check_row(title, selected, on_select, line: str | None = None) -> rx.Component:
    return choice_card(
        rx.hstack(
            rx.vstack(
                rx.text(title, size="3", weight="medium"),
                *([rx.text(line, size="2", color=T.TEXT_MUTED)] if line else []),
                spacing="1",
                align_items="start",
                flex="1",
            ),
            rx.cond(selected, choice_card_check()),
            width="100%",
            align="center",
        ),
        selected=selected,
        on_select=on_select,
        role="checkbox",
        padding="0.75rem 1rem",
        width="100%",
        min_height=_TAP,
    )


def _message_card(text: rx.Var[str]) -> rx.Component:
    return _check_row(text, P.picked.contains(text), P.toggle_message(text))


def _step_message() -> rx.Component:
    return rx.vstack(
        rx.text(MESSAGE_HELP, size="2", color=T.TEXT_MUTED),
        rx.vstack(
            rx.foreach(P.presets, _message_card),
            _check_row(OWN_MESSAGE, P.own_on, P.toggle_own),
            spacing="2",
            width="100%",
            role="group",
            aria_label=STEP_TITLES[STEP_MESSAGE],
        ),
        rx.cond(
            P.own_on,
            rx.vstack(
                rx.hstack(
                    rx.el.label(
                        rx.text(OWN_MESSAGE_LABEL, size="2", weight="medium"), html_for=_OWN_ID
                    ),
                    rx.spacer(),
                    rx.text(
                        P.own_count,
                        size="1",
                        color=T.TEXT_MUTED,
                        id=_OWN_COUNT_ID,
                        class_name="q-nums",
                        aria_live=P.own_count_live,
                    ),
                    width="100%",
                ),
                rx.input(
                    id=_OWN_ID,
                    value=P.own_text,
                    on_change=P.set_own_text,
                    max_length=P.max_chars,
                    placeholder=OWN_MESSAGE_HINT,
                    size="3",
                    width="100%",
                    custom_attrs={"aria-describedby": _OWN_COUNT_ID + " " + _OWN_ERROR_ID},
                ),
                # why «Siguiente» is off, said where the owner looks (text, not only colour)
                rx.text(
                    P.own_error,
                    id=_OWN_ERROR_ID,
                    size="1",
                    color=T.tone_color("warn", 11),
                    aria_live="polite",
                ),
                spacing="1",
                width="100%",
            ),
        ),
        rx.text(MESSAGE_AS_IS, size="1", color=T.TEXT_MUTED),
        spacing="3",
        width="100%",
    )


# ======================================================================================
# Step 4 — ¿Quieto o con movimiento? · Step 5 — Revisa y prepara
# ======================================================================================


def _step_motion() -> rx.Component:
    return rx.vstack(
        rx.text(MOTION_HELP, size="2", color=T.TEXT_MUTED),
        rx.vstack(
            _check_row(ANIMATED_TITLE, P.animated, P.toggle_animated, ANIMATED_LINE),
            _check_row(STILL_TITLE, P.still, P.toggle_still, STILL_LINE),
            spacing="2",
            width="100%",
            role="group",
        ),
        spacing="3",
        width="100%",
    )


def _step_review() -> rx.Component:
    drawing = P.chosen_drawing
    return rx.vstack(
        rx.hstack(
            media_thumb(
                rx.cond(drawing.src != "", BACKEND_BASE + drawing.src, ""),
                size="5rem",
                fit="contain",
                icon="smile",
                alt=drawing.alt,
            ),
            rx.text(P.review, size="3"),
            spacing="3",
            align="center",
            width="100%",
        ),
        callout(FREE_LINE, "ok", icon="gift"),
        rx.text(TRUST_LINE, size="2", color=T.TEXT_MUTED),
        spacing="3",
        width="100%",
    )


def _footer() -> rx.Component:
    return rx.vstack(
        rx.cond(P.flow_error != "", callout(P.flow_error, "warn")),
        rx.hstack(
            _button(
                BACK_LABEL,
                P.flow_back,
                icon="chevron-left",
                disabled=P.creating | P.asking | P.picking,
            ),
            rx.spacer(),
            rx.cond(
                P.flow_step < FLOW_STEPS,
                rx.cond(
                    P.no_products & (P.flow_step == STEP_PRODUCT),
                    rx.fragment(),
                    _button(
                        NEXT_LABEL,
                        P.flow_next,
                        solid=True,
                        disabled=~P.can_go_on,
                        aria_busy=rx.cond(P.picking, "true", "false"),
                    ),
                ),
                _button(
                    rx.cond(P.creating, PREPARING_LABEL, P.prepare_button),
                    P.create,
                    icon="sticker",
                    solid=True,
                    disabled=~P.can_go_on,
                    aria_busy=rx.cond(P.creating, "true", "false"),
                ),
            ),
            width="100%",
            align="center",
            spacing="2",
        ),
        spacing="2",
        width="100%",
    )


def _body() -> rx.Component:
    return rx.cond(
        P.loading,
        skeleton_rows(3, height="6rem"),
        rx.cond(
            P.load_error != "",
            rx.vstack(
                callout(P.load_error, "error"),
                _button(RETRY_LABEL, P.open_flow, icon="refresh-cw"),
                spacing="2",
                width="100%",
            ),
            rx.match(
                P.flow_step,
                (STEP_PRODUCT, _step_product()),
                (STEP_DRAWING, _step_drawing()),
                (STEP_MESSAGE, _step_message()),
                (STEP_MOTION, _step_motion()),
                _step_review(),
            ),
        ),
    )


def product_sticker_drawer() -> rx.Component:
    return drawer(
        _body(),
        open=P.flow_open,
        on_open_change=P.set_flow_open,
        title=P.flow_title,
        step=step_progress(P.flow_step, FLOW_STEPS),
        footer=_footer(),
        icon="smile",
    )
