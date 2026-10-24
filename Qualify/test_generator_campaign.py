"""m-24820838: the generator's optional «Campaña» — pick one of the brand's campaigns,
create a new one there, or leave the piece independent; it shows in «Resumen» and is
applied to the draft once Generar created it."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from . import campaign_provider as cp
from . import creative_state as module
from .creative_state import CreativeState

LANZ = cp.CampaignOptionVM(id=str(uuid4()), name="Lanzamiento", color="violet")
NAVIDAD = cp.CampaignOptionVM(id=str(uuid4()), name="Navidad", color="pink")


def _js(text: str) -> str:
    return json.dumps(text)[1:-1]


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

    def __init__(self, state: CreativeState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


def _state() -> CreativeState:
    state = CreativeState()
    state.choose_category("script")
    state.brief_topic = "La smash doble cayendo en cámara lenta"
    state.gen_campaigns = [LANZ, NAVIDAD]
    return state


def _summary_rows(state: CreativeState) -> dict[str, dict[str, str]]:
    state.go_to_view(str(len(state.gen_views) - 1))
    return {row["label"]: row for row in state.gen_summary}


def test_the_campaign_view_is_behind_mas_opciones_right_before_the_summary() -> None:
    """CREAR-2 (m-24848530): «Campaña» is optional, folded in step 3 under «Más
    opciones», the step right before «Revisa y crea»."""
    state = _state()
    assert state.gen_views[-2:] == ["campaign", "summary"]
    assert [step["label"] for step in state.gen_view_steps][-2:] == [
        "Cómo la quieres",
        "Revisa y crea",
    ]


def test_an_independent_piece_is_the_default_and_generates_as_before() -> None:
    state = _state()
    assert state.gen_campaign == cp.NO_CAMPAIGN
    rows = _summary_rows(state)
    assert rows["Campaña"]["value"] == "Sin campaña (publicación independiente)"
    assert rows["Campaña"]["view"] == "campaign"
    # «Editar» opens step 3 with «Más opciones» unfolded
    state.edit_view(rows["Campaña"]["view"])
    assert state.gen_step_key == "how" and state.campaign_open and not state.rules_open
    state.go_to_view(rows["Campaña"]["index"])
    state.go_to_view("99")
    assert state.gen_problem == ""


def test_an_existing_campaign_is_named_in_the_summary() -> None:
    state = _state()
    state.set_gen_campaign(NAVIDAD.id)
    assert _summary_rows(state)["Campaña"]["value"] == "Navidad"
    state.set_gen_campaign("not-a-campaign")  # never a value the select does not offer
    assert state.gen_campaign == NAVIDAD.id


def test_a_new_campaign_preselects_the_next_colour_and_needs_a_name() -> None:
    state = _state()
    state.set_gen_campaign(cp.NEW_CAMPAIGN)
    assert state.gen_campaign_new_color == "blue"  # two campaigns already: the third colour
    state.set_gen_campaign_new_color("teal")  # not a campaign colour
    assert state.gen_campaign_new_color == "blue"
    state.set_gen_campaign_new_color("orange")
    assert state.gen_campaign_new_color == "orange"
    rows = _summary_rows(state)
    assert rows["Campaña"]["value"] == "Nueva (falta el nombre)"
    assert state.gen_problem != ""  # Generar refuses a nameless campaign
    state.set_gen_campaign_new_name("  Black   Friday ")
    assert _summary_rows(state)["Campaña"]["value"] == "Nueva: Black Friday"
    assert state.gen_problem == ""


def test_a_chosen_campaign_that_is_gone_leaves_the_piece_independent() -> None:
    state = _state()
    state.set_gen_campaign(NAVIDAD.id)
    state._set_gen_campaigns([LANZ])
    assert state.gen_campaign == cp.NO_CAMPAIGN


def test_review_in_drafts_starts_the_campaign_over_and_crear_otro_keeps_it() -> None:
    state = _state()
    state.set_gen_campaign(LANZ.id)
    state.new_generation()
    assert state.gen_campaign == LANZ.id
    state.set_gen_campaign(cp.NEW_CAMPAIGN)
    state.set_gen_campaign_new_name("Verano")
    state.review_in_drafts()
    assert (state.gen_campaign, state.gen_campaign_new_name) == (cp.NO_CAMPAIGN, "")


def test_the_view_offers_the_brands_campaigns_and_a_new_one() -> None:
    from .content_generator import _campaign_view, _create_view

    rendered = str(_campaign_view())
    for words in ("Campaña (opcional)", "Sin campaña", "+ Nueva campaña"):
        assert _js(words) in rendered
    assert "set_gen_campaign" in rendered and "set_gen_campaign_new_name" in rendered
    for key in cp.COLOR_LABELS:
        assert f"q-swatch q-tint-{key}" in rendered
    assert "set_gen_campaign" in str(_create_view())


# -- Generar: the campaign is applied to the draft it created ------------------------------


async def _generate(
    state: CreativeState, monkeypatch: pytest.MonkeyPatch, apply: object
) -> tuple[UUID, list[object]]:
    draft_id = uuid4()
    tenant_id, brand_id, user_id = uuid4(), uuid4(), uuid4()

    async def ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return tenant_id, brand_id, user_id

    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(module, "submit_brief", lambda *a, **kw: draft_id)
    monkeypatch.setattr(module, "apply_post_choice", apply)
    created = cp.CampaignOptionVM(id=str(uuid4()), name="Black Friday", color="orange")
    monkeypatch.setattr(module, "brand_campaign_options", lambda *a: [LANZ, NAVIDAD, created])
    events = [event async for event in CreativeState.submit_generator_form.fn(_Proxy(state))]
    return draft_id, events


async def test_generar_creates_the_new_campaign_with_the_piece(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    def apply(tenant_id: UUID, post_id: UUID, value: str, **kw: object) -> None:
        calls.append((post_id, value, kw["new_name"], kw["new_color"]))

    state = _state()
    state.set_gen_campaign(cp.NEW_CAMPAIGN)
    state.set_gen_campaign_new_name("Black Friday")
    state.set_gen_campaign_new_color("orange")
    draft_id, _ = await _generate(state, monkeypatch, apply)
    assert calls == [(draft_id, cp.NEW_CAMPAIGN, "Black Friday", "orange")]
    assert state.gen_draft_id == str(draft_id) and state.generator_view == "result"
    # «Crear otro» goes on in the campaign just created, not in a second new one
    assert state.gen_campaign == state.gen_campaigns[-1].id
    assert state.gen_campaign_new_name == ""


async def test_generar_assigns_an_existing_campaign(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    state = _state()
    state.set_gen_campaign(LANZ.id)
    draft_id, _ = await _generate(
        state, monkeypatch, lambda t, post_id, value, **kw: calls.append((post_id, value))
    )
    assert calls == [(draft_id, LANZ.id)]
    assert state.gen_campaign == LANZ.id


async def test_an_independent_piece_writes_no_campaign(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    state = _state()
    draft_id, _ = await _generate(state, monkeypatch, lambda *a, **kw: calls.append(a))
    assert calls == [] and state.gen_draft_id == str(draft_id)


async def test_a_campaign_that_cannot_be_saved_keeps_the_piece(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def apply(*a: object, **kw: object) -> None:
        raise cp.UnknownCampaign("gone")

    state = _state()
    state.set_gen_campaign(LANZ.id)
    draft_id, events = await _generate(state, monkeypatch, apply)
    assert state.gen_draft_id == str(draft_id) and state.generator_view == "result"
    toasts = [str(event) for event in events if "__toast" in str(event)]
    assert len(toasts) == 1
    assert "no se pudo guardar su campa" in toasts[0] and "Elige otra" in toasts[0]
