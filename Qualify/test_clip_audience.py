"""m-25026509: «¿A quién le habla este video?» in a Clip (step 3) and in «Armar mi video
por partes». One optional value (`CreativeState.brief_audience`) shared by both places;
«Sin preferencia» sends nothing and keeps today's objective; each answer sets the
objective through `objective_for_level`; «Para quien aún no piensa en ti» hides the
catalog's «Precio» row and says so; the summary lists it only when given; a new piece
starts on «Sin preferencia»; other kinds never show or send it. Offline: no database,
no Claude."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.parts_ai import PartsBrief, PartsProposal
from qualify_creative.angles import AngleBrand
from qualify_creative.enums import AwarenessLevel, objective_for_level
from qualify_creative.schemas import PartsProvenance, VideoPartPlan

from . import creative_provider, variations_vm
from . import parts_start_provider as parts_provider
from . import parts_start_state as parts_state_module
from . import parts_start_vm as parts_vm
from .auth_state import AuthState
from .creative_state import CreativeState
from .creative_vm import (
    AUDIENCE_HINT,
    AUDIENCE_LABELS,
    AUDIENCE_NO_PRICE,
    AUDIENCE_NONE,
    AUDIENCE_NONE_LABEL,
    AUDIENCE_QUESTION,
    AUDIENCE_SUMMARY_LABEL,
    AUDIENCE_SUMMARY_NO_PRICE,
    PRICE_FACT_LABEL,
    audience_options,
    audience_value,
)
from .parts_start_state import PartsStartState

TENANT = UUID("00000000-0000-0000-0000-000000000001")
BRAND = UUID("00000000-0000-0000-0000-0000000000b1")
TODAY = "consideration"  # the screen's objective without an answer
LEVELS = [level.value for level in AwarenessLevel]


def _js(text: str) -> str:
    """A string as the compiled component carries it (non-ASCII escaped)."""
    return json.dumps(text)[1:-1]


def _clip() -> CreativeState:
    state = CreativeState()
    state.choose_kind("clip")
    state.brief_topic = "Nuestro shawarma mixto"
    state.catalog_items = [
        {
            "id": "p1",
            "name": "Shawarma",
            "photo_key": "",
            "photo_keys": "",
            "price_label": "$18.000",
        },
        {
            "id": "p2",
            "name": "Ensalada",
            "photo_key": "",
            "photo_keys": "",
            "price_label": "$15.000",
        },
    ]
    return state


def _price_rows(state: CreativeState) -> list[dict[str, str]]:
    return [row for row in state.brief_highlights if row.get("product")]


# --- the words -------------------------------------------------------------------------


def test_the_question_and_its_six_answers_in_the_owners_words() -> None:
    assert AUDIENCE_QUESTION == "¿A quién le habla este video?"
    assert AUDIENCE_HINT == (
        "Así el video le habla a ese cliente. Si no sabes, déjalo en «Sin preferencia»."
    )
    assert AUDIENCE_NO_PRICE == (
        "Este video no dirá el precio porque es para quien aún no piensa en ti. Elige otra "
        "opción si quieres mostrarlo."
    )
    assert AUDIENCE_SUMMARY_NO_PRICE == "Sin precio: el video es para quien aún no piensa en ti"
    assert audience_options() == (
        (AUDIENCE_NONE, "Sin preferencia"),
        ("unaware", "Para quien aún no piensa en ti"),
        ("problem_aware", "Para quien ya busca algo así"),
        ("solution_aware", "Para quien está comparando opciones"),
        ("product_aware", "Para quien te conoce pero no se decide"),
        ("most_aware", "Para quien está listo para comprar"),
    )
    words = " ".join(
        (AUDIENCE_QUESTION, AUDIENCE_HINT, AUDIENCE_NO_PRICE, AUDIENCE_SUMMARY_LABEL)
        + tuple(label for _v, label in audience_options())
    ).lower()
    for banned in ("consciencia", "awareness", "embudo", "funnel", "nivel"):
        assert banned not in words


def test_the_ideas_and_the_clip_share_one_list_of_labels() -> None:
    assert variations_vm.AUDIENCE_LABELS is AUDIENCE_LABELS


def test_only_a_level_is_kept_anything_else_is_sin_preferencia() -> None:
    assert audience_value(AUDIENCE_NONE) == ""
    assert audience_value("") == "" and audience_value("cualquiera") == ""
    assert audience_value(" unaware ") == "unaware"


# --- what reaches the brief ------------------------------------------------------------


def test_sin_preferencia_sends_nothing_and_keeps_todays_objective() -> None:
    state = _clip()
    assert state.audience_select_value == AUDIENCE_NONE
    form = state._generator_form()
    assert form["awareness_level"] is None and form["objective"] == TODAY
    brief = creative_provider.build_brief(BRAND, **form)
    assert brief.awareness_level is None and brief.objective.value == TODAY


@pytest.mark.parametrize("level", LEVELS)
def test_each_answer_reaches_the_brief_with_its_objective(level: str) -> None:
    state = _clip()
    state.set_brief_audience(level)
    form = state._generator_form()
    assert form["awareness_level"] == level
    assert form["objective"] == objective_for_level(level, TODAY)
    brief = creative_provider.build_brief(BRAND, **form)
    assert brief.awareness_level is AwarenessLevel(level)
    assert brief.objective.value == AwarenessLevel(level).objective.value


def test_choosing_sin_preferencia_again_goes_back_to_today() -> None:
    state = _clip()
    state.set_brief_audience("most_aware")
    state.set_brief_audience(AUDIENCE_NONE)
    assert state.brief_audience == ""
    assert state._generator_form()["awareness_level"] is None


def test_another_kind_never_sends_it() -> None:
    state = _clip()
    state.set_brief_audience("unaware")
    state.choose_kind("static_flyer")
    form = state._generator_form()
    assert form["awareness_level"] is None and form["objective"] == TODAY
    assert state.audience_no_price is False


def test_only_a_clip_shows_the_question() -> None:
    from .content_generator import _section_topic

    rendered = str(_section_topic())
    assert _js(AUDIENCE_QUESTION) in rendered and "clip-audience" in rendered
    assert '"clip"' in rendered  # drawn behind `brief_kind == "clip"`


# --- the price -------------------------------------------------------------------------


def test_for_someone_who_does_not_know_you_the_price_row_goes_and_comes_back() -> None:
    state = _clip()
    state.pick_catalog_product("p1")
    assert [(r["key"], r["value"]) for r in _price_rows(state)] == [(PRICE_FACT_LABEL, "$18.000")]
    state.set_brief_audience("unaware")
    assert _price_rows(state) == [] and state.audience_no_price is True
    # another product while it is chosen: still no price row
    state.pick_catalog_product("p2")
    assert _price_rows(state) == []
    state.set_brief_audience("problem_aware")
    assert [r["value"] for r in _price_rows(state)] == ["$15.000"]
    assert state.audience_no_price is False


def test_another_kind_gets_the_price_row_back() -> None:
    state = _clip()
    state.pick_catalog_product("p1")
    state.set_brief_audience("unaware")
    state.choose_kind("static_flyer")
    assert [r["value"] for r in _price_rows(state)] == ["$18.000"]


@pytest.mark.parametrize("level", [v for v in LEVELS if v != "unaware"])
def test_every_other_answer_keeps_the_price_row(level: str) -> None:
    state = _clip()
    state.pick_catalog_product("p1")
    state.set_brief_audience(level)
    assert [r["value"] for r in _price_rows(state)] == ["$18.000"]
    assert state.audience_no_price is False


# --- the summary and the reset ---------------------------------------------------------


def _summary(state: CreativeState, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(CreativeState, "_on_summary", lambda self: True)
    rows = CreativeState.gen_summary.fget(state)
    return {row["label"]: row["value"] for row in rows}


def test_the_summary_lists_the_answer_only_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _clip()
    assert AUDIENCE_SUMMARY_LABEL not in _summary(state, monkeypatch)
    state.set_brief_audience("solution_aware")
    assert _summary(state, monkeypatch)[AUDIENCE_SUMMARY_LABEL] == (
        "Para quien está comparando opciones"
    )
    state.choose_kind("static_flyer")
    assert AUDIENCE_SUMMARY_LABEL not in _summary(state, monkeypatch)


def test_a_new_piece_starts_on_sin_preferencia() -> None:
    state = _clip()
    state.set_brief_audience("most_aware")
    state._start_clean()
    assert state.brief_audience == "" and state.audience_select_value == AUDIENCE_NONE
    assert AUDIENCE_NONE_LABEL == "Sin preferencia"


# --- «Armar mi video por partes» -------------------------------------------------------


def test_the_parts_card_asks_the_same_question_on_the_same_value() -> None:
    from .parts_start_view import _question

    rendered = str(_question())
    assert _js(AUDIENCE_QUESTION) in rendered and "parts-audience" in rendered
    # one value: both places read and write `brief_audience` through the same handlers
    assert "audience_select_value" in rendered and "set_brief_audience" in rendered
    assert rendered.index(_js(AUDIENCE_QUESTION)) < rendered.index(_js(parts_vm.PROPOSE_LABEL))


def test_the_parts_brief_carries_the_answer_or_none() -> None:
    brief = parts_provider.build_brief("Mi video", AngleBrand(), None)
    assert brief.awareness_level is None
    brief = parts_provider.build_brief("Mi video", AngleBrand(), None, awareness_level="unaware")
    assert brief.awareness_level is AwarenessLevel.UNAWARE


def test_propose_hands_the_answer_to_the_parts_brief() -> None:
    seen: list[PartsBrief] = []

    def proposer(brief: PartsBrief, **_kw: Any) -> PartsProposal:
        seen.append(brief)
        return PartsProposal(
            parts=(VideoPartPlan(mode="reference", seconds=5, description="Parte uno."),),
            provenance=PartsProvenance(model_id="m", prompt_version="v", turns=1),
        )

    outcome = parts_provider.propose(
        TENANT,
        BRAND,
        story="Mi video",
        awareness_level="most_aware",
        facts=lambda *_a: (AngleBrand(), None),
        proposer=proposer,
    )
    assert outcome.ok and seen[0].awareness_level is AwarenessLevel.MOST_AWARE


class _Proxy:
    def __init__(self, state: PartsStartState, creative: CreativeState) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "creative", creative)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> Any:
        if cls is CreativeState:
            return self.creative
        assert cls is AuthState
        return SimpleNamespace(session_tenant_id=str(TENANT))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.state, name, value)


@pytest.mark.parametrize(("answer", "sent"), [("product_aware", "product_aware"), ("", "")])
async def test_the_card_proposes_with_step_threes_answer(
    monkeypatch: pytest.MonkeyPatch, answer: str, sent: str
) -> None:
    calls: list[dict[str, Any]] = []

    def propose(_tenant: UUID, _brand: UUID, **kw: Any) -> parts_provider.ProposalOutcome:
        calls.append(kw)
        return parts_provider.ProposalOutcome(error="x")

    monkeypatch.setattr(parts_state_module.provider, "propose", propose)
    creative = _clip()
    creative._brand_id = str(BRAND)
    creative.set_brief_audience(answer)
    proxy = _Proxy(PartsStartState(), creative)
    PartsStartState.set_story.fn(proxy.state, "Mi video")
    await PartsStartState.propose.fn(proxy)
    assert calls[0]["awareness_level"] == sent


# --- UX review (m-25026509): the summary's price, the closed line, the live region ------


def test_the_summary_says_why_there_is_no_price_never_ninguno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _clip()
    state.pick_catalog_product("p1")
    assert _summary(state, monkeypatch)["Datos clave"] == "Precio: $18.000"
    state.set_brief_audience("unaware")
    assert _summary(state, monkeypatch)["Datos clave"] == AUDIENCE_SUMMARY_NO_PRICE
    # a fact the owner added still shows as today
    state.brief_highlights = [*state.brief_highlights, {"key": "Horario", "value": "Hasta las 11"}]
    assert _summary(state, monkeypatch)["Datos clave"] == "Horario: Hasta las 11"
    # no product (nothing was hidden): «Ninguno» as before
    other = _clip()
    other.set_brief_audience("unaware")
    assert _summary(other, monkeypatch)["Datos clave"] == "Ninguno"


def test_after_the_parts_card_que_decir_shows_a_closed_line_until_cambiar() -> None:
    state = _clip()
    state.set_brief_audience("most_aware")
    assert state.audience_closed is False  # a plain clip: the open question
    state.parts_without_reel = True  # the plan came from «Armar mi video por partes»
    assert state.audience_closed is True
    assert state.audience_answer_label == "Para quien está listo para comprar"
    state.edit_audience()
    assert state.audience_closed is False  # «Cambiar» opens the dropdown in place
    state._start_clean()
    assert state.audience_editing is False


def test_the_closed_line_says_sin_preferencia_too() -> None:
    state = _clip()
    state.parts_without_reel = True
    assert state.audience_answer_label == "Sin preferencia"


def test_step_three_can_close_the_question_the_parts_card_never_does() -> None:
    from .audience_view import audience_question

    step3 = str(audience_question("clip-audience", closable=True))
    assert "audience_closed" in step3 and "edit_audience" in step3
    assert _js(AUDIENCE_SUMMARY_LABEL + ": ") in step3
    card = str(audience_question("parts-audience"))
    assert "audience_closed" not in card and "edit_audience" not in card


def test_the_no_price_status_is_always_mounted_and_only_its_text_changes() -> None:
    from .audience_view import audience_question

    rendered = str(audience_question("clip-audience"))
    # the status element is a sibling of the select, drawn unconditionally ...
    status = rendered[rendered.index('jsx(RadixThemesText,{"aria-live":"polite"') :]
    head, children = status.split("},", 1)
    assert 'role:"status"' in head
    # ... and only its text depends on the answer
    assert children.startswith("(reflex___state____state__qualify___creative_state")
    assert "audience_no_price" in children.split("?", 1)[0]
    assert _js(AUDIENCE_NO_PRICE) in children
    assert rendered.count('role:"status"') == 1
