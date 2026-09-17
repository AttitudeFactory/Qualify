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

from qualify_api.config import MetaOAuthSettings, PublicMediaSettings, redis_url
from qualify_api.connections.composition import degrade_connection_on_auth_error
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.publishing.client import HttpPublishClient, PublishClient
from qualify_api.publishing.media_token import MediaTokenStore
from qualify_api.publishing.repository import PostgresPublishAttemptRepository
from qualify_api.publishing.service import (
    MAX_CAROUSEL_ITEMS,
    ChildStatus,
    ConnectionTarget,
    MediaItem,
    PublishService,
    PublishState,
    TooManyItems,
)
from qualify_api.publishing.staging import MediaStagingService


class TokenPublicMediaLinker:
    """QUA-68's real `PublicMediaLinker` — mints a token via `MediaTokenStore` and turns it
    into the full URL Meta's fetcher will `GET`. The one place `/public/media/{token}` and
    `PublicMediaSettings.public_media_url` are composed together, so `PublishService` itself
    never needs to know either exists."""

    def __init__(self, store: MediaTokenStore, settings: PublicMediaSettings) -> None:
        self._store = store
        self._settings = settings

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        token = self._store.issue(
            tenant_id=tenant_id, object_key=object_key, content_type=content_type
        )
        return self._settings.public_media_url(token)


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
def production_media_token_store() -> MediaTokenStore:
    """QUA-68 — lazy `redis` import for the same reason `production_connect_service`
    (`connections/composition.py`) already gives: importing this module must not require a
    Redis to exist, only calling it. Cached for the same reason too: one connection pool,
    not one per publish attempt."""
    import redis  # noqa: PLC0415

    return MediaTokenStore(redis.Redis.from_url(redis_url(), decode_responses=True))


@cache
def production_public_media_linker() -> TokenPublicMediaLinker:
    """`PublicMediaSettings.from_env()` runs INSIDE this cached factory. Never called
    eagerly by `production_publish_service()` below — see `_LazyPublicMediaLinker`, the
    thing that IS passed there — so a deployment without `QUALIFY_PUBLIC_MEDIA_BASE_URL`
    set keeps publishing VIDEO exactly as before, and only fails an actual IMAGE publish."""
    return TokenPublicMediaLinker(production_media_token_store(), PublicMediaSettings.from_env())


class _LazyPublicMediaLinker:
    """Defers `production_public_media_linker()` — and therefore
    `PublicMediaSettings.from_env()` and the Redis connection — until `.link()` is actually
    called. `production_publish_service()` is ONE cached singleton shared by every publish,
    video included; resolving the public-media settings inside ITS construction would make
    a missing `QUALIFY_PUBLIC_MEDIA_BASE_URL` break video publishing too, in any environment
    that has not set it. This keeps that failure exactly where it belongs: the first real
    IMAGE publish attempt, never the video path, never app boot.
    """

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        return production_public_media_linker().link(
            tenant_id=tenant_id, object_key=object_key, content_type=content_type
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
        media_linker=_LazyPublicMediaLinker(),
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
        # QUA-68: only meaningful for IMAGE (`PublishService._start_image` uses it to mint
        # the public link's Content-Type); the VIDEO path ignores it, unchanged.
        content_type=staged.content_type,
    )


@dataclass(frozen=True)
class PendingUpload:
    """One not-yet-staged file for a multi-item (carousel) publish request (QUA-99,
    5/6) — the composition-layer counterpart of `publishing.service.MediaItem`, BEFORE
    staging turns raw bytes into an R2 object key.

    `media_type` (QUA-103) is **required, with no default** — same posture `MediaItem`
    takes, and for the same reason: propagated verbatim from `publishing_state.py`,
    never guessed here. `stage_and_start_many_publish` below still only ever exercises
    this with `"VIDEO"` items in this PR (`PublishState.publish` refuses a multi-item
    batch containing an IMAGE — see `publishing_state.py`'s own guard — so the carousel
    orchestration itself does not need to branch on this value yet).
    """

    fileobj: IO[bytes]
    content_type: str
    media_type: str


async def _stage_one(*, tenant_id: UUID, connection_id: UUID, pending: PendingUpload) -> MediaItem:
    """One item's R2 upload, in its own coroutine so `stage_and_start_many_publish`
    below can run N of these concurrently via `asyncio.gather`.

    `media_product_type` passed to `stage_media` is `pending.media_type` verbatim, not a
    hardcoded `MEDIA_TYPE_VIDEO` — QUA-103 requires no implicit IMAGE→VIDEO coercion
    anywhere in this chain. In practice this is always `"VIDEO"` today (the caller-side
    guard above keeps IMAGE out of a multi-item batch), but the plumbing itself makes no
    assumption about that — a stale caller check would fail loudly against Meta's own
    resumable-upload validation, not silently upload image bytes as a video container.
    """
    staged = await asyncio.to_thread(
        production_staging_service().stage_media,
        tenant_id=tenant_id,
        connection_id=connection_id,
        media_id=uuid4().hex,
        fileobj=pending.fileobj,
        content_type=pending.content_type,
        media_product_type=pending.media_type,
    )
    return MediaItem(
        media_object_key=staged.media_object_key,
        content_type=pending.content_type,
        media_type=pending.media_type,
    )


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

    QUA-99 latency follow-up (2026-09-10): every item now stages to R2 CONCURRENTLY
    (`asyncio.gather`) — this was a real, reported bottleneck ("sube exageradamente
    despacio con más de un video"), and a DIFFERENT one from the Meta-side concurrency
    this same follow-up already added to `PublishService._advance_children`: that fixed
    N children moving through Meta's own container pipeline; this fixes N raw uploads to
    R2 that happen BEFORE any of that even starts — entirely invisible to the earlier
    fix. Safe for the same class of reasons: `production_staging_service()` wraps ONE
    shared boto3 S3 client, and boto3 clients are documented thread-safe for concurrent
    use across threads (`asyncio.to_thread` runs each `stage_media` call in its own
    thread from the default executor) — each `put_object` call is independent, using its
    own connection from the client's own pool, touching no shared mutable state between
    items. Order is preserved by construction: `asyncio.gather` returns results in the
    SAME order its awaitables were given (`items`' order), never re-sorted afterward —
    that order becomes carousel `position` downstream (`PublishService.start_many`).

    Plain `gather` (not `return_exceptions=True`, unlike the Meta-side concurrency):
    nothing has been written to any database row yet at this point — `start_many`'s
    write-ahead only happens AFTER every item has staged successfully — so there is no
    partial state to reconcile if one upload fails; the first exception propagating and
    cancelling any still-running siblings is exactly right here (`stage_and_start_
    publish`'s single-item path already has this same "no attempt exists yet" posture).
    `MediaStagingService.stage_media` is always VIDEO — a carousel child never uses
    `REELS`, confirmed against Meta real (2026-09-10 smoke test). Staging happens HERE,
    in composition, exactly like the single-item path: `PublishService.start_many` never
    touches R2, same separation `stage_and_start_publish`/`start()` already keep.

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

    staged_items: list[MediaItem] = list(
        await asyncio.gather(
            *(
                _stage_one(tenant_id=tenant_id, connection_id=connection_id, pending=pending)
                for pending in items
            )
        )
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


def get_child_statuses(*, tenant_id: UUID, attempt_id: UUID) -> list[ChildStatus]:
    """Read-only carousel-progress seam (QUA-99 UX follow-up) — the composition-layer
    counterpart of `advance_publish`, but for DISPLAY only: it never advances anything,
    only projects what `PublishService.list_children_status` already reads from Postgres.
    Synchronous, same convention as `PostgresConnectionTargetReader.read`/
    `connections_for` — callers on the event loop run it off-thread via
    `asyncio.to_thread`, same as `active_connections` already does in
    `publishing_provider.py`."""
    return production_publish_service().list_children_status(
        tenant_id=tenant_id, attempt_id=attempt_id
    )
