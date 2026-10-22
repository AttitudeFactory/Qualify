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

from decimal import Decimal
from functools import cache
from uuid import UUID

from qualify_api.catalog.service import CatalogError, CatalogService
from qualify_api.creative.composition import media_root
from qualify_api.creative.media import LocalMediaStore
from qualify_creative.video import FfmpegVideoNormalizer

from .catalog_vm import ProductVM, build_product_vm

__all__ = [
    "CatalogError",
    "add_media",
    "create_product",
    "list_products",
    "remove_media",
    "set_primary",
    "update_product",
]


@cache
def _service() -> CatalogService:
    """One service per process: the store root and the ffmpeg wrapper are stateless."""
    return CatalogService(store=LocalMediaStore(media_root()), video=FfmpegVideoNormalizer())


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


def add_media(tenant_id: UUID, product_id: UUID, *, data: bytes, filename: str) -> None:
    """Normalizes (photo or clip) and stores one file. Raises `CatalogError`."""
    _service().add_media(tenant_id=tenant_id, product_id=product_id, data=data, filename=filename)


def set_primary(tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
    _service().set_primary(tenant_id=tenant_id, product_id=product_id, media_id=media_id)


def remove_media(tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
    _service().remove_media(tenant_id=tenant_id, product_id=product_id, media_id=media_id)
