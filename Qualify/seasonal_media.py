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
import threading
import time
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


def require_seasonal_key(tenant_id: UUID, brand_id: UUID, key: str, *, gate: Any = None) -> str:
    """The gate's public rule (`ObjectGate.seasonal_key_for`: the prefix of THIS business
    and the exact shape it writes); raises `TenantPrefixViolation`. Returns the content
    type, from the extension."""
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    if not isinstance(key, str) or "//" in key or ".." in key:
        raise TenantPrefixViolation("not a seasonal key")
    checked = (gate or _gate()).seasonal_key_for(tenant_id, brand_id, key)
    return _TYPES[checked.rsplit(".", 1)[-1]]


# Minted paths reused while their token has more than this left (process memory, like
# `r2_media`): a refresh every 5 s must not make the browser download every preview again.
_REUSE_MARGIN_SECONDS = 15 * 60
#: value = (path, token end, the store that minted it). The store itself is kept and
#: compared by identity: an `id()` alone can be reused by a new store once the old one is
#: garbage-collected, which served a token the new store never issued (CI flake on #604).
_issued: dict[tuple[UUID, UUID, str, int], tuple[str, float, Any]] = {}
_issued_lock = threading.Lock()


def issue_seasonal_view_path(
    tenant_id: UUID, brand_id: UUID, key: str | None, *, store: Any = None, gate: Any = None
) -> str:
    """`/r2seasonal/<token>` for one seasonal medium of THIS business, else ""."""
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    if not key or not isinstance(tenant_id, UUID) or not isinstance(brand_id, UUID):
        return ""
    try:
        content_type = require_seasonal_key(tenant_id, brand_id, key, gate=gate)
    except TenantPrefixViolation:
        return ""
    tokens = store or _token_store()
    cache_key = (tenant_id, brand_id, key, id(tokens))
    now = time.monotonic()
    with _issued_lock:
        hit = _issued.get(cache_key)
        if hit is not None and hit[2] is tokens and hit[1] - now > _REUSE_MARGIN_SECONDS:
            return hit[0]
    token = tokens.issue(tenant_id=tenant_id, object_key=key, content_type=content_type)
    path = f"{SEASONAL_MEDIA_ROUTE}/{token}"
    with _issued_lock:
        # prune on insert: an entry past its reuse margin is never served again
        for stale in [
            k for k, (_p, ends, _s) in _issued.items() if ends - now <= _REUSE_MARGIN_SECONDS
        ]:
            del _issued[stale]
        _issued[cache_key] = (path, now + VIEW_TTL_SECONDS, tokens)
    return path


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


def _checked(gate: Any, tenant_id: UUID, brand_id: UUID, key: str) -> int:
    """The business-bound check FIRST (`seasonal_key_for`), then the object's size."""
    gate.seasonal_key_for(tenant_id, brand_id, key)
    return gate.object_size(tenant_id, key)


def _read_whole(gate: Any, tenant_id: UUID, brand_id: UUID, key: str) -> bytes:
    fileobj = gate.open_seasonal_media(tenant_id, brand_id, key)
    try:
        return fileobj.read()
    finally:
        fileobj.close()


def _read_range(gate: Any, tenant_id: UUID, key: str, start: int, end: int) -> bytes:
    fileobj = gate.open_range(tenant_id, key, start, end)
    try:
        return fileobj.read()
    finally:
        fileobj.close()


async def serve(token: str, request: Request, store: Any, gate: Any) -> Response:
    """One seasonal medium: HEAD, one byte range (`r2_media`'s pattern: the gate's
    `object_size` + `open_range`, after the business-bound check), or the whole object
    through `open_seasonal_media`. Every failure is the same 404."""
    from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    target = store.resolve(token)
    brand_id = _brand_in(target.object_key) if target is not None else None
    if target is None or brand_id is None:
        return _not_found()
    tenant_id, key = target.tenant_id, target.object_key
    header = request.headers.get("range", "")
    try:
        if header or request.method == "HEAD":
            size = await asyncio.to_thread(_checked, gate, tenant_id, brand_id, key)
            if request.method == "HEAD":
                return Response(
                    status_code=200,
                    media_type=target.content_type,
                    headers={**_BASE_HEADERS, "Content-Length": str(size)},
                )
            try:
                wanted = parse_range(header, size)
            except ValueError:
                wanted, header = (0, size - 1), ""
            if header:
                if wanted is None:
                    return Response(
                        status_code=416,
                        headers={**_BASE_HEADERS, "Content-Range": f"bytes */{size}"},
                    )
                start, end = wanted
                body = await asyncio.to_thread(_read_range, gate, tenant_id, key, start, end)
                return Response(
                    content=body,
                    status_code=206,
                    media_type=target.content_type,
                    headers={**_BASE_HEADERS, "Content-Range": f"bytes {start}-{end}/{size}"},
                )
        body = await asyncio.to_thread(_read_whole, gate, tenant_id, brand_id, key)
    except (TenantPrefixViolation, ObjectNotFound, OSError):
        return _not_found()
    return Response(content=body, media_type=target.content_type, headers=dict(_BASE_HEADERS))
