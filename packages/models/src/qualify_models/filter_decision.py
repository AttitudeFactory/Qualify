"""Decision rules for the F2 (SigLIP) candidate filter — QUA-23.

## Why this module exists

`run_filter` used to bake its decision into one hardcoded number,
`threshold = 0.22`, applied to SigLIP's per-label probabilities. That number is
wrong, and wrong in an instructive way: it was chosen against a **softmax**
intuition (just above the `1/5` uniform baseline for five candidate labels) for a
model that **has no softmax head**. SigLIP scores each label independently as
`sigmoid(cos * logit_scale + logit_bias)`, and this checkpoint ships a trained
`logit_bias` of about -16.77, so a 0.22 probability demands a cosine similarity
of ~0.1376 that no realistic label reaches. Measured best on the one real
fixture: 0.1034. The filter therefore discards 100% of candidates and makes the
vision stage unreachable.

The root cause is settled. What is **not** settled is the replacement, and this
module exists so the replacement is a **named, swappable object with recorded
provenance** rather than another anonymous constant.

## What this module deliberately does NOT do

It does not pick the operating point. Every rule here is `calibrated=False`,
because choosing between them — and choosing their parameters — is an empirical
question that requires labelled data, and the golden set currently holds **one
item, labelled relevant**, i.e. one positive and zero negatives. See
`calibration.py` for the machinery that will make the choice once data exists,
and `NOTES_qua23_filter_decision_rule.md` §3 for why one item cannot support it.

Substituting a new unvalidated constant for the old one would be the same defect
with better optics. The default is therefore **unchanged**: `run_filter` still
behaves exactly as before, via `UNCALIBRATED_LEGACY_RULE`. Closing QUA-23 is a
one-line change of that default, on the day the data justifies it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# The checkpoint's trained sigmoid head
# ---------------------------------------------------------------------------

# Read off `SiglipModel` for google/siglip2-base-patch16-224, measured 2026-07-23
# and re-pinned here. Hard-coded so calibration arithmetic needs no weights and no
# network. These live in the module rather than in a test file because they are a
# property of the checkpoint, not of any one test.
SIGLIP2_LOGIT_SCALE: Final = 112.66890716552734
SIGLIP2_LOGIT_BIAS: Final = -16.771724700927734

# Best cosine similarity achieved on tests/fixtures/sample_frame.jpg across a
# hand-tuned label sweep ("text overlay on a video"), measured 2026-07-23. This is
# a single observation on a single frame, NOT a distributional claim.
BEST_MEASURED_COS_SIM: Final = 0.1034


def score_for_cosine(
    cos_sim: float,
    logit_scale: float = SIGLIP2_LOGIT_SCALE,
    logit_bias: float = SIGLIP2_LOGIT_BIAS,
) -> float:
    """SigLIP's per-label probability for a given cosine similarity."""
    return 1.0 / (1.0 + math.exp(-(cos_sim * logit_scale + logit_bias)))


def cosine_for_score(
    probability: float,
    logit_scale: float = SIGLIP2_LOGIT_SCALE,
    logit_bias: float = SIGLIP2_LOGIT_BIAS,
) -> float:
    """Invert the sigmoid head: which cosine similarity yields this probability?

    The function that exposes the defect — `cosine_for_score(0.22)` is ~0.1376,
    above anything the model actually produces on real frames.
    """
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be strictly between 0 and 1")
    logit = math.log(probability / (1.0 - probability))
    return (logit - logit_bias) / logit_scale


# ---------------------------------------------------------------------------
# Decisions and the rule protocol
# ---------------------------------------------------------------------------


class FilterDecision(BaseModel):
    """The outcome of applying one rule, carrying the rule that produced it.

    `rule_id`, `rule_params` and `calibrated` travel with the decision so a stored
    result can always answer "which rule, at which operating point, decided this,
    and had that operating point been validated?" — the provenance discipline the
    repo applies to model outputs, applied to the decision rule itself.
    """

    passed: bool
    rule_id: str
    rule_params: dict[str, Any]
    calibrated: bool
    top_label: str | None
    top_score: float | None


@runtime_checkable
class FilterDecisionRule(Protocol):
    """Turns per-label scores into a keep/discard decision."""

    @property
    def rule_id(self) -> str: ...

    @property
    def calibrated(self) -> bool: ...

    def decide(self, labels: Sequence[str], scores: Sequence[float]) -> FilterDecision: ...


def _validate(labels: Sequence[str], scores: Sequence[float]) -> None:
    if len(labels) != len(scores):
        raise ValueError("labels and scores must be the same length")


def _top(labels: Sequence[str], scores: Sequence[float]) -> tuple[str | None, float | None]:
    if not scores:
        return None, None
    best = max(range(len(scores)), key=lambda i: scores[i])
    return labels[best], scores[best]


# ---------------------------------------------------------------------------
# (a) Threshold in probability space — the current, defective form
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbabilityThresholdRule:
    """Pass when the best label's *probability* clears `threshold`.

    **This is the defective rule.** It is kept, not deleted, for three reasons:
    it is the current production behaviour and removing it would change results
    silently; the defect-pin tests assert against it; and naming a defect is more
    honest than hiding it behind a rename.

    A probability threshold is not inherently wrong — it is wrong *at 0.22*, and
    wrong to choose by softmax reasoning. Note how brutally non-linear the mapping
    is: the difference between passing everything and passing nothing spans a few
    hundredths of cosine similarity, which is exactly why this parameter cannot be
    eyeballed and must be fitted.
    """

    threshold: float = 0.22

    @property
    def rule_id(self) -> str:
        return "probability_threshold"

    @property
    def calibrated(self) -> bool:
        return False

    @property
    def required_cosine(self) -> float:
        """The cosine similarity this threshold actually demands."""
        return cosine_for_score(self.threshold)

    def decide(self, labels: Sequence[str], scores: Sequence[float]) -> FilterDecision:
        _validate(labels, scores)
        top_label, top_score = _top(labels, scores)
        return FilterDecision(
            passed=top_score is not None and top_score >= self.threshold,
            rule_id=self.rule_id,
            rule_params={"threshold": self.threshold},
            calibrated=self.calibrated,
            top_label=top_label,
            top_score=top_score,
        )


# ---------------------------------------------------------------------------
# (b) Threshold in cosine space
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CosineThresholdRule:
    """Pass when the best label's *cosine similarity* clears `min_cosine`.

    Mathematically this is a monotone reparameterisation of
    `ProbabilityThresholdRule` — the same family of decision boundaries, indexed
    differently. That is precisely the argument for it: cosine is the space the
    model's similarities actually live in and the space where observed values are
    legible (real labels land around 0.05-0.11), whereas the corresponding
    probabilities are compressed into the far tail of a sigmoid where a human
    reading `0.22` has no intuition at all for what it demands.

    It does not make the parameter free — `min_cosine` still has to be fitted to
    labelled data. It makes the parameter *interpretable*, so a badly-chosen value
    is visible rather than plausible-looking.
    """

    min_cosine: float

    @property
    def rule_id(self) -> str:
        return "cosine_threshold"

    @property
    def calibrated(self) -> bool:
        return False

    def decide(self, labels: Sequence[str], scores: Sequence[float]) -> FilterDecision:
        _validate(labels, scores)
        top_label, top_score = _top(labels, scores)
        passed = False
        if top_score is not None:
            passed = _cosine_of(top_score) >= self.min_cosine
        return FilterDecision(
            passed=passed,
            rule_id=self.rule_id,
            rule_params={"min_cosine": self.min_cosine},
            calibrated=self.calibrated,
            top_label=top_label,
            top_score=top_score,
        )


def _cosine_of(probability: float) -> float:
    """Cosine behind a probability, clamped so 0.0/1.0 do not blow up the logit."""
    eps = 1e-12
    clamped = min(max(probability, eps), 1.0 - eps)
    return cosine_for_score(clamped)


# ---------------------------------------------------------------------------
# (c) Argmax over partitioned labels — threshold-free
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArgmaxRelevantLabelRule:
    """Pass when the top-scoring label is one of the *relevant* labels.

    The candidate label list is partitioned into labels that mean "this post is a
    candidate" and distractor labels that mean "it is not". The post is kept iff
    the argmax falls on the relevant side.

    **This rule has no free numeric parameter**, which is its main attraction: it
    cannot be mis-tuned the way `0.22` was, because there is nothing to tune. It
    also sidesteps the sigmoid entirely — only the *ranking* of labels matters,
    and ranking is the part of this checkpoint's behaviour that was never in
    doubt (the defect was in thresholding absolute scores, not in the text tower).

    Note that `DEFAULT_LABELS` already looks designed for this: four
    brand-relevant labels plus `"generic scenery"`, which reads as an intended
    distractor.

    It is **not** free of design choices — the partition itself is a choice, and a
    badly chosen distractor set will silently skew the discard rate. But a
    partition is auditable by reading it, whereas a threshold is not. It still
    requires labelled data to *validate*; it requires none to *specify*.
    """

    relevant_labels: frozenset[str]

    @property
    def rule_id(self) -> str:
        return "argmax_relevant_label"

    @property
    def calibrated(self) -> bool:
        return False

    def decide(self, labels: Sequence[str], scores: Sequence[float]) -> FilterDecision:
        _validate(labels, scores)
        unknown = set(labels) - self.relevant_labels
        top_label, top_score = _top(labels, scores)
        return FilterDecision(
            passed=top_label is not None and top_label in self.relevant_labels,
            rule_id=self.rule_id,
            rule_params={
                "relevant_labels": sorted(self.relevant_labels),
                "distractor_labels": sorted(unknown),
            },
            calibrated=self.calibrated,
            top_label=top_label,
            top_score=top_score,
        )


# ---------------------------------------------------------------------------
# Rule forms rejected on structural grounds — no labelled data required
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RejectedRuleForm:
    """A candidate rule shape ruled out by reasoning rather than by measurement.

    Recorded as data, not prose, so the argument cannot be quietly forgotten and
    re-proposed. Not everything needs the golden set: some options are wrong for
    reasons visible from the cascade's structure alone.
    """

    name: str
    reason: str
    proposed_in: str


REJECTED_RULE_FORMS: Final[tuple[RejectedRuleForm, ...]] = (
    RejectedRuleForm(
        name="top_k_over_candidate_labels",
        reason=(
            "Top-k selects k labels for EVERY image. It ranks labels *within* an image and "
            "never rejects an image, so the discard rate is 0% by construction and the "
            "cascade's entire premise — spend VLM budget only on pre-qualified content — "
            "collapses. A filter must be able to say no; top-k structurally cannot. Its "
            "viable relative is ArgmaxRelevantLabelRule, which uses the same ranking signal "
            "but adds the relevant/distractor partition that makes rejection possible."
        ),
        proposed_in="QUA-23 acceptance criterion, option (b)",
    ),
)


# ---------------------------------------------------------------------------
# The default: unchanged behaviour, now named
# ---------------------------------------------------------------------------

LEGACY_PROBABILITY_THRESHOLD: Final = 0.22

UNCALIBRATED_LEGACY_RULE: Final = ProbabilityThresholdRule(threshold=LEGACY_PROBABILITY_THRESHOLD)
"""The rule `run_filter` uses when no rule is injected.

Named `UNCALIBRATED_` on purpose. It reproduces today's behaviour **exactly**, so
nothing changes silently while the question is open; the name is what stops a
reader mistaking it for a validated choice. Replacing this binding is the whole
of QUA-23's remaining code change, and it must not happen before the golden set
can justify the replacement.
"""


def default_relevant_labels(candidate_labels: Sequence[str]) -> frozenset[str]:
    """Everything except the known distractor, as a *starting point* for a partition.

    Provided so `ArgmaxRelevantLabelRule` can be constructed for experiments
    without hand-listing labels. It is a convenience, **not** a validated
    partition — which labels count as distractors is exactly the kind of choice
    the golden set has to confirm.
    """
    return frozenset(label for label in candidate_labels if label not in KNOWN_DISTRACTOR_LABELS)


KNOWN_DISTRACTOR_LABELS: Final[frozenset[str]] = frozenset({"generic scenery"})
"""Labels in `DEFAULT_LABELS` that read as "not a candidate".

One entry today, and it is an inference from the label text, not a measurement.
Flagged so a reader does not mistake it for an empirically derived partition.
"""


@dataclass(frozen=True)
class RuleRegistry:
    """The three rule forms still on the table, for the calibration sweep."""

    forms: tuple[str, ...] = field(
        default=("probability_threshold", "cosine_threshold", "argmax_relevant_label")
    )
