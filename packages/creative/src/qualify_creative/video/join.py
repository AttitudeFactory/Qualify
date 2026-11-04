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
"""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from qualify_creative.video.fit import DETAIL_X264, _cover_crop, _layer_frame

#: The joined soundtrack: AAC-LC, 48 kHz stereo — what Instagram and Seedance both use.
JOIN_SAMPLE_RATE = 48_000
JOIN_AUDIO_LAYOUT = "stereo"
JOIN_AUDIO_BITRATE = 128_000
#: Default output frame rate: Seedance's.
JOIN_FPS = 24
#: Default fade at every cut (design §5: «funde el audio 80 ms en cada corte»).
JOIN_CROSSFADE_S = 0.08
#: Version of this join's recipe — recorded with the joined asset (provenance).
JOIN_VERSION = "join-v1"
#: x264 for the join: the published piece keeps its detail (`DETAIL_X264`) with a short
#: rate-control lookahead — x264 keeps that many whole frames queued, and at 1080p the
#: preset's 30 cost ~130 MiB (2026-11-04, `deploy/measure/join_memory.py` on Windows, 1
#: part: 351 → 225 MiB; `threads` changed nothing). 6×10 s 1080p in the production deps
#: image (`--target deps`, amd64, `--memory=512m`): peak RSS 274 MiB, cgroup 240 MiB —
#: under 60 % of the worker's 512 MiB. Production runs linux/arm64 and was NOT measured
#: there. Not yet measured through the full worker harness
#: (`creative-worker-memory.sh`), which has no join phase until VE-10a wires it.
JOIN_X264 = {**DETAIL_X264, "rc-lookahead": "10"}
#: A frame time this close to a target tick counts as that tick (float noise).
_TICK_EPSILON = 1e-4


class JoinError(ValueError):
    """A part cannot be joined (no video stream, empty interval, nothing decodable)."""


@dataclass(frozen=True)
class JoinClip:
    """One part: its MP4 on disk and the interval to keep, in seconds from its first
    video frame. `end_s=None` keeps it to its end; an `end_s` past the end is cut to it."""

    path: Path
    start_s: float = 0.0
    end_s: float | None = None

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise JoinError(f"a part cannot start before 0 s ({self.start_s})")
        if self.end_s is not None and self.end_s <= self.start_s:
            raise JoinError(f"empty interval {self.start_s}–{self.end_s} s")


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
) -> JoinedVideo:
    """The parts in order as one H.264 `yuv420p` + AAC 48 kHz stereo MP4 at `size` and
    `fps`, `+faststart`, written to `out`. `overlay`: a transparent PNG (the brand's
    layer) laid over every frame. Always exactly one audio track, silent where a part had
    none. Encoded beside `out` and renamed into place at the end: a failed join leaves no
    file and never replaces one already at `out`."""
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
        frames, poster = _join(clips, partial, size, rate, overlay, crossfade_audio_s)
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


def _part_audio(
    av: Any, np: Any, clip: JoinClip, span: _Span, samples: int, fade: tuple[int, int]
) -> Any:
    """The part's sound for its kept interval as a (2, `samples`) float32 array at
    48 kHz stereo — silence where the part has none, before its sound starts or after it
    ends. Placed by counting decoded samples from the first decoded audio frame (risk N6).
    `fade`: samples of fade-in at its start and of fade-out at its end."""
    sound = np.zeros((2, samples), dtype=np.float32)
    with av.open(str(clip.path)) as source:
        if source.streams.audio:
            stream = source.streams.audio[0]
            # a mono track is copied to both sides at its own level (FFmpeg's upmix
            # would put it 3 dB lower than a stereo part next to it). More than two
            # channels (5.1) are downmixed by the resampler — intended for phase 1:
            # Seedance and OmniHuman parts are stereo or mono.
            mono = stream.codec_context.channels == 1
            resampler = av.AudioResampler(
                format="fltp", layout="mono" if mono else JOIN_AUDIO_LAYOUT, rate=JOIN_SAMPLE_RATE
            )
            offset = 0  # where the window starts, in decoded samples (set on frame one)
            cursor = 0  # decoded samples so far
            started = False

            def place(chunk: Any) -> None:
                nonlocal cursor
                values = chunk.to_ndarray()
                if mono:
                    values = np.repeat(values, 2, axis=0)
                count = values.shape[1]
                low = max(cursor, offset)
                high = min(cursor + count, offset + samples)
                if high > low:
                    sound[:, low - offset : high - offset] = values[:, low - cursor : high - cursor]
                cursor += count

            for frame in source.decode(stream):
                if not started:
                    started = True
                    first = frame.time if frame.time is not None else span.origin
                    offset = round((span.origin + clip.start_s - first) * JOIN_SAMPLE_RATE)
                for chunk in resampler.resample(frame):
                    place(chunk)
                if cursor >= offset + samples:
                    break
            else:
                if started:
                    for chunk in resampler.resample(None):
                        place(chunk)
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
        video_out.codec_context.time_base = tick
        audio_out = sink.add_stream("aac", rate=JOIN_SAMPLE_RATE)
        audio_out.layout = JOIN_AUDIO_LAYOUT
        audio_out.format = "fltp"
        audio_out.bit_rate = JOIN_AUDIO_BITRATE
        audio_out.codec_context.time_base = Fraction(1, JOIN_SAMPLE_RATE)
        chunk_size = audio_out.codec_context.frame_size or 1024

        pending = np.zeros((2, 0), dtype=np.float32)  # sound not yet handed to AAC
        sound_pts = 0

        def encode_sound(final: bool) -> None:
            nonlocal pending, sound_pts
            while pending.shape[1] >= chunk_size or (final and pending.shape[1]):
                take = min(chunk_size, pending.shape[1])
                frame = av.AudioFrame.from_ndarray(
                    np.ascontiguousarray(pending[:, :take]),
                    format="fltp",
                    layout=JOIN_AUDIO_LAYOUT,
                )
                frame.sample_rate = JOIN_SAMPLE_RATE
                frame.pts = sound_pts
                frame.time_base = Fraction(1, JOIN_SAMPLE_RATE)
                sound_pts += take
                pending = pending[:, take:]
                for packet in audio_out.encode(frame):
                    sink.mux(packet)

        def emit(frame: Any) -> None:
            nonlocal total
            if not poster:
                jpeg = io.BytesIO()
                frame.to_image().save(jpeg, format="JPEG", quality=90)
                poster.append(jpeg.getvalue())
            frame.pts = total  # one tick per frame: unstamped frames all land at 0
            frame.time_base = tick
            for packet in video_out.encode(frame):
                sink.mux(packet)
            total += 1

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
                sound = _part_audio(av, np, clip, span, samples, fade)
                pending = np.concatenate([pending, sound], axis=1)
                del sound
                encode_sound(final=False)
                _part_video(av, clip, span, frames, size, rate, overlay, emit)
            except JoinError:
                raise
            except (OSError, av.error.FFmpegError) as error:
                # a missing or corrupt part: one typed error, the cause kept
                raise JoinError(
                    f"part {index + 1} ({clip.path.name}) could not be joined: {error}"
                ) from error

        encode_sound(final=True)
        for packet in audio_out.encode():
            sink.mux(packet)
        for packet in video_out.encode():
            sink.mux(packet)
    return total, (poster[0] if poster else None)


def _part_video(
    av: Any,
    clip: JoinClip,
    span: _Span,
    frames: int,
    size: tuple[int, int],
    rate: Fraction,
    overlay: bytes | None,
    emit: Any,
) -> None:
    """Decode the part once and hand `frames` output frames to `emit`, each the source
    frame shown at that tick of the common rate (repeated or dropped as the rates
    differ), cover-cropped and scaled to `size`, with `overlay` on top."""
    width, height = size
    start = clip.start_s
    stop = start + frames / rate  # the kept interval, relative to the first frame
    with av.open(str(clip.path)) as source:
        stream = source.streams.video[0]
        base = stream.time_base
        graph = av.filter.Graph()
        video_in = graph.add_buffer(template=stream)
        crop = graph.add("crop", _cover_crop(width, height))
        scale = graph.add("scale", f"{width}:{height}")
        to_yuv = graph.add("format", "yuv420p")
        sink = graph.add("buffersink")
        video_in.link_to(crop)
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

        def offer(frame: Any) -> None:
            nonlocal written, shown
            moment = float(frame.time) - span.origin
            while written < frames and start + written / rate < moment - _TICK_EPSILON:
                emit(shown if shown is not None else frame)
                written += 1
            shown = frame

        def drain() -> None:
            while True:
                try:
                    fitted = sink.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    return
                offer(fitted)

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
            drain()
        if before is not None:  # the whole interval sits inside the last frame
            video_in.push(before)
        video_in.push(None)
        drain()
        if shown is None:
            raise JoinError(f"{clip.path.name}: no decodable frame in its interval")
        while written < frames:
            emit(shown)
            written += 1
