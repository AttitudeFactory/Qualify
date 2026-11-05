"""«Agrupa tus productos» (m-24955838): the notice and the two-step drawer.

Spec: `docs/ux-categorias-de-productos.md`. Only design-system pieces: `callout`,
`card`, `choice_card` (a real button: the whole 44 px row toggles a checkbox or picks a
category), `drawer` with `step_progress`, `tone_badge`. «Poner en…» opens inside the
drawer's foot — one drawer at a time, never nested (§5.8).
"""

from __future__ import annotations

import reflex as rx

from .catalog_group_state import CatalogGroupState
from .catalog_group_vm import (
    ALL_GROUPED,
    BACK_TO_GROUPS,
    DONE_HELP,
    FLOW_TITLE,
    GROUP_BUTTON,
    LEAVE_REST,
    NAME_HELP,
    NAME_LABEL,
    NAME_PLACEHOLDER,
    NEW_CATEGORY,
    NEW_CHOICE,
    NEXT,
    PUT_HERE,
    PUT_IN,
    RENAME,
    SKIP,
    STEP1_HELP,
    STEP1_TITLE,
    STEP2_HELP,
    STEP2_TITLE,
    STEP_DONE,
    STEP_GROUPS,
    STEP_LEFTOVERS,
    UNSKIP,
    GroupCardVM,
    LeftoverVM,
)
from .catalog_order_vm import BACK_TO_PRODUCTS, BACK_TO_WHATSAPP, ORDER_BUTTON
from .catalog_state import CatalogState
from .ui import callout, card, choice_card, choice_card_check, drawer, skeleton_rows, tone_badge
from .ui import tokens as T
from .ui.steps import step_progress

_G = CatalogGroupState
_TOUCH_MIN = "44px"
_BIG = {"size": "3", "min_height": _TOUCH_MIN}


def group_notice() -> rx.Component:
    """«Tienes N productos sin categoría…» + «Agruparlos», above «Tus productos» (only
    with 2 or more, and not after «Dejar el resto en «Otros»» until a new one appears)."""
    return rx.cond(
        CatalogState.group_notice_count > 0,
        rx.vstack(
            callout(CatalogState.group_notice_text, "warn", icon="layers"),
            rx.button(
                rx.icon("layers", size=T.ICON_SM),
                GROUP_BUTTON,
                type="button",
                on_click=_G.open_flow,
                width=rx.breakpoints(initial="100%", sm="auto"),
                **_BIG,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _name_field(
    value: rx.Var[str],
    on_change: object,
    counter: rx.Var[str],
    error: rx.Var[str],
    field_id: str,
) -> rx.Component:
    """«Nombre de la categoría», the 24-letter help, the counter and the problem."""
    return rx.vstack(
        rx.el.label(rx.text(NAME_LABEL, size="2", weight="medium"), html_for=field_id),
        rx.input(
            id=field_id,
            value=value,
            on_change=on_change,
            placeholder=NAME_PLACEHOLDER,
            size="3",
            width="100%",
            aria_describedby=f"{field_id}-help",
        ),
        rx.hstack(
            rx.text(NAME_HELP, size="1", color=T.TEXT_MUTED, id=f"{field_id}-help"),
            rx.spacer(),
            rx.text(counter, size="1", color=T.TEXT_MUTED, class_name="q-nums", flex_shrink="0"),
            width="100%",
            align="start",
        ),
        rx.cond(
            error != "",
            rx.text(error, size="2", color=T.tone_color("error", 11), role="alert"),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


# -- step 1 ---------------------------------------------------------------------------


def _group_card(group: rx.Var[GroupCardVM]) -> rx.Component:
    ghost = {"variant": "ghost", "size": "2", "min_height": _TOUCH_MIN, "type": "button"}
    return card(
        rx.vstack(
            rx.hstack(
                rx.text(group.name, size="3", weight="bold", min_width="0", truncate=True),
                rx.text("· ", group.count_label, size="2", color=T.TEXT_MUTED),
                rx.spacer(),
                rx.cond(
                    group.accepted,
                    rx.icon("check", size=T.ICON_MD, color=T.tone_color("ok", 11)),
                    tone_badge(SKIP, "neutral"),
                ),
                align="center",
                width="100%",
                spacing="2",
            ),
            rx.text(group.names_line, size="1", color=T.TEXT_MUTED),
            rx.cond(
                group.renaming,
                rx.vstack(
                    _name_field(
                        _G.rename_text,
                        _G.set_rename_text,
                        _G.rename_count,
                        _G.rename_error,
                        "q-group-rename",
                    ),
                    rx.hstack(
                        rx.button(
                            "Cancelar",
                            on_click=_G.cancel_rename,
                            **ghost,
                            **T.tone_scheme("neutral"),
                        ),
                        rx.button(
                            "Listo",
                            on_click=_G.save_rename,
                            size="2",
                            type="button",
                            min_height=_TOUCH_MIN,
                        ),
                        justify="end",
                        width="100%",
                        spacing="2",
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.hstack(
                    rx.cond(
                        group.accepted,
                        rx.fragment(
                            rx.button(
                                rx.icon("pencil", size=T.ICON_SM),
                                RENAME,
                                on_click=_G.start_rename(group.index),
                                aria_label=group.rename_label,
                                **ghost,
                            ),
                            rx.button(
                                SKIP,
                                on_click=_G.toggle_group(group.index),
                                aria_label=group.skip_label,
                                **ghost,
                                **T.tone_scheme("neutral"),
                            ),
                        ),
                        rx.button(
                            rx.icon("undo-2", size=T.ICON_SM),
                            UNSKIP,
                            on_click=_G.toggle_group(group.index),
                            **ghost,
                        ),
                    ),
                    spacing="3",
                    wrap="wrap",
                ),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="0.75rem 1rem",
        opacity=rx.cond(group.accepted, "1", "0.6"),
    )


def _step_groups() -> rx.Component:
    return rx.vstack(
        rx.heading(STEP1_TITLE, size="4", as_="h3"),
        rx.text(STEP1_HELP, size="2", color=T.TEXT_MUTED),
        rx.foreach(_G.cards, _group_card),
        spacing="3",
        width="100%",
        align_items="start",
    )


# -- step 2 ---------------------------------------------------------------------------


def _leftover_row(row: rx.Var[LeftoverVM]) -> rx.Component:
    return choice_card(
        rx.hstack(
            rx.icon(
                rx.cond(row.checked, "square-check", "square"),
                size=T.ICON_MD,
                color=rx.cond(row.checked, T.tone_color("info", 11), T.TEXT_MUTED),
                flex_shrink="0",
            ),
            rx.text(row.name, size="2", min_width="0", truncate=True),
            rx.spacer(),
            rx.text(row.price_label, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
            align="center",
            width="100%",
            spacing="2",
        ),
        selected=row.checked,
        on_select=_G.toggle_leftover(row.product_id),
        role="checkbox",
        padding="0.5rem 0.75rem",
        min_height=_TOUCH_MIN,
        width="100%",
        key=row.product_id,
    )


def _step_leftovers() -> rx.Component:
    return rx.vstack(
        rx.cond(
            _G.with_groups,
            rx.button(
                rx.icon("chevron-left", size=T.ICON_SM),
                BACK_TO_GROUPS,
                on_click=_G.back_to_groups,
                variant="ghost",
                size="2",
                min_height=_TOUCH_MIN,
                type="button",
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.heading(STEP2_TITLE, size="4", as_="h3"),
        rx.text(STEP2_HELP, size="2", color=T.TEXT_MUTED),
        rx.vstack(
            rx.foreach(_G.leftovers, _leftover_row),
            spacing="2",
            width="100%",
            role="group",
            aria_label=STEP2_TITLE,
        ),
        rx.button(
            LEAVE_REST,
            on_click=_G.leave_rest,
            variant="soft",
            disabled=_G.busy,
            type="button",
            width="100%",
            **_BIG,
            **T.tone_scheme("neutral"),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _category_choice(name: rx.Var[str]) -> rx.Component:
    selected = _G.sheet_choice == name
    return choice_card(
        rx.hstack(
            rx.text(name, size="2", weight="medium"),
            rx.spacer(),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            align="center",
            width="100%",
        ),
        selected=selected,
        on_select=_G.set_sheet_choice(name),
        padding="0.5rem 0.75rem",
        min_height=_TOUCH_MIN,
        width="100%",
    )


def _put_sheet() -> rx.Component:
    """«Poner en…»: the brand's categories and «+ Nueva categoría», then «Poner aquí»."""
    new_selected = _G.sheet_choice == NEW_CHOICE
    return rx.vstack(
        rx.text(PUT_IN, size="2", weight="bold"),
        rx.vstack(
            rx.foreach(_G.categories, _category_choice),
            choice_card(
                rx.hstack(
                    rx.text(NEW_CATEGORY, size="2", weight="medium"),
                    rx.spacer(),
                    rx.cond(new_selected, choice_card_check(), rx.fragment()),
                    align="center",
                    width="100%",
                ),
                selected=new_selected,
                on_select=_G.set_sheet_choice(NEW_CHOICE),
                padding="0.5rem 0.75rem",
                min_height=_TOUCH_MIN,
                width="100%",
            ),
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label=PUT_IN,
            max_height="min(40vh, 18rem)",
            overflow_y="auto",
        ),
        rx.cond(
            new_selected,
            _name_field(
                _G.sheet_new, _G.set_sheet_new, _G.sheet_count, _G.sheet_error, "q-group-new"
            ),
            rx.cond(
                _G.sheet_error != "",
                rx.text(_G.sheet_error, size="2", color=T.tone_color("error", 11), role="alert"),
            ),
        ),
        rx.hstack(
            rx.button(
                "Cancelar",
                on_click=_G.close_sheet,
                variant="soft",
                type="button",
                **_BIG,
                **T.tone_scheme("neutral"),
            ),
            rx.button(PUT_HERE, on_click=_G.put_here, type="button", **_BIG),
            justify="end",
            width="100%",
            spacing="2",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


# -- the end ----------------------------------------------------------------------------


def _step_done() -> rx.Component:
    back = rx.button(
        rx.cond(_G.returning, BACK_TO_WHATSAPP, BACK_TO_PRODUCTS),
        on_click=_G.close_flow,
        variant="soft",
        type="button",
        width="100%",
        **_BIG,
        **T.tone_scheme("neutral"),
    )
    order = rx.button(
        rx.icon("arrow-up-down", size=T.ICON_SM),
        ORDER_BUTTON,
        on_click=_G.go_order,
        type="button",
        width="100%",
        **_BIG,
    )
    return rx.vstack(
        rx.cond(
            _G.all_grouped,
            rx.text(ALL_GROUPED, size="3", weight="medium"),
            rx.vstack(
                rx.heading(_G.done_text, size="4", as_="h3"),
                rx.text(DONE_HELP, size="2", color=T.TEXT_MUTED),
                spacing="1",
                width="100%",
                align_items="start",
            ),
        ),
        order,
        back,
        spacing="3",
        width="100%",
        align_items="start",
    )


def _footer() -> rx.Component:
    return rx.match(
        _G.step,
        (
            STEP_GROUPS,
            rx.vstack(
                rx.cond(_G.left_text != "", rx.text(_G.left_text, size="2", color=T.TEXT_MUTED)),
                rx.hstack(
                    rx.spacer(),
                    rx.button(
                        NEXT,
                        rx.icon("arrow-right", size=T.ICON_SM),
                        on_click=_G.store_groups,
                        loading=_G.busy,
                        disabled=_G.loading,
                        type="button",
                        **_BIG,
                    ),
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        (
            STEP_LEFTOVERS,
            rx.cond(
                _G.sheet_open,
                _put_sheet(),
                rx.hstack(
                    rx.text(_G.chosen_text, size="2", class_name="q-nums", aria_live="polite"),
                    rx.spacer(),
                    rx.button(
                        PUT_IN,
                        on_click=_G.open_sheet,
                        disabled=~_G.has_checked | _G.busy,
                        loading=_G.busy,
                        type="button",
                        **_BIG,
                    ),
                    align="center",
                    width="100%",
                ),
            ),
        ),
        rx.fragment(),
    )


def group_drawer() -> rx.Component:
    return drawer(
        rx.vstack(
            rx.cond(_G.error != "", callout(_G.error, "error")),
            rx.cond(
                _G.loading,
                skeleton_rows(rows=4, height="5rem"),
                rx.match(
                    _G.step,
                    (STEP_GROUPS, _step_groups()),
                    (STEP_LEFTOVERS, _step_leftovers()),
                    (STEP_DONE, _step_done()),
                    _step_groups(),
                ),
            ),
            spacing="3",
            width="100%",
        ),
        open=_G.open,
        on_open_change=_G.set_open,
        title=FLOW_TITLE,
        step=rx.cond(
            _G.with_groups & (_G.step != STEP_DONE),
            step_progress(_G.step_number, _G.step_total),
            rx.fragment(),
        ),
        footer=_footer(),
        width="34rem",
        icon="layers",
    )
