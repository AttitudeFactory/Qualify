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

import reflex as rx

from . import clip_editor_vm as vm
from . import clip_texts_vm
from .creative_state import CreativeState
from .parts_start_state import PartsStartState
from .parts_start_view import parts_start_card
from .r2_media import BACKEND_BASE
from .ui import timeline_vm as tl_vm
from .ui import tokens as T
from .ui.clip_player import SOUND_LABEL
from .ui.edit_preview import edit_sequence_preview, edit_sequence_script
from .ui.primitives import (
    asset_script,
    callout,
    choice_card,
    choice_card_check,
    drawer,
    dropzone,
    tone_badge,
)
from .ui.text_panel import text_panel
from .ui.timeline import (
    timeline,
    timeline_actions,
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


# -- «Pedir una idea» ----------------------------------------------------------------------


def _idea() -> rx.Component:
    """«¿De qué trata tu video?»: the same `topic` as «Qué decir» (D-E4; moving it out of
    step 2 is ED-06)."""
    return rx.vstack(
        rx.text_area(
            value=S.brief_topic,
            on_change=S.set_brief_topic,
            id="clip-edit-idea",
            aria_label=vm.FLOW_QUESTIONS[vm.FLOW_IDEA],
            rows="4",
            width="100%",
        ),
        rx.text(vm.IDEA_HELP, size="1", color=T.TEXT_MUTED),
        rx.text(vm.IDEA_EXAMPLE, size="1", color=T.TEXT_MUTED),
        spacing="2",
        width="100%",
        align_items="start",
    )


# -- «Texto en pantalla» (ED-13 m-25029108) ------------------------------------------------


def _text_panel() -> rx.Component:
    """The text's panel (`ui.text_panel`), on `clip_text_panel_row`: in the side panel
    while «+ Texto» puts it, or under the timeline when its block is chosen (A1, Deivid
    2026-11-23: its times change on the timeline; no «¿En qué partes va?»)."""
    row = S.clip_text_panel_row
    return text_panel(
        row,
        on_text=lambda value: S.set_clip_text_value(row["uid"], value),
        on_text_commit=lambda value: S.commit_clip_text(row["uid"], value),
        on_place=S.set_clip_text_place,
        on_fade_step=S.step_clip_text_fade,
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
    )


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


def _block_extra() -> rx.Component:
    """The chosen block's own fields, by what it is."""
    row = S.clip_tl_chosen
    return rx.match(
        row["kind"],
        (
            "video",
            rx.cond(
                row["own"] == "1",
                _own_video(),
                rx.cond(
                    row["mine"] == "1",
                    # the own video not measured yet, or one this browser cannot play
                    rx.text(
                        rx.cond(S.clip_edit_video_playable, vm.CUT_WAITING, vm.PREVIEW_BROKEN),
                        size="2",
                        color=T.TEXT_MUTED,
                        role="status",
                    ),
                    rx.text(vm.SECOND_VIDEO_NOTE, size="2", color=T.TEXT_MUTED),
                ),
            ),
        ),
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
            # an effect's times move with ±½ s; a video is cut with «Cortar» (Deivid
            # 2026-11-17: no «Desde/Hasta»); a photo's length is ED-14's
            nudges=row["kind"] == "effect",
        ),
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
    the media sources: the chosen tab shows both, the others their icon)."""
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
                for flow, icon, name in vm.FLOW_TABS
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
        ),
        timeline_actions(
            S.clip_tl_chosen_kind,
            on_add=S.open_clip_flow,
            on_action=S.clip_block_action,
            label=S.clip_tl_chosen_label,
            actions=vm.EDITOR_ACTIONS,
            # ED-13 (criterion 2): «Texto» off with 3 texts, said above the «+»
            add_off={"media": S.clip_tl_full, "text": S.clip_text_full},
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


def arma_tu_video(media_body: rx.Component) -> rx.Component:
    """The step's body, top to bottom (Deivid, 2026-11-16): the preview (centred on a
    wide step), the timeline with its bar, the chosen block's panel under them («menú
    de control») and «Armar mi video por partes». What «Agregar» opens goes in the
    ONE side panel (`_flow_drawer`; «¿Con qué lo armamos?» is ``media_body``)."""
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
            _problem(),
            rx.text(vm.PREVIEW_FREE, size="1", color=T.TEXT_MUTED),
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
