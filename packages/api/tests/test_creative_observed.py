"""The generator's model calls traced in Langfuse (`qualify_api.creative.observed`),
offline: spans go to an in-memory exporter, providers are fakes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import (
    GenerationRequest,
    GenerationResult,
    RenderedPrompt,
    Usage,
)
from qualify_shared import observability

from qualify_api.creative.observed import TRACED_PROVIDERS, TracedProvider, traced_providers

PRICING = JsonPricingTable("v4")


@pytest.fixture
def spans() -> Iterator[Any]:
    with observability.capture_spans() as exporter:
        yield exporter


class FakeProvider:
    def __init__(
        self, name: str, result: GenerationResult | None = None, error: Exception | None = None
    ):
        self.name = name
        self.supports = frozenset({GenerationTask.COPY})
        self._result = result
        self._error = error
        self.calls: list[str] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.calls.append(api_key)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return Decimal("0.01")


def _copy_request() -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.COPY,
        rendered_prompt=RenderedPrompt("KIT DE MARCA", "BRIEF: promo del viernes", "fp"),
    )


def _media_request(**params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=params,
    )


def _span(exporter: Any, name: str) -> dict[str, Any]:
    observability.flush()
    (span,) = [s for s in exporter.get_finished_spans() if s.name == name]
    return dict(span.attributes)


def test_only_the_models_under_test_are_wrapped() -> None:
    """Claude, Seedream and Seedance; HeyGen and Remotion stay out (2026-10-13)."""
    providers = {
        name: FakeProvider(name) for name in TRACED_PROVIDERS | {"heygen": "", "remotion": ""}
    }
    wrapped = traced_providers(providers, PRICING)
    assert {n for n, p in wrapped.items() if isinstance(p, TracedProvider)} == {
        "anthropic",
        "seedream",
        "seedance",
    }
    assert wrapped["heygen"] is providers["heygen"]
    assert wrapped["remotion"] is providers["remotion"]


def test_a_copy_call_carries_its_prompt_tokens_and_our_price(spans: Any) -> None:
    result = GenerationResult(
        payload={"hook": "Nuevo drop"},
        model_id="claude-opus-5-5",
        provider="anthropic",
        usage=Usage(
            input_tokens=1000, output_tokens=500, cache_read_tokens=2000, cache_creation_tokens=0
        ),
    )
    inner = FakeProvider("anthropic", result)
    with observability.trace("generar creator_script"):
        got = TracedProvider(inner, PRICING).generate(_copy_request(), api_key="sk-k")

    assert got is result and inner.calls == ["sk-k"]  # the call itself is untouched
    attrs = _span(spans, "copy")
    assert attrs["langfuse.observation.model.name"] == "claude-opus-5-5"
    sent_input = json.loads(attrs["langfuse.observation.input"])
    assert sent_input["system"] == "KIT DE MARCA" and sent_input["user"].startswith("BRIEF")
    assert json.loads(attrs["langfuse.observation.output"]) == {"hook": "Nuevo drop"}
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {
        "input": 1000,
        "output": 500,
        "cache_read": 2000,
        "cache_creation": 0,
    }
    # Opus 5.5 at $4 / $20 per MTok, cache billed at the full input rate like the service:
    # 3000 * 4 / 1e6 = 0.012 and 500 * 20 / 1e6 = 0.01
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {
        "input": 0.012,
        "output": 0.01,
    }


def test_an_image_call_counts_its_references_and_never_sends_them(
    spans: Any,
) -> None:
    result = GenerationResult(
        payload={"images": [b"\xff\xd8\xff" * 1000]},
        model_id="seedream-5-0-lite-260128",
        provider="seedream",
        usage=Usage(pieces=1),
    )
    request = _media_request(
        prompt="Una hamburguesa en la mesa",
        images=["data:image/jpeg;base64,AAAA", "data:image/jpeg;base64,BBBB"],
        size="1728x2160",
    )
    with observability.trace("generar static_flyer"):
        TracedProvider(FakeProvider("seedream", result), PRICING).generate(request, api_key="k")

    attrs = _span(spans, "imagen")
    sent_input = json.loads(attrs["langfuse.observation.input"])
    assert sent_input["images_count"] == 2 and "images" not in sent_input
    assert sent_input["params"]["prompt"] == "Una hamburguesa en la mesa"
    assert json.loads(attrs["langfuse.observation.output"]) == {"images": 1}
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {"images": 1}
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"images": 0.035}


def test_a_video_call_is_priced_per_token_at_its_resolution(spans: Any) -> None:
    result = GenerationResult(
        payload={"task_id": "cgt-1", "resolution": "720p", "video_url": "https://vendor/24h"},
        model_id="seedance-1-0-pro-250528",
        provider="seedance",
        usage=Usage(output_tokens=108_000, media_seconds=Decimal(5)),
    )
    with observability.trace("generar carousel"):
        TracedProvider(FakeProvider("seedance", result), PRICING).generate(
            _media_request(prompt="zoom lento"), api_key="k"
        )
    attrs = _span(spans, "video")
    # the vendor's 24 h URL is not kept; the task id is
    assert json.loads(attrs["langfuse.observation.output"]) == {
        "task_id": "cgt-1",
        "resolution": "720p",
    }
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {
        "video_tokens": 108_000,
        "seconds": 5,
    }
    # 108 000 tokens at $2.5 / M
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"video": 0.27}


def test_a_vendor_failure_propagates_and_is_recorded(spans: Any) -> None:
    inner = FakeProvider("seedream", error=RuntimeError("HTTP 503"))
    with pytest.raises(RuntimeError, match="HTTP 503"):
        with observability.trace("generar static_flyer"):
            TracedProvider(inner, PRICING).generate(_media_request(prompt="x"), api_key="k")
    attrs = _span(spans, "imagen")
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert "HTTP 503" in attrs["langfuse.observation.status_message"]


def test_an_unpriced_model_is_still_traced_without_cost(spans: Any) -> None:
    result = GenerationResult(
        payload={"hook": "x"},
        model_id="claude-unknown-9",
        provider="anthropic",
        usage=Usage(input_tokens=10, output_tokens=5),
    )
    with observability.trace("t"):
        TracedProvider(FakeProvider("anthropic", result), PRICING).generate(
            _copy_request(), api_key="k"
        )
    attrs = _span(spans, "copy")
    assert attrs["langfuse.observation.model.name"] == "claude-unknown-9"
    assert "langfuse.observation.cost_details" not in attrs


def test_without_tracing_the_wrapper_is_transparent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(observability.PUBLIC_KEY_ENV, raising=False)
    observability.reset()
    result = GenerationResult(
        payload={"hook": "x"}, model_id="claude-opus-5-5", provider="anthropic", usage=Usage()
    )
    traced = TracedProvider(FakeProvider("anthropic", result), PRICING)
    assert traced.generate(_copy_request(), api_key="k") is result
    assert traced.estimate_cost_usd(_copy_request(), PRICING, api_key="k") == Decimal("0.01")
    assert (traced.name, traced.supports) == ("anthropic", frozenset({GenerationTask.COPY}))
    observability.reset()
