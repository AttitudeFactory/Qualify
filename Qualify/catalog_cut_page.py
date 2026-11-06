"""«Corta tu video en partes» — the cutter drawer of Galería (CM-4, m-24955924).

Built only from the design system: `ui.drawer` (the whole screen on a phone, Esc / the ×
/ the backdrop = «Cancelar»), the catalog tile's video frame (`.q-catalog-video`),
`callout`, `tone_badge`, the choice-card material for the part rows, Radix's slider for
the line and the same alert dialogs as «Quitar». One decision per step, in the order the
epic gives: move the line → «Cortar aquí» → pick a part → «Quitar esta parte» →
«Guardar partes». Phone first (360 px): «Cortar aquí» is the first button of the fixed
footer (the thumb's reach), «Atrás» / «Adelante» and every part row are 44 px, every
action is a word.
"""

from __future__ import annotations

import reflex as rx

from .catalog_cut_state import VIDEO_ID, CatalogCutState
from .catalog_cut_vm import (
    CANCEL,
    CUT_HELP,
    CUT_HERE,
    CUT_TITLE,
    LEAVE_DISCARD,
    LEAVE_TEXT,
    LEAVE_TITLE,
    NEXT_FRAME,
    PREV_FRAME,
    REMOVE_PART,
    REMOVE_PART_CONFIRM,
    REMOVE_PART_TITLE,
    SAVE,
    SAVE_PARTS,
    STAY,
    PartRow,
    TimelineBlock,
)
from .post_card import viewable_src
from .ui import callout, drawer, loading_spinner, tone_badge
from .ui import tokens as T

__all__ = ["cut_dialogs", "cut_drawer"]

C = CatalogCutState
_TOUCH_MIN = "44px"
_BIG = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}


def _preview() -> rx.Component:
    """The frame under the line (no native controls: the line is the one control)."""
    return rx.box(
        rx.el.video(
            id=VIDEO_ID,
            src=viewable_src(C.video_url),
            poster=rx.cond(C.poster_url != "", viewable_src(C.poster_url), ""),
            preload="auto",
            muted=True,
            plays_inline=True,
            aria_label="Vista del video en la línea",
            width="100%",
            height="100%",
        ),
        class_name="q-catalog-video",
        height="min(40vh, 18rem)",
        width="100%",
    )


def _block(block: rx.Var[TimelineBlock]) -> rx.Component:
    return rx.box(
        rx.cond(
            block.keep,
            rx.text(block.part, size="1", weight="medium", class_name="q-nums"),
        ),
        position="absolute",
        top="0",
        bottom="0",
        left=block.left,
        width=block.width,
        display="flex",
        align_items="center",
        justify_content="center",
        border_radius="var(--q-radius-control)",
        background=rx.cond(
            block.keep,
            rx.cond(block.selected, T.tone_color("accent", 6), T.tone_color("accent", 4)),
            "transparent",
        ),
        border=rx.cond(block.keep, "1px solid transparent", f"1px dashed {T.TEXT_FAINT}"),
        color=T.tone_color("accent", 11),
        overflow="hidden",
    )


def _timeline() -> rx.Component:
    """The parts as blocks (a removed one is an empty dashed gap), the line where the
    owner is, the time beside it, and the slider that moves it."""
    return rx.vstack(
        rx.box(
            rx.box(
                rx.text(C.playhead_text, size="1", weight="medium", class_name="q-nums"),
                position="absolute",
                top="-1.6rem",
                left=C.playhead_left,
                transform="translateX(-50%)",
                white_space="nowrap",
                aria_hidden="true",
            ),
            rx.foreach(C.blocks, _block),
            rx.box(
                position="absolute",
                top="-0.25rem",
                bottom="-0.25rem",
                left=C.playhead_left,
                width="2px",
                transform="translateX(-1px)",
                background=T.tone_color("accent", 9),
                aria_hidden="true",
            ),
            position="relative",
            height="2.5rem",
            width="100%",
            margin_top="1.75rem",
        ),
        rx.slider(
            value=[C.playhead_ms],
            min=0,
            max=C.duration_ms,
            step=33,
            on_change=C.move_line,
            size="3",
            width="100%",
            aria_label="Línea de corte",
        ),
        rx.box(
            rx.button(
                rx.icon("chevron-left", size=T.ICON_SM),
                PREV_FRAME,
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                type="button",
                on_click=C.nudge(-1),
                **_BIG,
            ),
            rx.button(
                NEXT_FRAME,
                rx.icon("chevron-right", size=T.ICON_SM),
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                type="button",
                on_click=C.nudge(1),
                **_BIG,
            ),
            display="grid",
            grid_template_columns="repeat(2, minmax(0, 1fr))",
            gap="0.75rem",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _part_row(row: rx.Var[PartRow]) -> rx.Component:
    on = C.selected == row.index
    return rx.el.button(
        rx.hstack(
            rx.text(row.label, size="3", weight="medium", class_name="q-nums"),
            rx.spacer(),
            rx.cond(row.too_short, tone_badge("Menos de 3 segundos", "warn", icon="clock")),
            align="center",
            width="100%",
            wrap="wrap",
            row_gap="0.35rem",
        ),
        type="button",
        role="radio",
        aria_checked=rx.cond(on, "true", "false"),
        aria_label=row.spoken,
        on_click=C.select_part(row.index),
        class_name=rx.cond(on, "q-choice-card q-choice-card--on", "q-choice-card"),
        min_height=_TOUCH_MIN,
        padding="0.6rem 0.9rem",
        width="100%",
        key=row.label,
    )


def _parts() -> rx.Component:
    return rx.vstack(
        rx.box(
            rx.foreach(C.rows, _part_row),
            role="radiogroup",
            aria_label="Partes de tu video",
            display="flex",
            flex_direction="column",
            gap="0.5rem",
            width="100%",
        ),
        rx.button(
            rx.icon("trash-2", size=T.ICON_SM),
            REMOVE_PART,
            variant="soft",
            type="button",
            disabled=~C.has_selection,
            on_click=C.ask_remove_part,
            **T.tone_scheme("error"),
            **_BIG,
        ),
        rx.cond(
            ~C.has_selection,
            rx.text("Toca una parte para elegirla.", size="1", color=T.TEXT_MUTED),
        ),
        spacing="2",
        width="100%",
    )


def _footer() -> rx.Component:
    return rx.vstack(
        rx.button(
            rx.icon("scissors", size=T.ICON_SM),
            CUT_HERE,
            type="button",
            on_click=C.cut_here,
            disabled=C.saving,
            **_BIG,
        ),
        rx.box(
            rx.button(
                CANCEL,
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                type="button",
                on_click=C.request_close,
                disabled=C.saving,
                **_BIG,
            ),
            rx.button(
                rx.cond(C.saving, loading_spinner("sm"), rx.icon("check", size=T.ICON_SM)),
                SAVE_PARTS,
                variant="soft",
                type="button",
                on_click=C.ask_save,
                disabled=C.saving | (C.blocker != ""),
                **_BIG,
            ),
            display="grid",
            grid_template_columns="repeat(2, minmax(0, 1fr))",
            gap="0.75rem",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def cut_drawer() -> rx.Component:
    return drawer(
        rx.vstack(
            _preview(),
            rx.text(CUT_HELP, size="2", color=T.TEXT_MUTED),
            _timeline(),
            rx.cond(C.error != "", callout(C.error, "warn")),
            _parts(),
            rx.cond(
                (C.blocker != "") & (C.error == ""),
                rx.text(C.blocker, size="2", color=T.TEXT_MUTED, role="status"),
            ),
            spacing="4",
            width="100%",
            padding_bottom="1rem",
        ),
        open=C.open,
        on_open_change=C.set_open,
        title=CUT_TITLE,
        icon="scissors",
        footer=_footer(),
    )


def _question(
    title: str | rx.Var,
    text: str,
    *,
    open_: rx.Var[bool],
    on_open_change: object,
    stay: object,
    go_label: str,
    go: object,
    tone: str,
) -> rx.Component:
    """The system's confirmation: «Volver» first and on Esc, the verb second; stacked
    full width on a phone."""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(title),
            *([rx.alert_dialog.description(text, size="2")] if text else []),
            rx.box(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=T.ICON_SM),
                        STAY,
                        variant="soft",
                        color_scheme=T.tone_scale("neutral"),
                        type="button",
                        on_click=stay,
                        **_BIG,
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(go_label, type="button", on_click=go, **T.tone_scheme(tone), **_BIG),
                ),
                display="grid",
                grid_template_columns=rx.breakpoints(
                    initial="minmax(0, 1fr)", sm="repeat(2, minmax(0, 1fr))"
                ),
                gap="0.75rem",
                margin_top="1.25rem",
                width="100%",
            ),
            max_width="28rem",
        ),
        open=open_,
        on_open_change=on_open_change,
    )


def cut_dialogs() -> rx.Component:
    return rx.fragment(
        _question(
            REMOVE_PART_TITLE,
            "",
            open_=C.remove_open,
            on_open_change=C.set_remove_open,
            stay=C.set_remove_open(False),
            go_label=REMOVE_PART_CONFIRM,
            go=C.confirm_remove_part,
            tone="error",
        ),
        _question(
            C.save_question,
            "",
            open_=C.save_open,
            on_open_change=C.set_save_open,
            stay=C.set_save_open(False),
            go_label=SAVE,
            go=C.confirm_save,
            tone="accent",
        ),
        _question(
            LEAVE_TITLE,
            LEAVE_TEXT,
            open_=C.leave_open,
            on_open_change=C.set_leave_open,
            stay=C.stay,
            go_label=LEAVE_DISCARD,
            go=C.discard,
            tone="error",
        ),
    )
