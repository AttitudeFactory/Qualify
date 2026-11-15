"""Writes the phone-like clips with a display matrix used by `test_video_upright.py` (EF-01).

Run from the repository root:

    uv run --no-sync python packages/creative/tests/fixtures/make_rotated_fixtures.py

Each clip stores a 64×36 landscape picture (as a phone stores its sensor's) for 1 s at
10 fps, and carries the turn a player applies in its display matrix — what an iPhone
`.mov` holds. PyAV writes it with `VideoStream.set_display_rotation` (degrees
counter-clockwise, as `VideoFrame.rotation` reads it back): no `ffmpeg` binary needed.

The picture is not symmetric, so a test can tell the direction of the turn and not only
the aspect: mid grey, with a red band along the stored TOP edge and a blue one along the
stored LEFT edge. Turned 90° counter-clockwise the red band ends on the left; turned 270°
(90° clockwise, an iPhone held upright) it ends on the right.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 64, 36
FPS = 10
FRAMES = 10
BAND = 8
#: file name → display rotation (degrees counter-clockwise)
CLIPS = {
    "video-rotated-90.mp4": 90,
    "video-rotated-270.mp4": 270,
    "video-rotated-45.mp4": 45,
}


def picture() -> np.ndarray:
    """The stored picture (RGB): grey, red band on top, blue band on the left."""
    pixels = np.full((HEIGHT, WIDTH, 3), 128, dtype=np.uint8)
    pixels[:BAND, :] = (220, 30, 30)
    pixels[:, :BAND] = (30, 30, 220)
    return pixels


def write(path: Path, rotation: int) -> None:
    tick = Fraction(1, FPS)
    with av.open(str(path), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height = WIDTH, HEIGHT
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "20", "preset": "veryslow"}
        stream.codec_context.time_base = tick
        stream.set_display_rotation(rotation)
        frame_rgb = picture()
        for index in range(FRAMES):
            frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24").reformat(format="yuv420p")
            frame.pts = index
            frame.time_base = tick
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)


def main() -> None:
    for name, rotation in CLIPS.items():
        write(HERE / name, rotation)
        print(f"{name}: {(HERE / name).stat().st_size} bytes, rotation {rotation}")


if __name__ == "__main__":
    main()
