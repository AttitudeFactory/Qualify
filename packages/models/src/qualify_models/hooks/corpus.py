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
from enum import StrEnum

from pydantic import BaseModel, Field

from qualify_models.hooks.analysis import minimum_n_per_group

# --- rates, each with its source ----------------------------------------------------

DATA365_USD_PER_1K_RECORDS = 0.60
"""docs/alternativas-fase1.md §2a: "Desde ~$0.60/1K registros". A post and a comment are
each one record.

CAVEAT added 2026-08-06, and it applies to every acquisition total in this module: this
prices **metadata records**, and the totals below silently assumed that paying for a record
yields a downloadable video. Nobody had checked that, and it is not true — byte-fetch is a
separate unsolved problem on the paid path. Treat these totals as a floor for metadata, not
as the price of a corpus. Moot in practice: acquisition was solved at $0 with yt-dlp
(NOTES_hook_pattern_spike.md §C.3), so the interesting cost is no longer money."""

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
"""STILL NOT SOURCED for the hosted path, but for a narrower reason than before.

Measured 2026-08-06 against a real hook call (featherless-ai, Qwen3-VL-4B, 6-frame contact
sheet): the API reports 316 prompt + 55 completion = 371 tokens per video. So the token
shape is no longer a guess — the *rate* is what is missing:

* HF's own docs say it charges the provider's rate with no markup, and HF publishes
  per-token rates per (model, provider) in its router catalogue — but Qwen3-VL-4B is not
  in that catalogue, and its `inferenceProviderMapping` carries no pricing block.
* featherless.ai publishes plans ($25/mo flat, $50/mo "billed per token") and no per-token
  rate for any specific model.

What would settle it, cheaply: run the 50-video pilot of C.5 and read the actual spend at
huggingface.co/settings/inference-providers/overview, which breaks usage down by model and
provider. That converts this from an estimate into a measurement, which is the only kind of
cost number this module accepts."""

HOSTED_VLM_SECONDS_PER_VIDEO = 15.0
"""MEASURED 2026-08-06 on this machine, wall clock for the full default extraction of one
video (3 windows -> 3 ASR calls + 1 hosted VLM call + the deterministic tier): 11.7 s and
17.8 s on two consecutive runs. 15 s is the round middle, not a target."""

LOCAL_VLM_SECONDS_PER_VIDEO = 1393.0
"""MEASURED TO COMPLETION 2026-08-06: 23 min 12.89 s wall clock (35 s user, 450 s system,
34% CPU) for one video on the *shipping* config — single 3 s window, 6-frame contact sheet
at 256 px, one ASR call, weights disk-offloaded.

This replaces the earlier 1200.0, which was a floor taken from a run cut at 20 min 48 s
before it finished. The completed run is both larger and better founded: it is the
configuration the CLI actually ships, and it terminated, so it is a duration rather than a
lower bound. Kept in the model because the ~90x gap against the hosted path is the whole
reason the extractor now defaults to hosted."""


# --- corpus sizing -------------------------------------------------------------------


MIN_ACCOUNTS_PER_TYPE = 3
"""A hook type seen in fewer than this many accounts is that account's house style, not a
pattern. Mirrors `hook_type_effects(min_accounts_per_type=3)`; kept here too because the
corpus has to be *bought* against it long before the analysis runs."""


class CorpusStudyKind(StrEnum):
    """What a given corpus can honestly be used for. These are not degrees of the same
    thing — they license different sentences in the final write-up."""

    INFERENTIAL = "inferential"
    """Enough accounts, with margin, to compare hook types and report an effect."""

    MEASUREMENT_ONLY = "measurement_only"
    """Too few accounts for any hook->performance claim, but able to settle the guesses the
    inferential design rests on (hook-type distribution, within-account hook variety,
    outcome dispersion). A real deliverable, not a consolation prize — it is what turns
    `rarest_type_share` from an assumption into a number."""

    NOT_VIABLE = "not_viable"
    """Cannot support either. Nothing to buy here."""


class CorpusFeasibility(BaseModel):
    """Whether the accounts that actually exist can carry the plan that was designed.

    Separate from `CorpusPlan` on purpose: the plan says what the *question* costs, this
    says what the *world* offers. When they disagree, the plan is not what gives way — the
    claim is. Lowering `min_accounts` to fit the available accounts would manufacture a
    finding, which is the one move this module exists to prevent.
    """

    available_accounts: int
    videos_available: int
    plan_min_accounts: int
    plan_total_posts: int
    accounts_margin: int = Field(
        description="available accounts beyond the per-type floor; 0 means zero degrees of freedom"
    )
    kind: CorpusStudyKind
    supports_hook_performance_claim: bool
    what_it_can_settle: list[str]
    reasons: list[str]


def assess_corpus_feasibility(
    plan: CorpusPlan,
    available_accounts: int,
    videos_available: int,
    min_accounts_per_type: int = MIN_ACCOUNTS_PER_TYPE,
) -> CorpusFeasibility:
    """Classify what a corpus of `available_accounts` accounts can honestly deliver.

    The arithmetic that matters, and it is not the one people reach for: with exactly
    `min_accounts_per_type` accounts, a hook type must appear in **every single one** to
    clear the floor. That is zero margin — one account not using a type removes that type
    from the study entirely, and one template-driven advertiser collapses the comparison.
    So `available_accounts == 3` is not "the 8-account plan, smaller"; it is a different
    kind of study, and this returns that as a typed value rather than a caveat someone can
    drop when copying the numbers into a deck.

    Note what this deliberately does NOT do: it never lowers `plan.min_accounts`. If the
    world offers three accounts and the question needs eight, the answer is that this
    corpus cannot answer that question — not that the question should be quietly rewritten
    to one the corpus can answer.
    """
    margin = available_accounts - min_accounts_per_type
    reasons: list[str] = []

    if available_accounts < min_accounts_per_type:
        kind = CorpusStudyKind.NOT_VIABLE
        reasons.append(
            f"{available_accounts} account(s) is below the {min_accounts_per_type}-account "
            "floor for distinguishing a pattern from one advertiser's house style."
        )
    elif available_accounts < plan.min_accounts:
        kind = CorpusStudyKind.MEASUREMENT_ONLY
        reasons.append(
            f"{available_accounts} accounts clears the {min_accounts_per_type}-account floor "
            f"with margin {margin}, but the plan needs {plan.min_accounts} to leave room for "
            "several hook types to clear it at once."
        )
        if margin == 0:
            reasons.append(
                "Margin is zero: every hook type would have to appear in ALL "
                f"{available_accounts} accounts to count. One account omitting a type erases "
                "that type from the study."
            )
    else:
        kind = CorpusStudyKind.INFERENTIAL
        reasons.append(
            f"{available_accounts} accounts meets the plan's {plan.min_accounts}-account floor."
        )

    if videos_available < plan.total_posts_needed:
        reasons.append(
            f"{videos_available} videos available against {plan.total_posts_needed} needed."
        )
        if kind is CorpusStudyKind.INFERENTIAL:
            kind = CorpusStudyKind.MEASUREMENT_ONLY

    can_settle: list[str] = []
    if kind is not CorpusStudyKind.NOT_VIABLE:
        can_settle = [
            "The hook-type distribution, i.e. whether `rarest_type_share=0.12` holds. This "
            "is the plan's most fragile assumption and it is currently a guess.",
            "Within-account hook variety — whether these accounts vary their openings at "
            "all. This is the real binding constraint: an account publishing one template "
            "contributes nothing at ANY corpus size, so more accounts would not fix it.",
            "Outcome dispersion, i.e. whether views actually spread within an account. A "
            "3.5x range measured on six videos is resolution, not variance.",
            "The per-video acquisition failure rate, which sets the over-enumeration budget.",
        ]

    return CorpusFeasibility(
        available_accounts=available_accounts,
        videos_available=videos_available,
        plan_min_accounts=plan.min_accounts,
        plan_total_posts=plan.total_posts_needed,
        accounts_margin=margin,
        kind=kind,
        supports_hook_performance_claim=kind is CorpusStudyKind.INFERENTIAL,
        what_it_can_settle=can_settle,
        reasons=reasons,
    )


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
    # Wall clock is a cost too, and on this corpus it was the binding one: the money was
    # ~$7 either way, while the choice of vision backend moved the run between one hour
    # and three days.
    extraction_hours_hosted_vlm: float
    extraction_hours_local_vlm: float
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

    # Serial, single-process: the honest worst case. Both numbers scale down with
    # concurrency, but only one of them is tolerable without it.
    hosted_hours = plan.total_posts_needed * HOSTED_VLM_SECONDS_PER_VIDEO / 3600
    local_hours = plan.total_posts_needed * LOCAL_VLM_SECONDS_PER_VIDEO / 3600

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
        extraction_hours_hosted_vlm=round(hosted_hours, 1),
        extraction_hours_local_vlm=round(local_hours, 1),
        notes=[
            "acquisition_usd_zyte is None: docs/alternativas-fase1.md quotes Zyte as a "
            "monthly plan, never as a per-request rate. Not invented here.",
            "vlm_usd is None for the hosted path: the token shape per video is measured "
            "(371 tokens) but no per-token rate is published for this model/provider "
            "pair. The 50-video pilot settles it by measurement.",
            "total_usd_low assumes Data365 acquisition + hosted ASR + local VLM.",
            f"Extraction wall clock, serial: {round(hosted_hours, 1)} h hosted vs "
            f"{round(local_hours, 1)} h local. Measured per-video times, not a target.",
            "The dominant real cost is not dollars, it is the "
            f"{round(labeling_hours, 1)} person-hours of human labelling needed for the "
            "golden set that makes the VLM's hook_type trustworthy.",
            "Video file bytes (download bandwidth) are excluded: a few GB, immaterial.",
        ],
    )
