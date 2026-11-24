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


def _write(path: Path, shots: list[tuple[tuple[int, int, int], float]]) -> Path:
    """An H.264 MP4: per shot, a flat colour for that many seconds, with the magenta
    layer band over every frame."""
    with av.open(str(path), "w") as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = SIZE[0], SIZE[1], "yuv420p"
        stream.options = {"preset": "ultrafast", "crf": "18"}
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
    assert params["version"] == "contact-sheet-2"
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
    kept and the keyframes after it."""
    ticks = iter(float(n) for n in range(10_000))
    sheet = make_contact_sheet(three_shots, budget_s=2.5, clock=lambda: next(ticks))
    assert sheet.cuts == "even" and sheet.params()["cuts"] == "even"
    assert len(sheet.frames) == SHEET_FRAMES
    assert all(f.role in ("start", "fill", "end") for f in sheet.frames)
    assert abs(sheet.duration_s - 6.0) < 0.1
    for frame in sheet.frames:
        band = _rgb(frame.jpeg)[LAYER_ROWS[0] + 4 : LAYER_ROWS[1] - 4]
        assert np.abs(band - np.array(LAYER)).mean() < 20


def test_an_unreadable_file_raises(tmp_path: Path) -> None:
    from qualify_creative.video.shots import VideoSourceError

    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(VideoSourceError):
        make_contact_sheet(bad)
