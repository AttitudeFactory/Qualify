"""«Tu Galería» — a tab of the generator's media drawer (m-24985141).

Design system only: `section` for «De tu negocio» / «De tus productos», CM-5's tiles
(`catalog_choose_page.choice_grid` — a real ``<button role="checkbox">`` with its number),
`callout`, `skeleton_rows` while it reads. Inside the drawer, «Agregar» is the drawer's own
foot (`gallery_add_bar`); `inline=<slot>` (a sheet that is already a drawer, UI-4) carries
the same bar under the tiles instead — one drawer at a time, never nested.
"""

from __future__ import annotations

import reflex as rx

from .catalog_choose_page import choice_grid, product_choice_group
from .catalog_choose_vm import GROUP_BUSINESS, GROUP_PRODUCTS
from .gen_gallery_pick_state import GenGalleryPickState
from .gen_gallery_pick_vm import COUNT_ID, EMPTY
from .ui import callout, section, skeleton_rows
from .ui import tokens as T

__all__ = ["gallery_add_bar", "gallery_tab"]

S = GenGalleryPickState
_TOUCH_MIN = "44px"


def gallery_tab(*, inline: str = "") -> rx.Component:
    """«Tu Galería». `inline`: the slot of an in-line selector (a part's sheet, UI-4),
    which carries its own «Agregar»; "" inside the media drawer (its foot has it)."""

    def pick(token: rx.Var[str]) -> object:
        return S.pick(token, inline)

    body = rx.cond(
        S.loading & ~S.loaded,
        skeleton_rows(rows=3, height="6.5rem"),
        rx.vstack(
            # not a dead end: where to put photos in (UX review)
            rx.cond(S.empty, rx.text(EMPTY, size="2", color=T.TEXT_MUTED)),
            rx.cond(
                S.business.length() > 0,
                section(GROUP_BUSINESS, choice_grid(S.business, pick)),
            ),
            rx.cond(
                S.products.length() > 0,
                section(
                    GROUP_PRODUCTS,
                    rx.vstack(
                        rx.foreach(S.products, lambda g: product_choice_group(g, pick)),
                        spacing="4",
                        width="100%",
                    ),
                ),
            ),
            spacing="4",
            width="100%",
        ),
    )
    if not inline:
        return body
    return rx.vstack(
        body,
        # in line, only once something is chosen (there is no drawer to close: «Listo»
        # would do nothing); an error still shows
        rx.cond(
            S.chosen.length() > 0,
            gallery_add_bar(rx.Var.create(""), target=inline),
            rx.cond(S.error != "", callout(S.error, "warn")),
        ),
        spacing="3",
        width="100%",
    )


def gallery_add_bar(summary: rx.Var[str], *, target: str = "") -> rx.Component:
    """What went wrong right above the button, where the eye is; then the live count
    (what is chosen in «Tu Galería», else what the slot holds — `summary`) and
    «Agregar», described by that count. «Agregar» closes the drawer."""
    count_id = f"{COUNT_ID}-{target}" if target else COUNT_ID
    return rx.vstack(
        rx.cond(S.error != "", rx.box(callout(S.error, "warn"), role="alert", width="100%")),
        rx.hstack(
            rx.text(
                rx.cond(S.count_text != "", S.count_text, summary),
                size="2",
                weight="medium",
                role="status",
                aria_live="polite",
                class_name="q-nums",
                id=count_id,
                flex="1",
                min_width="0",
            ),
            rx.button(
                rx.icon("check", size=T.ICON_SM),
                S.add_text,
                size="3",
                type="button",
                min_height=_TOUCH_MIN,
                loading=S.adding,
                on_click=S.finish(target),
                custom_attrs={"aria-describedby": count_id},
            ),
            align="center",
            width="100%",
            spacing="3",
        ),
        spacing="2",
        width="100%",
    )
