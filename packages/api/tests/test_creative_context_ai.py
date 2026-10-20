"""«Potenciar con IA» on the generator's context (§ request 2026-10-20), over a fake
Claude client: what the model is given, what comes back, and the refusals."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.schemas import BrandKit, ToneAxes

from qualify_api.creative.context_ai import (
    CONTEXT_MAX_CHARS,
    SCENE_MAX_CHARS,
    TOOL_NAME,
    ContextInput,
    ContextUnavailable,
    enhance_context,
    render_request,
)


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.messages = FakeMessages(responses)


def _answer(context: str, added: list[str] | None = None, stop: str = "tool_use") -> Any:
    return SimpleNamespace(
        model="claude-sonnet-5-5-20261001",
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=500, output_tokens=120, cache_read_input_tokens=0),
        content=[
            SimpleNamespace(
                type="tool_use",
                name=TOOL_NAME,
                input={"context": context, "added_facts": added or []},
            )
        ],
    )


def _kit() -> BrandKit:
    return BrandKit(
        brand_id=uuid4(),
        positioning="Smash burgers en Caracas",
        audience="Jóvenes que piden a domicilio",
        tone_axes=ToneAxes(
            formal_casual=80, sober_enthusiastic=70, technical_plain=90, brief_elaborate=30
        ),
        banned_words=("barato",),
        cta_patterns=("Pide por WhatsApp",),
    )


def _input(**overrides: Any) -> ContextInput:
    values: dict[str, Any] = {
        "text": "quiero la smash doble con papas, promo de fin de semana",
        "piece": "Clip",
        "product": "Smash doble",
        "highlights": (("precio", "20 $"),),
        "must_mention": "envío gratis",
    }
    values.update(overrides)
    return ContextInput(**values)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "test-key")


def test_the_model_gets_the_text_the_facts_and_the_brand() -> None:
    message = render_request(_input(), _kit())
    for expected in (
        "TIPO DE PIEZA: Clip",
        "PRODUCTO: Smash doble",
        "- precio: 20 $",
        "DEBE MENCIONAR: envío gratis",
        "Posicionamiento: Smash burgers en Caracas",
        "Palabras prohibidas: barato",
        "quiero la smash doble con papas",
        f"LARGO MÁXIMO: {CONTEXT_MAX_CHARS}",
    ):
        assert expected in message, expected
    assert f"LARGO MÁXIMO: {SCENE_MAX_CHARS}" in render_request(_input(scene=True), None)
    assert "BRAND KIT: (no hay)" in render_request(_input(), None)


def test_the_rewrite_comes_back_with_what_the_model_added() -> None:
    client = FakeClient([_answer("Quiero mostrar la smash doble…", ["2x1"])])
    proposal = enhance_context(_input(), _kit(), client_factory=lambda key: client)

    assert proposal.text == "Quiero mostrar la smash doble…"
    assert proposal.added_facts == ("2x1",)
    assert proposal.input_tokens == 500 and proposal.output_tokens == 120
    (call,) = client.messages.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["tools"][0]["name"] == TOOL_NAME and call["tools"][0]["strict"] is True
    assert "NO inventes hechos" in call["system"][0]["text"]


def test_a_scene_longer_than_its_field_is_cut_at_a_sentence() -> None:
    long = ("Una mano sostiene la hamburguesa. " * 40).strip()
    client = FakeClient([_answer(long)])
    proposal = enhance_context(_input(scene=True), None, client_factory=lambda key: client)
    assert len(proposal.text) <= SCENE_MAX_CHARS and proposal.text.endswith(".")


def test_a_refusal_or_no_tool_is_unavailable_and_a_short_text_is_refused() -> None:
    refused = FakeClient([_answer("", stop="refusal")])
    with pytest.raises(ContextUnavailable):
        enhance_context(_input(), _kit(), client_factory=lambda key: refused)
    no_tool = SimpleNamespace(
        model="m",
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        content=[SimpleNamespace(type="text", text="hola")],
    )
    with pytest.raises(ContextUnavailable):
        enhance_context(_input(), _kit(), client_factory=lambda key: FakeClient([no_tool]))
    with pytest.raises(ValueError):
        enhance_context(_input(text="hola"), _kit(), client_factory=lambda key: FakeClient([]))


def test_without_a_key_nothing_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY")
    client = FakeClient([])
    with pytest.raises(ContextUnavailable):
        enhance_context(_input(), _kit(), client_factory=lambda key: client)
    assert client.messages.calls == []
