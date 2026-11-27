"""Lay a Clip's character scenes over its built video (m-25128784, ADR 50 §12.2): each
scene's video REPLACES the picture and the sound of the Clip for `[start_s, start_s +
duration_s)` of its output, and the Clip keeps its length — nothing is inserted.

- **Picture.** Every frame of the Clip inside a scene's window is the scene's frame for
  that instant (the latest one shown at or before it), scaled to the Clip's size with a
  bicubic filter in ONE conversion (the scene is a 480p draft, 480×854; the Clip is
  1080×1920 — a softer picture is what a draft looks like, §12.4) and converted to the
  Clip's BT.709 limited range. A scene a few frames shorter than its window (AVESC-001:
  4.96 s of 5) holds its last frame (`held_frames`), never fails; a longer one is cut at
  the window's end. The way in and the way out are cuts: the frame before the window is
  the Clip's, the first one inside is the scene's — and the first frame after it is the
  Clip's again. Frames outside every window pass untouched (decoded once, encoded once).
- **Sound.** Inside a window the Clip's own sound is silent and the scene's plays; the
  edges fade over `sound.CROSSFADE_S` (half on each side, as every cut of the local
  assembly), so no click. Each scene's voice is brought to `TARGET_DBFS` of RMS over the
  part of it that is not silence (R3: the animated character's voice came out about 5 dB
  lower in AVESC-001), within ±`MAX_GAIN_DB` and never with a peak over `PEAK_CEILING`.
  A scene file without sound is silence in its window.
- **Output.** H.264 yuv420p (`text_overlay.OVERLAY_X264`, one thread), AAC-LC 48 kHz
  stereo 128 kbps (`sound.AacWriter`), `+faststart`. Written to `out`.partial and moved
  into place only when complete; `src` and the scenes' files are never touched. Cost:
  US$0 (no vendor).

The whole sound of the Clip is held in memory once (60 s at 48 kHz stereo float32 is
about 23 MB) — the windows are rewritten in place before it is encoded. Pictures are
decoded and encoded one at a time. PyAV and numpy are imported lazily, like the rest of
this package.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from qualify_creative.video import sound
from qualify_creative.video.text_overlay import (
    ASPECT_TOLERANCE,
    OVERLAY_X264,
    _frame_rate,
    bound_decoder,
)

#: The version of this step (provenance): what it did to the picture and the sound.
SCENE_OVERLAY_VERSION = "scene-overlay-v1"
#: R3: every scene's voice at this RMS (dBFS) over its non-silent part.
TARGET_DBFS = -20.0
#: The gain is never more than this either way (a nearly silent scene is not blown up).
MAX_GAIN_DB = 12.0
#: No sample of a scene goes over this after its gain (-1 dBFS).
PEAK_CEILING = 10 ** (-1.0 / 20)
#: A stretch of 20 ms quieter than this (dBFS) is silence for the loudness measure.
SILENCE_DBFS = -50.0
_BLOCK = sound.SAMPLE_RATE // 50
_EPSILON = 1e-6


class SceneOverlayError(ValueError):
    """The scenes could not be laid: `reason` is a stable code (`unreadable`, `no_video`,
    `aspect_mismatch`, `window`, `encode_failed`)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class SceneClip:
    """One scene to lay: its file on disk and its window on the Clip's output clock."""

    path: Path
    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass(frozen=True)
class LaidScene:
    """What one scene became in the Clip (provenance)."""

    start_s: float
    duration_s: float
    frames: int
    held_frames: int
    source_seconds: float | None
    sound: bool
    gain_db: float | None

    def params(self) -> dict[str, Any]:
        return {
            "start_s": round(self.start_s, 3),
            "duration_s": round(self.duration_s, 3),
            "frames": self.frames,
            "held_frames": self.held_frames,
            "source_seconds": (
                round(self.source_seconds, 3) if self.source_seconds is not None else None
            ),
            "sound": self.sound,
            "gain_db": round(self.gain_db, 2) if self.gain_db is not None else None,
        }


@dataclass(frozen=True)
class OverlaidScenes:
    path: Path
    width: int
    height: int
    frames: int
    seconds: float
    scenes: tuple[LaidScene, ...] = field(default_factory=tuple)

    def params(self) -> dict[str, Any]:
        return {
            "version": SCENE_OVERLAY_VERSION,
            "target_dbfs": TARGET_DBFS,
            "crossfade_s": sound.CROSSFADE_S,
            "scenes": [scene.params() for scene in self.scenes],
        }


def check_windows(scenes: Sequence[SceneClip], seconds: float) -> None:
    """Each window inside the video, none crossing another. Pure."""
    ordered = sorted(scenes, key=lambda s: s.start_s)
    for scene in ordered:
        if scene.duration_s <= 0 or scene.start_s < 0 or scene.end_s > seconds + 0.05:
            raise SceneOverlayError(
                "window",
                f"a scene at {scene.start_s}s for {scene.duration_s}s does not fit {seconds}s",
            )
    for before, after in zip(ordered, ordered[1:], strict=False):
        if after.start_s < before.end_s - _EPSILON:
            raise SceneOverlayError("window", "two scenes cross")


def scene_gain_db(samples: Any) -> float | None:
    """The gain (dB) that brings `samples` ((2, n) float32) to `TARGET_DBFS` of RMS over
    its non-silent 20 ms blocks, clamped to ±`MAX_GAIN_DB` and lowered so no peak passes
    `PEAK_CEILING`. None when it is all silence (left as it is)."""
    import numpy as np  # noqa: PLC0415

    count = samples.shape[1] // _BLOCK * _BLOCK
    if count == 0:
        return None
    mono = samples[:, :count].mean(axis=0).reshape(-1, _BLOCK)
    block_rms = np.sqrt(np.mean(np.square(mono, dtype=np.float64), axis=1))
    loud = block_rms > 10 ** (SILENCE_DBFS / 20)
    if not loud.any():
        return None
    rms = float(np.sqrt(np.mean(np.square(block_rms[loud]))))
    gain = TARGET_DBFS - 20 * math.log10(rms)
    gain = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain))
    peak = float(np.max(np.abs(samples)))
    if peak > 0:
        gain = min(gain, 20 * math.log10(PEAK_CEILING / peak))
    return gain


def overlay_scenes(
    src: Path | str,
    out: Path | str,
    scenes: Sequence[SceneClip],
    *,
    x264: dict[str, str] | None = None,
) -> OverlaidScenes:
    """`src` with every scene laid over its window (see the module), written to `out`.
    Raises `SceneOverlayError`; a failure leaves no `out`."""
    import av  # noqa: PLC0415

    src, out = Path(src), Path(out)
    partial = out.with_name(out.name + ".partial")
    try:
        result = _encode(av, src, partial, list(scenes), dict(x264 or OVERLAY_X264))
        os.replace(partial, out)
    except SceneOverlayError:
        partial.unlink(missing_ok=True)
        raise
    except av.error.FFmpegError as exc:
        partial.unlink(missing_ok=True)
        raise SceneOverlayError("encode_failed", f"the scenes could not be laid: {exc}") from exc
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return OverlaidScenes(path=out, **result)


def _probe(av: Any, path: Path) -> tuple[int, int, Fraction, int, float]:
    """(width, height, rate, frames, origin) of the Clip's video."""
    try:
        source = av.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise SceneOverlayError("unreadable", f"the video cannot be opened: {exc}") from exc
    with source:
        if not source.streams.video:
            raise SceneOverlayError("no_video", "the video has no picture")
        stream = source.streams.video[0]
        rate = _frame_rate(stream)
        base = stream.time_base
        origin = float(stream.start_time * base) if stream.start_time is not None else 0.0
        width, height = stream.codec_context.width, stream.codec_context.height
        frames = stream.frames or 0
        if not frames:
            bound_decoder(stream)
            frames = sum(1 for _ in source.decode(stream))
    return width, height, rate, frames, origin


def _scene_frames(av: Any, path: Path) -> Iterator[tuple[float, Any]]:
    """The scene's pictures with their time from its first one."""
    try:
        source = av.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise SceneOverlayError("unreadable", f"a scene cannot be opened: {exc}") from exc
    with source:
        if not source.streams.video:
            raise SceneOverlayError("no_video", "a scene has no picture")
        stream = source.streams.video[0]
        bound_decoder(stream)
        first: float | None = None
        for index, frame in enumerate(source.decode(stream)):
            moment = frame.time if frame.time is not None else index / float(_frame_rate(stream))
            if first is None:
                first = moment
            yield moment - first, frame


def _scene_sound(path: Path, samples: int) -> Any | None:
    """The scene's sound from its first picture, exactly `samples` long; None without one."""
    import numpy as np  # noqa: PLC0415

    if not sound.has_audio(path):
        return None
    import av  # noqa: PLC0415

    with av.open(str(path)) as source:
        stream = source.streams.video[0] if source.streams.video else None
        origin = (
            float(stream.start_time * stream.time_base)
            if stream is not None and stream.start_time is not None
            else 0.0
        )
    chunks = list(sound.window_chunks(path, at_s=origin, samples=samples, fallback_first_s=origin))
    return np.concatenate(chunks, axis=1) if chunks else np.zeros((2, samples), np.float32)


def _clip_sound(path: Path, samples: int, origin: float) -> Any:
    import numpy as np  # noqa: PLC0415

    chunks = list(sound.window_chunks(path, at_s=origin, samples=samples, fallback_first_s=origin))
    return np.concatenate(chunks, axis=1) if chunks else np.zeros((2, samples), np.float32)


def _ramp(np: Any, length: int, rising: bool) -> Any:
    return np.linspace(0.0, 1.0, length, dtype=np.float32)[:: 1 if rising else -1]


def _lay_sound(track: Any, scene: Any | None, first: int, last: int, gain_db: float | None) -> None:
    """Silence the Clip's own sound in `[first, last)` and play the scene there, both
    with `sound.half_fade` samples of fade on each side of each edge."""
    import numpy as np  # noqa: PLC0415

    total = track.shape[1]
    half = sound.half_fade()
    # the Clip's own sound fades out before the window, is silent in it, fades in after
    low = max(0, first - half)
    if first > low:
        track[:, low:first] *= _ramp(np, first - low, rising=False)
    track[:, first:last] = 0.0
    high = min(total, last + half)
    if high > last:
        track[:, last:high] *= _ramp(np, high - last, rising=True)
    if scene is None:
        return
    piece = scene[:, : last - first].astype(np.float32, copy=True)
    if gain_db is not None:
        piece *= np.float32(10 ** (gain_db / 20))
    edge = min(half, piece.shape[1] // 2)
    if edge:
        piece[:, :edge] *= _ramp(np, edge, rising=True)
        piece[:, -edge:] *= _ramp(np, edge, rising=False)
    track[:, first : first + piece.shape[1]] += piece


def _encode(
    av: Any, src: Path, out: Path, scenes: list[SceneClip], x264: dict[str, str]
) -> dict[str, Any]:
    import numpy as np  # noqa: PLC0415

    from qualify_creative.video.prepare import _source_colour  # noqa: PLC0415

    width, height, rate, total_frames, origin = _probe(av, src)
    seconds = total_frames / float(rate)
    check_windows(scenes, seconds)
    ordered = sorted(scenes, key=lambda s: s.start_s)
    windows = [
        (min(total_frames, round(s.start_s * rate)), min(total_frames, round(s.end_s * rate)))
        for s in ordered
    ]
    # the sound: the Clip's own, each window rewritten with its scene's
    samples = round(seconds * sound.SAMPLE_RATE)
    track = _clip_sound(src, samples, origin)
    laid_sound: list[tuple[bool, float | None]] = []
    for scene, (first_f, last_f) in zip(ordered, windows, strict=True):
        first = round(first_f / rate * sound.SAMPLE_RATE)
        last = min(samples, round(last_f / rate * sound.SAMPLE_RATE))
        voice = _scene_sound(scene.path, max(0, last - first))
        gain = scene_gain_db(voice) if voice is not None else None
        _lay_sound(track, voice, first, last, gain)
        laid_sound.append((voice is not None, gain))
    np.clip(track, -1.0, 1.0, out=track)

    tick = Fraction(1, 1) / Fraction(rate)
    per_frame = sound.SAMPLE_RATE / float(rate)
    stats: list[dict[str, Any]] = [{"frames": 0, "held": 0, "last": None} for _ in ordered]
    try:
        source = av.open(str(src))
    except Exception as exc:  # noqa: BLE001
        raise SceneOverlayError("unreadable", f"the video cannot be opened: {exc}") from exc
    with (
        source,
        av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink,
    ):
        stream = source.streams.video[0]
        bound_decoder(stream)
        encoder = sink.add_stream("libx264", rate=rate)
        encoder.width, encoder.height = width, height
        encoder.pix_fmt = "yuv420p"
        encoder.options = dict(x264)
        encoder.codec_context.thread_count = int(x264.get("threads", "1"))
        encoder.codec_context.time_base = tick
        audio = sound.AacWriter(av, sink)

        active: int | None = None
        frames_of: Iterator[tuple[float, Any]] | None = None
        shown: tuple[float, Any] | None = None
        upcoming: tuple[float, Any] | None = None
        fed = 0
        index = 0

        def scene_picture(number: int, at: float) -> Any:
            nonlocal frames_of, shown, upcoming
            assert frames_of is not None
            if upcoming is None and shown is None:
                upcoming = next(frames_of, None)
            while upcoming is not None and upcoming[0] <= at + _EPSILON:
                shown, upcoming = upcoming, next(frames_of, None)
            if shown is None:  # the scene's first picture starts a hair late: show it
                shown, upcoming = upcoming, next(frames_of, None)
            if shown is None:
                raise SceneOverlayError("no_video", "a scene has no picture to show")
            stats[number]["frames"] += 1
            if upcoming is None and at > shown[0] + 1.5 / float(rate):
                stats[number]["held"] += 1
            stats[number]["last"] = shown[0]
            picture = shown[1]
            if abs(picture.width / picture.height - width / height) > ASPECT_TOLERANCE * 2:
                raise SceneOverlayError(
                    "aspect_mismatch",
                    f"a {picture.width}×{picture.height} scene is not the Clip's aspect",
                )
            matrix, colour_range = _source_colour(picture)
            return picture.reformat(
                width=width,
                height=height,
                format="yuv420p",
                src_colorspace=matrix,
                src_color_range=colour_range,
                dst_colorspace="ITU709",
                dst_color_range="MPEG",
                interpolation="BICUBIC",
            )

        for frame in source.decode(stream):
            if index >= total_frames:
                break
            number = next(
                (n for n, (a, b) in enumerate(windows) if a <= index < b),
                None,
            )
            if number != active:
                active = number
                frames_of = _scene_frames(av, ordered[number].path) if number is not None else None
                shown = upcoming = None
            if number is not None:
                at = (index - windows[number][0]) / float(rate)
                picture = scene_picture(number, at)
            else:
                picture = (
                    frame.reformat(format="yuv420p") if frame.format.name != "yuv420p" else frame
                )
                picture.pict_type = av.video.frame.PictureType.NONE
            picture.pts = index
            picture.time_base = tick
            for packet in encoder.encode(picture):
                sink.mux(packet)
            index += 1
            # the sound up to this picture's end, interleaved with the pictures
            due = min(samples, round(index * per_frame))
            if due > fed:
                audio.add(track[:, fed:due])
                fed = due
        for packet in encoder.encode():
            sink.mux(packet)
        if fed < samples:
            audio.add(track[:, fed:samples])
        audio.finish()

    laid = tuple(
        LaidScene(
            start_s=scene.start_s,
            duration_s=scene.duration_s,
            frames=stat["frames"],
            held_frames=stat["held"],
            source_seconds=_seconds_of(av, scene.path),
            sound=has_sound,
            gain_db=gain,
        )
        for scene, stat, (has_sound, gain) in zip(ordered, stats, laid_sound, strict=True)
    )
    return {
        "width": width,
        "height": height,
        "frames": index,
        "seconds": index / float(rate),
        "scenes": laid,
    }


def _seconds_of(av: Any, path: Path) -> float | None:
    """The scene file's own length (its picture), for the provenance."""
    try:
        with av.open(str(path)) as source:
            stream = source.streams.video[0]
            if stream.duration is not None:
                return float(stream.duration * stream.time_base)
            if source.duration is not None:
                return source.duration / 1_000_000
    except Exception:  # noqa: BLE001 — provenance only
        return None
    return None


__all__ = [
    "MAX_GAIN_DB",
    "PEAK_CEILING",
    "SCENE_OVERLAY_VERSION",
    "TARGET_DBFS",
    "LaidScene",
    "OverlaidScenes",
    "SceneClip",
    "SceneOverlayError",
    "check_windows",
    "overlay_scenes",
    "scene_gain_db",
]
