"""«Arma tu video» (ED-02 m-25026621, ED-03 m-25026623, ED-05 m-25026630, ED-10
m-25026648): the normal Clip's first step as an editor, inside the usual step frame.

Top to bottom (the proposal `.claude/epica-efectos-propuesta-linea-de-tiempo.md` §1):

- the preview in sequence (ED-01b, `ui.edit_preview.edit_sequence_preview`) — on a phone
  it takes the height the step leaves (§ ED-10 UX note: as big as it can be without the
  page scrolling);
- the timeline (ED-00b, `ui.timeline`): ruler, playhead and the three tracks, on ONE
  clock with the preview (`[data-edit-sync]`); videos and photos reorder by dragging,
  texts and effects slide in time (`assets/timeline-drag.js`, D-T6: no grip; ←/→ with
  the keyboard);
- the action bar: «Agregar» (the orbit, its options opening to the right: «Foto o
  video · Texto · Efecto · Pedir una idea») with nothing chosen, the chosen block's
  buttons otherwise («Acciones de Video 1»);
- the chosen block's panel, with «Listo», under the bar — a video's with «Cortar»
  where the marker is (Deivid 2026-11-17: no «Desde/Hasta»); ED-03: the chosen piece of
  the own video is trimmed or lengthened inside its video with its two handles on the
  timeline (finger, mouse, ←/→), free.

ED-13 (m-25029108): «+ Texto» puts a text from the marker to the end and opens its
panel «Texto en pantalla» (`ui.text_panel`) in the side panel — up to 3 texts, each in
its own seconds and place; two in one place at once
(or one «Abajo» under the subtitles) show the warning and stop «Siguiente». Deivid
2026-11-23: its times change only on the timeline; its panel picks its background and
how it enters and leaves; the preview draws it in the brand's typography and colours.

ED-04 (m-25026627): every effect put is a block of «Efectos», moved and trimmed like a
text; «Efectos» has rows that come and go on their own (Deivid 2026-11-20), and an effect
goes from one to another by dragging it up or down (↑/↓ on it with the keyboard).
«+ Efecto» asks «¿En qué partes va?» with the blocks of «Fotos y videos» as boxes and
lists the effects by the business's rubro first («Todos» lists every one); a chosen
effect's panel is its title, Empieza/Termina and «Listo».

What «Agregar» opens goes in ONE side panel with tabs (`ui.drawer`, Deivid 2026-11-16
and 11-17). On a wide step the preview is centred over the timeline, which takes the
whole width (a 12 s video fits it). Every change is kept at once, said by the
timeline's live line (D-E6: no «Guardar»; no «Deshacer» since Deivid 2026-11-19). The
words are `clip_editor_vm`'s and `ui.timeline_vm`'s; the state is `CreativeState`'s
«clip editor» block. The first tab's body (the Clip's tiles and its media selector) is
built by `content_generator` from its own helpers and handed in.
"""

from __future__ import annotations

from typing import Any

import reflex as rx
from qualify_creative.schemas import PART_DESCRIPTION_MAX

from . import ai_block_vm as ai_vm
from . import clip_editor_vm as vm
from . import clip_joins_vm as joins_vm
from . import clip_photos_vm as photos_vm
from . import clip_refs_vm as refs_vm
from . import clip_texts_vm
from . import editor_idea_vm as idea_vm
from . import parts_start_vm as start_vm
from .creative_state import CreativeState
from .parts_start_state import PartsStartState
from .parts_start_view import parts_start_card
from .r2_media import BACKEND_BASE
from .ui import timeline_vm as tl_vm
from .ui import tokens as T
from .ui.clip_player import SOUND_LABEL
from .ui.edit_preview import edit_sequence_preview, edit_sequence_script
from .ui.primitives import (
    ai_mode_tag,
    asset_script,
    callout,
    choice_card,
    choice_card_check,
    drawer,
    dropzone,
    progress_panel,
    tone_badge,
)
from .ui.text_panel import text_panel
from .ui.timeline import (
    timeline,
    timeline_actions,
    timeline_join_panel,
    timeline_layout,
    timeline_panel,
    timeline_script,
)
from .upload_preview_state import upload_preview_notice

S = CreativeState

#: The sound button's name while the sound is on (ED-01b's demo words).
MUTE_LABEL = "Quitar sonido"
#: Sizes the phone's preview to the room the step leaves (`assets/edit-room.js`).
ROOM_SCRIPT = "edit-room.js"


def _preview() -> rx.Component:
    """The whole video in order (ED-01b), its clock shared with the timeline. No time
    under the frame: the timeline's clock over the tracks is the only one (ED-10)."""
    return rx.box(
        edit_sequence_preview(
            sequence=S.clip_seq_json.replace(vm.SEQ_BASE, BACKEND_BASE),
            texts=S.clip_seq_texts,
            effects=S.clip_seq_effects,
            # m-25120474: an R2 «Así se ve» loop is on the backend's origin
            effect_url_base=(vm.SEQ_BASE, BACKEND_BASE),
            slower=S.clip_seq_slower,
            on_duration=S.report_clip_media,
            on_time=S.hear_clip_time,
            note_text="",
            broken_text=vm.PREVIEW_UNAVAILABLE,
            slower_text=vm.PREVIEW_SLOWER,
            play_label=vm.PREVIEW_PLAY,
            pause_label=vm.PREVIEW_PAUSE,
            sound_label=SOUND_LABEL,
            mute_label=MUTE_LABEL,
            region_label=vm.PREVIEW_REGION,
            clock=False,
            # ED-07: the AI part's mark, while the state says the switch is on
            ai_mark=S.clip_ai_on,
        ),
        # the own R2 video has no playable path yet: ask for one (each time it is due)
        rx.cond(
            S.clip_seq_resolve,
            rx.box(display="none", on_mount=S.resolve_clip_preview),
        ),
        _brand_font(),
        class_name="q-edit__preview",
        # ED-13 B: the texts in the brand's typography (`.q-edit-preview__text-line`)
        style={
            clip_texts_vm.FONT_VAR: rx.cond(
                S.clip_text_font_family != "",
                S.clip_text_font_family,
                "var(--heading-font-family, inherit)",
            )
        },
    )


def _parts_link() -> rx.Component:
    """«Armar mi video por partes»: the flow of always (m-24921079), behind a tertiary
    link — its question opens right here."""
    fresh = PartsStartState.piece == S.parts_piece
    # ED-06: with the AI parts on, «Agregar → Pedir una idea» proposes the parts right on
    # the track (plan §2.1): the list flow is not offered a second time here
    return rx.cond(
        S.parts_start_shown & ~S.clip_ai_on,
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


# -- «Pedir una idea» ----------------------------------------------------------------------


_IDEA_FIELD_ID = "clip-edit-idea"


def _typed_idea() -> rx.Var[str]:
    """What «Pedir una idea»'s field holds right now, read in the browser at the tap (its
    `on_change` is debounced: the last letters would not be in the state yet)."""
    return rx.Var(f"(document.getElementById('{_IDEA_FIELD_ID}')?.value ?? '')", _var_type=str)


def _idea_propose() -> rx.Component:
    """ED-06 (design 03C, PR 7), only with `QUALIFY_CLIP_AI_PARTS` on: «Proponerme las
    partes» — Claude proposes the parts and they go at the end of the track, free until
    «Crear» —, the wait «Armando tu propuesta» (a `progress_panel`, never a spinner) and
    why not. Off while no part fits, with its reason (design D22)."""
    busy = PartsStartState.editor & PartsStartState.proposing
    off = S.clip_idea_off != ""
    return rx.cond(
        busy,
        progress_panel(
            start_vm.PROGRESS_TITLE,
            steps=PartsStartState.steps,
            creep_seconds=start_vm.PROGRESS_CREEP_SECONDS,
        ),
        rx.vstack(
            rx.cond(
                # UX review P3: while the button is off its reason, under it, is enough
                ~off
                & PartsStartState.editor
                & (PartsStartState.error != "")
                & (PartsStartState.error_epoch == S.clip_idea_epoch),
                callout(PartsStartState.error, "warn"),
            ),
            rx.button(
                rx.icon("lightbulb", size=T.ICON_SM, aria_hidden="true"),
                idea_vm.PROPOSE_LABEL,
                type="button",
                size="3",
                min_height="44px",
                width=["100%", "auto"],
                on_click=PartsStartState.propose_idea(_typed_idea()),
                aria_disabled=rx.cond(off, "true", "false"),
                aria_describedby=idea_vm.PROPOSE_WHY_ID,
                class_name=rx.cond(off, "q-button-off", ""),
            ),
            rx.text(
                rx.cond(
                    off,
                    S.clip_idea_off,
                    # UX review P4: nothing written yet, said before the tap
                    rx.cond(S.clip_topic_said, idea_vm.PROPOSE_NOTE, idea_vm.STORY_MISSING),
                ),
                id=idea_vm.PROPOSE_WHY_ID,
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _idea() -> rx.Component:
    """«¿De qué trata tu video?»: the same `topic` as the editor's general panel (D-E4,
    ED-06: the video's context lives in the editor) and, with the AI parts on, «Proponerme
    las partes» (`_idea_propose`)."""
    return rx.vstack(
        rx.text_area(
            value=S.brief_topic,
            on_change=S.set_brief_topic,
            id=_IDEA_FIELD_ID,
            aria_label=vm.FLOW_QUESTIONS[vm.FLOW_IDEA],
            aria_describedby="clip-edit-idea-help",
            rows="4",
            width="100%",
        ),
        rx.text(
            vm.IDEA_HELP + " " + vm.IDEA_EXAMPLE,
            id="clip-edit-idea-help",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.cond(S.clip_ai_on, _idea_propose()),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _whole_video() -> rx.Component:
    """ED-06 (design D6, D21): «Todo el video» over an AI part's panel, folded to its
    line — what the whole video is about, who guides what (in one sentence) and
    «Cambiar», which goes back to the general panel without opening another sheet."""
    return rx.flex(
        rx.icon("film", size=T.ICON_SM, aria_hidden="true", flex_shrink="0"),
        rx.vstack(
            rx.text(idea_vm.WHOLE_TITLE, size="1", weight="medium", color=T.TEXT_MUTED),
            rx.text(S.clip_topic_whole, size="2", class_name="q-edit__whole-value"),
            rx.text(idea_vm.WHOLE_RULE, size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
            flex="1",
            min_width="0",
        ),
        _topic_button(),
        align="start",
        gap="0.75rem",
        width="100%",
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        padding="0.75rem 1rem",
        class_name="q-edit__whole",
    )


def _topic_button(button_id: str = "") -> rx.Component:
    """«Cambiar» (something written) or «Escribir» (nothing yet): the general panel opens
    as the thing chosen, the focus on «¿De qué trata tu video?» (UX review)."""
    said = S.clip_topic_said
    return rx.button(
        rx.cond(said, idea_vm.CHANGE_LABEL, idea_vm.WRITE_LABEL),
        type="button",
        variant="ghost",
        size="2",
        min_height="44px",
        flex_shrink="0",
        on_click=S.edit_clip_general,
        aria_label=rx.cond(said, idea_vm.CHANGE_ARIA, idea_vm.WRITE_ARIA),
        **({"id": button_id} if button_id else {}),
    )


def _topic_row() -> rx.Component:
    """ED-06 (design D21): with nothing chosen, ONE folded row under the timeline — «Tu
    video trata de: «…»» · «Cambiar», or «Cuenta de qué trata tu video: guía el texto.» ·
    «Escribir»."""
    return rx.flex(
        rx.icon("film", size=T.ICON_SM, aria_hidden="true", flex_shrink="0"),
        rx.text(
            S.clip_topic_row, size="2", flex="1", min_width="0", class_name="q-edit__whole-value"
        ),
        _topic_button(idea_vm.ROW_BUTTON_ID),
        align="center",
        gap="0.75rem",
        width="100%",
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        padding="0.25rem 0.25rem 0.25rem 1rem",
        class_name="q-edit__topic-row",
    )


def _general_panel(general: rx.Component) -> rx.Component:
    """The general panel opened as the thing chosen (design D21), ending in «Listo»."""
    return rx.vstack(
        general,
        rx.el.div(
            rx.button(
                tl_vm.DONE_LABEL,
                type="button",
                on_click=S.close_clip_general,
                class_name="q-tl-actions__btn",
            ),
            class_name="q-tl-panel__done",
        ),
        spacing="4",
        width="100%",
        align_items="stretch",
        role="region",
        aria_label=idea_vm.PANEL_TITLE,
    )


# -- «Texto en pantalla» (ED-13 m-25029108) ------------------------------------------------


def _text_panel() -> rx.Component:
    """The text's panel (`ui.text_panel`), on `clip_text_panel_row`: in the side panel
    while «+ Texto» puts it, or under the timeline when its block is chosen (A1, Deivid
    2026-11-23: its times change on the timeline; no «¿En qué partes va?»)."""
    row = S.clip_text_panel_row
    panel = text_panel(
        row,
        on_text=lambda value: S.set_clip_text_value(row["uid"], value),
        on_text_commit=lambda value: S.commit_clip_text(row["uid"], value),
        on_place=S.set_clip_text_place,
        on_fade=S.set_clip_text_fade,
        fade=S.clip_text_fade_s,
        on_layout=S.set_clip_text_layout,
        on_motion_in=S.set_clip_text_motion_in,
        on_motion_out=S.set_clip_text_motion_out,
        on_show_motion=S.show_clip_text_motion,
        on_done=S.done_clip_block,
        warning=S.clip_text_warning,
        colors=S.clip_text_color_rows,
        on_color=S.set_clip_text_box_color,
        on_text_color=S.set_clip_text_text_color,
        on_size=S.set_clip_text_size,
        on_use_placement=S.use_clip_text_placement,
    )
    # EF-20 phase 2: the Clip's placement advice is read when a text's panel opens, another
    # text is chosen or the Clip's videos change (its React key), only when due — once
    # per Clip, again for a video still waiting for its advice (`load_clip_placement`);
    # never per key
    reader = rx.box(display="none", key=S.clip_placement_mount, on_mount=S.load_clip_placement)
    return rx.fragment(panel, reader)


def _text_tab() -> rx.Component:
    """«Texto en pantalla» in the side panel: the panel of the text «+ Texto» just put;
    none could be put (no photo or video yet, or 3 texts already): why, and what to
    do."""
    return rx.cond(
        S.clip_text_panel_on,
        _text_panel(),
        rx.text(S.clip_text_add_reason, size="2", color=T.TEXT_MUTED, role="status"),
    )


def _brand_font() -> rx.Component:
    """ED-13 B: the brand's typography for the preview's texts — its uploaded file as
    `@font-face` (built by Var concatenation: the CSS braces would read as Var
    placeholders), else its family's Google Fonts stylesheet; nothing without one."""
    head = rx.Var.create(
        f'@font-face {{ font-family: "{clip_texts_vm.BRAND_FONT_FAMILY}"; src: url("'
    ).to(str)
    tail = rx.Var.create('"); font-display: swap; }').to(str)
    return rx.fragment(
        rx.cond(
            S.clip_brand_font_path != "",
            rx.el.style(head + BACKEND_BASE + S.clip_brand_font_path + tail),
        ),
        rx.cond(
            S.clip_text_font_css_url != "",
            rx.el.link(rel="stylesheet", href=S.clip_text_font_css_url),
        ),
    )


# -- «+ Efecto» (ED-04 m-25026627) ------------------------------------------------------------

#: The id of «¿En qué partes va?»'s title (its group's `aria-labelledby`).
PARTS_TITLE_ID = "clip-effect-parts-title"


def _part_box(row: rx.Var) -> rx.Component:
    """One block of «Fotos y videos» as a box: «Video 1 · de 0:00 a 0:05»."""
    on = row["on"] == "1"
    return choice_card(
        rx.hstack(
            rx.cond(on, choice_card_check(), rx.box(width="1.15rem", min_width="1.15rem")),
            rx.text(row["label"], size="2", weight="medium"),
            rx.text(row["time"], size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=on,
        role="checkbox",
        on_select=S.toggle_clip_effect_part(row["id"]),
        padding="0.6rem 0.9rem",
        width="100%",
        min_height="44px",
        aria_label=row["name"],
    )


def _effect_parts() -> rx.Component:
    """«¿En qué partes va?» (Deivid 2026-11-17: «solo en los recuadros que yo elija»):
    the blocks of «Fotos y videos» as boxes. Each group of parts side by side is one
    effect, stuck to them: it follows them when they move, are cut or trimmed."""
    return rx.vstack(
        rx.text(vm.PARTS_TITLE, size="2", weight="medium", id=PARTS_TITLE_ID),
        rx.vstack(
            rx.foreach(S.clip_effect_part_rows, _part_box),
            spacing="2",
            width="100%",
            role="group",
            custom_attrs={"aria-labelledby": PARTS_TITLE_ID},
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _effect_filter() -> rx.Component:
    """«Todos · Comida · …» (Deivid 2026-11-16): the effects by rubro, the business's
    first; «Todos» lists every effect, for any business."""
    return rx.box(
        rx.segmented_control.root(
            rx.foreach(
                S.clip_effect_filters,
                lambda option: rx.segmented_control.item(
                    option["text"], value=option["value"], min_height="44px"
                ),
            ),
            value=S.clip_effect_filter_shown,
            on_change=S.set_clip_effect_filter,
            size="2",
            aria_label=vm.FILTER_LABEL,
            class_name="q-tl-seg q-seg-fill",
        ),
        width="100%",
        min_width="0",
    )


def _effect_choice(row: rx.Var) -> rx.Component:
    """One effect to put: its name, its category (always shown: smoke may go in any
    business's video), «De tu rubro» when it is the business's, «Gratis». Off, with the
    reason above the list, at 8 effects or with no part marked."""
    return rx.button(
        rx.icon("sparkles", size=T.ICON_SM, aria_hidden="true"),
        rx.text(row["label"], size="2", weight="medium", flex="1", text_align="left"),
        rx.cond(row["mine"] == "1", tone_badge(vm.YOUR_RUBRO, "info")),
        rx.cond(row["category"] != "", tone_badge(row["category"], "neutral")),
        tone_badge(vm.FREE, "ok"),
        type="button",
        variant="surface",
        size="3",
        width="100%",
        min_height="44px",
        disabled=S.clip_effect_add_reason != "",
        aria_label=row["put_label"],
        on_click=S.add_clip_effect(row["id"]),
        class_name="q-edit-effect-choice",
    )


def _effect_status() -> rx.Component:
    """Why the last change was not made, else why «+ Efecto» puts nothing now."""
    return rx.cond(
        S.clip_effect_error != "",
        callout(S.clip_effect_error, "warn"),
        rx.cond(
            S.clip_effect_add_reason != "",
            rx.text(S.clip_effect_add_reason, size="2", color=T.TEXT_MUTED, role="status"),
        ),
    )


def _effects() -> rx.Component:
    """«+ Efecto»: where it goes («¿En qué partes va?»), the filter by rubro and the
    layer effects whose loop exists (none until EF-05 makes them: it says so).
    «Cámara rápida» is the video's «Velocidad» now (D-T3)."""
    return rx.cond(
        S.clip_tl_effect_choices.length() > 0,
        rx.vstack(
            _effect_parts(),
            # «Ver efectos por rubro» only with more than one category (UX review)
            rx.cond(S.clip_effect_filter_offered, _effect_filter()),
            _effect_status(),
            rx.vstack(
                rx.foreach(S.clip_tl_effect_choices, _effect_choice),
                spacing="2",
                width="100%",
                role="group",
                aria_label=vm.EFFECTS_LIST_LABEL,
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        # nothing to pick yet: say so, and offer the «Texto» tab instead (UX review)
        rx.vstack(
            rx.text(vm.NO_EFFECTS_YET, size="2", color=T.TEXT_MUTED),
            rx.button(
                rx.icon("type", size=T.ICON_SM, aria_hidden="true"),
                vm.NO_EFFECTS_GO_TEXT,
                type="button",
                variant="soft",
                size="2",
                min_height="44px",
                on_click=S.switch_clip_flow(vm.FLOW_TEXT),
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
    )


# -- the own video's panel: its stretch, «Velocidad», «Girar» --------------------------------


#: Each speed's «why it is off» (its `aria-describedby`): `clip-speed-why-5`.
SPEED_WHY_PREFIX = "clip-speed-why-"


def _speed_item(key: str, text: str, name: str) -> rx.Component:
    """One «Velocidad» option. An off one (its result outside 3–60 s, or a video under
    6 s) stays focusable with `aria-disabled` and its reason in `aria-describedby` and
    `title`; tapped, the line under the control says why (`clip_speed_note`). The
    reasons live outside the control (`_speed_whys`): Radix renders an option's children
    twice, which would repeat an id."""
    why = S.clip_speed_reasons[key].to(str)
    off = why != ""
    return rx.segmented_control.item(
        text,
        value=key,
        min_height="44px",
        aria_label=name,
        title=rx.cond(off, why, name),
        custom_attrs={
            "aria-disabled": rx.cond(off, "true", "false"),
            "aria-describedby": rx.cond(off, SPEED_WHY_PREFIX + key, ""),
            "data-off": rx.cond(off, "true", "false"),
        },
    )


def _speed_whys() -> rx.Component:
    """Each speed's reason, read by `aria-describedby`, never shown."""
    return rx.el.div(
        *(
            rx.el.span(S.clip_speed_reasons[key].to(str), id=SPEED_WHY_PREFIX + key)
            for key, _text, _name in tl_vm.SPEEDS
        ),
        class_name="q-edit-sr",
    )


def _speed() -> rx.Component:
    """«Velocidad» Normal · ×2 · ×3 · ×5 · ×10 · ×20 (D-T3: «Cámara rápida» is the
    block's speed), ALWAYS on the own video's panel (Deivid 2026-11-17): a speed is on
    only when the whole video at it lasts 3–60 s; how long it lasts with it, and its
    warnings."""
    return rx.cond(
        S.clip_tl_speed_offered,
        rx.vstack(
            rx.text(tl_vm.SPEED_LABEL, size="2", weight="medium"),
            rx.box(
                rx.segmented_control.root(
                    *(_speed_item(key, text, name) for key, text, name in tl_vm.SPEEDS),
                    value=S.clip_tl_speed,
                    on_change=lambda value: S.set_clip_block_speed(S.clip_tl_selected, value),
                    size="2",
                    aria_label=tl_vm.SPEED_LABEL,
                    class_name="q-source-seg q-tl-seg q-seg-fill",
                ),
                width="100%",
                min_width="0",
            ),
            _speed_whys(),
            rx.cond(
                S.clip_speed_note != "",
                rx.text(S.clip_speed_note, size="1", color=T.TEXT_MUTED, role="status"),
            ),
            rx.cond(
                S.clip_speed_line != "",
                rx.text(S.clip_speed_line, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            ),
            rx.cond(S.clip_fast_warning != "", callout(S.clip_fast_warning, "warn")),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


#: The id of the line under «Cortar» that says why it is off (its `aria-describedby`).
CUT_WHY_ID = "clip-edit-cut-why"


def _cut() -> rx.Component:
    """«Cortar» (Deivid 2026-11-17: «solo quiero un botón para cortar y que se corte
    donde está el marcador»): the piece of the video under the marker splits in two
    blocks there, and the one after the cut is chosen. Off, with a short line beside it
    saying why, while the marker is not on the video or sits too close to a piece's
    edge (right after a cut it rests on the new line: moving it cuts again)."""
    off = S.clip_cut_here_reason != ""
    return rx.vstack(
        rx.button(
            rx.icon("scissors", size=T.ICON_SM, aria_hidden="true"),
            vm.CUT,
            variant="soft",
            size="3",
            min_height="44px",
            disabled=off,
            title=vm.CUT_LABEL,
            on_click=S.cut_clip_video,
            custom_attrs={"aria-describedby": CUT_WHY_ID},
        ),
        rx.text(
            S.clip_cut_here_reason,
            size="1",
            color=T.TEXT_MUTED,
            id=CUT_WHY_ID,
            display=rx.cond(off, "block", "none"),
        ),
        spacing="1",
        align_items="start",
    )


def _own_video() -> rx.Component:
    """What only the editor's own video has: what EF-03 says of the stretch, «Cortar»,
    «Velocidad» and «Girar» (Deivid 2026-11-17: no «Desde/Hasta», no «Usar el video
    entero»). ED-03: the piece is trimmed with its handles on the timeline; why a handle
    stopped, and A9's minute of video, are said here."""
    return rx.vstack(
        rx.text(S.clip_cut_usage_text, size="2", class_name="q-nums"),
        # why a handle stopped first; else A9's minute (before «Crear»); else what
        # EF-03's `plan_prepare` says of the stretch
        rx.cond(
            S.clip_cut_error != "",
            callout(S.clip_cut_error, "warn"),
            rx.cond(
                S.clip_source_too_long_line != "",
                callout(S.clip_source_too_long_line, "warn"),
                rx.cond(S.clip_cut_check[0] != "", callout(S.clip_cut_check[0], "warn")),
            ),
        ),
        rx.cond(S.clip_cut_check[1] != "", callout(S.clip_cut_check[1], "info")),
        rx.flex(
            _cut(),
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
            gap="0.75rem",
            wrap="wrap",
            align="start",
        ),
        _speed(),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _photo_block() -> rx.Component:
    """A photo's panel (ED-14, m-25029109): «Duración · Se ve N s» and how to change it —
    ONLY by dragging the end handle of its block (Deivid 2026-11-24: no «− ½ s / + ½ s»;
    focused, the handle takes ←/→, ½ s each). At 1 s or 5 s the line under it says why
    the handle stops, once (`photos_vm.LIMIT_ID`, the handle's `aria-describedby`: the
    live line never repeats it). «Girar» is on the bar."""
    row = S.clip_tl_chosen
    return rx.vstack(
        rx.text(
            row["end_label"] + " · " + row["end_value"],
            size="2",
            weight="medium",
            class_name="q-nums",
        ),
        rx.text(photos_vm.DRAG_HINT, size="1", color=T.TEXT_MUTED),
        rx.text(
            row["limit"],
            size="1",
            weight="medium",
            id=photos_vm.LIMIT_ID,
            display=rx.cond(row["limit"] != "", "block", "none"),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


# -- ED-07 (m-25026638): the «parte con IA» panel ---------------------------------------

#: The modes' icons (docs/design-system.md §5.10.1), «Nueva»'s first (the default).
_AI_MODE_ICONS = ("wand-sparkles", "copy", "corner-down-right")
#: Ids the panel's controls name in `aria-describedby`.
_AI_DESCRIPTION_ID = ai_vm.DESCRIPTION_FIELD_ID
_AI_DESCRIPTION_DEBOUNCE_MS = 400
_AI_SECONDS_ID = "q-ai-part-seconds-why"
_AI_TRY_ID = "q-ai-part-try-why"
_AI_MERGE_ID = "q-ai-part-merge-why"


def _mode_icon(name: rx.Var, size: int = 16) -> rx.Component:
    return rx.match(
        name,
        *((icon, rx.icon(icon, size=size, aria_hidden="true")) for icon in _AI_MODE_ICONS[1:]),
        rx.icon(_AI_MODE_ICONS[0], size=size, aria_hidden="true"),
    )


def _ai_option(option: rx.Var) -> rx.Component:
    """One way of «¿Cómo la hacemos?»: a radio card; one that cannot be chosen now stays
    focusable (`aria-disabled`, design D8) with its reason under it, which it names."""
    why = "q-ai-mode-why-" + option["mode"]
    return choice_card(
        rx.hstack(
            _mode_icon(option["icon"]),
            rx.text(option["label"], size="2", weight="medium"),
            spacing="2",
            align="center",
        ),
        rx.text(option["help"], size="1", color=T.TEXT_MUTED),
        rx.cond(
            option["reason"] != "",
            rx.text(option["reason"], size="1", id=why, class_name="q-choice-reason"),
        ),
        selected=option["chosen"] == "1",
        soft_off=option["reason"] != "",
        on_select=S.set_clip_ai_mode(option["mode"]),
        padding="0.75rem 1rem",
        aria_describedby=rx.cond(option["reason"] != "", why, ""),
        width="100%",
        text_align="left",
    )


def _ai_mode() -> rx.Component:
    """«¿Cómo la hacemos?»: the full badge (`ai_mode_tag`), why the rule chose it — or
    «Lo cambiaste tú.» with «Volver a lo que te propusimos» — and the three ways."""
    row = S.clip_ai_chosen
    reel = row["from_reel"] == "1"
    return rx.vstack(
        rx.cond(reel, rx.text(ai_vm.MODE_TITLE, size="2", weight="bold", as_="div")),
        rx.hstack(
            rx.match(
                row["mode"],
                ("edit", ai_mode_tag(row["full"], "copy")),
                ("extend", ai_mode_tag(row["full"], "corner-down-right")),
                ai_mode_tag(row["full"], "wand-sparkles"),
            ),
            wrap="wrap",
            spacing="2",
            custom_attrs={"data-ai-mode": row["mode"]},
        ),
        rx.cond(
            reel & (row["reason"] != ""),
            rx.hstack(
                rx.cond(
                    row["changed"] == "1",
                    rx.icon("pencil", size=T.ICON_SM, aria_hidden="true"),
                    rx.icon("info", size=T.ICON_SM, aria_hidden="true", class_name="q-ai-why"),
                ),
                rx.text(row["reason"], size="1"),
                rx.cond(
                    row["back_label"] != "",
                    rx.button(
                        row["back_label"],
                        type="button",
                        variant="ghost",
                        size="1",
                        min_height="44px",
                        on_click=S.set_clip_ai_mode(row["back_to"]),
                    ),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
        ),
        # ux review: with a reel, the three ways to choose from; without one, «Nueva» is
        # the only way — said as a fact, never as a question
        rx.cond(
            row["from_reel"] == "1",
            rx.el.div(
                rx.foreach(S.clip_ai_options, _ai_option),
                role="radiogroup",
                aria_label=ai_vm.MODE_TITLE,
                class_name="q-ai-modes",
                style={"display": "grid", "gap": "0.5rem", "width": "100%"},
            ),
            rx.vstack(
                rx.text(row["mode_fact"], size="2"),
                rx.text(row["mode_help"], size="1", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _ai_description() -> rx.Component:
    row = S.clip_ai_chosen
    return rx.vstack(
        rx.el.label(
            ai_vm.DESCRIPTION_TITLE,
            html_for=_AI_DESCRIPTION_ID,
            class_name="rt-Text rt-r-size-2 rt-r-weight-bold",
        ),
        # kept after a pause while typing (~400 ms) and when the field is left (ux
        # review). Uncontrolled (`default_value`): the server's echo never overwrites
        # what is being typed; `key` starts another part from its own words. Each event
        # names ITS part, so words that arrive late never land on another one (review)
        rx.text_area(
            default_value=row["description"],
            key=row["desc_key"],  # its id and revision: a join shows the joined words
            on_change=lambda value: S.set_clip_ai_description(row["id"], value).debounce(
                _AI_DESCRIPTION_DEBOUNCE_MS
            ),
            on_blur=lambda value: S.set_clip_ai_description(row["id"], value),
            id=_AI_DESCRIPTION_ID,
            max_length=PART_DESCRIPTION_MAX,
            width="100%",
            min_height="5rem",
            aria_describedby=_AI_DESCRIPTION_ID + "-example",
        ),
        rx.text(
            ai_vm.DESCRIPTION_EXAMPLE,
            size="1",
            color=T.TEXT_MUTED,
            id=_AI_DESCRIPTION_ID + "-example",
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _ai_step(label: str, delta: int, reason: rx.Var) -> rx.Component:
    """«− 1 s» / «+ 1 s»: off with its reason (focusable, `aria-disabled`)."""
    return rx.button(
        label,
        type="button",
        variant="surface",
        min_height="44px",
        min_width="44px",
        on_click=S.step_clip_ai_seconds(delta),
        aria_disabled=rx.cond(reason != "", "true", "false"),
        aria_describedby=rx.cond(reason != "", _AI_SECONDS_ID, ""),
        class_name=rx.cond(reason != "", "q-button-off", ""),
    )


def _ai_seconds() -> rx.Component:
    row = S.clip_ai_chosen
    why = rx.cond(row["minus_reason"] != "", row["minus_reason"], row["plus_reason"])
    return rx.vstack(
        rx.text(ai_vm.SECONDS_LABEL, size="2", weight="bold", as_="div"),
        rx.hstack(
            _ai_step(ai_vm.MINUS_LABEL, -1, row["minus_reason"]),
            rx.text(
                row["seconds_text"],
                size="3",
                weight="bold",
                class_name="q-nums",
                min_width="3rem",
                text_align="center",
            ),
            _ai_step(ai_vm.PLUS_LABEL, 1, row["plus_reason"]),
            spacing="2",
            align="center",
        ),
        rx.text(row["seconds_help"], size="1", color=T.TEXT_MUTED),
        rx.text(
            why,
            size="1",
            id=_AI_SECONDS_ID,
            class_name="q-choice-reason",
            display=rx.cond(why != "", "block", "none"),
        ),
        rx.cond(
            row["seconds_note"] != "",
            rx.text(row["seconds_note"], size="1", color=T.TEXT_MUTED),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


# -- m-25142725: the reference tracks — the AI part's box, a reference's panel, the tab --

#: «Subir de tu teléfono»'s upload in «Mostrar a la IA» (the business's own folder).
REF_UPLOAD_ID = "clip_ref_upload"
#: «Pone una copia en «{track}» para que la IA la mire. Gratis.», around its track.
_AS_REF_HEAD, _, _AS_REF_TAIL = refs_vm.USE_AS_REF_HELP.partition("{track}")
_REF_BOX_ID = "q-ai-part-refs"


def _ref_thumb(item: rx.Var, size: str = "40px") -> rx.Component:
    """A reference's picture, else its kind's icon (an audio always its icon)."""
    icon = rx.match(
        item["kind"],
        ("video", rx.icon("film", size=T.ICON_MD, aria_hidden="true")),
        ("audio", rx.icon("audio-lines", size=T.ICON_MD, aria_hidden="true")),
        rx.icon("image", size=T.ICON_MD, aria_hidden="true"),
    )
    return rx.cond(
        item["thumb"] != "",
        rx.image(
            src=BACKEND_BASE + item["thumb"],
            alt="",
            width=size,
            height=size,
            object_fit="cover",
            border_radius=T.RADIUS_CONTROL,
            flex="none",
        ),
        rx.box(icon, class_name="q-ref-thumb", width=size, height=size),
    )


def _ai_ref(item: rx.Var) -> rx.Component:
    """One line of «Lo que la IA mira aquí»: its picture and name; a video or an audio
    this part does not use in its mode, struck through with the contract's words."""
    return rx.hstack(
        _ref_thumb(item),
        rx.vstack(
            rx.text(
                item["name"],
                size="1",
                class_name=rx.cond(item["ignored"] == "1", "q-truncate q-ref-off", "q-truncate"),
            ),
            rx.cond(item["tag"] != "", rx.text(item["tag"], size="1", color=T.TEXT_MUTED)),
            rx.cond(item["note"] != "", rx.text(item["note"], size="1", color=T.TEXT_MUTED)),
            spacing="0",
            min_width="0",
        ),
        spacing="2",
        align="center",
        width="100%",
        role="listitem",
    )


def _ai_refs_box() -> rx.Component:
    """«Lo que la IA mira aquí» (notas §11): what lies under the chosen AI part on the
    reference tracks — read-only (one place per action: they move on the timeline) —,
    its cap's words when it takes too many, and «Agregar una referencia»."""
    row = S.clip_ai_chosen
    ignored = S.clip_ai_refs.contains("1", "ignored")  # type: ignore[attr-defined]
    return rx.vstack(
        rx.text(refs_vm.BOX_TITLE, size="2", weight="bold", as_="div"),
        rx.text(refs_vm.BOX_HELP, size="1", color=T.TEXT_MUTED),
        rx.cond(
            S.clip_ai_refs.length() > 0,  # type: ignore[attr-defined]
            rx.el.div(
                rx.foreach(S.clip_ai_refs, _ai_ref),
                role="list",
                aria_label=refs_vm.BOX_TITLE,
                class_name="q-ref-box",
            ),
            rx.text(refs_vm.BOX_EMPTY, size="1", color=T.TEXT_MUTED),
        ),
        rx.cond(ignored, rx.text(refs_vm.IGNORED_HELP, size="1", color=T.TEXT_MUTED)),
        rx.cond(row["refs_problem"] != "", callout(row["refs_problem"], "warn")),
        # Deivid (option A): before «Quitar», that its references go with it
        rx.cond(row["refs_go"] != "", rx.text(row["refs_go"], size="1", color=T.TEXT_MUTED)),
        rx.button(
            rx.icon("plus", size=T.ICON_SM, aria_hidden="true"),
            refs_vm.ADD_SHORTCUT,
            type="button",
            variant="surface",
            min_height="44px",
            on_click=S.open_clip_ref_for_part,
        ),
        id=_REF_BOX_ID,
        spacing="2",
        width="100%",
        align_items="start",
        class_name="q-ref-box-wrap",
    )


def _ref_photo(photo: rx.Var) -> rx.Component:
    return rx.hstack(
        _ref_thumb({"thumb": photo["thumb"], "kind": "photo"}),  # type: ignore[arg-type]
        rx.button(
            rx.icon("x", size=T.ICON_SM, aria_hidden="true"),
            refs_vm.REMOVE_PHOTO,
            type="button",
            variant="soft",
            color_scheme="gray",
            min_height="44px",
            on_click=S.remove_clip_ref_photo(photo["key"]),
            aria_label=photo["remove"],
        ),
        spacing="2",
        align="center",
        role="listitem",
    )


def _ref_panel() -> rx.Component:
    """A reference's panel (notas §8): what it is used for first («Se usa en las partes
    con IA 1 y 2.»), what it is, its times and how to change them (dragging its block),
    a product's photos one by one, and «Usar también en el video» (decision 6; never for
    an audio). «Quitar» is the bar's."""
    row = S.clip_ref_chosen
    return rx.vstack(
        rx.text(row["used"], size="2", weight="medium"),
        rx.text(row["what"], size="1", color=T.TEXT_MUTED),
        rx.text(row["times"], size="2", class_name="q-nums"),
        rx.text(row["hint"], size="1", color=T.TEXT_MUTED),
        rx.cond(
            row["product"] == "1",
            rx.vstack(
                rx.text(refs_vm.PRODUCT_PHOTOS_TITLE, size="2", weight="bold", as_="div"),
                rx.el.div(
                    rx.foreach(S.clip_ref_chosen_photos, _ref_photo),
                    role="list",
                    aria_label=refs_vm.PRODUCT_PHOTOS_TITLE,
                    class_name="q-ref-box",
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        rx.cond(
            row["copy"] == "1",
            rx.vstack(
                rx.button(
                    rx.icon("copy-plus", size=T.ICON_SM, aria_hidden="true"),
                    refs_vm.USE_IN_VIDEO,
                    type="button",
                    variant="surface",
                    min_height="44px",
                    on_click=S.copy_clip_ref_to_video,
                ),
                rx.text(refs_vm.USE_IN_VIDEO_HELP, size="1", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
        custom_attrs={"data-ref-panel": row["id"]},
    )


def _use_as_ref() -> rx.Component:
    """Decision 5: «Usar también como referencia» in an own photo's or video's panel —
    only while the Clip has AI parts (`clip_ref_copy_shown`)."""
    track = rx.cond(
        S.clip_tl_chosen_kind == "video",
        refs_vm.TRACK_NAMES["video"],
        refs_vm.TRACK_NAMES["photo"],
    )
    return rx.cond(
        S.clip_ref_copy_shown,
        rx.vstack(
            rx.button(
                rx.icon(T.AI_ICON, size=T.ICON_SM, aria_hidden="true"),
                refs_vm.USE_AS_REF,
                type="button",
                variant="surface",
                min_height="44px",
                on_click=S.copy_clip_block_to_refs,
            ),
            rx.text(
                _AS_REF_HEAD + track + _AS_REF_TAIL,
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="1",
            align_items="start",
        ),
    )


def _ref_seg(
    options: tuple[tuple[str, str], ...], value: rx.Var, on_change: Any, label: str
) -> rx.Component:
    """The kit's segmented menu (`.q-source-seg`): Radix radios, 44 px."""
    return rx.box(
        rx.segmented_control.root(
            *(
                rx.segmented_control.item(
                    text, value=key, min_height="44px", aria_label=text, title=text
                )
                for key, text in options
            ),
            value=value,
            on_change=on_change,
            size="2",
            aria_label=label,
            class_name="q-source-seg q-tl-seg q-seg-fill",
        ),
        width="100%",
        min_width="0",
    )


def _ref_pick(item: rx.Var) -> rx.Component:
    """A product's photo or video, put under the AI part in one tap."""
    return rx.el.button(
        _ref_thumb(
            {"thumb": item["thumb"], "kind": S.clip_ref_kind},  # type: ignore[arg-type]
            "56px",
        ),
        rx.text(item["name"], size="1", class_name="q-truncate"),
        type="button",
        class_name="q-ref-pick",
        on_click=S.add_clip_ref_key(item["key"]),
        aria_label=rx.cond(
            S.clip_ref_kind == "video",
            refs_vm.PICK_LABEL["video"],
            refs_vm.PICK_LABEL["photo"],
        )
        + ": "
        + item["name"],
    )


def _ref_upload(kind: str) -> rx.Component:
    return dropzone(
        rx.hstack(
            rx.icon("upload", size=T.ICON_SM, aria_hidden="true"),
            rx.text(refs_vm.UPLOAD_LABELS[kind], size="2"),
            spacing="2",
            align="center",
        ),
        upload_id=REF_UPLOAD_ID,
        accept=dict(refs_vm.ACCEPT[kind]),
        max_files=1,
        variant="compact",
        multiple=False,
        on_drop=S.handle_clip_ref_uploads(  # type: ignore[call-arg]
            rx.upload_files(upload_id=REF_UPLOAD_ID)
        ),
    )


def _ref_tab() -> rx.Component:
    """«Mostrar a la IA» (notas §9, UX review): where it goes and that it is not in the
    video, «Foto · Video · Audio», then the two sources one under the other — «De tus
    productos» with their pictures and «De tu teléfono» to upload (an audio only from the
    phone). Without an AI part it only says why."""
    products = rx.cond(
        S.clip_ref_products.length() > 0,  # type: ignore[attr-defined]
        rx.el.div(rx.foreach(S.clip_ref_products, _ref_pick), class_name="q-ref-picks"),
        rx.text(S.clip_ref_products_none, size="1", color=T.TEXT_MUTED),
    )
    upload = rx.match(
        S.clip_ref_kind,
        ("video", _ref_upload("video")),
        ("audio", _ref_upload("audio")),
        _ref_upload("photo"),
    )
    return rx.vstack(
        rx.text(S.clip_ref_where, size="2"),
        rx.cond(
            S.clip_ref_can_add,
            rx.vstack(
                _ref_seg(
                    refs_vm.KIND_OPTIONS, S.clip_ref_kind, S.set_clip_ref_kind, refs_vm.KIND_LABEL
                ),
                rx.cond(
                    S.clip_ref_kind != "audio",
                    rx.vstack(
                        rx.text(refs_vm.FROM_PRODUCTS, size="2", weight="bold", as_="div"),
                        products,
                        spacing="2",
                        width="100%",
                        align_items="start",
                    ),
                ),
                rx.vstack(
                    rx.text(refs_vm.FROM_PHONE, size="2", weight="bold", as_="div"),
                    rx.cond(
                        S.clip_ref_kind == "audio",
                        rx.text(refs_vm.NO_PRODUCT_MEDIA["audio"], size="1", color=T.TEXT_MUTED),
                        rx.cond(
                            S.clip_ref_kind == "photo",
                            rx.text(refs_vm.PHONE_EXAMPLE, size="1", color=T.TEXT_MUTED),
                        ),
                    ),
                    upload,
                    spacing="2",
                    width="100%",
                    align_items="start",
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _ai_actions() -> rx.Component:
    """«Probar esta parte» (off until PR 2, its reason beside it), «Juntar con la
    siguiente» (a short part of a reel). «Quitar» is the bar's, never twice."""
    row = S.clip_ai_chosen
    return rx.vstack(
        rx.cond(
            row["problem"] != "",
            callout(row["problem"], "warn"),
        ),
        rx.flex(
            rx.button(
                rx.icon(T.AI_ICON, size=T.ICON_SM, aria_hidden="true"),
                ai_vm.TRY_LABEL,
                type="button",
                variant="soft",
                min_height="44px",
                aria_disabled=rx.cond(row["try_reason"] != "", "true", "false"),
                aria_describedby=_AI_TRY_ID,
                class_name=rx.cond(row["try_reason"] != "", "q-button-off", ""),
            ),
            rx.cond(
                row["merge_shown"] == "1",
                rx.button(
                    ai_vm.MERGE_LABEL,
                    type="button",
                    variant="surface",
                    min_height="44px",
                    on_click=S.merge_clip_ai_part,
                    aria_disabled=rx.cond(row["merge_reason"] != "", "true", "false"),
                    aria_describedby=rx.cond(row["merge_reason"] != "", _AI_MERGE_ID, ""),
                    class_name=rx.cond(row["merge_reason"] != "", "q-button-off", ""),
                ),
            ),
            wrap="wrap",
            gap="0.5rem",
        ),
        rx.text(
            rx.cond(row["try_reason"] != "", row["try_reason"], row["try_line"]),
            size="1",
            color=T.TEXT_MUTED,
            id=_AI_TRY_ID,
        ),
        rx.cond(
            row["merge_reason"] != "",
            rx.text(row["merge_reason"], size="1", color=T.TEXT_MUTED, id=_AI_MERGE_ID),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _ai_part() -> rx.Component:
    """ED-07 (m-25026638): the chosen «parte con IA»'s panel (design 02): «Sin crear ·
    gratis hasta «Crear»», «¿Qué pasa en esta parte?», m-25142725's «Lo que la IA mira
    aquí» (its photos, videos and audios are the reference tracks' now: no «Fotos de tu
    producto» nor «Video o audio tuyo» of its own), its whole seconds, «¿Cómo la
    hacemos?» and its actions. No «Velocidad», «Girar» nor «Cortar»: an AI part goes at
    ×1 (contract §2)."""
    row = S.clip_ai_chosen
    return rx.cond(
        row["id"] != "",
        rx.vstack(
            # ED-06 (design D6): the whole video's context first, folded to its line
            _whole_video(),
            rx.text(row["not_created"], size="1", color=T.TEXT_MUTED),
            # ux review: what happens first, then what it looks at and its seconds
            _ai_description(),
            _ai_refs_box(),
            _ai_seconds(),
            _ai_mode(),
            _ai_actions(),
            spacing="4",
            width="100%",
            align_items="start",
            custom_attrs={"data-ai-panel": row["id"]},
        ),
    )


def _block_extra() -> rx.Component:
    """The chosen block's own fields, by what it is. m-25142725: a reference's panel, and
    «Usar también como referencia» in an own photo's or video's."""
    row = S.clip_tl_chosen
    ref = _ref_panel()
    return rx.match(
        row["kind"],
        ("photo", rx.fragment(_photo_block(), _use_as_ref())),
        (ai_vm.TL_KIND, _ai_part()),
        (
            "video",
            rx.fragment(
                rx.cond(
                    row["own"] == "1",
                    _own_video(),
                    rx.cond(
                        row["mine"] == "1",
                        # the own video not measured yet, or one this browser cannot play
                        # — decided from THIS block's file (m-25114465, `_clip_cut_note`)
                        rx.text(
                            row["cut_note"],
                            size="2",
                            color=T.TEXT_MUTED,
                            role="status",
                        ),
                        rx.text(vm.SECOND_VIDEO_NOTE, size="2", color=T.TEXT_MUTED),
                    ),
                ),
                _use_as_ref(),
            ),
        ),
        (refs_vm.TL_KINDS["photo"], ref),
        (refs_vm.TL_KINDS["video"], ref),
        (refs_vm.TL_KINDS["audio"], ref),
        rx.fragment(),
    )


def _block_panel() -> rx.Component:
    row = S.clip_tl_chosen
    # ED-13: a text's panel is «Texto en pantalla»'s own (its field, place, times, fade)
    return rx.cond(
        S.clip_text_panel_on,
        _text_panel(),
        timeline_panel(
            row,
            on_nudge=S.nudge_clip_block,
            on_done=S.done_clip_block,
            extra=_block_extra(),
            # Deivid 2026-11-24 («quita todos los selectores para subir y bajar el
            # tiempo»): no «− ½ s / + ½ s» anywhere — an effect's and a photo's times
            # change by dragging their block's handles (focused, ←/→ ½ s); a video is cut
            # with «Cortar» (Deivid 2026-11-17: no «Desde/Hasta»)
            nudges=False,
        ),
    )


def _join_panel() -> rx.Component:
    """m-25114465: the open join's panel («Corte · Fundido · Barrido»), under the bar."""
    return timeline_join_panel(
        S.clip_join_chosen,
        S.clip_join_choices,
        on_change=S.set_clip_join,
        on_done=S.close_clip_join,
        help_text=joins_vm.HELP,
        # Deivid 2026-11-26: its duration and, a wipe, its direction
        seconds=S.clip_join_seconds_value,
        seconds_min=S.clip_join_seconds_min,
        seconds_max=S.clip_join_seconds_max,
        seconds_step=joins_vm.STEP_S,
        on_seconds=S.set_clip_join_seconds,
        directions=S.clip_join_directions,
        on_direction=S.set_clip_join_direction,
    )


#: Where the focus goes when the side panel closes: what opened it — the «Producto»
#: row's «Cambiar» (`data-flow-opener`) or the «+» (the orbit's options are gone by
#: then) —, else the chosen block; never while another drawer took over.
FLOW_FOCUS_SCRIPT = (
    "window.setTimeout(function () {"
    " if (document.querySelector('.rt-DialogContent[data-state=\"open\"]')) return;"
    " var box = document.querySelector('[data-edit-sync]'); if (!box) return;"
    " var o = box.getAttribute('data-flow-opener');"
    " var b = (o && document.getElementById(o))"
    " || box.querySelector('[data-orbit-trigger]')"
    " || box.querySelector('.q-tl__item[data-tl-chosen=\"true\"] [data-tl-block]');"
    " if (b) b.focus(); }, 60)"
)


def _flow_question() -> rx.Var:
    return rx.match(S.clip_tl_flow, *((flow, vm.FLOW_QUESTIONS[flow]) for flow in vm.FLOWS), "")


def _flow_tabs() -> rx.Component:
    """The panel's tabs — «¿Con qué lo armamos? · Texto · Efecto · Pedir una idea» — on
    the design system's segmented menu with an icon and a name (`.q-source-seg`, like
    the media sources: the chosen tab shows both, the others their icon). m-25142725:
    «Referencia» last, only while the state says the AI parts are on (`clip_ai_on`)."""
    return rx.cond(
        S.clip_ai_on, _flow_tab_bar((*vm.FLOW_TABS, vm.REF_TAB)), _flow_tab_bar(vm.FLOW_TABS)
    )


def _flow_tab_bar(tabs: tuple[tuple[str, str, str], ...]) -> rx.Component:
    return rx.box(
        rx.segmented_control.root(
            *(
                rx.segmented_control.item(
                    rx.icon(icon, size=16, aria_hidden="true"),
                    rx.el.span(name, class_name="q-source-seg__text"),
                    value=flow,
                    min_height="44px",
                    aria_label=name,
                    title=name,
                    custom_attrs={"data-flow-tab": flow},
                )
                for flow, icon, name in tabs
            ),
            value=S.clip_tl_flow,
            on_change=S.switch_clip_flow,
            size="2",
            aria_label=vm.FLOW_TABS_LABEL,
            class_name="q-source-seg",
        ),
        width="100%",
        min_width="0",
    )


def _flow_drawer(media_body: rx.Component) -> rx.Component:
    """ONE side panel for everything «Agregar» opens (Deivid 2026-11-17: «que con qué
    armamos, los efectos y el texto se junten todo en un solo slide panel»): its tabs on
    top — «¿Con qué lo armamos?» (``media_body``: the products, «Tu Galería», uploads,
    publications, «Inspiración» and the brand's resources, in this same panel — never a
    second one on top), «Texto», «Efecto», «Pedir una idea» —, the tab's question and
    its fields, «Listo» at the foot. The design system's side panel (`ui.drawer`): on
    the right on a desktop, the whole screen on a phone. «Listo», ✕, Escape, the
    backdrop and «atrás» close it, and the focus goes back to what opened it."""
    return drawer(
        rx.cond(
            S.clip_tl_flow != "",
            rx.vstack(
                _flow_tabs(),
                # the first tab's name is its question already, and «Texto en pantalla»
                # has its own title and help: no second line for them
                rx.cond(
                    (S.clip_tl_flow != vm.FLOW_MEDIA) & (S.clip_tl_flow != vm.FLOW_TEXT),
                    rx.heading(_flow_question(), as_="h3", size="3"),
                ),
                rx.match(
                    S.clip_tl_flow,
                    (vm.FLOW_MEDIA, media_body),
                    (vm.FLOW_TEXT, _text_tab()),
                    (vm.FLOW_EFFECT, _effects()),
                    (vm.FLOW_IDEA, _idea()),
                    (vm.FLOW_REF, _ref_tab()),  # m-25142725
                    rx.fragment(),
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
        ),
        open=S.clip_flow_drawer_open,
        on_open_change=S.set_clip_flow_drawer_open,
        title=vm.FLOW_PANEL_TITLE,
        icon="plus",
        footer=rx.el.div(
            # what the video holds, at the foot where the eye is: a pick from any source
            # («Inspiración» too, which is never a block of the timeline) shows here
            rx.text(
                rx.cond(S.clip_tl_flow == vm.FLOW_MEDIA, S.clip_refs_summary, ""),
                size="2",
                weight="medium",
                role="status",
                aria_live="polite",
                class_name="q-nums",
                flex="1",
                min_width="0",
            ),
            rx.button(
                tl_vm.DONE_LABEL,
                type="button",
                on_click=S.done_clip_block,
                class_name="q-tl-actions__btn",
            ),
            class_name="q-tl-panel__done",
            style={"alignItems": "center", "gap": "0.75rem"},
        ),
        on_close_auto_focus=rx.call_script(FLOW_FOCUS_SCRIPT).prevent_default,
    )


# -- the trim handles' hint (ED-03) ---------------------------------------------------------


def _trim_hint() -> rx.Component:
    """Beside the timeline's live line (Deivid 2026-11-19: «lo de los tiradores no lo
    entendí»): while a video with handles is chosen and the owner has not trimmed yet,
    `clip_editor_vm.TRIM_HINT`. No «Deshacer» any more (Deivid 2026-11-19)."""
    return rx.cond(
        S.clip_trim_hint != "",
        rx.hstack(
            rx.icon("move-horizontal", size=T.ICON_SM, aria_hidden="true"),
            rx.text(S.clip_trim_hint, size="1"),
            spacing="1",
            align="center",
            color=T.TEXT_MUTED,
            class_name="q-edit__hint",
        ),
    )


def _timeline() -> rx.Component:
    """The timeline and its bar. ED-12 (m-25029107): the whole of it takes files of the
    computer dropped on it (the design system's «section» dropzone: never a click, its
    own controls stay usable) — uploaded as «Subir» does and put in the gap the line
    marked (`assets/timeline-insert.js`); «Foto o video» is off with 8 photos or
    videos, and says why."""
    return dropzone(
        rx.box(_timeline_body(), custom_attrs={"data-tl-insert-zone": ""}),
        upload_id=vm.TIMELINE_UPLOAD_ID,
        accept=vm.TIMELINE_ACCEPT,
        max_files=0,
        multiple=True,
        max_size=vm.TIMELINE_MAX_BYTES,
        on_drop=S.handle_clip_timeline_uploads(  # type: ignore[call-arg]
            rx.upload_files(upload_id=vm.TIMELINE_UPLOAD_ID)
        ),
        on_drop_rejected=S.clip_timeline_files_rejected,
        variant="section",
    )


def _timeline_body() -> rx.Component:
    # EF-20 decision A: the Clip's placement advice is read with the timeline (only when
    # due: once per Clip, `load_clip_placement`), so «+ Texto» already knows where the
    # product shows and puts the new text where it does not cover it
    reader = rx.box(display="none", key=S.clip_placement_videos, on_mount=S.load_clip_placement)
    # ED-11b: the frame strips' reader, mounted again when the Clip's videos change
    strips = rx.box(display="none", key=S.clip_strip_videos, on_mount=S.watch_clip_frame_strips)
    # ED-07 (review): the session's business, for the AI parts' file checks — always read
    # when the timeline mounts (the switch is the server's, never the compile's)
    tenant = rx.box(display="none", on_mount=S.remember_clip_tenant)
    return rx.fragment(_timeline_layout(), reader, strips, tenant)


def _timeline_layout() -> rx.Component:
    return timeline_layout(
        timeline(
            media=S.clip_tl_media_rows,
            texts=S.clip_tl_text_rows,
            effects=S.clip_tl_effect_rows,
            ticks=S.clip_tl_ticks,
            total=S.clip_tl_total,
            selected=S.clip_tl_selected,
            on_select=S.select_clip_block,
            status=S.clip_edit_notice,
            on_key=S.clip_block_key,
            on_drag=S.drop_clip_block,
            status_action=_trim_hint(),
            # ED-04: «Efectos» in rows that come and go on their own
            effect_lanes=S.clip_tl_effect_lanes,
            effect_lane_names=S.clip_tl_effect_lane_names,
            # ED-11: each block's picture is a backend path (`clip_editor_vm.block_thumbs`)
            thumb_base=BACKEND_BASE,
            # ED-11b: each uploaded video's frame strip, by block (its path after BACKEND_BASE)
            frames=S.clip_tl_frames,
            # m-25114465: «la unión» between every two blocks ([] off the switch)
            joins=S.clip_tl_joins,
            on_join=S.open_clip_join,
            # ED-07: a «parte con IA» is drawn while the state says the switch is on
            ai_on=S.clip_ai_on,
            # m-25142725: the reference tracks, only while the Clip has AI parts
            refs={
                "shown": S.clip_ref_shown,
                "lanes": S.clip_ref_lanes,
                "names": S.clip_ref_lane_names,
                "folded": S.clip_ref_folded,
                "columns": S.clip_ref_columns,
                "on_add": S.open_clip_refs_folded,
            },
        ),
        timeline_actions(
            S.clip_tl_chosen_kind,
            on_add=S.open_clip_flow,
            on_action=S.clip_block_action,
            label=S.clip_tl_chosen_label,
            actions=vm.EDITOR_ACTIONS,
            # ED-13 (criterion 2): «Texto» off with 3 texts, said above the «+»
            add_off={
                "media": S.clip_tl_full,
                "text": S.clip_text_full,
                ai_vm.ADD_KEY: S.clip_ai_add_off,  # ED-07: 8 blocks, 6 AI parts or 60 s
                # m-25142725: «Mostrar a la IA» off without an AI part (signed)
                vm.FLOW_REF: S.clip_ref_add_off,
            },
            # ED-07: «Parte con IA», drawn only while the state says the switch is on
            # (`clip_ai_on`, read on the server — as `clip_editor_shown` for the editor)
            # m-25142725: «Mostrar a la IA» after it, also behind the switch
            add_options=(
                *ai_vm.add_options(tl_vm.ADD_OPTIONS, on=True),
                (vm.FLOW_REF, refs_vm.ADD_ICON, refs_vm.ADD_LABEL),
            ),
            add_shown={ai_vm.ADD_KEY: S.clip_ai_on, vm.FLOW_REF: S.clip_ai_on},
            add_note=S.clip_tl_add_note,
        ),
        bar_below=True,
    )


def _problem() -> rx.Component:
    """B6 (m-25048789): why «Crear» cannot make this video yet — under 3 s or over 60 s
    with its seconds (EF-06 option A), a video still being read, … — said here, before
    «Crear», in the same words «Crear» uses (`clip_edit_problem`)."""
    words, tone = S.clip_edit_problem[0], S.clip_edit_problem[1]
    return rx.cond(
        words != "",
        rx.cond(tone == "info", callout(words, "info"), callout(words, "warn")),
    )


def arma_tu_video(media_body: rx.Component, general: rx.Component | None = None) -> rx.Component:
    """The step's body, top to bottom (Deivid, 2026-11-16): the preview (centred on a
    wide step), the timeline with its bar, the chosen block's panel under them («menú
    de control») and «Armar mi video por partes». What «Agregar» opens goes in the
    ONE side panel (`_flow_drawer`; «¿Con qué lo armamos?» is ``media_body``). ED-06
    (m-25026636): with nothing chosen — no block, no join, no side panel — the panel is
    ``general`` («¿De qué trata tu video?» and «Datos clave»: the video has 3 steps)."""
    nothing_chosen = (S.clip_tl_selected == "") & (S.clip_join_open == "") & (S.clip_tl_flow == "")
    # `.q-edit-host` is the size container: the preview is centred over the timeline on
    # a wide step, as tall as the screen allows on a phone (`[data-edit-sync]`: one
    # clock for preview and tracks)
    edit = rx.box(
        edit_sequence_script(),
        timeline_script(),
        rx.box(display="none", on_mount=rx.call_script(asset_script(ROOM_SCRIPT))),
        _preview(),
        rx.box(_timeline(), class_name="q-edit__timeline"),
        rx.box(
            rx.cond(S.clip_tl_selected != "", _block_panel()),
            rx.cond(S.clip_join_open != "", _join_panel()),
            *(
                [
                    rx.cond(
                        nothing_chosen,
                        rx.cond(S.clip_general_open, _general_panel(general), _topic_row()),
                    )
                ]
                if general is not None
                else []
            ),
            # m-25142725: a card under the line for each AI part over its cap
            rx.foreach(S.clip_ref_cards, lambda card: callout(card, "warn")),
            _problem(),
            rx.text(vm.PREVIEW_FREE, size="1", color=T.TEXT_MUTED),
            # m-25114465 (ux review): how to find the joins, until the first one; and,
            # with any join that is not «Corte», that the video takes longer — the line
            # nearest «Crear» on this step (its button is the step frame's)
            rx.cond(
                S.clip_join_hint != "",
                rx.text(S.clip_join_hint, size="1", color=T.TEXT_MUTED),
            ),
            rx.cond(
                S.clip_join_slower != "",
                rx.hstack(
                    rx.icon("clock", size=T.ICON_SM, aria_hidden="true"),
                    rx.text(S.clip_join_slower, size="1"),
                    spacing="1",
                    align="center",
                    color=T.TEXT_MUTED,
                ),
            ),
            upload_preview_notice(),  # ED-09: its 480p copy could not be made
            class_name="q-edit__main",
        ),
        # last, under the panel and full width, on a phone and on a desktop
        rx.box(_parts_link(), class_name="q-edit__parts"),
        _flow_drawer(media_body),
        class_name="q-edit q-edit--timeline",
        custom_attrs={
            "data-edit-sync": "",
            "data-chosen": rx.cond(S.clip_tl_selected != "", "true", "false"),
            "data-flow-opener": S.clip_flow_opener,
        },
    )
    return rx.box(edit, class_name="q-edit-host")


__all__ = ["arma_tu_video"]
