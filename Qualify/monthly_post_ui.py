"""«Publicación del mes» card on the Planificador (m-25120704)."""

from __future__ import annotations

import reflex as rx

from .monthly_post_state import MonthlyPostState as S
from .monthly_post_vm import (
    ENABLED_BADGE,
    EXPLAIN,
    KIND_LABEL,
    NO_PRODUCTS,
    NO_PRODUCTS_HREF,
    NO_PRODUCTS_LINK,
    NOT_SAVED,
    PICK_PRODUCT,
    PRODUCT_LABEL,
    PRODUCT_MISSING,
    TEMPLATE_KIND,
    TITLE,
    kind_options,
)
from .ui import (
    callout,
    card,
    choice_card,
    choice_card_check,
    media_thumb,
    skeleton_card,
    tone_badge,
)
from .ui import tokens as T

_SWITCH_ID = "monthly-post-switch"
_KIND_ID = "monthly-post-kind"
_PRODUCT_LABEL_ID = "monthly-post-product-label"


def _kind_select() -> rx.Component:
    return rx.vstack(
        rx.text(KIND_LABEL, as_="label", html_for=_KIND_ID, size="2", weight="medium"),
        rx.select.root(
            rx.select.trigger(id=_KIND_ID, width="100%", min_height="44px"),
            rx.select.content(
                *[rx.select.item(o["label"], value=o["value"]) for o in kind_options()]
            ),
            value=S.kind,
            on_change=S.set_kind,
            disabled=S.saving,
            size="3",
        ),
        spacing="1",
        width="100%",
    )


def _product_tile(row: rx.Var[dict[str, str]]) -> rx.Component:
    selected = S.product_id == row["id"]
    return choice_card(
        rx.hstack(
            media_thumb(rx.get_upload_url(row["photo_key"]), size="44px"),
            rx.text(row["name"], size="2", weight="medium", flex="1", text_align="left"),
            rx.cond(selected, choice_card_check()),
            align="center",
            spacing="3",
            width="100%",
        ),
        selected=selected,
        on_select=S.choose_product(row["id"]),
        disabled=S.saving,
        padding="0.5rem 0.75rem",
        min_height="44px",
        width="100%",
    )


def _product_picker() -> rx.Component:
    """«Con plantilla»: the one catalog product it shows, saved on choice (m-25121346)."""
    return rx.vstack(
        rx.text(PRODUCT_LABEL, id=_PRODUCT_LABEL_ID, size="2", weight="medium"),
        rx.cond(S.product_missing, callout(PRODUCT_MISSING, "warn")),
        rx.cond(
            S.products.length() > 0,
            rx.vstack(
                rx.cond(S.product_id == "", callout(PICK_PRODUCT, "warn")),
                rx.grid(
                    rx.foreach(S.products, _product_tile),
                    role="radiogroup",
                    aria_labelledby=_PRODUCT_LABEL_ID,
                    columns=rx.breakpoints(initial="1", sm="2"),
                    spacing="2",
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
            rx.vstack(
                callout(NOT_SAVED, "warn"),
                callout(NO_PRODUCTS, "info"),
                rx.link(
                    rx.button(
                        rx.icon("plus", size=T.ICON_SM), NO_PRODUCTS_LINK, variant="soft", size="3"
                    ),
                    href=NO_PRODUCTS_HREF,
                ),
                spacing="2",
                width="100%",
            ),
        ),
        spacing="2",
        width="100%",
    )


def monthly_post_card() -> rx.Component:
    return rx.cond(
        S.loading,
        skeleton_card(2),
        rx.cond(
            S.load_error != "",
            callout(S.load_error, "warn"),
            card(
                rx.vstack(
                    rx.hstack(
                        rx.switch(
                            id=_SWITCH_ID,
                            checked=S.enabled,
                            on_change=S.set_enabled,
                            disabled=S.saving,
                            size="3",
                        ),
                        rx.text(TITLE, as_="label", html_for=_SWITCH_ID, weight="medium"),
                        rx.cond(S.enabled, tone_badge(ENABLED_BADGE, "ok", icon="check")),
                        align="center",
                        wrap="wrap",
                        spacing="3",
                        min_height="44px",
                    ),
                    rx.text(EXPLAIN, size="2", color=T.TEXT_MUTED),
                    rx.cond(S.enabled, _kind_select()),
                    rx.cond(S.enabled & (S.kind == TEMPLATE_KIND), _product_picker()),
                    # what it costs, before turning it on too (the default kind's price)
                    rx.cond(
                        S.cost_text != "",
                        rx.cond(
                            S.cost_warns,
                            callout(S.cost_text, "warn"),
                            rx.text(S.cost_text, size="2", weight="medium"),
                        ),
                    ),
                    rx.cond(S.error != "", callout(S.error, "error")),
                    spacing="2",
                    width="100%",
                ),
                width="100%",
            ),
        ),
    )
