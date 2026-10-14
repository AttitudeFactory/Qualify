"""Inbound WhatsApp media, retrievable (migration 0061): the production `MediaLocator`.

`GET /api/whatsapp/media/{message_id}` (the chats API, `http/whatsapp_routes.py`) asks a
`chats.MediaLocator` for a URL to redirect to. This module's `CapturingMediaLocator` is
the real one. On a request:

1. Read the message's 0061 columns under `tenant_session` (`qualify_app`, RLS): another
   tenant's message reads as missing → `MediaMessageNotFound` (404, never 403).
2. No `media_id` (a text, a location, an outbound message, a pre-0061 row) →
   `MediaNotCaptured` (501 `media_not_captured`).
3. **First request only**: `client.media_url(media_id)` (Meta's 5-minute URL, bound to
   the connection's `phone_number_id`) → `client.download_media(url)` → `ObjectGate.
   put_media` under `inbound_media_key` → `UPDATE messages SET media_object_key`
   (guarded `IS NULL`, so two concurrent first requests converge on the same key — the
   key is deterministic, the second PUT rewrites identical bytes).
4. Every request: mint a public-media token for the R2 object
   (`publishing.composition.TokenPublicMediaLinker`, QUA-68's mechanism — 15-minute,
   hash-stored in Redis, served by `GET /public/media/{token}`) and return its URL. The
   route answers 307 to it. No new public surface: the token route already exists and
   already streams R2 objects by tenant-checked key.

Subsequent requests skip Meta entirely (step 3 is skipped when `media_object_key` is set).

## Failure mapping (the route turns these into status codes)

- `MediaExpired` → 410 `media_expired`: Meta answers 404 to `GET /{media_id}` or to the
  download, or 400 with code 100 (the object does not exist — an id past its ~30 days).
- `MediaUnavailable` → 502 `media_unavailable`: transport failure, 5xx, throttling, auth
  failure (401/190), any other Meta error, no client for the connection, R2 or Redis
  failure.

An auth failure is NOT turned into a connection degrade here: the outbox sender (WA-08)
and the connection health check own that transition, and a media view must not flip a
connection's state as a side effect of a GET.

## The R2 key

`t/{tenant_id}/fp/whatsapp/{connection_id}/media/{media_id}` — the first-party namespace
`qualify_scraper.shared.raw_payload_key` defines (`t/{tenant}/fp/{platform}/{connection}/
…`), so "delete everything of this tenant" stays one delete-by-prefix, and
`ObjectGate.put_media` re-checks the tenant prefix on write.

## Logging

Ids and status codes only — never a URL (Meta's lookaside URL is a bearer-protected
capability), never the token, never a caption.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import IO, Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import tenant_prefix
from sqlalchemy import text

from qualify_api.whatsapp.chats import (
    CHANNEL_WHATSAPP,
    MediaExpired,
    MediaMessageNotFound,
    MediaNotCaptured,
    MediaRecord,
    MediaUnavailable,
)
from qualify_api.whatsapp.client import WhatsAppApiError, WhatsAppClient
from qualify_api.whatsapp.outbox import ClientFactory

logger = logging.getLogger("qualify_api.whatsapp.media")

# Meta's media ids are numeric today; anything that could break out of a key segment
# (`/`, `..`) is refused rather than escaped.
_SAFE_MEDIA_ID = re.compile(r"[A-Za-z0-9_.\-]{1,200}")
# Graph error code for "object does not exist / unsupported get request" — what an id
# past its lifetime answers on `GET /{MEDIA_ID}` (support/error-codes; not yet seen live).
_GRAPH_OBJECT_MISSING_CODE = 100
_FALLBACK_CONTENT_TYPE = "application/octet-stream"


def inbound_media_key(tenant_id: UUID, connection_id: UUID, media_id: str) -> str:
    """The R2 key of an inbound media copy (module docstring, "The R2 key")."""
    if not _SAFE_MEDIA_ID.fullmatch(media_id) or ".." in media_id:
        raise ValueError("media_id is not a safe key segment")
    return f"{tenant_prefix(tenant_id)}fp/whatsapp/{connection_id}/media/{media_id}"


# ======================================================================================
# Seams
# ======================================================================================


class MediaRecordRepository(Protocol):
    """Tenant-scoped read of one message's media columns + the lazy fill.
    `chats.MemoryChatRepository` implements it for tests."""

    def get_media(self, *, tenant_id: UUID, message_id: UUID) -> MediaRecord | None: ...

    def set_media_object_key(
        self, *, tenant_id: UUID, message_id: UUID, object_key: str
    ) -> None: ...


class MediaSink(Protocol):
    """`qualify_shared.objects.ObjectGate`'s write half (tenant prefix re-checked)."""

    def put_media(
        self, tenant_id: UUID, object_key: str, fileobj: IO[bytes], content_type: str
    ) -> None: ...


class MediaLinker(Protocol):
    """`publishing.composition.TokenPublicMediaLinker`'s shape."""

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str: ...


# ======================================================================================
# Postgres
# ======================================================================================

_GET_MEDIA = text(
    """
    SELECT m.id, m.connection_id, m.direction, m.media_type, m.media_id, m.media_mime,
           m.media_object_key
      FROM messages m
      JOIN threads t ON t.id = m.thread_id
     WHERE m.id = :message_id AND t.channel = :channel AND m.deleted_at IS NULL
    """
)

_SET_OBJECT_KEY = text(
    """
    UPDATE messages SET media_object_key = :object_key
     WHERE id = :message_id AND media_object_key IS NULL
    """
)


class PostgresMediaRecordRepository:
    """`tenant_session(tenant_id)` per call (`qualify_app`: SELECT/UPDATE on `messages`
    since 0004 — a table-level grant, so 0061's columns are covered; RLS bounds both)."""

    def get_media(self, *, tenant_id: UUID, message_id: UUID) -> MediaRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                _GET_MEDIA, {"message_id": message_id, "channel": CHANNEL_WHATSAPP}
            ).one_or_none()
        if row is None:
            return None
        return MediaRecord(
            message_id=row.id,
            connection_id=row.connection_id,
            direction=row.direction,
            media_type=row.media_type,
            media_id=row.media_id,
            media_mime=row.media_mime,
            media_object_key=row.media_object_key,
        )

    def set_media_object_key(self, *, tenant_id: UUID, message_id: UUID, object_key: str) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(_SET_OBJECT_KEY, {"message_id": message_id, "object_key": object_key})


# ======================================================================================
# The locator
# ======================================================================================


def _is_expired(exc: WhatsAppApiError) -> bool:
    return exc.status == 404 or (exc.status == 400 and exc.code == _GRAPH_OBJECT_MISSING_CODE)


class CapturingMediaLocator:
    """The production `chats.MediaLocator` (module docstring)."""

    def __init__(
        self,
        records: MediaRecordRepository,
        sink: MediaSink,
        clients: ClientFactory,
        linker: MediaLinker,
    ) -> None:
        self._records = records
        self._sink = sink
        self._clients = clients
        self._linker = linker

    async def locate(self, *, tenant_id: UUID, message_id: UUID) -> str:
        record = await asyncio.to_thread(
            self._records.get_media, tenant_id=tenant_id, message_id=message_id
        )
        if record is None:
            raise MediaMessageNotFound(str(message_id))
        if record.direction != "inbound" or not record.media_id:
            raise MediaNotCaptured(str(message_id))
        content_type = record.media_mime or _FALLBACK_CONTENT_TYPE
        object_key = record.media_object_key
        if object_key is None:
            object_key, content_type = await self._capture(tenant_id, record)
        try:
            return await asyncio.to_thread(
                self._linker.link,
                tenant_id=tenant_id,
                object_key=object_key,
                content_type=content_type,
            )
        except Exception as exc:  # Redis/settings — the bytes are safe in R2
            logger.warning(
                "whatsapp.media.link_failed tenant_id=%s message_id=%s error=%s",
                tenant_id,
                message_id,
                type(exc).__name__,
            )
            raise MediaUnavailable(str(message_id)) from exc

    async def _capture(self, tenant_id: UUID, record: MediaRecord) -> tuple[str, str]:
        assert record.media_id is not None
        try:
            object_key = inbound_media_key(tenant_id, record.connection_id, record.media_id)
        except ValueError as exc:
            raise MediaNotCaptured(str(record.message_id)) from exc
        try:
            client = await self._clients(tenant_id=tenant_id, connection_id=record.connection_id)
        except Exception as exc:  # no phone row / no credential visible: cannot reach Meta
            logger.warning(
                "whatsapp.media.client_failed tenant_id=%s message_id=%s error=%s",
                tenant_id,
                record.message_id,
                type(exc).__name__,
            )
            raise MediaUnavailable(str(record.message_id)) from exc
        try:
            content, meta_mime = await self._download(client, record)
        finally:
            await _close(client)
        content_type = record.media_mime or meta_mime or _FALLBACK_CONTENT_TYPE
        try:
            await asyncio.to_thread(
                self._sink.put_media, tenant_id, object_key, io.BytesIO(content), content_type
            )
            await asyncio.to_thread(
                self._records.set_media_object_key,
                tenant_id=tenant_id,
                message_id=record.message_id,
                object_key=object_key,
            )
        except Exception as exc:
            logger.warning(
                "whatsapp.media.store_failed tenant_id=%s message_id=%s error=%s",
                tenant_id,
                record.message_id,
                type(exc).__name__,
            )
            raise MediaUnavailable(str(record.message_id)) from exc
        logger.info(
            "whatsapp.media.captured tenant_id=%s message_id=%s media_type=%s bytes=%d",
            tenant_id,
            record.message_id,
            record.media_type,
            len(content),
        )
        return object_key, content_type

    async def _download(
        self, client: WhatsAppClient, record: MediaRecord
    ) -> tuple[bytes, str | None]:
        assert record.media_id is not None
        step = "media_url"
        try:
            info = await client.media_url(record.media_id)
            step = "download_media"
            content = await client.download_media(info.url)
        except WhatsAppApiError as exc:
            logger.warning(
                "whatsapp.media.meta_failed message_id=%s step=%s status=%s code=%s transport=%s",
                record.message_id,
                step,
                exc.status,
                exc.code,
                exc.is_transport,
            )
            if _is_expired(exc):
                raise MediaExpired(str(record.message_id)) from exc
            raise MediaUnavailable(str(record.message_id)) from exc
        return content, info.mime_type


async def _close(client: Any) -> None:
    """Close the client's HTTP pool when it exposes one (the resolver-built client does,
    through its graph client); test fakes need not."""
    for target in (client, getattr(client, "_graph", None)):
        aclose = getattr(target, "aclose", None)
        if callable(aclose):
            await aclose()
            return


# ======================================================================================
# Production wiring
# ======================================================================================


def production_media_locator() -> CapturingMediaLocator:
    """R2 (`R2Settings`), Redis (`production_media_token_store`), the public base URL
    (`PublicMediaSettings`) and the Meta settings — all read here, lazily, so an app
    booted without them fails the first media request loudly, not the boot."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.config import MetaOAuthSettings, PublicMediaSettings  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
    from qualify_api.publishing.composition import (  # noqa: PLC0415
        TokenPublicMediaLinker,
        production_media_token_store,
    )
    from qualify_api.whatsapp.outbox import ResolverClientFactory  # noqa: PLC0415

    return CapturingMediaLocator(
        PostgresMediaRecordRepository(),
        ObjectGate(R2ObjectStore(R2Settings.from_env())),
        ResolverClientFactory(MetaOAuthSettings.from_env(), DevEncryptor()),
        TokenPublicMediaLinker(production_media_token_store(), PublicMediaSettings.from_env()),
    )


__all__ = [
    "CapturingMediaLocator",
    "MediaLinker",
    "MediaRecordRepository",
    "MediaSink",
    "PostgresMediaRecordRepository",
    "inbound_media_key",
    "production_media_locator",
]
