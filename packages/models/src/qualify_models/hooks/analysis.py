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
    """Which measured quantity is being explained."""

    ENGAGEMENT = "engagement"
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
    engagement: float = Field(description="likes + comments, or whichever composite is chosen")
    posted_at: date | None = None
    follower_count: int | None = None
    duration_seconds: float | None = None
    positive_sentiment_ratio: float | None = None

    def outcome(self, metric: Outcome) -> float | None:
        if metric is Outcome.ENGAGEMENT:
            return self.engagement
        return self.positive_sentiment_ratio


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


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


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
