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

ED-13 (m-25029108): a text may also leave with a fade (a second `fade`, type out), and enter or
leave sliding, zooming or — entering — letter by letter (`TimedLayer.motion_in/out`). Those
move or mask the SAME pixels Remotion drew, frame by frame, only inside their windows
(`_Motion`): rows shifted, the layer scaled with Pillow, the alpha of the letters not typed yet
cleared — no letter is drawn here either. A text that does not move takes exactly the graph
and the pixels it took before.

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


#: ED-13 (m-25029108): how a text enters and leaves — the SAME names and numbers as
#: `qualify_creative.schemas` (`VIDEO_TEXT_MOTIONS_IN/OUT`, `VIDEO_TEXT_SLIDE_FRACTION`,
#: `VIDEO_TEXT_ZOOM_FROM`), copied: importing the schemas would pull pydantic into the video
#: package (`test_text_motions_match_the_schemas` pins that they agree).
MOTIONS_IN: tuple[str, ...] = ("fade", "slide", "zoom", "typewriter")
MOTIONS_OUT: tuple[str, ...] = ("none", "fade", "slide", "zoom")
SLIDE_FRACTION = 0.05
ZOOM_FROM = 0.9


@dataclass(frozen=True)
class LetterReveal:
    """«Letra por letra» (ED-13): the letters layer's characters, each `(x, y, w, h, line)` in
    px of the canvas the layer was drawn on, in reading order — character `i` appears at once,
    `start_s + i * duration_s / len(boxes)` seconds into the video."""

    boxes: tuple[tuple[float, float, float, float, int], ...]
    duration_s: float

    def __post_init__(self) -> None:
        if not self.boxes or self.duration_s < 0:
            raise ValueError("a typed text has letters and a duration")


@dataclass(frozen=True)
class TimedLayer:
    """One text layer: its full-canvas transparent PNG and when it shows, in seconds of the
    video from its first frame. `end_s` None = until the end; `fade_in_s` 0 = no fade.

    ED-13 (m-25029108): `motion_in` — `fade` (the alpha from 0 to 1 over `fade_in_s`, as
    before), `slide` (that ramp while rising `SLIDE_FRACTION` of the height from below),
    `zoom` (that ramp while growing from `ZOOM_FROM` around `center`) or `typewriter` (the
    letters of `reveal` one by one, no ramp: `fade_in_s` unused). `motion_out` — `none` (cut
    at `end_s`, as before) or `fade`/`slide`/`zoom`, the mirror over the last `fade_out_s`
    seconds (needs an `end_s`). Positions and scales ease out entering, `1 - (1 - p)³`, and in
    leaving, `p³`; the alpha ramps are linear (FFmpeg's `fade`). The defaults are a text
    from before ED-13: same filter graph, same pixels."""

    png: bytes
    start_s: float
    end_s: float | None
    fade_in_s: float
    motion_in: str = "fade"
    motion_out: str = "none"
    fade_out_s: float = 0.0
    #: `zoom`'s centre (the text block's), px of the canvas; None = the layer's visible box
    center: tuple[float, float] | None = None
    reveal: LetterReveal | None = None

    def __post_init__(self) -> None:
        if self.start_s < 0 or self.fade_in_s < 0 or self.fade_out_s < 0:
            raise ValueError("a text layer's times are not negative")
        if self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("a text layer disappears after it appears")
        if self.motion_in not in MOTIONS_IN or self.motion_out not in MOTIONS_OUT:
            raise ValueError("a text layer moves in a closed set of ways")
        if (self.motion_in == "typewriter") != (self.reveal is not None):
            raise ValueError("a typed text, and only one, has its letters")
        if self.motion_out != "none" and self.end_s is None:
            raise ValueError("a text that leaves animated says when it leaves")

    @property
    def still(self) -> bool:
        """A text from before ED-13 (fades in, cut at the end): drawn exactly as then."""
        return self.motion_in == "fade" and self.motion_out == "none"


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


def _ease_in(p: float) -> float:
    """Entering: fast then settling, `1 - (1 - p)³`."""
    return 1 - (1 - p) ** 3


def _ease_out(p: float) -> float:
    """Leaving: slow then away, `p³`."""
    return p**3


class _Motion:
    """ED-13: the pixels of one moving text at each moment (the alpha ramps stay FFmpeg's
    `fade`). Outside its windows it hands the same array every frame; inside, a new one:
    the layer moved down (`slide`, the buffer `drop` px taller than the crop), scaled around
    the text block's centre (`zoom`, Pillow, premultiplied) or with only the letters typed so
    far visible (`typewriter`, a per-pixel letter index compared with how many are out)."""

    def __init__(
        self,
        pixels: Any,
        top_left: tuple[int, int],
        layer: TimedLayer,
        scale: tuple[float, float],
        size: tuple[int, int],
    ) -> None:
        import numpy as np  # noqa: PLC0415

        self.layer = layer
        self.pixels = pixels
        #: the video's first timestamp, in seconds (set by `_link_texts`)
        self.origin = 0.0
        h, w = pixels.shape[:2]
        x0, y0 = top_left
        sx, sy = scale
        slides = "slide" in (layer.motion_in, layer.motion_out)
        drop = round(SLIDE_FRACTION * size[1]) if slides else 0
        self.drop = drop + drop % 2  # yuv420: an even height
        self.rest = pixels
        if self.drop:
            self.rest = np.zeros((h + self.drop, w, 4), dtype=pixels.dtype)
            self.rest[:h] = pixels
        if layer.center is not None:
            self.center = (layer.center[0] * sx - x0, layer.center[1] * sy - y0)
        else:
            self.center = (w / 2, h / 2)
        self.index = None
        if layer.reveal is not None:
            self.index = _letter_index(layer.reveal, (w, h), top_left, scale)
            self.step = layer.reveal.duration_s / len(layer.reveal.boxes)
            self.count = len(layer.reveal.boxes)

    @property
    def shape(self) -> tuple[int, int]:
        return self.rest.shape[0], self.rest.shape[1]

    def at(self, t: float) -> Any:
        """The layer's pixels `t` seconds into the video (from its first frame)."""
        import numpy as np  # noqa: PLC0415

        layer = self.layer
        start, end = layer.start_s, layer.end_s
        drop, scale = 0.0, 1.0
        moving = False
        if layer.motion_in in ("slide", "zoom") and layer.fade_in_s > 0:
            p = (t - start) / layer.fade_in_s
            if p < 1:
                e = _ease_in(min(max(p, 0.0), 1.0))
                moving = True
                if layer.motion_in == "slide":
                    drop = (1 - e) * self.drop
                else:
                    scale = ZOOM_FROM + (1 - ZOOM_FROM) * e
        if layer.motion_out in ("slide", "zoom") and end is not None and layer.fade_out_s > 0:
            p = (t - (end - layer.fade_out_s)) / layer.fade_out_s
            if p > 0:
                e = _ease_out(min(p, 1.0))
                moving = True
                if layer.motion_out == "slide":
                    drop = max(drop, e * self.drop)
                else:
                    scale = min(scale, 1 - (1 - ZOOM_FROM) * e)
        pixels = self.pixels
        if self.index is not None:
            if t < start:
                shown = 0
            elif self.step <= 0:
                shown = self.count
            else:
                # a hair of slack: a frame landing exactly on a letter's time shows it
                shown = min(self.count, int((t - start) / self.step + 1e-6) + 1)
            if shown < self.count:
                pixels = pixels.copy()
                pixels[..., 3] = np.where(self.index < shown, pixels[..., 3], 0)
                moving = True
        if not moving:
            return self.rest
        if scale != 1.0:
            pixels = self._scaled(pixels, scale)
        if not self.drop:
            return pixels
        out = np.zeros_like(self.rest)
        dy = round(drop)
        out[dy : dy + pixels.shape[0]] = pixels
        return out

    def _scaled(self, pixels: Any, scale: float) -> Any:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        h, w = pixels.shape[:2]
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        small = np.asarray(
            Image.fromarray(pixels, "RGBA").resize((nw, nh), Image.Resampling.BILINEAR)
        )
        cx, cy = self.center
        left = min(max(round(cx * (1 - scale)), 0), w - nw)
        top = min(max(round(cy * (1 - scale)), 0), h - nh)
        out = np.zeros_like(pixels)
        out[top : top + nh, left : left + nw] = small
        return out


def _letter_index(
    reveal: LetterReveal,
    size: tuple[int, int],
    top_left: tuple[int, int],
    scale: tuple[float, float],
) -> Any:
    """For every pixel of the letters' crop, the index of the character it belongs to: the
    nearest line (by its centre), then the character whose box starts at or before it on that
    line — so a glyph's overhang or its shadow goes with its character, never alone."""
    import numpy as np  # noqa: PLC0415

    w, h = size
    x0, y0 = top_left
    sx, sy = scale
    lines: dict[int, list[tuple[int, float, float, float]]] = {}
    for i, (bx, by, _bw, bh, line) in enumerate(reveal.boxes):
        lines.setdefault(line, []).append((i, bx * sx - x0, by * sy - y0, bh * sy))
    order = sorted(lines)
    centres = np.array([lines[n][0][2] + lines[n][0][3] / 2 for n in order])
    rows = np.arange(h)
    nearest = np.abs(rows[:, None] - centres[None, :]).argmin(axis=1)
    cols = np.arange(w)
    index = np.zeros((h, w), dtype=np.int32)
    for k, n in enumerate(order):
        chars = lines[n]
        starts = np.array([c[1] for c in chars])
        ids = np.array([c[0] for c in chars])
        at = np.clip(np.searchsorted(starts, cols + 0.5, side="right") - 1, 0, len(chars) - 1)
        index[nearest == k] = ids[at]
    return index


def _prepare_texts(
    layers: Sequence[TimedLayer],
    size: tuple[int, int],
    canvas: tuple[int, int] = (1080, 1920),
) -> list[tuple[Any, tuple[int, int], TimedLayer, _Motion | None]]:
    """Each visible layer at the video's `size`, cropped: (RGBA array, top-left, layer, its
    motion — None for a text that does not move, drawn exactly as before ED-13)."""
    prepared: list[tuple[Any, tuple[int, int], TimedLayer, _Motion | None]] = []
    scale = (size[0] / canvas[0], size[1] / canvas[1])
    for layer in layers:
        crop = _layer_ndarray(layer.png, size)
        if crop is not None:
            motion = None if layer.still else _Motion(crop[0], crop[1], layer, scale, size)
            prepared.append((crop[0], crop[1], layer, motion))
    return prepared


def _link_texts(
    graph: Any,
    head: Any,
    prepared: Sequence[tuple[Any, tuple[int, int], TimedLayer, _Motion | None]],
    base: Fraction,
    origin: float,
) -> tuple[Any, list[tuple[Any, Any]]]:
    """The texts' part of a filter graph (shared with `layer_overlay`'s single pass): over
    a yuv420p `head`, one `buffer` (+ `fade` on the alpha, in and ED-13's out) + `overlay`
    per layer, shown from its start to its end on the video's own clock. Returns the new
    head and the (buffer, pixels or motion) pairs `_push_texts` feeds once per video frame."""
    inputs: list[tuple[Any, Any]] = []
    for pixels, (x, y), layer, motion in prepared:
        h, w = motion.shape if motion is not None else pixels.shape[:2]
        buffer = graph.add(
            "buffer",
            f"video_size={w}x{h}:pix_fmt=rgba"
            f":time_base={base.numerator}/{base.denominator}:pixel_aspect=1/1",
        )
        start = layer.start_s + origin
        last = buffer
        # «Letra por letra» types its letters (`_Motion`): no ramp on them
        if layer.fade_in_s > 0 and layer.motion_in != "typewriter":
            fade = graph.add(
                "fade",
                f"type=in:start_time={start:.6f}:duration={layer.fade_in_s:.6f}:alpha=1",
            )
            last.link_to(fade)
            last = fade
        if layer.motion_out != "none" and layer.fade_out_s > 0 and layer.end_s is not None:
            leave = layer.end_s - layer.fade_out_s + origin
            fade_out = graph.add(
                "fade",
                f"type=out:start_time={leave:.6f}:duration={layer.fade_out_s:.6f}:alpha=1",
            )
            last.link_to(fade_out)
            last = fade_out
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
        inputs.append((buffer, motion if motion is not None else pixels))
        if motion is not None:
            motion.origin = origin
    return head, inputs


def _push_texts(av: Any, inputs: Sequence[tuple[Any, Any]], frame: Any, base: Fraction) -> None:
    """One picture of every text for the video `frame` about to be pushed, same timestamp."""
    for buffer, source in inputs:
        if isinstance(source, _Motion):
            pixels = source.at(float(frame.pts * base) - source.origin)
        else:
            pixels = source
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

        prepared = _prepare_texts(layers, (width, height), canvas)

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
    "MOTIONS_IN",
    "MOTIONS_OUT",
    "OVERLAY_X264",
    "SLIDE_FRACTION",
    "ZOOM_FROM",
    "LetterReveal",
    "OverlaidVideo",
    "TextOverlayError",
    "TimedLayer",
    "decoded_frame_hashes",
    "bound_decoder",
    "overlay_text_layers",
]
