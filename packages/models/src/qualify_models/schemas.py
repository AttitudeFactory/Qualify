from __future__ import annotations

from pydantic import BaseModel


class Provenance(BaseModel):
    source_id: str
    detector_version: str
    pipeline_version: str


class FilterResult(Provenance):
    labels: list[str]
    scores: list[float]
    passed: bool
    threshold: float
    # Which decision rule produced `passed`, and whether that rule's operating
    # point had been validated against labelled data. Optional for backwards
    # compatibility with results produced before the rule seam existed (QUA-23);
    # populated by run_filter from here on. `rule_calibrated=False` is the honest
    # state today for every rule in filter_decision.
    rule_id: str | None = None
    rule_calibrated: bool | None = None


class VisionResult(Provenance):
    description: str
    model_id: str


class TranscriptionResult(Provenance):
    text: str
    language: str | None
    model_id: str


class SentimentResult(Provenance):
    label: str
    score: float
    # Optional for backwards compatibility with results produced before the
    # SentimentProvider seam existed; populated by run_sentiment from here on.
    model_id: str | None = None
