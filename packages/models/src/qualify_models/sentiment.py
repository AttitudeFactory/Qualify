from __future__ import annotations

from qualify_models.providers import LocalRobertuitoSentimentProvider, SentimentProvider
from qualify_models.schemas import SentimentResult

MODEL_ID = "pysentimiento/robertuito-sentiment-analysis"
DETECTOR_VERSION = "robertuito-sentiment-v1"

LABELS = ("POS", "NEG", "NEU")

_default_provider: SentimentProvider | None = None


def _get_default_provider() -> SentimentProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = LocalRobertuitoSentimentProvider(model_id=MODEL_ID)
    return _default_provider


def run_sentiment(
    text: str,
    source_id: str,
    pipeline_version: str,
    provider: SentimentProvider | None = None,
) -> SentimentResult:
    """Classify polarity of one text fragment.

    `provider` follows the same seam as vision/transcription: pass a provider
    to swap the model (or to run offline in tests); omit it for the default
    local robertuito. The resolved provider's `model_id` is recorded on the
    result so the output carries the checkpoint it came from.
    """
    resolved = provider if provider is not None else _get_default_provider()
    label, score = resolved.classify(text)
    return SentimentResult(
        source_id=source_id,
        detector_version=DETECTOR_VERSION,
        pipeline_version=pipeline_version,
        label=label,
        score=score,
        model_id=resolved.model_id,
    )
