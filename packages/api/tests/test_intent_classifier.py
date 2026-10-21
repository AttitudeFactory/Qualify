"""`ClaudeIntentClassifier` and `normalize_prediction` (m-24789644) against a scripted
client — no network, no API key. What the real model answers is measured by the golden
set (`qualify_api.intent.eval`), not here."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import ClaudeToolError
from qualify_api.intent import ClaudeIntentClassifier, IntentClass, normalize_prediction
from qualify_api.intent.classifier import (
    CLAUDE_INTENT_EFFORT,
    CLAUDE_INTENT_MODEL,
    INTENT_TOOL,
    SYSTEM_PROMPT,
)


class ScriptedClient:
    """Answers each `messages.create` with the next scripted tool input (or text)."""

    def __init__(self, *answers: dict[str, Any] | None) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        content = (
            [SimpleNamespace(type="tool_use", id="tu_1", name=INTENT_TOOL, input=answer)]
            if answer is not None
            else [SimpleNamespace(type="text", text="no sé")]
        )
        return SimpleNamespace(
            stop_reason="tool_use" if answer is not None else "end_turn",
            content=content,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
        )


def _result(index: int, *classes: tuple[str, float]) -> dict[str, Any]:
    return {"id": index, "classes": [{"class": c, "confidence": v} for c, v in classes]}


def _classifier(client: ScriptedClient, **kwargs: Any) -> ClaudeIntentClassifier:
    return ClaudeIntentClassifier(api_key="k", client_factory=lambda _key: client, **kwargs)


# --- normalize_prediction ------------------------------------------------------------


def test_normalize_keeps_known_classes_within_range() -> None:
    assert normalize_prediction([("price", 0.9), ("hours", 1.0), ("store", 0.0)]) == {
        IntentClass.PRICE: 0.9,
        IntentClass.HOURS: 1.0,
        IntentClass.STORE: 0.0,
    }


@pytest.mark.parametrize(
    "pair", [("discount", 0.9), ("price", 1.5), ("price", -0.1), ("price", "alta"), (None, 0.5)]
)
def test_normalize_drops_what_the_contract_would_reject(pair: tuple[Any, Any]) -> None:
    assert normalize_prediction([pair]) == {}


def test_normalize_keeps_the_highest_confidence_of_a_repeated_class() -> None:
    assert normalize_prediction([("price", 0.4), ("price", 0.8)]) == {IntentClass.PRICE: 0.8}


def test_normalize_drops_general_when_a_commercial_class_is_present() -> None:
    assert normalize_prediction([("general", 0.9), ("price", 0.6)]) == {IntentClass.PRICE: 0.6}
    assert normalize_prediction([("general", 0.9)]) == {IntentClass.GENERAL: 0.9}


# --- ClaudeIntentClassifier ----------------------------------------------------------


def test_one_call_sends_numbered_comments_and_one_strict_tool_unforced() -> None:
    client = ScriptedClient({"results": [_result(1, ("price", 0.9)), _result(2, ("general", 1))]})

    predictions = _classifier(client).classify(["¿Cuánto   cuesta?\n", "¡Qué lindo!"])

    assert predictions == [{IntentClass.PRICE: 0.9}, {IntentClass.GENERAL: 1.0}]
    call = client.calls[0]
    assert call["model"] == CLAUDE_INTENT_MODEL
    assert call["output_config"] == {"effort": CLAUDE_INTENT_EFFORT}
    assert call["tool_choice"] == {"type": "auto"}  # Haiku 5.5 thinks: never forced
    assert call["system"][0]["text"] == SYSTEM_PROMPT
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    tool = call["tools"][0]
    assert tool["name"] == INTENT_TOOL and tool["strict"] is True
    class_enum = tool["input_schema"]["properties"]["results"]["items"]["properties"]["classes"][
        "items"
    ]["properties"]["class"]["enum"]
    assert set(class_enum) == {c.value for c in IntentClass}
    assert call["messages"][0]["content"] == "Comentarios (2):\n1. ¿Cuánto cuesta?\n2. ¡Qué lindo!"


def test_answers_are_matched_by_id_not_by_position() -> None:
    client = ScriptedClient({"results": [_result(2, ("hours", 0.8)), _result(1, ("price", 0.7))]})

    assert _classifier(client).classify(["a", "b"]) == [
        {IntentClass.PRICE: 0.7},
        {IntentClass.HOURS: 0.8},
    ]


def test_missing_out_of_range_and_repeated_ids_leave_an_empty_prediction() -> None:
    client = ScriptedClient(
        {
            "results": [
                _result(1, ("price", 0.7)),
                _result(1, ("hours", 0.9)),  # repeated id: the first answer stands
                _result(7, ("store", 0.9)),  # no such comment
            ]
        }
    )

    assert _classifier(client).classify(["a", "b"]) == [{IntentClass.PRICE: 0.7}, {}]


def test_comments_are_sent_in_batches() -> None:
    client = ScriptedClient(
        {"results": [_result(1, ("price", 0.9)), _result(2, ("store", 0.9))]},
        {"results": [_result(1, ("hours", 0.9))]},
    )
    classifier = _classifier(client, batch_size=2)

    predictions = classifier.classify(["a", "b", "c"])

    assert len(client.calls) == 2
    assert predictions[2] == {IntentClass.HOURS: 0.9}
    assert len(classifier.last_stats) == 2
    assert all(stats.model_id == CLAUDE_INTENT_MODEL for stats in classifier.last_stats)


def test_no_comments_means_no_call() -> None:
    client = ScriptedClient()

    assert _classifier(client).classify([]) == []
    assert client.calls == []


def test_an_answer_without_the_tool_call_is_an_error() -> None:
    client = ScriptedClient(None)

    with pytest.raises(ClaudeToolError, match=INTENT_TOOL):
        _classifier(client).classify(["a"])


def test_the_classifier_records_no_pinned_revision() -> None:
    assert _classifier(ScriptedClient()).model_revision is None
