"""m-25017279 review: `image_size` reads a base photo's size from its header, and returns it
only when both sides are in 1..65,535 — `piece_base_photos.width/height` are
`integer CHECK (> 0)`, so a corrupt vendor header must give no size, never a row the
database refuses (which would have cost the paid piece)."""

from __future__ import annotations

import random
import struct

import pytest

from qualify_api.creative.image_pipeline.base import MAX_SIDE, image_size

PNG = b"\x89PNG\r\n\x1a\n"


def _png(width: int, height: int) -> bytes:
    return (
        PNG + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    )


def _jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + b"\xff\xe0\x00\x10" + b"JFIF\x00" + b"\x00" * 9 + sof + b"\xff\xd9"


def _webp(width: int, height: int) -> bytes:
    body = b"VP8X" + b"\x0a\x00\x00\x00" + b"\x00\x00\x00\x00"
    body += (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


@pytest.mark.parametrize("make", [_png, _jpeg, _webp])
def test_a_real_header_gives_its_size(make) -> None:  # noqa: ANN001
    assert image_size(make(1280, 1600)) == (1280, 1600)


@pytest.mark.parametrize(
    ("width", "height"), [(0, 0), (0, 1600), (1280, 0), (2**32 - 1, 1600), (MAX_SIDE + 1, 10)]
)
def test_an_impossible_png_size_is_no_size(width: int, height: int) -> None:
    assert image_size(_png(width, height)) is None


@pytest.mark.parametrize("cut", range(0, 33))
def test_a_truncated_png_header_is_no_size(cut: int) -> None:
    assert image_size(_png(1280, 1600)[:cut]) in (None, (1280, 1600))


def test_a_zero_jpeg_frame_is_no_size() -> None:
    assert image_size(_jpeg(0, 0)) is None


def test_fuzzed_headers_never_raise_and_never_break_the_column() -> None:
    """The review's fuzz: random headers of every kind, truncated anywhere."""
    rng = random.Random(25017279)
    for _ in range(20_000):
        prefix = rng.choice([PNG, b"\xff\xd8", b"RIFF"])
        data = prefix + rng.randbytes(rng.randint(0, 40))
        if prefix == b"RIFF" and len(data) >= 12 and rng.random() < 0.5:
            data = data[:8] + b"WEBPVP8X" + data[16:]
        if prefix == PNG and len(data) >= 16 and rng.random() < 0.5:
            data = data[:12] + b"IHDR" + data[16:]
        size = image_size(data)
        if size is not None:
            width, height = size
            assert 0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE
