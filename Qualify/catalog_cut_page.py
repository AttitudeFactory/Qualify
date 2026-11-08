"""«Corta tu video en partes» — the cutter drawer of Galería (CM-4, m-24955924).

Built only from the design system: `ui.drawer` (the whole screen on a phone, Esc / the ×
/ the backdrop = «Cancelar»), the catalog tile's video frame (`.q-catalog-video`),
`callout`, `tone_badge`, the choice-card material for the part rows, Radix's slider for
the line and the same alert dialogs as «Quitar». One decision per step, in the order the
epic gives: move the line → «Cortar aquí» → pick a part → «Quitar esta parte» →
«Guardar partes». Phone first (360 px): «Cortar aquí» is the first button of the fixed
footer (the thumb's reach), «Atrás» / «Adelante» and every part row are 44 px, every
action is a word.

m-24976806: after «Guardar» the drawer stays, on a waiting step read from the cut's job
(`CatalogGalleryState.panel_*`): `progress_panel` with the stage (en cola → cortando →
guardando) and «Puedes salir…» («Seguir en Galería»), then «Listo: tu video quedó en N
partes.» with the parts («Entendido»), or the failure with «Intentar de nuevo».
"""

from __future__ import annotations

import reflex as rx

from .catalog_cut_state import (
    ENDED_ID,
    PAUSE_JS,
    PLAY_JS,
    TICK_ID,
    TIME_JS,
    VIDEO_ID,
    CatalogCutState,
)
from .catalog_cut_vm import (
    CANCEL,
    CUT_DONE_DISMISS,
    CUT_HELP,
    CUT_HERE,
    CUT_TITLE,
    FRAME_MS,
    KEEP_BROWSING,
    LEAVE_DISCARD,
    LEAVE_TITLE,
    MIN_PART_HINT,
    NEXT_FRAME,
    PAUSE,
    PICK_PART_HINT,
    PLAY,
    PREV_FRAME,
    REMOVE_PART,
    SAVE,
    SAVE_PARTS,
    STAY,
    UNDO,
    WAITING_TITLE,
    PartRow,
    TimelineBlock,
)
from .catalog_gallery_state import CatalogGalleryState
from .catalog_gallery_vm import CUT_RETRY
from .post_card import viewable_src
from .ui import callout, drawer, loading_spinner, media_thumb, progress_panel, tone_badge
from .ui import tokens as T

__all__ = ["cut_dialogs", "cut_drawer", "cut_part_thumbs"]

C = CatalogCutState
G = CatalogGalleryState
_TOUCH_MIN = "44px"
_BIG = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}
#: Three to a row at 360 px: a size smaller, still 44 px tall.
_ROW = {
    "size": "2",
    "min_height": _TOUCH_MIN,
    "width": "100%",
    "padding_x": "0.4rem",
    # a larger system font wraps the word instead of cutting it (UX review)
    "white_space": "normal",
    "line_height": "1.2",
}


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
            aria_label="Así se ve tu video donde está la línea",
            width="100%",
            height="100%",
        ),
        # what the playing video clicks: a tick (the line follows it) and its end
        rx.el.button(
            id=TICK_ID,
            type="button",
            hidden=True,
            tab_index=-1,
            aria_hidden="true",
            on_click=rx.call_script(TIME_JS, callback=C.follow),
        ),
        rx.el.button(
            id=ENDED_ID,
            type="button",
            hidden=True,
            tab_index=-1,
            aria_hidden="true",
            on_click=C.playback_ended,
        ),
        class_name="q-catalog-video",
        height="min(30vh, 15rem)",
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
                # inside the bar at both ends (at 0:00 it used to be cut by the edge)
                left=f"clamp(1.6rem, {C.playhead_left}, calc(100% - 1.6rem))",
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
            # Uncontrolled while the finger drags (a server round trip never pulls the
            # thumb back); «Atrás» / «Adelante» move it by remounting it at the new
            # place (`line_key`).
            default_value=[C.playhead_ms],
            key=C.line_key,
            min=0,
            max=C.duration_ms,
            step=FRAME_MS,
            # a drag sends at most one move per 80 ms (a slow phone line never queues a
            # backlog); the release always lands exactly where the finger stopped
            on_change=C.move_line.throttle(80),
            on_value_commit=C.move_line,
            size="3",
            width="100%",
            aria_label="Línea de corte",
        ),
        # «‹ Atrás · Reproducir · Adelante ›»: one frame each way, and watching (with
        # sound) from the line; «Pausar» puts the line where the video stopped
        rx.box(
            rx.button(
                rx.icon("chevron-left", size=T.ICON_SM),
                PREV_FRAME,
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                type="button",
                on_click=C.nudge(-1),
                **_ROW,
            ),
            rx.cond(
                C.playing,
                rx.button(
                    rx.icon("pause", size=T.ICON_SM),
                    PAUSE,
                    variant="soft",
                    type="button",
                    on_click=rx.call_script(PAUSE_JS, callback=C.paused_at),
                    **_ROW,
                ),
                rx.button(
                    rx.icon("play", size=T.ICON_SM),
                    PLAY,
                    variant="soft",
                    type="button",
                    on_click=[rx.call_script(PLAY_JS), C.started],
                    **_ROW,
                ),
            ),
            rx.button(
                NEXT_FRAME,
                rx.icon("chevron-right", size=T.ICON_SM),
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                type="button",
                on_click=C.nudge(1),
                **_ROW,
            ),
            display="grid",
            grid_template_columns="repeat(3, minmax(0, 1fr))",
            gap="0.5rem",
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
        rx.box(
            rx.button(
                rx.icon("undo-2", size=T.ICON_SM),
                UNDO,
                variant="soft",
                color_scheme=T.tone_scale("neutral"),
                type="button",
                disabled=~C.can_undo,
                on_click=C.undo,
                **_ROW,
            ),
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                REMOVE_PART,
                variant="soft",
                type="button",
                disabled=~C.has_selection,
                on_click=C.remove_selected,
                **T.tone_scheme("error"),
                **_ROW,
            ),
            display="grid",
            grid_template_columns="minmax(0, 1fr) minmax(0, 1.4fr)",
            gap="0.5rem",
            width="100%",
        ),
        rx.cond(
            ~C.has_selection & (C.rows.length() > 0),
            rx.text(PICK_PART_HINT, size="1", color=T.TEXT_MUTED),
        ),
        spacing="2",
        width="100%",
    )


def _footer() -> rx.Component:
    """Fixed at the bottom: why «Guardar partes» waits (always in view at 360 px, UX
    review), then «Cortar aquí» under the thumb, then «Cancelar» / «Guardar partes»."""
    return rx.vstack(
        rx.cond(
            C.error != "",
            rx.text(C.error, size="2", color=T.tone_color("warn", 11), role="alert"),
            # what the last move did, then (always) why «Guardar partes» waits
            rx.vstack(
                rx.cond(
                    C.notice != "",
                    rx.text(C.notice, size="2", color=T.TEXT_MUTED, role="status"),
                ),
                rx.cond(
                    C.blocker != "",
                    rx.text(C.blocker, size="2", color=T.TEXT_MUTED, role="status"),
                ),
                spacing="1",
                width="100%",
            ),
        ),
        rx.button(
            rx.icon("scissors", size=T.ICON_SM),
            CUT_HERE,
            type="button",
            # pauses first and cuts at the frame on screen when the video was playing
            on_click=rx.call_script(PAUSE_JS, callback=C.cut_here),
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
                # no icon: «Guardar partes» fits on one line at 360 px
                rx.cond(C.saving, loading_spinner("sm")),
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


def cut_part_thumbs(urls: rx.Var[list[str]]) -> rx.Component:
    """The parts a cut saved, in order (also the cutter's «Listo» step)."""
    return rx.box(
        rx.foreach(
            urls,
            lambda url: media_thumb(
                viewable_src(url), has=url != "", size="4.5rem", icon="clapperboard"
            ),
        ),
        display="flex",
        flex_wrap="wrap",
        gap="0.5rem",
        role="list",
        aria_label="Tus partes",
    )


def _waiting() -> rx.Component:
    """The cut after «Guardar»: its stage while it runs, then how it ended."""
    return rx.match(
        G.panel_phase,
        (
            "done",
            rx.vstack(
                callout(G.panel_title, "ok"),
                cut_part_thumbs(G.panel_thumbs),
                spacing="3",
                width="100%",
                padding_y="1rem",
            ),
        ),
        (
            "failed",
            rx.vstack(
                callout(G.panel_title, "error"),
                rx.cond(
                    (G.retry_error != "") & (G.retry_for == G.panel_job),
                    rx.text(G.retry_error, size="2", role="alert"),
                ),
                spacing="3",
                width="100%",
                padding_y="1rem",
            ),
        ),
        rx.vstack(
            # which video (UX review: the step was a lone grey line on a phone)
            media_thumb(
                rx.cond(C.poster_url != "", viewable_src(C.poster_url), ""),
                has=C.poster_url != "",
                size="7rem",
                icon="clapperboard",
                margin_top="1.5rem",
            ),
            progress_panel(G.panel_title, steps=G.panel_steps, creep_seconds=60),
            # «Puedes salir; tus partes aparecerán en tu Galería.»
            rx.text(G.panel_detail, size="2", color=T.TEXT_MUTED, text_align="center"),
            align="center",
            spacing="0",
            width="100%",
        ),
    )


def _waiting_footer() -> rx.Component:
    return rx.match(
        G.panel_phase,
        (
            "done",
            rx.button(
                rx.icon("check", size=T.ICON_SM),
                CUT_DONE_DISMISS,
                type="button",
                on_click=C.finish_waiting,
                **_BIG,
            ),
        ),
        (
            "failed",
            rx.box(
                # the way forward first (on top at 360 px, where the two stack)
                rx.button(
                    rx.cond(
                        G.retrying, loading_spinner("sm"), rx.icon("rotate-ccw", size=T.ICON_SM)
                    ),
                    CUT_RETRY,
                    type="button",
                    on_click=G.retry_cut(G.panel_job),
                    disabled=G.retrying,
                    **_BIG,
                ),
                rx.button(
                    # not «Cerrar»: the drawer's × already says it (one name, one button)
                    KEEP_BROWSING,
                    variant="soft",
                    color_scheme=T.tone_scale("neutral"),
                    type="button",
                    on_click=C.leave_waiting,
                    disabled=G.retrying,
                    **_BIG,
                ),
                display="grid",
                grid_template_columns=rx.breakpoints(
                    initial="minmax(0, 1fr)", sm="repeat(2, minmax(0, 1fr))"
                ),
                gap="0.75rem",
                width="100%",
            ),
        ),
        rx.button(
            rx.icon("images", size=T.ICON_SM),
            KEEP_BROWSING,
            variant="soft",
            type="button",
            on_click=C.leave_waiting,
            **_BIG,
        ),
    )


def cut_drawer() -> rx.Component:
    editor = rx.vstack(
        _preview(),
        rx.text(CUT_HELP, size="2", color=T.TEXT_MUTED),
        # m-24976897: the minimum before the first cut, not only after a refusal
        rx.text(MIN_PART_HINT, size="2", color=T.TEXT_MUTED),
        _timeline(),
        _parts(),
        spacing="4",
        width="100%",
        padding_bottom="1rem",
    )
    return drawer(
        rx.cond(C.waiting, _waiting(), editor),
        open=C.open,
        on_open_change=C.set_open,
        # nothing is cut by hand any more on the waiting step: its own title
        title=rx.cond(C.waiting, WAITING_TITLE, CUT_TITLE),
        icon="scissors",
        footer=rx.cond(C.waiting, _waiting_footer(), _footer()),
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
            "",
            open_=C.leave_open,
            on_open_change=C.set_leave_open,
            stay=C.stay,
            go_label=LEAVE_DISCARD,
            go=C.discard,
            tone="error",
        ),
    )
