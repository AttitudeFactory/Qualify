"""ED-01b (m-25029106): the preview-in-sequence's clock (`assets/edit-sequence-core.js`)
run by `node` — no browser, no npm package. It is fed the JSON `edit_sequence` makes,
so Python and the script agree on the clock. Skipped where `node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from . import edit_sequence as seq

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not installed")

_MEDIA = [
    {"id": "v1", "key": "a", "kind": "video", "src_start": 0.0, "src_end": 4.0, "src_len": 15.0},
    {"id": "v2", "key": "a", "kind": "video", "src_start": 4.0, "src_end": 9.0, "src_len": 15.0},
    {"id": "f3", "key": "f", "kind": "photo", "dur": 2.0},
    {"id": "v4", "key": "b", "kind": "video", "src_start": 0.0, "src_end": 30.0, "src_len": 30.0,
     "speed": 10.0},
]  # fmt: skip
_OVERLAYS = [
    {"id": "t1", "kind": "text", "label": "2×1 hoy", "start": 2.0, "end": 5.0},
    {"id": "e1", "kind": "effect", "label": "Vapor", "start": 4.0, "end": 9.0},
]


def _run(body: str) -> object:
    """Run `body` (JS, with `core` and `seq` defined) and return what it prints as JSON."""
    sequence = seq.from_timeline(_MEDIA, _OVERLAYS, {"a": "/a.mp4", "b": "/b.mp4"}).to_json()
    script = (
        f"const core = require({json.dumps(str(_ASSETS / 'edit-sequence-core.js'))});\n"
        f"const seq = {sequence};\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def test_the_scripts_parse() -> None:
    for name in ("edit-sequence-core.js", "edit-preview.js", "timeline.js"):
        subprocess.run([_NODE, "--check", str(_ASSETS / name)], check=True, timeout=30)


def test_the_clock_walks_the_blocks_in_order() -> None:
    got = _run("return [0, 3.99, 4, 9.5, 11, 13.99, 99].map(t => core.blockAt(seq, t));")
    assert got == [0, 0, 1, 2, 3, 3, 3]
    assert _run("return core.total(seq);") == 14


def test_speed_maps_the_final_time_to_the_source() -> None:
    # block 4: 30 s of source at ×10 from 0:11 → at 0:12 the source is at 10 s
    got = _run(
        "const b = seq.blocks[3];"
        "return [core.sourceTime(b, 12), core.finalTime(b, 10), core.rate(10), core.rate(20),"
        " core.slower(16), core.slower(20)];"
    )
    assert got == [10, 12, 10, 16, False, True]


def test_a_text_from_two_to_five_shows_within_a_tenth() -> None:
    got = _run("return [1.95, 2.0, 2.05, 4.95, 5.0, 5.05].map(t => core.activeAt(seq.texts, t));")
    assert got == [[], [0], [0], [0], [], []]


def test_the_end_goes_back_to_the_start_and_timed_blocks_advance() -> None:
    got = _run(
        "return [core.advance(seq, 9.5, 1), core.advance(seq, 13.9, 0.2),"
        " core.nextIndex(seq, 3), core.nextVideo(seq, 1, {}), core.nextVideo(seq, 1, {b: true})];"
    )
    assert got == [
        {"t": 10.5, "index": 2, "wrapped": False},
        {"t": 0, "index": 0, "wrapped": True},
        0,
        3,
        0,  # «b» broken: the next playable video is block 1 again (a's first cut)
    ]


def test_clock_text() -> None:
    assert _run("return [core.clock(0), core.clock(4.5), core.clock(62)];") == [
        "0:00",
        "0:04,5",
        "1:02",
    ]


def test_rewinding_by_a_slide_sticks_and_is_not_scrolled_back() -> None:
    # The founder's bug: paused at 0:04,6 (the clock put the tracks at 4.6 × 44 = 202 px),
    # the owner slides back to 194 px. The slide is the owner's (not where the clock put
    # them), the time is the exact 194 / 44 ≈ 4.41 (not snapped to 4.5), and the seek it
    # makes writes nothing back to the scroller.
    got = _run(
        "const px = 44, max = 14 * px;"
        "const ours = core.slideTime({left: 202, t: 4.6, px, total: 14, max});"
        "const slid = core.slideTime({left: 194, t: 4.6, px, total: 14, max});"
        "const back = core.scrollTarget({owner: true, t: slid, px, current: 194, max});"
        "return [ours, Math.round(slid * 1000) / 1000, back];"
    )
    assert got == [-1, 4.409, -1]


def test_the_clock_scrolls_the_tracks_only_when_it_drives_them() -> None:
    got = _run(
        "const px = 44, max = 14 * px - 0.4;"  # the browser's end, a fraction short
        "return ["
        # playing (or a programmatic seek): the tracks follow the clock
        " core.scrollTarget({owner: false, t: 4.6, px, current: 198, max}),"
        # already there: no write (no scroll event, nothing to wait for)
        " core.scrollTarget({owner: false, t: 4.6, px, current: 202.4, max}),"
        # the end: clamped to what the browser allows, then never written again
        " core.scrollTarget({owner: false, t: 14, px, current: 0, max}),"
        " core.scrollTarget({owner: false, t: 14, px, current: 615, max}),"
        # at the clamped end the clock's own position is not mistaken for a slide …
        " core.slideTime({left: 615, t: 14, px, total: 14, max}),"
        # … and the owner's next slide back is heard at once (no stuck flag swallows it)
        " Math.round(core.slideTime({left: 600, t: 14, px, total: 14, max}) * 100) / 100,"
        # a slide past either end stays inside the video
        " core.slideTime({left: -30, t: 4, px, total: 14, max}),"
        "];"
    )
    assert got == [202, -1, 615, -1, -1, 13.64, 0]


def test_a_video_that_never_loads_does_not_freeze_the_clock() -> None:
    # After each 15 s wait for its length: ready → nothing; still on the network → wait
    # again (up to three waits); never loaded nor failed → broken (a timed block).
    got = _run(
        "return [core.WAIT_MS,"
        " core.waitVerdict({ready: true, loading: false, rounds: 1}),"
        " core.waitVerdict({ready: false, loading: true, rounds: 1}),"
        " core.waitVerdict({ready: false, loading: true, rounds: 2}),"
        " core.waitVerdict({ready: false, loading: true, rounds: 3}),"
        " core.waitVerdict({ready: false, loading: false, rounds: 1})];"
    )
    assert got == [15000, "ready", "wait", "wait", "broken", "broken"]


def test_the_clock_shows_whole_seconds_while_playing() -> None:
    """ED-10 UX note: playing, whole seconds (tenths change every frame); paused, the
    tenths."""
    got = _run(
        "return [core.clockShown(4.37, true), core.clockShown(4.37, false),"
        " core.clockShown(59.99, true), core.clockShown(-1, true)];"
    )
    assert got == ["0:04", "0:04,4", "0:59", "0:00"]
