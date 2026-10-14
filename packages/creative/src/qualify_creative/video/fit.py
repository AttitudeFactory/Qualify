"""Fit a video into a carousel slide (§ request 2026-10-09): cover-crop it to the
carousel's exact size — Seedance has no 4:5, and a reused Reel is 9:16 — and, when the
operator asked for words on it, lay the slide's transparent text layer
(`compose.text_layer`) over every frame.

Done with PyAV, not the `ffmpeg` binary: PyAV's wheels bundle FFmpeg's libraries (with
libx264 and the filters), so the same code runs on a developer's Windows machine and in
the production image, neither of which has `ffmpeg` on PATH. The crop, the scale and the
overlay run inside an FFmpeg filter graph — per-frame Pillow or numpy took 30 s for a
5 s slide, the graph ~5 s. The audio is dropped: Instagram plays a carousel muted, and
Seedance 1.0 makes none.

Behind a Protocol so the media producer's tests never encode a video.
"""

from __future__ import annotations

import io
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol

#: Instagram plays a carousel video of up to 60 s.
MAX_SLIDE_SECONDS = 60.0
#: The frame rate used when the source's own is missing or nonsensical (a file whose
#: frames all sit at time 0 reads as thousands of fps): Seedance's, and Instagram's.
FALLBACK_FPS = 24


@dataclass(frozen=True)
class FittedVideo:
    data: bytes
    width: int
    height: int
    duration_sec: float
    #: The first frame as fitted (text included), JPEG — the slide's thumbnail.
    poster: bytes | None = None
    content_type: str = "video/mp4"


class VideoFitter(Protocol):
    def fit(
        self,
        data: bytes,
        *,
        size: tuple[int, int],
        overlay: bytes | None = None,
        max_seconds: float = MAX_SLIDE_SECONDS,
    ) -> FittedVideo: ...


class PyAvVideoFitter:
    """H.264 `yuv420p` MP4 at `size`, `+faststart`, no audio."""

    def available(self) -> bool:
        try:
            import av  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    def fit(
        self,
        data: bytes,
        *,
        size: tuple[int, int],
        overlay: bytes | None = None,
        max_seconds: float = MAX_SLIDE_SECONDS,
    ) -> FittedVideo:
        width, height = size
        if width % 2 or height % 2:
            raise ValueError(f"an H.264 slide needs even dimensions, not {width}×{height}")
        # a real file, not a BytesIO: `+faststart` (the moov atom first, as Meta asks)
        # rewrites the file in a second pass, which a write-only buffer cannot take
        with tempfile.TemporaryDirectory(prefix="qualify-slide-") as tmp:
            out = Path(tmp) / "slide.mp4"
            frames, rate, poster = _encode(data, out, size, overlay, max_seconds)
            encoded = out.read_bytes()
        if not frames:
            raise ValueError("the video has no frames")
        return FittedVideo(
            data=encoded, width=width, height=height, duration_sec=frames / rate, poster=poster
        )


def _frame_rate(stream: Any) -> Fraction:
    """The source's frame rate, if it is a plausible one (1-120 fps); else the fallback.
    The average rate of a file whose frames all carry time 0 is its frame count per
    tick — thousands of fps — and encoding at that rate makes the 0.04 s "video" again."""
    for candidate in (stream.average_rate, stream.guessed_rate, stream.base_rate):
        if candidate and 1 <= candidate <= 120:
            return Fraction(candidate)
    return Fraction(FALLBACK_FPS)


def _layer_frame(av: Any, overlay: bytes, size: tuple[int, int]) -> Any:
    """The text layer as an RGBA frame — `VideoFrame.from_image` would drop the alpha."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    layer = Image.open(io.BytesIO(overlay)).convert("RGBA").resize(size)
    return av.VideoFrame.from_ndarray(np.asarray(layer), format="rgba")


def _encode(
    data: bytes, out: Path, size: tuple[int, int], overlay: bytes | None, max_seconds: float
) -> tuple[int, float, bytes | None]:
    import av  # noqa: PLC0415 — lazy: only a carousel's video slides need it

    width, height = size
    frames = 0
    poster: list[bytes] = []
    with av.open(io.BytesIO(data)) as source:
        if not source.streams.video:
            raise ValueError("the file has no video stream")
        stream = source.streams.video[0]
        rate = _frame_rate(stream)
        base = stream.time_base
        with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
            encoder = sink.add_stream("libx264", rate=rate)
            encoder.width, encoder.height = width, height
            encoder.pix_fmt = "yuv420p"
            encoder.options = {"crf": "23", "preset": "veryfast"}
            # every frame is stamped by hand: a frame handed to the encoder with no pts
            # is written at time 0, and 120 such frames make a 0.04 s file (seen
            # 2026-10-09 on the first real carousel — "videos de cero segundos")
            tick = Fraction(1, 1) / Fraction(rate)
            encoder.codec_context.time_base = tick

            graph = av.filter.Graph()
            video_in = graph.add_buffer(template=stream)
            # the centred window with the slide's aspect (`ImageOps.fit` in C)
            cover = f"w='min(iw,ih*{width}/{height})':h='min(ih,iw*{height}/{width})'"
            crop = graph.add("crop", cover)
            scale = graph.add("scale", f"{width}:{height}")
            to_yuv = graph.add("format", "yuv420p")
            frames_out = graph.add("buffersink")
            video_in.link_to(crop)
            crop.link_to(scale)
            layer_in = None
            if overlay is not None:
                layer_in = graph.add(
                    "buffer",
                    f"video_size={width}x{height}:pix_fmt=rgba"
                    f":time_base={base.numerator}/{base.denominator}:pixel_aspect=1/1",
                )
                # the layer is ONE frame: `eof_action=repeat` keeps it over every frame
                over = graph.add("overlay", "x=0:y=0:format=auto:eof_action=repeat")
                scale.link_to(over, 0, 0)
                layer_in.link_to(over, 0, 1)
                over.link_to(to_yuv)
            else:
                scale.link_to(to_yuv)
            to_yuv.link_to(frames_out)
            graph.configure()
            if layer_in is not None:
                layer = _layer_frame(av, overlay, size)
                layer.pts = 0
                layer.time_base = base
                layer_in.push(layer)
                layer_in.push(None)

            def drain() -> int:
                done = 0
                while True:
                    try:
                        frame = frames_out.pull()
                    except (av.error.BlockingIOError, av.error.EOFError):
                        return done
                    if not poster:
                        jpeg = io.BytesIO()
                        frame.to_image().save(jpeg, format="JPEG", quality=90)
                        poster.append(jpeg.getvalue())
                    frame.pts = frames + done  # one tick per frame, at `rate`
                    frame.time_base = tick
                    for packet in encoder.encode(frame):
                        sink.mux(packet)
                    done += 1

            for frame in source.decode(stream):
                if frame.time is not None and frame.time >= max_seconds:
                    break
                video_in.push(frame)
                frames += drain()
            video_in.push(None)
            frames += drain()
            for packet in encoder.encode():
                sink.mux(packet)
    return frames, float(rate), (poster[0] if poster else None)
