"""Reel badges «En ascenso» and «Top 10 % de tu rubro» — RF-09 of the reels-filter epic
(m-25119466, under m-24872324; design in `docs/epica-filtrado-reels.md`).

`reel_badges(tenant_id, reels)` takes the reels a screen is about to show (the ideas and
«Más reels revisados» of `reviewed_reels`, or any list of `PublicReel`) and returns, per
`(network, reel_id)`, the badges each one earns — each with its provenance. It never
touches `reviewed_reels` (RF-02b and RF-13 work on that file and on the screen): the
screen calls it next to `reviewed_reels(...)`, or through `badges_for_reviewed(...)`.

## «En ascenso» (`BADGE_RISING`)

The lift of `creators/metrics.py` (formula `cm-1`): the reel's views over the MEDIAN views
of its own account's measurable reels. A reel is «En ascenso» when

- its lift is at least `RISING_LIFT` = `reels.LIFT_HIGHLIGHT` = **2.0** — the same bar
  at which the cards paint «x2 sobre su media» in the strong tone and at which
  `metrics.standout` counts a reel as standing out. The bar is the same, the median is
  NOT: today's card figure (`reels.account_lifts`, via `Qualify/reels_ideas_vm.py`) uses
  the run's ~30-day reels, every reel with views (no maturity, no hidden-count filter),
  while the badge uses cm-1's 90-day median of measurable reels. So a card may read
  «x2,4 sobre su media» without «En ascenso», or the reverse. A screen that wants them to
  agree shows `provenance.value` (the badge's lift) instead of the card figure;
- the account's median comes from at least `metrics.MIN_SAMPLE` = **3** measurable
  reels (cm-1: views > 0, counts not hidden, at least `metrics.MATURITY_DAYS` = 3 days
  old when its counters were read — each reel judged at its own `metrics_at`) taken in
  the `RISING_WINDOW_DAYS` = **90** days before `now`; fewer → no badge, never a guess;
- the reel itself was taken in that window and its counts are not hidden (an old reel
  is not «rising»; a young one may be — that is exactly what the badge is for).

## «Top 10 % de tu rubro» (`BADGE_TOP_RUBRO`)

The reel's views against the 90th percentile (`percentile_cont(0.9)`, linear
interpolation — the memory twin computes the same) of the views of every measurable reel
taken in the `TOP_WINDOW_DAYS` = **90** days before `now` by accounts with the SAME
`creators.rubro` (RF-04, 0182). The reel earns it when its views reach that threshold, and
only when:

- its account has a known rubro (`creators.rubro` set and not `otro`) — an account
  without one NEVER shows it;
- when the caller passes `brand_rubros` (the brand's niches, `DiscoverySeed.niches`),
  the account's rubro is one of them: the label says «tu rubro». The screen SHOULD pass
  them; an empty collection means «the brand has no known rubro» and gives no «Top 10 %»
  at all; None (the default, for callers with no brand) compares each account within its
  own rubro;
- the pool holds at least `TOP_MIN_SAMPLE` = **30** reels from at least
  `TOP_MIN_ACCOUNTS` = **3** accounts (below that, «top 10 %» is 3 reels of one
  account, not a rubro); smaller → no badge;
- the reel was taken in the window and its counts are not hidden.

Changing a threshold, a window or a definition = a new `REEL_BADGES_VERSION`.

## Provenance

Every `Badge` carries a `BadgeProvenance`: the source reel `(network, reel_id)` and when
its counters were read (`metrics_at`), the badge formula version (`REEL_BADGES_VERSION`)
and the metrics formula it stands on (`metrics.CREATOR_METRICS_VERSION`), the window, the
sample (reels and accounts compared against), the baseline (account median / rubro
threshold) and the reel's value (lift / views). Nothing is stored: badges are recomputed
from the stored reels on each read, like the cm-1 sheet, so this is their whole
provenance. No migration.

## Free, read-only, tenant-safe

Only what is already stored: `public_reels` and `creators` — both GLOBAL public data of the
networks (0036, 0182), read through `tenant_session` (the sanctioned door). No
ScrapeCreators call, no model call, no write, no `vendor_usage_events` row. No `brand_*`
table is read: which business follows which account never enters the computation, and a
badge's provenance holds counts and figures, never a handle other than the reel's own,
a business or a tenant. The rubro pool is an aggregate over public reels; the same reels
earn the same badges for any business.
"""

from __future__ import annotations

import statistics
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creators import metrics
from qualify_api.creators.region_rubro import account_facts
from qualify_api.referentes.reel_store import _REEL_COLUMNS, PublicReel, _reel
from qualify_api.referentes.reels import LIFT_HIGHLIGHT
from qualify_api.referentes.reviewed_reels import ReviewedReels

#: The badge formula. Bump on any change of a threshold, window or definition below.
REEL_BADGES_VERSION = "rb-1"

BADGE_RISING = "rising"
BADGE_TOP_RUBRO = "top_rubro"
#: What the owner reads, exactly (ticket m-25119466).
LABEL_RISING = "En ascenso"
LABEL_TOP_RUBRO = "Top 10 % de tu rubro"
BADGE_LABELS: dict[str, str] = {BADGE_RISING: LABEL_RISING, BADGE_TOP_RUBRO: LABEL_TOP_RUBRO}

#: «En ascenso»: views at least this many times the account's median (cm-1 lift).
RISING_LIFT = LIFT_HIGHLIGHT
#: The account's reels the median is measured over, and the reels that may earn it.
RISING_WINDOW_DAYS = 90

#: «Top 10 %»: the percentile the reel's views must reach within its rubro.
TOP_PERCENTILE = 0.90
TOP_WINDOW_DAYS = 90
#: A rubro pool smaller than this (reels / distinct accounts) gives no badge.
TOP_MIN_SAMPLE = 30
TOP_MIN_ACCOUNTS = 3
#: The rubro that means «none of the catalog fits»: never a «tu rubro».
RUBRO_OTHER = "otro"

Key = tuple[str, str]


@dataclass(frozen=True)
class BadgeProvenance:
    """Where a badge comes from — enough to recompute it and to know when it would change."""

    #: The source: the reel `(network, reel_id)` and when its counters were read.
    network: str
    reel_id: str
    metrics_at: datetime
    #: The badge formula (`REEL_BADGES_VERSION`) and the metrics one it uses (`cm-1`).
    version: str
    metrics_version: str
    window_days: int
    #: Reels compared against, and how many accounts they belong to.
    sample: int
    accounts: int
    #: Rising: the account's median views. Top: the rubro's views threshold (p90).
    baseline: float
    #: Rising: the reel's lift. Top: the reel's views.
    value: float
    #: Top only: the rubro compared within ('' for rising).
    rubro: str = ""


@dataclass(frozen=True)
class Badge:
    key: str  # BADGE_RISING | BADGE_TOP_RUBRO
    label: str  # exactly what the screen shows
    provenance: BadgeProvenance


@dataclass(frozen=True)
class RubroPool:
    """The views threshold of one rubro over its window, and the sample behind it."""

    rubro: str
    threshold: float
    sample: int
    accounts: int


class ReelBadgeStore(Protocol):
    def account_reels(
        self, tenant_id: UUID, accounts: Sequence[Key], *, since: datetime, until: datetime
    ) -> list[PublicReel]:
        """Every stored reel of `accounts` taken in `[since, until]`."""
        ...

    def account_rubros(self, tenant_id: UUID, accounts: Sequence[Key]) -> dict[Key, str]:
        """`(network, handle) → creators.rubro` ('' or absent = unknown)."""
        ...

    def rubro_pools(
        self, tenant_id: UUID, rubros: Sequence[str], *, since: datetime, until: datetime
    ) -> dict[str, RubroPool]:
        """Per rubro, the `TOP_PERCENTILE` of the views of the measurable reels taken in
        `[since, until]` by accounts of that rubro, with the sample size."""
        ...


# --------------------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------------------


def _read(reel: PublicReel) -> metrics.ReelRead:
    return metrics.ReelRead(
        reel_id=reel.reel_id,
        url="",
        taken_at=reel.taken_at,
        duration_s=reel.duration_s,
        views=reel.views,
        likes=reel.likes,
        comments=reel.comments,
        counts_hidden=reel.counts_hidden,
        is_paid_partnership=reel.is_paid_partnership,
        coauthors=reel.coauthors,
        sound_id=reel.sound_id,
        sound_title=reel.sound,
        sound_is_original=reel.sound_is_original,
    )


def is_measurable(reel: PublicReel) -> bool:
    """cm-1's measurable reel, judged at the time its own counters were read."""
    return metrics.is_measurable(_read(reel), reel.metrics_at)


def account_median(reels: Iterable[PublicReel]) -> metrics.MetricValue:
    """cm-1's median views over the measurable ones of one account's `reels`
    (`insufficient` under `metrics.MIN_SAMPLE`)."""
    sample = [r.views or 0 for r in reels if is_measurable(r)]
    if len(sample) < metrics.MIN_SAMPLE:
        return metrics.MetricValue("median_views", None, "insufficient", len(sample))
    return metrics.MetricValue("median_views", float(statistics.median(sample)), "ok", len(sample))


def percentile_cont(values: Sequence[float], fraction: float) -> float:
    """Postgres `percentile_cont(fraction) WITHIN GROUP (ORDER BY v)`: linear
    interpolation between the two closest ranks."""
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def _counted(reel: PublicReel) -> bool:
    """A reel whose own views can be judged: known, positive, not hidden."""
    return not reel.counts_hidden and reel.views is not None and reel.views > 0


def _in_window(reel: PublicReel, since: datetime, until: datetime) -> bool:
    return since <= reel.taken_at <= until


def rising_badge(
    reel: PublicReel, account_reels: Iterable[PublicReel], *, now: datetime
) -> Badge | None:
    """«En ascenso» for `reel`, measured against `account_reels` (its account's stored
    reels; filtered here to the window), or None."""
    since = now - timedelta(days=RISING_WINDOW_DAYS)
    if not _counted(reel) or not _in_window(reel, since, now):
        return None
    own = [
        r
        for r in account_reels
        if (r.network, r.handle) == (reel.network, reel.handle) and _in_window(r, since, now)
    ]
    median = account_median(own)
    value = metrics.lift(_read(reel), median)
    if value is None or median.value is None or value < RISING_LIFT:
        return None
    return Badge(
        key=BADGE_RISING,
        label=LABEL_RISING,
        provenance=BadgeProvenance(
            network=reel.network,
            reel_id=reel.reel_id,
            metrics_at=reel.metrics_at,
            version=REEL_BADGES_VERSION,
            metrics_version=metrics.CREATOR_METRICS_VERSION,
            window_days=RISING_WINDOW_DAYS,
            sample=median.sample,
            accounts=1,
            baseline=median.value,
            value=round(value, 4),
        ),
    )


def usable_rubro(rubro: str | None, brand_rubros: Collection[str] | None) -> str:
    """The account's rubro when it may carry «tu rubro»; '' otherwise."""
    value = (rubro or "").strip()
    if not value or value == RUBRO_OTHER:
        return ""
    if brand_rubros is not None and value not in brand_rubros:
        return ""
    return value


def top_rubro_badge(
    reel: PublicReel, rubro: str, pool: RubroPool | None, *, now: datetime
) -> Badge | None:
    """«Top 10 % de tu rubro» for `reel` of an account of `rubro` ('' = unknown), against
    that rubro's `pool`, or None."""
    since = now - timedelta(days=TOP_WINDOW_DAYS)
    if not rubro or pool is None or pool.rubro != rubro:
        return None
    if pool.sample < TOP_MIN_SAMPLE or pool.accounts < TOP_MIN_ACCOUNTS:
        return None
    if not _counted(reel) or not _in_window(reel, since, now):
        return None
    views = float(reel.views or 0)
    if views < pool.threshold:
        return None
    return Badge(
        key=BADGE_TOP_RUBRO,
        label=LABEL_TOP_RUBRO,
        provenance=BadgeProvenance(
            network=reel.network,
            reel_id=reel.reel_id,
            metrics_at=reel.metrics_at,
            version=REEL_BADGES_VERSION,
            metrics_version=metrics.CREATOR_METRICS_VERSION,
            window_days=TOP_WINDOW_DAYS,
            sample=pool.sample,
            accounts=pool.accounts,
            baseline=round(pool.threshold, 4),
            value=views,
            rubro=rubro,
        ),
    )


def pool_of(rubro: str, reels: Iterable[PublicReel], rubros: Mapping[Key, str]) -> RubroPool | None:
    """The pool of `rubro` over already-windowed `reels` (the memory twin's computation;
    Postgres does the same in SQL)."""
    members = [r for r in reels if rubros.get((r.network, r.handle)) == rubro and is_measurable(r)]
    if not members:
        return None
    return RubroPool(
        rubro=rubro,
        threshold=percentile_cont([float(r.views or 0) for r in members], TOP_PERCENTILE),
        sample=len(members),
        accounts=len({(r.network, r.handle) for r in members}),
    )


# --------------------------------------------------------------------------------------
# stores
# --------------------------------------------------------------------------------------


class MemoryReelBadgeStore:
    """The offline twin: the global public reels and the creators' rubros, like Postgres
    (neither depends on the tenant)."""

    def __init__(
        self, reels: Iterable[PublicReel] = (), rubros: Mapping[Key, str] | None = None
    ) -> None:
        self.reels: dict[Key, PublicReel] = {(r.network, r.reel_id): r for r in reels}
        self.rubros: dict[Key, str] = dict(rubros or {})
        self.calls: list[str] = []

    def account_reels(
        self, tenant_id: UUID, accounts: Sequence[Key], *, since: datetime, until: datetime
    ) -> list[PublicReel]:
        self.calls.append("account_reels")
        wanted = set(accounts)
        return [
            r
            for r in self.reels.values()
            if (r.network, r.handle) in wanted and _in_window(r, since, until)
        ]

    def account_rubros(self, tenant_id: UUID, accounts: Sequence[Key]) -> dict[Key, str]:
        self.calls.append("account_rubros")
        return {key: self.rubros[key] for key in accounts if key in self.rubros}

    def rubro_pools(
        self, tenant_id: UUID, rubros: Sequence[str], *, since: datetime, until: datetime
    ) -> dict[str, RubroPool]:
        self.calls.append("rubro_pools")
        windowed = [r for r in self.reels.values() if _in_window(r, since, until)]
        out: dict[str, RubroPool] = {}
        for rubro in rubros:
            pool = pool_of(rubro, windowed, self.rubros)
            if pool is not None:
                out[rubro] = pool
        return out


_KEYS = "SELECT * FROM unnest(CAST(:nets AS text[]), CAST(:hands AS text[]))"


class PostgresReelBadgeStore:
    """`ReelBadgeStore` over `public_reels` (0020/0125) and `creators` (0036/0182): global
    public tables, read through `tenant_session` like every read of the app."""

    def account_reels(
        self, tenant_id: UUID, accounts: Sequence[Key], *, since: datetime, until: datetime
    ) -> list[PublicReel]:
        if not accounts:
            return []
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT {_REEL_COLUMNS} FROM public_reels "
                    f"WHERE (network, handle) IN ({_KEYS}) "
                    "AND taken_at >= :since AND taken_at <= :until"
                ),
                {
                    "nets": [n for n, _ in accounts],
                    "hands": [h for _, h in accounts],
                    "since": since,
                    "until": until,
                },
            ).all()
        return [_reel(row) for row in rows]

    def account_rubros(self, tenant_id: UUID, accounts: Sequence[Key]) -> dict[Key, str]:
        if not accounts:
            return {}
        # `account_facts` returns the handles as `creators` stores them (normalized);
        # `public_reels.handle` is stored normalized too, so the keys match the reels'.
        with tenant_session(tenant_id) as session:
            facts = account_facts(session, accounts)
        return {key: fact.rubro for key, fact in facts.items()}

    def rubro_pools(
        self, tenant_id: UUID, rubros: Sequence[str], *, since: datetime, until: datetime
    ) -> dict[str, RubroPool]:
        if not rubros:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    "SELECT c.rubro, "
                    "percentile_cont(CAST(:pct AS double precision)) WITHIN GROUP "
                    "(ORDER BY r.views) AS threshold, count(*) AS sample, "
                    "count(DISTINCT (r.network, r.handle)) AS accounts "
                    "FROM public_reels r "
                    "JOIN creators c ON c.network = r.network AND c.handle = r.handle "
                    "WHERE c.rubro = ANY(CAST(:rubros AS text[])) "
                    "AND r.views > 0 AND NOT r.counts_hidden "
                    "AND r.taken_at >= :since AND r.taken_at <= :until "
                    # cm-1 maturity, judged at the time the counters were read
                    "AND r.metrics_at - r.taken_at >= make_interval(days => :maturity) "
                    "GROUP BY c.rubro"
                ),
                {
                    "pct": TOP_PERCENTILE,
                    "rubros": list(rubros),
                    "since": since,
                    "until": until,
                    "maturity": metrics.MATURITY_DAYS,
                },
            ).all()
        return {
            row.rubro: RubroPool(
                rubro=row.rubro,
                threshold=float(row.threshold),
                sample=int(row.sample),
                accounts=int(row.accounts),
            )
            for row in rows
        }


_store: ReelBadgeStore | None = None


def default_store() -> ReelBadgeStore:
    global _store
    if _store is None:
        _store = PostgresReelBadgeStore()
    return _store


# --------------------------------------------------------------------------------------
# the entry points
# --------------------------------------------------------------------------------------


def reel_badges(
    tenant_id: UUID,
    reels: Sequence[PublicReel],
    *,
    brand_rubros: Collection[str] | None = None,
    store: ReelBadgeStore | None = None,
    now: datetime | None = None,
) -> dict[Key, tuple[Badge, ...]]:
    """`(network, reel_id) → its badges` (rising first), for every reel of `reels` that
    earns at least one. Three reads at most, whatever the list's length; free, no write.

    `brand_rubros`: the brand's rubro keys (`DiscoverySeed.niches`); when given, «Top 10 %
    de tu rubro» only goes to accounts of one of them. None = compare each account within
    its own rubro; empty = the brand has no known rubro, so no «Top 10 %»."""
    if not reels:
        return {}
    db = store or default_store()
    moment = now or datetime.now(UTC)
    accounts = sorted({(r.network, r.handle) for r in reels})
    rising_since = moment - timedelta(days=RISING_WINDOW_DAYS)
    by_account: dict[Key, list[PublicReel]] = {}
    for stored in db.account_reels(tenant_id, accounts, since=rising_since, until=moment):
        by_account.setdefault((stored.network, stored.handle), []).append(stored)
    rubros = {
        key: usable_rubro(rubro, brand_rubros)
        for key, rubro in db.account_rubros(tenant_id, accounts).items()
    }
    wanted = sorted({rubro for rubro in rubros.values() if rubro})
    pools = (
        db.rubro_pools(
            tenant_id,
            wanted,
            since=moment - timedelta(days=TOP_WINDOW_DAYS),
            until=moment,
        )
        if wanted
        else {}
    )
    out: dict[Key, tuple[Badge, ...]] = {}
    for reel in reels:
        account = (reel.network, reel.handle)
        rubro = rubros.get(account, "")
        earned = [
            badge
            for badge in (
                rising_badge(reel, by_account.get(account, ()), now=moment),
                top_rubro_badge(reel, rubro, pools.get(rubro), now=moment),
            )
            if badge is not None
        ]
        if earned:
            out[(reel.network, reel.reel_id)] = tuple(earned)
    return out


def badges_for_reviewed(
    tenant_id: UUID,
    reviewed: ReviewedReels,
    *,
    brand_rubros: Collection[str] | None = None,
    store: ReelBadgeStore | None = None,
    now: datetime | None = None,
) -> dict[Key, tuple[Badge, ...]]:
    """`reel_badges` over what `reviewed_reels.reviewed_reels(...)` returned: its
    (filtered) ideas and its page of «Más reels revisados» — only the reels the owner is
    shown, so nothing about another business's reels is ever computed for this one."""
    reels = [idea.reel for idea in reviewed.ideas] + [item.reel for item in reviewed.more]
    return reel_badges(tenant_id, reels, brand_rubros=brand_rubros, store=store, now=now)


def badge_labels(badges: Iterable[Badge]) -> list[str]:
    """What the screen paints, in order."""
    return [badge.label for badge in badges]


__all__ = [
    "BADGE_LABELS",
    "BADGE_RISING",
    "BADGE_TOP_RUBRO",
    "LABEL_RISING",
    "LABEL_TOP_RUBRO",
    "REEL_BADGES_VERSION",
    "RISING_LIFT",
    "RISING_WINDOW_DAYS",
    "RUBRO_OTHER",
    "TOP_MIN_ACCOUNTS",
    "TOP_MIN_SAMPLE",
    "TOP_PERCENTILE",
    "TOP_WINDOW_DAYS",
    "Badge",
    "BadgeProvenance",
    "MemoryReelBadgeStore",
    "PostgresReelBadgeStore",
    "ReelBadgeStore",
    "RubroPool",
    "account_median",
    "badge_labels",
    "badges_for_reviewed",
    "default_store",
    "is_measurable",
    "percentile_cont",
    "pool_of",
    "reel_badges",
    "rising_badge",
    "top_rubro_badge",
    "usable_rubro",
]
