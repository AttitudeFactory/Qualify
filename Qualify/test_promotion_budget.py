"""m-25091389: the suggested starting budget on the budget step."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from qualify_api.ads.budget_suggestion import (
    MINIMUM_UNAVAILABLE,
    BudgetSuggestion,
    BudgetSuggestionUnavailable,
    suggest,
)
from qualify_api.ads.investment_profile import InvestmentProfile

from . import promotion_budget_provider as provider
from . import promotion_state as state_module
from .investment_profile_vm import safe_return
from .promotion_budget_vm import budget_hint, daily_line, field_amount, over_cap_line
from .promotion_page import _budget
from .promotion_state import PromotionState
from .test_promotion_audience import AudienceContext
from .test_promotion_wizard import SOURCE, TENANT, ZONE, review, valid_form

K = 100_000  # $1.000 COP in hundredths
NOW = datetime(2026, 11, 22, tzinfo=UTC)


def profile(cap: int, weekly: int = 5) -> InvestmentProfile:
    return InvestmentProfile(
        uuid4(), "COP", 50 * K, 4000, False, weekly, cap, "chat", uuid4(), NOW, NOW
    )


def general(**kwargs: object) -> BudgetSuggestion:
    return suggest(
        profile=None, market=None, meta_daily_minimum_minor=4 * K, currency="COP", **kwargs
    )


def form(budget: str = "", end: str = "2027-01-17T09:00"):  # noqa: ANN201
    return replace(valid_form(), budget=budget, end_local=end)


def test_full_card_before_an_amount_is_typed() -> None:
    hint = budget_hint(general(days=7), "ready", "", form(), ZONE)
    assert hint.mode == "full"
    assert hint.headline == ("Te sugerimos $20.000 COP al día durante 7 días (total $140.000 COP).")
    assert hint.reasons == ["Es un monto prudente para una primera prueba."]
    assert hint.general_values and hint.button == "Usar $140.000 COP"
    assert hint.pieces_note == "Como es tu primer anuncio, empieza con esta sola publicación."


def test_a_shorter_period_says_the_button_moves_the_dates() -> None:
    short = form(end="2027-01-12T09:00")  # 2 days on screen; the table asks for 7
    hint = budget_hint(general(days=2), "ready", "", short, ZONE)
    assert hint.button == "Usar $140.000 COP y 7 días"


def test_confirmation_once_the_field_holds_the_suggestion() -> None:
    found = general(days=7)
    assert field_amount(found) == "140000"
    hint = budget_hint(found, "ready", "", form("140000"), ZONE)
    assert hint.mode == "applied"
    assert hint.line == "Pusimos $140.000 COP para 7 días. Puedes cambiarlo abajo."


def test_another_amount_keeps_a_compact_suggestion_without_judging_it() -> None:
    hint = budget_hint(general(days=7), "ready", "", form("50000"), ZONE, compact=True)
    assert hint.mode == "compact" and hint.headline.startswith("Sugerencia: $20.000 COP")
    assert not hint.reasons and hint.button == "Usar $140.000 COP"
    # typed after the card showed: it stays whole, the field does not jump per keystroke
    assert budget_hint(general(days=7), "ready", "", form("5"), ZONE).mode == "full"


def test_minimum_over_the_cap_shows_no_amount_and_no_button() -> None:
    found = suggest(
        profile=profile(cap=5 * K),
        market=None,
        meta_daily_minimum_minor=8 * K,
        currency="COP",
    )
    hint = budget_hint(found, "ready", "", form(), ZONE)
    assert hint.mode == "blocked" and not hint.button and not hint.headline
    assert hint.line.startswith("Meta pide al menos $8.000 COP al día")


def test_with_history_the_field_gets_this_publications_share() -> None:
    found = general(days=7, has_previous_promotions=True)
    assert found.pieces > 1 and found.piece_total_minor < found.total_minor
    hint = budget_hint(found, "ready", "", form(), ZONE)
    assert hint.button == "Usar $42.000 COP"
    assert hint.headline == (
        "Te sugerimos $126.000 COP en total para 3 publicaciones: $42.000 COP para esta, "
        "unos $6.000 COP al día durante 7 días."
    )
    assert int(field_amount(found)) * 100 == found.piece_total_minor
    applied = budget_hint(found, "ready", "", form(field_amount(found)), ZONE)
    assert applied.line.startswith("Pusimos $42.000 COP para esta publicación, en 7 días.")


def test_loading_and_failure_never_block_the_field() -> None:
    assert budget_hint(None, "loading", "", form(), ZONE).mode == "loading"
    failed = budget_hint(None, "failed", MINIMUM_UNAVAILABLE, form(), ZONE)
    assert failed.mode == "none" and failed.line == MINIMUM_UNAVAILABLE
    assert budget_hint(None, "", "", form(), ZONE).mode == ""


def test_daily_line_rounds_down_to_the_unit() -> None:
    assert daily_line(form("50000"), ZONE, "COP") == "Son unos $7.142 COP al día durante 7 días."
    assert daily_line(form(""), ZONE, "COP") == ""
    assert daily_line(form("50000", end="2027-01-01T09:00"), ZONE, "COP") == ""


def test_over_the_cap_is_information_under_the_total() -> None:
    found = suggest(
        profile=profile(cap=200 * K), market=None, meta_daily_minimum_minor=4 * K, currency="COP"
    )
    assert over_cap_line(found, form("150000"), ZONE) == ""
    assert over_cap_line(found, form("250000"), ZONE) == (
        "Este monto pasa tu tope de $200.000 COP al mes. Puedes seguir si lo decidiste."
    )
    assert over_cap_line(general(), form("9999999"), ZONE) == ""  # no profile, no cap


def test_use_suggestion_fills_the_total_and_moves_dates_only_when_said() -> None:
    context = AudienceContext()
    context.form = form("25000", end="2027-01-12T09:00")
    context._budget_suggestion = general(days=2)
    PromotionState.use_budget_suggestion.fn(context)
    assert context.form.budget == "140000" and context.form.end_local == "2027-01-17T09:00"
    assert not context.review.review_id  # the amount changed: review again
    context.form = form("25000", end="2027-01-20T09:00")  # 10 days: dates stay
    context._budget_suggestion = general(days=10)
    PromotionState.use_budget_suggestion.fn(context)
    assert context.form.budget == "200000" and context.form.end_local == "2027-01-20T09:00"


class BudgetContext(AudienceContext):
    market_shown = True

    def __init__(self) -> None:
        super().__init__()
        self.budget_hint_status = ""
        self.budget_hint_message = ""
        self._budget_suggestion = None
        self._budget_source = ""
        self._budget_minimum = ("", 0)
        self._budget_operation = ""


@pytest.mark.asyncio
async def test_meta_minimum_is_read_once_per_source(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    def read(*args: object) -> BudgetSuggestion:
        calls.append(args)
        return general(days=7)

    monkeypatch.setattr(state_module, "read_budget_suggestion", read)
    context = BudgetContext()
    await PromotionState.load_budget_suggestion.fn(context)
    assert context.budget_hint_status == "ready" and calls[0][5] is None
    await PromotionState.load_budget_suggestion.fn(context)
    assert calls[1][5] == 4 * K  # the cached minimum: no second Meta call
    assert calls[1][1] == SOURCE and calls[1][3].tzinfo is not None


@pytest.mark.asyncio
async def test_unavailable_suggestion_shows_the_backend_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object) -> BudgetSuggestion:
        raise BudgetSuggestionUnavailable("Todavía no tenemos una sugerencia para esta moneda.")

    monkeypatch.setattr(state_module, "read_budget_suggestion", refuse)
    context = BudgetContext()
    await PromotionState.load_budget_suggestion.fn(context)
    assert context.budget_hint_status == "failed"
    assert context.budget_hint_message.startswith("Todavía no tenemos")
    monkeypatch.setattr(state_module, "read_budget_suggestion", lambda *a: 1 / 0)
    await PromotionState.load_budget_suggestion.fn(context)
    assert context.budget_hint_message == MINIMUM_UNAVAILABLE and context._budget_suggestion is None


@pytest.mark.asyncio
async def test_prepared_promotion_keeps_the_suggestion_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = BudgetContext()
    context._budget_suggestion, context._budget_source = general(), str(SOURCE)
    kept: list[tuple] = []
    monkeypatch.setattr(state_module, "prepare_preview", lambda *args: review())
    monkeypatch.setattr(state_module, "keep_market_estimate", lambda *args: None)
    monkeypatch.setattr(state_module, "keep_budget_suggestion", lambda *args: kept.append(args))
    await context._remote(confirm=False)
    assert kept and kept[0][0] == TENANT and kept[0][2] == general()
    context._budget_source = "another-source"  # a suggestion for another publication
    kept.clear()
    context.success, context._request_key = "", "second"
    await context._remote(confirm=False)
    assert not kept


def test_keeping_the_suggestion_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kwargs: object) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(provider, "record_budget_suggestion", boom)
    provider.keep_budget_suggestion(TENANT, uuid4(), general())  # logged


def test_profile_links_come_back_to_this_step() -> None:
    context = BudgetContext()
    context._return_params = {"desde": "semana"}
    href = PromotionState._profile_href(context, paso="5")
    assert href.startswith("/promotions/perfil?paso=5&volver=")
    from urllib.parse import parse_qs, urlsplit

    back = parse_qs(urlsplit(href).query)["volver"][0]
    assert safe_return(back) == back and back.endswith("paso=4")


def test_budget_step_renders_the_suggestion() -> None:
    page = repr(_budget().render())
    assert "Sugerencia" in page and "Responder 5 preguntas (1 minuto)" in page
    assert "Revisar mi tope" in page
