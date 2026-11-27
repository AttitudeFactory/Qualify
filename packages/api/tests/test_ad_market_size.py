"""Market size (m-25091388): pure estimate over Meta's audience range + the versioned table."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from qualify_api.ads.audience import ReachEstimate
from qualify_api.ads.market_size import (
    LOGIN_NEEDED,
    Cpm,
    MarketEstimateUnavailable,
    estimate,
    estimate_market,
    load_table,
    market_class,
)

TABLE = load_table()
COP = Cpm(800_000, "COP", "table")  # $8.000 per 1.000 impressions


def _people(lower: int | None, upper: int | None, budget: int | None, days: int = 7, **kw):
    return estimate(
        lower=lower,
        upper=upper,
        budget_minor=budget,
        days=days,
        currency="COP",
        cpm=kw.get("cpm", COP),
        table=TABLE,
    )


def test_table_is_versioned_provisional_and_covers_the_three_countries() -> None:
    assert TABLE.version == "mercado-v1"
    assert TABLE.cpm == {"CO": ("COP", 800_000), "VE": ("USD", 150), "UY": ("UYU", 8000)}
    raw = (Path(__file__).parents[1] / "src/qualify_api/ads/data/mercado-v1.json").read_text(
        encoding="utf-8"
    )
    assert raw.count("hipótesis") >= 4 and "PROVISIONAL" in raw


def test_market_class_thresholds() -> None:
    assert [market_class(n, TABLE) for n in (49_999, 50_000, 500_000, 500_001)] == [
        "pequeno",
        "mediano",
        "mediano",
        "grande",
    ]


def test_small_audience_saturates_at_metas_upper_bound() -> None:
    result = _people(18_000, 21_000, 20_000_000)  # $200.000 → 25.000 impressions / 1.5
    assert result is not None
    assert result.people == 16_666 and result.saturated and result.market_class == "pequeno"
    capped = _people(18_000, 21_000, 100_000_000)
    assert capped is not None and capped.people == 21_000  # never above Meta's upper bound


def test_big_audience_scales_with_budget_and_is_not_saturated() -> None:
    small, big = _people(2_000_000, 2_400_000, 2_500_000), _people(2_000_000, 2_400_000, 5_000_000)
    assert small is not None and big is not None
    assert (small.people, big.people) == (2_083, 4_166)
    assert not big.saturated and big.market_class == "grande"
    assert (big.cpm_source, big.table_version) == ("table", "mercado-v1")


def test_frequency_grows_with_days_but_never_below_one() -> None:
    one_day, four_weeks = _people(10**6, 10**6, 2_500_000, 1), _people(10**6, 10**6, 2_500_000, 28)
    assert one_day is not None and four_weeks is not None
    assert (one_day.people, four_weeks.people) == (3_125, 520)


@pytest.mark.parametrize("bounds", [(None, None), (None, 5), (10, 5), (-1, -1)])
def test_missing_audience_range_gives_no_estimate(bounds) -> None:
    assert _people(*bounds, 2_500_000) is None


def test_no_budget_or_no_cpm_keeps_the_class_but_no_people() -> None:
    for result in (_people(1, 30_000, None), _people(1, 30_000, 2_500_000, cpm=None)):
        assert result is not None
        assert (result.people, result.saturated, result.cpm_source) == (None, False, None)
        assert result.market_class == "pequeno"


def test_currency_mismatch_is_refused() -> None:
    with pytest.raises(ValueError, match="currency"):
        _people(1, 30_000, 2_500_000, cpm=Cpm(150, "USD", "table"))


def test_service_needs_a_login() -> None:
    with pytest.raises(MarketEstimateUnavailable, match=LOGIN_NEEDED):
        estimate_market(
            tenant_id=uuid4(),
            brand_id=uuid4(),
            reach=ReachEstimate(),
            country="CO",
            currency="COP",
        )


def test_no_code_reads_the_retired_delivery_estimate_curve() -> None:
    """Meta retired these fields (discovery §1): nothing may depend on them."""
    root = Path(__file__).parents[3]
    retired = re.compile(r"daily_outcomes_curve|estimate_dau|budget_guardrail")
    sources = [
        *(root / "packages").glob("*/src/**/*.py"),
        *(p for p in (root / "Qualify").glob("*.py") if not p.name.startswith("test_")),
    ]
    assert len(sources) > 100
    offenders = [str(p) for p in sources if retired.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
