"""«Tu video completo» — the card under a video by parts' list of parts (m-24921084,
`docs/ux-video-por-planos.md` §3e and §4).

Built only from the design system's primitives (Liquid Glass rule: no new primitive):
`card` as the surface, `progress_panel` while the parts are being joined (never a
spinner: the stage's comment sits above the bar), `callout` for what blocks, expired
parts and failures, `tag` for metadata and `signal_pill` for the join's state, by tone.
The player is the generator's (`content_generator._media_preview`): `rx.video` with
`controls`, its poster and the `q-rv-media q-rv-media--video` 9:16 frame.

State: `final_video_card_state.FinalVideoState`. Words: `final_video_vm`.
"""

from __future__ import annotations

import reflex as rx

from .creative_pages import (
    APPROVED_BODY,
    APPROVED_NOT_READY_BODY,
    APPROVED_SCHEDULE,
    APPROVED_TITLE,
)
from .final_video_card_state import (
    APPROVE,
    CHANGE,
    CREATE,
    RECREATE,
    REJOIN,
    SCHEDULE_BUTTON_ID,
    FinalVideoState,
)
from .final_video_vm import ExpiredPartVM
from .post_card import readiness_note
from .r2_media import BACKEND_BASE
from .ui import tokens as T
from .ui.primitives import (
    callout,
    card,
    media_thumb,
    progress_panel,
    signal_pill,
    skeleton_card,
    tag,
)

S = FinalVideoState

#: N12: every tap target at least 44 px tall on a phone.
_TAP = "2.75rem"
CARD_ID = "q-final-video"
APPROVE_WHY_ID = "q-final-video-approve-why"
CHANGE_PANEL_ID = "q-final-video-change"
CHANGE_PICK_ID = "q-final-video-change-pick"
CHANGE_PICK_LABEL = "¿Qué parte quieres cambiar?"
CHANGE_TEXT_LABEL = "¿Qué le cambiamos? (opcional)"
CHANGE_TEXT_PLACEHOLDER = "Ej.: que se vea el producto más de cerca"
CHANGE_SUBMIT = "Crear otra versión"
CHANGE_NOTE = "Usa 1 vista previa. Las demás partes no cambian."
CHANGE_CANCEL = "Cancelar"
PART_WORD = "Parte "
VIDEO_LABEL = "Vista previa de tu video completo"

# The card's one live region is read, not seen (WCAG 4.1.3).
_SCREEN_READER_ONLY = {
    "position": "absolute",
    "width": "1px",
    "height": "1px",
    "overflow": "hidden",
    "clip": "rect(0 0 0 0)",
    "white_space": "nowrap",
}


def _src(url: rx.Var[str], key: rx.Var[str]) -> rx.Var[str]:
    """An R2 object through `/r2media`, else the local upload store (the generator's
    `_item_src` rule)."""
    return rx.cond(url != "", BACKEND_BASE + url, rx.get_upload_url(key))


def _poster() -> rx.Var[str]:
    return rx.cond(
        S.poster_url != "",
        BACKEND_BASE + S.poster_url,
        rx.cond(S.poster_key != "", rx.get_upload_url(S.poster_key), ""),
    )


def _header() -> rx.Component:
    """«Tu video completo · 18 s · [Vista previa]» and, while joining or failed, its
    `signal_pill`."""
    return rx.flex(
        rx.heading(S.card.title, as_="h3", size="4", weight="bold"),
        rx.cond(S.card.seconds_label != "", tag(S.card.seconds_label, size="2")),
        tag(S.card.badge, size="2"),
        rx.cond(
            S.card.pill_word != "",
            rx.match(
                S.card.pill_tone,
                ("error", signal_pill(S.card.pill_word, "error", size="2")),
                ("info", signal_pill(S.card.pill_word, "info", size="2")),
                signal_pill(S.card.pill_word, "neutral", size="2"),
            ),
        ),
        gap="0.5rem",
        align="center",
        wrap="wrap",
        width="100%",
    )


def _player() -> rx.Component:
    return rx.box(
        rx.video(
            src=_src(S.video_url, S.video_key),
            poster=_poster(),
            controls=True,
            width="100%",
            height="auto",
            class_name="q-rv-media q-rv-media--video",
        ),
        role="group",
        aria_label=VIDEO_LABEL,
        # UX review: on a 375 px phone a full-width 9:16 video pushed «Aprobar» off the
        # screen — narrow and centred there, beside the words from `sm` up
        width="100%",
        max_width=rx.breakpoints(initial="11rem", sm="14rem"),
        margin_x=rx.breakpoints(initial="auto", sm="0"),
        flex_shrink="0",
    )


def _approve_button() -> rx.Component:
    """«Aprobar» — the card's one solid action, last in its last row (Deivid, 2026-11-09).
    Off, it stays in the keyboard order as `aria-disabled` and the reader hears why
    (`aria-describedby`); the `approve` event itself refuses while it cannot approve."""
    blocked = ~S.card.approve_enabled | S.working
    return rx.button(
        rx.icon("check", size=16),
        S.card.approve_label,
        size="3",
        min_height=_TAP,
        loading=S.busy == APPROVE,
        on_click=S.approve,
        aria_disabled=rx.cond(blocked, "true", "false"),
        aria_describedby=APPROVE_WHY_ID,
    )


def _approve_texts() -> rx.Component:
    """What «Aprobar» says, as ONE block right above the last row: why it is off, what
    approving uses of the month (seconds, ADR 44 F1), and what does not count again."""
    return rx.vstack(
        rx.cond(
            S.card.approve_hint != "",
            rx.text(S.card.approve_hint, size="2", color=T.TEXT_MUTED),
        ),
        rx.cond(
            S.card.quota_text != "",
            rx.text(S.card.quota_text, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
        ),
        rx.cond(
            S.card.charged_note != "",
            rx.text(S.card.charged_note, size="2", color=T.TEXT_MUTED),
        ),
        id=APPROVE_WHY_ID,
        spacing="1",
        width="100%",
    )


def _actions() -> rx.Component:
    """The card's last row, «Aprobar» first (founder's call): [Aprobar] [Cambiar una
    parte] — or, with the change panel open, [Aprobar] [Crear otra versión] [Cancelar].
    On a 375 px phone it may take two lines; «Aprobar» stays the solid one."""
    can_change = S.card.change_part_visible & (S.part_options.length() > 0)
    changing = S.change_open & S.card.change_part_visible
    return rx.flex(
        rx.cond(S.card.approve_visible, _approve_button()),
        rx.cond(
            changing,
            rx.fragment(
                rx.button(
                    rx.icon("refresh-cw", size=16),
                    CHANGE_SUBMIT,
                    variant="soft",
                    size="3",
                    min_height=_TAP,
                    disabled=(S.change_index == "") | S.working,
                    loading=S.busy == CHANGE,
                    on_click=S.change_part,
                ),
                rx.button(
                    CHANGE_CANCEL,
                    variant="ghost",
                    color_scheme="gray",
                    size="3",
                    min_height=_TAP,
                    on_click=S.toggle_change,
                ),
            ),
            rx.cond(
                can_change,
                rx.button(
                    rx.icon("pencil", size=16),
                    S.card.change_part_label,
                    variant="soft",
                    color_scheme="gray",
                    size="3",
                    min_height=_TAP,
                    disabled=S.working,
                    on_click=S.toggle_change,
                    aria_expanded="false",
                    aria_controls=CHANGE_PANEL_ID,
                ),
            ),
        ),
        gap="0.75rem",
        align="center",
        wrap="wrap",
        width="100%",
    )


def _create_missing() -> rx.Component:
    """A part of the plan never created (visual review 2026-11-09): «La parte 6 todavía no
    se creó.», then «Crear la parte 6» / «Crear las que faltan» and what it uses."""
    return rx.vstack(
        callout(S.card.unmade_text, "info", icon="circle-plus"),
        rx.button(
            rx.icon("plus", size=16),
            S.card.create_label,
            variant="soft",
            size="3",
            min_height=_TAP,
            disabled=S.working,
            loading=S.busy == CREATE,
            on_click=S.create_missing,
        ),
        rx.text(S.card.create_text, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _thumb_src(item: rx.Var[dict[str, str]]) -> rx.Var[str]:
    return rx.cond(
        item["url"] != "",
        BACKEND_BASE + item["url"],
        rx.cond(item["key"] != "", rx.get_upload_url(item["key"]), ""),
    )


def _part_choice(item: rx.Var[dict[str, str]]) -> rx.Component:
    """One tile per part (Deivid, visual review 2026-11-09): its vista previa's poster
    on top — the system's `media_thumb`, an empty neutral frame when it has none — and
    «Parte N» under it. Chosen with one tap; the chosen one is filled, ticked and
    pressed (never the colour alone)."""
    option = item["index"]
    chosen = S.change_index == option
    return rx.button(
        rx.vstack(
            media_thumb(
                _thumb_src(item), width="3.5rem", height="6.25rem", icon="film", icon_size=18
            ),
            rx.hstack(
                rx.cond(chosen, rx.icon("check", size=14)),
                rx.text(PART_WORD + option, size="2", weight="medium"),
                spacing="1",
                align="center",
            ),
            spacing="1",
            align="center",
        ),
        variant=rx.cond(chosen, "soft", "outline"),
        size="3",
        height="auto",
        min_height=_TAP,
        padding="0.5rem",
        flex_shrink="0",
        aria_pressed=rx.cond(chosen, "true", "false"),
        aria_label=PART_WORD + option,
        on_click=S.set_change_index(option),
    )


def _change_panel() -> rx.Component:
    """«Cambiar una parte»: which one and, optionally, what to change — another version
    of that part only (1 vista previa). One tap picks the part (UX review: one
    decision per step), the optional words come under it."""
    return rx.vstack(
        rx.text(CHANGE_PICK_LABEL, size="2", weight="medium", id=CHANGE_PICK_ID),
        rx.flex(
            rx.foreach(S.part_thumbs, _part_choice),
            role="group",
            aria_labelledby=CHANGE_PICK_ID,
            gap="0.5rem",
            # one row that scrolls sideways on a 375 px phone, never a hidden part
            wrap="nowrap",
            overflow_x="auto",
            width="100%",
            padding_bottom="0.25rem",
        ),
        rx.text(CHANGE_TEXT_LABEL, size="2", weight="medium"),
        rx.text_area(
            value=S.change_text,
            on_change=S.set_change_text,
            placeholder=CHANGE_TEXT_PLACEHOLDER,
            aria_label=CHANGE_TEXT_LABEL,
            max_length=500,
            rows="3",
            width="100%",
        ),
        rx.text(CHANGE_NOTE, size="2", color=T.TEXT_MUTED),
        # its buttons live in the card's last row, beside «Aprobar» (`_actions`)
        id=CHANGE_PANEL_ID,
        spacing="2",
        width="100%",
        align_items="start",
    )


def _expired(item: ExpiredPartVM) -> rx.Component:
    return callout(item.text, "warn", icon="clock")


def _recreate() -> rx.Component:
    """The ONE button for the expired parts, and what it uses of the month."""
    return rx.vstack(
        rx.foreach(S.card.expired_parts, _expired),
        rx.button(
            rx.icon("rotate-ccw", size=16),
            S.card.recreate_label,
            variant="soft",
            size="3",
            min_height=_TAP,
            disabled=S.working,
            loading=S.busy == RECREATE,
            on_click=S.recreate,
        ),
        rx.cond(
            S.card.recreate_text != "",
            rx.text(S.card.recreate_text, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _failed() -> rx.Component:
    """«No pudimos juntar tus partes…» [Juntar otra vez] — ours, nothing charged."""
    return rx.vstack(
        callout(S.card.status_text, "error"),
        rx.button(
            rx.icon("refresh-cw", size=16),
            S.card.rejoin_label,
            variant="soft",
            size="3",
            min_height=_TAP,
            disabled=S.working,
            loading=S.busy == REJOIN,
            on_click=S.rejoin,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _approved() -> rx.Component:
    """Right after approving here — as on the piece's own page (m-24842978): it is not
    out yet, and «Elegir día y hora» opens Tu semana on it; if it cannot be planned yet,
    what is missing instead."""
    ready = S.approved_ready
    return rx.vstack(
        rx.hstack(
            rx.center(rx.icon("circle-check", size=16), class_name="q-rv-glyph"),
            rx.vstack(
                rx.text(APPROVED_TITLE, class_name="q-rv-title"),
                rx.text(
                    rx.cond(ready, APPROVED_BODY, APPROVED_NOT_READY_BODY),
                    class_name="q-rv-hint",
                ),
                spacing="0",
            ),
            align="center",
            spacing="2",
        ),
        rx.cond(~ready, readiness_note(S.approved_note)),
        rx.cond(
            ready,
            rx.button(
                rx.icon("calendar-clock", size=16),
                APPROVED_SCHEDULE,
                size="3",
                min_height=_TAP,
                on_click=S.go_schedule,
                id=SCHEDULE_BUTTON_ID,  # focused right after approving
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _body() -> rx.Component:
    joining = S.wants_refresh
    texts = rx.vstack(
        rx.cond(
            S.card.preview_text != "",
            rx.text(S.card.preview_text, size="2"),
        ),
        rx.cond(
            S.card.deadline_text != "",
            rx.text(S.card.deadline_text, size="2", weight="medium"),
        ),
        spacing="2",
        flex="1",
        min_width="0",
    )
    return rx.vstack(
        _header(),
        rx.cond(
            S.join_state == "purged",
            callout(S.card.status_text, "neutral"),
        ),
        rx.cond(S.card.rejoin_visible, _failed()),
        rx.cond(
            S.card.show_video,
            rx.flex(
                _player(),
                texts,
                direction=rx.breakpoints(initial="column", sm="row"),
                gap="1rem",
                align="start",
                width="100%",
            ),
            texts,
        ),
        # the join on its way (first time, or again while the earlier one stays above)
        rx.cond(
            joining,
            progress_panel(S.card.status_text, steps=S.join_steps, creep_seconds=90),
        ),
        # a refusal sits right above the actions it is about (UX review), not at the top
        rx.cond(S.error != "", callout(S.error, "warn")),
        # a part still being made: the card says so (visual review 2026-11-09)
        rx.cond(S.card.creating_text != "", callout(S.card.creating_text, "info", icon="clock")),
        rx.cond(S.card.create_visible, _create_missing()),
        rx.cond(S.card.recreate_visible, _recreate()),
        rx.cond(S.approved_here, _approved()),
        rx.cond(S.change_open & S.card.change_part_visible, _change_panel()),
        rx.cond(S.card.approve_visible, _approve_texts()),
        _actions(),  # «Aprobar» is always last (Deivid, 2026-11-09)
        spacing="4",
        width="100%",
        align_items="start",
    )


def final_video_card(parent_id: rx.Var[str] | str) -> rx.Component:
    """«Tu video completo» of the video by parts `parent_id` (the parent draft's id).

    Usage (UI-7 places it under the parts list; nothing here hooks it to a screen):

        final_video_card(PartProgressState.parent_id)

    It reads on mount (`FinalVideoState.load`). It never polls: while
    `FinalVideoState.wants_refresh` is True (the parts are being joined) the screen's
    own poll calls `FinalVideoState.refresh(parent_id)` on each tick — ONE read each.
    Renders nothing for an id that is not a video by parts of this business. Today the
    parent shows up in «Por aprobar» (`/drafts`, `GalleryState` →
    `planner_provider.load_gallery` → `planner.draft_post_reader`, which lists parents
    only, VE-08) and opens at `/drafts/[draft_id]` (`CreativeState.load_draft`)."""
    return rx.box(
        rx.cond(
            S.missing,
            rx.fragment(),
            rx.cond(
                S.loaded,
                card(_body(), padding="1.25rem 1.5rem"),
                # the first read failed (or no session): say so, never a skeleton forever
                rx.cond(S.error != "", callout(S.error, "warn"), skeleton_card(3)),
            ),
        ),
        rx.text(S.announce, aria_live="polite", role="status", style=_SCREEN_READER_ONLY),
        id=CARD_ID,
        position="relative",
        width="100%",
        on_mount=FinalVideoState.load(parent_id),
    )


__all__ = ["final_video_card"]
