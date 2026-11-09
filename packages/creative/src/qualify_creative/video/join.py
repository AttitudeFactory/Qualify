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

import gc
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
#: there. VE-10a wired a join phase into the full worker harness
#: (`creative-worker-memory.sh`, `PLATFORM=linux/arm64`); its arm64 run is pending.
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
    sound = np.zeros((2, samples), dtype=np.float32)
    with av.open(str(clip.path)) as source:
        if source.streams.audio:
            stream = source.streams.audio[0]
            if threads is not None:
                _bound(stream.codec_context, threads)
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
                sound = _part_audio(av, np, clip, span, samples, fade, threads)
                pending = np.concatenate([pending, sound], axis=1)
                del sound
                encode_sound(final=False)
                _part_video(av, clip, span, frames, size, rate, overlay, emit, threads)
                if threads is not None:
                    gc.collect()  # this part's decoder, graph and frames, before the next
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
    threads: int | None = None,
) -> None:
    """Decode the part once and hand `frames` output frames to `emit`, each the source
    frame shown at that tick of the common rate (repeated or dropped as the rates
    differ), cover-cropped and scaled to `size`, with `overlay` on top."""
    width, height = size
    start = clip.start_s
    stop = start + frames / rate  # the kept interval, relative to the first frame
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
) -> JoinSegment:
    """ONE part as `join_clips` would lay it in the joined video — cut to its interval,
    cover-cropped and scaled to `size`, `overlay` on every frame — encoded as a video-only
    segment with `JOIN_SEGMENT_X264`, and its sound as the exact samples its frames last
    (`frames × 48000 / fps`), with half the cut's fade at each edge that meets another
    part (`fade_in` / `fade_out`, as `join_clips` fades them). The sound is NOT encoded
    here: `concat_segments` encodes the whole soundtrack once, so the AAC encoder's
    priming happens once and never accumulates per cut (risk N6). Written beside `out`
    and renamed into place: a failure leaves neither file."""
    import av  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    width, height = size
    if width % 2 or height % 2:
        raise JoinError(f"an H.264 video needs even dimensions, not {width}×{height}")
    rate = Fraction(fps)
    tick = 1 / rate
    out, pcm_out = Path(out), Path(pcm_out)
    partial = out.with_name(f".{out.name}.{uuid.uuid4().hex}.partial.mp4")
    pcm_partial = pcm_out.with_name(f".{pcm_out.name}.{uuid.uuid4().hex}.partial")
    first: list[bytes] = []
    written = 0
    samples = 0
    try:
        try:
            span = _probe(av, clip.path)
            frames = _part_frames(clip, span, rate)
            samples = round(frames * JOIN_SAMPLE_RATE / rate)
            half = round(crossfade_audio_s / 2 * JOIN_SAMPLE_RATE)
            fade = (min(half, samples) if fade_in else 0, min(half, samples) if fade_out else 0)
            sound = _part_audio(av, np, clip, span, samples, fade, threads)
            np.ascontiguousarray(sound.T, dtype="<f4").tofile(pcm_partial)
            del sound
            with av.open(str(partial), mode="w", format="mp4") as sink:
                video_out = sink.add_stream("libx264", rate=rate)
                video_out.width, video_out.height = width, height
                video_out.pix_fmt = "yuv420p"
                video_out.options = segment_x264()
                if threads is not None:
                    video_out.options = {**video_out.options, "threads": str(threads)}
                    _bound(video_out.codec_context, threads)
                video_out.codec_context.time_base = tick

                def emit(frame: Any) -> None:
                    nonlocal written
                    if poster and not first:
                        jpeg = io.BytesIO()
                        frame.to_image().save(jpeg, format="JPEG", quality=90)
                        first.append(jpeg.getvalue())
                    frame.pts = written
                    frame.time_base = tick
                    for packet in video_out.encode(frame):
                        sink.mux(packet)
                    written += 1

                _part_video(av, clip, span, frames, size, rate, overlay, emit, threads)
                for packet in video_out.encode():
                    sink.mux(packet)
        except JoinError:
            raise
        except (OSError, av.error.FFmpegError) as error:
            raise JoinError(f"{clip.path.name} could not be encoded: {error}") from error
        os.replace(partial, out)
        os.replace(pcm_partial, pcm_out)
    finally:
        partial.unlink(missing_ok=True)
        pcm_partial.unlink(missing_ok=True)
    return JoinSegment(out, pcm_out, written, samples, first[0] if first else None)


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
            audio_out = sink.add_stream("aac", rate=JOIN_SAMPLE_RATE)
            audio_out.layout = JOIN_AUDIO_LAYOUT
            audio_out.format = "fltp"
            audio_out.bit_rate = JOIN_AUDIO_BITRATE
            audio_out.codec_context.time_base = Fraction(1, JOIN_SAMPLE_RATE)
            chunk = audio_out.codec_context.frame_size or 1024
            pending = np.zeros((2, 0), dtype=np.float32)
            sound_pts = 0

            def encode_sound(final: bool) -> None:
                nonlocal pending, sound_pts
                while pending.shape[1] >= chunk or (final and pending.shape[1]):
                    take = min(chunk, pending.shape[1])
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

            for index, segment in enumerate(segments):
                sound = np.fromfile(segment.pcm, dtype="<f4")
                if sound.size != segment.samples * 2:
                    raise JoinError(f"segment {index + 1}: its sound is not its length")
                pending = np.concatenate([pending, sound.reshape(-1, 2).T], axis=1)
                del sound
                encode_sound(final=False)
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
            encode_sound(final=True)
            for packet in audio_out.encode():
                sink.mux(packet)
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
