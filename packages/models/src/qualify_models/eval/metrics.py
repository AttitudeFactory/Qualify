from __future__ import annotations

import math
import re

import jiwer
from pydantic import BaseModel

# WER is computed by jiwer (Apache-2.0), the standard Levenshtein-based
# word-error-rate implementation, rather than hand-rolled. We only pre-normalize
# text (case, punctuation, whitespace) before handing the alignment/edit-distance
# work to jiwer.wer. See https://github.com/jitsi/jiwer.

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


DEFAULT_Z: float = 1.959963984540054
"""z for a two-sided 95% interval. Spelled out rather than rounded to 1.96 so a
reader can see which confidence level is meant."""


class ConfidenceInterval(BaseModel):
    """A Wilson score interval for a proportion.

    Wilson rather than the textbook normal approximation because the normal
    interval degenerates exactly where this project lives: tiny samples and
    proportions near 0 or 1. At 1 success in 1 trial the normal interval is the
    single point [1.0, 1.0] — it would report certainty from one observation.
    Wilson gives [0.21, 1.00], which is the honest answer.
    """

    low: float
    high: float
    n: int

    @property
    def half_width(self) -> float:
        return (self.high - self.low) / 2.0


def wilson_interval(successes: int, trials: int, z: float = DEFAULT_Z) -> ConfidenceInterval | None:
    """Wilson score interval, or None when there are no trials.

    `None` for `trials == 0` is deliberate: an interval over an empty denominator
    is not "wide", it is undefined, and returning [0, 1] would let a caller treat
    an unmeasured quantity as merely imprecise.
    """
    if successes < 0 or trials < 0 or successes > trials:
        raise ValueError("require 0 <= successes <= trials")
    if trials == 0:
        return None
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = (p + z * z / (2.0 * trials)) / denom
    spread = z / denom * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))
    return ConfidenceInterval(
        low=max(0.0, centre - spread),
        high=min(1.0, centre + spread),
        n=trials,
    )


def required_n_for_proportion(
    expected_p: float,
    half_width: float,
    z: float = DEFAULT_Z,
    max_n: int = 100_000,
) -> int:
    """Smallest n whose Wilson half-width is <= `half_width` at `expected_p`.

    Solved by search rather than the closed-form normal formula, so the answer
    matches the interval actually reported by `wilson_interval` instead of an
    approximation that disagrees with it at small n.

    This is what turns "the golden set is too small" into a number someone can
    budget against.
    """
    if not 0.0 <= expected_p <= 1.0:
        raise ValueError("expected_p must be in [0, 1]")
    if not 0.0 < half_width < 1.0:
        raise ValueError("half_width must be in (0, 1)")
    for n in range(1, max_n + 1):
        interval = wilson_interval(round(expected_p * n), n, z)
        if interval is not None and interval.half_width <= half_width:
            return n
    raise ValueError(f"no n <= {max_n} achieves half_width {half_width}")


class FilterMetrics(BaseModel):
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1: float
    support: int
    # Point estimates alone are misleading at the sample sizes this project has
    # (the golden set holds one item), so every rate ships with its interval.
    # None means the denominator was empty — unmeasured, not merely uncertain.
    precision_ci: ConfidenceInterval | None = None
    recall_ci: ConfidenceInterval | None = None


class SentimentMetrics(BaseModel):
    correct: int
    total: int
    accuracy: float


class TranscriptionMetrics(BaseModel):
    wer: float
    n_pairs: int
    n_skipped_empty_reference: int


def filter_metrics(predicted: list[bool], truth: list[bool]) -> FilterMetrics:
    """Binary precision/recall/F1 for the F2 filter. Positive class = "relevant
    candidate that should pass the filter"."""
    if len(predicted) != len(truth):
        raise ValueError("predicted and truth must be the same length")
    tp = sum(1 for p, t in zip(predicted, truth) if p and t)
    fp = sum(1 for p, t in zip(predicted, truth) if p and not t)
    fn = sum(1 for p, t in zip(predicted, truth) if not p and t)
    tn = sum(1 for p, t in zip(predicted, truth) if not p and not t)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return FilterMetrics(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        precision=precision,
        recall=recall,
        f1=f1,
        support=len(truth),
        # Precision is estimated over predicted-positives, recall over actual
        # positives. Different denominators, so they need separate intervals —
        # and separate sample-size budgets when planning a labelling round.
        precision_ci=wilson_interval(tp, tp + fp),
        recall_ci=wilson_interval(tp, tp + fn),
    )


def sentiment_accuracy(predicted: list[str], truth: list[str]) -> SentimentMetrics:
    """Exact-match accuracy over normalized (upper-cased) polarity labels."""
    if len(predicted) != len(truth):
        raise ValueError("predicted and truth must be the same length")
    total = len(truth)
    correct = sum(1 for p, t in zip(predicted, truth) if p.strip().upper() == t.strip().upper())
    accuracy = correct / total if total else 0.0
    return SentimentMetrics(correct=correct, total=total, accuracy=accuracy)


def transcription_wer(hypotheses: list[str], references: list[str]) -> TranscriptionMetrics:
    """Corpus-level WER via jiwer. Pairs whose reference normalizes to empty are
    skipped (WER is undefined with no reference words) and counted separately."""
    if len(hypotheses) != len(references):
        raise ValueError("hypotheses and references must be the same length")
    norm_refs: list[str] = []
    norm_hyps: list[str] = []
    skipped = 0
    for hyp, ref in zip(hypotheses, references):
        norm_ref = _normalize(ref)
        if not norm_ref:
            skipped += 1
            continue
        norm_refs.append(norm_ref)
        norm_hyps.append(_normalize(hyp))
    if not norm_refs:
        return TranscriptionMetrics(wer=0.0, n_pairs=0, n_skipped_empty_reference=skipped)
    wer = float(jiwer.wer(norm_refs, norm_hyps))
    return TranscriptionMetrics(wer=wer, n_pairs=len(norm_refs), n_skipped_empty_reference=skipped)


def _normalize(text: str) -> str:
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()
