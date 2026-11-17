"""Lay the library's smoke, ember and steam layers over a video (EF-08, m-25026581), in the
style of `text_overlay.py`.

A layer is a recorded loop (`effects.layer_loop_file`: a VP9 WebM on pure black, 9:16) that
the browser lays with CSS `mix-blend-mode: screen`; this module lays the SAME file the same
way, inside one FFmpeg filter graph (PyAV — no `ffmpeg` binary), so the final video shows
what the preview showed:

- the loop is decoded on the fly and repeated (reopened when it ends — never all its frames
  in memory), its frame `k` shown `k / loop_fps` seconds after the layer's `start_s`;
- it is scaled to the video's size and moved up or down by its `zone` relative to the
  effect's default zone (the default zone is no move, as in the preview; the band it leaves
  is black = no effect);
- it is blended with **screen in RGB**: the video and the loop go to `gbrp` with an explicit
  BT.709 limited-range conversion — never a screen on YUV planes, which tints magenta/green —
  and `blend=all_mode=screen` with `all_opacity` = the intensity: base + a·L·(1 − base),
  exactly CSS `opacity` on a screen-blended layer; outside `[start_s, end_s)` the blend is
  disabled (`enable`) and the picture passes untouched (the round trip to RGB and back
  runs with `accurate_rnd+full_chroma_int`: Y/U/V come back exactly as they went in);
- the result goes back to yuv420p BT.709 limited, tagged.

Several layers chain (several uses of one effect, or different effects).

ONE pass with the texts (`overlay_layers_and_texts`): the layers in `gbrp`, then
`format=yuv420p`, then the texts' `overlay`s (`text_overlay`'s own graph section, shared) —
one decode and ONE x264 encode for both, the words on top of the smoke and readable. With
no layer it is exactly `overlay_text_layers`; with no text exactly `overlay_effect_layers`.

The soundtrack is
copied as it is. x264 runs on ONE thread like `text_overlay`. Byte-for-byte determinism
is NOT guaranteed on this path (m-25029128): on a 2-core Linux runner two runs can differ
by a few levels on a handful of pixels — not the filter graph's threads, not the loop
decoder's; x264 without lookahead makes it stable but is not used (it would change the
published quality); the root cause is not identified (see `test_video_layer_overlay.
PSNR_MIN_DB` for what was measured). The text-only path stays byte for byte.
Written to `out`.partial
and moved into place only when complete; `src` is never touched. Cost: US$0.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cached_property
from pathlib import Path
from typing import Any

from qualify_creative.video._source import frame_rotation
from qualify_creative.video.text_overlay import (
    ASPECT_TOLERANCE,
    OVERLAY_X264,
    OverlaidVideo,
    TextOverlayError,
    TimedLayer,
    _escape,
    _frame_rate,
    _link_texts,
    _prepare_texts,
    _push_texts,
    bound_decoder,
    overlay_text_layers,
)
from qualify_creative.video.upright import upright_filters, upright_size

#: The version of this compose (provenance): what the layer step did to the picture.
#: v2 (m-25042483): the decoder bounded and x264's lookahead shortened (`OVERLAY_X264`).
LAYER_COMPOSE_VERSION = "layer-compose-v2"
#: Where each zone sits, as a fraction of the height from the top: moving a layer from its
#: default zone to another moves it by the difference.
ZONE_OFFSET: Mapping[str, float] = {"top": 0.0, "middle": 1 / 3, "bottom": 2 / 3}
#: The explicit conversions (never `auto`): limited-range BT.709 YUV ↔ full-range RGB.
#: `accurate_rnd+full_chroma_int`: without them swscale's 8-bit rounding darkens saturated
#: colours by one luma level on the round trip (review 2026-11-16), also outside a span.
_FLAGS = "accurate_rnd+full_chroma_int"
_TO_RGB = f"in_color_matrix=bt709:in_range=tv:out_range=pc:flags={_FLAGS}"
_TO_YUV = f"in_range=pc:out_color_matrix=bt709:out_range=tv:flags={_FLAGS}"
#: The loop's scale to the video's size: the same exact conversion, bicubic.
_LOOP_TO_RGB = f"in_color_matrix=bt709:in_range=tv:out_range=pc:flags=bicubic+{_FLAGS}"
_TAGS = "range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"


class LayerOverlayError(ValueError):
    """`code`: `unreadable` (not a video), `no_video` (no picture stream),
    `loop_unreadable` (the layer's loop cannot be decoded or is empty), `encode_failed`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TimedEffectLayer:
    """One use of a layer: its recorded loop, its intensity in [0, 1], the zone it is laid
    in and the effect's default zone (the loop is recorded for it), and when it shows — in
    seconds of the video from its first frame; `end_s` None = until the end. `effect_id`
    and `version` are its library entry (provenance)."""

    loop: Path
    intensity: float
    zone: str
    default_zone: str
    start_s: float = 0.0
    end_s: float | None = None
    effect_id: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError("a layer's intensity is between 0 and 1")
        if self.zone not in ZONE_OFFSET or self.default_zone not in ZONE_OFFSET:
            raise ValueError(f"a layer's zone is one of {sorted(ZONE_OFFSET)}")
        if self.start_s < 0:
            raise ValueError("a layer's times are not negative")
        if self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("a layer disappears after it appears")

    @classmethod
    def from_entry(
        cls,
        entry: Any,
        params: Mapping[str, object] | None = None,
        *,
        start_s: float | None = None,
        end_s: float | None = None,
    ) -> TimedEffectLayer:
        """A use of the library `entry` (an `EffectEntry` layer) with the owner's `params`
        (missing ones = the entry's defaults), its loop through the read-only door
        (`effects.layer_loop_file`, which refuses anything that is not a library layer)."""
        from qualify_creative.effects import layer_loop_file  # noqa: PLC0415

        chosen = dict(params or {})
        defaults = {name: spec.default for name, spec in entry.params.items()}
        intensity = chosen.get("intensity", defaults.get("intensity", 1.0))
        zone = chosen.get("zone", defaults.get("zone", "top"))
        return cls(
            loop=layer_loop_file(entry),
            intensity=float(intensity),  # type: ignore[arg-type]
            zone=str(zone),
            default_zone=str(defaults.get("zone", zone)),
            start_s=0.0 if start_s is None else float(start_s),
            end_s=end_s,
            effect_id=entry.id,
            version=entry.version,
        )

    @cached_property
    def loop_sha256(self) -> str:
        return hashlib.sha256(Path(self.loop).read_bytes()).hexdigest()

    def params(self) -> dict[str, object]:
        """Provenance of this use: the effect, its version, what the owner chose, the span,
        the exact loop laid (sha256), the compose version and the cost (US$0)."""
        return {
            "effect_id": self.effect_id,
            "effect_version": self.version,
            "intensity": round(self.intensity, 4),
            "zone": self.zone,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "loop_sha256": self.loop_sha256,
            "compose_version": LAYER_COMPOSE_VERSION,
            "cost_usd": "0.00",
        }


def zone_shift(layer: TimedEffectLayer, height: int) -> int:
    """How many pixels (even, + = down) the loop moves to sit in `layer.zone` instead of
    the zone it was recorded for."""
    shift = (ZONE_OFFSET[layer.zone] - ZONE_OFFSET[layer.default_zone]) * height
    return int(round(shift / 2.0)) * 2


class _Loop:
    """A layer's loop, decoded forward on demand and reopened when it ends: holds ONE
    decoded frame at a time. `get(k)` is frame `k` of the endlessly repeated loop."""

    def __init__(self, av: Any, path: Path) -> None:
        self._av = av
        self._path = path
        self._container: Any = None
        self._frames: Any = None
        self.index = -1
        self.frame: Any = None
        self.count: int | None = None
        self._open()
        stream = self._container.streams.video[0]
        self.size = (stream.codec_context.width, stream.codec_context.height)
        self.fps = float(_frame_rate(stream))

    def _open(self) -> None:
        self.close()
        try:
            self._container = self._av.open(str(self._path))
            stream = self._container.streams.video[0]
        except Exception as exc:  # noqa: BLE001 — any reader error is the same refusal
            self.close()  # opened but not a video: never leave it open
            raise LayerOverlayError("loop_unreadable", f"the loop cannot be read: {exc}") from exc
        self._frames = self._container.decode(stream)
        self.index, self.frame = -1, None

    def get(self, k: int) -> Any:
        if self.count is not None:
            k %= self.count
        if self.frame is None or k < self.index:
            self._open()
        while self.index < k:
            try:
                nxt = next(self._frames, None)
            except self._av.error.FFmpegError as exc:
                raise LayerOverlayError("loop_unreadable", f"the loop is broken: {exc}") from exc
            if nxt is None:
                if self.index < 0:
                    raise LayerOverlayError("loop_unreadable", "the loop has no frames")
                self.count = self.index + 1
                k %= self.count
                self._open()
                continue
            self.frame, self.index = nxt, self.index + 1
        return self.frame

    def close(self) -> None:
        if self._container is not None:
            self._container.close()
            self._container = None


def overlay_effect_layers(
    src: Path | str,
    out: Path | str,
    layers: Sequence[TimedEffectLayer],
    *,
    x264: Mapping[str, str] = OVERLAY_X264,
) -> OverlaidVideo:
    """`src` with every layer screen-blended over the frames it shows on, written to `out`
    (H.264 yuv420p BT.709 limited MP4, `+faststart`, the soundtrack copied). Written to
    `out`.partial first and moved into place only when complete: a failure leaves no `out`
    (and never touches `src`). No layers: the video goes through the same conversion.

    The input is assumed BT.709 limited-range yuv (what `prepare.py` leaves): the
    conversion to RGB is explicit, never read from the file — a full-range (`yuvj`)
    input would be read wrongly without a warning.
    """
    return _overlay(src, out, layers, (), canvas=(1080, 1920), x264=x264)


def overlay_layers_and_texts(
    src: Path | str,
    out: Path | str,
    layers: Sequence[TimedEffectLayer],
    texts: Sequence[TimedLayer],
    *,
    canvas: tuple[int, int] = (1080, 1920),
    x264: Mapping[str, str] = OVERLAY_X264,
) -> OverlaidVideo:
    """The layers, then the texts over them, in ONE decode and ONE encode (see the
    module). No layer: `overlay_text_layers` as it is; no text: `overlay_effect_layers`.
    A text problem raises what `overlay_text_layers` raises (`TextOverlayError`: the
    video not 9:16, a layer that is not an RGBA PNG); a layer problem `LayerOverlayError`.

    Like `overlay_effect_layers`, the input is assumed BT.709 limited-range yuv (what
    `prepare.py` leaves).
    """
    if not layers:
        return overlay_text_layers(src, out, texts, canvas=canvas, x264=x264)
    return _overlay(src, out, layers, texts, canvas=canvas, x264=x264)


def _overlay(
    src: Path | str,
    out: Path | str,
    layers: Sequence[TimedEffectLayer],
    texts: Sequence[TimedLayer],
    *,
    canvas: tuple[int, int],
    x264: Mapping[str, str],
) -> OverlaidVideo:
    import av  # noqa: PLC0415 — lazy, like every other encode

    src, out = Path(src), Path(out)
    partial = out.with_name(out.name + ".partial")
    loops: list[_Loop] = []
    try:
        for layer in layers:  # one by one: a failure closes the ones already open
            loops.append(_Loop(av, Path(layer.loop)))
        result = _encode(
            av,
            src,
            partial,
            list(zip(layers, loops, strict=True)),
            dict(x264),
            texts=texts,
            canvas=canvas,
        )
        for loop in loops:
            loop.close()
        os.replace(partial, out)
    except BaseException:
        for loop in loops:
            loop.close()
        partial.unlink(missing_ok=True)
        raise
    return OverlaidVideo(path=out, **result)


def _chain(graph: Any, head: Any, specs: Sequence[tuple[str, str | None]]) -> Any:
    for name, args in specs:
        step = graph.add(name, args or None)
        head.link_to(step)
        head = step
    return head


def _encode(
    av: Any,
    src: Path,
    out: Path,
    layers: Sequence[tuple[TimedEffectLayer, _Loop]],
    x264: dict[str, str],
    *,
    texts: Sequence[TimedLayer] = (),
    canvas: tuple[int, int] = (1080, 1920),
) -> dict[str, Any]:
    try:
        source = av.open(str(src))
    except Exception as exc:  # noqa: BLE001
        raise LayerOverlayError("unreadable", f"the video cannot be opened: {exc}") from exc
    with source:
        if not source.streams.video:
            raise LayerOverlayError("no_video", "the file has no video stream")
        stream = source.streams.video[0]
        bound_decoder(stream)  # before the first decode (m-25042483)
        rotation = 0
        for first in source.decode(stream):
            rotation = frame_rotation(first)
            break
        source.seek(0)
        turn = upright_filters(rotation)
        stored = (stream.codec_context.width, stream.codec_context.height)
        shown = upright_size(*stored, rotation)
        width, height = shown[0] - shown[0] % 2, shown[1] - shown[1] % 2
        if texts and abs(width / height - canvas[0] / canvas[1]) > ASPECT_TOLERANCE:
            raise TextOverlayError(
                "aspect_mismatch", f"a {width}×{height} video is not {canvas[0]}:{canvas[1]}"
            )
        prepared = _prepare_texts(texts, (width, height))
        rate = _frame_rate(stream)
        base = stream.time_base
        origin = float(stream.start_time * base) if stream.start_time is not None else 0.0
        audio_in = source.streams.audio[0] if source.streams.audio else None

        frames = 0
        with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
            audio_out = sink.add_stream_from_template(audio_in) if audio_in is not None else None
            encoder = sink.add_stream("libx264", rate=rate)
            encoder.width, encoder.height = width, height
            encoder.pix_fmt = "yuv420p"
            encoder.options = dict(x264)
            context = encoder.codec_context
            context.thread_count = int(x264.get("threads", "1"))
            context.color_range, context.colorspace = 1, 1  # limited, BT.709
            context.color_primaries, context.color_trc = 1, 1
            tick = Fraction(1, 1) / Fraction(rate)
            context.time_base = tick

            graph = av.filter.Graph()
            video_in = graph.add_buffer(template=stream)
            head = _chain(graph, video_in, [tuple(s.partition("=")[::2]) for s in turn])  # type: ignore[misc]
            if (width, height) != shown:
                head = _chain(graph, head, [("crop", f"{width}:{height}:0:0")])
            head = _chain(graph, head, [("scale", _TO_RGB), ("format", "gbrp")])
            inputs: list[tuple[Any, TimedEffectLayer, _Loop]] = []
            for layer, loop in layers:
                lw, lh = loop.size
                buffer = graph.add(
                    "buffer",
                    f"video_size={lw}x{lh}:pix_fmt=yuv420p"
                    f":time_base={base.numerator}/{base.denominator}:pixel_aspect=1/1",
                )
                specs: list[tuple[str, str | None]] = [
                    ("scale", f"{width}:{height}:{_LOOP_TO_RGB}"),
                    ("format", "gbrp"),
                ]
                shift = zone_shift(layer, height)
                if shift > 0:  # down: black band on top
                    specs += [
                        ("pad", f"{width}:{height + shift}:0:{shift}:black"),
                        ("crop", f"{width}:{height}:0:0"),
                    ]
                elif shift < 0:  # up: black band at the bottom
                    specs += [
                        ("crop", f"{width}:{height + shift}:0:{-shift}"),
                        ("pad", f"{width}:{height}:0:0:black"),
                    ]
                light = _chain(graph, buffer, specs)
                start = layer.start_s + origin
                shown_when = f"gte(t,{start:.6f})"
                if layer.end_s is not None:
                    shown_when += f"*lt(t,{layer.end_s + origin:.6f})"
                blend = graph.add(
                    "blend",
                    f"all_mode=screen:all_opacity={layer.intensity:.6f}"
                    f":shortest=0:repeatlast=1:enable={_escape(shown_when)}",
                )
                head.link_to(blend, 0, 0)
                light.link_to(blend, 0, 1)
                head = blend
                inputs.append((buffer, layer, loop))
            head = _chain(
                graph,
                head,
                [("scale", _TO_YUV), ("format", "yuv420p"), ("setparams", _TAGS)],
            )
            # the texts on top, in the same graph (`text_overlay`'s own section)
            head, text_inputs = _link_texts(graph, head, prepared, base, origin)
            sink_out = graph.add("buffersink")
            head.link_to(sink_out)
            graph.configure()

            def push(frame: Any) -> None:
                t = float(frame.pts * base) - origin if frame.pts is not None else 0.0
                for buffer, layer, loop in inputs:
                    inside = t >= layer.start_s - 1e-6 and (
                        layer.end_s is None or t < layer.end_s - 1e-6
                    )
                    if inside:
                        k = math.floor((t - layer.start_s) * loop.fps + 1e-6)
                        picture = loop.get(max(k, 0))
                    else:  # the blend is off here: any picture of the loop will do
                        picture = loop.frame if loop.frame is not None else loop.get(0)
                    picture.pts = frame.pts
                    picture.time_base = base
                    buffer.push(picture)
                _push_texts(av, text_inputs, frame, base)
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
                    # the same offset (text_overlay.py, fit.py)
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
                for buffer, _, _ in inputs:
                    buffer.push(None)
                for buffer, _ in text_inputs:
                    buffer.push(None)
                frames += drain()
                for packet in encoder.encode():
                    sink.mux(packet)
            except av.error.FFmpegError as exc:
                raise LayerOverlayError(
                    "encode_failed", f"the layer could not be laid: {exc}"
                ) from exc
    if not frames:
        raise LayerOverlayError("no_video", "the video has no frames")
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
    "LAYER_COMPOSE_VERSION",
    "ZONE_OFFSET",
    "LayerOverlayError",
    "TimedEffectLayer",
    "overlay_effect_layers",
    "overlay_layers_and_texts",
    "zone_shift",
]
