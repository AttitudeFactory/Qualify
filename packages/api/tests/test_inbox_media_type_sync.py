"""QUA-146 phase 2: `media_type` through the inbox — read on the calls that already
happen, completed once for active rows that lack it, never fetched for expired or
unmonitored media, kept verbatim when unknown, and budgeted like every other Meta call.
Also the monitorable surfaces (Reels + feed, never Stories/ads) and carousels read as the
album. Offline, against `MemoryInboxRepository` and fakes (same posture as
`test_inbox_service_lifecycle.py`, whose doubles are kept local here rather than imported).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGComment, IGCommentsPage

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.inbox.media_client import (
    MEDIA_FIELDS,
    HttpMediaClient,
    MediaReadError,
    MediaSummary,
    _parse_media_summary,
)
from qualify_api.inbox.monitoring import (
    METADATA_RETRY_AFTER,
    MONITORING_WINDOW,
    MediaMetadata,
    MetadataFetchError,
)
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import (
    META_CALL_BUDGET_PER_HOUR,
    MONITORABLE_MEDIA_PRODUCT_TYPES,
    CommentsAuthExpired,
    CommentsPermissionMissing,
    InboxService,
    MediaNotEligible,
    SyncBudgetExhausted,
)

TENANT = UUID("f1460000-0000-4000-8000-000000000001")
CONNECTION = UUID("f1460000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
GRANTED = frozenset(COMMENTS_EDGE_PERMISSIONS)
STORED_AT = NOW - timedelta(days=3)


class FakeComments:
    def __init__(self, comments_by_media: dict[str, list[IGComment]] | None = None) -> None:
        self._comments = comments_by_media or {}
        self.calls: list[str] = []

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        self.calls.append(ig_media_id)
        return IGCommentsPage(data=self._comments.get(ig_media_id, []))


class FakeMedia:
    def __init__(
        self,
        media: dict[str, MediaSummary] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._media = media or {}
        self._errors = errors or {}
        self.calls: list[str] = []

    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]:
        return tuple(m for m in self._media.values() if m.timestamp >= since)

    async def get_media(self, *, media_id: str) -> MediaSummary:
        self.calls.append(media_id)
        if media_id in self._errors:
            raise self._errors[media_id]
        if media_id not in self._media:
            raise MediaReadError("no such media")
        return self._media[media_id]


class Degrader:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> None:
        self.calls += 1


def _summary(
    media_id: str,
    *,
    posted_at: datetime = NOW - timedelta(days=2),
    product: str | None = "FEED",
    media_type: str | None = "IMAGE",
    caption: str = "from meta",
) -> MediaSummary:
    return MediaSummary(
        id=media_id,
        timestamp=posted_at,
        media_product_type=product,
        caption=caption,
        permalink=f"https://www.instagram.com/p/{media_id}/",
        media_type=media_type,
    )


def _service(
    repo: MemoryInboxRepository,
    *,
    comments: FakeComments | None = None,
    media: FakeMedia | None = None,
    degrader: Degrader | None = None,
) -> InboxService:
    return InboxService(
        repository=repo,
        comments_client=comments or FakeComments(),
        media_client=media or FakeMedia(),
        granted_scopes=GRANTED,
        connection_degrader=degrader,
    )


def _monitor_complete(
    repo: MemoryInboxRepository,
    media_id: str,
    *,
    posted_at: datetime = NOW - timedelta(days=2),
    media_type: str | None = None,
    monitored: bool = True,
) -> None:
    """A row whose QUA-149 metadata is complete — with `media_type=None`, exactly a row
    monitored before QUA-146 started asking Meta for it."""
    repo.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id=media_id,
        monitored=monitored,
        metadata=MediaMetadata(
            posted_at=posted_at,
            caption="stored caption",
            media_product_type="FEED",
            media_type=media_type,
        ),
        fetched_at=STORED_AT,
    )


def _row(repo: MemoryInboxRepository, media_id: str):
    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id=media_id
    )
    assert row is not None
    return row


def _ledger(repo: MemoryInboxRepository, at: datetime = NOW) -> int:
    return repo.calls_in_last_hour(tenant_id=TENANT, connection_id=CONNECTION, now=at)


async def _sync(service: InboxService, at: datetime = NOW):
    return await service.sync_comments(tenant_id=TENANT, connection_id=CONNECTION, now=at)


async def _activate(service: InboxService, media_id: str) -> None:
    await service.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id=media_id,
        monitored=True,
        now=NOW,
    )


# --- the client --------------------------------------------------------------------------


def test_the_field_list_asks_for_media_type_and_never_for_children() -> None:
    fields = MEDIA_FIELDS.split(",")
    assert "media_type" in fields
    assert "children" not in fields


@pytest.mark.parametrize("raw", ["IMAGE", "VIDEO", "CAROUSEL_ALBUM", "FUTURE_FORMAT"])
def test_the_parser_keeps_media_type_verbatim(raw: str) -> None:
    summary = _parse_media_summary(
        {"id": "m", "timestamp": "2026-10-08T10:00:00+0000", "media_type": raw}
    )
    assert summary.media_type == raw


def test_the_field_list_asks_for_media_url_for_photo_and_carousel_pictures() -> None:
    assert "media_url" in MEDIA_FIELDS.split(",")
    summary = _parse_media_summary(
        {"id": "m", "timestamp": "2026-10-08T10:00:00+0000", "media_url": "https://m/x.jpg"}
    )
    assert summary.media_url == "https://m/x.jpg"
    assert (
        _parse_media_summary({"id": "m", "timestamp": "2026-10-08T10:00:00+0000"}).media_url is None
    )


async def test_the_picker_carries_media_url_through() -> None:
    media = FakeMedia({"img": _summary("img", media_type="IMAGE")})
    media._media["img"] = MediaSummary(
        id="img",
        timestamp=NOW - timedelta(days=1),
        media_product_type="FEED",
        media_type="IMAGE",
        media_url="https://m/img.jpg",
    )

    (candidate,) = await _service(MemoryInboxRepository(), media=media).list_candidate_media(
        tenant_id=TENANT, connection_id=CONNECTION, ig_user_id="ig", now=NOW
    )

    assert candidate.media_url == "https://m/img.jpg"
    assert candidate.thumbnail_url is None


def test_the_parser_reads_a_missing_media_type_as_none() -> None:
    summary = _parse_media_summary({"id": "m", "timestamp": "2026-10-08T10:00:00+0000"})
    assert summary.media_type is None


async def test_get_media_requests_media_type_on_the_same_single_call() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["fields"])
        return httpx.Response(
            200,
            json={"id": "m", "timestamp": "2026-10-08T10:00:00+0000", "media_type": "IMAGE"},
        )

    settings = MetaOAuthSettings(
        app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
    )
    client = HttpMediaClient(
        graph_client=_InjectedAuthClient(
            "TOKEN", scheme=settings.graph_auth_scheme, transport=httpx.MockTransport(handler)
        ),
        graph_url="https://graph.facebook.com/v21.0",
    )

    summary = await client.get_media(media_id="m")

    assert len(seen) == 1 and "media_type" in seen[0].split(",")
    assert summary.media_type == "IMAGE"


# --- monitorable surfaces --------------------------------------------------------------


def test_reels_and_feed_are_the_only_monitorable_surfaces() -> None:
    assert MONITORABLE_MEDIA_PRODUCT_TYPES == frozenset({"REELS", "FEED"})


async def test_the_picker_offers_every_feed_format_and_reels_but_no_story_or_ad() -> None:
    media = FakeMedia(
        {
            "img": _summary("img", media_type="IMAGE"),
            "vid": _summary("vid", media_type="VIDEO"),
            "car": _summary("car", media_type="CAROUSEL_ALBUM"),
            "new": _summary("new", media_type="FUTURE_FORMAT"),
            "reel": _summary("reel", product="REELS", media_type="VIDEO"),
            "story": _summary("story", product="STORY", media_type="VIDEO"),
            "ad": _summary("ad", product="AD", media_type="IMAGE"),
            "none": _summary("none", product=None),
        }
    )

    candidates = await _service(MemoryInboxRepository(), media=media).list_candidate_media(
        tenant_id=TENANT, connection_id=CONNECTION, ig_user_id="ig", now=NOW
    )

    assert {c.external_media_id for c in candidates} == {"img", "vid", "car", "new", "reel"}


async def test_listing_candidates_never_turns_monitoring_on() -> None:
    """Opt-in stays per media: being offered is not being monitored."""
    repo = MemoryInboxRepository()
    media = FakeMedia({"img": _summary("img"), "car": _summary("car", media_type="CAROUSEL_ALBUM")})

    candidates = await _service(repo, media=media).list_candidate_media(
        tenant_id=TENANT, connection_id=CONNECTION, ig_user_id="ig", now=NOW
    )

    assert not any(c.is_monitored for c in candidates)
    assert repo.list_monitored_media_ids(tenant_id=TENANT, connection_id=CONNECTION) == frozenset()


@pytest.mark.parametrize(
    ("product", "media_type"),
    [("FEED", "IMAGE"), ("FEED", "VIDEO"), ("FEED", "CAROUSEL_ALBUM"), ("REELS", "VIDEO")],
)
async def test_activation_stores_the_media_type_from_its_single_read(
    product: str, media_type: str
) -> None:
    repo = MemoryInboxRepository()
    media = FakeMedia({"m": _summary("m", product=product, media_type=media_type)})

    await _activate(_service(repo, media=media), "m")

    row = _row(repo, "m")
    assert media.calls == ["m"]
    assert (row.media_product_type, row.media_type) == (product, media_type)
    assert row.caption == "from meta"


async def test_activation_keeps_an_unknown_format_verbatim_and_everything_else_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = MemoryInboxRepository()
    media = FakeMedia({"m": _summary("m", media_type="FUTURE_FORMAT")})

    with caplog.at_level(logging.WARNING, logger="qualify_api.inbox.service"):
        await _activate(_service(repo, media=media), "m")

    row = _row(repo, "m")
    assert row.media_type == "FUTURE_FORMAT"
    assert row.caption == "from meta"
    assert row.media_posted_at == NOW - timedelta(days=2)
    assert row.metadata_fetched_at == NOW
    assert "inbox.media_type.unrecognized" in caplog.text
    assert "from meta" not in caplog.text  # never the caption


@pytest.mark.parametrize("product", ["STORY", "AD", None])
async def test_activation_refuses_stories_ads_and_unreported_surfaces(product: str | None) -> None:
    repo = MemoryInboxRepository()
    media = FakeMedia({"m": _summary("m", product=product)})

    with pytest.raises(MediaNotEligible) as exc_info:
        await _activate(_service(repo, media=media), "m")

    assert exc_info.value.reason == "unsupported_surface"
    assert (
        repo.get_monitored_media(tenant_id=TENANT, connection_id=CONNECTION, external_media_id="m")
        is None
    )


async def test_an_old_feed_post_is_still_refused_as_too_old() -> None:
    media = FakeMedia({"m": _summary("m", posted_at=NOW - MONITORING_WINDOW - timedelta(days=1))})

    with pytest.raises(MediaNotEligible) as exc_info:
        await _activate(_service(MemoryInboxRepository(), media=media), "m")

    assert exc_info.value.reason == "too_old"


# --- carousels: comments on the album, never the children ------------------------------


async def test_a_carousel_s_comments_are_read_on_the_album_id_only() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "album", media_type="CAROUSEL_ALBUM")
    comments = FakeComments({"album": [IGComment.model_validate({"id": "c1", "text": "hola"})]})
    media = FakeMedia()

    summary = await _sync(_service(repo, comments=comments, media=media))

    assert comments.calls == ["album"]
    assert media.calls == []  # complete row: no metadata read
    assert summary.new_comments == 1


# --- legacy rows: media_type rides on the one QUA-149 read ------------------------------


async def test_a_legacy_row_gets_its_media_type_in_the_same_single_read() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="m", monitored=True
    )
    media = FakeMedia({"m": _summary("m", media_type="CAROUSEL_ALBUM")})

    summary = await _sync(_service(repo, media=media))

    assert media.calls == ["m"]
    assert _row(repo, "m").media_type == "CAROUSEL_ALBUM"
    assert summary.metadata_backfilled == 1
    assert _ledger(repo) == 2  # one metadata read + one comments page


# --- complete active rows without media_type: one dedicated, budgeted read --------------


async def test_a_complete_active_row_without_media_type_gets_one_dedicated_read() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    media = FakeMedia({"m": _summary("m", media_type="VIDEO", caption="edited on meta")})
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments, media=media))

    row = _row(repo, "m")
    assert media.calls == ["m"]
    assert row.media_type == "VIDEO"
    # Only media_type is written by the dedicated read.
    assert row.caption == "stored caption"
    assert row.metadata_fetched_at == STORED_AT
    assert row.media_posted_at == NOW - timedelta(days=2)
    assert row.metadata_error is None
    assert summary.metadata_backfilled == 1
    assert comments.calls == ["m"]
    assert _ledger(repo) == 2  # the dedicated read is in the ledger, before the comments


async def test_once_recovered_it_is_never_read_again() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    media = FakeMedia({"m": _summary("m", media_type="IMAGE")})
    service = _service(repo, media=media)

    await _sync(service)
    await _sync(service, at=NOW + timedelta(minutes=5))
    await _sync(service, at=NOW + timedelta(days=1))

    assert media.calls == ["m"]


async def test_one_dedicated_read_per_media_per_pass() -> None:
    repo = MemoryInboxRepository()
    for media_id in ("a", "b", "c"):
        _monitor_complete(repo, media_id)
    media = FakeMedia({m: _summary(m, media_type="IMAGE") for m in ("a", "b", "c")})

    await _sync(_service(repo, media=media))

    assert sorted(media.calls) == ["a", "b", "c"]


async def test_an_expired_row_without_media_type_is_never_read() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "old", posted_at=NOW - MONITORING_WINDOW - timedelta(seconds=1))
    media = FakeMedia({"old": _summary("old", media_type="IMAGE")})
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments, media=media))

    assert media.calls == [] and comments.calls == []
    assert _ledger(repo) == 0
    assert _row(repo, "old").media_type is None
    assert summary.expired_skipped == 1


async def test_a_row_with_monitoring_off_is_never_read() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "off", monitored=False)
    media = FakeMedia({"off": _summary("off", media_type="IMAGE")})

    await _sync(_service(repo, media=media))

    assert media.calls == []
    assert _ledger(repo) == 0


async def test_a_dedicated_read_keeps_an_unknown_format_verbatim(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    media = FakeMedia({"m": _summary("m", media_type="FUTURE_FORMAT")})

    with caplog.at_level(logging.WARNING, logger="qualify_api.inbox.service"):
        await _sync(_service(repo, media=media))

    assert _row(repo, "m").media_type == "FUTURE_FORMAT"
    assert "inbox.media_type.unrecognized" in caplog.text


async def test_a_response_without_media_type_is_spaced_out_never_looped() -> None:
    """Meta answered but left the field out: an UNKNOWN failure, so the next read waits
    `METADATA_RETRY_AFTER[UNKNOWN]` — and the comments are still synced meanwhile."""
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    media = FakeMedia({"m": _summary("m", media_type=None)})
    comments = FakeComments()
    service = _service(repo, comments=comments, media=media)

    first = await _sync(service)
    row = _row(repo, "m")
    assert row.media_type is None
    assert row.metadata_error is MetadataFetchError.UNKNOWN
    assert row.metadata_fetched_at == STORED_AT and row.caption == "stored caption"
    assert first.metadata_failed == 1
    assert comments.calls == ["m"]

    wait = METADATA_RETRY_AFTER[MetadataFetchError.UNKNOWN]
    await _sync(service, at=NOW + wait - timedelta(seconds=1))
    assert media.calls == ["m"]  # still waiting
    await _sync(service, at=NOW + wait)
    assert media.calls == ["m", "m"]  # its wait is over: one more, spaced read


async def test_a_full_read_without_media_type_never_erases_a_stored_one() -> None:
    """A legacy-style full write whose response lacks the field keeps the known value,
    while the caption and the other metadata ARE updated."""
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m", media_type="CAROUSEL_ALBUM")

    repo.record_media_metadata(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="m",
        metadata=MediaMetadata(posted_at=NOW - timedelta(days=2), caption="new caption"),
        fetched_at=NOW,
    )

    row = _row(repo, "m")
    assert row.media_type == "CAROUSEL_ALBUM"
    assert row.caption == "new caption"
    assert row.metadata_fetched_at == NOW


async def test_a_full_read_replaces_media_type_when_meta_sends_one() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m", media_type="FUTURE_FORMAT")

    repo.record_media_metadata(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="m",
        metadata=MediaMetadata(posted_at=NOW - timedelta(days=2), media_type="IMAGE"),
        fetched_at=NOW,
    )

    assert _row(repo, "m").media_type == "IMAGE"


# --- errors on the dedicated read: same handling as QUA-149 -----------------------------


async def test_a_confirmed_deletion_on_the_dedicated_read_turns_monitoring_off() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    deleted = MediaReadError("gone", http_status=400, platform_code=100, platform_subcode=33)
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments, media=FakeMedia(errors={"m": deleted})))

    row = _row(repo, "m")
    assert not row.is_monitored
    assert row.caption == "stored caption"
    assert summary.skipped_missing_media == ("m",)
    assert comments.calls == []


async def test_an_auth_failure_on_the_dedicated_read_degrades_the_connection() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    degrader = Degrader()
    expired = MediaReadError("auth", http_status=401, platform_code=190)

    with pytest.raises(CommentsAuthExpired):
        await _sync(_service(repo, media=FakeMedia(errors={"m": expired}), degrader=degrader))

    assert degrader.calls == 1
    row = _row(repo, "m")
    assert row.is_monitored and row.media_type is None and row.metadata_error is None


async def test_a_permission_failure_on_the_dedicated_read_is_labelled_and_kept_monitored() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    denied = MediaReadError("denied", http_status=400, platform_code=10)

    with pytest.raises(CommentsPermissionMissing):
        await _sync(_service(repo, media=FakeMedia(errors={"m": denied})))

    row = _row(repo, "m")
    assert row.is_monitored
    assert row.metadata_error is MetadataFetchError.PERMISSION
    assert row.media_type is None and row.caption == "stored caption"
    # A permanent refusal stops the entire account before any comments can be read.


# --- budget ---------------------------------------------------------------------------


async def test_the_dedicated_read_spends_the_last_unit_and_nothing_more() -> None:
    """199 of 200 calls already used: the floor (1) passes, the dedicated read takes the
    last unit, and the pass stops truncated before any comments call."""
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    for _ in range(META_CALL_BUDGET_PER_HOUR - 1):
        repo.record_call(tenant_id=TENANT, connection_id=CONNECTION, called_at=NOW)
    media = FakeMedia({"m": _summary("m", media_type="IMAGE")})
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments, media=media))

    assert media.calls == ["m"]
    assert comments.calls == []
    assert summary.truncated
    assert _ledger(repo) == META_CALL_BUDGET_PER_HOUR
    assert _row(repo, "m").media_type == "IMAGE"


async def test_an_exhausted_budget_makes_no_dedicated_read() -> None:
    repo = MemoryInboxRepository()
    _monitor_complete(repo, "m")
    for _ in range(META_CALL_BUDGET_PER_HOUR):
        repo.record_call(tenant_id=TENANT, connection_id=CONNECTION, called_at=NOW)
    media = FakeMedia({"m": _summary("m", media_type="IMAGE")})

    with pytest.raises(SyncBudgetExhausted):
        await _sync(_service(repo, media=media))

    assert media.calls == []
    assert _ledger(repo) == META_CALL_BUDGET_PER_HOUR


# --- a 200 whose body is not a JSON object --------------------------------------------


def _http_media(handler) -> HttpMediaClient:
    settings = MetaOAuthSettings(
        app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
    )
    return HttpMediaClient(
        graph_client=_InjectedAuthClient(
            "TOKEN", scheme=settings.graph_auth_scheme, transport=httpx.MockTransport(handler)
        ),
        graph_url="https://graph.facebook.com/v21.0",
    )


class _CountingHandler:
    """Answers every request with the same 200 body and counts the requests."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        return httpx.Response(200, content=self._body)


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b"", b"[1, 2]", b'"text"'])
async def test_a_200_that_is_not_a_json_object_is_a_media_read_error(body: bytes) -> None:
    with pytest.raises(MediaReadError) as exc_info:
        await _http_media(_CountingHandler(body)).get_media(media_id="m")

    # Status `None` is MediaReadError's documented spelling of "malformed 200".
    assert exc_info.value.http_status is None
    assert exc_info.value.platform_code is None
    assert "TOKEN" not in str(exc_info.value)


@pytest.mark.parametrize("legacy", [False, True], ids=["dedicated-read", "legacy-read"])
async def test_an_invalid_body_is_recorded_spaced_out_and_never_aborts_the_pass(
    legacy: bool,
) -> None:
    """The real HTTP client answering garbage: the pass goes on (comments still synced),
    the call stays in the ledger, the row is labelled UNKNOWN and is not read again
    before `METADATA_RETRY_AFTER[UNKNOWN]` — then exactly once more."""
    repo = MemoryInboxRepository()
    if legacy:
        repo.set_media_monitored(
            tenant_id=TENANT, connection_id=CONNECTION, external_media_id="m", monitored=True
        )
    else:
        _monitor_complete(repo, "m")
    _monitor_complete(repo, "other", media_type="IMAGE")
    handler = _CountingHandler(b"<html>gateway</html>")
    comments = FakeComments()
    service = InboxService(
        repository=repo,
        comments_client=comments,
        media_client=_http_media(handler),
        granted_scopes=GRANTED,
    )

    summary = await _sync(service)

    row = _row(repo, "m")
    assert handler.requests == 1
    assert summary.metadata_failed == 1 and not summary.truncated
    assert row.is_monitored
    assert row.metadata_error is MetadataFetchError.UNKNOWN
    assert row.metadata_attempted_at == NOW
    assert row.media_type is None
    assert sorted(comments.calls) == ["m", "other"]  # the pass went on, for every media
    assert _ledger(repo) == 3  # the failed read + one comments page per media

    wait = METADATA_RETRY_AFTER[MetadataFetchError.UNKNOWN]
    await _sync(service, at=NOW + wait - timedelta(seconds=1))
    assert handler.requests == 1
    await _sync(service, at=NOW + wait)
    assert handler.requests == 2
