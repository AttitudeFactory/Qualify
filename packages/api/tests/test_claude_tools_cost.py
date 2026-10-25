"""m-24852516: one pricing for a run's `CallStats.cost_usd` and each turn's Langfuse
cost — cache reads and cache writes included, each at its model's rate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qualify_api.claude_tools import (
    CACHE_READ_PRICES,
    CACHE_WRITE_MULTIPLIER,
    PRICES,
    CallStats,
    Meter,
    ModelConfig,
    _usage_and_cost,
    cost_breakdown,
)


def _response(model_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        model=f"{model_id}-20261001",
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=4000,
            cache_creation_input_tokens=2000,
        ),
    )


def test_every_priced_model_has_a_cache_read_price() -> None:
    assert set(CACHE_READ_PRICES) == set(PRICES)
    for model_id, (price_in, _) in PRICES.items():
        assert 0 < CACHE_READ_PRICES[model_id] < price_in
    assert CACHE_WRITE_MULTIPLIER == 1.25  # the 5-minute TTL, the only one sent


@pytest.mark.parametrize("model_id", sorted(PRICES))
def test_a_cached_call_costs_the_same_in_the_stats_and_in_the_trace(model_id: str) -> None:
    response = _response(model_id)
    meter = Meter(ModelConfig(model_id))
    meter.add(response)
    stats = meter.stats()
    assert stats.cache_read_tokens == 4000 and stats.cache_creation_tokens == 2000

    _, cost = _usage_and_cost(response, model_id)
    assert stats.cost_usd == pytest.approx(sum(cost.values()))
    # and the cache is really in it: more than the uncached input + output alone
    price_in, price_out = PRICES[model_id]
    assert stats.cost_usd > (1000 * price_in + 200 * price_out) / 1_000_000


def test_sonnet_5_rates_per_kind() -> None:
    assert cost_breakdown(
        "claude-sonnet-5",
        input_tokens=1000,
        output_tokens=200,
        cache_read_tokens=4000,
        cache_creation_tokens=2000,
    ) == pytest.approx(
        {"input": 0.002, "cache_read": 0.0008, "cache_creation": 0.005, "output": 0.002}
    )


def test_opus_5_5_reads_the_cache_at_its_own_rate() -> None:
    # $0.20 / MTok: 0.05x its $4 input, not the 0.1x of most models
    stats = CallStats("claude-opus-5-5", None, 0, 0, cache_read_tokens=1_000_000)
    assert stats.cost_usd == pytest.approx(0.20)


def test_an_unpriced_model_costs_nothing_rather_than_a_guess() -> None:
    assert cost_breakdown("claude-unknown", input_tokens=10, output_tokens=10) == {}
    assert CallStats("claude-unknown", None, 10, 10).cost_usd == 0.0
    assert _usage_and_cost(_response("claude-unknown"), "claude-unknown")[1] == {}


def test_positional_stats_keep_their_meaning() -> None:
    # callers build CallStats positionally (model, revision, in, out, cache read, turns,
    # tool calls): the new field is last and defaults to no cache writes
    stats = CallStats("claude-sonnet-5", None, 1000, 0, 0, 1, 1)
    assert stats.cache_creation_tokens == 0 and stats.turns == 1
    assert stats.cost_usd == pytest.approx(0.002)
