"""The seam between the catalog screen and `qualify_api.catalog` — thin, by design.

Every function here wraps one `CatalogService` call and returns `catalog_vm` shapes (or
nothing). The service owns every rule (normalization at upload, the primary photo, the
per-product cap); this module only wires the store it writes to — the SAME upload
directory the app serves with `rx.get_upload_url` (`media_root()`), so a catalog photo's
key renders in the browser exactly like a generator upload does — and translates the
service's records into view models.

Every function is a blocking DB (and for `add_media`, CPU: Pillow / ffmpeg) call —
callers on the event loop must run them off-thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from functools import cache
from uuid import UUID

from qualify_api.catalog.service import (
    CatalogError,
    CatalogService,
    OrderRefused,
    UnknownCategory,
    UnknownProduct,
)
from qualify_api.creative.composition import media_root
from qualify_api.creative.media import LocalMediaStore
from qualify_api.tenancy.models import Tenant
from qualify_creative.video import FfmpegVideoNormalizer
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .catalog_order_vm import OrderGroup, OrderItem
from .catalog_vm import ProductVM, build_product_vm

__all__ = [
    "CatalogError",
    "OrderRefused",
    "UnknownCategory",
    "UnknownProduct",
    "list_order",
    "set_category",
    "suggest_groups",
    "save_category_order",
    "save_product_order",
    "add_media",
    "business_currency",
    "create_product",
    "deactivate_product",
    "list_products",
    "remove_media",
    "reorder_media",
    "set_primary",
    "update_product",
    "product_price_label",
    "update_product_price",
]


@cache
def _service() -> CatalogService:
    """One service per process: the store root and the ffmpeg wrapper are stateless."""
    return CatalogService(store=LocalMediaStore(media_root()), video=FfmpegVideoNormalizer())


def business_currency(tenant_id: UUID) -> str:
    """The currency the business chose at signup (`tenants.currency`), read under the
    tenant's own RLS: the «Agregar producto» form starts with it (m-24842974)."""
    with tenant_session(tenant_id) as session:
        code = session.execute(
            select(Tenant.currency).where(Tenant.id == tenant_id)
        ).scalar_one_or_none()
    return code or ""


def list_products(tenant_id: UUID, brand_id: UUID) -> tuple[ProductVM, ...]:
    records = _service().list_products(tenant_id=tenant_id, brand_id=brand_id)
    return tuple(build_product_vm(record) for record in records)


def create_product(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    *,
    name: str,
    description: str,
    category: str,
    price_amount: Decimal | None = None,
    price_currency: str = "",
) -> UUID:
    """Raises `CatalogError` (Spanish message in `args[0]`) when the service refuses.
    The price is OPTIONAL (m-24803289): `None` creates a product without one, and the
    pieces of such a product print no price at all rather than an invented one."""
    return _service().create_product(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        name=name,
        description=description,
        category=category,
        price_amount=price_amount,
        price_currency=price_currency,
    )


def update_product(
    tenant_id: UUID,
    product_id: UUID,
    *,
    name: str,
    description: str,
    category: str,
    price_amount: Decimal | None = None,
    price_currency: str = "",
) -> None:
    """The editor shows the stored price, so what it sends is what the product keeps:
    an amount replaces it and `None` clears it — that is the operator emptying the
    field on purpose, the only way the screen ever drops a price."""
    _service().update_product(
        tenant_id=tenant_id,
        product_id=product_id,
        name=name,
        description=description,
        category=category,
        price_amount=price_amount,
        price_currency=price_currency,
    )


def update_product_price(tenant_id: UUID, product_id: UUID, amount: Decimal) -> None:
    """Only the price of one product (the «Precio» edited in «Datos clave», once the
    piece is made — founder 2026-11-04): the currency, name and the rest stay. Under the
    tenant's own RLS (`CatalogService`), so another business's product is
    `UnknownProduct` and nothing is written."""
    _service().update_product(tenant_id=tenant_id, product_id=product_id, price_amount=amount)


def product_price_label(tenant_id: UUID, product_id: UUID) -> str:
    """The product's price as the catalog has it NOW, in its own formatting ("" without
    one) — read again before a «Datos clave» edit is written back, so a change made
    meanwhile (another tab, the Catálogo screen) is never overwritten. Under the
    tenant's RLS: another business's product is `UnknownProduct`."""
    return _service().get_product(tenant_id=tenant_id, product_id=product_id).price_label


def deactivate_product(tenant_id: UUID, product_id: UUID) -> None:
    """«Eliminar producto» (request 2026-10-22): the row stays — pieces already made
    from it keep their provenance — but it leaves the catalog and every picker."""
    _service().update_product(tenant_id=tenant_id, product_id=product_id, is_active=False)


def add_media(tenant_id: UUID, product_id: UUID, *, data: bytes, filename: str) -> None:
    """Normalizes (photo or clip) and stores one file. Raises `CatalogError`."""
    _service().add_media(tenant_id=tenant_id, product_id=product_id, data=data, filename=filename)


def set_primary(tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
    _service().set_primary(tenant_id=tenant_id, product_id=product_id, media_id=media_id)


def reorder_media(tenant_id: UUID, product_id: UUID, ordered_ids: Sequence[str]) -> None:
    """The media in this order; the first photo becomes the primary."""
    _service().reorder_media(
        tenant_id=tenant_id,
        product_id=product_id,
        ordered_ids=tuple(UUID(media_id) for media_id in ordered_ids),
    )


def remove_media(tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
    _service().remove_media(tenant_id=tenant_id, product_id=product_id, media_id=media_id)


# -- «Ordenar tu menú» (m-24955643) -------------------------------------------------------


def list_order(tenant_id: UUID, brand_id: UUID) -> tuple[OrderGroup, ...]:
    """The brand's active products as the customer sees them on WhatsApp: ordered
    categories («Otros» included, last unless the owner moved it), each with its products
    in order (`CatalogService.list_ordered`, the one ordering rule)."""
    groups = _service().list_ordered(tenant_id=tenant_id, brand_id=brand_id)
    return tuple(
        OrderGroup(
            name=group.name,
            label=group.label,
            products=tuple(
                OrderItem(product_id=str(p.id), name=p.name, price_label=p.price_label)
                for p in group.products
            ),
        )
        for group in groups
    )


def save_category_order(
    tenant_id: UUID, brand_id: UUID, user_id: UUID | None, names: Sequence[str]
) -> None:
    """The whole category order ("" = «Otros»). Raises `UnknownCategory` /
    `OrderRefused` when the list changed under the screen."""
    _service().set_category_order(
        tenant_id=tenant_id, brand_id=brand_id, names=list(names), user_id=user_id
    )


def save_product_order(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    category: str,
    product_ids: Sequence[str],
) -> None:
    """The order of ONE category's products. Raises `UnknownCategory` / `OrderRefused`."""
    _service().reorder_products(
        tenant_id=tenant_id,
        brand_id=brand_id,
        category=category,
        product_ids=[UUID(i) for i in product_ids],
        user_id=user_id,
    )


# -- «Agrupa tus productos» (m-24955838) --------------------------------------------------


def suggest_groups(tenant_id: UUID, brand_id: UUID) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The sections to propose for the products without a category: (name, product ids),
    largest first (`CatalogService.suggest_category_groups`, no AI)."""
    groups = _service().suggest_category_groups(tenant_id=tenant_id, brand_id=brand_id)
    return tuple((g.name, tuple(str(i) for i in g.product_ids)) for g in groups)


def set_category(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    product_ids: Sequence[str],
    category: str,
) -> tuple[str, int, bool]:
    """Several products into one category ("" = back to «Otros»): (the category as
    stored, how many moved, whether it was created). Raises `UnknownProduct`,
    `OrderRefused`, or `CatalogError` with the owner's message (a name over 24 letters)."""
    done = _service().set_products_category(
        tenant_id=tenant_id,
        brand_id=brand_id,
        product_ids=[UUID(i) for i in product_ids],
        category=category,
        user_id=user_id,
    )
    return done.category, done.moved, done.created
