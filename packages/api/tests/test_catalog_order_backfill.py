"""Migration 0128's price backfill (founder, 2026-11-06), offline: the pure
`plan_brand_order` the migration runs, and its frozen `_category_key` pinned to the app's
`category_key`. The SQL against Postgres is `test_catalog_order_backfill_db.py`."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest

from qualify_api.catalog.order import category_key

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "postgres"
    / "versions"
    / "0128_brand_product_categories.py"
)


@pytest.fixture(scope="module")
def m0128() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0128", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _p(m: ModuleType, name: str, category: str, price: str | None, currency: str = "USD"):
    return m.SeedProduct(
        uuid4(), name, category, Decimal(price) if price is not None else None, currency
    )


def test_frozen_category_key_matches_the_app(m0128: ModuleType) -> None:
    for raw in ("Café", " cafe  ", "CAFÉ", "", None, "Otros", "Bebidas  Frías", "ÑANDÚ"):
        assert m0128._category_key(raw) == category_key(raw)


def test_bianki_shaped_brand_starts_with_main_dishes(m0128: ModuleType) -> None:
    products = [
        _p(m0128, "Agua", "Bebidas", "1"),
        _p(m0128, "Limonada", "Bebidas", "2.5"),
        _p(m0128, "Ensalada griega", "Ensaladas", "6"),
        _p(m0128, "Shawarma de pollo", "Shawarmas", "7"),
        _p(m0128, "Shawarma mixto", "Shawarmas", "8"),
        _p(m0128, "Combo personal", "Combos", "9"),
        _p(m0128, "Combo familiar", "Combos", "20"),
        _p(m0128, "Salsa de ajo", "", "0.5"),
        _p(m0128, "Salsa picante", "", None),
    ]
    plan = m0128.plan_brand_order(products)
    assert [n for n, _k in plan.categories] == ["Combos", "Shawarmas", "Ensaladas", "Bebidas"]
    pos = {p.name: plan.positions[p.id] for p in products}
    assert pos["Combo familiar"] == 0 and pos["Combo personal"] == 1
    assert pos["Shawarma mixto"] == 0 and pos["Shawarma de pollo"] == 1
    assert pos["Limonada"] == 0 and pos["Agua"] == 1
    # «Otros» gets no row; inside it, priced first and no price last.
    assert pos["Salsa de ajo"] == 0 and pos["Salsa picante"] == 1


def test_ties_unpriced_and_mixed_spellings(m0128: ModuleType) -> None:
    products = [
        _p(m0128, "b", "Postres", "5"),
        _p(m0128, "a", "postres ", "5"),
        _p(m0128, "Gratis", "Extras", None),
        _p(m0128, "x", "Zumos", "5"),
    ]
    plan = m0128.plan_brand_order(products)
    # Equal best price → by name; a category with no price at all after priced ones.
    assert plan.categories == (("postres", "postres"), ("Zumos", "zumos"), ("Extras", "extras"))
    assert [plan.positions[p.id] for p in products[:2]] == [1, 0]


def test_mixed_currencies_put_the_main_currency_first(m0128: ModuleType) -> None:
    products = [
        _p(m0128, "Caro en bolívares", "A", "900", "VES"),
        _p(m0128, "Plato 1", "B", "8", "USD"),
        _p(m0128, "Plato 2", "B", "3", "USD"),
        _p(m0128, "Bebida", "A", "2", "usd"),
        _p(m0128, "Sin precio", "A", None, ""),
    ]
    plan = m0128.plan_brand_order(products)
    assert [n for n, _k in plan.categories] == ["B", "A"]  # USD is the main currency
    pos = {p.name: plan.positions[p.id] for p in products}
    assert (pos["Bebida"], pos["Caro en bolívares"], pos["Sin precio"]) == (0, 1, 2)


def test_an_empty_brand_plans_nothing(m0128: ModuleType) -> None:
    assert m0128.plan_brand_order([]) == m0128.BrandPlan((), {})


def test_ids_are_uuids(m0128: ModuleType) -> None:
    plan = m0128.plan_brand_order([_p(m0128, "x", "A", "1")])
    assert all(isinstance(k, UUID) for k in plan.positions)
