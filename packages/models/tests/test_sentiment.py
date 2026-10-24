import pytest

from qualify_models.providers import (
    ROBERTUITO_MAX_INPUT_TOKENS,
    LocalRobertuitoSentimentProvider,
    SentimentProvider,
)
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


# --- m-24852236: robertuito input truncation, with stub pipelines (no weights) ---------


class _StubTokenizer:
    def __init__(self, model_max_length: object) -> None:
        self.model_max_length = model_max_length


class _StrictStubPipeline:
    """Behaves like the real checkpoint: one whitespace token per word, and an input over
    the limit raises exactly as robertuito does (IndexError on CPU) unless the call asks
    for truncation."""

    def __init__(self, model_max_length: object = 128) -> None:
        self.tokenizer = _StubTokenizer(model_max_length)
        self.calls: list[dict[str, object]] = []

    def __call__(self, text: str, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(kwargs)
        if len(text.split()) > 128 and not kwargs.get("truncation"):
            raise IndexError("index out of range in self")
        return [{"label": "NEU", "score": 0.75}]


def _provider_with(stub: _StrictStubPipeline) -> LocalRobertuitoSentimentProvider:
    provider = LocalRobertuitoSentimentProvider()
    provider._pipeline = stub  # injected: transformers is never loaded
    return provider


LONG_COMMENT = " ".join(["¿tienen envío a domicilio en Cúcuta y cuánto sale el combo?"] * 30)


def test_long_comment_is_truncated_not_raised() -> None:
    stub = _StrictStubPipeline(model_max_length=128)
    assert len(LONG_COMMENT.split()) > 128

    label, score = _provider_with(stub).classify(LONG_COMMENT)

    assert label == "NEU"
    assert score == pytest.approx(0.75)
    assert stub.calls == [{"truncation": True, "max_length": 128}]


def test_max_length_follows_the_tokenizer() -> None:
    stub = _StrictStubPipeline(model_max_length=64)
    _provider_with(stub).classify("me encanta")
    assert stub.calls[-1]["max_length"] == 64


@pytest.mark.parametrize("declared", [int(1e30), 0, None])
def test_unusable_declared_limit_falls_back_to_robertuito_limit(declared: object) -> None:
    provider = _provider_with(_StrictStubPipeline(model_max_length=declared))
    assert provider.max_input_tokens() == ROBERTUITO_MAX_INPUT_TOKENS == 128


def test_mixed_batch_classifies_every_text() -> None:
    """Short and long comments in one pass all get a result through `run_sentiment`."""
    stub = _StrictStubPipeline()
    provider = _provider_with(stub)
    texts = ["me encanta", LONG_COMMENT, "pésimo servicio"]

    results = [
        run_sentiment(t, source_id=f"c{i}", pipeline_version="0.1.0", provider=provider)
        for i, t in enumerate(texts)
    ]

    assert [r.label for r in results] == ["NEU", "NEU", "NEU"]
    assert all(call["truncation"] is True for call in stub.calls)
