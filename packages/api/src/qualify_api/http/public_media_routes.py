"""`GET/HEAD /public/media/{token}` (QUA-68 / ADR 28e) — the one unauthenticated route
Meta's own fetcher calls to retrieve a staged image.

Segregated under its own `/public/media` prefix, deliberately not folded into
`/api/publishing/*`: the point of a separate prefix is that "which routes skip
authentication" stays answerable by reading one router's prefix, not by auditing every
route in the app for a missing `Depends(current_principal)`. `leads_routes.py` is the
other precedent for a no-`Principal` router in this codebase, mounted at `/api/leads`
instead — this one gets its own top-level `/public/` prefix because ADR 28(e) asked for
that explicitly, and because a media-serving route benefits from being visually
distinguishable from the JSON API in any log line or dashboard that groups by path prefix.

**Every failure mode below answers with the SAME 404** — unknown token, expired token
(Redis already collapses "expired" into "not found" for us), and an object whose token is
still valid but whose R2 object is gone (`ObjectNotFound`) or outside its tenant's prefix
(`TenantPrefixViolation`, structurally unreachable in practice — `MediaTokenStore` only
ever stores keys `stage_media` itself wrote — but checked anyway, because a key read back
from a store is still input, same posture `ObjectGate.open_object` already takes). Meta,
or anyone else, must never be able to distinguish any of these from one another.

**m-24820842 (2026-11-03, clips that failed with a ReadTimeout):** BytePlus fetches a
clip's reference videos synchronously inside its task POST. This route used to read the
whole R2 object before the first byte and stream it chunked, with no length and no ranges
(TTFB 5–8 s through the dev tunnel). It now answers with `Content-Length`, `Accept-Ranges:
bytes` and single-range `206`s, and — when the store can read ranges (`R2ObjectStore`) —
streams the object in ranged reads, so the first byte leaves after the first megabyte, not
after the whole file. The token and tenant checks are exactly as before.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterator
from typing import IO
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.publishing.media_token import MediaTokenStore

router = APIRouter(prefix="/public/media", tags=["public-media"])

# Streams in fixed chunks rather than handing Starlette the whole body in one `bytes`.
_CHUNK_SIZE = 64 * 1024
#: One ranged read from the store while streaming (m-24820842): the first byte goes out
#: after this much, never after the whole object.
_RANGE_READ = 1024 * 1024

# Fixed, byte-for-byte identical across every failure branch — see the module docstring for
# why. `application/json` (not `text/plain`) so it reads like every other error body this
# API returns, in case anything ever inspects it besides Meta's fetcher.
_NOT_FOUND_BODY = b'{"detail":"not found"}'
_HEADERS = {"Cache-Control": "private, no-store", "Accept-Ranges": "bytes"}
_SINGLE_RANGE = re.compile(r"^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$")


def get_media_token_store() -> MediaTokenStore:
    """Overridden at app startup and in tests — same raising-default pattern as
    `publishing_routes.get_publish_service`."""
    raise NotImplementedError("media token store dependency is not configured")


def get_public_media_gate() -> ObjectGate:
    raise NotImplementedError("object gate dependency is not configured")


def _not_found() -> Response:
    return Response(content=_NOT_FOUND_BODY, status_code=404, media_type="application/json")


def _iter_chunks(fileobj: IO[bytes]) -> Iterator[bytes]:
    while True:
        chunk = fileobj.read(_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


def _iter_ranges(read: Callable[[int, int], IO[bytes]], start: int, end: int) -> Iterator[bytes]:
    """Bytes `start..end` inclusive, one ranged store read at a time (run by Starlette in
    a worker thread: a sync iterator never blocks the event loop)."""
    position = start
    while position <= end:
        last = min(position + _RANGE_READ - 1, end)
        yield from _iter_chunks(read(position, last))
        position = last + 1


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | bool:
    """A single `bytes=` range as inclusive (start, end); None when there is no usable
    range (absent, several ranges, another unit: the whole object is sent); False when
    it cannot be satisfied (416)."""
    if not header:
        return None
    match = _SINGLE_RANGE.match(header)
    if match is None:
        return None  # multi-range or another unit: RFC 9110 lets us send it all
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:  # a suffix: the last N bytes
        length = int(last)
        if length == 0 or size == 0:
            return False
        return max(size - length, 0), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or (last and int(last) < start):
        return False
    return start, end


class _Opened:
    """The object as this request reads it: its size, and either ranged reads from the
    store (`R2ObjectStore`) or the whole body already in memory (stores without ranges)."""

    def __init__(
        self,
        size: int,
        read: Callable[[int, int], IO[bytes]] | None = None,
        body: bytes | None = None,
    ) -> None:
        self.size = size
        self.read = read
        self.body = body

    def stream(self, start: int, end: int) -> Iterator[bytes]:
        if self.read is not None:
            return _iter_ranges(self.read, start, end)
        assert self.body is not None
        return iter((self.body[start : end + 1],)) if end >= start else iter(())


def _open(gate: ObjectGate, tenant_id: UUID, object_key: str) -> _Opened:
    """Size first (a HEAD on R2, no body read); a store that cannot read ranges (only
    `R2ObjectStore` offers them) falls back to `open_object`, the whole object, as before.
    Both doors check the tenant prefix before any store call."""
    try:
        size = gate.object_size(tenant_id, object_key)
    except (AttributeError, NotImplementedError):
        data = gate.open_object(tenant_id, object_key).read()
        return _Opened(len(data), body=data)
    return _Opened(
        size,
        read=lambda start, end: gate.open_range(tenant_id, object_key, start, end),
    )


@router.api_route("/{token}", methods=["GET", "HEAD"])
async def get_public_media(
    token: str,
    request: Request,
    store: MediaTokenStore = Depends(get_media_token_store),
    gate: ObjectGate = Depends(get_public_media_gate),
) -> Response:
    target = store.resolve(token)
    if target is None:
        return _not_found()

    try:
        opened = await asyncio.to_thread(_open, gate, target.tenant_id, target.object_key)
    except (TenantPrefixViolation, ObjectNotFound):
        return _not_found()

    size = opened.size
    wanted = parse_range(request.headers.get("range"), size)
    if wanted is False:
        return Response(
            status_code=416,
            headers={**_HEADERS, "Content-Range": f"bytes */{size}"},
        )
    start, end = wanted if isinstance(wanted, tuple) else (0, size - 1)
    headers = {**_HEADERS, "Content-Length": str(max(end - start + 1, 0))}
    status = 200
    if isinstance(wanted, tuple):
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    if request.method == "HEAD":
        return Response(status_code=status, media_type=target.content_type, headers=headers)

    return StreamingResponse(
        opened.stream(start, end),
        status_code=status,
        media_type=target.content_type,
        headers=headers,
    )
