"""m-25128784 (ADR 50 §12.2): a Clip's character scenes laid over its built video —
real encodes of tiny synthetic clips with PyAV (no network, no `ffmpeg` binary). The
Clip's frames carry a barcode (their index); a scene is a flat colour at another size and
frame rate, a few frames short of its window, with a quiet tone. Checked with tolerances,
never hashes (m-25029128)."""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video import sound  # noqa: E402
from qualify_creative.video.scene_overlay import (  # noqa: E402
    MAX_GAIN_DB,
    SCENE_OVERLAY_VERSION,
    TARGET_DBFS,
    SceneClip,
    SceneOverlayError,
    check_windows,
    overlay_scenes,
    scene_gain_db,
)

SIZE = (180, 320)
FPS = 30
BITS = 8
SR = sound.SAMPLE_RATE


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


def _write(
    path: Path,
    *,
    frames: int,
    fps: int,
    size: tuple[int, int],
    picture: Any,
    tone: float,
    hz: float,
    audio: bool = True,
) -> Path:
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = *size, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "18"}
        track = None
        if audio:
            track = sink.add_stream("aac", rate=SR)
            track.layout = "stereo"
        for i in range(frames):
            frame = av.VideoFrame.from_ndarray(picture(i), format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        if track is not None:
            total = round(frames / fps * SR)
            t = np.arange(total) / SR
            wave_ = (tone * np.sin(2 * np.pi * hz * t)).astype(np.float32)
            for start in range(0, total, 1024):
                chunk = np.tile(wave_[start : start + 1024], (2, 1))
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
                frame.sample_rate = SR
                frame.pts = start
                frame.time_base = Fraction(1, SR)
                for packet in track.encode(frame):
                    sink.mux(packet)
            for packet in track.encode():
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


def _clip(path: Path, seconds: float) -> Path:
    return _write(
        path,
        frames=round(seconds * FPS),
        fps=FPS,
        size=SIZE,
        picture=_barcode,
        tone=0.3,
        hz=440,
    )


def _scene(path: Path, seconds: float, *, fps: int = 24, audio: bool = True) -> Path:
    red = np.zeros((160, 90, 3), dtype=np.uint8)
    red[:, :, 0] = 220
    return _write(
        path,
        frames=round(seconds * fps),
        fps=fps,
        size=(90, 160),
        picture=lambda _i: red,
        tone=0.05,  # about -29 dBFS RMS: R3's quiet voice, 9 dB under the target
        hz=1000,
        audio=audio,
    )


def _decode(path: Path) -> tuple[list[Any], Any]:
    with av.open(str(path)) as out:
        frames = [f.to_ndarray(format="rgb24") for f in out.decode(out.streams.video[0])]
    with av.open(str(path)) as out:
        samples = np.concatenate([f.to_ndarray() for f in out.decode(out.streams.audio[0])], axis=1)
    return frames, samples


def _is_scene(pixels: Any) -> bool:
    return pixels[..., 0].mean() > 170 and pixels[..., 1].mean() < 60


def _band_rms(samples: Any, start_s: float, end_s: float, hz: float) -> float:
    """The RMS of the `hz` component in a window (a single-bin DFT)."""
    window = samples[0, int(start_s * SR) : int(end_s * SR)].astype(np.float64)
    t = np.arange(window.size) / SR
    c = np.dot(window, np.cos(2 * np.pi * hz * t)) * 2 / window.size
    s = np.dot(window, np.sin(2 * np.pi * hz * t)) * 2 / window.size
    return math.hypot(c, s) / math.sqrt(2)


def test_the_scene_replaces_its_window_and_the_clip_keeps_its_length(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "clip.mp4", 3.0)
    # 1.0 s asked, 0.9 s delivered: the last frame is held, nothing fails
    scene = _scene(tmp_path / "scene.mp4", 0.9)
    made = overlay_scenes(
        clip, tmp_path / "out.mp4", [SceneClip(path=scene, start_s=1.0, duration_s=1.0)]
    )
    frames, samples = _decode(made.path)
    assert made.frames == len(frames) == 90  # no frame added nor lost
    assert (made.width, made.height) == SIZE
    inside = [i for i, f in enumerate(frames) if _is_scene(f)]
    assert inside == list(range(30, 60))  # [1.0, 2.0) — cuts on both sides
    for i in (0, 29, 60, 89):
        assert _read_barcode(av.VideoFrame.from_ndarray(frames[i], format="rgb24")) == i
    (laid,) = made.scenes
    assert laid.frames == 30
    assert laid.held_frames >= 2  # 0.1 s short at 30 fps
    assert laid.sound is True
    assert laid.source_seconds == pytest.approx(0.9, abs=0.05)
    # the sound: the Clip's 440 Hz outside, gone inside; the scene's tone inside, louder
    assert _band_rms(samples, 0.2, 0.9, 440) > 0.15
    assert _band_rms(samples, 1.1, 1.9, 440) < 0.01
    assert _band_rms(samples, 2.1, 2.9, 440) > 0.15
    raised = _band_rms(samples, 1.1, 1.8, 1000)
    assert raised > 0.05 / math.sqrt(2) * 2  # R3: brought up to TARGET_DBFS
    assert 20 * math.log10(raised) == pytest.approx(TARGET_DBFS, abs=2.5)
    assert laid.gain_db is not None and 0 < laid.gain_db <= MAX_GAIN_DB
    params = made.params()
    assert params["version"] == SCENE_OVERLAY_VERSION
    assert params["scenes"][0]["held_frames"] == laid.held_frames


def test_a_scene_without_sound_is_silence_in_its_window(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "clip.mp4", 2.0)
    scene = _scene(tmp_path / "scene.mp4", 1.0, fps=30, audio=False)
    made = overlay_scenes(
        clip, tmp_path / "out.mp4", [SceneClip(path=scene, start_s=0.0, duration_s=1.0)]
    )
    frames, samples = _decode(made.path)
    assert [_is_scene(f) for f in frames[:30]] == [True] * 30
    assert not _is_scene(frames[30])
    assert np.abs(samples[:, int(0.1 * SR) : int(0.9 * SR)]).max() < 0.01
    assert made.scenes[0].sound is False and made.scenes[0].gain_db is None


def test_a_window_past_the_end_or_crossing_is_refused(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "clip.mp4", 1.0)
    scene = _scene(tmp_path / "scene.mp4", 1.0)
    with pytest.raises(SceneOverlayError) as caught:
        overlay_scenes(
            clip, tmp_path / "out.mp4", [SceneClip(path=scene, start_s=0.5, duration_s=1.0)]
        )
    assert caught.value.reason == "window"
    assert not (tmp_path / "out.mp4").exists()
    assert not (tmp_path / "out.mp4.partial").exists()
    with pytest.raises(SceneOverlayError):
        check_windows(
            [SceneClip(scene, 0.0, 5.0), SceneClip(scene, 4.0, 5.0)],
            20.0,
        )


def test_the_gain_never_passes_its_bounds_and_leaves_silence_alone() -> None:
    silent = np.zeros((2, SR), dtype=np.float32)
    assert scene_gain_db(silent) is None
    whisper = np.full((2, SR), 1e-3, dtype=np.float32)  # -60 dBFS: silence to the measure
    assert scene_gain_db(whisper) is None
    quiet = (0.006 * np.sin(np.arange(SR) * 0.1)).astype(np.float32)[None].repeat(2, 0)
    assert scene_gain_db(quiet) == pytest.approx(MAX_GAIN_DB)
    loud = np.full((2, SR), 0.95, dtype=np.float32)
    gain = scene_gain_db(loud)
    assert gain is not None and gain < 0
    assert 0.95 * 10 ** (gain / 20) <= 10 ** (-1 / 20) + 1e-6
