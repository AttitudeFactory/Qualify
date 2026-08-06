"""Fase C: how big the corpus has to be before the Fase D analysis means anything, and
what that corpus costs.

This module exists so the answer to "how many videos do we need?" is a computation the
founder can re-run with his own assumptions, not a number someone asserted. It derives
the corpus size from the effect the analysis is supposed to detect, and prices it against
rates that are **quoted from `docs/alternativas-fase1.md`** with the source named on each
constant.

House rule inherited from `eval/cost.py` and kept here: **an unsourced rate is `None`, not
a guess.** A total that silently omits an unpriced stage is worse than no total.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from qualify_models.hooks.analysis import minimum_n_per_group

# --- rates, each with its source ----------------------------------------------------

DATA365_USD_PER_1K_RECORDS = 0.60
"""docs/alternativas-fase1.md §2a: "Desde ~$0.60/1K registros". A post and a comment are
each one record."""

APIFY_USD_PER_1K_RECORDS = 1.70
"""docs/alternativas-fase1.md §2a: "~$1.70/1K (variable)". The prototyping option."""

GROQ_WHISPER_USD_PER_HOUR = 0.04
"""docs/alternativas-fase1.md §2b: Groq Whisper-v3 batch, ~$0.04/h of audio."""

ZYTE_USD_PER_REQUEST: float | None = None
"""NOT SOURCED. docs/alternativas-fase1.md quotes Zyte only as "PAYG desde $0 (tope
$100/mes); Standard $100/mes" — a plan price, not a per-request price. Any per-video Zyte
figure in this repo would be invented, so this stays None and every total that depends on
it is reported as None. Closing it needs a quote from docs.zyte.com/zyte-api/pricing.html
against the actual request type used."""

VLM_USD_PER_VIDEO: float | None = None
"""NOT SOURCED for the hosted path. The local Qwen3-VL path has zero marginal cost (it is
laptop time), and `eval/fase0_cost.py` can price a hosted frontier model at its documented
token-shape assumptions — but those assumptions were never traced against a real hook
prompt. Left None rather than copied across."""


# --- corpus sizing -------------------------------------------------------------------


class CorpusPlan(BaseModel):
    """What has to be collected, and why exactly that much."""

    detectable_effect_d: float = Field(description="smallest standardized effect targeted")
    power: float
    alpha: float
    n_hook_types_compared: int
    rarest_type_share: float = Field(description="assumed share of the rarest compared type")
    posts_per_type_needed: int
    total_posts_needed: int
    min_accounts: int
    posts_per_account: int
    rationale: str


def plan_corpus(
    detectable_effect_d: float = 0.8,
    power: float = 0.80,
    alpha: float = 0.05,
    n_hook_types_compared: int = 4,
    rarest_type_share: float = 0.12,
    min_accounts: int = 8,
) -> CorpusPlan:
    """Derive corpus size from the effect the study must be able to see.

    Defaults chosen to be achievable rather than flattering, and each is a lever the
    founder can move:

    * `detectable_effect_d=0.8` — a **large** effect. Targeting a medium effect (0.5)
      roughly triples the corpus. The honest framing: this study can find "question hooks
      clearly outrank statement hooks", and cannot find a subtle 5-percentile edge.
    * `n_hook_types_compared=4` — only the most common types get compared. Testing all 13
      both starves the rare ones and multiplies the false-positive correction.
    * `rarest_type_share=0.12` — the least common of those four is assumed to be ~12% of
      posts. This is a **guess about the corpus that has not been measured** (nobody has
      typed a real Spanish real-estate library yet) and it is the single assumption most
      likely to be wrong. If it turns out to be 5%, the corpus needs to be ~2.4x bigger.
      Measuring it is the first thing a 50-video pilot buys.
    * `min_accounts=8` — a hook type appearing in fewer than 3 accounts is that account's
      house style, not a pattern; 8 accounts leaves room for that floor to hold across
      several types.
    """
    per_type = minimum_n_per_group(detectable_effect_d, power=power, alpha=alpha)
    total = math.ceil(per_type / rarest_type_share)
    per_account = math.ceil(total / min_accounts)
    return CorpusPlan(
        detectable_effect_d=detectable_effect_d,
        power=power,
        alpha=alpha,
        n_hook_types_compared=n_hook_types_compared,
        rarest_type_share=rarest_type_share,
        posts_per_type_needed=per_type,
        total_posts_needed=total,
        min_accounts=min_accounts,
        posts_per_account=per_account,
        rationale=(
            f"{per_type} posts/type to detect d={detectable_effect_d} at {power:.0%} power; "
            f"the rarest of {n_hook_types_compared} compared types is assumed to be "
            f"{rarest_type_share:.0%} of the corpus, so {total} posts total, spread over "
            f"at least {min_accounts} accounts ({per_account} each)."
        ),
    )


# --- corpus cost ---------------------------------------------------------------------


class CorpusCost(BaseModel):
    """Cost of acquiring and processing one corpus. `None` means unpriced, never zero."""

    total_posts: int
    comments_per_post: int
    total_records: int
    acquisition_usd_data365: float
    acquisition_usd_apify: float
    acquisition_usd_zyte: float | None
    asr_usd: float
    vlm_usd: float | None
    total_usd_low: float | None
    total_usd_high: float | None
    human_labeling_hours: float
    notes: list[str]


def estimate_corpus_cost(
    plan: CorpusPlan,
    comments_per_post: int = 50,
    asr_seconds_per_video: float = 15.0,
    golden_set_size: int = 100,
    minutes_per_label: float = 2.0,
    labelers: int = 2,
) -> CorpusCost:
    """Price a corpus plan.

    `asr_seconds_per_video=15` is 3 s + 5 s + 7 s: the hook extractor transcribes each
    window separately (one exact short call per window beats interpolating timestamps it
    does not have), so it never touches the other ~50 s of the video.
    """
    total_records = plan.total_posts_needed * (1 + comments_per_post)
    data365 = total_records / 1000 * DATA365_USD_PER_1K_RECORDS
    apify = total_records / 1000 * APIFY_USD_PER_1K_RECORDS
    zyte = None if ZYTE_USD_PER_REQUEST is None else plan.total_posts_needed * ZYTE_USD_PER_REQUEST
    asr_hours = plan.total_posts_needed * asr_seconds_per_video / 3600
    asr = asr_hours * GROQ_WHISPER_USD_PER_HOUR
    vlm = None if VLM_USD_PER_VIDEO is None else plan.total_posts_needed * VLM_USD_PER_VIDEO

    # The local Qwen3-VL path costs nothing per video, so a total that assumes it is a
    # real, quotable number. The hosted path is not priced, and stays None.
    total_low = data365 + asr
    total_high = None if vlm is None else apify + asr + vlm

    labeling_hours = golden_set_size * labelers * minutes_per_label / 60

    return CorpusCost(
        total_posts=plan.total_posts_needed,
        comments_per_post=comments_per_post,
        total_records=total_records,
        acquisition_usd_data365=round(data365, 2),
        acquisition_usd_apify=round(apify, 2),
        acquisition_usd_zyte=zyte,
        asr_usd=round(asr, 4),
        vlm_usd=vlm,
        total_usd_low=round(total_low, 2),
        total_usd_high=total_high,
        human_labeling_hours=round(labeling_hours, 1),
        notes=[
            "acquisition_usd_zyte is None: docs/alternativas-fase1.md quotes Zyte as a "
            "monthly plan, never as a per-request rate. Not invented here.",
            "vlm_usd is None for the hosted path; the local Qwen3-VL path has zero "
            "marginal cash cost (laptop time only).",
            "total_usd_low assumes Data365 acquisition + hosted ASR + local VLM.",
            "The dominant real cost is not dollars, it is the "
            f"{round(labeling_hours, 1)} person-hours of human labelling needed for the "
            "golden set that makes the VLM's hook_type trustworthy.",
            "Video file bytes (download bandwidth) are excluded: a few GB, immaterial.",
        ],
    )
