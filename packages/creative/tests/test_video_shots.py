"""VE-02: the shot detector, the frame sampler and the window cut, over synthetic MP4s
written with PyAV inside the test (cuts at known frames, with and without a soundtrack).
No network, no `ffmpeg` binary. Skipped where PyAV is not installed."""

from __future__ import annotations

import functools
import io
import tracemalloc
from collections.abc import Sequence
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video.cut import (  # noqa: E402
    CutWindow,
    WindowUnavailable,
    cut_window,
    plan_window,
)
from qualify_creative.video.shots import (  # noqa: E402
    SamplingPlan,
    ShotSpan,
    detect_shots,
    sample_frames,
)

FPS = 30
SIZE = (108, 192)  # 9:16, small: the encode stays fast


def _shot_picture(shot: int, index: int, size: tuple[int, int]) -> np.ndarray:
    """A textured, slowly moving picture, different per shot: diagonal stripes whose
    colour, angle and width depend on the shot, panning a pixel per frame (motion inside a
    shot must not read as a cut), plus a little noise."""
    rng = np.random.default_rng(shot * 10_000 + index)
    picture = np.roll(_shot_base(shot, size), index, axis=1).astype(np.float32)
    picture += rng.normal(0, 3, picture.shape)
    return np.clip(picture, 0, 255).astype(np.uint8)


@functools.cache
def _shot_base(shot: int, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    y, x = np.mgrid[0:height, 0:width]
    # stripes scale with the frame: the detector reads a 64-px-wide thumbnail
    period = (16 + 8 * (shot % 4)) * width / SIZE[0]
    angle = (shot * 37) % 90 + 5
    wave = (x * np.cos(np.radians(angle)) + y * np.sin(np.radians(angle))) / period
    stripes = (0.5 + 0.5 * np.sin(wave * 2 * np.pi)).astype(np.float32)[..., None]
    base = np.array([(53 * shot) % 200 + 30, (97 * shot) % 200 + 30, (151 * shot) % 200 + 30])
    return (stripes * base + (1 - stripes) * (255 - base)).astype(np.uint8)


def _write(
    path: Path,
    frames: Sequence[tuple[int, float | None]],
    *,
    audio: bool = False,
    size: tuple[int, int] = SIZE,
    repeat: int = 1,
    container: str = "mp4",
    x264: dict[str, str] | None = None,
    rotation: int = 0,
) -> Path:
    """An H.264 MP4 at `FPS`: per frame, `(shot, None)` or `(shot, blend)` — a dissolve
    from `shot` to `shot + 1` at `blend` (0-1). With `audio`, an AAC tone over it. With
    `repeat` = 2, every picture is shown twice (a 15 fps source stored at 30). `container`
    and `x264` pick the file (an MPEG-TS with B-frames); `rotation` writes a phone's
    display matrix (degrees counter-clockwise)."""
    with av.open(str(path), "w", format=container) as sink:
        video = sink.add_stream("libx264", rate=FPS)
        video.width, video.height, video.pix_fmt = size[0], size[1], "yuv420p"
        video.options = x264 or {"preset": "ultrafast", "crf": "23"}
        if rotation:
            video.set_display_rotation(rotation)
        tone = sink.add_stream("aac", rate=44100) if audio else None
        if tone is not None:
            tone.layout = "mono"
        for index, (shot, blend) in enumerate(frames):
            picture = _shot_picture(shot, index // repeat, size)
            if blend is not None:
                after = _shot_picture(shot + 1, index // repeat, size)
                picture = (picture * (1 - blend) + after * blend).astype(np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(picture, format="rgb24")):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
        if tone is not None:
            samples, total = 1024, len(frames) * 44100 // FPS
            for start in range(0, total - samples, samples):
                t = (np.arange(samples) + start) / 44100
                wave = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)[None, :]
                chunk = av.AudioFrame.from_ndarray(wave, format="fltp", layout="mono")
                chunk.sample_rate, chunk.pts = 44100, start
                for packet in tone.encode(chunk):
                    sink.mux(packet)
            for packet in tone.encode():
                sink.mux(packet)
    return path


def _hard_cuts(cuts_at: Sequence[int], total: int) -> list[tuple[int, None]]:
    """`total` frames, a new shot starting at each frame of `cuts_at`."""
    shot, frames = 0, []
    for index in range(total):
        if index in cuts_at:
            shot += 1
        frames.append((shot, None))
    return frames


def _frames_of(path: Path) -> int:
    with av.open(str(path)) as source:
        return sum(1 for _ in source.decode(video=0))


# --- detect_shots --------------------------------------------------------------------


@pytest.mark.parametrize("audio", [False, True])
def test_three_known_cuts_are_found_within_a_frame(tmp_path: Path, audio: bool) -> None:
    cuts_at = (45, 100, 171)  # 1.5 s, 3.333 s, 5.7 s
    clip = _write(tmp_path / "cuts.mp4", _hard_cuts(cuts_at, 240), audio=audio)
    spans = detect_shots(clip)
    assert len(spans) == 4
    for span, frame in zip(spans[1:], cuts_at, strict=True):
        assert span.start_s == pytest.approx(frame / FPS, abs=1 / FPS + 1e-6)
        assert span.cut_score > 0
    assert spans[0].start_s == 0
    assert spans[-1].end_s == pytest.approx(240 / FPS, abs=1 / FPS)
    # contiguous, in order, the index is the position
    for previous, span in zip(spans, spans[1:], strict=False):
        assert span.start_s == previous.end_s and span.index == previous.index + 1


def test_a_slow_dissolve_is_not_a_cut(tmp_path: Path) -> None:
    # 1 s of shot 0, a 2 s dissolve into shot 1, then 1 s of shot 1, then a hard cut
    frames: list[tuple[int, float | None]] = [(0, None)] * FPS
    frames += [(0, (k + 1) / (2 * FPS)) for k in range(2 * FPS)]
    frames += [(1, None)] * FPS + [(2, None)] * FPS
    spans = detect_shots(_write(tmp_path / "fade.mp4", frames))
    assert [round(span.start_s * FPS) for span in spans] == [0, 4 * FPS]


def test_repeated_frames_do_not_make_every_real_frame_a_cut(tmp_path: Path) -> None:
    # half the differences are ~0 (each picture twice): they stay out of the baseline
    clip = _write(tmp_path / "15fps.mp4", _hard_cuts((60, 120), 180), repeat=2)
    assert [round(span.start_s * FPS) for span in detect_shots(clip)] == [0, 60, 120]


def test_reading_stops_at_max_seconds(tmp_path: Path) -> None:
    clip = _write(tmp_path / "long.mp4", _hard_cuts((30, 150), 180))
    spans = detect_shots(clip, max_seconds=3.0)
    assert len(spans) == 2  # the cut at 5 s lies past the reading
    assert spans[-1].end_s == pytest.approx(3.0, abs=1 / FPS)


@pytest.mark.slow
def test_detection_memory_does_not_grow_with_the_length(tmp_path: Path) -> None:
    """Streaming: the peak of Python/numpy allocations for 20 s is close to the one for
    4 s — a detector that kept every decoded frame would hold 5× more."""
    short = _write(tmp_path / "short.mp4", _hard_cuts((60,), 4 * FPS))
    long_ = _write(tmp_path / "long.mp4", _hard_cuts((60, 300), 20 * FPS))

    def peak(path: Path) -> int:
        tracemalloc.start()
        detect_shots(path)
        _, top = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return top

    peak(short)  # warm imports and caches out of the measure
    assert peak(long_) < 1.5 * peak(short) + 256 * 1024


# --- sample_frames -------------------------------------------------------------------


def test_two_frames_per_long_shot_one_per_short_plus_anchors(tmp_path: Path) -> None:
    # shots: 0-1.5 s, 1.5-2.0 s (short), 2.0-4.0 s. Shot 0's narrow stripes pan 1 px per
    # frame, a pixel difference large enough to hide its cut from the pixel signal alone —
    # the tone histogram finds it
    clip = _write(tmp_path / "s.mp4", _hard_cuts((45, 60), 120), audio=True)
    spans = detect_shots(clip)
    assert len(spans) == 3
    frames = sample_frames(clip, spans)
    shots = [f for f in frames if f.role == "shot"]
    anchors = [f for f in frames if f.role == "anchor"]
    assert [f.shot for f in shots] == [0, 0, 1, 2, 2]
    assert [f.target_s for f in anchors] == [0.0, 1.0, 3.0]
    assert [f.shot for f in anchors] == [0, 0, 2]
    assert shots[0].target_s == pytest.approx(0.15 * 1.5, abs=1e-3)
    assert shots[2].target_s == pytest.approx(1.75, abs=1 / FPS)
    for frame in frames:
        # the frame that answered: the first at or after the time asked, within a frame
        assert 0 <= frame.time_s - frame.target_s <= 1 / FPS + 1e-6
        assert (frame.width, frame.height) == SIZE  # a small source is never upscaled
        assert frame.jpeg[:2] == b"\xff\xd8"
    times = [f.time_s for f in frames]
    assert times == sorted(times)


def test_frames_fit_the_720x1280_box(tmp_path: Path) -> None:
    clip = _write(tmp_path / "big.mp4", _hard_cuts((), 3), size=(1080, 1920))
    (frame, *_) = sample_frames(clip, detect_shots(clip))
    assert (frame.width, frame.height) == (720, 1280)
    with av.open(io.BytesIO(frame.jpeg)) as image:
        decoded = next(image.decode(video=0))
        assert (decoded.width, decoded.height) == (720, 1280)


def test_the_cap_of_32_holds_and_falls_back_to_one_per_shot() -> None:
    from qualify_creative.video.shots import _targets

    plan = SamplingPlan()
    # 20 shots of 2 s: 40 + 3 > 32 → one per shot + the anchors = 23
    twenty = [ShotSpan(i, 2.0 * i, 2.0 * (i + 1)) for i in range(20)]
    targets = _targets(twenty, plan)
    assert len(targets) == 23
    assert sum(1 for t in targets if t[1] == "shot") == 20
    # 50 shots of 1 s: even one per shot is over; the anchors stay, the shots thin out
    fifty = [ShotSpan(i, 1.0 * i, 1.0 * (i + 1)) for i in range(50)]
    targets = _targets(fifty, plan)
    assert len(targets) == 32
    shot_ids = [t[2] for t in targets if t[1] == "shot"]
    assert shot_ids[0] == 0 and shot_ids[-1] == 49 and len(set(shot_ids)) == 29
    # 10 shots: the full plan fits
    ten = [ShotSpan(i, 2.0 * i, 2.0 * (i + 1)) for i in range(10)]
    assert len(_targets(ten, plan)) == 23


# --- cut_window ----------------------------------------------------------------------


def test_plan_window_rounds_up_to_whole_seconds_and_extends_to_the_neighbour() -> None:
    assert plan_window(2.0, 3.5, 10.0) == (2.0, 6.0)
    assert plan_window(2.0, 3.5, 10.0, toward="previous") == (0.0, 4.0)
    assert plan_window(5.0, 9.5, 10.0, toward="previous") == (4.5, 9.5)
    assert plan_window(1.2, 6.3, 10.0) == (1.2, 7.2)  # 5.1 s → 6 s
    assert plan_window(8.5, 9.8, 10.0) == (6.0, 10.0)  # slid back inside the source
    assert plan_window(0.0, 4.0001, 10.0) == (0.0, 4.0)
    with pytest.raises(WindowUnavailable) as short:
        plan_window(0.0, 2.0, 3.0)
    assert short.value.reason == "source_too_short"
    with pytest.raises(WindowUnavailable) as long_:
        plan_window(0.0, 10.5, 20.0)
    assert long_.value.reason == "too_long"


@pytest.mark.parametrize("audio", [False, True])
def test_a_short_shot_becomes_a_4_second_window_that_contains_it(
    tmp_path: Path, audio: bool
) -> None:
    clip = _write(tmp_path / "w.mp4", _hard_cuts((60, 105, 180), 300), audio=audio)
    spans = detect_shots(clip)
    shot = spans[1]  # 2.0-3.5 s: 1.5 s
    assert shot.seconds == pytest.approx(1.5, abs=1 / FPS)
    window = cut_window(clip, shot.start_s, shot.end_s, out=tmp_path / "part.mp4")
    assert isinstance(window, CutWindow)
    assert window.seconds == 4
    assert window.start_s <= shot.start_s and window.end_s >= shot.end_s - 1e-6
    assert window.duration_sec == pytest.approx(4.0, abs=1 / FPS)
    data = Path(window.path).read_bytes()
    assert data.find(b"moov") < data.find(b"mdat")  # +faststart
    with av.open(window.path) as out:
        (video,) = out.streams.video
        assert not out.streams.audio
        assert (video.codec_context.name, video.format.name) == ("h264", "yuv420p")
        assert (video.width, video.height) == SIZE
        assert out.duration / 1_000_000 == pytest.approx(4.0, abs=1 / FPS + 0.01)
    assert _frames_of(Path(window.path)) == pytest.approx(4 * FPS, abs=1)
    # the cut it contains lands where the source had it, relative to the window
    inner = detect_shots(window.path)
    assert inner[1].start_s == pytest.approx(105 / FPS - window.start_s, abs=1 / FPS + 1e-6)


def test_a_window_near_the_end_is_slid_back(tmp_path: Path) -> None:
    clip = _write(tmp_path / "e.mp4", _hard_cuts((150, 165), 180))
    window = cut_window(clip, 5.0, 5.5, out=tmp_path / "end.mp4")
    assert (window.start_s, window.end_s) == (2.0, 6.0)
    assert window.frames == pytest.approx(4 * FPS, abs=1)


def test_a_source_shorter_than_a_part_is_refused(tmp_path: Path) -> None:
    clip = _write(tmp_path / "tiny.mp4", _hard_cuts((30,), 90))
    with pytest.raises(WindowUnavailable) as refused:
        cut_window(clip, 1.0, 2.0, out=tmp_path / "x.mp4")
    assert refused.value.reason == "source_too_short"
    assert not (tmp_path / "x.mp4").exists()


# --- the source's timeline, seeks, rotation, failures --------------------------------

#: An MPEG-TS with B-frames and a keyframe every half second: it starts at ~1.4 s (not 0)
#: and its seeks can land after the time asked.
#: A keyframe every half second, so a seek can land on one after the time asked.
GOP_X264 = {"preset": "ultrafast", "g": "15", "crf": "23"}
TS_X264 = {"preset": "veryfast", "bf": "3", "g": "15", "crf": "23"}


def test_an_mpeg_ts_with_b_frames_counts_from_its_first_frame_and_cuts_right(
    tmp_path: Path,
) -> None:
    clip = _write(tmp_path / "b.ts", _hard_cuts((45, 90), 180), container="mpegts", x264=TS_X264)
    with av.open(str(clip)) as source:
        assert source.streams.video[0].start_time > 0  # a non-zero origin
    spans = detect_shots(clip)
    assert [round(span.start_s * FPS) for span in spans] == [0, 45, 90]
    assert spans[-1].end_s == pytest.approx(6.0, abs=1 / FPS)
    window = cut_window(clip, 1.5, 3.0, out=tmp_path / "part.mp4")
    assert (window.start_s, window.end_s, window.seconds) == (1.5, 5.5, 4)
    assert window.frames == pytest.approx(4 * FPS, abs=1)
    inner = detect_shots(window.path)
    assert inner[1].start_s == pytest.approx(1.5, abs=1 / FPS + 1e-6)  # the cut at 3.0 s
    frames = sample_frames(clip, spans)
    assert all(0 <= f.time_s - f.target_s <= 1 / FPS + 1e-6 for f in frames)


def test_a_seek_that_lands_late_is_retried_further_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.video import cut

    clip = _write(tmp_path / "late.mp4", _hard_cuts((60, 105, 180), 240), x264=GOP_X264)
    real_seek, calls = cut._seek, []

    def lands_late_once(container: object, stream: object, seconds: float | None) -> None:
        calls.append(seconds)
        # the first seek goes 1 s past what was asked, as a B-frame TS can
        real_seek(
            container,
            stream,
            None if seconds is None else seconds + (1.0 if len(calls) == 1 else 0),
        )

    monkeypatch.setattr(cut, "_seek", lands_late_once)
    window = cut_window(clip, 3.5, 4.0, out=tmp_path / "w.mp4")
    assert len(calls) == 2  # re-sought 2 s earlier
    assert window.start_s == 3.5 and window.frames == pytest.approx(4 * FPS, abs=1)
    assert detect_shots(window.path)[1].start_s == pytest.approx(
        6.0 - 3.5, abs=1 / FPS
    )  # the cut at 6 s


def test_a_seek_that_never_reaches_the_window_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.video import cut

    clip = _write(tmp_path / "late.mp4", _hard_cuts((60,), 240), x264=GOP_X264)
    real_seek = cut._seek
    monkeypatch.setattr(cut, "_seek", lambda c, s, seconds: real_seek(c, s, (seconds or 0.0) + 3.0))
    with pytest.raises(WindowUnavailable) as refused:
        cut_window(clip, 2.0, 3.0, out=tmp_path / "w.mp4")
    assert refused.value.reason == "seek_failed"
    assert list(tmp_path.iterdir()) == [clip]  # nothing half-written next to `out`


def test_no_frame_in_the_window_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.video import _source, cut

    clip = _write(tmp_path / "short.mp4", _hard_cuts((), 150))
    real_probe = _source.probe

    def longer(container: object, stream: object) -> _source.Timeline:
        timeline = real_probe(container, stream)
        return _source.Timeline(timeline.origin_s, 20.0, timeline.rate, timeline.rotation)

    monkeypatch.setattr(cut, "probe", longer)  # the header says 20 s, the frames end at 5
    with pytest.raises(WindowUnavailable) as refused:
        cut_window(clip, 12.0, 13.0, out=tmp_path / "w.mp4")
    assert refused.value.reason == "source_too_short"
    assert list(tmp_path.iterdir()) == [clip]


def test_a_rotated_phone_clip_is_sampled_and_cut_upright(tmp_path: Path) -> None:
    # stored 192x108 (landscape) with a 90-degree display matrix: shown 108x192
    clip = _write(tmp_path / "phone.mp4", _hard_cuts((60,), 150), size=(192, 108), rotation=90)
    (frame, *_) = sample_frames(clip, detect_shots(clip))
    assert (frame.width, frame.height) == (108, 192)
    from PIL import Image

    upright = np.asarray(Image.open(io.BytesIO(frame.jpeg)))
    stored = _shot_picture(0, 0, (192, 108))
    turned = np.rot90(stored, k=1)  # counter-clockwise, as the player shows it
    assert np.abs(upright.astype(int) - turned.astype(int)).mean() < 12
    window = cut_window(clip, 0.0, 1.0, out=tmp_path / "w.mp4")
    assert (window.width, window.height) == (108, 192)
    with av.open(window.path) as out:
        decoded = next(out.decode(video=0))
        assert (decoded.width, decoded.height) == (108, 192)
        assert not decoded.rotation  # the turn is in the pixels, no tag left


def test_a_display_rotation_that_is_not_a_right_angle_is_refused() -> None:
    from types import SimpleNamespace

    from qualify_creative.video._source import VideoSourceError, frame_rotation

    assert frame_rotation(SimpleNamespace(rotation=-90.0)) == 270
    assert frame_rotation(SimpleNamespace(rotation=180)) == 180
    with pytest.raises(VideoSourceError) as refused:
        frame_rotation(SimpleNamespace(rotation=45.0))
    assert refused.value.reason == "rotation_unsupported"


def test_a_corrupt_file_is_a_typed_error(tmp_path: Path) -> None:
    from qualify_creative.video import VideoSourceError

    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 40)
    for call in (
        lambda: detect_shots(junk),
        lambda: sample_frames(junk, [ShotSpan(0, 0.0, 1.0)]),
        lambda: cut_window(junk, 0.0, 1.0, out=tmp_path / "w.mp4"),
    ):
        with pytest.raises(VideoSourceError) as refused:
            call()
        assert refused.value.reason == "unreadable"
        assert isinstance(refused.value.__cause__, av.error.FFmpegError)


def test_a_rotation_within_half_a_degree_of_a_right_angle_is_that_angle() -> None:
    from types import SimpleNamespace

    from qualify_creative.video._source import VideoSourceError, frame_rotation

    assert frame_rotation(SimpleNamespace(rotation=89.8)) == 90
    assert frame_rotation(SimpleNamespace(rotation=-179.7)) == 180
    with pytest.raises(VideoSourceError):
        frame_rotation(SimpleNamespace(rotation=89.0))


def test_an_audio_only_file_has_no_video_stream(tmp_path: Path) -> None:
    from qualify_creative.video import NoVideoStream

    sound = tmp_path / "sound.m4a"
    with av.open(str(sound), "w", format="mp4") as sink:
        tone = sink.add_stream("aac", rate=44100)
        tone.layout = "mono"
        for start in range(0, 44100, 1024):
            chunk = av.AudioFrame.from_ndarray(
                np.zeros((1, 1024), np.float32), format="fltp", layout="mono"
            )
            chunk.sample_rate, chunk.pts = 44100, start
            for packet in tone.encode(chunk):
                sink.mux(packet)
        for packet in tone.encode():
            sink.mux(packet)
    for call in (
        lambda: detect_shots(sound),
        lambda: sample_frames(sound, [ShotSpan(0, 0.0, 1.0)]),
        lambda: cut_window(sound, 0.0, 1.0, out=tmp_path / "w.mp4"),
    ):
        with pytest.raises(NoVideoStream) as refused:
            call()
        assert refused.value.reason == "no_video"


def test_a_failed_write_is_not_blamed_on_the_source(tmp_path: Path) -> None:
    from qualify_creative.video import VideoSourceError

    clip = _write(tmp_path / "ok.mp4", _hard_cuts((), 150))
    with pytest.raises(VideoSourceError) as refused:
        cut_window(clip, 0.0, 1.0, out=tmp_path / "missing-folder" / "w.mp4")
    assert refused.value.reason == "encode_failed"
