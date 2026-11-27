"""ED-04 (m-25026627): «Efectos» in rows (they come and go on their own) on the timeline
component, and an effect block stuck to «Fotos y videos» placed to the hundredth.

Offline: the view model keeps each effect's row; the component renders one list per row,
each named («Efectos 1», «Pista de efectos 2 vacía»), the row names on the desktop
column, and the room for a new row while an effect is held (no «+ Pista» bar)."""

from __future__ import annotations

import json
from pathlib import Path

import reflex as rx

from Qualify.ui import timeline as tl
from Qualify.ui import timeline_vm as vm

_OVERLAYS = [
    {"id": "efecto-u1", "kind": "effect", "label": "Vapor", "start": 0.0, "end": 3.27, "lane": 0},
    {"id": "efecto-u2", "kind": "effect", "label": "Brasas", "start": 2.0, "end": 9.0, "lane": 1},
]
_CSS = Path(__file__).resolve().parent.parent / "assets" / "qualify-creative.css"


def _has(rendered: str, text: str) -> bool:
    escaped = json.dumps(text)[1:-1]
    return any(form in rendered for form in (text, escaped, escaped.replace("\\", "\\\\")))


def test_effect_rows_keep_their_row_and_exact_seconds() -> None:
    rows = vm.overlay_blocks(_OVERLAYS, "effect", 11)
    assert [row["lane"] for row in rows] == ["0", "1"]
    # stuck to a block ending at 0:03,27: the block ends there, not ½ s off
    assert (rows[0]["start"], rows[0]["length"]) == ("0", "3.27")
    assert rows[1]["name"] == "Brasas, de 0:02 a 0:09"


class _LanesState(rx.State):
    media: list[dict[str, str]] = []
    texts: list[dict[str, str]] = []
    effects: list[dict[str, str]] = vm.overlay_blocks(_OVERLAYS, "effect", 11)
    lanes: list[list[dict[str, str]]] = [
        [r for r in vm.overlay_blocks(_OVERLAYS, "effect", 11) if r["lane"] == "0"],
        [r for r in vm.overlay_blocks(_OVERLAYS, "effect", 11) if r["lane"] == "1"],
        [],
    ]
    lane_names: list[dict[str, str]] = [
        {"index": "0", "name": "Efectos 1", "empty": "Pista de efectos 1 vacía"},
        {"index": "1", "name": "Efectos 2", "empty": "Pista de efectos 2 vacía"},
        {"index": "2", "name": "Efectos 3", "empty": "Pista de efectos 3 vacía"},
    ]
    ticks: list[dict[str, str]] = vm.ticks(11)
    selected: str = ""

    @rx.event
    def pick(self, block_id: str) -> None:
        self.selected = block_id


def test_the_component_renders_one_named_list_per_row() -> None:
    rendered = str(
        tl.timeline(
            media=_LanesState.media,
            texts=_LanesState.texts,
            effects=_LanesState.effects,
            ticks=_LanesState.ticks,
            total="11",
            selected=_LanesState.selected,
            on_select=_LanesState.pick,
            effect_lanes=_LanesState.lanes,
            effect_lane_names=_LanesState.lane_names,
        ).render()
    )
    assert "lane_names" in rendered and "lanes" in rendered
    assert '"list"' in rendered and "q-tl__lane--effect" in rendered
    assert "data-tl-lane" in rendered
    # the plain one-row «Efectos» is not drawn as well
    assert not _has(rendered, "Pista de efectos vacía")


def test_without_rows_the_timeline_keeps_its_one_effects_track() -> None:
    rendered = str(
        tl.timeline(
            media=_LanesState.media,
            texts=_LanesState.texts,
            effects=_LanesState.effects,
            ticks=_LanesState.ticks,
            total="11",
            selected=_LanesState.selected,
            on_select=_LanesState.pick,
        ).render()
    )
    assert _has(rendered, "Efectos") and "data-tl-lane" not in rendered


def test_a_held_effect_shows_room_for_a_new_row() -> None:
    css = _CSS.read_text(encoding="utf-8")
    assert ".q-tl[data-tl-new-lane] .q-tl__canvas { padding-bottom: 48px; }" in css
    assert ".q-tl__lanes" not in css  # no «+ Pista» bar any more
