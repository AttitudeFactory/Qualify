"""WA-15: `brand_products` rows → the engine's `CatalogItem`s (pure mapper, offline)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from qualify_api.whatsapp.catalog import FALLBACK_CATEGORY, to_catalog_items
from qualify_api.whatsapp.menus.engine import CatalogItem


@dataclass(frozen=True)
class Row:
    id: UUID
    name: str
    price_amount: Decimal | None = Decimal("10000")
    price_currency: str = "COP"
    category: str = ""
    is_active: bool = True
    position: int = 0


def _row(
    name: str,
    *,
    price_amount: Decimal | None = Decimal("10000"),
    price_currency: str = "COP",
    category: str = "",
    is_active: bool = True,
    position: int = 0,
) -> Row:
    return Row(
        id=uuid4(),
        name=name,
        price_amount=price_amount,
        price_currency=price_currency,
        category=category,
        is_active=is_active,
        position=position,
    )


def test_orders_by_category_then_position_then_name() -> None:
    rows = [
        _row("Limonada", category="Bebidas", position=2),
        _row("Perro", category="Comidas", position=1),
        _row("Agua", category="Bebidas", position=2),
        _row("Hamburguesa", category="Comidas", position=0),
        _row("Gaseosa", category="Bebidas", position=0),
    ]
    items = to_catalog_items(rows)
    assert [(i.category, i.name) for i in items] == [
        ("Bebidas", "Gaseosa"),
        ("Bebidas", "Agua"),
        ("Bebidas", "Limonada"),
        ("Comidas", "Hamburguesa"),
        ("Comidas", "Perro"),
    ]


def test_inactive_rows_are_skipped() -> None:
    rows = [_row("Visible"), _row("Oculto", is_active=False)]
    assert [i.name for i in to_catalog_items(rows)] == ["Visible"]


def test_missing_price_stays_none_and_blank_currency_is_none() -> None:
    (item,) = to_catalog_items([_row("Sin precio", price_amount=None, price_currency="")])
    assert item.price_amount is None
    assert item.price_currency is None


def test_price_is_decimal_and_currency_upper() -> None:
    (item,) = to_catalog_items([_row("X", price_amount=Decimal("12500.50"), price_currency="cop")])
    assert isinstance(item.price_amount, Decimal)
    assert item.price_amount == Decimal("12500.50")
    assert item.price_currency == "COP"


def test_blank_category_falls_back_to_otros_and_goes_last() -> None:
    rows = [_row("Sin categoría", category="  "), _row("Combo", category="Combos")]
    items = to_catalog_items(rows)
    assert [(i.category, i.name) for i in items] == [
        ("Combos", "Combo"),
        (FALLBACK_CATEGORY, "Sin categoría"),
    ]
    assert FALLBACK_CATEGORY == "Otros"


def test_product_id_is_the_row_uuid_as_text() -> None:
    row = _row("Arepa")
    (item,) = to_catalog_items([row])
    assert item == CatalogItem(
        product_id=str(row.id),
        name="Arepa",
        price_amount=Decimal("10000"),
        price_currency="COP",
        category=FALLBACK_CATEGORY,
    )


def test_empty_and_nameless_rows_yield_nothing() -> None:
    assert to_catalog_items([]) == ()
    assert to_catalog_items([_row("   ")]) == ()
