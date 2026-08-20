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
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGComment, IGCommentsPage

from qualify_api.inbox.client import CommentsReadError
from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import (
    META_CALL_BUDGET_PER_HOUR,
    MONITORING_WINDOW,
    CommentsAuthExpired,
    CommentsPermissionMissing,
    InboxService,
    MediaNotEligible,
    SyncBudgetExhausted,
    SyncSummary,
)

TENANT_ID = UUID("f0000000-0000-4000-8000-000000000001")
CONNECTION_ID = UUID("f0000000-0000-4000-8000-000000000002")
IG_USER_ID = "17841400000000000"
NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)

# `sync_comments` fails closed without this — every test below that calls it must opt in
# explicitly, same discipline `FakeMediaClient({})` already uses to prove a code path
# never reached Meta (QUA-88: an unwired service must refuse, not silently allow).
GRANTED = frozenset(COMMENTS_EDGE_PERMISSIONS)


class FakeCommentsClient:
    """Returns one fixed page per media id, and records which ids were actually queried —
    the assertion surface for "only monitored media gets synced". `error_by_media`
    (QUA-90) lets a test inject a `CommentsReadError` for one specific media id instead
    of a page — everything else about the fake is unchanged."""

    def __init__(
        self,
        comments_by_media: dict[str, list[IGComment]],
        *,
        error_by_media: dict[str, Exception] | None = None,
    ) -> None:
        self._comments_by_media = comments_by_media
        self._error_by_media = error_by_media or {}
        self.calls: list[str] = []

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        self.calls.append(ig_media_id)
        error = self._error_by_media.get(ig_media_id)
        if error is not None:
            raise error
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
        granted_scopes=GRANTED,
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert comments_client.calls == ["A"]
    assert summary.media_checked == 1
    assert summary.new_comments == 1


# --------------------------------------------------------------------------------------
# QUA-90 — a runtime 401/190 degrades the connection and raises CommentsAuthExpired
# --------------------------------------------------------------------------------------


async def test_401_degrades_the_connection_and_raises_comments_auth_expired() -> None:
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    comments_client = FakeCommentsClient(
        {},
        error_by_media={
            "A": CommentsReadError("GET /A/comments failed with HTTP 401", http_status=401)
        },
    )
    degrade_calls: list[tuple[UUID, UUID]] = []
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
        connection_degrader=lambda *, tenant_id, connection_id: degrade_calls.append(
            (tenant_id, connection_id)
        ),
    )

    with pytest.raises(CommentsAuthExpired) as exc_info:
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert exc_info.value.connection_id == CONNECTION_ID
    assert degrade_calls == [(TENANT_ID, CONNECTION_ID)]


async def test_code_190_degrades_even_without_a_401_status() -> None:
    """The ticket's detection condition is HTTP 401 **or** `error.code=190` — code 190
    alone (no captured HTTP status) must trigger the same path."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    comments_client = FakeCommentsClient(
        {}, error_by_media={"A": CommentsReadError("boom", platform_code=190)}
    )
    degrade_calls: list[tuple[UUID, UUID]] = []
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
        connection_degrader=lambda *, tenant_id, connection_id: degrade_calls.append(
            (tenant_id, connection_id)
        ),
    )

    with pytest.raises(CommentsAuthExpired):
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert degrade_calls == [(TENANT_ID, CONNECTION_ID)]


async def test_other_comments_read_errors_do_not_degrade_or_change_type() -> None:
    """Regression: only 401/190 triggers QUA-90's path — any other `CommentsReadError`
    (a bad media id, a transient 5xx) propagates exactly as it already did."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    original = CommentsReadError("GET /A/comments failed with HTTP 500", http_status=500)
    comments_client = FakeCommentsClient({}, error_by_media={"A": original})
    degrade_calls: list[tuple[UUID, UUID]] = []
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
        connection_degrader=lambda *, tenant_id, connection_id: degrade_calls.append(
            (tenant_id, connection_id)
        ),
    )

    with pytest.raises(CommentsReadError) as exc_info:
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert exc_info.value is original  # the SAME exception, not re-wrapped
    assert degrade_calls == []


async def test_sync_comments_is_idempotent_across_two_runs() -> None:
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    comments_client = FakeCommentsClient({"A": [_comment("c1"), _comment("c2")]})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    first = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    second = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert first.new_comments == 2
    assert second.new_comments == 0


async def test_sync_comments_with_no_monitored_media_touches_nothing() -> None:
    repository = MemoryInboxRepository()
    comments_client = FakeCommentsClient({})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
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
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
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
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
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


# --------------------------------------------------------------------------------------
# sync_comments — cannot_observe vs observed_zero (QUA-88)
# --------------------------------------------------------------------------------------


async def test_sync_refuses_without_comments_permission() -> None:
    """No scope granted -> CommentsPermissionMissing, raised before Meta is ever
    touched. This is `cannot_observe` — must never look like a normal empty result."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    comments_client = FakeCommentsClient({"A": [_comment("c1")]})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=frozenset(),  # nothing granted
    )

    with pytest.raises(CommentsPermissionMissing) as exc_info:
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)

    assert exc_info.value.connection_id == CONNECTION_ID
    assert comments_client.calls == []


async def test_sync_with_permission_and_no_new_comments_is_observed_zero_not_an_error() -> None:
    """The other half of the distinction: correctly permitted, genuinely nothing new to
    sync — an ordinary `SyncSummary`, never an exception. `observed_zero`."""
    repository = MemoryInboxRepository()
    comments_client = FakeCommentsClient({})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)

    assert summary == SyncSummary(media_checked=0, new_comments=0)


# --------------------------------------------------------------------------------------
# sync_comments — the real Meta call budget, 200/hour sliding window (QUA-88)
# --------------------------------------------------------------------------------------


async def test_sync_refuses_when_budget_insufficient_for_needed_calls() -> None:
    """Two monitored media, only one call left in the budget -> `SyncBudgetExhausted`
    BEFORE any Meta call at all — the floor estimate alone is enough to refuse."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="B", monitored=True
    )
    for _ in range(META_CALL_BUDGET_PER_HOUR - 1):
        repository.record_call(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, called_at=NOW)
    comments_client = FakeCommentsClient({"A": [_comment("c1")], "B": [_comment("c2")]})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    with pytest.raises(SyncBudgetExhausted) as exc_info:
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)

    assert exc_info.value.needed == 2
    assert exc_info.value.remaining == 1
    assert comments_client.calls == []


async def test_calls_older_than_one_hour_do_not_count_against_the_budget() -> None:
    """A true sliding window, not a calendar bucket: calls from over an hour before `now`
    must not still be counted against the budget."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    stale_call = NOW - timedelta(hours=1, minutes=1)
    for _ in range(META_CALL_BUDGET_PER_HOUR):
        repository.record_call(
            tenant_id=TENANT_ID, connection_id=CONNECTION_ID, called_at=stale_call
        )
    comments_client = FakeCommentsClient({"A": [_comment("c1")]})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)

    assert summary.new_comments == 1
    assert comments_client.calls == ["A"]


async def test_sync_records_one_ledger_entry_per_real_call_not_per_sync() -> None:
    """Pagination matters: a media whose comments span two pages must log TWO calls, not
    one — the ledger counts Meta calls, not sync invocations."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    page_one = IGCommentsPage(data=[_comment("c1")], paging={"cursors": {"after": "CURSOR_1"}})
    page_two = IGCommentsPage(data=[_comment("c2")], paging=None)
    comments_client = PaginatedFakeCommentsClient({"A": {None: page_one, "CURSOR_1": page_two}})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)

    assert (
        repository.calls_in_last_hour(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)
        == 2
    )


async def test_budget_exhausted_mid_pagination_stops_and_returns_partial() -> None:
    """The floor estimate (1 call) fit the budget, but this media's comments paginate
    into a second page and the budget runs out exactly there: the sync must stop, keep
    what it already synced (idempotent, nothing lost), and say so via `truncated=True`
    — not raise and discard already-useful work."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, external_media_id="A", monitored=True
    )
    for _ in range(META_CALL_BUDGET_PER_HOUR - 1):  # exactly 1 call left
        repository.record_call(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, called_at=NOW)
    page_one = IGCommentsPage(data=[_comment("c1")], paging={"cursors": {"after": "CURSOR_1"}})
    page_two = IGCommentsPage(data=[_comment("c2")], paging=None)
    comments_client = PaginatedFakeCommentsClient({"A": {None: page_one, "CURSOR_1": page_two}})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)

    assert summary.truncated is True
    assert summary.new_comments == 1  # page one landed
    assert comments_client.after_values_seen == [None]  # page two was never requested
