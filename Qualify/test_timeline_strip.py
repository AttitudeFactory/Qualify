"""ED-11b (m-25029110): the server's frame strip under each uploaded video's block.

Offline: which tile each cell of a block shows and where (`timeline_vm.strip_cells`: 20 s,
a trimmed start, ×2, a piece of a cut, a block laid over by a transition, a 0,6 s video, a
20,4 s video), the row's style (`strip_style`), the read of the strips
(`upload_preview_state.read_strips`, on a fake `previews_for` and a minting double), the
editor's rows and cells (`CreativeState.clip_tl_frames`; never in the recipe), and the
block's markup and CSS (decorative, under the whole block, cells in seconds of the block).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import reflex as rx
from qualify_api.creative.upload_previews import FrameStrip, UploadPreview, preview_key, strip_key

from . import clip_editor_vm
from . import upload_preview_state as ups
from .creative_state import CreativeState
from .ui import timeline as tl
from .ui import timeline_vm as vm

_ASSETS = Path(__file__).parent.parent / "assets"
_CSS = (_ASSETS / "qualify-creative.css").read_text(encoding="utf-8")

TENANT = UUID("a0000000-0000-4000-8000-0000000e1101")
VIDEO = f"t/{TENANT}/uploads/abc_video.mp4"
OTHER = f"t/{TENANT}/uploads/def_video.mp4"
THIRD = f"t/{TENANT}/uploads/ghi_video.mp4"
STRIP = strip_key(TENANT, VIDEO)

#: The 20 s strip as the worker lays it: 20 tiles of 100×56, one row.
LAYOUT_20 = {"frames": 20, "columns": 20, "rows": 1}
#: The real read, taken before any test swaps it.
READ_STRIPS = ups.read_strips


def _f(value: str) -> float:
    return float(value)


def _check_aligned(
    cells: list[dict[str, str]], *, src_start: float, src_end: float, speed: float
) -> None:
    """The cells lie end to end over the block, and each one's picture is within ½ s of
    the ruler of the cell's middle (the frame of second *s* falls on its second)."""
    length = (src_end - src_start) / speed
    assert cells, "a strip must give cells"
    assert _f(cells[0]["at"]) == 0
    for before, after in zip(cells, cells[1:], strict=False):
        assert abs(_f(before["at"]) + _f(before["len"]) - _f(after["at"])) < 0.011  # no gap
    last = cells[-1]
    assert abs(_f(last["at"]) + _f(last["len"]) - length) < 0.011  # to the block's end
    for cell in cells:
        middle = _f(cell["at"]) + _f(cell["len"]) / 2
        shown_at = (_f(cell["shows"]) - src_start) / speed  # where the picture belongs
        assert abs(shown_at - middle) <= 0.5 + 1e-6, cell


# -- which tile goes where ---------------------------------------------------------------------


def test_a_20_second_video_gives_20_cells_each_on_its_second() -> None:
    cells = vm.strip_plan(0, 20, 1, **LAYOUT_20)
    assert len(cells) == 20
    assert [c["tile"] for c in cells] == [str(i) for i in range(20)]
    # the frame of second s sits on the ruler's [s, s+1): exactly, at ×1
    assert [(c["at"], c["len"]) for c in cells] == [(str(i), "1") for i in range(20)]
    assert [c["shows"] for c in cells] == [f"{i}.5" for i in range(20)]
    # one row: the tile's column as a share of the image
    assert cells[0]["pos"] == "0% 0%"
    assert cells[19]["pos"] == "100% 0%"
    assert cells[1]["pos"] == "5.2632% 0%"  # 1/19
    _check_aligned(cells, src_start=0, src_end=20, speed=1)


def test_a_trimmed_start_keeps_each_frame_on_its_second() -> None:
    cells = vm.strip_plan(3.5, 12, 1, **LAYOUT_20)
    # the first cell is the half second left of the 4th second, then whole seconds
    assert (cells[0]["at"], cells[0]["len"], cells[0]["tile"]) == ("0", "0.5", "3")
    assert (cells[1]["at"], cells[1]["len"], cells[1]["tile"]) == ("0.5", "1", "4")
    assert cells[-1]["tile"] == "11"
    assert len(cells) == 9
    _check_aligned(cells, src_start=3.5, src_end=12, speed=1)


def test_twice_as_fast_shows_one_frame_per_second_of_the_ruler() -> None:
    cells = vm.strip_plan(0, 20, 2, **LAYOUT_20)
    # 10 s on the ruler: a cell per ruler second, each the tile at its middle
    assert len(cells) == 10
    assert [(c["at"], c["len"]) for c in cells] == [(str(i), "1") for i in range(10)]
    assert [c["tile"] for c in cells] == [str(2 * i + 1) for i in range(10)]
    _check_aligned(cells, src_start=0, src_end=20, speed=2)
    # ×20 on a minute: never 60 slivers, three cells of a second
    minute = {"frames": 60, "columns": 60, "rows": 1}
    fast = vm.strip_plan(0, 60, 20, **minute)
    assert len(fast) == 3
    _check_aligned(fast, src_start=0, src_end=60, speed=20)


@pytest.mark.parametrize("speed", [1, 2, 3, 5, 10, 20])
def test_every_speed_and_trim_stays_within_half_a_second(speed: int) -> None:
    layout = {"frames": 60, "columns": 60, "rows": 1}
    for start, end in ((0, 60), (3.5, 41.25), (0.25, 7.75), (17, 18)):
        cells = vm.strip_plan(start, end, speed, **layout)
        _check_aligned(cells, src_start=start, src_end=end, speed=speed)


def test_a_piece_of_a_cut_shows_its_own_stretch() -> None:
    # «Cortar aquí» at 0:07 of the 20 s video: the second piece (`key#1`) uses 7…20 s
    first = vm.strip_plan(0, 7, 1, **LAYOUT_20)
    second = vm.strip_plan(7, 20, 1, **LAYOUT_20)
    assert [c["tile"] for c in first] == [str(i) for i in range(7)]
    assert [c["tile"] for c in second] == [str(i) for i in range(7, 20)]
    assert second[0]["at"] == "0"  # from its own block's start
    _check_aligned(second, src_start=7, src_end=20, speed=1)


def test_a_block_laid_over_by_a_transition_keeps_its_whole_strip() -> None:
    """m-25114465: the block after a «Fundido» of 1 s starts 1 s before the block before
    ends and is drawn WHOLE; its strip spans its whole length — the frames under the veil
    included — so every frame stays on its second of the ruler."""
    media = [
        {"id": "a", "kind": "video", "src_start": 0, "src_end": 10, "src_len": 10},
        {
            "id": "b",
            "kind": "video",
            "src_start": 0,
            "src_end": 8,
            "src_len": 8,
            "join": "fundido",
            "join_s": 1,
        },
    ]
    media[0]["tail_s"] = 1
    rows = vm.media_blocks(media)
    assert rows[1]["start"] == "9" and rows[1]["length"] == "8" and rows[1]["join_in"] == "1"
    cells = vm.strip_plan(0, 8, 1, frames=8, columns=8, rows=1)
    last = cells[-1]
    assert _f(last["at"]) + _f(last["len"]) == _f(rows[1]["length"])  # the block's real length
    # its first frame starts under the veil, at the block's own start (0:09 on the ruler)
    assert cells[0]["at"] == "0" and cells[0]["tile"] == "0"
    # the block before keeps its whole strip too (the next one is drawn over its end)
    before = vm.strip_plan(0, 10, 1, frames=10, columns=10, rows=1)
    assert _f(before[-1]["at"]) + _f(before[-1]["len"]) == _f(rows[0]["length"]) == 10


def test_a_video_under_a_second_shows_its_only_frame() -> None:
    cells = vm.strip_plan(0, 0.6, 1, frames=1, columns=1, rows=1)
    assert cells == [{"at": "0", "len": "0.6", "pos": "0% 0%", "tile": "0", "shows": "0.5"}]


def test_the_tail_with_no_tile_joins_the_cell_before() -> None:
    # 20,4 s gives 20 tiles (the last at 19,5 s): the last 0,4 s show tile 19, never a gap
    cells = vm.strip_plan(0, 20.4, 1, **LAYOUT_20)
    assert len(cells) == 20
    assert (cells[-1]["at"], cells[-1]["len"], cells[-1]["tile"]) == ("19", "1.4", "19")
    _check_aligned(cells, src_start=0, src_end=20.4, speed=1)


def test_past_the_strip_there_is_no_frame_rather_than_a_wrong_one() -> None:
    # a strip of 10 tiles for a stretch to 0:30 (an hour cap, a strip of an older copy)
    cells = vm.strip_plan(0, 30, 1, frames=10, columns=10, rows=1)
    assert [c["tile"] for c in cells] == [str(i) for i in range(10)]
    assert _f(cells[-1]["at"]) + _f(cells[-1]["len"]) <= 11


def test_a_long_video_wraps_into_rows() -> None:
    # 90 s: 60 tiles a row, two rows — tile 61 is column 1 of row 1
    cells = vm.strip_plan(60, 62, 1, frames=90, columns=60, rows=2)
    assert [c["tile"] for c in cells] == ["60", "61"]
    assert cells[0]["pos"] == "0% 100%"
    assert cells[1]["pos"] == "1.6949% 100%"  # 1/59


def test_a_five_minute_block_groups_seconds_into_60_cells() -> None:
    """review: a long block before any cut (5 min at ×1) never draws 300 cells: each cell
    takes 5 s of the ruler and shows the tile of its middle, still on its place."""
    layout = {"frames": 300, "columns": 60, "rows": 5}
    cells = vm.strip_plan(0, 300, 1, **layout)
    assert len(cells) == 60
    assert all(c["len"] == "5" for c in cells)
    assert [c["tile"] for c in cells[:3]] == ["2", "7", "12"]  # the middle of 0–5, 5–10…
    _check_aligned(cells, src_start=0, src_end=300, speed=1)
    # a minute stays one cell a second (the brief's 60 frames for 60 s)
    assert len(vm.strip_plan(0, 60, 1, frames=60, columns=60, rows=1)) == 60
    # a trimmed long stretch: still at most 60, still aligned
    odd = vm.strip_plan(3.5, 290.25, 1, **layout)
    assert len(odd) <= 60
    _check_aligned(odd, src_start=3.5, src_end=290.25, speed=1)


def test_nothing_to_draw_gives_no_cells() -> None:
    assert vm.strip_plan(5, 5, 1, **LAYOUT_20) == []
    assert vm.strip_plan(0, 5, 1, frames=0, columns=1, rows=1) == []


def test_the_rows_style() -> None:
    style = vm.strip_style("/r2media/tok", columns=60, rows=2, tile_width=100, tile_height=56)
    assert style == {
        "strip": "/r2media/tok",
        "strip_size": "6000% 200%",
        "strip_ratio": "1.7857",
        "strip_w": "100px",
    }
    vertical = vm.strip_style("/r2media/tok", columns=20, rows=1, tile_width=32, tile_height=56)
    assert vertical["strip_w"] == "32px" and vertical["strip_ratio"] == "0.5714"
    empty = vm.strip_style("", columns=60, rows=1, tile_width=100, tile_height=56)
    assert set(empty.values()) == {""}
    # every row carries the fields, empty until the screen lays a strip
    rows = vm.media_blocks([{"id": "a", "kind": "photo", "dur": 2}])
    rows += vm.overlay_blocks(
        [{"id": "t", "kind": "text", "label": "Hola", "start": 0, "end": 1}], "text", 2
    )
    assert all(row["strip"] == "" for row in rows)


# -- the read ------------------------------------------------------------------------------------


def _strip(**fields: Any) -> FrameStrip:
    layout = {"frames": 20, "columns": 20, "rows": 1, "tile_width": 100, "tile_height": 56}
    return FrameStrip(key=STRIP, **{**layout, **fields})


def _preview(status: str, key: str = VIDEO, **fields: Any) -> UploadPreview:
    return UploadPreview(
        source_key=key, status=status, preview_key=preview_key(TENANT, key), **fields
    )


@pytest.fixture
def previews(monkeypatch: pytest.MonkeyPatch) -> dict[str, UploadPreview]:
    rows: dict[str, UploadPreview] = {}
    monkeypatch.setattr(
        ups, "previews_for", lambda _t, keys: {k: rows[k] for k in keys if k in rows}
    )
    return rows


@pytest.fixture
def minted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    asked: list[tuple[str, str, str | None]] = []

    def mint(tenant_id: UUID, key: str, media_type: str, content_type: str | None = None) -> str:
        assert tenant_id == TENANT
        asked.append((key, media_type, content_type))
        return f"/r2media/tok-{len(asked)}"

    monkeypatch.setattr("Qualify.r2_media.issue_view_path", mint)
    return asked


def test_a_made_strip_is_minted_as_a_jpeg_of_the_business(previews, minted) -> None:
    previews[VIDEO] = _preview("done", strip=_strip(), strip_status="done")
    read = ups.read_strips(TENANT, [VIDEO])
    assert minted == [(STRIP, "image", "image/jpeg")]
    assert read.strips[VIDEO]["url"] == "/r2media/tok-1"
    assert read.strips[VIDEO]["frames"] == 20 and read.strips[VIDEO]["tile_width"] == 100
    assert read.ask == () and read.waiting is False


def test_a_v1_copy_asks_for_its_strip_and_waits(previews, minted) -> None:
    previews[VIDEO] = _preview("done", version="upload-preview-480p-v1")
    read = ups.read_strips(TENANT, [VIDEO])
    assert read.strips == {} and read.ask == (VIDEO,) and read.waiting is True
    assert minted == []


@pytest.mark.parametrize(
    ("status", "strip_status", "waiting"),
    [
        ("queued", "queued", True),
        ("running", "running", True),
        ("done", "running", True),
        ("failed", "failed", False),  # failed for good: nothing to wait for
    ],
)
def test_what_is_worth_reading_again(previews, minted, status, strip_status, waiting) -> None:
    fields: dict[str, Any] = {"strip_status": strip_status}
    if status == "failed":
        fields |= {"error_code": "unreadable", "strip_error_code": "unreadable"}
    if status == "done":
        fields |= {"strip_status": strip_status}
    previews[VIDEO] = _preview(status, **fields)
    read = ups.read_strips(TENANT, [VIDEO])
    assert read.strips == {} and read.ask == () and read.waiting is waiting


def test_a_video_whose_copy_was_never_asked_for_is_asked_once(previews, minted) -> None:
    """re-review: only the upload and the editor's OWN video ask for a copy; another video
    of the Clip whose request was lost would never get a strip — the reader asks."""
    previews[VIDEO] = _preview("none")
    read = ups.read_strips(TENANT, [VIDEO])
    assert read.ask == (VIDEO,) and read.waiting is True and minted == []


def test_a_strip_that_cannot_be_minted_is_left_out(previews, monkeypatch) -> None:
    previews[VIDEO] = _preview("done", strip=_strip(), strip_status="done")

    def broken(*_a: Any, **_k: Any) -> str:
        raise ConnectionError("redis down")

    monkeypatch.setattr("Qualify.r2_media.issue_view_path", broken)
    read = ups.read_strips(TENANT, [VIDEO])
    # made, but no path now: read again (never «done» with a strip missing)
    assert read.strips == {} and read.waiting is True and read.ask == ()


@pytest.mark.parametrize(
    "fields",
    [
        {},  # never asked for
        {"error_code": "attempts_exhausted", "transient_failures": 1},  # worth a retry
    ],
)
def test_asked_once_then_not_waited_for(previews, minted, fields) -> None:
    status = "failed" if fields else "none"
    previews[VIDEO] = _preview(status, **fields)
    first = ups.read_strips(TENANT, [VIDEO])
    assert first.ask == (VIDEO,) and first.waiting is True
    # asked already by this reader and still there: the request failed quietly
    again = ups.read_strips(TENANT, [VIDEO], asked={VIDEO})
    assert again.ask == () and again.waiting is False


def test_a_failed_read_is_no_strip(monkeypatch, caplog) -> None:
    def boom(*_a: Any) -> dict[str, UploadPreview]:
        raise RuntimeError("db down")

    monkeypatch.setattr(ups, "previews_for", boom)
    read = ups.read_strips(TENANT, [VIDEO])
    assert read == ups.StripRead({})
    assert "frame strips not read" in caplog.text


def test_only_the_owners_videos_are_read() -> None:
    videos = [
        {"key": VIDEO, "source": "upload"},
        {"key": VIDEO, "source": "upload"},
        {"key": OTHER, "source": "gallery"},
        {"key": f"t/{TENANT}/uploads/reel.mp4", "source": "reel"},
        {"key": f"t/{TENANT}/uploads/foto.jpg", "source": "upload"},
    ]
    assert ups.strip_video_keys(videos) == [VIDEO, OTHER]


# -- the editor's rows -----------------------------------------------------------------------


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


def _state() -> CreativeState:
    """The own uploaded video (20 s, measured) and a second uploaded video (8 s)."""
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_videos = [
        {"key": VIDEO, "name": "video.mp4", "source": "upload"},
        {"key": OTHER, "name": "otro.mp4", "source": "upload"},
    ]
    state.clip_sequence = [VIDEO, OTHER]
    # the own R2 video plays from its minted path (`resolve_clip_preview`)
    state.clip_preview_for, state.clip_preview_url = VIDEO, "/r2media/own"
    CreativeState.report_clip_source.fn(state, VIDEO, 20.0, 1080, 1920)
    CreativeState.report_clip_media.fn(state, OTHER, 8.0, 1080, 1920)
    return state


def _with_strip(state: CreativeState) -> CreativeState:
    state._clip_frame_strips = {
        VIDEO: {
            "url": "/r2media/strip",
            "frames": 20,
            "columns": 20,
            "rows": 1,
            "tile_width": 32,
            "tile_height": 56,
            "interval_s": 1,
            "offset_s": 0.5,
        }
    }
    return state


def test_without_a_strip_the_blocks_keep_their_picture(editor_on: None) -> None:
    state = _state()
    assert state.clip_tl_frames == {}
    assert all(row["strip"] == "" for row in state.clip_tl_media_rows)


def test_a_video_with_its_strip_carries_it_and_its_cells(editor_on: None) -> None:
    state = _with_strip(_state())
    rows = {row["id"]: row for row in state.clip_tl_media_rows}
    assert rows[VIDEO]["strip"] == "/r2media/strip"
    assert rows[VIDEO]["strip_w"] == "32px" and rows[VIDEO]["strip_size"] == "2000% 100%"
    assert rows[OTHER]["strip"] == ""  # its strip is not made yet: its picture of before
    frames = state.clip_tl_frames
    assert set(frames) == {VIDEO}
    # the editor proposes the first 15 s of a 20 s video: 15 cells, one per second
    assert frames[VIDEO] == _cells(0, 15)
    assert len(frames[VIDEO]) == 15
    # only what the screen draws travels to the browser
    assert set(frames[VIDEO][0]) == {"at", "len", "pos"}


def _cells(start: float, end: float, speed: float = 1) -> list[dict[str, str]]:
    return vm.strip_cells(start, end, speed, frames=20, columns=20, rows=1)


def test_cut_trimmed_and_sped_up_pieces_follow_their_stretch(editor_on: None) -> None:
    state = _with_strip(_state())
    CreativeState.select_clip_block.fn(state, VIDEO)
    CreativeState.hear_clip_time.fn(state, 5.0, "pause")
    CreativeState.cut_clip_video.fn(state)
    second = clip_editor_vm.piece_id(VIDEO, 1)
    frames = state.clip_tl_frames
    assert frames[VIDEO] == _cells(0, 5)
    assert frames[second] == _cells(5, 15)  # `key#1`: from its own block's start
    # trimmed with a handle: the cells follow the new stretch
    rows = {r["id"]: r for r in state.clip_tl_media_rows}
    CreativeState.drop_clip_block.fn(state, second, "start", float(rows[second]["start_now"]) + 2)
    assert state.clip_tl_frames[second] == _cells(7, 15)
    # sped up: fewer cells, each a second of the ruler
    before = len(state.clip_tl_frames[VIDEO])
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert len(state.clip_tl_frames[VIDEO]) < before


def test_the_strip_never_reaches_the_recipe(editor_on: None) -> None:
    plain = json.dumps(_state()._clip_edit_recipe(), default=str)
    drawn = json.dumps(_with_strip(_state())._clip_edit_recipe(), default=str)
    assert drawn == plain
    assert "strip" not in drawn and "/r2media/strip" not in drawn


def test_leaving_the_clip_forgets_the_strips(editor_on: None) -> None:
    state = _with_strip(_state())
    state._clip_strip_watch = "reader-1"
    state._reset_media_inputs()
    assert state._clip_frame_strips == {}
    assert state._clip_strip_watch != "reader-1"  # a reader still running stops


async def test_a_new_reader_never_reuses_an_old_token(editor_on: None, monkeypatch) -> None:
    """review: an int token went back to 0 with `reset()` and a reader from before could
    match a new one; a `uuid4` never repeats."""

    async def tenant(self: CreativeState) -> UUID:
        return TENANT

    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    state = _state()
    await CreativeState.watch_clip_frame_strips.fn(state)
    first = state._clip_strip_watch
    state._reset_media_inputs()
    state = _state()  # a fresh state, as after `reset()`
    await CreativeState.watch_clip_frame_strips.fn(state)
    assert first and state._clip_strip_watch and state._clip_strip_watch != first


# -- the reader's loop ---------------------------------------------------------------------------


class _Lock:
    """`async with self` of a background event, as a no-op."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Loop:
    """The reader's world: `read_strips` answers in turn, the session's business can
    change, and `ask_for_preview` / `asyncio.sleep` are recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, reads: list[ups.StripRead]) -> None:
        self.reads = list(reads)
        self.calls = 0
        self.asked: list[str] = []
        self.sleeps = 0
        self.waited: list[float] = []
        self.session: UUID | None = TENANT
        self.on_read: Any = None
        self.state = _state()
        self.state._clip_strip_tenant = str(TENANT)
        self.state._clip_strip_watch = "mine"
        state_cls = type(self.state)
        loop = self

        async def session(_self: CreativeState) -> UUID | None:
            return loop.session

        async def sleep(seconds: float) -> None:
            loop.sleeps += 1
            loop.waited.append(seconds)

        def read(tenant_id: UUID, keys: list[str], _asked: Any = ()) -> ups.StripRead:
            assert tenant_id == TENANT and VIDEO in keys
            loop.calls += 1
            if loop.on_read is not None:
                loop.on_read(loop)
            return loop.reads[min(loop.calls, len(loop.reads)) - 1]

        monkeypatch.setattr(state_cls, "_clip_preview_tenant", session)
        monkeypatch.setattr(state_cls, "__aenter__", _Lock.__aenter__, raising=False)
        monkeypatch.setattr(state_cls, "__aexit__", _Lock.__aexit__, raising=False)
        monkeypatch.setattr("Qualify.creative_state.asyncio.sleep", sleep)
        monkeypatch.setattr(ups, "read_strips", read)
        monkeypatch.setattr(
            "Qualify.creative_state.upload_preview_provider.ask_for_preview",
            lambda _t, _b, key: loop.asked.append(key),
        )

    async def run(self) -> None:
        await CreativeState.read_clip_frame_strips.fn(self.state, "mine")


_MADE = {VIDEO: {"url": "/r2media/s", "frames": 20, "columns": 20, "rows": 1}}


async def test_the_loop_keeps_reading_while_waiting_and_asks_once(
    editor_on: None, monkeypatch
) -> None:
    waiting = ups.StripRead({}, ask=(VIDEO,), waiting=True)
    loop = _Loop(monkeypatch, [waiting, waiting, ups.StripRead(_MADE)])
    await loop.run()
    assert loop.calls == 3 and loop.sleeps == 2
    assert loop.asked == [VIDEO]  # once per video and reader
    assert loop.state._clip_frame_strips == _MADE


async def test_a_video_never_asked_for_gets_its_strip_with_one_request(
    editor_on: None, monkeypatch, minted
) -> None:
    """The real read over a fake `previews_for`: none → queued → done with its strip.
    One request, and the strip kept."""
    loop = _Loop(monkeypatch, [])
    monkeypatch.setattr(ups, "read_strips", READ_STRIPS)
    states = iter(
        [
            _preview("none"),
            _preview("queued", strip_status="queued"),
            _preview("done", strip=_strip(), strip_status="done"),
        ]
    )
    reads: list[str] = []

    def previews_for(_t: UUID, keys: list[str]) -> dict[str, UploadPreview]:
        reads.append("read")
        now = next(states)
        return {VIDEO: now} if VIDEO in keys else {}

    monkeypatch.setattr(ups, "previews_for", previews_for)
    await loop.run()
    assert len(reads) == 3 and loop.sleeps == 2
    assert loop.asked == [VIDEO]  # one request
    assert loop.state._clip_frame_strips[VIDEO]["url"] == "/r2media/tok-1"
    assert loop.state._clip_strip_done_keys == f"{VIDEO}|{OTHER}"  # settled


async def test_the_loop_stops_when_nothing_is_on_its_way(editor_on: None, monkeypatch) -> None:
    loop = _Loop(monkeypatch, [ups.StripRead({}, waiting=False)])
    await loop.run()
    assert loop.calls == 1 and loop.sleeps == 0 and loop.asked == []


def test_the_waits_grow_and_last_half_an_hour() -> None:
    """Live test 2026-11-26: the worker took more than 4 min and the reader had given up.
    Now it waits 6 s, 12 s, 30 s, then a minute, for up to 30 min."""
    waits = ups.strip_waits()
    assert waits[:5] == [6.0, 12.0, 30.0, 60.0, 60.0]
    assert max(waits) == 60.0
    assert 29 * 60 <= sum(waits) <= ups.STRIP_GIVE_UP_SECONDS == 30 * 60
    assert sum(waits[:7]) > 4 * 60  # past the live test's wait within a few reads
    assert ups.strip_delay(0) == 0.0


async def test_the_loop_gives_up_after_half_an_hour(editor_on: None, monkeypatch) -> None:
    loop = _Loop(monkeypatch, [ups.StripRead({}, waiting=True)])
    loop.state._clip_strip_beat = 1.0
    await loop.run()
    assert loop.waited == ups.strip_waits()
    assert loop.calls == len(ups.strip_waits()) + 1
    # it ended: the next change of the timeline arms a new one
    assert loop.state._clip_strip_beat == 0.0


# -- when a reader is armed ----------------------------------------------------------------


async def _session(self: CreativeState) -> UUID:
    return TENANT


async def test_a_reader_alive_is_not_started_twice(editor_on: None, monkeypatch) -> None:
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", _session)
    state = _state()
    assert await CreativeState.watch_clip_frame_strips.fn(state) is not None
    first = state._clip_strip_watch
    # a remount or a timeline change while it is alive: it keeps its own waits
    assert await CreativeState.watch_clip_frame_strips.fn(state) is None
    assert state._clip_strip_watch == first
    # it gave up (or the server restarted and it never checked in again): armed anew
    state._clip_strip_beat = 0.0
    assert await CreativeState.watch_clip_frame_strips.fn(state) is not None
    assert state._clip_strip_watch != first
    state._clip_strip_beat = 1.0  # last heard of long ago
    assert await CreativeState.watch_clip_frame_strips.fn(state) is not None


async def test_videos_that_will_never_have_a_strip_cost_no_query_per_touch(
    editor_on: None, monkeypatch
) -> None:
    """re-review: a reader that ended with no strip and nothing on its way (failed for
    good, not an upload) settles THESE videos for a while: touching the timeline arms no
    new reader; other videos, or a long while after, are read again."""
    loop = _Loop(monkeypatch, [ups.StripRead({}, waiting=False)])
    state = loop.state
    await CreativeState.watch_clip_frame_strips.fn(state)  # arms "its" reader
    await CreativeState.read_clip_frame_strips.fn(state, state._clip_strip_watch)
    assert loop.calls == 1 and state._clip_frame_strips == {}
    assert state._clip_strip_beat == 0.0  # it ended
    # a trim, a drag, a remount: no reader, no query
    CreativeState.select_clip_block.fn(state, VIDEO)
    CreativeState.hear_clip_time.fn(state, 5.0, "pause")
    CreativeState.cut_clip_video.fn(state)
    assert await CreativeState.watch_clip_frame_strips.fn(state) is None
    # a long while after (the paths of made strips would be old): read again
    state._clip_strip_done_at = 1.0
    assert await CreativeState.watch_clip_frame_strips.fn(state) is not None


async def test_other_videos_are_read_again(editor_on: None, monkeypatch) -> None:
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", _session)
    state = _state()
    state._clip_strip_tenant = str(TENANT)
    state._clip_strip_done_keys = f"{VIDEO}|{OTHER}"
    state._clip_strip_done_at = time.time()
    assert await CreativeState.watch_clip_frame_strips.fn(state) is None
    state.clip_videos = [*state.clip_videos, {"key": THIRD, "name": "c.mp4", "source": "upload"}]
    assert await CreativeState.watch_clip_frame_strips.fn(state) is not None


async def test_changing_the_videos_replaces_a_live_reader(editor_on: None, monkeypatch) -> None:
    """re-review: with a reader alive, a video added arms a new reader; the old one, on
    waking, leaves without reading."""
    loop = _Loop(monkeypatch, [ups.StripRead({}, waiting=True)])
    state = loop.state
    await CreativeState.watch_clip_frame_strips.fn(state)
    old = state._clip_strip_watch

    async def wakes_to_new_videos(seconds: float) -> None:
        loop.waited.append(seconds)
        state.clip_videos = [*state.clip_videos, {"key": THIRD, "name": "c.mp4"}]
        assert await CreativeState.watch_clip_frame_strips.fn(state) is not None

    monkeypatch.setattr("Qualify.creative_state.asyncio.sleep", wakes_to_new_videos)
    await CreativeState.read_clip_frame_strips.fn(state, old)
    assert loop.calls == 1  # its first read only: woken, it found another reader
    assert state._clip_strip_watch != old and state._clip_strip_keys.endswith(THIRD)
    assert state._clip_strip_beat > 0  # the new reader's beat is left alone


def test_touching_the_timeline_mounts_the_reader_again(editor_on: None) -> None:
    state = _state()
    before = state.clip_strip_videos
    assert before.startswith(f"{VIDEO}|{OTHER}#")
    CreativeState.select_clip_block.fn(state, VIDEO)
    CreativeState.hear_clip_time.fn(state, 5.0, "pause")
    CreativeState.cut_clip_video.fn(state)
    assert state.clip_strip_videos != before


@pytest.mark.parametrize("change", ["another_reader", "editor_left", "another_business"])
async def test_the_loop_stops_and_drops_its_read(editor_on: None, monkeypatch, change: str) -> None:
    def changes(loop: _Loop) -> None:
        if change == "another_reader":
            loop.state._clip_strip_watch = "newer"
        elif change == "editor_left":
            loop.state.gen_category = "image"
        else:
            loop.session = UUID("b0000000-0000-4000-8000-0000000e1101")

    loop = _Loop(monkeypatch, [ups.StripRead(_MADE, ask=(VIDEO,), waiting=True)])
    loop.on_read = changes  # it changes while the read runs
    await loop.run()
    assert loop.calls == 1
    assert loop.state._clip_frame_strips == {}  # the read is dropped
    assert loop.asked == []  # and nothing is asked for


async def test_the_loop_checks_the_session_before_reading(editor_on: None, monkeypatch) -> None:
    loop = _Loop(monkeypatch, [ups.StripRead(_MADE)])
    loop.session = None  # logged out before the first read
    await loop.run()
    assert loop.calls == 0 and loop.asked == []


async def _no_tenant(self: CreativeState) -> None:
    return None


async def test_the_reader_needs_the_sessions_business(editor_on: None, monkeypatch) -> None:
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", _no_tenant)
    state = _with_strip(_state())
    assert await CreativeState.watch_clip_frame_strips.fn(state) is None
    assert state._clip_frame_strips == {}  # no business: nothing of a previous one


async def test_the_reader_forgets_another_business_and_hands_off(
    editor_on: None, monkeypatch
) -> None:
    async def tenant(self: CreativeState) -> UUID:
        return TENANT

    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    state = _with_strip(_state())
    state._clip_strip_tenant = "another"
    event = await CreativeState.watch_clip_frame_strips.fn(state)
    assert state._clip_frame_strips == {} and state._clip_strip_tenant == str(TENANT)
    assert event is not None


# -- the markup and the CSS ----------------------------------------------------------------------


class _StripState(rx.State):
    media: list[dict[str, str]] = [
        {
            **vm.media_blocks(
                [{"id": "v", "kind": "video", "src_start": 0, "src_end": 3, "src_len": 3}]
            )[0],
            **vm.strip_style("/r2media/s", columns=3, rows=1, tile_width=100, tile_height=56),
        }
    ]
    frames: dict[str, list[dict[str, str]]] = {
        "v": vm.strip_cells(0, 3, 1, frames=3, columns=3, rows=1)
    }
    none: list[dict[str, str]] = []
    selected: str = ""

    @rx.event
    def pick(self, block_id: str) -> None:
        self.selected = block_id


def _rendered(frames: bool = True) -> str:
    return str(
        tl.timeline(
            media=_StripState.media,
            texts=_StripState.none,
            effects=_StripState.none,
            ticks=_StripState.none,
            total="3",
            selected=_StripState.selected,
            on_select=_StripState.pick,
            thumb_base="https://api.example",
            frames=_StripState.frames if frames else None,
        ).render()
    )


def test_the_joins_stay_over_the_strip_and_take_taps() -> None:
    """Live test 2026-11-26 («la unión no abre»): the strip changes nothing of the joins'
    layer — it is still rendered beside the media track with its handler, above the
    blocks, and the strip (inside the block's own stacking context) never takes a tap."""
    rendered = str(
        tl.timeline(
            media=_StripState.media,
            texts=_StripState.none,
            effects=_StripState.none,
            ticks=_StripState.none,
            total="3",
            selected=_StripState.selected,
            on_select=_StripState.pick,
            frames=_StripState.frames,
            joins=_StripState.none,
            on_join=_StripState.pick,
        ).render()
    )
    assert "q-tl__joins" in rendered and "q-tl__media" in rendered
    layer = _CSS.split(".q-tl__joins {", 1)[1].split("}", 1)[0]
    assert "z-index: 4;" in layer  # over the blocks (z 2, a chosen one z 3)
    join = _CSS.split(".q-tl__join {", 1)[1].split("}", 1)[0]
    assert "pointer-events: auto;" in join
    for rule in ("\n.q-tl__strip {", "\n.q-tl__pic {"):
        body = _CSS.split(rule, 1)[1].split("}", 1)[0]
        assert "pointer-events: none;" in body and "z-index: -1;" in body


def test_the_block_draws_its_strip_decorative_with_its_name() -> None:
    rendered = _rendered()
    assert "q-tl__strip" in rendered and "q-tl__frame-cell" in rendered
    assert "q-tl__frame-pic" in rendered and "data-tl-strip" in rendered
    assert "--c-at" in rendered and "--c-len" in rendered and "backgroundPosition" in rendered
    # the image is the backend's origin followed by the row's strip path, inside url(...)
    image = re.escape('"--s-img"] : (("url(\\\\"https://api.example"+row_rx_state_?.["strip"]')
    assert re.search(image, rendered)
    strip = rendered[rendered.index("q-tl__strip") - 400 : rendered.index("q-tl__strip") + 400]
    assert "aria-hidden" in strip.replace("ariaHidden", "aria-hidden")
    # the block keeps its name and its picture of before when it has no strip
    assert "q-tl__label" in rendered and "q-tl__pic" in rendered


def test_without_frames_nothing_changes() -> None:
    rendered = _rendered(frames=False)
    assert "q-tl__strip" not in rendered and "data-tl-strip" not in rendered


def test_the_cells_are_placed_in_seconds_of_the_block() -> None:
    cell = _CSS.split(".q-tl__frame-cell {", 1)[1].split("}", 1)[0]
    assert "left: calc(var(--c-at) / var(--b-len) * 100%);" in cell
    assert "width: calc(var(--c-len) / var(--b-len) * 100%);" in cell
    pic = _CSS.split(".q-tl__frame-pic {", 1)[1].split("}", 1)[0]
    assert "background-size: var(--s-size);" in pic and "aspect-ratio: var(--s-ratio);" in pic
    strip = _CSS.split(".q-tl__strip {", 1)[1].split("}", 1)[0]
    # under the whole block (never shifted by a transition's veil), never catching a tap
    assert "inset: 0;" in strip and "z-index: -1;" in strip and "pointer-events: none;" in strip
    assert ".q-tl__strip" not in _CSS.split('.q-tl__item[data-tl-in="1"]', 1)[1].split("\n")[0]
    # high contrast: the icon, never a photo under the name; nothing animates
    forced = _CSS.split("@media (forced-colors: active) {\n  .q-tl__strip", 1)[1][:120]
    assert forced.startswith(" { display: none; }") and ".q-tl__pic { display: none; }" in forced
    assert "transition" not in cell + pic + strip and "animation" not in cell + pic + strip


def test_the_picture_of_before_stays_under_the_strip() -> None:
    """UX review: no grey flash while the frames load, and the picture of before when
    they never do (a `/r2media` path past its hour): the strip is transparent and drawn
    over the block's picture, which stays in the tree."""
    strip = _CSS.split(".q-tl__strip {", 1)[1].split("}", 1)[0]
    assert "background: transparent;" in strip and "gray" not in strip
    rendered = _rendered()
    assert rendered.index("q-tl__pic-img") < rendered.index("q-tl__strip")


def test_the_veil_and_the_playhead_read_over_the_frames() -> None:
    veil = _CSS.split('.q-tl__item:has(.q-tl__block[data-tl-strip="1"]) .q-tl__overlap {', 1)
    assert len(veil) == 2
    rule = veil[1].split("}", 1)[0]
    assert "var(--accent-a8)" in rule and "var(--black-a5)" in rule
    head = _CSS.split(".q-tl__head {", 1)[1].split("}", 1)[0]
    assert "box-shadow: 0 0 0 1px var(--black-a8);" in head
