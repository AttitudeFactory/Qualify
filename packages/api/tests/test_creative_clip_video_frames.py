"""A video as the clip's opening or closing frame (§ request 2026-10-19: «que se puedan
poner como inicio y final»): the producer takes the video's first frame to open the
clip and its last one to close it; an image frame passes as it is."""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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


# --- EF-01: a phone video's display rotation ------------------------------------------

#: `packages/creative/tests/fixtures`: 64×36 stored, a red band on the stored top edge;
#: `video-rotated-<n>.mp4` carries a display matrix of n° counter-clockwise
#: (`make_rotated_fixtures.py`). Turned 90° the red band ends on the left, 270° on the right.
FIXTURES = Path(__file__).resolve().parents[2] / "creative" / "tests" / "fixtures"


def _rotated(rotation: int) -> bytes:
    return (FIXTURES / f"video-rotated-{rotation}.mp4").read_bytes()


@pytest.mark.parametrize(("rotation", "red_edge"), [(90, "left"), (270, "right")])
@pytest.mark.parametrize("last", [False, True])
def test_a_phone_video_lends_an_upright_frame(rotation: int, red_edge: str, last: bool) -> None:
    image = Image.open(io.BytesIO(media_module._video_frame(_rotated(rotation), last=last)))
    width, height = image.size
    assert height > width, f"{width}×{height} lies on its side"
    edges = {
        "left": image.convert("RGB").getpixel((2, height // 2)),
        "right": image.convert("RGB").getpixel((width - 3, height // 2)),
    }
    red = edges[red_edge]
    other = edges["right" if red_edge == "left" else "left"]
    assert red[0] > 180 and red[1] < 80 and red[2] < 80, edges
    assert not (other[0] > 180 and other[1] < 80), edges


#: SHA-256 of the JPEG `_video_frame` made of `video-portrait-2s.mp4` on origin/main
#: (b7fbff73, before EF-01, PyAV 19.0.1): a video without a turn gives the same bytes.
UNTURNED_FRAME_SHA256 = {
    False: "0de0fda28db4cff700b9b018b0aa3ab6ce2bdcc111379b67673b10884576fdcb",
    True: "f0f4c35c03a9ecd44bf71427e846f6c36a63e3ec3e2dc2c9c34853694b3d909d",
}


@pytest.mark.skipif(
    sys.platform != "win32" or av.__version__ != "19.0.1",
    reason="hashes pinned on Windows with PyAV 19.0.1; the platform-free check is below",
)
@pytest.mark.parametrize("last", [False, True])
def test_a_video_without_a_turn_lends_the_same_frame_as_before(last: bool) -> None:
    video = (FIXTURES / "video-portrait-2s.mp4").read_bytes()
    jpeg = media_module._video_frame(video, last=last)
    assert hashlib.sha256(jpeg).hexdigest() == UNTURNED_FRAME_SHA256[last]


@pytest.mark.parametrize("last", [False, True])
def test_without_a_turn_the_frame_is_the_one_before_ef01(
    last: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any platform: the JPEG is byte for byte the one made with `to_image()` alone, as
    `_video_frame` did before EF-01."""
    video = (FIXTURES / "video-portrait-2s.mp4").read_bytes()
    jpeg = media_module._video_frame(video, last=last)
    monkeypatch.setattr(
        media_module, "upright_image", lambda frame: frame.to_image().convert("RGB")
    )
    assert media_module._video_frame(video, last=last) == jpeg


def test_a_rotation_that_is_not_a_right_angle_is_refused_and_said_plainly() -> None:
    from qualify_creative.video import VideoSourceError  # noqa: PLC0415

    video = _rotated(45)
    with pytest.raises(VideoSourceError) as refused:
        media_module._video_frame(video, last=False)
    assert refused.value.reason == "rotation_unsupported"

    class _Store:
        def read(self, key: str) -> bytes:
            return video

    producer = media_module.MediaProducer.__new__(media_module.MediaProducer)
    producer._store = _Store()
    with pytest.raises(media_module._MediaFailed) as failed:
        producer._clip_frame("uploads/t/phone.mov", last=False)
    assert "fotograma" in failed.value.detail
    assert isinstance(failed.value.__cause__, VideoSourceError)


def test_a_reference_video_with_such_a_rotation_fails_as_unreadable() -> None:
    """`_fitted_references`: the fitter's `rotation_unsupported` reaches the owner as the
    reference video that could not be prepared, never as a traceback."""
    from qualify_creative.video import PyAvVideoFitter, VideoSourceError  # noqa: PLC0415

    video = _rotated(45)

    class _Store:
        def read(self, key: str) -> bytes:
            if key != "uploads/t/phone.mov":
                raise KeyError(key)  # no fitted reference kept yet
            return video

    class _Save:
        def key_for(self, name: str) -> str:
            return f"generated/{name}"

        def __call__(self, name: str, data: bytes, content_type: str) -> str:
            raise AssertionError("nothing is saved for a refused video")

    producer = media_module.MediaProducer.__new__(media_module.MediaProducer)
    producer._store = _Store()
    producer._fitter = PyAvVideoFitter()
    producer._seedance_reference_model = None  # edit mode: never cut
    media = SimpleNamespace(clip_video_keys=("uploads/t/phone.mov",), clip_reference_mode="edit")
    with pytest.raises(media_module._MediaFailed) as failed:
        producer._fitted_references(uuid4(), media, _Save())
    assert failed.value.detail == media_module.REFERENCE_VIDEO_UNREADABLE_TEXT
    assert isinstance(failed.value.__cause__, VideoSourceError)


@pytest.mark.parametrize("rotation", [90, 270])
def test_a_phone_video_measures_as_it_is_shown(rotation: int) -> None:
    """m-25029131: stored 64×36 with a quarter-turn display matrix → the 36×64 a player
    shows, so an edit of a phone video keeps a vertical canvas."""
    assert media_module._video_dimensions(_rotated(rotation)) == (36, 64)


def test_a_video_without_a_turn_measures_as_before() -> None:
    video = (FIXTURES / "video-portrait-2s.mp4").read_bytes()
    assert media_module._video_dimensions(video) == (180, 320)


def test_a_turn_that_is_not_a_right_angle_keeps_the_stored_size() -> None:
    assert media_module._video_dimensions(_rotated(45)) == (64, 36)


def test_an_unreadable_video_has_no_dimensions() -> None:
    assert media_module._video_dimensions(b"not a video") is None
