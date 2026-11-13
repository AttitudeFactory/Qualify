"""`GET/HEAD /public/catalog-media/{tenant_id}/{media_id}/{sig}.jpg` (ADR 48 §8) — the
stable, signed URL Meta's catalog fetcher downloads a product's primary photo from.

Unlike `/public/media/{token}` (a 15-minute Redis token), a catalog image must stay
fetchable for as long as the item is in the catalog: Meta re-downloads it when it wants.
So the URL is stable and signed — `catalog_sync.media_url` holds the HMAC — and revoked by
state instead of by expiry: deleting the photo, removing the item (`deleted`) or rotating
the secret. Changing the primary photo does NOT revoke the old URL on purpose: any image of
a product with a live item is served, because Meta may keep the old URL until the owner
resyncs, and a 404 meanwhile would break the picture in WhatsApp (main thread, 2026-11-12).

Order of checks, every failure answering the SAME 404 byte for byte:

1. UUID shapes and the signature (`hmac.compare_digest`), BEFORE any database access;
   an unusable secret (missing, the development default, < 32 characters) fails here too.
2. Through `tenant_session(tenant_id)`: a `product_media` image row with that id whose
   product has an item not `deleted` in one of the business's catalogs.
3. `ObjectGate` opens the object with the tenant-prefix check (`TenantPrefixViolation`) and
   the object exists (`ObjectNotFound`). The gate is built only here, after the signature
   verified (a missing R2 setting is the same 404, never a 500). `_open`, not
   `_open_unpurged`: a `product_media` key is always `t/{tenant}/uploads/catalog/…`
   (`catalog/service.py`, the only writer), never a retention-purged piece folder
   (`t/{tenant}/generated/…`).

The answer: `Content-Type` from the row, `Content-Length`, single ranges like
`public_media_routes.py`, `Cache-Control: public, max-age=86400` (each file has a new key,
so the object behind a URL never changes).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.http.public_media_routes import _open, _Opened, parse_range
from qualify_api.whatsapp.catalog_sync.media_url import ROUTE_PREFIX, verify

router = APIRouter(prefix=ROUTE_PREFIX, tags=["public-catalog-media"])

_NOT_FOUND_BODY = b'{"detail":"not found"}'
_HEADERS = {"Cache-Control": "public, max-age=86400", "Accept-Ranges": "bytes"}
_SUFFIX = ".jpg"


@dataclass(frozen=True)
class CatalogMediaTarget:
    object_key: str
    content_type: str


CatalogMediaLookup = Callable[[UUID, UUID], CatalogMediaTarget | None]


def lookup_catalog_media(tenant_id: UUID, media_id: UUID) -> CatalogMediaTarget | None:
    """Step 2, through `tenant_session` (RLS bounds it to the tenant in the URL)."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import exists, select  # noqa: PLC0415

    from qualify_api.catalog.models import ProductMedia  # noqa: PLC0415
    from qualify_api.whatsapp.models import WhatsAppCatalogItem  # noqa: PLC0415

    live_item = exists().where(
        WhatsAppCatalogItem.product_id == ProductMedia.product_id,
        WhatsAppCatalogItem.state != "deleted",
    )
    with tenant_session(tenant_id) as session:
        row = session.execute(
            select(ProductMedia.object_key, ProductMedia.content_type).where(
                ProductMedia.id == media_id,
                ProductMedia.media_type == "image",
                live_item,
            )
        ).first()
    if row is None:
        return None
    return CatalogMediaTarget(object_key=row.object_key, content_type=row.content_type)


def get_catalog_media_lookup() -> CatalogMediaLookup:
    """Overridden in tests; the production lookup reads Postgres."""
    return lookup_catalog_media


GateFactory = Callable[[], ObjectGate]


def get_catalog_media_gate() -> GateFactory:
    """A FACTORY, called only after the signature verified (its failures are the 404)."""
    raise NotImplementedError("object gate dependency is not configured")


def _not_found() -> Response:
    return Response(content=_NOT_FOUND_BODY, status_code=404, media_type="application/json")


def _uuid(value: str) -> UUID | None:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
    # Only the canonical spelling is signed: a braced or uppercase variant is not the URL.
    return parsed if str(parsed) == value else None


def _resolve(
    lookup: CatalogMediaLookup, gate_factory: GateFactory, tenant_id: UUID, media_id: UUID
) -> tuple[CatalogMediaTarget, _Opened] | None:
    target = lookup(tenant_id, media_id)
    if target is None:
        return None
    try:
        return target, _open(gate_factory(), tenant_id, target.object_key)
    except (TenantPrefixViolation, ObjectNotFound):
        return None


@router.api_route("/{tenant_id}/{media_id}/{filename}", methods=["GET", "HEAD"])
async def get_catalog_media(
    tenant_id: str,
    media_id: str,
    filename: str,
    request: Request,
    lookup: CatalogMediaLookup = Depends(get_catalog_media_lookup),
    gate_factory: GateFactory = Depends(get_catalog_media_gate),
) -> Response:
    tenant = _uuid(tenant_id)
    media = _uuid(media_id)
    if tenant is None or media is None or not filename.endswith(_SUFFIX):
        return _not_found()
    if not verify(tenant, media, filename[: -len(_SUFFIX)]):
        return _not_found()

    try:
        found = await asyncio.to_thread(_resolve, lookup, gate_factory, tenant, media)
    except Exception:  # noqa: BLE001 — any lookup failure is the same 404
        return _not_found()
    if found is None:
        return _not_found()
    target, opened = found

    size = opened.size
    wanted = parse_range(request.headers.get("range"), size)
    if wanted is False:
        return Response(status_code=416, headers={**_HEADERS, "Content-Range": f"bytes */{size}"})
    start, end = wanted if isinstance(wanted, tuple) else (0, size - 1)
    headers = {**_HEADERS, "Content-Length": str(max(end - start + 1, 0))}
    status = 200
    if isinstance(wanted, tuple):
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    media_type = target.content_type or "image/jpeg"
    if request.method == "HEAD":
        return Response(status_code=status, media_type=media_type, headers=headers)
    return StreamingResponse(
        opened.stream(start, end), status_code=status, media_type=media_type, headers=headers
    )
