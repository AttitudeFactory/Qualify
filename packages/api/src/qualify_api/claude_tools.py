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

Every `messages.create` goes through `messages_create`, which records it as one Langfuse
generation (docs/plan-observabilidad-langfuse.md §5) — a no-op without LANGFUSE_* keys.
The caller's function is the trace (`observability.traced`); each turn nests in it.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from qualify_shared import observability

from qualify_api.privacy import mask_phones

API_KEY_ENV = "QUALIFY_ANTHROPIC_API_KEY"

#: The non-streaming `max_tokens` ceiling (larger values make the SDK demand streaming).
MAX_NON_STREAMING_TOKENS = 16000

#: $ per million tokens (input, output), from the `claude-api` skill's model table
#: (cached 2026-06-24; Haiku 5.5 added 2026-10-08; Opus 5.5 and Sonnet 5.5 2026-10-13).
#: Reported per run (`CallStats.cost_usd`, Langfuse) and the base of the Alta prefill's
#: cost cap (`qualify_api.meegle.prefill`). Haiku 5.5 is its <=100K-token-prompt card
#: ($0.50 / $2.50 above that); no Qualify prompt comes near it.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
}

#: $ per million cache-read tokens ("Cache hits and refreshes"). Not one multiplier: 0.1x
#: input on most models, 0.05x on Opus 5.5 and Sonnet 5.5. Source: the official pricing
#: table, https://platform.claude.com/docs/en/about-claude/pricing (read 2026-10-25,
#: m-24852539) — every row below checked against it. The `claude-api` skill (cached
#: 2026-10-06) still says $0.20 for Sonnet 5.5; the live page's $0.10 wins.
CACHE_READ_PRICES: dict[str, float] = {
    "claude-haiku-5-5": 0.01,
    "claude-haiku-4-5": 0.10,
    "claude-sonnet-5-5": 0.10,
    "claude-sonnet-5": 0.20,
    "claude-opus-5-5": 0.20,
    "claude-opus-5": 0.50,
}

#: Cache writes cost 1.25x the input rate with the 5-minute TTL (2x with 1 hour). Every
#: `cache_control` this module sends is the default 5-minute `ephemeral`, so writes are
#: priced at 1.25x (same source as `CACHE_READ_PRICES`).
CACHE_WRITE_MULTIPLIER = 1.25

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
    cache_creation_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        """Every token at its own rate (`cost_breakdown`); 0.0 for an unpriced model."""
        return sum(
            cost_breakdown(
                self.model_id,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cache_read_tokens=self.cache_read_tokens,
                cache_creation_tokens=self.cache_creation_tokens,
            ).values()
        )


def cost_breakdown(
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> dict[str, float]:
    """USD per token kind — uncached input, cache reads, cache writes, output: the one
    pricing behind both `CallStats.cost_usd` and the Langfuse cost details. Empty when
    the model has no price (refuse to guess)."""
    if model_id not in PRICES or model_id not in CACHE_READ_PRICES:
        return {}
    price_in, price_out = PRICES[model_id]
    return {
        "input": input_tokens * price_in / 1_000_000,
        "cache_read": cache_read_tokens * CACHE_READ_PRICES[model_id] / 1_000_000,
        "cache_creation": cache_creation_tokens * price_in * CACHE_WRITE_MULTIPLIER / 1_000_000,
        "output": output_tokens * price_out / 1_000_000,
    }


def api_key_from_env() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingAPIKey(f"{API_KEY_ENV} is not set")
    return key


def default_client(api_key: str) -> Any:
    """Anthropic itself (§ 2026-10-19: the OmniRoute gateway option was reverted)."""
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
    cache_creation: int = 0
    turns: int = 0
    tool_calls: int = 0

    def add(self, response: Any) -> None:
        self.turns += 1
        self.revision = getattr(response, "model", None) or self.revision
        usage = response.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def stats(self) -> CallStats:
        return CallStats(
            self.config.model_id,
            self.revision,
            self.input_tokens,
            self.output_tokens,
            self.cache_read,
            self.turns,
            self.tool_calls,
            self.cache_creation,
        )


#: Content blocks that carry a tenant's file — replaced by a marker before tracing.
_FILE_BLOCKS = frozenset({"image", "document"})


def _traceable(value: Any) -> Any:
    """What Langfuse may see of a request or an answer: every image or document block (a
    brief's PDF, a logo, a brandboard page) becomes a marker — base64 without a `data:`
    prefix would slip past the generic masking — and every phone number in a text is
    masked (`qualify_api.privacy.mask_phones`, m-24854323: bios and captions carry them,
    and the full number never leaves the tenant)."""
    if isinstance(value, str):
        return mask_phones(value)
    if isinstance(value, list):
        return [_traceable(item) for item in value]
    if isinstance(value, dict):
        if value.get("type") in _FILE_BLOCKS:
            source = value.get("source") if isinstance(value.get("source"), dict) else {}
            return {"type": value["type"], "omitted": True, "media_type": source.get("media_type")}
        return {key: _traceable(item) for key, item in value.items()}
    return value


def _response_blocks(response: Any) -> list[dict[str, Any]]:
    """The answer as text and tool calls; thinking blocks are left out (empty by default,
    and never the user's business)."""
    out: list[dict[str, Any]] = []
    for block in getattr(response, "content", None) or ():
        kind = getattr(block, "type", None)
        if kind == "text":
            out.append({"type": "text", "text": block.text})
        elif kind == "tool_use":
            out.append({"type": "tool_use", "name": block.name, "input": block.input})
    return out


def _usage_and_cost(response: Any, model_id: str) -> tuple[dict[str, int], dict[str, float]]:
    """Tokens, and their price per kind from `cost_breakdown` — the same keys, so Langfuse
    prices each kind and the total equals `CallStats.cost_usd`."""
    usage = response.usage
    tokens = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }
    return tokens, cost_breakdown(
        model_id,
        input_tokens=tokens["input"],
        output_tokens=tokens["output"],
        cache_read_tokens=tokens["cache_read"],
        cache_creation_tokens=tokens["cache_creation"],
    )


def _system_text(system: Any) -> Any:
    """The system prompt as plain text: `create_turn` sends it as a cached text block."""
    if isinstance(system, list):
        return "\n\n".join(block.get("text", "") for block in system if isinstance(block, dict))
    return system


def messages_create(client: Any, config: ModelConfig, **kwargs: Any) -> Any:
    """`client.messages.create(**kwargs)`, recorded as one Langfuse generation: the
    request (files replaced by markers), the answer, the tokens and their price. A
    refusal or a truncation is marked on it; the caller still decides what it means."""
    with observability.generation(
        "claude",
        model=config.model_id,
        input={
            "system": _traceable(_system_text(kwargs.get("system"))),
            "messages": _traceable(kwargs.get("messages")),
            "tools": [tool.get("name") for tool in kwargs.get("tools") or ()],
        },
        metadata={"effort": config.effort, "max_tokens": kwargs.get("max_tokens")},
    ) as observation:
        response = client.messages.create(**kwargs)
        model = getattr(response, "model", None) or config.model_id
        try:
            usage, cost = _usage_and_cost(response, config.model_id)
        except Exception:  # noqa: BLE001 — an odd usage object is still traced
            usage, cost = {}, {}
        observation.finish(
            output=_traceable(_response_blocks(response)),
            model=model,
            usage=usage,
            cost=cost,
            metadata={"stop_reason": response.stop_reason},
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            observation.fail(ClaudeToolError(f"stop_reason={response.stop_reason}"))
        return response


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
    response = messages_create(client, config, **kwargs)
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
