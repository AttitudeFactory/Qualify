"""A video as the clip's opening or closing frame (§ request 2026-10-19: «que se puedan
poner como inicio y final»): the producer takes the video's first frame to open the
clip and its last one to close it; an image frame passes as it is."""

from __future__ import annotations

import io

import pytest

av = pytest.importorskip("av")
Image = pytest.importorskip("PIL.Image")

from qualify_api.creative import media as media_module  # noqa: E402


def _two_colour_video() -> bytes:
    """A tiny MP4: two red frames, then two blue ones."""
    out = io.BytesIO()
    with av.open(out, mode="w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=4)
        stream.width, stream.height, stream.pix_fmt = 64, 64, "yuv420p"
        for colour in ((255, 0, 0), (255, 0, 0), (0, 0, 255), (0, 0, 255)):
            frame = av.VideoFrame.from_image(Image.new("RGB", (64, 64), colour))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return out.getvalue()


def _centre(jpeg: bytes) -> tuple[int, int, int]:
    return Image.open(io.BytesIO(jpeg)).convert("RGB").getpixel((32, 32))


def test_the_first_and_the_last_frame_of_a_video() -> None:
    video = _two_colour_video()
    red = _centre(media_module._video_frame(video, last=False))
    blue = _centre(media_module._video_frame(video, last=True))
    assert red[0] > 200 and red[2] < 60
    assert blue[2] > 200 and blue[0] < 60


def test_a_clip_frame_from_a_video_key_and_from_an_image_key() -> None:
    video = _two_colour_video()
    image = b"\x89PNG-not-really"
    store = {"uploads/t/ref.mp4": video, "uploads/t/p1.png": image}

    class _Store:
        def read(self, key: str) -> bytes:
            return store[key]

    producer = media_module.MediaProducer.__new__(media_module.MediaProducer)
    producer._store = _Store()
    assert producer._clip_frame(None, last=False) is None
    assert producer._clip_frame("uploads/t/p1.png", last=True) == image  # as it is
    closing = producer._clip_frame("uploads/t/ref.mp4", last=True)
    assert _centre(closing)[2] > 200  # the video's last frame, blue


def test_a_broken_video_frame_says_so() -> None:
    class _Store:
        def read(self, key: str) -> bytes:
            return b"not a video"

    producer = media_module.MediaProducer.__new__(media_module.MediaProducer)
    producer._store = _Store()
    with pytest.raises(media_module._MediaFailed):
        producer._clip_frame("uploads/t/broken.mp4", last=False)


def test_the_last_frame_of_a_longer_video_after_seeking() -> None:
    """Review 2026-10-19: the last frame comes from a seek near the end, not from
    decoding the whole file — a 4 s video with a keyframe every second, green last."""
    out = io.BytesIO()
    with av.open(out, mode="w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 64, "yuv420p"
        stream.codec_context.gop_size = 10
        for i in range(40):
            colour = (0, 255, 0) if i >= 35 else (255, 0, 0)
            frame = av.VideoFrame.from_image(Image.new("RGB", (64, 64), colour))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    green = _centre(media_module._video_frame(out.getvalue(), last=True))
    assert green[1] > 200 and green[0] < 60
