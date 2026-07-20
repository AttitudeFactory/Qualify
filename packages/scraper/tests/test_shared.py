from __future__ import annotations

from pathlib import Path
from uuid import UUID

from qualify_scraper.shared import (
    LocalDiskRawPayloadStore,
    Platform,
    make_natural_key,
    raw_payload_key,
)


def test_natural_key_shape() -> None:
    brand = UUID("11111111-1111-1111-1111-111111111111")
    assert make_natural_key(brand, Platform.TIKTOK, "abc") == (
        "11111111-1111-1111-1111-111111111111",
        Platform.TIKTOK,
        "abc",
    )


def test_raw_payload_key_is_stable_per_url() -> None:
    url = "https://www.tiktok.com/@x/video/1"
    assert raw_payload_key(Platform.TIKTOK, url) == raw_payload_key(Platform.TIKTOK, url)
    assert raw_payload_key(Platform.TIKTOK, url).startswith("hydration/tiktok/")


def test_local_disk_store_writes_and_returns_key(tmp_path: Path) -> None:
    store = LocalDiskRawPayloadStore(tmp_path)
    key = store.persist(Platform.INSTAGRAM, "https://instagram.com/p/1", {"a": 1})
    assert (tmp_path / key).exists()
    assert key.startswith("hydration/instagram/")
