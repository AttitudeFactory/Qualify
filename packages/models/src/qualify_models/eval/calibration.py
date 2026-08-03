"""Fitting and validating the F2 filter's decision rule — QUA-23.

This is the machine that answers "which rule, at which operating point?" **when
labelled data exists**. It does not answer it today, and the most important thing
it does is *refuse to*.

## The guard is the point

The defect this module exists to close was not a bad number. It was a number
chosen without data and then trusted. Replacing it with a second number chosen
without data — even a better-looking one, even one produced by a sweep — would
reproduce the defect exactly, with a plausibility it did not previously have.

So `recommend()` runs the sufficiency check first and returns a report with
`recommendation=None` when the data cannot support a choice. A sweep still runs
and is still reported, because seeing the curve is useful; but the curve is
labelled as insufficient rather than presented as a finding.

## Why the current golden set fails the check

One item, labelled relevant: **1 positive, 0 negatives.**

- With zero negatives a false positive **cannot occur at any operating point**.
  Every rule that passes the item scores precision 1.0 and every rule that
  rejects it scores 0.0. The precision column would be a rendering of the label
  distribution, not a measurement of the rule.
- Recall is one Bernoulli trial. Wilson 95% for 1/1 is about [0.21, 1.00] — an
  estimate compatible with a rule that is right one time in five.

Both failures are structural. No amount of sweeping fixes them, and neither does
a cleverer metric. Only more labelled items do.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel

from qualify_models.eval.metrics import (
    ConfidenceInterval,
    FilterMetrics,
    filter_metrics,
    required_n_for_proportion,
)
from qualify_models.filter_decision import FilterDecisionRule

# Planning defaults for the sample-size guidance. Both are judgement calls about
# how precise an answer is worth paying for, not statistical facts.
TARGET_HALF_WIDTH: Final = 0.10
"""+/-10 percentage points at 95%. Tight enough to distinguish a usable filter
from a broken one; loose enough to be affordable. +/-5pp costs roughly four times
as many items for a distinction this decision does not need."""

PLANNING_EXPECTED_RATE: Final = 0.90
"""Assumed true precision/recall when sizing a labelling round. Optimistic on
purpose: sample size *falls* as p approaches 1, so if the real rate is worse the
interval is wider than planned. Sizing at p=0.5 (the conservative maximum) would
roughly triple the ask for a decision that does not need it."""


class ScoredItem(BaseModel):
    """One labelled item with the model's per-label scores already computed.

    Scores are taken as input rather than computed here so the sweep is pure
    arithmetic: no weights, no network, and a rule can be re-evaluated over a
    stored set of scores without re-running the model. Re-scoring is only needed
    when the *checkpoint* or the *candidate labels* change.
    """

    item_id: str
    labels: list[str]
    scores: list[float]
    relevant: bool
    """Ground truth: should the filter pass this item on to the vision stage."""


class SufficiencyVerdict(BaseModel):
    """Whether a labelled set can support choosing an operating point at all."""

    sufficient: bool
    reasons: list[str]
    n_items: int
    n_positive: int
    n_negative: int
    required_positive: int
    required_negative: int

    @property
    def shortfall_positive(self) -> int:
        return max(0, self.required_positive - self.n_positive)

    @property
    def shortfall_negative(self) -> int:
        return max(0, self.required_negative - self.n_negative)


def required_items_per_class(
    expected_rate: float = PLANNING_EXPECTED_RATE,
    half_width: float = TARGET_HALF_WIDTH,
) -> int:
    """How many items per class to estimate a rate to `half_width` at 95%.

    Applied per class because **precision and recall have different
    denominators**: recall is estimated over actual positives, precision over
    predicted positives. A set of N items split badly can size one and starve the
    other, which is why the guard counts the two classes separately rather than
    checking a single total.
    """
    return required_n_for_proportion(expected_rate, half_width)


def check_sufficiency(
    items: Sequence[ScoredItem],
    expected_rate: float = PLANNING_EXPECTED_RATE,
    half_width: float = TARGET_HALF_WIDTH,
) -> SufficiencyVerdict:
    """Can this labelled set justify an operating point? Usually the answer is no."""
    n_positive = sum(1 for item in items if item.relevant)
    n_negative = sum(1 for item in items if not item.relevant)
    required = required_items_per_class(expected_rate, half_width)

    reasons: list[str] = []
    if n_negative == 0:
        reasons.append(
            "no negative items: a false positive cannot be observed at any operating "
            "point, so precision is not merely imprecise but unmeasurable"
        )
    if n_positive == 0:
        reasons.append(
            "no positive items: a true positive cannot be observed, so recall is unmeasurable"
        )
    if 0 < n_positive < required:
        reasons.append(
            f"only {n_positive} positive item(s); {required} needed to estimate recall "
            f"to +/-{half_width:.0%} at 95% (assuming a true rate near {expected_rate:.0%})"
        )
    if 0 < n_negative < required:
        reasons.append(
            f"only {n_negative} negative item(s); {required} needed to estimate precision "
            f"to +/-{half_width:.0%} at 95% (assuming a true rate near {expected_rate:.0%})"
        )

    return SufficiencyVerdict(
        sufficient=not reasons,
        reasons=reasons,
        n_items=len(items),
        n_positive=n_positive,
        n_negative=n_negative,
        required_positive=required,
        required_negative=required,
    )


@dataclass(frozen=True)
class OperatingPoint:
    """One rule at one parameterisation, with its measured performance."""

    rule_id: str
    params: dict[str, object]
    metrics: FilterMetrics
    discard_rate: float
    """Share of items the rule rejects. A rule that discards everything (the
    current defect) or nothing (top-k) is broken regardless of its F1."""

    @property
    def precision_ci(self) -> ConfidenceInterval | None:
        return self.metrics.precision_ci

    @property
    def recall_ci(self) -> ConfidenceInterval | None:
        return self.metrics.recall_ci


def evaluate_rule(rule: FilterDecisionRule, items: Sequence[ScoredItem]) -> OperatingPoint:
    """Apply one rule to a labelled set and measure it."""
    decisions = [rule.decide(item.labels, item.scores) for item in items]
    predicted = [d.passed for d in decisions]
    truth = [item.relevant for item in items]
    discarded = sum(1 for p in predicted if not p)
    return OperatingPoint(
        rule_id=rule.rule_id,
        params=decisions[0].rule_params if decisions else {},
        metrics=filter_metrics(predicted, truth),
        discard_rate=discarded / len(items) if items else 0.0,
    )


def sweep(
    rules: Sequence[FilterDecisionRule],
    items: Sequence[ScoredItem],
) -> list[OperatingPoint]:
    """Measure every candidate rule over the same labelled set."""
    return [evaluate_rule(rule, items) for rule in rules]


class CalibrationReport(BaseModel):
    """The result of a calibration attempt — including a refusal to conclude.

    A refusal is a first-class outcome, not an error. `recommendation` is None
    whenever `sufficiency.sufficient` is False, and callers must handle that
    rather than reading `operating_points` and picking the best row themselves —
    which is the failure mode this whole module exists to prevent.
    """

    model_config = {"arbitrary_types_allowed": True}

    sufficiency: SufficiencyVerdict
    operating_points: list[OperatingPoint]
    recommendation: OperatingPoint | None
    notes: list[str]

    @property
    def concluded(self) -> bool:
        return self.recommendation is not None


def recommend(
    rules: Sequence[FilterDecisionRule],
    items: Sequence[ScoredItem],
    expected_rate: float = PLANNING_EXPECTED_RATE,
    half_width: float = TARGET_HALF_WIDTH,
) -> CalibrationReport:
    """Sweep the candidate rules and, only if the data allows, pick one.

    Selection is by F1 among rules that actually discriminate. A rule with a
    degenerate discard rate — everything or nothing — is excluded regardless of
    its score, because both extremes can post a respectable F1 on a skewed set
    while doing no filtering at all.
    """
    verdict = check_sufficiency(items, expected_rate, half_width)
    points = sweep(rules, items)
    notes: list[str] = []

    if not verdict.sufficient:
        notes.append(
            "NO RECOMMENDATION. The sweep below is reported for inspection only; it "
            "cannot support a choice of operating point. Substituting one of these "
            "values for the current constant would repeat the original defect with "
            "better optics."
        )
        notes.extend(verdict.reasons)
        return CalibrationReport(
            sufficiency=verdict,
            operating_points=points,
            recommendation=None,
            notes=notes,
        )

    discriminating = [p for p in points if 0.0 < p.discard_rate < 1.0]
    if not discriminating:
        notes.append(
            "every candidate rule has a degenerate discard rate (0% or 100%): none of "
            "them is filtering, so none can be recommended"
        )
        return CalibrationReport(
            sufficiency=verdict,
            operating_points=points,
            recommendation=None,
            notes=notes,
        )

    best = max(discriminating, key=lambda p: p.metrics.f1)
    notes.append(
        f"recommended {best.rule_id} with F1={best.metrics.f1:.3f} over "
        f"{verdict.n_items} labelled items "
        f"({verdict.n_positive} positive, {verdict.n_negative} negative)"
    )
    return CalibrationReport(
        sufficiency=verdict,
        operating_points=points,
        recommendation=best,
        notes=notes,
    )
