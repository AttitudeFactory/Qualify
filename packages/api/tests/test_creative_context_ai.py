"""«Potenciar con IA» on the generator's context (§ request 2026-10-20), over a fake
Claude client: what the model is given, what comes back, and the refusals."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.schemas import BrandKit, ToneAxes

from qualify_api.claude_tools import Attribution as _Attribution
from qualify_api.creative.context_ai import (
    CONTEXT_MAX_CHARS,
    OUTPUT_MARGIN_CHARS,
    PROPOSAL_MAX_CHARS,
    SCENE_MAX_CHARS,
    TOOL_NAME,
    ContextInput,
    ContextMeaningUncertain,
    ContextTooLong,
    ContextUnavailable,
    enhance_context,
    normalize_context_proposal,
    render_request,
    validate_context_proposal,
)

#: m-24955649: who pays for the faked Claude calls of this module.
TEST_ATTRIBUTION = _Attribution.no_business("test")


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
        f"LARGO MÁXIMO: {PROPOSAL_MAX_CHARS}",
    ):
        assert expected in message, expected
    assert f"LARGO MÁXIMO: {PROPOSAL_MAX_CHARS}" in render_request(_input(scene=True), None)
    assert "BRAND KIT: (no hay)" in render_request(_input(), None)


def test_the_brand_typeface_is_in_the_brand_kit_lines() -> None:
    """§ request 2026-10-21: the Brand Kit's one type face reaches «Potenciar con IA»
    too — the headline face of a kit that held two; no line at all without one."""
    two = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    message = render_request(_input(), two)
    assert "- Tipografía de la marca: Baloo 2\n" in message and "Nunito" not in message
    assert "Tipografía" not in render_request(_input(), _kit())


def test_the_rewrite_comes_back_with_what_the_model_added() -> None:
    client = FakeClient([_answer("Quiero mostrar la smash doble…", ["2x1"])])
    proposal = enhance_context(
        _input(), _kit(), client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert proposal.text == "Quiero mostrar la smash doble…"
    assert proposal.added_facts == ("2x1",)
    assert proposal.input_tokens == 500 and proposal.output_tokens == 120
    (call,) = client.messages.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["tools"][0]["name"] == TOOL_NAME and call["tools"][0]["strict"] is True
    assert "NO inventes hechos" in call["system"][0]["text"]


def test_a_long_scene_is_refused_instead_of_losing_important_instructions() -> None:
    long = ("Una mano sostiene la hamburguesa. " * 40).strip() + " No cambies el uniforme."
    client = FakeClient([_answer(long)])
    with pytest.raises(ContextTooLong) as error:
        enhance_context(
            _input(scene=True),
            None,
            client_factory=lambda key: client,
            attribution=TEST_ATTRIBUTION,
        )
    assert error.value.actual_chars == len(long)
    assert error.value.max_chars == PROPOSAL_MAX_CHARS
    assert len(client.messages.calls) == 1  # No automatic second paid call.


def test_a_refusal_or_no_tool_is_unavailable_and_a_short_text_is_refused() -> None:
    refused = FakeClient([_answer("", stop="refusal")])
    with pytest.raises(ContextUnavailable):
        enhance_context(
            _input(), _kit(), client_factory=lambda key: refused, attribution=TEST_ATTRIBUTION
        )
    no_tool = SimpleNamespace(
        model="m",
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        content=[SimpleNamespace(type="text", text="hola")],
    )
    with pytest.raises(ContextUnavailable):
        enhance_context(
            _input(),
            _kit(),
            client_factory=lambda key: FakeClient([no_tool]),
            attribution=TEST_ATTRIBUTION,
        )
    with pytest.raises(ValueError):
        enhance_context(
            _input(text="hola"),
            _kit(),
            client_factory=lambda key: FakeClient([]),
            attribution=TEST_ATTRIBUTION,
        )


def test_without_a_key_nothing_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY")
    client = FakeClient([])
    with pytest.raises(ContextUnavailable):
        enhance_context(
            _input(), _kit(), client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
        )
    assert client.messages.calls == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "  Café\tcon\n\nleche.\u00a0No cambies\u202fel precio.  ",
            "Café con leche. No cambies el precio.",
        ),
        (" **Quiero mostrar la hamburguesa.** ", "Quiero mostrar la hamburguesa."),
        (
            "```text\nCafé  en primer plano.\nNo cambies el fondo.\n```",
            "Café en primer plano. No cambies el fondo.",
        ),
        (
            "Cafe\u0301, niño 中文 @Image1 @Video1 00:03 25% #Oferta -10%",
            "Café, niño 中文 @Image1 @Video1 00:03 25% #Oferta -10%",
        ),
        (
            'Pon **NO** y "2x1" en el letrero; conserva #MiMarca.',
            'Pon **NO** y "2x1" en el letrero; conserva #MiMarca.',
        ),
    ],
)
def test_cleanup_removes_layout_without_losing_instructions(raw: str, expected: str) -> None:
    result = normalize_context_proposal(raw)
    assert result == expected
    assert normalize_context_proposal(result) == expected


def test_literal_markup_and_hashtags_are_preserved() -> None:
    source = "Incluye #MiMarca; escribe **Oferta** literalmente."
    assert normalize_context_proposal(source, source_text=source) == source
    assert normalize_context_proposal("**Oferta**", source_text=source) == "**Oferta**"
    with pytest.raises(ContextMeaningUncertain):
        normalize_context_proposal("🍔 " + source, source_text=source)


@pytest.mark.parametrize("size", [299, 300])
def test_final_normalized_length_respects_a_supplied_300_character_limit(size: int) -> None:
    raw = "  " + "a" * size + "\n\n"
    assert validate_context_proposal(raw, max_chars=300) == "a" * size


def test_301_character_result_is_not_cut_to_300() -> None:
    with pytest.raises(ContextTooLong) as error:
        validate_context_proposal("a" * 301, max_chars=300)
    assert error.value.actual_chars == 301 and error.value.max_chars == 300
    # UX review B3: the owner reads no character counts (they stay on the exception)
    assert "dejamos tu texto como estaba" in str(error.value)
    assert not any(ch.isdigit() for ch in str(error.value))


@pytest.mark.parametrize("scene", [False, True])
def test_current_product_capacities_remain_and_include_final_spaces(scene: bool) -> None:
    data = _input(scene=scene)
    expected = 600 if scene else 1200
    assert data.field_max_chars == expected
    assert data.max_chars == PROPOSAL_MAX_CHARS == 300
    assert (SCENE_MAX_CHARS, CONTEXT_MAX_CHARS) == (600, 1200)
    message = render_request(data, None)
    assert f"OBJETIVO: hasta {PROPOSAL_MAX_CHARS - OUTPUT_MARGIN_CHARS}" in message
    raw = "  " + "a" * (PROPOSAL_MAX_CHARS - 2) + "\n b  "
    client = FakeClient([_answer(raw)])
    result = enhance_context(
        data, None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert len(result.text) == PROPOSAL_MAX_CHARS
    assert result.text.endswith(" b")
    assert result.prompt_version == "context-v3-compact-300"
    schema_text = client.messages.calls[0]["tools"][0]["input_schema"]["properties"]
    assert str(PROPOSAL_MAX_CHARS) in schema_text["context"]["description"]


@pytest.mark.parametrize("raw", ["", "   \t\n", "🍔 👩🏽‍🍳"])
def test_empty_after_cleanup_is_unavailable(raw: str) -> None:
    client = FakeClient([_answer(raw)])
    with pytest.raises(ContextUnavailable):
        enhance_context(
            _input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
        )


def test_explicit_symbols_in_key_facts_or_required_text_are_not_decorations() -> None:
    text = "Incluye 👩🏽‍🍳 y #MiMarca."
    client = FakeClient([_answer(text)])
    with pytest.raises(ContextMeaningUncertain):
        enhance_context(
            _input(must_mention=text),
            None,
            client_factory=lambda key: client,
            attribution=TEST_ATTRIBUTION,
        )
    assert len(client.messages.calls) == 1


@pytest.mark.parametrize("literal", ['"A  B"', "'A  B'", "«A  B»", "“A  B”"])
def test_explicit_literals_keep_internal_spaces(literal: str) -> None:
    source = f"Escribe exactamente {literal} en el letrero."
    proposal = f"  Quiero  el  letrero {literal}.\nSin cambiarlo.  "
    assert normalize_context_proposal(proposal, source_text=source) == (
        f"Quiero el letrero {literal}. Sin cambiarlo."
    )


def test_an_already_changed_explicit_literal_is_rejected() -> None:
    with pytest.raises(ContextMeaningUncertain):
        normalize_context_proposal(
            'Quiero el letrero "A B".', source_text='Escribe exactamente "A  B".'
        )


def test_named_emoji_request_cannot_disappear_during_cleanup() -> None:
    with pytest.raises(ContextMeaningUncertain):
        normalize_context_proposal(
            "Quiero mostrar el producto y cerrar con ❤️.",
            source_text="Añade el emoji de un corazón rojo al final.",
        )
    assert (
        normalize_context_proposal(
            "Quiero mostrar el producto y añadir un emoji de corazón rojo al final.",
            source_text="Añade el emoji de un corazón rojo al final.",
        )
        == "Quiero mostrar el producto y añadir un emoji de corazón rojo al final."
    )


@pytest.mark.parametrize("scene", [False, True])
def test_automatic_proposal_301_is_rejected_even_when_manual_field_can_hold_it(scene: bool) -> None:
    client = FakeClient([_answer("x" * 301)])
    with pytest.raises(ContextTooLong) as error:
        enhance_context(
            _input(scene=scene),
            None,
            client_factory=lambda key: client,
            attribution=TEST_ATTRIBUTION,
        )
    assert error.value.max_chars == 300
    assert len(client.messages.calls) == 1


@pytest.mark.parametrize(
    "proposal",
    [
        'Quiero el letrero "A  B".',
        "Quiero el letrero A  B.",
    ],
)
def test_literal_content_is_protected_independently_of_output_quotes(proposal: str) -> None:
    assert (
        normalize_context_proposal(
            proposal, source_text="Escribe exactamente «A  B» en el letrero."
        )
        == proposal
    )


@pytest.mark.parametrize(
    "source",
    [
        "Añade el emoji de un corazón rojo al final.",
        "Añade un corazón rojo al final.",
        "Muestra el producto.",
    ],
)
def test_any_emoji_bearing_proposal_is_refused_without_guessing_meaning(source: str) -> None:
    client = FakeClient([_answer("Quiero mostrar el producto y cerrar con ❤️.")])
    with pytest.raises(ContextMeaningUncertain):
        enhance_context(
            _input(text=source),
            None,
            client_factory=lambda key: client,
            attribution=TEST_ATTRIBUTION,
        )
    assert len(client.messages.calls) == 1


def test_explicit_literal_internal_spaces_count_towards_proposal_limit() -> None:
    literal = "A" + " " * 299 + "B"
    with pytest.raises(ContextTooLong):
        validate_context_proposal(literal, max_chars=300, source_text=f"Escribe «{literal}».")
