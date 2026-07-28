"""Parametric unit economics for an intent + reply activation stage, per conversation.

Third sibling of `cost.py` ($/video, Fase 1 cascade) and `fase0_cost.py`
($/connected-account/month, Fase 0 publishing API). The unit changes again
because the *billing* unit changes: a chat-activation product is priced per
**contact** — one person per month, regardless of message count — which is how
ManyChat, the incumbent this models against, actually charges (verified
2026-07-23, https://manychat.com/pricing).

That reframing is the point. A per-message or per-token cost says nothing about
whether the product can exist; the question is whether the AI spend triggered by
one contact fits inside the revenue that contact generates. At the published
prices below, the answer is frequently **no** for unconditional generation —
which is why the incumbent runs a routing cascade (deterministic automations →
cheap classifier gate → generation) rather than an LLM per inbound message. See
`breakeven_generation_rate`.

Same rate discipline as its siblings: the only hard-coded rates are Anthropic's
published $/MTok (imported from `fase0_cost`) and ManyChat's published plan
prices. Every provider-specific per-call rate (hosted zero-shot classification,
hosted embedding/retrieval) is a required caller input and stays `None` when
unsourced — a partial estimate with the gap named, never a fabricated total.
"""

from __future__ import annotations

from pydantic import BaseModel

from qualify_models.eval.fase0_cost import OperationCost, token_cost_usd


class PlanEconomics(BaseModel):
    """One published pricing tier of a per-contact chat-activation product."""

    name: str
    monthly_usd: float
    included_contacts: int
    overage_usd_per_contact: float | None

    @property
    def revenue_per_included_contact(self) -> float:
        """Effective monthly revenue attributable to one contact at plan capacity.

        This is the AI budget ceiling per conversation, and it is the number that
        makes the economics bite: it *falls* as the plan gets more expensive,
        because included contacts grow faster than price.
        """
        if self.included_contacts <= 0:
            return 0.0
        return self.monthly_usd / self.included_contacts


# ManyChat published plans, verified live 2026-07-23 from https://manychat.com/pricing
# (monthly billing; the annual overage rates are lower and are not modeled here).
# Recorded as a *sourced competitive anchor*, not as Qualify pricing.
MANYCHAT_PLANS: dict[str, PlanEconomics] = {
    "free": PlanEconomics(
        name="Free", monthly_usd=0.0, included_contacts=25, overage_usd_per_contact=None
    ),
    "essential": PlanEconomics(
        name="Essential", monthly_usd=14.0, included_contacts=250, overage_usd_per_contact=0.10
    ),
    "pro": PlanEconomics(
        name="Pro", monthly_usd=29.0, included_contacts=2500, overage_usd_per_contact=0.05
    ),
    "business": PlanEconomics(
        name="Business", monthly_usd=69.0, included_contacts=7500, overage_usd_per_contact=0.025
    ),
    "advanced": PlanEconomics(
        name="Advanced", monthly_usd=139.0, included_contacts=25000, overage_usd_per_contact=0.004
    ),
}

# Token shape of one retrieval-grounded reply. ENGINEERING ESTIMATES, not traced
# measurements — the assumption most worth challenging, exactly as in fase0_cost.
# A DM/comment reply is short on output and long on grounding context.
REPLY_SYSTEM_TOKENS_IN = 300  # persona, tone exemplars, safety instructions
REPLY_KNOWLEDGE_CHUNK_TOKENS = 300  # one retrieved chunk
REPLY_KNOWLEDGE_CHUNKS_DEFAULT = 3
REPLY_HISTORY_TOKENS_IN = 400  # prior turns of the thread
REPLY_TOKENS_OUT = 120  # a chat reply is short; this is not a caption or an article

# Fraction of per-contact revenue an activation product can spend on AI before the
# rest of the business (infra, payments, support, margin) is squeezed. Inherited
# verbatim from fase0_cost.AccountEconomics.margin_safe: a WORKING TRIPWIRE, not a
# sourced industry benchmark.
AI_BUDGET_SHARE_OF_REVENUE = 0.20


class ConversationEconomics(BaseModel):
    """AI cost of one conversation with one contact, against that contact's revenue."""

    model_id: str
    plan: PlanEconomics
    operations: list[OperationCost]
    generation_usd_per_conversation: float  # always priced: Anthropic list rates
    total_ai_usd_per_conversation: float | None  # None when any stage is unpriced
    caveats: list[str]

    @property
    def generation_share_of_contact_revenue(self) -> float | None:
        """Generation-only cost as a share of one contact's revenue.

        A **lower bound** on total AI share: classification and retrieval are
        excluded whenever their rates are unsourced. A value >= 1.0 means the
        contact costs more to talk to than it earns, on generation alone.
        """
        revenue = self.plan.revenue_per_included_contact
        if revenue <= 0:
            return None
        return self.generation_usd_per_conversation / revenue

    @property
    def total_share_of_contact_revenue(self) -> float | None:
        revenue = self.plan.revenue_per_included_contact
        if self.total_ai_usd_per_conversation is None or revenue <= 0:
            return None
        return self.total_ai_usd_per_conversation / revenue


def grounded_reply_usd(
    model_id: str, knowledge_chunks: int = REPLY_KNOWLEDGE_CHUNKS_DEFAULT
) -> float:
    """Cost of generating one retrieval-grounded reply turn at list token rates."""
    if knowledge_chunks < 0:
        raise ValueError("knowledge_chunks must be >= 0")
    tokens_in = (
        REPLY_SYSTEM_TOKENS_IN
        + REPLY_HISTORY_TOKENS_IN
        + knowledge_chunks * REPLY_KNOWLEDGE_CHUNK_TOKENS
    )
    return token_cost_usd(model_id, tokens_in, REPLY_TOKENS_OUT)


def intent_classification_usd(
    usd_per_label_call: float | None, labels: int, messages: int
) -> float | None:
    """Cost of zero-shot intent scoring over a conversation.

    An NLI cross-encoder scores one premise against each candidate label, so cost
    is linear in `labels` — which is why the incumbent's own guidance pushes
    operators toward few, narrow, non-overlapping intents (see
    NOTES_manychat_activation_layer.md §1.1). Returns `None` when no per-call
    rate is supplied: no hosted zero-shot classification rate is sourced anywhere
    in this repo.
    """
    if labels < 0 or messages < 0:
        raise ValueError("labels and messages must be >= 0")
    if usd_per_label_call is None:
        return None
    return usd_per_label_call * labels * messages


def breakeven_generation_rate(
    plan_key: str = "pro",
    model_id: str = "claude-haiku-4-5",
    generated_replies: int = 3,
    knowledge_chunks: int = REPLY_KNOWLEDGE_CHUNKS_DEFAULT,
    ai_budget_share: float = AI_BUDGET_SHARE_OF_REVENUE,
) -> float:
    """Max share of contacts that may reach the generative stage and stay in budget.

    This is the cascade discard threshold expressed in dollars, and it is the
    quantitative form of the teardown's central architectural finding: a
    per-contact price point does not fund generation for every contact, so a
    cheap gate in front of the LLM is not an optimization — it is the thing that
    makes the price point exist.

    Returns a fraction in [0, 1]. A value of 1.0 means every contact can be
    generated for within budget; 0.17 means at most ~17% may be.
    """
    plan = _plan(plan_key)
    budget = plan.revenue_per_included_contact * ai_budget_share
    per_generating_conversation = grounded_reply_usd(model_id, knowledge_chunks) * generated_replies
    if per_generating_conversation <= 0:
        return 1.0
    return min(1.0, budget / per_generating_conversation)


def estimate_conversation(
    model_id: str = "claude-haiku-4-5",
    plan_key: str = "pro",
    inbound_messages: int = 3,
    intent_labels: int = 8,
    generated_replies: int = 3,
    knowledge_chunks: int = REPLY_KNOWLEDGE_CHUNKS_DEFAULT,
    intent_usd_per_label_call: float | None = None,
    retrieval_usd_per_query: float | None = None,
) -> ConversationEconomics:
    """AI cost of one conversation, staged as intent -> retrieval -> generation.

    Levers, in descending order of impact:

    - `generated_replies` x `model_id` — the generative turns dominate everything
      else by one to two orders of magnitude, and are the only stage that can
      exceed a contact's revenue on its own.
    - `plan_key` — revenue per contact spans 10x across published tiers
      ($0.056 Essential -> $0.0056 Advanced) and moves the *wrong* way: the
      higher-priced plans have *less* room per contact, not more.
    - `knowledge_chunks` — linear on the input side, second-order at 3-5 chunks.
    - `intent_labels` — linear, but on a stage that is 1-2 orders of magnitude
      cheaper per call; it matters for latency more than for dollars.

    `intent_usd_per_label_call` and `retrieval_usd_per_query` are REQUIRED INPUTS
    with no default: no hosted zero-shot-classification or embedding rate is
    sourced in this repo. Leaving them `None` yields a generation-only lower
    bound with the gap named, never a fabricated total.
    """
    plan = _plan(plan_key)
    reply_unit = grounded_reply_usd(model_id, knowledge_chunks)
    generation_total = reply_unit * generated_replies
    intent_total = intent_classification_usd(
        intent_usd_per_label_call, intent_labels, inbound_messages
    )
    retrieval_total = (
        retrieval_usd_per_query * generated_replies if retrieval_usd_per_query is not None else None
    )

    operations: list[OperationCost] = [
        OperationCost(
            operation="intent_classification",
            usd_total=intent_total,
            documented=intent_total is not None,
            source="caller-supplied" if intent_total is not None else "UNDOCUMENTED",
            note=(
                f"{intent_labels} labels x {inbound_messages} messages; zero-shot NLI is linear "
                "in labels — no hosted per-call rate sourced in this repo — REQUIRED INPUT"
            ),
        ),
        OperationCost(
            operation="retrieval",
            usd_total=retrieval_total,
            documented=retrieval_total is not None,
            source="caller-supplied" if retrieval_total is not None else "UNDOCUMENTED",
            note=(
                f"{generated_replies} queries over the knowledge corpus; no hosted embedding "
                "rate sourced in this repo — REQUIRED INPUT"
            ),
        ),
        OperationCost(
            operation="grounded_generation",
            usd_total=generation_total,
            documented=True,
            source=f"Anthropic list price for {model_id} (claude-api skill, 2026-06-24)",
            note=(
                f"{generated_replies} turns @ ${reply_unit:.5f} "
                f"({knowledge_chunks} retrieved chunks per turn)"
            ),
        ),
    ]

    caveats: list[str] = []
    if intent_total is None:
        caveats.append(
            "Intent-classification $/call is undocumented — pass intent_usd_per_label_call from a "
            "quoted rate, or 0.0 when the classifier is self-hosted on the existing CPU worker."
        )
    if retrieval_total is None:
        caveats.append(
            "Retrieval $/query is undocumented — pass retrieval_usd_per_query from a quoted rate, "
            "or 0.0 when embeddings are self-hosted."
        )
    caveats.append(
        "Reply token shape (~1600 in / 120 out at 3 chunks) is an engineering estimate, not a "
        "traced measurement; re-measure against real prompts before pricing a plan on it."
    )
    caveats.append(
        "Anthropic list prices are cached 2026-06-24 and exclude prompt caching, which is a large "
        "unclaimed saving here: the persona/tone preamble is identical across every reply."
    )
    caveats.append(
        "Plan economics are ManyChat's published prices (verified 2026-07-23), used as a sourced "
        "competitive anchor for what a per-contact price point can fund — not as Qualify pricing."
    )

    total: float | None
    if any(op.usd_total is None for op in operations):
        total = None
    else:
        total = sum(op.usd_total for op in operations if op.usd_total is not None)

    return ConversationEconomics(
        model_id=model_id,
        plan=plan,
        operations=operations,
        generation_usd_per_conversation=generation_total,
        total_ai_usd_per_conversation=total,
        caveats=caveats,
    )


def _plan(plan_key: str) -> PlanEconomics:
    if plan_key not in MANYCHAT_PLANS:
        raise KeyError(f"Unknown plan {plan_key!r}; known: {sorted(MANYCHAT_PLANS)}")
    return MANYCHAT_PLANS[plan_key]
