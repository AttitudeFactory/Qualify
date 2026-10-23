"""«Tu marca» in five steps (m-24848529, MARCA-4): the step names and order, how a draft
of either old flow maps onto them, where an owner resumes, the one example phrase, the
«No tengo redes» way out, and that the five minimum answers make a kit the generator
reads without a warning (`readiness`)."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from qualify_api.creative.readiness import compute_readiness
from qualify_creative.schemas import BrandKit, ToneAxes

from . import brand_finish
from . import brand_minimal_vm as vm
from . import creative_wizard_pages as wiz
from .brand_minimal import BrandMinimalState
from .creative_state import CreativeState

# --------------------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------------------


def test_exactly_five_named_steps_in_the_decided_order() -> None:
    assert [title for _name, title, _sub in vm.STEPS] == [
        "Tus redes",
        "Tu negocio y rubro",
        "Tu logo",
        "Tus colores",
        "Cómo hablas",
    ]
    assert vm.TOTAL_STEPS == 5
    assert vm.FIRST_STEP == vm.STEP_SOCIALS and vm.LAST_STEP == vm.STEP_VOICE


def test_next_and_back_walk_by_name_and_never_leave_the_flow() -> None:
    assert vm.next_step(vm.STEP_SOCIALS) == vm.STEP_BUSINESS
    assert vm.next_step(vm.STEP_VOICE) == vm.STEP_VOICE
    assert vm.previous_step(vm.STEP_BUSINESS) == vm.STEP_SOCIALS
    assert vm.previous_step(vm.STEP_SOCIALS) == vm.STEP_SOCIALS
    assert vm.clamp_step("nada") == vm.STEP_SOCIALS
    assert vm.clamp_step(3) == vm.STEP_SOCIALS


def test_no_client_word_is_english_or_technical() -> None:
    words = " ".join(f"{title} {sub}" for _n, title, sub in vm.STEPS).lower()
    for banned in ("brand kit", "post", "feed", "brandboard", "insights", "prompt"):
        assert banned not in words


def test_every_unfinished_flow_resumes_on_the_five_steps() -> None:
    for flow in (brand_finish.MANUAL_FLOW, brand_finish.CONNECT_FLOW, vm.MINIMAL_FLOW):
        status = brand_finish.KitStatus(
            completed=False, progress={"flow": flow, "step": 1, "completed": False}
        )
        assert status.resume_route == "/brand"


# --------------------------------------------------------------------------------------
# old drafts → new steps
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (0, vm.STEP_BUSINESS),  # ¿Quién es la marca?
        (1, vm.STEP_LOGO),  # ¿Ya tienes logo?
        (2, vm.STEP_LOGO),  # Tu logo
        (3, vm.STEP_COLOURS),  # Tipografía (optional now) → its neighbour
        (4, vm.STEP_COLOURS),  # Paleta
        (5, vm.STEP_VOICE),  # ¿Todo correcto?
        (6, vm.STEP_VOICE),  # Así quedó tu marca
        (99, vm.STEP_VOICE),  # clamped
    ],
)
def test_a_manual_draft_maps_to_the_step_holding_its_data(step: int, expected: str) -> None:
    assert vm.step_from_progress({"flow": "manual", "step": step}) == expected


def test_the_mapping_covers_every_old_screen() -> None:
    assert len(vm._MANUAL_TO_STEP) == len(wiz.STEPS)
    assert len(vm._CONNECT_TO_STEP) == len(wiz.CONNECT_STEPS)


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (wiz._ACCOUNT_STEP, vm.STEP_SOCIALS),
        (wiz._PROFILE_STEP, vm.STEP_SOCIALS),
        (wiz._ACCOUNT_KIND_STEP, vm.STEP_BUSINESS),
        (wiz._RUBRO_STEP, vm.STEP_BUSINESS),
        (wiz._IDENTITY_STEP, vm.STEP_BUSINESS),
        (wiz._LOGO_QUESTION_STEP, vm.STEP_LOGO),
        (wiz._LOGO_UPLOAD_STEP, vm.STEP_LOGO),
        (wiz._TYPOGRAPHY_STEP, vm.STEP_COLOURS),
        (wiz._PALETTE_STEP, vm.STEP_COLOURS),
        (wiz._CONNECT_CONFIRM_STEP, vm.STEP_VOICE),
        (wiz._SORT_STEP, vm.STEP_VOICE),
        (wiz.CONNECT_LAST, vm.STEP_VOICE),
    ],
)
def test_a_connect_draft_maps_to_the_step_holding_its_data(step: int, expected: str) -> None:
    assert vm.step_from_progress({"flow": "connect", "step": step}) == expected


def test_this_flows_progress_is_read_by_name() -> None:
    assert vm.step_from_progress({"flow": "minimo", "step": "colores"}) == vm.STEP_COLOURS
    assert vm.step_from_progress({"flow": "minimo", "step": 3}) is None
    assert vm.step_from_progress({"flow": "minimo", "step": "otro"}) is None
    assert vm.step_from_progress({"flow": "manual", "step": "x"}) is None
    assert vm.step_from_progress(None) is None
    assert vm.step_from_progress({}) is None


_FULL = vm.KitFacts(
    socials_answered=True,
    rubro="shawarmas",
    positioning="Hecho al momento",
    audience="Estudiantes",
    has_logo_answer=True,
    palette="#0A3D2E",
    example="¡Llegó el combo nuevo!",
)


def test_resume_opens_the_saved_step_but_never_past_a_gap() -> None:
    assert vm.resume_step(vm.STEP_COLOURS, _FULL) == vm.STEP_COLOURS
    # a manual draft at ¿Todo correcto? has no rubro (the manual flow never asked it)
    from dataclasses import replace

    no_rubro = replace(_FULL, rubro="")
    assert vm.resume_step(vm.STEP_VOICE, no_rubro) == vm.STEP_BUSINESS
    no_palette = replace(_FULL, palette="")
    assert vm.resume_step(vm.STEP_VOICE, no_palette) == vm.STEP_COLOURS
    # an earlier saved step wins over a later gap
    assert vm.resume_step(vm.STEP_LOGO, no_palette) == vm.STEP_LOGO
    # Tus redes left halfway (a profile being read) stays there
    assert vm.resume_step(vm.STEP_SOCIALS, no_rubro) == vm.STEP_SOCIALS


def test_with_nothing_saved_the_flow_opens_on_tus_redes_or_the_first_gap() -> None:
    assert vm.resume_step(None, vm.KitFacts()) == vm.STEP_SOCIALS
    assert vm.resume_step(None, vm.KitFacts(positioning="algo")) == vm.STEP_BUSINESS
    assert vm.resume_step(None, _FULL) == vm.STEP_VOICE


def test_facts_from_a_saved_old_draft_keep_every_answer() -> None:
    facts = vm.facts_from_saved(
        positioning="Hecho al momento",
        audience="Estudiantes",
        palette="#112233, #445566",
        do_examples="\n¡Llegó el combo!\nOtro",
        connect={"rubro_text": "", "sector": "food"},
        profile={"username": "bianki"},
        logo_brief={},
        file_kinds=["font", "logo_version"],
        progress={"flow": "connect", "step": 8, "completed": False},
    )
    assert facts.socials_answered and facts.rubro == "food"
    assert facts.has_logo_answer and facts.example == "¡Llegó el combo!"
    assert vm.first_gap(facts) is None
    # a typography file alone is not a logo; a brief or the profile picture is
    only_font = vm.facts_from_saved(
        positioning="",
        audience="",
        palette="",
        do_examples="",
        connect=None,
        profile=None,
        logo_brief={"style": "  "},
        file_kinds=["font"],
        progress={},
    )
    assert not only_font.has_logo_answer and not only_font.socials_answered
    assert vm.facts_from_saved(
        positioning="",
        audience="",
        palette="",
        do_examples="",
        connect=None,
        profile=None,
        logo_brief=None,
        file_kinds=[],
        progress={"logo_from_profile": True, "started_without_socials": True},
    ).has_logo_answer


def test_a_kit_is_finished_only_without_unfinished_progress() -> None:
    assert vm.kit_finished(True, {})
    assert vm.kit_finished(True, {"completed": True})
    assert not vm.kit_finished(True, {"completed": False})
    assert not vm.kit_finished(False, {})
    assert vm.progress_of({"progress": {"flow": "minimo"}}) == {"flow": "minimo"}
    assert vm.progress_of({"progress": "x"}) == {}
    assert vm.progress_of(None) == {}


def test_each_step_says_what_continuar_needs() -> None:
    empty = vm.KitFacts()
    assert not vm.step_complete(vm.STEP_SOCIALS, profile_read=False, facts=empty)
    assert vm.step_complete(vm.STEP_SOCIALS, profile_read=True, facts=empty)
    for name in (vm.STEP_BUSINESS, vm.STEP_LOGO, vm.STEP_COLOURS, vm.STEP_VOICE):
        assert not vm.step_complete(name, profile_read=False, facts=empty)
        assert vm.step_complete(name, profile_read=False, facts=_FULL)


# --------------------------------------------------------------------------------------
# Cómo hablas → do_examples → readiness
# --------------------------------------------------------------------------------------


def test_the_phrase_goes_first_and_replaces_only_itself() -> None:
    assert vm.with_example_phrase("", "", "¡Llegó!") == "¡Llegó!"
    assert vm.with_example_phrase("Otra frase", "", "¡Llegó!") == "¡Llegó!\nOtra frase"
    assert vm.with_example_phrase("¡Llegó!\nOtra frase", "¡Llegó!", "¡Ya llegó!") == (
        "¡Ya llegó!\nOtra frase"
    )
    assert vm.with_example_phrase("¡Llegó!\nOtra frase", "¡Llegó!", "") == "Otra frase"
    assert vm.with_example_phrase("Otra frase", "", "Otra frase") == "Otra frase"
    assert vm.first_example("\n  \n Hola \nchao") == "Hola"


def test_the_five_minimum_answers_make_a_kit_the_generator_reads_without_a_warning() -> None:
    """positioning + audience (Tu negocio y rubro), one example (Cómo hablas) and the
    voice adopted on finishing → `can_generate`, so /create shows no «Completa tu marca»."""
    kit = BrandKit(
        brand_id=uuid4(),
        positioning="Shawarma hecho al momento",
        audience="Estudiantes de la zona",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        do_examples=("¡Llegó el combo nuevo! Pásate hoy.",),
        palette_rgb=("#0A3D2E",),
    )
    verdict = compute_readiness(kit, has_active_voice=True)
    assert verdict.can_distill and verdict.can_generate
    # without the phrase it is not enough — that is why Cómo hablas asks for it
    no_example = kit.model_copy(update={"do_examples": ()})
    assert not compute_readiness(no_example, has_active_voice=True).can_generate


# --------------------------------------------------------------------------------------
# the state
# --------------------------------------------------------------------------------------


class _States:
    """`get_state` for a standalone `BrandMinimalState`: one instance per state class."""

    def __init__(self) -> None:
        self.instances: dict[type, Any] = {}

    def __call__(self, cls: type) -> Any:
        if cls not in self.instances:
            self.instances[cls] = cls()
        return self.instances[cls]


@pytest.fixture
def states(monkeypatch: pytest.MonkeyPatch) -> _States:
    holder = _States()

    async def get_state(_self: object, cls: type) -> Any:
        return holder(cls)

    monkeypatch.setattr(BrandMinimalState, "get_state", get_state)
    monkeypatch.setattr(wiz.BrandWizardState, "get_state", get_state)
    monkeypatch.setattr(wiz.BrandConnectState, "get_state", get_state)
    return holder


async def test_no_tengo_redes_goes_to_step_two_without_prefilling(states: _States) -> None:
    connect = states(wiz.BrandConnectState)
    connect.profile_username = "otra.cuenta"
    connect.sector = "food"
    connect.country_code = "CO"
    connect.city = "Cúcuta"
    wizard = states(wiz.BrandWizardState)
    wizard.has_logo = wiz.HAS_LOGO_PROFILE
    state = BrandMinimalState()
    await BrandMinimalState.skip_socials.fn(state)
    assert state.step == vm.STEP_BUSINESS
    assert connect.started_without_socials
    assert (connect.profile_username, connect.sector, connect.country_code, connect.city) == (
        "",
        "",
        "",
        "",
    )
    assert wizard.has_logo == ""


async def test_back_keeps_what_was_written(states: _States) -> None:
    creative = states(CreativeState)
    creative.kit_positioning = "Hecho al momento"
    state = BrandMinimalState()
    state.step = vm.STEP_LOGO
    BrandMinimalState.prev_step.fn(state)
    assert state.step == vm.STEP_BUSINESS
    assert creative.kit_positioning == "Hecho al momento"


async def test_leaving_the_business_step_starts_the_search_in_the_background(
    states: _States,
) -> None:
    connect = states(wiz.BrandConnectState)
    connect.rubro_text = "shawarmas"
    state = BrandMinimalState()
    state.step = vm.STEP_BUSINESS
    fired = await BrandMinimalState.next_step.fn(state)
    assert state.step == vm.STEP_LOGO
    assert fired is not None and "run_discovery" in str(fired)
    # the same answers again: nothing restarts
    connect.discovery_answers = connect._answers()
    state.step = vm.STEP_BUSINESS
    assert await BrandMinimalState.next_step.fn(state) is None


async def test_the_phrase_fills_the_kits_examples(states: _States) -> None:
    creative = states(CreativeState)
    creative.kit_do_examples = "Una que ya estaba"
    state = BrandMinimalState()
    await BrandMinimalState.set_phrase.fn(state, "¡Llegó el combo!")
    await BrandMinimalState.set_phrase.fn(state, "¡Llegó el combo nuevo!")
    assert creative.kit_do_examples == "¡Llegó el combo nuevo!\nUna que ya estaba"
    assert state.phrase == "¡Llegó el combo nuevo!"


async def test_the_logo_answer_stays_on_the_same_step(states: _States) -> None:
    state = BrandMinimalState()
    state.step = vm.STEP_LOGO
    await BrandMinimalState.answer_logo.fn(state, "si")
    assert states(wiz.BrandWizardState).has_logo == "si"
    assert state.step == vm.STEP_LOGO
    # the profile picture only when it is a real one
    await BrandMinimalState.answer_logo.fn(state, wiz.HAS_LOGO_PROFILE)
    assert states(wiz.BrandWizardState).has_logo == "si"
    await BrandMinimalState.answer_logo.fn(state, "cualquier cosa")
    assert states(wiz.BrandWizardState).has_logo == "si"
    await BrandMinimalState.change_logo_answer.fn(state)
    assert states(wiz.BrandWizardState).has_logo == ""


def test_the_page_compiles_with_its_five_steps_and_its_controls() -> None:
    from .brand_minimal import brand_minimal_index

    rendered = str(brand_minimal_index())

    def shown(text: str) -> bool:  # the compiled page escapes non-ASCII characters
        return text in rendered or json.dumps(text)[1:-1] in rendered

    for text in ("Seguir después", "Atrás", "No tengo redes", "Mejora tu marca (opcional)"):
        assert shown(text), text
    assert all(shown(title) for _name, title, _sub in vm.STEPS)


async def test_progress_is_saved_by_step_name(states: _States) -> None:
    """`brand_finish` stores this flow's position as the step NAME (architect)."""
    state = BrandMinimalState()
    states.instances[BrandMinimalState] = state
    state.step = vm.STEP_COLOURS
    states(wiz.BrandConnectState).started_without_socials = True

    class Holder:
        async def get_state(self, cls: type) -> Any:
            return states(cls)

    progress = await brand_finish._progress_document(Holder(), vm.MINIMAL_FLOW, completed=False)
    assert progress["flow"] == "minimo" and progress["step"] == "colores"
    assert progress["started_without_socials"] is True
    assert vm.step_from_progress(progress) == vm.STEP_COLOURS
    # the old flows keep saving their positions
    states(wiz.BrandWizardState).step = 4
    manual = await brand_finish._progress_document(Holder(), "manual", completed=False)
    assert manual["step"] == 4


# -- UX review (m-24848529) --------------------------------------------------------------


def test_each_blocked_step_says_what_it_still_needs() -> None:
    assert set(vm.MISSING_HINTS) == set(vm.STEP_NAMES) - {vm.STEP_SOCIALS}
    assert vm.MISSING_HINTS[vm.STEP_VOICE] == (
        "Para terminar, escribe cómo se lo dirías a un cliente."
    )
    assert all(hint.startswith("Para ") for hint in vm.MISSING_HINTS.values())


def test_the_account_country_is_never_asked_twice() -> None:
    known = frozenset({"CO", "VE", "UY"})
    assert vm.account_country("", "ve", known) == "VE"
    # what a read profile or a draft already holds wins
    assert vm.account_country("CO", "VE", known) == "CO"
    # a country the step cannot name stays out
    assert vm.account_country("", "AR", known) == ""
    assert vm.account_country("", None, known) == ""


async def test_forgetting_a_profile_puts_the_accounts_country_back(states: _States) -> None:
    connect = states(wiz.BrandConnectState)
    connect.profile_username = "otra.cuenta"
    connect.country_code = "CO"
    connect.city = "Cúcuta"
    state = BrandMinimalState()
    state.account_country = "VE"
    await BrandMinimalState.skip_socials.fn(state)
    assert (connect.country_code, connect.city) == ("VE", "")


def test_the_optional_parts_open_only_when_asked() -> None:
    state = BrandMinimalState()
    assert not state.more_logo_versions and not state.show_place
    BrandMinimalState.show_more_logo_versions.fn(state)
    BrandMinimalState.open_place.fn(state)
    assert state.more_logo_versions and state.show_place


def test_the_logo_and_business_steps_ask_in_the_owners_words() -> None:
    from .brand_minimal import _MAIN_LOGO_VERSION, brand_minimal_index

    assert _MAIN_LOGO_VERSION == "imagotipo"  # the version the palette reads first
    rendered = str(brand_minimal_index())

    def shown(text: str) -> bool:
        return text in rendered or json.dumps(text)[1:-1] in rendered

    for text in (
        "Sube tu logo",
        "Una foto o imagen de tu logo. Con una basta.",
        "Tengo otras versiones de mi logo (opcional)",
        "Más opciones: país y ciudad",
        "Para seguir, toca la rueda y elige al menos un color.",
    ):
        assert shown(text), text


def test_the_tone_sliders_have_a_name_and_no_bare_number() -> None:
    import reflex as rx

    rendered = str(rx.fragment(*wiz._tone_sliders()))
    assert "Entre " in rendered
    assert "toString" not in rendered
