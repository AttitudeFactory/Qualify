"""EF-18 (m-25026598): the contact sheet of a composed video — which frames (start, end
and the shots between), always six, deterministic, and taken from the file as it is (a
layer laid over the video shows in every frame). Synthetic MP4s written with PyAV; no
network, no `ffmpeg` binary."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from qualify_creative.video.contact_sheet import (  # noqa: E402
    CELL_BOX,
    SHEET_FRAMES,
    STRIP_HEIGHT,
    make_contact_sheet,
    pick_times,
)
from qualify_creative.video.shots import ShotSpan  # noqa: E402

FPS = 30
SIZE = (180, 320)  # 9:16
#: The «layer»: a magenta band laid over every frame, as a composed text would be.
LAYER = (255, 0, 255)
LAYER_ROWS = (40, 80)


def _write(
    path: Path,
    shots: list[tuple[tuple[int, int, int], float]],
    options: dict[str, str] | None = None,
) -> Path:
    """An H.264 MP4: per shot, a flat colour for that many seconds, with the magenta
    layer band over every frame."""
    with av.open(str(path), "w") as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = SIZE[0], SIZE[1], "yuv420p"
        stream.options = {"preset": "ultrafast", "crf": "18", **(options or {})}
        for colour, seconds in shots:
            for _ in range(round(seconds * FPS)):
                picture = np.empty((SIZE[1], SIZE[0], 3), dtype=np.uint8)
                picture[:] = colour
                picture[LAYER_ROWS[0] : LAYER_ROWS[1], :] = LAYER
                frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
                for packet in stream.encode(frame):
                    sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return path


THREE_SHOTS = [((200, 40, 40), 2.0), ((40, 200, 40), 2.0), ((40, 40, 200), 2.0)]


def _spans(*starts: float, end: float) -> list[ShotSpan]:
    bounds = [*starts, end]
    return [ShotSpan(i, bounds[i], bounds[i + 1]) for i in range(len(starts))]


# ---------------------------------------------------------------------------
# which frames


def test_six_frames_start_end_and_the_cuts() -> None:
    times = pick_times(_spans(0.0, 2.0, 4.0, end=6.0), 6.0)
    assert len(times) == SHEET_FRAMES
    assert times[0] == (0.6, "start") and times[-1] == (5.75, "end")
    # each cut a moment after it, so a fade in has settled
    assert (2.5, "cut") in times and (4.5, "cut") in times
    assert [t for t, _ in times] == sorted(t for t, _ in times)
    assert sum(role == "fill" for _, role in times) == 2


def test_a_single_shot_is_filled_evenly() -> None:
    times = pick_times(_spans(0.0, end=10.0), 10.0)
    assert [role for _, role in times] == ["start", "fill", "fill", "fill", "fill", "end"]
    gaps = [b[0] - a[0] for a, b in zip(times, times[1:], strict=False)]
    assert max(gaps) - min(gaps) < 1.0


def test_many_cuts_are_thinned_keeping_the_first_and_the_last() -> None:
    starts = [float(s) for s in range(0, 20, 2)]  # ten shots of 2 s
    times = pick_times(_spans(*starts, end=20.0), 20.0)
    cuts = [t for t, role in times if role == "cut"]
    assert len(times) == SHEET_FRAMES and len(cuts) == SHEET_FRAMES - 2
    assert cuts[0] == 2.5 and cuts[-1] == 18.5


def test_a_very_short_video_still_gets_six_frames() -> None:
    times = pick_times(_spans(0.0, end=0.5), 0.5)
    assert len(times) == SHEET_FRAMES
    assert all(0.0 <= t <= 0.5 for t, _ in times)


# ---------------------------------------------------------------------------
# the frames themselves


@pytest.fixture(scope="module")
def three_shots(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write(tmp_path_factory.mktemp("sheet") / "three.mp4", THREE_SHOTS)


def _rgb(jpeg: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(jpeg)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.int16)


def test_the_sheet_has_six_frames_with_the_layer_on_top(three_shots: Path) -> None:
    sheet = make_contact_sheet(three_shots)
    assert len(sheet.frames) == SHEET_FRAMES and sheet.shots == 3
    assert abs(sheet.duration_s - 6.0) < 0.05
    for frame in sheet.frames:
        pixels = _rgb(frame.jpeg)
        assert pixels.shape[:2] == (frame.height, frame.width)
        assert frame.width <= CELL_BOX[0] and frame.height <= CELL_BOX[1]
        band = pixels[LAYER_ROWS[0] + 4 : LAYER_ROWS[1] - 4]
        assert np.abs(band - np.array(LAYER)).mean() < 20  # the layer is in every frame
    # every shot shows: red, green and blue below the band
    bodies = {int(np.argmax(_rgb(frame.jpeg)[200:300].mean(axis=(0, 1)))) for frame in sheet.frames}
    assert bodies == {0, 1, 2}


def test_the_strip_is_one_row_of_the_six(three_shots: Path) -> None:
    sheet = make_contact_sheet(three_shots)
    with Image.open(io.BytesIO(sheet.strip)) as strip:
        assert strip.format == "JPEG"
        assert strip.size == sheet.strip_size
        assert strip.height > STRIP_HEIGHT and strip.width > 6 * STRIP_HEIGHT * 9 / 16


def test_the_same_file_gives_the_same_sheet(three_shots: Path) -> None:
    first, second = make_contact_sheet(three_shots), make_contact_sheet(three_shots)
    assert [f.jpeg for f in first.frames] == [f.jpeg for f in second.frames]
    assert first.strip == second.strip
    assert [(f.target_s, f.time_s) for f in first.frames] == [
        (f.target_s, f.time_s) for f in second.frames
    ]


def test_the_provenance_names_the_process(three_shots: Path) -> None:
    params = make_contact_sheet(three_shots).params()
    assert params["version"] == "contact-sheet-4"
    assert params["detector"] and params["frames_wanted"] == SHEET_FRAMES
    assert params["shots"] == 3 and params["cuts"] == "detected"
    assert params["av_version"] == av.__version__
    import PIL

    assert params["pillow_version"] == PIL.__version__
    assert params["decode_threads"] <= 2


def test_the_shots_are_the_detectors(three_shots: Path) -> None:
    """The one pass finds the same cuts as `shots.detect_shots` on the same file."""
    from qualify_creative.video.shots import detect_shots

    sheet = make_contact_sheet(three_shots)
    cuts = [f.target_s for f in sheet.frames if f.role == "cut"]
    expected = [round(s.start_s + 0.5, 4) for s in detect_shots(three_shots)[1:]]
    assert cuts == expected


def test_a_pass_over_its_budget_spreads_the_frames_evenly(three_shots: Path) -> None:
    """A slow pass is dropped: six frames spread evenly over the length, from what it
    kept and a seek to each time it lacks."""
    ticks = iter(float(n) for n in range(10_000))
    sheet = make_contact_sheet(three_shots, budget_s=0.0025, clock=lambda: next(ticks) * 1e-3)
    assert sheet.cuts == "even" and sheet.params()["cuts"] == "even"
    assert len(sheet.frames) == SHEET_FRAMES
    assert all(f.role in ("start", "fill", "end") for f in sheet.frames)
    assert abs(sheet.duration_s - 6.0) < 0.1
    for frame in sheet.frames:
        band = _rgb(frame.jpeg)[LAYER_ROWS[0] + 4 : LAYER_ROWS[1] - 4]
        assert np.abs(band - np.array(LAYER)).mean() < 20


#: Ten one-second shots whose colour says which second a frame is from (red = 25 × s).
SECONDS = [((25 * s, 255 - 25 * s, 128), 1.0) for s in range(10)]
#: One keyframe at the start and none after it (no scene cut keyframes either).
ONE_KEYFRAME = {"g": "1000", "keyint_min": "1000", "sc_threshold": "0"}


def _second_of(jpeg: bytes) -> int:
    red = float(_rgb(jpeg)[200:300, :, 0].mean())
    return round(red / 25)


def _keyframes(path: Path) -> list[float]:
    with av.open(str(path)) as source:
        stream = source.streams.video[0]
        return [
            float(packet.pts * stream.time_base)
            for packet in source.demux(stream)
            if packet.is_keyframe and packet.pts is not None
        ]


@pytest.mark.parametrize("clock", ["budget_zero", "slow_clock"])
def test_even_frames_are_distinct_and_reach_the_end_without_keyframes(
    tmp_path: Path, clock: str
) -> None:
    """The Docker finding (768m, 1 CPU): a pass over its budget, on a video with no
    keyframe after its start, must still give six DIFFERENT frames spread to the end —
    each read by seeking to its time, the last at 90 % of the length or more."""
    video = _write(tmp_path / "tens.mp4", SECONDS, ONE_KEYFRAME)
    assert [k for k in _keyframes(video) if k > 5.0] == []  # none after the half
    if clock == "budget_zero":
        sheet = make_contact_sheet(video, budget_s=0)
    else:
        ticks = iter(float(n) for n in range(10_000))
        sheet = make_contact_sheet(video, budget_s=0.003, clock=lambda: next(ticks) * 1e-3)
    assert sheet.cuts == "even"
    times = [f.time_s for f in sheet.frames]
    assert len(times) == SHEET_FRAMES and len(set(times)) == SHEET_FRAMES
    assert times == sorted(times)
    assert times[-1] >= 0.9 * sheet.duration_s and abs(sheet.duration_s - 10.0) < 0.1
    for frame in sheet.frames:  # the picture IS the frame of its time
        assert frame.time_s + 1e-3 >= frame.target_s
        assert _second_of(frame.jpeg) == min(9, int(frame.time_s + 1e-6))


def test_a_detected_sheet_ends_near_the_end(three_shots: Path) -> None:
    sheet = make_contact_sheet(three_shots)
    assert sheet.cuts == "detected"
    assert sheet.frames[-1].time_s >= sheet.duration_s - 0.3
    assert len({f.time_s for f in sheet.frames}) == len(sheet.frames)


def test_a_video_too_short_for_six_frames_gives_fewer_never_a_repeat(tmp_path: Path) -> None:
    video = _write(tmp_path / "short.mp4", [((200, 40, 40), 0.1)])  # three frames
    for budget in (10.0, 0.0):
        sheet = make_contact_sheet(video, budget_s=budget)
        times = [f.time_s for f in sheet.frames]
        assert 1 <= len(times) <= 3 and len(set(times)) == len(times)
        assert [f.index for f in sheet.frames] == list(range(len(times)))


#: Twenty one-second shots (red = 12 × s) and a keyframe every 2 s exactly.
TWENTY = [((12 * s, 255 - 12 * s, 128), 1.0) for s in range(20)]
GOP_2S = {"g": "60", "keyint_min": "60", "sc_threshold": "0"}


def _second_of_twenty(jpeg: bytes) -> int:
    return round(float(_rgb(jpeg)[200:300, :, 0].mean()) / 12)


def _over(path: Path, duration_s: float | None) -> object:
    """What `_scan` hands the fallback when it stops at once (nothing kept yet)."""
    from qualify_creative.video._source import open_video, probe
    from qualify_creative.video.contact_sheet import _OverBudget

    with open_video(path) as (container, stream):
        timeline = probe(container, stream, need_end=False)
    return _OverBudget(duration_s, [], 0.0, timeline.origin_s, timeline.rotation)


def _check_even(frames: list, duration: float, seconds_of: object) -> list[float]:
    times = [f.time_s for f in frames]
    assert times == sorted(times) and len(set(times)) == len(times)
    assert [f.index for f in frames] == list(range(len(frames)))
    for frame in frames:  # the picture IS the frame of its own time
        assert seconds_of(frame.jpeg) == min(int(duration) - 1, int(frame.time_s + 1e-6))
    return times


@pytest.fixture(scope="module")
def gop_2s(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write(tmp_path_factory.mktemp("even") / "gop2.mp4", TWENTY, GOP_2S)


def test_even_with_budget_answers_each_time_with_its_own_frame(gop_2s: Path) -> None:
    from qualify_creative.video.contact_sheet import _evenly

    ticks = iter(float(n) for n in range(100_000))
    frames, duration = _evenly(gop_2s, _over(gop_2s, 20.0), lambda: next(ticks) * 1e-3)
    times = _check_even(frames, duration, _second_of_twenty)
    assert len(times) == SHEET_FRAMES
    assert all(f.time_s + 1e-3 >= f.target_s for f in frames)
    assert times[-1] >= duration - 0.25 - 1e-3  # within 0.25 s of the end


def test_even_with_no_budget_takes_each_times_keyframe_end_kept(gop_2s: Path) -> None:
    """Budget 0: each time gets the keyframe at or before it (documented): the end's is
    the keyframe nearest the end (18 s), never lost to another time's frame."""
    from qualify_creative.video.contact_sheet import _evenly

    frames, duration = _evenly(gop_2s, _over(gop_2s, 20.0), lambda: 0.0, budget_s=0)
    times = _check_even(frames, duration, _second_of_twenty)
    assert all(abs(t / 2 - round(t / 2)) < 1e-3 for t in times)  # keyframes only
    assert all(f.time_s <= f.target_s + 1e-3 for f in frames)
    assert times[-1] == pytest.approx(18.0, abs=1e-3)
    assert len(times) == SHEET_FRAMES  # six times on six different keyframes


def test_even_with_a_clock_spent_mid_gop_keeps_the_end(gop_2s: Path) -> None:
    """The budget runs out inside the first seek's GOP: that seek (the end's) keeps the
    last frame it decoded; the rest are keyframes. Still ordered, distinct, its own."""
    from qualify_creative.video.contact_sheet import _evenly

    ticks = iter(float(n) for n in range(100_000))
    frames, duration = _evenly(gop_2s, _over(gop_2s, 20.0), lambda: float(next(ticks)), budget_s=20)
    times = _check_even(frames, duration, _second_of_twenty)
    assert 18.0 - 1e-3 <= times[-1] <= 19.75 + 1e-3  # in the end's own GOP


def test_even_with_one_keyframe_and_no_budget_gives_one_frame(tmp_path: Path) -> None:
    """One keyframe at the start and no budget: every time lands on it — one frame, kept
    by the start by rank (documented: fewer frames, never a repeat)."""
    from qualify_creative.video.contact_sheet import _evenly

    video = _write(tmp_path / "one.mp4", SECONDS, ONE_KEYFRAME)
    frames, duration = _evenly(video, _over(video, 10.0), lambda: 0.0, budget_s=0)
    assert [f.time_s for f in frames] == [0.0] and frames[0].role == "start"
    _check_even(frames, duration, _second_of)


def test_even_with_no_duration_in_the_header_reads_it_from_the_packets(gop_2s: Path) -> None:
    from qualify_creative.video.contact_sheet import _demuxed_seconds, _evenly

    over = _over(gop_2s, None)
    assert _demuxed_seconds(gop_2s, over.origin_s) == pytest.approx(20.0, abs=0.05)
    ticks = iter(float(n) for n in range(100_000))
    frames, duration = _evenly(gop_2s, over, lambda: next(ticks) * 1e-3)
    assert duration == pytest.approx(20.0, abs=0.05)
    times = _check_even(frames, duration, _second_of_twenty)
    assert times[-1] >= duration - 0.25 - 1e-3


@pytest.fixture(scope="module")
def one_keyframe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write(tmp_path_factory.mktemp("even") / "one.mp4", SECONDS, ONE_KEYFRAME)


def _check_roles(frames: list, duration: float) -> list[str]:
    """The provenance follows the pictures: targets grow with the times, the start is
    the first frame, the end the last and near its time; a far end is `reached`."""
    from qualify_creative.video.contact_sheet import _end_slack

    targets = [f.target_s for f in frames]
    assert targets == sorted(targets) and len(set(targets)) == len(targets)
    roles = [f.role for f in frames]
    assert set(roles) <= {"start", "fill", "end", "reached"}
    assert all(roles.count(r) <= 1 for r in ("start", "end", "reached"))
    assert "start" not in roles or roles[0] == "start"
    assert not ("end" in roles and "reached" in roles)
    for frame in frames:
        if frame.role == "end":
            assert frame is frames[-1]
            assert frame.target_s - frame.time_s <= _end_slack(duration)
        if frame.role == "reached":
            assert frame is frames[-1]
            assert frame.target_s - frame.time_s > _end_slack(duration)
    return roles


#: (video, budget) → the roles, and the last frame's time (None: not checked).
EVEN_CASES = {
    ("one_keyframe", 10.0): (["start", "fill", "fill", "fill", "fill", "end"], 9.7667),
    # the review's case: the start's seek stops mid-GOP, the fills get the keyframe at
    # 0.0 — before the start's frame: dropped, never a «fill» ahead of the «start»
    ("one_keyframe", 0.3): (["start", "end"], 9.7667),
    ("one_keyframe", 0.0): (["start"], 0.0),
    ("gop_2s", 10.0): (["start", "fill", "fill", "fill", "fill", "end"], 19.7667),
    ("gop_2s", 0.3): (["start", "fill", "fill", "fill", "fill", "end"], 19.7667),
    ("gop_2s", 0.0): (["start", "fill", "fill", "fill", "fill", "end"], 18.0),
}


@pytest.mark.parametrize(("video", "budget"), list(EVEN_CASES))
def test_even_roles_and_targets_follow_the_frames_time_order(
    request: pytest.FixtureRequest, video: str, budget: float
) -> None:
    from qualify_creative.video.contact_sheet import _evenly

    path = request.getfixturevalue(video)
    length = 10.0 if video == "one_keyframe" else 20.0
    seconds_of = _second_of if video == "one_keyframe" else _second_of_twenty
    ticks = iter(range(1_000_000))
    frames, duration = _evenly(
        path, _over(path, length), lambda: next(ticks) * 1e-3, budget_s=budget
    )
    _check_even(frames, duration, seconds_of)
    roles, last_s = EVEN_CASES[(video, budget)]
    assert _check_roles(frames, duration) == roles
    assert frames[-1].time_s == pytest.approx(last_s, abs=1e-3)
    if video == "one_keyframe" and budget == 0.3:
        assert frames[0].time_s < frames[0].target_s  # the start's frame, stopped short


def test_an_even_end_read_far_from_the_end_is_not_the_end(one_keyframe: Path) -> None:
    """One keyframe and a budget spent ~1 s into the end's seek of a 10 s video: that
    frame is kept as `reached` (its own second, after the start), never called «end»."""
    from qualify_creative.video.contact_sheet import _evenly

    ticks = iter(range(1_000_000))
    frames, duration = _evenly(
        one_keyframe, _over(one_keyframe, 10.0), lambda: next(ticks) * 1e-2, budget_s=0.3
    )
    _check_even(frames, duration, _second_of)
    assert _check_roles(frames, duration) == ["start", "reached"]
    assert frames[0].time_s == 0.0 and frames[-1].time_s < 2.0
    assert frames[-1].target_s == pytest.approx(9.75)


def test_an_unreadable_file_raises(tmp_path: Path) -> None:
    from qualify_creative.video.shots import VideoSourceError

    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(VideoSourceError):
        make_contact_sheet(bad)
