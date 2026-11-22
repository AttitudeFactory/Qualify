"""m-25091388: market size on the audience step and people reached on the budget step."""

from __future__ import annotations

import re
from dataclasses import replace
from uuid import uuid4

import pytest
from qualify_api.ads.audience import ReachEstimate
from qualify_api.ads.market_size import MarketEstimate, estimate, load_table

from . import promotion_audience_provider as provider
from . import promotion_state as state_module
from .promotion_audience_vm import AudienceReachVM, approx_people, reach_label
from .promotion_market_vm import NO_RANGE, market_estimate, market_view
from .promotion_page import _budget, _review
from .promotion_state import PromotionState
from .test_promotion_audience import AudienceContext
from .test_promotion_wizard import TENANT, ZONE, review, valid_form

READY = AudienceReachVM(
    available=True,
    status="ready",
    lower=18_000,
    upper=21_000,
    audience_hash="h1",
    market_class="pequeno",
    cpm_minor=800_000,
    cpm_source="table",
)


@pytest.mark.parametrize(
    ("lower", "upper", "label"),
    [
        (120_000, 140_000, "Entre 120.000 y 140.000 personas en este público"),
        (900_000, 1_100_000, "Entre 900.000 y 1,1 millones de personas en este público"),
        (25_000_000, 30_000_000, "Entre 25 y 30 millones de personas en este público"),
        (200, 900, "Menos de 1.000 personas en este público"),
    ],
)
def test_meta_range_reads_as_people(lower: int, upper: int, label: str) -> None:
    assert reach_label(lower, upper) == label


@pytest.mark.parametrize(
    ("value", "words"),
    [
        (0, "menos de 100 personas"),
        (850, "unas 800 personas"),
        (9_432, "unas 9.400 personas"),
        (231_000, "unas 230.000 personas"),
        (1_234_567, "unas 1,2 millones de personas"),
    ],
)
def test_our_number_is_rounded_and_never_zero(value: int, words: str) -> None:
    assert approx_people(value) == words


def test_budget_line_with_days_note_and_review() -> None:
    view = market_view(READY, valid_form(), ZONE)
    assert view.line.startswith("Con $25.000 COP en 7 días llegarías a unas ")
    assert view.line.endswith("de tu público (aproximado).")
    assert "Colombia" in view.note and not view.saturated
    assert view.review.endswith("de un público de 18.000 a 21.000 personas")


def test_big_amount_is_capped_at_meta_upper_bound_and_warns_without_pushing() -> None:
    view = market_view(READY, replace(valid_form(), budget="9000000"), ZONE)
    assert "casi todas las personas de tu público (unas 21.000 personas)" in view.line
    assert view.saturated
    found = market_estimate(READY, replace(valid_form(), budget="9000000"), ZONE)
    assert found is not None and found.people == 21_000


@pytest.mark.parametrize(
    "reach",
    [
        AudienceReachVM(status="unavailable"),
        AudienceReachVM(status="failed"),
        AudienceReachVM(),
        replace(READY, market_failed=True),
    ],
)
def test_no_range_never_shows_a_number(reach: AudienceReachVM) -> None:
    view = market_view(reach, valid_form(), ZONE)
    assert not re.search(r"\d", view.line) and not view.saturated
    assert market_estimate(reach, valid_form(), ZONE) is None


def test_meta_without_range_lets_the_owner_go_on() -> None:
    assert (
        "Puedes seguir"
        in market_view(AudienceReachVM(status="unavailable"), valid_form(), ZONE).line
    )
    assert market_view(AudienceReachVM(status="unavailable"), valid_form(), ZONE).line == NO_RANGE


def test_no_cost_data_for_the_country_says_so_in_words() -> None:
    view = market_view(
        replace(READY, cpm_minor=0), replace(valid_form(), location_country="UY"), ZONE
    )
    assert "Uruguay" in view.line and not re.search(r"\d", view.line)
    found = market_estimate(replace(READY, cpm_minor=0), valid_form(), ZONE)
    assert found is not None and found.people is None and found.market_class == "pequeno"


def test_missing_amount_or_dates_asks_for_them() -> None:
    assert "Escribe el monto" in market_view(READY, replace(valid_form(), budget=""), ZONE).line
    late = replace(valid_form(), end_local="2027-01-01T09:00")
    assert "Revisa las fechas" in market_view(READY, late, ZONE).line
    assert market_estimate(READY, late, ZONE).people is None


def test_read_reach_keeps_bounds_and_class_without_a_second_meta_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def meta(**kwargs: object) -> ReachEstimate:
        calls.append({})
        return ReachEstimate(True, 18_000, 21_000, "", "h1")

    def market(**kwargs: object) -> MarketEstimate:
        assert kwargs["reach"].upper == 21_000 and kwargs["country"] == "CO"
        return MarketEstimate(18_000, 21_000, "pequeno", 0, False, "COP", 800_000, "own", "v")

    monkeypatch.setattr(provider, "estimate_audience", meta)
    monkeypatch.setattr(provider, "estimate_market", market)
    form = replace(
        valid_form(), enhancements=replace(valid_form().enhancements, brand_id=str(uuid4()))
    )
    reach = provider.read_reach({"tenant_id": TENANT}, form)
    assert len(calls) == 1
    assert (reach.lower, reach.upper, reach.cpm_minor, reach.cpm_source) == (
        18_000,
        21_000,
        800_000,
        "own",
    )
    assert reach.size_label == "Público pequeño" and "distancia" in reach.size_hint


def test_read_reach_without_meta_range_has_no_size(monkeypatch: pytest.MonkeyPatch) -> None:
    async def meta(**kwargs: object) -> ReachEstimate:
        return ReachEstimate()

    monkeypatch.setattr(provider, "estimate_audience", meta)
    reach = provider.read_reach({}, valid_form())
    assert reach.status == "unavailable" and not reach.size_label and "Puedes seguir" in reach.label


def test_market_failure_keeps_meta_range(monkeypatch: pytest.MonkeyPatch) -> None:
    async def meta(**kwargs: object) -> ReachEstimate:
        return ReachEstimate(True, 18_000, 21_000, "", "h1")

    monkeypatch.setattr(provider, "estimate_audience", meta)
    reach = provider.read_reach({"tenant_id": TENANT}, valid_form())  # no brand id
    assert reach.available and reach.market_failed and not reach.size_label
    assert market_view(reach, valid_form(), ZONE).retry


def test_keeping_the_estimate_never_blocks_the_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kwargs: object) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(provider, "record_market_estimate", boom)
    found = estimate(
        lower=1, upper=2, budget_minor=None, days=None, currency="COP", cpm=None, table=load_table()
    )
    provider.keep_market_estimate(TENANT, uuid4(), found)  # logged, not raised
    provider.keep_market_estimate(TENANT, uuid4(), None)


def test_widen_audience_goes_back_to_the_audience_step_keeping_the_amount() -> None:
    context = AudienceContext()
    context.step, context.reviewed = 4, False
    event = PromotionState.widen_audience.fn(context)
    assert event is not None and context.step == 3 and context.direction == "back"
    assert context.form.budget == "25000"


def test_unpublished_pieces_have_no_market_block() -> None:
    assert "audience" not in state_module.step_keys(replace(valid_form(), media_kind="images"))
    assert "audience" in state_module.step_keys(valid_form())


def test_budget_and_review_render_the_market_rows() -> None:
    budget, review_page = repr(_budget().render()), repr(_review().render())
    assert "personas llegar" in budget and "Ampliar mi p" in budget
    assert "Volver a calcular" in budget
    assert "personas llegar" in review_page


@pytest.mark.asyncio
async def test_prepared_promotion_keeps_the_estimate_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = AudienceContext()
    context.audience_reach = READY
    kept: list[tuple] = []
    monkeypatch.setattr(state_module, "prepare_preview", lambda *args: review())
    monkeypatch.setattr(state_module, "keep_market_estimate", lambda *args: kept.append(args))
    await context._remote(confirm=False)
    assert len(kept) == 1
    tenant, promotion, found = kept[0]
    assert tenant == TENANT and str(promotion) == review().promotion_id
    assert found.market_class == "pequeno" and found.audience_hash == "h1"
    assert found.people is not None and found.people <= 21_000
