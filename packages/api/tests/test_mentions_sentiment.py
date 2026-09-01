"""Offline tests for `MentionSentimentService.analyze_pending_mentions` (QUA-49) — no DB,
no model weights. Mirrors `test_sentiment_service.py`'s fake-provider style exactly, over
`mentions/repository.py`'s in-memory implementation instead of `sentiment/repository.py`'s
— proving the reuse `mentions/sentiment.py`'s module docstring claims (same
`analyze_text`/`AnalysisVersion` machinery) actually works end to end for a mention.
"""

from __future__ import annotations

from uuid import uuid4

from qualify_api.mentions.repository import ENRICHMENT_OK, MemoryMentionsRepository, NewMention
from qualify_api.mentions.sentiment import MentionSentimentService
from qualify_api.sentiment.repository import AnalysisVersion

TENANT_ID = uuid4()
CONNECTION_ID = uuid4()

VERSION = AnalysisVersion(
    detector_version="d1",
    pipeline_version="mentions-text-1.0.0",
    model_id="m1",
    model_revision=None,
)


class StubProvider:
    model_id = "stub/deterministic"

    def classify(self, text: str) -> tuple[str, float]:
        return ("NEG", 0.9) if "mal" in text.lower() else ("POS", 0.9)


def _mention(text: str | None = None, caption: str | None = None) -> NewMention:
    return NewMention(
        tenant_id=TENANT_ID,
        connection_id=CONNECTION_ID,
        external_account_id="ig-user-1",
        media_id=f"media-{uuid4()}",
        comment_id=None if caption is not None else f"comment-{uuid4()}",
        caption=caption,
        text=text,
        author_username="someone",
        media_type="IMAGE",
        like_count=1,
        content_posted_at=None,
        enrichment_status=ENRICHMENT_OK,
    )


def _service() -> tuple[MentionSentimentService, MemoryMentionsRepository]:
    repo = MemoryMentionsRepository()
    return MentionSentimentService(repository=repo, version=VERSION, provider=StubProvider()), repo


def test_analyzes_a_pending_mention_comment_text() -> None:
    service, repo = _service()
    repo.upsert_mention(_mention(text="me encanta el producto"))

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert summary.mentions_checked == 1
    assert summary.new_results == 1
    assert summary.skipped_empty == 0


def test_analyzes_a_pending_mention_caption_text() -> None:
    """A caption mention (no `comment_id`, text lives in `caption`) must be picked up
    identically to a comment mention — `list_pending_for_analysis` falls back to
    `caption` when `text` is `None`, and this proves the service does not special-case
    which field carried the words."""
    service, repo = _service()
    repo.upsert_mention(_mention(caption="excelente atención al cliente"))

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert summary.mentions_checked == 1
    assert summary.new_results == 1


def test_whitespace_only_text_is_skipped_not_classified() -> None:
    service, repo = _service()
    repo.upsert_mention(_mention(text="   "))

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert summary.mentions_checked == 1
    assert summary.new_results == 0
    assert summary.skipped_empty == 1


def test_mention_with_no_text_at_all_never_reaches_the_service() -> None:
    """An unenriched/failed-enrichment mention (both `text` and `caption` `None`) is
    excluded by the repository's own `list_pending_for_analysis` — this pins that the
    service never even sees it as a zero-checked pass."""
    service, repo = _service()
    repo.upsert_mention(_mention(text=None, caption=None))

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert summary.mentions_checked == 0


def test_analysis_is_idempotent_under_the_same_version() -> None:
    service, repo = _service()
    mention_id, _created = repo.upsert_mention(_mention(text="me encanta"))

    first = service.analyze_pending_mentions(tenant_id=TENANT_ID)
    second = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert first.new_results == 1
    # The second pass finds nothing pending: the mention is already analyzed under
    # VERSION, so it never reaches the classifier again.
    assert second.mentions_checked == 0
    assert second.new_results == 0
    records = repo.list_mentions(tenant_id=TENANT_ID, connection_id=None, version=VERSION)
    assert next(r for r in records if r.id == mention_id).sentiment_label == "POS"


def test_result_label_reflects_the_classifier() -> None:
    service, repo = _service()
    repo.upsert_mention(_mention(text="Que mal servicio, nunca vuelvo"))

    service.analyze_pending_mentions(tenant_id=TENANT_ID)

    records = repo.list_mentions(tenant_id=TENANT_ID, connection_id=None, version=VERSION)
    assert records[0].sentiment_label == "NEG"


def test_only_analyzes_the_requested_tenants_mentions() -> None:
    service, repo = _service()
    repo.upsert_mention(_mention(text="me encanta"))
    other_tenant = uuid4()
    other_mention = NewMention(
        tenant_id=other_tenant,
        connection_id=uuid4(),
        external_account_id="ig-user-2",
        media_id=f"media-{uuid4()}",
        comment_id=None,
        caption="hola",
        text=None,
        author_username=None,
        media_type=None,
        like_count=None,
        content_posted_at=None,
        enrichment_status=ENRICHMENT_OK,
    )
    repo.upsert_mention(other_mention)

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert summary.mentions_checked == 1
