"""Anthropic copy adapter, exercised entirely offline with a fake client."""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_creative.adapters import AnthropicCopyAdapter, CopyRefused
from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt

SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"hook": {"type": "string"}, "caption": {"type": "string"}},
    "required": ["hook", "caption"],
    "additionalProperties": False,
}

STABLE_PREFIX = "BRAND KIT + VOICE PROFILE (byte-identical per brand/voice version)"
VOLATILE_SUFFIX = "BRIEF: new product post for the Friday drop"


def make_request(output_schema: dict[str, object] | None = SCHEMA) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.COPY,
        rendered_prompt=RenderedPrompt(
            stable_prefix=STABLE_PREFIX,
            volatile_suffix=VOLATILE_SUFFIX,
            prefix_fingerprint="fp-abc123",
        ),
        output_schema=output_schema,
    )


class FakeMessages:
    def __init__(self, response: Any = None, count_result: Any = None) -> None:
        self._response = response
        self._count_result = count_result
        self.create_kwargs: dict[str, Any] | None = None
        self.count_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        return self._response

    def count_tokens(self, **kwargs: Any) -> Any:
        self.count_kwargs = kwargs
        return self._count_result


class FakeClient:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


class RefusalResponse:
    """A refusal is HTTP 200 with empty content; reading content here is the bug the
    adapter must not have, so both accessors detonate."""

    stop_reason = "refusal"

    @property
    def content(self) -> Any:
        raise AssertionError("content was read before checking stop_reason")

    @property
    def usage(self) -> Any:
        raise AssertionError("usage was read before checking stop_reason")


def ok_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason="end_turn",
        model="claude-opus-5",
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=350,
            cache_read_input_tokens=1000,
            cache_creation_input_tokens=64,
        ),
    )


def make_adapter(messages: FakeMessages) -> tuple[AnthropicCopyAdapter, list[str]]:
    seen_keys: list[str] = []
    client = FakeClient(messages)

    def factory(api_key: str) -> FakeClient:
        seen_keys.append(api_key)
        return client

    return AnthropicCopyAdapter(client_factory=factory), seen_keys


def test_generate_request_shape_and_result() -> None:
    payload = {"hook": "Nuevo drop", "caption": "Solo este viernes"}
    messages = FakeMessages(response=ok_response(payload))
    adapter, seen_keys = make_adapter(messages)

    result = adapter.generate(make_request(), api_key="sk-tenant-key")

    # The explicit key reached the factory — no environment fallback path exists.
    assert seen_keys == ["sk-tenant-key"]

    kwargs = messages.create_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["max_tokens"] == 16000
    # Prompt caching: the stable prefix takes the cache_control breakpoint.
    assert kwargs["system"] == [
        {"type": "text", "text": STABLE_PREFIX, "cache_control": {"type": "ephemeral"}}
    ]
    # The volatile brief rides the user message, after the breakpoint.
    assert kwargs["messages"] == [{"role": "user", "content": VOLATILE_SUFFIX}]
    assert kwargs["thinking"] == {"type": "adaptive"}
    # Structured output via output_config.format, never prefill.
    assert kwargs["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    # Sampling params 400 on claude-opus-5 — they must never appear.
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs

    assert result.payload == payload
    assert result.provider == "anthropic"
    assert result.model_id == "claude-opus-5"
    assert result.usage.input_tokens == 1200
    assert result.usage.output_tokens == 350
    assert result.usage.cache_read_tokens == 1000
    assert result.usage.cache_creation_tokens == 64
    assert result.usage.pieces == 0


def test_generate_without_schema_omits_output_config() -> None:
    messages = FakeMessages(response=ok_response({"hook": "x"}))
    adapter, _ = make_adapter(messages)

    adapter.generate(make_request(output_schema=None), api_key="sk-k")

    assert messages.create_kwargs is not None
    assert "output_config" not in messages.create_kwargs


def test_refusal_raises_before_reading_content() -> None:
    messages = FakeMessages(response=RefusalResponse())
    adapter, _ = make_adapter(messages)

    with pytest.raises(CopyRefused) as excinfo:
        adapter.generate(make_request(), api_key="sk-k")
    assert excinfo.value.model_id == "claude-opus-5"


def test_estimate_cost_usd_counts_input_and_prices_allowance() -> None:
    # 100_000 input tokens at $5/MTok = $0.50; 2_000 allowance at $25/MTok = $0.05.
    messages = FakeMessages(count_result=SimpleNamespace(input_tokens=100_000))
    adapter, seen_keys = make_adapter(messages)

    estimate = adapter.estimate_cost_usd(make_request(), JsonPricingTable(), api_key="sk-count-key")

    assert estimate == Decimal("0.55")
    assert seen_keys == ["sk-count-key"]
    assert messages.count_kwargs is not None
    assert messages.count_kwargs["model"] == "claude-opus-5"
    # The counted prompt mirrors the generate prompt (system prefix + user brief).
    assert messages.count_kwargs["system"] == [{"type": "text", "text": STABLE_PREFIX}]
    assert messages.count_kwargs["messages"] == [{"role": "user", "content": VOLATILE_SUFFIX}]


def test_estimate_without_api_key_refuses_environment_fallback() -> None:
    adapter, _ = make_adapter(FakeMessages())
    with pytest.raises(ValueError, match="api_key"):
        adapter.estimate_cost_usd(make_request(), JsonPricingTable())


def test_supports_copy_only() -> None:
    adapter, _ = make_adapter(FakeMessages())
    assert adapter.name == "anthropic"
    assert adapter.supports == frozenset({GenerationTask.COPY})


def test_the_output_schema_is_strict_for_structured_outputs() -> None:
    """The API rejects an object schema without `additionalProperties: false` (HTTP 400,
    measured 2026-09-25) — every object in the copy schema, nested ones included."""
    from qualify_creative.adapters.anthropic_copy import strict_schema
    from qualify_creative.schemas import CopyPayload

    schema = strict_schema(CopyPayload.model_json_schema())

    def objects(node: object) -> list[dict]:
        found: list[dict] = []
        if isinstance(node, dict):
            if node.get("type") == "object":
                found.append(node)
            for value in node.values():
                found.extend(objects(value))
        elif isinstance(node, list):
            for value in node:
                found.extend(objects(value))
        return found

    assert objects(schema) and all(o["additionalProperties"] is False for o in objects(schema))
    hook = schema["properties"]["hook"]
    assert "maxLength" not in hook and "maxLength: 60" in hook["description"]


def test_the_strict_schema_matches_the_sdks_own_transform() -> None:
    anthropic = pytest.importorskip("anthropic")
    from qualify_creative.adapters.anthropic_copy import strict_schema
    from qualify_creative.schemas import CopyPayload

    raw = CopyPayload.model_json_schema()
    assert strict_schema(raw) == anthropic.transform_schema(raw)
