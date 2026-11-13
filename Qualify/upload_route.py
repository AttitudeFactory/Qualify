"""`GET /_upload/<key>` keeps working once the owner's files live in R2 (CM-9, m-24957283).

Every screen shows an upload with `rx.get_upload_url(key)` — a path on Reflex's own
static route over the `uploads` volume. Since CM-9 a new upload is an R2 key
(`t/{tenant}/uploads/…`) and an old one is moved to R2 by the one-time copy, so this
middleware sits in front of that route (`api_transformer`, `Qualify.py`):

1. a file that IS on the volume is left to Reflex, exactly as before;
2. an owner upload in R2 (`t/{tenant}/uploads/…`, or an old piece copied to
   `t/{tenant}/generated-local/…` — `owner_uploads.served_upload_tenant`) is streamed from
   R2 through `ObjectGate`;
3. an old local key no longer on disk is looked up in the key map
   (`owner_uploads.resolve_moved_key`, under that key's own tenant: RLS) and its R2
   object streamed;
4. anything else falls through to Reflex (its own 404).

**Exposure does not widen.** The route served the volume's files to anyone holding the
path before CM-9; it serves the very same files now, and nothing else of R2: the Brand
Kit, the pieces and the connections' objects stay behind `/r2media` tokens. Every
upload key carries a fresh `uuid4`. The headers are Reflex's own for uploads
(`X-Content-Type-Options: nosniff`, `Content-Disposition: attachment` except a PDF), so an
uploaded HTML or SVG never runs as a page.

Memory: ranges are read from R2 with `ObjectGate.open_range`; a whole-object GET is
streamed in 1 MiB ranges, never buffered (the `reflex` container is capped at 768 MiB
with FFmpeg inside).
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

UPLOAD_PREFIX = "/_upload/"
#: Bytes per R2 ranged read (a ranged request is also clamped to this by `parse_range`).
_CHUNK = 1024 * 1024
#: The bytes behind a key never change (written once), so the browser may keep them.
_CACHE = "private, max-age=3600"


def _local_file(root: Path, key: str) -> bool:
    """Whether `key` names a file on the volume (inside `root`, never outside)."""
    base = root.resolve()
    try:
        path = (base / key).resolve()
        path.relative_to(base)
    except (ValueError, OSError):
        return False
    return path.is_file()


def _headers(content_type: str, size: int | None = None) -> dict[str, str]:
    headers = {
        "Cache-Control": _CACHE,
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
    }
    if content_type != "application/pdf":
        headers["Content-Disposition"] = "attachment"
    if size is not None:
        headers["Content-Length"] = str(size)
    return headers


class R2UploadFallback:
    """ASGI middleware over the whole backend app; only `GET`/`HEAD /_upload/<key>` that
    the volume cannot answer is served here."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        root: Callable[[], Path] | None = None,
        gate: Callable[[], Any] | None = None,
        resolver: Callable[[UUID, str], str | None] | None = None,
    ) -> None:
        self.app = app
        self._root = root
        self._gate = gate
        self._resolver = resolver

    def _media_root(self) -> Path:
        if self._root is not None:
            return self._root()
        from qualify_api.creative.composition import media_root  # noqa: PLC0415

        return media_root()

    def _object_gate(self) -> Any:
        if self._gate is not None:
            return self._gate()
        from .r2_media import _gate  # noqa: PLC0415 — the one cached production gate

        return _gate()

    def _resolve(self, tenant_id: UUID, key: str) -> str | None:
        if self._resolver is not None:
            return self._resolver(tenant_id, key)
        from qualify_api.creative.owner_uploads import resolve_moved_key  # noqa: PLC0415

        return resolve_moved_key(tenant_id, key)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in ("GET", "HEAD")
            or not str(scope.get("path", "")).startswith(UPLOAD_PREFIX)
        ):
            await self.app(scope, receive, send)
            return
        key = str(scope["path"])[len(UPLOAD_PREFIX) :]
        try:
            target = await asyncio.to_thread(self._target, key)
        except Exception as exc:  # the map unreadable: Reflex answers as it always did
            logger.warning("upload fallback: lookup failed: %s", type(exc).__name__)
            target = None
        if target is None:
            await self.app(scope, receive, send)
            return
        response = await self._serve(Request(scope, receive), *target)
        await response(scope, receive, send)

    def _target(self, key: str) -> tuple[UUID, str] | None:
        """`(tenant, R2 key)` to serve, or None to leave the request to Reflex."""
        from qualify_api.creative.owner_uploads import (  # noqa: PLC0415
            local_key_tenant,
            served_upload_tenant,
        )

        if not key or "\\" in key or _local_file(self._media_root(), key):
            return None
        tenant = served_upload_tenant(key)
        if tenant is not None:
            return tenant, key
        tenant = local_key_tenant(key)
        if tenant is None:
            return None
        moved = self._resolve(tenant, key)
        # only ever an upload or a copied old piece of THIS tenant — never another R2
        # object, whatever a map row says (defence in depth over the 0138 CHECK)
        if not moved or served_upload_tenant(moved) != tenant:
            return None
        return tenant, moved

    async def _serve(self, request: Request, tenant_id: UUID, key: str) -> Response:
        from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415
        from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

        from .r2_media import parse_range  # noqa: PLC0415

        gate = self._object_gate()
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        try:
            size = await asyncio.to_thread(gate.object_size, tenant_id, key)
        except (ObjectNotFound, TenantPrefixViolation):
            return Response(status_code=404)
        except Exception as exc:
            logger.warning("upload fallback: R2 unavailable: %s", type(exc).__name__)
            return Response(status_code=503)
        if request.method == "HEAD":
            return Response(
                status_code=200, media_type=content_type, headers=_headers(content_type, size)
            )
        header = request.headers.get("range", "")
        if header:
            try:
                wanted = parse_range(header, size)
            except ValueError:
                header = ""  # not understood: the whole object, as HTTP allows
            else:
                if wanted is None:
                    return Response(
                        status_code=416,
                        headers={**_headers(content_type), "Content-Range": f"bytes */{size}"},
                    )
                start, end = wanted
                body = await asyncio.to_thread(_read_range, gate, tenant_id, key, start, end)
                return Response(
                    content=body,
                    status_code=206,
                    media_type=content_type,
                    headers={
                        **_headers(content_type, end - start + 1),
                        "Content-Range": f"bytes {start}-{end}/{size}",
                    },
                )
        return StreamingResponse(
            _stream(gate, tenant_id, key, size),
            status_code=200,
            media_type=content_type,
            headers=_headers(content_type, size),
        )


def _read_range(gate: Any, tenant_id: UUID, key: str, start: int, end: int) -> bytes:
    stream = gate.open_range(tenant_id, key, start, end)
    try:
        return stream.read()
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()


async def _stream(gate: Any, tenant_id: UUID, key: str, size: int) -> AsyncIterator[bytes]:
    start = 0
    while start < size:
        end = min(start + _CHUNK, size) - 1
        yield await asyncio.to_thread(_read_range, gate, tenant_id, key, start, end)
        start = end + 1


def upload_fallback(app: ASGIApp) -> ASGIApp:
    """The `api_transformer` entry (`Qualify.py`)."""
    return R2UploadFallback(app)
