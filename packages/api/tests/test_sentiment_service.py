"""Offline tests for `SentimentService.analyze_pending_comments` (QUA-21) — no DB, no
model weights. Mirrors `test_inbox_service.py`'s fake-repository style.
"""

from __future__ import annotations

from uuid import uuid4

from qualify_api.sentiment.repository import AnalysisVersion, MemorySentimentRepository
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
