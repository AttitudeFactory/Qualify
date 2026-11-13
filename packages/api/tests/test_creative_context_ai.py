"""«Mejorar mi texto» on the generator's context (§ request 2026-10-20; three versions
since m-25017274), over a fake Claude client: what the model is given, what comes back,
and the refusals."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.schemas import BrandKit, ToneAxes

from qualify_api.claude_tools import Attribution as _Attribution
from qualify_api.creative.context_ai import (
    APPROACHES,
    CONTEXT_MAX_CHARS,
    CONTEXT_PROMPT_VERSION,
    OUTPUT_MARGIN_CHARS,
    PROPOSAL_MAX_CHARS,
    SCENE_APPROACHES,
    SCENE_MAX_CHARS,
    TOOL_NAME,
    ContextInput,
    ContextMeaningUncertain,
    ContextTooLong,
    ContextUnavailable,
    enhance_context,
    normalize_context_proposal,
    render_request,
    scene_text_request,
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


def _answer(
    context: str | list[str],
    added: list[str] | None = None,
    stop: str = "tool_use",
    scene: bool = False,
) -> Any:
    """The tool call of one press: `context` is the three versions, or one text that every
    approach repeats with a different ending (so they stay distinct) — or exactly the same
    when it would not survive validation anyway."""
    keys = [key for key, _ in (SCENE_APPROACHES if scene else APPROACHES)]
    texts = context if isinstance(context, list) else [context] * len(keys)
    return SimpleNamespace(
        model="claude-sonnet-5-5-20261001",
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=500, output_tokens=120, cache_read_input_tokens=0),
        content=[
            SimpleNamespace(
                type="tool_use",
                name=TOOL_NAME,
                input={**dict(zip(keys, texts, strict=True)), "added_facts": added or []},
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


THREE = [
    "Quiero la smash doble con papas, promo de fin de semana. Pide por WhatsApp.",
    "Quiero que se vea la smash doble jugosa, papas doradas: promo de fin de semana.",
    "Quiero contarte que este fin de semana la smash doble con papas está en promo.",
]


def test_the_rewrite_comes_back_as_three_versions_with_what_the_model_added() -> None:
    client = FakeClient([_answer(THREE, ["2x1"])])
    proposal = enhance_context(
        _input(), _kit(), client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert [v.text for v in proposal.versions] == THREE
    assert [v.approach for v in proposal.versions] == ["directa", "descriptiva", "cercana"]
    assert proposal.added_facts == ("2x1",)
    assert proposal.prompt_version == CONTEXT_PROMPT_VERSION == "context-v5-scene-no-text"
    assert proposal.input_tokens == 500 and proposal.output_tokens == 120
    (call,) = client.messages.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["tools"][0]["name"] == TOOL_NAME and call["tools"][0]["strict"] is True
    schema = call["tools"][0]["input_schema"]
    assert schema["required"] == ["directa", "descriptiva", "cercana", "added_facts"]
    assert "NO inventes hechos" in call["system"][0]["text"]
    assert "TRES versiones" in call["system"][0]["text"]


def test_a_long_scene_is_refused_instead_of_losing_important_instructions() -> None:
    long = ("Una mano sostiene la hamburguesa. " * 40).strip() + " No cambies el uniforme."
    client = FakeClient([_answer(long, scene=True)])
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
    client = FakeClient([_answer(raw, scene=scene)])
    result = enhance_context(
        data, None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert len(result.versions) == 1  # the other two repeat it and are dropped
    (version,) = result.versions
    assert len(version.text) == PROPOSAL_MAX_CHARS
    assert version.text.endswith(" b")
    assert result.prompt_version == "context-v5-scene-no-text"
    properties = client.messages.calls[0]["tools"][0]["input_schema"]["properties"]
    first = (SCENE_APPROACHES if scene else APPROACHES)[0][0]
    assert str(PROPOSAL_MAX_CHARS) in properties[first]["description"]


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
    client = FakeClient([_answer("x" * 301, scene=scene)])
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


# -- m-25017274: three distinct versions, «Otra versión», the publication's kind -------


def test_the_request_names_the_kind_the_format_and_the_approaches() -> None:
    message = render_request(
        _input(content_type="Promoción", format="Reel (video corto) 9:16"), _kit()
    )
    for expected in (
        "TIPO DE PUBLICACIÓN: Promoción",
        "FORMATO: Reel (video corto) 9:16",
        "PRODUCTO: Smash doble",
        "- directa: MÁS DIRECTA",
        "- descriptiva: MÁS DESCRIPTIVA",
        "- cercana: MÁS CERCANA",
    ):
        assert expected in message, expected
    assert "VERSIONES YA MOSTRADAS" not in message
    scene = render_request(_input(scene=True), None)
    assert "- producto: EL PRODUCTO DE CERCA" in scene and "- directa:" not in scene


def test_otra_version_sends_the_versions_already_shown_and_drops_a_repeat() -> None:
    shown = tuple(THREE)
    fresh = [
        "Quiero la smash doble con papas este fin de semana, en promo.",
        THREE[1] + "  ",  # the model repeated a card already shown: dropped
        "Quiero hablarte como a un vecino: el fin de semana la smash doble va en promo.",
    ]
    client = FakeClient([_answer(fresh)])
    proposal = enhance_context(
        _input(previous_versions=shown),
        _kit(),
        client_factory=lambda key: client,
        attribution=TEST_ATTRIBUTION,
    )
    message = client.messages.calls[0]["messages"][0]["content"]
    assert "VERSIONES YA MOSTRADAS" in message
    for text in shown:
        assert f"- {text}" in message
    # the ORIGINAL text is what gets rewritten, never a card
    assert message.rstrip().endswith(_input().text)
    assert [v.approach for v in proposal.versions] == ["directa", "cercana"]
    assert all(v.text not in shown for v in proposal.versions)


def test_only_the_newest_previous_versions_are_sent() -> None:
    shown = tuple(f"Versión vieja número {n} de la smash doble" for n in range(20))
    message = render_request(_input(previous_versions=shown), None)
    assert "número 19" in message and "número 11" in message
    assert "número 10 " not in message


def test_a_version_equal_to_the_original_or_another_is_dropped() -> None:
    original = _input().text
    client = FakeClient([_answer([original.upper() + ".", THREE[1], THREE[1]])])
    proposal = enhance_context(
        _input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert [v.text for v in proposal.versions] == [THREE[1]]


def test_one_bad_version_is_dropped_and_the_others_kept() -> None:
    client = FakeClient([_answer([THREE[0], "x" * 301, "🍔 " + THREE[2]])])
    proposal = enhance_context(
        _input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert [v.text for v in proposal.versions] == [THREE[0]]


def test_when_every_version_fails_the_most_useful_refusal_is_raised() -> None:
    client = FakeClient([_answer(["🍔 hola", "x" * 301, ""])])
    with pytest.raises(ContextTooLong):
        enhance_context(
            _input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
        )
    client = FakeClient([_answer([_input().text, _input().text, _input().text])])
    with pytest.raises(ContextUnavailable):
        enhance_context(
            _input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
        )


# -- m-25017274 (live on Bianki, 2026-11-13): a SCENE never asks for written text -------


def _scene_input(**overrides: Any) -> ContextInput:
    values: dict[str, Any] = {
        "text": "Un shawarma de carne recién hecho sobre la barra del local, con la salsa cayendo",
        "piece": "Imagen",
        "scene": True,
        "product": "Shawarma de carne",
        "highlights": (("Precio", "$22.000"),),
    }
    values.update(overrides)
    return ContextInput(**values)


def test_a_scene_request_says_its_key_facts_are_never_written() -> None:
    from qualify_api.creative.context_ai import SYSTEM_PROMPT

    scene = render_request(_scene_input(), None)
    assert "sin nada escrito en ella" in scene
    assert "DATOS CLAVE (solo orientan lo que se ve; nunca se escriben en la imagen):" in scene
    copy = render_request(_input(), None)
    assert "DATOS CLAVE:\n- precio: 20 $" in copy and "nunca se escriben" not in copy
    assert "La imagen NO lleva nada escrito" in SYSTEM_PROMPT
    assert CONTEXT_PROMPT_VERSION == "context-v5-scene-no-text"


@pytest.mark.parametrize(
    "version",
    [
        # verbatim from production, 2026-11-13
        "Plano cerrado del shawarma con la salsa cayendo. El precio $22.000 se ve claro.",
        "La barra del local, luz cálida. Precio 22.000 a la vista.",
        "Etiqueta con el precio legible en una esquina, el shawarma al centro.",
        "Cartel junto al plato, luz de tarde, salsa cayendo.",
        "Un letrero cercano y el shawarma sobre la barra.",
        "Rótulo grande con el texto del combo sobre la mesa.",
        "La barra del local, luz cálida, 22 000 en una esquina.",
    ],
)
def test_a_scene_version_that_shows_text_is_detected(version: str) -> None:
    assert scene_text_request(version, _scene_input()) != ""


@pytest.mark.parametrize(
    "version",
    [
        "Plano cerrado del shawarma, la salsa cayendo, luz cálida. Sin texto en la imagen.",
        "Vista amplia de la barra, sin letreros ni precios, luz natural.",
        "Una mano toma el shawarma sobre la barra. Nada escrito en la imagen.",
        "Dos shawarmas sobre la bandeja de madera, luz cálida.",  # a 2x1 seen, not written
    ],
)
def test_a_negated_or_clean_scene_version_passes(version: str) -> None:
    assert scene_text_request(version, _scene_input()) == ""


def test_the_owners_own_words_are_not_an_addition() -> None:
    """The scene field's own example names «la etiqueta» (the cup's printed label)."""
    own = _scene_input(text="Una mano sosteniendo el vaso con la etiqueta de frente")
    assert scene_text_request("El vaso con la etiqueta de frente, luz cálida.", own) == ""
    assert scene_text_request("El vaso y un cartel detrás.", own) == "cartel"


def test_scene_versions_that_show_text_are_dropped_and_the_rest_shown() -> None:
    clean = "Plano cerrado del shawarma con la salsa cayendo, luz cálida sobre la barra."
    client = FakeClient(
        [
            _answer(
                [clean, "La barra del local. Se ve el precio $22.000.", "Un letrero al fondo."],
                scene=True,
            )
        ]
    )
    proposal = enhance_context(
        _scene_input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert [v.text for v in proposal.versions] == [clean]


def test_when_every_scene_version_shows_text_the_failure_path_runs() -> None:
    client = FakeClient(
        [
            _answer(
                ["Precio $22.000 a la vista.", "Cartel con 22.000.", "Etiqueta clara."], scene=True
            )
        ]
    )
    with pytest.raises(ContextUnavailable):
        enhance_context(
            _scene_input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
        )


def test_copy_versions_still_carry_the_price() -> None:
    with_price = [
        "Quiero la smash doble a 20 $ con papas, promo de fin de semana.",
        "Quiero que se vea la smash doble jugosa: 20 $ este fin de semana.",
        "Quiero contarte que la smash doble está a 20 $ con el precio de promo.",
    ]
    client = FakeClient([_answer(with_price)])
    proposal = enhance_context(
        _input(), None, client_factory=lambda key: client, attribution=TEST_ATTRIBUTION
    )
    assert [v.text for v in proposal.versions] == with_price
