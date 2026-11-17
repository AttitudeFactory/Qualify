"""ED-10 (m-25026648): the timeline's drag and drop (`assets/timeline-drag-core.js`) run
by `node` — no browser, no npm package. The target slot with blocks of different widths,
px → seconds with the ½ s magnet, and the scroll near the edges. Skipped where `node` is
not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from .ui import timeline_vm as vm

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not installed")


def _run(body: str) -> object:
    """Run `body` (JS, with `core` defined) and return what it prints as JSON."""
    script = (
        f"const core = require({json.dumps(str(_ASSETS / 'timeline-drag-core.js'))});\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def test_the_scripts_parse() -> None:
    for name in ("timeline-drag-core.js", "timeline-drag.js", "timeline.js"):
        subprocess.run([_NODE, "--check", str(_ASSETS / name)], check=True, timeout=30)


# -- move: the target slot with variable widths ------------------------------------------


def test_at_rest_a_block_keeps_its_own_slot() -> None:
    # 4 s, 1 s, 2 s, 6 s blocks at 44 px per second
    widths = [176, 44, 88, 264]
    lefts = [0, 176, 220, 308]
    got = _run(f"const w = {widths}; return {lefts}.map((left, i) => core.dropIndex(w, i, left));")
    assert got == [0, 1, 2, 3]


def test_a_wide_block_takes_the_next_slot_past_half_its_neighbour() -> None:
    widths = [176, 44, 88, 264]  # the 4 s video lifted, a 1 s photo next to it
    got = _run(
        f"const w = {widths};"
        " return [21, 23, 44, 87, 89, 133, 500, -80].map(dx => core.dropIndex(w, 0, dx));"
    )
    # the slots' left edges: 0, 44 (after the photo), 132 (after the 2 s), 396 — past
    # 22 px (half of the 1 s photo) it goes after the photo, past 88 px after the 2 s
    assert got == [0, 1, 1, 1, 2, 2, 3, 0]


def test_a_narrow_block_dragged_left_over_a_wide_one() -> None:
    widths = [176, 44, 88, 264]
    # the 1 s photo (slot 1, left 176) dragged left: slot 0's edge is at 0
    got = _run(f"const w = {widths}; return [176, 89, 87, 0].map(l => core.dropIndex(w, 1, l));")
    assert got == [1, 1, 0, 0]


def test_the_others_make_room_with_the_lifted_blocks_width() -> None:
    widths = [176, 44, 88, 264]
    got = _run(
        f"const w = {widths}; return [core.layoutShifts(w, 0, 2), core.layoutShifts(w, 3, 0)];"
    )
    # 0 → 2: the 1 s and 2 s blocks move left by 176 px, the lifted one lands at 132
    assert got[0] == [132, -176, -176, 0]  # type: ignore[index]
    # 3 → 0: the others move right by 264 px, the lifted one goes to 0
    assert got[1] == [264, 264, 264, -308]  # type: ignore[index]


def test_the_drop_matches_move_to() -> None:
    """The script's remove-then-insert is `timeline_vm.move_to`'s."""
    media = [
        {"id": "a", "kind": "video", "src_start": 0.0, "src_end": 4.0, "src_len": 9.0},
        {"id": "b", "kind": "photo", "dur": 1.0},
        {"id": "c", "kind": "photo", "dur": 2.0},
    ]
    moved = [item["id"] for item in vm.move_to(media, "a", 2)]
    assert moved == ["b", "c", "a"]
    shifts = _run("return core.layoutShifts([176, 44, 88], 0, 2);")
    # the lifted block lands after the other two (44 + 88 px from the start)
    assert shifts == [132, -176, -176]


def test_one_block_alone_never_moves() -> None:
    assert _run("return [core.dropIndex([100], 0, 300), core.layoutShifts([100], 0, 0)];") == [
        0,
        [0],
    ]


# -- time: px → seconds with the ½ s magnet ---------------------------------------------


def test_px_to_seconds_snaps_to_half_a_second() -> None:
    got = _run(
        "return [10, 11, 22, 33, 34, -23].map(dx => core.shiftedStart("
        "{start: 2, length: 3, total: 12, dx: dx, px: 44}));"
    )
    # 10 px = 0.23 s → 2; 11 px = 0.25 s → 2.5; 33 px = 0.75 s → 3; -23 px → 1.5
    assert got == [2, 2.5, 2.5, 3, 3, 1.5]


def test_a_dragged_text_stays_inside_the_video() -> None:
    got = _run(
        "return [-9999, 9999].map(dx => core.shiftedStart("
        "{start: 2, length: 3, total: 12, dx: dx, px: 44}));"
    )
    assert got == [0, 9]


def test_the_scale_on_a_phone_and_on_a_desktop() -> None:
    got = _run(
        "return [core.scaleOf({phone: true, px: 44}), core.scaleOf({phone: true}),"
        " core.scaleOf({phone: false, total: 12, width: 960}),"
        " core.scaleOf({phone: false, total: 0, width: 960})];"
    )
    assert got == [44, 44, 80, 44]
    # on a desktop 80 px per second: 40 px is ½ s
    assert (
        _run("return core.shiftedStart({start: 0, length: 2, total: 12, dx: 40, px: 80});") == 0.5
    )


def test_python_and_script_agree_on_the_magnet() -> None:
    for dx in (0, 10, 11, 21, 22, 23, 66, 67):
        js = _run(
            f"return core.shiftedStart({{start: 1, length: 2, total: 20, dx: {dx}, px: 44}});"
        )
        assert js == vm.seconds_from_drag(1.0, float(dx), 44.0, length=2.0, total=20.0)


# -- the scroll near the edges and the lift ----------------------------------------------


def test_the_tracks_scroll_near_the_edges_only() -> None:
    got = _run(
        "const box = {left: 0, right: 375};"
        " return [0, 24, 47, 48, 200, 327, 351, 375, 500]"
        ".map(x => core.autoScrollStep({x: x, left: box.left, right: box.right}));"
    )
    assert got[4] == 0  # the middle: no scroll
    assert got[0] == -14 and got[8] == 14  # at / past the edge: full speed
    assert got[1] < 0 and got[1] > got[0]  # halfway into the band: slower
    assert got[6] > 0 and got[6] < got[7]
    assert got[3] == 0 and got[5] == 0  # the band's inner edge


def test_the_scroll_stays_inside_the_scroller() -> None:
    got = _run(
        "return [core.clampScroll(10, -14, 400), core.clampScroll(395, 14, 400),"
        " core.clampScroll(100, 14, 400)];"
    )
    assert got == [0, 400, 114]


def test_a_mouse_lifts_after_five_px_a_finger_after_300_ms() -> None:
    got = _run(
        "return ["
        " core.liftDecision({touch: false, dist: 4}),"
        " core.liftDecision({touch: false, dist: 5}),"
        " core.liftDecision({touch: true, dist: 3, elapsed: 299}),"
        " core.liftDecision({touch: true, dist: 3, elapsed: 300}),"
        " core.liftDecision({touch: true, dist: 11, elapsed: 100})];"
    )
    assert got == ["wait", "lift", "wait", "lift", "cancel"]


def test_the_bubble_reads_like_the_screen() -> None:
    got = _run("return [0, 4.5, 4.24, 62, -1].map(core.clock);")
    assert got == [vm.clock(s) for s in (0, 4.5, 4.24, 62, -1)]


# -- the liquid lens moves WITH the dragged block (Deivid, 2026-11-16) --------------------


def test_the_lens_reads_the_blocks_shift() -> None:
    got = _run(
        "return ['translateX(12px)', 'translateX(-30.5px)', 'translateX( 4px )', '',"
        " 'none', null, 'scale(2)', 'matrix(1, 0, 0, 1, -42.5, 0)',"
        " 'matrix3d(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 17, 0, 0, 1)'].map(core.shiftOf);"
    )
    # the inline value the drag writes, and the computed one mid-transition
    assert got == [12, -30.5, 4, 0, 0, 0, 0, -42.5, 17]


def test_every_move_of_a_block_moves_the_lens_in_the_same_frame() -> None:
    """The drag writes a block's `translateX` without any attribute the lens watches:
    it tells the lens itself each time (held, settling, put back, re-rendered), and the
    lens wears the block's own transform and transition."""
    drag = (_ASSETS / "timeline-drag.js").read_text(encoding="utf-8")
    lens = (_ASSETS / "timeline.js").read_text(encoding="utf-8")
    update = drag[drag.index("function update()") : drag.index("function loop()")]
    assert "syncLens(d.root)" in update
    release = drag[drag.index("function release(e)") :]
    assert release.index("syncLens(d.root)") < release.index("report(d.root")
    clear = drag[drag.index("function clearTransforms(d)") : drag.index("function putBack(d)")]
    assert "syncLens(d.root, true)" in clear  # the new order: in place, no glide
    put_back = drag[drag.index("function putBack(d)") : drag.index("function clearOnRender")]
    assert "syncLens(d.root)" in put_back
    assert "lens: lens" in lens
    place = lens[lens.index("function placeLens(root, instant)") : lens.index("function shiftOf")]
    # its resting place (the computed shift, mid-transition too), then the same transform
    assert "shiftOf(getComputedStyle(item).transform)" in place
    assert "lens.style.transform = moved" in place
    assert "getComputedStyle(item).transition" in place


# -- a block never leaves the timeline (Deivid, 2026-11-17: «puedo sacar los componentes
# fuera de la time line no quiero eso») ---------------------------------------------------


def test_the_drop_point_is_inside_the_tracks_or_not() -> None:
    got = _run(
        "const box = {left: 10, right: 385, top: 100, bottom: 220};"
        " return [[200, 160], [10, 100], [385, 220], [9, 160], [386, 160], [200, 99],"
        " [200, 221], [200, 600]].map(([x, y]) => core.insideTracks("
        "Object.assign({x: x, y: y}, box)));"
    )
    # the edges count as inside; one px off any side is outside
    assert got == [True, True, True, False, False, False, False, False]


def test_a_held_block_stays_inside_its_track() -> None:
    # the 1 s photo (left 176, 44 px wide) in a 572 px row: it can go 176 px left and
    # 572 - 44 - 176 = 352 px right, never further
    got = _run(
        "return [-9999, -176, -10, 0, 100, 352, 9999].map(dx => core.clampShift("
        "{dx: dx, left: 176, width: 44, span: 572}));"
    )
    assert got == [-176, -176, -10, 0, 100, 352, 352]


def test_a_text_held_stays_inside_the_video() -> None:
    # a 3 s text from 2 s in a 12 s video at 44 px per second: from 0 to 9 s
    got = _run(
        "return [-9999, 9999].map(dx => core.clampShift("
        "{dx: dx, left: 2 * 44, width: 3 * 44, span: 12 * 44}));"
    )
    assert got == [-88, 7 * 44]
    # the clamped move gives the same start as the magnet's own bound
    starts = _run(
        "return [-88, 308].map(dx => core.shiftedStart("
        "{start: 2, length: 3, total: 12, dx: dx, px: 44}));"
    )
    assert starts == [0, 9]


def test_a_block_wider_than_its_track_does_not_move() -> None:
    assert _run("return core.clampShift({dx: 50, left: 0, width: 600, span: 500});") == 0


def test_a_drop_outside_the_tracks_changes_nothing() -> None:
    got = _run(
        "return ["
        " core.dropVerdict({outside: true, same: false}),"
        " core.dropVerdict({outside: false, same: false}),"
        " core.dropVerdict({outside: false, same: true}),"
        " core.dropVerdict({cancelled: true, outside: false, same: false}),"
        " core.dropVerdict(null)];"
    )
    assert got == ["back", "apply", "back", "back", "back"]


def test_the_drag_puts_a_block_dropped_outside_back() -> None:
    """The DOM half asks the core at the release: off the tracks it goes back (the
    existing return), without telling the screen; held, X is clamped and Y never moves."""
    drag = (_ASSETS / "timeline-drag.js").read_text(encoding="utf-8")
    release = drag[drag.index("function release(e)") :]
    verdict = release.index("core().dropVerdict(")
    assert "outside: outsideTracks(d, e.clientX, e.clientY)" in release
    back = release.index('if (verdict === "back")')
    assert verdict < back < release.index("putBack(d)") < release.index("report(d.root")
    update = drag[drag.index("function update()") : drag.index("function loop()")]
    assert "core().clampShift(" in update
    assert "translateY" not in drag  # only X ever moves
