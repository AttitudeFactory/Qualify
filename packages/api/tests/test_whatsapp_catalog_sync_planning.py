"""ADR 48 §4.2, §6: what «Cargar o sincronizar todos» would send, the plan key the person
confirms, the request key that makes a double click a no-op, and the per-product state
the Galería screen shows. Pure, in memory."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from qualify_api.whatsapp.catalog_sync import media_url
from qualify_api.whatsapp.catalog_sync.mapping import (
    MappingContext,
    PhotoSnapshot,
    ProductSnapshot,
    product_hash,
)
from qualify_api.whatsapp.catalog_sync.planning import (
    ItemSnapshot,
    compute_plan,
    plan_key,
    product_state,
    request_key,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CATALOG = UUID("44444444-4444-4444-8444-444444444444")


@pytest.fixture(autouse=True)
def _signing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(media_url.SECRET_ENV, "s" * 40)
    monkeypatch.setenv(media_url.BASE_URL_ENV, "https://qualify.example")


CTX = MappingContext(
    tenant_id=TENANT,
    brand_name="Bianki",
    link="https://bianki.example",
    media_url=media_url.catalog_media_url,
)


def _product(n: int, **overrides: object) -> ProductSnapshot:
    values: dict[str, object] = {
        "id": UUID(int=n),
        "name": f"Producto {n}",
        "description": "",
        "price_amount": Decimal("10000"),
        "price_currency": "COP",
        "is_active": True,
        "photo": PhotoSnapshot(UUID(int=1000 + n), f"t/{TENANT}/p{n}.jpg", "image/jpeg", 800, 800),
    }
    values.update(overrides)
    return ProductSnapshot(**values)  # type: ignore[arg-type]


def _item(product: ProductSnapshot | None, n: int, state: str, **overrides: object) -> ItemSnapshot:
    pushed = (
        product_hash(product, retailer_id=str(product.id), ctx=CTX)
        if product is not None and state == "synced"
        else None
    )
    values: dict[str, object] = {
        "id": UUID(int=5000 + n),
        "product_id": product.id if product is not None else None,
        "retailer_id": str(product.id) if product is not None else f"gone-{n}",
        "state": state,
        "last_pushed_hash": pushed,
        "error_code": None,
        "sync_version": 1,
    }
    values.update(overrides)
    return ItemSnapshot(**values)  # type: ignore[arg-type]


def _scenario() -> tuple[dict[UUID, ProductSnapshot], list[ItemSnapshot]]:
    new = _product(1)
    unchanged = _product(2)
    changed = _product(3, price_amount=Decimal("15000"))
    inactive_live = _product(4, is_active=False)
    in_flight = _product(5)
    no_photo = _product(6, photo=None)
    errored = _product(7)
    reupload = _product(8)
    products = {
        p.id: p
        for p in (new, unchanged, changed, inactive_live, in_flight, no_photo, errored, reupload)
    }
    items = [
        _item(unchanged, 2, "synced"),
        _item(changed, 3, "synced", last_pushed_hash="old"),
        _item(_product(4), 4, "synced"),
        _item(in_flight, 5, "queued"),
        _item(errored, 7, "error", error_code="send_failed"),
        _item(reupload, 8, "deleted"),
        _item(None, 9, "synced"),  # its product was deleted
        _item(None, 10, "deleted"),
    ]
    return products, items


def test_plan_counts_every_kind() -> None:
    products, items = _scenario()
    plan = compute_plan(catalog_row_id=CATALOG, products=products, items=items, ctx=CTX)
    assert plan.count("new") == 2  # product 1, and 8 reusing its deleted row
    assert plan.count("changed") == 2  # product 3 (price), 7 (error retried)
    assert plan.count("delete") == 2  # product 4 inactive, the orphan of item 9
    assert plan.unchanged == 1
    assert plan.in_flight == 1
    assert plan.not_eligible == {"no_photo": 1}


def test_a_deleted_row_is_reused_with_its_retailer_id() -> None:
    products, items = _scenario()
    plan = compute_plan(catalog_row_id=CATALOG, products=products, items=items, ctx=CTX)
    reuse = next(d for d in plan.decisions if d.product_id == UUID(int=8))
    assert reuse.kind == "new" and reuse.item_id == UUID(int=5008)
    fresh = next(d for d in plan.decisions if d.product_id == UUID(int=1))
    assert fresh.item_id is None and fresh.retailer_id == str(UUID(int=1))


def test_plan_key_is_stable_and_changes_with_the_plan() -> None:
    products, items = _scenario()
    first = compute_plan(catalog_row_id=CATALOG, products=products, items=items, ctx=CTX)
    again = compute_plan(catalog_row_id=CATALOG, products=products, items=items, ctx=CTX)
    assert first.plan_key == again.plan_key
    products[UUID(int=1)] = _product(1, price_amount=Decimal("1"))
    changed = compute_plan(catalog_row_id=CATALOG, products=products, items=items, ctx=CTX)
    assert changed.plan_key != first.plan_key
    assert plan_key(CATALOG, []) != plan_key(UUID(int=1), [])


def test_nothing_to_do_when_everything_is_synced() -> None:
    product = _product(1)
    plan = compute_plan(
        catalog_row_id=CATALOG,
        products={product.id: product},
        items=[_item(product, 1, "synced")],
        ctx=CTX,
    )
    assert plan.decisions == () and plan.unchanged == 1


def test_request_key_is_order_free_and_bound_to_the_version() -> None:
    a = (UUID(int=1), "upsert", "h1", 0)
    b = (UUID(int=2), "delete", "", 3)
    assert request_key(CATALOG, "sync_all", [a, b]) == request_key(CATALOG, "sync_all", [b, a])
    assert request_key(CATALOG, "sync_all", [a]) != request_key(CATALOG, "upload_one", [a])
    retried = (UUID(int=1), "upsert", "h1", 1)
    assert request_key(CATALOG, "resync_one", [a]) != request_key(CATALOG, "resync_one", [retried])


# --- the per-product state (§4.2) ---------------------------------------------------------


def test_product_states_in_order() -> None:
    product = _product(1)
    assert product_state(product, _item(product, 1, "queued"), CTX).state == "queued"
    assert product_state(product, _item(product, 1, "uploading"), CTX).state == "uploading"
    errored = product_state(product, _item(product, 1, "error", error_code="meta_rejected"), CTX)
    assert (errored.state, errored.reason) == ("error", "meta_rejected")
    assert product_state(product, None, CTX).state == "not_uploaded"
    assert product_state(product, _item(product, 1, "deleted"), CTX).state == "not_uploaded"
    small = _product(1, photo=PhotoSnapshot(UUID(int=7), "k", "image/jpeg", 100, 100))
    state = product_state(small, None, CTX)
    assert (state.state, state.reason) == ("not_eligible", "photo_too_small")
    assert product_state(product, _item(product, 1, "synced"), CTX).state == "synced"
    stale = _item(product, 1, "synced", last_pushed_hash="old")
    assert product_state(product, stale, CTX).state == "out_of_date"
    inactive = _product(1, is_active=False)
    assert product_state(inactive, _item(product, 1, "synced"), CTX).state == "out_of_date"


def test_synced_without_media_config_is_shown_synced() -> None:
    product = _product(1)
    stale = _item(product, 1, "synced", last_pushed_hash="old")
    assert product_state(product, stale, None).state == "synced"
