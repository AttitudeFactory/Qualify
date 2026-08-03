from __future__ import annotations

from pathlib import Path
from typing import Any

from transformers import pipeline

from qualify_models.filter_decision import (
    UNCALIBRATED_LEGACY_RULE,
    FilterDecisionRule,
    ProbabilityThresholdRule,
)
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
        _pipeline_cache[MODEL_ID] = pipeline(task="zero-shot-image-classification", model=MODEL_ID)
    return _pipeline_cache[MODEL_ID]


def run_filter(
    image_path: Path,
    source_id: str,
    pipeline_version: str,
    candidate_labels: list[str] = DEFAULT_LABELS,
    threshold: float = 0.22,
    rule: FilterDecisionRule | None = None,
) -> FilterResult:
    """Score a frame against the candidate labels and decide whether to keep it.

    `rule` makes the decision rule injectable. Omitting it reproduces the previous
    behaviour **exactly**: a probability threshold at `threshold`, i.e.
    `UNCALIBRATED_LEGACY_RULE` when `threshold` is left at its default.

    That default is known to be defective — it discards 100% of real candidates,
    see `filter_decision` and QUA-23 — and is deliberately left in place anyway.
    Changing it without labelled data to justify the replacement would repeat the
    original mistake. The rule is now named and recorded on the result, so a
    stored decision says which rule produced it and whether that rule had been
    calibrated.
    """
    clf = _get_pipeline()
    outputs = clf(str(image_path), candidate_labels=candidate_labels)
    labels = [o["label"] for o in outputs]
    scores = [o["score"] for o in outputs]

    resolved: FilterDecisionRule
    if rule is not None:
        resolved = rule
    elif threshold == UNCALIBRATED_LEGACY_RULE.threshold:
        resolved = UNCALIBRATED_LEGACY_RULE
    else:
        resolved = ProbabilityThresholdRule(threshold=threshold)

    decision = resolved.decide(labels, scores)
    return FilterResult(
        source_id=source_id,
        detector_version=DETECTOR_VERSION,
        pipeline_version=pipeline_version,
        labels=labels,
        scores=scores,
        passed=decision.passed,
        threshold=threshold,
        rule_id=decision.rule_id,
        rule_calibrated=decision.calibrated,
    )
