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
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import IO

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.publishing.media_token import MediaTokenStore

router = APIRouter(prefix="/public/media", tags=["public-media"])

# Streams in fixed chunks rather than handing Starlette the whole body in one `bytes`
# object — `ObjectGate.open_object` already returns a fully-buffered `IO[bytes]` today (see
# its own module docstring), so this does not reduce PEAK memory below what the object door
# already uses; what it avoids is a SECOND full copy inside this route's own response
# construction. Harmless either way at the 8 MB IMAGE ceiling — this is future-proofing for
# whenever `open_object` itself starts streaming from R2, not a fix for a real problem today.
_CHUNK_SIZE = 64 * 1024

# Fixed, byte-for-byte identical across every failure branch — see the module docstring for
# why. `application/json` (not `text/plain`) so it reads like every other error body this
# API returns, in case anything ever inspects it besides Meta's fetcher.
_NOT_FOUND_BODY = b'{"detail":"not found"}'


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
        fileobj = await asyncio.to_thread(gate.open_object, target.tenant_id, target.object_key)
    except (TenantPrefixViolation, ObjectNotFound):
        return _not_found()

    if request.method == "HEAD":
        # `ObjectGate.open_object` has no lightweight "exists"/"stat" primitive today (only
        # `open`, which fully reads the object) — a known, accepted cost at the 8 MB IMAGE
        # ceiling this route exists to serve, not hidden: a real `HEAD` here still opens the
        # object, just discards the body instead of streaming it out.
        body = await asyncio.to_thread(fileobj.read)
        return Response(
            status_code=200,
            media_type=target.content_type,
            headers={"Content-Length": str(len(body)), "Cache-Control": "private, no-store"},
        )

    return StreamingResponse(
        _iter_chunks(fileobj),
        media_type=target.content_type,
        headers={"Cache-Control": "private, no-store"},
    )
