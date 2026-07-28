"""Tests for the OAuth/CRM-path cost model (task D4).

Pure arithmetic and matrix wiring — no weights, no network.
"""

from __future__ import annotations

import pytest

from qualify_models.eval.fase0_cost import (
    CrmAccountEconomics,
    comment_sentiment_applies,
    estimate_crm_account,
    video_analysis_usd,
)

# A fully-specified profile. Every value here is a MODELLING ASSUMPTION chosen
# to exercise the arithmetic, not a measurement of anything.
FULLY_PRICED = dict(
    comments_per_month=500,
    mentions_per_month=200,
    mention_gate_pass_rate=0.2,
    sentiment_usd_per_comment=0.0,
    gate_usd_per_mention=0.0,
    asr_usd_per_mention=0.0,
)


def test_matrix_wiring_holds() -> None:
    """The cost model's premise is read from oauth_scope, not restated."""
    assert comment_sentiment_applies() is True


def test_defaults_yield_no_total() -> None:
    """Nothing is measured, so nothing is totalled."""
    est = estimate_crm_account()
    assert isinstance(est, CrmAccountEconomics)
    assert est.total_ai_usd_per_month is None
    assert est.ai_share_of_revenue is None
    assert est.margin_safe is None


def test_unmeasured_volumes_are_named_as_caveats() -> None:
    est = estimate_crm_account()
    joined = " ".join(est.caveats)
    assert "comments_per_month is unmeasured" in joined
    assert "mentions_per_month is unmeasured" in joined
    assert "mention_gate_pass_rate is uncalibrated" in joined
    assert "asr_usd_per_mention is undocumented" in joined


def test_day_one_increment_needs_only_comment_inputs() -> None:
    """Comments only: no VLM, no ASR, no gate — the increment that runs today."""
    est = estimate_crm_account(
        analyze_mentions=False,
        comments_per_month=500,
        sentiment_usd_per_comment=0.0,
    )
    assert [op.operation for op in est.operations] == ["comment_sentiment"]
    assert est.total_ai_usd_per_month == pytest.approx(0.0)
    assert est.margin_safe is True
    assert any("Day-one increment" in c for c in est.caveats)


def test_day_one_increment_still_blocks_on_unmeasured_volume() -> None:
    """Self-hosting makes the rate zero; it does not make the volume known."""
    est = estimate_crm_account(analyze_mentions=False, sentiment_usd_per_comment=0.0)
    assert est.total_ai_usd_per_month is None


def test_mention_enrichment_adds_three_operations() -> None:
    est = estimate_crm_account(**FULLY_PRICED)
    assert [op.operation for op in est.operations] == [
        "comment_sentiment",
        "enrichment_gate",
        "mention_vision",
        "mention_transcription",
    ]


def test_gate_pass_rate_scales_vlm_spend_linearly() -> None:
    """The gate's whole purpose, pinned: pass-rate multiplies downstream cost."""
    cheap = estimate_crm_account(**{**FULLY_PRICED, "mention_gate_pass_rate": 0.1})
    dear = estimate_crm_account(**{**FULLY_PRICED, "mention_gate_pass_rate": 0.5})

    assert cheap.total_ai_usd_per_month is not None
    assert dear.total_ai_usd_per_month is not None
    assert dear.total_ai_usd_per_month == pytest.approx(5 * cheap.total_ai_usd_per_month)
    assert cheap.mentions_enriched_per_month == pytest.approx(20.0)
    assert dear.mentions_enriched_per_month == pytest.approx(100.0)


def test_vlm_cost_matches_the_unit_helper() -> None:
    est = estimate_crm_account(**FULLY_PRICED)
    vision = next(op for op in est.operations if op.operation == "mention_vision")
    expected = 200 * 0.2 * video_analysis_usd("claude-haiku-4-5", frames=4)
    assert vision.usd_total == pytest.approx(expected)


def test_ungated_mentions_can_exceed_revenue_on_a_single_account() -> None:
    """The structural risk of the earned-media increment.

    Mention volume is set by third parties, so it can grow without limit while
    revenue stays fixed at one account's subscription. With no gate (pass-rate
    1.0) and a busy brand, VLM spend alone goes underwater.
    """
    est = estimate_crm_account(
        **{**FULLY_PRICED, "mentions_per_month": 1000, "mention_gate_pass_rate": 1.0},
        revenue_usd_per_month=6.0,
    )
    assert est.ai_share_of_revenue is not None
    assert est.ai_share_of_revenue > 1.0
    assert est.margin_safe is False


def test_a_working_gate_rescues_the_same_workload() -> None:
    """Same volume, 10% gate — the economic argument for building the gate."""
    est = estimate_crm_account(
        **{**FULLY_PRICED, "mentions_per_month": 1000, "mention_gate_pass_rate": 0.1},
        revenue_usd_per_month=6.0,
    )
    assert est.ai_share_of_revenue is not None
    assert est.ai_share_of_revenue < 0.20
    assert est.margin_safe is True


def test_frontier_model_moves_the_verdict() -> None:
    """Model choice alone can flip margin_safe at identical volume.

    100 enriched mentions/month on a $6 account: Haiku 4.5 sits inside the 20%
    tripwire, Opus 4.8 does not. Written first with a 0.25 pass-rate, which
    failed — Haiku breaches 20% there too. That failure is the finding pinned
    in test_mention_budget_is_small_even_on_the_cheapest_model below.
    """
    common = {**FULLY_PRICED, "mentions_per_month": 1000, "mention_gate_pass_rate": 0.1}
    haiku = estimate_crm_account(model_id="claude-haiku-4-5", **common)
    opus = estimate_crm_account(model_id="claude-opus-4-8", **common)

    assert haiku.ai_share_of_revenue is not None and opus.ai_share_of_revenue is not None
    assert opus.ai_share_of_revenue > haiku.ai_share_of_revenue
    assert haiku.margin_safe is True
    assert opus.margin_safe is False


@pytest.mark.parametrize(
    ("model_id", "max_enriched_mentions"),
    [
        ("claude-haiku-4-5", 135),
        ("claude-sonnet-5", 45),
        ("claude-opus-4-8", 27),
    ],
)
def test_mention_budget_is_small_even_on_the_cheapest_model(
    model_id: str, max_enriched_mentions: int
) -> None:
    """How many mentions a $6 account can afford to enrich before the tripwire.

    The headline number for the earned-media increment, and it is small: even
    on Haiku 4.5 a $6/month account affords only ~135 enriched mentions before
    AI spend passes 20% of revenue. Any brand with real mention volume needs
    either a hard per-tenant quota, metered pricing, or an aggressive gate —
    the same "billing unit and cost driver come apart" problem
    NOTES_fase0_agentive_layer.md §3.3 found for competitor analysis.

    Bounds are checked either side of the threshold rather than pinned exactly,
    so this survives a token-shape revision without becoming a brittle assert.
    """
    inside = estimate_crm_account(
        model_id=model_id,
        revenue_usd_per_month=6.0,
        mentions_per_month=max_enriched_mentions - 5,
        mention_gate_pass_rate=1.0,
        comments_per_month=0,
        sentiment_usd_per_comment=0.0,
        gate_usd_per_mention=0.0,
        asr_usd_per_mention=0.0,
    )
    outside = estimate_crm_account(
        model_id=model_id,
        revenue_usd_per_month=6.0,
        mentions_per_month=max_enriched_mentions + 5,
        mention_gate_pass_rate=1.0,
        comments_per_month=0,
        sentiment_usd_per_comment=0.0,
        gate_usd_per_mention=0.0,
        asr_usd_per_mention=0.0,
    )
    assert inside.margin_safe is True
    assert outside.margin_safe is False


def test_one_missing_rate_nulls_the_whole_total() -> None:
    """No silently-partial totals — the discipline inherited from cost.py."""
    est = estimate_crm_account(**{**FULLY_PRICED, "asr_usd_per_mention": None})
    assert est.total_ai_usd_per_month is None
    assert est.ai_share_of_revenue is None


def test_competitor_content_is_absent_by_construction() -> None:
    """No OAuth-path cost can be attributed to unreachable surfaces."""
    est = estimate_crm_account(**FULLY_PRICED)
    assert any("UNREACHABLE" in c for c in est.caveats)
    assert not any("competitor" in op.operation for op in est.operations)


def test_gate_note_flags_that_no_gate_exists_yet() -> None:
    """The model prices a component that has not been built (task #13)."""
    est = estimate_crm_account(**FULLY_PRICED)
    gate = next(op for op in est.operations if op.operation == "enrichment_gate")
    assert gate.note is not None
    assert "#13" in gate.note


def test_invalid_pass_rate_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_crm_account(mention_gate_pass_rate=1.5)
    with pytest.raises(ValueError):
        estimate_crm_account(mention_gate_pass_rate=-0.1)


def test_zero_frames_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_crm_account(frames_per_mention=0)
