"""m-25129406: the paid measurement of «Sigue a la anterior» after the owner's own video is
prepared, never run — its quote is the price guard's own and its guards refuse to spend
without Deivid's written OK. Offline: nothing is sent."""

from __future__ import annotations

from decimal import Decimal

import pytest
from qualify_creative.pricing import JsonPricingTable

from qualify_api.creative.part_extend import EXTEND_OWN_SOURCE_MAX_S
from qualify_api.evals import extend_own_video_bench as bench


def test_the_quote_is_the_price_guards_and_fits_the_proposed_ceiling() -> None:
    pricing = JsonPricingTable(bench.PRICING_VERSION)
    items = bench.plan_items(bench.CASES, pricing, {})
    assert [i.label for i in items] == list(bench.CASE_IDS)
    # every case quoted at the most that is ever sent (10 s of the owner's video)
    assert len({i.quote_usd for i in items}) == 1 and items[0].quote_usd > 0
    need = sum((i.reserved_usd for i in items), Decimal(0))
    assert need <= bench.PROPOSED_MAX_USD <= bench.HARD_CEILING_USD
    assert (
        bench.fits_ceiling(items, max_usd=bench.PROPOSED_MAX_USD, spent_before=Decimal(0)) is None
    )


def test_a_shorter_tail_costs_less() -> None:
    pricing = JsonPricingTable(bench.PRICING_VERSION)
    case = bench.CASES[0]
    assert bench.case_quote(case, pricing, 5.0) < bench.case_quote(case, pricing, 10.0)


def test_the_tail_is_whole_seconds_and_at_most_ten() -> None:
    assert bench.tail_seconds(3.2) == 4.0
    assert bench.tail_seconds(25.0) == EXTEND_OWN_SOURCE_MAX_S


def test_the_request_is_an_extend_as_the_producer_sends_it() -> None:
    params = bench.extend_params(
        bench.CASES[1], video_url="https://x.invalid/a.mp4", input_seconds=6
    )
    assert params["omni_reference_task_type"] == "extend" and params["ratio"] == "adaptive"
    assert params["draft"] is True and params["duration_seconds"] == bench.PART_SECONDS
    assert params["reference_videos"] == ["https://x.invalid/a.mp4"]


def test_nothing_is_spent_without_the_written_ok() -> None:
    assert bench.mode_refusal(paid=False, dry_run=False) is not None
    assert bench.mode_refusal(paid=True, dry_run=True) is not None
    with pytest.raises(bench.SpendRefused):
        bench.validate_max_usd("50")
