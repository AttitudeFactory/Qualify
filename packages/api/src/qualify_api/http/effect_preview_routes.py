"""`GET /r2effects/<id>/v<n>` — the «Así se ve» video of a library effect (m-25120474).

The example video of a «Con IA» effect lives in R2 under a platform key
(`platform/effects/<id>/v<n>/preview.mp4`, EF-12 m-25026587), shared by every business and
naming none. The editor needs to play it without a per-business signed URL, so this route
serves exactly that key shape and nothing else:

- URL: `/r2effects/<id>/v<n>` → R2 key `platform/effects/<id>/v<n>/preview.mp4`, served as
  `video/mp4`. `<id>` matches the library's `EFFECT_ID_PATTERN` (`[a-z][a-z0-9_]{0,39}`),
  `<n>` is `1..9999` with no leading zero. The file inside the version is fixed: the URL
  never carries a file name, so it cannot name another object.
- Read-only (GET and HEAD). Any other path under `/r2effects` — an extra or missing
  segment, `..`, an encoded slash, upper case, `v0`, `v01` — answers the same 404 WITHOUT
  calling R2 (`PlatformEffectsReader` checks the id and version before any store call).
  A missing object is the same 404.
- No tenant, no session, no business: nothing tenant-scoped is read or returned.
- Cache: a version folder is written by the bench once per effect version; a new example
  is a new version (new URL). The bench may still re-upload a version whose video it
  re-made, so the cache is long but not `immutable`: one day, `public` (it is the same
  bytes for everyone).
- Range requests (one range, at most `MAX_RANGE_BYTES` per answer) so `<video>` can seek.

Mounted on the Reflex backend next to `/r2media` (`Qualify/Qualify.py`), and routed there by
the production Caddy (`deploy/Caddyfile`, `@reflex_backend`).
"""

from __future__ import annotations

import asyncio
import logging
import re
from functools import cache
from typing import Any

from fastapi import APIRouter, Request, Response
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.platform_effects import (
    PREVIEW_CONTENT_TYPE,
    NotAnEffectPreview,
    PlatformEffectsReader,
    preview_key,
)

logger = logging.getLogger(__name__)

R2_EFFECTS_ROUTE = "/r2effects"
#: One day, shared caches allowed (see the module docstring for why not `immutable`).
CACHE_CONTROL = "public, max-age=86400"
_BASE_HEADERS = {"Cache-Control": CACHE_CONTROL, "Accept-Ranges": "bytes"}
#: The most one ranged answer returns (the same 1 MiB as `/r2media`).
MAX_RANGE_BYTES = 1024 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def effect_preview_path(effect_id: str, version: int | str) -> str:
    """`/r2effects/<id>/v<n>` for one effect version, or "" when either is malformed."""
    try:
        preview_key(effect_id, version)
    except NotAnEffectPreview:
        return ""
    return f"{R2_EFFECTS_ROUTE}/{effect_id}/v{version}"


def path_for_key(key: object) -> str:
    """The route for an R2 key `platform/effects/<id>/v<n>/preview.mp4`, else ""."""
    from qualify_shared.objects.platform_effects import is_effect_preview_key  # noqa: PLC0415

    if not is_effect_preview_key(key):
        return ""
    effect_id, folder, _file = str(key).split("/")[2:5]
    return effect_preview_path(effect_id, folder[1:])


@cache
def _reader() -> PlatformEffectsReader:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return PlatformEffectsReader(R2ObjectStore(R2Settings.from_env()))


def _not_found() -> Response:
    return Response(status_code=404, headers={"Cache-Control": "no-store"})


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """The single range asked for, clamped to the object and to `MAX_RANGE_BYTES`;
    `None` when unsatisfiable (→ 416). `ValueError` when not understood (→ whole object)."""
    match = _RANGE.match(header.replace(" ", ""))
    if not match or (not match[1] and not match[2]):
        raise ValueError(header)
    if not match[1]:
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


router = APIRouter()


@router.api_route(R2_EFFECTS_ROUTE + "/{effect_id}/{version}", methods=["GET", "HEAD"])
async def effect_preview(effect_id: str, version: str, request: Request) -> Response:
    return await serve(effect_id, version, request, _reader)


@router.api_route(R2_EFFECTS_ROUTE, methods=["GET", "HEAD"])
@router.api_route(R2_EFFECTS_ROUTE + "/{rest:path}", methods=["GET", "HEAD"])
async def not_an_effect_preview(request: Request, rest: str = "") -> Response:
    """Every other shape under `/r2effects` (extra or missing segments): the same 404."""
    return _not_found()


async def serve(effect_id: str, version: str, request: Request, reader: Any) -> Response:
    """One effect version's example video. `reader` is a callable returning the
    `PlatformEffectsReader` — called only once the id and version are valid."""
    raw_path = request.scope.get("raw_path") or b""
    if not version.startswith("v") or b"%" in raw_path or b"\\" in raw_path:
        return _not_found()  # the real URL is plain ASCII: any escape is not one of ours
    number = version[1:]
    try:
        preview_key(effect_id, number)
    except NotAnEffectPreview:
        return _not_found()  # nothing reached R2
    door = reader()
    header = request.headers.get("range", "")
    try:
        if header or request.method == "HEAD":
            size = await asyncio.to_thread(door.size, effect_id, number)
            if request.method == "HEAD":
                return Response(
                    status_code=200,
                    media_type=PREVIEW_CONTENT_TYPE,
                    headers={**_BASE_HEADERS, "Content-Length": str(size)},
                )
            try:
                wanted = _parse_range(header, size)
            except ValueError:
                wanted, header = None, ""  # not understood: the whole object below
            if header:
                if wanted is None:
                    return Response(
                        status_code=416,
                        headers={**_BASE_HEADERS, "Content-Range": f"bytes */{size}"},
                    )
                start, end = wanted
                body = await asyncio.to_thread(
                    lambda: _read(door.open_range(effect_id, number, start, end))
                )
                return Response(
                    content=body,
                    status_code=206,
                    media_type=PREVIEW_CONTENT_TYPE,
                    headers={**_BASE_HEADERS, "Content-Range": f"bytes {start}-{end}/{size}"},
                )
        body = await asyncio.to_thread(lambda: _read(door.open(effect_id, number)))
    except ObjectNotFound:
        return _not_found()
    return Response(
        content=body, status_code=200, media_type=PREVIEW_CONTENT_TYPE, headers=_BASE_HEADERS
    )


def _read(fileobj: Any) -> bytes:
    try:
        return fileobj.read()
    finally:
        fileobj.close()
