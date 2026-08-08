"""Fase D: turning hook features + engagement into a claim that survives scrutiny — or
refusing to make one.

The naive version of this analysis ("group by hook_type, average the likes, sort") is
worse than useless, because it produces a confident, well-formatted, wrong answer. The
dominant driver of likes across accounts is **audience size**, not creative. An account
with 200k followers beats one with 2k on every hook type it happens to use, and a
cross-account average will credit that account's habits.

So the design here is fixed and not optional:

1. **Every account is its own control.** The outcome is a post's **percentile within its
   own account's library**, not its raw likes. Follower count, account age, niche,
   language and posting cadence are account-level constants, and ranking inside the
   account removes all of them at once — without needing to measure any of them.
2. **Optional recency adjustment inside the account.** A library grows with its audience,
   so later posts get more reach for reasons unrelated to the hook. `RECENCY_ADJUSTED`
   regresses engagement rank on date rank within the account and keeps the residual.
3. **A hook type must appear in several accounts to count.** Otherwise "question hooks
   win" can mean "one prolific agent who happens to be good uses question hooks".
4. **Effects ship with a bootstrap interval and a multiple-comparison correction**, and
   the report refuses to call itself conclusive when the corpus cannot support it.

Nothing in this module is a causal claim, and `CorrelationReport` says so in a field that
serializes into every output file. Observational data with no randomisation supports
"posts that opened this way ranked higher within their own accounts" and nothing stronger.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

# --- normal-quantile helper -------------------------------------------------------
# Needed for the power calculations. Implemented here rather than pulled from scipy:
# scipy is not a dependency of this package and adding one for a single inverse CDF is
# not worth the install-size and version-drift cost.

_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)


def inverse_normal_cdf(p: float) -> float:
    """Standard-normal quantile (Acklam's rational approximation, |error| < 1.15e-9).

    Accurate far beyond anything this analysis needs; the point is that the power numbers
    do not depend on a hand-copied z-table with two significant figures.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
        )
    if p > p_high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
        * q
        / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)
    )


# --- inputs -----------------------------------------------------------------------


class Outcome(StrEnum):
    """Which measured quantity is being explained.

    These are not interchangeable columns; each answers a different question, and on a
    corpus of small accounts the difference decides whether there is anything to measure:

    * `VIEWS` — how far the platform distributed the post. On TikTok distribution is
      driven by early retention, which is exactly what a hook buys, so this is the
      outcome closest to the mechanism under study **and** the one with real resolution
      (measured 383-1324 on a candidate account, against likes of 2-14 on the same posts).
    * `ENGAGEMENT` — likes + comments. Closer to stated preference, but on these accounts
      it is a small integer, and small integers make ties, and ties are what a rank test
      has nothing to do with.
    * `ENGAGEMENT_RATE` — engagement / views. Removes the distribution component, at the
      cost of keeping the noisy count in the numerator: at 2 likes, one like is a 50%
      swing. It relocates the integer-noise problem rather than solving it.
    * `POSITIVE_SENTIMENT_RATIO` — needs enough comments per post to be a proportion
      rather than noise (see §D.7); on posts with 0-3 comments it is not usable.
    """

    VIEWS = "views"
    ENGAGEMENT = "engagement"
    ENGAGEMENT_RATE = "engagement_rate"
    POSITIVE_SENTIMENT_RATIO = "positive_sentiment_ratio"


class Normalization(StrEnum):
    RAW = "raw"
    """Raw outcome, pooled across accounts. Present ONLY so the naive analysis can be run
    side by side and shown to disagree. Never report it on its own."""

    WITHIN_ACCOUNT = "within_account"
    """Percentile inside the post's own account library. The default and the honest one."""

    RECENCY_ADJUSTED = "recency_adjusted"
    """Within-account percentile with the account's own growth trend regressed out."""


class PostObservation(BaseModel):
    """One post: its hook, its account, its outcome. The join of the Fase B table with
    whatever metrics the corpus of Fase C brings back."""

    source_id: str
    account_id: str
    hook_type: str
    engagement: float | None = Field(
        default=None, description="likes + comments, or whichever composite is chosen"
    )
    views: float | None = None
    posted_at: date | None = None
    follower_count: int | None = None
    duration_seconds: float | None = None
    positive_sentiment_ratio: float | None = None

    def outcome(self, metric: Outcome) -> float | None:
        """The requested metric, or `None` when it cannot be computed from this row.

        Every branch returns `None` rather than a substitute value. That is the whole
        discipline of this class: a missing metric is missing, and `normalized_outcomes`
        drops it. Imputing 0 would rank an unmeasured post as the worst in its library —
        a confident statement about a post nobody measured.

        `engagement` is optional for the same reason. It is a *composite* of likes and
        comments, so if either component failed to come back, the sum is not "lower", it
        is unknown, and the loader must be able to say so.
        """
        if metric is Outcome.ENGAGEMENT:
            return self.engagement
        if metric is Outcome.VIEWS:
            return self.views
        if metric is Outcome.ENGAGEMENT_RATE:
            # Undefined rather than zero when nobody saw the post: a rate with an empty
            # denominator is not a low rate, it is an absent measurement. Same for an
            # unknown numerator — a rate needs both halves.
            if self.engagement is None or self.views is None or self.views <= 0:
                return None
            return self.engagement / self.views
        return self.positive_sentiment_ratio


# --- viability: is there anything here to explain? ----------------------------------
#
# This runs BEFORE any correlation and can veto it. The design compares hook types by
# ranking posts inside their own account, which needs variance on both sides: spread in
# the outcome, and variety in the hook. A niche that publishes inventory listings on one
# caption template, to accounts whose posts all land within a few likes of each other,
# has neither — and the machinery would still return a tidy table of numbers.
#
# The failure is quiet by construction: `_percentiles` maps a fully tied library to 0.5
# everywhere, so a corpus with no variance produces effects centred exactly on "no
# difference" rather than an error. That is the right behaviour and the wrong thing to
# discover late.

MAX_TIE_FRACTION = 0.5
"""Above this, most within-account pairs are ties and the ranking carries little. Likes in
the 0-17 range on a 30-post library cross it easily; that is the measured worry, not a
hypothetical one."""

MIN_SPAN_COVERAGE = 0.5
"""Achieved span must reach at least this fraction of the requested span before a
*negative* variety finding counts as evidence. Measured case that motivates it: a run
targeting 365 days returned 98 (coverage 0.27) because the picks at both ends of the
window failed and only interior backups survived. A working threshold, not a sourced one."""

MAX_HOOK_TIME_SEPARATION = 0.25
"""Above this, an account's hook types occupy different eras rather than coexisting.

Scale, and it is worth getting right because the obvious threshold is unreachable: each
hook type gets the mean recency-percentile of its posts inside the account, and the
statistic is the gap between the highest and the lowest. Two equally-sized types splitting
the timeline cleanly sit at 0.25 and 0.75 — so **0.5 is the maximum a balanced two-type
account can produce**, not a midpoint, and a threshold of 0.5 would never fire for exactly
the case it was meant to catch. 0 is perfect interleaving. 0.25 is therefore the halfway
mark: past it, the types are more separated than mixed. (Unbalanced groups or more than two
types can exceed 0.5, which is why the statistic is not normalised to it.)

Why it is fatal rather than untidy: date carries follower growth, platform changes and
seasonality, and `Normalization.RECENCY_ADJUSTED` exists to regress exactly that out. If
hook type is collinear with date, removing the time trend removes the hook effect with it —
there is no variance left that belongs to the hook alone. A corpus can therefore show
plenty of hook *variety* and still be unusable, which is not obvious and is why this is
measured rather than assumed.

A working threshold, not a sourced one."""

MIN_DISTINCT_VALUES_PER_ACCOUNT = 5
"""A percentile computed over fewer than five distinct levels is a coarse ordinal grade,
not a ranking, and reporting it as a percentile overstates its precision."""

MIN_POSTS_PER_TYPE_FOR_VARIETY = 2
"""A hook type represented once inside an account cannot be distinguished from that one
post's topic, so it does not count toward the account having variety."""


class OutcomeViability(BaseModel):
    """Whether a corpus can support the Fase D comparison at all, per outcome.

    Deliberately separate from `CorrelationReport`: this answers "is the question
    askable?", not "what is the answer?". A negative verdict here is a real finding —
    it says the niche does not vary enough to study, which saves building a product on an
    effect nobody could have measured.
    """

    outcome: Outcome
    n_posts: int
    n_accounts: int
    n_posts_with_outcome: int
    accounts_with_hook_variety: int
    median_distinct_values_per_account: float
    median_tie_fraction: float
    median_spread_ratio: float | None = Field(
        default=None,
        description="within-account max/min of the outcome; reported, never gated on, "
        "because no defensible threshold exists for it",
    )
    viable: bool
    reasons: list[str]


def assess_viability(
    observations: Sequence[PostObservation],
    metric: Outcome = Outcome.VIEWS,
    max_tie_fraction: float = MAX_TIE_FRACTION,
    min_distinct_values: int = MIN_DISTINCT_VALUES_PER_ACCOUNT,
) -> OutcomeViability:
    """Check that both sides of the comparison actually vary, before comparing anything.

    Note what this does NOT check: whether the corpus is large enough for inference. That
    is `plan_corpus()`'s job and a separate question — a pilot can be perfectly viable in
    the sense measured here and still be far too small to conclude anything.
    """
    by_account: dict[str, list[PostObservation]] = {}
    for obs in observations:
        by_account.setdefault(obs.account_id, []).append(obs)

    tie_fractions: list[float] = []
    distinct_counts: list[float] = []
    spread_ratios: list[float] = []
    accounts_with_variety = 0
    n_with_outcome = 0

    for posts in by_account.values():
        values = [v for v in (p.outcome(metric) for p in posts) if v is not None]
        n_with_outcome += len(values)
        if values:
            distinct = len(set(values))
            distinct_counts.append(float(distinct))
            tie_fractions.append(1.0 - distinct / len(values))
            low = min(values)
            if low > 0:
                spread_ratios.append(max(values) / low)

        counts: dict[str, int] = {}
        for p in posts:
            counts[p.hook_type] = counts.get(p.hook_type, 0) + 1
        if sum(1 for c in counts.values() if c >= MIN_POSTS_PER_TYPE_FOR_VARIETY) >= 2:
            accounts_with_variety += 1

    median_ties = _median(tie_fractions) if tie_fractions else 1.0
    median_distinct = _median(distinct_counts) if distinct_counts else 0.0
    median_spread = _median(spread_ratios) if spread_ratios else None

    reasons: list[str] = []
    if not observations:
        reasons.append("No observations.")
    if n_with_outcome == 0:
        reasons.append(f"No post carries a value for {metric.value}.")
    if median_ties > max_tie_fraction:
        reasons.append(
            f"Outcome is mostly ties: median tie fraction {median_ties:.2f} exceeds "
            f"{max_tie_fraction:.2f}. Within-account ranking has little to order, so "
            f"consider an outcome with more resolution (views over likes)."
        )
    if median_distinct < min_distinct_values:
        reasons.append(
            f"Median of {median_distinct:.1f} distinct outcome values per account is "
            f"below {min_distinct_values}: this is an ordinal grade, not a percentile."
        )
    if accounts_with_variety == 0:
        reasons.append(
            "No account publishes two hook types with at least "
            f"{MIN_POSTS_PER_TYPE_FOR_VARIETY} posts each. With no within-account "
            "variety in the predictor there is nothing to compare, whatever the corpus "
            "size — the accounts publish one template."
        )
    if not reasons:
        reasons.append("Both the outcome and the hook vary enough for the comparison.")

    return OutcomeViability(
        outcome=metric,
        n_posts=len(observations),
        n_accounts=len(by_account),
        n_posts_with_outcome=n_with_outcome,
        accounts_with_hook_variety=accounts_with_variety,
        median_distinct_values_per_account=round(median_distinct, 2),
        median_tie_fraction=round(median_ties, 3),
        median_spread_ratio=round(median_spread, 2) if median_spread is not None else None,
        viable=not any(r for r in reasons if not r.startswith("Both the outcome")),
        reasons=reasons,
    )


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


class AccountTemporalSeparation(BaseModel):
    account_id: str
    n_posts: int
    n_hook_types: int
    separation: float | None = Field(
        default=None,
        description="gap between the highest and lowest mean recency-percentile across "
        "hook types; None when fewer than two types or no dates",
    )
    earliest: date | None = None
    latest: date | None = None
    span_days: int | None = None


class TemporalConfounding(BaseModel):
    """Whether an account's hook variety coexists or merely succeeded itself.

    This is the question a sampling strategy decides and cannot answer. Sampling evenly
    across a four-year catalogue maximises the *variety* you observe, and simultaneously
    maximises the chance that the variety is drift — the account's 2022 style versus its
    2026 style. Drift-variety looks identical to repertoire-variety in a frequency table
    and is worthless to the design.
    """

    accounts: list[AccountTemporalSeparation]
    max_separation: float | None
    median_separation: float | None
    hook_type_is_confounded_with_time: bool
    min_span_coverage: float | None = Field(
        default=None,
        description="worst achieved_span / requested_span across accounts; None when no "
        "requested span was supplied",
    )
    negative_findings_interpretable: bool = True
    reasons: list[str]


def hook_temporal_separation(
    observations: Sequence[PostObservation],
    max_separation: float = MAX_HOOK_TIME_SEPARATION,
    requested_span_days: int | None = None,
    min_span_coverage: float = MIN_SPAN_COVERAGE,
) -> TemporalConfounding:
    """Measure, per account, how far apart in time the hook types sit.

    Undated posts are ignored rather than assumed contemporaneous, and an account with
    fewer than two dated hook types yields `separation=None` — there is nothing to
    separate, which is not the same as being well mixed.

    `requested_span_days` is what the harvest *asked* for. Supply it, because the harvest
    routinely does not deliver it: a run targeting 365 days can come back with 98 when the
    picks at both ends fail, which at a ~50% per-video failure rate is ordinary rather than
    unlucky. The gap matters asymmetrically, and that asymmetry is the whole point of the
    check:

    * A **positive** variety finding is safe at any span. Variety was observed, so it
      exists — a wider sample could only have found more.
    * A **negative** variety finding is only interpretable if the span was actually
      covered. A hook type the account used solely in the months that went missing is
      simply absent from the corpus, and the gate would read that as "this account does not
      vary" when it does.

    Since the pilot exists to falsify the pessimistic hypothesis, an uninterpretable
    negative is its worst possible outcome — it looks like a decisive answer and is not.
    """
    by_account: dict[str, list[PostObservation]] = defaultdict(list)
    for obs in observations:
        if obs.posted_at is not None:
            by_account[obs.account_id].append(obs)

    rows: list[AccountTemporalSeparation] = []
    for account_id, posts in sorted(by_account.items()):
        recency = _percentiles([float(p.posted_at.toordinal()) for p in posts])  # type: ignore[union-attr]
        per_type: dict[str, list[float]] = defaultdict(list)
        for post, pct in zip(posts, recency):
            per_type[post.hook_type].append(pct)
        means = [sum(v) / len(v) for v in per_type.values()]
        dates = [p.posted_at for p in posts if p.posted_at is not None]
        rows.append(
            AccountTemporalSeparation(
                account_id=account_id,
                n_posts=len(posts),
                n_hook_types=len(per_type),
                separation=(max(means) - min(means)) if len(means) >= 2 else None,
                earliest=min(dates) if dates else None,
                latest=max(dates) if dates else None,
                span_days=((max(dates) - min(dates)).days if dates else None),
            )
        )

    separations = [r.separation for r in rows if r.separation is not None]
    worst = max(separations) if separations else None
    middle = _median(separations) if separations else None

    reasons: list[str] = []
    confounded = worst is not None and worst > max_separation
    if not separations:
        reasons.append(
            "No account has two dated hook types, so temporal confounding cannot be "
            "assessed. This is not evidence of absence."
        )
    elif confounded:
        reasons.append(
            f"Hook type separates in time (max separation {worst:.2f} > {max_separation:.2f}): "
            "the account changed style rather than alternating styles. Hook type is standing "
            "in for date, and the recency adjustment would remove the effect along with the "
            "trend. Narrow the sampling window before collecting more."
        )
    else:
        reasons.append(
            f"Hook types coexist in time (max separation {worst:.2f}); variety is repertoire, "
            "not drift."
        )

    coverage: float | None = None
    interpretable = True
    if requested_span_days is not None and requested_span_days > 0:
        spans = [r.span_days for r in rows if r.span_days is not None]
        if spans:
            coverage = min(spans) / requested_span_days
            if coverage < min_span_coverage:
                interpretable = False
                reasons.append(
                    f"Achieved span covers only {coverage:.0%} of the {requested_span_days}-day "
                    f"window requested. A NEGATIVE variety finding is not interpretable here — a "
                    "hook type used only in the missing months would be absent from the corpus "
                    "and would read as 'this account does not vary'. A positive finding is "
                    "unaffected: variety observed is variety that exists."
                )

    return TemporalConfounding(
        accounts=rows,
        max_separation=worst,
        median_separation=middle,
        hook_type_is_confounded_with_time=confounded,
        min_span_coverage=round(coverage, 3) if coverage is not None else None,
        negative_findings_interpretable=interpretable,
        reasons=reasons,
    )


# --- normalization ----------------------------------------------------------------


def _percentiles(values: Sequence[float]) -> list[float]:
    """Mid-rank percentile in [0, 1]. Ties share their average rank, so a library of
    identical values maps to 0.5 everywhere rather than to an arbitrary order."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return [(r + 0.5) / n for r in ranks]


def normalized_outcomes(
    observations: Sequence[PostObservation],
    metric: Outcome = Outcome.ENGAGEMENT,
    normalization: Normalization = Normalization.WITHIN_ACCOUNT,
) -> dict[str, float]:
    """Map `source_id -> normalized outcome`. Posts with a missing outcome are dropped
    (not imputed): an absent metric is missing data, and filling it in would manufacture
    observations that never happened."""
    usable = [o for o in observations if o.outcome(metric) is not None]
    if normalization is Normalization.RAW:
        return {o.source_id: float(o.outcome(metric) or 0.0) for o in usable}

    by_account: dict[str, list[PostObservation]] = defaultdict(list)
    for obs in usable:
        by_account[obs.account_id].append(obs)

    result: dict[str, float] = {}
    for posts in by_account.values():
        values = [float(p.outcome(metric) or 0.0) for p in posts]
        pcts = _percentiles(values)
        if normalization is Normalization.RECENCY_ADJUSTED:
            pcts = _remove_recency_trend(posts, pcts)
        for post, pct in zip(posts, pcts):
            result[post.source_id] = pct
    return result


_RESIDUAL_NOISE_FLOOR = 1e-9
"""Residual spread below this is floating-point dust from a perfect linear fit, not signal.
Percentile ranking is scale-free, so without this floor a spread of 1e-16 becomes a
full-range ordering indistinguishable from a real one."""

MAX_RESIDUAL_TREND = 0.2
"""Above this |Spearman| between recency and the *adjusted* outcome, detrending did not
work and must not be reported as if it had. A working threshold, not a sourced one."""


_MIN_POSTS_FOR_ERA_CHECK = 6
"""Three eras need at least two posts each to have a mean worth comparing."""


class DetrendCheck(BaseModel):
    """Did `RECENCY_ADJUSTED` actually remove the time trend, or merely dent it?

    `_remove_recency_trend` fits a linear trend **on ranks**, and that detail decides what
    it can and cannot absorb. Because ranks are involved, *any* monotone trend — steady
    growth, a one-off step up after a viral post, a policy change that lifted reach — is
    perfectly linear in rank space and comes out completely.

    What survives is **non-monotone** drift: an account that grew and then declined, or one
    that peaked mid-catalogue. In ranks that is a curve, a straight line barely touches it,
    and the adjusted numbers still carry the confounder while looking corrected. That shape
    is the realistic one on a multi-year catalogue, which is exactly the sample a
    full-catalogue spread produces.

    On a corpus sampled across several years this stops being hygiene and becomes
    load-bearing, so it is measured per account rather than assumed.
    """

    accounts_checked: int
    max_era_gap: float | None = Field(
        default=None,
        description="largest difference between era means of the adjusted outcome; ~0 when "
        "detrending worked",
    )
    median_era_gap: float | None = None
    detrending_worked: bool
    reasons: list[str]


def detrend_residual_check(
    observations: Sequence[PostObservation],
    metric: Outcome = Outcome.VIEWS,
    max_residual: float = MAX_RESIDUAL_TREND,
) -> DetrendCheck:
    """Split each account's catalogue into three eras and compare the adjusted outcome.

    After a successful adjustment every era should average ~0.5 — "an average post for its
    account" — so the gap between the highest and lowest era mean is ~0.

    **Why eras and not a correlation with recency.** A rank correlation only sees monotone
    structure, and the residual this check exists to catch is *not* monotone: an account
    that grew and then declined leaves a symmetric U, whose Spearman against recency is
    approximately **zero**. Measuring it that way would have reported a clean bill of
    health for precisely the shape it was built to detect. (It did, in the first version of
    this function.) Comparing era means catches monotone and curved residuals alike.

    A non-zero gap means the account's trend was not linear in ranks, and the honest
    responses are to narrow the sampling window or stratify by period — not to report the
    adjusted figures anyway.
    """
    adjusted = normalized_outcomes(
        observations, metric=metric, normalization=Normalization.RECENCY_ADJUSTED
    )
    by_account: dict[str, list[PostObservation]] = defaultdict(list)
    for obs in observations:
        if obs.posted_at is not None and obs.source_id in adjusted:
            by_account[obs.account_id].append(obs)

    gaps: list[float] = []
    for posts in by_account.values():
        if len(posts) < _MIN_POSTS_FOR_ERA_CHECK:
            continue
        dated = sorted(posts, key=lambda p: p.posted_at)  # type: ignore[arg-type,return-value]
        if len({p.posted_at for p in dated}) < 2:
            # Every post shares one date: no trend to remove and no eras to compare.
            # Skipped rather than scored, so it cannot read as a pass.
            continue
        third = len(dated) // 3
        eras = [dated[:third], dated[third : 2 * third], dated[2 * third :]]
        means = [sum(adjusted[p.source_id] for p in era) / len(era) for era in eras if era]
        if len(means) >= 2:
            gaps.append(max(means) - min(means))

    worst = max(gaps) if gaps else None
    middle = _median(gaps) if gaps else None
    reasons: list[str] = []
    if not gaps:
        reasons.append(
            f"No account has the {_MIN_POSTS_FOR_ERA_CHECK} dated posts needed to compare "
            "eras, so the residual trend could not be checked. Not evidence that it is absent."
        )
        worked = True
    elif worst is not None and worst > max_residual:
        worked = False
        reasons.append(
            f"Residual trend remains after detrending (max era gap {worst:.2f} > "
            f"{max_residual:.2f}). The account's trend is not linear in ranks — narrow the "
            "sampling window or stratify by period rather than reporting the adjusted values."
        )
    else:
        worked = True
        reasons.append(f"Detrending removed the time trend (max era gap {worst:.2f}).")

    return DetrendCheck(
        accounts_checked=len(gaps),
        max_era_gap=worst,
        median_era_gap=middle,
        detrending_worked=worked,
        reasons=reasons,
    )


def _remove_recency_trend(posts: Sequence[PostObservation], pcts: list[float]) -> list[float]:
    """Regress the engagement percentile on the post's recency percentile within the
    account and keep the residual, re-expressed as a percentile.

    Accounts for the single confounder that within-account ranking does NOT remove: an
    account's audience grows over the life of its library, so later posts start ahead.
    Posts with no date are left untouched — the adjustment is skipped for the whole
    account rather than applied to a partially dated library.
    """
    if any(p.posted_at is None for p in posts) or len(posts) < 3:
        return pcts
    recency = _percentiles([p.posted_at.toordinal() for p in posts])  # type: ignore[union-attr]
    mean_x = sum(recency) / len(recency)
    mean_y = sum(pcts) / len(pcts)
    var_x = sum((x - mean_x) ** 2 for x in recency)
    if var_x == 0:
        return pcts
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(recency, pcts)) / var_x
    residuals = [y - (mean_y + slope * (x - mean_x)) for x, y in zip(recency, pcts)]

    # When the trend explains the library completely, the residuals are floating-point
    # noise — spreads of ~1e-16. Percentiling that noise would amplify it into a full 0-1
    # ranking and hand back a confident ordering of nothing, which is worse than the
    # confounder it was removing. An account whose performance is entirely explained by
    # time has no hook signal left, and the honest encoding of that is "every post is
    # average", not an invented order.
    if max(residuals) - min(residuals) <= _RESIDUAL_NOISE_FLOOR:
        return [0.5] * len(residuals)
    return _percentiles(residuals)


# --- statistics ---------------------------------------------------------------------


def spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation. `None` for n < 3 or zero variance — undefined, not zero."""
    if len(xs) != len(ys):
        raise ValueError("xs and ys must be the same length")
    if len(xs) < 3:
        return None
    rx, ry = _percentiles(xs), _percentiles(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def bootstrap_median_ci(
    values: Sequence[float],
    iterations: int = 2000,
    alpha: float = 0.05,
    seed: int = 20260805,
) -> tuple[float, float] | None:
    """Percentile bootstrap interval for the median.

    The median rather than the mean because engagement is heavy-tailed — one viral post
    routinely carries an account's whole distribution, and a mean would report that post's
    hook type as a general finding. The seed is fixed so a report is reproducible.
    """
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    n = len(values)
    medians = []
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        medians.append(_median(sample))
    medians.sort()
    lo = medians[max(0, int((alpha / 2) * iterations) - 1)]
    hi = medians[min(iterations - 1, int((1 - alpha / 2) * iterations))]
    return lo, hi


# --- power / minimum n ---------------------------------------------------------------


def minimum_n_per_group(
    effect_size_d: float,
    power: float = 0.80,
    alpha: float = 0.05,
    rank_based: bool = True,
) -> int:
    """Posts needed **per hook type** to detect a standardized difference of `effect_size_d`.

    Two-sided, two-sample. `rank_based=True` adds the ~5% inflation that a rank test
    (Mann-Whitney) costs relative to a t-test at normal data — this analysis is rank-based
    by design, so the honest budget includes it.
    """
    if effect_size_d <= 0:
        raise ValueError("effect_size_d must be > 0")
    z_alpha = inverse_normal_cdf(1 - alpha / 2)
    z_beta = inverse_normal_cdf(power)
    n = 2 * ((z_alpha + z_beta) / effect_size_d) ** 2
    if rank_based:
        n *= 1.05
    return math.ceil(n)


def minimum_n_for_correlation(rho: float, power: float = 0.80, alpha: float = 0.05) -> int:
    """Posts needed to detect a Spearman correlation of `rho` (Fisher-z, +6% for ranks)."""
    if not 0 < abs(rho) < 1:
        raise ValueError("rho must be in (-1, 1) and non-zero")
    z_alpha = inverse_normal_cdf(1 - alpha / 2)
    z_beta = inverse_normal_cdf(power)
    n = ((z_alpha + z_beta) / math.atanh(abs(rho))) ** 2 + 3
    return math.ceil(n * 1.06)


def bonferroni_alpha(n_comparisons: int, alpha: float = 0.05) -> float:
    """Corrected significance level. With 13 hook types there are 13 one-vs-rest tests, so
    an uncorrected α=0.05 expects ~0.65 false positives per run — and the product would
    report them as findings with a straight face."""
    if n_comparisons < 1:
        raise ValueError("n_comparisons must be >= 1")
    return alpha / n_comparisons


# --- the confounder registry ---------------------------------------------------------


class Confounder(BaseModel):
    name: str
    why_it_matters: str
    handled: str  # "controlled" | "partially" | "uncontrolled"
    how: str


CONFOUNDERS: tuple[Confounder, ...] = (
    Confounder(
        name="follower_count",
        why_it_matters="Reach tracks audience size far more strongly than creative choice.",
        handled="controlled",
        how="Within-account ranking: follower count is ~constant inside one account's library.",
    ),
    Confounder(
        name="account_quality_and_niche",
        why_it_matters="A good agent in a hot market beats a weak one on every hook type.",
        handled="controlled",
        how="Same mechanism — the comparison never crosses accounts.",
    ),
    Confounder(
        name="audience_growth_over_the_library",
        why_it_matters="Later posts get more reach for reasons unrelated to the opening.",
        handled="partially",
        how="RECENCY_ADJUSTED regresses out the within-account time trend, when dates exist.",
    ),
    Confounder(
        name="post_topic_and_property_quality",
        why_it_matters="A spectacular property performs regardless of how the video opens.",
        handled="uncontrolled",
        how="Not measured. Plausibly correlated with hook choice, so effects are inflated.",
    ),
    Confounder(
        name="posting_time_and_platform_algorithm",
        why_it_matters="Distribution changes under you; the same video posted twice differs.",
        handled="uncontrolled",
        how="Not measured, and not measurable from scraped data alone.",
    ),
    Confounder(
        name="video_duration_music_and_caption",
        why_it_matters="All correlate with engagement and with hook style.",
        handled="partially",
        how="duration_seconds is captured and can be checked; music and caption are not.",
    ),
    Confounder(
        name="survivorship_of_the_scraped_library",
        why_it_matters="Deleted underperformers never appear, biasing the corpus upward.",
        handled="uncontrolled",
        how="Unknowable from the outside. Affects every scraped-library study.",
    ),
    Confounder(
        name="hook_type_measurement_error",
        why_it_matters="A VLM that mislabels 20% of hooks attenuates every effect toward zero.",
        handled="uncontrolled",
        how="Requires the human-labelled golden set of §B.4; not yet built.",
    ),
    Confounder(
        name="country_and_address_register",
        why_it_matters=(
            "The corpus spans two countries (Táchira VE / Cúcuta CO). Usted-vs-tú tracks "
            "country, and country carries currency, purchasing power and a different "
            "algorithmic audience — so an effect credited to the hook may be a border."
        ),
        handled="partially",
        how=(
            "Within-account ranking already absorbs it whenever an account is "
            "single-country and single-register, which is the normal case. What it does "
            "NOT absorb is a hook type that is itself register-bound: if usted-speaking "
            "advisors favour command hooks, 'command hooks win' and 'Colombia wins' are "
            "the same claim. second_person_register is recorded per row so this can be "
            "checked rather than assumed — falsification test F5."
        ),
    ),
)
"""Serialized into every report on purpose. A confounder list that lives in a slide gets
dropped when the slide is copied; one that lives in the JSON does not."""


# --- report ---------------------------------------------------------------------------


class HookTypeEffect(BaseModel):
    hook_type: str
    n_posts: int
    n_accounts: int
    median_outcome: float
    ci_low: float | None = None
    ci_high: float | None = None
    meets_min_posts: bool
    meets_min_accounts: bool

    @property
    def separates_from_chance(self) -> bool:
        """Under within-account normalization, 0.5 is 'an average post for its account'.
        An interval containing 0.5 is a non-finding, however pretty the point estimate."""
        if self.ci_low is None or self.ci_high is None:
            return False
        return self.ci_low > 0.5 or self.ci_high < 0.5


class CorrelationReport(BaseModel):
    outcome: Outcome
    normalization: Normalization
    n_posts: int
    n_accounts: int
    min_posts_per_type: int
    min_accounts_per_type: int
    alpha_corrected: float
    effects: list[HookTypeEffect]
    confounders: list[Confounder]
    causal_claim_supported: bool = False
    interpretation: str

    @property
    def conclusive(self) -> bool:
        return any(
            e.meets_min_posts and e.meets_min_accounts and e.separates_from_chance
            for e in self.effects
        )


def hook_type_effects(
    observations: Sequence[PostObservation],
    metric: Outcome = Outcome.ENGAGEMENT,
    normalization: Normalization = Normalization.WITHIN_ACCOUNT,
    min_posts_per_type: int = 30,
    min_accounts_per_type: int = 3,
    alpha: float = 0.05,
) -> CorrelationReport:
    """The whole Fase D analysis, in one call, with its own guard rails attached.

    `min_posts_per_type=30` and `min_accounts_per_type=3` are floors, not targets: see
    `minimum_n_per_group` for what detecting a given effect actually costs. A type that
    misses either floor still appears in the report — suppressed rows are how a corpus
    gets quietly cherry-picked — but carries `meets_min_*: False`, and `conclusive`
    ignores it.
    """
    normalized = normalized_outcomes(observations, metric=metric, normalization=normalization)
    by_type: dict[str, list[float]] = defaultdict(list)
    accounts_by_type: dict[str, set[str]] = defaultdict(set)
    for obs in observations:
        value = normalized.get(obs.source_id)
        if value is None:
            continue
        by_type[obs.hook_type].append(value)
        accounts_by_type[obs.hook_type].add(obs.account_id)

    alpha_corrected = bonferroni_alpha(max(1, len(by_type)), alpha)
    effects: list[HookTypeEffect] = []
    for hook_type, values in sorted(by_type.items()):
        ci = bootstrap_median_ci(values, alpha=alpha_corrected)
        effects.append(
            HookTypeEffect(
                hook_type=hook_type,
                n_posts=len(values),
                n_accounts=len(accounts_by_type[hook_type]),
                median_outcome=_median(values),
                ci_low=ci[0] if ci else None,
                ci_high=ci[1] if ci else None,
                meets_min_posts=len(values) >= min_posts_per_type,
                meets_min_accounts=len(accounts_by_type[hook_type]) >= min_accounts_per_type,
            )
        )

    return CorrelationReport(
        outcome=metric,
        normalization=normalization,
        n_posts=len(normalized),
        n_accounts=len({o.account_id for o in observations}),
        min_posts_per_type=min_posts_per_type,
        min_accounts_per_type=min_accounts_per_type,
        alpha_corrected=alpha_corrected,
        effects=effects,
        confounders=list(CONFOUNDERS),
        causal_claim_supported=False,
        interpretation=(
            "Observational, non-causal. Reads as: 'posts whose opening was typed X ranked "
            "at this percentile within their own account's library'. It does NOT read as "
            "'using hook X causes more engagement' — there is no randomisation and no "
            "counterfactual, and at least three listed confounders are uncontrolled."
        ),
    )
