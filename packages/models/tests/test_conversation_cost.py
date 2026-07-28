from __future__ import annotations

import pytest

from qualify_models.eval.conversation_cost import (
    MANYCHAT_PLANS,
    ConversationEconomics,
    breakeven_generation_rate,
    estimate_conversation,
    grounded_reply_usd,
    intent_classification_usd,
)


def test_grounded_reply_matches_hand_calculation() -> None:
    # haiku 4.5 = $1/MTok in, $5/MTok out.
    # in = 300 system + 400 history + 3*300 chunks = 1600; out = 120.
    expected = 1600 * 1.0 / 1e6 + 120 * 5.0 / 1e6
    assert grounded_reply_usd("claude-haiku-4-5") == pytest.approx(expected)


def test_chunks_scale_reply_cost() -> None:
    model = "claude-haiku-4-5"
    assert grounded_reply_usd(model, knowledge_chunks=6) > grounded_reply_usd(
        model, knowledge_chunks=3
    )


def test_negative_chunks_rejected() -> None:
    with pytest.raises(ValueError):
        grounded_reply_usd("claude-haiku-4-5", knowledge_chunks=-1)


def test_unknown_plan_raises() -> None:
    with pytest.raises(KeyError):
        estimate_conversation(plan_key="enterprise")


def test_revenue_per_contact_falls_as_plan_price_rises() -> None:
    """The counterintuitive shape of per-contact pricing, pinned.

    Included contacts grow faster than plan price, so the *bigger* plans leave
    *less* AI budget per conversation. Any activation feature that is affordable
    on the entry tier can be underwater on the top tier.
    """
    per_contact = [
        MANYCHAT_PLANS[key].revenue_per_included_contact
        for key in ("essential", "pro", "business", "advanced")
    ]
    assert per_contact == sorted(per_contact, reverse=True)
    assert per_contact[0] > 10 * per_contact[-1]


def test_unpriced_stages_yield_no_total() -> None:
    """Undocumented rates must produce None, never a silently-partial total."""
    est = estimate_conversation()
    assert isinstance(est, ConversationEconomics)
    assert est.total_ai_usd_per_conversation is None
    assert est.total_share_of_contact_revenue is None
    assert any("Intent-classification" in c for c in est.caveats)
    assert any("Retrieval" in c for c in est.caveats)


def test_generation_lower_bound_is_always_available() -> None:
    """Generation is priced from list rates, so the lower bound survives the Nones."""
    est = estimate_conversation()
    assert est.generation_usd_per_conversation > 0
    assert est.generation_share_of_contact_revenue is not None


def test_self_hosted_stages_close_the_total() -> None:
    est = estimate_conversation(intent_usd_per_label_call=0.0, retrieval_usd_per_query=0.0)
    assert est.total_ai_usd_per_conversation == pytest.approx(est.generation_usd_per_conversation)
    assert est.total_share_of_contact_revenue is not None


def test_top_tier_underwater_on_generation_alone() -> None:
    """The central D4 finding, pinned as a regression test.

    At the published Advanced tier ($139 / 25000 contacts = $0.00556 per contact),
    a three-turn grounded conversation on the CHEAPEST frontier model already
    costs more than the contact earns — before classification, retrieval, infra,
    or margin. Per-contact pricing cannot fund unconditional generation.
    """
    advanced = estimate_conversation(model_id="claude-haiku-4-5", plan_key="advanced")
    share = advanced.generation_share_of_contact_revenue
    assert share is not None and share > 1.0

    # ... while the entry tier, with 10x the revenue per contact, is comfortable.
    essential = estimate_conversation(model_id="claude-haiku-4-5", plan_key="essential")
    essential_share = essential.generation_share_of_contact_revenue
    assert essential_share is not None and essential_share < 0.20


def test_cascade_gate_is_what_makes_the_price_point_exist() -> None:
    """The cost argument for a cheap classifier in front of the LLM.

    Under the 20% AI-spend tripwire, only a minority of contacts can reach the
    generative stage on the higher tiers. That is the routing cascade the
    incumbent documents, expressed in dollars.
    """
    advanced = breakeven_generation_rate(plan_key="advanced", model_id="claude-haiku-4-5")
    pro = breakeven_generation_rate(plan_key="pro", model_id="claude-haiku-4-5")
    essential = breakeven_generation_rate(plan_key="essential", model_id="claude-haiku-4-5")

    assert advanced < 0.25
    assert advanced < pro < essential
    assert essential == pytest.approx(1.0)


def test_frontier_model_tightens_the_gate() -> None:
    haiku = breakeven_generation_rate(plan_key="pro", model_id="claude-haiku-4-5")
    opus = breakeven_generation_rate(plan_key="pro", model_id="claude-opus-4-8")
    assert opus < haiku


def test_intent_cost_is_linear_in_labels() -> None:
    assert intent_classification_usd(0.0001, labels=8, messages=3) == pytest.approx(0.0024)
    assert intent_classification_usd(None, labels=8, messages=3) is None


def test_intent_cost_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        intent_classification_usd(0.0001, labels=-1, messages=3)
