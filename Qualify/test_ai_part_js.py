"""ED-07 (m-25026638): the «parte con IA» in the browser's scripts, run by `node` (no
browser, no npm package) — it is dragged like a photo or a video (`timeline-drag-core.js`
`dragMode`) and the preview marks it while its clock is on it (`edit-sequence-core.js`
`aiMark`) — and the track and the panel as Reflex renders them. Node tests are skipped
where `node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import reflex as rx
from qualify_api.creative.video_pipeline import ai_parts as contract_ai

from . import ai_block_vm as ai_vm
from . import edit_sequence
from .ui import timeline as tl
from .ui import timeline_vm

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node is not installed")


def _run(core: str, body: str) -> object:
    script = (
        f"const core = require({json.dumps(str(_ASSETS / core))});\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    assert _NODE is not None
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


@needs_node
def test_the_scripts_parse() -> None:
    for name in (
        "timeline-drag-core.js",
        "timeline-drag.js",
        "timeline.js",
        "edit-sequence-core.js",
        "edit-preview.js",
    ):
        subprocess.run([_NODE, "--check", str(_ASSETS / name)], check=True, timeout=30)  # type: ignore[list-item]


@needs_node
def test_an_ai_part_is_dragged_to_another_place_like_a_photo_or_a_video() -> None:
    got = _run(
        "timeline-drag-core.js",
        'return ["video", "photo", "ai", "text", "effect", ""].map(core.dragMode);',
    )
    assert got == ["move", "move", "move", "time", "time", "time"]
    assert ai_vm.TL_KIND == timeline_vm.AI_KIND == "ai"


def test_the_drag_and_the_keys_ask_the_core_and_know_the_ai_block() -> None:
    drag = (_ASSETS / "timeline-drag.js").read_text(encoding="utf-8")
    assert "var mode = core().dragMode(kind);" in drag
    keys = (_ASSETS / "timeline.js").read_text(encoding="utf-8")
    assert 'kind === "video" || kind === "photo" || kind === "ai"' in keys


@needs_node
def test_the_preview_marks_only_an_ai_part_not_made_yet() -> None:
    media = [
        {"id": "f", "key": "f.jpg", "kind": "photo", "dur": 2.0},
        {
            "id": "ai:p1",
            "key": "ai:p1",
            "kind": "ai",
            "src_start": 0.0,
            "src_end": 5.0,
            "speed": 1.0,
            "thumb": "/p.jpg",
        },
    ]
    seq = edit_sequence.from_timeline(media, [], {"f.jpg": "/f.jpg"}).to_dict()
    got = _run(
        "edit-sequence-core.js",
        f"const s = {json.dumps(seq)};"
        " return [core.aiMark(s, 0), core.aiMark(s, 1), core.aiMark(s, 9),"
        " core.aiMark(null, 0), core.blockAt(s, 3)];",
    )
    assert got == ["", "Parte con IA 1 · se crea al tocar «Crear»", "", "", 1]
    # its poster shows (a timed block with a picture), never a playable address
    assert seq["blocks"][1]["url"] == "" and seq["blocks"][1]["poster"] == "/p.jpg"


def test_the_preview_shows_the_mark_with_its_class() -> None:
    script = (_ASSETS / "edit-preview.js").read_text(encoding="utf-8")
    assert "c.aiMark(st.seq, st.idx)" in script
    css = (_ASSETS / "qualify-creative.css").read_text(encoding="utf-8")
    assert ".q-edit-seq__ai:not([data-on]) { display: none; }" in css


_ON = rx.Var.create(True)


def _rendered_block(ai_on: object = _ON) -> str:
    item = {
        "id": "ai:p1",
        "key": "ai:p1",
        "kind": "ai",
        "src_start": 0.0,
        "src_end": 5.0,
        "src_len": 5.0,
        "speed": 1.0,
        "ai_n": 1,
    }
    (row,) = timeline_vm.media_blocks([item])  # type: ignore[list-item]
    row.update(ai_vm.row_fields(item, ai_vm.new_ai_block(0)[1], start_s=0.0, poster="/p.jpg"))
    return str(
        tl._block(
            rx.Var.create(row),
            selected=rx.Var.create(""),
            on_select=lambda _id: rx.console_log(_id),
            ai_on=ai_on,  # type: ignore[arg-type]
        )
    )


_AI_CLASSES = ("q-tl__mode", "q-tl__mode-word", "q-tl__ai-line", "q-tl__ai-name", "q-tl__state")


def test_the_track_draws_the_signed_ai_block() -> None:
    """`docs/design-system.md` §5.10.1: the two lines, ✦ + the mode's icon and word, the
    name and seconds before «Crear» (or its state), `data-ai-state` on the button — all
    behind the screen's state var (`CreativeState.clip_ai_on`)."""
    rendered = _rendered_block()
    for cls in _AI_CLASSES:
        assert cls in rendered, cls
    assert "data-ai-state" in rendered
    assert "data-tl-block" in rendered


def test_the_views_never_read_the_switch_when_compiled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review: production builds the frontend without `QUALIFY_CLIP_AI_PARTS`, so the
    page is the same with the switch on or off; the state var (read on the server) is
    what draws the AI part, its mark and «Parte con IA» in «Agregar»."""
    pages = []
    for value in ("off", "on"):
        monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, value)
        pages.append((_rendered_block(), str(_preview_component(_ON))))
    assert pages[0] == pages[1]
    for source in ("ui/timeline.py", "ui/edit_preview.py", "clip_editor_view.py"):
        text = (Path(__file__).resolve().parent / source).read_text(encoding="utf-8")
        assert "clip_ai_parts_on" not in text and "switch_on()" not in text, source
    # a screen that passes no state var renders as before ED-07
    assert not [cls for cls in _AI_CLASSES if cls in _rendered_block(False)]
    assert "data-ai-state" not in _rendered_block(False)
    assert "data-edit-seq-ai" not in str(_preview_component(False))
    assert "data-edit-seq-ai" in str(_preview_component(_ON))
    # a sequence with no AI part writes no `mark`
    media = [{"id": "f", "key": "f.jpg", "kind": "photo", "dur": 2.0}]
    data = edit_sequence.from_timeline(media, [], {"f.jpg": "/f.jpg"}).to_dict()
    assert "mark" not in data["blocks"][0]


def test_agregar_draws_parte_con_ia_only_while_its_var_is_true() -> None:
    from .ui.primitives import OrbitItem, orbit_menu  # noqa: PLC0415

    items = [
        OrbitItem("media", "image-plus", "Foto o video", rx.console_log("m")),
        OrbitItem(ai_vm.ADD_KEY, "sparkles", "Parte con IA", rx.console_log("a"), shown=_ON),
    ]
    rendered = str(orbit_menu("Agregar", items))
    assert "Parte con IA" in rendered and "Foto o video" in rendered


def _preview_component(ai_mark: object = False) -> rx.Component:
    from .ui.edit_preview import edit_sequence_preview  # noqa: PLC0415

    return edit_sequence_preview(
        sequence=rx.Var.create("{}"),
        texts=rx.Var.create([]).to(list[dict[str, str]]),
        effects=rx.Var.create([]).to(list[dict[str, str]]),
        slower=rx.Var.create(False),
        on_duration=lambda *a: rx.console_log("d"),
        on_time=lambda *a: rx.console_log("t"),
        note_text="",
        broken_text="",
        slower_text="",
        play_label="",
        pause_label="",
        sound_label="",
        mute_label="",
        region_label="",
        ai_mark=ai_mark,  # type: ignore[arg-type]
    )


def test_every_media_and_overlay_row_reads_the_ai_keys() -> None:
    media = [
        {"id": "f", "key": "f.jpg", "kind": "photo", "dur": 2.0},
        {
            "id": "ai:p1",
            "key": "ai:p1",
            "kind": "ai",
            "src_start": 0.0,
            "src_end": 5.0,
            "src_len": 5.0,
            "speed": 1.0,
            "ai_n": 1,
        },
    ]
    rows = timeline_vm.media_blocks(media)  # type: ignore[arg-type]
    assert all(set(timeline_vm.NO_AI) <= set(row) for row in rows)
    assert rows[1]["label"] == "Parte con IA 1"
    assert timeline_vm.media_label(media[1], 2) == "Parte con IA 1"
    overlays = timeline_vm.overlay_blocks(
        [{"id": "t", "kind": "text", "label": "Hola", "start": 0.0, "end": 1.0}], "text", 7.0
    )
    assert all(set(timeline_vm.NO_AI) <= set(row) for row in overlays)
    assert timeline_vm.moved_text(media, "ai:p1") == "Moviste la parte con IA 1."  # type: ignore[arg-type]
