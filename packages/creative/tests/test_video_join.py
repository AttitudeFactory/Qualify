"""VE-07: the local join of a video's parts with PyAV — real encodes of tiny synthetic
parts written to disk (no network, no `ffmpeg` binary). Skipped where PyAV is missing."""

from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.compose import text_layer  # noqa: E402
from qualify_creative.video import JoinClip, JoinError, join_clips  # noqa: E402
from qualify_creative.video.join import (  # noqa: E402
    JOIN_SAMPLE_RATE,
    JOIN_VERSION,
    concat_segments,
    encode_segment,
)

SIZE = (180, 320)  # a small 9:16


def _part(
    path: Path,
    *,
    size: tuple[int, int],
    seconds: float,
    fps: int,
    audio: bool,
    codec: str = "libx264",
    pix_fmt: str = "yuv420p",
    tone_hz: float = 440.0,
    sample_rate: int = 44_100,
    layout: str = "mono",
) -> Path:
    """A part like a vendor's: a grey ramp per frame, and optionally a sine tone."""
    width, height = size
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream(codec, rate=fps)
        video.width, video.height, video.pix_fmt = width, height, pix_fmt
        sound = None
        if audio:
            sound = sink.add_stream("aac", rate=sample_rate)
            sound.layout = layout
        frames = round(seconds * fps)
        for i in range(frames):
            pixels = np.full((height, width, 3), (9 * i) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        if sound is not None:
            total = round(seconds * sample_rate)
            t = np.arange(total) / sample_rate
            wave = (0.3 * np.sin(2 * np.pi * tone_hz * t)).astype(np.float32)
            channels = 1 if layout == "mono" else 2
            for start in range(0, total, 1024):
                chunk = np.tile(wave[start : start + 1024], (channels, 1))
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout=layout)
                frame.sample_rate = sample_rate
                frame.pts = start
                frame.time_base = Fraction(1, sample_rate)
                for packet in sound.encode(frame):
                    sink.mux(packet)
            for packet in sound.encode():
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


def _joined(clips: list[JoinClip], **options: object) -> bytes:
    """Join into a fresh file beside the first part (a test's `tmp_path`) and read it
    back — the tests' only in-memory copy."""
    out = clips[0].path.with_name(f"join-{len(list(clips[0].path.parent.iterdir()))}.mp4")
    join_clips(clips, out=out, **options)
    return out.read_bytes()


def _decode(data: bytes) -> dict[str, object]:
    """Decode the whole output: frame count, last frame end, audio samples and levels."""
    with av.open(io.BytesIO(data)) as out:
        (video,) = out.streams.video
        (audio,) = out.streams.audio
        info: dict[str, object] = {
            "codec": video.codec_context.name,
            "pix_fmt": video.codec_context.pix_fmt,
            "size": (video.codec_context.width, video.codec_context.height),
            "rate": video.average_rate,
            "audio_codec": audio.codec_context.name,
            "sample_rate": audio.codec_context.sample_rate,
            "channels": audio.codec_context.channels,
        }
        frames = 0
        last_end = 0.0
        chunks = []
        for frame in out.decode(video, audio):
            if isinstance(frame, av.VideoFrame):
                frames += 1
                last_end = max(last_end, float(frame.time) + float(1 / video.average_rate))
            else:
                chunks.append(frame.to_ndarray())
        samples = np.concatenate(chunks, axis=1)
        info.update(frames=frames, video_end=last_end, samples=samples)
    return info


def _rms(samples: np.ndarray, start_s: float, end_s: float) -> float:
    window = samples[:, int(start_s * JOIN_SAMPLE_RATE) : int(end_s * JOIN_SAMPLE_RATE)]
    return float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))


@pytest.fixture
def three_parts(tmp_path: Path) -> list[JoinClip]:
    """Three parts like a real join: a 480p-ish preview with sound, one at 25 fps
    WITHOUT a soundtrack, and one of another size and aspect (stereo, 48 kHz)."""
    a = _part(tmp_path / "a.mp4", size=(240, 426), seconds=2.0, fps=24, audio=True)
    b = _part(tmp_path / "b.mp4", size=(240, 426), seconds=1.5, fps=25, audio=False)
    c = _part(
        tmp_path / "c.mp4",
        size=(320, 240),
        seconds=2.0,
        fps=24,
        audio=True,
        tone_hz=660.0,
        sample_rate=48_000,
        layout="stereo",
    )
    return [JoinClip(a, 0.5, 2.0), JoinClip(b), JoinClip(c, 0.0, 1.25)]


def test_three_parts_join_into_one_synced_video(
    three_parts: list[JoinClip], tmp_path: Path
) -> None:
    out = tmp_path / "out" / "join.mp4"
    out.parent.mkdir()
    joined = join_clips(three_parts, out=out, size=SIZE, fps=24)
    assert joined.path == out and out.is_file()
    assert (joined.fps, joined.version, joined.content_type) == (24, JOIN_VERSION, "video/mp4")
    assert not list(out.parent.glob("*.partial.mp4"))  # nothing left beside it
    data = out.read_bytes()
    expected = 1.5 + 1.5 + 1.25  # the sum of the kept intervals
    assert joined.duration_sec == pytest.approx(expected, abs=1 / 24)
    assert (joined.width, joined.height) == SIZE
    assert joined.poster is not None
    assert data.find(b"moov") < data.find(b"mdat")  # +faststart

    info = _decode(data)
    assert info["codec"] == "h264" and info["pix_fmt"] == "yuv420p"
    assert info["size"] == SIZE and info["rate"] == 24
    assert (info["audio_codec"], info["sample_rate"], info["channels"]) == ("aac", 48_000, 2)
    # decodes fully: every frame comes out, the picture lasts the sum ± one frame
    assert info["frames"] == round(expected * 24)
    assert info["video_end"] == pytest.approx(expected, abs=1 / 24)
    # sound and picture end together: within one frame after decoding the whole file
    audio_end = info["samples"].shape[1] / JOIN_SAMPLE_RATE
    assert abs(audio_end - info["video_end"]) <= 1 / 24


def test_a_part_without_sound_is_silence_in_its_own_place(
    three_parts: list[JoinClip],
) -> None:
    samples = _decode(_joined(three_parts, size=SIZE))["samples"]
    # part a: 0–1.5 s tone; part b (no track): 1.5–3.0 s silence; part c: 3.0–4.25 s tone.
    # Windows keep clear of the 40 ms fades and the AAC frame edges.
    assert _rms(samples, 0.2, 1.3) > 0.15
    assert _rms(samples, 1.7, 2.8) < 0.01
    assert _rms(samples, 3.2, 4.0) > 0.15


def test_the_tone_starts_where_its_part_starts_after_six_cuts(tmp_path: Path) -> None:
    """Risk N6: six parts alternating silent / tone; every tone onset must land where its
    part starts — a per-part drift (AAC priming, packet times) would accumulate."""
    loud = _part(tmp_path / "loud.mp4", size=(160, 284), seconds=1.0, fps=24, audio=True)
    mute = _part(tmp_path / "mute.mp4", size=(160, 284), seconds=1.0, fps=30, audio=False)
    clips = [JoinClip(mute if i % 2 == 0 else loud) for i in range(6)]
    info = _decode(_joined(clips, size=SIZE, crossfade_audio_s=0.0))
    samples = info["samples"]
    assert info["frames"] == 6 * 24
    envelope = np.abs(samples[0])
    for part in (1, 3, 5):
        onset = part * JOIN_SAMPLE_RATE  # each part lasts exactly 1 s
        loud_from = onset + int(np.argmax(envelope[onset - 2400 : onset + 2400] > 0.05)) - 2400
        # sample-accurate (measured 0–2): a slipped AAC frame (1024) would fail here
        assert abs(loud_from - onset) <= 64, (part, loud_from - onset)
        assert _rms(samples, part - 0.6, part - 0.1) < 0.01  # the silent part before it


def test_the_fade_softens_every_cut(tmp_path: Path) -> None:
    loud = _part(tmp_path / "loud.mp4", size=(160, 284), seconds=1.0, fps=24, audio=True)
    samples = _decode(_joined([JoinClip(loud)] * 2, size=SIZE))["samples"]
    # around the cut at 1 s the level dips to (almost) nothing, then recovers
    assert _rms(samples, 0.995, 1.005) < 0.05
    assert _rms(samples, 0.5, 0.9) > 0.15 and _rms(samples, 1.1, 1.5) > 0.15


def test_the_overlay_is_laid_over_the_whole_join(tmp_path: Path) -> None:
    size = (540, 960)
    layer = text_layer(size=size, cta="Pide ya", palette=("#1F2937", "#0EA5A4"))
    part = _part(tmp_path / "p.mp4", size=(240, 426), seconds=0.5, fps=24, audio=False)
    plain = _joined([JoinClip(part)] * 2, size=size)
    worded = _joined([JoinClip(part)] * 2, size=size, overlay=layer)

    def last_frame(data: bytes) -> np.ndarray:
        with av.open(io.BytesIO(data)) as out:
            *_, frame = out.decode(video=0)
            return frame.to_ndarray(format="rgb24").astype(int)

    assert np.abs(last_frame(plain) - last_frame(worded)).mean() > 1.0


def test_the_output_parameters_do_not_depend_on_the_inputs(tmp_path: Path) -> None:
    small = _part(tmp_path / "s.mp4", size=(96, 128), seconds=0.5, fps=30, audio=True)
    wide = _part(tmp_path / "w.mp4", size=(320, 180), seconds=0.5, fps=12, audio=False)
    first = _decode(_joined([JoinClip(small), JoinClip(wide)], size=SIZE, fps=30))
    second = _decode(_joined([JoinClip(wide), JoinClip(small)], size=SIZE, fps=30))
    for key in ("codec", "pix_fmt", "size", "rate", "audio_codec", "sample_rate", "channels"):
        assert first[key] == second[key], key
    assert first["frames"] == second["frames"] == 30


def test_an_hevc_10_bit_part_is_joined(tmp_path: Path) -> None:
    """Seedance 2.5's 1080p final is HEVC 10-bit (`media.py`)."""
    try:
        hevc = _part(
            tmp_path / "hevc.mp4",
            size=(192, 342),
            seconds=1.0,
            fps=24,
            audio=True,
            codec="libx265",
            pix_fmt="yuv420p10le",
        )
    except (av.error.FFmpegError, ValueError) as error:  # the local wheel has no x265
        pytest.skip(f"no 10-bit HEVC encoder here: {error}")
    with av.open(str(hevc)) as source:
        assert source.streams.video[0].codec_context.name == "hevc"
    info = _decode(_joined([JoinClip(hevc)], size=SIZE))
    assert info["pix_fmt"] == "yuv420p" and info["frames"] == 24


@pytest.mark.parametrize(
    ("clip", "message"),
    [
        (lambda p: JoinClip(p, 5.0), "ends before"),
        (lambda p: JoinClip(p, 0.0, 0.01), "shorter than one frame"),
    ],
)
def test_an_impossible_interval_is_refused(tmp_path: Path, clip, message: str) -> None:
    """...and a failed join keeps what was already at `out` and leaves no partial file."""
    part = _part(tmp_path / "p.mp4", size=(96, 128), seconds=1.0, fps=24, audio=False)
    out = tmp_path / "join.mp4"
    out.write_bytes(b"the previous join")
    with pytest.raises(JoinError, match=message):
        join_clips([JoinClip(part), clip(part)], out=out, size=SIZE)
    assert out.read_bytes() == b"the previous join"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["join.mp4", "p.mp4"]


def test_bad_arguments_are_refused(tmp_path: Path) -> None:
    with pytest.raises(JoinError):
        join_clips([], out=tmp_path / "j.mp4", size=SIZE)
    with pytest.raises(JoinError):
        join_clips([JoinClip(tmp_path / "x.mp4")], out=tmp_path / "j.mp4", size=(181, 320))
    with pytest.raises(JoinError):
        JoinClip(tmp_path / "x.mp4", 2.0, 1.0)


def test_a_missing_or_corrupt_part_is_a_join_error(tmp_path: Path) -> None:
    good = _part(tmp_path / "good.mp4", size=(96, 128), seconds=0.5, fps=24, audio=False)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"not a video" * 50)
    for bad in (tmp_path / "missing.mp4", corrupt):
        with pytest.raises(JoinError, match=rf"part 2 \({bad.name}\)") as caught:
            join_clips([JoinClip(good), JoinClip(bad)], out=tmp_path / "join.mp4", size=SIZE)
        assert caught.value.__cause__ is not None
    assert not (tmp_path / "join.mp4").exists()
    assert not list(tmp_path.glob("*.partial.mp4"))  # nothing left beside it


# --- EF-01 in the join (m-25029131): a phone part comes out upright --------------------

#: `video-rotated-<n>.mp4` (`fixtures/make_rotated_fixtures.py`): 64×36 stored, 1 s at
#: 10 fps, a display matrix of n° counter-clockwise; a red band on the stored top edge and
#: a blue one on the stored left edge. Turned 90° the red band ends on the left and the
#: blue one at the bottom; turned 270° (an iPhone held upright) red right, blue top.
FIXTURES = Path(__file__).parent / "fixtures"
TURNED_EDGES = {90: ("left", "bottom"), 270: ("right", "top")}
UPRIGHT_SIZE = (72, 128)  # the turned 36×64 at twice its size: no crop, only the scale


def _rotated_part(tmp_path: Path, rotation: int) -> Path:
    path = tmp_path / f"phone-{rotation}.mp4"
    path.write_bytes((FIXTURES / f"video-rotated-{rotation}.mp4").read_bytes())
    return path


def _edges(pixels: np.ndarray) -> dict[str, tuple[int, ...]]:
    """The colour at the middle of each edge of an RGB picture (rows × columns × 3)."""
    height, width = pixels.shape[:2]
    return {
        "left": tuple(pixels[height // 2, 2]),
        "right": tuple(pixels[height // 2, width - 3]),
        "top": tuple(pixels[2, width // 2]),
        "bottom": tuple(pixels[height - 3, width // 2]),
    }


def _assert_upright(pixels: np.ndarray, rotation: int) -> None:
    """Portrait, and turned the way a player shows it — not merely stretched to portrait."""
    height, width = pixels.shape[:2]
    assert height > width, f"{width}×{height} is lying down"
    red_edge, blue_edge = TURNED_EDGES[rotation]
    edges = _edges(pixels)
    red, blue = edges[red_edge], edges[blue_edge]
    assert red[0] > 180 and red[1] < 80 and red[2] < 80, edges
    assert blue[2] > 180 and blue[0] < 80 and blue[1] < 80, edges


def _frames(data_or_path: bytes | Path) -> tuple[tuple[int, int], list[Any]]:
    source = io.BytesIO(data_or_path) if isinstance(data_or_path, bytes) else str(data_or_path)
    with av.open(source) as out:
        stream = out.streams.video[0]
        size = (stream.codec_context.width, stream.codec_context.height)
        return size, list(out.decode(stream))


@pytest.mark.parametrize("rotation", [90, 270])
def test_a_phone_part_is_joined_upright(tmp_path: Path, rotation: int) -> None:
    phone = _rotated_part(tmp_path, rotation)
    vertical = _part(tmp_path / "vertical.mp4", size=(36, 64), seconds=0.5, fps=10, audio=False)
    out = tmp_path / "join.mp4"
    joined = join_clips([JoinClip(phone), JoinClip(vertical)], out=out, size=UPRIGHT_SIZE, fps=10)

    assert (joined.width, joined.height) == UPRIGHT_SIZE
    assert joined.frames == 15  # 1 s + 0.5 s at 10 fps
    size, frames = _frames(out)
    assert size == UPRIGHT_SIZE
    assert len(frames) == 15
    assert frames[0].rotation == 0  # the turn is in the pixels, no matrix written
    _assert_upright(frames[0].to_ndarray(format="rgb24"), rotation)
    _assert_upright(frames[9].to_ndarray(format="rgb24"), rotation)  # the part's last frame

    assert joined.poster is not None
    from PIL import Image  # noqa: PLC0415

    poster = Image.open(io.BytesIO(joined.poster))
    assert poster.size == UPRIGHT_SIZE
    _assert_upright(np.asarray(poster.convert("RGB")), rotation)


def test_a_phone_part_after_a_vertical_one_is_upright_too(tmp_path: Path) -> None:
    vertical = _part(tmp_path / "vertical.mp4", size=(36, 64), seconds=0.5, fps=10, audio=False)
    phone = _rotated_part(tmp_path, 270)
    out = tmp_path / "join.mp4"
    join_clips([JoinClip(vertical), JoinClip(phone)], out=out, size=UPRIGHT_SIZE, fps=10)
    size, frames = _frames(out)
    assert size == UPRIGHT_SIZE and len(frames) == 15
    _assert_upright(frames[5].to_ndarray(format="rgb24"), 270)


def test_a_part_turned_by_no_right_angle_is_a_join_error(tmp_path: Path) -> None:
    good = _part(tmp_path / "good.mp4", size=(36, 64), seconds=0.5, fps=10, audio=False)
    tilted = _rotated_part(tmp_path, 45)
    with pytest.raises(JoinError, match="phone-45.mp4"):
        join_clips([JoinClip(good), JoinClip(tilted)], out=tmp_path / "j.mp4", size=UPRIGHT_SIZE)
    assert not (tmp_path / "j.mp4").exists()


def test_a_phone_segment_is_upright_and_concatenates_upright(tmp_path: Path) -> None:
    """The VE-10b path: `encode_segment` shares `_part_video`, so a phone part's segment
    — and its poster — are upright, and `concat_segments` keeps them so."""
    phone = encode_segment(
        JoinClip(_rotated_part(tmp_path, 270)),
        out=tmp_path / "seg-1.mp4",
        pcm_out=tmp_path / "seg-1.pcm",
        size=UPRIGHT_SIZE,
        fps=10,
        fade_out=True,
        poster=True,
    )
    vertical = encode_segment(
        JoinClip(_part(tmp_path / "v.mp4", size=(36, 64), seconds=0.5, fps=10, audio=False)),
        out=tmp_path / "seg-2.mp4",
        pcm_out=tmp_path / "seg-2.pcm",
        size=UPRIGHT_SIZE,
        fps=10,
        fade_in=True,
    )
    assert phone.frames == 10
    size, frames = _frames(phone.path)
    assert size == UPRIGHT_SIZE
    _assert_upright(frames[0].to_ndarray(format="rgb24"), 270)
    assert phone.poster is not None
    from PIL import Image  # noqa: PLC0415

    _assert_upright(np.asarray(Image.open(io.BytesIO(phone.poster)).convert("RGB")), 270)

    joined = concat_segments([phone, vertical], out=tmp_path / "final.mp4", fps=10)
    assert (joined.width, joined.height) == UPRIGHT_SIZE
    assert joined.frames == 15
    size, frames = _frames(joined.path)
    assert size == UPRIGHT_SIZE and len(frames) == 15
    _assert_upright(frames[0].to_ndarray(format="rgb24"), 270)


def test_without_a_turn_the_join_graph_is_the_one_before_ef01(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A part with no display matrix gets exactly the graph `_part_video` built before
    EF-01 (1616ee18): the same nodes, in the same order, with the same arguments."""
    calls: list[tuple[str, object]] = []
    real_graph = av.filter.Graph

    class _SpyGraph:
        """Records what `_part_video` adds, then hands it to a real graph."""

        def __init__(self) -> None:
            self._graph = real_graph()

        def add_buffer(self, template: object = None, **kwargs: object) -> object:
            calls.append(("buffer", type(template).__name__))
            return self._graph.add_buffer(template=template, **kwargs)

        def add(self, filter: str, args: object = None, **kwargs: object) -> object:  # noqa: A002
            calls.append((filter, args))
            return self._graph.add(filter, args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._graph, name)

    part = _part(tmp_path / "plain.mp4", size=(36, 64), seconds=0.5, fps=10, audio=False)
    layer = text_layer(size=UPRIGHT_SIZE, cta="Pide ya", palette=("#1F2937", "#0EA5A4"))
    monkeypatch.setattr(av.filter, "Graph", _SpyGraph)
    join_clips([JoinClip(part)], out=tmp_path / "j.mp4", size=UPRIGHT_SIZE, fps=10, overlay=layer)
    width, height = UPRIGHT_SIZE
    overlay_buffer = calls.pop(5)
    assert overlay_buffer[0] == "buffer"
    assert str(overlay_buffer[1]).startswith(f"video_size={UPRIGHT_SIZE[0]}x{UPRIGHT_SIZE[1]}")
    assert calls == [
        ("buffer", "VideoStream"),
        ("crop", f"w='min(iw,ih*{width}/{height})':h='min(ih,iw*{height}/{width})'"),
        ("scale", f"{width}:{height}"),
        ("format", "yuv420p"),
        ("buffersink", None),
        ("overlay", "x=0:y=0:format=auto:eof_action=repeat"),
    ]
