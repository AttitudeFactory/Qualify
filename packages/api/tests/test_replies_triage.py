"""ATENDER-4a (m-24848532): the Haiku comment triager and the any-comment draft prompt,
against a scripted Messages client — no network."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import CallStats, ClaudeToolError
from qualify_api.intent.contract import IntentClass
from qualify_api.replies.any_comment_drafts import (
    ANY_COMMENT_SYSTEM_PROMPT,
    any_comment_context,
)
from qualify_api.replies.claude_drafts import ClaudeReplyDraftProvider
from qualify_api.replies.repository import CandidateComment, MemoryReplyRepository
from qualify_api.replies.service import ReplyService
from qualify_api.replies.triage import (
    TRIAGE_PROMPT_VERSION,
    ClaudeCommentTriager,
    CommentKind,
    Sentiment,
    parse_triage,
)
from qualify_api.sentiment.repository import AnalysisVersion


def _response(*blocks: Any, stop_reason: str = "tool_use") -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        model="claude-haiku-5-5",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
    )


def _tool(results: list[dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use", name="registrar_comentarios", input={"results": results}
    )


class Scripted:
    def __init__(self, *responses: SimpleNamespace) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_one_call_returns_sentiment_kind_and_needs_reply_in_order() -> None:
    client = Scripted(
        _response(
            _tool(
                [
                    {"id": 2, "sentiment": "neg", "kind": "complaint", "needs_reply": True},
                    {"id": 1, "sentiment": "pos", "kind": "praise", "needs_reply": False},
                ]
            )
        )
    )
    triager = ClaudeCommentTriager(api_key="sk-test", client_factory=lambda _: client)

    first, second = triager.triage(["qué rico", "llegó frío"])

    assert first is not None and second is not None
    assert (first.sentiment, first.kind, first.needs_reply) == (
        Sentiment.POS,
        CommentKind.PRAISE,
        False,
    )
    assert (second.sentiment, second.kind, second.needs_reply) == (
        Sentiment.NEG,
        CommentKind.COMPLAINT,
        True,
    )
    assert first.model_id == "claude-haiku-5-5"
    assert first.prompt_version == TRIAGE_PROMPT_VERSION
    (call,) = client.calls
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["tool_choice"] == {"type": "auto"}  # Haiku 5.5 thinks
    assert "1. qué rico" in call["messages"][0]["content"]
    (stats,) = triager.last_stats
    assert stats.cost_usd == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1_000_000)


def test_missing_or_off_contract_entries_are_none_never_guessed() -> None:
    client = Scripted(
        _response(_tool([{"id": 1, "sentiment": "angry", "kind": "praise", "needs_reply": False}]))
    )
    triager = ClaudeCommentTriager(api_key="sk-test", client_factory=lambda _: client)
    assert triager.triage(["a", "b"]) == [None, None]


def test_batches_split_the_texts() -> None:
    entry = {"id": 1, "sentiment": "neu", "kind": "other", "needs_reply": False}
    client = Scripted(_response(_tool([entry])), _response(_tool([entry])))
    triager = ClaudeCommentTriager(api_key="k", client_factory=lambda _: client, batch_size=1)
    assert len([t for t in triager.triage(["a", "b"]) if t]) == 2
    assert len(client.calls) == 2


def test_no_tool_call_is_an_error() -> None:
    client = Scripted(_response(SimpleNamespace(type="text", text="hola"), stop_reason="end_turn"))
    triager = ClaudeCommentTriager(api_key="k", client_factory=lambda _: client)
    with pytest.raises(ClaudeToolError):
        triager.triage(["a"])


@pytest.mark.parametrize("kind", ["question", "complaint"])
def test_a_question_or_complaint_always_needs_a_reply(kind: str) -> None:
    parsed = parse_triage(
        {"sentiment": "neu", "kind": kind, "needs_reply": False}, model_id="m", prompt_version="v"
    )
    assert parsed is not None and parsed.needs_reply is True


def test_needs_reply_must_be_a_boolean() -> None:
    assert (
        parse_triage(
            {"sentiment": "neu", "kind": "other", "needs_reply": "yes"},
            model_id="m",
            prompt_version="v",
        )
        is None
    )


def test_any_comment_prompt_speaks_in_first_person_and_never_states_prices() -> None:
    assert "primera persona" in ANY_COMMENT_SYSTEM_PROMPT
    assert "tercera persona" in ANY_COMMENT_SYSTEM_PROMPT
    assert "NUNCA escribas un precio" in ANY_COMMENT_SYSTEM_PROMPT
    complaint = any_comment_context(kind=CommentKind.COMPLAINT, sentiment=Sentiment.NEG)
    assert "queja" in complaint and "mensaje privado" in complaint
    priced = any_comment_context(
        kind=CommentKind.QUESTION, sentiment=Sentiment.NEU, classes=[IntentClass.PRICE]
    )
    assert "no lo digas" in priced
    upset = any_comment_context(kind=CommentKind.QUESTION, sentiment=Sentiment.NEG)
    assert "molesta" in upset


# --- every draft records model, prompt version and cost (criterion 4) ---------------


def _text_response() -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="¡Gracias!")],
        stop_reason="end_turn",
        model="claude-haiku-5-5",
        usage=SimpleNamespace(input_tokens=300, output_tokens=60, cache_read_input_tokens=0),
    )


def test_claude_provider_keeps_the_last_call_stats() -> None:
    client = Scripted(_text_response())
    provider = ClaudeReplyDraftProvider(client_factory=lambda _: client, api_key="k")
    assert provider.last_stats is None
    provider.draft_reply(comment_text="qué lindo")
    assert isinstance(provider.last_stats, CallStats)
    assert provider.last_stats.input_tokens == 300


def test_a_thank_you_draft_stores_model_and_cost() -> None:
    from uuid import UUID, uuid4

    tenant = UUID("11111111-1111-4111-8111-111111111111")
    connection = UUID("22222222-2222-4222-8222-222222222222")
    repo = MemoryReplyRepository()
    repo.seed_candidates(
        connection_id=connection,
        candidates=(
            CandidateComment(
                message_id=uuid4(),
                source_id="c-1",
                text="me encanta!",
                sentiment_result_id=uuid4(),
                sentiment_label="POS",
            ),
        ),
    )
    client = Scripted(_text_response())
    service = ReplyService(
        repository=repo,
        version=AnalysisVersion(
            detector_version="d", pipeline_version="p", model_id="m", model_revision=None
        ),
        generator_version="qua22.2:claude-haiku-5-5",
        provider=ClaudeReplyDraftProvider(client_factory=lambda _: client, api_key="k"),
        client_factory=None,  # type: ignore[arg-type]
    )

    service.generate_drafts(tenant_id=tenant, connection_id=connection)

    (draft,) = repo.list_pending_drafts(tenant_id=tenant, connection_id=connection)
    assert draft.generator_version == "qua22.2:claude-haiku-5-5"  # prompt version
    assert draft.model_id == "claude-haiku-5-5"
    assert draft.input_tokens == 300 and draft.output_tokens == 60
    assert draft.cost_usd == Decimal("0.00006")
