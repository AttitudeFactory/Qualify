"""Tests for the filter calibration machinery (QUA-23, deliverables B and C).

Fully offline. Every labelled set here is **synthetic on purpose and legitimately
so**: these tests exercise the *estimator* — the sweep, the intervals, the
sufficiency guard — not the model. Whether SigLIP is any good is a golden-set
question and the golden set has one item; nothing in this file claims otherwise.

The most important test is `test_recommend_refuses_on_the_real_golden_set_shape`:
it pins that the machinery declines to conclude from the data that actually
exists today.
"""

from __future__ import annotations

import pytest

from qualify_models.eval.calibration import (
    PLANNING_EXPECTED_RATE,
    TARGET_HALF_WIDTH,
    ScoredItem,
    check_sufficiency,
    evaluate_rule,
    recommend,
    required_items_per_class,
    sweep,
)
from qualify_models.eval.metrics import (
    required_n_for_proportion,
    wilson_interval,
)
from qualify_models.filter_decision import (
    UNCALIBRATED_LEGACY_RULE,
    ArgmaxRelevantLabelRule,
    CosineThresholdRule,
    ProbabilityThresholdRule,
)

LABELS = ["brand logo", "generic scenery"]


def _item(item_id: str, top_is_brand: bool, relevant: bool) -> ScoredItem:
    scores = [0.9, 0.1] if top_is_brand else [0.1, 0.9]
    return ScoredItem(item_id=item_id, labels=LABELS, scores=scores, relevant=relevant)


def _balanced_set(n_per_class: int) -> list[ScoredItem]:
    """A set where the argmax rule is a perfect predictor. Synthetic by design."""
    items = [_item(f"pos{i}", True, True) for i in range(n_per_class)]
    items += [_item(f"neg{i}", False, False) for i in range(n_per_class)]
    return items


# ---------------------------------------------------------------------------
# Wilson intervals (deliverable C)
# ---------------------------------------------------------------------------


def test_wilson_interval_for_one_of_one_is_not_certainty() -> None:
    """The number that quantifies the blocker: 1/1 spans [0.21, 1.00].

    The normal approximation would return the single point [1.0, 1.0] here and
    report certainty from one observation. That is the failure this replaces.
    """
    interval = wilson_interval(1, 1)
    assert interval is not None
    assert interval.low == pytest.approx(0.2065, abs=1e-3)
    assert interval.high == pytest.approx(1.0, abs=1e-6)


def test_wilson_interval_is_none_when_there_are_no_trials() -> None:
    """Undefined, not wide. Returning [0, 1] would let callers treat an
    unmeasured quantity as merely imprecise."""
    assert wilson_interval(0, 0) is None


def test_wilson_interval_narrows_as_n_grows() -> None:
    widths = [wilson_interval(round(0.9 * n), n).half_width for n in (10, 50, 200, 1000)]  # type: ignore[union-attr]
    assert widths == sorted(widths, reverse=True)


def test_wilson_interval_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(5, 2)


def test_required_n_matches_the_interval_it_promises() -> None:
    """The sample-size answer must agree with the interval actually reported."""
    n = required_n_for_proportion(0.9, 0.10)
    interval = wilson_interval(round(0.9 * n), n)
    assert interval is not None
    assert interval.half_width <= 0.10


def test_required_n_grows_as_the_demanded_precision_tightens() -> None:
    assert required_n_for_proportion(0.9, 0.15) < required_n_for_proportion(0.9, 0.10)
    assert required_n_for_proportion(0.9, 0.10) < required_n_for_proportion(0.9, 0.05)


def test_required_n_is_largest_near_one_half() -> None:
    """p=0.5 is the conservative worst case; sizing there roughly triples the ask."""
    assert required_n_for_proportion(0.5, 0.10) > required_n_for_proportion(0.9, 0.10)


def test_the_documented_sample_size_is_what_the_code_computes() -> None:
    """Pins the number quoted to the founder: ~34 per estimand at +/-10pp."""
    assert required_items_per_class(PLANNING_EXPECTED_RATE, TARGET_HALF_WIDTH) == 34


def test_filter_metrics_ship_intervals_on_both_rates() -> None:
    points = evaluate_rule(
        ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"})),
        _balanced_set(10),
    )
    assert points.precision_ci is not None
    assert points.recall_ci is not None
    assert points.precision_ci.n == 10
    assert points.recall_ci.n == 10


def test_precision_and_recall_intervals_use_different_denominators() -> None:
    """The reason the labelling budget is per-class, not a single total."""
    items = [_item("a", True, True), _item("b", True, False), _item("c", False, True)]
    point = evaluate_rule(ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"})), items)
    assert point.precision_ci is not None and point.precision_ci.n == 2  # predicted positive
    assert point.recall_ci is not None and point.recall_ci.n == 2  # actual positive


# ---------------------------------------------------------------------------
# The sufficiency guard (deliverable B)
# ---------------------------------------------------------------------------


def test_sufficiency_fails_on_the_real_golden_set_shape() -> None:
    """One item, labelled relevant: 1 positive, 0 negatives — today's reality."""
    verdict = check_sufficiency([_item("only", True, True)])
    assert verdict.sufficient is False
    assert verdict.n_positive == 1
    assert verdict.n_negative == 0
    assert any("unmeasurable" in reason for reason in verdict.reasons)


def test_zero_negatives_is_reported_as_unmeasurable_not_merely_small() -> None:
    """The distinction that matters: no amount of sweeping fixes a missing class."""
    verdict = check_sufficiency([_item(f"p{i}", True, True) for i in range(500)])
    assert verdict.sufficient is False
    assert any("false positive cannot be observed" in r for r in verdict.reasons)


def test_sufficiency_reports_the_shortfall_per_class() -> None:
    verdict = check_sufficiency([_item("p", True, True), _item("n", False, False)])
    assert verdict.shortfall_positive == verdict.required_positive - 1
    assert verdict.shortfall_negative == verdict.required_negative - 1


def test_sufficiency_passes_on_an_adequately_sized_balanced_set() -> None:
    verdict = check_sufficiency(_balanced_set(40))
    assert verdict.sufficient is True
    assert verdict.reasons == []


def test_empty_set_is_insufficient_on_both_classes() -> None:
    verdict = check_sufficiency([])
    assert verdict.sufficient is False
    assert len(verdict.reasons) >= 2


# ---------------------------------------------------------------------------
# The refusal — the point of the whole module
# ---------------------------------------------------------------------------


def test_recommend_refuses_on_the_real_golden_set_shape() -> None:
    """With today's data the machinery must decline to pick an operating point.

    This is the test that stops QUA-23 being "closed" by swapping one unvalidated
    constant for another.
    """
    report = recommend(
        [UNCALIBRATED_LEGACY_RULE, CosineThresholdRule(min_cosine=0.09)],
        [_item("only", True, True)],
    )
    assert report.concluded is False
    assert report.recommendation is None
    assert any("NO RECOMMENDATION" in note for note in report.notes)


def test_refusal_still_reports_the_sweep_for_inspection() -> None:
    """Seeing the curve is useful; mistaking it for evidence is not."""
    report = recommend(
        [UNCALIBRATED_LEGACY_RULE, CosineThresholdRule(min_cosine=0.09)],
        [_item("only", True, True)],
    )
    assert len(report.operating_points) == 2
    assert report.recommendation is None


def test_recommend_concludes_once_the_data_supports_it() -> None:
    report = recommend(
        [
            ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"})),
            ProbabilityThresholdRule(threshold=0.99),
        ],
        _balanced_set(40),
    )
    assert report.concluded is True
    assert report.recommendation is not None
    assert report.recommendation.rule_id == "argmax_relevant_label"


def test_a_rule_that_discards_everything_is_never_recommended() -> None:
    """The current defect's signature: 100% discard, and an F1 that hides it."""
    report = recommend([ProbabilityThresholdRule(threshold=0.999)], _balanced_set(40))
    assert report.recommendation is None
    assert any("degenerate discard rate" in note for note in report.notes)


def test_a_rule_that_discards_nothing_is_never_recommended() -> None:
    """The top-k signature, had it been implementable: 0% discard."""
    report = recommend([ProbabilityThresholdRule(threshold=0.0)], _balanced_set(40))
    assert report.recommendation is None
    assert any("degenerate discard rate" in note for note in report.notes)


# ---------------------------------------------------------------------------
# Sweep mechanics
# ---------------------------------------------------------------------------


def test_sweep_measures_every_rule_over_the_same_set() -> None:
    rules = [
        UNCALIBRATED_LEGACY_RULE,
        CosineThresholdRule(min_cosine=0.09),
        ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"})),
    ]
    points = sweep(rules, _balanced_set(5))
    assert [p.rule_id for p in points] == [
        "probability_threshold",
        "cosine_threshold",
        "argmax_relevant_label",
    ]


def test_discard_rate_is_reported_alongside_f1() -> None:
    """F1 alone cannot distinguish a good filter from one that filters nothing."""
    point = evaluate_rule(
        ArgmaxRelevantLabelRule(relevant_labels=frozenset({"brand logo"})),
        _balanced_set(10),
    )
    assert point.discard_rate == pytest.approx(0.5)


def test_evaluate_rule_records_the_parameters_that_were_applied() -> None:
    point = evaluate_rule(CosineThresholdRule(min_cosine=0.09), _balanced_set(3))
    assert point.params == {"min_cosine": 0.09}
