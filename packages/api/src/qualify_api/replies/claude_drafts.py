"""Reply drafts written by Claude Haiku — the production `ReplyDraftProvider` (QUA-128).

Replaces `HFInferenceReplyDraftProvider` in production: that path needed an `HF_TOKEN`
(and HF credits) that production never had, so "Generar borradores" failed with a bare
`ValueError` before any request. Claude is already a production dependency — the key
(`QUALIFY_ANTHROPIC_API_KEY`) and the SDK (`qualify-creative[llm]`) are there for the
hashtag catalog and the Brand Kit — so this adds no vendor and no secret.

Same grounding contract as the HF provider: the system prompt is
`qualify_models.providers.REPLY_SYSTEM_PROMPT`, unchanged, and the comment text is the
only user content. Nothing but the model's text answer leaves this class.

Model choice (`claude-api` skill, 2026-10): `claude-haiku-5-5` at $0.10 / $0.50 per
million input/output tokens. Haiku 5.5 thinks by default; `effort: "low"` keeps a one-
or two-sentence reply cheap. Cost per call is logged until QUA-144 gives it a home.
"""

from __future__ import annotations

import logging
from typing import Any

from qualify_shared import observability

from qualify_api.claude_tools import (
    ClaudeToolError,
    ClientFactory,
    Meter,
    ModelConfig,
    api_key_from_env,
    default_client,
    messages_create,
)

logger = logging.getLogger(__name__)

DRAFT_MODEL = ModelConfig("claude-haiku-5-5", effort="low")

#: Room for Haiku's (low-effort) thinking plus a 1-2 sentence reply. Thinking counts
#: against `max_tokens`, so this is far above the visible reply's length on purpose.
MAX_TOKENS = 2048


class ClaudeReplyDraftProvider:
    """`ReplyDraftProvider` over the Messages API. The client is built on the first
    draft, not at construction: `production_reply_service()` is cached and also serves
    list/decide/send, which must keep working when the key is missing."""

    def __init__(
        self,
        *,
        config: ModelConfig = DRAFT_MODEL,
        client_factory: ClientFactory = default_client,
        api_key: str | None = None,
    ) -> None:
        self.model_id = config.model_id
        self._config = config
        self._client_factory = client_factory
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self._api_key or api_key_from_env())
        return self._client

    @observability.traced("respuesta inbox", tags=("inbox",))
    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str:
        from qualify_models.providers import REPLY_SYSTEM_PROMPT  # noqa: PLC0415

        business_line = f" El negocio se llama {business_name}." if business_name else ""
        kwargs: dict[str, Any] = {
            "model": self._config.model_id,
            "max_tokens": MAX_TOKENS,
            "system": REPLY_SYSTEM_PROMPT + business_line,
            "messages": [{"role": "user", "content": comment_text}],
        }
        if self._config.effort:
            kwargs["output_config"] = {"effort": self._config.effort}
        response = messages_create(self._get_client(), self._config, **kwargs)

        meter = Meter(self._config)
        meter.add(response)
        stats = meter.stats()
        logger.info(
            "reply_draft model=%s input_tokens=%d output_tokens=%d cost_usd=%.6f",
            stats.model_revision or stats.model_id,
            stats.input_tokens,
            stats.output_tokens,
            stats.cost_usd,
        )

        if response.stop_reason == "refusal":
            raise ClaudeToolError(f"{self._config.model_id} refused the draft")
        if response.stop_reason == "max_tokens":
            raise ClaudeToolError(f"{self._config.model_id} hit max_tokens={MAX_TOKENS}")
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise ClaudeToolError(f"{self._config.model_id} returned an empty draft")
        return text
