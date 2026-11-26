"""«Publicación del mes» setting (m-25120704) — offline, with an in-memory store."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentKind

from qualify_api.catalog.service import MediaRecord, ProductRecord, UnknownProduct
from qualify_api.creative.brand_kit_store import BrandKitDetails, carry_reserved
from qualify_api.planner.monthly_post import (
    MONTHLY_POST_KINDS,
    MonthlyPostSetting,
    get_monthly_post_setting,
    product_photo_keys,
    set_monthly_post_setting,
)


class FakeStore:
    def __init__(self) -> None:
        self.docs: dict[tuple[UUID, UUID], dict[str, Any]] = {}

    def load_details(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKitDetails:
        return BrandKitDetails(connect=dict(self.docs.get((tenant_id, brand_id), {})))

    def set_document_key(self, *, tenant_id, brand_id, document, key, value) -> bool:  # noqa: ANN001
        assert document == "connect"
        self.docs.setdefault((tenant_id, brand_id), {})[key] = value
        return True


T, B = uuid4(), uuid4()


def test_default_is_off_with_the_advertising_image() -> None:
    assert get_monthly_post_setting(T, B, store=FakeStore()) == MonthlyPostSetting(
        enabled=False, kind=ContentKind.STATIC_FLYER
    )


def test_set_then_get_round_trips_per_brand() -> None:
    store = FakeStore()
    set_monthly_post_setting(T, B, True, "clip", store=store)
    assert get_monthly_post_setting(T, B, store=store) == MonthlyPostSetting(True, ContentKind.CLIP)
    assert get_monthly_post_setting(T, uuid4(), store=store).enabled is False


@pytest.mark.parametrize(
    "kind",
    [
        "nope",
        "shot_video",
        "own_media",
        "creator_script",
        "template",  # without its product
        "",
    ],
)
def test_kind_is_validated_at_the_boundary(kind: str) -> None:
    store = FakeStore()
    with pytest.raises(ValueError):
        set_monthly_post_setting(T, B, True, kind, store=store)
    assert store.docs == {}


def test_enabled_must_be_a_bool() -> None:
    with pytest.raises(ValueError):
        set_monthly_post_setting(T, B, "yes", "clip", store=FakeStore())  # type: ignore[arg-type]


def test_malformed_stored_value_reads_as_default() -> None:
    store = FakeStore()
    store.docs[(T, B)] = {"monthly_post": {"enabled": "true", "kind": "own_media"}}
    assert get_monthly_post_setting(T, B, store=store) == MonthlyPostSetting()


def test_the_six_kinds_are_offered() -> None:
    # founder, 2026-11-26 (m-25121346): every ready-to-publish kind of «Crear pieza»
    assert set(MONTHLY_POST_KINDS) == {
        ContentKind.STATIC_FLYER,
        ContentKind.CAROUSEL,
        ContentKind.TEMPLATE,
        ContentKind.CLIP,
        ContentKind.ANIMATED_AVATAR_VIDEO,
        ContentKind.AVATAR_VIDEO,
    }


@pytest.mark.parametrize("kind", ["carousel", "avatar_video", "animated_avatar_video"])
def test_a_kind_saved_while_825_offered_it_reads_as_saved(kind: str) -> None:
    store = FakeStore()
    store.docs[(T, B)] = {"monthly_post": {"enabled": True, "kind": kind}}
    assert get_monthly_post_setting(T, B, store=store) == MonthlyPostSetting(
        True, ContentKind(kind)
    )


def test_a_template_saved_without_its_product_reads_as_the_default_kind() -> None:
    store = FakeStore()  # saved while #825 offered six kinds, before `product_id`
    store.docs[(T, B)] = {"monthly_post": {"enabled": True, "kind": "template"}}
    assert get_monthly_post_setting(T, B, store=store) == MonthlyPostSetting(
        True, ContentKind.STATIC_FLYER
    )


# -- the template's product (m-25121346) --------------------------------------------------


def _product(brand: UUID = B, *, active: bool = True, photos: int = 1) -> ProductRecord:
    media = tuple(
        MediaRecord(
            uuid4(),
            "image",
            f"t/x/catalog/p{i}.jpg",
            "p.jpg",
            "image/jpeg",
            None,
            None,
            None,
            None,
            i == photos - 1,
            i,
        )
        for i in range(photos)
    )
    return ProductRecord(
        uuid4(), brand, "Shawarma", "shawarma", "", None, "", "", (), active, 0, media
    )


class FakeCatalog:
    def __init__(self, *products: ProductRecord) -> None:
        self.products = {p.id: p for p in products}

    def get_product(self, *, tenant_id: UUID, product_id: UUID) -> ProductRecord:
        if product_id not in self.products:
            raise UnknownProduct(str(product_id))
        return self.products[product_id]


def test_a_template_saves_and_reads_its_product() -> None:
    store, product = FakeStore(), _product()
    catalog = FakeCatalog(product)
    saved = set_monthly_post_setting(
        T, B, True, "template", str(product.id), store=store, catalog=catalog
    )
    assert saved.product_id == product.id
    assert store.docs[(T, B)]["monthly_post"] == {
        "enabled": True,
        "kind": "template",
        "product_id": str(product.id),
    }
    read = get_monthly_post_setting(T, B, store=store, catalog=catalog)
    assert read == MonthlyPostSetting(True, ContentKind.TEMPLATE, product.id, False)


@pytest.mark.parametrize(
    "product",
    [None, _product(uuid4()), _product(active=False), _product(photos=0)],
    ids=["none", "other_brand", "inactive", "no_photo"],
)
def test_a_template_refuses_a_product_that_cannot_make_it(product: ProductRecord | None) -> None:
    store = FakeStore()
    catalog = FakeCatalog(*([product] if product else []))
    product_id = product.id if product else None
    with pytest.raises(ValueError):
        set_monthly_post_setting(T, B, True, "template", product_id, store=store, catalog=catalog)
    with pytest.raises(ValueError):  # unknown id
        set_monthly_post_setting(T, B, True, "template", uuid4(), store=store, catalog=catalog)
    assert store.docs == {}


def test_another_kind_drops_the_product() -> None:
    store = FakeStore()
    saved = set_monthly_post_setting(T, B, True, "clip", uuid4(), store=store)
    assert saved.product_id is None
    assert store.docs[(T, B)]["monthly_post"] == {"enabled": True, "kind": "clip"}


def test_a_product_gone_since_reads_as_missing() -> None:
    store, product = FakeStore(), _product()
    set_monthly_post_setting(
        T, B, True, "template", product.id, store=store, catalog=FakeCatalog(product)
    )
    read = get_monthly_post_setting(T, B, store=store, catalog=FakeCatalog())
    assert read.kind is ContentKind.TEMPLATE and read.product_missing


def test_the_main_photo_goes_first() -> None:
    assert product_photo_keys(_product(photos=3))[0] == "t/x/catalog/p2.jpg"


def test_the_setting_survives_a_wizard_save() -> None:
    stored = {"city": "Bogotá", "monthly_post": {"enabled": True, "kind": "clip"}}
    written = carry_reserved("connect", stored, {"city": "Cúcuta"})
    assert written["monthly_post"] == {"enabled": True, "kind": "clip"}
