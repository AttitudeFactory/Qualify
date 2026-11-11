"""Gallery photos share the catalog's bounded decode and process-wide guard."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from qualify_creative.photo.normalize import PhotoDimensionsExceeded

from qualify_api.catalog import business_media as gallery
from qualify_api.catalog.business_media_staging import OUTCOME_STAGED, StagedFile


def test_gallery_uses_bounded_decode_and_shows_dimensions_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gallery, "tenant_session", lambda _: nullcontext(object()))
    monkeypatch.setattr(gallery, "_require_brand", lambda *_: None)
    monkeypatch.setattr(gallery, "_live_by_digest", lambda *_: None)
    monkeypatch.setattr(gallery, "_counts", lambda *_: (0, 0))
    seen: dict[str, object] = {}

    def reject(data: bytes, **kwargs: object) -> None:
        seen.update(kwargs)
        raise PhotoDimensionsExceeded("too many pixels")

    monkeypatch.setattr(gallery, "load_normalized", reject)
    service = gallery.BusinessMediaService(gate=None, staging_root=tmp_path)  # type: ignore[arg-type]
    with pytest.raises(gallery.CatalogError, match=gallery.PHOTO_DIMENSIONS_TEXT):
        service.add_business_photo(tenant_id=uuid4(), brand_id=uuid4(), data=b"x", filename="a.jpg")
    assert seen == {
        "max_pixels": 50_000_000,
        "max_non_jpeg_pixels": 25_000_000,
        "max_aspect_ratio": 8,
        "decode_width": 1080,
    }


def test_direct_gallery_photo_enforces_byte_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gallery, "MAX_PHOTO_BYTES", 2)
    service = gallery.BusinessMediaService(gate=None, staging_root=tmp_path)  # type: ignore[arg-type]
    with pytest.raises(gallery.CatalogError, match=gallery.PHOTO_TOO_HEAVY_TEXT):
        service.add_business_photo(
            tenant_id=uuid4(), brand_id=uuid4(), data=b"abc", filename="a.jpg"
        )


def test_waiting_gallery_photo_stays_on_disk_until_decode_slot_is_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entered = Event()
    release = Event()
    second_read = Event()
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"photo")
    tenant_id = uuid4()
    brand_id = uuid4()
    service = gallery.BusinessMediaService(gate=None, staging_root=tmp_path)  # type: ignore[arg-type]

    def resolve(root: Path, tenant: object, relpath: str) -> Path:
        if relpath == "second":
            second_read.set()
        return source

    def process(**kwargs: object) -> tuple[None, bool]:
        if kwargs["filename"] == "first.jpg":
            entered.set()
            assert release.wait(5)
        return None, False

    monkeypatch.setattr(gallery, "resolve_staged", resolve)
    monkeypatch.setattr(gallery, "discard_staged", lambda *_: None)
    monkeypatch.setattr(service, "_add_photo", process)
    first = StagedFile("first.jpg", OUTCOME_STAGED, 5, relpath="first")
    second = StagedFile("second.jpg", OUTCOME_STAGED, 5, relpath="second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        task1 = pool.submit(
            service.add_staged, tenant_id=tenant_id, brand_id=brand_id, staged=first
        )
        try:
            assert entered.wait(5)
            task2 = pool.submit(
                service.add_staged, tenant_id=tenant_id, brand_id=brand_id, staged=second
            )
            assert not second_read.wait(0.2)
        finally:
            release.set()
        task1.result(timeout=5)
        task2.result(timeout=5)
    assert second_read.is_set()
