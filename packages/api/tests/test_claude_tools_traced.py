"""Phase 3 of docs/plan-observabilidad-langfuse.md: the Brand Kit's and the inbox's Claude
calls traced in Langfuse — offline, into memory, with fake clients."""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from qualify_shared import observability

from qualify_api.claude_tools import Attribution as _Attribution
from qualify_api.claude_tools import (
    ClaudeToolError,
    Meter,
    ModelConfig,
    create_turn,
    messages_create,
    strict_tool,
)
from qualify_api.replies.claude_drafts import ClaudeReplyDraftProvider

#: m-24955649: who pays for the faked Claude calls of this module.
TEST_ATTRIBUTION = _Attribution.no_business("test")


@pytest.fixture
def spans() -> Iterator[Any]:
    with observability.capture_spans() as exporter:
        yield exporter


def _finished(exporter: Any) -> list[Any]:
    observability.flush()
    return list(exporter.get_finished_spans())


def _attrs(exporter: Any, name: str) -> dict[str, Any]:
    (span,) = [s for s in _finished(exporter) if s.name == name]
    return dict(span.attributes)


class FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def _response(
    *, stop_reason: str = "tool_use", model: str = "claude-sonnet-5", text: str = ""
) -> SimpleNamespace:
    content = [
        SimpleNamespace(type="thinking", thinking=""),
        *([SimpleNamespace(type="text", text=text)] if text else []),
        SimpleNamespace(type="tool_use", name="proponer", input={"campo": "valor"}),
    ]
    return SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=0,
        ),
    )


def _client(response: Any) -> SimpleNamespace:
    return SimpleNamespace(messages=FakeMessages(response))


def test_a_turn_is_a_generation_with_its_files_replaced_by_markers(spans: Any) -> None:
    """A brief's PDF or a logo is a tenant's file: it never reaches Langfuse, not even as
    base64 (which the generic masking would not recognise without a `data:` prefix)."""
    config = ModelConfig("claude-sonnet-5", effort="medium")
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": "JVBERi0x",
                    },
                },
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0K"},
                },
                {"type": "text", "text": "Lee el brief"},
            ],
        }
    ]
    with observability.trace("leer documento"):
        create_turn(
            _client(_response()),
            config,
            Meter(config),
            system="Eres el lector de briefs",
            messages=messages,
            tools=[strict_tool("proponer", "d", {"campo": {"type": "string"}})],
            tool_choice={"type": "auto"},
            max_tokens=16000,
            attribution=TEST_ATTRIBUTION,
        )

    attrs = _attrs(spans, "claude")
    sent = json.loads(attrs["langfuse.observation.input"])
    blocks = sent["messages"][0]["content"]
    assert blocks[0] == {"type": "document", "omitted": True, "media_type": "application/pdf"}
    assert blocks[1] == {"type": "image", "omitted": True, "media_type": "image/png"}
    assert blocks[2]["text"] == "Lee el brief"
    assert sent["tools"] == ["proponer"] and sent["system"] == "Eres el lector de briefs"
    assert "JVBERi0x" not in json.dumps(attrs) and "iVBORw0K" not in json.dumps(attrs)
    # the answer: tool calls and text, never the thinking blocks
    assert json.loads(attrs["langfuse.observation.output"]) == [
        {"type": "tool_use", "name": "proponer", "input": {"campo": "valor"}}
    ]
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {
        "input": 1000,
        "output": 200,
        "cache_read": 500,
        "cache_creation": 0,
    }
    # Sonnet 5 at $2 / $10, cache reads at $0.20: one price per kind, same keys as usage
    assert json.loads(attrs["langfuse.observation.cost_details"]) == pytest.approx(
        {
            "input": 0.002,
            "cache_read": 0.0001,
            "cache_creation": 0.0,
            "output": 0.002,
            "total": 0.0041,
        }
    )
    assert attrs["langfuse.observation.metadata.effort"] == "medium"


def test_a_refusal_is_marked_and_still_raised_by_the_turn(spans: Any) -> None:
    config = ModelConfig("claude-sonnet-5", effort="low")
    with pytest.raises(ClaudeToolError, match="refused"):
        with observability.trace("revisar referentes"):
            create_turn(
                _client(_response(stop_reason="refusal")),
                config,
                Meter(config),
                system="s",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                tool_choice={"type": "auto"},
                max_tokens=2048,
                attribution=TEST_ATTRIBUTION,
            )
    attrs = _attrs(spans, "claude")
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert "refusal" in attrs["langfuse.observation.status_message"]


def test_messages_create_without_tracing_is_a_plain_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(observability.PUBLIC_KEY_ENV, raising=False)
    observability.reset()
    client = _client(_response(stop_reason="end_turn", text="hola"))
    response = messages_create(
        client,
        ModelConfig("claude-haiku-4-5"),
        model="claude-haiku-4-5",
        attribution=TEST_ATTRIBUTION,
    )
    assert response is client.messages.response
    assert client.messages.kwargs == {"model": "claude-haiku-4-5"}
    observability.reset()


def test_a_traced_function_is_one_trace_and_a_nested_one_a_child_span(spans: Any) -> None:
    """«analizar voz» calls «sugerir tono»: one trace, named after the outer unit."""

    @observability.traced("sugerir tono", tags=("brand_kit",))
    def inner() -> str:
        with observability.generation("claude") as call:
            call.finish(output="tono")
        return "ok"

    @observability.traced("analizar voz", tags=("brand_kit",))
    def outer() -> str:
        return inner()

    assert outer() == "ok"
    found = {span.name: span for span in _finished(spans)}
    assert set(found) == {"analizar voz", "sugerir tono", "claude"}
    root, child, call = found["analizar voz"], found["sugerir tono"], found["claude"]
    assert root.parent is None
    assert child.parent.span_id == root.context.span_id
    assert call.parent.span_id == child.context.span_id
    # the nested unit does not rename the trace
    assert child.attributes["langfuse.trace.name"] == "analizar voz"
    assert call.attributes["langfuse.trace.name"] == "analizar voz"
    assert "langfuse.trace.metadata.function" in root.attributes


def test_an_inbox_reply_is_its_own_trace(spans: Any) -> None:
    client = _client(_response(stop_reason="end_turn", model="claude-haiku-5-5", text="¡Gracias!"))
    provider = ClaudeReplyDraftProvider(client_factory=lambda key: client, api_key="sk-k")

    assert (
        provider.draft_reply(comment_text="Me encantó", attribution=TEST_ATTRIBUTION) == "¡Gracias!"
    )

    found = {span.name: span for span in _finished(spans)}
    assert found["claude"].parent.span_id == found["respuesta inbox"].context.span_id
    root = dict(found["respuesta inbox"].attributes)
    assert tuple(root["langfuse.trace.tags"]) == ("inbox",)
    call = dict(found["claude"].attributes)
    assert call["langfuse.observation.model.name"] == "claude-haiku-5-5"
    assert json.loads(call["langfuse.observation.input"])["messages"] == [
        {"role": "user", "content": "Me encantó"}
    ]


def test_every_brand_kit_model_call_is_a_traced_unit() -> None:
    """The nine functions that call Claude for the Brand Kit, the caption and the voice
    carry `observability.traced` (their `__wrapped__` is the original)."""
    from qualify_api.creative import brief_ai, font_ai, voice_analysis
    from qualify_api.hashtags import ai, caption, from_profile
    from qualify_api.referentes import ai as referentes_ai

    functions = [
        brief_ai._propose,
        font_ai.identify_fonts,
        voice_analysis.suggest_tone,
        voice_analysis.analyze_recording,
        ai.classify_hashtags,
        ai.select_hashtags,
        caption.suggest_for_caption,
        from_profile.generate,
        referentes_ai.review_accounts,
    ]
    assert all(hasattr(function, "__wrapped__") for function in functions)


def test_the_client_is_anthropic_itself() -> None:
    """§ 2026-10-19: the OmniRoute gateway option was reverted — every call goes to
    api.anthropic.com."""
    pytest.importorskip("anthropic")
    from qualify_api.claude_tools import default_client

    assert "api.anthropic.com" in str(default_client("k").base_url)


def test_a_pricing_failure_loses_the_cost_never_the_tokens(
    spans: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api import claude_tools

    def broken(*_: Any, **__: Any) -> dict[str, float]:
        raise KeyError("no price")

    monkeypatch.setattr(claude_tools, "cost_breakdown", broken)
    messages_create(
        _client(_response()),
        ModelConfig("claude-sonnet-5"),
        model="m",
        attribution=TEST_ATTRIBUTION,
    )
    attrs = _attrs(spans, "claude")
    assert json.loads(attrs["langfuse.observation.usage_details"])["input"] == 1000
    assert "langfuse.observation.cost_details" not in attrs


def test_one_claude_call_is_one_generation_with_the_responses_tokens(spans: Any) -> None:
    """m-24955563: the anthropic SDK (>= 1.15) traces every `messages.create` itself, as
    an `anthropic.messages.create` span with `gen_ai.*` usage, which Langfuse exported as
    a second generation and doubled the trace's tokens. Through the real SDK (an HTTP
    mock, no network) the SDK still emits its span, but only ours leaves the process -
    and its tokens are exactly the response's."""
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    body = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "content": [{"type": "tool_use", "id": "tu_1", "name": "proponer", "input": {}}],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 1234,
            "output_tokens": 56,
            "cache_read_input_tokens": 7,
            "cache_creation_input_tokens": 8,
        },
    }
    everything = InMemorySpanExporter()  # what the SDK emits, before Langfuse filters
    spans.tracer_provider.add_span_processor(SimpleSpanProcessor(everything))
    client = anthropic.Anthropic(
        api_key="sk-ant-test",
        max_retries=0,
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(lambda request: httpx2.Response(200, json=body))
        ),
        open_telemetry={"tracer_provider": spans.tracer_provider},
    )
    config = ModelConfig("claude-haiku-4-5")
    with observability.trace("describir reel"):
        create_turn(
            client,
            config,
            Meter(config),
            system="s",
            messages=[{"role": "user", "content": "hola"}],
            tools=[strict_tool("proponer", "d", {})],
            tool_choice={"type": "auto"},
            max_tokens=64,
            attribution=TEST_ATTRIBUTION,
        )

    emitted = {span.instrumentation_scope.name for span in everything.get_finished_spans()}
    assert observability.ANTHROPIC_SDK_SCOPE in emitted  # the SDK did trace the call
    exported = _finished(spans)
    generations = [
        span
        for span in exported
        if (span.attributes or {}).get("langfuse.observation.type") == "generation"
        or any(key.startswith("gen_ai.usage") for key in (span.attributes or {}))
    ]
    assert [span.name for span in generations] == ["claude"]
    assert all(
        span.instrumentation_scope.name != observability.ANTHROPIC_SDK_SCOPE for span in exported
    )
    usage = json.loads(generations[0].attributes["langfuse.observation.usage_details"])
    assert usage == {"input": 1234, "output": 56, "cache_read": 7, "cache_creation": 8}
    # the total Langfuse adds up for the trace is ours alone (it does not sum cost parts)
    cost = json.loads(generations[0].attributes["langfuse.observation.cost_details"])
    assert cost["total"] == pytest.approx(sum(v for k, v in cost.items() if k != "total"))
    assert cost["total"] > 0
