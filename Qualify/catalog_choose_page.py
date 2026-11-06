"""«Elegir para una publicación» — choosing media in Galería (CM-5, m-24955926).

Design system only: `section` for the two groups («De tu negocio», «De tus productos»
with each product's name), the choice-card material for every tile (a real ``<button>``
with ``role="checkbox"``, its number in a `tone_badge`), `media_thumb`, and the sticky
action bar the Creadores screen uses (opaque card material, lifted above the phone's
bottom bar, in the flow — so it never covers the last row). Phone first: three tiles a
row at 360 px, 44 px buttons, «N elegidas» said as it changes.
"""

from __future__ import annotations

import reflex as rx

from .catalog_choose_state import CatalogChooseState
from .catalog_choose_vm import (
    CANCEL,
    CHOOSE_BUTTON,
    CHOOSE_HELP,
    CHOOSE_TITLE,
    CREATE_WITH,
    GROUP_BUSINESS,
    GROUP_PRODUCTS,
    ChoiceVM,
    ProductChoicesVM,
)
from .catalog_gallery_state import CatalogGalleryState
from .catalog_state import CatalogState
from .post_card import viewable_src
from .ui import media_thumb, section, tone_badge
from .ui import tokens as T

__all__ = ["choose_button", "choose_view"]

S = CatalogChooseState
_TOUCH_MIN = "44px"
_THUMB_H = "6.5rem"
_NOTHING = "Todavía no hay fotos ni videos para elegir. Sube algunos y vuelve aquí."


def choose_button() -> rx.Component:
    """Shown when there is something to choose: a ready medium of the business or a
    product with photos."""
    return rx.cond(
        CatalogGalleryState.has_choosable | CatalogState.has_products,
        rx.button(
            rx.icon("list-checks", size=T.ICON_SM),
            CHOOSE_BUTTON,
            variant="soft",
            size="3",
            type="button",
            min_height=_TOUCH_MIN,
            width=rx.breakpoints(initial="100%", sm="auto"),
            on_click=S.start,
        ),
    )


def _picture(c: rx.Var[ChoiceVM]) -> rx.Component:
    return rx.cond(
        c.thumb != "",
        media_thumb(viewable_src(c.thumb), size=None, width="100%", height=_THUMB_H),
        rx.cond(
            c.video != "",
            rx.box(
                rx.el.video(
                    # the first frame stands in for a poster (a product video has none)
                    src=viewable_src(c.video) + "#t=0.1",
                    preload="metadata",
                    muted=True,
                    plays_inline=True,
                    aria_hidden="true",
                    width="100%",
                    height="100%",
                ),
                class_name="q-catalog-video",
                height=_THUMB_H,
                width="100%",
            ),
            media_thumb(
                "",
                has=rx.Var.create(False),
                size=None,
                width="100%",
                height=_THUMB_H,
                icon=rx.cond(c.media_type == "video", "film", "image"),
            ),
        ),
    )


def _tile(c: rx.Var[ChoiceVM]) -> rx.Component:
    on = c.order > 0
    return rx.el.button(
        rx.box(
            _picture(c),
            rx.cond(
                on,
                rx.box(
                    tone_badge(c.order.to_string(), "accent", size="2"),
                    position="absolute",
                    top="0.35rem",
                    left="0.35rem",
                    class_name="q-nums",
                ),
            ),
            rx.cond(
                c.duration != "",
                rx.box(
                    tone_badge(c.duration, "neutral", icon="film"),
                    position="absolute",
                    bottom="0.35rem",
                    right="0.35rem",
                    class_name="q-nums",
                ),
            ),
            position="relative",
            width="100%",
        ),
        type="button",
        role="checkbox",
        aria_checked=rx.cond(on, "true", "false"),
        aria_label=c.spoken,
        on_click=S.pick(c.token),
        class_name=rx.cond(on, "q-choice-card q-choice-card--on", "q-choice-card"),
        padding="0.3rem",
        min_width="0",
        key=c.token,
    )


def _grid(choices: rx.Var[list[ChoiceVM]]) -> rx.Component:
    return rx.box(
        rx.foreach(choices, _tile),
        display="grid",
        # three a row on a 360 px phone
        grid_template_columns="repeat(auto-fill, minmax(6.25rem, 1fr))",
        gap="0.5rem",
        width="100%",
    )


def _product_group(group: rx.Var[ProductChoicesVM]) -> rx.Component:
    return rx.vstack(
        rx.text(group.name, size="2", weight="medium"),
        _grid(group.choices),
        spacing="2",
        width="100%",
        key=group.name,
    )


def _bar() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(
                S.count_text,
                size="3",
                weight="medium",
                role="status",
                aria_live="polite",
                class_name="q-nums",
            ),
            rx.cond(
                S.error != "",
                rx.text(S.error, size="2", color=T.tone_color("warn", 11), role="alert"),
            ),
            align="center",
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
        rx.box(
            rx.button(
                rx.icon("sparkles", size=T.ICON_SM),
                CREATE_WITH,
                size="3",
                type="button",
                min_height=_TOUCH_MIN,
                width="100%",
                disabled=~S.has_chosen,
                on_click=S.create,
            ),
            rx.button(
                CANCEL,
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                size="3",
                type="button",
                min_height=_TOUCH_MIN,
                width="100%",
                on_click=S.cancel,
            ),
            display="grid",
            grid_template_columns=rx.breakpoints(
                initial="minmax(0, 1fr)", sm="minmax(0, 2fr) minmax(0, 1fr)"
            ),
            gap="0.5rem",
            width="100%",
        ),
        spacing="2",
        # the Creadores bar: opaque, above the phone's bottom bar, in the flow
        class_name="q-card",
        padding="0.75rem 1rem",
        background="var(--color-panel-solid)",
        position="sticky",
        bottom=(
            "calc(var(--q-bottom-bar-h, 0px) + 2 * var(--q-gap) + env(safe-area-inset-bottom, 0px))"
        ),
        width="100%",
        z_index="3",
    )


def choose_view() -> rx.Component:
    return rx.vstack(
        section(
            CHOOSE_TITLE,
            rx.cond(
                (S.business.length() == 0) & (S.products.length() == 0),
                rx.text(_NOTHING, size="2", color=T.TEXT_MUTED),
            ),
            description=CHOOSE_HELP,
        ),
        rx.cond(S.business.length() > 0, section(GROUP_BUSINESS, _grid(S.business))),
        rx.cond(
            S.products.length() > 0,
            section(
                GROUP_PRODUCTS,
                rx.vstack(
                    rx.foreach(S.products, _product_group),
                    spacing="4",
                    width="100%",
                ),
            ),
        ),
        _bar(),
        spacing="5",
        width="100%",
    )
