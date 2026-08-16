"""`InboxService`, fully offline against fakes — no network, no database. Mirrors the
posture of `test_publishing_service.py`-style tests elsewhere: the fakes are the only
implementation of `CommentsClient`/`MediaClient`/`InboxRepository` these tests touch, and
`MemoryInboxRepository` is the real production fake (same reasoning
`MemoryPublishAttemptRepository` gets used from production code, not reinvented per test).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import IGComment, IGCommentsPage

from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import (
    MONITORING_WINDOW,
    InboxService,
    MediaNotEligible,
    SyncSummary,
)

TENANT_ID = UUID("f0000000-0000-4000-8000-000000000001")
CONNECTION_ID = UUID("f0000000-0000-4000-8000-000000000002")
IG_USER_ID = "17841400000000000"
NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


class FakeCommentsClient:
    """Returns one fixed page per media id, and records which ids were actually queried —
    the assertion surface for "only monitored media gets synced"."""

    def __init__(self, comments_by_media: dict[str, list[IGComment]]) -> None:
        self._comments_by_media = comments_by_media
        self.calls: list[str] = []

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        self.calls.append(ig_media_id)
        return IGCommentsPage(data=self._comments_by_media.get(ig_media_id, []))


class FakeMediaClient:
    def __init__(self, media_by_id: dict[str, MediaSummary]) -> None:
        self._media_by_id = media_by_id
        self.get_media_calls: list[str] = []

    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]:
        return tuple(m for m in self._media_by_id.values() if m.timestamp >= since)

    async def get_media(self, *, media_id: str) -> MediaSummary:
        self.get_media_calls.append(media_id)
        media = self._media_by_id.get(media_id)
        if media is None:
            raise MediaReadError(f"no such media {media_id!r}")
        return media


def _comment(comment_id: str) -> IGComment:
    return IGComment.model_validate({"id": comment_id, "text": "hi"})


# --------------------------------------------------------------------------------------
# sync_comments — only monitored media, idempotent across runs
# --------------------------------------------------------------------------------------


async def test_sync_comments_only_processes_monitored_media() -> None:
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="B", monitored=False
    )
    comments_client = FakeCommentsClient({"A": [_comment("c1")], "B": [_comment("c2")]})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert comments_client.calls == ["A"]
    assert summary.media_checked == 1
    assert summary.new_comments == 1


async def test_sync_comments_is_idempotent_across_two_runs() -> None:
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    comments_client = FakeCommentsClient({"A": [_comment("c1"), _comment("c2")]})
    service = InboxService(
        repository=repository, comments_client=comments_client, media_client=FakeMediaClient({})
    )

    first = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    second = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert first.new_comments == 2
    assert second.new_comments == 0


async def test_sync_comments_with_no_monitored_media_touches_nothing() -> None:
    repository = MemoryInboxRepository()
    comments_client = FakeCommentsClient({})
    service = InboxService(
        repository=repository, comments_client=comments_client, media_client=FakeMediaClient({})
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary == SyncSummary(media_checked=0, new_comments=0)
    assert comments_client.calls == []


class PaginatedFakeCommentsClient:
    """Unlike `FakeCommentsClient` (always one fixed page, `after` ignored), this walks a
    real `after`-cursor chain — the B2 acceptance criterion's "a new comment mid-pagination
    shifts the window" scenario, `ig_shapes.INCREMENTAL_POLLING_NOTE`. Records every
    `after` value it was called with, so a test can assert the service actually followed
    the cursor rather than only reading page one."""

    def __init__(self, pages_by_media: dict[str, dict[str | None, IGCommentsPage]]) -> None:
        self._pages_by_media = pages_by_media
        self.after_values_seen: list[str | None] = []

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        self.after_values_seen.append(after)
        return self._pages_by_media[ig_media_id][after]


async def test_sync_comments_walks_multiple_pages_via_the_after_cursor() -> None:
    """Two pages, a real cursor between them: both pages' comments must land, and the
    service must have actually asked for page two with the cursor page one returned —
    not just read page one and stopped."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    page_one = IGCommentsPage(
        data=[_comment("c1"), _comment("c2")], paging={"cursors": {"after": "CURSOR_1"}}
    )
    page_two = IGCommentsPage(data=[_comment("c3")], paging=None)  # terminal: no cursor
    comments_client = PaginatedFakeCommentsClient({"A": {None: page_one, "CURSOR_1": page_two}})
    service = InboxService(
        repository=repository, comments_client=comments_client, media_client=FakeMediaClient({})
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert comments_client.after_values_seen == [None, "CURSOR_1"]
    assert summary.media_checked == 1
    assert summary.new_comments == 3  # c1 + c2 (page one) + c3 (page two)

    # Re-running must find all three already known (no duplicates), proving they were
    # actually persisted — not merely counted — from BOTH pages, not just page one.
    second = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    assert second.new_comments == 0


async def test_sync_comments_stops_paginating_once_a_page_is_fully_known() -> None:
    """The other half of the same criterion: a re-sync where page one has NOTHING new
    must not walk into page two at all — `page_had_new=False` breaks the loop
    immediately (`service.py`'s early-stop, since there is no since-cursor to lean on
    instead per `INCREMENTAL_POLLING_NOTE`). Proven by a media id whose SECOND page is
    intentionally missing from the fake: if the service tried to fetch it, this test
    would raise `KeyError`, not merely assert something wrong."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    page_one = IGCommentsPage(data=[_comment("c1")], paging={"cursors": {"after": "CURSOR_1"}})
    page_two = IGCommentsPage(data=[_comment("c2")], paging=None)
    comments_client = PaginatedFakeCommentsClient({"A": {None: page_one, "CURSOR_1": page_two}})
    service = InboxService(
        repository=repository, comments_client=comments_client, media_client=FakeMediaClient({})
    )
    await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)  # primes c1, c2
    # A resync's PaginatedFakeCommentsClient here reuses the same two pages: page one is
    # now fully known (c1 already stored), so the service must stop right there.
    comments_client.after_values_seen.clear()

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert comments_client.after_values_seen == [None]  # page two never requested
    assert summary.new_comments == 0


# --------------------------------------------------------------------------------------
# set_media_monitored — the 2-week re-validation, live against Meta, every time
# --------------------------------------------------------------------------------------


async def test_set_media_monitored_accepts_recent_media() -> None:
    repository = MemoryInboxRepository()
    media_client = FakeMediaClient({"A": MediaSummary(id="A", timestamp=NOW - timedelta(days=1))})
    service = InboxService(
        repository=repository, comments_client=FakeCommentsClient({}), media_client=media_client
    )

    await service.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        now=NOW,
    )

    assert repository.list_monitored_media_ids(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID
    ) == {"A"}


async def test_set_media_monitored_rejects_media_older_than_the_window() -> None:
    repository = MemoryInboxRepository()
    old_timestamp = NOW - MONITORING_WINDOW - timedelta(days=1)
    media_client = FakeMediaClient({"OLD": MediaSummary(id="OLD", timestamp=old_timestamp)})
    service = InboxService(
        repository=repository, comments_client=FakeCommentsClient({}), media_client=media_client
    )

    with pytest.raises(MediaNotEligible) as exc_info:
        await service.set_media_monitored(
            tenant_id=TENANT_ID,
            connection_id=CONNECTION_ID,
            external_media_id="OLD",
            monitored=True,
            now=NOW,
        )

    assert exc_info.value.reason == "too_old"
    # The rejection must be enforced BEFORE persistence, not just reported after.
    assert repository.list_monitored_media_ids(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID
    ) == (frozenset())


async def test_set_media_monitored_wraps_an_unreadable_media_as_not_eligible() -> None:
    """A caller bypassing the candidate-listing UI with a fabricated or foreign media_id
    must be rejected the same way an old one is — `get_media` failing is not a crash."""
    repository = MemoryInboxRepository()
    service = InboxService(
        repository=repository,
        comments_client=FakeCommentsClient({}),
        media_client=FakeMediaClient({}),
    )

    with pytest.raises(MediaNotEligible) as exc_info:
        await service.set_media_monitored(
            tenant_id=TENANT_ID,
            connection_id=CONNECTION_ID,
            external_media_id="DOES_NOT_EXIST",
            monitored=True,
            now=NOW,
        )

    assert exc_info.value.reason == "not_found_or_inaccessible"


async def test_disabling_monitoring_never_calls_meta() -> None:
    """Turning OFF is not gated by age — the window only bounds what can be ADDED."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    media_client = FakeMediaClient({})  # would raise MediaReadError if ever called
    service = InboxService(
        repository=repository, comments_client=FakeCommentsClient({}), media_client=media_client
    )

    await service.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=False,
        now=NOW,
    )

    assert media_client.get_media_calls == []
    assert repository.list_monitored_media_ids(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID
    ) == (frozenset())


# --------------------------------------------------------------------------------------
# list_candidate_media — cross-references what is already monitored
# --------------------------------------------------------------------------------------


async def test_list_candidate_media_marks_already_monitored_items() -> None:
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    media_client = FakeMediaClient(
        {
            "A": MediaSummary(
                id="A", timestamp=NOW - timedelta(days=1), media_product_type="REELS"
            ),
            "B": MediaSummary(
                id="B", timestamp=NOW - timedelta(days=2), media_product_type="REELS"
            ),
        }
    )
    service = InboxService(
        repository=repository, comments_client=FakeCommentsClient({}), media_client=media_client
    )

    candidates = await service.list_candidate_media(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, ig_user_id=IG_USER_ID, now=NOW
    )

    by_id = {c.external_media_id: c for c in candidates}
    assert by_id["A"].is_monitored is True
    assert by_id["B"].is_monitored is False


async def test_list_candidate_media_carries_display_fields_through() -> None:
    repository = MemoryInboxRepository()
    media_client = FakeMediaClient(
        {
            "A": MediaSummary(
                id="A",
                timestamp=NOW - timedelta(days=1),
                media_product_type="REELS",
                caption="hello world",
                permalink="https://instagram.com/reel/A",
                thumbnail_url="https://cdn/A.jpg",
            )
        }
    )
    service = InboxService(
        repository=repository, comments_client=FakeCommentsClient({}), media_client=media_client
    )

    (candidate,) = await service.list_candidate_media(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, ig_user_id=IG_USER_ID, now=NOW
    )

    assert candidate.caption == "hello world"
    assert candidate.permalink == "https://instagram.com/reel/A"
    assert candidate.thumbnail_url == "https://cdn/A.jpg"


async def test_list_candidate_media_excludes_non_reel_media() -> None:
    """Feed photos/carousels are real Meta media but nothing downstream of this screen
    (monitoring, publishing) operates on them — only REELS is offered."""
    repository = MemoryInboxRepository()
    media_client = FakeMediaClient(
        {
            "A": MediaSummary(
                id="A", timestamp=NOW - timedelta(days=1), media_product_type="REELS"
            ),
            "B": MediaSummary(id="B", timestamp=NOW - timedelta(days=1), media_product_type="FEED"),
            "C": MediaSummary(id="C", timestamp=NOW - timedelta(days=1), media_product_type=None),
        }
    )
    service = InboxService(
        repository=repository, comments_client=FakeCommentsClient({}), media_client=media_client
    )

    candidates = await service.list_candidate_media(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, ig_user_id=IG_USER_ID, now=NOW
    )

    assert [c.external_media_id for c in candidates] == ["A"]
