"""«Arma tu video» (ED-02 m-25026621, ED-03 m-25026623, ED-05 m-25026630, on ED-01
m-25026605's preview): the normal Clip's first step as an editor, inside the usual step
frame. The live preview on top (fixed on a phone), the card «Tu video» with the way to
«Armar mi video por partes», and the tools — «Fotos y videos», «Idea», «Efectos»,
«Cortar» — one open at a time, each asking one question. It is not a video editor: no
tracks, no keyframes, no zoom, no free dragging; everything comes proposed and «Siguiente»
works without opening any tool (proposal E1–E6).

Every change is kept at once with «Deshacer» for a few seconds (D-E6: no «Guardar»). The
words are `clip_editor_vm`'s; the state is `CreativeState`'s «clip editor» block. The
media tool's body (the same drawer, tiles and «Producto» row of the Clip) is built by
`content_generator` from its own helpers and handed in.
"""

from __future__ import annotations

import reflex as rx
from reflex_components_radix.primitives.slider import (
    SliderRange,
    SliderRoot,
    SliderThumb,
    SliderTrack,
)

from . import clip_editor_vm as vm
from . import editor_preview_contract as contract
from .creative_state import CreativeState
from .parts_start_state import PartsStartState
from .parts_start_view import parts_start_card
from .r2_media import BACKEND_BASE
from .ui import tokens as T
from .ui.clip_player import SOUND_LABEL
from .ui.edit_preview import edit_preview, edit_preview_script
from .ui.primitives import callout, card, choice_card, choice_card_check, tone_badge

S = CreativeState


def _preview(poster_src: rx.Var[str]) -> rx.Component:
    """ED-01 on the Clip: the owner's video (or the first photo, or the thumbnail of a
    video it cannot play here) with the text and the effects over it; «Deshacer» takes
    the note's place in this fixed zone while a change is fresh."""
    key = S.clip_edit_video_key
    # a local file from the upload store; an R2 one through its `/r2media/` path
    playable_src = rx.cond(
        S.clip_edit_video_r2, BACKEND_BASE + S.clip_preview_url, rx.get_upload_url(key)
    )
    src = rx.cond(S.clip_edit_video_playable, playable_src, "")
    return edit_preview(
        src=src,
        video_key=key,
        poster=rx.cond(S.clip_edit_video_playable, "", poster_src),
        start=S.clip_cut_start,
        end=S.clip_cut_end_shown,
        speed=S.clip_edit_speed_real,
        rate=S.clip_edit_rate,
        rotate=S.clip_rotate,
        text=S.clip_edit_text_shown,
        place=S.clip_text_place,
        text_long=S.clip_edit_text_long,
        text_layout=contract.TEXT_LAYOUT_ID,
        effect_srcs=S.clip_edit_effect_srcs,
        focus=S.clip_cut_focus,
        play_nonce=S.clip_cut_play,
        known=S.clip_cut_ready,
        remote=S.clip_edit_remote,
        pending=S.clip_edit_r2_pending,
        on_resolve=S.resolve_clip_preview,
        on_duration=S.report_clip_source,
        note_text=vm.PREVIEW_NOTE,
        remote_text=vm.PREVIEW_REMOTE,
        broken_text=vm.PREVIEW_BROKEN,
        slower_text=vm.PREVIEW_SLOWER,
        slower=S.clip_edit_slower,
        empty_text=vm.PREVIEW_EMPTY,
        play_label=vm.PREVIEW_PLAY,
        pause_label=vm.PREVIEW_PAUSE,
        sound_label=SOUND_LABEL,
        region_label=vm.PREVIEW_REGION,
        undo=_undo_line(),
        undo_on=S.clip_edit_notice != "",
    )


def _video_card(card_thumb: rx.Component) -> rx.Component:
    """The strip of a normal Clip: ONE card «Tu video · {s} s», its picture, the effects
    chosen and the text on one line. Never dragged nor removed (no parts here)."""
    return card(
        rx.hstack(
            card_thumb,
            rx.vstack(
                rx.text(S.clip_card_title, size="2", weight="medium", class_name="q-nums"),
                rx.cond(
                    S.clip_card_line != "",
                    rx.text(
                        S.clip_card_line,
                        size="1",
                        color=T.TEXT_MUTED,
                        truncate=True,
                        title=S.clip_card_line,
                        width="100%",
                    ),
                ),
                spacing="0",
                min_width="0",
                flex="1 1 0",
                align_items="start",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        padding="0.75rem",
    )


def _parts_link() -> rx.Component:
    """«Armar mi video por partes»: the flow of always (m-24921079), behind a tertiary
    link — its question opens right here."""
    fresh = PartsStartState.piece == S.parts_piece
    return rx.cond(
        S.parts_start_shown,
        rx.cond(
            fresh & (PartsStartState.open | PartsStartState.proposing),
            parts_start_card(),
            rx.button(
                rx.icon("layers", size=T.ICON_SM, aria_hidden="true"),
                vm.PARTS_LINK,
                variant="ghost",
                size="2",
                min_height="44px",
                on_click=PartsStartState.open_card,
            ),
        ),
    )


def _tools() -> rx.Component:
    """The tools as the kit's segmented menu (`.q-source-seg`): on a phone the chosen one
    with its name and the others their icon (name in `aria-label`); from 900 px all
    names. Radix radios: arrows move, `aria-checked`, 44 px tall."""
    return rx.box(
        rx.segmented_control.root(
            rx.foreach(
                S.clip_edit_tools,
                lambda tool: rx.segmented_control.item(
                    rx.match(
                        tool,
                        *(
                            (t, rx.icon(vm.TOOL_ICONS[t], size=16, aria_hidden="true"))
                            for t in vm.TOOLS
                        ),
                        rx.fragment(),
                    ),
                    rx.el.span(
                        rx.match(tool, *((t, vm.TOOL_LABELS[t]) for t in vm.TOOLS), ""),
                        class_name="q-source-seg__text",
                    ),
                    value=tool,
                    min_height="44px",
                    aria_label=rx.match(tool, *((t, vm.TOOL_LABELS[t]) for t in vm.TOOLS), ""),
                    title=rx.match(tool, *((t, vm.TOOL_LABELS[t]) for t in vm.TOOLS), ""),
                ),
            ),
            value=S.clip_edit_tool_open,
            on_change=S.set_clip_edit_tool,
            size="2",
            aria_label=vm.TOOLS_LABEL,
            class_name="q-source-seg q-edit-tools",
        ),
        width="100%",
        min_width="0",
    )


def _question() -> rx.Component:
    return rx.heading(S.clip_edit_question, size="4", as_="h2")


# -- «Idea» ---------------------------------------------------------------------------------


def _idea() -> rx.Component:
    """«¿De qué trata tu video?»: the same `topic` as «Qué decir» (D-E4; moving it out of
    step 2 is ED-06)."""
    return rx.vstack(
        rx.text_area(
            value=S.brief_topic,
            on_change=S.set_brief_topic,
            id="clip-edit-idea",
            aria_label=vm.TOOL_QUESTIONS[vm.TOOL_IDEA],
            rows="4",
            width="100%",
        ),
        rx.text(vm.IDEA_HELP, size="1", color=T.TEXT_MUTED),
        rx.text(vm.IDEA_EXAMPLE, size="1", color=T.TEXT_MUTED),
        spacing="2",
        width="100%",
        align_items="start",
    )


# -- «Efectos» ------------------------------------------------------------------------------


def _text_block() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.el.label(vm.TEXT_TITLE, html_for="clip-edit-text", class_name="q-field-label"),
            tone_badge(vm.FREE, "ok"),
            spacing="2",
            align="center",
        ),
        rx.input(
            value=S.clip_overlay_text,
            on_change=S.set_clip_overlay_text,
            on_blur=S.commit_clip_overlay_text,
            id="clip-edit-text",
            max_length=contract.VIDEO_TEXT_MAX,
            size="3",
            width="100%",
        ),
        # the example under the field, like «Idea»'s (never a placeholder)
        rx.text(vm.TEXT_EXAMPLE, size="1", color=T.TEXT_MUTED),
        rx.segmented_control.root(
            *(
                rx.segmented_control.item(label, value=place, min_height="44px")
                for place, label in vm.TEXT_PLACES.items()
            ),
            value=S.clip_text_place,
            on_change=S.set_clip_text_place,
            size="2",
            aria_label=vm.TEXT_PLACE_LABEL,
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _effect_row(row: rx.Var) -> rx.Component:
    on = row["on"] == "true"
    off = row["off"] == "true"
    return choice_card(
        rx.vstack(
            rx.hstack(
                rx.cond(on, choice_card_check(), rx.box(width="1.15rem", min_width="1.15rem")),
                rx.text(row["label"], size="2", weight="medium", flex="1"),
                tone_badge(vm.FREE, "ok"),
                spacing="3",
                align="center",
                width="100%",
            ),
            # why it cannot be chosen, inside the row (a video under 15 s)
            rx.cond(off, rx.text(row["reason"], size="1", color=T.TEXT_MUTED)),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        selected=on,
        disabled=off,
        role="checkbox",
        on_select=S.toggle_clip_effect(row["id"]),
        padding="0.6rem 0.9rem",
        width="100%",
        min_height="44px",
        aria_label=rx.cond(off, row["label"] + ". " + row["reason"], row["label"]),
    )


def _speed_block() -> rx.Component:
    """«Velocidad» ×5 · ×10 · ×20 and how long the video lasts with it."""
    return rx.vstack(
        rx.text(vm.SPEED_TITLE, size="2", weight="medium"),
        rx.segmented_control.root(
            *(
                rx.segmented_control.item(
                    vm.speed_label(speed),
                    value=str(speed),
                    min_height="44px",
                    aria_label=vm.speed_aria(speed),
                )
                for speed in contract.FAST_MOTION_SPEEDS
            ),
            value=S.clip_speed.to(str),
            on_change=S.set_clip_speed,
            size="2",
            aria_label=vm.SPEED_TITLE,
        ),
        rx.cond(
            S.clip_speed_line != "",
            rx.text(S.clip_speed_line, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
        ),
        rx.cond(S.clip_fast_warning != "", callout(S.clip_fast_warning, "warn")),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _effects() -> rx.Component:
    return rx.vstack(
        _text_block(),
        rx.vstack(
            rx.foreach(S.clip_edit_effect_rows, _effect_row),
            spacing="2",
            width="100%",
            role="group",
            aria_label=vm.EFFECTS_LIST_LABEL,
        ),
        rx.cond(S.clip_fast_on, _speed_block()),
        spacing="4",
        width="100%",
        align_items="start",
    )


# -- «Cortar» -------------------------------------------------------------------------------


def _thumb(label: str, valuetext: rx.Var[str]) -> rx.Component:
    """A handle: its name and, as `aria-valuetext`, the time it marks («0:04»)."""
    return SliderThumb.create(
        aria_label=label,
        custom_attrs={"aria-valuetext": valuetext},
        class_name="q-edit-cut__thumb",
    )


def _slider() -> rx.Component:
    """Radix's slider with two handles, in half seconds (it takes integers): ←/→ move a
    handle half a second; «Desde» and «Hasta» name them; at least 1 s between them."""
    return SliderRoot.create(
        SliderTrack.create(
            SliderRange.create(class_name="q-edit-cut__range"), class_name="q-edit-cut__track"
        ),
        _thumb(vm.FROM_LABEL, S.clip_cut_start_clock),
        _thumb(vm.TO_LABEL, S.clip_cut_end_clock),
        value=S.clip_cut_units,
        min=0,
        max=S.clip_cut_max_units,
        step=1,
        min_steps_between_thumbs=2,
        on_value_change=S.slide_clip_cut,
        on_value_commit=S.commit_clip_cut,
        class_name="q-edit-cut",
    )


def _nudges(handle: str, label: str) -> rx.Component:
    def button(text: str, name: str, delta: float) -> rx.Component:
        return rx.button(
            text,
            variant="soft",
            color_scheme="gray",
            size="2",
            min_height="44px",
            min_width="44px",
            aria_label=f"{label}: {name}",
            title=name,
            on_click=S.nudge_clip_cut(handle, delta),
        )

    return rx.vstack(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.hstack(
            button(vm.EARLIER_TEXT, vm.EARLIER, -contract.NUDGE_SECONDS),
            button(vm.LATER_TEXT, vm.LATER, contract.NUDGE_SECONDS),
            spacing="2",
        ),
        spacing="1",
        align_items="start",
    )


def _cut_ready() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(S.clip_cut_start_text, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            rx.text(S.clip_cut_total_text, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            justify="between",
            width="100%",
        ),
        _slider(),
        rx.text(S.clip_cut_range_text, size="2", weight="medium", class_name="q-nums"),
        rx.flex(
            _nudges("start", vm.FROM_LABEL),
            _nudges("end", vm.TO_LABEL),
            gap="1rem",
            wrap="wrap",
            width="100%",
        ),
        rx.text(S.clip_cut_usage_text, size="2", class_name="q-nums"),
        # the ±½ s refusal first; else what EF-03's `plan_prepare` says of the stretch
        rx.cond(
            S.clip_cut_error != "",
            callout(S.clip_cut_error, "warn"),
            rx.cond(
                S.clip_cut_check[0] != "",
                callout(S.clip_cut_check[0], "warn"),
            ),
        ),
        rx.cond(S.clip_cut_check[1] != "", callout(S.clip_cut_check[1], "info")),
        rx.flex(
            rx.button(
                rx.icon("rotate-cw", size=T.ICON_SM, aria_hidden="true"),
                vm.ROTATE,
                variant="soft",
                size="3",
                min_height="44px",
                aria_label=vm.ROTATE_LABEL,
                title=vm.ROTATE_LABEL,
                on_click=S.rotate_clip_video,
            ),
            rx.button(
                S.clip_cut_whole_label,
                variant="soft",
                color_scheme="gray",
                size="3",
                min_height="44px",
                on_click=S.use_whole_clip_video,
            ),
            gap="0.75rem",
            wrap="wrap",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _cut() -> rx.Component:
    return rx.cond(
        S.clip_cut_ready,
        _cut_ready(),
        rx.text(
            rx.cond(S.clip_edit_video_playable, vm.CUT_WAITING, vm.PREVIEW_BROKEN),
            size="2",
            color=T.TEXT_MUTED,
            role="status",
        ),
    )


# -- «Deshacer» (D-E6) ----------------------------------------------------------------------


def _undo_line() -> rx.Component:
    """The last change and «Deshacer», in the preview's fixed zone (D-E6), until the
    next change or until the owner leaves the step — no timer (WCAG 2.2.1). What screen
    readers hear is `_undo_status` (always mounted)."""
    return rx.box(
        rx.text(S.clip_edit_notice, size="2", aria_hidden="true"),
        rx.button(
            vm.UNDO,
            variant="soft",
            size="2",
            min_height="44px",
            on_click=S.undo_clip_edit,
        ),
        class_name="q-edit-undo",
    )


def _undo_status() -> rx.Component:
    """The same line for screen readers: a polite status, always mounted, so only its
    words change and it is heard once."""
    return rx.el.p(S.clip_edit_notice, role="status", class_name="q-edit-sr")


def arma_tu_video(
    media_body: rx.Component, poster_src: rx.Var[str], card_thumb: rx.Component
) -> rx.Component:
    """The step's body: preview · card · tools · the open tool's panel · the live line."""
    panel = rx.match(
        S.clip_edit_tool_open,
        (vm.TOOL_IDEA, _idea()),
        (vm.TOOL_EFFECTS, _effects()),
        (vm.TOOL_CUT, _cut()),
        media_body,
    )
    # `.q-edit-host` is the size container: preview and tools sit side by side only when
    # the step's own width allows it, never by the window's (a narrow desktop with the
    # side panel open stacks them)
    edit = rx.box(
        edit_preview_script(),
        rx.box(_preview(poster_src), class_name="q-edit__preview"),
        rx.box(
            _video_card(card_thumb),
            rx.text(vm.PREVIEW_FREE, size="1", color=T.TEXT_MUTED),
            _parts_link(),
            _tools(),
            rx.el.section(
                _question(),
                panel,
                id="clip-edit-panel",
                aria_label=S.clip_edit_question,
                class_name="q-edit__panel",
            ),
            _undo_status(),
            class_name="q-edit__main",
        ),
        class_name="q-edit",
    )
    return rx.box(edit, class_name="q-edit-host")


__all__ = ["arma_tu_video"]
