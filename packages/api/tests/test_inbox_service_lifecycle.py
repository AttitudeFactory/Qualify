"""QUA-149 phase 2: the 14-day lifecycle applied by `InboxService` — activation stores
metadata, the sync skips expired media without any Meta call, and legacy rows get their
metadata read once, with deletions told apart from transient/permission/rate-limit
failures. Offline, against `MemoryInboxRepository` and fakes (same posture as
`test_inbox_service.py`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGComment, IGCommentsPage

from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.monitoring import (
    METADATA_RETRY_AFTER,
    MONITORING_WINDOW,
    MediaMetadata,
    MetadataFetchError,
    MonitoringState,
)
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import (
    META_CALL_BUDGET_PER_HOUR,
    CommentsAuthExpired,
    CommentsPermissionMissing,
    InboxService,
    MediaNotEligible,
)

TENANT = UUID("f1490000-0000-4000-8000-000000000001")
CONNECTION = UUID("f1490000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
GRANTED = frozenset(COMMENTS_EDGE_PERMISSIONS)


class FakeComments:
    def __init__(
        self,
        comments_by_media: dict[str, list[IGComment]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._comments = comments_by_media or {}
        self._errors = errors or {}
        self.calls: list[str] = []

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        self.calls.append(ig_media_id)
        if ig_media_id in self._errors:
            raise self._errors[ig_media_id]
        return IGCommentsPage(data=self._comments.get(ig_media_id, []))


class FakeMedia:
    """`get_media` returns the summary or raises the error configured for that id."""

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


def _summary(media_id: str, posted_at: datetime, caption: str = "caption") -> MediaSummary:
    return MediaSummary(
        id=media_id,
        timestamp=posted_at,
        media_product_type="REELS",
        caption=caption,
        permalink=f"https://www.instagram.com/reel/{media_id}/",
    )


def _comment(comment_id: str) -> IGComment:
    return IGComment.model_validate({"id": comment_id, "text": "hola"})


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


def _monitor(repo: MemoryInboxRepository, media_id: str, posted_at: datetime | None) -> None:
    """`posted_at=None` seeds a LEGACY row (monitored before 0046, no metadata). A dated
    row is complete, `media_type` included (QUA-146) — rows without it are covered in
    `test_inbox_media_type_sync.py`."""
    repo.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id=media_id,
        monitored=True,
        metadata=None
        if posted_at is None
        else MediaMetadata(
            posted_at=posted_at, caption="c", media_product_type="REELS", media_type="VIDEO"
        ),
        fetched_at=None if posted_at is None else NOW - timedelta(days=20),
    )


def _ledger(repo: MemoryInboxRepository, at: datetime = NOW) -> int:
    return repo.calls_in_last_hour(tenant_id=TENANT, connection_id=CONNECTION, now=at)


def _row(repo: MemoryInboxRepository, media_id: str):
    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id=media_id
    )
    assert row is not None
    return row


async def _sync(service: InboxService, at: datetime = NOW):
    return await service.sync_comments(tenant_id=TENANT, connection_id=CONNECTION, now=at)


# --- activation -------------------------------------------------------------------------


async def test_activation_stores_what_meta_returned() -> None:
    repo = MemoryInboxRepository()
    media = FakeMedia({"R": _summary("R", NOW - timedelta(days=2), caption="Promo")})

    await _service(repo, media=media).set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="R", monitored=True, now=NOW
    )

    row = _row(repo, "R")
    assert row.is_monitored
    assert row.media_posted_at == NOW - timedelta(days=2)
    assert row.caption == "Promo"
    assert row.permalink == "https://www.instagram.com/reel/R/"
    assert row.media_product_type == "REELS"
    assert row.metadata_fetched_at == NOW


async def test_activation_on_the_exact_boundary_is_accepted() -> None:
    repo = MemoryInboxRepository()
    media = FakeMedia({"R": _summary("R", NOW - MONITORING_WINDOW)})

    await _service(repo, media=media).set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="R", monitored=True, now=NOW
    )

    assert _row(repo, "R").is_monitored


async def test_activation_just_past_the_window_is_refused_and_stores_nothing() -> None:
    repo = MemoryInboxRepository()
    media = FakeMedia({"R": _summary("R", NOW - MONITORING_WINDOW - timedelta(microseconds=1))})

    with pytest.raises(MediaNotEligible) as exc_info:
        await _service(repo, media=media).set_media_monitored(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            external_media_id="R",
            monitored=True,
            now=NOW,
        )

    assert exc_info.value.reason == "too_old"
    assert (
        repo.get_monitored_media(tenant_id=TENANT, connection_id=CONNECTION, external_media_id="R")
        is None
    )


async def test_turning_off_keeps_the_stored_metadata_and_calls_no_meta() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "R", NOW - timedelta(days=2))
    media = FakeMedia()

    await _service(repo, media=media).set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="R", monitored=False, now=NOW
    )

    row = _row(repo, "R")
    assert not row.is_monitored and row.caption == "c"
    assert media.calls == []


# --- expired media: no Meta call, no ledger entry, history intact -----------------------


async def test_an_expired_media_costs_no_meta_call_and_no_ledger_entry() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "OLD", NOW - MONITORING_WINDOW - timedelta(seconds=1))
    comments, media = FakeComments({"OLD": [_comment("x")]}), FakeMedia()

    summary = await _sync(_service(repo, comments=comments, media=media))

    assert comments.calls == [] and media.calls == []
    assert _ledger(repo) == 0
    assert summary.media_checked == 0
    assert summary.expired_skipped == 1
    assert _row(repo, "OLD").state(NOW) is MonitoringState.EXPIRED


async def test_the_window_boundary_is_exact_in_the_sync() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "EDGE", NOW - MONITORING_WINDOW)
    _monitor(repo, "PAST", NOW - MONITORING_WINDOW - timedelta(seconds=1))
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments))

    assert comments.calls == ["EDGE"]
    assert summary.media_checked == 1 and summary.expired_skipped == 1


async def test_expiry_never_soft_deletes_or_touches_stored_comments() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "R", NOW - timedelta(days=13))
    comments = FakeComments({"R": [_comment("c1"), _comment("c2")]})
    service = _service(repo, comments=comments)
    first = await _sync(service, NOW)
    assert first.new_comments == 2

    # Two days later the Reel is past its window; Meta would now return nothing.
    later = NOW + timedelta(days=2)
    second = await _sync(_service(repo, comments=FakeComments({"R": []})), later)

    assert second.media_checked == 0 and second.expired_skipped == 1
    assert second.deleted_comments == 0
    for comment_id in ("c1", "c2"):
        assert not repo.is_comment_deleted(connection_id=CONNECTION, external_message_id=comment_id)
    assert _row(repo, "R").caption == "c"


async def test_active_media_keep_syncing_next_to_expired_ones() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "A1", NOW - timedelta(days=1))
    _monitor(repo, "OLD", NOW - timedelta(days=30))
    _monitor(repo, "A2", NOW - timedelta(days=10))
    comments = FakeComments({"A1": [_comment("a")], "A2": [_comment("b")], "OLD": [_comment("z")]})

    summary = await _sync(_service(repo, comments=comments))

    assert sorted(comments.calls) == ["A1", "A2"]
    assert summary.new_comments == 2 and summary.expired_skipped == 1
    assert _ledger(repo) == 2


async def test_expired_media_are_not_part_of_the_budget_floor() -> None:
    """With one call left, one active and many expired media must still sync — the floor
    counts only media in their window."""
    repo = MemoryInboxRepository()
    _monitor(repo, "ACTIVE", NOW - timedelta(days=1))
    for i in range(5):
        _monitor(repo, f"OLD{i}", NOW - timedelta(days=40))
    for _ in range(META_CALL_BUDGET_PER_HOUR - 1):
        repo.record_call(tenant_id=TENANT, connection_id=CONNECTION, called_at=NOW)
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments))

    assert comments.calls == ["ACTIVE"]
    assert summary.expired_skipped == 5 and not summary.truncated


# --- legacy rows: metadata read once ---------------------------------------------------


async def test_a_legacy_active_row_is_completed_then_synced() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    media = FakeMedia({"L": _summary("L", NOW - timedelta(days=3), caption="Legacy")})
    comments = FakeComments({"L": [_comment("c1")]})

    summary = await _sync(_service(repo, comments=comments, media=media))

    assert media.calls == ["L"] and comments.calls == ["L"]
    assert summary.metadata_backfilled == 1 and summary.new_comments == 1
    assert _ledger(repo) == 2  # one metadata read + one comments page, both real
    row = _row(repo, "L")
    assert row.caption == "Legacy" and row.metadata_fetched_at == NOW


async def test_a_legacy_expired_row_is_completed_and_never_synced_or_reread() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    media = FakeMedia({"L": _summary("L", NOW - timedelta(days=60), caption="Old one")})
    comments = FakeComments({"L": [_comment("c1")]})
    service = _service(repo, comments=comments, media=media)

    first = await _sync(service)
    second = await _sync(service, NOW + timedelta(hours=2))

    assert media.calls == ["L"]  # read once, never again
    assert comments.calls == []
    assert first.metadata_backfilled == 1 and first.expired_skipped == 1
    assert second.expired_skipped == 1 and second.metadata_backfilled == 0
    assert _ledger(repo, NOW) == 1
    row = _row(repo, "L")
    assert row.is_monitored and row.caption == "Old one"
    assert row.state(NOW) is MonitoringState.EXPIRED


async def test_a_confirmed_deletion_turns_monitoring_off_and_keeps_history() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    repo.upsert_comment(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="L", comment=_comment("c1")
    )
    deleted = MediaReadError("gone", http_status=400, platform_code=100, platform_subcode=33)
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments, media=FakeMedia(errors={"L": deleted})))

    assert summary.skipped_missing_media == ("L",)
    assert comments.calls == []
    assert not _row(repo, "L").is_monitored
    assert not repo.is_comment_deleted(connection_id=CONNECTION, external_message_id="c1")


async def test_code_100_without_subcode_33_is_not_a_deletion() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    error = MediaReadError("bad", http_status=400, platform_code=100, platform_subcode=None)
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments, media=FakeMedia(errors={"L": error})))

    row = _row(repo, "L")
    assert row.is_monitored
    assert row.metadata_error is MetadataFetchError.UNKNOWN
    assert summary.metadata_failed == 1 and summary.skipped_missing_media == ()
    assert comments.calls == ["L"]  # date unknown: still synced


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (MediaReadError("x", http_status=500), MetadataFetchError.TRANSIENT),
        (MediaReadError("x", http_status=400, platform_code=2), MetadataFetchError.TRANSIENT),
        (MediaReadError("x", http_status=403, platform_code=10), MetadataFetchError.PERMISSION),
        (MediaReadError("x", http_status=400, platform_code=200), MetadataFetchError.PERMISSION),
        (MediaReadError("malformed 200"), MetadataFetchError.UNKNOWN),
    ],
)
async def test_non_deletion_failures_are_labelled_and_never_unmonitor(
    error: MediaReadError, label: MetadataFetchError
) -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    comments = FakeComments({"L": [_comment("c1")]})

    service = _service(repo, comments=comments, media=FakeMedia(errors={"L": error}))
    permanent_permission = error.platform_code == 10 or (
        error.platform_code is not None and 200 <= error.platform_code < 300
    )
    if permanent_permission:
        with pytest.raises(CommentsPermissionMissing):
            await _sync(service)
    else:
        summary = await _sync(service)

    row = _row(repo, "L")
    assert row.is_monitored
    assert row.metadata_error is label and row.metadata_attempted_at == NOW
    assert row.metadata_fetched_at is None
    if permanent_permission:
        assert comments.calls == []
    else:
        assert summary.metadata_failed == 1 and not summary.truncated
        assert comments.calls == ["L"] and summary.new_comments == 1


@pytest.mark.parametrize(
    "error",
    [
        MediaReadError("x", http_status=429),
        MediaReadError("x", http_status=400, platform_code=4),
        MediaReadError("x", http_status=400, platform_code=80002),
    ],
)
async def test_a_rate_limited_read_stops_the_pass_without_unmonitoring(
    error: MediaReadError,
) -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "A", NOW - timedelta(days=1))
    _monitor(repo, "L", None)
    _monitor(repo, "Z", NOW - timedelta(days=1))
    comments = FakeComments()

    summary = await _sync(_service(repo, comments=comments, media=FakeMedia(errors={"L": error})))

    assert summary.truncated
    assert summary.metadata_failed == 1
    assert comments.calls == ["A"]  # stopped at L, Z left for the next pass
    row = _row(repo, "L")
    assert row.is_monitored and row.metadata_error is MetadataFetchError.RATE_LIMITED


@pytest.mark.parametrize("error", list(MetadataFetchError))
async def test_a_failed_row_is_not_retried_before_its_wait_is_over(
    error: MetadataFetchError,
) -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    repo.record_media_metadata_failure(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="L",
        error=error,
        attempted_at=NOW,
    )
    wait = METADATA_RETRY_AFTER[error]
    media = FakeMedia({"L": _summary("L", NOW - timedelta(days=1))})
    comments = FakeComments()
    service = _service(repo, comments=comments, media=media)

    early = await _sync(service, NOW + wait - timedelta(seconds=1))
    assert media.calls == []
    assert early.metadata_deferred == 1
    assert comments.calls == ["L"]  # comments still synced while the date is unknown
    assert _ledger(repo, NOW + wait - timedelta(seconds=1)) == 1  # comments only

    due = await _sync(service, NOW + wait)
    assert media.calls == ["L"]
    assert due.metadata_backfilled == 1
    assert _row(repo, "L").metadata_error is None


async def test_a_failure_never_overwrites_stored_metadata() -> None:
    """Only rows still missing metadata are ever read again, so a complete row cannot be
    damaged by a later failure: it is never asked for again."""
    repo = MemoryInboxRepository()
    _monitor(repo, "R", NOW - timedelta(days=1))
    media = FakeMedia(errors={"R": MediaReadError("x", http_status=500)})

    await _sync(_service(repo, media=media))

    assert media.calls == []
    row = _row(repo, "R")
    assert row.caption == "c" and row.metadata_error is None


async def test_an_auth_failure_on_a_metadata_read_degrades_and_touches_no_row() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    degrader = Degrader()
    expired_token = MediaReadError("x", http_status=401, platform_code=190)

    with pytest.raises(CommentsAuthExpired):
        await _sync(_service(repo, media=FakeMedia(errors={"L": expired_token}), degrader=degrader))

    assert degrader.calls == 1
    row = _row(repo, "L")
    assert row.is_monitored and row.metadata_error is None and row.metadata_attempted_at is None


async def test_a_metadata_read_only_counts_as_a_call_when_it_is_made() -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)
    repo.record_media_metadata_failure(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="L",
        error=MetadataFetchError.PERMISSION,
        attempted_at=NOW,
    )
    media = FakeMedia()

    await _sync(_service(repo, media=media), NOW + timedelta(hours=1))

    assert media.calls == []
    assert _ledger(repo, NOW + timedelta(hours=1)) == 1  # the comments call only


# --- timeouts on the metadata read only (accepted 2026-10-09) ---------------------------


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.ConnectError("connection refused"),
    ],
)
async def test_a_network_failure_on_a_metadata_read_is_transient_and_the_pass_goes_on(
    error: Exception,
) -> None:
    repo = MemoryInboxRepository()
    _monitor(repo, "A", NOW - timedelta(days=1))
    _monitor(repo, "L", None)
    _monitor(repo, "Z", NOW - timedelta(days=1))
    comments = FakeComments({"L": [_comment("c1")]})

    summary = await _sync(_service(repo, comments=comments, media=FakeMedia(errors={"L": error})))

    assert not summary.truncated
    assert summary.metadata_failed == 1
    assert sorted(comments.calls) == ["A", "L", "Z"]  # the other media still synced
    row = _row(repo, "L")
    assert row.is_monitored
    assert row.metadata_error is MetadataFetchError.TRANSIENT
    assert row.metadata_attempted_at == NOW and row.metadata_fetched_at is None


async def test_a_network_failure_on_the_comments_path_still_fails_the_pass() -> None:
    """Unchanged behaviour: only the metadata read treats a timeout as transient."""
    repo = MemoryInboxRepository()
    _monitor(repo, "A", NOW - timedelta(days=1))
    comments = FakeComments(errors={"A": httpx.ReadTimeout("read timed out")})

    with pytest.raises(httpx.ReadTimeout):
        await _sync(_service(repo, comments=comments))


async def test_known_limitation_an_unresolved_legacy_row_keeps_costing_comment_calls() -> None:
    """Accepted 2026-10-09 and documented in `InboxService.sync_comments`: while a legacy
    row's metadata read keeps failing, its date stays unknown and its comments keep being
    synced — even when Meta would say it is long expired. Pinned so a change to this
    behaviour is a deliberate decision, not an accident."""
    repo = MemoryInboxRepository()
    _monitor(repo, "L", None)  # in reality published 60 days ago
    media = FakeMedia(errors={"L": MediaReadError("x", http_status=500)})
    comments = FakeComments()
    service = _service(repo, comments=comments, media=media)

    first = await _sync(service, NOW)
    second = await _sync(service, NOW + timedelta(minutes=5))  # still inside the 15 min wait

    assert comments.calls == ["L", "L"]
    assert media.calls == ["L"]  # the metadata read itself is not repeated
    assert first.metadata_failed == 1 and second.metadata_deferred == 1
    assert _row(repo, "L").state(NOW) is MonitoringState.ACTIVE
