"""VE-07: the local join of a video's parts with PyAV — real encodes of tiny synthetic
parts written to disk (no network, no `ffmpeg` binary). Skipped where PyAV is missing."""

from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.compose import text_layer  # noqa: E402
from qualify_creative.video import JoinClip, JoinError, join_clips  # noqa: E402
from qualify_creative.video.join import JOIN_SAMPLE_RATE, JOIN_VERSION  # noqa: E402

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
