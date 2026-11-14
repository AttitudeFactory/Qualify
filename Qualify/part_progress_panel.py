"""How the parts of a video by parts are doing (m-24921082, UI-7; m-25016656).

`part_progress_panel(parent_id)` mounts the screen's ONE poll (`PartProgressState.poll`)
and stops it on unmount. Nothing renders while the parent has no parts to show.

m-25016656 (Deivid, «Sí, opción A» / «En los dos» — /create and /drafts alike): ONE
status line («Creando tus partes: 2 de 3», «Tus 3 partes están creadas»…) and only the
rows that wait for the owner's decision, open with their buttons. No bar, no big title,
no «Ver las N partes». The panel stays mounted with no row on screen: it is the screen's
only poll and holds its ONE `aria-live="polite"` region (`PartProgressState.announce`,
read by screen readers only). Only the design system (`Qualify/ui/`): `callout`, `card`,
`signal_pill` (word + tone, never colour alone) — one pill per row, no arrows.

m-24992894: a row «Para revisar» or «Lista» with a vista previa shows it on its left —
`ui.clip_player`, 9:16, 4.5rem wide, its length under it («4 s») — played in place on
tap; the other rows are exactly as before. Watching only: the decision buttons are
UI-8's.
"""

from __future__ import annotations

import reflex as rx

from .final_video_card_state import FinalVideoState
from .part_progress_state import STATUS_ID
from .part_progress_state import PartProgressState as S
from .part_progress_vm import (
    REMOVE_CONFIRM_NO,
    REMOVE_CONFIRM_YES,
    STATUS_CLOSED_MANY,
    STATUS_CLOSED_ONE,
)
from .r2_media import BACKEND_BASE
from .ui import tokens as T
from .ui.clip_player import clip_player, clip_player_renew, clip_player_script
from .ui.primitives import callout, card, signal_pill

#: The tones a row's pill can take (`part_progress_vm.STATE_TONES`).
_TONES = ("ok", "warn", "error", "info", "neutral")


def _pill(word: rx.Var, tone: rx.Var) -> rx.Component:
    """`signal_pill` takes its tone at build time: one branch per tone."""
    return rx.match(
        tone,
        *[(t, signal_pill(word, t)) for t in _TONES if t != "neutral"],
        signal_pill(word, "neutral"),
    )


#: Visually hidden, still read (the usual «sr-only» rules, inline: no new primitive).
_SR_ONLY = {
    "position": "absolute",
    "width": "1px",
    "height": "1px",
    "padding": "0",
    "margin": "-1px",
    "overflow": "hidden",
    "clip": "rect(0, 0, 0, 0)",
    "clip_path": "inset(50%)",
    "white_space": "nowrap",
    "border": "0",
}


def _closed_here(parent_id: rx.Var[str] | str) -> rx.Var[bool]:
    """The video of THIS panel is approved (or purged): «Tu video completo» read it.
    `FinalVideoState` keeps the last video it read — a failed parent's page mounts the
    panel without the card, so another video's `closed` must never count here."""
    return FinalVideoState.closed & (FinalVideoState.parent_id == parent_id)


def _joining_here(parent_id: rx.Var[str] | str) -> rx.Var[bool]:
    """THIS panel's video is being joined («Tu video completo» read it so)."""
    return FinalVideoState.wants_refresh & (FinalVideoState.parent_id == parent_id)


def _shows_decisions(parent_id: rx.Var[str] | str) -> rx.Var[bool]:
    """The rows that wait for a decision are drawn: there are some, and this panel's
    video is not closed (an approved video is only to watch)."""
    return (S.decision_rows.length() > 0) & ~_closed_here(parent_id)


def _status(parent_id: rx.Var[str] | str) -> rx.Component:
    """The panel's one line: what the video waits for now (m-25016656)."""
    # `tabIndex=-1`: where the keyboard lands once a row's action went through and the
    # row is about to go (`PartProgressState.FOCUS_STATUS_JS`)
    count = S.rows.length()
    before, after = STATUS_CLOSED_MANY.split("{total}")
    closed_line = rx.cond(count == 1, STATUS_CLOSED_ONE, before + count.to_string() + after)
    return rx.text(
        # an approved video's parts are only to watch: never «Falta que decidas…»
        rx.cond(_closed_here(parent_id), closed_line, S.status_line),
        id=STATUS_ID,
        tab_index=-1,
        size="3",
        weight="medium",
        width="100%",
    )


def _live_region() -> rx.Component:
    """The screen's ONE polite region: «La parte 3 está lista.» — never the first read."""
    return rx.box(S.announce, aria_live="polite", style=_SR_ONLY)


def _notice() -> rx.Component:
    """The purged-files notice, said once on top. `callout` gives every non-error tone
    `role="status"` (an implicit polite live region); here it is a plain `note` so the
    screen keeps ONE live region (`ui/primitives.py` untouched)."""
    notice = callout(S.notice, "warn")
    notice.role = rx.Var.create("note")
    return notice


def _button(button: rx.Var, row: rx.Var) -> rx.Component:
    return rx.button(
        button.label,
        # «Quitar parte» asks first when its row carries a question (m-24985192)
        on_click=rx.cond(
            button.action == "remove",
            S.ask_remove(row.index),
            S.run_part_action(row.index, button.action),
        ),
        aria_label=button.aria_label,
        variant="soft",
        size="2",
        min_height="44px",
        # «Un momento…» while it runs: aria-disabled keeps the focus (UX of UI-7); the
        # event ignores taps meanwhile
        aria_disabled=row.busy,
    )


def _question_id(row: rx.Var) -> rx.Var:
    return "q-part-remove-" + row.index.to_string()


def _remove_question(row: rx.Var) -> rx.Component:
    """«Quitar parte» asked in the row (no modal in `ui/`): what happens to the next
    part, then «Quitar parte» / «Dejarla». Focus lands on «Dejarla», the safe answer."""
    return rx.vstack(
        rx.text(
            row.remove_confirm,
            id=_question_id(row),
            size="2",
            weight="medium",
            overflow_wrap="anywhere",
        ),
        rx.flex(
            rx.button(
                REMOVE_CONFIRM_YES,
                on_click=S.confirm_remove(row.index),
                aria_label=row.aria_label + ": " + REMOVE_CONFIRM_YES,
                variant="soft",
                color_scheme="tomato",
                size="2",
                min_height="44px",
            ),
            rx.button(
                REMOVE_CONFIRM_NO,
                on_click=S.cancel_remove,
                variant="soft",
                color_scheme="gray",
                size="2",
                min_height="44px",
                auto_focus=True,
            ),
            gap="2",
            wrap="wrap",
        ),
        role="group",
        # named by its own sentence, read once
        aria_labelledby=_question_id(row),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _removed() -> rx.Component:
    """«Quitaste la parte 2. Tu video sigue con 3 partes.» — visible once; screen readers
    hear it through the one live region, so this callout is a plain `note`."""
    said = callout(S.removed_text, "ok")
    said.role = rx.Var.create("note")
    return said


#: The vista previa's picture on a row (m-24992894): narrow, vertical, on the left.
_PREVIEW_W = "4.5rem"


def _preview(row: rx.Var) -> rx.Component:
    """The row's vista previa: its poster with ▶, played in place (muted, a sound
    toggle), and its length under it. Keyed by the part's draft, so a poll's re-render
    never mounts a new player for the same part."""
    return rx.vstack(
        clip_player(
            rx.cond(row.poster_url != "", BACKEND_BASE + row.poster_url, ""),
            src=BACKEND_BASE + row.preview_url,
            label=row.play_label,
            pause_label=row.pause_label,
            key=row.draft_id,
            framed=True,
            small=True,
            # a `/r2media` path may have expired since the poll stopped: renew first
            renew=True,
            width=_PREVIEW_W,
            aspect_ratio="9 / 16",
        ),
        rx.text(row.duration_text, size="1", color=T.TEXT_MUTED),
        spacing="1",
        align_items="center",
        flex_shrink="0",
    )


def _row_body(row: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.text(row.label, size="3", weight="medium"),
            _pill(row.word, row.tone),
            justify="between",
            align="center",
            gap="2",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            row.detail != "",
            rx.text(row.detail, size="2", color=T.TEXT_MUTED, overflow_wrap="anywhere"),
        ),
        rx.cond(row.error != "", callout(row.error, "error")),
        rx.cond(row.confirming, _remove_question(row)),
        rx.cond(
            (row.buttons.length() > 0) & ~row.confirming,
            rx.flex(
                rx.foreach(row.buttons, lambda b: _button(b, row)),
                gap="2",
                wrap="wrap",
            ),
        ),
        spacing="2",
        width="100%",
        min_width="0",
        align_items="start",
    )


def _row(row: rx.Var) -> rx.Component:
    return card(
        rx.cond(
            row.preview_url != "",
            rx.flex(
                _preview(row),
                _row_body(row),
                gap="3",
                align="start",
                width="100%",
            ),
            _row_body(row),
        ),
        padding="0.875rem 1rem",
        role="listitem",
        aria_label=row.aria_label,
        aria_busy=row.busy,
    )


#: The rows' list: only the parts that wait for the owner.
ROWS_LABEL = "Partes por decidir"


def _content(parent_id: rx.Var[str] | str) -> rx.Component:
    return rx.vstack(
        rx.cond(S.notice != "", _notice()),
        rx.cond(S.removed_text != "", _removed()),
        # purged files: the notice says it, no status line
        rx.cond((S.notice == "") & (S.status_line != ""), _status(parent_id)),
        rx.cond(
            _shows_decisions(parent_id),
            rx.vstack(
                rx.foreach(S.decision_rows, _row),
                role="list",
                aria_label=ROWS_LABEL,
                spacing="2",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
        min_width="0",
    )


def part_progress_panel(parent_id: rx.Var[str] | str) -> rx.Component:
    """The parts of the video `parent_id` and their state; nothing while there are none."""
    return rx.box(
        # a session that closed or reads that keep failing: said even without rows
        rx.cond(S.top_error != "", callout(S.top_error, "error")),
        # Deivid, 2026-11-13: while THIS video's parts are joined, «Tu video completo»
        # is only its wait — nothing under it either. The panel stays mounted (it owns
        # the poll that brings everything back), only its words hide.
        rx.cond(S.has_progress & ~_joining_here(parent_id), _content(parent_id)),
        # the vista previa players' script and their «renew» button: also for the one
        # the tiles of «Tus partes» in «Tu video completo» play theirs (`part_tiles`)
        clip_player_script(),
        clip_player_renew(S.renew_previews),
        _live_region(),
        on_mount=S.watch(parent_id),
        on_unmount=S.leave,
        width="100%",
        min_width="0",
        position="relative",
    )


__all__ = ["part_progress_panel"]
