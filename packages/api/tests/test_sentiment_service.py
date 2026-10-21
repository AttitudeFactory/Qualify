"""Offline tests for `SentimentService.analyze_pending_comments` (QUA-21) — no DB, no
model weights. Mirrors `test_inbox_service.py`'s fake-repository style.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.sentiment import service as service_module
from qualify_api.sentiment.repository import (
    SENTIMENT_FILTER_PENDING,
    AnalysisVersion,
    MemorySentimentRepository,
    ReelListCursor,
    ReelSummary,
)
from qualify_api.sentiment.service import SentimentModelUnavailable, SentimentService

TENANT_ID = uuid4()
CONNECTION_ID = uuid4()

VERSION = AnalysisVersion(
    detector_version="d1", pipeline_version="p1", model_id="m1", model_revision=None
)


class StubProvider:
    model_id = "stub/deterministic"

    def classify(self, text: str) -> tuple[str, float]:
        return ("NEG", 0.9) if "mal" in text.lower() else ("POS", 0.9)


def _service() -> tuple[SentimentService, MemorySentimentRepository]:
    repo = MemorySentimentRepository()
    return SentimentService(repository=repo, version=VERSION, provider=StubProvider()), repo


def test_analyzes_a_pending_comment_and_persists_it() -> None:
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(), connection_id=CONNECTION_ID, source_id="c1", text="me encanta"
    )

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.comments_checked == 1
    assert summary.new_results == 1
    assert summary.skipped_empty == 0


def test_whitespace_only_comment_is_skipped_not_classified() -> None:
    """QUA-21 AC5, restriction 1: never manufacture a label from empty text."""
    service, repo = _service()
    repo.seed_message(message_id=uuid4(), connection_id=CONNECTION_ID, source_id="c1", text="   ")

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.comments_checked == 1
    assert summary.new_results == 0
    assert summary.skipped_empty == 1


def test_none_text_never_reaches_the_service_at_all() -> None:
    """The repository excludes `text=None` from `list_pending_for_analysis` — this pins
    that the service never sees it, let alone calls `.strip()` on it."""
    service, repo = _service()
    repo.seed_message(message_id=uuid4(), connection_id=CONNECTION_ID, source_id="c1", text=None)

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.comments_checked == 0


def test_a_soft_deleted_comment_never_reaches_the_service_either() -> None:
    """QUA-101: a comment Meta no longer returns (`deleted_at` set by
    `InboxRepository.reconcile_media_comments`) is excluded from
    `list_pending_for_analysis` the same way a `None` text already is — no point
    spending analysis compute on a comment that no longer exists."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="me encanta",
        deleted_at=datetime.now(UTC),
    )

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.comments_checked == 0


def test_already_analyzed_comment_is_not_reanalyzed() -> None:
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(), connection_id=CONNECTION_ID, source_id="c1", text="me encanta"
    )
    first = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    second = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert first.new_results == 1
    assert second.comments_checked == 0


def test_a_different_connection_is_isolated() -> None:
    service, repo = _service()
    other_connection = uuid4()
    repo.seed_message(
        message_id=uuid4(), connection_id=other_connection, source_id="c1", text="me encanta"
    )

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.comments_checked == 0


# --- list_reel_summaries / global_sentiment_summary / list_comments_for_thread (QUA-93) --


def test_reel_summary_shows_unanalyzed_as_not_analyzed_never_neu() -> None:
    """The requirement that survives from QUA-92 into QUA-93: a comment with no
    `comment_sentiment_results` row counts as `not_analyzed`, never `neutral`."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="?",
        external_thread_id="media-1",
    )

    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.total == 1
    assert summary.not_analyzed == 1
    assert summary.positive == summary.neutral == summary.negative == 0


def test_reel_summary_counts_by_label_after_analysis() -> None:
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="me encanta",
        external_thread_id="media-1",
    )
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c2",
        text="que mal",
        external_thread_id="media-1",
    )
    service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.total == 2
    assert summary.positive == 1
    assert summary.negative == 1
    assert summary.not_analyzed == 0


def test_reel_summary_groups_by_thread_not_by_connection() -> None:
    """The whole point of QUA-93: one row per Reel, not one flat pile of comments."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="a",
        external_thread_id="media-1",
    )
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c2",
        text="b",
        external_thread_id="media-2",
    )

    summaries = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert len(summaries) == 2
    assert {s.external_thread_id for s in summaries} == {"media-1", "media-2"}
    assert all(s.total == 1 for s in summaries)


def test_reel_summary_paginates_by_cursor_never_offset() -> None:
    service, repo = _service()
    for i in range(5):
        repo.seed_message(
            message_id=uuid4(),
            connection_id=CONNECTION_ID,
            source_id=f"c{i}",
            text="x",
            external_thread_id=f"media-{i}",
            posted_at=datetime(2026, 8, 20, tzinfo=UTC) - timedelta(minutes=i),
        )

    page1 = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID, limit=2)
    assert len(page1) == 2
    cursor = ReelListCursor(
        last_message_at=page1[-1].last_message_at, thread_id=page1[-1].thread_id
    )
    page2 = service.list_reel_summaries(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, cursor=cursor, limit=2
    )
    assert len(page2) == 2
    assert {s.thread_id for s in page1}.isdisjoint({s.thread_id for s in page2})


def test_reel_summary_isolated_by_connection() -> None:
    service, repo = _service()
    other_connection = uuid4()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=other_connection,
        source_id="c1",
        text="x",
        external_thread_id="media-1",
    )

    summaries = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summaries == ()


# --- monitored_media decoration, never a filter (QUA-94) -------------------------------


def test_reel_summary_reports_is_monitored_true_for_an_actively_monitored_reel() -> None:
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="a",
        external_thread_id="media-1",
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=True
    )

    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.is_monitored is True


def test_desmonitored_reel_keeps_its_history_flagged_not_monitored() -> None:
    """The QUA-94 rule end to end: turning monitoring off never hides or drops a Reel's
    comment history — `list_reel_summaries` still returns it, just decorated
    `is_monitored=False`."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="a",
        external_thread_id="media-1",
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=True
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=False
    )

    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.is_monitored is False
    assert summary.total == 1  # the history is still there, not filtered out


def test_reel_with_no_monitored_media_row_defaults_is_monitored_false() -> None:
    """A thread can exist without ever having a `monitored_media` row (e.g. seeded
    directly in a test, or a pre-QUA-94 legacy row) — the absence must read as "not
    currently monitored", the same default the Postgres `COALESCE(mm.is_monitored,
    false)` produces."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="a",
        external_thread_id="media-1",
    )

    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.is_monitored is False


def test_remonitoring_a_reel_flips_is_monitored_back_without_duplicating_history() -> None:
    """Re-monitoring the same `external_media_id` is a toggle (UPDATE), never a second
    row — `list_reel_summaries` must keep returning exactly ONE summary for the Reel,
    with its full original comment count, now flagged monitored again."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="a",
        external_thread_id="media-1",
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=True
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=False
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=True
    )

    summaries = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert len(summaries) == 1
    assert summaries[0].is_monitored is True
    assert summaries[0].total == 1


def test_global_summary_totals_across_all_reels() -> None:
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="me encanta",
        external_thread_id="media-1",
    )
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c2",
        text="   ",  # whitespace-only: analyze_pending_comments skips it, stays not_analyzed
        external_thread_id="media-2",
    )
    service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    summary = service.global_sentiment_summary(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.total == 2
    assert summary.positive == 1
    assert summary.not_analyzed == 1


def test_global_summary_keeps_counting_a_desmonitored_reels_comments() -> None:
    """QUA-94 semantics pin: `global_sentiment_summary` is explicitly NOT filtered by
    `monitored_media.is_monitored` — see its docstring. This test locks that decision
    in so a future change cannot silently narrow the widget to monitored-only without
    a test failing to announce it."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="me encanta",
        external_thread_id="media-1",
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=False
    )

    service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    summary = service.global_sentiment_summary(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.total == 1
    assert summary.positive == 1


def test_pending_analysis_still_offers_a_desmonitored_reels_unanalyzed_comments() -> None:
    """QUA-94 product decision: desmonitorear stops future ingestion, it does not make
    already-synced comments un-analyzable. `analyze_pending_comments` must still pick
    up an unanalyzed comment that belongs to a Reel with `is_monitored=False`."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="me encanta",
        external_thread_id="media-1",
    )
    repo.seed_monitored_media(
        connection_id=CONNECTION_ID, external_media_id="media-1", is_monitored=False
    )

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.comments_checked == 1
    assert summary.new_results == 1


def test_comments_for_thread_scoped_to_one_reel() -> None:
    service, repo = _service()
    target = uuid4()
    repo.seed_message(
        message_id=target,
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="a",
        external_thread_id="media-1",
    )
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c2",
        text="b",
        external_thread_id="media-2",
    )
    (media_1_summary,) = [
        s
        for s in service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
        if s.external_thread_id == "media-1"
    ]

    comments = service.list_comments_for_thread(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, thread_id=media_1_summary.thread_id
    )

    assert [c.message_id for c in comments] == [target]


def test_comments_for_thread_filters_by_sentiment() -> None:
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="me encanta",
        external_thread_id="media-1",
    )
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c2",
        text="   ",  # whitespace-only: skipped, stays pending forever
        external_thread_id="media-1",
    )
    service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    pending = service.list_comments_for_thread(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        thread_id=summary.thread_id,
        sentiment_filter=SENTIMENT_FILTER_PENDING,
    )
    positive = service.list_comments_for_thread(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        thread_id=summary.thread_id,
        sentiment_filter="POS",
    )

    assert len(pending) == 1
    assert pending[0].label is None
    assert len(positive) == 1
    assert positive[0].label == "POS"


def test_comments_for_thread_search_by_text() -> None:
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="precio especial",
        external_thread_id="media-1",
    )
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c2",
        text="saludos",
        external_thread_id="media-1",
    )
    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    matches = service.list_comments_for_thread(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        thread_id=summary.thread_id,
        search="precio",
    )

    assert len(matches) == 1
    assert "precio" in matches[0].text


def test_comments_for_thread_search_is_accent_and_case_insensitive() -> None:
    """Bug reported after QUA-93 shipped: searching "llego" (no accent) must still match
    "llegó" (mobile keyboards routinely drop accents), and case must not matter either
    direction — a search term or the stored text can carry either."""
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c1",
        text="El producto llegó tarde y además no cumplió con lo que prometía.",
        external_thread_id="media-1",
    )
    repo.seed_message(
        message_id=uuid4(),
        connection_id=CONNECTION_ID,
        source_id="c2",
        text="saludos",
        external_thread_id="media-1",
    )
    (summary,) = service.list_reel_summaries(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    no_accent = service.list_comments_for_thread(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        thread_id=summary.thread_id,
        search="llego tarde",  # no accent, lowercase
    )
    upper_with_accent = service.list_comments_for_thread(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        thread_id=summary.thread_id,
        search="LLEGÓ",  # accent, uppercase
    )

    assert len(no_accent) == 1
    assert "llegó" in no_accent[0].text
    assert len(upper_with_accent) == 1
    assert upper_with_accent[0].message_id == no_accent[0].message_id


def test_reel_summary_domain_object_has_only_scalar_roll_up_fields() -> None:
    """QUA-93 scale invariant, domain layer: `ReelSummary` (what `list_reel_summaries`
    returns) must stay a pure per-Reel roll-up — no field can hold a list of comments,
    which is exactly what would let the main view accidentally materialize more than one
    Reel's comments at once. A whitelist, not a substring scan: a newly added field
    forces a conscious look here rather than silently passing."""
    fields = {f.name: f.type for f in dataclasses.fields(ReelSummary)}
    assert fields == {
        "thread_id": "UUID",
        "external_thread_id": "str",
        "last_message_at": "datetime",
        "total": "int",
        "positive": "int",
        "neutral": "int",
        "negative": "int",
        "not_analyzed": "int",
        "is_monitored": "bool",
        # QUA-149: the media's own persisted metadata — scalars about the Reel, never
        # comment content.
        "media_posted_at": "datetime | None",
        "caption": "str | None",
        "permalink": "str | None",
        # m-24789644 (B2): the media's surface and format — scalars about the media.
        "media_product_type": "str | None",
        "media_type": "str | None",
    }


# --- B8: the default (local) model's runtime may be absent — production ships without it


def test_default_provider_without_its_runtime_refuses_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No injected provider = the local robertuito model, which needs the `ml` group.
    Without it the pass refuses up front — nothing is read, nothing half-written."""
    monkeypatch.setattr(service_module, "local_model_available", lambda: False)
    repo = MemorySentimentRepository()
    repo.seed_message(
        message_id=uuid4(), connection_id=CONNECTION_ID, source_id="c1", text="me encanta"
    )
    service = SentimentService(repository=repo, version=VERSION)

    with pytest.raises(SentimentModelUnavailable):
        service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    still_pending = repo.list_pending_for_analysis(
        tenant_id=TENANT_ID, connection_id=CONNECTION_ID, version=VERSION
    )
    assert len(still_pending) == 1


def test_an_injected_provider_does_not_need_the_local_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module, "local_model_available", lambda: False)
    service, repo = _service()
    repo.seed_message(
        message_id=uuid4(), connection_id=CONNECTION_ID, source_id="c1", text="me encanta"
    )

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert summary.new_results == 1
