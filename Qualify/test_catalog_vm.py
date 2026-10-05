"""Pure tests for the catalog screen's view models (`catalog_vm`) — no Reflex, no DB.

Pins:
1. `parse_price` reads what a shop owner types ("12,50", " 8 ", "") and refuses what is
   not a price, in Spanish.
2. `price_text` round-trips the stored amount into the edit field without noise.
3. `counts_label` reads naturally in singular/plural and says "Sin fotos" at zero.
4. `build_product_vm` carries everything the card prints as plain strings/ints, with the
   primary photo first in `primary_photo_key` and media ordered by position.
5. The currency picker puts the tenant's own currency first — also one outside the usual
   five, so the default is always selectable.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from qualify_api.catalog.service import MediaRecord, ProductRecord

from .catalog_vm import (
    CURRENCIES,
    MEDIA_ACCEPT,
    build_product_vm,
    counts_label,
    currency_choices,
    media_meta_label,
    parse_price,
    price_text,
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
# 1-2. price in / price out


def test_parse_price_reads_what_the_operator_types() -> None:
    assert parse_price("12.50") == Decimal("12.50")
    assert parse_price("12,5") == Decimal("12.50")
    assert parse_price(" 8 ") == Decimal("8.00")
    assert parse_price("1 250,00") == Decimal("1250.00")
    assert parse_price("") is None
    assert parse_price("   ") is None


@pytest.mark.parametrize("bad", ["doce", "12.5.0", "-3"])
def test_parse_price_refuses_non_prices_in_spanish(bad: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_price(bad)
    assert "precio" in str(excinfo.value).lower()


def test_price_text_round_trips_without_noise() -> None:
    assert price_text(Decimal("12.50")) == "12.5"
    assert price_text(Decimal("8.00")) == "8"
    assert price_text(Decimal("0.99")) == "0.99"
    assert price_text(None) == ""
    # what the field shows parses back to the same amount
    assert parse_price(price_text(Decimal("12.50"))) == Decimal("12.50")


# ---------------------------------------------------------------------------
# 3. counts and media meta


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
# 4. the product card


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
    assert vm.price_label == "$12.5"
    assert vm.price_text == "12.5"
    assert vm.currency == "USD"
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
    assert vm.price_label == ""
    assert vm.price_text == ""
    assert vm.primary_photo_key == ""
    assert vm.counts_label == "Sin fotos"


def test_the_flagged_primary_photo_wins_over_position() -> None:
    record = _product(media=(_media(1, position=0), _media(2, position=1, is_primary=True)))
    vm = build_product_vm(record)
    assert vm.primary_photo_key == record.media[1].object_key
    assert [m.is_primary for m in vm.media] == [False, True]


# ---------------------------------------------------------------------------
# 5. currencies and the upload zone


def test_currency_choices_put_the_tenants_own_first() -> None:
    assert currency_choices("USD")[0] == "USD"
    assert currency_choices("ves")[0] == "VES"
    assert currency_choices("")[0] == "USD"
    # a tenant currency outside the usual five is still offered (and first)
    choices = currency_choices("MXN")
    assert choices[0] == "MXN" and set(CURRENCIES) <= set(choices)
    assert len(choices) == len(set(choices))


def test_the_upload_zone_takes_photos_and_phone_videos() -> None:
    assert "image/*" in MEDIA_ACCEPT
    assert ".mp4" in MEDIA_ACCEPT["video/mp4"]
    assert ".mov" in MEDIA_ACCEPT["video/quicktime"]
