"""Migration 0128's price backfill against the compose Postgres, as the migration owner
(`QUALIFY_MIGRATION_DSN`): two tenants' brands with mixed prices and categories get the
price order, every row carries its brand's own tenant, a brand already ordered is left
alone, and a second run changes nothing. Scoped to the test's brands (`brand_ids`) so the
shared dev database's other rows are never rewritten."""

from __future__ import annotations

import importlib.util
import os
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text

from qualify_api.catalog.models import BrandProduct, BrandProductCategory
from qualify_api.catalog.service import CatalogService
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-00000000b128")
TENANT_B = UUID("b0000000-0000-4000-8000-00000000b128")
_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "postgres"
    / "versions"
    / "0128_brand_product_categories.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("m0128_db", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _brand(tenant_id: UUID, products: list[tuple[str, str, str | None, str]]) -> UUID:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"backfill-{tenant_id.hex[:4]}",
                    country="VE",
                    timezone="America/Caracas",
                    currency="USD",
                )
            )
            session.flush()
        brand = Brand(tenant_id=tenant_id, name=f"backfill-{uuid4().hex[:8]}")
        session.add(brand)
        session.flush()
        brand_id = brand.id
    with tenant_session(tenant_id) as session:
        for i, (name, category, price, currency) in enumerate(products):
            session.add(
                BrandProduct(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    name=name,
                    slug=f"p-{uuid4().hex[:10]}",
                    category=category,
                    price_amount=Decimal(price) if price is not None else None,
                    price_currency=currency,
                    position=i,  # creation order: cheapest first, on purpose
                )
            )
    return brand_id


def _run(brand_ids: list[UUID]) -> int:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.begin() as conn:
            return _module().backfill(conn, brand_ids)
    finally:
        engine.dispose()


def test_backfill_orders_by_price_per_tenant_and_is_idempotent() -> None:
    brand_a = _brand(
        TENANT_A,
        [
            ("Agua", "Bebidas", "1", "USD"),
            ("Shawarma de pollo", "Shawarmas", "7", "USD"),
            ("Combo familiar", "Combos", "20", "USD"),
            ("Combo personal", "Combos", "9", "USD"),
            ("Salsa", "", None, ""),
            ("Postre en bolívares", "Postres", "500", "VES"),
        ],
    )
    brand_b = _brand(TENANT_B, [("Té", "Infusiones", "3", "USD"), ("Pan", "Panes", "4", "USD")])
    already = _brand(TENANT_B, [("Uno", "Z", "1", "USD"), ("Dos", "Y", "9", "USD")])
    CatalogService(store=None).set_category_order(  # type: ignore[arg-type]
        tenant_id=TENANT_B, brand_id=already, names=["Z"], user_id=None
    )

    assert _run([brand_a, brand_b, already]) == 2  # `already` has an order: skipped

    service = CatalogService(store=None)  # type: ignore[arg-type]
    assert service.category_order(tenant_id=TENANT_A, brand_id=brand_a) == (
        "Combos",
        "Shawarmas",
        "Bebidas",
        "Postres",  # VES is not brand A's main currency
    )
    assert [p.name for p in service.list_products(tenant_id=TENANT_A, brand_id=brand_a)] == [
        "Combo familiar",
        "Combo personal",
        "Shawarma de pollo",
        "Agua",
        "Postre en bolívares",
        "Salsa",
    ]
    assert service.category_order(tenant_id=TENANT_B, brand_id=brand_b) == ("Panes", "Infusiones")
    assert service.category_order(tenant_id=TENANT_B, brand_id=already) == ("Z",)

    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT c.tenant_id AS row_tenant, b.tenant_id AS brand_tenant "
                "FROM brand_product_categories c JOIN brands b ON b.id = c.brand_id "
                "WHERE c.brand_id = ANY(:ids)"
            ),
            {"ids": [brand_a, brand_b, already]},
        ).all()
    assert rows and all(r.row_tenant == r.brand_tenant for r in rows)
    with tenant_session(TENANT_B) as session:
        visible = session.query(BrandProductCategory).filter_by(brand_id=brand_a).all()
    assert visible == []

    assert _run([brand_a, brand_b]) == 0  # second run: both now have an order
