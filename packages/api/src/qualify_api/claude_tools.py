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

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
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
    """The run could not produce a usable answer (refusal, truncation, no final tool).
    `stats` is what the run spent before it failed (every turn that got an answer), when
    the raiser knew it — a caller's books stay exact without guessing."""

    def __init__(self, *args: object, stats: CallStats | None = None) -> None:
        super().__init__(*args)
        self.stats = stats


class BudgetExhausted(ClaudeToolError):
    """The run's `DollarMeter` cannot pay for the next turn even with the least useful
    output: the turn is not made — nothing is sent."""


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


# --------------------------------------------------------------------------------------
# The dollar meter (m-24854322): a run's spend bounded per TURN, not per call
# --------------------------------------------------------------------------------------

#: The least output a turn is sent with: below it a thinking model cannot reach its tool
#: call, so a lowered turn would only pay for a truncation.
MIN_TURN_OUTPUT_TOKENS = 512
#: Tokens added to the first turn's byte count: the tool-use system prompt the API adds
#: around `tools` and the per-message framing, neither of which is in the request bytes.
FIRST_TURN_MARGIN_TOKENS = 1_000

#: Money is booked to the nano-dollar: every price x token count is exact at 9 decimals,
#: so rounding there only removes float noise, never a real fraction.
_NANO = Decimal("0.000000001")


def _usd(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(_NANO, rounding=ROUND_HALF_EVEN)


def worst_turn_usd(model_id: str, input_tokens: int, max_tokens: int) -> Decimal | None:
    """The most one turn can bill: every input token as a 5-minute cache WRITE (the
    dearest an input token can be: x1.25) and `max_tokens` of output, through
    `cost_breakdown`. None for an unpriced model (refuse to guess)."""
    parts = cost_breakdown(
        model_id, input_tokens=0, output_tokens=max_tokens, cache_creation_tokens=input_tokens
    )
    if not parts:
        return None
    return _usd(sum(parts.values()))


def billed_usd(model_id: str, usage: Any) -> Decimal | None:
    """What a turn's `usage` bills, every token at its own rate; None when unpriced."""
    parts = cost_breakdown(
        model_id,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )
    if not parts:
        return None
    return _usd(sum(parts.values()))


@dataclass
class DollarMeter:
    """What one run may spend in USD, and what it spent — every Claude turn and every
    other paid unit (ScrapeCreators credits, `charge`) in ONE balance.

    Before each turn `fit_turn` prices the worst the turn can bill (`worst_turn_usd` over
    `turn_input_ceiling`) and RESERVES it: if it fits, the turn goes as asked; if it fits
    only with less output, `max_tokens` is lowered to what fits (`lowered_turns`); if not
    even `MIN_TURN_OUTPUT_TOKENS` fit, the turn is refused (`BudgetExhausted`,
    `refused_turns`) and nothing is sent. `settle_turn` swaps the reservation for what
    the answer billed — or keeps the whole reservation as spent when no answer came (a
    timeout may still have billed). A billed turn above its reservation is booked anyway
    and counted in `overruns` (the input bound was wrong; tests pin 0)."""

    limit_usd: Decimal
    spent_usd: Decimal = Decimal(0)
    reserved_usd: Decimal = Decimal(0)
    refused_turns: int = 0
    lowered_turns: int = 0
    overruns: int = 0
    #: (what, usd) of every booking, in order.
    entries: list[tuple[str, Decimal]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.limit_usd = Decimal(str(self.limit_usd))

    @property
    def remaining_usd(self) -> Decimal:
        return self.limit_usd - self.spent_usd - self.reserved_usd

    def charge(self, usd: Decimal, *, what: str = "") -> None:
        """Book a non-Claude cost (a ScrapeCreators credit) BEFORE it is incurred; raises
        `BudgetExhausted` — and books nothing — when it does not fit."""
        usd = Decimal(str(usd))
        if usd > self.remaining_usd:
            raise BudgetExhausted(f"{what or 'charge'} of {usd} USD does not fit the meter")
        self.spent_usd += usd
        self.entries.append((what, usd))

    def fit_turn(self, model_id: str, input_tokens: int, max_tokens: int) -> tuple[int, Decimal]:
        """`(allowed_max_tokens, reservation)` for a turn whose prompt is at most
        `input_tokens`; the reservation is held until `settle_turn`."""
        worst = worst_turn_usd(model_id, input_tokens, max_tokens)
        if worst is None:
            self.refused_turns += 1
            raise BudgetExhausted(f"{model_id} has no price: the turn cannot be bounded")
        allowed = max_tokens
        if worst > self.remaining_usd:
            input_only = worst_turn_usd(model_id, input_tokens, 0) or Decimal(0)
            per_output = Decimal(repr(PRICES[model_id][1])) / Decimal(1_000_000)
            room = self.remaining_usd - input_only
            allowed = 0
            if room > 0:
                allowed = int((room / per_output).to_integral_value(rounding=ROUND_FLOOR))
            allowed = min(allowed, max_tokens)
            # rounding to the nano-dollar: step down until the reservation fits
            while allowed >= MIN_TURN_OUTPUT_TOKENS:
                worst = worst_turn_usd(model_id, input_tokens, allowed) or worst
                if worst <= self.remaining_usd:
                    break
                allowed -= 1
            if allowed < MIN_TURN_OUTPUT_TOKENS:
                self.refused_turns += 1
                raise BudgetExhausted(
                    f"{model_id}: {self.remaining_usd} USD left does not pay a turn of "
                    f"{input_tokens} input tokens"
                )
            self.lowered_turns += 1
        self.reserved_usd += worst
        return allowed, worst

    def settle_turn(self, model_id: str, reserved: Decimal, usage: Any | None) -> Decimal:
        """Release `reserved` and book what the turn billed (`usage`), or the whole
        reservation when there is no usage (no answer came). Returns what was booked."""
        self.reserved_usd -= reserved
        billed = billed_usd(model_id, usage) if usage is not None else None
        booked = reserved if billed is None else billed
        if booked > reserved:
            self.overruns += 1
        self.spent_usd += booked
        self.entries.append((f"claude:{model_id}", booked))
        return booked

    def as_document(self) -> dict[str, Any]:
        return {
            "limit_usd": str(self.limit_usd),
            "spent_usd": str(self.spent_usd),
            "refused_turns": self.refused_turns,
            "lowered_turns": self.lowered_turns,
            "overruns": self.overruns,
        }


@dataclass(frozen=True)
class TurnBound:
    """What `turn_input_ceiling` needs of the previous turn of the same run."""

    #: The input bound that turn was priced with.
    ceiling: int
    #: Its billed prompt (input + cache read + cache write); 0 when unknown.
    billed_prompt: int
    #: Its billed output (the assistant content the next turn carries back).
    output: int
    #: The request bytes it counted (`request_bytes`).
    sent_bytes: int


def _jsonable(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    return str(value)


def request_bytes(system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    """UTF-8 bytes of what a turn sends, WITHOUT the assistant messages (their tokens are
    the previous turns' billed output, counted as such). A token is never shorter than
    one byte, so bytes bound tokens from above."""
    sent = {
        "system": system,
        "tools": tools,
        "messages": [m for m in messages if m.get("role") != "assistant"],
    }
    blob = json.dumps(sent, ensure_ascii=False, default=_jsonable)
    return len(blob.encode("utf-8"))


def turn_input_ceiling(
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    previous: TurnBound | None = None,
) -> tuple[int, int]:
    """`(input_token_bound, request_bytes)` of the next turn. The first turn: its bytes
    + `FIRST_TURN_MARGIN_TOKENS`. A later turn: the LARGER of the previous turn's billed
    prompt and its own bound (a turn that under-reports its input must never lower the
    next bound — a property test pins it), plus the previous output, plus the bytes
    added since."""
    sent = request_bytes(system, messages, tools)
    if previous is None:
        return sent + FIRST_TURN_MARGIN_TOKENS, sent
    added = max(0, sent - previous.sent_bytes)
    base = max(previous.billed_prompt, previous.ceiling)
    return base + previous.output + added, sent


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
    #: The last metered turn's bound (`turn_input_ceiling`), for the next one.
    last_bound: TurnBound | None = None

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
    budget: DollarMeter | None = None,
) -> Any:
    """One `messages.create` with the stable system prompt cached, metered, and a
    refusal or truncation turned into `ClaudeToolError` before `content` is read.

    With a `budget` (the Alta prefill, m-24854322) the turn is priced first
    (`DollarMeter.fit_turn` over `turn_input_ceiling`): it goes as asked, with a lower
    `max_tokens`, or not at all (`BudgetExhausted`: nothing is sent). Its reservation is
    settled with what it billed, or kept whole when the call raised. Every error raised
    here carries the run's `stats` so far. Without a budget nothing changes."""
    reservation: Decimal | None = None
    sent = ceiling = 0
    if budget is not None:
        ceiling, sent = turn_input_ceiling(system, messages, tools, meter.last_bound)
        try:
            max_tokens, reservation = budget.fit_turn(config.model_id, ceiling, max_tokens)
        except BudgetExhausted as exc:
            exc.stats = meter.stats()
            raise
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
    try:
        response = messages_create(client, config, **kwargs)
    except BaseException:
        if budget is not None and reservation is not None:
            budget.settle_turn(config.model_id, reservation, None)
        raise
    if budget is not None and reservation is not None:
        usage = getattr(response, "usage", None)
        budget.settle_turn(config.model_id, reservation, usage)
        meter.last_bound = TurnBound(
            ceiling=ceiling,
            billed_prompt=_billed_prompt(usage),
            output=int(getattr(usage, "output_tokens", 0) or 0),
            sent_bytes=sent,
        )
    meter.add(response)
    if response.stop_reason == "refusal":
        raise ClaudeToolError(f"{config.model_id} refused the request", stats=meter.stats())
    if response.stop_reason == "max_tokens":
        raise ClaudeToolError(f"{config.model_id} hit max_tokens={max_tokens}", stats=meter.stats())
    return response


def _billed_prompt(usage: Any) -> int:
    return int(
        (getattr(usage, "input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    )


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
