"""m-25049580: the local assembly keeps the original sound of its ×1 stretches — `prepare`'s
sidecar, `speed`'s single AAC track, and the overlays that copy it. Real encodes of tiny
synthetic clips with PyAV (no network, no `ffmpeg` binary): a barcoded picture (the source
frame's index) and short clicks at known instants, so the sound's place is checked against
the frame that shows the same instant — within one frame (33 ms) — with tolerances, never
hashes (m-25029128)."""

from __future__ import annotations

import io
import wave
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video import sound  # noqa: E402
from qualify_creative.video.prepare import (  # noqa: E402
    PREPARE_VERSION,
    PrepareSegment,
    apply_prepare,
    plan_prepare,
    read_source,
)
from qualify_creative.video.speed import (  # noqa: E402
    CODE_AUDIO,
    SPEED_VERSION,
    SpeedError,
    SpeedSegment,
    plan_speed,
    render_speed,
)

SIZE = (180, 320)
FPS = 30
BITS = 8
ONE_FRAME = 1 / FPS
SR = sound.SAMPLE_RATE


# ---------------------------------------------------------------------------
# synthetic clips


def _barcode(index: int) -> Any:
    width, height = SIZE
    pixels = np.full((height, width, 3), 128, dtype=np.uint8)
    stripe = width // BITS
    for bit in range(BITS):
        pixels[: height // 2, bit * stripe : (bit + 1) * stripe] = 255 if (index >> bit) & 1 else 0
    return pixels


def _read_barcode(frame: Any) -> int:
    luma = frame.to_ndarray(format="gray")
    height, width = luma.shape
    stripe = width // BITS
    index = 0
    for bit in range(BITS):
        cell = luma[
            height // 8 : height // 2 - height // 8, bit * stripe + 3 : (bit + 1) * stripe - 3
        ]
        if cell.mean() > 128:
            index |= 1 << bit
    return index


def _clip(
    path: Path,
    *,
    seconds: float,
    audio: str | None = "mono",
    clicks: tuple[float, ...] = (),
    tone: float = 0.0,
    audio_start_s: float = 0.0,
    audio_seconds: float | None = None,
    rate: int = 44_100,
) -> Path:
    """`seconds` of barcoded 30 fps frames (frame i shows i) and, unless `audio` is None, a
    track (`mono`/`stereo`) from `audio_start_s`: `tone` amplitude of 440 Hz under 20 ms
    bursts of 2 kHz at amplitude 0.8 at each of `clicks` (seconds of the picture)."""
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=FPS)
        video.width, video.height, video.pix_fmt = *SIZE, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "20"}
        track = None
        if audio is not None:
            track = sink.add_stream("aac", rate=rate)
            track.layout = audio
        for i in range(round(seconds * FPS)):
            frame = av.VideoFrame.from_ndarray(_barcode(i), format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, FPS)
            for packet in video.encode(frame):
                sink.mux(packet)
        if track is not None:
            length = audio_seconds if audio_seconds is not None else seconds - audio_start_s
            total = round(length * rate)
            t = np.arange(total) / rate + audio_start_s  # the picture's clock
            wave_ = (tone * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
            for at in clicks:
                burst = (t >= at) & (t < at + 0.02)
                wave_[burst] = (0.8 * np.sin(2 * np.pi * 2000 * (t[burst] - at))).astype(np.float32)
            channels = 1 if audio == "mono" else 2
            first = round(audio_start_s * rate)
            for start in range(0, total, 1024):
                chunk = np.tile(wave_[start : start + 1024], (channels, 1))
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout=audio)
                frame.sample_rate = rate
                frame.pts = first + start
                frame.time_base = Fraction(1, rate)
                for packet in track.encode(frame):
                    sink.mux(packet)
            for packet in track.encode():
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


def _prepared(source: Path, out: Path, start: float, end: float, *, keep: bool = True) -> Any:
    info = read_source(source)
    plan = plan_prepare(
        info.width,
        info.height,
        info.rotation,
        PrepareSegment(key=source.name, start_s=start, end_s=end),
        info.duration_s,
    )
    return apply_prepare(source, plan, out, keep_audio=keep)


def _wav(path: str | Path) -> Any:
    with wave.open(str(path), "rb") as source:
        assert (source.getnchannels(), source.getsampwidth(), source.getframerate()) == (2, 2, SR)
        raw = source.readframes(source.getnframes())
    return np.frombuffer(raw, dtype="<i2").reshape(-1, 2).T.astype(np.float32) / 32768.0


def _decode(path: Path) -> dict[str, Any]:
    """The whole output: its barcodes in order, its one audio track and that track's
    samples (48 kHz stereo float), the frame count."""
    with av.open(str(path)) as out:
        assert len(out.streams.video) == 1
        audio = list(out.streams.audio)
        info: dict[str, Any] = {"audio_streams": len(audio)}
        barcodes = [_read_barcode(f) for f in out.decode(out.streams.video[0])]
        info["barcodes"] = barcodes
        if audio:
            (track,) = audio
            context = track.codec_context
            info.update(
                codec=context.name,
                sample_rate=context.sample_rate,
                channels=context.channels,
                bit_rate=track.bit_rate or context.bit_rate,
            )
    if audio:
        with av.open(str(path)) as out:
            chunks = [f.to_ndarray() for f in out.decode(out.streams.audio[0])]
        info["samples"] = np.concatenate(chunks, axis=1)
    return info


def _onsets(samples: Any, *, after_s: float = 0.0, threshold: float = 0.3) -> list[float]:
    """The start (seconds) of every burst louder than `threshold` after `after_s`, bursts
    at least 0.2 s apart."""
    envelope = np.abs(samples).max(axis=0)
    loud = np.flatnonzero(envelope > threshold)
    found: list[float] = []
    for index in loud:
        at = index / SR
        if at < after_s:
            continue
        if not found or at - found[-1] > 0.2:
            found.append(at)
    return found


def _rms(samples: Any, start_s: float, end_s: float) -> float:
    window = samples[:, int(start_s * SR) : int(end_s * SR)]
    return float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))


# ---------------------------------------------------------------------------
# the sound helpers


def test_faded_ramps_only_the_edges_whatever_the_chunking() -> None:
    whole = np.ones((2, 1000), dtype=np.float32)
    once = sound.faded(whole, 0, 1000, 100, 50)
    parts = np.concatenate(
        [
            sound.faded(whole[:, a:b], a, 1000, 100, 50)
            for a, b in ((0, 37), (37, 960), (960, 1000))
        ],
        axis=1,
    )
    assert np.allclose(once, parts)
    assert once[0, 0] == 0.0 and once[0, 99] == pytest.approx(1.0)
    assert once[0, 500] == 1.0 and once[0, 999] == 0.0
    assert sound.faded(whole[:, 200:300], 200, 1000, 100, 50) is not None
    assert whole.min() == 1.0  # never written in place


def test_silence_and_a_wav_read_past_its_end_give_exactly_the_samples(tmp_path: Path) -> None:
    assert sum(chunk.shape[1] for chunk in sound.silence(SR * 2 + 7)) == SR * 2 + 7
    path = tmp_path / "s.wav"
    with wave.open(str(path), "wb") as sink:
        sink.setnchannels(2)
        sink.setsampwidth(2)
        sink.setframerate(SR)
        sink.writeframes((np.ones((1000, 2)) * 16384).astype("<i2").tobytes())
    chunks = list(sound.read_wav_window(path, start=900, samples=300))
    values = np.concatenate(chunks, axis=1)
    assert values.shape == (2, 300)
    assert np.allclose(values[:, :100], 0.5) and not values[:, 100:].any()
    assert not np.concatenate(list(sound.read_wav_window(path, start=5000, samples=10)), 1).any()


# ---------------------------------------------------------------------------
# prepare: the sidecar


def test_prepare_keeps_the_stretchs_sound_on_the_pictures_clock(tmp_path: Path) -> None:
    """Criterion 1 at the first step: the stretch [1.0, 4.0) of a clip with a click at 2.5 s
    (frame 75) gives a sidecar of exactly the prepared video's length, the click at 1.5 s —
    where the prepared video shows frame 75."""
    source = _clip(tmp_path / "a.mp4", seconds=6.0, clicks=(2.5,))
    made = _prepared(source, tmp_path / "prepared.mp4", 1.0, 4.0)
    assert PREPARE_VERSION == "prepare-v2"
    assert made.audio_path == str(tmp_path / "prepared.wav")
    samples = _wav(made.audio_path)
    assert samples.shape[1] == round(made.frames * SR / FPS) == 3 * SR
    (click,) = _onsets(samples)
    with av.open(made.path) as prepared:
        codes = [_read_barcode(f) for f in prepared.decode(prepared.streams.video[0])]
        assert not prepared.streams.audio  # the MP4 itself stays video only
    shown = codes.index(75) / FPS
    assert abs(click - 1.5) <= ONE_FRAME
    assert abs(click - shown) <= ONE_FRAME
    # mono copied to both sides at its own level
    assert np.allclose(samples[0], samples[1], atol=1e-3)


def test_without_keep_audio_prepare_writes_no_sidecar(tmp_path: Path) -> None:
    source = _clip(tmp_path / "a.mp4", seconds=4.0, clicks=(1.0,))
    made = _prepared(source, tmp_path / "prepared.mp4", 0.0, 3.0, keep=False)
    assert made.audio_path is None
    assert not (tmp_path / "prepared.wav").exists()


def test_a_source_without_sound_prepares_without_a_sidecar(tmp_path: Path) -> None:
    """Criterion 3 at the first step: no sound track is no sidecar, never a failure."""
    source = _clip(tmp_path / "mute.mp4", seconds=4.0, audio=None)
    made = _prepared(source, tmp_path / "prepared.mp4", 0.0, 3.0)
    assert made.audio_path is None and made.frames == 90
    assert not (tmp_path / "prepared.wav").exists()


def test_a_sound_that_starts_late_and_ends_early_is_padded_with_silence(tmp_path: Path) -> None:
    """The sound starts 0.5 s after the picture and stops at 3.0 s: the sidecar of
    [0, 4.0) is still exactly 4 s, silent outside the sound, the click where it was."""
    source = _clip(
        tmp_path / "late.mp4",
        seconds=4.5,
        clicks=(2.0,),
        tone=0.2,
        audio_start_s=0.5,
        audio_seconds=2.5,
        audio="stereo",
    )
    made = _prepared(source, tmp_path / "prepared.mp4", 0.0, 4.0)
    samples = _wav(made.audio_path)
    assert samples.shape[1] == 4 * SR
    assert _rms(samples, 0.0, 0.45) < 0.01  # before the sound
    assert _rms(samples, 1.0, 1.9) > 0.1  # the tone
    assert _rms(samples, 3.1, 4.0) < 0.01  # after it
    (click,) = _onsets(samples, threshold=0.5)
    assert abs(click - 2.0) <= ONE_FRAME


# ---------------------------------------------------------------------------
# speed: one track for the whole video


@pytest.fixture(scope="module")
def stretches(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Prepared like the assembly does: `a` (5 s, clicks at 2.5 and 4.0 s), `loud` (a loud
    tone, 10 s), `mute` (no sound)."""
    folder = tmp_path_factory.mktemp("sound-stretches")
    a = _clip(folder / "a.mp4", seconds=5.0, clicks=(2.5, 4.0))
    loud = _clip(folder / "loud.mp4", seconds=10.0, tone=0.5, audio="stereo")
    mute = _clip(folder / "mute.mp4", seconds=4.0, audio=None)
    return {
        "a": _prepared(a, folder / "a-prepared.mp4", 0.0, 5.0),
        "loud": _prepared(loud, folder / "loud-prepared.mp4", 0.0, 10.0),
        "mute": _prepared(mute, folder / "mute-prepared.mp4", 0.0, 4.0),
    }


def _render(plan: Any, out: Path, made: dict[str, Any], **kw: Any) -> Any:
    files = {name: p.path for name, p in made.items()}
    sounds = {name: p.audio_path for name, p in made.items()}
    return render_speed(plan, out, resolve=files.__getitem__, resolve_audio=sounds.get, **kw)


def test_x1_x5_x1_is_one_track_in_sync_with_no_drift(
    stretches: dict[str, Any], tmp_path: Path
) -> None:
    """Criteria 1, 2, 5, 6: ×1 of `a` [0, 3) — click at 2.5 s —, ×5 of `loud` (2 s,
    silent), ×1 of `a` [3.5, 5.0) — click at 4.0 s, i.e. 0.5 s into it, at 5.5 s of the
    output. One AAC 48 kHz stereo track as long as the picture; each click at the frame
    that shows its source frame (75 and 120), within a frame — after two cuts, no drift."""
    plan = plan_speed(
        [
            SpeedSegment("a", 0.0, 3.0, 1.0),
            SpeedSegment("loud", 0.0, 10.0, 5.0),
            SpeedSegment("a", 3.5, 5.0, 1.0),
        ]
    )
    result = _render(plan, tmp_path / "out.mp4", stretches)
    info = _decode(result.path)
    assert info["audio_streams"] == 1
    assert (info["codec"], info["sample_rate"], info["channels"]) == ("aac", 48_000, 2)
    frames = len(info["barcodes"])
    assert frames == plan.frames == 90 + 60 + 45
    samples = info["samples"]
    assert abs(samples.shape[1] - frames * SR // FPS) <= 1024  # the AAC's last frame
    first, second = _onsets(samples)
    assert abs(first - 2.5) <= ONE_FRAME
    assert abs(first - info["barcodes"].index(75) / FPS) <= ONE_FRAME
    assert abs(second - 5.5) <= ONE_FRAME
    assert abs(second - (150 + info["barcodes"][150:].index(120)) / FPS) <= ONE_FRAME
    assert _rms(samples, 3.1, 4.9) < 0.005  # the ×5 stretch: silence, not the loud tone
    params = result.params()
    assert params["effect_version"] == SPEED_VERSION == "camara_rapida-v3"
    assert params["audio"] is True
    assert params["sound"]["original_sound"] == [0, 2]
    assert params["sound"]["sample_rate"] == 48_000 and params["sound"]["layout"] == "stereo"


def test_every_cut_fades_80_ms(stretches: dict[str, Any], tmp_path: Path) -> None:
    """Criterion 5: two ×1 stretches of the loud tone: at the cut (3.0 s) the sound fades
    out and in again over 40 ms each side; well inside each stretch it is the tone."""
    plan = plan_speed([SpeedSegment("loud", 0.0, 3.0, 1.0), SpeedSegment("loud", 5.0, 8.0, 1.0)])
    info = _decode(_render(plan, tmp_path / "cut.mp4", stretches).path)
    # criterion 6: 128 kbps (measured on a track that is sound throughout, not silence)
    assert abs(info["bit_rate"] - 128_000) <= 0.2 * 128_000
    samples = info["samples"]
    steady = _rms(samples, 1.0, 2.0)
    assert steady > 0.3
    assert _rms(samples, 2.996, 3.004) < 0.2 * steady  # the cut, faded to near nothing
    # inside the linear fade-out (2.96-3.0 s): 0.75 → 0.5 of the level, then 0.375 → 0.125
    assert _rms(samples, 2.97, 2.98) == pytest.approx(0.625 * steady, rel=0.15)
    assert _rms(samples, 2.985, 2.995) < 0.4 * steady
    assert _rms(samples, 3.05, 3.1) == pytest.approx(steady, rel=0.15)


def test_a_source_without_sound_and_a_photo_are_silence_of_their_length(
    stretches: dict[str, Any], tmp_path: Path
) -> None:
    """Criteria 3 and 4: a ×1 stretch of a file without sound and a stretch without a
    sidecar (a photo) still give one track, silent, as long as the picture."""
    plan = plan_speed([SpeedSegment("mute", 0.0, 3.0, 1.0), SpeedSegment("photo", 0.0, 1.5, 1.0)])
    files = {"mute": stretches["mute"].path, "photo": stretches["mute"].path}
    result = render_speed(
        plan, tmp_path / "quiet.mp4", resolve=files.__getitem__, resolve_audio=lambda _: None
    )
    info = _decode(result.path)
    assert info["audio_streams"] == 1
    assert abs(info["samples"].shape[1] - 4.5 * SR) <= 1024
    assert np.abs(info["samples"]).max() < 1e-3
    assert result.params()["sound"]["original_sound"] == []


def test_without_resolve_audio_the_render_stays_silent(
    stretches: dict[str, Any], tmp_path: Path
) -> None:
    plan = plan_speed([SpeedSegment(stretches["a"].path, 0.0, 3.0, 1.0)])
    result = render_speed(plan, tmp_path / "silent.mp4")
    assert _decode(result.path)["audio_streams"] == 0
    assert result.params()["audio"] is False and "sound" not in result.params()


def test_a_sidecar_that_is_not_one_is_refused_before_anything_is_written(
    stretches: dict[str, Any], tmp_path: Path
) -> None:
    bad = tmp_path / "bad.wav"
    with wave.open(str(bad), "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(44_100)
        sink.writeframes(b"\0\0" * 100)
    plan = plan_speed([SpeedSegment("a", 0.0, 3.0, 1.0)])
    out = tmp_path / "never.mp4"
    with pytest.raises(SpeedError) as caught:
        render_speed(
            plan,
            out,
            resolve=lambda _: stretches["a"].path,
            resolve_audio=lambda _: bad,
        )
    assert caught.value.code == CODE_AUDIO
    assert not out.exists() and list(tmp_path.iterdir()) == [bad]


# ---------------------------------------------------------------------------
# the overlays copy the track as it is


def _text_png() -> bytes:
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    img.paste((255, 255, 255, 255), (100, 1400, 980, 1600))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_texts_and_layers_keep_the_sound_in_sync(stretches: dict[str, Any], tmp_path: Path) -> None:
    """EF-05 and EF-08 copy the speed step's AAC track: after either, the click is still at
    the frame that shows source frame 75, within a frame."""
    from qualify_creative.effects import load_effects
    from qualify_creative.video.layer_overlay import TimedEffectLayer, overlay_effect_layers
    from qualify_creative.video.text_overlay import TimedLayer, overlay_text_layers

    plan = plan_speed([SpeedSegment("a", 0.0, 4.0, 1.0)])
    built = _render(plan, tmp_path / "built.mp4", stretches).path
    entry = load_effects().get("humo_capa", 1)
    assert entry is not None
    smoke = TimedEffectLayer.from_entry(entry, None, start_s=0.0, end_s=4.0)
    texts = overlay_text_layers(
        built,
        tmp_path / "texts.mp4",
        [TimedLayer(png=_text_png(), start_s=0.0, end_s=None, fade_in_s=0.0)],
    )
    layers = overlay_effect_layers(built, tmp_path / "layers.mp4", [smoke])
    for made in (texts, layers):
        assert made.has_audio
        info = _decode(made.path)
        assert info["audio_streams"] == 1 and info["sample_rate"] == 48_000
        (click,) = _onsets(info["samples"])
        assert abs(click - 2.5) <= ONE_FRAME
        assert abs(info["samples"].shape[1] - 4 * SR) <= 2048
