"""EF-16 (m-25026594, ADR 50 D9): transitions between parts at the join — a fade and a
wipe of 0.3–0.8 s that OVERLAP the two parts, in the whole join (`join_clips`) and in the
segments of the 1080p final (`encode_segment` + `encode_transition` + `concat_segments`).
Real encodes of tiny synthetic parts (no network, no `ffmpeg` binary). Skipped where
PyAV is missing."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video import JoinClip, JoinError, JoinTransition, join_clips  # noqa: E402
from qualify_creative.video import join as join_module  # noqa: E402
from qualify_creative.video.join import (  # noqa: E402
    JOIN_SAMPLE_RATE,
    concat_segments,
    encode_segment,
    encode_transition,
)

SIZE = (180, 320)  # a small 9:16
FPS = 24
FADE = JoinTransition("fade", 0.5)


def _flat(
    path: Path,
    *,
    shade: int,
    seconds: float = 1.0,
    fps: int = FPS,
    tone_hz: float | None = 440.0,
) -> Path:
    """A part of ONE grey level (so a blend is measurable) and optionally a sine tone."""
    width, height = 120, 214
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        sound = None
        if tone_hz is not None:
            sound = sink.add_stream("aac", rate=JOIN_SAMPLE_RATE)
            sound.layout = "stereo"
        for i in range(round(seconds * fps)):
            pixels = np.full((height, width, 3), shade, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        if sound is not None:
            total = round(seconds * JOIN_SAMPLE_RATE)
            wave = 0.3 * np.sin(2 * np.pi * tone_hz * np.arange(total) / JOIN_SAMPLE_RATE)
            wave = wave.astype(np.float32)
            for start in range(0, total, 1024):
                chunk = np.tile(wave[start : start + 1024], (2, 1))
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
                frame.sample_rate, frame.pts = JOIN_SAMPLE_RATE, start
                frame.time_base = Fraction(1, JOIN_SAMPLE_RATE)
                for packet in sound.encode(frame):
                    sink.mux(packet)
            for packet in sound.encode():
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


def _decode(path: Path) -> dict[str, Any]:
    """Frames (their mean luma and the luma of their left and right quarters), samples."""
    with av.open(str(path)) as source:
        (video,) = source.streams.video
        (audio,) = source.streams.audio
        lumas, lefts, rights, tops, bottoms, chunks = [], [], [], [], [], []
        end = 0.0
        for frame in source.decode(video, audio):
            if isinstance(frame, av.VideoFrame):
                y = frame.to_ndarray(format="gray").astype(np.float64)
                h, w = y.shape
                lumas.append(float(y.mean()))
                lefts.append(float(y[:, : w // 4].mean()))
                rights.append(float(y[:, -w // 4 :].mean()))
                tops.append(float(y[: h // 4].mean()))
                bottoms.append(float(y[-h // 4 :].mean()))
                end = max(end, float(frame.time) + 1 / float(video.average_rate))
            else:
                chunks.append(frame.to_ndarray())
    samples = np.concatenate(chunks, axis=1)
    return {
        "frames": len(lumas),
        "luma": lumas,
        "left": lefts,
        "right": rights,
        "top": tops,
        "bottom": bottoms,
        "video_end": end,
        "samples": samples,
    }


def _rms(samples: np.ndarray, start_s: float, end_s: float) -> float:
    window = samples[:, int(start_s * JOIN_SAMPLE_RATE) : int(end_s * JOIN_SAMPLE_RATE)]
    return float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))


def _join(clips: list[JoinClip], name: str = "join.mp4", **options: Any) -> Path:
    out = clips[0].path.with_name(name)
    join_clips(clips, out=out, size=SIZE, fps=FPS, **options)
    return out


# ---------------------------------------------------------------------------
# the transition itself


@pytest.mark.parametrize("seconds", [0.29, 0.81, 2.0])
def test_a_transition_lasts_between_0_3_and_0_8_seconds(seconds: float) -> None:
    with pytest.raises(JoinError, match="0.3"):
        JoinTransition("fade", seconds)


def test_a_transition_of_an_unknown_kind_or_direction_is_refused() -> None:
    with pytest.raises(JoinError):
        JoinTransition("zoom", 0.5)  # type: ignore[arg-type]
    with pytest.raises(JoinError):
        JoinTransition("wipe", 0.5, "diagonal")  # type: ignore[arg-type]


def test_a_transition_round_trips_through_its_spec() -> None:
    wipe = JoinTransition("wipe", 0.4, "up")
    assert JoinTransition.from_spec(wipe.as_spec()) == wipe
    assert JoinTransition.from_spec(None) is None
    assert (FADE.frames(24), JoinTransition("fade", 0.3).frames(30)) == (12, 9)


def test_the_first_part_has_nothing_to_blend_with(tmp_path: Path) -> None:
    a = _flat(tmp_path / "a.mp4", shade=40)
    with pytest.raises(JoinError, match="first part"):
        _join([JoinClip(a, transition_in=FADE), JoinClip(a)])


def test_a_part_shorter_than_its_transitions_is_refused_before_encoding(
    tmp_path: Path,
) -> None:
    short = _flat(tmp_path / "s.mp4", shade=40, seconds=1.0)
    long = _flat(tmp_path / "l.mp4", shade=200, seconds=1.0)
    eight = JoinTransition("fade", 0.8)  # 19 frames in, 19 out: 38 > 24
    clips = [
        JoinClip(long),
        JoinClip(short, transition_in=eight),
        JoinClip(long, transition_in=eight),
    ]
    with pytest.raises(JoinError, match="shorter than its transitions"):
        _join(clips)
    assert not list(tmp_path.glob("*.partial.mp4"))


# ---------------------------------------------------------------------------
# Criterion 1: «Corte» is today's join, byte for byte


def test_a_cut_is_todays_join_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a transition the join takes VE-07's path, untouched (`_cut_parts`). The
    path that blends, given only cuts, writes the very same bytes — the frames come from
    the same generator and the sound from the same samples, so a cut stays a cut."""
    a = _flat(tmp_path / "a.mp4", shade=40, seconds=1.0)
    b = _flat(tmp_path / "b.mp4", shade=200, seconds=1.0, fps=25, tone_hz=None)
    c = _flat(tmp_path / "c.mp4", shade=120, seconds=1.0, tone_hz=660.0)
    clips = [JoinClip(a, 0.1), JoinClip(b), JoinClip(c, 0.0, 0.75)]
    cut = _join(clips, "cut.mp4", threads=1).read_bytes()
    assert _join(clips, "again.mp4", threads=1).read_bytes() == cut  # deterministic

    blended = join_module._blended_parts

    def blending_path(av_: Any, np_: Any, clips_: Any, *args: Any) -> None:
        blended(av_, np_, clips_, [0] * len(clips_), *args)

    monkeypatch.setattr(join_module, "_cut_parts", blending_path)
    assert _join(clips, "blended.mp4", threads=1).read_bytes() == cut


def test_a_cut_segment_is_todays_segment(tmp_path: Path) -> None:
    """The segment of a part with no transition (drops 0) is what VE-10b encoded: its
    frames, samples and bytes do not depend on the new parameters."""
    a = _flat(tmp_path / "a.mp4", shade=40, seconds=1.0)
    one = encode_segment(
        JoinClip(a),
        out=tmp_path / "1.mp4",
        pcm_out=tmp_path / "1.pcm",
        size=SIZE,
        threads=1,
        fade_out=True,
    )
    two = encode_segment(
        JoinClip(a),
        out=tmp_path / "2.mp4",
        pcm_out=tmp_path / "2.pcm",
        size=SIZE,
        threads=1,
        fade_out=True,
        drop_head=0,
        drop_tail=0,
    )
    assert (one.frames, one.samples) == (two.frames, two.samples) == (24, 48_000)
    assert one.path.read_bytes() == two.path.read_bytes()
    assert one.pcm.read_bytes() == two.pcm.read_bytes()


# ---------------------------------------------------------------------------
# Criterion 2: a 0.5 s fade → the sum of the parts − 0.5 s, the sound in sync


def test_a_fade_overlaps_the_parts_by_its_duration(tmp_path: Path) -> None:
    a = _flat(tmp_path / "a.mp4", shade=40, seconds=2.0)
    b = _flat(tmp_path / "b.mp4", shade=200, seconds=2.0, tone_hz=660.0)
    joined = join_clips(
        [JoinClip(a), JoinClip(b, transition_in=FADE)], out=tmp_path / "j.mp4", size=SIZE
    )
    expected = 2.0 + 2.0 - 0.5
    assert joined.frames == round(expected * FPS) == 84
    assert joined.duration_sec == pytest.approx(expected)
    info = _decode(joined.path)
    assert info["frames"] == 84
    assert info["video_end"] == pytest.approx(expected, abs=1 / FPS)
    # the sound lasts the picture: within one frame after decoding the whole file
    audio_end = info["samples"].shape[1] / JOIN_SAMPLE_RATE
    assert abs(audio_end - info["video_end"]) <= 1 / FPS
    # the picture: part a, then 12 frames rising from a's grey to b's, then part b
    luma = info["luma"]
    overlap = luma[36:48]  # a's frames 36–47 blended with b's frames 0–11
    assert max(luma[:30]) < 60 and min(luma[50:]) > 170
    assert all(x < y for x, y in zip(overlap, overlap[1:], strict=False))
    assert max(luma[:30]) + 3 < overlap[0] < overlap[-1] < min(luma[50:]) - 3


def test_the_sound_stays_in_sync_through_six_fades(tmp_path: Path) -> None:
    """VE-07's method (risk N6): parts alternating silent / tone, now overlapped by
    0.5 s fades. Every tone must be fully in where its part's own frames start (its
    transition over) and fully out where the next transition ends — a drift of an AAC
    frame or of a part's overlap would move the level out of these windows."""
    loud = _flat(tmp_path / "loud.mp4", shade=200, seconds=2.0, tone_hz=440.0)
    mute = _flat(tmp_path / "mute.mp4", shade=40, seconds=2.0, tone_hz=None)
    clips = [
        JoinClip(mute if i % 2 == 0 else loud, transition_in=None if i == 0 else FADE)
        for i in range(6)
    ]
    out = _join(clips, crossfade_audio_s=0.0)
    info = _decode(out)
    assert info["frames"] == 6 * 48 - 5 * 12
    samples = info["samples"]
    for part in range(6):
        start = part * 1.5  # each part starts 0.5 s before the previous one ends
        own = (start + 0.5 if part else 0.0, start + 1.5)  # no transition over it
        level = _rms(samples, own[0] + 0.05, own[1] - 0.05)
        if part % 2:
            assert level > 0.2, (part, level)
        else:
            assert level < 0.01, (part, level)
        if part:  # the crossfade: half way through it, the tone is half in (equal power)
            middle = _rms(samples, start + 0.2, start + 0.3)
            assert 0.08 < middle < 0.2, (part, middle)
    assert abs(samples.shape[1] / JOIN_SAMPLE_RATE - info["video_end"]) <= 1 / FPS


@pytest.mark.parametrize(
    ("direction", "first", "second"),
    [
        ("left", "right", "left"),
        ("right", "left", "right"),
        ("up", "bottom", "top"),
        ("down", "top", "bottom"),
    ],
)
def test_a_wipe_uncovers_the_next_part_from_one_side(
    tmp_path: Path, direction: str, first: str, second: str
) -> None:
    """`left`: the next part comes in from the right edge, its edge travelling left."""
    a = _flat(tmp_path / "a.mp4", shade=40, seconds=1.0)
    b = _flat(tmp_path / "b.mp4", shade=200, seconds=1.0)
    wipe = JoinTransition("wipe", 0.5, direction)  # type: ignore[arg-type]
    info = _decode(_join([JoinClip(a), JoinClip(b, transition_in=wipe)]))
    assert info["frames"] == 48 - 12
    early = 12 + 3  # a quarter into the wipe: only the side it starts from shows b
    assert info[first][early] > 150 and info[second][early] < 80
    late = 12 + 11  # its last overlapped frame: almost all b
    assert info[second][late] > 150 or info["luma"][late] > 150
    assert min(info["luma"][24:]) > 170 and max(info["luma"][:12]) < 60


# ---------------------------------------------------------------------------
# the 1080p final: segments with their transition, laid end to end


def test_segments_with_a_transition_make_the_same_video(tmp_path: Path) -> None:
    """The final's path: part a without its last 12 frames, the transition's 12 frames,
    part b without its first 12 — laid end to end by stream copy — lasts what
    `join_clips` lasts and blends the same way."""
    a = _flat(tmp_path / "a.mp4", shade=40, seconds=2.0)
    b = _flat(tmp_path / "b.mp4", shade=200, seconds=2.0, tone_hz=660.0)
    before, after = JoinClip(a), JoinClip(b, transition_in=FADE)
    first = encode_segment(
        before, out=tmp_path / "s0.mp4", pcm_out=tmp_path / "s0.pcm", size=SIZE, drop_tail=12
    )
    middle = encode_transition(
        before, after, out=tmp_path / "t.mp4", pcm_out=tmp_path / "t.pcm", size=SIZE
    )
    last = encode_segment(
        after, out=tmp_path / "s1.mp4", pcm_out=tmp_path / "s1.pcm", size=SIZE, drop_head=12
    )
    assert (first.frames, middle.frames, last.frames) == (36, 12, 36)
    assert (first.samples, middle.samples, last.samples) == (72_000, 24_000, 72_000)
    final = concat_segments([first, middle, last], out=tmp_path / "final.mp4")
    assert final.frames == 84 and final.duration_sec == pytest.approx(3.5)
    info = _decode(final.path)
    whole = _decode(join_clips([before, after], out=tmp_path / "j.mp4", size=SIZE).path)
    assert info["frames"] == whole["frames"] == 84
    assert np.allclose(info["luma"], whole["luma"], atol=3)
    assert info["samples"].shape == whole["samples"].shape
    assert abs(info["samples"].shape[1] / JOIN_SAMPLE_RATE - info["video_end"]) <= 1 / FPS


def test_a_transition_segment_needs_a_transition(tmp_path: Path) -> None:
    a = _flat(tmp_path / "a.mp4", shade=40)
    with pytest.raises(JoinError, match="transition"):
        encode_transition(
            JoinClip(a), JoinClip(a), out=tmp_path / "t.mp4", pcm_out=tmp_path / "t.pcm", size=SIZE
        )
    assert not list(tmp_path.glob("t.*"))


def test_the_child_carries_the_transition(tmp_path: Path) -> None:
    """The join in a child process (VE-10b) gets each part's transition through its
    spec — and a cut writes the spec it always wrote."""
    from qualify_creative.video.join_child import (
        _clip_of,
        _clip_spec,
        join_in_child,
        segment_in_child,
        transition_in_child,
    )

    cut = JoinClip(Path("a.mp4"), 0.5, 2.0)
    assert _clip_spec(cut) == ["a.mp4", 0.5, 2.0]
    faded = JoinClip(Path("b.mp4"), transition_in=JoinTransition("wipe", 0.4, "down"))
    assert _clip_of(_clip_spec(faded)) == faded and _clip_of(_clip_spec(cut)) == cut

    a = _flat(tmp_path / "a.mp4", shade=40, seconds=1.0)
    b = _flat(tmp_path / "b.mp4", shade=200, seconds=1.0)
    clips = [JoinClip(a), JoinClip(b, transition_in=FADE)]
    joined = join_in_child(clips, out=tmp_path / "j.mp4", size=SIZE)
    assert joined.frames == 36
    middle = transition_in_child(
        clips[0], clips[1], out=tmp_path / "t.mp4", pcm_out=tmp_path / "t.pcm", size=SIZE
    )
    assert (middle.frames, middle.samples) == (12, 24_000)
    rest = segment_in_child(
        clips[1], out=tmp_path / "s.mp4", pcm_out=tmp_path / "s.pcm", size=SIZE, drop_head=12
    )
    assert (rest.frames, rest.samples) == (12, 24_000)


def test_both_files_are_closed_when_a_blend_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A part that fails half way through a transition leaves no output and no file
    open (Windows would refuse to delete an open one)."""
    a = _flat(tmp_path / "a.mp4", shade=40, seconds=1.0)
    b = _flat(tmp_path / "b.mp4", shade=200, seconds=1.0)

    def broken(*_: Any) -> Any:
        raise JoinError("broken blend")

    monkeypatch.setattr(join_module, "_blend", broken)
    with pytest.raises(JoinError, match="broken blend"):
        _join([JoinClip(a), JoinClip(b, transition_in=FADE)])
    a.unlink()
    b.unlink()
    assert not list(tmp_path.glob("*.mp4"))


def test_the_final_transition_opens_one_decoder_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 1080p 10-bit decoder is ~70 MiB: the transition's child spools the part before's
    overlapped frames and closes it before the part after is opened — and leaves no
    spool file behind."""
    a = _flat(tmp_path / "a.mp4", shade=40, seconds=1.0)
    b = _flat(tmp_path / "b.mp4", shade=200, seconds=1.0)
    events: list[str] = []
    real = join_module._part_video_frames

    def watched(av_: Any, clip: JoinClip, *args: Any) -> Any:
        events.append(f"open {clip.path.name}")
        try:
            yield from real(av_, clip, *args)
        finally:
            events.append(f"close {clip.path.name}")

    monkeypatch.setattr(join_module, "_part_video_frames", watched)
    made = encode_transition(
        JoinClip(a),
        JoinClip(b, transition_in=FADE),
        out=tmp_path / "t.mp4",
        pcm_out=tmp_path / "t.pcm",
        size=SIZE,
    )
    assert made.frames == 12
    assert events == ["open a.mp4", "close a.mp4", "open b.mp4", "close b.mp4"]
    assert not list(tmp_path.glob("*.yuv")) and not list(tmp_path.glob("*.partial*"))
