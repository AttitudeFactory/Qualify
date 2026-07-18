from __future__ import annotations

from pathlib import Path
from typing import Any

from transformers import pipeline

from qualify_models.schemas import FilterResult

MODEL_ID = "google/siglip2-base-patch16-224"
DETECTOR_VERSION = "siglip2-base-patch16-224-v1"

DEFAULT_LABELS = [
    "product close-up",
    "person using a product",
    "brand logo",
    "indoor lifestyle scene",
    "generic scenery",
]

_pipeline_cache: dict[str, Any] = {}


def _get_pipeline() -> Any:
    if MODEL_ID not in _pipeline_cache:
        _pipeline_cache[MODEL_ID] = pipeline(
            task="zero-shot-image-classification", model=MODEL_ID
        )
    return _pipeline_cache[MODEL_ID]


def run_filter(
    image_path: Path,
    source_id: str,
    pipeline_version: str,
    candidate_labels: list[str] = DEFAULT_LABELS,
    threshold: float = 0.22,
) -> FilterResult:
    clf = _get_pipeline()
    outputs = clf(str(image_path), candidate_labels=candidate_labels)
    labels = [o["label"] for o in outputs]
    scores = [o["score"] for o in outputs]
    return FilterResult(
        source_id=source_id,
        detector_version=DETECTOR_VERSION,
        pipeline_version=pipeline_version,
        labels=labels,
        scores=scores,
        passed=max(scores) >= threshold,
        threshold=threshold,
    )
