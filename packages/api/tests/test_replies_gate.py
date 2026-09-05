"""QUA-22's cheap gate — pure, no fakes needed. Every failing condition is tested
independently, and the DM-shaped input is checked to name the real blocker (Advanced
Access), not a generic "wrong channel" message."""

from __future__ import annotations

from qualify_api.replies.gate import GateInput, evaluate_gate


def _input(**overrides: object) -> GateInput:
    base = dict(
        channel="comment",
        sentiment_label="POS",
        comment_text="qué lindo!",
        has_existing_draft=False,
    )
    base.update(overrides)
    return GateInput(**base)  # type: ignore[arg-type]


def test_comment_pos_nonempty_no_draft_passes() -> None:
    verdict = evaluate_gate(_input())
    assert verdict.passed is True
    assert "POS" in verdict.reason


def test_dm_channel_is_rejected_naming_advanced_access() -> None:
    verdict = evaluate_gate(_input(channel="dm"))
    assert verdict.passed is False
    assert "Advanced Access" in verdict.reason
    assert "QUA-20" in verdict.reason or "QUA-69" in verdict.reason


def test_existing_draft_is_rejected() -> None:
    verdict = evaluate_gate(_input(has_existing_draft=True))
    assert verdict.passed is False
    assert "already exists" in verdict.reason


def test_negative_sentiment_is_rejected() -> None:
    verdict = evaluate_gate(_input(sentiment_label="NEG"))
    assert verdict.passed is False


def test_neutral_sentiment_is_rejected() -> None:
    verdict = evaluate_gate(_input(sentiment_label="NEU"))
    assert verdict.passed is False


def test_empty_text_is_rejected() -> None:
    verdict = evaluate_gate(_input(comment_text=""))
    assert verdict.passed is False


def test_whitespace_only_text_is_rejected() -> None:
    verdict = evaluate_gate(_input(comment_text="   \n\t"))
    assert verdict.passed is False


def test_none_text_is_rejected() -> None:
    verdict = evaluate_gate(_input(comment_text=None))
    assert verdict.passed is False


def test_gate_never_raises() -> None:
    # Every branch above is independently sufficient — this asserts the function is
    # total: an input failing on MULTIPLE grounds still returns a verdict, not an
    # exception.
    verdict = evaluate_gate(
        GateInput(channel="dm", sentiment_label="NEG", comment_text=None, has_existing_draft=True)
    )
    assert verdict.passed is False
