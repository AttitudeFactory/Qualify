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

import pytest
from qualify_api.catalog.service import MediaRecord, ProductRecord

from .catalog_vm import (
    MEDIA_ACCEPT,
    NO_CURRENCY,
    build_product_vm,
    counts_label,
    currency_choice,
    currency_from_choice,
    media_meta_label,
    parse_price_input,
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
    # the price is back as an OPTIONAL field (m-24803289): formatted for reading, raw
    # for the edit form, and the code as stored
    assert (vm.price_label, vm.price_amount, vm.price_currency) == ("$12.5", "12.5", "USD")
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
    # a product with no price carries no price: the pieces then print none, never one
    # that was made up (requirement 8 of m-24803289)
    assert (vm.price_label, vm.price_amount, vm.price_currency) == ("", "", "")
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


# ---------------------------------------------------------------------------
# The optional price (m-24803289)
#
# The whole point of the field is that a piece prints the catalog's price and never an
# invented one, so the parser is exact or it refuses: every ambiguous form below raises
# instead of guessing.


def test_an_empty_price_is_a_valid_answer() -> None:
    assert parse_price_input("") is None
    assert parse_price_input("   ") is None


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("89990", "89990.00"),
        ("89.990", "89990.00"),  # thousands, the LatAm way
        ("89,990", "89990.00"),
        ("1999,90", "1999.90"),  # decimals, comma
        ("1999.90", "1999.90"),  # decimals, point
        ("1.234,56", "1234.56"),  # mixed, point groups
        ("1,234.56", "1234.56"),  # mixed, comma groups
        ("$ 89990", "89990.00"),  # the symbol is noise, not data
        ("12", "12.00"),
    ],
)
def test_a_price_that_can_be_read_exactly_is_read_exactly(typed: str, expected: str) -> None:
    assert parse_price_input(typed) == Decimal(expected)


@pytest.mark.parametrize(
    "typed",
    [
        "1.234.56",  # two point separators: thousands or decimals? refused
        "abc",
        "12.3456",  # four decimals is not money this column holds
        "-5",
        "1 2 3,4,5",
        "99999999999999",  # past Numeric(12, 2)
    ],
)
def test_a_price_that_cannot_be_read_exactly_is_refused(typed: str) -> None:
    with pytest.raises(ValueError):
        parse_price_input(typed)


def test_zero_is_not_a_price() -> None:
    with pytest.raises(ValueError, match="mayor que cero"):
        parse_price_input("0")


def test_the_currency_select_never_invents_a_code() -> None:
    assert currency_choice("") == NO_CURRENCY
    assert currency_choice("CLP") == "CLP"
    assert currency_from_choice(NO_CURRENCY) == ""
    assert currency_from_choice("CLP") == "CLP"
    assert currency_from_choice("clp") == "CLP"
    # anything that is not one of the offered codes stores no currency at all
    assert currency_from_choice("inventada") == ""
    assert currency_from_choice("") == ""
