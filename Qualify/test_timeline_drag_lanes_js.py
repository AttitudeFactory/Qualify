"""ED-04 (m-25026627, Deivid 2026-11-20: «moverlos entre pistas»): an effect dragged up
or down to another row of «Efectos», run by `node` on `assets/timeline-drag-core.js` —
the row under the pointer (never out of the effects' rows), how far the block shows
moved, and what the screen hears at the drop. Skipped where `node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not installed")

#: Three 44 px rows of «Efectos», 4 px apart, from y = 100 (client px).
_ROWS = "const tops = [100, 148, 196]; const bottoms = [144, 192, 240];"


def _run(body: str) -> object:
    """Run `body` (JS, with `core` defined) and return what it prints as JSON."""
    script = (
        f"const core = require({json.dumps(str(_ASSETS / 'timeline-drag-core.js'))});\n"
        f"{_ROWS}\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def test_the_row_under_the_pointer() -> None:
    got = _run(
        "return [120, 144, 150, 191, 200, 240].map(y => core.laneAt("
        "{y: y, tops: tops, bottoms: bottoms, from: 0}));"
    )
    assert got == [0, 0, 1, 1, 2, 2]


def test_an_effect_never_leaves_the_effects_rows() -> None:
    # above the first row it is the first; below the last, the last; in a gap, the
    # nearest (the first when both are as near)
    got = _run(
        "return [-500, 99, 146, 241, 9999].map(y => core.laneAt("
        "{y: y, tops: tops, bottoms: bottoms, from: 1}));"
    )
    assert got == [0, 0, 0, 2, 2]
    assert _run("return core.laneAt({y: 120, tops: [], bottoms: [], from: 1});") == 1


def test_the_block_moves_a_whole_row_at_a_time() -> None:
    got = _run(
        "return [[0, 0], [0, 1], [0, 2], [2, 0], [1, 5], [-1, 0]].map(([f, t]) =>"
        " core.laneShift({tops: tops, from: f, to: t}));"
    )
    assert got == [0, 48, 96, -96, 0, 0]


def test_the_drop_says_the_new_row() -> None:
    got = _run(
        "return [core.timeWhat({from: 0, to: 0}), core.timeWhat({from: 0, to: 2}),"
        " core.timeWhat({from: 1}), core.timeWhat({from: 2, to: 0}), core.timeWhat(null)];"
    )
    assert got == ["time", "time@2", "time", "time@0", "time"]


def test_the_lens_reads_a_block_moved_to_another_row() -> None:
    assert _run("return core.shiftOf('translate(12px, 48px)');") == 12
    assert _run("return core.shiftOf('translate( -30.5px , -96px)');") == -30.5


def test_only_an_effect_moves_up_or_down() -> None:
    """The DOM half: rows only for an effect block (a photo, a video or a text stays in
    X), the row from `laneAt`, the shift from `laneShift`, the drop through
    `timeWhat`; a still drop on its own row and time changes nothing."""
    drag = (_ASSETS / "timeline-drag.js").read_text(encoding="utf-8")
    arm = drag[drag.index("function arm()") : drag.index("function update()")]
    assert 'd.block.getAttribute("data-tl-block") === "effect"' in arm
    assert ".q-tl__lane--effect" in arm
    assert "core().laneAt(" in drag and "core().laneShift(" in drag
    release = drag[drag.index("function release(e)") :]
    assert "d.laneTo === d.laneFrom" in release
    assert "core().timeWhat({ from: d.laneFrom, to: d.laneTo })" in release
    assert "translateY" not in drag  # a row move is one `translate(x, y)`


def test_up_and_down_keys_reach_the_screen_for_an_effect_only() -> None:
    script = (_ASSETS / "timeline.js").read_text(encoding="utf-8")
    assert '(e.key === "ArrowUp" || e.key === "ArrowDown")' in script
    assert 'el.getAttribute("data-tl-block") === "effect"' in script


def test_the_scripts_parse() -> None:
    for name in ("timeline-drag-core.js", "timeline-drag.js", "timeline.js"):
        subprocess.run([_NODE, "--check", str(_ASSETS / name)], check=True, timeout=30)


# -- round 3 (Deivid 2026-11-20) -------------------------------------------------------------


def test_the_lens_reads_how_far_down_a_block_is_moved() -> None:
    """«su efecto cristal se separa»: the lens takes the block's Y shift off its resting
    place too (then wears the same transform), so it never sits a row off."""
    got = _run(
        "return ['translate(12px, 48px)', 'translate(-3px, -96px)', 'translateX(12px)', '',"
        " 'none', 'matrix(1, 0, 0, 1, -42.5, 30)',"
        " 'matrix3d(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 17, -48, 0, 1)'].map(core.shiftYOf);"
    )
    assert got == [48, -96, 0, 0, 0, 30, -48]
    lens = (_ASSETS / "timeline.js").read_text(encoding="utf-8")
    place = lens[lens.index("function placeLens(root, instant)") : lens.index("function shiftOf")]
    assert "var nowY = item ? shiftYOf(getComputedStyle(item).transform) : 0;" in place
    assert "- pad - nowY," in place


def test_a_held_effect_can_open_a_new_row_under_the_last() -> None:
    drag = (_ASSETS / "timeline-drag.js").read_text(encoding="utf-8")
    arm = drag[drag.index("function arm()") : drag.index("function update()")]
    assert 'd.root.setAttribute("data-tl-new-lane", "")' in arm
    # not for the only effect of the last row: that would be its own row again
    assert "!(d.laneFrom === last && itemsOf(d.lane).length < 2)" in arm
    lanes = drag[drag.index("function laneDy(d)") : drag.index("function moveOf")]
    assert "if (d.newLane && tops.length)" in lanes
    # a row more under the last one: the core lands on it (index = the rows' count)
    got = _run(
        "return core.laneAt({y: 260, tops: tops.concat([244]), bottoms: bottoms.concat([288]),"
        " from: 0});"
    )
    assert got == 3


def test_nothing_a_drag_lifted_stays_on_the_page() -> None:
    """The «0:01,5» left on a row after a drop: every block still carrying the bubble
    or the lifted look goes back to normal, wherever React put it, and the screen's
    answer is heard on every row of «Efectos» and on the live line."""
    drag = (_ASSETS / "timeline-drag.js").read_text(encoding="utf-8")
    strays = drag[drag.index("function strays(d)") : drag.index("function clearTransforms")]
    assert ".q-tl__item[data-tl-time], .q-tl__item--lifted, .q-tl__item--settle" in strays
    assert 'd.root.removeAttribute("data-tl-new-lane")' in strays
    clear = drag[drag.index("function clearTransforms(d)") : drag.index("function putBack(d)")]
    assert "strays(d).forEach" in clear
    put_back = drag[drag.index("function putBack(d)") : drag.index("function clearOnRender")]
    assert "var all = strays(d);" in put_back
    on_render = drag[drag.index("function clearOnRender(d)") : drag.index("function report(")]
    assert "[d.lane].concat(d.lanes || [])" in on_render
    assert '.querySelector(".q-tl__status")' in on_render
    assert 'closest(".q-glass-blob")' in on_render  # the lens's own moves are no answer
