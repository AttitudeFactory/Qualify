"""Model calls of the generator, traced in Langfuse (docs/plan-observabilidad-langfuse.md
§4-§5).

`traced_providers` wraps the router's providers at composition time, so neither the
router nor the adapters know Langfuse exists (`qualify_creative` stays vendor-free). Each
call of a wrapped provider is one Langfuse *generation* nested under the draft's trace
(`ContentService._generate`), with:

- the input — the copy prompt (system + user), or a media request's parameters with its
  reference images reduced to a count (`qualify_shared.observability` masks the rest);
- the output — the copy payload, or a summary of the media (never its bytes);
- usage in the vendor's own unit, and its cost from OUR pricing table — the same numbers
  `creative_usage_events` records, so Langfuse never prices anything itself.

Only the models under test are wrapped: Claude, Seedream and Seedance. Remotion is
left out by decision of 2026-10-13 (a deterministic render, not a model), and so was
HeyGen — retired 2026-10-16; the talking presenter's OmniHuman and Seed Speech are not
wrapped yet (their spend is in `creative_usage_events` all the same).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from qualify_creative.adapters.byteplus_ark import video_cost_usd
from qualify_creative.providers import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    PricingTable,
)
from qualify_shared import observability

from qualify_api.claude_tools import cost_breakdown

logger = logging.getLogger(__name__)

#: The providers whose calls are traced, and what Langfuse calls each observation.
TRACED_PROVIDERS: Mapping[str, str] = {
    "anthropic": "copy",
    "seedream": "imagen",
    "seedance": "video",
}

_MTOK = Decimal(1_000_000)

UsageAndCost = tuple[dict[str, int], dict[str, float]]


def _copy_usage(
    pricing: PricingTable, request: GenerationRequest, result: GenerationResult
) -> UsageAndCost:
    """Tokens, priced like `ContentService._call_cost` (m-24852539): a Claude model
    `claude_tools` prices gets its per-kind `cost_breakdown` (cache reads and writes at
    their own rates); any other model keeps the table, cache at the full input rate."""
    usage = result.usage
    tokens = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_read": usage.cache_read_tokens,
        "cache_creation": usage.cache_creation_tokens,
    }
    cost = cost_breakdown(
        result.model_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
    )
    if cost:
        return tokens, cost
    per_in = pricing.unit_price(model_id=result.model_id, unit="per_mtok_in")
    per_out = pricing.unit_price(model_id=result.model_id, unit="per_mtok_out")
    billable_in = usage.input_tokens + usage.cache_read_tokens + usage.cache_creation_tokens
    cost = {
        "input": float(Decimal(billable_in) * per_in / _MTOK),
        "output": float(Decimal(usage.output_tokens) * per_out / _MTOK),
    }
    return tokens, cost


def _image_usage(
    pricing: PricingTable, request: GenerationRequest, result: GenerationResult
) -> UsageAndCost:
    pieces = max(result.usage.pieces, 1)
    price = pricing.unit_price(model_id=result.model_id, unit="per_piece")
    return {"images": pieces}, {"images": float(price * pieces)}


def _video_usage(
    pricing: PricingTable, request: GenerationRequest, result: GenerationResult
) -> UsageAndCost:
    payload = result.payload if isinstance(result.payload, Mapping) else {}
    resolution = str(payload.get("resolution") or request.params.get("resolution") or "720p")
    tokens = int(result.usage.output_tokens)
    usage = {"video_tokens": tokens}
    if result.usage.media_seconds:
        usage["seconds"] = int(round(result.usage.media_seconds))
    cost = video_cost_usd(pricing, result.model_id, resolution, tokens)
    return usage, {"video": float(cost)}


_USAGE: Mapping[str, Callable[[PricingTable, GenerationRequest, GenerationResult], UsageAndCost]]
_USAGE = {"anthropic": _copy_usage, "seedream": _image_usage, "seedance": _video_usage}


def _request_input(request: GenerationRequest) -> dict[str, Any]:
    """What the model was asked. A copy call is its prompt; a media call its parameters,
    the reference images counted rather than sent (they are tenants' photos)."""
    prompt = request.rendered_prompt
    out: dict[str, Any] = {"task": request.task.value}
    if prompt.stable_prefix or prompt.volatile_suffix:
        out["system"] = prompt.stable_prefix
        out["user"] = prompt.volatile_suffix
    params = dict(request.params)
    for key in ("images", "image", "reference_images"):
        value = params.pop(key, None)
        if value:
            out[f"{key}_count"] = len(value) if isinstance(value, list | tuple) else 1
    if params:
        out["params"] = params
    return out


def _result_output(name: str, result: GenerationResult) -> Any:
    """What came back: the copy payload as is; for media, a summary — never the bytes or
    a vendor URL that expires in 24 h."""
    payload = result.payload
    if name == "anthropic":
        return payload
    if not isinstance(payload, Mapping):
        return None
    summary: dict[str, Any] = {}
    images = payload.get("images")
    if images:
        summary["images"] = len(images)
    for key in ("task_id", "duration", "duration_sec", "resolution", "ratio", "status"):
        if payload.get(key) is not None:
            summary[key] = payload[key]
    return summary


class TracedProvider:
    """A `GenerationProvider` that opens one Langfuse generation around each call of the
    provider it wraps. Everything else is the inner provider's."""

    def __init__(self, inner: GenerationProvider, pricing: PricingTable) -> None:
        self._inner = inner
        self._pricing = pricing
        self.name = inner.name
        self.supports = inner.supports

    @property
    def inner(self) -> GenerationProvider:
        return self._inner

    def estimate_cost_usd(self, request: GenerationRequest, pricing: PricingTable, **kwargs: Any):
        return self._inner.estimate_cost_usd(request, pricing, **kwargs)

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        name = self._inner.name
        # the copy adapter knows its model up front; the media ones resolve it per call,
        # so theirs arrives with the result (`finish`)
        model = getattr(self._inner, "_model_id", None)
        with observability.generation(
            TRACED_PROVIDERS.get(name, name),
            model=model if isinstance(model, str) else None,
            input=_request_input(request),
            metadata={"provider": name, "task": request.task.value},
        ) as observation:
            result = self._inner.generate(request, api_key=api_key)
            usage: dict[str, int] | None = None
            cost: dict[str, float] | None = None
            try:
                usage, cost = _USAGE[name](self._pricing, request, result)
            except Exception as exc:  # noqa: BLE001 — an unpriced model is still traced
                logger.warning("no Langfuse cost for %s %s: %s", name, result.model_id, exc)
            observation.finish(
                output=_result_output(name, result),
                model=result.model_id,
                usage=usage,
                cost=cost,
                metadata={"provider": result.provider, "model_revision": result.model_revision},
            )
            return result


def traced_providers(
    providers: Mapping[str, GenerationProvider], pricing: PricingTable
) -> dict[str, GenerationProvider]:
    """`providers` with the ones under test wrapped in `TracedProvider`. With tracing off
    the wrapper costs one no-op context manager per call."""
    return {
        name: TracedProvider(provider, pricing) if name in TRACED_PROVIDERS else provider
        for name, provider in providers.items()
    }
