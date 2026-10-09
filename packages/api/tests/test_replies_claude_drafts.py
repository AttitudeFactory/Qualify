"""`ClaudeReplyDraftProvider` (QUA-128) against a scripted Messages client — no network."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import API_KEY_ENV, ClaudeToolError, MissingAPIKey
from qualify_api.replies.claude_drafts import DRAFT_MODEL, ClaudeReplyDraftProvider


def _response(
    *blocks: Any, stop_reason: str = "end_turn", model: str = "claude-haiku-5-5"
) -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(input_tokens=300, output_tokens=60, cache_read_input_tokens=0),
    )


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


class ScriptedClient:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.response


def _provider(response: SimpleNamespace, keys: list[str] | None = None) -> Any:
    client = ScriptedClient(response)

    def build(api_key: str) -> ScriptedClient:
        if keys is not None:
            keys.append(api_key)
        return client

    return ClaudeReplyDraftProvider(client_factory=build, api_key="sk-test"), client


def test_drafts_with_haiku_at_low_effort_and_the_shared_grounding_prompt() -> None:
    from qualify_models.providers import REPLY_SYSTEM_PROMPT

    keys: list[str] = []
    provider, client = _provider(_response(_text("  ¡Gracias por tu comentario!  ")), keys)

    text = provider.draft_reply(comment_text="me encantó el reel", business_name="PuntoServis")

    assert text == "¡Gracias por tu comentario!"
    assert keys == ["sk-test"]
    (call,) = client.calls
    assert call["model"] == "claude-haiku-5-5" == provider.model_id == DRAFT_MODEL.model_id
    assert call["output_config"] == {"effort": "low"}
    assert call["system"].startswith(REPLY_SYSTEM_PROMPT)
    assert "PuntoServis" in call["system"]
    # The comment is the only user content — nothing else reaches the model.
    assert call["messages"] == [{"role": "user", "content": "me encantó el reel"}]


def test_thinking_blocks_never_leak_into_the_draft() -> None:
    thinking = SimpleNamespace(type="thinking", thinking="")
    provider, _ = _provider(_response(thinking, _text("Gracias")))
    assert provider.draft_reply(comment_text="genial") == "Gracias"


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (_response(stop_reason="refusal"), "refused"),
        (_response(_text("Graci"), stop_reason="max_tokens"), "max_tokens"),
        (_response(_text("   ")), "empty"),
    ],
)
def test_unusable_answers_raise_instead_of_saving_a_bad_draft(
    response: SimpleNamespace, match: str
) -> None:
    provider, _ = _provider(response)
    with pytest.raises(ClaudeToolError, match=match):
        provider.draft_reply(comment_text="genial")


def test_the_key_is_read_on_first_draft_not_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    provider = ClaudeReplyDraftProvider(client_factory=lambda key: None)  # builds fine
    with pytest.raises(MissingAPIKey):
        provider.draft_reply(comment_text="genial")


def test_every_draft_logs_model_tokens_and_cost(caplog: pytest.LogCaptureFixture) -> None:
    provider, _ = _provider(_response(_text("Gracias")))
    with caplog.at_level(logging.INFO, logger="qualify_api.replies.claude_drafts"):
        provider.draft_reply(comment_text="genial")
    # 300 in * $0.10/M + 60 out * $0.50/M = $0.00006
    assert "model=claude-haiku-5-5 input_tokens=300 output_tokens=60 cost_usd=0.000060" in (
        caplog.text
    )


def test_production_service_drafts_with_claude_and_stamps_the_new_version() -> None:
    from qualify_api.replies import composition

    assert composition.current_reply_generator_version() == "qua22.2:claude-haiku-5-5"
    composition.production_reply_service.cache_clear()
    try:
        service = composition.production_reply_service()
        assert isinstance(service._provider, ClaudeReplyDraftProvider)
    finally:
        composition.production_reply_service.cache_clear()
