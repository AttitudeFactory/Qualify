from __future__ import annotations

import pytest

from qualify_models.eval.fase0_cost import (
    AccountEconomics,
    caption_generation_usd,
    estimate_account,
    token_cost_usd,
    video_analysis_usd,
)


def test_token_cost_matches_hand_calculation() -> None:
    # haiku 4.5 = $1/MTok in, $5/MTok out
    assert token_cost_usd("claude-haiku-4-5", 1_000_000, 0) == pytest.approx(1.0)
    assert token_cost_usd("claude-haiku-4-5", 0, 1_000_000) == pytest.approx(5.0)


def test_unknown_model_raises() -> None:
    with pytest.raises(KeyError):
        token_cost_usd("gpt-not-a-model", 100, 100)


def test_video_analysis_dominates_caption_generation() -> None:
    """The load-bearing ratio: analyzing a video costs ~6x generating a caption.

    If this inverts, the Fase 0 cost argument in NOTES_fase0_agentive_layer.md
    no longer holds and the recommendation needs revisiting.
    """
    model = "claude-haiku-4-5"
    assert video_analysis_usd(model) > 5 * caption_generation_usd(model)


def test_frames_scale_video_cost() -> None:
    model = "claude-haiku-4-5"
    assert video_analysis_usd(model, frames=8) > video_analysis_usd(model, frames=4)


def test_zero_frames_rejected() -> None:
    with pytest.raises(ValueError):
        video_analysis_usd("claude-haiku-4-5", frames=0)


def test_unpriced_stages_yield_no_total() -> None:
    """Undocumented rates must produce None, never a silently-partial total."""
    est = estimate_account()
    assert est.total_ai_usd_per_month is None
    assert est.ai_share_of_revenue is None
    assert est.margin_safe is None
    assert any("ASR" in c for c in est.caveats)
    assert any("Comment-triage" in c for c in est.caveats)


def test_fully_priced_profile_totals() -> None:
    est = estimate_account(
        model_id="claude-haiku-4-5",
        revenue_usd_per_month=6.0,
        posts_per_month=20,
        own_videos_analyzed_per_month=20,
        asr_usd_per_video=0.0,
        comment_triage_usd_per_month=0.0,
    )
    assert isinstance(est, AccountEconomics)
    assert est.total_ai_usd_per_month is not None
    assert est.ai_share_of_revenue is not None
    assert est.margin_safe is True


def test_cheapest_tier_breaks_under_frontier_model() -> None:
    """The central Fase 0 finding, pinned as a regression test.

    At the $1/account tier, analyzing 20 videos/month on Opus 4.8 consumes most
    of the account's revenue, while the same workload on Haiku 4.5 does not.
    """
    common = dict(
        revenue_usd_per_month=1.0,
        posts_per_month=20,
        own_videos_analyzed_per_month=20,
        asr_usd_per_video=0.0,
        comment_triage_usd_per_month=0.0,
    )
    opus = estimate_account(model_id="claude-opus-4-8", **common)
    haiku = estimate_account(model_id="claude-haiku-4-5", **common)

    assert opus.ai_share_of_revenue is not None and opus.ai_share_of_revenue > 0.80
    assert opus.margin_safe is False
    assert haiku.ai_share_of_revenue is not None and haiku.ai_share_of_revenue < 0.30
