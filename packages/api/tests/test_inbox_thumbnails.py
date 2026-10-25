"""A monitored publication's picture kept in R2 (m-24852202): stored once when the media's
details are saved, reused from what we published, bounded, and never able to fail the
activation or the sync around it."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import IO
from uuid import UUID

import httpx
import pytest
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.keys import TenantPrefixViolation
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGCommentsPage

from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import META_CALL_BUDGET_PER_HOUR, InboxService
from qualify_api.inbox.thumbnails import (
    HttpPictureFetcher,
    MemoryThumbnailStore,
    R2ThumbnailStore,
    ThumbnailSource,
    ThumbnailUnavailable,
    picture_url,
    reusable_published_image,
    thumbnail_key,
)

TENANT = UUID("f0000000-0000-4000-8000-0000000000a1")
CONNECTION = UUID("f0000000-0000-4000-8000-0000000000a2")
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _media(
    media_id: str = "1801",
    *,
    thumbnail_url: str | None = "https://cdn.example/t.jpg",
    media_url: str | None = None,
    media_type: str | None = "VIDEO",
    posted: datetime = NOW - timedelta(days=1),
) -> MediaSummary:
    return MediaSummary(
        id=media_id,
        timestamp=posted,
        media_product_type="REELS" if media_type == "VIDEO" else "FEED",
        caption="Hola",
        permalink="https://instagram.example/p/x",
        thumbnail_url=thumbnail_url,
        media_type=media_type,
        media_url=media_url,
    )


class FakeMedia:
    def __init__(self, media: dict[str, MediaSummary], *, fail: set[str] | None = None) -> None:
        self._media = media
        self._fail = fail or set()
        self.get_calls: list[str] = []

    async def list_recent_media(self, *, ig_user_id: str, since: datetime):
        return tuple(self._media.values())

    async def list_recent_stories(self, *, ig_user_id: str):
        return ()

    async def get_media(self, *, media_id: str) -> MediaSummary:
        self.get_calls.append(media_id)
        if media_id in self._fail:
            raise MediaReadError("boom", http_status=500)
        return self._media[media_id]


class NoComments:
    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        return IGCommentsPage.model_validate({"data": []})


def _service(repo, media, thumbnails) -> InboxService:
    return InboxService(
        repository=repo,
        comments_client=NoComments(),
        media_client=media,
        granted_scopes=frozenset(COMMENTS_EDGE_PERMISSIONS),
        thumbnails=thumbnails,
    )


async def _activate(service: InboxService, media_id: str = "1801") -> None:
    await service.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id=media_id,
        monitored=True,
        now=NOW,
    )


def _row(repo: MemoryInboxRepository, media_id: str = "1801"):
    return repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id=media_id
    )


# --- the service: once, on save, never failing the caller ----------------------------


async def test_activation_stores_the_picture_once_with_its_provenance() -> None:
    repo, store = MemoryInboxRepository(), MemoryThumbnailStore()
    service = _service(repo, FakeMedia({"1801": _media()}), store)

    await _activate(service)
    await _activate(service)  # turned on again: no second download

    row = _row(repo)
    assert row is not None
    assert row.thumbnail_key == f"t/{TENANT}/inbox/thumbs/{CONNECTION}/1801"
    assert row.thumbnail_source == ThumbnailSource.META_THUMBNAIL_URL
    assert store.calls == ["1801"]


async def test_a_failed_picture_never_fails_the_activation() -> None:
    repo = MemoryInboxRepository()
    service = _service(repo, FakeMedia({"1801": _media()}), MemoryThumbnailStore(fail=True))

    await _activate(service)

    row = _row(repo)
    assert row is not None and row.is_monitored and row.thumbnail_key is None


async def test_an_unexpected_store_error_is_swallowed_too() -> None:
    class Exploding:
        async def store(self, **_: object):
            raise RuntimeError("R2 not configured")

    repo = MemoryInboxRepository()
    await _activate(_service(repo, FakeMedia({"1801": _media()}), Exploding()))
    assert _row(repo).thumbnail_key is None  # type: ignore[union-attr]


async def test_without_a_store_nothing_is_kept() -> None:
    repo = MemoryInboxRepository()
    await _activate(_service(repo, FakeMedia({"1801": _media()}), None))
    assert _row(repo).thumbnail_key is None  # type: ignore[union-attr]


async def test_the_sync_metadata_read_of_a_legacy_row_keeps_its_picture() -> None:
    repo, store = MemoryInboxRepository(), MemoryThumbnailStore()
    # A legacy row: monitored with no metadata (before QUA-149), so the sync reads it once.
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="1801", monitored=True
    )
    service = _service(repo, FakeMedia({"1801": _media()}), store)

    await service.sync_comments(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    assert _row(repo).thumbnail_key is not None  # type: ignore[union-attr]
    assert store.calls == ["1801"]


async def test_backfill_reads_only_rows_without_a_picture_and_is_idempotent() -> None:
    repo, store = MemoryInboxRepository(), MemoryThumbnailStore()
    old = NOW - timedelta(days=60)  # long past the window: still gets its picture
    media = FakeMedia(
        {
            "1": _media("1", posted=old),
            "2": _media("2", posted=old, thumbnail_url=None, media_type="VIDEO"),
            "3": _media("3", posted=old),
        },
        fail={"3"},
    )
    for media_id in ("1", "2", "3"):
        repo.set_media_monitored(
            tenant_id=TENANT, connection_id=CONNECTION, external_media_id=media_id, monitored=True
        )
    service = _service(repo, media, store)

    first = await service.backfill_thumbnails(
        tenant_id=TENANT, connection_id=CONNECTION, limit=10, now=NOW
    )
    assert (first.stored, first.failed, first.skipped_budget) == (1, 2, 0)
    assert repo.calls_in_last_hour(tenant_id=TENANT, connection_id=CONNECTION, now=NOW) == 3

    media.get_calls.clear()
    await service.backfill_thumbnails(tenant_id=TENANT, connection_id=CONNECTION, limit=10, now=NOW)
    assert media.get_calls == ["2", "3"]  # "1" already has its picture: never read again


async def test_backfill_never_spends_past_the_hourly_budget() -> None:
    repo = MemoryInboxRepository()
    for _ in range(META_CALL_BUDGET_PER_HOUR - 1):
        repo.record_call(tenant_id=TENANT, connection_id=CONNECTION, called_at=NOW)
    for media_id in ("1", "2", "3"):
        repo.set_media_monitored(
            tenant_id=TENANT, connection_id=CONNECTION, external_media_id=media_id, monitored=True
        )
    media = FakeMedia({m: _media(m) for m in ("1", "2", "3")})
    result = await _service(repo, media, MemoryThumbnailStore()).backfill_thumbnails(
        tenant_id=TENANT, connection_id=CONNECTION, limit=10, now=NOW
    )
    assert (result.stored, result.skipped_budget) == (1, 2)
    assert media.get_calls == ["1"]


def test_record_media_thumbnail_never_replaces_a_stored_picture() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="1801", monitored=True
    )
    kwargs = {
        "tenant_id": TENANT,
        "connection_id": CONNECTION,
        "external_media_id": "1801",
        "content_type": "image/jpeg",
        "source": "meta_thumbnail_url",
        "stored_at": NOW,
    }
    assert repo.record_media_thumbnail(key="t/a", **kwargs) is True
    assert repo.record_media_thumbnail(key="t/b", **kwargs) is False
    assert _row(repo).thumbnail_key == "t/a"  # type: ignore[union-attr]


# --- which picture -------------------------------------------------------------------


def test_picture_url_prefers_the_video_frame_then_a_photo_picture() -> None:
    assert picture_url(_media()) == (
        "https://cdn.example/t.jpg",
        ThumbnailSource.META_THUMBNAIL_URL,
    )
    photo = _media(thumbnail_url=None, media_url="https://cdn.example/p.jpg", media_type="IMAGE")
    assert picture_url(photo) == ("https://cdn.example/p.jpg", ThumbnailSource.META_MEDIA_URL)
    album = _media(
        thumbnail_url=None, media_url="https://cdn.example/a.jpg", media_type="CAROUSEL_ALBUM"
    )
    assert picture_url(album) is not None
    # A video's media_url is the video file, never a picture.
    video = _media(thumbnail_url=None, media_url="https://cdn.example/v.mp4", media_type="VIDEO")
    assert picture_url(video) is None


def test_the_key_sits_under_the_tenant_prefix_and_refuses_odd_ids() -> None:
    assert thumbnail_key(TENANT, CONNECTION, "1801").startswith(f"t/{TENANT}/inbox/thumbs/")
    with pytest.raises(ThumbnailUnavailable):
        thumbnail_key(TENANT, CONNECTION, "../other")


def test_only_an_image_of_this_tenant_outside_purgeable_roots_is_reused() -> None:
    mine = f"t/{TENANT}/media/{CONNECTION}/abc"
    assert reusable_published_image(TENANT, mine, "image/jpeg") == (mine, "image/jpeg")
    assert reusable_published_image(TENANT, mine, "video/mp4") is None
    assert reusable_published_image(TENANT, f"t/{TENANT}/generated/d/x.jpg", "image/jpeg") is None
    assert reusable_published_image(TENANT, "t/someone-else/media/x", "image/jpeg") is None
    assert reusable_published_image(TENANT, None, None) is None


# --- the R2 store ----------------------------------------------------------------------


class MemoryObjects:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self.objects[key][0])


class FakeFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch(self, url: str) -> tuple[bytes, str]:
        self.urls.append(url)
        return b"\xff\xd8jpeg", "image/jpeg"


class FakePublished:
    def __init__(self, found: tuple[str, str] | None) -> None:
        self._found = found

    def image_for(self, **_: object) -> tuple[str, str] | None:
        return self._found


async def test_r2_store_downloads_once_into_the_tenant_prefix() -> None:
    objects, fetcher = MemoryObjects(), FakeFetcher()
    store = R2ThumbnailStore(
        gate_factory=lambda: ObjectGate(objects), fetcher=fetcher, published=FakePublished(None)
    )
    stored = await store.store(tenant_id=TENANT, connection_id=CONNECTION, media=_media())
    assert stored.key == thumbnail_key(TENANT, CONNECTION, "1801")
    assert objects.objects[stored.key] == (b"\xff\xd8jpeg", "image/jpeg")
    assert fetcher.urls == ["https://cdn.example/t.jpg"]


async def test_r2_store_reuses_our_published_image_without_downloading() -> None:
    objects, fetcher = MemoryObjects(), FakeFetcher()
    key = f"t/{TENANT}/media/{CONNECTION}/pub"
    store = R2ThumbnailStore(
        gate_factory=lambda: ObjectGate(objects),
        fetcher=fetcher,
        published=FakePublished((key, "image/png")),
    )
    stored = await store.store(tenant_id=TENANT, connection_id=CONNECTION, media=_media())
    assert (stored.key, stored.source) == (key, ThumbnailSource.PUBLISHED_ASSET)
    assert fetcher.urls == [] and objects.objects == {}


async def test_r2_store_refuses_a_published_key_of_another_tenant() -> None:
    store = R2ThumbnailStore(
        gate_factory=lambda: ObjectGate(MemoryObjects()),
        fetcher=FakeFetcher(),
        published=FakePublished(("t/other/media/x", "image/png")),
    )
    with pytest.raises(TenantPrefixViolation):
        await store.store(tenant_id=TENANT, connection_id=CONNECTION, media=_media())


async def test_r2_store_without_a_picture_url_raises_unavailable() -> None:
    store = R2ThumbnailStore(
        gate_factory=lambda: ObjectGate(MemoryObjects()),
        fetcher=FakeFetcher(),
        published=FakePublished(None),
    )
    with pytest.raises(ThumbnailUnavailable):
        await store.store(
            tenant_id=TENANT, connection_id=CONNECTION, media=_media(thumbnail_url=None)
        )


# --- the bounded download --------------------------------------------------------------


def _fetcher(handler, **kwargs) -> HttpPictureFetcher:
    return HttpPictureFetcher(transport=httpx.MockTransport(handler), **kwargs)


async def test_fetch_returns_an_image() -> None:
    fetcher = _fetcher(
        lambda r: httpx.Response(200, content=b"img", headers={"content-type": "image/jpeg"})
    )
    assert await fetcher.fetch("https://cdn.example/t.jpg") == (b"img", "image/jpeg")


@pytest.mark.parametrize(
    ("url", "response"),
    [
        (
            "http://cdn.example/t.jpg",
            httpx.Response(200, content=b"x", headers={"content-type": "image/jpeg"}),
        ),
        ("https://cdn.example/t.jpg", httpx.Response(403, content=b"no")),
        (
            "https://cdn.example/t.jpg",
            httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
        ),
        (
            "https://cdn.example/t.jpg",
            httpx.Response(200, content=b"x" * 2048, headers={"content-type": "image/jpeg"}),
        ),
        (
            "https://cdn.example/t.jpg",
            httpx.Response(200, content=b"", headers={"content-type": "image/jpeg"}),
        ),
    ],
)
async def test_fetch_refuses_anything_but_a_small_https_image(url: str, response) -> None:
    fetcher = _fetcher(lambda r: response, max_bytes=1024)
    with pytest.raises(ThumbnailUnavailable) as caught:
        await fetcher.fetch(url)
    assert "cdn.example" not in str(caught.value)  # a signed URL never reaches an error


async def test_fetch_turns_a_network_error_into_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(ThumbnailUnavailable):
        await _fetcher(boom).fetch("https://cdn.example/t.jpg")
