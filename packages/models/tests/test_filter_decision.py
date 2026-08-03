"""Tests for the F2 filter's decision rules (QUA-23, deliverable A).

Fully offline: pure arithmetic over the checkpoint's trained sigmoid constants,
no weights and no network.

These tests assert **mechanism**, never that a rule is correct. No rule here is
calibrated, so "correct" is not yet a property any of them can have.
"""

from __future__ import annotations

import pytest

from qualify_models.filter import DEFAULT_LABELS
from qualify_models.filter_decision import (
    BEST_MEASURED_COS_SIM,
    KNOWN_DISTRACTOR_LABELS,
    LEGACY_PROBABILITY_THRESHOLD,
    REJECTED_RULE_FORMS,
    SIGLIP2_LOGIT_BIAS,
    SIGLIP2_LOGIT_SCALE,
    UNCALIBRATED_LEGACY_RULE,
    ArgmaxRelevantLabelRule,
    CosineThresholdRule,
    FilterDecisionRule,
    ProbabilityThresholdRule,
    cosine_for_score,
    default_relevant_labels,
    score_for_cosine,
)

# Scores of the shape SigLIP actually produces: tiny, and not summing to 1.
REALISTIC_SCORES = [score_for_cosine(c) for c in (0.1034, 0.08, 0.07, 0.05, 0.03)]


# ---------------------------------------------------------------------------
# The sigmoid head
# ---------------------------------------------------------------------------


def test_sigmoid_and_its_inverse_round_trip() -> None:
    for cos in (0.0, 0.05, 0.1034, 0.2):
        assert cosine_for_score(score_for_cosine(cos)) == pytest.approx(cos, abs=1e-9)


def test_unrelated_pair_scores_near_zero_by_design() -> None:
    """The trained negative bias encodes a very low prior of match.

    This is correct behaviour for a pairwise-sigmoid-loss model, and it is exactly
    what a softmax-shaped threshold fails to account for.
    """
    assert score_for_cosine(0.0) == pytest.approx(5.2e-8, rel=0.05)


def test_scores_do_not_sum_to_one() -> None:
    """Per-label sigmoid, not softmax over candidates — the core misreading."""
    assert sum(REALISTIC_SCORES) < 0.01


def test_checkpoint_constants_are_pinned() -> None:
    """If the checkpoint changes, every calibration claim must be re-derived."""
    assert SIGLIP2_LOGIT_SCALE == pytest.approx(112.6689, abs=1e-3)
    assert SIGLIP2_LOGIT_BIAS == pytest.approx(-16.7717, abs=1e-3)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
def test_cosine_for_score_rejects_degenerate_probabilities(bad: float) -> None:
    with pytest.raises(ValueError):
        cosine_for_score(bad)


# ---------------------------------------------------------------------------
# The defect, as arithmetic
# ---------------------------------------------------------------------------


def test_legacy_threshold_demands_an_unreachable_cosine() -> None:
    """p=0.22 requires cos >= ~0.1376; the best measured real label is 0.1034."""
    required = UNCALIBRATED_LEGACY_RULE.required_cosine
    assert required == pytest.approx(0.1376, abs=1e-3)
    assert required > BEST_MEASURED_COS_SIM


def test_legacy_threshold_matches_a_softmax_uniform_baseline() -> None:
    """Evidence for how 0.22 was picked: 1/5 candidate labels is 0.20."""
    assert 1.0 / len(DEFAULT_LABELS) == pytest.approx(0.20)
    assert 0.20 < LEGACY_PROBABILITY_THRESHOLD < 0.25


def test_legacy_rule_discards_realistic_scores() -> None:
    """The defect itself: nothing realistic clears the bar."""
    decision = UNCALIBRATED_LEGACY_RULE.decide(list(DEFAULT_LABELS), REALISTIC_SCORES)
    assert decision.passed is False


# ---------------------------------------------------------------------------
# The default must not change silently
# ---------------------------------------------------------------------------


def test_the_default_rule_is_unchanged_and_named_uncalibrated() -> None:
    """Closing QUA-23 means changing this binding — deliberately, with data."""
    assert UNCALIBRATED_LEGACY_RULE.threshold == 0.22
    assert UNCALIBRATED_LEGACY_RULE.rule_id == "probability_threshold"
    assert UNCALIBRATED_LEGACY_RULE.calibrated is False


def test_no_rule_claims_to_be_calibrated() -> None:
    """No labelled data exists to calibrate any of them yet."""
    rules = [
        ProbabilityThresholdRule(threshold=0.22),
        CosineThresholdRule(min_cosine=0.09),
        ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"})),
    ]
    assert all(r.calibrated is False for r in rules)


def test_rules_satisfy_the_protocol() -> None:
    rules: list[FilterDecisionRule] = [
        ProbabilityThresholdRule(threshold=0.22),
        CosineThresholdRule(min_cosine=0.09),
        ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"})),
    ]
    for rule in rules:
        decision = rule.decide(list(DEFAULT_LABELS), REALISTIC_SCORES)
        assert isinstance(decision.passed, bool)
        assert decision.rule_id


# ---------------------------------------------------------------------------
# Decisions carry their own provenance
# ---------------------------------------------------------------------------


def test_decision_records_the_rule_and_its_parameters() -> None:
    decision = CosineThresholdRule(min_cosine=0.09).decide(list(DEFAULT_LABELS), REALISTIC_SCORES)
    assert decision.rule_id == "cosine_threshold"
    assert decision.rule_params == {"min_cosine": 0.09}
    assert decision.calibrated is False
    assert decision.top_label == DEFAULT_LABELS[0]


# ---------------------------------------------------------------------------
# Cosine-space threshold
# ---------------------------------------------------------------------------


def test_cosine_rule_passes_what_it_should_and_rejects_what_it_should() -> None:
    labels = list(DEFAULT_LABELS)
    assert CosineThresholdRule(min_cosine=0.09).decide(labels, REALISTIC_SCORES).passed is True
    assert CosineThresholdRule(min_cosine=0.12).decide(labels, REALISTIC_SCORES).passed is False


def test_cosine_rule_is_a_reparameterisation_of_the_probability_rule() -> None:
    """Same decision boundary, expressed in the space the similarities live in.

    This is the argument for the cosine form: not that it decides differently,
    but that its parameter is legible. 0.09 is visibly near the observed range;
    the equivalent probability is not.
    """
    labels = list(DEFAULT_LABELS)
    equivalent_probability = score_for_cosine(0.09)
    by_cosine = CosineThresholdRule(min_cosine=0.09).decide(labels, REALISTIC_SCORES)
    by_probability = ProbabilityThresholdRule(threshold=equivalent_probability).decide(
        labels, REALISTIC_SCORES
    )
    assert by_cosine.passed == by_probability.passed


def test_cosine_rule_survives_degenerate_scores() -> None:
    """0.0 and 1.0 would blow up the logit if not clamped."""
    labels = ["a", "b"]
    assert CosineThresholdRule(min_cosine=0.09).decide(labels, [0.0, 0.0]).passed is False
    assert CosineThresholdRule(min_cosine=0.09).decide(labels, [1.0, 0.0]).passed is True


# ---------------------------------------------------------------------------
# Argmax over partitioned labels — the threshold-free option
# ---------------------------------------------------------------------------


def test_argmax_rule_passes_when_the_winner_is_relevant() -> None:
    labels = ["brand logo", "generic scenery"]
    rule = ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"}))
    assert rule.decide(labels, [0.9, 0.1]).passed is True


def test_argmax_rule_rejects_when_the_winner_is_a_distractor() -> None:
    labels = ["brand logo", "generic scenery"]
    rule = ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"}))
    assert rule.decide(labels, [0.1, 0.9]).passed is False


def test_argmax_rule_is_immune_to_the_sigmoid_scale() -> None:
    """The defect that broke the threshold rule cannot touch this one.

    Absolute scores can be arbitrarily tiny — as SigLIP's genuinely are — and the
    decision is unchanged, because only the ranking is consulted.
    """
    labels = ["brand logo", "generic scenery"]
    rule = ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"}))
    tiny = [score_for_cosine(0.10), score_for_cosine(0.02)]
    assert rule.decide(labels, tiny).passed is True
    assert max(tiny) < LEGACY_PROBABILITY_THRESHOLD


def test_argmax_rule_has_no_free_numeric_parameter() -> None:
    """Its whole appeal: there is no constant available to mis-tune."""
    rule = ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"}))
    decision = rule.decide(["brand logo"], [0.5])
    assert not any(isinstance(v, (int, float)) for v in decision.rule_params.values())


def test_argmax_rule_reports_the_partition_it_used() -> None:
    """The partition is a design choice, so it must be auditable in the output."""
    labels = list(DEFAULT_LABELS)
    rule = ArgmaxRelevantLabelRule(relevant_labels=default_relevant_labels(labels))
    decision = rule.decide(labels, REALISTIC_SCORES)
    assert decision.rule_params["distractor_labels"] == ["generic scenery"]


def test_default_partition_treats_generic_scenery_as_the_distractor() -> None:
    relevant = default_relevant_labels(DEFAULT_LABELS)
    assert "generic scenery" not in relevant
    assert "brand logo" in relevant
    assert KNOWN_DISTRACTOR_LABELS == {"generic scenery"}


# ---------------------------------------------------------------------------
# Structurally rejected rule forms
# ---------------------------------------------------------------------------


def test_top_k_is_recorded_as_structurally_rejected() -> None:
    """Ruled out by reasoning, not measurement — and the reasoning is kept.

    Top-k selects k labels for every image, so it never rejects one and the
    discard rate is 0% by construction. Recorded as data so the option cannot be
    quietly re-proposed later.
    """
    names = {form.name for form in REJECTED_RULE_FORMS}
    assert "top_k_over_candidate_labels" in names
    top_k = next(f for f in REJECTED_RULE_FORMS if f.name == "top_k_over_candidate_labels")
    assert "never rejects an image" in top_k.reason


def test_every_rejected_form_explains_itself_and_cites_its_origin() -> None:
    for form in REJECTED_RULE_FORMS:
        assert form.reason.strip()
        assert form.proposed_in.strip()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_mismatched_labels_and_scores_raise() -> None:
    with pytest.raises(ValueError, match="same length"):
        UNCALIBRATED_LEGACY_RULE.decide(["a", "b"], [0.5])


def test_empty_input_does_not_pass() -> None:
    """No labels means no evidence, which must not read as a pass."""
    decision = UNCALIBRATED_LEGACY_RULE.decide([], [])
    assert decision.passed is False
    assert decision.top_label is None
