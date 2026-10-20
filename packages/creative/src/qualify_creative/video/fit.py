"""Fit a video into a carousel slide (§ request 2026-10-09): cover-crop it to the
carousel's exact size — Seedance has no 4:5, and a reused Reel is 9:16 — and, when the
operator asked for words on it, lay the slide's transparent text layer
(`compose.text_layer`) over every frame.

Done with PyAV, not the `ffmpeg` binary: PyAV's wheels bundle FFmpeg's libraries (with
libx264 and the filters), so the same code runs on a developer's Windows machine and in
the production image, neither of which has `ffmpeg` on PATH. The crop, the scale and the
overlay run inside an FFmpeg filter graph — per-frame Pillow or numpy took 30 s for a
5 s slide, the graph ~5 s. The audio is dropped: Instagram plays a carousel muted, and
Seedance 1.0 makes none — unless the caller keeps it (`keep_audio`, § request 2026-10-20:
a clip with the brand's logo over it keeps its soundtrack), then it is copied as it is.

It also turns ONE still into a short video (`animate_still`, § request 2026-10-13): the
advertising image offered as a Reel. Instagram publishes only a video as a Reel, so the
composed image — words and logo already on it — gets a slow push-in, encoded the same
way. The text is part of the image, so it stays sharp; nothing is generated twice.

Behind a Protocol so the media producer's tests never encode a video.
"""

from __future__ import annotations

import io
import math
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
#: A still animated into a Reel (`animate_still`): its length, frame rate and how far the
#: push-in goes — 6 % over the whole clip reads as motion without blurring the words.
STILL_SECONDS = 6.0
STILL_FPS = 30
STILL_ZOOM = 1.06


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
        keep_audio: bool = False,
    ) -> FittedVideo: ...

    def animate_still(
        self, image: bytes, *, size: tuple[int, int], seconds: float = STILL_SECONDS
    ) -> FittedVideo: ...


class PyAvVideoFitter:
    """H.264 `yuv420p` MP4 at `size`, `+faststart`; no audio unless `keep_audio`."""

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
        keep_audio: bool = False,
    ) -> FittedVideo:
        width, height = size
        if width % 2 or height % 2:
            raise ValueError(f"an H.264 slide needs even dimensions, not {width}×{height}")
        # a real file, not a BytesIO: `+faststart` (the moov atom first, as Meta asks)
        # rewrites the file in a second pass, which a write-only buffer cannot take
        with tempfile.TemporaryDirectory(prefix="qualify-slide-") as tmp:
            out = Path(tmp) / "slide.mp4"
            frames, rate, poster = _encode(
                data, out, size, overlay, max_seconds, keep_audio=keep_audio
            )
            encoded = out.read_bytes()
        if not frames:
            raise ValueError("the video has no frames")
        return FittedVideo(
            data=encoded, width=width, height=height, duration_sec=frames / rate, poster=poster
        )

    def animate_still(
        self, image: bytes, *, size: tuple[int, int], seconds: float = STILL_SECONDS
    ) -> FittedVideo:
        """`image` as a `seconds`-long H.264 MP4 at `size` with a slow, eased push-in to
        the centre; the poster is the still itself."""
        width, height = size
        if width % 2 or height % 2:
            raise ValueError(f"an H.264 video needs even dimensions, not {width}×{height}")
        if seconds <= 0:
            raise ValueError("a video needs a positive length")
        with tempfile.TemporaryDirectory(prefix="qualify-still-") as tmp:
            out = Path(tmp) / "still.mp4"
            frames, poster = _encode_still(image, out, size, seconds)
            encoded = out.read_bytes()
        return FittedVideo(
            data=encoded,
            width=width,
            height=height,
            duration_sec=frames / STILL_FPS,
            poster=poster,
        )


def _push_in_box(progress: float, size: tuple[int, int]) -> tuple[float, float, float, float]:
    """The source window at `progress` (0-1) of the push-in: centred, shrinking from the
    whole frame to 1/STILL_ZOOM of it, eased in and out. Float coordinates — Pillow
    resamples from a fractional box, so the motion has no one-pixel steps."""
    eased = 0.5 - 0.5 * math.cos(math.pi * min(max(progress, 0.0), 1.0))
    zoom = 1.0 + (STILL_ZOOM - 1.0) * eased
    width, height = size
    w, h = width / zoom, height / zoom
    x, y = (width - w) / 2, (height - h) / 2
    return (x, y, x + w, y + h)


def _encode_still(
    image: bytes, out: Path, size: tuple[int, int], seconds: float
) -> tuple[int, bytes]:
    import av  # noqa: PLC0415 — lazy: only an ad image offered as a Reel needs it
    from PIL import Image, ImageOps  # noqa: PLC0415

    still = ImageOps.fit(Image.open(io.BytesIO(image)).convert("RGB"), size)
    poster = io.BytesIO()
    still.save(poster, format="JPEG", quality=90)
    total = max(1, round(seconds * STILL_FPS))
    tick = Fraction(1, STILL_FPS)
    with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        encoder = sink.add_stream("libx264", rate=STILL_FPS)
        encoder.width, encoder.height = size
        encoder.pix_fmt = "yuv420p"
        encoder.options = {"crf": "20", "preset": "veryfast"}
        encoder.codec_context.time_base = tick
        for index in range(total):
            box = _push_in_box(index / max(total - 1, 1), size)
            frame = av.VideoFrame.from_image(
                still.resize(size, Image.Resampling.BICUBIC, box=box)
            ).reformat(format="yuv420p")
            # stamped by hand, one tick per frame (see `_encode`: no pts = time 0)
            frame.pts = index
            frame.time_base = tick
            for packet in encoder.encode(frame):
                sink.mux(packet)
        for packet in encoder.encode():
            sink.mux(packet)
    return total, poster.getvalue()


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
    data: bytes,
    out: Path,
    size: tuple[int, int],
    overlay: bytes | None,
    max_seconds: float,
    *,
    keep_audio: bool = False,
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
        audio_in = source.streams.audio[0] if keep_audio and source.streams.audio else None
        with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
            # the soundtrack is copied, not re-encoded: the picture is the only change
            audio_out = sink.add_stream_from_template(audio_in) if audio_in is not None else None
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

            if audio_in is None:
                for frame in source.decode(stream):
                    if frame.time is not None and frame.time >= max_seconds:
                        break
                    video_in.push(frame)
                    frames += drain()
            else:
                # the fitted picture starts at 0 from the source's first frame, so the
                # copied soundtrack is moved by the same offset — a source whose streams
                # start later than 0 would otherwise come out of sync (review 2026-10-20);
                # sound from before the first frame is dropped
                start = stream.start_time * stream.time_base if stream.start_time is not None else 0
                shift = round(start / audio_in.time_base)
                ended = False
                for packet in source.demux(stream, audio_in):
                    if packet.stream.type == "audio":
                        # the empty packet that flushes a demuxer is not muxed
                        if packet.dts is None or packet.pts is None:
                            continue
                        pts = packet.pts - shift
                        if pts < 0 or pts * packet.time_base >= max_seconds:
                            continue
                        packet.pts, packet.dts = pts, max(packet.dts - shift, 0)
                        packet.stream = audio_out
                        sink.mux(packet)
                        continue
                    if ended:
                        continue
                    for frame in packet.decode():
                        if frame.time is not None and frame.time - start >= max_seconds:
                            ended = True
                            break
                        video_in.push(frame)
                        frames += drain()
            video_in.push(None)
            frames += drain()
            for packet in encoder.encode():
                sink.mux(packet)
    return frames, float(rate), (poster[0] if poster else None)
