"""Reviewed reels, filterable — RF-01 of the reels-filter epic (m-25119458, under
m-24872324; design in `docs/epica-filtrado-reels.md`).

Every run already stores Claude's verdict of ~32 reels + 3 per account in
`brand_reel_verdicts` (RLS, never purged), but the screen shows only the run's 6-8 ideas.
This module reads what is already stored and returns, for one brand:

- **the ideas** of the current run (`reel_runs.view`), in their order — R9/R11 unchanged:
  with no filter they are today's list (`view.ideas`) minus any idea whose account is
  labelled `detractor` today; a filter keeps the matching ones in the same order. The
  screen reads `ReviewedReels.ideas`, never `ReviewedReels.view.ideas` (unfiltered);
- **«Más reels revisados»** (`MORE_REVIEWED_TITLE`), paginated: every other reel the
  product check KEPT for the brief the ideas were chosen with, ordered like the ideas
  (views, then likes; no «ordenar por» — decision 2 of the epic).

**Source.** `brand_reel_verdicts` ⨝ `public_reels` ⨝ `brand_account_labels`, never
`brand_reel_ideas` (which only keeps the 6-8). Per reel, only its NEWEST verdict for the
shown run's `brief_hash` counts (a newer transcript or model may have judged it again),
and it must keep the strict product filter: `fits` AND `affinity` in `reels_ai.FITS`
(a verdict stored under an older rule cannot slip in). A brand with no `ok` run has no
brief to judge against, so the list is empty.

**Filters** (`ReelFilters`, every one optional, combinable): channel (Instagram /
TikTok), account kind (`referente` = inspiradores, `competencia` = competidores — decision
1), one or several accounts (network + handle), and duration bucket (<15 s, 15-30 s,
30-60 s, 60 s or more; half-open, so a 15.0 s reel is «15-30»; a reel with no known
duration is left out only when a duration filter is set). **Detractors never appear**
(decision 3): their reels are never returned or counted, and a detractor kind is refused;
an idea whose account is labelled `detractor` today is dropped too.

**Region and niche — the gap, not invented.** `ReelFilters.regions` / `.niches` exist so
RF-02b can wire them, but they are refused (`FilterUnavailable`) while
`REGION_NICHE_READY` is False. The only candidate data today is the global `creators`
row (`country_code`, `category`, migration 0036), whose fill on the brands' accounts is
unmeasured (RF-00, m-25119446) and is not joined here; RF-04 (m-25119461) brings the
region and rubro of each account, with provenance, and turns them on.

**Competidores — a second data gap.** The run reads only `referente` accounts today
(`reels.brand_referentes`), so no verdict exists yet for a `competencia` account: that
kind and those accounts return nothing until RF-05 (m-25119465) reads them. The query
already serves them; nothing here invents them.

**Free and read-only.** Opening the list never calls ScrapeCreators nor Claude, writes
nothing (no `vendor_usage_events` row) and never queues the production reel analyzer,
which only runs over the ideas (`reel_runs._analyze`). The `brand_*` tables are read only
through `tenant_session` (RLS with the NULLIF policy); `public_reels` is global public
data with no policy to scope. No migration: the verdicts are reached through
`uq_brand_reel_verdict` (`brand_id` first), the reels through `uq_public_reel` and the
labels through `uq_account_label`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.referentes import reel_runs, reels_ai
from qualify_api.referentes.reel_runs import RunView
from qualify_api.referentes.reel_store import (
    _REEL_COLUMNS,
    _VERDICT_COLUMNS,
    Idea,
    MemoryReelRunStore,
    PublicReel,
    ReelRunStore,
    StoredVerdict,
    _reel,
    _verdict,
)
from qualify_api.referentes.repository import normalize_handle

#: The heading the owner reads over the second list (exact, ticket m-25119458).
MORE_REVIEWED_TITLE = "Más reels revisados"

NETWORKS = ("instagram", "tiktok")
#: The account kinds the list may show: inspiradores and competidores. `detractor` is
#: never one of them (decision 3 of the epic).
KIND_REFERENTE = "referente"
KIND_COMPETENCIA = "competencia"
ACCOUNT_KINDS = (KIND_REFERENTE, KIND_COMPETENCIA)
KIND_DETRACTOR = "detractor"

#: Duration buckets, in seconds, half-open `[low, high)`; `None` = no upper bound.
DURATION_UNDER_15 = "lt15"
DURATION_15_30 = "15_30"
DURATION_30_60 = "30_60"
DURATION_OVER_60 = "gte60"
DURATION_BUCKETS: dict[str, tuple[float, float | None]] = {
    DURATION_UNDER_15: (0.0, 15.0),
    DURATION_15_30: (15.0, 30.0),
    DURATION_30_60: (30.0, 60.0),
    DURATION_OVER_60: (60.0, None),
}

#: Region and niche need RF-04's per-account data; until then they are refused.
REGION_NICHE_READY = False

PAGE_SIZE = 12
MAX_PAGE_SIZE = 48


class FilterUnavailable(ValueError):
    """A filter whose data does not exist yet (region, niche — RF-04)."""


def _frozen(values: Iterable[str] | None) -> frozenset[str]:
    return frozenset(str(v).strip().lower() for v in (values or ()) if str(v).strip())


@dataclass(frozen=True)
class ReelFilters:
    """What the owner narrowed the list to. Empty = no narrowing on that axis."""

    networks: frozenset[str] = frozenset()
    kinds: frozenset[str] = frozenset()
    #: `(network, handle)` pairs; the handle is normalized (no «@», lowercase).
    accounts: frozenset[tuple[str, str]] = frozenset()
    durations: frozenset[str] = frozenset()
    #: Prepared for RF-04 / RF-02b; refused while `REGION_NICHE_READY` is False.
    regions: frozenset[str] = frozenset()
    niches: frozenset[str] = frozenset()

    @classmethod
    def of(
        cls,
        *,
        networks: Iterable[str] | None = None,
        kinds: Iterable[str] | None = None,
        accounts: Iterable[tuple[str, str]] | None = None,
        durations: Iterable[str] | None = None,
        regions: Iterable[str] | None = None,
        niches: Iterable[str] | None = None,
    ) -> ReelFilters:
        """Build and validate filters from loose values (lists, any case, «@handle»)."""
        return cls(
            networks=_frozen(networks),
            kinds=_frozen(kinds),
            accounts=frozenset(
                (str(network).strip().lower(), normalize_handle(str(handle)))
                for network, handle in (accounts or ())
            ),
            durations=frozenset(str(d).strip() for d in (durations or ()) if str(d).strip()),
            regions=_frozen(regions),
            niches=_frozen(niches),
        )

    def __post_init__(self) -> None:
        if unknown := self.networks - set(NETWORKS):
            raise ValueError(f"unknown network filter: {sorted(unknown)}")
        if unknown := self.kinds - set(ACCOUNT_KINDS):
            raise ValueError(f"unknown account kind filter: {sorted(unknown)}")
        if unknown := {network for network, _ in self.accounts} - set(NETWORKS):
            raise ValueError(f"unknown account network: {sorted(unknown)}")
        if unknown := self.durations - set(DURATION_BUCKETS):
            raise ValueError(f"unknown duration bucket: {sorted(unknown)}")
        if (self.regions or self.niches) and not REGION_NICHE_READY:
            raise FilterUnavailable("region and niche filters wait for RF-04 (m-25119461)")

    @property
    def wanted_kinds(self) -> tuple[str, ...]:
        """The kinds the list reads: the chosen ones, or both — never `detractor`."""
        return tuple(k for k in ACCOUNT_KINDS if not self.kinds or k in self.kinds)


NO_FILTERS = ReelFilters()


def duration_bucket(seconds: float | None) -> str | None:
    """The bucket a reel of `seconds` falls in; None when its duration is unknown."""
    if seconds is None:
        return None
    for key, (low, high) in DURATION_BUCKETS.items():
        if seconds >= low and (high is None or seconds < high):
            return key
    return None


def matches(reel: PublicReel, kind: str | None, filters: ReelFilters) -> bool:
    """Whether one reel of an account of `kind` (None = unlabelled) passes `filters`.
    A detractor's reel never does."""
    if kind == KIND_DETRACTOR:
        return False
    if filters.networks and reel.network not in filters.networks:
        return False
    if filters.kinds and kind not in filters.kinds:
        return False
    if filters.accounts and (reel.network, reel.handle) not in filters.accounts:
        return False
    if filters.durations and duration_bucket(reel.duration_s) not in filters.durations:
        return False
    return True


@dataclass(frozen=True)
class ReviewedReel:
    """One reel of «Más reels revisados»: the reel, the verdict that kept it (provenance:
    `model_id`, `prompt_version`) and the kind of its account."""

    reel: PublicReel
    verdict: StoredVerdict
    account_kind: str


@dataclass(frozen=True)
class ReviewedReels:
    """What RF-02's screen reads: the run's state (for «inténtalo más tarde» and the
    «preparing» notice, unchanged), its ideas and one page of the reviewed reels."""

    #: The run's state only: its `ideas` are unfiltered — show `ideas` below instead.
    view: RunView
    #: The ideas to show: filtered, never a detractor's, in the run's order.
    ideas: list[Idea]
    more: list[ReviewedReel]
    filters: ReelFilters
    offset: int
    limit: int
    has_more: bool
    title: str = MORE_REVIEWED_TITLE
    #: The accounts the «Cuenta» filter can offer: `(network, handle) → kind`, without
    #: detractors.
    accounts: dict[tuple[str, str], str] = field(default_factory=dict)


class ReviewedReelsStore(Protocol):
    def account_kinds(self, tenant_id: UUID, brand_id: UUID) -> dict[tuple[str, str], str]:
        """`(network, handle) → label` of every labelled account of the brand."""
        ...

    def fitting(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        brief_hash: str,
        filters: ReelFilters,
        exclude: Sequence[tuple[str, str]],
        offset: int,
        limit: int,
    ) -> list[ReviewedReel]:
        """The kept reels of the brand for `brief_hash`, newest verdict per reel, filtered,
        without `exclude` (`(network, reel_id)`), ordered by views then likes."""
        ...


def _rank(reel: PublicReel) -> tuple[int, int, str, str]:
    """The ideas' order (`reels._views_rank`), with a stable tail for pagination."""
    return (-(reel.views or 0), -(reel.likes or 0), reel.network, reel.reel_id)


def _strictly_fits(verdict: StoredVerdict) -> bool:
    return bool(verdict.fits) and verdict.affinity in reels_ai.FITS


class MemoryReviewedReelsStore:
    """The offline twin over a `MemoryReelRunStore` (its reels and verdicts) and a
    referentes repository (its labels), tenant-scoped like Postgres."""

    def __init__(self, runs: MemoryReelRunStore, labels: Any) -> None:
        self.runs = runs
        self.labels = labels

    def account_kinds(self, tenant_id: UUID, brand_id: UUID) -> dict[tuple[str, str], str]:
        return {
            (lb.network, lb.handle): lb.label
            for lb in self.labels.labels(tenant_id=tenant_id, brand_id=brand_id)
        }

    def fitting(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        brief_hash: str,
        filters: ReelFilters,
        exclude: Sequence[tuple[str, str]],
        offset: int,
        limit: int,
    ) -> list[ReviewedReel]:
        newest: dict[tuple[str, str], StoredVerdict] = {}
        for tenant, brand, verdict in self.runs.verdict_rows.values():  # insertion order
            if (tenant, brand) == (tenant_id, brand_id) and verdict.brief_hash == brief_hash:
                newest[(verdict.network, verdict.reel_id)] = verdict
        kinds = self.account_kinds(tenant_id, brand_id)
        skip = set(exclude)
        out: list[ReviewedReel] = []
        for key, verdict in newest.items():
            reel = self.runs.reels.get(key)
            if reel is None or key in skip or not _strictly_fits(verdict):
                continue
            kind = kinds.get((reel.network, reel.handle))
            if kind not in filters.wanted_kinds or not matches(reel, kind, filters):
                continue
            out.append(ReviewedReel(reel=reel, verdict=verdict, account_kind=kind))
        out.sort(key=lambda item: _rank(item.reel))
        return out[offset : offset + limit]


class PostgresReviewedReelsStore:
    """`ReviewedReelsStore` over 0020 + 0117, every statement inside `tenant_session`:
    RLS scopes `brand_reel_verdicts` and `brand_account_labels`; `public_reels` is global."""

    def account_kinds(self, tenant_id: UUID, brand_id: UUID) -> dict[tuple[str, str], str]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    "SELECT network, handle, label FROM brand_account_labels "
                    "WHERE brand_id = :brand"
                ),
                {"brand": brand_id},
            ).all()
        return {(row.network, row.handle): row.label for row in rows}

    def fitting(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        brief_hash: str,
        filters: ReelFilters,
        exclude: Sequence[tuple[str, str]],
        offset: int,
        limit: int,
    ) -> list[ReviewedReel]:
        reel_cols = ", ".join(f"r.{c.strip()} AS r_{c.strip()}" for c in _REEL_COLUMNS.split(","))
        verdict_names = [c.strip() for c in _VERDICT_COLUMNS.split(",")]
        latest_cols = ", ".join(f"v.{c}" for c in verdict_names)
        verdict_cols = ", ".join(f"v.{c} AS v_{c}" for c in verdict_names)
        where = [
            "v.fits",
            "v.affinity = ANY(CAST(:fits AS text[]))",
            "l.label = ANY(CAST(:kinds AS text[]))",
        ]
        params: dict[str, Any] = {
            "brand": brand_id,
            "brief": brief_hash,
            "fits": sorted(reels_ai.FITS),
            "kinds": list(filters.wanted_kinds),
            "limit": limit,
            "offset": offset,
        }
        if filters.networks:
            where.append("r.network = ANY(CAST(:networks AS text[]))")
            params["networks"] = sorted(filters.networks)
        if filters.accounts:
            accounts = sorted(filters.accounts)
            where.append(
                "EXISTS (SELECT 1 FROM unnest(CAST(:acc_net AS text[]), "
                "CAST(:acc_handle AS text[])) AS a(network, handle) "
                "WHERE a.network = r.network AND a.handle = r.handle)"
            )
            params["acc_net"] = [network for network, _ in accounts]
            params["acc_handle"] = [handle for _, handle in accounts]
        if filters.durations:
            spans = []
            for key in sorted(filters.durations):  # validated: only DURATION_BUCKETS keys
                low, high = DURATION_BUCKETS[key]
                upper = f" AND r.duration_s < {high:g}" if high is not None else ""
                spans.append(f"(r.duration_s >= {low:g}{upper})")
            where.append(f"r.duration_s IS NOT NULL AND ({' OR '.join(spans)})")
        if exclude:
            skip = sorted(set(exclude))
            where.append(
                "NOT EXISTS (SELECT 1 FROM unnest(CAST(:ex_net AS text[]), "
                "CAST(:ex_id AS text[])) AS x(network, reel_id) "
                "WHERE x.network = r.network AND x.reel_id = r.reel_id)"
            )
            params["ex_net"] = [network for network, _ in skip]
            params["ex_id"] = [reel_id for _, reel_id in skip]
        sql = (
            # the newest verdict of each reel for the brief (a newer transcript, model or
            # prompt may have judged it again): that one decides
            "WITH latest AS (SELECT DISTINCT ON (v.network, v.reel_id) "
            f"{latest_cols} FROM brand_reel_verdicts v "
            "WHERE v.brand_id = :brand AND v.brief_hash = :brief "
            "ORDER BY v.network, v.reel_id, v.created_at DESC, v.id DESC) "
            f"SELECT {reel_cols}, {verdict_cols}, l.label AS account_kind "
            "FROM latest v "
            "JOIN public_reels r ON r.network = v.network AND r.reel_id = v.reel_id "
            "JOIN brand_account_labels l ON l.brand_id = :brand "
            "AND l.network = r.network AND l.handle = r.handle "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY COALESCE(r.views, 0) DESC, COALESCE(r.likes, 0) DESC, "
            # code-point tie-break, as the memory twin sorts
            'r.network COLLATE "C", r.reel_id COLLATE "C" LIMIT :limit OFFSET :offset'
        )
        with tenant_session(tenant_id) as session:
            rows = session.execute(text(sql), params).all()
        return [
            ReviewedReel(
                reel=_reel(row, "r_"),
                verdict=_verdict(row, "v_"),
                account_kind=row.account_kind,
            )
            for row in rows
        ]


_library: ReviewedReelsStore | None = None


def default_library() -> ReviewedReelsStore:
    global _library
    if _library is None:
        _library = PostgresReviewedReelsStore()
    return _library


def reviewed_reels(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    filters: ReelFilters | None = None,
    offset: int = 0,
    limit: int = PAGE_SIZE,
    store: ReelRunStore | None = None,
    library: ReviewedReelsStore | None = None,
    now: datetime | None = None,
) -> ReviewedReels:
    """The brand's ideas and one page of «Más reels revisados», narrowed by `filters`.

    Only reads Postgres: never the vendor, never the model, never a write, never the
    reel analyzer. `offset`/`limit` page the second list only (`limit` is clamped to
    1..`MAX_PAGE_SIZE`); `has_more` says whether a next page exists. `store` is the runs
    store `reel_runs.view` reads; `library` the reviewed-reels store."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    chosen = filters or NO_FILTERS
    lib = library or default_library()
    seen = reel_runs.view(tenant_id, brand_id, store=store, now=now)
    kinds = lib.account_kinds(tenant_id, brand_id)
    ideas = [
        idea
        for idea in seen.ideas
        if matches(idea.reel, kinds.get((idea.reel.network, idea.reel.handle)), chosen)
    ]
    more: list[ReviewedReel] = []
    has_more = False
    brief = seen.shown.brief_hash if seen.shown is not None else None
    if brief:
        page = lib.fitting(
            tenant_id,
            brand_id,
            brief_hash=brief,
            filters=chosen,
            exclude=[(idea.reel.network, idea.reel.reel_id) for idea in seen.ideas],
            offset=offset,
            limit=limit + 1,  # one more says whether a next page exists
        )
        more, has_more = page[:limit], len(page) > limit
    return ReviewedReels(
        view=seen,
        ideas=ideas,
        more=more,
        filters=chosen,
        offset=offset,
        limit=limit,
        has_more=has_more,
        accounts={
            key: kind
            for key, kind in sorted(kinds.items())
            if kind in ACCOUNT_KINDS and key[0] in NETWORKS
        },
    )


__all__ = [
    "ACCOUNT_KINDS",
    "DURATION_15_30",
    "DURATION_30_60",
    "DURATION_BUCKETS",
    "DURATION_OVER_60",
    "DURATION_UNDER_15",
    "KIND_COMPETENCIA",
    "KIND_REFERENTE",
    "MAX_PAGE_SIZE",
    "MORE_REVIEWED_TITLE",
    "NETWORKS",
    "NO_FILTERS",
    "PAGE_SIZE",
    "REGION_NICHE_READY",
    "FilterUnavailable",
    "MemoryReviewedReelsStore",
    "PostgresReviewedReelsStore",
    "ReelFilters",
    "ReviewedReel",
    "ReviewedReels",
    "ReviewedReelsStore",
    "default_library",
    "duration_bucket",
    "matches",
    "reviewed_reels",
]
