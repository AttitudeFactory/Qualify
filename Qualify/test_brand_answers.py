"""«Te faltan 3 cosas que solo tú sabes» (m-24854331, OL2-6): the approved copy, who takes
the path, where a returning owner opens, the rubro's examples, the B1 drafts (and that
one reaches the kit only on «Sí, así es»), «Atrás», «Lo hago después» and the finish."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.brand_kit_store import PREFILL_KEY
from qualify_api.creative.brand_prefill_review import STATE_APPROVED

from . import brand_answers, brand_minimal
from . import brand_answers_vm as vm
from . import brand_minimal_vm as minimal_vm
from . import creative_wizard_pages as wiz
from .auth_state import AuthState
from .brand_answers import BrandAnswersState
from .brand_minimal import BrandMinimalState
from .brand_proposal import BrandProposalState
from .creative_state import CreativeState

TENANT = UUID("c0000000-0000-4000-8000-0000000000e1")
BRAND = UUID("b0000000-0000-4000-8000-0000000000e1")

# --------------------------------------------------------------------------------------
# copy — literal, as approved (epic §7.10, T16–T28)
# --------------------------------------------------------------------------------------


def test_the_copy_is_the_approved_text() -> None:
    assert (vm.MISSING_TITLE, vm.ANSWER_NOW_LABEL, vm.LATER_LABEL) == (
        "Te faltan 3 cosas que solo tú sabes",
        "Responder ahora",
        "Lo hago después",
    )
    assert vm.APPROVED_NOTICE == "Listo. Guardamos tu identidad de marca."
    assert vm.counter(vm.Q_DISTINCT) == "1 de 3" and vm.counter(vm.Q_PHRASE) == "3 de 3"
    assert vm.counter(vm.SCREEN_MISSING) == ""
    assert (*vm.DONE_ITEMS, *(item for _k, _q, item in vm.QUESTIONS)) == (
        "Tu cuenta",
        "A qué te dedicas",
        "Tu logo y tus colores",
        "Tus etiquetas",
        "Qué te hace distinto",
        "Quién te compra",
        "Cómo le hablas a tus clientes",
    )
    assert tuple(q for _k, q, _i in vm.QUESTIONS) == (
        "¿Qué te hace distinto?",
        "¿Quién te compra?",
        "¿Cómo le dirías a un cliente que llegó algo nuevo?",
    )
    assert (vm.DRAFT_HINT, vm.DRAFT_CONFIRM_LABEL, vm.DRAFT_CORRECT_LABEL) == (
        "Lo escribimos leyendo tus publicaciones. Cámbialo si no es así.",
        "Sí, así es",
        "Corregir",
    )
    assert vm.TONE_LABEL == "Ajustar el tono (opcional)"
    assert (vm.READY_TITLE, vm.READY_BODY, vm.READY_CREATE_LABEL, vm.READY_BRAND_LABEL) == (
        "Tu marca está lista",
        "Cada publicación que crees va a salir con tu logo, tus colores y tu forma de "
        "hablar. Nada se publica sin que lo apruebes.",
        "Crear mi primera publicación",
        "Ver mi identidad de marca",
    )
    assert vm.EMPTY_ANSWER_HINT == "Para seguir, escribe tu respuesta."  # T27
    assert vm.SAVED_FOR_LATER == (  # T28
        "Guardamos lo que llevas. Cuando vuelvas, sigues con lo que te falta."
    )


def test_the_rubro_examples_are_the_approved_ones() -> None:
    assert vm.example_hints(vm.EXAMPLE_FOOD) == {
        vm.Q_DISTINCT: "Por ejemplo: «Hacemos todo el mismo día, con receta de la casa.»",
        vm.Q_BUYERS: "Por ejemplo: «Familias y oficinas de la zona que piden a domicilio.»",
        vm.Q_PHRASE: "Por ejemplo: «Llegó el combo nuevo: pruébalo esta semana.»",
    }
    assert vm.EXAMPLES[vm.EXAMPLE_ICE_CREAM][0] == "Helados de yogur sin azúcar añadida."
    assert vm.EXAMPLES[vm.EXAMPLE_REAL_ESTATE][1] == "Familias que buscan su primera casa."
    assert vm.EXAMPLES[vm.EXAMPLE_TRAVEL][2] == "Abrimos cupos para un destino nuevo."


def test_no_client_word_is_english_or_technical() -> None:
    words = " ".join(
        str(getattr(vm, name)) for name in dir(vm) if name.isupper() and not name.startswith("_")
    ).lower()
    for banned in ("brand kit", " post", "feed", "hashtag", "prompt", "error", "draft", "ok"):
        assert banned not in words, banned


# --------------------------------------------------------------------------------------
# who takes the path, and where it opens
# --------------------------------------------------------------------------------------


def _connect(state: str = STATE_APPROVED, **proposal: Any) -> dict[str, Any]:
    return {
        "sector": "food_drink",
        "rubro_text": "Heladería de yogur",
        "hashtags": [{"tag": "helados"}],
        PREFILL_KEY: {"status": "ok", "state": state, "proposal": {"connect": {}, **proposal}},
    }


def test_only_an_approval_with_rubro_logo_and_colours_takes_the_path() -> None:
    full = {"rubro": "Shawarmas", "has_logo": True, "palette": "#0f766e"}
    assert vm.applies(state="approved", **full)
    for state in ("changed", "discarded", "superseded", "proposed", ""):
        assert not vm.applies(state=state, **full), state
    assert not vm.applies(state="approved", **{**full, "rubro": " "})
    assert not vm.applies(state="approved", **{**full, "has_logo": False})
    assert not vm.applies(state="approved", **{**full, "palette": ""})
    assert vm.prefill_state(_connect()) == "approved"
    assert vm.prefill_state({}) == "" and vm.prefill_state({PREFILL_KEY: "x"}) == ""


def test_a_returning_owner_opens_on_the_first_question_still_empty() -> None:
    assert vm.resume_screen(vm.Answers()) == vm.SCREEN_MISSING  # right after «Aprobar»
    assert vm.resume_screen(vm.Answers(distinct="Hecho al día")) == vm.Q_BUYERS
    assert vm.resume_screen(vm.Answers(buyers="Familias")) == vm.Q_DISTINCT
    assert vm.resume_screen(vm.Answers("a", "b")) == vm.Q_PHRASE
    assert vm.resume_screen(vm.Answers("a", "b", "c")) == vm.Q_PHRASE  # to finish
    assert vm.resume_screen(vm.Answers("  ", "", "")) == vm.SCREEN_MISSING


def test_the_screens_walk_in_order_and_never_leave_the_path() -> None:
    assert vm.next_screen(vm.SCREEN_MISSING) == vm.Q_DISTINCT
    assert vm.next_screen(vm.Q_DISTINCT) == vm.Q_BUYERS
    assert vm.next_screen(vm.Q_PHRASE) == vm.Q_PHRASE
    assert vm.previous_screen(vm.Q_DISTINCT) == vm.SCREEN_MISSING
    assert vm.previous_screen(vm.Q_PHRASE) == vm.Q_BUYERS
    assert vm.clamp_screen("otra") == vm.SCREEN_MISSING


@pytest.mark.parametrize(
    ("sector", "rubro", "expected"),
    [
        ("food_drink", "Heladería de yogur", vm.EXAMPLE_ICE_CREAM),
        ("food_drink", "HELADOS artesanales", vm.EXAMPLE_ICE_CREAM),
        ("real_estate", "Asesoría", vm.EXAMPLE_REAL_ESTATE),
        ("", "Inmobiliaria en Cúcuta", vm.EXAMPLE_REAL_ESTATE),
        ("travel_lifestyle", "", vm.EXAMPLE_TRAVEL),
        ("", "Agencia de viajes", vm.EXAMPLE_TRAVEL),
        ("food_drink", "Shawarmas y ensaladas", vm.EXAMPLE_FOOD),
        ("fashion_beauty", "Peluquería", vm.EXAMPLE_FOOD),  # the fallback
        ("", "", vm.EXAMPLE_FOOD),
    ],
)
def test_each_rubro_gets_its_examples(sector: str, rubro: str, expected: str) -> None:
    assert vm.example_set(sector=sector, rubro=rubro) == expected


# --------------------------------------------------------------------------------------
# B1 drafts (contract of OL2-3, epic §7.5)
# --------------------------------------------------------------------------------------


def test_drafts_are_read_from_the_approved_proposal_only() -> None:
    borradores = {
        "distinto": {"texto": " Helado hecho cada mañana. ", "fuente": "hecho cada mañana"},
        "quien_compra": "Familias del barrio",
        "frase_ejemplo": {"texto": "", "fuente": ""},
        "tono": {"formal_casual": 70},
    }
    assert vm.drafts_from(_connect(borradores=borradores)) == {
        "distinto": "Helado hecho cada mañana.",
        "quien_compra": "Familias del barrio",
    }
    assert vm.drafts_from(_connect("proposed", borradores=borradores)) == {}
    assert vm.drafts_from(_connect()) == {}  # B1 off: no `borradores`
    assert vm.drafts_from(_connect(borradores=["x"])) == {}
    assert vm.drafts_from(_connect(borradores={"distinto": 3})) == {}
    assert vm.drafts_from({}) == {} and vm.drafts_from(None) == {}


def test_a_draft_never_stands_over_an_answer() -> None:
    drafts = {"distinto": "Hecho al día"}
    assert vm.shows_draft(drafts=drafts, question="distinto", answer="", correcting=False)
    assert not vm.shows_draft(drafts=drafts, question="distinto", answer="Mío", correcting=False)
    assert not vm.shows_draft(drafts=drafts, question="distinto", answer="", correcting=True)
    assert not vm.shows_draft(drafts=drafts, question="quien_compra", answer="", correcting=False)


# --------------------------------------------------------------------------------------
# the state
# --------------------------------------------------------------------------------------


class _States:
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

    for cls in (
        BrandAnswersState,
        BrandMinimalState,
        BrandProposalState,
        CreativeState,
        wiz.BrandWizardState,
        wiz.BrandConnectState,
    ):
        monkeypatch.setattr(cls, "get_state", get_state)
    return holder


def _on_path(states: _States, *, drafts: dict[str, str] | None = None) -> BrandAnswersState:
    state = states(BrandAnswersState)
    state.open(
        active=True,
        answers=vm.Answers(),
        hints=vm.example_hints(vm.EXAMPLE_FOOD),
        drafts=drafts or {},
        has_tags=True,
    )
    return state


async def test_the_example_is_help_text_never_the_saved_answer(states: _States) -> None:
    state = _on_path(states)
    assert state.step == vm.SCREEN_MISSING
    await BrandAnswersState.answer_now.fn(state)
    assert state.step == vm.Q_DISTINCT and state.counter_text == "1 de 3"
    assert state.current_hint.startswith("Por ejemplo: «Hacemos todo")
    creative = states(CreativeState)
    assert creative.kit_positioning == "" and creative.kit_audience == ""
    assert creative.kit_do_examples == ""


async def test_back_keeps_what_was_typed(states: _States) -> None:
    state = _on_path(states)
    await BrandAnswersState.answer_now.fn(state)
    creative = states(CreativeState)
    creative.kit_positioning = "Hecho al día"
    await BrandAnswersState.next_step.fn(state)
    creative.kit_audience = "Familias"
    await BrandAnswersState.prev_step.fn(state)
    assert state.step == vm.Q_DISTINCT
    assert (creative.kit_positioning, creative.kit_audience) == ("Hecho al día", "Familias")
    await BrandAnswersState.prev_step.fn(state)
    assert state.step == vm.SCREEN_MISSING  # the checklist
    await BrandAnswersState.answer_now.fn(state)
    assert state.step == vm.Q_PHRASE  # «Responder ahora»: the first one still empty


async def test_the_third_answer_is_the_first_example_of_the_kit(states: _States) -> None:
    state = _on_path(states)
    state.step = vm.Q_PHRASE
    creative = states(CreativeState)
    creative.kit_do_examples = "Otra frase del documento"
    await BrandMinimalState.set_phrase.fn(states(BrandMinimalState), "Llegó el sabor nuevo")
    assert creative.kit_do_examples.splitlines() == [
        "Llegó el sabor nuevo",
        "Otra frase del documento",
    ]


async def test_a_draft_reaches_the_kit_only_on_si_asi_es(states: _States) -> None:
    drafts = {vm.Q_DISTINCT: "Helado hecho cada mañana.", vm.Q_PHRASE: "Llegó un sabor nuevo."}
    state = _on_path(states, drafts=drafts)
    creative = states(CreativeState)
    await BrandAnswersState.answer_now.fn(state)
    assert state.current_draft == "Helado hecho cada mañana."
    assert creative.kit_positioning == ""  # shown, not saved
    await BrandAnswersState.confirm_draft.fn(state)
    assert creative.kit_positioning == "Helado hecho cada mañana."
    assert state.step == vm.Q_BUYERS  # and on to the next question
    # no draft for this one: «Sí, así es» does nothing
    await BrandAnswersState.confirm_draft.fn(state)
    assert creative.kit_audience == "" and state.step == vm.Q_BUYERS
    creative.kit_audience = "Familias"
    await BrandAnswersState.next_step.fn(state)
    await BrandAnswersState.confirm_draft.fn(state)
    assert states(BrandMinimalState).phrase == "Llegó un sabor nuevo."
    assert creative.kit_do_examples == "Llegó un sabor nuevo."
    assert state.step == vm.Q_PHRASE  # the last one stays, for «Terminar mi marca»


async def test_corregir_saves_what_the_owner_leaves_never_the_draft_alone(
    states: _States,
) -> None:
    state = _on_path(states, drafts={vm.Q_DISTINCT: "Helado hecho cada mañana."})
    creative = states(CreativeState)
    await BrandAnswersState.answer_now.fn(state)
    BrandAnswersState.correct_draft.fn(state)
    assert state.correcting and state.correction == "Helado hecho cada mañana."
    assert creative.kit_positioning == ""
    BrandAnswersState.set_correction.fn(state, "Helado de yogur hecho en casa.")
    await BrandAnswersState.next_step.fn(state)
    assert creative.kit_positioning == "Helado de yogur hecho en casa."
    assert not state.correcting and state.step == vm.Q_BUYERS


async def test_lo_hago_despues_saves_and_goes_back_to_the_checklist(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    from . import brand_finish

    saved: list[str] = []

    async def save_progress(_state: Any, flow: str) -> None:
        saved.append(flow)

    monkeypatch.setattr(brand_finish, "save_progress", save_progress)
    state = _on_path(states)
    state.step = vm.Q_BUYERS
    events = [e async for e in BrandAnswersState.save_for_later.fn(state)]
    assert saved == [minimal_vm.MINIMAL_FLOW]
    assert state.step == vm.SCREEN_MISSING
    assert vm.SAVED_FOR_LATER in str(events[-1])

    async def broken(_state: Any, _flow: str) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(brand_finish, "save_progress", broken)
    state.step = vm.Q_BUYERS
    events = [e async for e in BrandAnswersState.save_for_later.fn(state)]
    assert state.step == vm.Q_BUYERS and vm.SAVE_LATER_FAILED in str(events[-1])


async def test_finishing_saves_the_kit_and_shows_tu_marca_esta_lista(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    from . import brand_finish

    flows: list[str | None] = []

    async def save_brand_kit(_state: Any, flow: str | None = None) -> bool:
        flows.append(flow)
        return True

    monkeypatch.setattr(brand_finish, "save_brand_kit", save_brand_kit)
    monkeypatch.setattr(brand_answers, "_finish_route", _no_route)
    state = _on_path(states)
    state.step = vm.Q_PHRASE
    _ = [e async for e in BrandAnswersState.finish.fn(state)]
    assert flows == [minimal_vm.MINIMAL_FLOW]  # the five steps' own finish
    assert state.step == vm.SCREEN_READY
    assert states(wiz.BrandConnectState).voice_configured

    async def failed(_state: Any, flow: str | None = None) -> bool:
        return False

    async def explain(_state: Any) -> None:
        return None

    monkeypatch.setattr(brand_finish, "save_brand_kit", failed)
    monkeypatch.setattr(brand_answers, "_explain_finish_failure", explain)
    state.step = vm.Q_PHRASE
    _ = [e async for e in BrandAnswersState.finish.fn(state)]
    assert state.step == vm.Q_PHRASE  # the error stays on the question


async def _no_route(_state: Any) -> None:
    return None


def test_tu_marca_esta_lista_leads_only_to_its_own_routes(states: _States) -> None:
    state = _on_path(states)
    assert "/create" in str(BrandAnswersState.leave.fn(state, "/create"))
    assert not state.active
    assert "/brand/kit" in str(BrandAnswersState.leave.fn(state, "https://otro.sitio"))


# --------------------------------------------------------------------------------------
# the entry (`BrandMinimalState.enter` / `_read_entry`)
# --------------------------------------------------------------------------------------


def _patch_store(monkeypatch: pytest.MonkeyPatch, connect: dict[str, Any], **form: str) -> None:
    from qualify_api.creative import brand_kit_store

    from . import creative_provider
    from .creative_vm import KitFormVM

    class Store:
        def load_details(self, **_kw: Any) -> Any:
            return brand_kit_store.BrandKitDetails(
                connect={
                    **connect,
                    "progress": {"flow": "minimo", "completed": False, "logo_from_profile": True},
                },
                profile={"username": "heladeria.polar"},
            )

        def list_assets(self, **_kw: Any) -> list:
            return []

    monkeypatch.setattr(brand_kit_store, "BrandKitStore", Store)
    monkeypatch.setattr(creative_provider, "default_brand_id", lambda _t: BRAND)
    monkeypatch.setattr(
        creative_provider,
        "load_kit_form",
        lambda _t, _b: KitFormVM(palette_rgb="#0f766e,#f8fafc", **form),
    )


def test_an_approved_proposal_opens_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_store(monkeypatch, _connect(borradores={"quien_compra": "Familias"}))
    entry = brand_minimal._read_entry(TENANT)
    assert entry is not None and entry.answers_path
    assert entry.hints[vm.Q_DISTINCT] == "Por ejemplo: «Helados de yogur sin azúcar añadida.»"
    assert entry.drafts == {"quien_compra": "Familias"} and entry.has_tags


@pytest.mark.parametrize("state", ["changed", "discarded", "superseded"])
def test_every_other_owner_keeps_the_five_steps(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    _patch_store(monkeypatch, _connect(state))
    entry = brand_minimal._read_entry(TENANT)
    assert entry is not None and not entry.answers_path and entry.drafts == {}


def test_an_approval_without_colours_keeps_the_five_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_store(monkeypatch, _connect())
    from . import creative_provider
    from .creative_vm import KitFormVM

    monkeypatch.setattr(creative_provider, "load_kit_form", lambda _t, _b: KitFormVM())
    entry = brand_minimal._read_entry(TENANT)
    assert entry is not None and not entry.answers_path


async def _enter(states: _States, monkeypatch: pytest.MonkeyPatch, entry: Any) -> None:
    monkeypatch.setattr(brand_minimal, "_read_entry", lambda _t: entry)
    monkeypatch.setattr(brand_minimal, "_read_account_country", lambda _t: "VE")
    auth = states(AuthState)
    auth.session_tenant_id = str(TENANT)
    minimal = states(BrandMinimalState)
    _ = [e async for e in BrandMinimalState.enter.fn(minimal)]


def _entry(*, positioning: str = "", answers_path: bool = True) -> Any:
    facts = minimal_vm.KitFacts(
        socials_answered=True,
        rubro="Heladería",
        positioning=positioning,
        has_logo_answer=True,
        palette="#0f766e",
    )
    return brand_minimal._Entry(
        False,
        "negocio",
        facts,
        {"flow": "minimo", "completed": False},
        answers_path=answers_path,
        hints=vm.example_hints(vm.EXAMPLE_ICE_CREAM),
        has_tags=False,
    )


async def test_after_aprobar_the_checklist_replaces_paso_2_de_5(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _enter(states, monkeypatch, _entry())
    answers = states(BrandAnswersState)
    assert answers.active and answers.step == vm.SCREEN_MISSING and not answers.has_tags
    assert states(BrandMinimalState).entered


async def test_a_returning_owner_lands_on_the_first_unanswered_question(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _enter(states, monkeypatch, _entry(positioning="Sin azúcar añadida"))
    assert states(BrandAnswersState).step == vm.Q_BUYERS


async def test_off_the_path_the_five_steps_open_as_before(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    states(BrandAnswersState).active = True  # left from an earlier visit
    await _enter(states, monkeypatch, _entry(answers_path=False))
    assert not states(BrandAnswersState).active
    assert states(BrandMinimalState).step == minimal_vm.STEP_BUSINESS


# --------------------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------------------


def _js(text: str) -> str:
    """`text` as the compiler writes it (accents as «\\u00fa»)."""
    return json.dumps(text)[1:-1]


def test_the_page_carries_the_path_and_its_controls() -> None:
    rendered = str(brand_minimal.brand_minimal_index())
    for text in (
        vm.MISSING_TITLE,
        vm.ANSWER_NOW_LABEL,
        vm.LATER_LABEL,
        vm.EMPTY_ANSWER_HINT,
        vm.DRAFT_CONFIRM_LABEL,
        vm.DRAFT_CORRECT_LABEL,
        vm.TONE_LABEL,
        vm.READY_TITLE,
        vm.READY_CREATE_LABEL,
        vm.READY_BRAND_LABEL,
        "Terminar mi marca",
        "Paso ",  # the five steps are still there for everyone else
    ):
        assert _js(text) in rendered, text


def test_the_ready_screen_has_no_check_over_the_picture() -> None:
    """UX review (2026-10-25): a check over the picture repeats the title."""
    rendered = str(brand_answers._ready_view())
    assert "circle-check" not in rendered.lower() and "circle_check" not in rendered.lower()
    assert _js(vm.READY_BODY) in rendered


# -- founder, 2026-10-26: the title counts down (T16, T16b, T16c) ------------------------


def test_the_missing_title_counts_down() -> None:
    assert vm.missing_title(3) == "Te faltan 3 cosas que solo tú sabes"  # T16
    assert vm.missing_title(2) == "Te faltan 2 cosas que solo tú sabes"  # T16b
    assert vm.missing_title(1) == "Te falta 1 cosa que solo tú sabes"  # T16c


async def test_the_checklist_title_follows_the_answers(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    from . import brand_finish

    async def save_progress(_state: Any, _flow: str) -> None:
        return None

    monkeypatch.setattr(brand_finish, "save_progress", save_progress)
    state = _on_path(states)
    assert state.missing_title == vm.MISSING_TITLE  # n=3
    await BrandAnswersState.answer_now.fn(state)
    states(CreativeState).kit_positioning = "Sin azúcar añadida"
    await BrandAnswersState.prev_step.fn(state)  # back to the checklist
    assert state.missing_title == "Te faltan 2 cosas que solo tú sabes"
    await BrandAnswersState.answer_now.fn(state)
    states(CreativeState).kit_audience = "Familias"
    _ = [e async for e in BrandAnswersState.save_for_later.fn(state)]
    assert state.step == vm.SCREEN_MISSING
    assert state.missing_title == "Te falta 1 cosa que solo tú sabes"
    state.step = vm.Q_DISTINCT
    assert state.counter_text == "1 de 3"  # T17 stays fixed
