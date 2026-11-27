"""N1 (m-25142900): the automatic cover of a historia's video, offline — the frame's shape
and where it is kept. The database half is `test_story_covers_db.py`."""

from __future__ import annotations

import io
import shutil
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from qualify_creative.video.still import VideoStillError, poster_from_video_file

from qualify_api.creative.story_covers import PIECE_FILES, cover_key, vertical_jpeg


def jpeg(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 40)).save(out, "JPEG")
    return out.getvalue()


def test_an_exact_vertical_frame_is_kept_as_it_is() -> None:
    frame = jpeg(360, 640)
    assert vertical_jpeg(frame) == (frame, 360, 640)


def test_a_frame_a_pixel_off_is_cropped_to_exact_9_16() -> None:
    cover, width, height = vertical_jpeg(jpeg(361, 641))
    assert (width, height) == (360, 640) and width * 16 == height * 9
    assert Image.open(io.BytesIO(cover)).size == (360, 640)


@pytest.mark.parametrize("frame", [b"not a picture", jpeg(8, 15)])
def test_an_unusable_frame_is_refused(frame: bytes) -> None:
    with pytest.raises(VideoStillError):
        vertical_jpeg(frame)


def test_the_cover_sits_next_to_its_video_and_is_stable() -> None:
    tenant, draft, asset = uuid4(), uuid4(), uuid4()
    video = f"t/{tenant}/generated/{draft}/r1/video.mp4"
    key = cover_key(video, asset)
    assert key.startswith(f"t/{tenant}/generated/{draft}/r1/story-cover-") and key.endswith(".jpg")
    assert cover_key(video, asset) == key != cover_key(video, uuid4())
    # a new file in the same row (a re-join) gets its own cover, never the old one's key
    assert cover_key(f"t/{tenant}/generated/{draft}/r2/video.mp4", asset) != key


def test_the_story_readers_keep_the_name_and_columns_they_filter_on() -> None:
    assert PIECE_FILES.endswith("AS image_assets")
    for column in ("draft_id", "version_id", "object_key", "position"):
        assert column in PIECE_FILES


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs the ffmpeg binary")
def test_a_real_mp4_gives_a_full_size_9_16_cover(tmp_path: Path) -> None:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    path, (width, height), tick = tmp_path / "story.mp4", (360, 640), Fraction(1, 30)
    with av.open(str(path), "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.codec_context.time_base = tick
        for index in range(60):
            frame = av.VideoFrame.from_ndarray(
                np.full((height, width, 3), 120, np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = index, tick
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    frame = poster_from_video_file(path, at_seconds=1.0, max_side=max(width, height))
    assert vertical_jpeg(frame)[1:] == (360, 640)
