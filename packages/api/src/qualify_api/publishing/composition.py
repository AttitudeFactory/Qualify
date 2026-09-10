"""Production assembly for publishing (A5) — the analogue of `connections/composition.py`.

The R2 store is imported LAZILY inside the factory: `boto3` is not yet a declared
dependency (C3 owns that declaration and the venv ritual), so importing it at module
level would break every consumer of this package today. The tests never call this
factory — they inject fakes — which is exactly why the lazy import is safe.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import cache
from typing import IO
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.composition import degrade_connection_on_auth_error
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.publishing.client import MEDIA_TYPE_VIDEO, HttpPublishClient, PublishClient
from qualify_api.publishing.repository import PostgresPublishAttemptRepository
from qualify_api.publishing.service import (
    MAX_CAROUSEL_ITEMS,
    ConnectionTarget,
    MediaItem,
    PublishService,
    PublishState,
    TooManyItems,
)
from qualify_api.publishing.staging import MediaStagingService


class PostgresConnectionTargetReader:
    """Reads the two facts publishing needs from `social_connections`, RLS-scoped."""

    def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(SocialConnection).where(SocialConnection.id == connection_id)
            )
            if row is None:
                return None
            return ConnectionTarget(ig_user_id=row.external_account_id, status=row.status)


class ResolverPublishClientFactory:
    """Two authenticated clients per publish — one per host/scheme (R12) — resolved at
    publish time through the credential seam. Nothing here ever holds a token."""

    def __init__(self, settings: MetaOAuthSettings, encryptor: Encryptor) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> PublishClient:
        resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), self._encryptor)
        graph = await resolver.client_for(connection_id, scheme=self._settings.graph_auth_scheme)
        rupload = await resolver.client_for(
            connection_id, scheme=self._settings.rupload_auth_scheme
        )
        return HttpPublishClient(
            graph_client=graph, rupload_client=rupload, graph_url=self._settings.graph_url
        )


@cache
def production_publish_service() -> PublishService:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415 — see module docstring
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    settings = MetaOAuthSettings.from_env()
    return PublishService(
        repository=PostgresPublishAttemptRepository(),
        gate=ObjectGate(R2ObjectStore(R2Settings.from_env())),
        connections=PostgresConnectionTargetReader(),
        client_factory=ResolverPublishClientFactory(settings, DevEncryptor()),
        connection_degrader=degrade_connection_on_auth_error,
    )


@cache
def production_staging_service() -> MediaStagingService:
    """Same lazy-import reasoning as `production_publish_service()` — cached for the same
    reason `production_connect_service()`/`production_revoke_service()` are: this factory
    is called once per Reflex publish click, and rebuilding a boto3 client each time would
    open a fresh connection pool per attempt."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return MediaStagingService(ObjectGate(R2ObjectStore(R2Settings.from_env())))


async def stage_and_start_publish(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    fileobj: IO[bytes],
    content_type: str,
    media_product_type: str,
    idempotency_key: str,
    caption: str | None = None,
    thumb_offset: int | None = None,
) -> PublishState:
    """The published seam for Reflex — the publishing analogue of `start_connect`/
    `revoke_connection` above: a plain async function over ids, no HTTP hop.

    `media_id` is minted HERE (`uuid4().hex`), never accepted from the caller — the same
    server-owns-the-identifier invariant `publishing_routes.py:105` enforces over HTTP.

    Frontier: `MediaStagingService.stage_media` is BLOCKING I/O (synchronous boto3 against
    R2), so it is wrapped in `asyncio.to_thread` HERE, inside the seam — never in Reflex.
    `PublishService.start()` is already `async def` (it awaits an `httpx.AsyncClient`
    internally) and is awaited directly, so this function's caller never needs
    `asyncio.to_thread` at all — unlike `start_connect`/`revoke_connection`, whose
    services are synchronous.
    """
    staged = await asyncio.to_thread(
        production_staging_service().stage_media,
        tenant_id=tenant_id,
        connection_id=connection_id,
        media_id=uuid4().hex,
        fileobj=fileobj,
        content_type=content_type,
        media_product_type=media_product_type,
    )
    return await production_publish_service().start(
        tenant_id=tenant_id,
        connection_id=connection_id,
        media_object_key=staged.media_object_key,
        media_product_type=staged.media_product_type,
        idempotency_key=idempotency_key,
        caption=caption,
        thumb_offset=thumb_offset,
    )


@dataclass(frozen=True)
class PendingUpload:
    """One not-yet-staged file for a multi-video (carousel) publish request (QUA-99,
    5/6) — the composition-layer counterpart of `publishing.service.MediaItem`, BEFORE
    staging turns raw bytes into an R2 object key. VIDEO-ONLY, same posture `MediaItem`
    already takes: no media_type field — every item is staged and later created as
    `MEDIA_TYPE_VIDEO`, regardless of what the single-item path would use (`REELS`).
    """

    fileobj: IO[bytes]
    content_type: str


async def stage_and_start_many_publish(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    items: list[PendingUpload],
    idempotency_key: str,
    caption: str | None = None,
) -> PublishState:
    """The multi-video counterpart of `stage_and_start_publish` above (QUA-99, 5/6) —
    the seam Commit 6 calls once the gallery holds 2-10 items. `stage_and_start_publish`
    itself is UNCHANGED by this function's existence: this is a new, parallel path, not
    a rewrite of it.

    Each item is staged SEQUENTIALLY — mirrors `PublishService`'s own no-parallel-Meta-
    calls posture (QUA-99, 4/6) — always as `MEDIA_TYPE_VIDEO`: a carousel child never
    uses `REELS`, confirmed against Meta real (2026-09-10 smoke test). Staging happens
    HERE, in composition, exactly like the single-item path: `PublishService.start_many`
    never touches R2, same separation `stage_and_start_publish`/`start()` already keep.

    `PublishService.start_many` decides 1-vs-2-10 internally (delegating to `start()` for
    exactly one item, QUA-99 4/6) — this function does not special-case the count itself,
    it stages whatever `items` it is given and hands the result to the one seam.

    The `MAX_CAROUSEL_ITEMS` guard is CHECKED HERE TOO, before staging a single byte —
    `start_many` already refuses the same way, but only after this function would have
    staged every item to R2 first. Rejecting here as well means "before any platform
    call" also means before any costly I/O, not just before the Meta call specifically.
    """
    if len(items) > MAX_CAROUSEL_ITEMS:
        raise TooManyItems(len(items))

    staged_items: list[MediaItem] = []
    for pending in items:
        staged = await asyncio.to_thread(
            production_staging_service().stage_media,
            tenant_id=tenant_id,
            connection_id=connection_id,
            media_id=uuid4().hex,
            fileobj=pending.fileobj,
            content_type=pending.content_type,
            media_product_type=MEDIA_TYPE_VIDEO,
        )
        staged_items.append(
            MediaItem(media_object_key=staged.media_object_key, content_type=pending.content_type)
        )
    return await production_publish_service().start_many(
        tenant_id=tenant_id,
        connection_id=connection_id,
        items=staged_items,
        idempotency_key=idempotency_key,
        caption=caption,
    )


async def advance_publish(*, tenant_id: UUID, attempt_id: UUID) -> PublishState:
    """One `advance()` step — the seam's poll call. See `PublishService.advance` for why
    there is no loop here: the CLIENT (Reflex, for this seam) drives the cadence via
    repeated calls, exactly as the HTTP `GET /api/publishing/attempts/{id}` route does."""
    return await production_publish_service().advance(tenant_id=tenant_id, attempt_id=attempt_id)
