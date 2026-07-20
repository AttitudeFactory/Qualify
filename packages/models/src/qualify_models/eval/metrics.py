from __future__ import annotations

import re

import jiwer
from pydantic import BaseModel

# WER is computed by jiwer (Apache-2.0), the standard Levenshtein-based
# word-error-rate implementation, rather than hand-rolled. We only pre-normalize
# text (case, punctuation, whitespace) before handing the alignment/edit-distance
# work to jiwer.wer. See https://github.com/jitsi/jiwer.

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


class FilterMetrics(BaseModel):
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1: float
    support: int


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
