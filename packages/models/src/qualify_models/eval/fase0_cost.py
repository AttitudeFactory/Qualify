"""Parametric unit economics for a Fase 0 publishing-API product.

Sibling of `cost.py`, which models the Fase 1 cascade at $/video. Fase 0 sells
per *connected account per month*, so the unit of analysis changes: the question
is not "what does one video cost" but "does the AI spend on one account fit
inside that account's subscription revenue".

Same discipline as `cost.py`: rates that cannot be sourced stay `None` and are
reported as caveats rather than invented. The only rates hard-coded here are
Anthropic's published $/MTok token prices; everything provider-specific
(hosted ASR, hosted VLM, scraping) is a required caller input.
"""

from __future__ import annotations

from pydantic import BaseModel

from qualify_models.oauth_scope import (
    CascadeStage,
    ContentSurface,
    requires_enrichment_gate,
    stages_for_surface,
)

# Anthropic list prices, USD per million tokens (input, output).
# Source: claude-api skill model table, cached 2026-06-24. Re-verify before
# quoting externally — list prices change and intro pricing expires.
TOKEN_RATES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Token shapes for the two generative operations modeled here. These are
# engineering estimates of prompt/response size, not measured values — they are
# the assumption most worth challenging with a real trace.
CAPTION_TOKENS_IN = 500
CAPTION_TOKENS_OUT = 200

# One "video analysis" = N sampled frames through a VLM plus a short prompt.
# ~1600 input tokens per frame is the standard-resolution image cost on the
# Anthropic API; high-resolution frames cost up to ~3x more.
VIDEO_FRAMES_DEFAULT = 4
VIDEO_TOKENS_PER_FRAME = 1600
VIDEO_PROMPT_TOKENS_IN = 500
VIDEO_TOKENS_OUT = 400


class OperationCost(BaseModel):
    """Cost of one operation over the period defined by the enclosing model.

    `usd_total` was named `usd_per_call` until 2026-07-24, which was a misnomer:
    every construction site populates it with a *period total*, not a unit
    price — a month of captions in `estimate_account`, one conversation's worth
    of turns in `conversation_cost`. Harmless internally, actively misleading
    the moment this model is serialized into a pricing deck. Renamed
    period-neutrally rather than to `usd_per_month`, because the two consumers
    aggregate over different periods.
    """

    operation: str
    usd_total: float | None
    documented: bool
    source: str
    note: str | None = None


class AccountEconomics(BaseModel):
    """Monthly AI cost for one connected account, against its revenue."""

    model_id: str
    revenue_usd_per_month: float
    operations: list[OperationCost]
    total_ai_usd_per_month: float | None
    ai_share_of_revenue: float | None  # None when any operation is unpriced
    caveats: list[str]

    @property
    def margin_safe(self) -> bool | None:
        """True when AI spend stays under 20% of the account's revenue.

        20% is a working threshold, not a sourced industry benchmark: it leaves
        room for infra, payment fees, and support inside a per-account price
        that is already only $1-6. Treat it as a tripwire, not a target.
        """
        if self.ai_share_of_revenue is None:
            return None
        return self.ai_share_of_revenue < 0.20


def token_cost_usd(model_id: str, tokens_in: int, tokens_out: int) -> float:
    """Cost of a single call at a model's list token rates."""
    if model_id not in TOKEN_RATES_USD_PER_MTOK:
        raise KeyError(f"Unknown model_id {model_id!r}; known: {sorted(TOKEN_RATES_USD_PER_MTOK)}")
    rate_in, rate_out = TOKEN_RATES_USD_PER_MTOK[model_id]
    return tokens_in * rate_in / 1e6 + tokens_out * rate_out / 1e6


def caption_generation_usd(model_id: str) -> float:
    """Cost of generating one platform-adapted caption."""
    return token_cost_usd(model_id, CAPTION_TOKENS_IN, CAPTION_TOKENS_OUT)


def video_analysis_usd(model_id: str, frames: int = VIDEO_FRAMES_DEFAULT) -> float:
    """Cost of one VLM pass over `frames` sampled frames of a video.

    This is the Fase 0 reuse of the Fase 1 cascade's F3 stage, repriced against
    a hosted frontier VLM instead of a self-hosted open-weight one. It excludes
    ASR: no per-minute transcription rate is sourced (see `estimate_account`).
    """
    if frames < 1:
        raise ValueError("frames must be >= 1")
    tokens_in = frames * VIDEO_TOKENS_PER_FRAME + VIDEO_PROMPT_TOKENS_IN
    return token_cost_usd(model_id, tokens_in, VIDEO_TOKENS_OUT)


def estimate_account(
    model_id: str = "claude-haiku-4-5",
    revenue_usd_per_month: float = 6.0,
    posts_per_month: int = 20,
    captions_per_post: int = 1,
    own_videos_analyzed_per_month: int = 0,
    competitor_videos_analyzed_per_month: int = 0,
    frames_per_video: int = VIDEO_FRAMES_DEFAULT,
    asr_usd_per_video: float | None = None,
    comment_triage_usd_per_month: float | None = None,
) -> AccountEconomics:
    """Monthly AI cost for one connected account under a usage profile.

    Levers, in descending order of impact on the total:

    - `*_videos_analyzed_per_month` — video analysis is ~6x a caption per call
      and is the only lever that can plausibly exceed revenue on its own.
    - `model_id` — Opus 4.8 is ~5x Haiku 4.5 for identical token shapes.
    - `revenue_usd_per_month` — the denominator moves 6x across the pricing
      tiers of a per-connected-account product ($6 -> $1), so an operation that
      is affordable for a small customer can be underwater for a large one.
    - `posts_per_month` / `captions_per_post` — real but second-order.

    `asr_usd_per_video` and `comment_triage_usd_per_month` are REQUIRED INPUTS
    with no default rate: no per-minute hosted-ASR price and no comment-volume
    profile is sourced anywhere in this repo. Leaving them `None` yields a
    partial estimate with the gap named, never a fabricated total.
    """
    caption_unit = caption_generation_usd(model_id)
    video_unit = video_analysis_usd(model_id, frames=frames_per_video)
    total_videos = own_videos_analyzed_per_month + competitor_videos_analyzed_per_month

    operations: list[OperationCost] = [
        OperationCost(
            operation="caption_generation",
            usd_total=caption_unit * posts_per_month * captions_per_post,
            documented=True,
            source=f"Anthropic list price for {model_id} (claude-api skill, 2026-06-24)",
            note=f"{posts_per_month * captions_per_post} captions/mo @ ${caption_unit:.5f}",
        ),
        OperationCost(
            operation="video_analysis",
            usd_total=video_unit * total_videos,
            documented=True,
            source=f"Anthropic list price for {model_id} (claude-api skill, 2026-06-24)",
            note=(
                f"{total_videos} videos/mo @ ${video_unit:.4f} "
                f"({frames_per_video} frames); VLM only, excludes ASR"
            ),
        ),
        OperationCost(
            operation="transcription",
            usd_total=(asr_usd_per_video * total_videos) if asr_usd_per_video is not None else None,
            documented=asr_usd_per_video is not None,
            source="caller-supplied" if asr_usd_per_video is not None else "UNDOCUMENTED",
            note="no hosted per-minute ASR rate is sourced in this repo — REQUIRED INPUT",
        ),
        OperationCost(
            operation="comment_triage",
            usd_total=comment_triage_usd_per_month,
            documented=comment_triage_usd_per_month is not None,
            source=(
                "caller-supplied" if comment_triage_usd_per_month is not None else "UNDOCUMENTED"
            ),
            note="depends on per-account comment volume, which is unmeasured — REQUIRED INPUT",
        ),
    ]

    caveats: list[str] = []
    if asr_usd_per_video is None:
        caveats.append(
            "ASR $/video is undocumented — pass asr_usd_per_video from a quoted/measured rate."
        )
    if comment_triage_usd_per_month is None:
        caveats.append(
            "Comment-triage $/month is undocumented — depends on unmeasured comment volume."
        )
    caveats.append(
        "Token shapes (caption ~500/200, frame ~1600 in) are engineering estimates, not "
        "measured traces; re-measure against real prompts before pricing a plan on them."
    )
    caveats.append(
        "Anthropic list prices are cached 2026-06-24 and exclude prompt caching and batch "
        "discounts (batch is 50% off), both of which materially lower steady-state cost."
    )

    if any(op.usd_total is None for op in operations):
        total: float | None = None
        share: float | None = None
    else:
        total = sum(op.usd_total for op in operations if op.usd_total is not None)
        share = total / revenue_usd_per_month if revenue_usd_per_month > 0 else None

    return AccountEconomics(
        model_id=model_id,
        revenue_usd_per_month=revenue_usd_per_month,
        operations=operations,
        total_ai_usd_per_month=total,
        ai_share_of_revenue=share,
        caveats=caveats,
    )


# --------------------------------------------------------------------------
# CRM integration path (task D4)
#
# Sibling of `estimate_account`, not a replacement. The publishing product is
# driven by how much the client PUBLISHES; the CRM product is driven by how
# much their audience and third parties SAY — inbound volume, which is a
# behaviour of other people and is entirely unmeasured in this project.
#
# Stage applicability is read from `oauth_scope.APPLICABILITY` rather than
# restated here, so a stage that does not apply to a surface contributes a
# structural zero instead of a number someone typed.
# --------------------------------------------------------------------------


class CrmAccountEconomics(BaseModel):
    """Monthly AI cost for one connected account on the OAuth/CRM path."""

    model_id: str
    revenue_usd_per_month: float
    operations: list[OperationCost]
    total_ai_usd_per_month: float | None
    ai_share_of_revenue: float | None
    mentions_enriched_per_month: float | None
    caveats: list[str]

    @property
    def margin_safe(self) -> bool | None:
        """True when AI spend stays under 20% of the account's revenue.

        Same working tripwire as `AccountEconomics.margin_safe`, and the same
        caveat: not a sourced industry benchmark.
        """
        if self.ai_share_of_revenue is None:
            return None
        return self.ai_share_of_revenue < 0.20


def comment_sentiment_applies() -> bool:
    """Whether polarity over owned-media comments is a billable stage.

    Reads the applicability matrix instead of asserting it, so this module and
    `oauth_scope` cannot drift apart silently.
    """
    return CascadeStage.SENTIMENT in stages_for_surface(ContentSurface.OWNED_MEDIA_COMMENTS)


def estimate_crm_account(
    model_id: str = "claude-haiku-4-5",
    revenue_usd_per_month: float = 6.0,
    comments_per_month: int | None = None,
    mentions_per_month: int | None = None,
    mention_gate_pass_rate: float | None = None,
    frames_per_mention: int = VIDEO_FRAMES_DEFAULT,
    sentiment_usd_per_comment: float | None = None,
    gate_usd_per_mention: float | None = None,
    asr_usd_per_mention: float | None = None,
    analyze_mentions: bool = True,
) -> CrmAccountEconomics:
    """Monthly AI cost for one connected Instagram account on the CRM path.

    Two increments, selected by `analyze_mentions`:

    - **Day-one increment** (`analyze_mentions=False`): comments only. Polarity
      over owned-media comments is the single stage that transfers unchanged
      (`oauth_scope`, docs/fase0-zernio-mercado.md §4.3) — no VLM, no GPU, no
      scraping.
    - **Earned-media increment** (`analyze_mentions=True`): adds `mentioned_media`
      and `tags`, where vision and transcription transfer unchanged. This is
      where cost stops being trivial, because third-party volume is unbounded.

    Levers, in descending order of impact:

    - `mentions_per_month` x `mention_gate_pass_rate` — dominant, and the reason
      the gate exists. Mention volume is set by third parties, not by the
      client, so it is the one input that can grow without limit while revenue
      stays fixed at one account's subscription.
    - `mention_gate_pass_rate` — multiplies every downstream per-mention cost.
      A gate that passes 20% cuts VLM+ASR spend fivefold. NOTE: no such gate
      currently works — `filter.py` is a constant-`False` function (task #13),
      and per `oauth_scope` the surviving gate is metadata/text predicates, not
      siglip2. So this parameter prices a component that does not yet exist.
    - `model_id` — Opus 4.8 is ~5x Haiku 4.5 at identical token shapes.
    - `comments_per_month` — real but second-order once a cheap classifier is
      self-hosted; see `sentiment_usd_per_comment`.

    UNMEASURED INPUTS WITH NO DEFAULT. All of these are behaviours of other
    people that nobody in this project has measured, so none of them gets an
    invented value; leaving any of them `None` yields a partial estimate with
    the gap named, never a fabricated total:

    - `comments_per_month`, `mentions_per_month` — no connected-account volume
      data exists in this repo.
    - `mention_gate_pass_rate` — no gate has ever been calibrated.
    - `sentiment_usd_per_comment` — robertuito's CPU cost has never been
      measured here, and no hosted per-call rate is sourced. Pass `0.0` when
      self-hosting on an already-provisioned worker; that is a modelling
      choice the caller makes explicitly, not a default this function assumes.
    - `gate_usd_per_mention` — likewise for the enrichment gate.
    - `asr_usd_per_mention` — the same unsourced hosted-ASR rate that
      `eval/README.md` and `estimate_account` have flagged since Fase 1.

    Only VLM cost is priced from published rates (Anthropic list prices), and
    only because it is a token-shaped operation on a model whose prices are
    published.
    """
    if not comment_sentiment_applies():  # pragma: no cover - guards matrix drift
        raise RuntimeError(
            "oauth_scope no longer marks sentiment billable on owned_media_comments; "
            "the CRM cost model's premise has changed and must be re-derived."
        )
    if mention_gate_pass_rate is not None and not 0.0 <= mention_gate_pass_rate <= 1.0:
        raise ValueError("mention_gate_pass_rate must lie in [0.0, 1.0]")
    if frames_per_mention < 1:
        raise ValueError("frames_per_mention must be >= 1")

    caveats: list[str] = []
    operations: list[OperationCost] = []

    # --- comment polarity: the day-one increment --------------------------
    comment_total: float | None = None
    if comments_per_month is not None and sentiment_usd_per_comment is not None:
        comment_total = comments_per_month * sentiment_usd_per_comment
    operations.append(
        OperationCost(
            operation="comment_sentiment",
            usd_total=comment_total,
            documented=comment_total is not None,
            source="caller-supplied" if comment_total is not None else "UNDOCUMENTED",
            note=(
                "robertuito over owned-media comments; the only stage transferring "
                "unchanged. Volume AND unit cost are both unmeasured — REQUIRED INPUTS"
            ),
        )
    )
    if comments_per_month is None:
        caveats.append(
            "comments_per_month is unmeasured — no connected-account comment-volume data "
            "exists in this repo. REQUIRED INPUT."
        )
    if sentiment_usd_per_comment is None:
        caveats.append(
            "sentiment_usd_per_comment is unmeasured — robertuito CPU cost was never profiled "
            "here and no hosted per-call rate is sourced. Pass 0.0 to model self-hosting."
        )

    # --- earned-media increment -------------------------------------------
    enriched: float | None = None
    if not analyze_mentions:
        caveats.append(
            "Day-one increment: mention enrichment excluded (analyze_mentions=False). "
            "Comments only — no VLM, no ASR, no GPU."
        )
    else:
        if not requires_enrichment_gate(ContentSurface.MENTIONED_MEDIA):  # pragma: no cover
            raise RuntimeError("oauth_scope no longer gates mentioned_media; re-derive this model.")

        if mentions_per_month is not None and mention_gate_pass_rate is not None:
            enriched = mentions_per_month * mention_gate_pass_rate

        gate_total: float | None = None
        if mentions_per_month is not None and gate_usd_per_mention is not None:
            gate_total = mentions_per_month * gate_usd_per_mention
        operations.append(
            OperationCost(
                operation="enrichment_gate",
                usd_total=gate_total,
                documented=gate_total is not None,
                source="caller-supplied" if gate_total is not None else "UNDOCUMENTED",
                note=(
                    "runs on EVERY mention, before the VLM. Metadata/text predicates, not "
                    "siglip2 — and no such gate is implemented yet (task #13) — REQUIRED INPUT"
                ),
            )
        )

        vlm_unit = video_analysis_usd(model_id, frames=frames_per_mention)
        vlm_total = enriched * vlm_unit if enriched is not None else None
        operations.append(
            OperationCost(
                operation="mention_vision",
                usd_total=vlm_total,
                documented=vlm_total is not None,
                source=f"Anthropic list price for {model_id} (claude-api skill, 2026-06-24)",
                note=(
                    f"{frames_per_mention} frames @ ${vlm_unit:.5f}/mention, charged only on "
                    "gate-passing mentions; VLM only, excludes ASR"
                ),
            )
        )

        asr_total: float | None = None
        if enriched is not None and asr_usd_per_mention is not None:
            asr_total = enriched * asr_usd_per_mention
        operations.append(
            OperationCost(
                operation="mention_transcription",
                usd_total=asr_total,
                documented=asr_total is not None,
                source="caller-supplied" if asr_total is not None else "UNDOCUMENTED",
                note="no hosted per-minute ASR rate is sourced in this repo — REQUIRED INPUT",
            )
        )

        if mentions_per_month is None:
            caveats.append(
                "mentions_per_month is unmeasured and is set by third parties, not by the "
                "client — it can grow without limit while revenue stays fixed. REQUIRED INPUT."
            )
        if mention_gate_pass_rate is None:
            caveats.append(
                "mention_gate_pass_rate is uncalibrated — no enrichment gate has ever been "
                "measured, and the incumbent filter is a constant-False function (task #13)."
            )
        if gate_usd_per_mention is None:
            caveats.append("gate_usd_per_mention is unmeasured — pass 0.0 to model self-hosting.")
        if asr_usd_per_mention is None:
            caveats.append(
                "asr_usd_per_mention is undocumented — the same open question flagged in "
                "eval/README.md since Fase 1, still unclosed."
            )

    caveats.append(
        "Competitor and unaffiliated-creator content are absent from this model by construction: "
        "oauth_scope marks them UNREACHABLE, so no OAuth-path cost can be attributed to them."
    )
    caveats.append(
        "Anthropic list prices are cached 2026-06-24 and exclude prompt caching and batch "
        "discounts; token shapes are engineering estimates, not traced measurements."
    )

    if any(op.usd_total is None for op in operations):
        total: float | None = None
        share: float | None = None
    else:
        total = sum(op.usd_total for op in operations if op.usd_total is not None)
        share = total / revenue_usd_per_month if revenue_usd_per_month > 0 else None

    return CrmAccountEconomics(
        model_id=model_id,
        revenue_usd_per_month=revenue_usd_per_month,
        operations=operations,
        total_ai_usd_per_month=total,
        ai_share_of_revenue=share,
        mentions_enriched_per_month=enriched,
        caveats=caveats,
    )
