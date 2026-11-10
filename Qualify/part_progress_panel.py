"""«Creando tus partes»: the result of a video by parts, part by part (m-24921082, UI-7).

`part_progress_panel(parent_id)` mounts the screen's ONE poll (`PartProgressState.poll`)
and stops it on unmount. Nothing renders while the parent has no parts to show. Only the
design system (`Qualify/ui/`): `progress_panel` (never a spinner), `callout`, `card`,
`signal_pill` (word + tone, never colour alone) — one pill per row, no arrows (Deivid's
UI-3 decisions). The screen has ONE `aria-live="polite"` region: the last change
(`PartProgressState.announce`), read by screen readers only; the sentence under the
title (`live_text`) is plain visible text.
"""

from __future__ import annotations

import reflex as rx

from .part_progress_state import PartProgressState as S
from .ui import tokens as T
from .ui.primitives import callout, card, progress_panel, signal_pill

#: The tones a row's pill can take (`part_progress_vm.STATE_TONES`).
_TONES = ("ok", "warn", "error", "info", "neutral")


def _pill(word: rx.Var, tone: rx.Var) -> rx.Component:
    """`signal_pill` takes its tone at build time: one branch per tone."""
    return rx.match(
        tone,
        *[(t, signal_pill(word, t)) for t in _TONES if t != "neutral"],
        signal_pill(word, "neutral"),
    )


def _panel() -> rx.Component:
    """`progress_panel` with the stage comment («2 de 4 creadas») above the bar, the
    bar's `aria-valuetext` («2 de 4 partes creadas») and its name. The panel's steps box
    is not a live region here: the screen's only one is `_live_region`."""
    panel = progress_panel(S.title, value=S.value, steps=S.comment_steps)
    for child in panel.children:
        attrs = getattr(child, "custom_attrs", None)
        if attrs is None:
            continue
        attrs.pop("aria-live", None)
        if "aria-valuenow" in attrs:  # the progressbar
            attrs["aria-valuetext"] = S.value_text
            attrs["aria-label"] = S.title
    return panel


#: Visually hidden, still read (the usual «sr-only» rules, inline: no new primitive).
_SR_ONLY = {
    "position": "absolute",
    "width": "1px",
    "height": "1px",
    "padding": "0",
    "margin": "-1px",
    "overflow": "hidden",
    "clip": "rect(0, 0, 0, 0)",
    "white_space": "nowrap",
    "border": "0",
}


def _phrase() -> rx.Component:
    return rx.text(S.live_text, size="2", color=T.TEXT_MUTED, text_align="center", width="100%")


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
        on_click=S.run_part_action(row.index, button.action),
        aria_label=button.aria_label,
        variant="soft",
        size="2",
        min_height="44px",
        # «Un momento…» while it runs: aria-disabled keeps the focus (UX of UI-7); the
        # event ignores taps meanwhile
        aria_disabled=row.busy,
    )


def _row(row: rx.Var) -> rx.Component:
    return card(
        rx.vstack(
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
            rx.cond(
                row.buttons.length() > 0,
                rx.flex(
                    rx.foreach(row.buttons, lambda b: _button(b, row)),
                    gap="2",
                    wrap="wrap",
                ),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="0.875rem 1rem",
        role="listitem",
        aria_label=row.aria_label,
        aria_busy=row.busy,
    )


def _content() -> rx.Component:
    return rx.vstack(
        rx.cond(S.notice != "", _notice()),
        # purged files: only the notice and the rows (nothing is being made)
        rx.cond(S.notice == "", rx.fragment(_panel(), _phrase())),
        rx.vstack(
            rx.foreach(S.rows, _row),
            role="list",
            aria_label="Tus partes",
            spacing="2",
            width="100%",
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
        rx.cond(S.has_progress, _content()),
        _live_region(),
        on_mount=S.watch(parent_id),
        on_unmount=S.leave,
        width="100%",
        min_width="0",
        position="relative",
    )


__all__ = ["part_progress_panel"]
