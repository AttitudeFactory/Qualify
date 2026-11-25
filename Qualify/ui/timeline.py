"""`timeline` — the «Arma tu video» timeline (ED-00b m-25029104; built for ED-10 to take).

Anatomy (the proposal `.claude/epica-efectos-propuesta-linea-de-tiempo.md` §1, §3):

- a group «Línea de tiempo de tu video» with a ruler, three tracks («Fotos y videos»
  56 px, «Textos» and «Efectos» 44 px) and the playhead;
- every block is a button with its full name (`aria-pressed` when chosen); the chosen
  one shows its two handles OUTSIDE the block (44 × 56 px / 44 × 44 px), each a
  `role="slider"` with `aria-valuetext`;
- the playhead is a native range input («Momento del video», value text «0:05 de 0:12»);
- a `role="status"` line under it.

**Phone** (the component narrower than 52rem — the step's 900 px of §1.4 minus its padding,
measured on the component's own container, never the window): 1 s = 44 px, the tracks slide
horizontally INSIDE their box (the page never scrolls sideways) and the playhead stays
fixed at the centre; sliding the tracks moves the playhead. **Desktop**: the tracks fill
the width, the track names show on the left, a click on the ruler moves the playhead.

The playhead lives in the browser (`assets/timeline.js`): it is the same clock as the
preview (ED-01b), so the server never hears every half second. Blocks, the chosen block
and the edits are the screen's state: rows from `ui.timeline_vm` (strings only).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import reflex as rx

from . import timeline_vm as vm
from . import tokens as T
from .primitives import OrbitItem, asset_script, media_thumb, orbit_menu

#: The script's name under `assets/`.
SCRIPT = "timeline.js"
#: ED-10 m-25026648: drag and drop — the pure math (tested with node) and the DOM half.
DRAG_CORE_SCRIPT = "timeline-drag-core.js"
DRAG_SCRIPT = "timeline-drag.js"
#: ED-12 m-25029107: photos and videos of the computer dropped on the timeline, with
#: the line that marks where they land.
INSERT_SCRIPT = "timeline-insert.js"
#: ED-12 UX review S4: the id of «Agregar»'s why (above the «+»), which the «+» names in
#: `aria-describedby` while it says something.
ADD_NOTE_ID = "q-tl-add-note"

Rows = rx.Var[list[dict[str, str]]]
Row = rx.Var[dict[str, str]]


def timeline_script() -> rx.Component:
    """Mount `assets/timeline.js` and the drag and drop (ED-10). Their guards keep one set
    of document listeners; a second mount only attaches the timelines now on the page,
    and the unmount lets go of the observers of a timeline that left (ED-10 review)."""
    names = (DRAG_CORE_SCRIPT, DRAG_SCRIPT, INSERT_SCRIPT, SCRIPT)
    script = ";".join(asset_script(name) for name in names)
    return rx.box(
        display="none",
        on_mount=rx.call_script(script),
        on_unmount=rx.call_script("window.__qTimeline && window.__qTimeline.sweep();"),
    )


#: The global the script fills before pressing the hidden key button.
KEY_GLOBAL = "window.__qTimelineKey"


def _key_trigger(on_key: Callable[[str, str, str], Any]) -> rx.Component:
    """The hidden button the script presses on ←/→/Escape over a block or a handle (an
    `rx.el.button`/`div` takes no `on_key_down` here); the handler receives
    `(id, edge, key)` read from `KEY_GLOBAL` — ``edge`` is "" for the block itself."""

    def read(field: str) -> rx.Var:
        return rx.Var(f"String(({KEY_GLOBAL} || {{}}).{field} || '')", _var_type=str)

    return rx.el.button(
        type="button",
        on_click=on_key(read("id"), read("edge"), read("key")),
        tab_index=-1,
        aria_hidden="true",
        display="none",
        custom_attrs={"data-tl-key-trigger": ""},
    )


#: The global the drag script fills before pressing the hidden drop button.
DROP_GLOBAL = "window.__qTimelineDrop"


def _drag_trigger(on_drag: Callable[[str, str, float], Any]) -> rx.Component:
    """The hidden button `assets/timeline-drag.js` presses when a block is dropped: the
    handler receives `(id, what, value)` — «move» and the new index of a video or photo,
    «time» and the new start (seconds) of a text or effect, or (ED-03) «start»/«end» and
    where a handle was released."""
    block_id = rx.Var(f"String(({DROP_GLOBAL} || {{}}).id || '')", _var_type=str)
    what = rx.Var(f"String(({DROP_GLOBAL} || {{}}).what || '')", _var_type=str)
    value = rx.Var(f"Number(({DROP_GLOBAL} || {{}}).value || 0)", _var_type=float)
    return rx.el.button(
        type="button",
        on_click=on_drag(block_id, what, value),
        tab_index=-1,
        aria_hidden="true",
        display="none",
        custom_attrs={"data-tl-drag-trigger": ""},
    )


def _handle(row: Any, edge: str) -> rx.Component:
    """One handle of the chosen block: a slider the keyboard moves ½ s with ←/→, and —
    ED-03 m-25026623 — a finger or a mouse drags at once (`assets/timeline-drag.js`; no
    long press: it is not the block's move). Its value is in the handle's own unit —
    seconds of the video for a video's piece, of the final video for a text or effect —
    within `aria-valuemin`/`-max`; ``data-tl-at`` (where the block starts on the track),
    ``data-tl-from`` (the value its start handle has) and ``data-tl-speed`` place it on
    the track."""
    return rx.el.div(
        rx.el.span(class_name="q-tl__grip", aria_hidden="true"),
        tab_index=0,
        class_name=f"q-tl__handle q-tl__handle--{edge}",
        custom_attrs={
            "role": "slider",
            "aria-label": row[f"{edge}_handle"],
            # «Desde 0:04» / «Hasta 0:09» (ED-03 UX review)
            "aria-valuetext": row[f"{edge}_value"],
            "aria-valuenow": row[f"{edge}_now"],
            "aria-valuemin": row[f"{edge}_min"],
            "aria-valuemax": row[f"{edge}_max"],
            "aria-orientation": "horizontal",
            # ED-14: why it stops at an edge, when the row says it (``*_why``, an id; ""
            # points at nothing)
            "aria-describedby": row[f"{edge}_why"],
            "data-tl-handle": edge,
            "data-tl-id": row["id"],
            "data-tl-at": row["start"],
            "data-tl-from": row["start_now"],
            "data-tl-speed": row["speed"],
            # the bubble's word while it is dragged («Desde», «Hasta», «Empieza»…)
            "data-tl-word": row[f"{edge}_label"],
        },
    )


def _picture(src: rx.Var[str]) -> rx.Component:
    """ED-11 (m-25026650): a block's picture — one `<img alt="">` at its start (the
    block's name already says what it is) and the same picture repeated along the rest
    (`background-repeat: repeat-x`, `.q-tl__pic`), so a wide block reads as a strip
    and a narrow one shows only the picture. Never a new frame: ``src`` is a picture the
    screen already holds."""
    return rx.el.span(
        rx.el.img(
            src=src,
            alt="",
            class_name="q-tl__pic-img",
            loading="lazy",
            decoding="async",
            draggable=False,
        ),
        class_name="q-tl__pic",
        aria_hidden="true",
        style={"backgroundImage": rx.Var.create('url("') + src + '")'},
    )


def _block(
    row: Any,
    *,
    selected: rx.Var[str],
    on_select: Callable[[str], Any],
    thumb_base: rx.Var[str] | str = "",
    overlap: bool = False,
) -> rx.Component:
    chosen = row["id"] == selected
    # ED-11: a video or a photo with a picture shows it under its name and seconds
    # (`_picture`); without one, the frame with the film / photo icon and its name — never
    # an empty box. A text «Aa», an effect ✦.
    pic = row["thumb"] != ""
    thumb = {"size": "40px", "icon_size": T.ICON_MD}
    icon = rx.match(
        row["kind"],
        ("video", media_thumb("", icon="film", **thumb)),
        ("photo", media_thumb("", icon="image", **thumb)),
        ("text", rx.el.span("Aa", class_name="q-tl__aa")),
        rx.icon("sparkles", size=T.ICON_SM),
    )
    # ED-11 review: under the picture, its film / photo icon centred on the block — it
    # shows through when the picture does not load (a `/r2media` token past its hour) or
    # is hidden (high contrast), so the block is never a bare grey box. No script.
    under = rx.el.span(
        rx.cond(
            row["kind"] == "photo",
            rx.icon("image", size=T.ICON_MD),
            rx.icon("film", size=T.ICON_MD),
        ),
        class_name="q-tl__pic-fallback",
        aria_hidden="true",
    )
    button = rx.el.button(
        rx.cond(
            pic,
            rx.fragment(under, _picture(thumb_base + row["thumb"])),
            rx.el.span(icon, class_name="q-tl__icon", aria_hidden="true"),
        ),
        rx.el.span(row["label"], class_name="q-tl__label", aria_hidden="true"),
        rx.cond(
            pic & (row["secs"] != ""),
            rx.el.span(row["secs"], class_name="q-tl__secs", aria_hidden="true"),
        ),
        rx.cond(
            row["speed_tag"] != "",
            rx.el.span(row["speed_tag"], class_name="q-tl__speed", aria_hidden="true"),
        ),
        type="button",
        class_name="q-tl__block",
        on_click=on_select(row["id"]),
        aria_label=row["name"],
        aria_pressed=rx.cond(chosen, "true", "false"),
        custom_attrs={
            # its help is read once, from the timeline's hidden span (`vm.HELP_IDS`)
            "aria-describedby": row["help_id"],
            "data-tl-block": row["kind"],
            "data-tl-id": row["id"],
            # where it sits and how long, in seconds (the drag reads them)
            "data-tl-start": row["start"],
            "data-tl-len": row["length"],
            # ED-11: it shows its picture (the name and seconds go over it)
            "data-tl-pic": rx.cond(pic, "1", "0"),
            # ED-13: in a clash (two texts in one place at once) — the warning tone
            "data-tl-warn": rx.cond(row["warn"] == "1", "1", "0"),
        },
    )
    # m-25114465 («bloques enteros, encimados»): the start of a «Fotos y videos» block
    # laid over the block before it — its transition in — marked with the transition's
    # stripes (Deivid, option A: its icon goes on the join's point). Only a picture: the
    # join's point says it in words (`_join`'s name), nothing here takes the focus or is
    # read twice. The block's name and picture start after it (`data-tl-in`).
    overlay = (
        [
            rx.cond(
                row["join_kind"] != "",
                rx.el.span(
                    class_name="q-tl__overlap",
                    aria_hidden="true",
                    style={"--b-in": row["join_in"]},
                ),
            )
        ]
        if overlap
        else []
    )
    return rx.el.div(
        button,
        *overlay,
        # a row may say it has no handles the screen moves yet (``handles`` "")
        rx.cond(
            chosen & (row["handles"] != ""),
            rx.fragment(
                rx.cond(row["has_start"] != "", _handle(row, "start")),
                _handle(row, "end"),
            ),
        ),
        role="listitem",
        class_name="q-tl__item",
        style={
            "--b-start": row["start"],
            "--b-len": row["length"],
            **({"--b-in": row["join_in"]} if overlap else {}),
        },
        custom_attrs={
            "data-tl-chosen": rx.cond(chosen, "true", "false"),
            **({"data-tl-in": rx.cond(row["join_kind"] != "", "1", "")} if overlap else {}),
            # ED-14: it starts / ends the track — that handle sits inside the block
            "data-tl-at-start": row["at_start"],
            "data-tl-at-end": row["at_end"],
        },
    )


def _lane(
    track: str,
    rows: Rows,
    **block_props: Any,
) -> rx.Component:
    """One track. An empty one stays a blank row of the same height (no hint text); its
    accessible name says it is empty."""
    label = vm.TRACK_LABELS[track]
    media = track == vm.TRACK_MEDIA
    return rx.el.div(
        rx.foreach(rows, lambda row: _block(row, overlap=media, **block_props)),
        role="list",
        aria_label=rx.cond(
            rows.length() > 0,  # type: ignore[attr-defined]
            label,
            vm.EMPTY_TRACK_NAMES[track],
        ),
        class_name=f"q-tl__lane q-tl__lane--{track}",
    )


def _effect_lane(rows: Any, names: Any, **block_props: Any) -> rx.Component:
    """ED-04 (m-25026627): one row of «Efectos»: its blocks, named «Efectos
    2» (``names["name"]``) or, empty, «Pista de efectos 2 vacía» (``names["empty"]``)."""
    return rx.el.div(
        rx.foreach(rows, lambda row: _block(row, **block_props)),
        role="list",
        aria_label=rx.cond(rows.length() > 0, names["name"], names["empty"]),
        class_name=f"q-tl__lane q-tl__lane--{vm.TRACK_EFFECT}",
        # the row a block dragged up or down lands on (`assets/timeline-drag.js`)
        custom_attrs={"data-tl-lane": names["index"]},
    )


def _join(row: Any, on_join: Callable[[str], Any], selected: rx.Var[str]) -> rx.Component:
    """m-25114465 «la unión»: the point between two blocks of «Fotos y videos», a button
    named with its choice («Unión entre Video 1 y Foto 2: Corte»), centred on the overlap
    of the two blocks (``row["at"]``, seconds) and riding the track's TOP edge, as
    CapCut's transition button (`.q-tl__join`: absolute, it takes no room). While a block
    touching it is chosen (the one after, the one before it in the recipe or on the track)
    its trim handles sit right there and win: the point hides and leaves the tab order
    (``data-join-off``); one a handle only reaches is dimmed by `assets/timeline.js`
    (``data-join-near``). ``aria-expanded`` while its panel shows."""
    off = (selected != "") & (
        (row["id"] == selected) | (row["before"] == selected) | (row["beside"] == selected)
    )
    # Deivid (option A): a «Fundido» / «Barrido» point carries its icon, white on the
    # accent, CapCut-like; a «Corte» point is empty. A picture only: the name says it
    icon = rx.match(
        row["kind"],
        ("fundido", rx.icon("blend", size=12, class_name="q-tl__join-icon")),
        ("barrido", rx.icon("arrow-left-right", size=12, class_name="q-tl__join-icon")),
        rx.fragment(),
    )
    return rx.el.button(
        rx.el.span(icon, class_name="q-tl__join-dot", aria_hidden="true"),
        type="button",
        class_name="q-tl__join",
        on_click=on_join(row["id"]),
        aria_label=row["name"],
        title=row["name"],
        aria_expanded=rx.cond(row["open"] == "1", "true", "false"),
        style={"--j-at": row["at"]},
        custom_attrs={
            "data-join-kind": row["kind"],
            "data-join-warn": row["warn"],
            "data-join-id": row["id"],
            "data-join-off": rx.cond(off, "1", ""),
        },
        tab_index=rx.cond(off, -1, 0),
    )


def _joins(joins: Rows, on_join: Callable[[str], Any], selected: rx.Var[str]) -> rx.Component:
    """Every join, as a layer laid OVER «Fotos y videos» (Deivid 2026-11-26: «las pistas
    se mueven hacia abajo, no me gusta» — no row of its own): absolute, no height, no
    margin, so every track stays exactly where it was. Each point rides the track's top
    edge (half of it in the gap above), its target 24 px wide (WCAG 2.5.8's minimum, ~12
    px over each block at 375 px) and 44 px tall; the layer itself lets every other tap
    through to the blocks."""
    return rx.el.div(
        rx.foreach(joins, lambda row: _join(row, on_join, selected)),
        class_name="q-tl__joins",
    )


def _direction_item(way: Any) -> rx.Component:
    """One of «← Izquierda · → Derecha · ↑ Arriba · ↓ Abajo»: its arrow (the way the
    block moves in, `clip_joins_vm.DIRECTION_ICONS`) before its word."""
    arrow = rx.match(
        way["value"],
        ("right", rx.icon("arrow-right", size=16, aria_hidden="true")),
        ("up", rx.icon("arrow-up", size=16, aria_hidden="true")),
        ("down", rx.icon("arrow-down", size=16, aria_hidden="true")),
        rx.icon("arrow-left", size=16, aria_hidden="true"),
    )
    return rx.segmented_control.item(
        rx.el.span(arrow, way["label"], class_name="q-tl-join-way"),
        value=way["value"],
        min_height="44px",
        aria_label=way["label"],
        title=way["label"],
    )


def timeline_join_panel(
    row: Row,
    choices: rx.Var[list[dict[str, str]]],
    *,
    on_change: Callable[[Any], Any],
    on_done: Any,
    help_text: str,
    seconds: rx.Var[float] | float = 0.0,
    seconds_min: rx.Var[float] | float = 0.0,
    seconds_max: rx.Var[float] | float = 1.0,
    seconds_step: float = 0.1,
    on_seconds: Callable[[Any], Any] | None = None,
    directions: rx.Var[list[dict[str, str]]] | None = None,
    on_direction: Callable[[Any], Any] | None = None,
) -> rx.Component:
    """m-25114465: the open join's panel — its title («Unión entre el bloque 1 y el 2»),
    ``help_text``, its choices on the kit's segmented menu («Corte · Fundido ·
    Barrido», only those that fit: ``choices`` rows ``{value, label}``), why only
    «Corte» when that is all (``row["why"]``), the server's warning when a block is too
    short for its transitions (``row["problem"]``), how much longer the video takes to
    be ready with the choice (``row["slower"]``) and «Listo»."""
    return rx.el.div(
        rx.text(row["title"], size="2", weight="bold"),
        rx.text(help_text, size="1", color=T.TEXT_MUTED),
        rx.box(
            rx.segmented_control.root(
                rx.foreach(
                    choices,
                    lambda choice: rx.segmented_control.item(
                        choice["label"],
                        value=choice["value"],
                        min_height="44px",
                        aria_label=choice["label"],
                        title=choice["label"],
                    ),
                ),
                value=row["kind"],
                on_change=on_change,
                size="2",
                aria_label=row["title"],
                class_name="q-source-seg q-tl-seg q-seg-fill",
            ),
            width="100%",
            min_width="0",
        ),
        rx.cond(row["why"] != "", rx.text(row["why"], size="1", color=T.TEXT_MUTED)),
        *(
            [
                # Deivid 2026-11-26: the duration on the same bar as a text's fade
                # (`ui.text_panel._fade_row`): «Dura 0,5 s» over a Radix slider, 0,1 s a
                # step, the arrows move it, named by its own words; never past what fits
                rx.cond(
                    row["has_seconds"] == "1",
                    rx.el.div(
                        rx.text(
                            row["seconds_line"],
                            size="2",
                            weight="medium",
                            class_name="q-nums",
                            id="clip-join-seconds-line",
                        ),
                        rx.text(row["overlap_line"], size="1", color=T.TEXT_MUTED),
                        rx.slider(
                            default_value=[seconds],
                            value=[seconds],
                            min=seconds_min,
                            max=seconds_max,
                            step=seconds_step,
                            on_change=on_seconds,
                            size="2",
                            width="100%",
                            aria_label=row["seconds_label"],
                            # «0,5 segundos»: `assets/timeline.js` puts it on the thumb
                            # (Radix Themes passes no props to it)
                            custom_attrs={"data-join-seconds": ""},
                        ),
                        class_name="q-tl-panel__field",
                    ),
                )
            ]
            if on_seconds is not None
            else []
        ),
        *(
            [
                # a wipe's way: «Izquierda · Derecha · Arriba · Abajo», a named group on
                # the kit's segmented menu (Radix radios: 44 px, the arrows move)
                rx.cond(
                    row["has_direction"] == "1",
                    rx.el.div(
                        rx.text(row["direction_title"], size="2", weight="medium"),
                        rx.box(
                            rx.segmented_control.root(
                                rx.foreach(directions, _direction_item),
                                value=row["direction"],
                                on_change=on_direction,
                                size="2",
                                aria_label=row["direction_title"],
                                class_name="q-source-seg q-tl-seg q-seg-fill",
                            ),
                            width="100%",
                            min_width="0",
                        ),
                        class_name="q-tl-panel__field",
                    ),
                )
            ]
            if directions is not None and on_direction is not None
            else []
        ),
        rx.cond(
            row["problem"] != "",
            rx.text(
                row["problem"],
                size="2",
                weight="medium",
                role="status",
                class_name="q-tl-panel__warn",
            ),
        ),
        rx.cond(
            row["slower"] != "",
            rx.hstack(
                rx.icon("clock", size=T.ICON_SM, aria_hidden="true"),
                rx.text(row["slower"], size="1"),
                spacing="1",
                align="center",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.el.div(
            rx.button(
                vm.DONE_LABEL, type="button", on_click=on_done, class_name="q-tl-actions__btn"
            ),
            class_name="q-tl-panel__done",
        ),
        class_name="q-tl-panel",
        tab_index=-1,
        role="group",
        aria_label=row["title"],
        custom_attrs={"data-tl-join-panel": row["id"]},
    )


def timeline(
    *,
    media: Rows,
    texts: Rows,
    effects: Rows,
    ticks: Rows,
    total: rx.Var[str] | str,
    selected: rx.Var[str],
    on_select: Callable[[str], Any],
    status: rx.Var[str] | str = "",
    on_key: Callable[[str, str, str], Any] | None = None,
    on_drag: Callable[[str, str, float], Any] | None = None,
    status_action: rx.Component | None = None,
    effect_lanes: rx.Var[list[list[dict[str, str]]]] | None = None,
    effect_lane_names: rx.Var[list[dict[str, str]]] | None = None,
    thumb_base: rx.Var[str] | str = "",
    joins: Rows | None = None,
    on_join: Callable[[str], Any] | None = None,
) -> rx.Component:
    """The timeline of one video.

    m-25114465: with ``joins`` (rows `{id, at, kind, name, open, warn}`) and ``on_join(id)``
    a point sits on the line between every two blocks of «Fotos y videos» — «la unión»
    (`_join`); tapped, the screen shows its panel (`timeline_join_panel`).

    ``media`` / ``texts`` / ``effects``: rows of `timeline_vm.media_blocks` /
    `overlay_blocks`; ``ticks``: `timeline_vm.ticks`; ``total``: the length in seconds
    as a string (`timeline_vm.total_seconds`, for the CSS and the playhead's max).
    ``selected``: the chosen block's id ("" = none). ``on_select(id)``: a block was
    clicked (or Enter). ``on_key(id, edge, key)``: ←/→/Escape on a block (``edge`` "":
    ←/→ move it, Escape lets it go — §3.7) or on a handle (``edge`` "start"/"end": ←/→ =
    ½ s).
    ``status``: the live line («Moviste el video 2.»), a polite `role="status"`;
    ``status_action`` sits beside it (the editor's hint). ``on_drag(id, what,
    value)``: a block dropped (ED-10, `assets/timeline-drag.js`) — «move» with the new
    index of a video or photo, «time» with the new start of a text or effect, and
    (ED-03) «start»/«end» with a handle's new value in its own unit; without it nothing
    drags. The playhead is the browser's (`timeline_script`, mounted by the screen).

    ED-04 (m-25026627): with ``effect_lanes`` (its rows' blocks, row by row) and
    ``effect_lane_names`` (``{"name", "empty"}`` each) «Efectos» is several rows — the
    owner's effects never overlapping on a row; an effect dragged up or down changes
    row (`assets/timeline-drag.js`).

    ED-11 (m-25026650): ``thumb_base`` goes before each media row's ``thumb`` path (the
    browser's backend origin; "" when the rows carry whole addresses)."""
    block_props = {"selected": selected, "on_select": on_select, "thumb_base": thumb_base}
    lanes = effect_lanes is not None and effect_lane_names is not None
    effect_names: list[rx.Component] = [
        rx.foreach(
            effect_lane_names,  # type: ignore[arg-type]
            lambda names: rx.el.span(
                names["name"], class_name=f"q-tl__name q-tl__name--{vm.TRACK_EFFECT}"
            ),
        )
        if lanes
        else rx.el.span(
            vm.TRACK_LABELS[vm.TRACK_EFFECT], class_name=f"q-tl__name q-tl__name--{vm.TRACK_EFFECT}"
        )
    ]
    names = rx.el.div(
        rx.el.span(class_name="q-tl__name q-tl__name--ruler"),
        rx.el.span(
            vm.TRACK_LABELS[vm.TRACK_MEDIA], class_name=f"q-tl__name q-tl__name--{vm.TRACK_MEDIA}"
        ),
        rx.el.span(
            vm.TRACK_LABELS[vm.TRACK_TEXT], class_name=f"q-tl__name q-tl__name--{vm.TRACK_TEXT}"
        ),
        *effect_names,
        class_name="q-tl__names",
        aria_hidden="true",
    )
    effect_rows = (
        rx.foreach(
            effect_lanes,  # type: ignore[arg-type]
            lambda rows, i: _effect_lane(rows, effect_lane_names[i], **block_props),  # type: ignore[index]
        )
        if lanes
        else _lane(vm.TRACK_EFFECT, effects, **block_props)
    )
    ruler = rx.el.div(
        rx.foreach(
            ticks,
            lambda tick: rx.el.span(
                tick["text"], class_name="q-tl__tick", style={"--b-start": tick["at"]}
            ),
        ),
        class_name="q-tl__ruler",
        aria_hidden="true",
    )
    scrub = rx.el.input(
        type="range",
        min="0",
        max=total,
        step=str(vm.STEP_S),
        default_value="0",
        class_name="q-tl__scrub",
        aria_label=vm.PLAYHEAD_LABEL,
    )
    media_lane = _lane(vm.TRACK_MEDIA, media, **block_props)
    if joins is not None and on_join is not None:
        # m-25114465: the joins lie over the media track — its box is the track's own
        # height (`.q-tl__media`), so nothing below it moves
        media_lane = rx.el.div(
            media_lane, _joins(joins, on_join, selected), class_name="q-tl__media"
        )
    canvas = rx.el.div(
        ruler,
        scrub,
        media_lane,
        _lane(vm.TRACK_TEXT, texts, **block_props),
        effect_rows,
        rx.el.div(class_name="q-tl__head q-tl__head--move", aria_hidden="true"),
        class_name="q-tl__canvas",
    )
    return rx.el.div(
        rx.el.div(
            rx.el.span(class_name="q-tl__clock", aria_hidden="true"),
            class_name="q-tl__top",
        ),
        rx.el.div(
            names,
            rx.el.div(canvas, class_name="q-tl__scroller"),
            rx.el.div(class_name="q-tl__head q-tl__head--fixed", aria_hidden="true"),
            class_name="q-tl__frame",
        ),
        rx.el.div(
            rx.el.p(status, role="status", class_name="q-tl__status"),
            *([status_action] if status_action is not None else []),
            class_name="q-tl__live",
        ),
        # the blocks' help, read through `aria-describedby` (never shown)
        rx.el.div(
            *(rx.el.span(text, id=help_id) for text, help_id in vm.HELP_IDS.items()),
            class_name="q-edit-sr",
        ),
        *([_key_trigger(on_key)] if on_key is not None else []),
        *([_drag_trigger(on_drag)] if on_drag is not None else []),
        role="group",
        aria_label=vm.GROUP_LABEL,
        class_name="q-tl",
        style={"--tl-total": total, "--tl-px": f"{vm.PX_PER_SECOND}px"},
        custom_attrs={
            "data-q-timeline": "",
            "data-tl-lift-text": vm.LIFT_HINT,
            **({} if on_drag is not None else {"data-tl-no-drag": ""}),
        },
    )


def _action_button(label: str, icon: str, on_action: Callable[[str], Any] | None) -> rx.Component:
    props: dict[str, Any] = {}
    if on_action is not None:
        props["on_click"] = on_action(label)
    return rx.button(
        rx.icon(icon, size=T.ICON_SM, aria_hidden="true"),
        label,
        variant="surface",
        type="button",
        class_name="q-tl-actions__btn",
        **props,
    )


def timeline_add(
    on_add: Callable[[str], Any],
    *,
    off: Mapping[str, Any] | None = None,
    note: rx.Var[str] | str = "",
) -> rx.Component:
    """«Agregar» with nothing chosen: the kit's `orbit_menu` — «+» turns into «×» and
    opens «Foto o video · Texto · Efecto · Idea» to its right. ``on_add(key)`` OPENS the
    flow of that option (the drawer, the text field, the effects list), never adds by
    itself. ``off``: an option's key → a `Var[bool]` that turns it off; ``note``: why,
    said on its own line ABOVE the «+» while it is not "" — never beside it, where the
    options open over it (ED-12: «Tu video ya tiene 8 fotos o videos. Quita una para
    agregar otra.») —, with an id the «+» names in `aria-describedby` (`ADD_NOTE_ID`)."""
    shut = dict(off or {})
    saying = rx.Var.create(note) != ""
    return rx.el.div(
        rx.cond(
            saying,
            rx.text(
                note, size="2", color=T.TEXT_MUTED, class_name="q-tl-add__note", id=ADD_NOTE_ID
            ),
        ),
        rx.el.div(
            orbit_menu(
                vm.ADD_LABEL,
                [
                    OrbitItem(key, icon, text, on_add(key), disabled=shut.get(key, False))
                    for key, icon, text in vm.ADD_OPTIONS
                ],
                # Deivid, 2026-11-16: the options open to the right of the «+», not above it
                direction="right",
                # the «+» is described by its why while there is one (UX review S4)
                described_by=rx.cond(saying, ADD_NOTE_ID, ""),
            ),
            class_name="q-tl-add__row",
        ),
        class_name="q-tl-add",
    )


def timeline_actions(
    kind: rx.Var[str],
    *,
    on_add: Callable[[str], Any],
    on_action: Callable[[str], Any] | None = None,
    label: rx.Var[str] | str = "",
    actions: dict[str, tuple[tuple[str, str], ...]] | None = None,
    add_off: Mapping[str, Any] | None = None,
    add_note: rx.Var[str] | str = "",
) -> rx.Component:
    """What the owner can do now (§2): with nothing chosen (``kind`` ""), «Agregar»
    (`timeline_add`); with a video, a photo, a text or an effect chosen, its up-to-4
    `surface` buttons floating in a glass island (`.q-island`). ``on_action(label)``.
    ``label``: the chosen block's short name — the bar is «Acciones de Video 1»
    (`aria-label`). ``actions``: a screen's own buttons by kind (default `vm.ACTIONS`;
    a kind with none shows no island). ``add_off`` / ``add_note``: «Agregar»'s options
    turned off and why (`timeline_add`)."""
    by_kind = vm.ACTIONS if actions is None else actions
    name: rx.Var[str] | str = (
        vm.actions_label(label)
        if isinstance(label, str)
        else rx.cond(label != "", vm.ACTIONS_PREFIX + label, "Acciones")
    )

    def bar(key: str) -> rx.Component:
        items = by_kind.get(key, ())
        if not items:
            return rx.fragment()
        return rx.el.div(
            *(_action_button(text, icon, on_action) for text, icon in items),
            class_name="q-island q-tl-island q-tl-actions",
            role="toolbar",
            aria_label=name,
        )

    return rx.match(
        kind,
        *((key, bar(key)) for key in ("video", "photo", "text", "effect")),
        timeline_add(on_add, off=add_off, note=add_note),
    )


def _segmented(
    options: Sequence[tuple[str, str, str]],
    *,
    value: Any,
    on_change: Callable[[Any], Any],
    label: str,
) -> rx.Component:
    """The kit's segmented menu (`.q-source-seg`): Radix radios, 44 px, arrows move."""
    return rx.box(
        rx.segmented_control.root(
            *(
                # plain text: `.q-source-seg__text` hides the label of an unchosen item
                # (the icon-and-name tools pattern); these options have no icon
                rx.segmented_control.item(
                    text,
                    value=key,
                    min_height="44px",
                    aria_label=name,
                    title=name,
                )
                for key, text, name in options
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


def _nudge_row(
    label: rx.Var[str], row: Row, edge: str, on_nudge: Callable[[str, str, float], Any]
) -> rx.Component:
    """«Desde 0:04 [− ½ s] [+ ½ s]»: the value beside its buttons (ED-10 UX note), so the
    owner sees what each tap did; the group is named by the plain label («Desde»)."""
    return rx.el.div(
        rx.text(
            row[f"{edge}_value"],
            size="2",
            weight="medium",
            class_name="q-tl-panel__label q-nums",
        ),
        rx.button(
            vm.MINUS_HALF,
            variant="soft",
            color_scheme="gray",
            type="button",
            class_name="q-tl-actions__btn",
            on_click=on_nudge(row["id"], edge, -vm.STEP_S),
        ),
        rx.button(
            vm.PLUS_HALF,
            variant="soft",
            color_scheme="gray",
            type="button",
            class_name="q-tl-actions__btn",
            on_click=on_nudge(row["id"], edge, vm.STEP_S),
        ),
        class_name="q-tl-panel__row",
        role="group",
        aria_label=label,
    )


def timeline_panel(
    row: Row,
    *,
    on_nudge: Callable[[str, str, float], Any],
    on_done: Any,
    on_speed: Callable[[str, str], Any] | None = None,
    on_place: Callable[[str, str], Any] | None = None,
    extra: rx.Component | None = None,
    nudges: rx.Var[bool] | bool = True,
) -> rx.Component:
    """The chosen block's panel (§1.2/§1.3): its title, «Desde/Hasta» (a video),
    «Duración» (a photo) or «Empieza/Termina» (a text or effect) with «− ½ s / + ½ s»,
    «Velocidad» Normal · ×5 · ×10 · ×20 for a video (``on_speed(id, value)``), the
    text's place «Arriba · En el medio · Abajo» (``on_place(id, value)``), and «Listo»,
    which lets the block go. ``on_nudge(id, edge, delta)``; ``nudges`` False hides the
    «− ½ s / + ½ s» rows (a block whose times the screen cannot change yet). ``extra``:
    the screen's own fields, before «Listo». Escape inside the panel lets the block go
    too (`assets/timeline.js`, `data-tl-panel`)."""
    extras: list[rx.Component] = []
    if on_speed is not None:
        extras.append(
            rx.cond(
                row["kind"] == "video",
                rx.el.div(
                    rx.text(vm.SPEED_LABEL, size="2", weight="medium"),
                    _segmented(
                        vm.SPEEDS,
                        value=row["speed"],
                        on_change=lambda value: on_speed(row["id"], value),
                        label=vm.SPEED_LABEL,
                    ),
                    class_name="q-tl-panel__field",
                ),
            )
        )
    if on_place is not None:
        extras.append(
            rx.cond(
                row["kind"] == "text",
                rx.el.div(
                    rx.text(vm.PLACE_LABEL, size="2", weight="medium"),
                    _segmented(
                        [(key, text, text) for key, text in vm.PLACES],
                        value=row["place"],
                        on_change=lambda value: on_place(row["id"], value),
                        label=vm.PLACE_LABEL,
                    ),
                    class_name="q-tl-panel__field",
                ),
            )
        )
    rows = rx.fragment(
        rx.cond(
            row["start_label"] != "",
            _nudge_row(row["start_label"], row, "start", on_nudge),
        ),
        _nudge_row(row["end_label"], row, "end", on_nudge),
    )
    return rx.el.div(
        rx.text(row["panel"], size="2", weight="bold"),
        rows if isinstance(nudges, bool) and nudges else rx.cond(nudges, rows),
        *extras,
        *([extra] if extra is not None else []),
        rx.el.div(
            rx.button(
                vm.DONE_LABEL, type="button", on_click=on_done, class_name="q-tl-actions__btn"
            ),
            class_name="q-tl-panel__done",
        ),
        class_name="q-tl-panel",
        tab_index=-1,
        role="group",
        aria_label=row["panel"],
        custom_attrs={"data-tl-panel": row["id"]},
    )


def timeline_layout(
    timeline_view: rx.Component,
    actions: rx.Component,
    panel: rx.Component | None = None,
    *,
    bar_below: bool = False,
) -> rx.Component:
    """The timeline with its action bar and its panel, in their places: on a phone the
    bar sits ABOVE the tracks (in the flow: it never covers the tracks nor the
    playhead), on a desktop under them; the panel always last (`.q-tl-stack`).
    ``bar_below``: the bar under the tracks at every size (the editor, ED-10: preview,
    tracks, bar, panel — top to bottom)."""
    return rx.el.div(
        rx.el.div(actions, class_name="q-tl-stack__actions"),
        rx.el.div(timeline_view, class_name="q-tl-stack__track"),
        *([rx.el.div(panel, class_name="q-tl-stack__panel")] if panel is not None else []),
        class_name="q-tl-stack q-tl-stack--bar-below" if bar_below else "q-tl-stack",
    )
