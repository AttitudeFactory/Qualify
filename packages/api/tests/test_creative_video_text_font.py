"""ED-13 (m-25029108): the producer hands a local Clip's texts the Brand Kit's own font file —
only a file FreeType draws; anything else leaves the family to the render (never a failed
piece), recorded. Offline: an in-memory store, no render call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qualify_creative.render.video_text import BrandText
from qualify_creative.schemas import VideoTextLayer

from .test_creative_media import SpyVendor, _kit
from .test_video_pipeline_local import TENANT_ID, _local_clip, _producer

FONT = (
    Path(__file__).resolve().parents[2] / "creative" / "tests" / "fixtures" / "DejaVuSans.ttf"
).read_bytes()
KEY = f"t/{TENANT_ID}/brand/b/font/heading/marca.ttf"


class Store:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.reads: list[str] = []

    def read(self, key: str) -> bytes:
        self.reads.append(key)
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]


def _brand(files: dict[str, bytes], *, texts: bool = True, key: str | None = KEY) -> Any:
    store = Store(files)
    producer = _producer(store, SpyVendor())
    producer._brand_fonts = lambda **_: key
    layers = (VideoTextLayer(text="Hoy", place="top"),) if texts else ()
    brief = _local_clip(text_layers=layers)
    return producer._video_text_brand(TENANT_ID, brief, _kit()), store


def test_a_usable_font_file_travels_with_the_kit() -> None:
    brand, store = _brand({KEY: FONT})
    assert isinstance(brand, BrandText) and brand.font is not None
    assert brand.font.data == FONT and brand.font.key == KEY and not brand.font_rejected
    assert store.reads == [KEY]


def test_a_file_that_is_not_a_font_leaves_the_family_and_is_recorded() -> None:
    brand, _ = _brand({KEY: b"wOF2" + b"\x00" * 60})
    assert isinstance(brand, BrandText) and brand.font is None and brand.font_rejected


def test_an_unreadable_file_leaves_the_family() -> None:
    brand, _ = _brand({})
    assert isinstance(brand, BrandText) and brand.font is None and brand.font_rejected


def test_no_file_or_no_text_reads_nothing() -> None:
    kitless, store = _brand({KEY: FONT}, key=None)
    assert not isinstance(kitless, BrandText) and store.reads == []
    untexted, store = _brand({KEY: FONT}, texts=False)
    assert not isinstance(untexted, BrandText) and store.reads == []
