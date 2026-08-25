"""Offline tests for `SentimentService.analyze_pending_comments` (QUA-21) — no DB, no
model weights. Mirrors `test_inbox_service.py`'s fake-repository style.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from qualify_api.sentiment.repository import (
    SENTIMENT_FILTER_PENDING,
    AnalysisVersion,
    MemorySentimentRepository,
    ReelListCursor,
)
from qualify_api.sentiment.service import SentimentService

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
