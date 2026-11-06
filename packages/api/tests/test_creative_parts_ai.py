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
from qualify_api.creative.parts_ai import (
    MAX_TOKENS,
    PARTS_MIN,
    PROPOSE_EFFORT,
    PROPOSE_MODEL,
    PROPOSE_PARTS_PROMPT_VERSION,
    PROPOSE_TOOL,
    PartsBrief,
    PartsProposalUnavailable,
    fit_to_target,
    guard_price,
    parse_parts,
    propose_parts,
    propose_system_prompt,
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
            "description": f"Toma {i + 1}: el producto sobre la mesa, cámara que se acerca.",
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
        *({"description": f"Toma extra {i}.", "seconds": 5} for i in range(5)),
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


def test_v2_prompt_names_the_new_rules_and_no_business() -> None:
    prompt = propose_system_prompt()
    assert PROPOSE_PARTS_PROMPT_VERSION == "proponer-partes-v2"
    assert "nunca le agregues componentes" in prompt
    assert "no es un \ncierre" in prompt or "no es un cierre" in prompt
    assert "No empieces por costumbre" in prompt
    assert "NUNCA supera la duración total pedida" in prompt
    for word in ("hamburgues", "carne", "queso", "plancha", "papas", "ingrediente", "sabor"):
        assert word not in prompt.casefold()
