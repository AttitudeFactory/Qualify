"""«Buscar más cuentas en TikTok» — the paid fallback of «Descubrir cuentas nuevas»
(RF-07b, m-25119482).

Epic m-24872324, `docs/epica-filtrado-reels.md`, cost option B signed by Deivid on
2026-11-25: «base compartida primero, presupuesto 50/200». RF-07a
(`creators.discover_accounts`) lists, for free, the accounts the shared pool already
knows; when that list has fewer than `FEW_RESULTS` (8) accounts, the owner may press a
button and this module searches TikTok — paying — for more.

## What this module guarantees

- **Only as a fallback.** Before anything is paid, the free list is read again with the
  owner's filters (`DiscoverStore.page`); with `FEW_RESULTS` or more accounts the search
  stops (`enough_results`) and nothing is called.
- **Only on the owner's click.** `search_more_accounts` needs the owner's user id; no
  worker, tick or schedule calls it. It never labels an account: the accounts it finds
  only join RF-07a's list, and following one is still `discover_accounts.follow_account`
  (the owner's click).
- **TikTok only.** Instagram has no user search (`/v2/instagram/reels/search` is
  Google-indexed and answers reels from anywhere — measured 2026-09-11,
  `Qualify/creator_discovery.py`), so an Instagram request answers
  `instagram_unsupported` with `INSTAGRAM_TEXT` and calls nothing.
- **No product search** (epic decision 2). The query is built here from the rubro of
  the Brand Kit catalog (`RUBRO_QUERIES`) and, optionally, the city — never typed free
  text: «comida Cúcuta», «gimnasio Montevideo».
- **Its own budget per business: `SEARCH_DAY_CAP` (50) credits a local day,
  `SEARCH_MONTH_CAP` (200) a local month**, summed over its own feature
  (`scrapecreators.FEATURE_DISCOVER_SEARCH`, migration 0184) in `vendor_usage_events` —
  apart from the Creators module's 50/300 and from the reels runs' features. Every credit
  is booked by the metered gate (`vendors.scrapecreators.metered_get`) BEFORE the request
  leaves, charged to this business and brand, inside the business's 150/600 cap (ADR 42
  R5): the search never goes past either. A cap reached reads `DAILY_CAP_TEXT` /
  `MONTHLY_CAP_TEXT` and no call is made. An uncapped business («Lecturas sin límite»,
  `vendors.uncapped`, m-24956180) skips this budget as it skips the Creators one; its
  credits are still booked.
- **Idempotent: the same search is never paid twice in a week.** Every answer is kept in
  the shared `vendor_payloads` (`SEARCH_TTL`, 7 days) under its path and parameters —
  the same cache the Referentes search uses — and asked first: the same search again
  (the same day, another tab, another business) is served for 0 credits (`cached`). An
  empty search (the vendor's HTTP 404 `not_found`) is kept too. Inside one process, a
  business's searches run one at a time (`_tenant_lock`), so a double click waits for
  the first and then reads its kept answer. Two app processes racing on the same search
  in the same second could both pay it once — the app runs one process, and the gate
  still books and caps both.
- **Every derived row says where it came from.** The accounts go to the global
  `creators` (merged as the pool always merges, `repository._merge`) and each one gets a
  `creator_sightings` row (kind `keyword`, the query, the region asked) — the provenance
  RF-07a already reads; the country TikTok states per video is applied with
  `region_rubro.apply_region` citing `vendor_payloads:<id>` (`region-free-1`). The
  outcome carries the `vendor_payloads` ids and `PAID_SEARCH_VERSION`.
- **Tenant isolation.** The only per-tenant tables touched are `vendor_usage_events`
  (written by the gate, read for the budget) and `brands` / `brand_account_labels`
  (RF-07a's read), all through `tenant_session` with the RLS policy
  `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. The global
  pool keeps no tenant: nothing there says which business searched.

## Cost

One search = one TikTok keyword page (`/v1/tiktok/search/keyword`, 30 videos, 1 credit,
measured 2026-09-11 and 2026-10-01 — `docs/scrapecreators-crecimiento-organico-y-contenido-ia.md`),
and a second page only when the first showed fewer than `FEW_RESULTS` distinct accounts:
`SEARCH_MAX_CREDITS` (2) at most. At USD 0.0019 a credit (`pricing_data/v10.json`) that
is USD 0.0019, at most USD 0.0038, per search; the 200-credit month caps a business at
≈ USD 0.38. A repeated search inside the week costs 0.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from qualify_shared.db.session import tenant_session

from qualify_api.creators.discover_accounts import (
    FEW_RESULTS,
    FOLLOWERS_SEARCH,
    DiscoveredAccount,
    DiscoverFilters,
    DiscoverPage,
    DiscoverStore,
    MemoryDiscoverStore,
)
from qualify_api.creators.region_rubro import (
    RegionClaim,
    apply_region,
    best_claims,
    claims_from_payload,
)
from qualify_api.creators.repository import (
    CachedPayload,
    CreatorFacts,
    MemoryCreatorPoolRepository,
    PostgresCreatorPoolRepository,
    Sighting,
    normalize_handle,
    params_key,
    record_sightings_in,
    upsert_creators_in,
)
from qualify_api.referentes.ai import normalize_country
from qualify_api.referentes.discovery_seed import country_name
from qualify_api.vendors import scrapecreators, uncapped, usage

logger = logging.getLogger(__name__)

#: Version of this search (query building + what is kept). Bump when either changes.
PAID_SEARCH_VERSION = "discover-paid-1"

NETWORK = "tiktok"
#: TikTok's keyword search: `query=` (not `keyword=`, HTTP 400 otherwise — measured
#: 2026-09-11), optional `region=` (the vendor's proxy country) and `cursor=`.
PATH = "/v1/tiktok/search/keyword"
FEATURE = scrapecreators.FEATURE_DISCOVER_SEARCH

#: The search's own budget per business (Deivid, option B, 2026-11-25).
SEARCH_DAY_CAP = 50
SEARCH_MONTH_CAP = 200
#: Pages one search may read; 1 credit each.
SEARCH_MAX_PAGES = 2
SEARCH_MAX_CREDITS = SEARCH_MAX_PAGES

#: The word searched for each rubro of the Brand Kit catalog (`NICHE_LABELS`): what a
#: neighbor would type in TikTok. Never a product (epic decision 2).
RUBRO_QUERIES: dict[str, str] = {
    "food_drink": "comida",
    "fashion_beauty": "moda",
    "fitness_health": "gimnasio",
    "travel_lifestyle": "viajes",
    "real_estate": "inmobiliaria",
    "technology": "tecnología",
    "education": "cursos",
    "entertainment": "humor",
}
_PLACE_MAX = 40

SearchStatus = Literal[
    "searched",  # paid now (credits > 0)
    "cached",  # served from `vendor_payloads`: 0 credits
    "enough_results",  # the free list has FEW_RESULTS or more: nothing called
    "instagram_unsupported",  # Instagram has no user search: nothing called
    "daily_cap",  # this search's 50 a day, or the business's 150 a day
    "monthly_cap",  # this search's 200 a month, or the business's 600 a month
    "unavailable",  # the gate did not call (switch, credit floor, 402, unreadable usage)
    "error",  # the network or the vendor failed
]

#: Exact client-facing texts (ticket m-25119482, «Criterios de aceptación», and
#: `qualify-copy-es`). Never credits or money.
SEARCH_BUTTON = "Buscar más cuentas en TikTok"
FEW_RESULTS_TEXT = "Encontramos pocas cuentas. ¿Quieres que busquemos más en TikTok?"
DAILY_CAP_TEXT = "Hoy ya se alcanzó el límite de búsquedas de tu negocio. Inténtalo mañana."
MONTHLY_CAP_TEXT = (
    "Este mes ya se alcanzó el límite de búsquedas de tu negocio. "
    "Desde el {renewal} puedes buscar de nuevo."
)
INSTAGRAM_TEXT = "Por ahora la búsqueda de cuentas nuevas solo funciona en TikTok."
NO_NEW_TEXT = "No encontramos cuentas nuevas en TikTok. Prueba con otro rubro o ciudad."
UNAVAILABLE_TEXT = "No pudimos buscar cuentas nuevas en este momento. Inténtalo más tarde."

Key = tuple[str, str]


@dataclass(frozen=True)
class SearchBudget:
    """What this business has used of the search's own budget (never shown as numbers)."""

    day: int
    month: int
    uncapped: bool = False

    @property
    def left(self) -> int:
        return max(0, min(SEARCH_DAY_CAP - self.day, SEARCH_MONTH_CAP - self.month))

    @property
    def reached(self) -> SearchStatus | None:
        """`daily_cap` / `monthly_cap` when not even one credit is left, else None."""
        if self.uncapped:
            return None
        if self.day >= SEARCH_DAY_CAP:
            return "daily_cap"
        if self.month >= SEARCH_MONTH_CAP:
            return "monthly_cap"
        return None


@dataclass(frozen=True)
class PaidSearchOutcome:
    status: SearchStatus
    #: The owner's sentence, or None when the list itself says it all.
    message: str | None
    #: The search actually run («comida cúcuta»); "" when none was.
    query: str
    #: Credits booked by this call — for the log and the tests; the screen NEVER shows it.
    credits: int
    #: Every account the search saw (labeled ones included); empty when none was run.
    found: tuple[Key, ...] = ()
    #: RF-07a's list read again after the search, with the same filters — what the screen
    #: shows. None when the brand's list could not be read.
    page: DiscoverPage | None = None
    #: Provenance: the `vendor_payloads` rows the accounts came from.
    payload_ids: tuple[UUID, ...] = ()
    version: str = PAID_SEARCH_VERSION


# --------------------------------------------------------------------------------------
# pure rules
# --------------------------------------------------------------------------------------


def build_query(rubro: str, place: str = "") -> str:
    """The search for a rubro of the catalog, and optionally a city or country name:
    `("food_drink", "Cúcuta")` → «comida cúcuta». Lower case and single spaces, so the
    same search always has the same cache key. Raises `ValueError` for a rubro outside
    `RUBRO_QUERIES` (`otro` included: it says nothing to search for)."""
    word = RUBRO_QUERIES.get(rubro)
    if word is None:
        raise ValueError(f"rubro must be one of {tuple(RUBRO_QUERIES)}, got {rubro!r}")
    where = " ".join(str(place or "").split())[:_PLACE_MAX].strip()
    return " ".join(f"{word} {where}".split()).lower()


def place_for(city: str = "", region_code: str = "") -> str:
    """The place a search names: the city, else the country's name, else nothing."""
    city = " ".join(str(city or "").split())
    if city:
        return city
    return country_name(normalize_country(region_code)) if region_code else ""


def search_params(query: str, region_code: str = "", cursor: str = "") -> dict[str, str]:
    params = {"query": query}
    if region_code:
        params["region"] = region_code
    if cursor:
        params["cursor"] = cursor
    return params


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _videos(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = payload.get("search_item_list")
    if not isinstance(items, list):
        return []
    return [
        item["aweme_info"]
        for item in items
        if isinstance(item, Mapping) and isinstance(item.get("aweme_info"), Mapping)
    ]


def _is_ai(video: Mapping[str, Any]) -> bool:
    info = video.get("aigc_info")
    if not isinstance(info, Mapping):
        return False
    label = info.get("aigc_label_type")
    return bool(info.get("created_by_ai")) or (isinstance(label, int) and label != 0)


@dataclass
class _Seen:
    """One author across the videos of a search's pages."""

    handle: str
    full_name: str = ""
    bio: str = ""
    avatar_url: str = ""
    followers: int | None = None
    total_likes: int | None = None
    is_private: bool = False
    is_verified: bool = False
    hashtags: list[str] = field(default_factory=list)
    posts: int = 0
    ai_posts: int = 0
    likes: int = 0
    comments: int = 0
    views: int = 0


def _avatar(author: Mapping[str, Any]) -> str:
    for key in ("avatar_medium", "avatar_thumb", "avatar_larger"):
        value = author.get(key)
        urls = value.get("url_list") if isinstance(value, Mapping) else None
        if isinstance(urls, list):
            for url in urls:
                if isinstance(url, str) and url.startswith("https://"):
                    return url
    return ""


def accounts_from_pages(
    payloads: Sequence[Mapping[str, Any]],
    *,
    query: str,
    region_code: str = "",
    seen_at: datetime | None = None,
) -> tuple[list[CreatorFacts], list[Sighting]]:
    """The accounts a search's answers show, as the pool keeps them, and one sighting
    each (kind `keyword`, the query, the region asked). Pure.

    Follower counts come from each video's `author.follower_count`; TikTok trims it to 0
    on some feeds (measured 2026-09-11), so 0 means unknown, never «no followers». The
    figures seen (likes, comments, views, posts) add up over the videos of the search."""
    moment = seen_at or datetime.now(UTC)
    seen: dict[str, _Seen] = {}
    for payload in payloads:
        for video in _videos(payload):
            author = video.get("author")
            if not isinstance(author, Mapping):
                continue
            handle = normalize_handle(str(author.get("unique_id") or ""))
            if not handle:
                continue
            entry = seen.setdefault(handle, _Seen(handle))
            entry.full_name = entry.full_name or str(author.get("nickname") or "")
            entry.bio = entry.bio or " ".join(str(author.get("signature") or "").split())
            entry.avatar_url = entry.avatar_url or _avatar(author)
            followers = _int(author.get("follower_count"))
            if followers:
                entry.followers = max(entry.followers or 0, followers)
            likes_total = _int(author.get("total_favorited"))
            if likes_total:
                entry.total_likes = max(entry.total_likes or 0, likes_total)
            entry.is_private = entry.is_private or bool(author.get("is_private_account"))
            entry.is_verified = (
                entry.is_verified
                or bool(author.get("is_verified"))
                or author.get("verification_type") == 1
            )
            stats = video.get("statistics")
            stats = stats if isinstance(stats, Mapping) else {}
            entry.posts += 1
            entry.ai_posts += 1 if _is_ai(video) else 0
            entry.likes += _int(stats.get("digg_count"))
            entry.comments += _int(stats.get("comment_count"))
            entry.views += _int(stats.get("play_count"))
            for extra in video.get("text_extra") or []:
                tag = extra.get("hashtag_name") if isinstance(extra, Mapping) else None
                if isinstance(tag, str) and tag.strip():
                    tag = tag.strip().lower()
                    if tag not in entry.hashtags:
                        entry.hashtags.append(tag)
    facts: list[CreatorFacts] = []
    sightings: list[Sighting] = []
    for entry in seen.values():
        facts.append(
            CreatorFacts(
                network=NETWORK,
                handle=entry.handle,
                full_name=entry.full_name,
                bio=entry.bio,
                profile_url=f"https://www.tiktok.com/@{entry.handle}",
                avatar_url=entry.avatar_url,
                followers=entry.followers,
                total_likes=entry.total_likes,
                is_private=entry.is_private,
                is_verified=entry.is_verified,
                hashtags=tuple(entry.hashtags[:30]),
                posts_seen=entry.posts,
                ai_posts_seen=entry.ai_posts,
                likes_seen=entry.likes,
                comments_seen=entry.comments,
                views_seen=entry.views,
                read_at=None,  # a feed sighting, not a profile read
                seen_at=moment,
            )
        )
        sightings.append(
            Sighting(
                network=NETWORK,
                handle=entry.handle,
                kind="keyword",
                term=query,
                country_code=region_code,
                seen_at=moment,
            )
        )
    return facts, sightings


def region_claims(entries: Sequence[CachedPayload]) -> list[RegionClaim]:
    """The country TikTok states with each video of the kept answers, best per account
    (`region_rubro.best_claims`), each citing its `vendor_payloads` row."""
    claims: list[RegionClaim] = []
    for entry in entries:
        if entry.status == 200:
            claims.extend(
                claims_from_payload(PATH, entry.params_key, entry.payload, payload_id=str(entry.id))
            )
    return list(best_claims(claims).values())


# --------------------------------------------------------------------------------------
# where the answers and the accounts go
# --------------------------------------------------------------------------------------


class PaidSearchPool(Protocol):
    def get_payload(
        self, path: str, params: Mapping[str, Any], *, now: datetime | float | None = None
    ) -> CachedPayload | None: ...

    def put_payload(
        self,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int = 200,
        credits_charged: int = 0,
        now: datetime | float | None = None,
    ) -> CachedPayload: ...

    def record(
        self,
        facts: Sequence[CreatorFacts],
        sightings: Sequence[Sighting],
        claims: Sequence[RegionClaim],
        *,
        now: datetime | None = None,
    ) -> None:
        """The accounts, their sightings and their free region, in one unit of work."""
        ...


class PostgresPaidSearchPool(PostgresCreatorPoolRepository):
    """The shared pool through `tenant_session` (the role and the pool; the tables are
    global). `record` is one transaction: accounts, sightings, region."""

    def record(
        self,
        facts: Sequence[CreatorFacts],
        sightings: Sequence[Sighting],
        claims: Sequence[RegionClaim],
        *,
        now: datetime | None = None,
    ) -> None:
        if not facts:
            return
        with tenant_session(self.tenant_id) as session:
            upsert_creators_in(session, facts)
            # the accounts must exist before a sighting or a region names them
            session.flush()
            record_sightings_in(session, sightings)
            for claim in claims:
                apply_region(session, claim, now=now)


@dataclass
class MemoryPaidSearchPool:
    """Offline twin: the pool's payloads and accounts in a `MemoryCreatorPoolRepository`,
    and every account recorded mirrored into a `MemoryDiscoverStore` (so it joins RF-07a's
    list the way the SQL read makes it join in Postgres)."""

    repository: MemoryCreatorPoolRepository
    discover: MemoryDiscoverStore
    records: int = 0

    def get_payload(
        self, path: str, params: Mapping[str, Any], *, now: datetime | float | None = None
    ) -> CachedPayload | None:
        return self.repository.get_payload(path, params, now=now)

    def put_payload(
        self,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int = 200,
        credits_charged: int = 0,
        now: datetime | float | None = None,
    ) -> CachedPayload:
        return self.repository.put_payload(
            path, params, payload, status=status, credits_charged=credits_charged, now=now
        )

    def record(
        self,
        facts: Sequence[CreatorFacts],
        sightings: Sequence[Sighting],
        claims: Sequence[RegionClaim],
        *,
        now: datetime | None = None,
    ) -> None:
        self.records += 1
        self.repository.upsert_creators(facts)
        self.repository.record_sightings(sightings)
        regions = {claim.key: claim for claim in claims}
        for fact in facts:
            stored = self.repository.creator(fact.network, fact.handle) or fact
            region = regions.get((fact.network, fact.handle))
            known = next(
                (a for a in self.discover.pool if a.key == (fact.network, fact.handle)), None
            )
            account = DiscoveredAccount(
                network=stored.network,
                handle=stored.handle,
                full_name=stored.full_name,
                avatar_url=stored.avatar_url,
                profile_url=stored.profile_url,
                followers=stored.followers,
                followers_source=FOLLOWERS_SEARCH if stored.followers is not None else "",
            )
            if region is not None:
                account = replace(account, region_code=region.code, region_source=region.source)
            elif known is not None:
                account = replace(
                    account, region_code=known.region_code, region_source=known.region_source
                )
            times = self.discover.seen_times.get(account.key, 0) + 1
            self.discover.add(account, seen_times=times)


# --------------------------------------------------------------------------------------
# the budget
# --------------------------------------------------------------------------------------


def budget(tenant_id: UUID, *, now: datetime | None = None) -> SearchBudget:
    """This business's use of the search's own budget, in its local day and month — what
    the screen asks before offering the button. Raises whatever the usage store raises
    (the caller treats an unreadable budget as «no disponible», never as «free»)."""
    if uncapped.is_uncapped(tenant_id):
        return SearchBudget(0, 0, uncapped=True)
    spent = usage.store().spent(tenant_id, usage.SCRAPECREATORS, now, features=(FEATURE,))
    return SearchBudget(spent.day, spent.month)


def cap_text(status: SearchStatus, *, zone: ZoneInfo | None, now: datetime | None) -> str:
    if status == "daily_cap":
        return DAILY_CAP_TEXT
    return MONTHLY_CAP_TEXT.format(renewal=usage.renewal_label(zone or ZoneInfo("UTC"), now))


_locks_guard = threading.Lock()
_locks: dict[UUID, threading.Lock] = {}


def _tenant_lock(tenant_id: UUID) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(tenant_id, threading.Lock())


# --------------------------------------------------------------------------------------
# the search
# --------------------------------------------------------------------------------------


def _credits_charged(payload: Mapping[str, Any]) -> int:
    value = payload.get("credits_charged")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 1


def search_more_accounts(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    requested_by: UUID,
    network: str,
    rubro: str,
    filters: DiscoverFilters,
    store: DiscoverStore,
    pool: PaidSearchPool,
    city: str = "",
    region_code: str = "",
    client: httpx.Client | None = None,
    zone: ZoneInfo | None = None,
    zone_of: Callable[[UUID], ZoneInfo] = usage.tenant_zone,
    now: datetime | None = None,
) -> PaidSearchOutcome:
    """«Buscar más cuentas en TikTok» — the owner's click, never a job.

    `filters` are the ones on the owner's screen: the free list is read with them first
    and the search only runs when it has fewer than `FEW_RESULTS` accounts. `rubro` (a
    key of `RUBRO_QUERIES`) and `city` / `region_code` build the query; `region_code` is
    also TikTok's `region` and the sightings' country. After the search the same list is
    read again and returned (`page`).

    Raises `ValueError` for a missing owner, an unknown network or rubro, or a brand the
    tenant does not own (from `store.page`)."""
    if requested_by is None:
        raise ValueError("a paid search needs the owner who clicked")
    net = (network or "").strip().lower()
    if net == "instagram":
        return PaidSearchOutcome("instagram_unsupported", INSTAGRAM_TEXT, "", 0)
    if net != NETWORK:
        raise ValueError(f"network must be tiktok or instagram, got {network!r}")
    region = normalize_country(region_code)
    query = build_query(rubro, place_for(city, region))

    free = store.page(tenant_id=tenant_id, brand_id=brand_id, filters=filters, now=now)
    if not free.few_results:
        return PaidSearchOutcome("enough_results", None, "", 0, page=free)

    with _tenant_lock(tenant_id):
        return _search(
            tenant_id=tenant_id,
            brand_id=brand_id,
            query=query,
            region=region,
            filters=filters,
            store=store,
            pool=pool,
            client=client,
            zone=zone,
            zone_of=zone_of,
            now=now,
        )


def _search(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    query: str,
    region: str,
    filters: DiscoverFilters,
    store: DiscoverStore,
    pool: PaidSearchPool,
    client: httpx.Client | None,
    zone: ZoneInfo | None,
    zone_of: Callable[[UUID], ZoneInfo],
    now: datetime | None,
) -> PaidSearchOutcome:
    def capped(status: SearchStatus, credits: int = 0) -> PaidSearchOutcome:
        where = zone if zone is not None or status == "daily_cap" else zone_of(tenant_id)
        text = cap_text(status, zone=where, now=now)
        return PaidSearchOutcome(status, text, query, credits, page=_reread())

    def _reread() -> DiscoverPage | None:
        try:
            return store.page(tenant_id=tenant_id, brand_id=brand_id, filters=filters, now=now)
        except Exception:  # noqa: BLE001 - the search's outcome must still reach the owner
            logger.exception("discover paid: list of brand %s not re-read", brand_id)
            return None

    kept: list[CachedPayload] = []
    #: Answers paid for but not written to `vendor_payloads` (the write failed): still
    #: used for the accounts, never cited as provenance.
    unstored: set[UUID] = set()

    def keep(
        params: dict[str, str], payload: dict[str, Any], *, status: int, credits_charged: int
    ) -> CachedPayload:
        try:
            return pool.put_payload(
                PATH, params, payload, status=status, credits_charged=credits_charged, now=now
            )
        except Exception:  # noqa: BLE001 - the answer is paid for: use it, say it was not kept
            logger.exception("discover paid: answer to %r not kept", query)
            at = now or datetime.now(UTC)
            entry = CachedPayload(PATH, params_key(params), status, payload, at, at, uuid4())
            unstored.add(entry.id)
            return entry

    credits = 0
    left: int | None = None  # this search's budget, read before the first paid page
    owns_client = client is None
    http = client or httpx.Client(timeout=scrapecreators._TIMEOUT_SECONDS)  # noqa: SLF001
    usage.bind(http, usage.UsageCharge(tenant_id, brand_id))
    failed: SearchStatus | None = None
    try:
        cursor = ""
        for _ in range(SEARCH_MAX_PAGES):
            params = search_params(query, region, cursor)
            try:
                entry = pool.get_payload(PATH, params, now=now)
            except Exception as exc:  # noqa: BLE001 - an unreadable pool is no reason to pay
                logger.warning("discover paid: pool unreadable: %s", type(exc).__name__)
                failed = "unavailable"
                break
            if entry is None:
                if left is None:
                    try:
                        spent = budget(tenant_id, now=now)
                    except Exception as exc:  # noqa: BLE001 - never pay what cannot be counted
                        logger.warning(
                            "discover paid: budget of %s unreadable: %s",
                            tenant_id,
                            type(exc).__name__,
                        )
                        failed = "unavailable"
                        break
                    reached = spent.reached
                    if reached is not None and not kept:
                        return capped(reached, credits)
                    left = SEARCH_MAX_CREDITS if spent.uncapped else spent.left
                if credits >= left:
                    break  # the budget allows no more pages; keep what was read
                try:
                    payload = scrapecreators.metered_get(http, PATH, params, feature=FEATURE)
                except scrapecreators.ScrapeCreatorsBlocked as exc:
                    if exc.reason in usage.CAP_REASONS:
                        cap: SearchStatus = (
                            "daily_cap" if exc.reason == usage.REASON_DAILY_CAP else "monthly_cap"
                        )
                        if not kept:
                            return capped(cap, credits)
                        break
                    logger.warning("discover paid: gate refused %r: %s", query, exc.reason)
                    failed = "unavailable"
                    break
                except scrapecreators.ScrapeCreatorsError as exc:
                    credits += 1  # the gate booked it before the request left
                    if exc.status_code == 404:
                        # an empty search is a result: keep it, so it is not paid again
                        kept.append(keep(params, {}, status=404, credits_charged=1))
                        break
                    logger.warning("discover paid: search %r failed: %s", query, exc)
                    failed = "error"
                    break
                charged = _credits_charged(payload)
                credits += charged
                entry = keep(params, payload, status=200, credits_charged=charged)
            kept.append(entry)
            if entry.status != 200:
                break
            authors = {
                normalize_handle(str((v.get("author") or {}).get("unique_id") or ""))
                for e in kept
                if e.status == 200
                for v in _videos(e.payload)
            }
            authors.discard("")
            next_cursor = entry.payload.get("cursor")
            more = entry.payload.get("has_more")
            if len(authors) >= FEW_RESULTS or not next_cursor or more in (False, 0):
                break
            cursor = str(next_cursor)
    finally:
        if owns_client:
            http.close()

    answered = [e for e in kept if e.status == 200]
    facts, sightings = accounts_from_pages(
        [e.payload for e in answered],
        query=query,
        region_code=region,
        seen_at=now,
    )
    recorded = True
    if facts:
        cited = [e for e in answered if e.id not in unstored]
        try:
            pool.record(facts, sightings, region_claims(cited), now=now)
        except Exception:  # noqa: BLE001 - the credits are spent; the answers stay kept
            logger.exception("discover paid: accounts of %r not recorded", query)
            recorded = False
    page = _reread()
    found = tuple((f.network, f.handle) for f in facts)
    ids = tuple(e.id for e in kept if e.id not in unstored)
    if not recorded or (failed is not None and not facts):
        status_failed: SearchStatus = failed or "error"
        return PaidSearchOutcome(status_failed, UNAVAILABLE_TEXT, query, credits, (), page, ids)
    status: SearchStatus = "searched" if credits else "cached"
    message = None if facts else NO_NEW_TEXT
    logger.info(
        "discover paid: tenant=%s query=%r status=%s credits=%s accounts=%s version=%s",
        tenant_id,
        query,
        status,
        credits,
        len(facts),
        PAID_SEARCH_VERSION,
    )
    return PaidSearchOutcome(status, message, query, credits, found, page, ids)


__all__ = [
    "DAILY_CAP_TEXT",
    "FEATURE",
    "FEW_RESULTS_TEXT",
    "INSTAGRAM_TEXT",
    "MONTHLY_CAP_TEXT",
    "NETWORK",
    "NO_NEW_TEXT",
    "PAID_SEARCH_VERSION",
    "PATH",
    "RUBRO_QUERIES",
    "SEARCH_BUTTON",
    "SEARCH_DAY_CAP",
    "SEARCH_MAX_CREDITS",
    "SEARCH_MAX_PAGES",
    "SEARCH_MONTH_CAP",
    "UNAVAILABLE_TEXT",
    "MemoryPaidSearchPool",
    "PaidSearchOutcome",
    "PaidSearchPool",
    "PostgresPaidSearchPool",
    "SearchBudget",
    "accounts_from_pages",
    "budget",
    "build_query",
    "place_for",
    "region_claims",
    "search_more_accounts",
    "search_params",
]
