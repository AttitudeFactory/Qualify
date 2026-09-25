"""The shared plumbing for every Claude tool run in Qualify — one place for the client,
the per-turn request, usage accounting and the strict tool shape. Two callers today:
`qualify_api.hashtags.ai` (catalog tools) and `qualify_api.creative.brief_ai` (the
Brand Kit document tool).

API facts pinned from the `claude-api` skill (2026-09), not from memory:

- Model ids are the bare aliases (`claude-haiku-4-5`, `claude-sonnet-5`), never dated.
- Tools are `strict: true` (arguments guaranteed to match the schema).
- `effort` lives in `output_config` and is rejected by Haiku 4.5; Sonnet 5 runs adaptive
  thinking when `thinking` is omitted. A thinking model gets `tool_choice: auto` and the
  caller checks the expected tool was called; a forced tool is used only without
  thinking. No sampling parameters are sent (Sonnet 5 rejects them).
- A refusal is an HTTP 200 with `stop_reason == "refusal"`: checked before `content`.
- 16000 is the ceiling the SDK accepts for `max_tokens` without streaming.
- The client is always built with an explicit `api_key` (`QUALIFY_ANTHROPIC_API_KEY`):
  the no-arg constructor would fall back to ambient credentials and bill the wrong
  account.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

API_KEY_ENV = "QUALIFY_ANTHROPIC_API_KEY"

#: The non-streaming `max_tokens` ceiling (larger values make the SDK demand streaming).
MAX_NON_STREAMING_TOKENS = 16000

#: $ per million tokens (input, output), from the `claude-api` skill's model table
#: (cached 2026-06-24). Used for reporting only — nothing is budgeted from it.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}

ClientFactory = Callable[[str], Any]


class ClaudeToolError(RuntimeError):
    """The run could not produce a usable answer (refusal, truncation, no final tool)."""


class MissingAPIKey(ClaudeToolError):
    """`QUALIFY_ANTHROPIC_API_KEY` is not set — callers fall back to their rule path."""


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    #: `output_config.effort` — None for models that reject it (Haiku 4.5), which are
    #: also the ones that run without thinking and so accept a forced tool choice.
    effort: str | None = None

    @property
    def label(self) -> str:
        return f"{self.model_id}@{self.effort}" if self.effort else self.model_id

    @property
    def thinks(self) -> bool:
        return self.effort is not None


@dataclass(frozen=True)
class CallStats:
    """Provenance and cost of one run (every turn summed) — recorded with the answer."""

    model_id: str
    model_revision: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    turns: int = 0
    tool_calls: int = 0

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICES.get(self.model_id, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000


def api_key_from_env() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingAPIKey(f"{API_KEY_ENV} is not set")
    return key


def default_client(api_key: str) -> Any:
    import anthropic  # lazy: optional dependency (`qualify-creative[llm]`)

    return anthropic.Anthropic(api_key=api_key)


@dataclass
class Meter:
    """Usage summed over every turn of one run."""

    config: ModelConfig
    revision: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    turns: int = 0
    tool_calls: int = 0

    def add(self, response: Any) -> None:
        self.turns += 1
        self.revision = getattr(response, "model", None) or self.revision
        usage = response.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

    def stats(self) -> CallStats:
        return CallStats(
            self.config.model_id,
            self.revision,
            self.input_tokens,
            self.output_tokens,
            self.cache_read,
            self.turns,
            self.tool_calls,
        )


def create_turn(
    client: Any,
    config: ModelConfig,
    meter: Meter,
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any],
    max_tokens: int,
) -> Any:
    """One `messages.create` with the stable system prompt cached, metered, and a
    refusal or truncation turned into `ClaudeToolError` before `content` is read."""
    kwargs: dict[str, Any] = {
        "model": config.model_id,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    if config.effort:
        kwargs["output_config"] = {"effort": config.effort}
    response = client.messages.create(**kwargs)
    meter.add(response)
    if response.stop_reason == "refusal":
        raise ClaudeToolError(f"{config.model_id} refused the request")
    if response.stop_reason == "max_tokens":
        raise ClaudeToolError(f"{config.model_id} hit max_tokens={max_tokens}")
    return response


def tool_uses(response: Any) -> list[Any]:
    return [b for b in response.content if getattr(b, "type", None) == "tool_use"]


def strict_tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    """A `strict: true` tool whose every property is required and nothing else is
    allowed — the shape strict tool use needs."""
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def forced_or_auto(config: ModelConfig, tool_name: str) -> dict[str, Any]:
    """Force `tool_name` on a model without thinking; `auto` on a thinking one (the
    caller checks the tool was called)."""
    return {"type": "auto"} if config.thinks else {"type": "tool", "name": tool_name}
