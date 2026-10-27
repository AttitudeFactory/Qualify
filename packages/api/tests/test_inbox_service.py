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
from qualify_api.inbox.monitoring import MediaMetadata
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

# QUA-149: a row monitored after 0046 carries its metadata — published a day ago by the
# REAL clock (sync calls without `now=` use it), so it is inside the window whatever
# `now` a test passes. Seeding without it would model a legacy row, which now costs one
# metadata read; the tests that mean that seed it explicitly. QUA-146: complete also
# means "has its `media_type`" — a complete row without it costs one dedicated read
# (`MediaToSync.needs_media_type`); the tests that mean that seed it explicitly.
FRESH = MediaMetadata(
    posted_at=datetime.now(UTC) - timedelta(days=1),
    media_product_type="REELS",
    media_type="VIDEO",
)

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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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


# --------------------------------------------------------------------------------------
# Bug fix (2026-09-01): a monitored medium Meta confirms no longer exists must not abort
# the whole sync — see `InboxService.sync_comments`'s `_is_missing_media_error` branch.
# --------------------------------------------------------------------------------------


def _missing_media_error(media_id: str) -> CommentsReadError:
    """Meta's real, documented cross-edge "this node no longer exists" signature (HTTP
    400, `error.code=100`, `error.error_subcode=33`) — see `_is_missing_media_error`'s
    docstring in `service.py` for why this exact pairing, not `code=100` alone."""
    return CommentsReadError(
        f"GET /{media_id}/comments failed with HTTP 400",
        platform_code=100,
        platform_subcode=33,
        http_status=400,
    )


async def test_a_deleted_reel_between_two_healthy_ones_does_not_abort_the_sync() -> None:
    """The exact shape of the real-world bug: three monitored Reels, the middle one
    deleted at the source. Both healthy Reels must still sync — the old behavior was
    that ANY one `CommentsReadError` aborted the entire pass, so neither would."""
    repository = MemoryInboxRepository()
    for media_id in ("HEALTHY_1", "DELETED", "HEALTHY_2"):
        repository.set_media_monitored(
            tenant_id=TENANT_ID,
            connection_id=CONNECTION_ID,
            external_media_id=media_id,
            monitored=True,
            metadata=FRESH,
        )
    comments_client = FakeCommentsClient(
        {"HEALTHY_1": [_comment("c1")], "HEALTHY_2": [_comment("c2")]},
        error_by_media={"DELETED": _missing_media_error("DELETED")},
    )
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    # Both healthy media were actually queried — the deleted one in between never
    # aborted the loop, regardless of where it fell in iteration order.
    assert set(comments_client.calls) == {"HEALTHY_1", "DELETED", "HEALTHY_2"}
    assert summary.new_comments == 2  # c1 + c2 — both healthy Reels' comments landed
    assert summary.skipped_missing_media == ("DELETED",)
    assert summary.media_checked == 3  # every monitored id was attempted


async def test_sync_with_only_a_deleted_reel_succeeds_with_nothing_new() -> None:
    """The narrowest case the bug report described: the ONE monitored Reel is the
    deleted one. Must return normally (no exception) with an informative summary, never
    raise `CommentsReadError` up to the caller."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="DELETED",
        monitored=True,
        metadata=FRESH,
    )
    comments_client = FakeCommentsClient(
        {}, error_by_media={"DELETED": _missing_media_error("DELETED")}
    )
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.new_comments == 0
    assert summary.skipped_missing_media == ("DELETED",)
    assert summary.truncated is False


async def test_a_deleted_reel_is_auto_unmonitored() -> None:
    """Meta itself just confirmed the id can never be read again — leaving
    `is_monitored=true` would only retry it (and burn QUA-88 budget) on every future
    sync/poll tick forever. Must come out of `list_monitored_media_ids` afterward."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="DELETED",
        monitored=True,
        metadata=FRESH,
    )
    comments_client = FakeCommentsClient(
        {}, error_by_media={"DELETED": _missing_media_error("DELETED")}
    )
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert (
        repository.list_monitored_media_ids(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
        == frozenset()
    )
    # And a re-sync right after must not even attempt it again — it is simply no longer
    # monitored, the ordinary way `list_monitored_media_ids` already excludes it.
    comments_client.calls.clear()
    await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    assert comments_client.calls == []


async def test_a_code_100_error_with_a_different_subcode_is_not_treated_as_deleted() -> None:
    """Regression guard for the bug-fix requirement to NOT filter on `platform_code ==
    100` alone: `reference/meta-instagram-platform/.../error-codes.md` documents over a
    dozen UNRELATED validation errors that also carry `code=100` (bad media type, too
    many tags, malformed params, ...). A `code=100` error with a subcode OTHER than 33
    is a real, different failure and must still abort/propagate exactly like any other
    `CommentsReadError` did before this fix — never silently swallowed as "deleted"."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
    )
    original = CommentsReadError(
        "GET /A/comments failed with HTTP 400",
        platform_code=100,
        platform_subcode=9050,  # a real, unrelated code-100 error from error-codes.md
        http_status=400,
    )
    comments_client = FakeCommentsClient({}, error_by_media={"A": original})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    with pytest.raises(CommentsReadError) as exc_info:
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert exc_info.value is original  # propagated, not misclassified as "deleted"
    # Never auto-unmonitored on a false-positive "deleted" read.
    assert repository.list_monitored_media_ids(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID
    ) == {"A"}


async def test_a_real_500_between_two_healthy_reels_still_aborts_the_sync() -> None:
    """Contrast case, same 3-media shape as the "deleted Reel" test above: a genuinely
    different, real Meta failure (a transient 500, not "does not exist") must NOT be
    quietly absorbed the same way — it still aborts the pass exactly as before this fix,
    so it stays visible as a real failure rather than being hidden as a soft skip."""
    repository = MemoryInboxRepository()
    for media_id in ("HEALTHY_1", "BROKEN", "HEALTHY_2"):
        repository.set_media_monitored(
            tenant_id=TENANT_ID,
            connection_id=CONNECTION_ID,
            external_media_id=media_id,
            monitored=True,
            metadata=FRESH,
        )
    real_error = CommentsReadError("GET /BROKEN/comments failed with HTTP 500", http_status=500)
    comments_client = FakeCommentsClient(
        {"HEALTHY_1": [_comment("c1")], "HEALTHY_2": [_comment("c2")]},
        error_by_media={"BROKEN": real_error},
    )
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    with pytest.raises(CommentsReadError) as exc_info:
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert exc_info.value is real_error
    # Never auto-unmonitored on a real, unrelated failure.
    assert "BROKEN" in repository.list_monitored_media_ids(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID
    )


async def test_a_deleted_reel_does_not_short_circuit_a_401_elsewhere_in_the_batch() -> None:
    """The auth path (QUA-90) must stay exactly as aborting/degrading as before this fix
    — a deleted Reel earlier in the same batch must not mask or interfere with a genuine
    401 on another monitored id."""
    repository = MemoryInboxRepository()
    for media_id in ("DELETED", "AUTH_BROKEN"):
        repository.set_media_monitored(
            tenant_id=TENANT_ID,
            connection_id=CONNECTION_ID,
            external_media_id=media_id,
            monitored=True,
            metadata=FRESH,
        )
    comments_client = FakeCommentsClient(
        {},
        error_by_media={
            "DELETED": _missing_media_error("DELETED"),
            "AUTH_BROKEN": CommentsReadError(
                "GET /AUTH_BROKEN/comments failed with HTTP 401", http_status=401
            ),
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

    with pytest.raises(CommentsAuthExpired):
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert degrade_calls == [(TENANT_ID, CONNECTION_ID)]


async def test_sync_comments_is_idempotent_across_two_runs() -> None:
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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


async def test_sync_comments_still_walks_to_completion_when_a_page_is_fully_known() -> None:
    """QUA-101 behavior change, superseding the old early-stop: a re-sync where page one
    has NOTHING new must still walk into page two, all the way to Meta's own end of
    pagination (`cursor is None`) — stopping at the first fully-known page (the previous
    design) is structurally blind to a comment disappearing further back in the list, so
    it cannot coexist with deletion reconciliation. Both pages being fully known and
    unchanged, nothing is (re)marked deleted."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
    comments_client.after_values_seen.clear()

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert comments_client.after_values_seen == [None, "CURSOR_1"]  # page two now requested
    assert summary.new_comments == 0
    assert summary.deleted_comments == 0
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c1")
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c2")


@pytest.mark.parametrize("code", [10, 200, 230])
async def test_permission_removed_marks_account_and_stops_before_next_media(code) -> None:
    repository = MemoryInboxRepository()
    for media_id in ("A", "B"):
        repository.set_media_monitored(
            tenant_id=TENANT_ID,
            connection_id=CONNECTION_ID,
            external_media_id=media_id,
            monitored=True,
            metadata=FRESH,
        )
    observed = []
    client = FakeCommentsClient(
        {},
        error_by_media={"A": CommentsReadError("permission", platform_code=code, http_status=403)},
    )
    service = InboxService(
        repository=repository,
        comments_client=client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
        connection_unavailable=lambda **kwargs: observed.append(kwargs),
    )
    with pytest.raises(CommentsPermissionMissing):
        await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    assert client.calls == ["A"]
    assert observed == [
        dict(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, cause="permission_missing")
    ]


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, None, CommentsAuthExpired),
        (400, 190, CommentsAuthExpired),
        (403, 10, CommentsPermissionMissing),
        (403, 230, CommentsPermissionMissing),
    ],
)
async def test_media_picker_classifies_permanent_account_failures(status, code, expected) -> None:
    class RefusedMedia(FakeMediaClient):
        async def list_recent_media(self, **kwargs):
            raise MediaReadError("denied", http_status=status, platform_code=code)

    causes = []
    auth = []
    service = InboxService(
        repository=MemoryInboxRepository(),
        comments_client=FakeCommentsClient({}),
        media_client=RefusedMedia({}),
        granted_scopes=GRANTED,
        connection_degrader=lambda **kwargs: auth.append(kwargs),
        connection_unavailable=lambda **kwargs: causes.append(kwargs),
    )
    with pytest.raises(expected):
        await service.list_candidate_media(
            tenant_id=TENANT_ID, connection_id=CONNECTION_ID, ig_user_id=IG_USER_ID
        )
    assert bool(auth) is (expected is CommentsAuthExpired)
    assert [cause["cause"] for cause in causes] == (
        ["permission_missing"] if expected is CommentsPermissionMissing else []
    )


# --------------------------------------------------------------------------------------
# set_media_monitored — the 2-week re-validation, live against Meta, every time
# --------------------------------------------------------------------------------------


async def test_set_media_monitored_accepts_recent_media() -> None:
    repository = MemoryInboxRepository()
    media_client = FakeMediaClient(
        {"A": MediaSummary(id="A", timestamp=NOW - timedelta(days=1), media_product_type="REELS")}
    )
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
    media_client = FakeMediaClient(
        {"OLD": MediaSummary(id="OLD", timestamp=old_timestamp, media_product_type="REELS")}
    )
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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


async def test_list_candidate_media_offers_reels_and_feed_only() -> None:
    """QUA-146: Reels and feed posts (any `media_type`) are offered; Stories, ads and a
    media whose surface Meta did not report are not."""
    repository = MemoryInboxRepository()
    media_client = FakeMediaClient(
        {
            "A": MediaSummary(
                id="A", timestamp=NOW - timedelta(days=1), media_product_type="REELS"
            ),
            "B": MediaSummary(id="B", timestamp=NOW - timedelta(days=1), media_product_type="FEED"),
            "C": MediaSummary(id="C", timestamp=NOW - timedelta(days=1), media_product_type=None),
            "D": MediaSummary(
                id="D", timestamp=NOW - timedelta(days=1), media_product_type="STORY"
            ),
            "E": MediaSummary(id="E", timestamp=NOW - timedelta(days=1), media_product_type="AD"),
        }
    )
    service = InboxService(
        repository=repository, comments_client=FakeCommentsClient({}), media_client=media_client
    )

    candidates = await service.list_candidate_media(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, ig_user_id=IG_USER_ID, now=NOW
    )

    assert [c.external_media_id for c in candidates] == ["A", "B"]


# --------------------------------------------------------------------------------------
# sync_comments — cannot_observe vs observed_zero (QUA-88)
# --------------------------------------------------------------------------------------


async def test_sync_refuses_without_comments_permission() -> None:
    """No scope granted -> CommentsPermissionMissing, raised before Meta is ever
    touched. This is `cannot_observe` — must never look like a normal empty result."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
    )
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="B",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
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


# --------------------------------------------------------------------------------------
# QUA-101 — reconciliation: a comment Meta stops returning is soft-deleted, restored if
# it reappears, and a truncated/whole-Reel-deleted walk never reconciles at all.
# --------------------------------------------------------------------------------------


async def test_a_comment_deleted_at_the_source_is_marked_deleted_and_excluded() -> None:
    """The exact shape of the reported bug (QUA-101): sync a comment, persist it, then
    Meta simply stops returning it on the next sync (the Reel itself is untouched, no
    error) — Qualify must mark it deleted rather than leaving it looking active forever."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
    )
    comments_by_media: dict[str, list[IGComment]] = {"A": [_comment("c1")]}
    comments_client = FakeCommentsClient(comments_by_media)
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )
    first = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    assert first.new_comments == 1
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c1")

    # The comment's author deleted it on Instagram: the next poll's response for this
    # media simply no longer includes it — no error, the Reel itself is fine.
    comments_by_media["A"] = []

    second = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert second.new_comments == 0
    assert second.deleted_comments == 1
    assert repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c1")


async def test_a_comment_still_present_across_syncs_is_never_marked_deleted() -> None:
    """Guards against a false positive: a comment Meta keeps returning, unchanged,
    across repeated syncs must never be (mis)marked deleted."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
    )
    comments_client = FakeCommentsClient({"A": [_comment("c1")]})
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    for _ in range(3):
        summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
        assert summary.deleted_comments == 0
        assert not repository.is_comment_deleted(
            connection_id=CONNECTION_ID, external_message_id="c1"
        )


async def test_a_new_comment_alongside_an_existing_one_still_counts_as_new() -> None:
    """New-comment detection must keep working unchanged: an existing comment staying
    put and a genuinely new one appearing alongside it in the same sync must both be
    handled correctly — the existing one untouched, the new one landing as new."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
    )
    comments_by_media: dict[str, list[IGComment]] = {"A": [_comment("c1")]}
    comments_client = FakeCommentsClient(comments_by_media)
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )
    await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    comments_by_media["A"] = [_comment("c1"), _comment("c2")]  # c2 is genuinely new

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.new_comments == 1  # only c2
    assert summary.deleted_comments == 0
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c1")
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c2")


async def test_a_soft_deleted_comment_that_reappears_is_restored() -> None:
    """If Meta shows a previously-vanished comment again — most plausibly the
    pagination-shift race `ig_shapes.INCREMENTAL_POLLING_NOTE` documents, not a real
    delete-then-undelete on Instagram's side — it must come back as active, not stay
    soft-deleted forever."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
    )
    comments_by_media: dict[str, list[IGComment]] = {"A": [_comment("c1")]}
    comments_client = FakeCommentsClient(comments_by_media)
    service = InboxService(
        repository=repository,
        comments_client=comments_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )
    await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    comments_by_media["A"] = []
    await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    assert repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c1")

    comments_by_media["A"] = [_comment("c1")]  # reappears

    third = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert third.new_comments == 0  # a restore is not "new"
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c1")


async def test_a_deleted_reel_does_not_soft_delete_its_already_synced_comments() -> None:
    """Differentiates the two deletion shapes explicitly (QUA-101): the WHOLE-REEL case
    (`_is_missing_media_error`, already auto-unmonitors) must never ALSO run
    comment-level reconciliation for it — a Reel disappearing is a different, already
    fully-handled event, not a signal that every comment ever synced under it is now
    individually "deleted"."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="DELETED",
        monitored=True,
        metadata=FRESH,
    )
    priming_service = InboxService(
        repository=repository,
        comments_client=FakeCommentsClient({"DELETED": [_comment("c1")]}),
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )
    await priming_service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    # The Reel itself is deleted at the source on the next sync — a different client,
    # same shape `test_a_deleted_reel_is_auto_unmonitored` already uses.
    service = InboxService(
        repository=repository,
        comments_client=FakeCommentsClient(
            {}, error_by_media={"DELETED": _missing_media_error("DELETED")}
        ),
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    summary = await service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.skipped_missing_media == ("DELETED",)
    assert summary.deleted_comments == 0
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c1")


async def test_a_truncated_walk_never_reconciles_anything() -> None:
    """Safety net: a walk that ran out of budget mid-pagination has not seen Meta's
    complete current list, so it must never conclude a comment is missing — doing so
    would be a false positive the moment the budget (not a real deletion) was the
    reason a comment was not (yet) observed this pass."""
    repository = MemoryInboxRepository()
    repository.set_media_monitored(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_media_id="A",
        monitored=True,
        metadata=FRESH,
    )
    # Prime c1 and c2 in an earlier, unconstrained sync.
    page_one = IGCommentsPage(data=[_comment("c1")], paging={"cursors": {"after": "CURSOR_1"}})
    page_two = IGCommentsPage(data=[_comment("c2")], paging=None)
    priming_client = PaginatedFakeCommentsClient({"A": {None: page_one, "CURSOR_1": page_two}})
    priming_service = InboxService(
        repository=repository,
        comments_client=priming_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )
    await priming_service.sync_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW)

    # Now re-sync with only 1 call left in the budget: page one (still just c1) is all
    # that gets fetched before the budget forces a stop — c2 was never re-observed this
    # pass, but that must NOT be read as "c2 was deleted". Accounts for the 2 calls the
    # priming sync above already logged — the budget is a real sliding window, not reset
    # between syncs.
    already_logged = repository.calls_in_last_hour(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW
    )
    for _ in range(META_CALL_BUDGET_PER_HOUR - 1 - already_logged):
        repository.record_call(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, called_at=NOW)
    constrained_client = PaginatedFakeCommentsClient({"A": {None: page_one, "CURSOR_1": page_two}})
    constrained_service = InboxService(
        repository=repository,
        comments_client=constrained_client,
        media_client=FakeMediaClient({}),
        granted_scopes=GRANTED,
    )

    summary = await constrained_service.sync_comments(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, now=NOW
    )

    assert summary.truncated is True
    assert summary.deleted_comments == 0
    assert not repository.is_comment_deleted(connection_id=CONNECTION_ID, external_message_id="c2")
