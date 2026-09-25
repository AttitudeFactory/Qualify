"""Anthropic copy adapter — the text half of the ``GenerationProvider`` seam.

API facts pinned from the ``claude-api`` skill (2026-08), not from memory:

- Default model ``claude-opus-5`` ($5.00 / $25.00 per MTok in/out).
- ``temperature`` / ``top_p`` / ``top_k`` return a 400 on this model — style variation is
  asked for in the prompt, never via sampling parameters.
- Thinking is adaptive (``thinking={"type": "adaptive"}``); ``max_tokens`` caps thinking
  plus response text together, so it is set generously.
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

DEFAULT_MODEL_ID = "claude-opus-5"
#: Generous on purpose: on claude-opus-5 ``max_tokens`` is a hard cap on thinking plus
#: response text together, and a tight cap truncates the copy mid-answer.
DEFAULT_MAX_TOKENS = 16000
#: Documented output allowance used by the pre-flight estimate: the input side is counted
#: exactly, the output side is a flat allowance of this many tokens per variant.
DEFAULT_OUTPUT_ALLOWANCE_TOKENS = 2000

_MTOK = Decimal(1_000_000)


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
    ) -> None:
        self._model_id = model_id
        self._client_factory = client_factory
        self._max_tokens = max_tokens
        self._output_allowance_tokens = output_allowance_tokens

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
        if request.output_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": strict_schema(request.output_schema)}
            }
        # NEVER pass temperature/top_p/top_k: claude-opus-5 rejects them with a 400.
        response = client.messages.create(**kwargs)

        # Check the stop reason BEFORE reading content: a refusal is an HTTP 200 with an
        # empty content array, and content[0] on it is a crash, not a refusal handler.
        if response.stop_reason == "refusal":
            raise CopyRefused(self._model_id)

        payload = self._parse_payload(response)
        raw_usage = response.usage
        usage = Usage(
            input_tokens=raw_usage.input_tokens,
            output_tokens=raw_usage.output_tokens,
            cache_read_tokens=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_tokens=getattr(raw_usage, "cache_creation_input_tokens", 0) or 0,
        )
        return GenerationResult(
            payload=payload,
            model_id=self._model_id,
            provider=self.name,
            usage=usage,
            model_revision=getattr(response, "model", None),
        )

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
