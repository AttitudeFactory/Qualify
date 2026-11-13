"""The menu engine's catalog, read from `brand_products` (WA-15, QUA-214).

A `products` node (`menus.schema.ProductsNode`, `source = 'catalog'`) is rendered from
the catalog of the brand the WhatsApp number belongs to. Two halves:

- `to_catalog_items(rows, category_order)` — **pure**: the active rows only, in the
  catalog's one order (`catalog.order.order_catalog`, m-24955643: the owner's
  categories first, the rest alphabetically, «Otros» last; `position` then name inside
  each), projected onto
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
  predicate is the code's, not the policy's). The owner's category order comes from
  `brand_product_categories` (0128 grants the worker `tenant_id, brand_id, name_key,
  position`), filtered the same way.

- `load_cart_products_for_phone(phone_number_row_id, product_ids)` — the production
  `cart_product_loader` of the same handler (m-25018684): the Galería products a
  catalog cart points at, by id, among the products of the receiving number's brand
  and tenant, active or not (an order for a product hidden since is still that
  product). One query for every line; an id of another brand or tenant is simply not
  found, so it never links.

Only the columns 0059 grants are selected — a `SELECT *` would be denied by design.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select

from qualify_api.catalog.models import BrandProduct, BrandProductCategory
from qualify_api.catalog.order import (
    FALLBACK_CATEGORY,
    canonical_labels,
    category_key,
    category_label,
    order_catalog,
)
from qualify_api.whatsapp.menus.engine import CatalogItem
from qualify_api.whatsapp.models import WhatsAppPhoneNumber
from qualify_api.whatsapp.orders import CartProduct


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


def to_catalog_items(
    rows: Iterable[CatalogRow], category_order: Sequence[str] = ()
) -> tuple[CatalogItem, ...]:
    """Active rows → `CatalogItem`s in the catalog's order (`order_catalog`): the
    categories in `category_order` first, the rest alphabetically, «Otros» last;
    `position`, then name inside each. Pure: the same input gives the same tuple."""
    active = [r for r in rows if r.is_active and (r.name or "").strip()]
    ordered = order_catalog(active, category_order)
    # The engine groups by exact text: every row of a category gets the same title
    # (the first row's spelling), so «Café» and «cafe» are one section, as on screen.
    labels = canonical_labels(ordered)
    return tuple(
        CatalogItem(
            product_id=str(row.id),
            name=row.name.strip(),
            price_amount=_price(row.price_amount),
            price_currency=(row.price_currency or "").strip().upper() or None,
            category=category_label(labels[category_key(row.category)]),
        )
        for row in ordered
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
        order = session.scalars(
            select(BrandProductCategory.name_key)
            .where(
                BrandProductCategory.tenant_id == phone.tenant_id,
                BrandProductCategory.brand_id == phone.brand_id,
            )
            .order_by(BrandProductCategory.position, BrandProductCategory.name_key)
        ).all()
        return to_catalog_items(rows, tuple(order))


def to_cart_products(rows: Iterable[CatalogRow]) -> dict[str, CartProduct]:
    """Rows → `orders.CartProduct` keyed by the product id as canonical UUID text."""
    return {
        str(UUID(str(row.id))): CartProduct(
            product_id=str(UUID(str(row.id))),
            name=(row.name or "").strip(),
            price_amount=_price(row.price_amount),
            price_currency=(row.price_currency or "").strip().upper() or None,
        )
        for row in rows
    }


def load_cart_products_for_phone(
    phone_number_row_id: UUID, product_ids: Collection[UUID]
) -> dict[str, CartProduct]:
    """The products of a cart, read as `qualify_webhook_worker` (m-25018684). Empty when
    no id was given, the number is unknown or has no brand."""
    if not product_ids:
        return {}
    with webhook_worker_session() as session:
        phone = session.execute(
            select(WhatsAppPhoneNumber.tenant_id, WhatsAppPhoneNumber.brand_id).where(
                WhatsAppPhoneNumber.id == phone_number_row_id
            )
        ).first()
        if phone is None or phone.brand_id is None:
            return {}
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
                BrandProduct.id.in_(list(product_ids)),
            )
        ).all()
        return to_cart_products(rows)


__all__ = [
    "FALLBACK_CATEGORY",
    "CatalogRow",
    "load_cart_products_for_phone",
    "load_catalog_for_phone",
    "to_cart_products",
    "to_catalog_items",
]
