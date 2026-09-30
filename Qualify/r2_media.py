"""Media that lives ONLY in R2, shown and downloaded from the draft screen.

The problem (request 2026-09-30, "no se ve el video" / "descargar → Not Found"): the
draft screen resolves every media key with `rx.get_upload_url`, i.e. the backend's
LOCAL upload store. A POST whose media exists only in R2 (`t/{tenant}/…` keys, e.g.
media staged for publishing) has nothing there, so the player stays black and the
download link answers 404. Nothing in the app served R2 objects to a browser.

The fix reuses QUA-68's door instead of adding a second one (ADR 28e):
- `issue_view_path` mints a `MediaTokenStore` token — 256 random bits, only its hash
  stored in Redis, never derived from the tenant or the key — for ONE object, and only
  for a key under the viewing tenant's own prefix. It is called server-side while the
  draft is read through RLS, so a token can only ever name an object of a draft that
  tenant could already see.
- `GET /r2media/{token}` answers through `public_media_routes.get_public_media` itself:
  same tenant-prefix check on the way out (`ObjectGate`), same single 404 for every
  failure. `?download=1` only adds `Content-Disposition: attachment`.
- Tokens live `VIEW_TTL_SECONDS` (1 h): long enough to watch and download, short enough
  that a copied link dies. Reloading the draft mints fresh ones.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from functools import cache
from uuid import UUID

import reflex as rx
from fastapi import APIRouter, Request, Response
from reflex.constants import Dirs
from reflex.utils.imports import ImportVar
from reflex.vars import VarData

logger = logging.getLogger(__name__)

R2_MEDIA_ROUTE = "/r2media"
VIEW_TTL_SECONDS = 60 * 60
_R2_PREFIX = "t/"

# What the POST's media_type implies when the row does not carry a content type — the
# formats the creative pipeline and the publisher use (MP4 video, JPEG image).
_DEFAULT_CONTENT_TYPE = {"video": "video/mp4", "image": "image/jpeg"}


def is_r2_key(key: str) -> bool:
    return key.startswith(_R2_PREFIX)


@cache
def _token_store():
    import redis  # noqa: PLC0415
    from qualify_api.config import redis_url  # noqa: PLC0415
    from qualify_api.publishing.media_token import MediaTokenStore  # noqa: PLC0415

    return MediaTokenStore(
        redis.Redis.from_url(redis_url(), decode_responses=True), ttl_seconds=VIEW_TTL_SECONDS
    )


@cache
def _gate():
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


def issue_view_path(
    tenant_id: UUID, key: str, media_type: str, content_type: str | None = None, *, store=None
) -> str:
    """`/r2media/<token>` for one R2 object of `tenant_id`, or "" when `key` is not an
    R2 key of THAT tenant (then the caller keeps the local upload-store path)."""
    from qualify_shared.objects.keys import (  # noqa: PLC0415
        TenantPrefixViolation,
        require_tenant_prefix,
    )

    if not is_r2_key(key):
        return ""
    try:
        require_tenant_prefix(tenant_id, key)
    except TenantPrefixViolation:
        return ""
    tokens = store or _token_store()
    # Same object, same viewer tenant → same URL while the token has life left: the list,
    # the calendar and the dialog then share ONE browser cache entry instead of each
    # re-downloading the same bytes under a fresh token (measured 2026-09-30: 53 range
    # requests / 106 MB for two reels shown on a few cards).
    cache_key = (tenant_id, key, id(tokens))
    now = time.monotonic()
    with _issued_lock:
        hit = _issued.get(cache_key)
        if hit is not None and hit[1] - now > _REUSE_MARGIN_SECONDS:
            return hit[0]
    token = tokens.issue(
        tenant_id=tenant_id,
        object_key=key,
        content_type=content_type
        or _DEFAULT_CONTENT_TYPE.get(media_type, "application/octet-stream"),
    )
    path = f"{R2_MEDIA_ROUTE}/{token}"
    with _issued_lock:
        _issued[cache_key] = (path, now + VIEW_TTL_SECONDS)
    return path


# Minted paths kept for reuse (process memory; a restart just mints new ones). A path is
# reused only while its token has more than this left, so a page never gets one that
# dies while it is open.
_REUSE_MARGIN_SECONDS = 15 * 60
_issued: dict[tuple[UUID, str, int], tuple[str, float]] = {}
_issued_lock = threading.Lock()


router = APIRouter()

#: The most one ranged response returns. A browser opens a video with `Range: bytes=0-`
#: ("from here to the end"); answering with at most this much is allowed by HTTP (the
#: `Content-Range` says what was sent) and makes it ask for the next piece only if it
#: needs it. 1 MiB, not more: a fragmented MP4 (these reels are `moof`/`mdat`) makes the
#: browser probe each fragment index with an open-ended range, and each probe used to
#: cost the whole cap (2 MiB) for a ~2 KB read. Still ahead of playback bitrate.
MAX_RANGE_BYTES = 1024 * 1024

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_EXTENSIONS = {"video/mp4": "mp4", "video/quicktime": "mov", "image/jpeg": "jpg"}
# `private` (never a shared cache) but cacheable: the URL is an opaque token that dies
# with the token, and the bytes behind a key never change — so the browser may reuse a
# range it already has instead of asking again. `no-store` forced a re-download per card.
_CACHE = f"private, max-age={VIEW_TTL_SECONDS - _REUSE_MARGIN_SECONDS}"
_BASE_HEADERS = {"Cache-Control": _CACHE, "Accept-Ranges": "bytes"}


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """The single byte range `header` asks for, clamped to the object and to
    `MAX_RANGE_BYTES`; `None` when it cannot be satisfied (→ 416). Raises `ValueError`
    for a header this route does not understand (several ranges, other units) — the
    caller then ignores it and serves the whole object, as HTTP allows."""
    match = _RANGE.match(header.replace(" ", ""))
    if not match or (not match[1] and not match[2]):
        raise ValueError(header)
    if not match[1]:  # suffix: the last N bytes
        length = int(match[2])
        if length == 0 or size == 0:
            return None
        start, end = max(0, size - length), size - 1
    else:
        start = int(match[1])
        end = int(match[2]) if match[2] else size - 1
        if start >= size or end < start:
            return None
        end = min(end, size - 1)
    return start, min(end, start + MAX_RANGE_BYTES - 1)


def _log_served(request: Request, response: Response, header: str) -> Response:
    """One line per request — status, the Range asked for and the bytes actually sent —
    so "the browser no longer pulls whole reels" is measurable from the server log. No
    token, no key, no tenant in it (ids of objects are not log material)."""
    logger.info(
        "r2media.served method=%s status=%s range=%s bytes=%s",
        request.method,
        response.status_code,
        header or "-",
        response.headers.get("content-length", "stream"),
    )
    return response


@router.api_route(R2_MEDIA_ROUTE + "/{token}", methods=["GET", "HEAD"])
async def r2_media(token: str, request: Request, download: int = 0) -> Response:
    header = "" if download else request.headers.get("range", "")
    return _log_served(request, await _serve(token, request, download), header)


async def _serve(token: str, request: Request, download: int) -> Response:
    from qualify_api.http.public_media_routes import _not_found, get_public_media  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    store, gate = _token_store(), _gate()
    target = store.resolve(token)
    if target is None:
        return _not_found()
    header = "" if download else request.headers.get("range", "")
    if header or request.method == "HEAD":
        try:
            size = gate.object_size(target.tenant_id, target.object_key)
        except (TenantPrefixViolation, ObjectNotFound):
            return _not_found()
        if request.method == "HEAD":
            return Response(
                status_code=200,
                media_type=target.content_type,
                headers={**_BASE_HEADERS, "Content-Length": str(size)},
            )
        try:
            wanted = parse_range(header, size)
        except ValueError:
            wanted = (0, size - 1) if size else None
            header = ""  # not understood: fall through to the whole object below
        if header:
            if wanted is None:
                return Response(
                    status_code=416, headers={**_BASE_HEADERS, "Content-Range": f"bytes */{size}"}
                )
            start, end = wanted
            try:
                body = gate.open_range(target.tenant_id, target.object_key, start, end).read()
            except (TenantPrefixViolation, ObjectNotFound):
                return _not_found()
            return Response(
                content=body,
                status_code=206,
                media_type=target.content_type,
                headers={**_BASE_HEADERS, "Content-Range": f"bytes {start}-{end}/{size}"},
            )

    # No range (or a download): the whole object, through QUA-68's own route — same
    # tenant-prefix check and the same single 404.
    response = await get_public_media(token, request, store=store, gate=gate)
    if response.status_code == 200:
        response.headers["Accept-Ranges"] = "bytes"
        if download:
            extension = _EXTENSIONS.get((response.media_type or "").lower(), "bin")
            response.headers["Content-Disposition"] = (
                f'attachment; filename="qualify-media.{extension}"'
            )
    return response


#: The backend's origin in the browser — same expression as
#: `creative_wizard_pages._AVATAR_BASE` (`getBackendURL(env.UPLOAD)` minus `/_upload`).
BACKEND_BASE: rx.Var[str] = rx.Var(
    _js_expr='(String(getBackendURL(env.UPLOAD)).replace(/\\/_upload\\/?$/, ""))',
    _var_data=VarData(
        imports={
            f"$/{Dirs.STATE_PATH}": "getBackendURL",
            "$/env.json": ImportVar(tag="env", is_default=True),
        }
    ),
).to(str)
