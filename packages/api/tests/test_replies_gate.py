"""The cheap gate — pure, no fakes needed. QUA-22's conditions (channel, text, no live
draft, POS) plus Fase B's (m-24789645): commercial intent under the CURRENT intent
version, and no public draft for a comment someone already chose to answer by DM. Every
failing condition is tested independently and every outcome carries a reason."""

from __future__ import annotations

from qualify_api.replies.gate import (
    ROUTE_COMMERCIAL,
    ROUTE_SENTIMENT,
    GateInput,
    IntentEvidence,
    evaluate_gate,
)
from qualify_api.sentiment.repository import AnalysisVersion

CURRENT = AnalysisVersion(
    detector_version="intent-claude-v2",
    pipeline_version="intent-pipeline-v1",
    model_id="claude-haiku-5-5",
    model_revision=None,
)
STALE = AnalysisVersion(
    detector_version="intent-claude-v1",
    pipeline_version="intent-pipeline-v1",
    model_id="claude-haiku-5-5",
    model_revision=None,
)


def _input(**overrides: object) -> GateInput:
    base: dict[str, object] = dict(
        channel="comment",
        sentiment_label="POS",
        comment_text="qué lindo!",
        has_live_draft=False,
        current_intent_version=CURRENT,
    )
    base.update(overrides)
    return GateInput(**base)  # type: ignore[arg-type]


def _commercial(version: AnalysisVersion = CURRENT, *, commercial: bool = True) -> IntentEvidence:
    return IntentEvidence(commercial_intent=commercial, version=version)


def test_comment_pos_nonempty_no_draft_passes() -> None:
    verdict = evaluate_gate(_input())
    assert verdict.passed is True
    assert "POS" in verdict.reason
    assert verdict.route == ROUTE_SENTIMENT


def test_commercial_neutral_comment_passes_on_the_commercial_route() -> None:
    verdict = evaluate_gate(
        _input(sentiment_label="NEU", comment_text="¿cuánto cuesta?", intent=_commercial())
    )
    assert verdict.passed is True
    assert verdict.route == ROUTE_COMMERCIAL
    assert "commercial intent under intent-claude-v2" in verdict.reason


def test_commercial_without_any_sentiment_row_passes() -> None:
    verdict = evaluate_gate(_input(sentiment_label="", intent=_commercial()))
    assert (verdict.passed, verdict.route) == (True, ROUTE_COMMERCIAL)


def test_pos_and_commercial_goes_to_the_grounded_route() -> None:
    """«¡Me encanta! ¿cuánto cuesta?» must not reach the ungrounded thank-you generator."""
    verdict = evaluate_gate(_input(intent=_commercial()))
    assert verdict.route == ROUTE_COMMERCIAL


def test_general_only_neutral_comment_fails() -> None:
    verdict = evaluate_gate(_input(sentiment_label="NEU", intent=_commercial(commercial=False)))
    assert verdict.passed is False
    assert verdict.route is None
    assert "no current commercial intent" in verdict.reason


def test_a_stale_intent_version_does_not_count() -> None:
    verdict = evaluate_gate(_input(sentiment_label="NEU", intent=_commercial(STALE)))
    assert verdict.passed is False
    assert "intent-claude-v1" in verdict.reason and "intent-claude-v2" in verdict.reason


def test_intent_is_ignored_when_the_service_has_no_intent_version() -> None:
    verdict = evaluate_gate(
        _input(sentiment_label="NEU", intent=_commercial(), current_intent_version=None)
    )
    assert verdict.passed is False


def test_a_stale_intent_on_a_pos_comment_still_passes_as_sentiment() -> None:
    verdict = evaluate_gate(_input(intent=_commercial(STALE)))
    assert (verdict.passed, verdict.route) == (True, ROUTE_SENTIMENT)


def test_dm_channel_is_rejected_naming_advanced_access() -> None:
    verdict = evaluate_gate(_input(channel="dm"))
    assert verdict.passed is False
    assert "Advanced Access" in verdict.reason
    assert "QUA-20" in verdict.reason or "QUA-69" in verdict.reason


def test_a_live_draft_is_rejected() -> None:
    verdict = evaluate_gate(_input(has_live_draft=True))
    assert verdict.passed is False
    assert "already exists" in verdict.reason


def test_a_commercial_comment_with_a_live_draft_is_rejected() -> None:
    verdict = evaluate_gate(_input(has_live_draft=True, intent=_commercial()))
    assert verdict.passed is False


def test_an_approved_dm_followup_blocks_a_public_draft() -> None:
    for sentiment in ("NEU", "POS"):
        verdict = evaluate_gate(
            _input(sentiment_label=sentiment, intent=_commercial(), followup_status="approved")
        )
        assert verdict.passed is False, sentiment
        assert "answered by DM" in verdict.reason


def test_an_open_or_discarded_followup_does_not_block() -> None:
    for status in ("open", "discarded", None):
        verdict = evaluate_gate(_input(intent=_commercial(), followup_status=status))
        assert verdict.passed is True, status


def test_negative_sentiment_is_rejected() -> None:
    verdict = evaluate_gate(_input(sentiment_label="NEG"))
    assert verdict.passed is False


def test_neutral_sentiment_is_rejected() -> None:
    verdict = evaluate_gate(_input(sentiment_label="NEU"))
    assert verdict.passed is False


def test_empty_text_is_rejected() -> None:
    verdict = evaluate_gate(_input(comment_text="", intent=_commercial()))
    assert verdict.passed is False
    assert "empty" in verdict.reason


def test_whitespace_only_text_is_rejected() -> None:
    verdict = evaluate_gate(_input(comment_text="   \n\t"))
    assert verdict.passed is False


def test_none_text_is_rejected() -> None:
    verdict = evaluate_gate(_input(comment_text=None))
    assert verdict.passed is False


def test_gate_never_raises_and_always_gives_a_reason() -> None:
    # An input failing on MULTIPLE grounds still returns a verdict, not an exception.
    verdict = evaluate_gate(
        GateInput(
            channel="dm",
            sentiment_label=None,
            comment_text=None,
            has_live_draft=True,
            intent=_commercial(STALE),
            current_intent_version=None,
            followup_status="approved",
        )
    )
    assert verdict.passed is False
    assert verdict.reason
