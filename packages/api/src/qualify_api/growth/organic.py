"""Organic growth, estimated from the outside.

"Organic" here means growth that is NOT bought: no ads, no boosted posts, no paid
followers. No vendor can tell that apart for a third-party account — only the
account's own Insights can — so this is an estimate built on one observable fact:
organic followers come from organic interactions. Followers that a creator's content
cannot explain are the non-organic candidate.

The formula (`docs/crecimiento-organico-estimacion.md` has the long version):

    dF        = F(t1) - F(t0)                        net followers gained in the window
    I_org     = sum of interactions gained on posts NOT flagged as pushed
    k         = median( g_i / I_i ) over clean intervals      followers per interaction
    G_org     = min(dF+, k * I_org)                   growth the content explains
    G_unexp   = dF+ - G_org                           growth nothing organic explains
    S_org     = G_org / dF+                           organic share   (0..1)
    OGR       = G_org / F(t0)                         organic growth rate over the window

A post is "pushed" (paid reach suspected) when any of: it carries a paid label; its
reach is far above the creator's median while its engagement per view is far below
(ads deliver views, not likes); or most of its views arrived after its first 72 h
while the creator's posts usually peak inside them (a boost run later). Interactions
on pushed posts do not count as organic.

Limits, stated: unlabeled ads with healthy engagement pass as organic; a spike from
outside the platform (TV, a mention elsewhere) counts as unexplained. The estimate
carries a confidence (series length x posts with two reads) and says where `k` came
from (the creator's own series, or a reference when it is too short).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from qualify_api.growth.repository import FollowerPoint, PostRead

#: Reach outlier x engagement deficit = a pushed post: views over `REACH_OUTLIER` times
#: the creator's median AND engagement per view under `ENGAGEMENT_DEFICIT` of it.
REACH_OUTLIER = 3.0
ENGAGEMENT_DEFICIT = 0.4
#: A post whose views mostly arrived after its first 72 h, for a creator whose posts
#: usually peak inside them: a boost run later.
LATE_WAVE_HOURS = 72
LATE_WAVE_SHARE = 0.5
LATE_WAVE_USUAL = 0.2
#: Followers per interaction when the creator's own series cannot say (too short):
#: a reference, not a measurement — the estimate says so (`k_from = "referencia"`).
REFERENCE_K = 0.03
REFERENCE_ER = 0.03
K_BOUNDS = (0.002, 0.3)
#: Enough history to trust the creator's own `k` and the whole estimate.
MIN_CLEAN_INTERVALS = 3
FULL_CONFIDENCE_DAYS = 14
FULL_CONFIDENCE_POSTS = 5
MIN_POSTS_FOR_OWN_MEDIANS = 3


@dataclass(frozen=True)
class Reference:
    """Where `k` and the engagement baseline come from when the series is short: the
    sector's referentes (the Brand Kit's own search) or a default."""

    k: float = REFERENCE_K
    engagement_per_view: float = REFERENCE_ER


@dataclass(frozen=True)
class PostVerdict:
    post_id: str
    views: int
    interactions: int
    interactions_gained: int
    engagement_per_view: float | None
    late_wave_share: float | None
    pushed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class OrganicEstimate:
    start: datetime
    end: datetime
    followers_start: int
    followers_end: int
    delta: int
    organic: int
    unexplained: int
    organic_share: float | None
    organic_rate: float | None
    k: float
    k_from: str  # "serie" | "referencia"
    interactions_organic: int
    interactions_pushed: int
    pushed_reach_share: float | None
    confidence: float
    posts: tuple[PostVerdict, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def _by_post(posts: Iterable[PostRead]) -> dict[str, list[PostRead]]:
    grouped: dict[str, list[PostRead]] = {}
    for read in posts:
        grouped.setdefault(read.post_id, []).append(read)
    for reads in grouped.values():
        reads.sort(key=lambda r: r.fetched_at)
    return grouped


def _gained(reads: Sequence[PostRead], start: datetime, end: datetime) -> int:
    """Interactions the post gained inside `(start, end]`: its last read at or before
    `end` minus its last read at or before `start` (nothing before the window = all of
    it). Half-open so a read landing exactly on a follower point belongs to one
    interval, never to two."""
    before = [r for r in reads if r.fetched_at <= start]
    inside = [r for r in reads if start < r.fetched_at <= end]
    if not inside:
        return 0
    base = before[-1].interactions if before else 0
    return max(inside[-1].interactions - base, 0)


def _late_wave(reads: Sequence[PostRead]) -> float | None:
    """Share of the post's views that arrived after its first `LATE_WAVE_HOURS` — needs
    a read at or after that mark and a later one."""
    taken = reads[0].taken_at
    mark = taken + timedelta(hours=LATE_WAVE_HOURS)
    at_mark = next((r for r in reads if r.fetched_at >= mark and r.views is not None), None)
    last = reads[-1]
    if at_mark is None or last is at_mark or last.views is None or last.views <= 0:
        return None
    return max(last.views - (at_mark.views or 0), 0) / last.views


def _verdicts(
    grouped: dict[str, list[PostRead]],
    start: datetime,
    end: datetime,
    paid: set[str],
    reference: Reference,
) -> list[PostVerdict]:
    facts: list[tuple[str, int, int, int, float | None, float | None]] = []
    for post_id, reads in grouped.items():
        last = reads[-1]
        views = last.views or 0
        interactions = last.interactions
        er = interactions / views if views > 0 else None
        facts.append(
            (post_id, views, interactions, _gained(reads, start, end), er, _late_wave(reads))
        )

    with_views = [f for f in facts if f[1] > 0]
    own = len(with_views) >= MIN_POSTS_FOR_OWN_MEDIANS
    er_med = (
        median([f[4] for f in with_views if f[4] is not None])
        if own
        else reference.engagement_per_view
    )
    views_med = median([f[1] for f in with_views]) if own else None
    late = [f[5] for f in facts if f[5] is not None]
    late_usual = median(late) if len(late) >= MIN_POSTS_FOR_OWN_MEDIANS else None

    verdicts: list[PostVerdict] = []
    for post_id, views, interactions, gained, er, late_share in facts:
        reasons: list[str] = []
        if post_id in paid:
            reasons.append("etiqueta de contenido pagado")
        if (
            views_med
            and er is not None
            and views > REACH_OUTLIER * views_med
            and er < ENGAGEMENT_DEFICIT * er_med
        ):
            reasons.append("alcance muy alto con interacción muy baja")
        if (
            late_share is not None
            and late_share > LATE_WAVE_SHARE
            and (late_usual is None or late_usual < LATE_WAVE_USUAL)
        ):
            reasons.append("la mayoría de las views llegó después de las primeras 72 h")
        verdicts.append(
            PostVerdict(
                post_id, views, interactions, gained, er, late_share, bool(reasons), tuple(reasons)
            )
        )
    return verdicts


def _followers_per_interaction(
    series: Sequence[FollowerPoint],
    grouped: dict[str, list[PostRead]],
    pushed: set[str],
) -> float | None:
    """`k` from the creator's own series: over each interval between two follower
    points where no pushed post gained anything ("clean"), followers gained per
    organic interaction gained; the median of those, or None with too few."""
    ratios: list[float] = []
    for a, b in zip(series, series[1:]):
        organic = 0
        dirty = False
        for post_id, reads in grouped.items():
            gained = _gained(reads, a.at, b.at)
            if gained <= 0:
                continue
            if post_id in pushed:
                dirty = True
                break
            organic += gained
        if dirty or organic <= 0:
            continue
        gain = b.followers - a.followers
        if gain < 0:
            continue
        ratios.append(gain / organic)
    if len(ratios) < MIN_CLEAN_INTERVALS:
        return None
    return min(max(median(ratios), K_BOUNDS[0]), K_BOUNDS[1])


def estimate_organic_growth(
    followers: Sequence[FollowerPoint],
    posts: Sequence[PostRead],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    paid_post_ids: Iterable[str] = (),
    reference: Reference = Reference(),
) -> OrganicEstimate | None:
    """The estimate over `[start, end]` (default: the whole follower series), or None
    with fewer than two follower points inside it."""
    series = sorted(followers, key=lambda p: p.at)
    if start is not None:
        series = [p for p in series if p.at >= start]
    if end is not None:
        series = [p for p in series if p.at <= end]
    if len(series) < 2:
        return None
    first, last = series[0], series[-1]
    window_start, window_end = first.at, last.at
    paid = set(paid_post_ids)

    grouped = _by_post(p for p in posts if p.fetched_at <= window_end)
    verdicts = _verdicts(grouped, window_start, window_end, paid, reference)
    pushed = {v.post_id for v in verdicts if v.pushed}
    interactions_organic = sum(v.interactions_gained for v in verdicts if not v.pushed)
    interactions_pushed = sum(v.interactions_gained for v in verdicts if v.pushed)

    own_k = _followers_per_interaction(series, grouped, pushed)
    k, k_from = (own_k, "serie") if own_k is not None else (reference.k, "referencia")

    delta = last.followers - first.followers
    positive = max(delta, 0)
    organic = min(positive, round(k * interactions_organic))
    unexplained = positive - organic
    share = (organic / positive) if positive > 0 else None
    rate = (organic / first.followers) if first.followers > 0 else None

    total_views = sum(v.views for v in verdicts)
    pushed_views = sum(v.views for v in verdicts if v.pushed)
    pushed_reach = (pushed_views / total_views) if total_views > 0 else None

    days = (window_end - window_start).total_seconds() / 86400
    twice_read = sum(1 for reads in grouped.values() if len(reads) >= 2)
    confidence = min(1.0, days / FULL_CONFIDENCE_DAYS) * min(
        1.0, twice_read / FULL_CONFIDENCE_POSTS
    )

    notes: list[str] = []
    if k_from == "referencia":
        notes.append(
            "Pocas lecturas limpias: los seguidores por interacción salen de una referencia, "
            "no de esta cuenta."
        )
    if delta < 0:
        notes.append("La cuenta perdió seguidores en el periodo: no hay crecimiento que repartir.")
    if pushed:
        notes.append(f"{len(pushed)} publicación(es) con señales de alcance pagado, excluidas.")
    if confidence < 0.5:
        notes.append("Estimación preliminar: hacen falta más días y más lecturas por publicación.")

    return OrganicEstimate(
        start=window_start,
        end=window_end,
        followers_start=first.followers,
        followers_end=last.followers,
        delta=delta,
        organic=organic,
        unexplained=unexplained,
        organic_share=share,
        organic_rate=rate,
        k=k,
        k_from=k_from,
        interactions_organic=interactions_organic,
        interactions_pushed=interactions_pushed,
        pushed_reach_share=pushed_reach,
        confidence=round(confidence, 3),
        posts=tuple(verdicts),
        notes=tuple(notes),
    )
