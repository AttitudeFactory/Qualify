"""Pure tests for the catalog screen's view models (`catalog_vm`) — no Reflex, no DB.

Pins:
1. `counts_label` reads naturally in singular/plural and says "Sin fotos" at zero.
2. `build_product_vm` carries everything the card prints as plain strings/ints, with the
   primary photo first in `primary_photo_key` and media ordered by position. The screen
   no longer has a price (founder, 2026-10-19): the view model carries none.
3. The upload zone takes photos and phone videos.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from qualify_api.catalog.service import MediaRecord, ProductRecord

from .catalog_vm import (
    MEDIA_ACCEPT,
    build_product_vm,
    counts_label,
    media_meta_label,
)

_PRODUCT_ID = UUID("d0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")


def _media(n: int, media_type: str = "image", **kw: object) -> MediaRecord:
    return MediaRecord(
        id=UUID(f"e0000000-0000-4000-8000-00000000000{n}"),
        media_type=media_type,
        object_key=f"uploads/t/catalog/p/{n}.{'mp4' if media_type == 'video' else 'jpg'}",
        filename=f"f{n}",
        content_type="video/mp4" if media_type == "video" else "image/jpeg",
        width=kw.get("width"),  # type: ignore[arg-type]
        height=kw.get("height"),  # type: ignore[arg-type]
        duration_sec=kw.get("duration_sec"),  # type: ignore[arg-type]
        bytes=None,
        is_primary=bool(kw.get("is_primary", False)),
        position=int(kw.get("position", n)),  # type: ignore[arg-type]
    )


def _product(**kw: object) -> ProductRecord:
    base: dict[str, object] = {
        "id": _PRODUCT_ID,
        "brand_id": _BRAND_ID,
        "name": "Shawarma mixto",
        "slug": "shawarma-mixto",
        "description": "Pollo y carne",
        "price_amount": Decimal("12.50"),
        "price_currency": "USD",
        "category": "shawarmas",
        "tags": (),
        "is_active": True,
        "position": 0,
        "media": (),
    }
    base.update(kw)
    return ProductRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. counts and media meta


def test_counts_label_reads_naturally() -> None:
    assert counts_label(0, 0) == "Sin fotos"
    assert counts_label(1, 0) == "1 foto"
    assert counts_label(3, 0) == "3 fotos"
    assert counts_label(0, 1) == "1 video"
    assert counts_label(3, 2) == "3 fotos · 2 videos"


def test_media_meta_label() -> None:
    assert media_meta_label("image", 1080, 1350, None) == "1080×1350"
    assert media_meta_label("video", 1080, 1920, 7.4) == "7 s"
    assert media_meta_label("image", None, None, None) == ""


# ---------------------------------------------------------------------------
# 2. the product card


def test_build_product_vm_carries_the_card_as_plain_values() -> None:
    # media arrive ordered by position, as `CatalogService` builds its records
    record = _product(
        media=(
            _media(1, position=0),
            _media(2, position=1),
            _media(3, "video", position=2, duration_sec=9.0),
        )
    )
    vm = build_product_vm(record)
    assert vm.product_id == str(_PRODUCT_ID)
    assert (vm.name, vm.slug, vm.category) == ("Shawarma mixto", "shawarma-mixto", "shawarmas")
    # no price at all (founder, 2026-10-19)
    assert not any(hasattr(vm, f) for f in ("price_label", "price_text", "currency"))
    assert (vm.photo_count, vm.video_count) == (2, 1)
    assert vm.counts_label == "2 fotos · 1 video"
    # no flagged primary → the first photo stands in
    assert vm.primary_photo_key == record.media[0].object_key
    assert [m.position for m in vm.media] == [0, 1, 2]
    assert [m.media_type for m in vm.media] == ["image", "image", "video"]
    assert vm.media[2].meta_label == "9 s"
    # every field is a plain value a Reflex var can carry
    for value in vm.__dict__.values():
        assert isinstance(value, str | int | tuple), value


def test_build_product_vm_without_price_or_photos() -> None:
    vm = build_product_vm(_product(price_amount=None, price_currency="", media=()))
    assert vm.primary_photo_key == ""
    assert vm.counts_label == "Sin fotos"


def test_the_flagged_primary_photo_wins_over_position() -> None:
    record = _product(media=(_media(1, position=0), _media(2, position=1, is_primary=True)))
    vm = build_product_vm(record)
    assert vm.primary_photo_key == record.media[1].object_key
    assert [m.is_primary for m in vm.media] == [False, True]


# ---------------------------------------------------------------------------
# 3. the upload zone


def test_the_upload_zone_takes_photos_and_phone_videos() -> None:
    assert "image/*" in MEDIA_ACCEPT
    assert ".mp4" in MEDIA_ACCEPT["video/mp4"]
    assert ".mov" in MEDIA_ACCEPT["video/quicktime"]
