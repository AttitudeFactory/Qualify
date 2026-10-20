"""Anthropic copy adapter — the text half of the ``GenerationProvider`` seam.

API facts pinned from the ``claude-api`` skill (2026-10-06), not from memory:

- Default model ``claude-opus-5-5`` ($4.00 / $20.00 per MTok in/out), migrated from
  ``claude-opus-5`` on 2026-10-13. Same tokenizer and context; 20 % cheaper.
- ``temperature`` / ``top_p`` / ``top_k`` return a 400 on this model — style variation is
  asked for in the prompt, never via sampling parameters.
- Thinking is always on (``{"type": "disabled"}`` is a 400 on Opus 5.5); ``max_tokens``
  caps thinking plus response text together, so it is set generously.
- ``effort`` is set EXPLICITLY: Opus 5.5 defaults to ``medium`` where Opus 5 defaulted to
  ``high``, and its ``medium`` already beats Opus 5's ``high`` in Anthropic's testing.
- Forced ``tool_choice`` (``any``/``tool``) is a 400 on Opus 5.5 — this adapter uses
  structured outputs instead, never forced tool use.
- Character limits are HELD, not only asked for (2026-10-13). Structured outputs cannot
  carry ``maxLength`` (``strict_schema`` moves it into the description), so a model may
  answer a 61-character hook to a 60-character schema — and ``CopyPayload`` then rejects
  it, which failed the whole draft. The limits are the schema's own plus
  ``request.params["max_lengths"]`` (the printed hook/CTA of a flyer, template or
  carousel); a field over its limit gets ONE repair turn asking to shorten exactly those
  fields, and whatever is still over is cut at a word boundary — a draft never fails on
  one character.
- Server-side fallbacks (``fallbacks: "default"``, beta ``server-side-fallback-2026-07-01``):
  a safety-classifier decline is re-run on Anthropic's recommended model for that
  category (Opus 5 / Opus 4.8) inside the same call, so a false positive is not an
  outage. The model that SERVED the copy is reported and priced, not the one asked.
- Structured output goes through ``output_config.format`` with a JSON Schema — the
  assistant-turn prefill trick 400s on this model family.
- A safety refusal is an HTTP 200 with ``stop_reason == "refusal"`` and an empty
  ``content`` array, so ``stop_reason`` is checked BEFORE ``content`` is read.
- Prompt caching: the stable prefix (brand kit + voice profile) takes the
  ``cache_control`` breakpoint on the system block; the volatile brief rides the user
  message so the cache actually hits.
- Cost estimation uses the vendor's own ``messages.count_tokens`` — tiktoken-style
  estimators undercount Claude tokens by 15-20%, more on Spanish.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import (
    GenerationRequest,
    GenerationResult,
    PricingTable,
    Usage,
)

DEFAULT_MODEL_ID = "claude-opus-5-5"
#: Opus 5.5's own default is `medium`; it is set here so a model swap never changes how
#: much the copy model thinks by accident. The level to compare against is measured in
#: the Langfuse experiments (docs/plan-observabilidad-langfuse.md §6).
DEFAULT_EFFORT = "medium"
#: Server-side refusal fallbacks (`fallbacks: "default"`): the beta that gates the scalar
#: form. The array form uses a DIFFERENT header (`-2026-06-01`); never mix them.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: Generous on purpose: ``max_tokens`` is a hard cap on thinking plus response text
#: together, and a tight cap truncates the copy mid-answer. Non-streaming: 16000 is the
#: SDK's ceiling without streaming.
DEFAULT_MAX_TOKENS = 16000
#: Documented output allowance used by the pre-flight estimate: the input side is counted
#: exactly, the output side is a flat allowance of this many tokens per variant.
DEFAULT_OUTPUT_ALLOWANCE_TOKENS = 2000

logger = logging.getLogger(__name__)

_MTOK = Decimal(1_000_000)
#: Repair turns per call when a field comes back over its limit — one: a second miss is
#: cut at a word boundary instead of paying for another call.
MAX_LENGTH_REPAIRS = 1


class CopyRefused(Exception):
    """Claude's safety classifiers declined the request.

    A refusal is an HTTP 200 whose ``stop_reason`` is ``"refusal"`` and whose ``content``
    is empty — code that indexes ``content[0]`` breaks. This exception is raised before
    ``content`` is ever read, and it is deliberately not a generic provider error: the
    router's copy chain has no aggregator mirror, so a refusal is a policy decision, not
    a retryable transport failure.
    """

    def __init__(self, model_id: str) -> None:
        super().__init__(f"copy generation refused by {model_id} (stop_reason='refusal')")
        self.model_id = model_id


class AnthropicCopyAdapter:
    """``GenerationProvider`` for copy over the Anthropic Messages API.

    The client is built ONLY through :meth:`_client`, always with an explicit
    ``api_key`` — NEVER a bare ``Anthropic()``: the no-arg constructor falls back to
    environment credentials (``ANTHROPIC_API_KEY`` → ``ANTHROPIC_AUTH_TOKEN`` → OAuth
    profile on disk) and silently bills the wrong account. If the tenant's key is
    missing, the call must fail loudly, not degrade to ambient credentials.
    """

    name = "anthropic"
    supports = frozenset({GenerationTask.COPY})

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        client_factory: Callable[[str], Any] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        output_allowance_tokens: int = DEFAULT_OUTPUT_ALLOWANCE_TOKENS,
        effort: str = DEFAULT_EFFORT,
        fallbacks: bool = True,
    ) -> None:
        self._model_id = model_id
        self._client_factory = client_factory
        self._max_tokens = max_tokens
        self._output_allowance_tokens = output_allowance_tokens
        self._effort = effort
        self._fallbacks = fallbacks

    def _client(self, api_key: str) -> Any:
        """Build the SDK client for ``api_key``. Tests inject ``client_factory``;
        production lazily imports ``anthropic`` here so importing ``qualify_creative``
        never drags a network SDK, and constructs ``anthropic.Anthropic(api_key=...)``
        explicitly — never the no-arg form (see the class docstring for why)."""
        if self._client_factory is not None:
            return self._client_factory(api_key)
        import anthropic  # lazy: optional dependency, install via the `llm` extra

        return anthropic.Anthropic(api_key=api_key)

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        client = self._client(api_key)
        kwargs: dict[str, Any] = {
            "model": self._model_id,
            "max_tokens": self._max_tokens,
            # The stable prefix takes the cache breakpoint: byte-identical across every
            # generation of the same brand+voice version, so reads cost ~0.1x.
            "system": [
                {
                    "type": "text",
                    "text": request.rendered_prompt.stable_prefix,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": request.rendered_prompt.volatile_suffix}],
            "thinking": {"type": "adaptive"},
        }
        output_config: dict[str, Any] = {"effort": self._effort}
        if request.output_schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": strict_schema(request.output_schema),
            }
        kwargs["output_config"] = output_config
        response = self._create(client, kwargs)
        payload = self._parse_payload(response)
        usage = _usage(response)

        limits = max_lengths(request)
        over = _overflow(payload, limits)
        for _ in range(MAX_LENGTH_REPAIRS if over else 0):
            try:
                repaired = self._create(client, _repair_kwargs(kwargs, payload, over))
                candidate = self._parse_payload(repaired)
            except CopyRefused:
                break
            except Exception as exc:  # noqa: BLE001 — the cut below still saves the draft
                logger.warning("copy length repair failed: %s", type(exc).__name__)
                break
            usage = _add_usage(usage, _usage(repaired))
            response, payload = repaired, candidate
            over = _overflow(payload, limits)
            if not over:
                break
        if over:
            logger.warning("copy still over its limits after repair, cut: %s", over)
            payload = _cut_to_limits(payload, limits)
        return GenerationResult(
            payload=payload,
            # the model that SERVED the copy: after a fallback the top-level usage is the
            # fallback attempt's, billed at the fallback model's rates
            model_id=self._served_model(response),
            provider=self.name,
            usage=usage,
            model_revision=getattr(response, "model", None),
        )

    def _create(self, client: Any, kwargs: dict[str, Any]) -> Any:
        """One Messages call. NEVER pass temperature/top_p/top_k: Opus 5.5 rejects them.
        The stop reason is checked BEFORE content is read: a refusal is an HTTP 200 with
        an empty content array (with fallbacks on, the whole chain declined)."""
        if self._fallbacks:
            response = client.beta.messages.create(
                **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
            )
        else:
            response = client.messages.create(**kwargs)
        if response.stop_reason == "refusal":
            raise CopyRefused(self._model_id)
        return response

    def _served_model(self, response: Any) -> str:
        """`model_id` unless a server-side fallback served the response — then the
        fallback model, as the API names it (`response.model`). The served-by signal is a
        `fallback_message` entry in `usage.iterations`, which also covers sticky-routed
        turns that carry no `fallback` content block."""
        iterations = getattr(response.usage, "iterations", None) or ()
        if any(getattr(entry, "type", None) == "fallback_message" for entry in iterations):
            return str(getattr(response, "model", None) or self._model_id)
        return self._model_id

    def estimate_cost_usd(
        self,
        request: GenerationRequest,
        pricing: PricingTable,
        *,
        api_key: str | None = None,
    ) -> Decimal:
        """Pre-flight estimate for the router's (P) budget check.

        The input side is counted exactly with the vendor's own counter
        (``messages.count_tokens`` — authenticated but unbilled); the output side is a
        flat, documented allowance of ``output_allowance_tokens`` per variant. Both are
        priced via the ``PricingTable`` (``per_mtok_in`` / ``per_mtok_out``).

        ``api_key`` is keyword-only and defaults to ``None`` purely so the signature
        stays structurally compatible with the base Protocol; the counter still needs an
        authenticated client, so ``CreativeRouter`` always supplies the resolved key and
        a missing key raises — the no-environment-fallback rule of ``generate`` applies
        to counting too.
        """
        if api_key is None:
            raise ValueError(
                "estimate_cost_usd requires an explicit api_key: refusing to let the SDK "
                "fall back to environment credentials"
            )
        client = self._client(api_key)
        counted = client.messages.count_tokens(
            model=self._model_id,
            system=[{"type": "text", "text": request.rendered_prompt.stable_prefix}],
            messages=[{"role": "user", "content": request.rendered_prompt.volatile_suffix}],
        )
        per_mtok_in = pricing.unit_price(model_id=self._model_id, unit="per_mtok_in")
        per_mtok_out = pricing.unit_price(model_id=self._model_id, unit="per_mtok_out")
        input_cost = Decimal(counted.input_tokens) * per_mtok_in / _MTOK
        output_cost = Decimal(self._output_allowance_tokens) * per_mtok_out / _MTOK
        return input_cost + output_cost

    @staticmethod
    def _parse_payload(response: Any) -> Mapping[str, object]:
        """Parse the first text block as JSON. With ``output_config.format`` the API
        guarantees the first text block is valid JSON matching the schema; anything else
        (no text block, non-object JSON) is a hard error, not a payload."""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                parsed = json.loads(block.text)
                if not isinstance(parsed, dict):
                    raise ValueError(
                        f"copy payload must be a JSON object, got {type(parsed).__name__}"
                    )
                return parsed
        raise ValueError("response contains no text block to parse as the copy payload")


def max_lengths(request: GenerationRequest) -> dict[str, int]:
    """Every top-level string field's character limit: the schema's own `maxLength`
    (directly, or on the string branch of an optional field) and, tighter, the
    `request.params["max_lengths"]` the caller adds (the printed hook and CTA)."""
    limits: dict[str, int] = {}
    properties = (request.output_schema or {}).get("properties") or {}
    for name, spec in properties.items():
        if not isinstance(spec, Mapping):
            continue
        for branch in [spec, *(spec.get("anyOf") or [])]:
            if isinstance(branch, Mapping) and isinstance(branch.get("maxLength"), int):
                limits[name] = branch["maxLength"]
    extra = request.params.get("max_lengths") if request.params else None
    if isinstance(extra, Mapping):
        for name, limit in extra.items():
            limits[name] = min(int(limit), limits.get(name, int(limit)))
    return limits


def _overflow(
    payload: Mapping[str, object], limits: Mapping[str, int]
) -> dict[str, tuple[int, int]]:
    """`{field: (length, limit)}` of every string field over its limit."""
    return {
        name: (len(value), limit)
        for name, limit in limits.items()
        if isinstance(value := payload.get(name), str) and len(value) > limit
    }


def _repair_kwargs(
    kwargs: Mapping[str, Any],
    payload: Mapping[str, object],
    over: Mapping[str, tuple[int, int]],
) -> dict[str, Any]:
    """The same request, continued: the answer as the assistant turn (its JSON only, no
    thinking block replayed, so nothing earlier is edited) and the exact fields to
    shorten. Append-only, so the cached prefix still hits."""
    detail = "; ".join(
        f"{name}: {length} characters, maximum {limit}" for name, (length, limit) in over.items()
    )
    answer = json.dumps(payload, ensure_ascii=False)
    return {
        **kwargs,
        "messages": [
            *kwargs["messages"],
            {"role": "assistant", "content": [{"type": "text", "text": answer}]},
            {
                "role": "user",
                "content": (
                    f"These fields are over their character limits: {detail}. Rewrite ONLY "
                    "those fields so each one fits, keeping the meaning, the language and "
                    "the voice of the brand. Every other field stays exactly as it is. "
                    "Answer with the whole JSON object again."
                ),
            },
        ],
    }


def _cut(text: str, limit: int) -> str:
    """`text` within `limit` characters, cut at the last word boundary and stripped of a
    dangling separator; mid-word only when a single word is longer than the limit."""
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    space = head.rfind(" ")
    cut = head[:space] if space > 0 else text[:limit]
    return cut.rstrip(" ,;:-\u2013\u2014").rstrip() or text[:limit]


def _cut_to_limits(payload: Mapping[str, object], limits: Mapping[str, int]) -> dict[str, object]:
    out = dict(payload)
    for name, limit in limits.items():
        value = out.get(name)
        if isinstance(value, str) and len(value) > limit:
            out[name] = _cut(value, limit)
    return out


def _usage(response: Any) -> Usage:
    raw = response.usage
    return Usage(
        input_tokens=raw.input_tokens,
        output_tokens=raw.output_tokens,
        cache_read_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
    )


def _add_usage(a: Usage, b: Usage) -> Usage:
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens,
        cache_creation_tokens=a.cache_creation_tokens + b.cache_creation_tokens,
    )


#: Keywords structured outputs accepts as-is (everything else is folded into the
#: description, where the model may still follow it).
_STRING_FORMATS = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
)


def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A pydantic JSON schema in the shape structured outputs accepts — the same rules as
    the SDK's own `anthropic.transform_schema`, kept here so this module needs no SDK at
    import time: every object gets `additionalProperties: false`, and what the API does
    not accept (`maxLength`, `default`, `maxItems`…) moves into the description.

    Measured live 2026-09-25: the raw `CopyPayload.model_json_schema()` is rejected with
    HTTP 400 ("For 'object' type, 'additionalProperties' must be explicitly set to
    false"), so without this no copy could be generated at all."""
    source = dict(schema)
    out: dict[str, Any] = {}
    defs = source.pop("$defs", None)
    if defs is not None:
        out["$defs"] = {name: strict_schema(item) for name, item in defs.items()}
    ref = source.pop("$ref", None)
    if ref is not None:
        out["$ref"] = ref
        return out
    kind = source.pop("type", None)
    for key in ("anyOf", "oneOf", "allOf"):
        variants = source.pop(key, None)
        if isinstance(variants, list):
            out["allOf" if key == "allOf" else "anyOf"] = [strict_schema(v) for v in variants]
            break
    else:
        if kind is None:
            raise ValueError("schema has no type, anyOf, oneOf or allOf")
        out["type"] = kind
    for key in ("enum", "description", "title"):
        if key in source:
            out[key] = source.pop(key)
    if kind == "object":
        out["properties"] = {
            name: strict_schema(item) for name, item in source.pop("properties", {}).items()
        }
        source.pop("additionalProperties", None)
        out["additionalProperties"] = False
        if "required" in source:
            out["required"] = source.pop("required")
    elif kind == "string":
        fmt = source.pop("format", None)
        if fmt in _STRING_FORMATS:
            out["format"] = fmt
        elif fmt:
            source["format"] = fmt
    elif kind == "array":
        items = source.pop("items", None)
        if items is not None:
            out["items"] = strict_schema(items)
        if source.get("minItems") in (0, 1):
            out["minItems"] = source.pop("minItems")
    if source:
        extra = "{" + ", ".join(f"{key}: {value}" for key, value in source.items()) + "}"
        out["description"] = f"{out['description']}\n\n{extra}" if "description" in out else extra
    return out
