"""«¿Cuánto te conviene pagar por un cliente?» (m-25091387): parsing, margin, flow."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.ads.investment_profile import InvestmentProfile, InvestmentProfileUnavailable
from qualify_api.tenancy.acting import current_acting_login

from . import investment_profile_state as state_module
from .auth_state import AuthState, business_state_classes
from .creative_state import CreativeState
from .investment_profile_page import investment_profile_card, investment_profile_index
from .investment_profile_provider import profile_vm
from .investment_profile_state import EDIT, STEPS, InvestmentProfileState
from .investment_profile_vm import (
    AMOUNT_CENTS,
    AMOUNT_LETTERS,
    AMOUNT_ZERO,
    CLIENTS_DECIMALS,
    EXACT_ZERO,
    PICK_OBJECTIVE,
    REVIEW_MARGIN,
    SAVED_NOTICE,
    STEP_TITLES,
    TICKET_EMPTY,
    ProfileAnswersVM,
    answer_rows,
    answers_from,
    cap_echo,
    card_title,
    first_problem,
    margin_options,
    margin_percent,
    money_copy,
    read_amount,
    read_clients,
    safe_return,
    save_values,
    step_problem,
    with_answer,
)
from .page_metadata import PAGE_DESCRIPTIONS
from .promotion_vm import STEP_TITLES as WIZARD_TITLES
from .ui.nav_vm import current_routes

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
LOGIN = UUID("b0000000-0000-4000-8000-000000000001")
USER = UUID("c0000000-0000-4000-8000-000000000001")
BRAND = UUID("d0000000-0000-4000-8000-000000000001")
CONTEXT = str(TENANT), str(LOGIN), str(USER)
PROMOTE = "/drafts/e0000000-0000-4000-8000-000000000001/promote"

ANSWERS = ProfileAnswersVM(
    objective="chat", ticket="20.000", margin_choice="mid", clients="15", cap="200.000"
)


def row(**changes: object) -> InvestmentProfile:
    now = datetime(2026, 11, 22, tzinfo=UTC)
    base = InvestmentProfile(
        brand_id=BRAND,
        currency="COP",
        average_ticket_minor=2_000_000,
        margin_basis_points=3000,
        margin_is_estimated=False,
        weekly_new_clients=15,
        monthly_cap_minor=20_000_000,
        objective="chat",
        updated_by=LOGIN,
        created_at=now,
        updated_at=now,
    )
    return replace(base, **changes)


def test_money_reads_thousands_dots_and_refuses_cents_and_letters() -> None:
    for typed in ("20000", "20.000", "$20.000", " 20 000 ", "$ 20,000"):
        assert read_amount(typed) == (20_000, "")
    assert read_amount("1.500.000") == (1_500_000, "")
    for typed in ("20.000,50", "20000.5", "20,5"):
        assert read_amount(typed) == (0, AMOUNT_CENTS)
    for typed in ("veinte mil", "20k", "20.00.0", "-5"):
        assert read_amount(typed) == (0, AMOUNT_LETTERS)
    assert read_amount("") == (0, TICKET_EMPTY)
    assert read_amount("0") == (0, AMOUNT_ZERO)
    assert read_clients("15") == (15, "")
    assert read_clients("1,5") == (0, CLIENTS_DECIMALS)
    assert cap_echo("200.000", "COP") == "Son $200.000 COP al mes, unos $46.000 COP por semana."


def test_margin_ranges_follow_the_owners_price_and_become_a_percent() -> None:
    labels = [label for _, label in margin_options("20.000", "COP")]
    assert labels == [
        "Poco: menos de $4.000 COP",
        "Entre $4.000 COP y $8.000 COP",
        "Entre $8.000 COP y $12.000 COP",
        "Más de $12.000 COP",
        "Lo sé exacto",
        "No lo sé todavía",
    ]
    # no price yet: only the two choices that do not need it
    assert [key for key, _ in margin_options("", "COP")] == ["exact", "unknown"]
    assert margin_percent("mid", "20.000", "") == (Decimal(30), "")
    assert margin_percent("unknown", "20.000", "") == (None, "")
    assert margin_percent("exact", "20.000", "8.000") == (Decimal("40.00"), "")
    assert margin_percent("exact", "30.000", "7.000") == (Decimal("23.33"), "")  # cut down
    assert margin_percent("exact", "20.000", "0") == (None, EXACT_ZERO)
    assert "menor que lo que paga tu cliente" in margin_percent("exact", "20.000", "20.000")[1]
    assert margin_percent("", "20.000", "")[1]


def test_answers_validate_per_step_and_save_in_hundredths() -> None:
    assert step_problem(ProfileAnswersVM(), 1) == PICK_OBJECTIVE
    assert first_problem(ANSWERS) == (0, "")
    assert first_problem(replace(ANSWERS, clients="0"))[0] == 4
    assert save_values(ANSWERS) == {
        "objective": "chat",
        "average_ticket_minor": 2_000_000,
        "margin_percent": Decimal(30),
        "weekly_new_clients": 15,
        "monthly_cap_minor": 20_000_000,
    }
    assert save_values(replace(ANSWERS, margin_choice="unknown"))["margin_percent"] is None
    # only known fields and choices are taken from the browser
    assert with_answer(ANSWERS, "objective", "visit") == ANSWERS
    assert with_answer(ANSWERS, "margin_choice", "all") == ANSWERS
    assert with_answer(ANSWERS, "_brand", "x") == ANSWERS
    assert with_answer(ANSWERS, "ticket", "9" * 41) == ANSWERS


def test_saved_profile_reads_back_and_reopens_each_answer() -> None:
    vm = profile_vm(row())
    assert (vm.ticket, vm.kept, vm.max_cost, vm.cap) == (20_000, 6_000, 6_000, 200_000)
    assert card_title(vm) == "Hasta $6.000 COP por cliente nuevo"
    assert answers_from(vm) == replace(ANSWERS, ticket="20.000", cap="200.000")
    assert answer_rows(vm)[0] == (1, "Lo que quieres", "Que te escriban")
    estimated = profile_vm(row(margin_is_estimated=True))
    assert answers_from(estimated).margin_choice == "unknown"
    assert answer_rows(estimated)[2][2] == "Unos $6.000 COP (aproximado)"
    exact = profile_vm(row(average_ticket_minor=3_000_000, margin_basis_points=2333))
    reopened = answers_from(exact)
    assert (reopened.margin_choice, reopened.margin_exact) == ("exact", "6.999")
    assert save_values(reopened)["margin_percent"] == Decimal("23.33")
    # saving the same exact answer again stores the same margin (no drift)
    exact = profile_vm(row(average_ticket_minor=1_500_000, margin_basis_points=3333))
    assert answers_from(exact).margin_exact == "5.000"
    assert save_values(answers_from(exact))["margin_percent"] == Decimal("33.33")
    typed = replace(ANSWERS, ticket="5.070", margin_choice="exact", margin_exact="833")
    percent = save_values(typed)["margin_percent"]
    points = int(percent * 100)  # type: ignore[operator]
    exact = profile_vm(row(average_ticket_minor=507_000, margin_basis_points=points))
    assert answers_from(exact).margin_exact == "833"
    assert save_values(answers_from(exact))["margin_percent"] == percent


def test_return_address_is_only_a_promotion_wizard() -> None:
    assert safe_return(PROMOTE + "?desde=semana&evento=x") == PROMOTE + "?desde=semana&evento=x"
    for bad in ("https://evil.test" + PROMOTE, "//evil.test", "/settings", PROMOTE + "#x", ""):
        assert safe_return(bad) == ""


class Context:
    _params = InvestmentProfileState._params
    _session = InvestmentProfileState._session
    _cached_brand = InvestmentProfileState._cached_brand
    _reset = InvestmentProfileState._reset

    def __init__(self, **params: str) -> None:
        self.auth = SimpleNamespace(
            session_tenant_id=str(TENANT), _auth_user_id=str(LOGIN), _session_user_id=str(USER)
        )
        self.creative = SimpleNamespace(_brand_id=str(BRAND))
        self.router = SimpleNamespace(url=SimpleNamespace(query_parameters=params, path=PROMOTE))
        self._context = CONTEXT
        self._brand = str(BRAND)
        self._operation = ""
        self._offer_skipped = False
        self._offer_settled = ("", "", "")
        self.profile = profile_vm(None)
        self.answers = ANSWERS
        self.loading = self.busy = self.offer = False
        self.mode, self.step, self.direction = STEPS, 1, "next"
        self.error = self.reason = self.notice = self.return_to = ""

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        return {AuthState: self.auth, CreativeState: self.creative}[state_class]


def test_steps_check_each_answer_and_the_last_one_saves() -> None:
    context = Context()
    context.answers = ProfileAnswersVM()
    assert InvestmentProfileState.next_step.fn(context) is None
    assert context.reason == PICK_OBJECTIVE and context.step == 1
    context.answers = ANSWERS
    assert InvestmentProfileState.next_step.fn(context) is not None
    assert context.step == 2 and context.reason == ""
    InvestmentProfileState.back_step.fn(context)
    assert context.step == 1 and context.answers == ANSWERS  # going back keeps it (N6)
    context.step = 5
    assert InvestmentProfileState.next_step.fn(context) is InvestmentProfileState.save


def test_change_opens_one_step_and_a_new_price_reviews_the_range() -> None:
    context = Context()
    context.profile = profile_vm(row())
    InvestmentProfileState.change.fn(context, 2)
    assert (context.mode, context.step) == (EDIT, 2)
    assert InvestmentProfileState.back_step.fn(context) is None  # no «Atrás» in an edit
    context.answers = replace(context.answers, ticket="40.000")
    InvestmentProfileState.next_step.fn(context)
    assert (context.step, context.notice) == (3, REVIEW_MARGIN)
    assert InvestmentProfileState.next_step.fn(context) is InvestmentProfileState.save
    InvestmentProfileState.leave.fn(context)
    assert context.mode == ""


@pytest.mark.asyncio
async def test_save_runs_as_the_login_and_shows_the_backend_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def save(tenant: UUID, brand: UUID, answers: ProfileAnswersVM) -> object:
        assert current_acting_login() == LOGIN
        calls.append((tenant, brand, answers))
        if len(calls) == 1:
            raise InvestmentProfileUnavailable("Por ahora solo podemos guardar montos en pesos.")
        return profile_vm(row())

    monkeypatch.setattr(state_module, "save_profile", save)
    context = Context()
    context.mode, context.return_to = EDIT, PROMOTE
    events = [event async for event in InvestmentProfileState.save.fn(context)]
    assert not events and context.error.startswith("Por ahora") and not context.busy
    events = [event async for event in InvestmentProfileState.save.fn(context)]
    assert calls[-1] == (TENANT, BRAND, ANSWERS)
    assert context.profile.exists and context.mode == "" and context.notice == SAVED_NOTICE
    assert len(events) == 1
    # an unanswered step is shown instead of calling the backend
    context.answers = replace(ANSWERS, cap="")
    events = [event async for event in InvestmentProfileState.save.fn(context)]
    assert context.step == 5 and context.reason and len(calls) == 2


@pytest.mark.asyncio
async def test_offer_comes_once_and_never_blocks_promoting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter([True, False])
    monkeypatch.setattr(state_module, "should_offer", lambda tenant, brand: next(answers))
    context = Context(desde="semana")
    redirect = await InvestmentProfileState.offer_gate.fn(context)
    assert "oferta=1" in str(redirect) and "promote%3Fdesde%3Dsemana" in str(redirect)
    assert await InvestmentProfileState.offer_gate.fn(context) is None  # settled now
    assert context._offer_settled == CONTEXT
    # «Ahora no» goes on to the wizard and is not asked again this session
    context = Context()
    context.return_to = PROMOTE
    InvestmentProfileState.skip_offer.fn(context)
    assert context._offer_skipped
    assert await InvestmentProfileState.offer_gate.fn(context) is None

    def broken(tenant: UUID, brand: UUID) -> bool:
        raise RuntimeError("database down")

    monkeypatch.setattr(state_module, "should_offer", broken)
    assert await InvestmentProfileState.offer_gate.fn(Context()) is None


def test_screens_render_with_their_route_and_reset_on_logout() -> None:
    rendered = str(investment_profile_index().render())
    for text in (
        "Antes de tu primer anuncio",
        "Responder (1 minuto)",
        "Ahora no, seguir con el anuncio",
        "Tus respuestas",
        "44px",
    ):
        assert text in rendered
    assert "Calcularlo" in str(investment_profile_card().render())
    assert STEP_TITLES[0] == WIZARD_TITLES[1]  # the same question as the wizard's
    assert current_routes(("/promotions", "/responder"), "/promotions/perfil") == ["/promotions"]
    assert "/promotions/perfil" in PAGE_DESCRIPTIONS
    assert InvestmentProfileState in business_state_classes()


def test_money_questions_follow_the_account_currency() -> None:
    """m-25091394: a dollar or Uruguayan account reads its own unit and examples."""
    assert cap_echo("100", "USD") == "Son $100 USD al mes, unos $23 USD por semana."
    copy = money_copy("USD")
    assert copy["ticket_label"] == "Lo que paga en una compra, en dólares"
    assert copy["cap_placeholder"] == "Ejemplo: 100"
    assert money_copy("UYU")["kept_label"] == "Me quedan, en pesos uruguayos"
    assert money_copy("COP")["margin_hint"].endswith("Te quedan $12.000 COP.")
