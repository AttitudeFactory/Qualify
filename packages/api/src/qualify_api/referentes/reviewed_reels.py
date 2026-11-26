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
shown run's `brief_hash` (and the later manual reads', RF-05 below) counts (a newer
transcript or model may have judged it again), and it must keep the strict product
filter: `fits` AND `affinity` in `reels_ai.FITS` (a verdict stored under an older rule
cannot slip in). A brand with no `ok` run nor `ok` manual read has no brief to judge
against, so the list is empty.

**Filters** (`ReelFilters`, every one optional, combinable): channel (Instagram /
TikTok), account kind (`referente` = inspiradores, `competencia` = competidores — decision
1), one or several accounts (network + handle), and duration bucket (<15 s, 15-30 s,
30-60 s, 60 s or more; half-open, so a 15.0 s reel is «15-30»; a reel with no known
duration is left out only when a duration filter is set). **Detractors never appear**
(decision 3): their reels are never returned or counted, and a detractor kind is refused;
an idea whose account is labelled `detractor` today is dropped too.

**Region and niche (RF-02b, m-25119463).** Each account's country and rubro come from
the GLOBAL `creators` row RF-04 (m-25119461, migration 0182) fills with provenance
(`creators.region_rubro`): `region_code` (ISO-2, free sources only) and `rubro` (a key of
`discovery_seed.NICHE_LABELS` or `otro`, from the account review). The reel's account is
LEFT JOINed on `(network, handle)` — public data, no tenant, no policy — so a reel whose
account the pool does not know, or knows without a country / rubro, still reads with
`region_code = rubro = ''`. **An unknown value never matches a set filter and never hides
a reel when that filter is off**: with no region chosen («Todas») every reel enters, with
one or several regions only the reels of accounts known to be in one of them do; the same
for the niche. The ideas follow the same rule. `REGION_OPTIONS` are the three markets of
the business (`tenancy.locale.COUNTRIES`: Colombia, Venezuela, Uruguay — what signup and
Configuración offer) plus «Todas»; `brand_niche` reads the brand's rubro from its Brand
Kit (`connect.sector`, the rubro select, through `tenant_session`) for the fixed «Nicho: »
label. The niche is NOT applied by default: rubro coverage is ~0 % until each account is
reviewed again (RF-04), and a default niche filter would empty the list.

**Competidores** (RF-05, m-25119465). The Monday run also reads the 6 `competencia`
accounts the owner picked (`reels.brand_competitors`) and stores their verdicts under the
run's brief, and «Ver sus reels ahora» (`competitors.read_now`) reads any other one. A
manual read judges with the brief of its own moment, so the list reads the shown run's
brief plus the brief of every manual read that ended `ok` after it (`_briefs`); per reel
the newest verdict decides. A brand with no `ok` weekly run still sees what its manual
reads kept.

**Free and read-only.** Opening the list never calls ScrapeCreators nor Claude, writes
nothing (no `vendor_usage_events` row) and never queues the production reel analyzer,
which only runs over the ideas (`reel_runs._analyze`). The `brand_*` tables are read only
through `tenant_session` (RLS with the NULLIF policy); `public_reels` and `creators` are
global public data with no policy to scope. No migration: the verdicts are reached through
`uq_brand_reel_verdict` (`brand_id` first), the reels through `uq_public_reel` and the
labels through `uq_account_label`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creators.region_rubro import AccountFacts, account_facts
from qualify_api.referentes import reel_runs, reels_ai
from qualify_api.referentes.ai import RUBROS, normalize_country
from qualify_api.referentes.discovery_seed import NICHE_LABELS
from qualify_api.referentes.reel_runs import RunView
from qualify_api.referentes.reel_store import (
    _REEL_COLUMNS,
    _VERDICT_COLUMNS,
    STATUS_OK,
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

#: Region and niche read RF-04's per-account data (`creators.region_code` / `.rubro`).
REGION_NICHE_READY = True

#: What the bar reads (exact, ticket m-25119463).
REGION_TITLE = "Región"
REGION_ALL_LABEL = "Todas"
NICHE_PREFIX = "Nicho: "

PAGE_SIZE = 12
#: RF-05: with no weekly run shown, the manual reads of this many days back are read.
MANUAL_READS_DAYS = 30
MAX_PAGE_SIZE = 48

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegionOption:
    """One choice of the «Región» filter: `code` is ISO-2, "" for «Todas»."""

    code: str
    label: str


def _region_options() -> tuple[RegionOption, ...]:
    from qualify_api.tenancy.locale import COUNTRIES  # the business's three markets

    return (
        *(RegionOption(country.code, country.name) for country in COUNTRIES),
        RegionOption("", REGION_ALL_LABEL),
    )


#: «Colombia», «Venezuela», «Uruguay», then «Todas» (the default: no region filter).
REGION_OPTIONS: tuple[RegionOption, ...] = _region_options()


@dataclass(frozen=True)
class NicheOption:
    """The brand's rubro for the fixed «Nicho: …» label. `key` is a
    `discovery_seed.NICHE_LABELS` key ("" when the Brand Kit has none — then `label` is
    the owner's own words, `rubro_text`, or "" when there is nothing to show)."""

    key: str
    label: str

    @property
    def text(self) -> str:
        """«Nicho: Comida y bebida», "" when the brand has no rubro yet."""
        return f"{NICHE_PREFIX}{self.label}" if self.label else ""


NO_NICHE = NicheOption("", "")

#: `(tenant_id, brand_id) → the Brand Kit's connect document` (a mapping).
ConnectLoader = Callable[[UUID, UUID], Mapping[str, Any]]


def _load_connect(tenant_id: UUID, brand_id: UUID) -> Mapping[str, Any]:
    """The brand's Brand Kit `connect` document, read through `tenant_session` (the
    store's door: RLS hands back this business's row or nothing)."""
    from qualify_api.creative.brand_kit_store import BrandKitStore  # heavy: lazy

    connect = BrandKitStore().load_details(tenant_id=tenant_id, brand_id=brand_id).connect
    return connect if isinstance(connect, Mapping) else {}


def brand_niche(
    tenant_id: UUID, brand_id: UUID, *, connect: ConnectLoader | None = None
) -> NicheOption:
    """The brand's rubro as its Brand Kit keeps it (`connect.sector`, the rubro select;
    `connect.rubro_text`, the owner's own words, when no catalog key was chosen). A kit
    that cannot be read gives `NO_NICHE`: the label only disappears."""
    try:
        data = (connect or _load_connect)(tenant_id, brand_id)
    except Exception as exc:  # noqa: BLE001 — an unreadable kit only hides the label
        logger.warning("brand kit unreadable for the niche label: %s", type(exc).__name__)
        return NO_NICHE
    sector = str(data.get("sector") or "").strip().lower()
    if sector in NICHE_LABELS:
        return NicheOption(sector, NICHE_LABELS[sector])
    words = " ".join(str(data.get("rubro_text") or "").split())
    return NicheOption("", words) if words else NO_NICHE


class FilterUnavailable(ValueError):
    """A filter whose data does not exist yet (kept for callers; none is refused today)."""


def _frozen(values: Iterable[str] | None) -> frozenset[str]:
    return frozenset(str(v).strip().lower() for v in (values or ()) if str(v).strip())


def _regions(values: Iterable[str] | None) -> frozenset[str]:
    """ISO-2 codes, upper case; a value that is not one is refused (ValueError)."""
    out: set[str] = set()
    for value in values or ():
        raw = str(value).strip()
        if not raw:
            continue
        code = normalize_country(raw)
        if not code:
            raise ValueError(f"not a region code: {raw!r}")
        out.add(code)
    return frozenset(out)


@dataclass(frozen=True)
class ReelFilters:
    """What the owner narrowed the list to. Empty = no narrowing on that axis."""

    networks: frozenset[str] = frozenset()
    kinds: frozenset[str] = frozenset()
    #: `(network, handle)` pairs; the handle is normalized (no «@», lowercase).
    accounts: frozenset[tuple[str, str]] = frozenset()
    durations: frozenset[str] = frozenset()
    #: ISO-2 codes (upper case) of `creators.region_code`; empty = «Todas».
    regions: frozenset[str] = frozenset()
    #: `creators.rubro` keys (`ai.RUBROS`); empty = no niche narrowing.
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
            regions=_regions(regions),
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
        if bad := {r for r in self.regions if normalize_country(r) != r}:
            raise ValueError(f"unknown region filter: {sorted(bad)}")
        if unknown := self.niches - set(RUBROS):
            raise ValueError(f"unknown niche filter: {sorted(unknown)}")
        if (self.regions or self.niches) and not REGION_NICHE_READY:
            raise FilterUnavailable("region and niche filters are switched off")

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


def matches(
    reel: PublicReel,
    kind: str | None,
    filters: ReelFilters,
    facts: AccountFacts | None = None,
) -> bool:
    """Whether one reel of an account of `kind` (None = unlabelled) passes `filters`.
    A detractor's reel never does. `facts` are the account's region and rubro (None =
    the pool does not know the account): an unknown value never passes a set region or
    niche filter, and never matters when that filter is off."""
    if kind == KIND_DETRACTOR:
        return False
    if filters.regions and (facts is None or facts.region_code not in filters.regions):
        return False
    if filters.niches and (facts is None or facts.rubro not in filters.niches):
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
    #: The account's country (ISO-2) and rubro from `creators` (RF-04); "" = unknown.
    region_code: str = ""
    rubro: str = ""


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
    #: Region and rubro (`creators`, RF-04) of the ideas' and offered accounts the pool
    #: knows: `(network, handle) → AccountFacts`. An absent key = unknown.
    facts: dict[tuple[str, str], AccountFacts] = field(default_factory=dict)


class ReviewedReelsStore(Protocol):
    def account_kinds(self, tenant_id: UUID, brand_id: UUID) -> dict[tuple[str, str], str]:
        """`(network, handle) → label` of every labelled account of the brand."""
        ...

    def account_facts(
        self, tenant_id: UUID, keys: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], AccountFacts]:
        """Region and rubro of the `(network, handle)` accounts the global pool knows."""
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
        also_briefs: Sequence[str] = (),
    ) -> list[ReviewedReel]:
        """The kept reels of the brand for `brief_hash` (and `also_briefs`: the briefs of
        the owner's later «Ver sus reels ahora», RF-05), newest verdict per reel, filtered,
        without `exclude` (`(network, reel_id)`), ordered by views then likes."""
        ...


def _rank(reel: PublicReel) -> tuple[int, int, str, str]:
    """The ideas' order (`reels._views_rank`), with a stable tail for pagination."""
    return (-(reel.views or 0), -(reel.likes or 0), reel.network, reel.reel_id)


def _strictly_fits(verdict: StoredVerdict) -> bool:
    return bool(verdict.fits) and verdict.affinity in reels_ai.FITS


class MemoryReviewedReelsStore:
    """The offline twin over a `MemoryReelRunStore` (its reels and verdicts) and a
    referentes repository (its labels), tenant-scoped like Postgres. `creators` is the
    global pool's region / rubro per `(network, handle)` (shared by every business, like
    the `creators` table): `set_facts` fills it."""

    def __init__(self, runs: MemoryReelRunStore, labels: Any) -> None:
        self.runs = runs
        self.labels = labels
        self.creators: dict[tuple[str, str], AccountFacts] = {}

    def set_facts(self, network: str, handle: str, *, region: str = "", rubro: str = "") -> None:
        key = (network, normalize_handle(handle))
        region = normalize_country(region)
        self.creators[key] = AccountFacts(
            network=key[0],
            handle=key[1],
            region_code=region,
            region_source="sightings" if region else "",
            rubro=rubro,
            rubro_source="ai" if rubro else "",
        )

    def account_kinds(self, tenant_id: UUID, brand_id: UUID) -> dict[tuple[str, str], str]:
        return {
            (lb.network, lb.handle): lb.label
            for lb in self.labels.labels(tenant_id=tenant_id, brand_id=brand_id)
        }

    def account_facts(
        self, tenant_id: UUID, keys: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], AccountFacts]:
        wanted = {(network, normalize_handle(handle)) for network, handle in keys}
        return {key: facts for key, facts in self.creators.items() if key in wanted}

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
        also_briefs: Sequence[str] = (),
    ) -> list[ReviewedReel]:
        briefs = {brief_hash, *also_briefs}
        newest: dict[tuple[str, str], StoredVerdict] = {}
        for tenant, brand, verdict in self.runs.verdict_rows.values():  # insertion order
            if (tenant, brand) == (tenant_id, brand_id) and verdict.brief_hash in briefs:
                newest[(verdict.network, verdict.reel_id)] = verdict
        kinds = self.account_kinds(tenant_id, brand_id)
        skip = set(exclude)
        out: list[ReviewedReel] = []
        for key, verdict in newest.items():
            reel = self.runs.reels.get(key)
            if reel is None or key in skip or not _strictly_fits(verdict):
                continue
            kind = kinds.get((reel.network, reel.handle))
            facts = self.creators.get((reel.network, reel.handle))
            if kind not in filters.wanted_kinds or not matches(reel, kind, filters, facts):
                continue
            out.append(
                ReviewedReel(
                    reel=reel,
                    verdict=verdict,
                    account_kind=kind,
                    region_code=facts.region_code if facts else "",
                    rubro=facts.rubro if facts else "",
                )
            )
        out.sort(key=lambda item: _rank(item.reel))
        return out[offset : offset + limit]


class PostgresReviewedReelsStore:
    """`ReviewedReelsStore` over 0020 + 0117 + 0182, every statement inside
    `tenant_session`: RLS scopes `brand_reel_verdicts` and `brand_account_labels`;
    `public_reels` and `creators` are global."""

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

    def account_facts(
        self, tenant_id: UUID, keys: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], AccountFacts]:
        wanted = list(keys)
        if not wanted:
            return {}
        with tenant_session(tenant_id) as session:
            return account_facts(session, wanted)

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
        also_briefs: Sequence[str] = (),
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
            "briefs": sorted({brief_hash, *also_briefs}),
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
        # RF-02b: an account the pool does not know (no `creators` row) has c.* NULL and
        # never matches a set region / niche; with the filter off it is never tested
        if filters.regions:
            where.append("c.region_code = ANY(CAST(:regions AS text[]))")
            params["regions"] = sorted(filters.regions)
        if filters.niches:
            where.append("c.rubro = ANY(CAST(:niches AS text[]))")
            params["niches"] = sorted(filters.niches)
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
            "WHERE v.brand_id = :brand AND v.brief_hash = ANY(CAST(:briefs AS text[])) "
            "ORDER BY v.network, v.reel_id, v.created_at DESC, v.id DESC) "
            f"SELECT {reel_cols}, {verdict_cols}, l.label AS account_kind, "
            "COALESCE(c.region_code, '') AS c_region_code, COALESCE(c.rubro, '') AS c_rubro "
            "FROM latest v "
            "JOIN public_reels r ON r.network = v.network AND r.reel_id = v.reel_id "
            "JOIN brand_account_labels l ON l.brand_id = :brand "
            "AND l.network = r.network AND l.handle = r.handle "
            # the global pool (0182, uq_creator): one row per account at most
            "LEFT JOIN creators c ON c.network = r.network AND c.handle = r.handle "
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
                region_code=row.c_region_code,
                rubro=row.c_rubro,
            )
            for row in rows
        ]


_library: ReviewedReelsStore | None = None


def default_library() -> ReviewedReelsStore:
    global _library
    if _library is None:
        _library = PostgresReviewedReelsStore()
    return _library


def _briefs(
    tenant_id: UUID,
    brand_id: UUID,
    seen: RunView,
    store: ReelRunStore | None,
    now: datetime | None = None,
) -> list[str]:
    """The briefs whose verdicts the second list reads: the shown run's, plus (RF-05) the
    one of every «Ver sus reels ahora» that ended `ok` after it — a read the owner asked
    for shows at once, even when the brief changed since Monday or there is no `ok`
    weekly run yet. Per reel the newest verdict still decides."""
    briefs: list[str] = []
    if seen.shown is not None and seen.shown.brief_hash:
        briefs.append(seen.shown.brief_hash)
    after = seen.shown.finished_at if seen.shown is not None else None
    if after is None:  # no weekly run yet: the manual reads of the last month only
        after = (now or datetime.now(UTC)) - timedelta(days=MANUAL_READS_DAYS)
    reads = (store or reel_runs.default_store()).competitor_runs(
        tenant_id, brand_id, finished_after=after
    )
    for run in reads:
        if run.status == STATUS_OK and run.brief_hash and run.brief_hash not in briefs:
            briefs.append(run.brief_hash)
    return briefs


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
    offered = {key for key, kind in kinds.items() if kind in ACCOUNT_KINDS and key[0] in NETWORKS}
    idea_keys = {
        key
        for key in ((idea.reel.network, idea.reel.handle) for idea in seen.ideas)
        if kinds.get(key) != KIND_DETRACTOR
    }
    facts = lib.account_facts(tenant_id, sorted(offered | idea_keys))
    ideas = [
        idea
        for idea in seen.ideas
        if matches(
            idea.reel,
            kinds.get((idea.reel.network, idea.reel.handle)),
            chosen,
            facts.get((idea.reel.network, idea.reel.handle)),
        )
    ]
    more: list[ReviewedReel] = []
    has_more = False
    briefs = _briefs(tenant_id, brand_id, seen, store, now)
    if briefs:
        page = lib.fitting(
            tenant_id,
            brand_id,
            brief_hash=briefs[0],
            also_briefs=briefs[1:],
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
        facts=facts,
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
    "NICHE_PREFIX",
    "NO_FILTERS",
    "NO_NICHE",
    "PAGE_SIZE",
    "REGION_ALL_LABEL",
    "REGION_NICHE_READY",
    "REGION_OPTIONS",
    "REGION_TITLE",
    "FilterUnavailable",
    "MemoryReviewedReelsStore",
    "NicheOption",
    "PostgresReviewedReelsStore",
    "ReelFilters",
    "RegionOption",
    "ReviewedReel",
    "ReviewedReels",
    "ReviewedReelsStore",
    "brand_niche",
    "default_library",
    "duration_bucket",
    "matches",
    "reviewed_reels",
]
