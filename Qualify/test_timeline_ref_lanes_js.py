"""m-25142725: a reference block of the Clip's reference tracks dragged with the mouse or
a finger, run by `node` on `assets/timeline-drag-core.js` — it slides in time as a text
or an effect, changes row only inside its own kind, never opens a new row by itself (the
screen stacks one that overlaps), and the screen hears «time» or «time@N». Skipped where
`node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from . import clip_refs_vm

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not installed")


def _run(body: str) -> object:
    script = (
        f"const core = require({json.dumps(str(_ASSETS / 'timeline-drag-core.js'))});\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def test_a_reference_slides_in_time() -> None:
    kinds = sorted(clip_refs_vm.TL_KINDS.values())
    got = _run(f"return {json.dumps(kinds)}.map(k => core.dragMode(k));")
    assert got == ["time", "time", "time"]
    assert _run("return ['video', 'photo', 'ai'].map(k => core.dragMode(k));") == [
        "move",
        "move",
        "move",
    ]


def test_a_reference_changes_row_only_inside_its_kind_and_opens_none() -> None:
    got = _run(
        "return ['refphoto', 'refvideo', 'refaudio', 'effect', 'text', 'photo']"
        ".map(k => core.rowKind(k));"
    )
    assert got == [
        {"lanes": ".q-tl__lane--refphoto", "newLane": False},
        {"lanes": ".q-tl__lane--refvideo", "newLane": False},
        {"lanes": ".q-tl__lane--refaudio", "newLane": False},
        {"lanes": ".q-tl__lane--effect", "newLane": True},
        None,
        None,
    ]


def test_dropped_on_another_row_the_screen_hears_its_row() -> None:
    got = _run(
        "return [core.timeWhat({from: 0, to: 0}), core.timeWhat({from: 0, to: 1}),"
        " core.timeWhat({from: 1})];"
    )
    assert got == ["time", "time@1", "time"]


def test_its_new_start_stays_inside_the_video_on_the_half_second() -> None:
    # a 5 s reference at 2 s of a 9 s video, 44 px a second: dragged 1,3 s right, then
    # past the end
    got = _run(
        "return [57, 1000, -1000].map(dx => core.shiftedStart("
        "{start: 2, length: 5, total: 9, dx: dx, px: 44}));"
    )
    assert got == [3.5, 4, 0]
