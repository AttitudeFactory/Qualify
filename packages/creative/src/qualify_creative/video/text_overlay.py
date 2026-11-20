"""Lay the owner's texts over a video (EF-05, m-25026573), in the style of `fit.py`.

Each text is ONE transparent PNG drawn by the render service (`qualify_creative.render.
video_text`, a 1080×1920 canvas): this module lays it over the frames of an already
assembled video inside one FFmpeg filter graph (PyAV — the same libraries in development and
production, no `ffmpeg` binary), shown from `start_s` to `end_s` seconds of the video's own
output, appearing with a fade of `fade_in_s` (the layer's alpha from 0 to 1). The soundtrack
is copied as it is: the picture is the only change.

How: a layer is cropped to its visible pixels (the scrim and the letters; the rest of the
canvas is transparent) and fed to its own `buffer` once per video frame, with that frame's
timestamp, so FFmpeg's `fade` (on the alpha) and the `overlay`'s `enable` read the same clock
as the picture. Nothing is drawn in Python.

Same input file, same layers → the same picture going INTO the encoder. What comes out
is NOT guaranteed identical, neither the bytes nor the decoded frames, even on one x264
thread (m-25029128): x264's SIMD macroblock-tree propagation depends on the state of the
process's memory, so the rate control can pick slightly different quantizers for the same
frames as the process ages (a few levels on a handful of pixels). The tests that compare
two encodes exactly use the `reproducible_x264` fixture (`cpu-independent=1`,
`packages/creative/tests/conftest.py`); `decoded_frame_hashes` compares decoded pictures.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from qualify_creative.video._source import frame_rotation
from qualify_creative.video.upright import upright_filters, upright_size

#: The x264 settings: the composed video is the piece the owner publishes, so it keeps its
#: detail (fit.py's `DETAIL_X264`), on ONE thread (one thread alone does NOT make the bytes
#: reproducible — m-25029128, see the module docstring). A short
#: `rc-lookahead` (m-25042483): x264 keeps that many whole 1080×1920 frames queued — the
#: preset's 30 were most of the compose's memory (`join.JOIN_X264` does the same).
OVERLAY_X264: Mapping[str, str] = {
    "crf": "18",
    "preset": "fast",
    "threads": "1",
    "rc-lookahead": "10",
}
#: Decoder threads for the video under the texts, slice-threaded and set before the first
#: decode (m-25042483): FFmpeg's automatic frame threading holds a frame per core.
DECODE_THREADS = 2


def bound_decoder(stream: Any, threads: int = DECODE_THREADS) -> None:
    """At most `threads` slice threads for `stream`'s decoder (`join._bound`)."""
    stream.codec_context.thread_count = threads
    stream.codec_context.thread_type = "SLICE"


#: The aspect the layers are drawn for (9:16): a video off it by more than this is refused —
#: stretching the letters would change the brand's design.
ASPECT_TOLERANCE = 0.01


class TextOverlayError(ValueError):
    """`code`: `unreadable` (not a video), `no_video` (no picture stream), `aspect_mismatch`
    (the video is not 9:16), `layer_unreadable` (a layer is not an RGBA PNG), `encode_failed`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TimedLayer:
    """One text layer: its full-canvas transparent PNG and when it shows, in seconds of the
    video from its first frame. `end_s` None = until the end; `fade_in_s` 0 = no fade."""

    png: bytes
    start_s: float
    end_s: float | None
    fade_in_s: float

    def __post_init__(self) -> None:
        if self.start_s < 0 or self.fade_in_s < 0:
            raise ValueError("a text layer's times are not negative")
        if self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("a text layer disappears after it appears")


@dataclass(frozen=True)
class OverlaidVideo:
    path: Path
    frames: int
    fps: float
    width: int
    height: int
    duration_s: float
    has_audio: bool


def decoded_frame_hashes(path: Path | str) -> list[str]:
    """The sha256 of every decoded picture (planes as decoded, yuv as stored): what «the same
    video» means here — container bytes may differ (muxer metadata) when the pictures do not."""
    import av  # noqa: PLC0415

    hashes: list[str] = []
    with av.open(str(path)) as source:
        stream = source.streams.video[0]
        for frame in source.decode(stream):
            digest = hashlib.sha256()
            digest.update(f"{frame.width}x{frame.height}:{frame.format.name}".encode())
            for plane in frame.planes:
                digest.update(bytes(plane))
            hashes.append(digest.hexdigest())
    return hashes


def _even_box(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """`box` grown to even edges inside `size` (yuv420p's chroma is per 2×2 pixels)."""
    x0, y0, x1, y1 = box
    x0, y0 = x0 - x0 % 2, y0 - y0 % 2
    x1, y1 = min(size[0], x1 + x1 % 2), min(size[1], y1 + y1 % 2)
    return x0, y0, x1, y1


def _layer_ndarray(png: bytes, size: tuple[int, int]) -> tuple[Any, tuple[int, int]] | None:
    """The layer at the video's `size`, cropped to its visible pixels: (RGBA array, top-left).
    None when nothing in it is visible."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    try:
        layer = Image.open(io.BytesIO(png))
        layer.load()
    except Exception as exc:  # noqa: BLE001 — any decoder error is the same refusal
        raise TextOverlayError("layer_unreadable", f"a text layer is not an image: {exc}") from exc
    if layer.mode != "RGBA":
        raise TextOverlayError("layer_unreadable", f"a text layer has no alpha ({layer.mode})")
    if layer.size != size:
        layer = layer.resize(size, Image.Resampling.LANCZOS)
    alpha_box = layer.getchannel("A").getbbox()
    if alpha_box is None:
        return None
    x0, y0, x1, y1 = _even_box(alpha_box, size)
    return np.ascontiguousarray(np.asarray(layer.crop((x0, y0, x1, y1)))), (x0, y0)


def _escape(expr: str) -> str:
    """Commas escaped, as an option value inside a filter's arguments needs."""
    return expr.replace(",", "\\,")


def _frame_rate(stream: Any) -> Fraction:
    for candidate in (stream.average_rate, stream.guessed_rate, stream.base_rate):
        if candidate and 1 <= candidate <= 120:
            return Fraction(candidate)
    return Fraction(30)


def _prepare_texts(
    layers: Sequence[TimedLayer], size: tuple[int, int]
) -> list[tuple[Any, tuple[int, int], TimedLayer]]:
    """Each visible layer at the video's `size`, cropped: (RGBA array, top-left, layer)."""
    prepared: list[tuple[Any, tuple[int, int], TimedLayer]] = []
    for layer in layers:
        crop = _layer_ndarray(layer.png, size)
        if crop is not None:
            prepared.append((crop[0], crop[1], layer))
    return prepared


def _link_texts(
    graph: Any,
    head: Any,
    prepared: Sequence[tuple[Any, tuple[int, int], TimedLayer]],
    base: Fraction,
    origin: float,
) -> tuple[Any, list[tuple[Any, Any]]]:
    """The texts' part of a filter graph (shared with `layer_overlay`'s single pass): over
    a yuv420p `head`, one `buffer` (+ `fade` on the alpha) + `overlay` per layer, shown
    from its start to its end on the video's own clock. Returns the new head and the
    (buffer, pixels) pairs `_push_texts` feeds once per video frame."""
    inputs: list[tuple[Any, Any]] = []
    for pixels, (x, y), layer in prepared:
        h, w = pixels.shape[:2]
        buffer = graph.add(
            "buffer",
            f"video_size={w}x{h}:pix_fmt=rgba"
            f":time_base={base.numerator}/{base.denominator}:pixel_aspect=1/1",
        )
        start = layer.start_s + origin
        last = buffer
        if layer.fade_in_s > 0:
            fade = graph.add(
                "fade",
                f"type=in:start_time={start:.6f}:duration={layer.fade_in_s:.6f}:alpha=1",
            )
            buffer.link_to(fade)
            last = fade
        shown_when = f"gte(t,{start:.6f})"
        if layer.end_s is not None:
            shown_when += f"*lt(t,{layer.end_s + origin:.6f})"
        over = graph.add(
            "overlay",
            f"x={x}:y={y}:format=yuv420:eof_action=repeat:enable={_escape(shown_when)}",
        )
        head.link_to(over, 0, 0)
        last.link_to(over, 0, 1)
        head = over
        inputs.append((buffer, pixels))
    return head, inputs


def _push_texts(av: Any, inputs: Sequence[tuple[Any, Any]], frame: Any, base: Fraction) -> None:
    """One picture of every text for the video `frame` about to be pushed, same timestamp."""
    for buffer, pixels in inputs:
        # a fresh frame each time: `fade` writes into the frame it gets
        copy = av.VideoFrame.from_ndarray(pixels, format="rgba")
        copy.pts = frame.pts
        copy.time_base = base
        buffer.push(copy)


def overlay_text_layers(
    src: Path | str,
    out: Path | str,
    layers: Sequence[TimedLayer],
    *,
    canvas: tuple[int, int] = (1080, 1920),
    x264: Mapping[str, str] = OVERLAY_X264,
) -> OverlaidVideo:
    """`src` with every layer over the frames it shows on, written to `out` (H.264 yuv420p
    MP4, `+faststart`, the soundtrack copied). Written to `out`.partial first and moved into
    place only when complete: a failure leaves no `out` (and never touches `src`).
    `canvas`: the size the layers are drawn at; they are scaled to the video's size, which
    must have the same aspect."""
    import av  # noqa: PLC0415 — lazy, like every other encode

    src, out = Path(src), Path(out)
    partial = out.with_name(out.name + ".partial")
    try:
        result = _encode(av, src, partial, layers, canvas, dict(x264))
        os.replace(partial, out)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return OverlaidVideo(path=out, **result)


def _encode(
    av: Any,
    src: Path,
    out: Path,
    layers: Sequence[TimedLayer],
    canvas: tuple[int, int],
    x264: dict[str, str],
) -> dict[str, Any]:
    try:
        source = av.open(str(src))
    except Exception as exc:  # noqa: BLE001
        raise TextOverlayError("unreadable", f"the video cannot be opened: {exc}") from exc
    with source:
        if not source.streams.video:
            raise TextOverlayError("no_video", "the file has no video stream")
        stream = source.streams.video[0]
        bound_decoder(stream)  # before the first decode
        rotation = 0
        for first in source.decode(stream):
            rotation = frame_rotation(first)
            break
        source.seek(0)
        turn = upright_filters(rotation)
        stored = (stream.codec_context.width, stream.codec_context.height)
        shown = upright_size(*stored, rotation)
        width, height = shown[0] - shown[0] % 2, shown[1] - shown[1] % 2
        if abs(width / height - canvas[0] / canvas[1]) > ASPECT_TOLERANCE:
            raise TextOverlayError(
                "aspect_mismatch", f"a {width}×{height} video is not {canvas[0]}:{canvas[1]}"
            )
        rate = _frame_rate(stream)
        base = stream.time_base
        origin = float(stream.start_time * base) if stream.start_time is not None else 0.0
        audio_in = source.streams.audio[0] if source.streams.audio else None

        prepared = _prepare_texts(layers, (width, height))

        frames = 0
        with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
            audio_out = sink.add_stream_from_template(audio_in) if audio_in is not None else None
            encoder = sink.add_stream("libx264", rate=rate)
            encoder.width, encoder.height = width, height
            encoder.pix_fmt = "yuv420p"
            encoder.options = dict(x264)
            encoder.codec_context.thread_count = int(x264.get("threads", "1"))
            tick = Fraction(1, 1) / Fraction(rate)
            encoder.codec_context.time_base = tick

            graph = av.filter.Graph()
            video_in = graph.add_buffer(template=stream)
            head = video_in
            for spec in turn:
                name, _, args = spec.partition("=")
                step = graph.add(name, args or None)
                head.link_to(step)
                head = step
            if (width, height) != shown:
                crop_even = graph.add("crop", f"{width}:{height}:0:0")
                head.link_to(crop_even)
                head = crop_even
            to_yuv = graph.add("format", "yuv420p")
            head.link_to(to_yuv)
            head = to_yuv
            head, inputs = _link_texts(graph, head, prepared, base, origin)
            sink_out = graph.add("buffersink")
            head.link_to(sink_out)
            graph.configure()

            def push(frame: Any) -> None:
                _push_texts(av, inputs, frame, base)
                video_in.push(frame)

            def drain() -> int:
                done = 0
                while True:
                    try:
                        picture = sink_out.pull()
                    except (av.error.BlockingIOError, av.error.EOFError):
                        return done
                    picture.pts = frames + done
                    picture.time_base = tick
                    for packet in encoder.encode(picture):
                        sink.mux(packet)
                    done += 1

            try:
                if audio_in is None:
                    for frame in source.decode(stream):
                        push(frame)
                        frames += drain()
                else:
                    # the picture starts at 0 from the first frame: the copied sound moves by
                    # the same offset (fit.py, review 2026-10-20)
                    start_t = stream.start_time * base if stream.start_time is not None else 0
                    shift = round(start_t / audio_in.time_base)
                    for packet in source.demux(stream, audio_in):
                        if packet.stream.type == "audio":
                            if packet.dts is None or packet.pts is None:
                                continue
                            pts = packet.pts - shift
                            if pts < 0:
                                continue
                            packet.pts, packet.dts = pts, max(packet.dts - shift, 0)
                            packet.stream = audio_out
                            sink.mux(packet)
                            continue
                        for frame in packet.decode():
                            push(frame)
                            frames += drain()
                video_in.push(None)
                for buffer, _ in inputs:
                    buffer.push(None)
                frames += drain()
                for packet in encoder.encode():
                    sink.mux(packet)
            except av.error.FFmpegError as exc:
                raise TextOverlayError(
                    "encode_failed", f"the text could not be laid: {exc}"
                ) from exc
    if not frames:
        raise TextOverlayError("no_video", "the video has no frames")
    fps = float(rate)
    return {
        "frames": frames,
        "fps": fps,
        "width": width,
        "height": height,
        "duration_s": round(frames / fps, 6) if fps else math.nan,
        "has_audio": audio_in is not None,
    }


__all__ = [
    "ASPECT_TOLERANCE",
    "DECODE_THREADS",
    "OVERLAY_X264",
    "OverlaidVideo",
    "TextOverlayError",
    "TimedLayer",
    "decoded_frame_hashes",
    "bound_decoder",
    "overlay_text_layers",
]
