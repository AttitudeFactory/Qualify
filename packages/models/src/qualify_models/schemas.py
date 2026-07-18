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
