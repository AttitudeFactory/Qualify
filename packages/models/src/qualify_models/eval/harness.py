from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from qualify_models import filter as filter_stage
from qualify_models import sentiment as sentiment_stage
from qualify_models.cascade import PIPELINE_VERSION, CascadeResult, run_cascade
from qualify_models.eval.cost import CostEstimate
from qualify_models.eval.metrics import (
    FilterMetrics,
    SentimentMetrics,
    TranscriptionMetrics,
    filter_metrics,
    sentiment_accuracy,
    transcription_wer,
)
from qualify_models.eval.provenance import StageProvenance, resolve_revision
from qualify_models.eval.schema import GoldenItem, GoldenSet

CascadeRunner = Callable[[GoldenItem], CascadeResult]
RevisionResolver = Callable[[str], str | None]

# Bumped when the harness/metric computation changes in a way that makes reports
# non-comparable across versions (e.g. a WER normalization change). Distinct from
# pipeline_version (the cascade) — a report pins both.
HARNESS_VERSION = "0.1.0"


class StageMetricsReport(BaseModel):
    filter: FilterMetrics | None = None
    transcription: TranscriptionMetrics | None = None
    sentiment: SentimentMetrics | None = None


class EvalReport(BaseModel):
    harness_version: str
    pipeline_version: str
    manifest_id: str | None
    manifest_version: str | None
    manifest_sha256: str | None
    generated_at: datetime
    n_items: int
    metrics: StageMetricsReport
    provenance: list[StageProvenance]
    cost_estimate: CostEstimate | None = None


def default_runner(item: GoldenItem) -> CascadeResult:
    return run_cascade(
        source_id=item.post_id,
        image_path=item.image_path,
        audio_path=item.audio_path,
        caption=item.caption,
    )


def evaluate(
    golden_set: GoldenSet,
    runner: CascadeRunner = default_runner,
    revision_resolver: RevisionResolver = resolve_revision,
    cost_estimate: CostEstimate | None = None,
) -> EvalReport:
    """Run the cascade over every labeled item and compute per-stage metrics.

    `runner` defaults to the real cascade but is injectable: tests pass a fake
    that returns canned CascadeResults so the suite never touches the network.
    `revision_resolver` is likewise injectable so offline runs record
    provenance without a Hub call.
    """
    filter_pred: list[bool] = []
    filter_truth: list[bool] = []
    hyps: list[str] = []
    refs: list[str] = []
    sent_pred: list[str] = []
    sent_truth: list[str] = []

    vision_model_id: str | None = None
    transcription_model_id: str | None = None

    for item in golden_set.items:
        result = runner(item)

        filter_pred.append(result.filter.passed)
        filter_truth.append(item.filter_relevant)

        hyps.append(result.transcription.text)
        refs.append(item.reference_transcript)
        transcription_model_id = result.transcription.model_id

        if result.vision is not None:
            vision_model_id = result.vision.model_id

        if item.sentiment_label is not None and result.sentiment is not None:
            sent_pred.append(result.sentiment.label)
            sent_truth.append(item.sentiment_label)

    metrics = StageMetricsReport(
        filter=filter_metrics(filter_pred, filter_truth) if filter_pred else None,
        transcription=transcription_wer(hyps, refs) if refs else None,
        sentiment=sentiment_accuracy(sent_pred, sent_truth) if sent_pred else None,
    )

    provenance = _build_provenance(
        revision_resolver=revision_resolver,
        vision_model_id=vision_model_id,
        transcription_model_id=transcription_model_id,
        ran_sentiment=bool(sent_pred),
    )

    return EvalReport(
        harness_version=HARNESS_VERSION,
        pipeline_version=PIPELINE_VERSION,
        manifest_id=golden_set.manifest_id,
        manifest_version=golden_set.manifest_version,
        manifest_sha256=golden_set.manifest_sha256,
        generated_at=datetime.now(UTC),
        n_items=len(golden_set.items),
        metrics=metrics,
        provenance=provenance,
        cost_estimate=cost_estimate,
    )


def _build_provenance(
    revision_resolver: RevisionResolver,
    vision_model_id: str | None,
    transcription_model_id: str | None,
    ran_sentiment: bool,
) -> list[StageProvenance]:
    entries: list[StageProvenance] = [
        StageProvenance(
            stage="filter",
            model_id=filter_stage.MODEL_ID,
            detector_version=filter_stage.DETECTOR_VERSION,
        )
    ]
    if vision_model_id is not None:
        entries.append(StageProvenance(stage="vision", model_id=vision_model_id))
    if transcription_model_id is not None:
        entries.append(StageProvenance(stage="transcription", model_id=transcription_model_id))
    if ran_sentiment:
        entries.append(
            StageProvenance(
                stage="sentiment",
                model_id=sentiment_stage.MODEL_ID,
                detector_version=sentiment_stage.DETECTOR_VERSION,
            )
        )
    for entry in entries:
        entry.revision = revision_resolver(entry.model_id)
    return entries
