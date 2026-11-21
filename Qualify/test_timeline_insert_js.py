"""ED-12 (m-25029107): photos and videos of the computer dropped on «Fotos y videos» on a
desktop — the pure part run by `node` on `assets/timeline-drag-core.js` (the gap under
the pointer, a drag of files told from text or a link), the DOM half
`assets/timeline-insert.js` read statically, and the «Agregar» option that goes off with
8 photos or videos (its why on its own line above the «+», the pill solid). The node
tests are skipped where `node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import reflex as rx

from . import clip_editor_vm
from .ui import timeline as tl
from .ui.primitives import OrbitItem, orbit_menu

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node is not installed")


def _run(body: str) -> object:
    """Run `body` (JS, with `core` defined) and return what it prints as JSON."""
    assert _NODE is not None
    script = (
        f"const core = require({json.dumps(str(_ASSETS / 'timeline-drag-core.js'))});\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


@_needs_node
def test_the_gap_under_the_pointer() -> None:
    # three blocks whose middles are at 50, 150 and 300 px
    got = _run(
        "return [0, 49, 51, 149, 151, 299, 301, 900].map(x => core.insertIndex([50, 150, 300], x));"
    )
    assert got == [0, 0, 1, 1, 2, 2, 3, 3]
    assert _run("return core.insertIndex([], 120);") == 0


@_needs_node
def test_only_a_drag_of_files_is_taken() -> None:
    got = _run(
        "return ["
        " core.carriesFiles(['Files']),"
        " core.carriesFiles(['text/plain', 'Files']),"
        " core.carriesFiles(['text/uri-list']),"
        " core.carriesFiles([]),"
        " core.carriesFiles(null)];"
    )
    assert got == [True, True, False, False, False]


def test_the_insert_script_reports_through_the_timeline_drop_button() -> None:
    script = (_ASSETS / tl.INSERT_SCRIPT).read_text(encoding="utf-8")
    assert "window.__qTimelineInsert" in script  # one set of document listeners
    assert "data-tl-drag-trigger" in script and "__qTimelineDrop" in script
    assert '"place"' in script and "carriesFiles" in script
    assert "data-tl-insert-zone" in script
    assert "q-tl__insert" in script and "aria-hidden" in script
    # mounted with the timeline's other scripts
    assert "__qTimelineInsert" in str(tl.timeline_script().event_triggers["on_mount"])


def test_the_add_option_goes_off_and_says_why() -> None:
    rendered = str(
        tl.timeline_add(
            lambda key: rx.console_log(key),
            off={"media": rx.Var.create(True)},
            note=rx.Var.create(clip_editor_vm.FULL_LINE),
        ).render()
    )
    assert "q-tl-add__note" in rendered
    assert "disabled" in rendered
    # its why goes on its own line ABOVE the «+» (never beside it, under the options)
    assert rendered.index("q-tl-add__note") < rendered.index("q-tl-add__row")
    # UX review S4: the «+» is described by that line (its id) while it says something
    assert tl.ADD_NOTE_ID in rendered and "aria-describedby" in rendered
    # an orbit option with no `disabled` stays on (the WhatsApp composer is unchanged)
    plain = str(
        orbit_menu(
            "Agregar", [OrbitItem("a", "plus", "Uno", None), OrbitItem("b", "plus", "Dos", None)]
        ).render()
    )
    assert "q-orbit-pill" in plain
    assert "aria-describedby" not in plain  # optional: only where a screen asks for it


def test_the_off_option_is_solid_and_legible() -> None:
    css = (_ASSETS / "qualify-creative.css").read_text(encoding="utf-8")
    start = css.index(".radix-themes .rt-BaseMenuItem.q-orbit-pill[data-disabled]")
    rule = css[start : css.index("}", start)]
    assert "opacity: 1" in rule and "backdrop-filter: none" in rule
    assert "var(--gray-3)" in rule and "var(--gray-11)" in rule and "var(--gray-a6)" in rule
    assert "cursor: not-allowed" in rule
    # the note is in the flow, not laid over the button
    note = css[css.index(".q-tl-add__note") :]
    assert "position: absolute" not in note[: note.index("}")]
