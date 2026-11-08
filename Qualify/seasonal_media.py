"""Previews of the brand's seasonal stickers and videos (m-24976895) — a seasonal-only
variant of `r2_media`'s view tokens, NOT a generic signer.

Why a separate door: `r2_media.issue_view_path` signs only `t/`, `gallery/` and
`reel-windows/` keys, and the gate's generic reads accept any `seasonal/{tenant}/…` of the
tenant — no business bound. Seasonal media belong to ONE business, so:

- `issue_seasonal_view_path(tenant, brand, key)` mints a token only for a key that the
  gate's own exact-shape rule accepts for THIS tenant and THIS brand
  (`seasonal/{tenant}/{brand}/{season}/{uuid}.{webp|mp4}`: no `..`, no `//`, nothing
  else). The content type comes from the extension, never from the caller. The caller
  passes the session's business (Tu marca) or the number's business (the chat).
- Tokens live in their OWN Redis namespace (`seasonal:` in front of the media-token
  keys): the generic `/r2media/{token}` route cannot resolve them, and this route cannot
  resolve a generic token.
- `GET /r2seasonal/{token}` reads only through `ObjectGate.open_seasonal_media`, which
  re-checks the exact key shape for the tenant on the token and the business in the key.
  Every failure is the same 404. Same TTL and `Cache-Control` as `r2_media`.
"""

from __future__ import annotations

import asyncio
import logging
from functools import cache
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response

from .r2_media import _BASE_HEADERS, VIEW_TTL_SECONDS, parse_range

logger = logging.getLogger(__name__)

SEASONAL_MEDIA_ROUTE = "/r2seasonal"
_NAMESPACE = "seasonal:"
_TYPES = {"webp": "image/webp", "mp4": "video/mp4"}


class _NamespacedRedis:
    """The media-token store's Redis surface with every key under `seasonal:`."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def set(self, name: str, value: str, *, ex: int | None = None) -> Any:
        return self._redis.set(_NAMESPACE + name, value, ex=ex)

    def get(self, name: str) -> Any:
        return self._redis.get(_NAMESPACE + name)


def seasonal_token_store(redis: Any) -> Any:
    from qualify_api.publishing.media_token import MediaTokenStore  # noqa: PLC0415

    return MediaTokenStore(_NamespacedRedis(redis), ttl_seconds=VIEW_TTL_SECONDS)


@cache
def _token_store() -> Any:
    import redis  # noqa: PLC0415
    from qualify_api.config import redis_url  # noqa: PLC0415

    return seasonal_token_store(redis.Redis.from_url(redis_url(), decode_responses=True))


@cache
def _gate() -> Any:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


def require_seasonal_key(tenant_id: UUID, brand_id: UUID, key: str) -> str:
    """The gate's own rule (`ObjectGate._require_seasonal`: prefix of THIS business + the
    exact shape it writes); raises `TenantPrefixViolation`. Returns the content type."""
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    if not isinstance(key, str) or "//" in key or ".." in key:
        raise TenantPrefixViolation("not a seasonal key")
    # the check reads no instance state: the gate's exact rule, without a store
    ObjectGate._require_seasonal(None, tenant_id, brand_id, key)  # type: ignore[arg-type]
    return _TYPES[key.rsplit(".", 1)[-1]]


def issue_seasonal_view_path(
    tenant_id: UUID, brand_id: UUID, key: str | None, *, store: Any = None
) -> str:
    """`/r2seasonal/<token>` for one seasonal medium of THIS business, else ""."""
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    if not key or not isinstance(tenant_id, UUID) or not isinstance(brand_id, UUID):
        return ""
    try:
        content_type = require_seasonal_key(tenant_id, brand_id, key)
    except TenantPrefixViolation:
        return ""
    tokens = store or _token_store()
    token = tokens.issue(tenant_id=tenant_id, object_key=key, content_type=content_type)
    return f"{SEASONAL_MEDIA_ROUTE}/{token}"


def _brand_in(key: str) -> UUID | None:
    parts = key.split("/")
    try:
        return UUID(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return None


def _not_found() -> Response:
    return Response(status_code=404, headers={"Cache-Control": "no-store"})


router = APIRouter()


@router.api_route(SEASONAL_MEDIA_ROUTE + "/{token}", methods=["GET", "HEAD"])
async def seasonal_media(token: str, request: Request) -> Response:
    return await serve(token, request, _token_store(), _gate())


def _read(gate: Any, tenant_id: UUID, brand_id: UUID, key: str) -> bytes:
    fileobj = gate.open_seasonal_media(tenant_id, brand_id, key)
    try:
        return fileobj.read()
    finally:
        fileobj.close()


async def serve(token: str, request: Request, store: Any, gate: Any) -> Response:
    """One seasonal medium (a sticker ≤ 500 KB, a video ≤ 16 MB): whole or one range."""
    from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    target = store.resolve(token)
    if target is None:
        return _not_found()
    brand_id = _brand_in(target.object_key)
    if brand_id is None:
        return _not_found()
    try:
        body = await asyncio.to_thread(_read, gate, target.tenant_id, brand_id, target.object_key)
    except (TenantPrefixViolation, ObjectNotFound, OSError):
        return _not_found()
    size = len(body)
    if request.method == "HEAD":
        return Response(
            status_code=200,
            media_type=target.content_type,
            headers={**_BASE_HEADERS, "Content-Length": str(size)},
        )
    header = request.headers.get("range", "")
    if header:
        try:
            wanted = parse_range(header, size)
        except ValueError:
            wanted, header = (0, size - 1), ""
        if header:
            if wanted is None:
                return Response(
                    status_code=416, headers={**_BASE_HEADERS, "Content-Range": f"bytes */{size}"}
                )
            start, end = wanted
            return Response(
                content=body[start : end + 1],
                status_code=206,
                media_type=target.content_type,
                headers={**_BASE_HEADERS, "Content-Range": f"bytes {start}-{end}/{size}"},
            )
    return Response(content=body, media_type=target.content_type, headers=dict(_BASE_HEADERS))
