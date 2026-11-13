"""ADR 48 §4.1, §4.2, §5: Qualify product → Meta catalog item, its content hash, the
eligibility reasons and the signed photo URL. Pure functions, no I/O."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from qualify_api.whatsapp.catalog_sync import media_url
from qualify_api.whatsapp.catalog_sync.mapping import (
    PIPELINE_VERSION,
    MappingContext,
    MediaCandidate,
    PhotoSnapshot,
    ProductSnapshot,
    clip,
    content_hash,
    default_link,
    delete_data,
    format_price,
    ineligibility,
    item_data,
    primary_photo,
    resolve_link,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")
PRODUCT = UUID("22222222-2222-4222-8222-222222222222")
PHOTO = UUID("33333333-3333-4333-8333-333333333333")
SECRET = "s" * 40
BASE = "https://qualify.example"


@pytest.fixture(autouse=True)
def _signing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(media_url.SECRET_ENV, SECRET)
    monkeypatch.setenv(media_url.BASE_URL_ENV, BASE + "/")


def _photo(**overrides: object) -> PhotoSnapshot:
    values: dict[str, object] = {
        "id": PHOTO,
        "object_key": f"t/{TENANT}/catalog/p.jpg",
        "content_type": "image/jpeg",
        "width": 1080,
        "height": 1080,
    }
    values.update(overrides)
    return PhotoSnapshot(**values)  # type: ignore[arg-type]


def _product(**overrides: object) -> ProductSnapshot:
    values: dict[str, object] = {
        "id": PRODUCT,
        "name": "  Shawarma mixto  ",
        "description": "Pollo y carne, salsa de ajo.",
        "price_amount": Decimal("12500"),
        "price_currency": "COP",
        "is_active": True,
        "photo": _photo(),
    }
    values.update(overrides)
    return ProductSnapshot(**values)  # type: ignore[arg-type]


def _ctx(link: str = "https://bianki.example") -> MappingContext:
    return MappingContext(
        tenant_id=TENANT, brand_name="Bianki", link=link, media_url=media_url.catalog_media_url
    )


# --- the golden item ----------------------------------------------------------------------


def test_golden_item_data_is_exactly_what_meta_receives() -> None:
    sig = media_url.sign(TENANT, PHOTO)
    assert item_data(_product(), retailer_id=str(PRODUCT), ctx=_ctx()) == {
        "id": "22222222-2222-4222-8222-222222222222",
        "title": "Shawarma mixto",
        "description": "Pollo y carne, salsa de ajo.",
        "brand": "Bianki",
        "price": "12500.00 COP",
        "availability": "in stock",
        "condition": "new",
        "link": "https://bianki.example",
        "image": [
            {
                "url": f"{BASE}/public/catalog-media/{TENANT}/{PHOTO}/{sig}.jpg",
            }
        ],
    }
    assert len(sig) == 43 and "=" not in sig


def test_pipeline_version_is_pinned() -> None:
    assert PIPELINE_VERSION == "wa-catalog-map-v1"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("12500"), "12500.00 COP"),
        (Decimal("12500.5"), "12500.50 COP"),
        (Decimal("1234567.891"), "1234567.89 COP"),
        (Decimal("1E+3"), "1000.00 COP"),
    ],
)
def test_price_is_two_decimals_a_point_and_the_code(amount: Decimal, expected: str) -> None:
    assert format_price(amount, "COP") == expected


def test_title_and_description_are_clipped_to_meta_limits() -> None:
    data = item_data(
        _product(name="a" * 150, description="b" * 6_000),
        retailer_id=str(PRODUCT),
        ctx=_ctx(),
    )
    assert data["title"] == "a" * 100
    assert data["description"] == "b" * 5_000
    assert "…" not in data["title"]


def test_clip_never_splits_a_grapheme() -> None:
    accented = "e" * 99 + "é"  # 101 code points, the last «é» is two
    assert clip(accented, 100) == "e" * 99
    family = "x" * 98 + "\U0001f468‍\U0001f469"  # 👨‍👩 starts at 98
    assert clip(family, 100) == "x" * 98
    assert clip("corto", 100) == "corto"


def test_empty_description_falls_back_to_the_name() -> None:
    data = item_data(_product(description="   "), retailer_id=str(PRODUCT), ctx=_ctx())
    assert data["description"] == "Shawarma mixto"


def test_link_falls_back_to_wa_me_with_the_digits_of_the_number() -> None:
    assert default_link("+57 300 123-4567") == "https://wa.me/573001234567"
    assert resolve_link(None, "+57 300 123 4567") == "https://wa.me/573001234567"
    assert resolve_link("https://bianki.example", "+57") == "https://bianki.example"


def test_delete_data_is_only_the_id() -> None:
    assert delete_data("abc") == {"id": "abc"}


# --- eligibility --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"is_active": False}, "inactive"),
        ({"price_amount": None}, "no_price"),
        ({"price_amount": Decimal("0")}, "no_price"),
        ({"price_currency": ""}, "no_currency"),
        ({"price_currency": "cop"}, "no_currency"),
        ({"price_currency": "PESOS"}, "no_currency"),
        ({"photo": None}, "no_photo"),
        ({"photo": _photo(content_type="image/webp")}, "photo_format"),
        ({"photo": _photo(width=499)}, "photo_too_small"),
        ({"photo": _photo(height=None)}, "photo_too_small"),
    ],
)
def test_each_ineligibility_reason(overrides: dict[str, object], reason: str) -> None:
    assert ineligibility(_product(**overrides)) == reason


def test_png_of_500_is_eligible() -> None:
    assert (
        ineligibility(_product(photo=_photo(content_type="image/png", width=500, height=500)))
        is None
    )


def test_item_data_refuses_an_ineligible_product() -> None:
    with pytest.raises(ValueError):
        item_data(_product(is_active=False), retailer_id=str(PRODUCT), ctx=_ctx())


def test_primary_photo_prefers_the_marked_image_then_position() -> None:
    def media(
        n: int, *, kind: str = "image", primary: bool = False, pos: int = 0
    ) -> MediaCandidate:
        return MediaCandidate(
            id=UUID(int=n),
            media_type=kind,
            object_key=f"k{n}",
            content_type="image/jpeg",
            width=800,
            height=800,
            is_primary=primary,
            position=pos,
        )

    assert primary_photo([media(1, pos=2), media(2, pos=1)]).id == UUID(int=2)  # type: ignore[union-attr]
    assert primary_photo([media(1, pos=0), media(2, pos=5, primary=True)]).id == UUID(int=2)  # type: ignore[union-attr]
    assert primary_photo([media(1, kind="video")]) is None


# --- the hash -----------------------------------------------------------------------------


def test_hash_is_stable_and_covers_what_meta_sees() -> None:
    base = content_hash(item_data(_product(), retailer_id=str(PRODUCT), ctx=_ctx()))
    again = content_hash(item_data(_product(), retailer_id=str(PRODUCT), ctx=_ctx()))
    assert base == again and len(base) == 64
    changed = {
        "price": _product(price_amount=Decimal("13000")),
        "title": _product(name="Shawarma"),
        "photo": _product(photo=_photo(id=UUID(int=9))),
    }
    for product in changed.values():
        assert content_hash(item_data(product, retailer_id=str(PRODUCT), ctx=_ctx())) != base
    other_link = item_data(_product(), retailer_id=str(PRODUCT), ctx=_ctx("https://wa.me/57"))
    assert content_hash(other_link) != base


def test_hash_includes_the_pipeline_version() -> None:
    data = item_data(_product(), retailer_id=str(PRODUCT), ctx=_ctx())
    assert content_hash(data) != content_hash(data, pipeline_version="wa-catalog-map-v2")


# --- the signed URL -----------------------------------------------------------------------


def test_signature_verifies_and_binds_tenant_and_media() -> None:
    sig = media_url.sign(TENANT, PHOTO)
    assert media_url.verify(TENANT, PHOTO, sig)
    assert not media_url.verify(UUID(int=1), PHOTO, sig)
    assert not media_url.verify(TENANT, UUID(int=1), sig)
    assert not media_url.verify(TENANT, PHOTO, sig[:-1] + ("A" if sig[-1] != "A" else "B"))
    assert not media_url.verify(TENANT, PHOTO, "short")


@pytest.mark.parametrize("secret", ["", "dev-only-state-secret-not-for-production", "x" * 31])
def test_an_unusable_secret_makes_media_unavailable(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    monkeypatch.setenv(media_url.SECRET_ENV, secret)
    assert not media_url.media_ready()
    with pytest.raises(media_url.CatalogMediaUnavailable):
        media_url.catalog_media_url(TENANT, PHOTO)
    assert not media_url.verify(TENANT, PHOTO, "a" * 43)


def test_a_missing_base_url_makes_media_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(media_url.BASE_URL_ENV, raising=False)
    assert not media_url.media_ready()
    with pytest.raises(media_url.CatalogMediaUnavailable):
        media_url.catalog_media_url(TENANT, PHOTO)
