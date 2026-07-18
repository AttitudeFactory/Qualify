from __future__ import annotations

from typing import Any

from transformers import pipeline

from qualify_models.schemas import SentimentResult

MODEL_ID = "pysentimiento/robertuito-sentiment-analysis"
DETECTOR_VERSION = "robertuito-sentiment-v1"

_pipeline_cache: dict[str, Any] = {}


def _get_pipeline() -> Any:
    if MODEL_ID not in _pipeline_cache:
        _pipeline_cache[MODEL_ID] = pipeline(task="text-classification", model=MODEL_ID)
    return _pipeline_cache[MODEL_ID]


def run_sentiment(
    text: str, source_id: str, pipeline_version: str
) -> SentimentResult:
    clf = _get_pipeline()
    output = clf(text)[0]
    return SentimentResult(
        source_id=source_id,
        detector_version=DETECTOR_VERSION,
        pipeline_version=pipeline_version,
        label=output["label"],
        score=output["score"],
    )
