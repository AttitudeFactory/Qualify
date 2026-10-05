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
from qualify_api.tenancy.models import Tenant
from qualify_creative.video import FfmpegVideoNormalizer
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .catalog_vm import DEFAULT_CURRENCY, ProductVM, build_product_vm

__all__ = [
    "CatalogError",
    "add_media",
    "create_product",
    "list_products",
    "remove_media",
    "set_primary",
    "tenant_currency",
    "update_product",
]


@cache
def _service() -> CatalogService:
    """One service per process: the store root and the ffmpeg wrapper are stateless."""
    return CatalogService(store=LocalMediaStore(media_root()), video=FfmpegVideoNormalizer())


def tenant_currency(tenant_id: UUID) -> str:
    """The tenant's ISO-4217 currency (signup's choice), `DEFAULT_CURRENCY` when the
    row cannot be read — a default for a form field is not worth failing the page."""
    try:
        with tenant_session(tenant_id) as session:
            value = session.scalar(select(Tenant.currency).where(Tenant.id == tenant_id))
    except Exception:  # noqa: BLE001 — a default is all that is needed
        return DEFAULT_CURRENCY
    return (value or DEFAULT_CURRENCY).strip().upper()


def list_products(tenant_id: UUID, brand_id: UUID) -> tuple[ProductVM, ...]:
    records = _service().list_products(tenant_id=tenant_id, brand_id=brand_id)
    return tuple(build_product_vm(record) for record in records)


def create_product(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    *,
    name: str,
    price_amount: Decimal | None,
    currency: str,
    description: str,
    category: str,
) -> UUID:
    """Raises `CatalogError` (Spanish message in `args[0]`) when the service refuses."""
    return _service().create_product(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        name=name,
        price_amount=price_amount,
        price_currency=currency,
        description=description,
        category=category,
    )


def update_product(
    tenant_id: UUID,
    product_id: UUID,
    *,
    name: str,
    price_amount: Decimal | None,
    currency: str,
    description: str,
    category: str,
) -> None:
    _service().update_product(
        tenant_id=tenant_id,
        product_id=product_id,
        name=name,
        price_amount=price_amount,
        price_currency=currency,
        description=description,
        category=category,
    )


def add_media(tenant_id: UUID, product_id: UUID, *, data: bytes, filename: str) -> None:
    """Normalizes (photo or clip) and stores one file. Raises `CatalogError`."""
    _service().add_media(tenant_id=tenant_id, product_id=product_id, data=data, filename=filename)


def set_primary(tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
    _service().set_primary(tenant_id=tenant_id, product_id=product_id, media_id=media_id)


def remove_media(tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
    _service().remove_media(tenant_id=tenant_id, product_id=product_id, media_id=media_id)
