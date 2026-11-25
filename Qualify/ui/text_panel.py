"""The «Texto en pantalla» panel of «Arma tu video» (ED-13 m-25029108), a self-contained
component: it receives its Vars and events as parameters and knows no state.

Top to bottom: the title and its help («Estas palabras se ven encima de tu video.»), the
field (at most 120 characters, the example under it, never a placeholder) and when the
text shows («Se ve de 0:04 a 0:08. Para cambiarlo, arrastra las puntas de su bloque,
abajo.»: no «Empieza»/«Termina» here, the times change on the timeline). «¿En qué partes
va?» is gone (Deivid 2026-11-23): a text has its own seconds, from «+ Texto» or the
timeline. Every option is a section that folds (Deivid 2026-11-23, round 3):
Radix's accordion (`rx.accordion`, Crear's pattern, `type="multiple"`, all shut at
first), each header a ≥ 44 px button with the section's title, what is chosen under it
(both its accessible name) and a chevron that turns when it opens: «Dónde va el texto» ·
«Abajo», then:

- «Fondo de las letras» · «Franja, color principal»: a 2×2 grid of `choice_card` as a
  radiogroup: «Sombra» · «Franja» · «Recuadro de tu color» · «Sin fondo», each with what
  it is. Under it, for «Franja» / «Recuadro de tu color», their colour (Deivid
  2026-11-23): «Color de la franja» / «Color del recuadro» and the Brand Kit's colours,
  black and white as round 44 px chips (a radiogroup named by that title, each chip by
  its role, the chosen one ringed and checked), «Elegido: …» under them; for «Sin
  fondo», that it may get lost on a light video and (round 3) the same chips as «Color
  de las letras» (white until another is picked);
- «Cómo entra y sale» · «Aparece · Desaparece» (folds since round 3): two compact
  radiogroups (44 px) «Cómo entra» / «Cómo sale», and ONE length
  «Tarda en entrar y salir: 0,5 s» over a slider (0,3 to 1 s, 0,1 s a step; Deivid
  2026-11-24: no «− 0,1 s / + 0,1 s»). «Letra por letra» past 40 characters is off but focusable
  (`aria-disabled`, its reason under the grid), as «Abajo» with the subtitles; chosen, it
  warns the video takes a bit longer.

Each radiogroup is `aria-labelledby` its title (for the place control and the
background, the section header's first line, always in the page), one tab stop (the
chosen card has `tabindex` 0, the others -1) and the arrows move and choose
(`assets/choice-radio.js`); each card is `aria-describedby` its description. Then the
warning when there is one, and «Listo». With the subtitles on, «Abajo» is off (Deivid
2026-11-23): shown faded, never hidden, still focusable with `aria-disabled`, its reason
written under the control (no tooltip) and read by `aria-describedby`; a text that was
«Abajo» says it is under the subtitles. The words are `clip_texts_vm`'s; the classes are
the timeline panel's (`.q-tl-panel*`, `.q-tl-actions__btn`, `.q-seg-fill`), so it looks
like every other block's panel.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import reflex as rx

from .. import clip_texts_vm as vm
from . import tokens as T
from .primitives import asset_script, callout, choice_card, choice_card_check

#: The field's id (its `<label>` points at it).
FIELD_ID = vm.FIELD_ID
#: The sections' accordion items (`value`), in order; all shut at first.
SECTION_PLACE = "place"
SECTION_SIZE = "size"
SECTION_LAYOUT = "layout"
SECTION_MOTION = "motion"
#: «Dónde va el texto»'s title id (its segmented control's `aria-labelledby`).
PLACE_TITLE_ID = "clip-text-place-title"
#: Why «Abajo» is off (the subtitles go there): the option's `aria-describedby`.
PLACE_NOTE_ID = "clip-text-place-note"
#: «Este texto queda debajo de los subtítulos.»: the control's `aria-describedby`.
COVERED_NOTE_ID = "clip-text-covered-note"
#: The radiogroups' titles (`aria-labelledby`) and «Letra por letra»'s reason.
LAYOUT_TITLE_ID = "clip-text-layout-title"
MOTION_IN_TITLE_ID = "clip-text-motion-in-title"
MOTION_OUT_TITLE_ID = "clip-text-motion-out-title"
TYPEWRITER_NOTE_ID = "clip-text-typewriter-note"
#: «Cómo entra y sale»'s title (its header's first line).
MOTION_TITLE_ID = "clip-text-motion-title"
#: «Color de la franja» / «Color del recuadro» (the chips' `aria-labelledby`).
BOX_COLOR_TITLE_ID = "clip-text-box-color-title"
#: «Tamaño de las letras»'s title (its radiogroup's `aria-labelledby`) and why «Grande»
#: is off (round 4).
SIZE_TITLE_ID = "clip-text-size-title"
LARGE_NOTE_ID = "clip-text-large-note"
#: The line under the field that `assets/text-fit.js` fills when a word is wider than the
#: screen (Deivid 2026-11-24); the field's `aria-describedby`.
WIDE_NOTE_ID = "clip-text-wide-note"
#: Measures the text's words with the final video's criterion (`word_too_wide`).
FIT_SCRIPT = "text-fit.js"
#: «Si tu video es claro…» under the grid while «Sin fondo» is chosen.
SHADOW_NOTE_ID = "clip-text-shadow-note"
#: The length slider's visible line (its accessible name is the same words).
FADE_LINE_ID = "clip-text-fade-line"
#: One tab stop per radiogroup, the arrows move and choose (`assets/choice-radio.js`).
RADIO_SCRIPT = "choice-radio.js"
SHOW_MOTION = "Ver cómo se mueve"


def _fade_row(
    row: rx.Var, fade: rx.Var[float] | float, on_fade: Callable[[Any, Any], Any]
) -> rx.Component:
    """«Tarda en entrar y salir: 0,5 s» over a slider (Deivid 2026-11-23: one length for
    both; «Tarda en entrar» when it leaves «De golpe»; 2026-11-24: a slider, no
    «− 0,1 s / + 0,1 s»). From 0,3 to 1 s, 0,1 s a step — the arrows move it a step;
    it stops at its ends by itself. Radix's slider (`rx.slider`, as Crear's tone
    sliders), named by the same words as its line. Not drawn when it changes nothing."""
    return rx.cond(
        row["fade_shown"] == "1",
        rx.el.div(
            rx.text(
                row["fade_value"],
                size="2",
                weight="medium",
                class_name="q-nums",
                id=FADE_LINE_ID,
            ),
            rx.slider(
                # controlled by ``fade``; Radix's own default (50) would sit off the range
                default_value=[vm.FADE_DEFAULT],
                value=[fade],
                min=vm.FADE_MIN,
                max=vm.FADE_MAX,
                step=vm.FADE_STEP,
                on_change=lambda value: on_fade(row["uid"], value),
                size="2",
                width="100%",
                aria_label=row["fade_label"],
            ),
            class_name="q-tl-panel__field",
        ),
    )


def _place_item(row: rx.Var, place: str, text: str) -> rx.Component:
    """One of «Arriba · En el medio · Abajo». «Abajo» with the subtitles on
    (``row["bottom_off"]``) is off: faded, never hidden, still focusable, its reason
    the visible line under the control (`PLACE_NOTE_ID`; a tap says it too:
    `set_clip_text_place`)."""
    if place != vm.SUBTITLES_PLACE:
        return rx.segmented_control.item(text, value=place, min_height="44px")
    off = row["bottom_off"] == "1"
    return rx.segmented_control.item(
        text,
        value=place,
        min_height="44px",
        custom_attrs={
            "aria-disabled": rx.cond(off, "true", "false"),
            "aria-describedby": rx.cond(off, PLACE_NOTE_ID, ""),
            "data-off": rx.cond(off, "true", "false"),
        },
    )


def _radio_card(
    *,
    group: str,
    key: str,
    name: str,
    what: str,
    chosen: rx.Var[bool],
    on_choose: Any,
    off: rx.Var[bool] | None = None,
    note_id: str = "",
    compact: bool = False,
    extra_note_id: str = "",
) -> rx.Component:
    """One option of a radiogroup: a `choice_card` with `role="radio"`, the name and —
    when there is one — what it is (its `aria-describedby`). ``off``: drawn off but
    still focusable (`aria-disabled`; its reason is ``note_id``'s line). ``extra_note_id``:
    a line under the grid about this option (empty while it is not chosen)."""
    desc_id = f"{group}-{key}-desc"
    described = [desc_id] if what else []
    if extra_note_id:
        described.append(extra_note_id)
    body: list[rx.Component] = [
        rx.hstack(
            rx.text(name, size="2", weight="medium"),
            rx.cond(chosen, choice_card_check()),
            justify="between",
            align="center",
            width="100%",
        )
    ]
    if what:
        body.append(rx.text(what, size="1", color=T.TEXT_MUTED, id=desc_id))
    attrs: dict[str, Any] = {
        "data-q-radio": key,
        "aria-describedby": " ".join(described),
    }
    if off is not None:
        attrs["aria-describedby"] = rx.cond(
            off, " ".join([*described, note_id]), attrs["aria-describedby"]
        )
        attrs["data-off"] = rx.cond(off, "true", "false")
    return choice_card(
        rx.vstack(*body, spacing="1", align_items="start", width="100%"),
        selected=chosen,
        role="radio",
        on_select=on_choose,
        soft_off=off,
        padding="0.5rem 0.75rem" if compact else "0.75rem 0.9rem",
        min_height="44px",
        width="100%",
        text_align="left",
        tab_index=rx.cond(chosen, 0, -1),
        custom_attrs=attrs,
    )


def _radio_grid(
    *,
    group: str,
    title: str | None,
    title_id: str,
    choices: Sequence[tuple[str, str, str]],
    value: rx.Var,
    on_choose: Callable[[str], Any],
    off: dict[str, rx.Var[bool]] | None = None,
    note_id: str = "",
    compact: bool = False,
    notes: dict[str, str] | None = None,
) -> rx.Component:
    """A titled radiogroup of `choices` (`(key, name, what)`) in a 2×2 grid. ``title``
    None: its title is the section's header, already in the page with ``title_id``.
    ``notes``: per option, the id of a line under the grid it is also described by."""
    heading = [] if title is None else [rx.text(title, size="2", weight="medium", id=title_id)]
    return rx.vstack(
        *heading,
        rx.el.div(
            *(
                _radio_card(
                    group=group,
                    key=key,
                    name=name,
                    what=what,
                    chosen=value == key,
                    on_choose=on_choose(key),
                    off=(off or {}).get(key),
                    note_id=note_id,
                    compact=compact,
                    extra_note_id=(notes or {}).get(key, ""),
                )
                for key, name, what in choices
            ),
            role="radiogroup",
            class_name="q-text-choices",
            custom_attrs={"aria-labelledby": title_id, "data-q-radiogroup": group},
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _section(
    key: str, title: str, title_id: str, summary: rx.Var | str, *children: rx.Component
) -> rx.Component:
    """One folding section (Deivid 2026-11-23, round 3): an item of Radix's accordion, as
    Crear's (`creative_pages._kit_accordion`) — its header a real button (`aria-expanded`,
    Enter and Space, the arrows between headers) of ≥ 44 px with the title, what is
    chosen under it (both inside the button: its accessible name) and the chevron that
    turns when it opens. The title's id names what is inside (`aria-labelledby`)."""
    return rx.accordion.item(
        header=rx.el.span(
            rx.el.span(title, id=title_id, class_name="q-text-acc__title"),
            rx.el.span(summary, class_name="q-text-acc__summary"),
            class_name="q-text-acc__head",
        ),
        content=rx.vstack(*children, spacing="3", width="100%", align_items="start"),
        value=key,
    )


def _color_chip(chip: rx.Var, uid: rx.Var, on_color: Callable[[Any, Any], Any]) -> rx.Component:
    """One colour of the box: the campaign picker's round swatch (`.q-swatch`, ringed when
    chosen with `.q-swatch--on`) at 44 × 44 (`.q-swatch--box`), its colour in `--tint`, a
    check in the letters' colour when chosen, named by its role («Color principal de tu
    marca», «Negro»), never by its hex. One tab stop for the row (`assets/choice-radio.js`)."""
    on = chip["on"] == "1"
    return rx.el.button(
        rx.cond(on, rx.icon("check", size=18, aria_hidden="true")),
        type="button",
        role="radio",
        aria_checked=rx.cond(on, "true", "false"),
        aria_label=chip["name"],
        title=chip["name"],
        tab_index=rx.cond(on, 0, -1),
        on_click=on_color(uid, chip["value"]),
        class_name=rx.cond(on, "q-swatch q-swatch--box q-swatch--on", "q-swatch q-swatch--box"),
        style={"--tint": chip["value"], "color": chip["ink"]},
        custom_attrs={"data-q-radio": chip["value"]},
    )


def _box_colors(
    row: rx.Var,
    colors: rx.Var,
    on_color: Callable[[Any, Any], Any],
    on_text_color: Callable[[Any, Any], Any] | None = None,
) -> rx.Component:
    """Under «Franja» / «Recuadro de tu color» (Deivid 2026-11-23): «Color de la franja»
    (or «del recuadro»), the Brand Kit's colours then black and white as a radiogroup
    labelled by that visible title, and «Elegido: …» in grey under them. Round 3: under
    «Sin fondo», the same chips as «Color de las letras», each picking the letters'
    colour (``on_text_color``)."""
    chip_list = rx.foreach(colors, lambda chip: _color_chip(chip, row["uid"], on_color))
    if on_text_color is not None:
        chip_list = rx.cond(
            row["chips_for_text"] == "1",
            rx.foreach(colors, lambda chip: _color_chip(chip, row["uid"], on_text_color)),
            chip_list,
        )
    return rx.cond(
        row["box_color_shown"] == "1",
        rx.vstack(
            rx.text(row["box_color_title"], size="2", weight="medium", id=BOX_COLOR_TITLE_ID),
            rx.el.div(
                chip_list,
                role="radiogroup",
                class_name="q-text-colors",
                custom_attrs={
                    "aria-labelledby": BOX_COLOR_TITLE_ID,
                    "data-q-radiogroup": "clip-text-box-color",
                },
            ),
            rx.text(row["box_color_chosen"], size="1", color=T.TEXT_MUTED),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _layout_section(
    row: rx.Var,
    on_layout: Callable[[Any, str], Any],
    colors: rx.Var | None = None,
    on_color: Callable[[Any, Any], Any] | None = None,
    on_text_color: Callable[[Any, Any], Any] | None = None,
) -> rx.Component:
    """«Fondo de las letras» · «<actual>, <color>» (ED-13 C): the four backgrounds, then —
    for «Franja» / «Recuadro de tu color» — their colour chips, or — for «Sin fondo» —
    the line that it may get lost on a light video (each card's `aria-describedby` adds
    it while chosen) and, since round 3, the chips of its letters' colour."""
    chips: list[rx.Component] = []
    if colors is not None and on_color is not None:
        chips.append(_box_colors(row, colors, on_color, on_text_color))
    return _section(
        SECTION_LAYOUT,
        vm.LAYOUT_TITLE,
        LAYOUT_TITLE_ID,
        row["layout_choice"],
        _radio_grid(
            group="clip-text-layout",
            title=None,
            title_id=LAYOUT_TITLE_ID,
            choices=vm.LAYOUT_CHOICES,
            value=row["layout"],
            on_choose=lambda key: on_layout(row["uid"], key),
            notes={"shadow": SHADOW_NOTE_ID},
        ),
        # «Sin fondo»: white letters with nothing behind can get lost on a light video
        rx.text(
            row["shadow_note"],
            id=SHADOW_NOTE_ID,
            display=rx.cond(row["shadow_note"] != "", "block", "none"),
            size="1",
            color=T.TEXT_MUTED,
        ),
        *chips,
    )


def _motion_section(
    row: rx.Var,
    *,
    on_motion_in: Callable[[Any, str], Any],
    on_motion_out: Callable[[Any, str], Any],
    on_fade: Callable[[Any, Any], Any],
    fade: rx.Var[float] | float,
    on_show_motion: Callable[[Any], Any],
) -> rx.Component:
    """«Cómo entra y sale» · «Aparece · Desaparece» (ED-13 D; folds since round 3, Deivid
    2026-11-23): «Cómo entra» / «Cómo sale» and the one length «Tarda en entrar y
    salir»."""
    muted = {"size": "1", "color": T.TEXT_MUTED}
    return _section(
        SECTION_MOTION,
        vm.MOTION_TITLE,
        MOTION_TITLE_ID,
        row["motion_choice"],
        _radio_grid(
            group="clip-text-in",
            title=vm.MOTION_IN_TITLE,
            title_id=MOTION_IN_TITLE_ID,
            choices=[(key, name, "") for key, name in vm.MOTION_IN_CHOICES],
            value=row["motion_in"],
            on_choose=lambda key: on_motion_in(row["uid"], key),
            off={vm.TYPEWRITER: row["typewriter_off"] == "1"},
            note_id=TYPEWRITER_NOTE_ID,
            compact=True,
        ),
        # why «Letra por letra» is off (visible, no tooltip), and what choosing it costs
        rx.text(
            row["typewriter_note"],
            id=TYPEWRITER_NOTE_ID,
            display=rx.cond(row["typewriter_note"] != "", "block", "none"),
            **muted,
        ),
        rx.cond(row["typewriter_slow"] != "", rx.text(row["typewriter_slow"], **muted)),
        _radio_grid(
            group="clip-text-out",
            title=vm.MOTION_OUT_TITLE,
            title_id=MOTION_OUT_TITLE_ID,
            choices=[(key, name, "") for key, name in vm.MOTION_OUT_CHOICES],
            value=row["motion_out"],
            on_choose=lambda key: on_motion_out(row["uid"], key),
            compact=True,
        ),
        _fade_row(row, fade, on_fade),
        rx.cond(row["cut_note"] != "", rx.text(row["cut_note"], **muted)),
        # with prefers-reduced-motion nothing plays by itself: the owner asks for it
        rx.button(
            SHOW_MOTION,
            type="button",
            variant="soft",
            color_scheme="gray",
            on_click=on_show_motion(row["uid"]),
            class_name="q-tl-actions__btn q-text-show-motion",
        ),
    )


def _size_section(row: rx.Var, on_size: Callable[[Any, str], Any]) -> rx.Component:
    """«Tamaño de las letras» · «Tamaño: Mediana» (ED-13 round 4, Deivid 2026-11-23: «3
    tamaños»): «Pequeña · Mediana · Grande» as a compact radiogroup, «Grande» off — faded,
    still focusable, its reason the line under it — for a text over `vm.LARGE_MAX`
    characters (option A)."""
    return _section(
        SECTION_SIZE,
        vm.SIZE_TITLE,
        SIZE_TITLE_ID,
        row["size_choice"],
        _radio_grid(
            group="clip-text-size",
            title=None,
            title_id=SIZE_TITLE_ID,
            choices=[(key, name, "") for key, name in vm.SIZE_CHOICES],
            value=row["size"],
            on_choose=lambda key: on_size(row["uid"], key),
            off={vm.LARGE: row["large_off"] == "1"},
            note_id=LARGE_NOTE_ID,
            compact=True,
        ),
        rx.text(
            row["large_note"],
            id=LARGE_NOTE_ID,
            display=rx.cond(row["large_note"] != "", "block", "none"),
            size="1",
            color=T.TEXT_MUTED,
        ),
    )


def _place_section(row: rx.Var, on_place: Callable[[Any, Any], Any]) -> rx.Component:
    """«Dónde va el texto» · «Abajo»: «Arriba · En el medio · Abajo», and under it — when
    they apply — that the text is under the subtitles and why «Abajo» is off."""
    return _section(
        SECTION_PLACE,
        vm.PLACE_LABEL,
        PLACE_TITLE_ID,
        row["place_choice"],
        rx.segmented_control.root(
            *(_place_item(row, place, text) for place, text in vm.PLACE_TEXTS.items()),
            value=row["place"],
            on_change=lambda value: on_place(row["uid"], value),
            size="2",
            class_name="q-tl-seg q-seg-fill",
            custom_attrs={
                "aria-labelledby": PLACE_TITLE_ID,
                "aria-describedby": rx.cond(row["covered_note"] != "", COVERED_NOTE_ID, ""),
            },
        ),
        # a text left «Abajo» when the subtitles were turned on: it is under them
        rx.text(
            row["covered_note"],
            size="1",
            weight="medium",
            id=COVERED_NOTE_ID,
            display=rx.cond(row["covered_note"] != "", "block", "none"),
        ),
        # under the control, visible (no tooltip): why «Abajo» is off
        rx.text(
            row["place_note"],
            size="1",
            color=T.TEXT_MUTED,
            id=PLACE_NOTE_ID,
            display=rx.cond(row["place_note"] != "", "block", "none"),
        ),
    )


def text_panel(
    row: rx.Var,
    *,
    on_text: Callable[[Any], Any],
    on_text_commit: Callable[[Any], Any],
    on_place: Callable[[Any, Any], Any],
    on_fade: Callable[[Any, Any], Any],
    on_layout: Callable[[Any, str], Any],
    on_motion_in: Callable[[Any, str], Any],
    on_motion_out: Callable[[Any, str], Any],
    on_show_motion: Callable[[Any], Any],
    on_done: Any,
    fade: rx.Var[float] | float = vm.FADE_DEFAULT,
    warning: rx.Var[str] | str = "",
    colors: rx.Var | None = None,
    on_color: Callable[[Any, Any], Any] | None = None,
    on_text_color: Callable[[Any, Any], Any] | None = None,
    on_size: Callable[[Any, str], Any] | None = None,
) -> rx.Component:
    """The chosen text's panel. ``row`` is `clip_texts_vm.text_panel_row` (as a Var);
    ``on_text(value)`` while typing, ``on_text_commit(value)`` when the field is left,
    ``on_place(uid, place)``, ``on_fade(uid, value)`` (the length slider, at ``fade``
    seconds; Radix sends a list), ``on_layout(uid, layout)``,
    ``on_motion_in(uid, motion)`` / ``on_motion_out(uid, motion)`` and
    ``on_show_motion(uid)`` («Ver cómo se mueve»); ``warning`` (`texts_problem`, or
    why the last choice was not taken) shows as a warning callout when not empty.
    ``colors`` (`clip_texts_vm.box_color_rows`) with ``on_color(uid, hex)`` show the
    box's colour chips under «Franja» / «Recuadro de tu color»; ``on_text_color(uid,
    hex)`` the same chips under «Sin fondo», for its letters (round 3);
    ``on_size(uid, size)`` shows «Tamaño de las letras» (round 4).
    Escape inside lets the text go, as the timeline panel (`data-tl-panel`)."""
    sections: list[rx.Component] = [
        _place_section(row, on_place),
        *([_size_section(row, on_size)] if on_size is not None else []),
        _layout_section(row, on_layout, colors, on_color, on_text_color),
        _motion_section(
            row,
            on_motion_in=on_motion_in,
            on_motion_out=on_motion_out,
            on_fade=on_fade,
            fade=fade,
            on_show_motion=on_show_motion,
        ),
    ]
    # `callout` already says a warning politely (`role="status"`)
    warn = (
        rx.cond(warning != "", callout(warning, tone="warn"))
        if isinstance(warning, rx.Var)
        else (callout(warning, tone="warn") if warning else rx.fragment())
    )
    return rx.el.div(
        rx.vstack(
            rx.text(vm.TITLE, size="2", weight="bold"),
            rx.text(vm.HELP, size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
        ),
        rx.el.div(
            rx.el.label(vm.FIELD_LABEL, html_for=FIELD_ID, class_name="q-field-label"),
            rx.input(
                value=row["text"],
                on_change=on_text,
                on_blur=on_text_commit,
                id=FIELD_ID,
                max_length=vm.TEXT_MAX_CHARS,
                size="3",
                width="100%",
                aria_describedby=WIDE_NOTE_ID,
            ),
            # a word wider than the screen: filled and shown by `text-fit.js` (React
            # renders no children here), with the final video's own criterion
            rx.el.p(
                id=WIDE_NOTE_ID,
                class_name="q-text-fit-note",
                aria_live="polite",
                custom_attrs={
                    "data-text-fit": "",
                    "data-text": row["text"],
                    "data-size": row["size"],
                    "data-line": vm.WIDE_WORD_LINE,
                },
            ),
            rx.text(vm.EXAMPLE, size="1", color=T.TEXT_MUTED),
            class_name="q-tl-panel__field",
        ),
        # A1: when it shows, and where to change that (the timeline, below)
        rx.text(row["time_line"], size="1", color=T.TEXT_MUTED, class_name="q-nums"),
        # every option folds (Deivid 2026-11-23, round 3); several may be open at once
        rx.accordion.root(
            *sections,
            type="multiple",
            collapsible=True,
            variant="surface",
            width="100%",
            class_name="q-text-acc",
        ),
        warn,
        # «Listo» stays at hand on a phone: fixed at the foot of the panel while it scrolls
        rx.el.div(
            rx.button(vm.DONE, type="button", on_click=on_done, class_name="q-tl-actions__btn"),
            class_name="q-tl-panel__done q-text-panel__done",
        ),
        # the radiogroups' arrows (its guard keeps one listener)
        rx.box(display="none", on_mount=rx.call_script(asset_script(RADIO_SCRIPT))),
        # «palabra demasiado larga» under the field (its guard keeps one observer)
        rx.box(display="none", on_mount=rx.call_script(asset_script(FIT_SCRIPT))),
        class_name="q-tl-panel",
        tab_index=-1,
        role="group",
        aria_label=row["name"],
        custom_attrs={"data-tl-panel": row["id"]},
    )
