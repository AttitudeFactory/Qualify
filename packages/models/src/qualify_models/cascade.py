from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qualify_models.filter import run_filter
from qualify_models.providers import TranscriptionProvider, VisionProvider
from qualify_models.schemas import FilterResult, SentimentResult, TranscriptionResult, VisionResult
from qualify_models.sentiment import run_sentiment
from qualify_models.transcription import run_transcription
from qualify_models.vision import run_vision

PIPELINE_VERSION = "0.1.0"


@dataclass
class CascadeResult:
    filter: FilterResult
    vision: VisionResult | None
    transcription: TranscriptionResult
    sentiment: SentimentResult | None


def run_cascade(
    source_id: str,
    image_path: Path,
    audio_path: Path,
    caption: str | None = None,
    vision_provider: VisionProvider | None = None,
    transcription_provider: TranscriptionProvider | None = None,
) -> CascadeResult:
    """MVP ordering: filter (F2) gates vision (F3); transcription (F1) and
    sentiment run unconditionally. docs/arquitectura.md §3.4 documents F1
    gating F2 too (discard ~60% with no spoken/visual signal before even
    filtering frames) — that needs a "has signal" classifier this package
    doesn't have yet, so it's not implemented here."""
    filter_result = run_filter(image_path, source_id=source_id, pipeline_version=PIPELINE_VERSION)

    vision_result = None
    if filter_result.passed:
        vision_result = run_vision(
            image_path,
            source_id=source_id,
            pipeline_version=PIPELINE_VERSION,
            provider=vision_provider,
        )

    transcription_result = run_transcription(
        audio_path,
        source_id=source_id,
        pipeline_version=PIPELINE_VERSION,
        provider=transcription_provider,
    )

    sentiment_result = None
    if caption:
        sentiment_result = run_sentiment(
            caption, source_id=source_id, pipeline_version=PIPELINE_VERSION
        )

    return CascadeResult(
        filter=filter_result,
        vision=vision_result,
        transcription=transcription_result,
        sentiment=sentiment_result,
    )
