"""Asking Claude for the visual angles of a product (ticket 24803289) — the network half
of `qualify_creative.angles`, the same strict-tool pattern as `brief_ai` / `font_ai`.

One call, one tool (`proponer_angulos_visuales`), the answer bounded and de-duplicated by
the pure module; a model that does not call the tool is asked once more, then refused.
A top-up call passes the angles already kept as `avoid`: they are named in the prompt
as not to repeat, and the answer is de-duplicated against them too.

Anthropic not answering (rate limit, overload, server error, timeout, network) is
retried by the SDK itself; once it gives up, the error arrives as `AnglesProviderError`
— a `ClaudeToolError`, so the caller records a failed set instead of leaking a vendor
exception — saying whether trying again later may work.
The catalog's price goes into the prompt as DATA to keep exact — and whatever the model
answers, the pieces print the catalog's label, never the model's (see `angle_brief`).

Model: Claude Sonnet 5 at medium effort — judgement enough to tell ten scenarios apart,
cents per set; the copy of each piece is written later by the copy adapter as usual.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from typing import Any

from qualify_creative.angles import (
    ANGLES_TOOL,
    DEFAULT_ANGLE_COUNT,
    MAX_ANGLE_COUNT,
    AngleBrand,
    AnglePreset,
    AngleProduct,
    CreativeAngle,
    angles_system_prompt,
    angles_tool,
    angles_user_prompt,
    parse_angles,
)
from qualify_shared import observability

from ..claude_tools import (
    CallStats,
    ClaudeToolError,
    ClientFactory,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    tool_uses,
)

logger = logging.getLogger(__name__)

ANGLES_MODEL = "claude-sonnet-5"
ANGLES_EFFORT = "medium"
#: Ten structured angles are a few hundred tokens each; generous so thinking fits too.
MAX_TOKENS = 6000


class AnglesProviderError(ClaudeToolError):
    """Anthropic did not answer after the SDK's own retries. `status` is the HTTP status
    (None for a timeout or a network failure); `retryable` says whether the same request
    may succeed later (429, 408, 409, 5xx, timeout, network) or will not (another 4xx)."""

    def __init__(self, message: str, *, status: int | None, retryable: bool) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _provider_error(exc: BaseException) -> AnglesProviderError | None:
    """The SDK's typed error as `AnglesProviderError`; None when `exc` is not one."""
    try:
        import anthropic  # noqa: PLC0415 — optional dependency (`qualify-creative[llm]`)
    except ImportError:  # pragma: no cover — no SDK, so no SDK error either
        return None
    if isinstance(exc, anthropic.APITimeoutError):
        return AnglesProviderError("anthropic timed out", status=None, retryable=True)
    if isinstance(exc, anthropic.APIConnectionError):
        return AnglesProviderError("anthropic unreachable", status=None, retryable=True)
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        retryable = status in (408, 409, 429) or status >= 500
        return AnglesProviderError(
            f"anthropic answered HTTP {status}", status=status, retryable=retryable
        )
    return None


def prompt_fingerprint(system: str, user: str) -> str:
    """What identifies the exact prompt a set was generated with (provenance)."""
    return hashlib.sha256(f"{system}\n\n{user}".encode()).hexdigest()[:16]


@observability.traced("proponer ángulos visuales", tags=("creative", "angles"))
def generate_angles(
    product: AngleProduct,
    brand: AngleBrand,
    preset: AnglePreset,
    *,
    api_key: str,
    count: int = DEFAULT_ANGLE_COUNT,
    avoid: Sequence[CreativeAngle] = (),
    config: ModelConfig = ModelConfig(ANGLES_MODEL, ANGLES_EFFORT),
    client_factory: ClientFactory | None = None,
) -> tuple[tuple[CreativeAngle, ...], CallStats, str]:
    """Ask Claude for `count` visual angles that differ from `avoid` (the angles a
    previous call already gave). Returns the NEW angles only (bounded, de-duplicated
    among themselves and against `avoid`, at most `count`, positions continuing after
    `avoid`), the call's stats and the prompt fingerprint. Raises `ClaudeToolError`
    (refusal, truncation, no tool call) or its `AnglesProviderError` (Anthropic did
    not answer)."""
    system = angles_system_prompt()
    # a set holds at most MAX_ANGLE_COUNT angles: never pay for ones that cannot fit
    count = min(count, MAX_ANGLE_COUNT - len(avoid))
    user = angles_user_prompt(product, brand, preset, count=max(count, 0), avoid=avoid)
    meter = Meter(config)
    if count <= 0:
        return (), meter.stats(), prompt_fingerprint(system, user)
    client = (client_factory or default_client)(api_key)
    tool = angles_tool(count)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    for attempt in range(2):
        try:
            response = create_turn(
                client,
                config,
                meter,
                system=system,
                messages=messages,
                tools=[tool],
                tool_choice=forced_or_auto(config, ANGLES_TOOL),
                max_tokens=MAX_TOKENS,
            )
        except Exception as exc:
            typed = _provider_error(exc)
            if typed is None:
                raise
            logger.warning("angles call failed: %s (retryable=%s)", typed, typed.retryable)
            raise typed from exc
        calls = [u for u in tool_uses(response) if u.name == ANGLES_TOOL]
        if calls:
            meter.tool_calls += 1
            # the count is the total counting `avoid`; only the new angles come back
            angles = parse_angles(calls[0].input or {}, count=len(avoid) + count, existing=avoid)
            return angles, meter.stats(), prompt_fingerprint(system, user)
        if attempt == 0:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": f"Entrega la respuesta con {ANGLES_TOOL}."})
    raise ClaudeToolError(f"{config.model_id} did not call {ANGLES_TOOL}")


__all__ = [
    "ANGLES_EFFORT",
    "AnglesProviderError",
    "ANGLES_MODEL",
    "MAX_TOKENS",
    "generate_angles",
    "prompt_fingerprint",
]
