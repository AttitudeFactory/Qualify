"""«Descubrir cuentas nuevas» — free discovery from the shared pool (RF-07a, m-25119467).

Epic m-24872324, `docs/epica-filtrado-reels.md` (cost option B: the shared pool first, a paid
search only afterwards — RF-07b). A business is offered public accounts the pool already
knows (`creators`, fed by every business's searches through `creator_sightings`) that it
has not labeled yet, and the owner may follow one as inspiration (`referente`) or as a
competitor (`competencia`).

## What this module guarantees

- **Free.** Listing and filtering read Postgres only: `creators`, `creator_sightings`,
  `public_reels` (global, migrations 0036 / 0117 / 0182) and the business's own
  `brand_account_labels`. No ScrapeCreators, no Claude, no `vendor_usage_events` row. When
  fewer than `FEW_RESULTS` accounts match, the page says so (`few_results`) and stops:
  RF-07b decides whether to pay.
- **Never reveals other businesses.** The global tables name no tenant (0117's rule); the
  only per-tenant table read is `brand_account_labels`, through `tenant_session` (RLS with
  the `NULLIF(current_setting('app.tenant_id', true), '')::uuid` policy) and filtered to the
  brand. Nothing returned says how many businesses saw or follow an account, nor which
  search terms found it.
- **Never proposes what the brand already labeled** — `referente`, `competencia` and,
  above all, `detractor` (epic decision 3: detractors are out of the epic).
- **Assisted, never autonomous.** `follow_account` is the only write, it needs the owner's
  user id (the click), it only ever writes `referente` / `competencia`, it goes through
  `ReferentesRepository.set_label`, and it is idempotent: a second click, or an account
  that already has any label, leaves the stored label as it is (see `follow_account` for
  the one race it does not close).

## Each fact and where it came from (`*_source`)

- followers — `profile` (a profile read backed the row, `creators.read_at`) or `search`
  (the count a search feed showed); "" when unknown.
- region / rubro — `creators.region_source` / `rubro_source` from RF-04
  (`creators/region_rubro.py`): free sources for the region, the account review for the
  rubro.
- views — `public_reels`: the median views of the account's stored reels that are at least
  `metrics.MATURITY_DAYS` old and show their counts (`metrics.is_measurable`), from
  `metrics.MIN_SAMPLE` reels up; else `sightings`: the average views per post the pool's
  searches saw (`creators.views_seen / posts_seen`, also from `MIN_SAMPLE` posts) — an
  average, not a median, so the screen must say «promedio» for it; else none.
- interaction — `(likes + comments) / views`: the median over the same reels
  (`metrics.engagement_rate`), else the searches' totals when they saw some likes or
  comments (hidden likes read 0, which means unknown); else none.

## Default order (the screen offers no «Ordenar por», epic decision)

1. accounts with both a views figure and an interaction figure first — a proposal the
   owner can judge beats one with blanks;
2. higher interaction — it does not grow with size, so a small local account whose
   audience answers ranks above a large one whose audience does not, which is what a small
   business can learn from;
3. more views, then more followers (unknowns last);
4. how often the pool's searches came across the account (`creator_sightings.times`) — a
   relevance signal; never shown;
5. network, handle — a total order, so pages never repeat or skip an account.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from qualify_api.creators.metrics import MATURITY_DAYS, MIN_SAMPLE
from qualify_api.creators.models import NETWORKS
from qualify_api.referentes.ai import RUBRO_OTHER, RUBROS, normalize_country
from qualify_api.referentes.repository import (
    AccountLabel,
    ReferentesRepository,
    normalize_handle,
)
from qualify_api.tenancy.models import Brand

#: Version of this read (ranking + what each fact means). Bump when either changes.
DISCOVER_VERSION = "discover-accounts-1"

#: Under this many matches the page carries `few_results`, the signal RF-07b reads to
#: decide whether a paid search is worth it. Nothing is paid here.
FEW_RESULTS = 8

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

#: The two labels the owner can give from this list (never `detractor`).
FOLLOW_LABELS: tuple[str, ...] = ("referente", "competencia")
FollowLabel = Literal["referente", "competencia"]

#: Sources of each fact (see the module docstring).
FOLLOWERS_PROFILE = "profile"
FOLLOWERS_SEARCH = "search"
VIEWS_PUBLIC_REELS = "public_reels"
VIEWS_SIGHTINGS = "sightings"

#: Exact client-facing texts (ticket m-25119467, «Criterios de aceptación»).
TITLE = "Descubrir cuentas nuevas"
FOLLOW_AS_INSPIRATION = "Seguir como inspiración"
FOLLOW_AS_COMPETITOR = "Seguir como competidor"
EMPTY_TEXT = "Todavía no encontramos cuentas nuevas con estos filtros."
FOLLOW_BUTTONS: dict[str, str] = {
    "referente": FOLLOW_AS_INSPIRATION,
    "competencia": FOLLOW_AS_COMPETITOR,
}

Key = tuple[str, str]


@dataclass(frozen=True)
class FollowerBand:
    """A followers range, `low <= followers < high` (`high=None`: no ceiling)."""

    key: str
    label: str
    low: int
    high: int | None


FOLLOWER_BANDS: tuple[FollowerBand, ...] = (
    FollowerBand("hasta_10k", "Hasta 10 mil", 0, 10_000),
    FollowerBand("10k_50k", "De 10 mil a 50 mil", 10_000, 50_000),
    FollowerBand("50k_200k", "De 50 mil a 200 mil", 50_000, 200_000),
    FollowerBand("200k_1m", "De 200 mil a 1 millón", 200_000, 1_000_000),
    FollowerBand("mas_1m", "Más de 1 millón", 1_000_000, None),
)
_BANDS_BY_KEY = {band.key: band for band in FOLLOWER_BANDS}


@dataclass(frozen=True)
class DiscoverFilters:
    """What the owner filters by. Empty = no filter on that fact; within one fact the
    values are alternatives (OR), across facts all must hold (AND). A threshold filter
    leaves out the accounts whose figure is unknown."""

    networks: tuple[str, ...] = ()
    follower_bands: tuple[str, ...] = ()
    region_codes: tuple[str, ...] = ()
    rubros: tuple[str, ...] = ()
    min_median_views: int | None = None
    #: A fraction: 0.03 = 3 % interaction.
    min_engagement: float | None = None

    def __post_init__(self) -> None:
        networks = tuple(dict.fromkeys(n.strip().lower() for n in self.networks))
        bad = [n for n in networks if n not in NETWORKS]
        if bad:
            raise ValueError(f"networks must be among {NETWORKS}, got {bad}")
        bands = tuple(dict.fromkeys(self.follower_bands))
        bad = [b for b in bands if b not in _BANDS_BY_KEY]
        if bad:
            raise ValueError(f"unknown follower bands {bad}")
        regions = tuple(dict.fromkeys(normalize_country(r) for r in self.region_codes))
        if "" in regions:
            raise ValueError(f"not a country code among {self.region_codes}")
        rubros = tuple(dict.fromkeys(self.rubros))
        bad = [r for r in rubros if r not in RUBROS]
        if bad:
            raise ValueError(f"rubros must be among {RUBROS}, got {bad}")
        if self.min_median_views is not None and self.min_median_views < 0:
            raise ValueError("min_median_views must be >= 0")
        if self.min_engagement is not None and not (
            math.isfinite(self.min_engagement) and self.min_engagement >= 0
        ):
            raise ValueError("min_engagement must be a finite fraction >= 0")
        object.__setattr__(self, "networks", networks)
        object.__setattr__(self, "follower_bands", bands)
        object.__setattr__(self, "region_codes", regions)
        object.__setattr__(self, "rubros", rubros)


@dataclass(frozen=True)
class DiscoveredAccount:
    """One proposal, with what the owner needs to decide and where each fact came from."""

    network: str
    handle: str
    full_name: str = ""
    avatar_url: str = ""
    profile_url: str = ""
    followers: int | None = None
    followers_source: str = ""
    region_code: str = ""
    region_source: str = ""
    rubro: str = ""
    rubro_source: str = ""
    median_views: float | None = None
    views_source: str = ""
    views_sample: int = 0
    engagement: float | None = None
    engagement_source: str = ""
    engagement_sample: int = 0

    @property
    def key(self) -> Key:
        return (self.network, self.handle)


@dataclass(frozen=True)
class DiscoverPage:
    accounts: tuple[DiscoveredAccount, ...]
    page: int
    page_size: int
    total: int
    #: Fewer than `FEW_RESULTS` accounts match: RF-07b may offer a paid search. Never acted
    #: on here.
    few_results: bool
    version: str = DISCOVER_VERSION

    @property
    def has_more(self) -> bool:
        return (self.page + 1) * self.page_size < self.total


@dataclass(frozen=True)
class FollowResult:
    label: AccountLabel
    #: False when the account already had a label — it was left untouched (idempotent).
    created: bool


@dataclass(frozen=True)
class SuggestedFilters:
    """Starting filters from the brand's own labeled accounts: their most common region
    and rubro. Empty when the brand has none with that fact."""

    region_code: str = ""
    rubro: str = ""


# --------------------------------------------------------------------------------------
# pure rules, shared by both stores
# --------------------------------------------------------------------------------------


def _page_args(page: int, page_size: int) -> tuple[int, int]:
    if page < 0:
        raise ValueError("page must be >= 0")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    return page, page_size


def matches(account: DiscoveredAccount, filters: DiscoverFilters) -> bool:
    if filters.networks and account.network not in filters.networks:
        return False
    if filters.follower_bands:
        if account.followers is None:
            return False
        if not any(
            band.low <= account.followers and (band.high is None or account.followers < band.high)
            for band in (_BANDS_BY_KEY[k] for k in filters.follower_bands)
        ):
            return False
    if filters.region_codes and account.region_code not in filters.region_codes:
        return False
    if filters.rubros and account.rubro not in filters.rubros:
        return False
    if filters.min_median_views is not None and (
        account.median_views is None or account.median_views < filters.min_median_views
    ):
        return False
    return filters.min_engagement is None or (
        account.engagement is not None and account.engagement >= filters.min_engagement
    )


def order_key(account: DiscoveredAccount, seen_times: int = 0) -> tuple[Any, ...]:
    """The default order (module docstring), as an ascending sort key."""
    complete = account.median_views is not None and account.engagement is not None
    return (
        not complete,
        -(account.engagement if account.engagement is not None else -math.inf),
        -(account.median_views if account.median_views is not None else -math.inf),
        -(account.followers if account.followers is not None else -1),
        -seen_times,
        account.network,
        account.handle,
    )


def _check_follow_label(label: str) -> str:
    if label not in FOLLOW_LABELS:
        raise ValueError(f"an owner follows as one of {FOLLOW_LABELS}, got {label!r}")
    return label


def follow_account(
    repo: ReferentesRepository,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    labeled_by: UUID,
    network: str,
    handle: str,
    label: FollowLabel,
) -> FollowResult:
    """«Seguir como inspiración / competidor» — the owner's click, never a job.

    Writes `brand_account_labels` through `ReferentesRepository.set_label`
    (`tenant_session`, RLS, `ON CONFLICT` on `uq_account_label`). Idempotent: when the
    account already carries any label for this brand (the same click twice, another tab,
    or a detractor mark) the stored label is returned as it is and nothing is written.

    The check and the write are two statements (`set_label` upserts and is shared with the
    Referentes wizard, so it is reused as it is): only a label written by the same owner in
    another tab in between those two statements could be replaced. The list never offers
    a labeled account, so that needs two screens racing on the same account."""
    if labeled_by is None:
        raise ValueError("following an account needs the owner who clicked")
    chosen = _check_follow_label(label)
    net = network.strip().lower()
    if net not in NETWORKS:
        raise ValueError(f"network must be one of {NETWORKS}, got {network!r}")
    hand = normalize_handle(handle)
    for existing in repo.labels(tenant_id=tenant_id, brand_id=brand_id):
        if (existing.network, existing.handle) == (net, hand):
            return FollowResult(label=existing, created=False)
    stored = repo.set_label(
        tenant_id=tenant_id,
        brand_id=brand_id,
        network=net,
        handle=hand,
        label=chosen,
        labeled_by=labeled_by,
    )
    return FollowResult(label=stored, created=True)


def _suggest(facts: Iterable[tuple[str, str]]) -> SuggestedFilters:
    regions: Counter[str] = Counter()
    rubros: Counter[str] = Counter()
    for region, rubro in facts:
        if region:
            regions[region] += 1
        if rubro and rubro != RUBRO_OTHER:
            rubros[rubro] += 1

    def top(counter: Counter[str]) -> str:
        # Most common; ties go to the alphabetically first, so the suggestion is stable.
        return min(counter, key=lambda v: (-counter[v], v)) if counter else ""

    return SuggestedFilters(region_code=top(regions), rubro=top(rubros))


# --------------------------------------------------------------------------------------
# stores
# --------------------------------------------------------------------------------------


class DiscoverStore(Protocol):
    def page(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        filters: DiscoverFilters,
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
        now: datetime | None = None,
    ) -> DiscoverPage:
        """The brand's proposals, filtered, in the default order. Raises `ValueError` for
        a brand the tenant does not own."""
        ...

    def suggested_filters(self, *, tenant_id: UUID, brand_id: UUID) -> SuggestedFilters: ...


@dataclass
class MemoryDiscoverStore:
    """Offline twin of `PostgresDiscoverStore`: a pool of accounts whose facts are already
    derived, and the labels of a `ReferentesRepository` (so a follow hides the account)."""

    labels_repo: ReferentesRepository
    pool: list[DiscoveredAccount] = field(default_factory=list)
    seen_times: dict[Key, int] = field(default_factory=dict)
    private: set[Key] = field(default_factory=set)
    brands: dict[UUID, UUID] = field(default_factory=dict)  # brand → tenant

    def add(self, account: DiscoveredAccount, *, seen_times: int = 0) -> None:
        account = replace(account, handle=normalize_handle(account.handle))
        self.pool = [a for a in self.pool if a.key != account.key] + [account]
        self.seen_times[account.key] = seen_times

    def _check_brand(self, tenant_id: UUID, brand_id: UUID) -> None:
        if self.brands.get(brand_id) != tenant_id:
            raise ValueError("brand not found for this tenant")

    def _labeled(self, tenant_id: UUID, brand_id: UUID) -> set[Key]:
        return {
            (label.network, label.handle)
            for label in self.labels_repo.labels(tenant_id=tenant_id, brand_id=brand_id)
        }

    def page(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        filters: DiscoverFilters,
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
        now: datetime | None = None,
    ) -> DiscoverPage:
        page, page_size = _page_args(page, page_size)
        self._check_brand(tenant_id, brand_id)
        labeled = self._labeled(tenant_id, brand_id)
        found = sorted(
            (
                a
                for a in self.pool
                if a.key not in labeled and a.key not in self.private and matches(a, filters)
            ),
            key=lambda a: order_key(a, self.seen_times.get(a.key, 0)),
        )
        start = page * page_size
        return DiscoverPage(
            accounts=tuple(found[start : start + page_size]),
            page=page,
            page_size=page_size,
            total=len(found),
            few_results=len(found) < FEW_RESULTS,
        )

    def suggested_filters(self, *, tenant_id: UUID, brand_id: UUID) -> SuggestedFilters:
        self._check_brand(tenant_id, brand_id)
        followed = {
            (label.network, label.handle)
            for label in self.labels_repo.labels(tenant_id=tenant_id, brand_id=brand_id)
            if label.label in FOLLOW_LABELS
        }
        return _suggest((a.region_code, a.rubro) for a in self.pool if a.key in followed)


#: The whole read in one statement, filtered as early as possible: `candidates` applies the
#: owner's filters on `creators`' own columns (index `ix_creators_region_rubro`) and drops
#: the brand's labeled accounts, and only those accounts' reels and sightings are
#: aggregated. `:brand_id` filters the brand's labels; RLS on `brand_account_labels`
#: already limits them to the session's tenant. The global tables are read only as
#: aggregates per account — nothing per tenant comes out of them.
_POOL_SQL = """
WITH candidates AS (
    SELECT c.*
    FROM creators c
    WHERE NOT c.is_private AND NOT c.missing AND {base_where}
      AND NOT EXISTS (
          SELECT 1 FROM brand_account_labels l
          WHERE l.brand_id = :brand_id AND l.network = c.network AND l.handle = c.handle
      )
),
reel_stats AS (
    SELECT r.network, r.handle,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY r.views::float8) AS median_views,
           count(*) AS views_sample,
           percentile_cont(0.5) WITHIN GROUP (
               ORDER BY (coalesce(r.likes, 0) + coalesce(r.comments, 0))::float8 / r.views
           ) FILTER (WHERE r.likes IS NOT NULL) AS engagement,
           count(*) FILTER (WHERE r.likes IS NOT NULL) AS engagement_sample
    FROM public_reels r
    JOIN candidates c ON c.network = r.network AND c.handle = r.handle
    WHERE r.views > 0 AND NOT r.counts_hidden AND r.taken_at <= :mature_before
    GROUP BY r.network, r.handle
),
seen AS (
    SELECT s.network, s.handle, sum(s.times) AS seen_times
    FROM creator_sightings s
    JOIN candidates c ON c.network = s.network AND c.handle = s.handle
    GROUP BY s.network, s.handle
),
pool AS (
    SELECT c.network, c.handle, c.full_name, c.avatar_url, c.profile_url, c.followers,
           CASE WHEN c.followers IS NULL THEN ''
                WHEN c.read_at IS NOT NULL THEN :followers_profile
                ELSE :followers_search END AS followers_source,
           c.region_code, c.region_source, c.rubro, c.rubro_source,
           CASE WHEN rs.views_sample >= :min_sample THEN rs.median_views
                WHEN {seen_views} THEN c.views_seen::float8 / c.posts_seen END AS median_views,
           CASE WHEN rs.views_sample >= :min_sample THEN :views_reels
                WHEN {seen_views} THEN :views_sightings
                ELSE '' END AS views_source,
           CASE WHEN rs.views_sample >= :min_sample THEN rs.views_sample
                WHEN {seen_views} THEN c.posts_seen
                ELSE 0 END AS views_sample,
           CASE WHEN rs.engagement_sample >= :min_sample THEN rs.engagement
                WHEN {seen_engagement}
                     THEN (c.likes_seen + c.comments_seen)::float8 / c.views_seen END
               AS engagement,
           CASE WHEN rs.engagement_sample >= :min_sample THEN :views_reels
                WHEN {seen_engagement} THEN :views_sightings
                ELSE '' END AS engagement_source,
           CASE WHEN rs.engagement_sample >= :min_sample THEN rs.engagement_sample
                WHEN {seen_engagement} THEN c.posts_seen
                ELSE 0 END AS engagement_sample,
           coalesce(s.seen_times, 0) AS seen_times
    FROM candidates c
    LEFT JOIN reel_stats rs ON rs.network = c.network AND rs.handle = c.handle
    LEFT JOIN seen s ON s.network = c.network AND s.handle = c.handle
)
"""

#: The searches' figures count once enough posts were seen with views; their interaction
#: only when some likes or comments were seen too (Instagram hides likes: a 0 there means
#: «unknown», not «nobody answers»).
_SEEN_VIEWS = "(c.posts_seen >= :min_sample AND c.views_seen > 0)"
_SEEN_ENGAGEMENT = (
    "(c.posts_seen >= :min_sample AND c.views_seen > 0 AND c.likes_seen + c.comments_seen > 0)"
)

# Handles compare byte-wise (COLLATE "C"), as Python's `str` order in `order_key` does.
_PAGE_SQL = """
SELECT network, handle, full_name, avatar_url, profile_url, followers, followers_source,
       region_code, region_source, rubro, rubro_source, median_views, views_source,
       views_sample, engagement, engagement_source, engagement_sample,
       count(*) OVER () AS total
FROM pool
WHERE {derived_where}
ORDER BY (median_views IS NOT NULL AND engagement IS NOT NULL) DESC,
         engagement DESC NULLS LAST, median_views DESC NULLS LAST,
         followers DESC NULLS LAST, seen_times DESC,
         network COLLATE "C", handle COLLATE "C"
LIMIT :limit OFFSET :offset
"""

_COUNT_SQL = "SELECT count(*) FROM pool WHERE {derived_where}"


def _where(filters: DiscoverFilters) -> tuple[str, str, dict[str, Any]]:
    """The filters as SQL — the same rules as `matches`: the ones on `creators`' own
    columns (applied in `candidates`) and the ones on derived figures (over `pool`)."""
    base: list[str] = ["TRUE"]
    derived: list[str] = ["TRUE"]
    params: dict[str, Any] = {}
    if filters.networks:
        base.append("c.network = ANY(:f_networks)")
        params["f_networks"] = list(filters.networks)
    if filters.follower_bands:
        bands = []
        for i, key in enumerate(filters.follower_bands):
            band = _BANDS_BY_KEY[key]
            params[f"f_low{i}"] = band.low
            if band.high is None:
                bands.append(f"c.followers >= :f_low{i}")
            else:
                params[f"f_high{i}"] = band.high
                bands.append(f"(c.followers >= :f_low{i} AND c.followers < :f_high{i})")
        base.append("(" + " OR ".join(bands) + ")")
    if filters.region_codes:
        base.append("c.region_code = ANY(:f_regions)")
        params["f_regions"] = list(filters.region_codes)
    if filters.rubros:
        base.append("c.rubro = ANY(:f_rubros)")
        params["f_rubros"] = list(filters.rubros)
    if filters.min_median_views is not None:
        derived.append("median_views >= :f_min_views")
        params["f_min_views"] = filters.min_median_views
    if filters.min_engagement is not None:
        derived.append("engagement >= :f_min_engagement")
        params["f_min_engagement"] = filters.min_engagement
    return " AND ".join(base), " AND ".join(derived), params


def _pool_sql(base_where: str) -> str:
    return _POOL_SQL.format(
        base_where=base_where, seen_views=_SEEN_VIEWS, seen_engagement=_SEEN_ENGAGEMENT
    )


def _brand_owned(session: Session, tenant_id: UUID, brand_id: UUID) -> bool:
    # `brands` is RLS-scoped: under `tenant_session` another tenant's brand is not there.
    return (
        session.scalar(select(Brand.id).where(Brand.id == brand_id, Brand.tenant_id == tenant_id))
        is not None
    )


def _account(row: Any) -> DiscoveredAccount:
    return DiscoveredAccount(
        network=row.network,
        handle=row.handle,
        full_name=row.full_name,
        avatar_url=row.avatar_url,
        profile_url=row.profile_url,
        followers=row.followers,
        followers_source=row.followers_source,
        region_code=row.region_code,
        region_source=row.region_source,
        rubro=row.rubro,
        rubro_source=row.rubro_source,
        median_views=None if row.median_views is None else float(row.median_views),
        views_source=row.views_source,
        views_sample=int(row.views_sample),
        engagement=None if row.engagement is None else float(row.engagement),
        engagement_source=row.engagement_source,
        engagement_sample=int(row.engagement_sample),
    )


def discover_page_in(
    session: Session,
    *,
    brand_id: UUID,
    filters: DiscoverFilters,
    page: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    now: datetime | None = None,
) -> DiscoverPage:
    """`PostgresDiscoverStore.page` inside a session the caller opened with
    `tenant_session` (the brand check is the caller's)."""
    page, page_size = _page_args(page, page_size)
    base_where, derived_where, params = _where(filters)
    pool = _pool_sql(base_where)
    moment = now or datetime.now(UTC)
    params.update(
        brand_id=brand_id,
        mature_before=moment - timedelta(days=MATURITY_DAYS),
        min_sample=MIN_SAMPLE,
        followers_profile=FOLLOWERS_PROFILE,
        followers_search=FOLLOWERS_SEARCH,
        views_reels=VIEWS_PUBLIC_REELS,
        views_sightings=VIEWS_SIGHTINGS,
        limit=page_size,
        offset=page * page_size,
    )
    rows = session.execute(text(pool + _PAGE_SQL.format(derived_where=derived_where)), params).all()
    if rows:
        total = int(rows[0].total)
    elif page == 0:
        total = 0
    else:
        # Past the last page: the window count is gone with the rows; count once more.
        sql = pool + _COUNT_SQL.format(derived_where=derived_where)
        total = int(session.scalar(text(sql), params) or 0)
    return DiscoverPage(
        accounts=tuple(_account(r) for r in rows),
        page=page,
        page_size=page_size,
        total=total,
        few_results=total < FEW_RESULTS,
    )


class PostgresDiscoverStore:
    """All access through `tenant_session`: RLS scopes `brand_account_labels` and `brands`;
    the global pool tables are read as per-account aggregates only."""

    def page(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        filters: DiscoverFilters,
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
        now: datetime | None = None,
    ) -> DiscoverPage:
        _page_args(page, page_size)
        with tenant_session(tenant_id) as session:
            if not _brand_owned(session, tenant_id, brand_id):
                raise ValueError("brand not found for this tenant")
            return discover_page_in(
                session, brand_id=brand_id, filters=filters, page=page, page_size=page_size, now=now
            )

    def suggested_filters(self, *, tenant_id: UUID, brand_id: UUID) -> SuggestedFilters:
        with tenant_session(tenant_id) as session:
            if not _brand_owned(session, tenant_id, brand_id):
                raise ValueError("brand not found for this tenant")
            rows = session.execute(
                text(
                    "SELECT c.region_code, c.rubro FROM brand_account_labels l "
                    "JOIN creators c ON c.network = l.network AND c.handle = l.handle "
                    "WHERE l.brand_id = :brand_id AND l.label = ANY(:labels)"
                ),
                {"brand_id": brand_id, "labels": list(FOLLOW_LABELS)},
            ).all()
        return _suggest((r[0], r[1]) for r in rows)


def band_of(followers: int | None) -> str:
    """The band key a followers count falls in ("" when unknown) — for the screen's chip."""
    if followers is None:
        return ""
    for band in FOLLOWER_BANDS:
        if band.low <= followers and (band.high is None or followers < band.high):
            return band.key
    return ""


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "DISCOVER_VERSION",
    "EMPTY_TEXT",
    "FEW_RESULTS",
    "FOLLOWER_BANDS",
    "FOLLOW_AS_COMPETITOR",
    "FOLLOW_AS_INSPIRATION",
    "FOLLOW_BUTTONS",
    "FOLLOW_LABELS",
    "MAX_PAGE_SIZE",
    "TITLE",
    "DiscoverFilters",
    "DiscoverPage",
    "DiscoverStore",
    "DiscoveredAccount",
    "FollowResult",
    "FollowerBand",
    "MemoryDiscoverStore",
    "PostgresDiscoverStore",
    "SuggestedFilters",
    "band_of",
    "discover_page_in",
    "follow_account",
    "matches",
    "order_key",
]
