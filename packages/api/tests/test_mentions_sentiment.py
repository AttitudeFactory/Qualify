"""Offline tests for `MentionSentimentService.analyze_pending_mentions` (QUA-49) — no DB,
no model weights. Mirrors `test_sentiment_service.py`'s fake-provider style exactly, over
`mentions/repository.py`'s in-memory implementation instead of `sentiment/repository.py`'s
— proving the reuse `mentions/sentiment.py`'s module docstring claims (same
`analyze_text`/`AnalysisVersion` machinery) actually works end to end for a mention.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from qualify_api.mentions.repository import (
    ENRICHMENT_OK,
    MAX_SENTIMENT_ATTEMPTS,
    SENTIMENT_ERROR,
    SENTIMENT_NO_TEXT,
    SENTIMENT_PENDING,
    MemoryMentionsRepository,
    MentionQuery,
    NewMention,
)
from qualify_api.mentions.sentiment import MentionSentimentService
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.sentiment.service import SentimentModelUnavailable

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


# --------------------------------------------------------------------------------------
# QUA-152 — automatic analysis: bounded retries, environment vs mention failures
# --------------------------------------------------------------------------------------


class ModelBlewUp(RuntimeError):
    pass


class FailingOnProvider:
    """Raises on any text containing `poison`; classifies everything else."""

    model_id = "stub/failing"

    def __init__(self, exc: Exception | None = None) -> None:
        self.calls: list[str] = []
        self._exc = exc or ModelBlewUp("secret user text must never be stored")

    def classify(self, text: str) -> tuple[str, float]:
        self.calls.append(text)
        if "poison" in text:
            raise self._exc
        return ("NEU", 0.7)


def _states(repo: MemoryMentionsRepository) -> dict[UUID, str]:
    page = repo.list_mentions_page(
        tenant_id=TENANT_ID, version=VERSION, query=MentionQuery(), page=1
    )
    return {r.id: r.sentiment_state for r in page.rows}


def test_one_failing_mention_is_recorded_and_the_pass_continues() -> None:
    repo = MemoryMentionsRepository()
    provider = FailingOnProvider()
    service = MentionSentimentService(repository=repo, version=VERSION, provider=provider)
    bad, _ = repo.upsert_mention(_mention(text="poison"))
    good, _ = repo.upsert_mention(_mention(text="todo bien"))

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert (summary.mentions_checked, summary.new_results, summary.failed) == (2, 1, 1)
    assert _states(repo) == {bad: SENTIMENT_PENDING, good: "NEU"}


def test_retries_are_bounded_and_an_exhausted_mention_is_error() -> None:
    repo = MemoryMentionsRepository()
    provider = FailingOnProvider()
    service = MentionSentimentService(repository=repo, version=VERSION, provider=provider)
    bad, _ = repo.upsert_mention(_mention(text="poison"))

    for _ in range(MAX_SENTIMENT_ATTEMPTS + 2):
        service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert provider.calls.count("poison") == MAX_SENTIMENT_ATTEMPTS
    assert _states(repo) == {bad: SENTIMENT_ERROR}
    assert repo.list_pending_for_analysis(tenant_id=TENANT_ID, version=VERSION) == ()
    counts = repo.list_mentions_page(
        tenant_id=TENANT_ID, version=VERSION, query=MentionQuery(), page=1
    ).counts
    assert (counts.error, counts.positive, counts.neutral, counts.negative) == (1, 0, 0, 0)


def test_a_new_analysis_version_starts_attempts_from_zero() -> None:
    repo = MemoryMentionsRepository()
    provider = FailingOnProvider()
    repo.upsert_mention(_mention(text="poison"))
    old = MentionSentimentService(repository=repo, version=VERSION, provider=provider)
    for _ in range(MAX_SENTIMENT_ATTEMPTS):
        old.analyze_pending_mentions(tenant_id=TENANT_ID)

    new_version = AnalysisVersion(
        detector_version="d2",
        pipeline_version="mentions-text-1.0.0",
        model_id="m1",
        model_revision=None,
    )

    assert len(repo.list_pending_for_analysis(tenant_id=TENANT_ID, version=new_version)) == 1


def test_an_environment_failure_records_nothing_and_stops_the_pass() -> None:
    repo = MemoryMentionsRepository()
    provider = FailingOnProvider(OSError("weights not found"))
    service = MentionSentimentService(repository=repo, version=VERSION, provider=provider)
    repo.upsert_mention(_mention(text="poison"))

    with pytest.raises(SentimentModelUnavailable):
        service.analyze_pending_mentions(tenant_id=TENANT_ID)

    # No attempt charged to the mention: it stays pending with all its retries.
    assert len(repo.list_pending_for_analysis(tenant_id=TENANT_ID, version=VERSION)) == 1


def test_the_default_model_missing_refuses_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_mention(text="hola"))
    monkeypatch.setattr("qualify_api.mentions.sentiment.local_model_available", lambda: False)
    service = MentionSentimentService(repository=repo, version=VERSION)  # default provider

    with pytest.raises(SentimentModelUnavailable):
        service.analyze_pending_mentions(tenant_id=TENANT_ID)


def test_analysis_can_target_one_mention() -> None:
    service, repo = _service()
    target, _ = repo.upsert_mention(_mention(text="me encanta"))
    other, _ = repo.upsert_mention(_mention(text="también"))

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID, mention_id=target)

    assert summary.new_results == 1
    assert _states(repo) == {target: "POS", other: SENTIMENT_PENDING}


def test_reanalysis_is_idempotent() -> None:
    service, repo = _service()
    mention_id, _ = repo.upsert_mention(_mention(text="me encanta"))

    first = service.analyze_pending_mentions(tenant_id=TENANT_ID, mention_id=mention_id)
    second = service.analyze_pending_mentions(tenant_id=TENANT_ID, mention_id=mention_id)

    assert (first.new_results, second.new_results, second.mentions_checked) == (1, 0, 0)


def test_no_text_is_never_sent_to_the_model() -> None:
    repo = MemoryMentionsRepository()
    provider = FailingOnProvider()
    service = MentionSentimentService(repository=repo, version=VERSION, provider=provider)
    blank, _ = repo.upsert_mention(_mention(caption="   "))

    service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert provider.calls == []
    assert _states(repo) == {blank: SENTIMENT_NO_TEXT}


# --------------------------------------------------------------------------------------
# QUA-152 D3 — a result belongs to the exact text it analyzed
# --------------------------------------------------------------------------------------


def _edit_text(repo: MemoryMentionsRepository, mention_id: UUID, text: str) -> None:
    from qualify_api.mentions.repository import MentionContent

    assert repo.refresh_content(
        tenant_id=TENANT_ID,
        mention_id=mention_id,
        content=MentionContent(
            caption=None,
            text=text,
            author_username=None,
            media_type=None,
            like_count=None,
            content_posted_at=None,
            permalink=None,
        ),
    )


def test_an_edited_text_is_analyzed_again_and_the_old_result_stops_counting() -> None:
    service, repo = _service()
    mention_id, _ = repo.upsert_mention(_mention(text="me encanta"))
    service.analyze_pending_mentions(tenant_id=TENANT_ID)
    assert _states(repo)[mention_id] == "POS"

    _edit_text(repo, mention_id, "ahora me parece mal")

    assert _states(repo)[mention_id] == SENTIMENT_PENDING  # the old POS no longer counts
    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)
    assert summary.new_results == 1
    assert _states(repo)[mention_id] == "NEG"


def test_a_result_computed_on_the_old_text_never_lands_on_the_new_one() -> None:
    _service_unused, repo = _service()
    mention_id, _ = repo.upsert_mention(_mention(text="me encanta"))
    (pending,) = repo.list_pending_for_analysis(tenant_id=TENANT_ID, version=VERSION)

    _edit_text(repo, mention_id, "ahora me parece mal")  # edited while "analyzing"
    landed = repo.record_sentiment_result(
        tenant_id=TENANT_ID,
        mention_id=mention_id,
        version=VERSION,
        label="POS",
        score=0.9,
        text_md5=pending.text_md5,
    )

    assert landed is False
    assert _states(repo)[mention_id] == SENTIMENT_PENDING


def test_an_unchanged_text_keeps_its_result_after_a_refresh() -> None:
    service, repo = _service()
    mention_id, _ = repo.upsert_mention(_mention(text="me encanta"))
    service.analyze_pending_mentions(tenant_id=TENANT_ID)

    _edit_text(repo, mention_id, "me encanta")  # a refresh that changed nothing

    assert _states(repo)[mention_id] == "POS"
    assert service.analyze_pending_mentions(tenant_id=TENANT_ID).mentions_checked == 0


def test_an_edited_text_starts_its_attempts_from_zero() -> None:
    repo = MemoryMentionsRepository()
    service = MentionSentimentService(
        repository=repo, version=VERSION, provider=FailingOnProvider()
    )
    mention_id, _ = repo.upsert_mention(_mention(text="poison"))
    for _ in range(MAX_SENTIMENT_ATTEMPTS):
        service.analyze_pending_mentions(tenant_id=TENANT_ID)
    assert _states(repo)[mention_id] == SENTIMENT_ERROR

    _edit_text(repo, mention_id, "texto corregido")

    assert _states(repo)[mention_id] == SENTIMENT_PENDING
    assert service.analyze_pending_mentions(tenant_id=TENANT_ID).new_results == 1


def test_recording_the_same_text_twice_never_duplicates_its_result() -> None:
    _service_unused, repo = _service()
    mention_id, _ = repo.upsert_mention(_mention(text="me encanta"))
    (pending,) = repo.list_pending_for_analysis(tenant_id=TENANT_ID, version=VERSION)

    first, second = (
        repo.record_sentiment_result(
            tenant_id=TENANT_ID,
            mention_id=mention_id,
            version=VERSION,
            label="POS",
            score=0.9,
            text_md5=pending.text_md5,
        )
        for _ in range(2)
    )

    assert (first, second) == (True, False)
    assert repo.list_pending_for_analysis(tenant_id=TENANT_ID, version=VERSION) == ()


def test_a_timeout_on_one_mention_is_recorded_and_the_pass_continues() -> None:
    repo = MemoryMentionsRepository()
    service = MentionSentimentService(
        repository=repo, version=VERSION, provider=FailingOnProvider(TimeoutError("slow"))
    )
    stuck, _ = repo.upsert_mention(_mention(text="poison"))
    fine, _ = repo.upsert_mention(_mention(text="todo bien"))

    summary = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert (summary.failed, summary.new_results) == (1, 1)  # not a model outage
    assert _states(repo)[fine] == "NEU"
    assert repo._failed_attempts(stuck, VERSION) == 1


def test_a_pass_can_be_bounded() -> None:
    service, repo = _service()
    for i in range(5):
        repo.upsert_mention(_mention(text=f"texto {i}"))

    first = service.analyze_pending_mentions(tenant_id=TENANT_ID, limit=2)
    rest = service.analyze_pending_mentions(tenant_id=TENANT_ID)

    assert (first.new_results, rest.new_results) == (2, 3)


def test_an_empty_comment_text_never_falls_back_to_the_caption() -> None:
    _service_unused, repo = _service()
    mention_id, _ = repo.upsert_mention(
        NewMention(
            tenant_id=TENANT_ID,
            connection_id=CONNECTION_ID,
            external_account_id="ig-user-1",
            media_id="media-x",
            comment_id="comment-x",
            caption="caption de la publicación",
            text="",
            author_username=None,
            media_type=None,
            like_count=None,
            content_posted_at=None,
            enrichment_status=ENRICHMENT_OK,
        )
    )

    (pending,) = repo.list_pending_for_analysis(tenant_id=TENANT_ID, version=VERSION)

    assert (pending.mention_id, pending.text) == (mention_id, "")
    assert _states(repo)[mention_id] == SENTIMENT_NO_TEXT
