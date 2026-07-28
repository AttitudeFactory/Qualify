import pytest

from qualify_models.providers import SentimentProvider
from qualify_models.sentiment import DETECTOR_VERSION, MODEL_ID, run_sentiment


class StubSentimentProvider:
    """Fixed-output provider implementing the SentimentProvider Protocol."""

    model_id = "stub/fixed-output"

    def __init__(self, label: str = "POS", score: float = 0.9) -> None:
        self._label = label
        self._score = score

    def classify(self, text: str) -> tuple[str, float]:
        return self._label, self._score


def test_run_sentiment_with_injected_provider() -> None:
    """Offline replacement for the integration test below.

    Proves the stage's contract — provenance, label and score plumbing — without
    weights or network, via the SentimentProvider seam.
    """
    provider: SentimentProvider = StubSentimentProvider(label="NEG", score=0.83)
    result = run_sentiment(
        "El pedido llegó roto y nadie responde",
        source_id="comment_1",
        pipeline_version="0.1.0",
        provider=provider,
    )

    assert result.label == "NEG"
    assert result.score == pytest.approx(0.83)
    assert result.source_id == "comment_1"
    assert result.pipeline_version == "0.1.0"
    assert result.detector_version == DETECTOR_VERSION
    assert result.model_id == "stub/fixed-output"


def test_provider_receives_the_text_verbatim() -> None:
    seen: list[str] = []

    class RecordingProvider:
        model_id = "stub/recording"

        def classify(self, text: str) -> tuple[str, float]:
            seen.append(text)
            return "NEU", 0.5

    run_sentiment(
        "  texto con espacios  ",
        source_id="c",
        pipeline_version="0.1.0",
        provider=RecordingProvider(),
    )

    assert seen == ["  texto con espacios  "]


@pytest.mark.integration
def test_run_sentiment_on_spanish_text() -> None:
    """Exercises the real robertuito checkpoint; downloads weights on a cold cache.

    Marked integration after a cold-cache run showed it failing with an OSError
    on a clean checkout — it passed locally only via a warm HF cache. The
    offline contract test above replaces its non-model coverage.
    """
    result = run_sentiment(
        "Me encanta este producto, la verdad superó mis expectativas!",
        source_id="comment_1",
        pipeline_version="0.1.0",
    )
    assert result.label in {"POS", "NEG", "NEU"}
    assert 0.0 <= result.score <= 1.0
    assert result.model_id == MODEL_ID
