"""m-24852539: Claude cache pricing is the same everywhere — Sonnet 5.5 cache reads at
the official $0.10/MTok, `ContentService._call_cost` billing cache tokens through
`claude_tools.cost_breakdown`, and summed angle runs keeping their cache writes."""

from __future__ import annotations

from decimal import Decimal

import pytest
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import Usage

from qualify_api.claude_tools import CACHE_READ_PRICES, CallStats, cost_breakdown
from qualify_api.creative.angle_sets import _sum_stats
from qualify_api.creative.service import ContentService

PRICING = JsonPricingTable("v7")

#: "Cache hits and refreshes", https://platform.claude.com/docs/en/about-claude/pricing
#: (read 2026-10-25).
OFFICIAL_CACHE_READ = {
    "claude-haiku-5-5": 0.01,
    "claude-haiku-4-5": 0.10,
    "claude-sonnet-5-5": 0.10,
    "claude-sonnet-5": 0.20,
    "claude-opus-5-5": 0.20,
    "claude-opus-5": 0.50,
}


def _service() -> ContentService:
    service = ContentService.__new__(ContentService)
    service._pricing = PRICING
    return service


def test_cache_read_prices_match_the_official_table() -> None:
    assert CACHE_READ_PRICES == OFFICIAL_CACHE_READ


def test_sonnet_5_5_reads_the_cache_at_ten_cents() -> None:
    stats = CallStats("claude-sonnet-5-5", None, 0, 0, cache_read_tokens=1_000_000)
    assert stats.cost_usd == pytest.approx(0.10)
    breakdown = cost_breakdown(
        "claude-sonnet-5-5", input_tokens=1000, output_tokens=0, cache_read_tokens=4000
    )
    assert breakdown["cache_read"] == pytest.approx(0.0004)
    assert breakdown["input"] == pytest.approx(0.002)


@pytest.mark.parametrize("model_id", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5"])
def test_call_cost_agrees_with_cost_breakdown_on_a_cached_call(model_id: str) -> None:
    usage = Usage(
        input_tokens=1000, output_tokens=200, cache_read_tokens=4000, cache_creation_tokens=2000
    )
    expected = sum(
        cost_breakdown(
            model_id,
            input_tokens=1000,
            output_tokens=200,
            cache_read_tokens=4000,
            cache_creation_tokens=2000,
        ).values()
    )
    got = _service()._call_cost(usage, model_id)
    assert isinstance(got, Decimal)
    assert float(got) == pytest.approx(expected)
    # and no longer the old full-input-rate figure for the cached part
    per_in = PRICING.unit_price(model_id=model_id, unit="per_mtok_in")
    per_out = PRICING.unit_price(model_id=model_id, unit="per_mtok_out")
    full_rate = (Decimal(7000) * per_in + Decimal(200) * per_out) / Decimal(1_000_000)
    assert got < full_rate


def test_a_model_claude_tools_does_not_price_keeps_the_conservative_table() -> None:
    # claude-opus-4-8 is in the table (a fallback model) but not in claude_tools.PRICES
    usage = Usage(input_tokens=1000, output_tokens=0, cache_read_tokens=1000)
    assert cost_breakdown("claude-opus-4-8", input_tokens=1000, output_tokens=0) == {}
    per_in = PRICING.unit_price(model_id="claude-opus-4-8", unit="per_mtok_in")
    assert _service()._call_cost(usage, "claude-opus-4-8") == (
        Decimal(2000) * per_in / Decimal(1_000_000)
    )


def test_summing_angle_runs_keeps_cache_writes() -> None:
    a = CallStats("claude-opus-5-5", "r1", 100, 10, 50, 1, 1, cache_creation_tokens=300)
    b = CallStats("claude-opus-5-5", "r2", 200, 20, 60, 2, 1, cache_creation_tokens=400)
    total = _sum_stats(a, b)
    assert total.cache_creation_tokens == 700
    assert total.cache_read_tokens == 110
    assert (total.input_tokens, total.output_tokens, total.turns, total.tool_calls) == (
        300,
        30,
        3,
        2,
    )
    assert total.model_revision == "r2"
    assert total.cost_usd == pytest.approx(a.cost_usd + b.cost_usd)
