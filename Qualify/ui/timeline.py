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

from collections.abc import Callable, Sequence
from typing import Any

import reflex as rx

from . import timeline_vm as vm
from . import tokens as T
from .primitives import OrbitItem, asset_script, media_thumb, orbit_menu

#: The script's name under `assets/`.
SCRIPT = "timeline.js"

Rows = rx.Var[list[dict[str, str]]]
Row = rx.Var[dict[str, str]]


def timeline_script() -> rx.Component:
    """Mount `assets/timeline.js` once (its guard keeps one set of listeners)."""
    return rx.box(display="none", on_mount=rx.call_script(asset_script(SCRIPT)))


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


def _handle(row: Any, edge: str) -> rx.Component:
    """One handle of the chosen block: a slider the keyboard moves ½ s with ←/→."""
    return rx.el.div(
        rx.el.span(class_name="q-tl__grip", aria_hidden="true"),
        tab_index=0,
        class_name=f"q-tl__handle q-tl__handle--{edge}",
        custom_attrs={
            "role": "slider",
            "aria-label": row[f"{edge}_handle"],
            "aria-valuetext": row[f"{edge}_text"],
            "aria-valuenow": row[f"{edge}_now"],
            "aria-valuemin": row[f"{edge}_min"],
            "aria-valuemax": row[f"{edge}_max"],
            "aria-orientation": "horizontal",
            "data-tl-handle": edge,
            "data-tl-id": row["id"],
        },
    )


def _block(
    row: Any,
    *,
    selected: rx.Var[str],
    on_select: Callable[[str], Any],
) -> rx.Component:
    chosen = row["id"] == selected
    # A video or a photo shows its picture (`media_thumb`; ``thumb`` "" = the frame with
    # the film / photo icon until ED-11 brings the real frame); a text «Aa», an effect ✦.
    thumb = {"size": "40px", "icon_size": T.ICON_MD, "alt": ""}
    icon = rx.match(
        row["kind"],
        ("video", media_thumb(row["thumb"], icon="film", **thumb)),
        ("photo", media_thumb(row["thumb"], icon="image", **thumb)),
        ("text", rx.el.span("Aa", class_name="q-tl__aa")),
        rx.icon("sparkles", size=T.ICON_SM),
    )
    button = rx.el.button(
        rx.el.span(icon, class_name="q-tl__icon", aria_hidden="true"),
        rx.el.span(row["label"], class_name="q-tl__label", aria_hidden="true"),
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
            "aria-description": row["help"],
            "data-tl-block": row["kind"],
            "data-tl-id": row["id"],
        },
    )
    return rx.el.div(
        button,
        rx.cond(
            chosen,
            rx.fragment(
                rx.cond(row["has_start"] != "", _handle(row, "start")),
                _handle(row, "end"),
            ),
        ),
        role="listitem",
        class_name="q-tl__item",
        style={"--b-start": row["start"], "--b-len": row["length"]},
        custom_attrs={"data-tl-chosen": rx.cond(chosen, "true", "false")},
    )


def _lane(
    track: str,
    rows: Rows,
    *,
    empty_hint: bool,
    **block_props: Any,
) -> rx.Component:
    blocks = rx.foreach(rows, lambda row: _block(row, **block_props))
    content: rx.Component = blocks
    if empty_hint:
        content = rx.cond(
            rows.length() > 0,  # type: ignore[attr-defined]
            blocks,
            rx.el.div(
                rx.el.span(vm.EMPTY_HINT_PHONE[track], class_name="q-tl__hint-phone"),
                rx.el.span(vm.EMPTY_HINT_DESKTOP[track], class_name="q-tl__hint-desk"),
                class_name="q-tl__empty",
            ),
        )
    return rx.el.div(
        content,
        role="list",
        aria_label=vm.TRACK_LABELS[track],
        class_name=f"q-tl__lane q-tl__lane--{track}",
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
) -> rx.Component:
    """The timeline of one video.

    ``media`` / ``texts`` / ``effects``: rows of `timeline_vm.media_blocks` /
    `overlay_blocks`; ``ticks``: `timeline_vm.ticks`; ``total``: the length in seconds
    as a string (`timeline_vm.total_seconds`, for the CSS and the playhead's max).
    ``selected``: the chosen block's id ("" = none). ``on_select(id)``: a block was
    clicked (or Enter). ``on_key(id, edge, key)``: ←/→/Escape on a block (``edge`` "":
    ←/→ move it, Escape lets it go — §3.7) or on a handle (``edge`` "start"/"end": ←/→ =
    ½ s).
    ``status``: the live line («Moviste el video 2.»). The playhead is the browser's
    (`timeline_script`, mounted by the screen once)."""
    block_props = {"selected": selected, "on_select": on_select}
    names = rx.el.div(
        rx.el.span(class_name="q-tl__name q-tl__name--ruler"),
        *(
            rx.el.span(vm.TRACK_LABELS[track], class_name=f"q-tl__name q-tl__name--{track}")
            for track in (vm.TRACK_MEDIA, vm.TRACK_TEXT, vm.TRACK_EFFECT)
        ),
        class_name="q-tl__names",
        aria_hidden="true",
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
    canvas = rx.el.div(
        ruler,
        scrub,
        _lane(vm.TRACK_MEDIA, media, empty_hint=False, **block_props),
        _lane(vm.TRACK_TEXT, texts, empty_hint=True, **block_props),
        _lane(vm.TRACK_EFFECT, effects, empty_hint=True, **block_props),
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
        rx.el.p(status, role="status", class_name="q-tl__status"),
        *([_key_trigger(on_key)] if on_key is not None else []),
        role="group",
        aria_label=vm.GROUP_LABEL,
        class_name="q-tl",
        style={"--tl-total": total, "--tl-px": f"{vm.PX_PER_SECOND}px"},
        custom_attrs={"data-q-timeline": ""},
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


def timeline_add(on_add: Callable[[str], Any]) -> rx.Component:
    """«Agregar» with nothing chosen: the kit's `orbit_menu` — «+» turns into «×» and
    opens «Foto o video · Texto · Efecto · Idea» above it. ``on_add(key)`` OPENS the
    flow of that option (the drawer, the text field, the effects list), never adds by
    itself."""
    return rx.el.div(
        orbit_menu(
            vm.ADD_LABEL,
            [OrbitItem(key, icon, text, on_add(key)) for key, icon, text in vm.ADD_OPTIONS],
        ),
        class_name="q-tl-add",
    )


def timeline_actions(
    kind: rx.Var[str],
    *,
    on_add: Callable[[str], Any],
    on_action: Callable[[str], Any] | None = None,
) -> rx.Component:
    """What the owner can do now (§2): with nothing chosen (``kind`` ""), «Agregar»
    (`timeline_add`); with a video, a photo, a text or an effect chosen, its up-to-4
    `surface` buttons floating in a glass island (`.q-island`). ``on_action(label)``."""

    def bar(key: str) -> rx.Component:
        return rx.el.div(
            *(_action_button(label, icon, on_action) for label, icon in vm.ACTIONS[key]),
            class_name="q-island q-tl-island q-tl-actions",
            role="toolbar",
            aria_label="Acciones",
        )

    return rx.match(
        kind,
        *((key, bar(key)) for key in ("video", "photo", "text", "effect")),
        timeline_add(on_add),
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
            class_name="q-source-seg q-tl-seg",
        ),
        width="100%",
        min_width="0",
    )


def _nudge_row(
    label: rx.Var[str], row: Row, edge: str, on_nudge: Callable[[str, str, float], Any]
) -> rx.Component:
    return rx.el.div(
        rx.text(label, size="2", weight="medium", class_name="q-tl-panel__label"),
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
) -> rx.Component:
    """The chosen block's panel (§1.2/§1.3): its title, «Desde/Hasta» (a video),
    «Duración» (a photo) or «Empieza/Termina» (a text or effect) with «− ½ s / + ½ s»,
    «Velocidad» Normal · ×5 · ×10 · ×20 for a video (``on_speed(id, value)``), the
    text's place «Arriba · En el medio · Abajo» (``on_place(id, value)``), and «Listo»,
    which lets the block go. ``on_nudge(id, edge, delta)``."""
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
    return rx.el.div(
        rx.text(row["panel"], size="2", weight="bold"),
        rx.cond(
            row["start_label"] != "",
            _nudge_row(row["start_label"], row, "start", on_nudge),
        ),
        _nudge_row(row["end_label"], row, "end", on_nudge),
        *extras,
        rx.el.div(
            rx.button(
                vm.DONE_LABEL, type="button", on_click=on_done, class_name="q-tl-actions__btn"
            ),
            class_name="q-tl-panel__done",
        ),
        class_name="q-tl-panel",
    )


def timeline_layout(
    timeline_view: rx.Component,
    actions: rx.Component,
    panel: rx.Component | None = None,
) -> rx.Component:
    """The timeline with its action bar and its panel, in their places: on a phone the
    bar sits ABOVE the tracks (in the flow: it never covers the tracks nor the
    playhead), on a desktop under them; the panel always last (`.q-tl-stack`)."""
    return rx.el.div(
        rx.el.div(actions, class_name="q-tl-stack__actions"),
        rx.el.div(timeline_view, class_name="q-tl-stack__track"),
        *([rx.el.div(panel, class_name="q-tl-stack__panel")] if panel is not None else []),
        class_name="q-tl-stack",
    )
