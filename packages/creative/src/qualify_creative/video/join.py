"""Join a video's parts into one MP4 (VE-07, epic «Video por partes», ADR 44 F2): the
local, deterministic join — what the owner approved part by part is exactly what gets
published, at no vendor cost (design `docs/diseno-video-por-planos.md` §5, option A).

Each part is cut to its interval, cover-cropped and scaled to the target size, resampled
to one common frame rate and laid end to end; the brand's layer (logo) goes over the
whole join once. Its sound is decoded, resampled to 48 kHz stereo and re-encoded as ONE
AAC stream, with a short fade at every cut so a hard cut does not click. A part without a
soundtrack (Seedance without `generate_audio`, a stock clip) gets synthetic silence of its
exact length, so the next part's sound never slides earlier.

Synchrony across up to six cuts (risk N6): every part's sound is placed by counting the
decoded samples from the first decoded frame — never from packet timestamps — and is cut
or padded to exactly the samples its frames last (`frames × 48000 / fps`). Since the audio
is encoded once, the AAC encoder's priming delay happens once, at the start, where the
MP4 edit list removes it; it cannot accumulate per part.

Memory (the creative worker has 512 MiB): parts are processed one after another with a
single decoder open at a time, and frames go straight from the decoder through the filter
graph to the encoder — nothing holds a part's frames. The only per-part buffer is its
sound (10 s of 48 kHz stereo float = 3.7 MiB). The MP4 is muxed straight to the caller's
path — the joined bytes never sit in memory (founder, 2026-11-04).

Done with PyAV (its wheels bundle FFmpeg with libx264 and AAC), imported lazily like
`fit.py`: production has no `ffmpeg` binary.

Transitions (EF-16, m-25026594, ADR 50 D9): a part may blend with the one before it
(`JoinClip.transition_in`) — a fade (`fundido`) or a wipe (`barrido`) of 0.3–0.8 s. The
two parts OVERLAP for that time: the last `n` frames of the part before are blended with
the first `n` frames of the part after (`n` = the duration at the common rate), so the
joined video lasts the sum of its parts minus each transition. Nothing is added or paid
for: the parts are the same seconds the owner was charged for. The sound overlaps the
same way, as an equal-power crossfade of exactly the samples those frames last, so the
synchrony rule above still holds sample for sample. A part without a transition (a cut,
`corte`) is joined exactly as before — same frames, same sound, same bytes. The blend is
done on the fitted `yuv420p` frames with numpy, in integers, never with an `xfade` graph:
one frame of each part at a time. In the 1080p final's segments (`encode_transition`, one
child per transition) only ONE decoder is open at a time: the part before's `n` fitted
frames are spooled to a raw file first.

Measured 2026-11-20 with `deploy/measure/join_memory.py` (Windows, peak working set,
`threads=1`): the whole join of 6 × 10 s 1080p H.264 parts — cuts 229 MiB / 73.5 s, five
0.5 s fades 265 MiB / 71.9 s, five 0.8 s wipes 257 MiB / 66.3 s; the final's children
on 10-bit H.265 1080p parts — a part's segment 222 MiB / 47 s, a 0.8 s transition's
247 MiB (fade) / 239 MiB (wipe), 14–16 s (it decodes the part before from its start, no
seek). Not measured on linux/arm64 nor under the worker's cgroup.
"""

from __future__ import annotations

import gc
import io
import os
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from qualify_creative.video._source import VideoSourceError, frame_rotation
from qualify_creative.video.fit import DETAIL_X264, _cover_crop, _layer_frame
from qualify_creative.video.sound import (
    AAC_BITRATE,
    CROSSFADE_S,
    LAYOUT,
    SAMPLE_RATE,
    AacWriter,
    window_chunks,
)
from qualify_creative.video.upright import upright_filters

#: The joined soundtrack: AAC-LC, 48 kHz stereo — what Instagram and Seedance both use
#: (`sound`'s, shared with the local assembly since m-25049580).
JOIN_SAMPLE_RATE = SAMPLE_RATE
JOIN_AUDIO_LAYOUT = LAYOUT
JOIN_AUDIO_BITRATE = AAC_BITRATE
#: Default output frame rate: Seedance's.
JOIN_FPS = 24
#: Default fade at every cut (design §5: «funde el audio 80 ms en cada corte»).
JOIN_CROSSFADE_S = CROSSFADE_S
#: Version of this join's recipe — recorded with the joined asset (provenance).
JOIN_VERSION = "join-v1"
#: x264 for the join: the published piece keeps its detail (`DETAIL_X264`) with a short
#: rate-control lookahead — x264 keeps that many whole frames queued, and at 1080p the
#: preset's 30 cost ~130 MiB (2026-11-04, `deploy/measure/join_memory.py` on Windows, 1
#: part: 351 → 225 MiB; `threads` changed nothing). 6×10 s 1080p in the production deps
#: image (`--target deps`, amd64, `--memory=512m`): peak RSS 274 MiB, cgroup 240 MiB —
#: under 60 % of the worker's 512 MiB. Production runs linux/arm64 and was NOT measured
#: there. VE-10a wired a join phase into the full worker harness
#: (`creative-worker-memory.sh`, `PLATFORM=linux/arm64`); its arm64 run is pending.
JOIN_X264 = {**DETAIL_X264, "rc-lookahead": "10"}
#: A frame time this close to a target tick counts as that tick (float noise).
_TICK_EPSILON = 1e-4


class JoinError(ValueError):
    """A part cannot be joined (no video stream, empty interval, nothing decodable)."""


#: EF-16: how long a transition between two parts lasts (the ticket: 0,3–0,8 s).
TRANSITION_MIN_S = 0.3
TRANSITION_MAX_S = 0.8
TransitionKind = Literal["fade", "wipe"]
#: Where a wipe's edge travels: `left` = the next part comes in from the right edge.
WipeDirection = Literal["left", "right", "up", "down"]
WIPE_DIRECTIONS: tuple[str, ...] = ("left", "right", "up", "down")


@dataclass(frozen=True)
class JoinTransition:
    """How a part blends with the part before it (EF-16): a `fade` (the library's
    `fundido`) or a `wipe` (`barrido`, toward `direction`) lasting `duration_s`, during
    which the two parts overlap. A cut (`corte`) is no transition: None."""

    kind: TransitionKind
    duration_s: float
    direction: WipeDirection = "left"
    #: The library entry it came from, `(effect_id, version)` — provenance only: not part
    #: of what the join draws (not compared, not in the child's spec).
    source: tuple[str, int] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.kind not in ("fade", "wipe"):
            raise JoinError(f"unknown transition {self.kind!r}")
        if not TRANSITION_MIN_S - 1e-9 <= self.duration_s <= TRANSITION_MAX_S + 1e-9:
            raise JoinError(
                f"a transition lasts {TRANSITION_MIN_S}–{TRANSITION_MAX_S} s, not {self.duration_s}"
            )
        if self.direction not in WIPE_DIRECTIONS:
            raise JoinError(f"unknown wipe direction {self.direction!r}")

    def frames(self, rate: int | Fraction) -> int:
        """How many output frames the two parts overlap at `rate` (at least one)."""
        return max(1, round(self.duration_s * Fraction(rate)))

    def as_spec(self) -> dict[str, Any]:
        """A JSON-safe record (the child's spec, provenance and fingerprints)."""
        return {"kind": self.kind, "duration_s": self.duration_s, "direction": self.direction}

    @classmethod
    def from_spec(cls, spec: Any) -> JoinTransition | None:
        """`as_spec` back; None for None (a cut)."""
        if spec is None:
            return None
        return cls(
            kind=spec["kind"],
            duration_s=float(spec["duration_s"]),
            direction=spec.get("direction", "left"),
        )


@dataclass(frozen=True)
class JoinClip:
    """One part: its MP4 on disk and the interval to keep, in seconds from its first
    video frame. `end_s=None` keeps it to its end; an `end_s` past the end is cut to it.
    `transition_in` (EF-16): how it blends with the part before it — None is a cut."""

    path: Path
    start_s: float = 0.0
    end_s: float | None = None
    transition_in: JoinTransition | None = None

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise JoinError(f"a part cannot start before 0 s ({self.start_s})")
        if self.end_s is not None and self.end_s <= self.start_s:
            raise JoinError(f"empty interval {self.start_s}–{self.end_s} s")


def _overlaps(clips: Sequence[JoinClip], rate: Fraction) -> list[int]:
    """The frames each part overlaps the one before it (0 = a cut, and always 0 for the
    first part, which has nothing before it to blend with: a `JoinError`)."""
    if clips and clips[0].transition_in is not None:
        raise JoinError("the first part has no part before it to blend with")
    return [0 if c.transition_in is None else c.transition_in.frames(rate) for c in clips]


def _check_room(name: str, frames: int, overlap_in: int, overlap_out: int) -> None:
    """A part must last at least the transitions that eat into it, or two would cross."""
    if overlap_in + overlap_out > frames:
        raise JoinError(
            f"{name} lasts {frames} frames, shorter than its transitions "
            f"({overlap_in} + {overlap_out})"
        )


def _transition_samples(frames: int, rate: Fraction) -> int:
    """The samples `frames` overlapped frames last — the sound overlaps exactly as long."""
    return round(frames * JOIN_SAMPLE_RATE / rate)


def _crossfade(np: Any, tail: Any, head: Any) -> Any:
    """Equal-power crossfade of two (2, n) float32 sounds: the part before fades out as
    the part after fades in, with no dip in loudness for two unrelated sounds."""
    n = tail.shape[1]
    ramp = (np.arange(n, dtype=np.float32) + 0.5) / max(n, 1)
    fade_in = np.sin(ramp * (np.pi / 2)).astype(np.float32)
    fade_out = np.cos(ramp * (np.pi / 2)).astype(np.float32)
    return (tail * fade_out + head * fade_in).astype(np.float32)


def _blend(av: Any, np: Any, before: Any, after: Any, step: int, steps: int, how: Any) -> Any:
    """Overlapped frame `step` of `steps` (0-based): `before`'s picture blended into
    `after`'s, both fitted `yuv420p` frames of the same size. A fade mixes the planes
    by the progress; a wipe shows `after` on the side its edge has uncovered. Returns a
    new frame (the inputs are left as they are)."""
    width, height = before.width, before.height
    progress = (step + 1) / (steps + 1)  # never all of one part: both show in every frame
    a = before.to_ndarray()  # (height * 3 / 2, width): Y, then U, then V, flat
    b = after.to_ndarray()
    if how.kind == "fade":
        # integer weights out of 256, in place in two uint16 buffers: a float32 mix made
        # ~60 MiB of temporaries per 1080p frame (measured, `deploy/measure/join_memory.py`)
        weight = round(progress * 256)
        mixed = a.astype(np.uint16)
        mixed *= 256 - weight
        other = b.astype(np.uint16)
        other *= weight
        mixed += other
        del other
        mixed += 128  # round to nearest: at most 255 × 256 + 128, inside uint16
        mixed >>= 8
        out = mixed.astype(np.uint8)
    else:
        out = a.copy()
        flat_out, flat_b = out.reshape(-1), b.reshape(-1)
        luma = width * height
        chroma = (width // 2) * (height // 2)
        planes = (
            (0, width, height),
            (luma, width // 2, height // 2),
            (luma + chroma, width // 2, height // 2),
        )
        for offset, w, h in planes:
            target = flat_out[offset : offset + w * h].reshape(h, w)
            source = flat_b[offset : offset + w * h].reshape(h, w)
            if how.direction in ("left", "right"):
                edge = round(width // 2 * progress) * (w // (width // 2))  # luma = 2 × chroma
                cols = slice(w - edge, w) if how.direction == "left" else slice(0, edge)
                target[:, cols] = source[:, cols]
            else:
                edge = round(height // 2 * progress) * (h // (height // 2))
                rows = slice(h - edge, h) if how.direction == "up" else slice(0, edge)
                target[rows, :] = source[rows, :]
    frame = av.VideoFrame.from_ndarray(out, format="yuv420p")
    return frame


@dataclass(frozen=True)
class JoinedVideo:
    """The joined MP4 on disk and what the piece records about it (provenance)."""

    path: Path
    width: int
    height: int
    fps: Fraction
    frames: int
    duration_sec: float
    #: The first frame as joined (logo included), JPEG — the piece's thumbnail.
    poster: bytes | None
    content_type: str = "video/mp4"
    version: str = JOIN_VERSION


def join_clips(
    clips: Sequence[JoinClip],
    *,
    out: Path,
    size: tuple[int, int],
    fps: int | Fraction = JOIN_FPS,
    overlay: bytes | None = None,
    crossfade_audio_s: float = JOIN_CROSSFADE_S,
    threads: int | None = None,
) -> JoinedVideo:
    """The parts in order as one H.264 `yuv420p` + AAC 48 kHz stereo MP4 at `size` and
    `fps`, `+faststart`, written to `out`. `overlay`: a transparent PNG (the brand's
    layer) laid over every frame. Always exactly one audio track, silent where a part had
    none. Encoded beside `out` and renamed into place at the end: a failed join leaves no
    file and never replaces one already at `out`.

    `threads` (VE-10b): when set, every decoder and the x264 encoder run with at most that
    many threads (slice threading: no frame queued per thread) and each part's decoder,
    filter graph and frames are collected before the next part opens — the creative
    worker's 1080p final join runs with 1 (`cpus: 1.0`). None keeps FFmpeg's defaults
    (VE-07's behaviour for every other caller)."""
    width, height = size
    if width % 2 or height % 2:
        raise JoinError(f"an H.264 video needs even dimensions, not {width}×{height}")
    if not clips:
        raise JoinError("nothing to join")
    rate = Fraction(fps)
    if not 1 <= rate <= 120:
        raise JoinError(f"implausible frame rate {fps}")
    if crossfade_audio_s < 0:
        raise JoinError("the fade cannot be negative")
    out = Path(out)
    # unique per call: two joins aimed at the same `out` never write the same file
    partial = out.with_name(f".{out.name}.{uuid.uuid4().hex}.partial.mp4")
    try:
        frames, poster = _join(clips, partial, size, rate, overlay, crossfade_audio_s, threads)
        os.replace(partial, out)
    finally:
        partial.unlink(missing_ok=True)
    return JoinedVideo(
        path=out,
        width=width,
        height=height,
        fps=rate,
        frames=frames,
        duration_sec=float(frames / rate),
        poster=poster,
    )


@dataclass(frozen=True)
class _Span:
    """A part's video timeline: when its first frame is shown (`origin`, absolute
    seconds) and how long its picture lasts from there."""

    origin: float
    length: float


def _probe(av: Any, path: Path) -> _Span:
    """The picture's span, from packet timestamps alone — demuxed, never decoded."""
    with av.open(str(path)) as source:
        if not source.streams.video:
            raise JoinError(f"{path.name} has no video stream")
        stream = source.streams.video[0]
        base = stream.time_base
        first: int | None = None
        last_end: int | None = None
        for packet in source.demux(stream):
            if packet.pts is None:
                continue
            duration = packet.duration or 0
            first = packet.pts if first is None else min(first, packet.pts)
            end = packet.pts + duration
            last_end = end if last_end is None else max(last_end, end)
        if first is None or last_end is None:
            raise JoinError(f"{path.name} has no video frames")
        length = float((last_end - first) * base)
        if length <= 0:
            # one frame whose packet carries no duration: a frame of the source's rate
            from qualify_creative.video.fit import _frame_rate  # noqa: PLC0415

            length = float(1 / _frame_rate(stream))
        return _Span(origin=float(first * base), length=length)


def _part_frames(clip: JoinClip, span: _Span, rate: Fraction) -> int:
    """How many output frames the part gets: its kept interval at the common rate."""
    available = span.length - clip.start_s
    if available <= 0:
        raise JoinError(f"{clip.path.name} ends before {clip.start_s} s")
    end = available if clip.end_s is None else min(clip.end_s - clip.start_s, available)
    frames = round(end * rate)
    if frames < 1:
        raise JoinError(f"{clip.path.name}: the interval is shorter than one frame")
    return frames


def _bound(context: Any, threads: int) -> None:
    """At most `threads` codec threads, slice-threaded (VE-10b): frame threading keeps
    a whole frame in flight per thread, which at 1080p 10-bit is what the worker's cap
    cannot spare."""
    context.thread_count = threads
    context.thread_type = "SLICE"


def _part_audio(
    av: Any,
    np: Any,
    clip: JoinClip,
    span: _Span,
    samples: int,
    fade: tuple[int, int],
    threads: int | None = None,
) -> Any:
    """The part's sound for its kept interval as a (2, `samples`) float32 array at
    48 kHz stereo — silence where the part has none, before its sound starts or after it
    ends. Placed by counting decoded samples from the first decoded audio frame (risk N6).
    `fade`: samples of fade-in at its start and of fade-out at its end."""
    # the window, placed by `sound.window_chunks` (m-25049580: shared with the local
    # assembly) — mono copied to both sides at its own level, 5.1 downmixed
    sound = np.zeros((2, samples), dtype=np.float32)
    position = 0
    for chunk in window_chunks(
        clip.path,
        at_s=span.origin + clip.start_s,
        samples=samples,
        fallback_first_s=span.origin,
        threads=threads,
    ):
        sound[:, position : position + chunk.shape[1]] = chunk
        position += chunk.shape[1]
    fade_in, fade_out = fade
    if fade_in:
        sound[:, :fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out:
        sound[:, samples - fade_out :] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    return sound


def _join(
    clips: Sequence[JoinClip],
    out: Path,
    size: tuple[int, int],
    rate: Fraction,
    overlay: bytes | None,
    crossfade_s: float,
    threads: int | None = None,
) -> tuple[int, bytes | None]:
    import av  # noqa: PLC0415 — lazy: only a joined video needs it
    import numpy as np  # noqa: PLC0415

    width, height = size
    tick = 1 / rate
    total = 0  # output frames written
    poster: list[bytes] = []
    with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        video_out = sink.add_stream("libx264", rate=rate)
        video_out.width, video_out.height = width, height
        video_out.pix_fmt = "yuv420p"
        video_out.options = dict(JOIN_X264)
        if threads is not None:
            video_out.options = {**video_out.options, "threads": str(threads)}
            _bound(video_out.codec_context, threads)
        video_out.codec_context.time_base = tick
        sound_out = AacWriter(av, sink)  # the sound not yet handed to AAC waits there

        def emit(frame: Any) -> None:
            nonlocal total
            if not poster:
                jpeg = io.BytesIO()
                # already upright: `_part_video`'s graph turned the pixels (EF-01). The
                # frame still carries the source's display matrix, so `upright_image`
                # here would turn it a second time.
                frame.to_image().save(jpeg, format="JPEG", quality=90)
                poster.append(jpeg.getvalue())
            frame.pts = total  # one tick per frame: unstamped frames all land at 0
            frame.time_base = tick
            for packet in video_out.encode(frame):
                sink.mux(packet)
            total += 1

        overlaps = _overlaps(clips, rate)
        if not any(overlaps):
            # only cuts: exactly the join before EF-16, part after part (same bytes)
            _cut_parts(av, np, clips, size, rate, overlay, crossfade_s, threads, emit, sound_out)
        else:
            _blended_parts(
                av, np, clips, overlaps, size, rate, overlay, crossfade_s, threads, emit, sound_out
            )

        sound_out.finish()
        for packet in video_out.encode():
            sink.mux(packet)
    return total, (poster[0] if poster else None)


def _joined_wrong(index: int, clip: JoinClip, error: BaseException) -> JoinError:
    """A missing or corrupt part: one typed error, naming it (the cause is chained)."""
    return JoinError(f"part {index + 1} ({clip.path.name}) could not be joined: {error}")


def _cut_parts(
    av: Any,
    np: Any,
    clips: Sequence[JoinClip],
    size: tuple[int, int],
    rate: Fraction,
    overlay: bytes | None,
    crossfade_s: float,
    threads: int | None,
    emit: Any,
    sound_out: AacWriter,
) -> None:
    """Every part after the other with a hard cut (VE-07, unchanged by EF-16): its sound
    with half the cut's fade at each edge that meets another part, then its frames."""
    half_fade = round(crossfade_s / 2 * JOIN_SAMPLE_RATE)
    for index, clip in enumerate(clips):
        try:
            span = _probe(av, clip.path)
            frames = _part_frames(clip, span, rate)
            samples = round(frames * JOIN_SAMPLE_RATE / rate)
            fade = (
                min(half_fade, samples) if index > 0 else 0,
                min(half_fade, samples) if index < len(clips) - 1 else 0,
            )
            sound_out.add(_part_audio(av, np, clip, span, samples, fade, threads))
            _part_video(av, clip, span, frames, size, rate, overlay, emit, threads)
            if threads is not None:
                gc.collect()  # this part's decoder, graph and frames, before the next
        except JoinError:
            raise
        except (OSError, av.error.FFmpegError) as error:
            raise _joined_wrong(index, clip, error) from error


def _take_frame(frames: Iterator[Any], clip: JoinClip) -> Any:
    try:
        return next(frames)
    except StopIteration:  # `_part_video_frames` yields exactly its count: never expected
        raise JoinError(f"{clip.path.name}: fewer frames than its interval") from None


def _blended_parts(
    av: Any,
    np: Any,
    clips: Sequence[JoinClip],
    overlaps: Sequence[int],
    size: tuple[int, int],
    rate: Fraction,
    overlay: bytes | None,
    crossfade_s: float,
    threads: int | None,
    emit: Any,
    sound_out: AacWriter,
) -> None:
    """EF-16: the parts with at least one transition. Each part's frames that no
    transition touches go out as in a cut; where part `i + 1` blends in, the last `n`
    frames of part `i` and the first `n` of part `i + 1` are read side by side (two
    decoders open for those `n` frames only) and blended (`_blend`). The sound: the
    samples those frames last are crossfaded (`_crossfade`); a cut keeps its short
    fade. Every count is known before decoding (`_probe`), so a part too short for its
    transitions is refused before anything is encoded."""
    spans: list[_Span] = []
    counts: list[int] = []
    for index, clip in enumerate(clips):
        try:
            span = _probe(av, clip.path)
            frames = _part_frames(clip, span, rate)
        except JoinError:
            raise
        except (OSError, av.error.FFmpegError) as error:
            raise _joined_wrong(index, clip, error) from error
        spans.append(span)
        counts.append(frames)
    last = len(clips) - 1
    after = [*overlaps[1:], 0]  # the frames each part overlaps the next one
    for index, clip in enumerate(clips):
        name = f"part {index + 1} ({clip.path.name})"
        _check_room(name, counts[index], overlaps[index], after[index])

    half_fade = round(crossfade_s / 2 * JOIN_SAMPLE_RATE)
    tail: Any = None  # the part before's last samples, crossfaded into this part's first
    current: Iterator[Any] | None = None  # this part's frames, opened by its transition
    nxt: Iterator[Any] | None = None  # the next part's, while a transition reads it
    try:
        for index, clip in enumerate(clips):
            try:
                frames, n_in, n_out = counts[index], overlaps[index], after[index]
                samples = round(frames * JOIN_SAMPLE_RATE / rate)
                # the samples the part before kept for this crossfade (its own clamp)
                t_in = min(tail.shape[1], samples) if n_in else 0
                t_out = min(_transition_samples(n_out, rate), samples - t_in) if n_out else 0
                fade = (
                    min(half_fade, samples) if index > 0 and not n_in else 0,
                    min(half_fade, samples) if index < last and not n_out else 0,
                )
                sound = _part_audio(av, np, clip, spans[index], samples, fade, threads)
                if n_in:
                    sound_out.add(_crossfade(np, tail, sound[:, :t_in]))
                sound_out.add(sound[:, t_in : samples - t_out])
                tail = sound[:, samples - t_out :].copy() if n_out else None
                del sound
                if current is None:
                    current = _part_video_frames(
                        av, clip, spans[index], frames, size, rate, overlay, threads
                    )
                for _ in range(frames - n_in - n_out):
                    emit(_take_frame(current, clip))
                if n_out:
                    following = clips[index + 1]
                    how = following.transition_in
                    nxt = _part_video_frames(
                        av,
                        following,
                        spans[index + 1],
                        counts[index + 1],
                        size,
                        rate,
                        overlay,
                        threads,
                    )
                    for step in range(n_out):
                        picture = _blend(
                            av,
                            np,
                            _take_frame(current, clip),
                            _take_frame(nxt, following),
                            step,
                            n_out,
                            how,
                        )
                        emit(picture)
                    current.close()
                    current, nxt = nxt, None
                else:
                    current.close()
                    current = None
                if threads is not None:
                    gc.collect()  # this part's decoder, graph and frames, before the next
            except JoinError:
                raise
            except (OSError, av.error.FFmpegError) as error:
                raise _joined_wrong(index, clip, error) from error
    finally:
        for opened in (current, nxt):
            if opened is not None:
                opened.close()  # its file, even when a part failed half way


def _part_rotation(av: Any, clip: JoinClip, threads: int | None = None) -> int:
    """The part's display rotation (EF-01): its first decoded frame's, as `fit` reads it
    (`frame_rotation`: 0/90/180/270). 0 when nothing decodes — `_part_video` then fails on
    that as before. A turn that is not a right angle is the part's fault: a `JoinError`."""
    with av.open(str(clip.path)) as source:
        stream = source.streams.video[0]
        if threads is not None:
            _bound(stream.codec_context, threads)
        try:
            for frame in source.decode(stream):
                return frame_rotation(frame)
        except VideoSourceError as error:
            raise JoinError(f"{clip.path.name}: {error}") from error
    return 0


def _part_video(
    av: Any,
    clip: JoinClip,
    span: _Span,
    frames: int,
    size: tuple[int, int],
    rate: Fraction,
    overlay: bytes | None,
    emit: Any,
    threads: int | None = None,
) -> None:
    """Decode the part once and hand `frames` output frames to `emit`, each the source
    frame shown at that tick of the common rate (repeated or dropped as the rates
    differ), cover-cropped and scaled to `size`, with `overlay` on top
    (`_part_video_frames`, consumed whole)."""
    for frame in _part_video_frames(av, clip, span, frames, size, rate, overlay, threads):
        emit(frame)


def _part_video_frames(
    av: Any,
    clip: JoinClip,
    span: _Span,
    frames: int,
    size: tuple[int, int],
    rate: Fraction,
    overlay: bytes | None,
    threads: int | None = None,
) -> Iterator[Any]:
    """Decode the part once and yield `frames` output frames, each the source frame
    shown at that tick of the common rate (repeated or dropped as the rates differ),
    cover-cropped and scaled to `size`, with `overlay` on top. A generator (EF-16): a
    transition reads the tail of one part and the head of the next side by side; closing
    it early closes the part's file.

    Upright (EF-01): a phone part's display rotation is applied first in the graph
    (`upright_filters`, FFmpeg's `transpose` in YUV), so the crop and the scale work on
    the size a player shows. A part without one gets exactly the graph it had before."""
    width, height = size
    start = clip.start_s
    stop = start + frames / rate  # the kept interval, relative to the first frame
    turn_filters = upright_filters(_part_rotation(av, clip, threads))
    with av.open(str(clip.path)) as source:
        stream = source.streams.video[0]
        if threads is not None:
            _bound(stream.codec_context, threads)
        base = stream.time_base
        graph = av.filter.Graph()
        video_in = graph.add_buffer(template=stream)
        crop = graph.add("crop", _cover_crop(width, height))
        scale = graph.add("scale", f"{width}:{height}")
        to_yuv = graph.add("format", "yuv420p")
        sink = graph.add("buffersink")
        head = video_in
        for spec in turn_filters:
            name, _, args = spec.partition("=")
            turn = graph.add(name, args or None)
            head.link_to(turn)
            head = turn
        head.link_to(crop)
        crop.link_to(scale)
        last = scale
        layer_in = None
        if overlay is not None:
            layer_in = graph.add(
                "buffer",
                f"video_size={width}x{height}:pix_fmt=rgba"
                f":time_base={base.numerator}/{base.denominator}:pixel_aspect=1/1",
            )
            over = graph.add("overlay", "x=0:y=0:format=auto:eof_action=repeat")
            last.link_to(over, 0, 0)
            layer_in.link_to(over, 0, 1)
            last = over
        last.link_to(to_yuv)
        to_yuv.link_to(sink)
        graph.configure()
        if layer_in is not None:
            layer = _layer_frame(av, overlay, size)
            # stamped no later than the first frame, so it is there from frame one
            layer.pts = min(0, round(span.origin / base))
            layer.time_base = base
            layer_in.push(layer)
            layer_in.push(None)

        written = 0
        shown: Any = None  # the last fitted frame, shown until the next one's time

        def offer(frame: Any) -> Iterator[Any]:
            nonlocal written, shown
            moment = float(frame.time) - span.origin
            while written < frames and start + written / rate < moment - _TICK_EPSILON:
                yield shown if shown is not None else frame
                written += 1
            shown = frame

        def drain() -> Iterator[Any]:
            while True:
                try:
                    fitted = sink.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    return
                yield from offer(fitted)

        before: Any = None  # the latest frame before the interval: shown at its start
        for frame in source.decode(stream):
            if frame.time is None:
                continue
            moment = float(frame.time) - span.origin
            if moment < start - _TICK_EPSILON:
                before = frame
                continue
            if before is not None:
                video_in.push(before)
                before = None
            if moment >= stop - _TICK_EPSILON:
                break
            video_in.push(frame)
            yield from drain()
        if before is not None:  # the whole interval sits inside the last frame
            video_in.push(before)
        video_in.push(None)
        yield from drain()
        if shown is None:
            raise JoinError(f"{clip.path.name}: no decodable frame in its interval")
        while written < frames:
            yield shown
            written += 1


# ---------------------------------------------------------------------------
# VE-10b (m-24921068): the join in segments — one part encoded per child process, then
# the segments laid end to end by stream copy

#: Version of the segment recipe (in a segment's fingerprint and the final's provenance).
JOIN_SEGMENT_VERSION = "join-segment-v1"
#: x264 for a segment: the join's settings, plus what lets N segments be laid end to end
#: by stream copy as ONE H.264 track — the same profile and level in every one (so one
#: SPS/PPS serves all), a closed, fixed GOP (2 s at 24 fps) and no scene-cut keyframes,
#: so every segment starts with an IDR frame and none refers to another.
#: Lookahead 0 and crf 17 (Deivid, 2026-11-07): no frames queued in the encoder (the
#: 768 MiB worker, 1080p) and one crf step down to spend back what mb-tree gave —
#: measured against lookahead 10 / crf 18 on 6 × 10 s 1080p: worker peak 445.6 MiB
#: (58 %) and +0.03 dB PSNR / −0.0022 SSIM (§2.7 of the VE-10b hand-over).
JOIN_SEGMENT_X264 = {
    **JOIN_X264,
    "crf": "17",
    "rc-lookahead": "0",
    "profile": "high",
    "level": "4.0",
    "x264-params": "open-gop=0:keyint=48:min-keyint=48:scenecut=0",
}
#: Overrides the segments' x264 lookahead (`rc-lookahead`, frames kept queued: memory
#: at 1080p) — unset, the segments' 0. For measuring only (Deivid, 2026-11-07); it is in
#: the segment fingerprint, so segments made with another lookahead are never mixed.
SEGMENT_LOOKAHEAD_ENV = "QUALIFY_JOIN_SEGMENT_LOOKAHEAD"


def segment_lookahead() -> str:
    """The segments' x264 lookahead now: the override when it is a whole number >= 0,
    else `JOIN_SEGMENT_X264`'s."""
    raw = os.getenv(SEGMENT_LOOKAHEAD_ENV, "").strip()
    if raw.isdigit():
        return str(int(raw))
    return JOIN_SEGMENT_X264["rc-lookahead"]


#: Overrides the segments' x264 CRF (0-51) — unset, the segments' 17. For measuring only
#: (Deivid, 2026-11-07: lookahead 0 drops mb-tree; a lower CRF spends the bits back).
#: In the segment fingerprint too.
SEGMENT_CRF_ENV = "QUALIFY_JOIN_SEGMENT_CRF"


def segment_crf() -> str:
    """The segments' x264 CRF now: the override when it is a whole number 0-51, else
    `JOIN_SEGMENT_X264`'s."""
    raw = os.getenv(SEGMENT_CRF_ENV, "").strip()
    if raw.isdigit() and 0 <= int(raw) <= 51:
        return str(int(raw))
    return JOIN_SEGMENT_X264["crf"]


def segment_x264() -> dict[str, str]:
    """`JOIN_SEGMENT_X264` with the lookahead and CRF in force (`segment_lookahead`,
    `segment_crf`)."""
    return {**JOIN_SEGMENT_X264, "rc-lookahead": segment_lookahead(), "crf": segment_crf()}


@dataclass(frozen=True)
class JoinSegment:
    """One part encoded on its own: a video-only H.264 MP4 (`path`) and its sound as raw
    48 kHz stereo float32, interleaved (`pcm`), of EXACTLY `frames` and `samples`."""

    path: Path
    pcm: Path
    frames: int
    samples: int
    poster: bytes | None = None


def encode_segment(
    clip: JoinClip,
    *,
    out: Path,
    pcm_out: Path,
    size: tuple[int, int],
    fps: int | Fraction = JOIN_FPS,
    overlay: bytes | None = None,
    fade_in: bool = False,
    fade_out: bool = False,
    crossfade_audio_s: float = JOIN_CROSSFADE_S,
    threads: int | None = None,
    poster: bool = False,
    drop_head: int = 0,
    drop_tail: int = 0,
) -> JoinSegment:
    """ONE part as `join_clips` would lay it in the joined video — cut to its interval,
    cover-cropped and scaled to `size`, `overlay` on every frame — encoded as a video-only
    segment with `JOIN_SEGMENT_X264`, and its sound as the exact samples its frames last
    (`frames × 48000 / fps`), with half the cut's fade at each edge that meets another
    part (`fade_in` / `fade_out`, as `join_clips` fades them). The sound is NOT encoded
    here: `concat_segments` encodes the whole soundtrack once, so the AAC encoder's
    priming happens once and never accumulates per cut (risk N6). Written beside `out`
    and renamed into place: a failure leaves neither file.

    EF-16: `drop_head` / `drop_tail` leave out the frames a transition overlaps with the
    part before / after (and the samples they last): those go in the transition's own
    segment (`encode_transition`). An edge with a transition has no cut fade."""
    import av  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    _even(size)
    rate = Fraction(fps)
    out, pcm_out = Path(out), Path(pcm_out)
    partial = out.with_name(f".{out.name}.{uuid.uuid4().hex}.partial.mp4")
    pcm_partial = pcm_out.with_name(f".{pcm_out.name}.{uuid.uuid4().hex}.partial")
    written = 0
    samples = 0
    picture: bytes | None = None
    try:
        try:
            span = _probe(av, clip.path)
            frames = _part_frames(clip, span, rate)
            _check_room(clip.path.name, frames, drop_head, drop_tail)
            samples = round(frames * JOIN_SAMPLE_RATE / rate)
            half = round(crossfade_audio_s / 2 * JOIN_SAMPLE_RATE)
            fade = (min(half, samples) if fade_in else 0, min(half, samples) if fade_out else 0)
            sound = _part_audio(av, np, clip, span, samples, fade, threads)
            if drop_head or drop_tail:
                head = _transition_samples(drop_head, rate) if drop_head else 0
                tail = min(_transition_samples(drop_tail, rate), samples - head) if drop_tail else 0
                sound = sound[:, head : samples - tail]
                samples -= head + tail
            np.ascontiguousarray(sound.T, dtype="<f4").tofile(pcm_partial)
            del sound
            pictures: Iterator[Any] = _part_video_frames(
                av, clip, span, frames, size, rate, overlay, threads
            )
            if drop_head or drop_tail:
                pictures = _middle(
                    pictures, clip, skip=drop_head, keep=frames - drop_head - drop_tail
                )
            written, picture = _write_segment(av, partial, size, rate, threads, pictures, poster)
        except JoinError:
            raise
        except (OSError, av.error.FFmpegError) as error:
            raise JoinError(f"{clip.path.name} could not be encoded: {error}") from error
        os.replace(partial, out)
        os.replace(pcm_partial, pcm_out)
    finally:
        partial.unlink(missing_ok=True)
        pcm_partial.unlink(missing_ok=True)
    return JoinSegment(out, pcm_out, written, samples, picture)


def _even(size: tuple[int, int]) -> None:
    width, height = size
    if width % 2 or height % 2:
        raise JoinError(f"an H.264 video needs even dimensions, not {width}×{height}")


def _middle(frames: Iterator[Any], clip: JoinClip, *, skip: int, keep: int) -> Iterator[Any]:
    """`keep` frames after the first `skip` — then the part's file is closed."""
    try:
        for _ in range(skip):
            _take_frame(frames, clip)
        for _ in range(keep):
            yield _take_frame(frames, clip)
    finally:
        _close(frames)


def _close(frames: Iterator[Any]) -> None:
    close = getattr(frames, "close", None)
    if callable(close):
        close()


def _write_segment(
    av: Any,
    path: Path,
    size: tuple[int, int],
    rate: Fraction,
    threads: int | None,
    pictures: Iterator[Any],
    poster: bool,
) -> tuple[int, bytes | None]:
    """Encode `pictures` as a video-only segment at `path` (`segment_x264`: closed GOP,
    the same profile and level as every other segment, so they lay end to end by stream
    copy). Returns the frames written and, with `poster`, the first one as JPEG."""
    try:
        return _encode_pictures(av, path, size, rate, threads, pictures, poster)
    finally:
        _close(pictures)  # the parts' files, also when the encode failed half way


def _encode_pictures(
    av: Any,
    path: Path,
    size: tuple[int, int],
    rate: Fraction,
    threads: int | None,
    pictures: Iterator[Any],
    poster: bool,
) -> tuple[int, bytes | None]:
    width, height = size
    tick = 1 / rate
    written = 0
    first: bytes | None = None
    with av.open(str(path), mode="w", format="mp4") as sink:
        video_out = sink.add_stream("libx264", rate=rate)
        video_out.width, video_out.height = width, height
        video_out.pix_fmt = "yuv420p"
        video_out.options = segment_x264()
        if threads is not None:
            video_out.options = {**video_out.options, "threads": str(threads)}
            _bound(video_out.codec_context, threads)
        video_out.codec_context.time_base = tick
        for frame in pictures:
            if poster and first is None:
                jpeg = io.BytesIO()
                # already upright from `_part_video_frames`'s graph (see `_join`'s emit)
                frame.to_image().save(jpeg, format="JPEG", quality=90)
                first = jpeg.getvalue()
            frame.pts = written
            frame.time_base = tick
            for packet in video_out.encode(frame):
                sink.mux(packet)
            written += 1
        for packet in video_out.encode():
            sink.mux(packet)
    return written, first


def encode_transition(
    before: JoinClip,
    after: JoinClip,
    *,
    out: Path,
    pcm_out: Path,
    size: tuple[int, int],
    fps: int | Fraction = JOIN_FPS,
    overlay: bytes | None = None,
    threads: int | None = None,
) -> JoinSegment:
    """EF-16: the segment of the transition between two parts (`after.transition_in`):
    the last `n` frames of `before` blended with the first `n` of `after`, as
    `join_clips` blends them, and the samples those frames last, crossfaded. It sits in
    the joined video between `before`'s segment (made with `drop_tail=n`) and `after`'s
    (`drop_head=n`), so the video lasts the sum of the parts minus `n` frames. Encoded
    like any segment (`_write_segment`); written beside `out` and renamed into place."""
    import av  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    how = after.transition_in
    if how is None:
        raise JoinError("a transition segment needs the part after to have a transition")
    _even(size)
    rate = Fraction(fps)
    n = how.frames(rate)
    out, pcm_out = Path(out), Path(pcm_out)
    partial = out.with_name(f".{out.name}.{uuid.uuid4().hex}.partial.mp4")
    pcm_partial = pcm_out.with_name(f".{pcm_out.name}.{uuid.uuid4().hex}.partial")
    spool = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tail.yuv")
    samples = _transition_samples(n, rate)
    written = 0
    try:
        try:
            span_b, span_a = _probe(av, before.path), _probe(av, after.path)
            frames_b = _part_frames(before, span_b, rate)
            frames_a = _part_frames(after, span_a, rate)
            _check_room(before.path.name, frames_b, 0, n)
            _check_room(after.path.name, frames_a, n, 0)
            whole_b = round(frames_b * JOIN_SAMPLE_RATE / rate)
            whole_a = round(frames_a * JOIN_SAMPLE_RATE / rate)
            samples = min(samples, whole_b, whole_a)
            tail = _part_audio(av, np, before, span_b, whole_b, (0, 0), threads)
            tail = tail[:, whole_b - samples :].copy()
            head = _part_audio(av, np, after, span_a, whole_a, (0, 0), threads)
            head = head[:, :samples].copy()
            sound = _crossfade(np, tail, head)
            np.ascontiguousarray(sound.T, dtype="<f4").tofile(pcm_partial)
            del sound, tail, head
            # the part before from its first overlapped frame: its earlier frames are
            # decoded (no seek) but never fitted
            last = JoinClip(
                before.path,
                start_s=before.start_s + (frames_b - n) / rate,
                end_s=before.start_s + frames_b / rate,
            )
            # ONE decoder at a time (a 1080p 10-bit H.265 decoder is ~70 MiB): the part
            # before's `n` fitted frames go to a raw file beside `out`, its decoder is
            # closed, then the part after is decoded and blended frame by frame with them
            _spool(av, _part_video_frames(av, last, span_b, n, size, rate, overlay, threads), spool)
            if threads is not None:
                gc.collect()  # the part before's decoder and graph, before the next opens
            pictures = _blended(
                av,
                np,
                _unspool(av, np, spool, size, n, before),
                _part_video_frames(av, after, span_a, frames_a, size, rate, overlay, threads),
                before,
                after,
                n,
                how,
            )
            written, _ = _write_segment(av, partial, size, rate, threads, pictures, False)
        except JoinError:
            raise
        except (OSError, av.error.FFmpegError) as error:
            raise JoinError(
                f"the transition {before.path.name} → {after.path.name} could not be "
                f"encoded: {error}"
            ) from error
        os.replace(partial, out)
        os.replace(pcm_partial, pcm_out)
    finally:
        partial.unlink(missing_ok=True)
        pcm_partial.unlink(missing_ok=True)
        spool.unlink(missing_ok=True)
    return JoinSegment(out, pcm_out, written, samples, None)


def _forget_pages(handle: Any) -> None:
    """Let the kernel drop a file's cached pages (the worker's cgroup counts page cache):
    `posix_fadvise(DONTNEED)` where the platform has it. A hint, never a failure."""
    advise = getattr(os, "posix_fadvise", None)
    if advise is None:
        return
    try:
        os.fsync(handle.fileno())
        advise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    except OSError:
        pass


def _spool(av: Any, frames: Iterator[Any], path: Path) -> None:
    """Write fitted `yuv420p` frames to `path` as raw planes (Y, U, V, flat), closing the
    part's file once they are all out."""
    try:
        with path.open("wb") as handle:
            for frame in frames:
                handle.write(frame.to_ndarray().tobytes())
            handle.flush()
            _forget_pages(handle)
    finally:
        _close(frames)


def _unspool(
    av: Any, np: Any, path: Path, size: tuple[int, int], count: int, clip: JoinClip
) -> Iterator[Any]:
    """`_spool`'s frames back, one at a time."""
    width, height = size
    length = width * height * 3 // 2
    with path.open("rb") as handle:
        for _ in range(count):
            data = handle.read(length)
            if len(data) != length:
                raise JoinError(f"{clip.path.name}: fewer frames than its interval")
            planes = np.frombuffer(data, dtype=np.uint8).reshape(height * 3 // 2, width)
            yield av.VideoFrame.from_ndarray(planes, format="yuv420p")
        _forget_pages(handle)


def _blended(
    av: Any,
    np: Any,
    tail: Iterator[Any],
    head: Iterator[Any],
    before: JoinClip,
    after: JoinClip,
    n: int,
    how: JoinTransition,
) -> Iterator[Any]:
    """The `n` overlapped frames (`_blend`), then both parts' files closed."""
    try:
        for step in range(n):
            yield _blend(av, np, _take_frame(tail, before), _take_frame(head, after), step, n, how)
    finally:
        _close(tail)
        _close(head)


def segment_frames(path: Path) -> int:
    """How many video frames a segment holds (its packets, demuxed, never decoded)."""
    import av  # noqa: PLC0415

    with av.open(str(path)) as source:
        stream = source.streams.video[0]
        return sum(1 for packet in source.demux(stream) if packet.size)


def concat_segments(
    segments: Sequence[JoinSegment],
    *,
    out: Path,
    fps: int | Fraction = JOIN_FPS,
) -> JoinedVideo:
    """The segments end to end as ONE MP4, `+faststart`, without decoding a frame: each
    segment's H.264 packets are copied with their timestamps moved by the frames before
    it (`frames / fps`, in the stream's own time base), and the segments' sound — already
    cut to the samples their frames last and faded at the cuts — is encoded ONCE as
    AAC-LC 48 kHz stereo, interleaved segment by segment. So the video lasts exactly the
    sum of the frames and the sound exactly the sum of the samples: no drift at any cut.
    Written beside `out` and renamed into place."""
    import av  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    if not segments:
        raise JoinError("nothing to join")
    rate = Fraction(fps)
    out = Path(out)
    partial = out.with_name(f".{out.name}.{uuid.uuid4().hex}.partial.mp4")
    total = 0
    width = height = 0
    try:
        with av.open(
            str(partial), mode="w", format="mp4", options={"movflags": "+faststart"}
        ) as sink:
            with av.open(str(segments[0].path)) as head:
                template = head.streams.video[0]
                base = template.time_base
                width, height = template.width, template.height
                video_out = sink.add_stream_from_template(template)
            sound_out = AacWriter(av, sink)

            for index, segment in enumerate(segments):
                sound = np.fromfile(segment.pcm, dtype="<f4")
                if sound.size != segment.samples * 2:
                    raise JoinError(f"segment {index + 1}: its sound is not its length")
                sound_out.add(sound.reshape(-1, 2).T)
                del sound
                offset = round(Fraction(total) / rate / base)
                with av.open(str(segment.path)) as source:
                    stream = source.streams.video[0]
                    if stream.time_base != base:
                        raise JoinError(f"segment {index + 1} has another time base")
                    for packet in source.demux(stream):
                        if packet.dts is None or not packet.size:
                            continue  # the demuxer's flush packet
                        if packet.pts is not None:
                            packet.pts += offset
                        packet.dts += offset
                        packet.stream = video_out
                        sink.mux(packet)
                total += segment.frames
            sound_out.finish()
        os.replace(partial, out)
    except (OSError, av.error.FFmpegError) as error:
        raise JoinError(f"the segments could not be laid end to end: {error}") from error
    finally:
        partial.unlink(missing_ok=True)
    return JoinedVideo(
        path=out,
        width=width,
        height=height,
        fps=rate,
        frames=total,
        duration_sec=float(total / rate),
        poster=segments[0].poster,
    )
