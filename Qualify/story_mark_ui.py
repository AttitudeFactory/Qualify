"""«Es una historia» on the piece's own page (m-25040496): one switch with its words
and help, off with the reason when the piece may not change. Design-system pieces only
(`rx.switch` in a 44 px label, as the generator's switches; `callout` for an error)."""

from __future__ import annotations

import reflex as rx

from .story_mark_state import StoryMarkState as S
from .story_mark_vm import STORY_MARK_HELP, STORY_MARK_LABEL
from .ui import callout
from .ui import tokens as T

_SWITCH_ID = "story-mark-switch"
#: The line under the switch — the reason when it is off, else the help — read with it.
_NOTE_ID = "story-mark-note"


def story_mark_control(draft_id: rx.Var[str]) -> rx.Component:
    mine = S.loaded & (S.draft_id == draft_id)
    return rx.vstack(
        # (re)reads whenever another piece is shown (the page reuses its component)
        rx.fragment(rx.box(display="none", on_mount=S.load_for(draft_id)), key=draft_id),
        rx.cond(
            mine & S.shown,
            rx.vstack(
                rx.el.label(
                    rx.hstack(
                        rx.switch(
                            id=_SWITCH_ID,
                            checked=S.is_story,
                            on_change=S.set_story,
                            disabled=S.busy | ~S.can_change,
                            size="2",
                            custom_attrs={"aria-describedby": _NOTE_ID},
                        ),
                        rx.text(STORY_MARK_LABEL, size="2", weight="medium"),
                        spacing="2",
                        align="center",
                        min_height="44px",
                    ),
                    html_for=_SWITCH_ID,
                    cursor=rx.cond(S.can_change, "pointer", "default"),
                ),
                rx.text(
                    rx.cond(S.reason != "", S.reason, STORY_MARK_HELP),
                    id=_NOTE_ID,
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.cond(S.error != "", callout(S.error, "warn")),
                spacing="1",
                align_items="start",
                width="100%",
            ),
        ),
        spacing="1",
        align_items="start",
        width="100%",
    )
