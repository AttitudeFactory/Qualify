"""End-to-end proof of sentiment over owned-content Instagram comments.

Runs fully offline against a stub SentimentProvider: no weights, no network,
no HF cache. The one test that exercises the real robertuito checkpoint is
marked `integration`, matching this package's existing convention.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qualify_models.providers import SentimentProvider
from qualify_models.social.ig_comments import (
    OWNED_COMMENTS_PIPELINE_VERSION,
    CommentSentimentSummary,
    InstagramComment,
    analyze_comment,
    analyze_comments,
    parse_comments_payload,
)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_ig_comments.json"


class StubSentimentProvider:
    """Deterministic keyword classifier standing in for robertuito.

    Implements the SentimentProvider Protocol. Exists so the pipeline around
    the model can be proven without the model — it is NOT a sentiment model and
    its labels carry no evaluative meaning.
    """

    model_id = "stub/deterministic-keyword-classifier"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def classify(self, text: str) -> tuple[str, float]:
        self.seen.append(text)
        lowered = text.lower()
        if any(w in lowered for w in ("encanta", "superó", "sí, envían")):
            return "POS", 0.95
        if any(w in lowered for w in ("esperando", "pésima", "no vuelvo")):
            return "NEG", 0.91
        return "NEU", 0.72


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_is_labelled_synthetic() -> None:
    """Fixture honesty is enforced, not merely intended.

    If someone swaps in real captured payloads they must consciously remove
    this marker, which is the moment to think about whether real user comments
    belong in a git repo.
    """
    payload = _load_fixture()
    assert payload["_fixture_kind"] == "SYNTHETIC"
    assert "NOT REAL INSTAGRAM DATA" in payload["_warning"]
    assert payload["_provisional_shape"]


def test_stub_satisfies_the_provider_protocol() -> None:
    provider: SentimentProvider = StubSentimentProvider()
    label, score = provider.classify("hola")
    assert label in {"POS", "NEG", "NEU"}
    assert 0.0 <= score <= 1.0


def test_parse_payload_yields_typed_comments() -> None:
    comments = parse_comments_payload(_load_fixture())
    assert len(comments) == 7
    assert all(isinstance(c, InstagramComment) for c in comments)
    assert comments[0].id == "synthetic_comment_0001"
    assert comments[3].parent_id == "synthetic_comment_0003"


def test_parse_payload_rejects_malformed_envelope() -> None:
    with pytest.raises(ValueError):
        parse_comments_payload({"data": "not a list"})


def test_parse_payload_tolerates_unknown_fields() -> None:
    """The real edge returns more than polarity needs; D1 owns the full contract."""
    comments = parse_comments_payload(
        {"data": [{"id": "c1", "text": "hola", "some_future_field": 123}]}
    )
    assert comments[0].id == "c1"


def test_single_comment_carries_provenance() -> None:
    """Every derived signal traces to the fragment and checkpoint it came from."""
    provider = StubSentimentProvider()
    comment = InstagramComment(id="synthetic_comment_0001", text="Me encanta este producto")
    result = analyze_comment(comment, provider=provider)

    assert result.source_id == "synthetic_comment_0001"
    assert result.detector_version == "robertuito-sentiment-v1"
    assert result.pipeline_version == OWNED_COMMENTS_PIPELINE_VERSION
    assert result.model_id == "stub/deterministic-keyword-classifier"


def test_end_to_end_over_the_synthetic_payload() -> None:
    """The whole point of D2: payload in, attributed polarity roll-up out."""
    provider = StubSentimentProvider()
    comments = parse_comments_payload(_load_fixture())
    summary = analyze_comments(comments, media_id="synthetic_media_1", provider=provider)

    assert isinstance(summary, CommentSentimentSummary)
    assert summary.media_id == "synthetic_media_1"
    assert summary.total_comments == 7
    assert summary.analyzed_comments == 5
    assert summary.skipped_empty == 2
    assert summary.label_counts == {"POS": 2, "NEG": 2, "NEU": 1}
    assert summary.net_sentiment == pytest.approx(0.0)
    assert summary.negative_share == pytest.approx(0.4)


def test_empty_and_whitespace_comments_are_skipped_not_classified() -> None:
    """Classifying empty text would manufacture a label from nothing."""
    provider = StubSentimentProvider()
    comments = parse_comments_payload(_load_fixture())
    analyze_comments(comments, provider=provider)

    assert all(text.strip() for text in provider.seen)
    assert len(provider.seen) == 5


def test_counts_reconcile_with_the_total() -> None:
    provider = StubSentimentProvider()
    comments = parse_comments_payload(_load_fixture())
    summary = analyze_comments(comments, provider=provider)

    assert summary.analyzed_comments + summary.skipped_empty == summary.total_comments
    assert sum(summary.label_counts.values()) == summary.analyzed_comments
    assert len(summary.results) == summary.analyzed_comments


def test_all_negative_payload_reports_minus_one() -> None:
    provider = StubSentimentProvider()
    comments = [
        InstagramComment(id="c1", text="Pésima atención"),
        InstagramComment(id="c2", text="no vuelvo a comprar"),
    ]
    summary = analyze_comments(comments, provider=provider)

    assert summary.net_sentiment == pytest.approx(-1.0)
    assert summary.negative_share == pytest.approx(1.0)


def test_empty_comment_list_yields_no_net_sentiment() -> None:
    """No comments is not neutral sentiment — it is the absence of a measurement."""
    summary = analyze_comments([], provider=StubSentimentProvider())

    assert summary.analyzed_comments == 0
    assert summary.net_sentiment is None
    assert summary.negative_share is None


@pytest.mark.integration
def test_end_to_end_against_real_robertuito() -> None:
    """Same path with the real checkpoint. Needs weights, so marked integration.

    Asserts only that labels are in-vocabulary and provenance is populated —
    NOT that the labels are correct. Label accuracy is a golden-set question
    and the golden set has 1 item.
    """
    comments = parse_comments_payload(_load_fixture())
    summary = analyze_comments(comments, media_id="synthetic_media_1")

    assert summary.analyzed_comments == 5
    assert set(summary.label_counts).issubset({"POS", "NEG", "NEU"})
    assert all(r.model_id == "pysentimiento/robertuito-sentiment-analysis" for r in summary.results)
    assert all(0.0 <= r.score <= 1.0 for r in summary.results)
