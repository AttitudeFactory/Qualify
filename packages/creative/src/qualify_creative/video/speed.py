"""«Cámara rápida» (EF-04, epic «Video automático con efectos, por pasos», ADR 50): one or
more stretches of already prepared (upright, vertical) videos, each sped up ×1 to ×30, laid
end to end with hard cuts as one H.264 MP4 at 30 fps CFR — a Reel's time-lapse — silent, or
with the ×1 stretches' own sound when the caller asks for it (`resolve_audio`).

Two steps, so a live preview (an editor-like timeline) can use the first without a file:

1. `plan_speed` is PURE — it opens no file and does not import PyAV. From the stretches in
   order it computes each one's place on the output timeline (`out_start_s`, `out_end_s`,
   its frames) and the total, and refuses what cannot be rendered: a speed outside ×1–×30,
   an empty list, an empty interval, a total outside a Reel's 3–60 s. A stretch's `end_s`
   is therefore required; `resolve_segment` reads it from the file when the owner meant
   «to the end».
2. `render_speed` encodes a plan, frame by frame, and returns the provenance the asset
   keeps in its `params` (`SpeedResult.params()`).

Sources are REFERENCES, not paths: `SpeedSegment.source` is a stable, opaque id (the
prepared asset's id or its R2 key) — what the plan, its JSON and the asset's `params` keep.
The caller downloads the files to a temporary folder and passes `resolve` (reference →
local path) to `render_speed` / `resolve_segment`; by default the reference IS the path
(identity), which is what tests and local tools use. A temporary path never lands in the
provenance.

Speeding up = sampling: output frame `n` of a stretch shows the latest source frame at or
before `t_src = start_s + n × speed / 30` (seconds from the source's first decoded frame),
with half a source frame of slack for jittery stamps — the same rule as
`cut._write_retimed` and `prepare._encode`. So the output is 30 fps whatever the source's
rate, and a variable-rate source keeps its real pace (a slow part's frames repeat, a fast
part's are thinned). A stretch lasts `round_half_up((end_s − start_s) / speed × 30)` output
frames (at least one); the total is the sum of those frames over 30, so the plan, the file
and the preview agree to the frame. The output rate is always `SPEED_FPS`.

Size: `size` when the caller gives one (the local assembly always asks for 1080×1920,
m-25041163), else the first stretch's, floored to even numbers (yuv420p). A stretch of
another size is cover-cropped (centred, as `fit` and `join` do) and scaled to it, bicubic,
in this same pass — so a small prepared video is enlarged by the ONE 1080×1920 encode the
part needs anyway, never encoded at that size twice; a stretch already at `size` is not
resampled (FFmpeg's `scale` passes it through). Refusing another size would make the owner
re-prepare a video for a difference the eye accepts; stretching it would distort it.

Colour: the output is tagged BT.709, limited range — what its sources (`prepare`,
`photo_hold`) write; the crop and scale keep the YUV values as they are.

Sources must be upright: one carrying a display rotation is refused
(`rotation_unsupported`) before anything is written — `prepare` writes them upright.

Sound (m-25049580). Without `resolve_audio` (every caller but the local assembly) only
the video stream is decoded and the output has no audio track. With it the output ALWAYS
has exactly one AAC-LC 48 kHz stereo 128 kbps track for its whole length
(`sound.AacWriter`, `join`'s format), so the music (a later step) and `join` always find
one: a ×1 stretch whose source has a sidecar (`resolve_audio(reference)` → a `sound` WAV,
sample 0 at the source's first frame, as `prepare` writes it) takes ITS samples from
`start_s × 48000`, exactly `frames × 1600` of them (48000 / 30) — the instants its frames
show, so picture and sound start and end together; a sped-up stretch (its sound would be
noise; no time-stretching), a photo or a source without sound is silence of its exact
length. The track is encoded once, sample-counted from 0, so nothing drifts across cuts,
with `join`'s 80 ms fade at every cut (half on each side, `sound.faded`). The sidecar is
read a second at a time: never a whole stretch's sound in memory.

Before the encoder opens, every distinct source is probed ONCE (`_source.probe`, through
`open_video` so FFmpeg errors come out typed): readable, has a picture, upright, the
interval inside it. Each stretch is then decoded from a seek (`cut._decode_from`, checked
to land at or before the stretch's start), not from frame 0.

Memory (the creative worker has 512 MiB): stretches are rendered one after another with a
single decoder open at a time; frames go from the decoder through a crop/scale graph to
the encoder and only the frame being shown is held — no list of frames, ever. Decoder and
encoder run with `threads` codec threads, slice-threaded (`join._bound`, set before the
first decode: FFmpeg's automatic frame threading cost 224 MiB on the first 4K decode in
`prepare`'s measurement), x264 with `JOIN_X264` (a short `rc-lookahead`), the decoder's
graph collected between stretches, and the MP4 muxed straight to a partial file beside the
caller's path, then renamed into place: a failed render leaves no file and never replaces
one already there. Measured 2026-11-14 on Windows (8 cores; a fresh process, the source
made by `deploy/measure/prepare_memory.py make --size 1080x1920`: 16 s of noisy 30 fps
H.264 + AAC), 15 s of it at ×5 → 3 s out: peak working set 208 MiB with `threads` 1 or
2 (35 MiB before the render), 30 s and 15 s wall. NOT measured on linux/arm64 nor under
the worker's cgroup (`creative-worker-memory.sh`).

PyAV is imported lazily (only `render_speed` and `resolve_segment` need it), like `fit.py`
and `join.py`: production has no `ffmpeg` binary.
"""

from __future__ import annotations

import gc
import math
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qualify_creative.video._source import Timeline, VideoSourceError

#: The effect's id in the effects catalogue and in the asset's `params`.
SPEED_EFFECT_ID = "camara_rapida"
#: Version of this effect's recipe — recorded with the asset (provenance). v2
#: (m-25041163): renders at the `size` asked for (the local assembly's 1080×1920), enlarging
#: a smaller stretch bicubic in its own pass, and tags the output BT.709 limited range. This
#: is the RENDER recipe's provenance; the catalogue's `camara_rapida` entry (its params
#: contract, never offered — D-T3) keeps `version: 1`, as its `speed` param did not change.
#: v3 (m-25049580): the ×1 stretches' own sound on request (`resolve_audio`).
SPEED_VERSION = "camara_rapida-v3"
#: How a stretch of another size is scaled to the output (FFmpeg `scale` flags).
SPEED_SCALE_FLAGS = "bicubic"
#: The scale keeps the YUV as it is: without these, FFmpeg's `scale` converts a BT.709
#: source to its BT.601 default even at the same size (a pure red came out with 23 of green).
_SCALE_COLOUR = "in_color_matrix=bt709:out_color_matrix=bt709:in_range=tv:out_range=tv"
#: AVCOL_* codes the output is tagged with (BT.709 primaries, transfer and matrix; limited).
_BT709 = 1
_LIMITED_RANGE = 1
#: Output frame rate (CFR) — the only one: a stored plan with another is refused.
SPEED_FPS = 30
#: The speeds the owner may pick, inclusive.
MIN_SPEED = 1.0
MAX_SPEED = 30.0
#: A Reel's length, inclusive, in seconds.
MIN_TOTAL_S = 3.0
MAX_TOTAL_S = 60.0
#: Codec threads for the decoder and the encoder, slice-threaded (`prepare.PREPARE_THREADS`).
#: 1080×1920, 15 s at ×5: peak 208 MiB with 1 or 2 threads; 2 halves the wall time.
SPEED_THREADS = 2
#: Stable error codes (`SpeedError.code`), besides `VideoSourceError`'s own
#: (`unreadable`, `no_video`, `rotation_unsupported`, `seek_failed`).
CODE_EMPTY = "speed_empty"
CODE_SPEED = "speed_out_of_range"
CODE_INTERVAL = "speed_interval_invalid"
CODE_TOO_SHORT = "speed_segment_too_short"
CODE_DURATION = "speed_duration_out_of_range"
CODE_OUT_OF_SOURCE = "speed_interval_out_of_source"
CODE_ENCODE = "speed_encode_failed"
CODE_END_UNKNOWN = "speed_source_end_unknown"
CODE_AUDIO = "speed_audio_invalid"
#: How far past the source's last frame an interval may end (container rounding).
_END_TOLERANCE_S = 0.05

#: Turns a source reference into a local file path (default: the reference is the path).
Resolver = Callable[[str], "str | os.PathLike[str]"]
#: Turns a source reference into its sound's sidecar (`sound`'s WAV), or None: no sound.
AudioResolver = Callable[[str], "str | os.PathLike[str] | None"]


class SpeedError(VideoSourceError):
    """The stretches cannot be sped up as asked. `code` is stable (the constants above,
    or `VideoSourceError`'s reasons); the message is for logs, never for the owner."""

    @property
    def code(self) -> str:
        return self.reason


class SpeedDurationOutOfRange(SpeedError):
    """The sped-up total falls outside a Reel's 3–60 s. `duration_s`: the computed total,
    so the screen can say how long it came out."""

    def __init__(self, duration_s: float) -> None:
        super().__init__(
            CODE_DURATION,
            f"the sped-up video lasts {duration_s:.2f} s; a Reel needs "
            f"{MIN_TOTAL_S:g}–{MAX_TOTAL_S:g} s",
        )
        self.duration_s = duration_s


@dataclass(frozen=True)
class SpeedSegment:
    """One stretch: the prepared video `source` (a stable, opaque reference — asset id or
    R2 key — resolved to a local file only at render time), the interval
    `[start_s, end_s)` in seconds from its first decoded frame, and how many times faster
    it plays."""

    source: str
    start_s: float
    end_s: float
    speed: float

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise SpeedError(
                CODE_INTERVAL, f"a stretch needs a source reference, not {self.source!r}"
            )
        for name in ("start_s", "end_s", "speed"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise SpeedError(CODE_INTERVAL, f"{name} must be a number, not {value!r}")
            if not math.isfinite(value):
                raise SpeedError(CODE_INTERVAL, f"{name} must be finite, not {value!r}")
            object.__setattr__(self, name, float(value))
        if not MIN_SPEED <= self.speed <= MAX_SPEED:
            raise SpeedError(
                CODE_SPEED, f"speed ×{self.speed:g} is outside ×{MIN_SPEED:g}–×{MAX_SPEED:g}"
            )
        if self.start_s < 0:
            raise SpeedError(CODE_INTERVAL, f"a stretch cannot start before 0 s ({self.start_s})")
        if self.end_s <= self.start_s:
            raise SpeedError(CODE_INTERVAL, f"empty interval {self.start_s}–{self.end_s} s")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "speed": self.speed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SpeedSegment:
        return cls(
            source=data["source"],
            start_s=data["start_s"],
            end_s=data["end_s"],
            speed=data["speed"],
        )


@dataclass(frozen=True)
class PlannedSegment:
    """A stretch placed on the output timeline: output frames
    `[out_start_frame, out_start_frame + frames)`, i.e. `[out_start_s, out_end_s)`."""

    segment: SpeedSegment
    out_start_frame: int
    frames: int

    @property
    def out_start_s(self) -> float:
        return self.out_start_frame / SPEED_FPS

    @property
    def out_end_s(self) -> float:
        return (self.out_start_frame + self.frames) / SPEED_FPS

    @property
    def duration_s(self) -> float:
        return self.frames / SPEED_FPS

    def source_time(self, n: int) -> float:
        """Seconds into the source (from its first frame) that output frame `n` of this
        stretch shows: `start_s + n × speed / 30`."""
        return self.segment.start_s + n * self.segment.speed / SPEED_FPS

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.segment.to_dict(),
            "out_start_s": round(self.out_start_s, 6),
            "out_end_s": round(self.out_end_s, 6),
            "out_start_frame": self.out_start_frame,
            "frames": self.frames,
            "duration_s": round(self.duration_s, 6),
        }


@dataclass(frozen=True)
class SpeedPlan:
    """The validated output timeline: every stretch in order, back to back, and the total
    (`frames` at `SPEED_FPS`, `duration_s` = frames / 30, between 3 and 60 s)."""

    segments: tuple[PlannedSegment, ...]
    frames: int

    @property
    def fps(self) -> int:
        return SPEED_FPS

    @property
    def duration_s(self) -> float:
        return self.frames / SPEED_FPS

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready. `from_dict` reads back only the stretches and plans them again: the
        timeline is always recomputed, never trusted from storage."""
        return {
            "fps": SPEED_FPS,
            "frames": self.frames,
            "duration_s": round(self.duration_s, 6),
            "segments": [planned.to_dict() for planned in self.segments],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SpeedPlan:
        fps = data.get("fps", SPEED_FPS)
        if fps != SPEED_FPS:
            raise SpeedError(CODE_INTERVAL, f"a plan at {fps!r} fps; «Cámara rápida» is 30 fps")
        return plan_speed([SpeedSegment.from_dict(item) for item in data["segments"]])


def segment_frames(start_s: float, end_s: float, speed: float) -> int:
    """Output frames of a stretch: `(end_s − start_s) / speed × 30` rounded half up (a
    tiny epsilon absorbs float noise, so 2.5 → 3 even when it reads 2.4999999). Half up,
    not Python's half-to-even, so the same interval always rounds the same way."""
    raw = (end_s - start_s) / speed * SPEED_FPS
    return math.floor(raw + 0.5 + 1e-9)


def plan_speed(segments: Sequence[SpeedSegment]) -> SpeedPlan:
    """The output timeline of `segments` in order — pure: no file is opened. Raises
    `SpeedError` (`speed_empty`, `speed_out_of_range`, `speed_interval_invalid`,
    `speed_segment_too_short`) or `SpeedDurationOutOfRange` (`speed_duration_out_of_range`,
    with `duration_s`) when the total is outside 3–60 s."""
    if not segments:
        raise SpeedError(CODE_EMPTY, "nothing to speed up")
    planned: list[PlannedSegment] = []
    cursor = 0
    for index, segment in enumerate(segments):
        if not isinstance(segment, SpeedSegment):
            raise SpeedError(CODE_INTERVAL, f"stretch {index + 1} is not a SpeedSegment")
        frames = segment_frames(segment.start_s, segment.end_s, segment.speed)
        if frames < 1:
            raise SpeedError(
                CODE_TOO_SHORT,
                f"stretch {index + 1} lasts less than one frame at ×{segment.speed:g}",
            )
        planned.append(PlannedSegment(segment, out_start_frame=cursor, frames=frames))
        cursor += frames
    duration_s = cursor / SPEED_FPS
    if not MIN_TOTAL_S <= duration_s <= MAX_TOTAL_S:
        raise SpeedDurationOutOfRange(round(duration_s, 3))
    return SpeedPlan(segments=tuple(planned), frames=cursor)


def _identity(source: str) -> str:
    return source


def resolve_segment(
    source: str,
    *,
    speed: float,
    start_s: float = 0.0,
    end_s: float | None = None,
    resolve: Resolver | None = None,
) -> SpeedSegment:
    """A stretch whose `end_s` may be None («to the end of the file»): reads the end of
    `resolve(source)` from its frames (`_source.probe`) and returns the `SpeedSegment` —
    which keeps the reference `source`, not the local path. Opens the file; needs PyAV."""
    if end_s is None:
        end_s = _end_of(_probe((resolve or _identity)(source), SPEED_THREADS))
    return SpeedSegment(source=source, start_s=start_s, end_s=end_s, speed=speed)


@dataclass(frozen=True)
class SpeedResult:
    """The rendered MP4 and what the asset records about it."""

    path: Path
    width: int
    height: int
    plan: SpeedPlan
    content_type: str = "video/mp4"
    effect_id: str = SPEED_EFFECT_ID
    version: str = SPEED_VERSION
    #: The sound track's provenance (its format and which stretches carry their own
    #: sound), None when the render was silent (no `resolve_audio`).
    sound: dict[str, Any] | None = None

    @property
    def fps(self) -> int:
        return SPEED_FPS

    @property
    def frames(self) -> int:
        return self.plan.frames

    @property
    def duration_s(self) -> float:
        return self.plan.duration_s

    def params(self) -> dict[str, Any]:
        """The provenance for the asset's `params` — JSON-serializable; every stretch's
        `source` is its reference, never a temporary path."""
        return {
            "effect_id": self.effect_id,
            "effect_version": self.version,
            "fps": SPEED_FPS,
            "frames": self.frames,
            "duration_s": round(self.duration_s, 6),
            "width": self.width,
            "height": self.height,
            "audio": self.sound is not None,
            **({"sound": self.sound} if self.sound is not None else {}),
            "segments": [planned.to_dict() for planned in self.plan.segments],
        }


@dataclass(frozen=True)
class _Probed:
    """A source as probed once: its timeline and stored size."""

    path: str
    timeline: Timeline
    width: int
    height: int


def render_speed(
    plan: SpeedPlan,
    out_path: str | os.PathLike[str],
    *,
    resolve: Resolver | None = None,
    threads: int = SPEED_THREADS,
    size: tuple[int, int] | None = None,
    resolve_audio: AudioResolver | None = None,
) -> SpeedResult:
    """Encode `plan` as H.264 `yuv420p` at 30 fps CFR, BT.709 limited, `+faststart`, to
    `out_path`, at `size` (floored to even; default the first stretch's) — without an audio
    track, or with `resolve_audio` one AAC track for the whole video (see the module): a ×1
    stretch's sidecar sliced to its interval, silence for the rest. Every sidecar is checked
    (`speed_audio_invalid`) before the encoder opens.
    Sources are `prepare` / `photo_hold` output (BT.709, limited range): the scale keeps
    their YUV as is, so a BT.601 or full-range file from elsewhere would shift colour.
    `resolve` turns each stretch's source reference into a local file
    (default: the reference is the path); `threads` bounds the codec threads. The plan is
    re-planned first (a hand-built or stored plan is never trusted), and every distinct
    source is probed once BEFORE the encoder opens: an unreadable file, a missing video
    stream, a rotated source or an interval past the source's end fails with nothing
    written. Encoded beside `out_path` and renamed into place."""
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise SpeedError(CODE_INTERVAL, f"implausible thread count {threads!r}")
    if size is not None and (
        len(size) != 2
        or not all(isinstance(side, int) and not isinstance(side, bool) for side in size)
        or min(size) < 2
    ):
        raise SpeedError(CODE_INTERVAL, f"implausible output size {size!r}")
    plan = plan_speed([planned.segment for planned in plan.segments])
    import av  # noqa: PLC0415 — lazy: only a rendered video needs it

    resolve = resolve or _identity
    out = Path(out_path)
    probed: dict[str, _Probed] = {}
    sources: list[_Probed] = []
    for planned in plan.segments:
        reference = planned.segment.source
        if reference not in probed:
            probed[reference] = _probe(resolve(reference), threads)
        sources.append(_check_interval(planned, probed[reference]))
    sounds = _sounds(plan, resolve_audio)
    if size is None:
        width, height = sources[0].width, sources[0].height
    else:
        width, height = size[0] // 2 * 2, size[1] // 2 * 2
    partial = out.with_name(f".{out.name}.{uuid.uuid4().hex}.partial.mp4")
    try:
        try:
            _render(av, plan, sources, partial, (width, height), threads, sounds)
        except VideoSourceError:
            raise
        except (OSError, av.error.FFmpegError) as error:
            raise SpeedError(
                CODE_ENCODE, f"the sped-up video cannot be written: {error}"
            ) from error
        os.replace(partial, out)
    finally:
        partial.unlink(missing_ok=True)
    return SpeedResult(
        path=out,
        width=width,
        height=height,
        plan=plan,
        sound=_sound_params(sounds) if sounds is not None else None,
    )


def _sounds(plan: SpeedPlan, resolve_audio: AudioResolver | None) -> list[str | None] | None:
    """Each stretch's sidecar — asked only for a ×1 stretch; None for a sped-up one, a
    photo or a silent source — or None for a silent render. Each sidecar's format is checked
    here, before anything is written."""
    if resolve_audio is None:
        return None
    from qualify_creative.video.sound import SoundError, wav_samples  # noqa: PLC0415

    sounds: list[str | None] = []
    for planned in plan.segments:
        found = resolve_audio(planned.segment.source) if planned.segment.speed == 1.0 else None
        if found is not None:
            try:
                wav_samples(found)
            except (SoundError, OSError) as error:
                raise SpeedError(
                    CODE_AUDIO, f"{planned.segment.source}: its sound cannot be read: {error}"
                ) from error
        sounds.append(None if found is None else os.fspath(found))
    return sounds


def _sound_params(sounds: Sequence[str | None]) -> dict[str, Any]:
    """The sound track's provenance: its format and the stretches (0-based, in the plan's
    order) that carry their own sound — the others are silence."""
    from qualify_creative.video.sound import SOUND_VERSION, sound_format  # noqa: PLC0415

    return {
        "version": SOUND_VERSION,
        **sound_format(),
        "original_sound": [index for index, found in enumerate(sounds) if found is not None],
    }


def _probe(path: str | os.PathLike[str], threads: int) -> _Probed:
    """The source's timeline (first and last decoded frame, rate, rotation) and its stored
    size made even — refused when it is turned or has no picture size."""
    from qualify_creative.video._source import open_video, probe  # noqa: PLC0415
    from qualify_creative.video.join import _bound  # noqa: PLC0415

    with open_video(path) as (container, stream):
        _bound(stream.codec_context, threads)  # before the first decode
        timeline = probe(container, stream, need_end=True)
        width = (stream.codec_context.width or 0) // 2 * 2
        height = (stream.codec_context.height or 0) // 2 * 2
    name = Path(path).name
    if timeline.rotation:
        raise SpeedError("rotation_unsupported", f"{name} is turned {timeline.rotation}°")
    if width < 2 or height < 2:
        raise SpeedError("no_video", f"{name} has no picture size")
    return _Probed(path=os.fspath(path), timeline=timeline, width=width, height=height)


def _end_of(probed: _Probed) -> float:
    """Where the source's picture ends (seconds from its first frame) — refused when the
    probe could not tell, never guessed."""
    if probed.timeline.end_s is None:
        raise SpeedError(CODE_END_UNKNOWN, f"the end of {Path(probed.path).name} is unknown")
    return probed.timeline.end_s


def _check_interval(planned: PlannedSegment, probed: _Probed) -> _Probed:
    end = _end_of(probed)
    if planned.segment.end_s > end + _END_TOLERANCE_S:
        raise SpeedError(
            CODE_OUT_OF_SOURCE,
            f"{planned.segment.source} lasts {end:.2f} s; the stretch ends at "
            f"{planned.segment.end_s:.2f} s",
        )
    return probed


def _render(
    av: Any,
    plan: SpeedPlan,
    sources: Sequence[_Probed],
    out: Path,
    size: tuple[int, int],
    threads: int,
    sounds: Sequence[str | None] | None = None,
) -> int:
    from fractions import Fraction  # noqa: PLC0415

    from qualify_creative.video.join import JOIN_X264, _bound  # noqa: PLC0415
    from qualify_creative.video.sound import AacWriter  # noqa: PLC0415

    width, height = size
    tick = Fraction(1, SPEED_FPS)
    written = 0
    with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        encoder = sink.add_stream("libx264", rate=SPEED_FPS)
        encoder.width, encoder.height = width, height
        encoder.pix_fmt = "yuv420p"
        encoder.options = {**JOIN_X264, "threads": str(threads)}
        context = encoder.codec_context
        context.time_base = tick
        context.color_range = _LIMITED_RANGE
        context.colorspace = _BT709
        context.color_primaries = _BT709
        context.color_trc = _BT709
        _bound(context, threads)
        sound_out = AacWriter(av, sink) if sounds is not None else None

        def emit(frame: Any) -> None:
            nonlocal written
            # stamped by hand, one tick per frame (CFR); a repeated picture is the same
            # object re-stamped — the encoder took its pts and a reference at `encode`
            frame.pts = written
            frame.time_base = tick
            try:
                for packet in encoder.encode(frame):
                    sink.mux(packet)
            except av.error.FFmpegError as error:
                # raised inside the source's `open_video`, which would call ANY FFmpeg
                # error the source's («unreadable»): a full disk or x264 is the writing
                raise SpeedError(CODE_ENCODE, f"the frame cannot be written: {error}") from error
            written += 1

        last = len(plan.segments) - 1
        for index, (planned, source) in enumerate(zip(plan.segments, sources, strict=True)):
            if sound_out is not None and sounds is not None:
                # the stretch's sound first, as `join` lays a part's: the muxer interleaves
                _sound_segment(sound_out, planned, sounds[index], index > 0, index < last)
            _render_segment(av, planned, source, size, threads, emit)
            gc.collect()  # this stretch's decoder, graph and frames, before the next
        if sound_out is not None:
            sound_out.finish()
        for packet in encoder.encode():
            sink.mux(packet)
    if written != plan.frames:  # pragma: no cover — the sampler always fills its frames
        raise SpeedError(CODE_ENCODE, f"wrote {written} frames, planned {plan.frames}")
    return written


def _sound_segment(
    sound_out: Any, planned: PlannedSegment, sidecar: str | None, fade_in: bool, fade_out: bool
) -> None:
    """The stretch's sound handed to the AAC track: exactly `frames × 48000 / 30` samples —
    its sidecar's from `start_s` (sample 0 = the source's first frame, the clock its frames'
    `source_time` counts on) or silence — with half the cut's fade at each edge that meets
    another stretch. Streamed from the sidecar a second at a time."""
    from qualify_creative.video import sound  # noqa: PLC0415

    samples = planned.frames * sound.SAMPLE_RATE // SPEED_FPS
    half = min(sound.half_fade(), samples)
    fades = (half if fade_in else 0, half if fade_out else 0)
    chunks = (
        sound.read_wav_window(
            sidecar, start=round(planned.segment.start_s * sound.SAMPLE_RATE), samples=samples
        )
        if sidecar is not None
        else sound.silence(samples)
    )
    position = 0
    for chunk in chunks:
        sound_out.add(sound.faded(chunk, position, samples, *fades))
        position += chunk.shape[1]


def _decode(container: Any, stream: Any, timeline: Timeline, start_s: float) -> Any:
    """Decoded frames from at or before `start_s` (`cut._decode_from`: a checked seek,
    decode errors typed) — a seam the memory test wraps."""
    from qualify_creative.video.cut import _decode_from  # noqa: PLC0415

    return _decode_from(container, stream, timeline, start_s)


def _render_segment(
    av: Any,
    planned: PlannedSegment,
    source: _Probed,
    size: tuple[int, int],
    threads: int,
    emit: Callable[[Any], None],
) -> None:
    """Hand `planned.frames` output frames to `emit`: frame `n` is the latest source frame
    at or before `planned.source_time(n)` (half a source frame of slack), cover-cropped
    and scaled to `size`. Holds only the frame being shown (raw and fitted); a source
    frame no tick lands on is dropped without being fitted."""
    from qualify_creative.video._source import frame_seconds, open_video  # noqa: PLC0415
    from qualify_creative.video.fit import _cover_crop  # noqa: PLC0415
    from qualify_creative.video.join import _bound  # noqa: PLC0415

    width, height = size
    frames = planned.frames
    timeline = source.timeline
    half_frame = 0.5 / float(timeline.rate)
    with open_video(source.path) as (container, stream):
        _bound(stream.codec_context, threads)  # before the first decode
        graph = av.filter.Graph()
        video_in = graph.add_buffer(template=stream)
        crop = graph.add("crop", _cover_crop(width, height))
        scale = graph.add("scale", f"{width}:{height}:{_SCALE_COLOUR}:flags={SPEED_SCALE_FLAGS}")
        to_yuv = graph.add("format", "yuv420p")
        sink = graph.add("buffersink")
        video_in.link_to(crop)
        crop.link_to(scale)
        scale.link_to(to_yuv)
        to_yuv.link_to(sink)
        graph.configure()

        held: Any = None  # the source frame shown now
        fitted: Any = None  # `held` cropped and scaled (computed once, on first show)
        n = 0

        def show() -> None:
            nonlocal fitted, n
            if fitted is None:
                try:
                    video_in.push(held)
                    fitted = sink.pull()
                except av.error.FFmpegError as error:  # the crop/scale, not the source
                    raise SpeedError(CODE_ENCODE, f"the frame cannot be fitted: {error}") from (
                        error
                    )
            emit(fitted)
            n += 1

        for frame in _decode(container, stream, timeline, planned.segment.start_s):
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            moment = time_s - timeline.origin_s
            # every tick this frame comes after shows the frame held until now
            while n < frames and planned.source_time(n) + half_frame < moment:
                if held is None:  # the interval starts before the first frame: show it
                    held, fitted = frame, None
                show()
            if n >= frames:
                break
            held, fitted = frame, None
        if held is None:
            raise SpeedError("no_video", f"{planned.segment.source}: no frame in its interval")
        while n < frames:  # the source's last frame lasts to the interval's end
            show()
