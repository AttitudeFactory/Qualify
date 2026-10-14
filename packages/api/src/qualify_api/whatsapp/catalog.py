"""The menu engine's catalog, read from `brand_products` (WA-15, QUA-214).

A `products` node (`menus.schema.ProductsNode`, `source = 'catalog'`) is rendered from
the catalog of the brand the WhatsApp number belongs to. Two halves:

- `to_catalog_items(rows)` — **pure**: the active rows only, ordered by category, then
  `position`, then name (the fallback category «Otros» last), projected onto
  `menus.engine.CatalogItem`. An empty `price_currency` (0038's server default) becomes
  `None`; a NULL `price_amount` stays `None` (the engine renders the row without a price
  and leaves it out of the total). The engine groups by category in order of first
  appearance, so the order fixed here is the order the customer sees.
- `load_catalog_for_phone(phone_number_row_id)` — the production `catalog_loader` of the
  WA-07 handler, registered by `webhooks.processor.production_processor`. It runs as
  `qualify_webhook_worker` (tenant-blind, BYPASSRLS, column grants only — migration
  `0059_whatsapp_catalog_grants`): phone row → `(tenant_id, brand_id)`; a number with no
  brand has no catalog; otherwise the brand's active products, filtered by the phone
  row's `tenant_id` as well (defence in depth: the worker bypasses RLS, so the tenant
  predicate is the code's, not the policy's).

Only the columns 0059 grants are selected — a `SELECT *` would be denied by design.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Final, Protocol
from uuid import UUID

from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select

from qualify_api.catalog.models import BrandProduct
from qualify_api.whatsapp.menus.engine import CatalogItem
from qualify_api.whatsapp.models import WhatsAppPhoneNumber

# Section title for products whose `category` is blank (0038 defaults it to '').
FALLBACK_CATEGORY: Final = "Otros"


class CatalogRow(Protocol):
    """The `brand_products` columns the mapper reads — `BrandProduct` satisfies it, and
    so does any test double with the same attributes."""

    @property
    def id(self) -> UUID | str: ...

    @property
    def name(self) -> str: ...

    @property
    def price_amount(self) -> Decimal | int | str | None: ...

    @property
    def price_currency(self) -> str | None: ...

    @property
    def category(self) -> str | None: ...

    @property
    def is_active(self) -> bool: ...

    @property
    def position(self) -> int | None: ...


def _price(value: Decimal | int | str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _category(value: str | None) -> str:
    cleaned = (value or "").strip()
    return cleaned or FALLBACK_CATEGORY


def to_catalog_items(rows: Iterable[CatalogRow]) -> tuple[CatalogItem, ...]:
    """Active rows → `CatalogItem`s, ordered by category (fallback last), `position`,
    then name (case-insensitive). Pure: no I/O, the same rows give the same tuple."""
    active = [r for r in rows if r.is_active and (r.name or "").strip()]

    def key(row: CatalogRow) -> tuple[bool, str, int, str]:
        category = _category(row.category)
        return (
            category == FALLBACK_CATEGORY,
            category.casefold(),
            row.position or 0,
            row.name.strip().casefold(),
        )

    return tuple(
        CatalogItem(
            product_id=str(row.id),
            name=row.name.strip(),
            price_amount=_price(row.price_amount),
            price_currency=(row.price_currency or "").strip().upper() or None,
            category=_category(row.category),
        )
        for row in sorted(active, key=key)
    )


def load_catalog_for_phone(phone_number_row_id: UUID) -> tuple[CatalogItem, ...]:
    """The catalog a number sells, read as `qualify_webhook_worker`. Empty when the
    number is unknown, has no brand, or its brand has no active products."""
    with webhook_worker_session() as session:
        phone = session.execute(
            select(WhatsAppPhoneNumber.tenant_id, WhatsAppPhoneNumber.brand_id).where(
                WhatsAppPhoneNumber.id == phone_number_row_id
            )
        ).first()
        if phone is None or phone.brand_id is None:
            return ()
        rows = session.execute(
            select(
                BrandProduct.id,
                BrandProduct.name,
                BrandProduct.price_amount,
                BrandProduct.price_currency,
                BrandProduct.category,
                BrandProduct.is_active,
                BrandProduct.position,
            ).where(
                BrandProduct.tenant_id == phone.tenant_id,
                BrandProduct.brand_id == phone.brand_id,
                BrandProduct.is_active.is_(True),
            )
        ).all()
        return to_catalog_items(rows)


__all__ = [
    "FALLBACK_CATEGORY",
    "CatalogRow",
    "load_catalog_for_phone",
    "to_catalog_items",
]
