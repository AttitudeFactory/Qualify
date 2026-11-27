"""«Es una historia» on the piece's own page (m-25040496): one switch with its words
and help, off with the reason when the piece may not change. Design-system pieces only
(`rx.switch` in a 44 px label, as the generator's switches; `callout` for an error).

Also the historia's phone actions on that page (founder 2026-11-26): «Abrir en
Instagram» on Android (the gallery card's own block and rule) and, on an iPhone, the
line next to «Descargar». Both read `StoryMarkState`, so they follow the switch at once.
"""

from __future__ import annotations

import reflex as rx

from .gallery_state import USER_AGENT_JS, GalleryState
from .stories_page import story_share_block, story_share_button_id
from .stories_vm import PLATFORM_IOS, STORY_DOWNLOAD_HINT_IOS
from .story_mark_state import StoryMarkState as S
from .story_mark_vm import (
    REASON_SCHEDULED,
    SCHEDULED_LINK,
    SCHEDULED_LINK_ARIA,
    STORY_MARK_HELP,
    STORY_MARK_LABEL,
)
from .ui import callout
from .ui import tokens as T

_SWITCH_ID = "story-mark-switch"
#: The line under the switch — the reason when it is off, else the help — read with it.
_NOTE_ID = "story-mark-note"


def _mine(draft_id: rx.Var[str]) -> rx.Var[bool]:
    """The state holds THIS piece (the page reuses its components between pieces)."""
    return S.loaded & (S.draft_id == draft_id)


def story_page_phone_actions(draft_id: rx.Var[str]) -> rx.Component:
    """Right under the piece's picture and its «Descargar»: on Android «Abrir en
    Instagram» (only an approved, publishable historia of one file — `S.share_url`); on
    an iPhone, for an approved historia, how to finish it from «Descargar». A computer
    gets nothing new. Both follow the gallery card's rule (`S.story_ready`), so a
    template historia — which has no switch — gets them too."""
    mine = _mine(draft_id)
    return rx.fragment(
        rx.cond(
            mine & (S.share_url != "") & GalleryState.story_share_here,
            rx.box(
                story_share_block(
                    S.share_url,
                    story_share_button_id(draft_id),
                    GalleryState.handle_story_share,
                ),
                margin_top="0.75rem",
                width="100%",
            ),
        ),
        rx.cond(
            mine & S.story_ready & (GalleryState.device == PLATFORM_IOS),
            rx.text(
                STORY_DOWNLOAD_HINT_IOS,
                size="2",
                color=T.TEXT_MUTED,
                margin_top="0.5rem",
            ),
        ),
    )


def story_mark_control(draft_id: rx.Var[str], status: rx.Var[str] | str = "") -> rx.Component:
    """`status`: the piece's approval state — a change (approving it on this page) reads
    the piece again, so «Abrir en Instagram» shows without a reload."""
    mine = _mine(draft_id)
    return rx.vstack(
        # (re)reads whenever another piece is shown (the page reuses its component); the
        # phone it runs on is the gallery's own reading (`GalleryState.device`)
        rx.fragment(
            rx.box(
                display="none",
                on_mount=[
                    S.load_for(draft_id),
                    rx.call_script(USER_AGENT_JS, callback=GalleryState.set_device),
                ],
            ),
            key=draft_id + "-" + status,
        ),
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
                # founder 2026-11-26: a switch blocked by its event opens that event in
                # Tu semana, where the owner can remove it
                rx.cond(
                    (S.reason == REASON_SCHEDULED) & (S.event_href != ""),
                    # ONE control: the design system's link-button (`as_child`), never a
                    # button inside a link
                    rx.button(
                        rx.link(
                            rx.icon("calendar-days", size=15),
                            SCHEDULED_LINK,
                            href=S.event_href,
                            underline="none",
                            aria_label=SCHEDULED_LINK_ARIA,
                        ),
                        as_child=True,
                        variant="soft",
                        size="2",
                        min_height="44px",
                    ),
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
