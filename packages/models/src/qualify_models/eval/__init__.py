"""Golden-set evaluation harness for the multimodal cascade.

Implements the per-stage evaluation described in docs/arquitectura.md §7:
loads a labeled golden set, runs the cascade (filter -> vision -> transcription
-> sentiment) per item, and computes per-stage metrics (filter
precision/recall/F1, transcription WER, sentiment accuracy) with checkpoint +
revision provenance on every report.
"""

from __future__ import annotations

from qualify_models.eval.cost import CostEstimate, StageCost, estimate_cost
from qualify_models.eval.harness import EvalReport, evaluate
from qualify_models.eval.metrics import (
    FilterMetrics,
    SentimentMetrics,
    TranscriptionMetrics,
    filter_metrics,
    sentiment_accuracy,
    transcription_wer,
)
from qualify_models.eval.provenance import StageProvenance, resolve_revision
from qualify_models.eval.schema import GoldenItem, GoldenSet, load_golden_set

__all__ = [
    "CostEstimate",
    "EvalReport",
    "FilterMetrics",
    "GoldenItem",
    "GoldenSet",
    "SentimentMetrics",
    "StageCost",
    "StageProvenance",
    "TranscriptionMetrics",
    "estimate_cost",
    "evaluate",
    "filter_metrics",
    "load_golden_set",
    "resolve_revision",
    "sentiment_accuracy",
    "transcription_wer",
]
