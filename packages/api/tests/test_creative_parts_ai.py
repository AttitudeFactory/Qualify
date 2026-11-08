"""`qualify_api.creative.parts_ai` without the network (VE-14 m-24921071): «Proponerme las
partes» asks Claude (simulated here) for 3-6 parts of a video by parts without a reel. The
answer validates as `VideoPartPlan`s the owner can edit, rides a `SHOT_VIDEO` brief with
its provenance, never reaches Seedance, and every call passes the price guard first."""

from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import anthropic
import httpx2
import pytest
from qualify_creative.adapters import byteplus_ark
from qualify_creative.angles import AngleBrand, AngleProduct, CreativeAngle
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    PART_DESCRIPTION_MAX,
    PARTS_MAX,
    MediaInputs,
    PartsProvenance,
    VideoPartPlan,
)

from qualify_api.claude_tools import ModelConfig
from qualify_api.creative import parts_ai
from qualify_api.creative.parts import neutral_people
from qualify_api.creative.parts_ai import (
    MAX_TOKENS,
    PARTS_MIN,
    PROPOSE_EFFORT,
    PROPOSE_MODEL,
    PROPOSE_PARTS_PROMPT_VERSION,
    PROPOSE_TOOL,
    PartsBrief,
    PartsProposalUnavailable,
    english_words,
    film_words,
    fit_to_target,
    guard_price,
    parse_parts,
    propose_parts,
    propose_system_prompt,
    sound_words,
)

from .test_content_service import make_brief

PRODUCT = AngleProduct(
    product_id=uuid4(),
    name="Producto estrella",
    description="Lo más pedido de la casa.",
    price_label="$18.000",
    photo_keys=("uploads/t/p1.jpg", "uploads/t/p2.jpg"),
)
BRAND = AngleBrand(name="Mi Marca", palette=("#112233", "#FFCC00"), typeface="Poppins")
BRIEF = PartsBrief(
    story="Cómo lo preparamos y dónde pedirlo hoy.",
    brand=BRAND,
    product=PRODUCT,
    target_seconds=20,
)
ANGLE = CreativeAngle(
    position=1, title="Recién hecho", scene="El producto sale humeante", hook="¿Ya pediste?"
)


def _rows(*seconds: int) -> list[dict[str, Any]]:
    return [
        {
            "description": f"Parte {i + 1}: el producto sobre la mesa, la imagen se acerca.",
            "seconds": s,
        }
        for i, s in enumerate(seconds)
    ]


def _response(blocks: list[Any], stop: str = "tool_use") -> Any:
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop,
        model="claude-sonnet-5-20260601",
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=900,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _tool_use(payload: dict[str, Any], use_id: str = "toolu_1") -> Any:
    return SimpleNamespace(type="tool_use", name=PROPOSE_TOOL, input=payload, id=use_id)


def _client(*responses: Any) -> tuple[Any, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        return responses[len(requests) - 1]

    return SimpleNamespace(messages=SimpleNamespace(create=create)), requests


def _propose(*responses: Any, **kwargs: Any) -> tuple[Any, list[dict[str, Any]]]:
    client, requests = _client(*responses)
    proposal = propose_parts(
        kwargs.pop("brief", BRIEF),
        kwargs.pop("angle", None),
        api_key="test-key",
        client_factory=lambda _key: client,
        **kwargs,
    )
    return proposal, requests


# -- criterion 1: the output validates as VideoPartPlan and can be edited ----------------


def test_the_answer_is_a_plan_of_reference_parts_with_its_provenance() -> None:
    proposal, requests = _propose(_response([_tool_use({"parts": _rows(5, 4, 6, 5)})]))

    assert len(proposal.parts) == 4
    assert all(isinstance(p, VideoPartPlan) for p in proposal.parts)
    assert {p.mode for p in proposal.parts} == {"reference"}
    assert all(p.analysis_id is None and not p.shot_indexes for p in proposal.parts)
    assert [p.seconds for p in proposal.parts] == [5, 4, 6, 5]
    assert proposal.total_seconds == 20
    prov = proposal.provenance
    assert prov.model_id == PROPOSE_MODEL
    assert prov.model_revision == "claude-sonnet-5-20260601"
    assert prov.prompt_version == PROPOSE_PARTS_PROMPT_VERSION
    assert prov.pricing_version == parts_ai.PRICING_VERSION
    assert len(prov.prompt_fingerprint) == 16
    assert prov.input_tokens == 1200 and prov.output_tokens == 900
    assert prov.cost_usd == Decimal("0.0114")  # 1200 x $2/M + 900 x $10/M
    assert len(requests) == 1


def test_the_owner_edits_the_plan_and_it_rides_a_video_by_parts_brief() -> None:
    proposal, _ = _propose(_response([_tool_use({"parts": _rows(5, 4, 6)})]))
    edited = list(proposal.parts)
    edited[1] = edited[1].model_copy(update={"description": "Unas manos lo sirven."})
    edited[1] = VideoPartPlan.model_validate(edited[1].model_dump())  # revalidates
    edited.append(VideoPartPlan(seconds=3, description="Cierre con el local."))
    del edited[0]

    brief = make_brief(
        variants=1,
        kind=ContentKind.SHOT_VIDEO,
        format=ContentFormat.REELS_9_16,
        topic=BRIEF.story,
        media=MediaInputs(
            parts=tuple(edited),
            product_keys=PRODUCT.photo_keys,
            parts_provenance=proposal.provenance,
        ),
    )

    assert [p.description for p in brief.media.parts][0] == "Unas manos lo sirven."
    assert brief.media.parts_provenance == proposal.provenance
    stored = MediaInputs.model_validate(brief.media.model_dump(mode="json"))
    assert stored.parts_provenance == proposal.provenance


def test_a_proposed_parents_parts_do_not_inherit_its_provenance() -> None:
    from qualify_api.creative.parts import _child_brief

    proposal, _ = _propose(_response([_tool_use({"parts": _rows(5, 4, 6)})]))
    parent = make_brief(
        variants=1,
        kind=ContentKind.SHOT_VIDEO,
        format=ContentFormat.REELS_9_16,
        topic=BRIEF.story,
        media=MediaInputs(
            parts=proposal.parts,
            product_keys=PRODUCT.photo_keys,
            parts_provenance=proposal.provenance,
        ),
    )
    child = _child_brief(parent, parent.media.parts[1], 2, None)

    assert child.kind is ContentKind.CLIP
    assert child.media.parts_provenance is None
    assert child.media.part is not None and child.media.part.mode == "reference"
    assert child.media.clip_reference_mode == "motion"


def test_provenance_belongs_to_a_video_by_parts_only() -> None:
    provenance = PartsProvenance(model_id=PROPOSE_MODEL, prompt_version="v")
    with pytest.raises(ValueError, match="video by parts"):
        make_brief(
            variants=1, kind=ContentKind.CLIP, media=MediaInputs(parts_provenance=provenance)
        )


def test_the_parse_bounds_the_answer() -> None:
    rows = [
        {"description": "  Un hombre joven   prepara el producto. ", "seconds": 2},
        {"description": "un hombre joven prepara el producto.", "seconds": 5},  # repeated
        {"description": "", "seconds": 5},
        {"description": "x" * (PART_DESCRIPTION_MAX + 50), "seconds": 30},
        {"description": "Unas manos lo empacan.", "seconds": "no"},
        *({"description": f"Parte extra {i}.", "seconds": 5} for i in range(5)),
    ]
    parts, problems = parse_parts({"parts": rows})

    assert problems == ()
    assert len(parts) == PARTS_MAX
    assert parts[0].description == "Una persona prepara el producto."
    assert parts[0].seconds == 4  # never a part shorter than Seedance makes
    assert len(parts[1].description) == PART_DESCRIPTION_MAX and parts[1].seconds == 10
    assert parts[2].seconds == 5


def test_too_few_parts_or_a_price_are_problems() -> None:
    _, few = parse_parts({"parts": _rows(5, 5)})
    assert few and f"entre {PARTS_MIN}" in few[0]
    rows = _rows(5, 5, 5)
    rows[1]["description"] = "El producto con un cartel de $18.000."
    parts, priced = parse_parts({"parts": rows})
    assert len(parts) == 3 and priced and "precio" in priced[0]
    assert parse_parts({"parts": "nope"})[0] == ()


# -- criterion 2: no Seedance call ---------------------------------------------------------


def test_a_proposal_never_reaches_seedance(monkeypatch: pytest.MonkeyPatch) -> None:
    vendor_calls: list[str] = []

    def refuse(name: str) -> Any:
        def call(*_args: Any, **_kwargs: Any) -> Any:
            vendor_calls.append(name)
            raise AssertionError(f"{name} must not run while proposing parts")

        return call

    monkeypatch.setattr(byteplus_ark._ArkClient, "_post", refuse("ark._post"))
    monkeypatch.setattr(byteplus_ark.SeedanceVideoAdapter, "generate", refuse("seedance.generate"))
    monkeypatch.setattr(byteplus_ark.SeedanceVideoAdapter, "submit", refuse("seedance.submit"))

    proposal, requests = _propose(_response([_tool_use({"parts": _rows(5, 5, 5)})]))

    assert len(proposal.parts) == 3
    assert vendor_calls == []
    assert len(requests) == 1  # one Claude call, nothing else


def test_the_module_knows_no_video_vendor() -> None:
    source = inspect.getsource(parts_ai)
    for name in ("byteplus", "seedance", "MediaProducer", "dispatch", "create_parts("):
        assert name not in source.split('"""', 2)[2], name


# -- the call: shape, corrective turn, failures -------------------------------------------


def test_the_call_is_one_strict_tool_with_the_story_and_no_price() -> None:
    _, requests = _propose(_response([_tool_use({"parts": _rows(5, 5, 5)})]), angle=ANGLE)
    request = requests[0]

    assert request["model"] == PROPOSE_MODEL
    assert request["output_config"] == {"effort": PROPOSE_EFFORT}
    assert request["tool_choice"] == {"type": "auto"}  # a thinking model
    assert request["max_tokens"] == MAX_TOKENS
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    (tool,) = request["tools"]
    assert tool["name"] == PROPOSE_TOOL and tool["strict"] is True
    assert tool["input_schema"]["additionalProperties"] is False
    user = request["messages"][0]["content"]
    assert BRIEF.story in user
    assert PRODUCT.name in user and "Poppins" in user and "#112233" in user
    assert ANGLE.title in user and ANGLE.hook in user
    assert "18.000" not in user  # a part never shows a price
    assert "como máximo 20 segundos, y no menos de 17" in user


def test_the_system_prompt_names_no_business() -> None:
    prompt = propose_system_prompt().casefold()
    for word in ("bianki", "polette", "shawarma", "yogur", "inmobiliaria", "agencia", "viaje"):
        assert word not in prompt


def test_a_broken_answer_is_corrected_once() -> None:
    bad = _rows(5, 5)
    proposal, requests = _propose(
        _response([_tool_use({"parts": bad}, "toolu_a")]),
        _response([_tool_use({"parts": _rows(5, 5, 5, 5)}, "toolu_b")]),
    )

    assert len(proposal.parts) == 4
    assert len(requests) == 2
    (result,) = requests[1]["messages"][-1]["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_a"
    assert result["is_error"] is True
    assert proposal.provenance.input_tokens == 2400  # both turns


def test_twice_broken_is_unavailable() -> None:
    with pytest.raises(PartsProposalUnavailable) as raised:
        _propose(
            _response([_tool_use({"parts": _rows(5)})]),
            _response([_tool_use({"parts": _rows(5)})]),
        )
    assert raised.value.stats is not None and raised.value.stats.turns == 2


def test_no_tool_call_is_asked_once_more() -> None:
    text = SimpleNamespace(type="text", text="Aquí va")
    proposal, requests = _propose(
        _response([text], stop="end_turn"),
        _response([_tool_use({"parts": _rows(4, 4, 4)})]),
    )
    assert len(proposal.parts) == 3
    assert requests[1]["messages"][-1]["content"] == f"Entrega la respuesta con {PROPOSE_TOOL}."


def test_a_refusal_is_unavailable() -> None:
    with pytest.raises(PartsProposalUnavailable):
        _propose(_response([], stop="refusal"))


def test_anthropic_busy_is_retryable() -> None:
    def create(**_kwargs: Any) -> Any:
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.RateLimitError(
            "busy", response=httpx2.Response(429, request=request), body=None
        )

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(PartsProposalUnavailable) as raised:
        propose_parts(BRIEF, api_key="k", client_factory=lambda _key: client)
    assert raised.value.retryable is True


def test_without_a_story_nothing_is_asked() -> None:
    client, requests = _client()
    with pytest.raises(ValueError):
        propose_parts(PartsBrief(story="   "), api_key="k", client_factory=lambda _key: client)
    assert requests == []


def test_without_a_key_it_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(PartsProposalUnavailable):
        propose_parts(BRIEF, client_factory=lambda _key: pytest.fail("no client without a key"))


# -- the price guard ---------------------------------------------------------------------


def test_an_unpriced_model_is_refused_before_anything_is_sent() -> None:
    built: list[str] = []
    with pytest.raises(PartsProposalUnavailable, match="price guard"):
        propose_parts(
            BRIEF,
            api_key="k",
            config=ModelConfig("claude-unknown-1", "medium"),
            client_factory=lambda key: built.append(key),  # type: ignore[func-returns-value]
        )
    assert built == []


def test_a_call_over_the_cap_is_refused_before_anything_is_sent() -> None:
    built: list[str] = []
    with pytest.raises(PartsProposalUnavailable, match="cap"):
        propose_parts(
            BRIEF,
            api_key="k",
            budget_usd=Decimal("0.001"),
            client_factory=lambda key: built.append(key),  # type: ignore[func-returns-value]
        )
    assert built == []


def test_the_guard_prices_from_the_versioned_table() -> None:
    worst = guard_price(
        ModelConfig(PROPOSE_MODEL, PROPOSE_EFFORT), input_tokens=3000, max_tokens=4000
    )
    # v7: Sonnet 5 cache write $2.50/M, output $10/M
    assert worst == Decimal("0.0475")


def test_the_pricing_version_is_the_generators() -> None:
    from qualify_api.creative.composition import PRICING_VERSION

    assert parts_ai.PRICING_VERSION == PRICING_VERSION


# -- only Spanish, and people without age or gender --------------------------------------


def test_english_words_send_the_plan_back_once() -> None:
    assert english_words("La hamburguesa smash also flota con the luz") == ("also", "the")
    assert english_words("Unas manos sostienen la smash burger con luz de neón") == ()
    rows = _rows(5, 5, 5)
    rows[0]["description"] = "La persona flota and also gira con el producto."
    _, problems = parse_parts({"parts": rows})
    assert problems and "«and», «also»" in problems[0] and "solo en español" in problems[0]

    proposal, requests = _propose(
        _response([_tool_use({"parts": rows}, "toolu_a")]),
        _response([_tool_use({"parts": _rows(5, 5, 5)}, "toolu_b")]),
    )
    assert len(requests) == 2 and len(proposal.parts) == 3
    assert "inglés" in requests[1]["messages"][-1]["content"][0]["content"]


def test_english_names_the_owner_gave_are_not_slips() -> None:
    brief = PartsBrief(
        story="Promo de Smash Is Love este viernes",
        brand=AngleBrand(name="The Burger House"),
        product=AngleProduct(product_id=uuid4(), name="Smash Is Love"),
    )
    rows = _rows(5, 5, 5)
    rows[0]["description"] = "Unas manos levantan la Smash Is Love frente a The Burger House."
    rows[1]["description"] = "La caja also gira sobre la mesa."
    _, problems = parse_parts({"parts": rows}, allowed_words=parts_ai.brief_words(brief))
    assert len(problems) == 1 and "«also»" in problems[0]

    rows[1]["description"] = "La caja gira sobre la mesa."
    proposal, requests = _propose(_response([_tool_use({"parts": rows})]), brief=brief)
    assert len(requests) == 1 and len(proposal.parts) == 3


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Unas manos jóvenes toman el producto.", "Unas manos toman el producto."),
        ("Un vaso chico sobre la mesa.", "Un vaso sobre la mesa."),
        ("Una persona joven sonríe.", "Una persona sonríe."),
        ("Un hombre joven muerde el producto.", "Una persona muerde el producto."),
        ("Dos mujeres conversan.", "Dos personas conversan."),
        ("Los niños ríen.", "Las personas ríen."),
        ("Comparte con jóvenes del barrio.", "Comparte con personas del barrio."),
        ("Jóvenes bailan en la calle.", "Personas bailan en la calle."),
        ("La chica, feliz, lo prueba.", "La persona, feliz, lo prueba."),
        ("Unas manos levantan el producto.", "Unas manos levantan el producto."),
        ("Llegan niños corriendo.", "Llegan personas corriendo."),
        ("Aparecen jóvenes en la terraza.", "Aparecen personas en la terraza."),
        ("Sus caras adolescentes sonríen.", "Sus caras sonríen."),
        ("Una mujer mayor lo prueba.", "Una persona lo prueba."),
        ("dos mujeres y la chica señalan", "dos personas y la persona señalan"),
    ],
)
def test_neutral_people_keeps_the_phrase_whole(before: str, after: str) -> None:
    assert neutral_people(before) == after


def test_parse_restores_the_capital_after_neutralizing() -> None:
    rows = _rows(5, 5, 5)
    rows[0]["description"] = "Unas manos jóvenes toman el producto."
    rows[1]["description"] = "Dos chicas lo comparten."
    parts, problems = parse_parts({"parts": rows})
    assert problems == ()
    assert parts[0].description == "Unas manos toman el producto."
    assert parts[1].description == "Dos personas lo comparten."


# -- v2: the total never exceeds what was asked ------------------------------------------


def test_a_total_over_the_target_is_trimmed_from_the_longest_parts() -> None:
    parts, problems = parse_parts({"parts": _rows(10, 8, 6)}, target_seconds=20)
    assert problems == ()
    assert [p.seconds for p in parts] == [7, 7, 6]
    assert sum(p.seconds for p in parts) == 20


def test_too_many_parts_for_the_target_go_back_to_the_model() -> None:
    _, problems = parse_parts({"parts": _rows(5, 5, 5, 5, 5, 5)}, target_seconds=20)
    assert problems and "menos partes" in problems[0]
    assert fit_to_target([4, 4, 4, 4, 4, 4], 20) is None
    assert fit_to_target([5, 5], 20) == [5, 5]


def test_the_call_never_returns_more_than_the_target() -> None:
    proposal, requests = _propose(_response([_tool_use({"parts": _rows(10, 10, 10, 9)})]))
    assert proposal.total_seconds <= BRIEF.target_seconds
    assert len(requests) == 1  # trimmed in code, no second paid turn


def test_v3_prompt_keeps_v2s_rules_in_everyday_words_and_no_business() -> None:
    prompt = propose_system_prompt()
    assert PROPOSE_PARTS_PROMPT_VERSION == "proponer-partes-v3.1"
    assert "nunca le agregues componentes" in prompt
    assert "Usarlo, probarlo o disfrutarlo no es el cierre" in prompt
    assert "consigue el producto: lo pide, lo recibe o se lo lleva" in prompt
    assert "UNA sola frase de 25 palabras como máximo" in prompt
    assert "nunca describas lo que se escucha" in prompt
    assert "No empieces por costumbre" in prompt
    assert "NUNCA supera la duración total pedida" in prompt
    assert "palabras de todos los días" in prompt and "«desde arriba»" in prompt
    assert "Nada de palabras técnicas de cine" in prompt
    for word in ("hamburgues", "carne", "queso", "plancha", "papas", "ingrediente", "sabor"):
        assert word not in prompt.casefold()
    for business in ("restaurante", "comida", "inmueble", "casa", "apartamento", "plato"):
        assert business not in prompt.casefold()
    # the rules the model reads use no film word except in the list that forbids them
    allowed_list = prompt.split("Nada de palabras técnicas")[1].split("Quien lo lee")[0]
    assert not film_words(prompt.replace(allowed_list, ""))


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Primer plano de unas manos que abren la bolsa.", ("primer plano",)),
        ("Toma cenital de la mesa; la cámara fija.", ("toma cenital", "camara fija")),
        (
            "PRIMERÍSIMO PRIMER PLANO del producto, fondo desenfocado.",
            ("primerisimo primer plano", "desenfocado"),
        ),
        ("Plano medio en el local, encuadre cerrado.", ("plano medio", "encuadre")),
        (
            "Una toma lateral con poca profundidad de campo y zoom.",
            ("una toma lateral", "profundidad de campo", "zoom"),
        ),
        ("El fondo de colores desenfocándose un poco.", ("desenfocandose",)),
        ("La cámara enfoca las manos.", ("enfoca",)),
        ("Las manos, enfocadas; luego enfocándose en la caja.", ("enfocadas", "enfocandose")),
        ("Toma macro del grano, con cambio de enfoque.", ("toma macro", "cambio de enfoque")),
        ("Toma cenital. Toma de detalle del borde.", ("toma cenital", "toma de detalle")),
        ("Una toma del mostrador. Toma frontal.", ("una toma", "toma frontal")),
        # accepted: a bare «Toma…»/«Tomas…» at the start of a sentence is never flagged,
        # noun or verb («Toma del vaso» is the verb)
        ("Toma del producto sobre la mesa.", ()),
        ("Tomas de la cocina con el horno encendido.", ()),
        # the verb «tomar», everyday Spanish and the other senses stay unflagged
        ("La persona toma desde la vitrina un pan.", ()),
        ("Una persona toma a la altura del pecho la caja.", ()),
        ("Toma la bolsa y sale. Toma su café con calma.", ()),
        ("Toma esa taza. Toma este vaso. Toma dos galletas. Toma aire y sonríe.", ()),
        ("Los clientes conversan en segundo plano.", ()),
        (
            "Una toma corta del mostrador. Unas tomas largas del lugar.",
            ("una toma corta", "unas tomas largas"),
        ),
        (
            "Esa toma entera de la vitrina, otra toma amplia del lugar.",
            ("esa toma entera", "otra toma amplia"),
        ),
        # after a bare «toma» the feminine qualifiers are the verb
        ("Una persona toma media porción.", ()),
        ("Se toma media hora. Se toma entera la bebida. Toma larga la fila.", ()),
        ("Espera media hora con la caja entera y una vista amplia.", ()),
        ("Una persona camina en cámara lenta hacia la puerta.", ()),
        ("Un enfoque fresco para empezar el día.", ()),
        ("Un local con enfoque en lo natural.", ()),
        ("La cámara con enfoque en la caída de cada capa.", ("camara con enfoque en",)),
        ("La gran venta macro del mes, se ve todo el lugar.", ()),
        ("Se ve desde arriba, de cerca; el fondo se ve borroso.", ()),
        ("Unas manos la toman y la levantan; una persona toma el vaso.", ()),
        ("Cebolla picada sobre un plato plano, la imagen se acerca.", ()),
        ("La cámara se acerca despacio a la vitrina.", ()),
    ],
)
def test_film_words_are_found_whole_and_without_accents(text: str, found: tuple[str, ...]) -> None:
    assert film_words(text) == found


def test_film_words_send_the_plan_back_once() -> None:
    rows = _rows(5, 5, 5)
    rows[1]["description"] = "Toma cenital del producto con el fondo desenfocado."
    _, problems = parse_parts({"parts": rows})
    assert len(problems) == 1
    assert "La parte 2 usa palabras de cine" in problems[0]
    assert "«toma cenital», «desenfocado»" in problems[0] and "«desde arriba»" in problems[0]

    proposal, requests = _propose(
        _response([_tool_use({"parts": rows}, "toolu_a")]),
        _response([_tool_use({"parts": _rows(5, 5, 5)}, "toolu_b")]),
    )
    assert len(requests) == 2 and len(proposal.parts) == 3
    assert "palabras de cine" in requests[1]["messages"][-1]["content"][0]["content"]
    assert proposal.provenance.turns == 2
    assert proposal.provenance.prompt_version == "proponer-partes-v3.1"


def test_a_long_description_goes_back_once() -> None:
    assert parts_ai.word_count("De cerca, 2 manos sostienen la caja.") == 6
    rows = _rows(5, 5, 5)
    rows[2]["description"] = " ".join(["palabra"] * (parts_ai.DESCRIPTION_WORDS_MAX + 1))
    _, problems = parse_parts({"parts": rows})
    assert len(problems) == 1
    assert "La parte 3 tiene 26 palabras" in problems[0] and "25 palabras" in problems[0]
    rows[2]["description"] = " ".join(["palabra"] * parts_ai.DESCRIPTION_WORDS_MAX)
    assert parse_parts({"parts": rows})[1] == ()

    long_rows = _rows(5, 5, 5)
    long_rows[0]["description"] = " ".join(["mesa"] * 30)
    proposal, requests = _propose(
        _response([_tool_use({"parts": long_rows}, "toolu_a")]),
        _response([_tool_use({"parts": _rows(5, 5, 5)}, "toolu_b")]),
    )
    assert len(requests) == 2 and proposal.provenance.turns == 2
    assert "palabras como máximo" in requests[1]["messages"][-1]["content"][0]["content"]


def test_film_words_twice_are_unavailable_within_the_meter() -> None:
    rows = _rows(5, 5, 5)
    rows[0]["description"] = "Primer plano del producto girando."
    with pytest.raises(PartsProposalUnavailable) as caught:
        _propose(
            _response([_tool_use({"parts": rows}, "toolu_a")]),
            _response([_tool_use({"parts": rows}, "toolu_b")]),
        )
    assert "palabras de cine" in str(caught.value)
    assert caught.value.stats is not None and caught.value.stats.turns == 2


def test_a_film_word_the_owner_wrote_is_his() -> None:
    brief = PartsBrief(story="Quiero un zoom a la vitrina", brand=BRAND)
    rows = _rows(5, 5, 5)
    rows[0]["description"] = "Un zoom rápido a la vitrina."
    _, problems = parse_parts({"parts": rows}, allowed_words=parts_ai.brief_words(brief))
    assert problems == ()


@pytest.mark.parametrize(
    ("text", "found"),
    [
        # the four v3.1 outputs of PARTES-001 that described a sound
        ("Se ve de cerca el chisporroteo.", ("chisporroteo",)),
        ("La carne se dora y chisporrotea de cerca.", ("chisporrotea",)),
        ("El borde dorado chisporroteando.", ("chisporroteando",)),
        (
            "Se escucha la música; se escuchan risas y suena el timbre.",
            ("se escucha", "se escuchan", "suena"),
        ),
        (
            "Suenan las campanas con el ruido de la calle, sin sonidos raros.",
            ("suenan", "ruido de", "sonidos"),
        ),
        ("Se oye el crujido del pan, la corteza cruje.", ("se oye", "crujido", "cruje")),
        (
            "Un zumbido, un silbido y aplausos; una canción de fondo.",
            ("zumbido", "silbido", "aplausos", "cancion"),
        ),
        ("EL ACEITE CREPITA, la tapa hace un CHASQUIDO.", ("crepita", "chasquido")),
        # accepted: what one SEES stays unflagged
        ("Papas doradas y crujientes, una corteza crujiente.", ()),
        ("Una persona sonríe con una gran sonrisa.", ()),
        ("Sueña con su café; la clienta sueña despierta.", ()),
        ("Unas personas aplauden y una canta frente al mostrador.", ()),
        ("Una clase de zumba; un vaso de zumo.", ()),
        ("Unas papas humeantes sobre la mesa.", ()),
        (
            "Una voz en off presenta el local; se oyen voces y gritos, un chirrido.",
            ("voz en off", "se oyen", "voces", "gritos", "chirrido"),
        ),
        (
            "Bailan al ritmo de la música; suena música de fondo.",
            ("al ritmo de la musica", "suena", "musica de fondo"),
        ),
        ("Una crujiente corteza sonando al partirse.", ("sonando",)),
        # accepted: listening is a gesture, «oye» alone, opinions and figures of speech
        ("La asesora escucha a la clienta y la escuchan con calma.", ()),
        ("Oye, mira la vitrina; el cliente oye y sonríe.", ()),
        ("Un cartel de música en vivo junto a un show musical.", ()),
        ("El local hace ruido en redes.", ()),
        ("La idea suena bien, suena a verano; suenan mal las excusas.", ()),
        ("Suen\u0303a con su cafe\u0301 y sue\u00f1a despierta.", ()),  # decomposed accents
    ],
)
def test_sound_words_are_found_whole_and_without_accents(text: str, found: tuple[str, ...]) -> None:
    assert sound_words(text) == found


def test_sounds_ride_the_one_corrective_turn_with_the_other_problems() -> None:
    rows = _rows(5, 5, 5)
    rows[0]["description"] = "La carne chisporrotea en la plancha, primer plano."
    rows[2]["description"] = "Se escucha la música del local."
    _, problems = parse_parts({"parts": rows})
    assert len(problems) == 3
    assert "La parte 1 usa palabras de cine" in problems[0]
    assert "La parte 1 describe sonidos («chisporrotea»)" in problems[1]
    assert "La parte 3 describe sonidos («se escucha»)" in problems[2]
    assert "se ve" in problems[2]

    proposal, requests = _propose(
        _response([_tool_use({"parts": rows}, "toolu_a")]),
        _response([_tool_use({"parts": _rows(5, 5, 5)}, "toolu_b")]),
    )
    assert len(requests) == 2 and proposal.provenance.turns == 2
    correction = requests[1]["messages"][-1]["content"][0]["content"]
    assert "palabras de cine" in correction and correction.count("describe sonidos") == 2
    assert proposal.provenance.prompt_version == "proponer-partes-v3.1"


def test_sounds_twice_are_unavailable_within_the_meter() -> None:
    rows = _rows(5, 5, 5)
    rows[1]["description"] = "Se oye el crujido del pan recién horneado."
    with pytest.raises(PartsProposalUnavailable) as caught:
        _propose(
            _response([_tool_use({"parts": rows}, "toolu_a")]),
            _response([_tool_use({"parts": rows}, "toolu_b")]),
        )
    assert "describe sonidos" in str(caught.value)
    assert caught.value.stats is not None and caught.value.stats.turns == 2


def test_a_sound_word_the_owner_wrote_is_his() -> None:
    brief = PartsBrief(story="Quiero el local con música de fondo", brand=BRAND)
    rows = _rows(5, 5, 5)
    rows[0]["description"] = "Las mesas del local con música de fondo."
    _, problems = parse_parts({"parts": rows}, allowed_words=parts_ai.brief_words(brief))
    assert problems == ()
    rows[0]["description"] = "Las mesas con música suave."
    assert parse_parts({"parts": rows})[1] != ()


def test_a_clean_first_answer_records_one_turn() -> None:
    proposal, _ = _propose(_response([_tool_use({"parts": _rows(5, 5, 5)})]))
    assert proposal.provenance.turns == 1


def test_the_owner_is_promised_a_retry_only_when_it_may_work() -> None:
    busy = PartsProposalUnavailable("anthropic answered HTTP 429", retryable=True)
    refused = PartsProposalUnavailable("price guard", retryable=False)
    assert parts_ai.unavailable_text(busy) == parts_ai.PROPOSE_RETRY_TEXT
    assert "Vuelve a intentarlo" in parts_ai.PROPOSE_RETRY_TEXT
    assert parts_ai.unavailable_text(refused) == parts_ai.PROPOSE_UNAVAILABLE_TEXT
    assert "intent" not in parts_ai.PROPOSE_UNAVAILABLE_TEXT.lower()
