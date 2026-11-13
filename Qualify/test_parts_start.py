"""m-24921079: «Armar mi video por partes» without a reel — the card's words and rules
(`parts_start_vm`), the proposal seam (`parts_start_provider`, with fakes: no database, no
Claude) and the card's state (`PartsStartState`, the backend monkeypatched)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.claude_tools import Attribution
from qualify_api.creative.parts_ai import (
    PROPOSE_RETRY_TEXT,
    PROPOSE_UNAVAILABLE_TEXT,
    PartsBrief,
    PartsProposal,
    PartsProposalUnavailable,
)
from qualify_creative.angles import AngleBrand, AngleProduct
from qualify_creative.schemas import PartsProvenance, VideoPartPlan

from . import parts_start_provider as provider
from . import parts_start_state as state_module
from . import parts_start_vm as vm
from . import reel_parts_vm
from .auth_state import AuthState
from .creative_state import CreativeState
from .parts_start_state import PartsStartState, apply_to_creative

TENANT = UUID("00000000-0000-0000-0000-000000000001")
BRAND = UUID("00000000-0000-0000-0000-0000000000b1")
PRODUCT = uuid4()


def _proposal(n: int = 3) -> PartsProposal:
    parts = tuple(
        VideoPartPlan(mode="reference", seconds=5, description=f"Parte {i} de la hamburguesa.")
        for i in range(1, n + 1)
    )
    return PartsProposal(
        parts=parts,
        provenance=PartsProvenance(
            model_id="claude-sonnet-5", prompt_version="proponer-partes-v3.1", turns=1
        ),
    )


# --- the VM ----------------------------------------------------------------------------


def test_the_card_texts_read_literally() -> None:
    assert vm.CARD_TITLE == "¿Quieres un video más largo?"
    assert vm.CARD_ACTION == "Armar mi video por partes"
    assert vm.QUESTION == "¿De qué trata tu video?"
    assert vm.PROPOSE_LABEL == "Proponerme las partes"
    assert vm.MANUAL_LABEL == "Prefiero armarlas yo"
    assert vm.PROGRESS_TITLE == "Armando tu propuesta"
    assert vm.PROGRESS_STAGES == (
        "Pensando el comienzo",
        "Mostrando tu producto",
        "Cerrando con la invitación",
    )
    assert vm.CARD_HELP == (
        "Te proponemos las partes con tu producto y tu marca. Las revisas antes de crear nada."
    )
    assert vm.QUESTION_HINT == "Ej.: «Qué tiene de especial y cómo conseguirlo»."
    assert vm.EMPTY_TITLE == "Completa las partes de tu video"


def test_no_client_text_carries_english_or_film_words() -> None:
    texts = [
        vm.CARD_TITLE,
        vm.CARD_ACTION,
        vm.CARD_HELP,
        vm.QUESTION,
        vm.QUESTION_HINT,
        vm.PROPOSE_LABEL,
        vm.MANUAL_LABEL,
        vm.CLOSE_LABEL,
        vm.PROGRESS_TITLE,
        *vm.PROGRESS_STAGES,
        vm.EMPTY_TITLE,
        vm.EMPTY_BODY,
        vm.STORY_MISSING_TEXT,
        vm.NO_SESSION_TEXT,
    ]
    banned = ("post", "brand kit", "clip", "plano", "prompt", "reel", "toma")
    for text in texts:
        words = text.lower().replace("«", " ").replace("»", " ").split()
        assert not any(w.strip(".,:¿?") in banned for w in words), text


@pytest.mark.parametrize(
    ("kind", "from_reel", "has_plan", "shown"),
    [
        ("clip", False, False, True),
        ("clip", False, True, False),  # a plan is on screen: «Orden del clip» holds it
        ("clip", True, False, False),  # «Hacer uno parecido» has its reel's own plan
        ("image", False, False, False),
        ("avatar_video", False, False, False),
    ],
)
def test_the_card_shows_only_on_a_clip_without_a_plan(
    kind: str, from_reel: bool, has_plan: bool, shown: bool
) -> None:
    assert vm.card_shown(kind, from_reel=from_reel, has_plan=has_plan) is shown


def test_the_sentence_starts_from_the_product_or_what_the_owner_wrote() -> None:
    assert vm.initial_story("Smash  doble") == "Smash doble"
    assert vm.initial_story("Smash doble", "smash doble") == "Smash doble"
    assert vm.initial_story("Smash doble", " Combo  para pedir hoy ") == "Combo para pedir hoy"
    assert vm.initial_story("", "") == ""


def test_the_stages_walk_and_hold_on_the_last() -> None:
    assert [s["status"] for s in vm.progress_steps(0)] == ["running", "pending", "pending"]
    assert [s["status"] for s in vm.progress_steps(1)] == ["done", "running", "pending"]
    assert [s["status"] for s in vm.progress_steps(9)] == ["done", "done", "running"]
    assert vm.next_stage(0) == 1
    assert vm.next_stage(2) == 2
    assert [s["title"] for s in vm.progress_steps(0)] == list(vm.PROGRESS_STAGES)


def test_empty_entries_are_two_new_parts_that_ask_for_a_description() -> None:
    entries = vm.empty_entries()
    assert len(entries) == 2
    assert len({e["key"] for e in entries}) == 2
    for entry in entries:
        assert set(entry) == {"key", "plan", "person", "reason"}
        plan = VideoPartPlan.model_validate(entry["plan"])
        assert plan.mode == "reference"
        assert plan.analysis_id is None
        assert plan.notices == ("describe_it",)
        assert plan.description == ""
        assert entry["person"] is False and entry["reason"] == ""
    assert vm.plan_is_empty(entries)


def test_a_proposal_becomes_entries_in_order_without_a_reel() -> None:
    entries = vm.entries_from_proposal(_proposal(4))
    assert [e["plan"]["description"] for e in entries] == [
        f"Parte {i} de la hamburguesa." for i in range(1, 5)
    ]
    assert all(e["plan"]["analysis_id"] is None for e in entries)
    assert not vm.plan_is_empty(entries)
    assert not vm.plan_is_empty([])
    assert vm.provenance_json(_proposal())["prompt_version"] == "proponer-partes-v3.1"


def test_the_entries_are_the_shape_order_del_clip_lists() -> None:
    """Same entries as `reel_parts_vm`: its rows, plans and totals read them as they are."""
    entries = vm.entries_from_proposal(_proposal(3))
    rows = reel_parts_vm.part_rows(entries)
    assert [r["label"] for r in rows] == ["Parte 1 · 5 s", "Parte 2 · 5 s", "Parte 3 · 5 s"]
    assert {r["why"] for r in rows} == {""}
    assert reel_parts_vm.form_label(entries[0]["plan"]) == reel_parts_vm.FORM_NEW
    assert len(reel_parts_vm.plans(entries)) == 3
    assert reel_parts_vm.total_seconds(entries) == 15
    rest, at = reel_parts_vm.remove_part(entries, entries[1]["key"])
    assert at == 2 and len(rest) == 2


def test_error_texts_promise_a_retry_only_when_it_may_work() -> None:
    assert vm.error_text(PartsProposalUnavailable("down", retryable=True)) == PROPOSE_RETRY_TEXT
    assert vm.error_text(PartsProposalUnavailable("no key")) == PROPOSE_UNAVAILABLE_TEXT
    assert vm.error_text(RuntimeError("boom")) == PROPOSE_RETRY_TEXT
    assert PROPOSE_UNAVAILABLE_TEXT == "Hoy no podemos proponerte las partes. Inténtalo más tarde."


def test_no_error_sends_the_owner_to_a_button_the_card_hides() -> None:
    """While «Prefiero armarlas yo» is hidden, no text says «arma las partes tú»."""
    assert vm.MANUAL_PARTS_ENABLED is True
    errors = (
        PartsProposalUnavailable("down", retryable=True),
        PartsProposalUnavailable("no key"),
        RuntimeError("boom"),
    )
    for error in errors:
        text = vm.error_text(error).lower()
        assert "tú" not in text and "ármalas" not in text and "arma las" not in text


def test_the_retry_text_has_one_source_and_no_other_way_out() -> None:
    assert PROPOSE_RETRY_TEXT == (
        "No pudimos armar tu propuesta esta vez. Vuelve a intentarlo en un minuto."
    )
    assert not hasattr(vm, "RETRY_TEXT")


# --- the provider ----------------------------------------------------------------------


class FakeFacts:
    def __init__(self, product: AngleProduct | None = None) -> None:
        self.calls: list[tuple[UUID, UUID, str, str]] = []
        self.product = product

    def __call__(
        self, tenant_id: UUID, brand_id: UUID, product_id: str, product_name: str
    ) -> tuple[AngleBrand, AngleProduct | None]:
        self.calls.append((tenant_id, brand_id, product_id, product_name))
        return AngleBrand(name="Smash Hiro", sector="Comida"), self.product


class FakeProposer:
    def __init__(self, answer: PartsProposal | Exception) -> None:
        self.answer = answer
        self.briefs: list[PartsBrief] = []
        self.attributions: list[Attribution] = []

    def __call__(self, brief: PartsBrief, *, attribution: Attribution) -> PartsProposal:
        self.briefs.append(brief)
        self.attributions.append(attribution)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_propose_builds_the_brief_and_books_the_call_to_the_business() -> None:
    product = AngleProduct(product_id=PRODUCT, name="Smash doble", photo_keys=("a", "b"))
    facts, proposer = FakeFacts(product), FakeProposer(_proposal(3))
    outcome = provider.propose(
        TENANT,
        BRAND,
        story="  Smash doble:  de la plancha a la mano ",
        product_id=str(PRODUCT),
        product_name="Smash doble",
        facts=facts,
        proposer=proposer,
    )
    assert outcome.ok and len(outcome.entries) == 3
    assert outcome.provenance is not None
    assert facts.calls == [(TENANT, BRAND, str(PRODUCT), "Smash doble")]
    brief = proposer.briefs[0]
    assert brief.story == "Smash doble: de la plancha a la mano"
    assert brief.product == product
    assert brief.brand.name == "Smash Hiro"
    assert brief.target_seconds == 20
    attribution = proposer.attributions[0]
    assert (attribution.tenant_id, attribution.brand_id) == (TENANT, BRAND)
    assert attribution.feature == provider.FEATURE


def test_propose_without_a_sentence_calls_nothing() -> None:
    facts, proposer = FakeFacts(), FakeProposer(_proposal())
    outcome = provider.propose(TENANT, BRAND, story="   ", facts=facts, proposer=proposer)
    assert outcome.error == vm.STORY_MISSING_TEXT and outcome.entries == []
    assert facts.calls == [] and proposer.briefs == []


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (PartsProposalUnavailable("overloaded", retryable=True), PROPOSE_RETRY_TEXT),
        (PartsProposalUnavailable("price guard"), PROPOSE_UNAVAILABLE_TEXT),
        (RuntimeError("anything"), PROPOSE_RETRY_TEXT),
    ],
)
def test_a_failed_proposal_is_a_sentence_never_an_exception(error: Exception, text: str) -> None:
    outcome = provider.propose(
        TENANT, BRAND, story="Mi combo", facts=FakeFacts(), proposer=FakeProposer(error)
    )
    assert not outcome.ok and outcome.error == text
    assert outcome.entries == [] and outcome.provenance is None


def test_a_facts_failure_is_a_sentence_too() -> None:
    def broken(*_args: Any) -> Any:
        raise OSError("db down")

    outcome = provider.propose(
        TENANT, BRAND, story="Mi combo", facts=broken, proposer=FakeProposer(_proposal())
    )
    assert outcome.error == PROPOSE_RETRY_TEXT


def test_a_stock_pick_or_no_product_reads_no_catalog() -> None:
    assert provider.product_facts(TENANT, BRAND, "stock:123", "Taza") is None
    assert provider.product_facts(TENANT, BRAND, "", "") is None


# --- the state -------------------------------------------------------------------------


class Proxy:
    """`async with self` / `get_state` over plain states (as in `test_reel_wait_state`)."""

    def __init__(self, state: PartsStartState, creative: CreativeState, auth: Any) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "creative", creative)
        object.__setattr__(self, "auth", auth)

    async def __aenter__(self) -> Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> Any:
        if cls is CreativeState:
            return self.creative
        assert cls is AuthState
        return self.auth

    def __getattr__(self, name: str) -> Any:
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.state, name, value)


def _clip() -> CreativeState:
    creative = CreativeState()
    creative.choose_kind("clip")
    creative.selected_product_id = str(PRODUCT)
    creative.brief_product_ref = "Smash doble"
    creative.brief_topic = "Smash doble"
    creative._brand_id = str(BRAND)
    return creative


def _proxy(creative: CreativeState | None = None, tenant: str = str(TENANT)) -> Proxy:
    return Proxy(PartsStartState(), creative or _clip(), SimpleNamespace(session_tenant_id=tenant))


async def test_opening_the_card_prefills_the_sentence_with_the_product() -> None:
    proxy = _proxy()
    await PartsStartState.open_card.fn(proxy)
    assert proxy.state.open is True
    assert proxy.state.story == "Smash doble"
    assert proxy.state.phase == vm.PHASE_IDLE
    PartsStartState.close_card.fn(proxy.state)
    assert proxy.state.open is False


@pytest.fixture
def manual_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Prefiero armarlas yo» as it will be once UI-4's sheet exists."""
    monkeypatch.setattr(vm, "MANUAL_PARTS_ENABLED", True)


async def test_prefer_to_build_them_can_be_explicitly_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Option A (Deivid, 2026-11-10): no button and the event does nothing."""
    monkeypatch.setattr(vm, "MANUAL_PARTS_ENABLED", False)
    proxy = _proxy()
    await PartsStartState.open_card.fn(proxy)
    await PartsStartState.choose_manual.fn(proxy)
    assert proxy.creative.reel_parts_count == 0
    assert proxy.creative.brief_topic == "Smash doble"
    assert proxy.state.phase == vm.PHASE_IDLE and proxy.state.open is True
    from .parts_start_view import _question

    rendered = str(_question())
    assert vm.MANUAL_LABEL not in rendered
    assert vm.PROPOSE_LABEL in rendered and vm.CLOSE_LABEL in rendered


@pytest.mark.usefixtures("manual_on")
async def test_prefer_to_build_them_leaves_two_empty_parts_and_fills_que_decir() -> None:
    proxy = _proxy()
    await PartsStartState.open_card.fn(proxy)
    PartsStartState.set_story.fn(proxy.state, "Smash doble, de la plancha a la mano")
    await PartsStartState.choose_manual.fn(proxy)
    creative = proxy.creative
    assert creative.brief_topic == "Smash doble, de la plancha a la mano"
    assert creative.reel_parts_count == 2
    assert vm.plan_is_empty(creative._reel_plan)
    assert proxy.state.phase == vm.PHASE_READY and proxy.state.manual is True
    assert proxy.state.open is False


@pytest.mark.usefixtures("manual_on")
async def test_prefer_to_build_them_with_no_sentence_keeps_que_decir() -> None:
    proxy = _proxy()
    await PartsStartState.open_card.fn(proxy)
    PartsStartState.set_story.fn(proxy.state, "  ")
    await PartsStartState.choose_manual.fn(proxy)
    assert proxy.creative.brief_topic == "Smash doble"
    assert proxy.creative.reel_parts_count == 2


@pytest.fixture
def slow_propose(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`provider.propose` answering after a few stage ticks; records what it was asked."""
    seen: dict[str, Any] = {"calls": [], "answer": None, "stages": []}
    monkeypatch.setattr(vm, "STAGE_SECONDS", 0.01)

    def propose(tenant_id: UUID, brand_id: UUID, **kw: Any) -> provider.ProposalOutcome:
        import time

        seen["calls"].append((tenant_id, brand_id, kw))
        time.sleep(0.08)
        return seen["answer"]

    monkeypatch.setattr(state_module.provider, "propose", propose)
    original = PartsStartState._show_stage

    def show_stage(self: Any, stage: int) -> None:
        seen["stages"].append(stage)
        original(self, stage)

    monkeypatch.setattr(PartsStartState, "_show_stage", show_stage)
    return seen


async def test_proposing_walks_the_stages_then_fills_the_plan_and_que_decir(
    slow_propose: dict[str, Any],
) -> None:
    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance={"model_id": "m"}
    )
    proxy = _proxy()
    PartsStartState.set_story.fn(proxy.state, "Smash doble para pedir hoy")
    await PartsStartState.propose.fn(proxy)
    tenant, brand, kw = slow_propose["calls"][0]
    assert (tenant, brand) == (TENANT, BRAND)
    assert kw["story"] == "Smash doble para pedir hoy"
    assert kw["product_id"] == str(PRODUCT) and kw["product_name"] == "Smash doble"
    assert slow_propose["stages"][0] == 0 and max(slow_propose["stages"]) >= 1
    assert proxy.state.phase == vm.PHASE_READY and proxy.state.manual is False
    assert proxy.creative.brief_topic == "Smash doble para pedir hoy"
    assert proxy.creative.reel_parts_count == 3
    assert proxy.state.steps == []


async def test_a_failed_proposal_says_why_and_keeps_the_plan_untouched(
    slow_propose: dict[str, Any],
) -> None:
    slow_propose["answer"] = provider.ProposalOutcome(error=PROPOSE_RETRY_TEXT)
    proxy = _proxy()
    PartsStartState.set_story.fn(proxy.state, "Mi combo")
    await PartsStartState.propose.fn(proxy)
    assert proxy.state.phase == vm.PHASE_ERROR
    assert proxy.state.error == PROPOSE_RETRY_TEXT
    assert proxy.creative.brief_topic == "Smash doble"
    assert proxy.creative.reel_parts_count == 0
    # typing again clears the error
    PartsStartState.set_story.fn(proxy.state, "Mi combo de hoy")
    assert proxy.state.phase == vm.PHASE_IDLE and proxy.state.error == ""


async def test_no_sentence_or_no_session_asks_nothing(slow_propose: dict[str, Any]) -> None:
    proxy = _proxy()
    PartsStartState.set_story.fn(proxy.state, " ")
    await PartsStartState.propose.fn(proxy)
    assert proxy.state.error == vm.STORY_MISSING_TEXT
    assert proxy.state.phase == vm.PHASE_ERROR
    assert vm.STORY_MISSING_TEXT == "Cuéntanos de qué trata tu video para proponerte las partes."
    proxy = _proxy(tenant="")
    PartsStartState.set_story.fn(proxy.state, "Mi combo")
    await PartsStartState.propose.fn(proxy)
    assert proxy.state.error == vm.NO_SESSION_TEXT
    assert slow_propose["calls"] == []


async def test_a_new_piece_drops_a_late_proposal(
    slow_propose: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance=None
    )
    proxy = _proxy()
    PartsStartState.set_story.fn(proxy.state, "Mi combo")
    running = asyncio.ensure_future(PartsStartState.propose.fn(proxy))
    await asyncio.sleep(0.03)
    assert proxy.state.proposing
    PartsStartState.reset_start.fn(proxy.state)
    await running
    assert proxy.state.phase == vm.PHASE_IDLE
    assert proxy.creative.reel_parts_count == 0


def test_the_hook_writes_only_que_decir_and_the_plan() -> None:
    creative = _clip()
    apply_to_creative(creative, story="", entries=vm.empty_entries(), provenance=None)
    assert creative.brief_topic == "Smash doble"
    assert creative.reel_parts_count == 2
    apply_to_creative(creative, story="Otra frase", entries=[], provenance=None)
    assert creative.brief_topic == "Otra frase" and creative.reel_parts_count == 0


# --- the view --------------------------------------------------------------------------


def test_the_card_and_the_empty_note_build() -> None:
    from .parts_start_view import parts_empty_notice, parts_start_card

    assert parts_start_card() is not None
    assert parts_empty_notice() is not None


def test_the_hook_drops_a_plan_once_the_piece_is_not_a_clip_without_a_reel() -> None:
    creative = _clip()
    creative.brief_kind = "avatar_video"
    assert not apply_to_creative(
        creative, story="Frase", entries=vm.empty_entries(), provenance=None
    )
    assert creative.brief_topic == "Smash doble" and creative.reel_parts_count == 0
    creative = _clip()
    creative.from_reel_ideas = True
    assert not apply_to_creative(
        creative, story="Frase", entries=vm.empty_entries(), provenance=None
    )


# --- the wiring into the create flow (UI-3 list, UI-6 parent) ---------------------------


def test_a_one_part_clip_looks_as_today_and_offers_the_card() -> None:
    creative = _clip()
    assert creative.reel_plan_shown is False
    assert creative.parts_start_shown is True
    assert creative.reel_parts_count == 0 and creative.reel_plan_empty is False


def test_a_plan_without_a_reel_is_listed_in_orden_del_clip() -> None:
    creative = _clip()
    entries = vm.entries_from_proposal(_proposal(3))
    assert apply_to_creative(creative, story="Frase", entries=entries, provenance={"x": 1})
    assert creative.parts_without_reel is True
    assert creative._parts_provenance == {"x": 1}
    assert creative.reel_plan_shown is True
    assert creative.parts_start_shown is False
    assert creative.reel_plan_empty is False
    # a new piece / another kind forgets it: back to today's Clip
    creative._forget_ideas_origin()
    assert creative.parts_without_reel is False and creative._parts_provenance is None
    assert creative.reel_parts_count == 0 and creative.reel_plan_shown is False


def test_empty_parts_say_so_and_no_reel_is_named() -> None:
    creative = _clip()
    apply_to_creative(creative, story="", entries=vm.empty_entries(), provenance=None)
    assert creative.reel_plan_empty is True
    assert {r["describe"] for r in creative.reel_part_rows} == {reel_parts_vm.DESCRIBE_NEW_TEXT}


def test_reel_parts_vm_reads_a_plan_without_a_reel() -> None:
    parts = _proposal(2).parts
    entries = reel_parts_vm.entries_from_plan(None, parts)
    assert [(e["person"], e["reason"]) for e in entries] == [(False, ""), (False, "")]
    summary = reel_parts_vm.review_summary_text(entries, "smash doble")
    assert summary == (
        "Tu video de 10 s en 2 partes, con tu smash doble. "
        "Las 2 partes se hacen con tu producto y tu marca."
    )
    one = reel_parts_vm.entries_from_plan(None, parts[:1])
    assert reel_parts_vm.review_summary_text(one) == (
        "Tu video de 5 s en 1 parte. La parte se hace con tu marca."  # m-24985141
    )
    assert "reel" not in summary
    blank = reel_parts_vm.entries_from_plan(None, vm.empty_parts())
    assert reel_parts_vm.part_rows(blank)[0]["describe"] == "Falta contar qué pasa en esta parte."


async def test_the_parent_carries_who_proposed_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from .test_reel_review_state import on_summary, press, session, with_month

    calls = session(monkeypatch)
    creative = _clip()
    provenance = vm.provenance_json(_proposal(3))
    entries = vm.entries_from_proposal(_proposal(3))
    assert apply_to_creative(creative, story="Mi smash", entries=entries, provenance=provenance)
    on_summary(with_month(creative, previews=10))
    assert creative.reel_review_text.startswith("Tu video de 15 s en 3 partes")
    await press(creative, "create_all_reel_parts")
    (options,) = calls
    assert options["provenance"] == provenance
    assert options["topic"] == "Mi smash" and len(options["parts"]) == 3


def test_submit_parts_brief_puts_the_provenance_on_the_parent() -> None:
    from .creative_provider import submit_parts_brief
    from .test_reel_parts_provider import BRAND as P_BRAND
    from .test_reel_parts_provider import TENANT as P_TENANT
    from .test_reel_parts_provider import USER as P_USER
    from .test_reel_parts_provider import Content, form_and_plans

    form, _ = form_and_plans()
    content = Content(left=10)
    proposal = _proposal(3)
    submit_parts_brief(
        P_TENANT,
        P_BRAND,
        P_USER,
        parts=proposal.parts,
        scope="all",
        provenance=vm.provenance_json(proposal),
        content=content,
        **form,
    )
    (brief,) = content.briefs
    assert brief.media.parts_provenance == proposal.provenance
    content = Content(left=10)
    submit_parts_brief(
        P_TENANT, P_BRAND, P_USER, parts=proposal.parts, scope="all", content=content, **form
    )
    assert content.briefs[0].media.parts_provenance is None


# --- review fixes (review-agent and UX, 2026-11-10) -------------------------------------


async def _in_flight(proxy: Proxy, change: Any) -> None:
    """A proposal running when `change` happens; waits for it to end."""
    PartsStartState.set_story.fn(proxy.state, "Mi combo")
    running = asyncio.ensure_future(PartsStartState.propose.fn(proxy))
    await asyncio.sleep(0.03)
    assert proxy.state.proposing
    change()
    await running


async def test_a_new_piece_never_receives_the_last_ones_proposal(
    slow_propose: dict[str, Any],
) -> None:
    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance={"model_id": "m"}
    )
    proxy = _proxy()
    events: list[Any] = []

    def new_piece() -> None:
        events.extend(CreativeState.start_new_piece.fn(proxy.creative))

    await _in_flight(proxy, new_piece)
    creative = proxy.creative
    assert creative.reel_parts_count == 0 and creative._parts_provenance is None
    assert creative.brief_topic == ""
    assert creative.reel_plan_shown is False
    # the new piece's card starts over: start_new_piece resets it, and until then the
    # card of the earlier piece is not this piece's (the view shows it closed)
    assert PartsStartState.reset_start in events
    assert proxy.state.piece != creative.parts_piece


async def test_another_product_drops_the_proposal(slow_propose: dict[str, Any]) -> None:
    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance=None
    )
    proxy = _proxy()
    await _in_flight(proxy, proxy.creative.clear_product)
    assert proxy.creative.reel_parts_count == 0
    assert proxy.creative.reel_plan_shown is False


async def test_a_business_switch_drops_the_proposal(slow_propose: dict[str, Any]) -> None:
    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance={"model_id": "m"}
    )
    proxy = _proxy()

    def switch() -> None:
        proxy.auth.session_tenant_id = "00000000-0000-0000-0000-000000000002"

    await _in_flight(proxy, switch)
    assert proxy.creative.reel_parts_count == 0
    assert proxy.creative.brief_topic == "Smash doble"
    assert proxy.state.phase == vm.PHASE_IDLE and proxy.state.error == ""


async def test_reopening_after_a_new_piece_starts_a_fresh_card() -> None:
    proxy = _proxy()
    await PartsStartState.open_card.fn(proxy)
    PartsStartState.set_story.fn(proxy.state, " ")
    proxy.state.phase, proxy.state.error = vm.PHASE_ERROR, vm.STORY_MISSING_TEXT
    proxy.creative._forget_ideas_origin()  # the piece changed
    await PartsStartState.open_card.fn(proxy)
    assert proxy.state.error == "" and proxy.state.phase == vm.PHASE_IDLE
    assert proxy.state.story == "Smash doble"
    assert proxy.state.piece == proxy.creative.parts_piece


def test_the_token_is_never_repeated_by_a_reset() -> None:
    state = PartsStartState()
    PartsStartState.reset_start.fn(state)
    first = state._token
    PartsStartState.reset_start.fn(state)
    assert first and state._token and state._token != first


def test_todo_listo_names_a_plan_without_a_reel_video_por_partes() -> None:
    creative = _clip()
    apply_to_creative(
        creative, story="", entries=vm.entries_from_proposal(_proposal(3)), provenance=None
    )
    assert creative.gen_kind_label == reel_parts_vm.PARTS_PIECE_LABEL == "Video por partes"


def test_taking_out_every_part_is_back_to_todays_clip() -> None:
    creative = _clip()
    apply_to_creative(
        creative, story="", entries=vm.entries_from_proposal(_proposal(2)), provenance={"a": 1}
    )
    for row in list(creative.reel_part_rows):
        CreativeState.remove_reel_part.fn(creative, row["key"])
    assert creative.reel_parts_count == 0
    assert creative.reel_plan_shown is False
    assert creative.parts_without_reel is False and creative._parts_provenance is None
    assert creative.parts_start_shown is True
    assert creative.gen_kind_label != reel_parts_vm.PARTS_PIECE_LABEL


def test_blocked_parts_without_a_reel_go_back_to_step_2_never_to_ideas() -> None:
    entries = vm.empty_entries() + vm.entries_from_proposal(_proposal(1))
    assert reel_parts_vm.parts_blocked_text(entries) == (
        "Falta contar qué pasa en las partes 1 y 2. Escríbelo para crear tu video."
    )
    one = vm.entries_from_proposal(_proposal(1)) + vm.empty_entries()[:1]
    assert reel_parts_vm.parts_blocked_text(one) == (
        "Falta contar qué pasa en la parte 2. Escríbelo para crear tu video."
    )
    every = vm.empty_entries()
    assert reel_parts_vm.parts_blocked_text(every) == (
        "Falta contar qué pasa en las partes 1 y 2. Escríbelo para crear tu video."
    )
    actions = reel_parts_vm.review_actions(every)
    assert actions.to_ideas is False and actions.back_to_parts is True


def test_a_plan_without_a_reel_never_says_the_reel_has_one_scene() -> None:
    creative = _clip()
    creative.reel_single_part = True  # left by anything earlier
    apply_to_creative(
        creative, story="", entries=vm.entries_from_proposal(_proposal(1)), provenance=None
    )
    assert creative.reel_single_part is False


def test_the_empty_state_body_says_what_to_show() -> None:
    assert vm.EMPTY_BODY == (
        "Te dejamos 2 partes para llenar: cuenta qué pasa en cada una y elige qué mostrar."
    )


def test_sending_a_piece_to_borradores_starts_the_card_over() -> None:
    creative = _clip()
    events = creative.review_in_drafts()
    assert PartsStartState.reset_start in events


# --- another product (review 2026-11-10, round 2) --------------------------------------


def _with_plan() -> CreativeState:
    creative = _clip()
    creative.catalog_items = [{"id": "other", "name": "Papas", "photo_key": "", "photo_keys": ""}]
    apply_to_creative(
        creative, story="", entries=vm.entries_from_proposal(_proposal(3)), provenance={"a": 1}
    )
    assert creative.reel_plan_shown
    return creative


def _gone(creative: CreativeState) -> None:
    assert creative.reel_parts_count == 0 and creative.reel_plan_shown is False
    assert creative.parts_without_reel is False and creative._parts_provenance is None
    assert creative.parts_start_shown is True


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.choose_product("other"),
        lambda c: c.clear_product(),
    ],
    ids=["choose_product", "clear_product"],
)
def test_another_product_takes_away_a_plan_without_a_reel(change: Any) -> None:
    creative = _with_plan()
    piece = creative.parts_piece
    change(creative)
    _gone(creative)
    assert creative.parts_piece > piece  # the card of the earlier product shows as new


def test_another_product_keeps_a_reels_plan() -> None:
    from .test_reel_parts_state import planned

    creative = planned()
    count = creative.reel_parts_count
    assert count > 0 and creative.reel_plan_shown
    creative.clear_product()
    assert creative.reel_parts_count == count and creative.reel_plan_shown


async def test_the_tap_sends_what_the_field_holds_not_the_debounced_value(
    slow_propose: dict[str, Any],
) -> None:
    """Live test 2026-11-10: typed, then «Proponerme» at once — the debounced
    `set_story` had not arrived, and the OLD sentence was proposed and written."""
    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance=None
    )
    proxy = _proxy()
    await PartsStartState.open_card.fn(proxy)
    assert proxy.state.story == "Smash doble"  # prefilled; the edit never reached the state
    await PartsStartState.propose.fn(proxy, "La arepa de la casa, para pedir hoy")
    assert slow_propose["calls"][0][2]["story"] == "La arepa de la casa, para pedir hoy"
    assert proxy.creative.brief_topic == "La arepa de la casa, para pedir hoy"
    assert proxy.state.story == "La arepa de la casa, para pedir hoy"


def test_the_button_reads_the_field_and_the_field_flushes_on_blur() -> None:
    from .parts_start_view import _question

    rendered = str(_question())
    assert "document.getElementById('parts-start-story')?.value" in rendered
    assert "onBlur" in rendered


async def test_the_new_sentence_reaches_the_provider_and_que_decir(
    slow_propose: dict[str, Any],
) -> None:
    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance=None
    )
    proxy = _proxy()
    await PartsStartState.propose.fn(proxy, "frase nueva")
    assert slow_propose["calls"][0][2]["story"] == "frase nueva"
    assert proxy.creative.brief_topic == "frase nueva"


async def test_a_too_long_sentence_is_cut_at_what_the_proposal_reads(
    slow_propose: dict[str, Any],
) -> None:
    from qualify_api.creative.parts_ai import STORY_MAX

    slow_propose["answer"] = provider.ProposalOutcome(
        entries=vm.entries_from_proposal(_proposal(3)), provenance=None
    )
    proxy = _proxy()
    await PartsStartState.propose.fn(proxy, "a" * (STORY_MAX + 500))
    sent = slow_propose["calls"][0][2]["story"]
    assert len(sent) == STORY_MAX and len(proxy.state.story) == STORY_MAX
    assert proxy.creative.brief_topic == sent


@pytest.mark.parametrize("junk", [None, 42, ["x"], {"a": 1}])
async def test_something_that_is_not_text_never_breaks_the_event(
    junk: Any, slow_propose: dict[str, Any]
) -> None:
    proxy = _proxy()
    PartsStartState.set_story.fn(proxy.state, junk)
    assert proxy.state.story == ""
    await PartsStartState.propose.fn(proxy, junk)
    if junk is None:  # nothing sent: the field's own state is used
        assert proxy.state.error == vm.STORY_MISSING_TEXT
    else:
        assert proxy.state.story == "" and proxy.state.error == vm.STORY_MISSING_TEXT
    assert slow_propose["calls"] == []


def test_the_field_holds_at_most_what_the_proposal_reads() -> None:
    from qualify_api.creative.parts_ai import STORY_MAX

    from .parts_start_view import _question

    assert f"maxLength:{STORY_MAX}" in str(_question()).replace(" ", "")
    assert vm.clean_story("  uno   dos  ") == "uno dos"
    assert len(vm.clean_story("b" * 2000)) == STORY_MAX
