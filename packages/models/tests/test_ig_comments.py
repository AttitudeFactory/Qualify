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
    COMMENT_LENGTH_BUCKETS,
    OWNED_COMMENTS_PIPELINE_VERSION,
    CommentSentimentSummary,
    InstagramComment,
    analyze_comment,
    analyze_comments,
    analyze_text,
    parse_comments_payload,
    stratify_by_length,
)

# The fixture lives with the contract it instantiates (R11a), not here. This test is the
# CONSUMER, so reaching toward `packages/shared` is the permitted direction —
# `qualify_models` depends on `qualify_shared`, never the reverse. Keeping the fixture here
# and having the contract's own conformance test reach in would invert that.
FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "shared"
    / "tests"
    / "fixtures"
    / "synthetic_ig_comments.json"
)


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


def test_analyze_text_is_the_primitive_analyze_comment_wraps() -> None:
    """QUA-21: the real service calls this directly against `Message.text` +
    `external_message_id` — never a reconstructed `IGComment`."""
    provider = StubSentimentProvider()
    result = analyze_text(
        "Me encanta este producto", source_id="real_message_id_123", provider=provider
    )

    assert result.source_id == "real_message_id_123"
    assert result.label in {"POS", "NEG", "NEU"}


def test_analyze_comment_delegates_to_analyze_text() -> None:
    provider = StubSentimentProvider()
    comment = InstagramComment(id="c1", text="Pésima atención")
    via_comment = analyze_comment(comment, provider=provider)
    via_text = analyze_text("Pésima atención", source_id="c1", provider=StubSentimentProvider())

    assert via_comment.source_id == via_text.source_id == "c1"
    assert via_comment.label == via_text.label


def test_sentiment_result_carries_model_revision_field() -> None:
    """QUA-21: the field exists and defaults to None — LocalRobertuitoSentimentProvider
    does not pin a `revision=`, so no real value can be recorded without inventing one."""
    provider = StubSentimentProvider()
    result = analyze_text("hola", source_id="c1", provider=provider)

    assert result.model_revision is None


def test_stratify_by_length_buckets_by_documented_boundaries() -> None:
    provider = StubSentimentProvider()
    short_text = "hola"  # len 4, well under the 39-char "short" ceiling
    medium_text = "a" * 80  # inside 40-120
    long_text = "a" * 200  # over 120

    pairs = [
        (short_text, analyze_text(short_text, source_id="s1", provider=provider)),
        (medium_text, analyze_text(medium_text, source_id="m1", provider=provider)),
        (long_text, analyze_text(long_text, source_id="l1", provider=provider)),
    ]
    buckets = stratify_by_length(pairs)

    assert set(buckets) == {name for name, _, _ in COMMENT_LENGTH_BUCKETS}
    assert sum(sum(counts.values()) for counts in buckets.values()) == 3
    assert sum(buckets["short"].values()) == 1
    assert sum(buckets["medium"].values()) == 1
    assert sum(buckets["long"].values()) == 1


def test_stratify_by_length_boundary_exact_39_is_short_40_is_medium() -> None:
    """Pins the exact edge the boundaries claim, not just 'somewhere in the middle'."""
    provider = StubSentimentProvider()
    at_39 = "a" * 39
    at_40 = "a" * 40

    buckets = stratify_by_length(
        [
            (at_39, analyze_text(at_39, source_id="x1", provider=provider)),
            (at_40, analyze_text(at_40, source_id="x2", provider=provider)),
        ]
    )

    assert sum(buckets["short"].values()) == 1
    assert sum(buckets["medium"].values()) == 1


def test_analyze_comments_summary_includes_length_stratified() -> None:
    provider = StubSentimentProvider()
    comments = parse_comments_payload(_load_fixture())
    summary = analyze_comments(comments, provider=provider)

    assert sum(sum(counts.values()) for counts in summary.length_stratified.values()) == (
        summary.analyzed_comments
    )


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
