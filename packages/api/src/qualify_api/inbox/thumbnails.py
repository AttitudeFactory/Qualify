"""A monitored publication's picture, kept in R2 (m-24852202).

Meta's `thumbnail_url`/`media_url` are signed CDN links that expire, and the live media
list only covers the last 14 days, so a publication older than that used to lose its
picture in Interacciones. This module copies the picture ONCE, when the media's details
are saved (`InboxService.set_media_monitored`, the sync's one metadata read, or the
optional backfill command), into the tenant's own R2 prefix:

    t/{tenant_id}/inbox/thumbs/{connection_id}/{external_media_id}

through the sanctioned door (`qualify_shared.objects.ObjectGate`, which re-checks the
prefix on every read and write). The key is deterministic, so storing twice overwrites the
same object instead of piling up copies; the service also skips a row that already has a
key, so the second time does not even download.

Which picture, in order:

1. **The image Qualify published itself** (`publish_attempts.published_media_id` →
   `scheduled_posts.media_object_key`): already in R2 under this tenant, reused as is, no
   download (`published_asset`). Only when it is an image (a video file is not a picture
   an `<img>` can show) and not under a purgeable root (`PURGEABLE_ROOTS`: the retention
   job may empty it one day).
2. **Meta's `thumbnail_url`** — the frame of a video or Reel (`meta_thumbnail_url`).
3. **Meta's `media_url`** — only for an `IMAGE` or a `CAROUSEL_ALBUM` (for a `VIDEO` it is
   the video file) (`meta_media_url`).

Bounded: one picture per media, at most `MAX_THUMBNAIL_BYTES`, `FETCH_TIMEOUT_SECONDS`,
`https` only, an `image/*` answer only. Failure-tolerant: every failure is raised as
`ThumbnailUnavailable` (or, for anything unexpected, caught by the service) and the row
simply keeps no key — the screen shows its usual icon. Provenance: the row's own
`external_media_id` is the source media id; `thumbnail_source` says which of the three.
"""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

import httpx
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import PURGEABLE_ROOTS, ObjectGate
from qualify_shared.objects.keys import require_tenant_prefix, tenant_prefix
from sqlalchemy import select

from qualify_api.inbox.media_client import MediaSummary
from qualify_api.inbox.media_type import MediaType, known_media_type

#: A thumbnail is small; anything bigger than this is not what we asked for.
MAX_THUMBNAIL_BYTES: Final = 8 * 1024 * 1024
FETCH_TIMEOUT_SECONDS: Final = 10.0

# The formats whose Meta `media_url` IS a picture (same rule as the picker's
# `inbox_vm.candidate_picture_url`).
_PICTURE_MEDIA_TYPES: Final = frozenset({MediaType.IMAGE, MediaType.CAROUSEL_ALBUM})
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ThumbnailSource(StrEnum):
    """Where a stored picture came from — `monitored_media.thumbnail_source` (0089)."""

    META_THUMBNAIL_URL = "meta_thumbnail_url"
    META_MEDIA_URL = "meta_media_url"
    PUBLISHED_ASSET = "published_asset"


@dataclass(frozen=True)
class StoredThumbnail:
    key: str
    content_type: str
    source: ThumbnailSource


class ThumbnailUnavailable(Exception):
    """No picture could be stored for this media (no usable URL, a failed or oversized
    download, a non-image answer). Never carries the URL: it is a signed Meta link."""


def thumbnail_key(tenant_id: UUID, connection_id: UUID, external_media_id: str) -> str:
    """The deterministic R2 key of a media's picture, under the tenant prefix. Meta's ids
    are digits; anything else is refused rather than escaped into a path."""
    if not _SAFE_ID.match(external_media_id):
        raise ThumbnailUnavailable("media id is not a plain identifier")
    return f"{tenant_prefix(tenant_id)}inbox/thumbs/{connection_id}/{external_media_id}"


def picture_url(media: MediaSummary) -> tuple[str, ThumbnailSource] | None:
    """Meta's picture for this media and which field it came from, or `None`."""
    if media.thumbnail_url:
        return media.thumbnail_url, ThumbnailSource.META_THUMBNAIL_URL
    if media.media_url and known_media_type(media.media_type) in _PICTURE_MEDIA_TYPES:
        return media.media_url, ThumbnailSource.META_MEDIA_URL
    return None


class PictureFetcher(Protocol):
    async def fetch(self, url: str) -> tuple[bytes, str]:
        """The bytes and content type at `url`; raises `ThumbnailUnavailable`."""
        ...


class HttpPictureFetcher:
    """Downloads one picture from Meta's CDN — bounded in time and size, `https` only,
    and only an `image/*` answer is accepted. The URL never reaches a log or an error."""

    def __init__(
        self,
        *,
        timeout: float = FETCH_TIMEOUT_SECONDS,
        max_bytes: int = MAX_THUMBNAIL_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._transport = transport

    async def fetch(self, url: str) -> tuple[bytes, str]:
        if not url.startswith("https://"):
            raise ThumbnailUnavailable("picture URL is not https")
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=True, transport=self._transport
                ) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code != 200:
                    raise ThumbnailUnavailable(f"picture answered HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if not content_type.startswith("image/"):
                    raise ThumbnailUnavailable("picture answer is not an image")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise ThumbnailUnavailable("picture is larger than the cap")
        except httpx.HTTPError as exc:
            raise ThumbnailUnavailable(f"picture download failed: {type(exc).__name__}") from exc
        if not body:
            raise ThumbnailUnavailable("picture answer is empty")
        return bytes(body), content_type


class PublishedAssetLookup(Protocol):
    def image_for(
        self, *, tenant_id: UUID, connection_id: UUID, external_media_id: str
    ) -> tuple[str, str] | None:
        """`(object_key, content_type)` of the image Qualify published as this media, or
        `None` (not ours, a video, or under a purgeable root)."""
        ...


class PostgresPublishedAssetLookup:
    """`publish_attempts.published_media_id` → its `scheduled_posts` media, through
    `tenant_session` (RLS)."""

    def image_for(
        self, *, tenant_id: UUID, connection_id: UUID, external_media_id: str
    ) -> tuple[str, str] | None:
        from qualify_api.publishing.models import PublishAttempt, ScheduledPost  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(ScheduledPost.media_object_key, ScheduledPost.media_content_type)
                .join(PublishAttempt, PublishAttempt.scheduled_post_id == ScheduledPost.id)
                .where(
                    PublishAttempt.connection_id == connection_id,
                    PublishAttempt.published_media_id == external_media_id,
                )
                .limit(1)
            ).first()
        if row is None:
            return None
        return reusable_published_image(tenant_id, row[0], row[1])


def reusable_published_image(
    tenant_id: UUID, key: str | None, content_type: str | None
) -> tuple[str, str] | None:
    """The published asset as a thumbnail, when it is safe to point at it: an image, under
    this tenant's prefix, and outside every root the retention job may empty."""
    if not key or not content_type or not content_type.startswith("image/"):
        return None
    if not key.startswith(tenant_prefix(tenant_id)):
        return None
    rest = key[len(tenant_prefix(tenant_id)) :]
    if any(rest.startswith(root) for root in PURGEABLE_ROOTS):
        return None
    return key, content_type


class ThumbnailStore(Protocol):
    async def store(
        self, *, tenant_id: UUID, connection_id: UUID, media: MediaSummary
    ) -> StoredThumbnail:
        """Store (or point at) this media's picture; raises `ThumbnailUnavailable`."""
        ...


class R2ThumbnailStore:
    """The production store: published asset first, else one download into R2."""

    def __init__(
        self,
        *,
        gate_factory: Callable[[], ObjectGate],
        fetcher: PictureFetcher | None = None,
        published: PublishedAssetLookup | None = None,
    ) -> None:
        self._gate_factory = gate_factory
        self._fetcher = fetcher or HttpPictureFetcher()
        self._published = published or PostgresPublishedAssetLookup()

    async def store(
        self, *, tenant_id: UUID, connection_id: UUID, media: MediaSummary
    ) -> StoredThumbnail:
        reused = await asyncio.to_thread(
            self._published.image_for,
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_media_id=media.id,
        )
        if reused is not None:
            key, content_type = reused
            return StoredThumbnail(
                key=require_tenant_prefix(tenant_id, key),
                content_type=content_type,
                source=ThumbnailSource.PUBLISHED_ASSET,
            )
        found = picture_url(media)
        if found is None:
            raise ThumbnailUnavailable("media has no picture URL")
        url, source = found
        key = thumbnail_key(tenant_id, connection_id, media.id)
        body, content_type = await self._fetcher.fetch(url)
        gate = self._gate_factory()
        await asyncio.to_thread(gate.put_media, tenant_id, key, io.BytesIO(body), content_type)
        return StoredThumbnail(key=key, content_type=content_type, source=source)


@dataclass
class MemoryThumbnailStore:
    """Offline twin: answers a deterministic key per media without any network or R2.
    `fail` makes every call raise `ThumbnailUnavailable`; `calls` records media ids."""

    fail: bool = False
    calls: list[str] = field(default_factory=list)

    async def store(
        self, *, tenant_id: UUID, connection_id: UUID, media: MediaSummary
    ) -> StoredThumbnail:
        self.calls.append(media.id)
        if self.fail:
            raise ThumbnailUnavailable("memory store set to fail")
        found = picture_url(media)
        if found is None:
            raise ThumbnailUnavailable("media has no picture URL")
        return StoredThumbnail(
            key=thumbnail_key(tenant_id, connection_id, media.id),
            content_type="image/jpeg",
            source=found[1],
        )
