"""Creator / brand discovery PROTOTYPE over the Scrape Creators search endpoints.

Goal (2026-09-11): a Mercado-Libre-style search for accounts compatible with a Brand
Kit profile — country, city, niche, follower band, engagement — fed by the vendor the
Brand Kit "Ya tengo redes" flow already uses (`scrapecreators_client`). This is a
test bench, not the product: it writes its result to a JSON file under
`Qualify/fixtures/` so the output can be inspected before anything is persisted to a
table. No Postgres, no tenant scoping — on purpose. Since 2026-09-11 the Brand Kit wizard
calls the phased search at the bottom of this module (`PhasedDiscovery`, section
"Brand Kit integration"); it still owns no Reflex state of its own.

What the vendor gives and what it does not (docs.scrapecreators.com, read 2026-09-11,
then MEASURED LIVE the same day — two runs, 18 credits, CO / Cúcuta / food_drink +
travel, raw payloads kept under `fixtures/discovery_raw/`):

  - TikTok HASHTAG search (`/v1/tiktok/search/hashtag`, city-composed `#cucutafood`)
    is the productive source: 16 local food accounts per page, each with bio
    (`signature`), `region` = CO, the video's stats and its co-occurring hashtags.
    BUT its `author.follower_count` is 0 for every account — treated as unknown and
    filled by `enrich` (one profile read per candidate).
  - TikTok KEYWORD search (`/v1/tiktok/search/keyword`) takes `query=`, not
    `keyword=` (HTTP 400 `missing_parameter` otherwise): 30 videos per page and, unlike
    the hashtag feed, REAL follower counts in `author`. With `region=CO` and
    "foodie Cucuta" / "viajes Cucuta" it produced most of the matches.
  - TikTok USER search (`/v1/tiktok/search/users`) returned 0 users for both two-word
    queries — queued last so a small budget never reaches it.
  - Instagram has NO user search. `/v2/instagram/reels/search` is Google-indexed: free
    text ("foodie Cucuta") returned reels from Japan and Australia with NO
    `follower_count` on `owner` (the docs say there is one) and no `location`; the
    city-composed hashtag ("cucutafood") returned HTTP 404 `not_found` = nothing
    indexed. Instagram discovery needs another path (the `edge_related_profiles` the
    Brand Kit profile read already pays for, or a hashtag/location endpoint).
  - None of the search endpoints filter by niche, city, follower band or engagement.
    Every one of those is applied HERE, programmatically, after the fetch — the API
    only takes a query string (and, on TikTok, a `region`).
  - Engagement here = (likes + comments) per video SEEN / followers. Search surfaces an
    account's best-performing videos, so this over-estimates (34% for a 34k account
    is not a weekly average). It ranks candidates; it is not the figure to show a
    user. The honest number needs the account's recent video list
    (`scrapecreators_client.fetch_recent_posts`, 1 more credit per candidate).

Hashtags are nested PROVISIONALLY inside the niche taxonomy (`NICHE_TAXONOMY`): each
niche carries the hashtags it fans out to, and the city is composed into them
(`#cucutafood`, `#foodcucuta`). That table is a first guess to run the experiment, not
a curated taxonomy — it is the thing to move into a database once the shape of a
useful result is known.

Credits: every request is 1 credit. `max_credits` is a hard cap per run because the
development key holds a few dozen credits at a time — the run stops cleanly when the
budget is spent and reports how many queries it did and did not execute.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

# The seed read from the brand's own account and the pure tables it stands on moved to
# the backend (m-24852195) so a worker can build it without the Reflex app. The names
# this module uses are imported back; the `X as X` ones are re-exported for the callers
# that still reach them as `creator_discovery.X`.
from qualify_api.referentes.discovery_seed import (
    _GENERIC_HASHTAGS as _GENERIC_HASHTAGS,
)
from qualify_api.referentes.discovery_seed import (
    CHOSEN_HASHTAGS as CHOSEN_HASHTAGS,
)
from qualify_api.referentes.discovery_seed import (
    COUNTRIES,
    NICHE_TAXONOMY,
    PHASED_PLAN_VERSION,
    WEAK_CITY_SLUGS,
    DiscoverySeed,
    _city_in,
    _fold,
    _mentions_country,
    _slug,
    _stems,
    country_name,
    detect_niches,
    named_countries,
    resolve_niche,
)
from qualify_api.referentes.discovery_seed import (
    NICHE_LABELS as NICHE_LABELS,
)
from qualify_api.referentes.discovery_seed import (
    SECTOR_CATALOG_TAGS as SECTOR_CATALOG_TAGS,
)
from qualify_api.referentes.discovery_seed import (
    _is_place_tag as _is_place_tag,
)
from qualify_api.referentes.discovery_seed import (
    _is_place_tag_anywhere as _is_place_tag_anywhere,
)
from qualify_api.referentes.discovery_seed import (
    detect_location as detect_location,
)
from qualify_api.referentes.discovery_seed import (
    seed_from_profile as seed_from_profile,
)
from qualify_api.referentes.discovery_seed import (
    split_terms as split_terms,
)
from qualify_api.referentes.scrapecreators_client import (
    _TIMEOUT_SECONDS,
    ScrapeCreatorsError,
    _get,
)

logger = logging.getLogger(__name__)

#: Where a run writes its result. One file per (country, city, niches) — overwritten
#: on each run, like `brand_connect_profile.json`, and gitignored the same way.
DISCOVERY_DIR = Path(__file__).resolve().parent / "fixtures"

#: Bumped when the output shape changes so a stale file is recognisable.
DISCOVERY_SCHEMA = 1

#: Default per-run credit cap. Small on purpose: the dev key had 30 credits on
#: 2026-09-11 and one exploratory run must not eat them all.
DEFAULT_MAX_CREDITS = 8

#: Follower bands, market shorthand → numeric range. Used by the CLI (`--band micro`)
#: and reported back on every candidate.
FOLLOWER_BANDS: dict[str, tuple[int, int | None]] = {
    "nano": (1_000, 10_000),
    "micro": (10_000, 100_000),
    "mid": (100_000, 500_000),
    "macro": (500_000, 1_000_000),
    "mega": (1_000_000, None),
}


#: Local evidence per city: the city itself plus the neighbourhood / metro-area names a
#: bio would use instead. PROVISIONAL, same status as the taxonomy.
CITY_KEYWORDS: dict[str, list[str]] = {
    "cucuta": [
        r"cucuta",
        r"norte de santander",
        r"motilon",
        r"los patios",
        r"villa del rosario",
        r"\bnds\b",
        r"frontera",
    ],
}

_FALLBACK_NICHE = "lifestyle"


# --------------------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------------------


def _hashtags_in(text: str) -> list[str]:
    return [tag.lower() for tag in re.findall(r"#(\w+)", text or "")]


def is_local(text: str, city: str) -> bool:
    folded = _fold(text)
    patterns = CITY_KEYWORDS.get(_slug(city), [re.escape(_fold(city))])
    return any(re.search(pattern, folded) for pattern in patterns)


# --------------------------------------------------------------------------------------
# Filters (the JSON the caller sends) and queries (what we send to the vendor)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryFilters:
    country_code: str
    city: str
    niches: tuple[str, ...]
    follower_min: int | None = None
    follower_max: int | None = None
    engagement_rate_min: float | None = None
    limit: int = 50
    networks: tuple[str, ...] = ("tiktok", "instagram")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DiscoveryFilters:
        """Parse the agreed request shape::

        {"filters": {"location": {"country_code": "CO", "city": "Cucuta"},
                     "niche": ["food_drink", "travel"],
                     "follower_range": {"min": 10000, "max": 100000},
                     "engagement_rate_min": 2.5},
         "limit": 50}
        """
        filters = payload.get("filters", payload)
        location = filters.get("location", {})
        follower_range = filters.get("follower_range") or {}
        niches = filters.get("niche") or filters.get("niches") or []
        if isinstance(niches, str):
            niches = [niches]
        networks = payload.get("networks") or filters.get("networks") or ("tiktok", "instagram")
        return cls(
            country_code=str(location.get("country_code", "")).upper(),
            city=str(location.get("city", "")),
            niches=tuple(resolve_niche(n) for n in niches),
            follower_min=follower_range.get("min"),
            follower_max=follower_range.get("max"),
            engagement_rate_min=filters.get("engagement_rate_min"),
            limit=int(payload.get("limit", 50)),
            networks=tuple(networks),
        )


@dataclass(frozen=True)
class Query:
    network: str  # "tiktok" | "instagram"
    kind: str  # "users" | "keyword" | "hashtag" | "reels"
    term: str
    niche: str

    @property
    def label(self) -> str:
        prefix = "#" if self.kind == "hashtag" else ""
        return f"{self.network}:{self.kind}:{prefix}{self.term}"


def hashtags_for(niche: str, city: str) -> list[str]:
    """The provisional hashtag nest for one niche in one city: `food` → `cucutafood`,
    `foodcucuta`, then the bare `food` as the last resort (city-agnostic, noisier)."""
    city_slug = _slug(city)
    out: list[str] = []
    for tag in NICHE_TAXONOMY[niche]["hashtags"]:
        if city_slug:
            out.extend([f"{city_slug}{tag}", f"{tag}{city_slug}"])
        out.append(tag)
    # de-dupe, keep order
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def build_queries(filters: DiscoveryFilters, *, per_niche: int = 1) -> list[Query]:
    """Fan a filter set out into vendor queries, most productive first so a small credit
    budget spends itself where the first live run (2026-09-11) found signal.

    Per niche, with `per_niche=1`: one TikTok hashtag search, one TikTok keyword
    search, one Instagram reels search — and, last, one TikTok user search.

    Measured live: the city-composed HASHTAG (`#cucutafood`) returned 16 local accounts
    with bio + region + video stats; the Instagram reels search is Google-indexed, so it
    is sent the same composed hashtag (`cucutafood`) instead of free text ("foodie
    Cucuta" returned reels from Japan and Australia); the TikTok USER search returned 0
    for the two-word queries, so it is queued last and gets the bare niche term + city.
    """
    queries: list[Query] = []
    city = filters.city.strip()
    for niche in filters.niches:
        spec = NICHE_TAXONOMY[niche]
        terms = [f"{q} {city}".strip() for q in spec["queries"][:per_niche]]
        tags = hashtags_for(niche, city)[:per_niche]
        if "tiktok" in filters.networks:
            queries.extend(Query("tiktok", "hashtag", t, niche) for t in tags)
            queries.extend(Query("tiktok", "keyword", t, niche) for t in terms)
        if "instagram" in filters.networks:
            queries.extend(Query("instagram", "reels", t, niche) for t in tags)
    if "tiktok" in filters.networks:
        for niche in filters.niches:
            spec = NICHE_TAXONOMY[niche]
            queries.extend(
                Query("tiktok", "users", f"{q} {city}".strip(), niche)
                for q in spec["queries"][:per_niche]
            )
    return queries


# --------------------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------------------


@dataclass
class Candidate:
    network: str
    username: str
    full_name: str = ""
    bio: str = ""
    followers: int | None = None
    #: Lifetime likes when a profile read carried them (TikTok `stats.heartCount`).
    total_likes: int | None = None
    is_verified: bool = False
    is_private: bool = False
    country_code: str | None = None  # evidence from the vendor (TikTok `region`, IG location)
    posts_seen: int = 0
    likes_seen: int = 0
    comments_seen: int = 0
    views_seen: int = 0
    texts: list[str] = field(default_factory=list)  # captions seen, for niche/local evidence
    hashtags_seen: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    profile_url: str = ""
    #: The link the profile points at (Instagram `external_url`, TikTok `bioLink.link`)
    #: — kept with the full bio (§ 2026-10-01): where the business actually lives.
    external_url: str = ""
    #: Of `posts_seen`, how many carried the platform's own "made with AI" label
    #: (TikTok `aigc_info`, read on the search feeds; § 2026-10-01). The card shows
    #: the share so an AI account is told apart at a glance.
    ai_posts_seen: int = 0
    #: The vendor's picture URL, when a payload carried one. Signed and short-lived
    #: on TikTok's CDN (hours), so it is never rendered directly — `avatar_path`
    #: hands it to the backend proxy (`avatar_proxy.py`), which fetches it once while
    #: it is still valid and keeps the bytes on disk.
    avatar: str = ""
    # filled by `classify`
    is_local: bool = False
    detected_niches: list[str] = field(default_factory=list)
    engagement_rate: float | None = None
    follower_band: str | None = None
    exclusion_reasons: list[str] = field(default_factory=list)
    # filled by the AI review (`run_phase`, `AccountReviewer`) — empty when unreviewed
    #: What the account IS: marca / creador / medio / otro.
    account_kind: str = ""
    #: The reviewer's one-line reason, shown to the operator.
    review_reason: str = ""
    #: Who reviewed it (model id) — provenance of `account_kind` and of the drop.
    reviewed_by: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.network, self.username.lower())

    def evidence_text(self) -> str:
        return " ".join([self.bio, *self.texts])

    def absorb_post(
        self,
        *,
        likes: object,
        comments: object,
        views: object,
        text: str,
        ai_generated: bool | None = None,
    ) -> None:
        self.posts_seen += 1
        if ai_generated:
            self.ai_posts_seen += 1
        self.likes_seen += likes if isinstance(likes, int) else 0
        self.comments_seen += comments if isinstance(comments, int) else 0
        self.views_seen += views if isinstance(views, int) else 0
        if text:
            self.texts.append(text)
            for tag in _hashtags_in(text):
                if tag not in self.hashtags_seen:
                    self.hashtags_seen.append(tag)

    def merge(self, other: Candidate) -> None:
        """Fold a second sighting of the same account into this one."""
        self.full_name = self.full_name or other.full_name
        self.bio = self.bio or other.bio
        self.followers = self.followers if self.followers is not None else other.followers
        self.total_likes = self.total_likes if self.total_likes is not None else other.total_likes
        self.is_verified = self.is_verified or other.is_verified
        self.is_private = self.is_private or other.is_private
        self.country_code = self.country_code or other.country_code
        self.profile_url = self.profile_url or other.profile_url
        self.external_url = self.external_url or other.external_url
        self.avatar = self.avatar or other.avatar
        self.posts_seen += other.posts_seen
        self.ai_posts_seen += other.ai_posts_seen
        self.likes_seen += other.likes_seen
        self.comments_seen += other.comments_seen
        self.views_seen += other.views_seen
        self.texts.extend(other.texts)
        for tag in other.hashtags_seen:
            if tag not in self.hashtags_seen:
                self.hashtags_seen.append(tag)
        for src in other.sources:
            if src not in self.sources:
                self.sources.append(src)


def follower_band(followers: int | None) -> str | None:
    if followers is None:
        return None
    for name, (low, high) in FOLLOWER_BANDS.items():
        if followers >= low and (high is None or followers < high):
            return name
    return "under_nano"


def classify(candidate: Candidate, filters: DiscoveryFilters) -> Candidate:
    """Apply the programmatic filters, in the order the experiment defined them:
    country (strict, vendor evidence) → local (city in bio/caption) → niche (regex over
    bio/caption) → follower band → engagement. Every failed step is RECORDED, not
    silently dropped, so the raw dump explains why an account is not in the result."""
    reasons: list[str] = []
    text = candidate.evidence_text()

    candidate.is_local = is_local(text, filters.city) if filters.city else True
    candidate.detected_niches = detect_niches(text) or [_FALLBACK_NICHE]
    candidate.follower_band = follower_band(candidate.followers)
    if candidate.posts_seen and candidate.followers:
        interactions = candidate.likes_seen + candidate.comments_seen
        candidate.engagement_rate = round(
            (interactions / candidate.posts_seen) / candidate.followers * 100, 2
        )
    else:
        candidate.engagement_rate = None

    # 1. Country — strict where the vendor gave evidence; a local mention counts as
    #    evidence too (a bio saying "Cúcuta" is in Colombia). Unknown is excluded but
    #    labelled as unknown, not as foreign.
    if filters.country_code:
        if candidate.country_code and candidate.country_code.upper() != filters.country_code:
            reasons.append(f"country:{candidate.country_code}")
        elif not candidate.country_code and not candidate.is_local:
            reasons.append("country:unknown")
    # 2. City
    if filters.city and not candidate.is_local:
        reasons.append("not_local")
    # 3. Niche
    if filters.niches and not set(candidate.detected_niches) & set(filters.niches):
        reasons.append("niche:" + ",".join(candidate.detected_niches))
    # 4. Followers
    if candidate.followers is None:
        if filters.follower_min is not None or filters.follower_max is not None:
            reasons.append("followers:unknown")
    else:
        if filters.follower_min is not None and candidate.followers < filters.follower_min:
            reasons.append("followers:below_min")
        if filters.follower_max is not None and candidate.followers > filters.follower_max:
            reasons.append("followers:above_max")
    # 5. Engagement — unknown is not zero: excluded with its own reason.
    if filters.engagement_rate_min is not None:
        if candidate.engagement_rate is None:
            reasons.append("engagement:unknown")
        elif candidate.engagement_rate < filters.engagement_rate_min:
            reasons.append("engagement:below_min")

    candidate.exclusion_reasons = reasons
    return candidate


# --------------------------------------------------------------------------------------
# Vendor payload → candidates
# --------------------------------------------------------------------------------------


def _tiktok_avatar(user: dict[str, Any]) -> str:
    """The account's picture out of any TikTok user object. The feeds and the user
    search carry `avatar_larger`/`avatar_medium`/… as `{uri, url_list}` objects; a
    profile read carries `avatarLarger`/`avatarMedium`/… as plain URLs.

    SMALLEST first (revised 2026-09-14, "más rápido cargar las imágenes"): every
    place a card's picture renders is round and ≤72px (`_avatar`'s `size` argument in
    `creative_wizard_pages.py`) — `avatar_larger` can run past 100 KB for a busy,
    logo-style picture (measured live: `malejopizza`, 132 KB) for zero visible gain
    at that size, while `avatar_168x168`/`avatar_thumb` are a few KB and look
    identical once scaled down. `avatar_larger`/`avatarLarger` stay as the last
    resort, for a payload that only ever carries the one size."""
    for key in (
        "avatar_168x168",
        "avatar_thumb",
        "avatarThumb",
        "avatar_medium",
        "avatarMedium",
        "avatar_300x300",
        "avatar_larger",
        "avatarLarger",
    ):
        value = user.get(key)
        if isinstance(value, dict):
            urls = value.get("url_list")
            if isinstance(urls, list):
                picked = _renderable_url([u for u in urls if isinstance(u, str) and u])
                if picked:
                    return picked
        elif isinstance(value, str) and value.startswith("http"):
            return value
    return ""


#: Formats a browser renders. TikTok's `url_list` is `[heic, heic, jpeg]` for one and
#: the same picture (measured 2026-09-14 on every author in `fixtures/discovery_raw/`),
#: and HEIC renders nowhere but Safari — the first entry is the WRONG one to keep.
_RENDERABLE_EXTENSIONS = (".jpeg", ".jpg", ".webp", ".png")


def _renderable_url(urls: list[str]) -> str:
    """The `url_list` entry to keep: a browser-renderable format first, then anything
    that is not HEIC, then — only if that is all there is — the first one (the
    avatar proxy converts HEIC server-side as a last resort)."""
    if not urls:
        return ""

    def path(url: str) -> str:
        return url.split("?", 1)[0].lower()

    for url in urls:
        if path(url).endswith(_RENDERABLE_EXTENSIONS):
            return url
    for url in urls:
        if not path(url).endswith((".heic", ".heif")):
            return url
    return urls[0]


def _tiktok_author(author: dict[str, Any], source: str) -> Candidate | None:
    username = str(author.get("unique_id") or "")
    if not username:
        return None
    followers = author.get("follower_count")
    verification = author.get("verification_type")
    # Measured live 2026-09-11: the author object inside the hashtag/keyword video
    # feeds carries `follower_count: 0` for every account (TikTok trims the counts in
    # search feeds) — an account with a 264k-view video does not have zero followers.
    # Zero from a feed is therefore "unknown", to be filled by `enrich`.
    return Candidate(
        network="tiktok",
        username=username,
        full_name=str(author.get("nickname") or ""),
        bio=str(author.get("signature") or ""),
        followers=followers if isinstance(followers, int) and followers > 0 else None,
        is_verified=bool(author.get("is_verified")) or verification == 1,
        is_private=bool(author.get("is_private_account")),
        country_code=(str(author["region"]).upper() if author.get("region") else None),
        sources=[source],
        profile_url=f"https://www.tiktok.com/@{username}",
        avatar=_tiktok_avatar(author),
    )


def candidates_from_tiktok_users(payload: dict[str, Any], source: str) -> list[Candidate]:
    out: list[Candidate] = []
    for item in payload.get("users") or []:
        info = item.get("user_info") if isinstance(item, dict) else None
        if not isinstance(info, dict):
            continue
        candidate = _tiktok_author(info, source)
        if candidate:
            out.append(candidate)
    return out


def candidates_from_tiktok_videos(payload: dict[str, Any], source: str) -> list[Candidate]:
    """Both `/search/keyword` (`search_item_list[].aweme_info`) and `/search/hashtag`
    (`aweme_list[]`) — the video object is the same shape once unwrapped."""
    videos: list[dict[str, Any]] = []
    for item in payload.get("search_item_list") or []:
        info = item.get("aweme_info") if isinstance(item, dict) else None
        if isinstance(info, dict):
            videos.append(info)
    videos.extend(v for v in (payload.get("aweme_list") or []) if isinstance(v, dict))

    out: list[Candidate] = []
    for video in videos:
        author = video.get("author")
        if not isinstance(author, dict):
            continue
        candidate = _tiktok_author(author, source)
        if candidate is None:
            continue
        stats = video.get("statistics") or {}
        text = str(video.get("desc") or "")
        for extra in video.get("text_extra") or []:
            name = extra.get("hashtag_name") if isinstance(extra, dict) else None
            if name and f"#{name}" not in text:
                text += f" #{name}"
        candidate.absorb_post(
            likes=stats.get("digg_count"),
            comments=stats.get("comment_count"),
            views=stats.get("play_count"),
            text=text,
            ai_generated=_video_is_ai(video),
        )
        out.append(candidate)
    return out


def _video_is_ai(video: Mapping[str, Any]) -> bool | None:
    """TikTok's own "AI-generated content" label on a feed video (`aigc_info`,
    measured live 2026-10-01: present on the keyword and hashtag feeds unless the read
    was trimmed). None when the video says nothing — never "not AI"."""
    info = video.get("aigc_info")
    if not isinstance(info, dict):
        return None
    label_type = info.get("aigc_label_type")
    return bool(info.get("created_by_ai")) or (isinstance(label_type, int) and label_type != 0)


def _ig_location_country(location: object) -> tuple[str | None, str | None]:
    if not isinstance(location, dict):
        return None, None
    raw = location.get("address_json")
    address: dict[str, Any] = {}
    if isinstance(raw, str):
        try:
            address = json.loads(raw)
        except ValueError:
            address = {}
    elif isinstance(raw, dict):
        address = raw
    country = address.get("country_code")
    city = address.get("city_name")
    return (str(country).upper() if country else None, str(city) if city else None)


def candidates_from_instagram_reels(payload: dict[str, Any], source: str) -> list[Candidate]:
    out: list[Candidate] = []
    for reel in payload.get("reels") or []:
        if not isinstance(reel, dict):
            continue
        owner = reel.get("owner")
        if not isinstance(owner, dict) or not owner.get("username"):
            continue
        username = str(owner["username"])
        followers = owner.get("follower_count")
        country, city = _ig_location_country(reel.get("location"))
        text = str(reel.get("caption") or "")
        location_name = (reel.get("location") or {}).get("name") if reel.get("location") else None
        if location_name:
            text += f" [{location_name}]"
        if city:
            text += f" [{city}]"
        candidate = Candidate(
            network="instagram",
            username=username,
            full_name=str(owner.get("full_name") or ""),
            followers=followers if isinstance(followers, int) else None,
            is_verified=bool(owner.get("is_verified")),
            is_private=bool(owner.get("is_private")),
            country_code=country,
            sources=[source],
            profile_url=f"https://www.instagram.com/{username}/",
            avatar=str(owner.get("profile_pic_url") or ""),
        )
        candidate.absorb_post(
            likes=reel.get("like_count"),
            comments=reel.get("comment_count"),
            views=None,
            text=text,
        )
        out.append(candidate)
    return out


_ENDPOINTS: dict[tuple[str, str], tuple[str, str]] = {
    ("tiktok", "users"): ("/v1/tiktok/search/users", "query"),
    # `query`, not `keyword` — the docs' example is ambiguous; `keyword=` returned
    # HTTP 400 `missing_parameter` live (2026-09-11).
    ("tiktok", "keyword"): ("/v1/tiktok/search/keyword", "query"),
    ("tiktok", "hashtag"): ("/v1/tiktok/search/hashtag", "hashtag"),
    ("instagram", "reels"): ("/v2/instagram/reels/search", "query"),
}

_PARSERS = {
    ("tiktok", "users"): candidates_from_tiktok_users,
    ("tiktok", "keyword"): candidates_from_tiktok_videos,
    ("tiktok", "hashtag"): candidates_from_tiktok_videos,
    ("instagram", "reels"): candidates_from_instagram_reels,
}


#: A vendor call that fails with a 5xx or a network error is tried once more after
#: this pause — the keyword search answered 500 for one query and 200 for the next
#: within the same second (measured 2026-09-11, three times in one afternoon).
_RETRY_DELAY_SECONDS = 1.5


#: The vendor's answers are remembered across searches and tenants (§ 2026-10-01: "primero
#: busca en la db, luego al scraper"): a run's `client` may carry a `payload_cache` —
#: anything with `get(path, params) -> payload | None` and `put(path, params, payload,
#: status=)` — and `_get_retry` asks it before the network, answers it after. A 404 is
#: remembered as a payload with this status, so a handle that does not exist is not
#: looked up twice either. The cache is global data (the pool, `qualify_api.creators`):
#: what one tenant's search fetched serves the next one inside the answer's TTL.
NOT_FOUND_STATUS = 404


def _get_retry(client: httpx.Client, path: str, params: dict[str, str]) -> dict[str, Any]:
    cache = getattr(client, "payload_cache", None)
    if cache is not None:
        hit = cache.get(path, params)
        if hit is not None:
            if hit.status == NOT_FOUND_STATUS:
                raise ScrapeCreatorsError(
                    f"Scrape Creators {path} answered 404 (remembered)", status_code=404
                )
            # served from the pool: nothing was charged for it this time
            return {**hit.payload, "credits_charged": 0}
    try:
        payload = _get(client, path, params)
    except ScrapeCreatorsError as exc:
        if exc.status_code == NOT_FOUND_STATUS:
            if cache is not None:
                cache.put(path, params, {}, status=NOT_FOUND_STATUS)
            raise
        if exc.status_code is not None and exc.status_code < 500:
            raise
        time.sleep(_RETRY_DELAY_SECONDS)
        payload = _get(client, path, params)
    if cache is not None:
        charged = payload.get("credits_charged")
        cache.put(path, params, payload, credits_charged=charged if isinstance(charged, int) else 1)
    return payload


class PoolClient(httpx.Client):
    """An `httpx.Client` that carries the pool's payload cache for `_get_retry`."""

    def __init__(self, payload_cache: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.payload_cache = payload_cache


def run_query_pages(
    client: httpx.Client,
    query: Query,
    *,
    region: str | None = None,
    raw_dir: Path | None = None,
    pages: int = 1,
) -> tuple[list[Candidate], int]:
    """One vendor search → `(candidates, pages actually fetched)`, `pages` deep — 1
    credit per page. TikTok's video searches page with `cursor` / `has_more` (measured
    live 2026-09-11: 30 videos per page, cursor 0 → 30 → 60). A search answers by
    relevance, not by size, so a bigger sample is the only way to see the bigger
    accounts. With `raw_dir`, each untouched
    response is written to `<raw_dir>/<label>[_pN].json` first — the payload is what a
    later table would hold, and it is the only way to verify shapes without spending."""
    path, param = _ENDPOINTS[(query.network, query.kind)]
    params = {param: query.term}
    if region and query.network == "tiktok" and query.kind != "users":
        params["region"] = region
    found: list[Candidate] = []
    cursor: str | None = None
    for page in range(max(pages, 1)):
        if cursor:
            params["cursor"] = cursor
        payload = _get_retry(client, path, params)
        if raw_dir is not None:
            _dump_raw(raw_dir, query.label + (f" p{page + 1}" if page else ""), payload)
        found.extend(_PARSERS[(query.network, query.kind)](payload, query.label))
        next_cursor = payload.get("cursor")
        if not payload.get("has_more") or next_cursor in (None, "") or str(next_cursor) == cursor:
            break
        cursor = str(next_cursor)
    return found, page + 1


def run_query(
    client: httpx.Client,
    query: Query,
    *,
    region: str | None = None,
    raw_dir: Path | None = None,
    pages: int = 1,
) -> list[Candidate]:
    """`run_query_pages` without the page count — what the CLI experiment calls."""
    return run_query_pages(client, query, region=region, raw_dir=raw_dir, pages=pages)[0]


def _dump_raw(raw_dir: Path, label: str, payload: dict[str, Any]) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / (re.sub(r"[^a-z0-9]+", "_", _fold(label)).strip("_") + ".json")
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


# --------------------------------------------------------------------------------------
# Enrichment — a profile read per candidate, 1 credit each, ONLY for the ones that
# would match if their follower count were known.
# --------------------------------------------------------------------------------------

_PROFILE_ENDPOINT = {
    "tiktok": ("/v1/tiktok/profile", "handle"),
    "instagram": ("/v1/instagram/profile", "handle"),
}


@dataclass(frozen=True)
class ProfileFacts:
    """What one profile read says about an account, network-agnostic."""

    followers: int | None
    bio: str
    total_likes: int | None = None
    is_private: bool = False
    is_verified: bool = False
    category: str = ""
    related: tuple[str, ...] = ()
    full_name: str = ""
    avatar: str = ""
    #: The link the profile points at, when the read carried one.
    external_url: str = ""
    #: The captions of the account's most recent posts, when the read carried them
    #: (Instagram: `edge_owner_to_timeline_media`, the last 12 — measured live
    #: 2026-09-25 on `mouredev`: 12 posts, 58 hashtags). The only place an Instagram
    #: account found by Google, by related-profile walk or by mirroring shows the
    #: hashtags it uses; before, those reads kept the count and dropped the posts.
    captions: tuple[str, ...] = ()


#: Recent captions kept per profile read — Instagram serves 12, the cap is a ceiling.
PROFILE_CAPTIONS = 12


def _instagram_captions(user: dict[str, Any]) -> tuple[str, ...]:
    edges = (user.get("edge_owner_to_timeline_media") or {}).get("edges") or []
    out: list[str] = []
    for edge in edges[:PROFILE_CAPTIONS]:
        node = edge.get("node") if isinstance(edge, dict) else None
        captions = ((node or {}).get("edge_media_to_caption") or {}).get("edges") or []
        first = captions[0] if captions and isinstance(captions[0], dict) else {}
        text = str((first.get("node") or {}).get("text") or "").strip()
        if text:
            out.append(text)
    return tuple(out)


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def profile_facts(network: str, payload: dict[str, Any]) -> ProfileFacts:
    """The two documented profile shapes (`scrapecreators_client._normalize_tiktok` /
    `_normalize_instagram` know them), reduced to what the discovery ranks and
    filters on. Instagram's `edge_related_profiles` are its own "similar accounts" —
    measured live 2026-09-11 on `mouredev`: `midu.dev`, `carlosazaustre`,
    `nategentile7`, `aristidevs`… — exactly the sector's referentes, for free."""
    if network == "tiktok":
        stats = payload.get("stats") or {}
        user = payload.get("user") or {}
        return ProfileFacts(
            followers=_int(stats.get("followerCount")),
            bio=str(user.get("signature") or ""),
            total_likes=_int(stats.get("heartCount") or stats.get("heart")),
            is_private=bool(user.get("privateAccount")),
            is_verified=bool(user.get("verified")),
            full_name=str(user.get("nickname") or ""),
            avatar=_tiktok_avatar(user),
            external_url=str((user.get("bioLink") or {}).get("link") or "")
            if isinstance(user.get("bioLink"), dict)
            else "",
        )
    user = (payload.get("data") or {}).get("user") or {}
    edges = (user.get("edge_related_profiles") or {}).get("edges") or []
    related = tuple(
        str(e["node"]["username"])
        for e in edges
        if isinstance(e, dict)
        and isinstance(e.get("node"), dict)
        and e["node"].get("username")
        and not e["node"].get("is_private")
    )
    category = next(
        (
            str(v)
            for v in (
                user.get("category_name"),
                user.get("business_category_name"),
                user.get("overall_category_name"),
            )
            if isinstance(v, str) and v and v != "None"
        ),
        "",
    )
    return ProfileFacts(
        followers=_int((user.get("edge_followed_by") or {}).get("count")),
        bio=str(user.get("biography") or ""),
        is_private=bool(user.get("is_private")),
        is_verified=bool(user.get("is_verified")),
        category=category,
        related=related,
        full_name=str(user.get("full_name") or ""),
        avatar=str(user.get("profile_pic_url_hd") or user.get("profile_pic_url") or ""),
        external_url=str(user.get("external_url") or ""),
        captions=_instagram_captions(user),
    )


def _apply_facts(candidate: Candidate, facts: ProfileFacts, source: str) -> None:
    candidate.followers = facts.followers
    candidate.total_likes = (
        facts.total_likes if facts.total_likes is not None else candidate.total_likes
    )
    candidate.bio = facts.bio or candidate.bio
    candidate.full_name = candidate.full_name or facts.full_name
    candidate.external_url = facts.external_url or candidate.external_url
    # a profile read is the freshest sighting: its (signed, expiring) URL wins
    candidate.avatar = facts.avatar or candidate.avatar
    candidate.is_private = candidate.is_private or facts.is_private
    candidate.is_verified = candidate.is_verified or facts.is_verified
    if facts.category and facts.category not in candidate.texts:
        candidate.texts.append(facts.category)
    # The posts' words are evidence (niche, place, relevance) and their hashtags are what
    # the catalog learns from. Not `absorb_post`: a profile read is not a feed sighting,
    # and its posts must not move the engagement numbers the ranking reads.
    for caption in facts.captions:
        if caption in candidate.texts:
            continue
        candidate.texts.append(caption)
        for tag in _hashtags_in(caption):
            if tag not in candidate.hashtags_seen:
                candidate.hashtags_seen.append(tag)
    if source not in candidate.sources:
        candidate.sources.append(source)


def _worth_enriching(candidate: Candidate) -> bool:
    """True when the ONLY thing between this account and a match is a number the
    search feed did not carry (followers, hence engagement)."""
    blocking = {r for r in candidate.exclusion_reasons if not r.startswith("engagement:")}
    return blocking <= {"followers:unknown"} and "followers:unknown" in blocking


def enrich(
    candidates: list[Candidate],
    filters: DiscoveryFilters,
    *,
    client: httpx.Client,
    budget: int,
    raw_dir: Path | None = None,
) -> tuple[int, list[str]]:
    """Spend up to `budget` credits reading the profile of the most promising
    unknown-follower candidates (most interactions per post first — the only ranking
    signal available before followers are known), then re-classify them.
    Returns `(credits_spent, errors)`."""
    spent = 0
    errors: list[str] = []
    queue = [c for c in candidates if _worth_enriching(c)]
    queue.sort(key=lambda c: (c.likes_seen + c.comments_seen) / max(c.posts_seen, 1), reverse=True)
    for candidate in queue:
        if spent >= budget:
            break
        path, param = _PROFILE_ENDPOINT[candidate.network]
        spent += 1
        try:
            payload = _get(client, path, {param: candidate.username})
        except ScrapeCreatorsError as exc:
            errors.append(f"enrich {candidate.network}:@{candidate.username}: {exc}")
            continue
        if raw_dir is not None:
            _dump_raw(raw_dir, f"profile {candidate.network} {candidate.username}", payload)
        _apply_facts(
            candidate, profile_facts(candidate.network, payload), f"{candidate.network}:profile"
        )
        classify(candidate, filters)
        logger.info(
            "enrich %s:@%s -> followers=%s er=%s reasons=%s",
            candidate.network,
            candidate.username,
            candidate.followers,
            candidate.engagement_rate,
            candidate.exclusion_reasons,
        )
    return spent, errors


# --------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------


@dataclass
class DiscoveryResult:
    filters: DiscoveryFilters
    queries_run: list[str]
    queries_skipped: list[str]
    credits_used: int
    errors: list[str]
    matched: list[Candidate]
    excluded: list[Candidate]
    fetched_at: int
    #: Hashtags that co-occurred with the searches AND mention the city — the data-driven
    #: candidates for growing the provisional nest in `NICHE_TAXONOMY`
    #: (`comidacucuta`, `cucutagastronomica`, ... measured live 2026-09-11).
    discovered_hashtags: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DISCOVERY_SCHEMA,
            "fetchedAt": self.fetched_at,
            "filters": asdict(self.filters),
            "creditsUsed": self.credits_used,
            "queriesRun": self.queries_run,
            "queriesSkipped": self.queries_skipped,
            "errors": self.errors,
            "discoveredHashtags": self.discovered_hashtags,
            "matched": [asdict(c) for c in self.matched],
            "excluded": [asdict(c) for c in self.excluded],
        }


def discovered_hashtags(candidates: list[Candidate], city: str) -> dict[str, int]:
    city_slug = _slug(city)
    counts: dict[str, int] = {}
    for candidate in candidates:
        for tag in candidate.hashtags_seen:
            if city_slug and city_slug in _slug(tag):
                counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _rank_key(candidate: Candidate) -> tuple[float, int]:
    return (candidate.engagement_rate or 0.0, candidate.followers or 0)


def discover(
    filters: DiscoveryFilters,
    *,
    client: httpx.Client | None = None,
    max_credits: int = DEFAULT_MAX_CREDITS,
    per_niche: int = 1,
    enrich_budget: int = 0,
    raw_dir: Path | None = None,
) -> DiscoveryResult:
    """Fan the filters out into vendor queries, stop at `max_credits`, merge every
    sighting per (network, username), classify, optionally spend `enrich_budget` more
    credits on profile reads for the candidates blocked only by an unknown follower
    count, and rank the survivors by engagement then followers. Only `raw_dir` writes
    to disk here (the untouched vendor payloads) — the result file is `save_result`."""
    queries = build_queries(filters, per_niche=per_niche)
    pool: dict[tuple[str, str], Candidate] = {}
    run: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    credits = 0

    own_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        for query in queries:
            if credits >= max_credits:
                skipped.append(query.label)
                continue
            credits += 1
            try:
                found = run_query(
                    active, query, region=filters.country_code or None, raw_dir=raw_dir
                )
            except ScrapeCreatorsError as exc:
                errors.append(f"{query.label}: {exc}")
                run.append(query.label)
                continue
            run.append(query.label)
            logger.info("discovery %s -> %d sightings", query.label, len(found))
            for candidate in found:
                existing = pool.get(candidate.key)
                if existing is None:
                    pool[candidate.key] = candidate
                else:
                    existing.merge(candidate)

        for candidate in pool.values():
            classify(candidate, filters)
        if enrich_budget > 0:
            spent, enrich_errors = enrich(
                list(pool.values()), filters, client=active, budget=enrich_budget, raw_dir=raw_dir
            )
            credits += spent
            errors.extend(enrich_errors)
    finally:
        if own_client:
            active.close()

    matched = [c for c in pool.values() if not c.exclusion_reasons]
    excluded = [c for c in pool.values() if c.exclusion_reasons]
    matched.sort(key=_rank_key, reverse=True)
    excluded.sort(key=_rank_key, reverse=True)
    return DiscoveryResult(
        filters=filters,
        queries_run=run,
        queries_skipped=skipped,
        credits_used=credits,
        errors=errors,
        matched=matched[: filters.limit],
        excluded=excluded,
        fetched_at=int(time.time()),
        discovered_hashtags=discovered_hashtags(list(pool.values()), filters.city),
    )


def result_path(filters: DiscoveryFilters, *, directory: Path = DISCOVERY_DIR) -> Path:
    name = "_".join(
        p for p in (filters.country_code.lower(), _slug(filters.city), *filters.niches) if p
    )
    return directory / f"discovery_{name or 'run'}.json"


def save_result(result: DiscoveryResult, *, directory: Path = DISCOVERY_DIR) -> Path:
    path = result_path(result.filters, directory=directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# Brand Kit integration (2026-09-11) — a seed read from the profile, then a search in
# three phases: the sector's most influential accounts, then the country's, then the
# city's. What the wizard (`creative_wizard_pages.BrandConnectState.run_discovery`)
# calls; the CLI below stays the lab bench for the filter-JSON experiment.
# --------------------------------------------------------------------------------------


#: Phase keys, in the order they run and render.
PHASES: tuple[str, ...] = ("sector", "national", "local")

#: Accounts shown per phase, and how many of them each network is guaranteed when it
#: has that many — the rest of the slots go to the biggest accounts regardless of
#: network. Without the guarantee a phase would be all-TikTok or all-Instagram
#: depending on which sample happened to be larger.
MAX_PER_PHASE = 8
PER_NETWORK_FLOOR = 4

#: Profile reads the local phase may spend on TikTok candidates whose follower count
#: the hashtag feed hid (it reports 0 for everyone, measured 2026-09-11).
LOCAL_ENRICH_BUDGET = 3

#: TikTok search pages per query, per phase (30 videos each, 1 credit each). The sector
#: phase digs deepest: a search answers by relevance, and the biggest accounts of a
#: sector are not necessarily on page one (measured 2026-09-11: `mouredev`, 405K on
#: TikTok, was on neither of the first two pages for "programacion").
TIKTOK_PAGES: dict[str, int] = {"sector": 2, "national": 2, "local": 1}

#: Profile reads per phase AND per network (1 credit each, 0 when the vendor's 30-day
#: cache answers — both `/v1/tiktok/profile` and `/v1/instagram/profile` honour
#: `cache_max_age`, measured 2026-09-11). Neither network has a usable ACCOUNT search
#: (TikTok's `/search/users` answers empty for everything, Instagram has none), so
#: accounts come from Google restricted to each site, from the other network's
#: biggest accounts looked up under the same handle, and — Instagram only — from each
#: read profile's related accounts; every one of them costs a read to learn its size.
PROFILE_READS: dict[str, int] = {"sector": 12, "national": 8, "local": 8}

#: Of those reads, how many go to the accounts Google returned before the walk turns
#: to mirrors and neighbours — the neighbours of the biggest accounts found so far are
#: where a sector's other big creators are (measured 2026-09-11: `mouredev`'s related
#: are `midu.dev`, `carlosazaustre`, `nategentile7`, `aristidevs`…), and reading every
#: Google hit first used to exhaust the budget before any neighbour was reached.
GOOGLE_READS = 6

#: Reads per phase spent looking up the other network's biggest accounts under the
#: SAME handle. Creators keep one handle across networks far more often than not
#: (measured 2026-09-11: `mouredev` — 405K on TikTok, 611K on Instagram — was
#: reachable this way and through nothing else), and a handle that does not exist
#: answers 404, which costs nothing.
MIRROR_READS = 4

#: The discovery's own HTTP timeout — the vendor's hashtag search took over the
#: client's default 20 s once (a `ReadTimeout` on `#cucutafood`, 2026-09-11).
_DISCOVERY_TIMEOUT_SECONDS = 45.0

#: The vendor caches a profile read for this long when asked to; a cached answer is
#: free. Discovery never needs a fresher follower count than this.
_PROFILE_CACHE_MAX_AGE = "30d"

#: Where the results and the profile reads are remembered: Postgres, per tenant, with
#: a time to live (`qualify_api.referentes`: phases in `brand_discovery_phases` for 7
#: days, profile reads in `creator_profile_cache` for 30 — § 2026-10-01, "no quiero
#: más json"). This module only knows the in-memory `ProfileStore` a run carries; the
#: wizard hands it the Postgres-backed one (`creator_cache_provider.PostgresProfileStore`).

#: Vendor calls in flight at once. A phase used to be ~40 sequential calls of 1-5 s
#: each — minutes; the vendor has no rate limit and the calls are independent. Since
#: both networks walk at once (`_run_networks`, 2026-10-01) a round is up to twelve
#: reads (`GOOGLE_READS` per network): enough workers for it to be one wave.
PARALLEL_CALLS = 12


@dataclass
class PhaseResult:
    key: str
    title: str
    accounts: list[Candidate] = field(default_factory=list)
    #: Why the phase is empty, when it is — shown instead of a blank list.
    note: str = ""
    queries: list[str] = field(default_factory=list)
    credits: int = 0
    errors: list[str] = field(default_factory=list)
    #: Accounts the AI review said do not fit the brand — dropped, kept for the report.
    discarded: list[Candidate] = field(default_factory=list)
    #: The review ran and failed: the phase fell back to the unreviewed pick, and a
    #: caller that stores phases must not keep it (the next run should review it).
    review_failed: bool = False


#: Search terms per sector phase — the account's own topical hashtags first, then the
#: taxonomy's sector terms, de-duplicated. Four TikTok queries at 2 pages and three
#: Google pages is the widest net a run casts. (`_is_place_tag`, `SECTOR_CATALOG_TAGS`
#: and `CHOSEN_HASHTAGS` moved to `qualify_api.referentes.discovery_seed`, m-24852197,
#: for the hashtag catalog that now lives in the backend.)
SECTOR_OWN_TAGS = 2
SECTOR_TERMS = 4


def sector_terms(seed: DiscoverySeed) -> list[str]:
    """The sector phase's search terms: the operator's own words for the rubro first
    (`terms`), then up to `SECTOR_OWN_TAGS` of the account's own non-place hashtags
    (`#programacion`), then the taxonomy's sector terms for each niche (`queries[0]`,
    `queries[2:]`), until `SECTOR_TERMS`. All of them, not one: the own words and
    hashtags find the account's actual peers, the taxonomy's phrasings find the
    sector's biggest creators (measured 2026-09-11: `mouredev` only surfaced for
    "aprende a programar")."""
    terms = list(seed.terms)
    terms.extend([tag for tag in seed.hashtags if not _is_place_tag(tag, seed)][:SECTOR_OWN_TAGS])
    catalog_tags = [
        tag
        for tag in seed.steering_hashtags()
        if not _is_place_tag(tag, seed) and _slug(tag) not in {_slug(t) for t in terms}
    ]
    cap = CHOSEN_HASHTAGS if seed.chosen_hashtags else SECTOR_CATALOG_TAGS
    from_catalog = catalog_tags[:cap]
    terms.extend(from_catalog)
    for niche in seed.niches[:2]:
        queries = NICHE_TAXONOMY[niche]["queries"]
        for term in [queries[0], *queries[2:]]:
            if _slug(term) not in {_slug(t) for t in terms}:
                terms.append(term)
    return terms[: SECTOR_TERMS + len(from_catalog)]


def head_term(seed: DiscoverySeed) -> str:
    """The one term a city or country is appended to: the operator's own words when
    given, else the taxonomy's head term for the niche."""
    if seed.terms:
        return seed.terms[0]
    return NICHE_TAXONOMY[seed.niches[0]]["queries"][0] if seed.niches else ""


#: How many rubro terms the local phase pairs with the city (one TikTok keyword search
#: each, one page — `TIKTOK_PAGES["local"]`), so at most this many credits more than the
#: single-term plan it replaced.
LOCAL_TERMS = 3


def local_terms(seed: DiscoverySeed) -> list[str]:
    """The rubro terms the city is appended to in the local phase, most specific first:
    the head term, the national term, then the operator's first hashtag pill that is
    not a place (`#smashburger`). De-duplicated as slugs, at most `LOCAL_TERMS`."""
    candidates = [head_term(seed), *national_terms(seed)]
    candidates.extend(t for t in seed.chosen_hashtags if not _is_place_tag(t, seed))
    out: list[str] = []
    seen: set[str] = set()
    for term in candidates:
        slug = _slug(term)
        if term and slug and slug not in seen:
            seen.add(slug)
            out.append(term)
        if len(out) == LOCAL_TERMS:
            break
    return out


def national_terms(seed: DiscoverySeed) -> list[str]:
    if seed.terms:
        return [seed.terms[0]]
    return [NICHE_TAXONOMY[n]["queries"][1] for n in seed.niches[:2]]


def google_terms(key: str, seed: DiscoverySeed) -> list[str]:
    """The Google searches feeding the account side of one phase — same scoping as the
    TikTok video plan (`phase_queries`)."""
    if key == "sector":
        return sector_terms(seed)[:3]
    if key == "national":
        name = country_name(seed.country_code)
        return [f"{t} {name}" for t in national_terms(seed)] if name else []
    return [f"{t} {seed.city}" for t in local_terms(seed)[:2]] if seed.city else []


#: The owner's words for the two place-scoped phases (NAV-11, m-24849129).
SIMILAR_PREFIX = "Negocios parecidos al tuyo"


def phase_title(key: str, seed: DiscoverySeed) -> str:
    """The phase's title as the owner reads it on the search screen (NAV-11,
    m-24849129): the place-scoped phases name the businesses, not «referentes»."""
    if key == "sector":
        return "Referentes del sector"
    if key == "national":
        name = country_name(seed.country_code)
        return f"{SIMILAR_PREFIX} en {name}" if name else f"{SIMILAR_PREFIX} en tu país"
    return f"{SIMILAR_PREFIX} en {seed.city}" if seed.city else f"{SIMILAR_PREFIX} cerca de ti"


def owner_phase_title(key: str, title: str) -> str:
    """A stored phase title in today's words: searches saved before NAV-11 (m-24849129)
    kept «Referentes en …» / «Referentes nacionales» / «Referentes locales» in the
    database, and a saved search renders its stored title as it is."""
    if key not in ("national", "local"):
        return title
    if title == "Referentes nacionales":
        return f"{SIMILAR_PREFIX} en tu país"
    if title == "Referentes locales":
        return f"{SIMILAR_PREFIX} cerca de ti"
    if title.startswith("Referentes en "):
        return f"{SIMILAR_PREFIX} en {title.removeprefix('Referentes en ')}"
    return title


def phase_queries(key: str, seed: DiscoverySeed) -> list[tuple[Query, str | None]]:
    """`(query, region)` pairs for one phase — at most three credits each.

    - sector: no region — the most influential accounts regardless of where they are.
      When the account has hashtags of its own that are not about a place, its top
      two ARE the queries (`#programacion`, `#software`); only without them does the
      taxonomy's head term per niche stand in. Measured live 2026-09-11 on midu.dev:
      the broad head terms ("tecnología", "educación") surface news outlets with
      millions of followers that posted one video on the topic, and they out-rank
      every specialist once influence is follower-ranked.
    - national: the niche's second term + the country name, `region` pinned.
    - local: up to `LOCAL_TERMS` rubro terms + the city (`local_terms`: the head term,
      then the national term, then the operator's first hashtag pill), `region`
      pinned, plus ONE city hashtag — the account's own city hashtag when it has one
      (`#cucutafood` from its own captions), else the provisional composed one
      (`hashtags_for`). One term used to be the whole plan, and a niche rubro in a
      small city came back empty (2026-10-05).
    All keyword searches, except that last hashtag: the keyword feed carries real
    follower counts, the hashtag feed does not (the local phase enriches for that).
    """
    niches = seed.niches[:2]
    if key == "sector":
        label = ",".join(niches)
        return [(Query("tiktok", "keyword", term, label), None) for term in sector_terms(seed)]
    label = ",".join(niches) or "rubro"
    if key == "national":
        name = country_name(seed.country_code)
        if not name:
            return []
        return [
            (Query("tiktok", "keyword", f"{term} {name}", label), seed.country_code)
            for term in national_terms(seed)
        ]
    head = head_term(seed)
    if not seed.city or not head:
        return []
    region = seed.country_code or None
    city_slug = _slug(seed.city)
    own_city_tags = [tag for tag in seed.hashtags if city_slug and city_slug in _slug(tag)]
    plan = [
        (Query("tiktok", "keyword", f"{term} {seed.city}", label), region)
        for term in local_terms(seed)
    ]
    if own_city_tags:
        plan.append((Query("tiktok", "hashtag", own_city_tags[0], label), region))
    elif niches:
        composed = hashtags_for(niches[0], seed.city)[0]
        plan.append((Query("tiktok", "hashtag", composed, label), region))
    else:
        # A rubro outside the taxonomy has no niche to compose a city hashtag from: the
        # catalog's best hashtag for it stands in (`cucutaburgers`).
        catalog_tags = [t for t in seed.steering_hashtags() if not _is_place_tag(t, seed)]
        if catalog_tags:
            plan.append(
                (Query("tiktok", "hashtag", f"{city_slug}{catalog_tags[0]}", label), region)
            )
    return plan


def _has_country_evidence(candidate: Candidate, code: str) -> bool:
    """Whether the account's own words place it in `code`.

    Three tiers, strongest first: the structured location an Instagram reel carries,
    the country named in the text (name, demonym, flag), and finally one of the
    country's cities. That last tier is the circumstantial one and it is where a
    shared name used to leak an account into the wrong country — a Spanish account
    saying "Valencia" counted as Venezuelan and vice versa. So a weak city name
    (`WEAK_CITY_SLUGS`: shared by two countries, or an ordinary word) is evidence
    only while no OTHER country is named in the same text; an unambiguous one
    (Maracaibo, Cúcuta, Guayaquil) still stands on its own."""
    country = COUNTRIES.get(code.upper())
    if country is None:
        return False
    if candidate.country_code and candidate.country_code.upper() == code.upper():
        return True
    text = candidate.evidence_text()
    if _mentions_country(text, code):
        return True
    named_elsewhere = [c for c in named_countries(text) if c != code.upper()]
    tag_slugs = [_slug(t) for t in candidate.hashtags_seen]
    for city in country.cities:
        if not _city_in(text, tag_slugs, city):
            continue
        if _slug(city) in WEAK_CITY_SLUGS and named_elsewhere:
            continue
        return True
    return False


def relevance_stems(seed: DiscoverySeed) -> set[str]:
    stems = _stems(" ".join(seed.terms))
    for tag in (*seed.hashtags, *seed.steering_hashtags()):
        if not _is_place_tag(tag, seed):
            stems |= _stems(tag)
    return stems


def _about_the_sector(candidate: Candidate, seed: DiscoverySeed) -> bool:
    """Whether the account's own words (bio, category, the captions the search
    surfaced) mention the rubro: the taxonomy's keywords when the niche is known,
    and the stems of the operator's own words / the account's own hashtags for any
    rubro at all. Only the sector phase requires it: its searches are broad
    ("programación" also means a TV schedule — `@olgaenvivo`, "stream art", surfaced
    for it; a business-news outlet surfaced for "software"), while a city or country
    term already scopes the other two, whose accounts often carry nothing but an
    address in the bio."""
    stems = relevance_stems(seed)
    if not seed.niches and not stems:
        return True
    evidence = candidate.evidence_text()
    if seed.niches and set(detect_niches(evidence)) & set(seed.niches):
        return True
    folded = _fold(evidence)
    return any(stem in folded for stem in stems)


def _fits_phase(key: str, candidate: Candidate, seed: DiscoverySeed) -> bool:
    local = bool(seed.city) and is_local(candidate.evidence_text(), seed.city)
    if key == "sector":
        return _about_the_sector(candidate, seed)
    if key == "local":
        return local
    if key == "national":
        # A local account is reserved for the local phase, where it is the point.
        return _has_country_evidence(candidate, seed.country_code) and not local
    return True


#: News outlets and TV channels rank first on followers in any sector search (measured
#: 2026-09-11: @bbcnews, @skynews, @tvn for "software") but are not accounts a brand
#: partners with. Matched on the structured Instagram category and, for TikTok, on the
#: handle / display name / bio — PROVISIONAL, same status as the taxonomy.
_MEDIA_RE = re.compile(
    r"\bnews\b|noticias|noticiero|periodico|periodismo|\bdiario\b|\btv\b|television"
    r"|telediario|broadcast|newspaper|magazine|revista|\bradio\b|\bcanal \d"
    r"|insider|prensa|journal|herald|gazette|informativo"
)


def _is_media_outlet(candidate: Candidate) -> bool:
    fields = [candidate.username, candidate.full_name, candidate.bio]
    fields.extend(t for t in candidate.texts if len(t) < 60)  # categories, not captions
    return any(_MEDIA_RE.search(_fold(f)) for f in fields if f)


def _interactions_per_post(candidate: Candidate) -> float:
    return (candidate.likes_seen + candidate.comments_seen) / max(candidate.posts_seen, 1)


def facts_to_document(facts: ProfileFacts) -> dict[str, Any]:
    """`ProfileFacts` as the JSON document the cache keeps (`creator_profile_cache`)."""
    return {**asdict(facts), "related": list(facts.related), "captions": list(facts.captions)}


def facts_from_document(document: Mapping[str, Any]) -> ProfileFacts:
    return ProfileFacts(
        followers=_int(document.get("followers")),
        bio=str(document.get("bio") or ""),
        total_likes=_int(document.get("total_likes")),
        is_private=bool(document.get("is_private")),
        is_verified=bool(document.get("is_verified")),
        category=str(document.get("category") or ""),
        related=tuple(str(r) for r in document.get("related") or []),
        full_name=str(document.get("full_name") or ""),
        avatar=str(document.get("avatar") or ""),
        external_url=str(document.get("external_url") or ""),
        # Entries written before captions were kept have none: they fill in when the
        # entry expires, rather than spending a credit per account now.
        captions=tuple(str(c) for c in document.get("captions") or []),
    )


class ProfileStore:
    """A run's memory of profile reads: `network:handle` -> the `ProfileFacts` read, or
    the fact that the handle does not exist (a 404 is worth remembering too — mirrored
    handles miss often). In memory only (tests, the CLI): the wizard's runs carry
    `creator_cache_provider.PostgresProfileStore`, the same three methods over
    `creator_profile_cache` with its time to live. `_read_profile` is what calls it,
    from worker threads — one key at a time."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[bool, ProfileFacts | None]] = {}

    @staticmethod
    def _key(network: str, handle: str) -> str:
        return f"{network}:{_slug(handle)}"

    def get(
        self, network: str, handle: str, *, now: float | None = None
    ) -> tuple[bool, ProfileFacts | None]:
        """`(known, facts)`: known+facts for a remembered account, known+None for a
        remembered 404, unknown for anything else."""
        return self._entries.get(self._key(network, handle), (False, None))

    def put(
        self, network: str, handle: str, facts: ProfileFacts | None, *, now: float | None = None
    ) -> None:
        self._entries[self._key(network, handle)] = (True, facts)

    def save(self) -> None:
        """Nothing to flush in memory; the Postgres store writes as it goes."""


def _read_profile(
    client: httpx.Client,
    candidate: Candidate,
    raw_dir: Path | None,
    store: ProfileStore | None = None,
) -> tuple[int, ProfileFacts | None, str | None]:
    """One profile read applied to `candidate` — from the on-disk store when it
    remembers the handle, else from the vendor. Returns `(credits charged, facts,
    error)`: the vendor reports `credits_charged` itself (0 on a cache hit), and an
    error comes back as a string rather than raising, so one bad handle never ends a
    phase. Safe to call from a worker thread: it touches only `candidate` and the
    store's dict (one key)."""
    if store is not None:
        known, facts = store.get(candidate.network, candidate.username)
        if known:
            if facts is not None:
                _apply_facts(candidate, facts, f"{candidate.network}:profile")
            return 0, facts, None
    path, param = _PROFILE_ENDPOINT[candidate.network]
    params = {param: candidate.username, "cache_max_age": _PROFILE_CACHE_MAX_AGE}
    try:
        payload = _get_retry(client, path, params)
    except ScrapeCreatorsError as exc:
        if exc.status_code == 404:
            if store is not None:
                store.put(candidate.network, candidate.username, None)
            return 0, None, None  # no such account (a mirrored handle, a deleted one)
        return 1, None, f"profile {candidate.network}:@{candidate.username}: {exc}"
    if raw_dir is not None:
        _dump_raw(raw_dir, f"profile {candidate.network} {candidate.username}", payload)
    facts = profile_facts(candidate.network, payload)
    _apply_facts(candidate, facts, f"{candidate.network}:profile")
    if store is not None:
        store.put(candidate.network, candidate.username, facts)
    charged = payload.get("credits_charged")
    return (charged if isinstance(charged, int) else 1), facts, None


def lookup_account(
    network: str, handle: str, *, store: Any | None = None, payload_cache: Any | None = None
) -> tuple[Candidate, bool, str | None]:
    """One account read outside a search — the referente the operator adds by hand.
    Returns `(candidate, found, error)`: the candidate always comes back (a stub with
    its profile URL when the read missed), `found` says whether the profile exists, and
    a vendor failure is an error string, never an exception. With the pool's
    `payload_cache` a handle anyone read inside 30 days costs nothing."""
    candidate = _account_stub(network, handle, f"{network}:manual")
    active = store if store is not None else ProfileStore()
    client = (
        PoolClient(payload_cache, timeout=_DISCOVERY_TIMEOUT_SECONDS)
        if payload_cache is not None
        else httpx.Client(timeout=_DISCOVERY_TIMEOUT_SECONDS)
    )
    with client:
        _charged, facts, error = _read_profile(client, candidate, None, active)
    active.save()
    return candidate, facts is not None, error


def _run_parallel(executor: ThreadPoolExecutor | None, fn: Any, items: list[Any]) -> list[Any]:
    """`[fn(item) for item in items]`, on the executor when there is one — results in
    the items' order, so credits, queries and errors stay deterministic."""
    if executor is None or len(items) <= 1:
        return [fn(item) for item in items]
    return list(executor.map(fn, items))


NETWORKS = ("tiktok", "instagram")


def _run_networks(
    executor: ThreadPoolExecutor | None,
    result: PhaseResult,
    fn: Callable[[str, PhaseResult], None],
) -> None:
    """`fn(network, result)` for both networks. With an executor they run at the same
    time (2026-10-01: a network's walk is Google → reads → neighbours' reads, several
    vendor round trips, and Instagram's used to wait for TikTok's whole walk), each on
    its own accumulator, folded into `result` in network order afterwards — the same
    credits, queries and errors in the same order as one after the other. Safe because
    a walk only ever creates and reads candidates of its own network (the pool's keys
    are `(network, handle)`), and each one's own vendor calls still go through the
    shared executor. Without an executor (`parallel=1`) they run one after the other,
    as before."""
    if executor is None:
        for network in NETWORKS:
            fn(network, result)
        return
    partials = {n: PhaseResult(key=result.key, title=result.title) for n in NETWORKS}
    failures: dict[str, BaseException] = {}

    def run(network: str) -> None:
        try:
            fn(network, partials[network])
        except BaseException as exc:  # re-raised on the caller's thread below
            failures[network] = exc

    threads = [threading.Thread(target=run, args=(n,), daemon=True) for n in NETWORKS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for network in NETWORKS:
        if network in failures:
            raise failures[network]
        partial = partials[network]
        result.credits += partial.credits
        result.queries.extend(partial.queries)
        result.errors.extend(partial.errors)


# --------------------------------------------------------------------------------------
# Instagram — no account search exists (measured 2026-09-11: `/v2/instagram/reels/
# search` is Google-indexed and carries no follower counts; the vendor's related
# profiles come back empty for some accounts). Accounts come from two places instead:
# the vendor's Google search restricted to `site:instagram.com`, and each read
# profile's own `edge_related_profiles`, walked breadth-first under a read budget.
# --------------------------------------------------------------------------------------

_GOOGLE_ENDPOINT = "/v1/google/search"
_INSTAGRAM_URL_RE = re.compile(r"^https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{1,30})/?$")
_INSTAGRAM_RESERVED = frozenset(
    {
        "p",
        "reel",
        "reels",
        "explore",
        "popular",
        "accounts",
        "stories",
        "tv",
        "directory",
        "about",
        "legal",
        "developer",
        "api",
        "web",
    }
)


def instagram_handles_from_google(payload: dict[str, Any]) -> list[str]:
    """Usernames out of a `site:instagram.com` Google result page — profile URLs
    only (`instagram.com/<user>/`), never posts, reels or Instagram's own sections."""
    out: list[str] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        match = _INSTAGRAM_URL_RE.match(str(item.get("url") or item.get("link") or ""))
        if not match:
            continue
        handle = match.group(1)
        if handle.lower() in _INSTAGRAM_RESERVED or handle.lower() in {h.lower() for h in out}:
            continue
        out.append(handle)
    return out


_TIKTOK_URL_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]{1,30})")
_SITE = {"tiktok": "tiktok.com", "instagram": "instagram.com"}


def tiktok_handles_from_google(payload: dict[str, Any]) -> list[str]:
    """Usernames out of a `site:tiktok.com` Google result page — Google mostly returns
    video URLs (`tiktok.com/@user/video/…`, measured 2026-09-11), and the handle is in
    every one of them; `/discover/` and `/tag/` pages carry none."""
    out: list[str] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        match = _TIKTOK_URL_RE.search(str(item.get("url") or item.get("link") or ""))
        if match and match.group(1).lower() not in {h.lower() for h in out}:
            out.append(match.group(1))
    return out


def handles_from_google(network: str, payload: dict[str, Any]) -> list[str]:
    if network == "tiktok":
        return tiktok_handles_from_google(payload)
    return instagram_handles_from_google(payload)


def _account_stub(network: str, handle: str, source: str) -> Candidate:
    url = (
        f"https://www.tiktok.com/@{handle}"
        if network == "tiktok"
        else f"https://www.instagram.com/{handle}/"
    )
    return Candidate(network=network, username=handle, sources=[source], profile_url=url)


def _other(network: str) -> str:
    return "instagram" if network == "tiktok" else "tiktok"


def expand_accounts(
    key: str,
    seed: DiscoverySeed,
    network: str,
    *,
    client: httpx.Client,
    pool: dict[tuple[str, str], Candidate],
    result: PhaseResult,
    raw_dir: Path | None = None,
    budget: int | None = None,
    store: ProfileStore | None = None,
    executor: ThreadPoolExecutor | None = None,
) -> None:
    """Fill `pool` with `network` ACCOUNTS for one phase — the account-first side of
    the discovery, the same for any rubro — in rounds under one budget of charged
    credits: (1) the handles Google returns for `site:<network>` (plus, on
    Instagram's sector round, the seed's own related accounts), up to `GOOGLE_READS`
    of them read (followers, bio, category, related); (2) the related accounts of
    what was read, biggest parent first, until `budget` is spent. Google searches and
    profile reads run `PARALLEL_CALLS` at a time. The other network's accounts under
    the same handle are `mirror_accounts`, run once both networks are in."""
    budget = PROFILE_READS[key] if budget is None else budget
    queue: list[tuple[str, str]] = []
    if key == "sector" and network == "instagram":
        queue.extend((h, f"instagram:related:@{seed.handle}") for h in seed.related)

    terms = google_terms(key, seed)

    def search(term: str) -> tuple[str, dict[str, Any] | None, str | None]:
        label = f"{network}:google:{term}"
        try:
            payload = _get_retry(
                client, _GOOGLE_ENDPOINT, {"query": f"{term} site:{_SITE[network]}"}
            )
        except ScrapeCreatorsError as exc:
            return label, None, None if exc.status_code == 404 else f"{label}: {exc}"
        return label, payload, None

    for label, payload, error in _run_parallel(executor, search, terms):
        result.credits += 1
        result.queries.append(label)
        if error:
            result.errors.append(error)
        if payload is None:
            continue
        if raw_dir is not None:
            _dump_raw(raw_dir, label, payload)
        queue.extend((h, label) for h in handles_from_google(network, payload))

    own = _slug(seed.handle)
    seen: set[str] = set()
    spent = 0

    def stubs(handles: list[tuple[str, str]], limit: int) -> list[Candidate]:
        """Pool entries for up to `limit` handles not yet read — created in the main
        thread, so the reads only ever touch their own candidate."""
        out: list[Candidate] = []
        for handle, source in handles:
            if len(out) >= limit:
                break
            slug = _slug(handle)
            if not slug or slug == own or slug in seen:
                continue
            seen.add(slug)
            key_ = (network, handle.lower())
            candidate = pool.get(key_)
            if candidate is None:
                candidate = _account_stub(network, handle, source)
                pool[key_] = candidate
            elif source not in candidate.sources:
                candidate.sources.append(source)
            if candidate.followers is None:
                out.append(candidate)
        return out

    def read_all(candidates: list[Candidate]) -> list[tuple[Candidate, ProfileFacts]]:
        nonlocal spent
        outcomes = _run_parallel(
            executor, lambda c: _read_profile(client, c, raw_dir, store), candidates
        )
        read: list[tuple[Candidate, ProfileFacts]] = []
        for candidate, (charged, facts, error) in zip(candidates, outcomes):
            spent += charged
            result.credits += charged
            if error:
                result.errors.append(error)
            elif facts is not None:
                read.append((candidate, facts))
        return read

    read = read_all(stubs(queue, min(GOOGLE_READS, budget)))

    # Round two: neighbours, biggest parent first — a big account's related accounts
    # are big accounts in the same sector (Instagram carries them; TikTok never does).
    frontier = sorted(read, key=lambda pair: pair[0].followers or 0, reverse=True)
    related = [
        (h, f"{network}:related:@{parent.username}")
        for parent, facts in frontier
        for h in facts.related
    ]
    if related and spent < budget:
        read_all(stubs(related, budget - spent))


def mirror_accounts(
    seed: DiscoverySeed,
    network: str,
    *,
    client: httpx.Client,
    pool: dict[tuple[str, str], Candidate],
    result: PhaseResult,
    raw_dir: Path | None = None,
    budget: int = MIRROR_READS,
    store: ProfileStore | None = None,
    executor: ThreadPoolExecutor | None = None,
) -> None:
    """The other network's biggest accounts of the run, looked up under the same
    handle on `network` — its own round, run once BOTH networks' searches are in, so
    the bridge works in both directions (a TikTok creator found on Instagram, an
    Instagram one found on TikTok). A handle that does not exist answers 404 and
    costs nothing; one that does inherits the twin's words as evidence — same
    person. The lookups run in parallel — and so do the two networks' rounds
    (`_run_networks`), hence the snapshot of the pool: the other round adds its stubs
    to it meanwhile, none of them a twin (a stub has no follower count yet)."""
    own = _slug(seed.handle)
    twins = sorted(
        (c for c in list(pool.values()) if c.network == _other(network) and c.followers),
        key=lambda c: c.followers or 0,
        reverse=True,
    )
    pairs: list[tuple[Candidate, Candidate]] = []
    for twin in twins:
        if len(pairs) >= budget:
            break
        slug = _slug(twin.username)
        key_ = (network, twin.username.lower())
        if not slug or slug == own or key_ in pool:
            continue
        mirrored = _account_stub(network, twin.username, f"{network}:mirror:@{twin.username}")
        pool[key_] = mirrored
        pairs.append((twin, mirrored))
    outcomes = _run_parallel(
        executor, lambda pair: _read_profile(client, pair[1], raw_dir, store), pairs
    )
    for (twin, mirrored), (charged, _facts, error) in zip(pairs, outcomes):
        result.credits += charged
        if error:
            result.errors.append(error)
        if mirrored.followers is not None:
            evidence = (twin.bio, *twin.texts)
            mirrored.texts.extend(t for t in evidence if t and t not in mirrored.texts)
            mirrored.country_code = mirrored.country_code or twin.country_code


@dataclass(frozen=True)
class AccountVerdict:
    """What the AI review says about one account (`AccountReviewer`)."""

    kind: str
    fits: bool
    reason: str
    reviewed_by: str


#: `(phase key, accounts) -> verdict per account key`. Injected by the caller (the wizard
#: builds it over `qualify_api.referentes.ai.review_accounts`), so this module never
#: talks to a model itself; an account missing from the answer counts as unreviewed. It
#: may raise: the phase then falls back to the unreviewed pick (`review_failed`).
AccountReviewer = Callable[[str, list[Candidate]], Mapping[tuple[str, str], AccountVerdict]]

#: Accounts per network sent to the review: the best-ranked ones, enough that the
#: `MAX_PER_PHASE` pick (`PER_NETWORK_FLOOR` per network) still fills after the drops.
REVIEW_PER_NETWORK = 10


def _rank(candidate: Candidate) -> tuple[int, float]:
    return (candidate.followers or 0, _interactions_per_post(candidate))


def review_shortlist(eligible: list[Candidate]) -> list[Candidate]:
    """What the review reads: per network, the `REVIEW_PER_NETWORK` accounts the pick
    would reach first (followers known, best ranked) — the only ones that can end up on
    screen, so nothing is paid for an account that could never be shown."""
    by_network: dict[str, list[Candidate]] = {}
    for candidate in sorted((c for c in eligible if c.followers), key=_rank, reverse=True):
        by_network.setdefault(candidate.network, []).append(candidate)
    return [c for accounts in by_network.values() for c in accounts[:REVIEW_PER_NETWORK]]


def apply_review(
    key: str,
    eligible: list[Candidate],
    reviewer: AccountReviewer,
    result: PhaseResult,
) -> list[Candidate]:
    """The shortlist the review kept, each with its verdict on it; the ones it said do
    not fit go to `result.discarded`. On a review failure the eligible list comes back
    untouched and `result.review_failed` says so — a failed review never empties a
    phase."""
    shortlist = review_shortlist(eligible)
    if not shortlist:
        return eligible
    try:
        verdicts = reviewer(key, shortlist)
    except Exception as exc:  # the reviewer is a network call to a model
        logger.warning("referentes review failed for the %s phase: %s", key, exc)
        result.review_failed = True
        return eligible
    kept: list[Candidate] = []
    for candidate in shortlist:
        verdict = verdicts.get(candidate.key)
        if verdict is not None:
            candidate.account_kind = verdict.kind
            candidate.review_reason = verdict.reason
            candidate.reviewed_by = verdict.reviewed_by
            if not verdict.fits:
                result.discarded.append(candidate)
                continue
        kept.append(candidate)
    return kept


def _pick_accounts(eligible: list[Candidate]) -> list[Candidate]:
    """Top `MAX_PER_PHASE` by followers, each network guaranteed `PER_NETWORK_FLOOR`
    slots when it has that many accounts; ties broken by interactions per post."""
    rank = lambda c: (c.followers or 0, _interactions_per_post(c))  # noqa: E731
    by_network: dict[str, list[Candidate]] = {}
    for candidate in sorted((c for c in eligible if c.followers), key=rank, reverse=True):
        by_network.setdefault(candidate.network, []).append(candidate)
    chosen: list[Candidate] = []
    for accounts in by_network.values():
        chosen.extend(accounts[:PER_NETWORK_FLOOR])
    rest = sorted(
        (c for accounts in by_network.values() for c in accounts if c not in chosen),
        key=rank,
        reverse=True,
    )
    chosen.extend(rest[: max(MAX_PER_PHASE - len(chosen), 0)])
    return sorted(chosen, key=rank, reverse=True)[:MAX_PER_PHASE]


def run_phase(
    key: str,
    seed: DiscoverySeed,
    *,
    client: httpx.Client,
    pool: dict[tuple[str, str], Candidate],
    picked: set[tuple[str, str]],
    raw_dir: Path | None = None,
    enrich_budget: int = LOCAL_ENRICH_BUDGET,
    store: ProfileStore | None = None,
    executor: ThreadPoolExecutor | None = None,
    reviewer: AccountReviewer | None = None,
) -> PhaseResult:
    """Run one phase's TikTok searches and Instagram walk into the shared `pool`, then
    pick its most influential accounts from EVERYTHING seen so far (a national account
    surfaced by the sector search still counts) that no earlier phase already picked.
    Influence = followers, then interactions per post seen; `_pick_accounts` keeps
    both networks represented. A search the vendor answers with 404 is an empty
    result, not an error (the Instagram reels 404s of the first run).

    With a `reviewer` (version 9), the accounts the pick could reach are first reviewed
    by Claude (`apply_review`): the ones that are not real peers of the brand are
    dropped, the rest carry what they are (marca / creador / medio)."""
    result = PhaseResult(key=key, title=phase_title(key, seed))
    if key == "national" and not seed.country_code:
        result.note = "Indica tu país para ver referentes nacionales."
        return result
    if key == "local" and not seed.city:
        result.note = "Indica tu ciudad para ver referentes locales."
        return result
    plan = phase_queries(key, seed)
    if not plan and not google_terms(key, seed):
        result.note = "Indica tu rubro para buscar referentes."
        return result

    pages = TIKTOK_PAGES.get(key, 1)

    def search(item: tuple[Query, str | None]) -> tuple[Query, list[Candidate], int, str | None]:
        query, region = item
        query_pages = pages if query.kind == "keyword" else 1
        try:
            found, fetched = run_query_pages(
                client, query, region=region, raw_dir=raw_dir, pages=query_pages
            )
        except ScrapeCreatorsError as exc:
            return query, [], 1, None if exc.status_code == 404 else f"{query.label}: {exc}"
        return query, found, fetched, None

    for query, found, fetched, error in _run_parallel(executor, search, plan):
        result.queries.append(query.label)
        result.credits += fetched
        if error:
            result.errors.append(error)
        for candidate in found:
            existing = pool.get(candidate.key)
            if existing is None:
                pool[candidate.key] = candidate
            else:
                existing.merge(candidate)

    _run_networks(
        executor,
        result,
        lambda network, acc: expand_accounts(
            key,
            seed,
            network,
            client=client,
            pool=pool,
            result=acc,
            raw_dir=raw_dir,
            store=store,
            executor=executor,
        ),
    )
    _run_networks(
        executor,
        result,
        lambda network, acc: mirror_accounts(
            seed,
            network,
            client=client,
            pool=pool,
            result=acc,
            raw_dir=raw_dir,
            store=store,
            executor=executor,
        ),
    )

    # Compared as slugs: the same person is `midu.dev` on Instagram and `midudev` on
    # TikTok (measured live 2026-09-11), and a brand's Instagram search finds its own
    # profile.
    own = _slug(seed.handle)
    eligible = [
        c
        for c in pool.values()
        if c.key not in picked
        and not (own and _slug(c.username) == own)
        and not c.is_private
        and not _is_media_outlet(c)
        and _fits_phase(key, c, seed)
    ]
    if key == "local" and enrich_budget > 0:
        unknown = sorted(
            (c for c in eligible if c.followers is None and c.network == "tiktok"),
            key=_interactions_per_post,
            reverse=True,
        )
        outcomes = _run_parallel(
            executor, lambda c: _read_profile(client, c, raw_dir, store), unknown[:enrich_budget]
        )
        for charged, _facts, error in outcomes:
            result.credits += charged
            if error:
                result.errors.append(error)

    if reviewer is not None:
        eligible = apply_review(key, eligible, reviewer, result)
    result.accounts = _pick_accounts(eligible)
    picked.update(c.key for c in result.accounts)
    # A discarded account is not offered by a later phase either: it does not fit the
    # brand, whichever category would have shown it.
    picked.update(c.key for c in result.discarded)
    if not result.accounts:
        result.note = (
            f"No encontramos cuentas de {seed.city} para tu rubro todavía."
            if key == "local"
            else "Todavía no encontramos cuentas para esta fase."
        )
    return result


class PhasedDiscovery:
    """One discovery run across its phases: owns the HTTP client and the pool / picked
    sets the phases share, so a caller that renders phase by phase (the wizard's
    background event) can run them one at a time without threading that state
    through itself."""

    def __init__(
        self,
        seed: DiscoverySeed,
        *,
        client: httpx.Client | None = None,
        raw_dir: Path | None = None,
        store: Any | None = None,
        payload_cache: Any | None = None,
        parallel: int = PARALLEL_CALLS,
        reviewer: AccountReviewer | None = None,
    ) -> None:
        self.seed = seed
        self.reviewer = reviewer
        self._owns_client = client is None
        #: With a `payload_cache` (the shared pool's), every vendor answer of this run is
        #: asked of the pool first and kept in it after (`_get_retry`).
        self.client = client or (
            PoolClient(payload_cache, timeout=_DISCOVERY_TIMEOUT_SECONDS)
            if payload_cache is not None
            else httpx.Client(timeout=_DISCOVERY_TIMEOUT_SECONDS)
        )
        self.raw_dir = raw_dir
        self.pool: dict[tuple[str, str], Candidate] = {}
        self.picked: set[tuple[str, str]] = set()
        #: `ProfileStore` or anything with its `get` / `put` / `save` (the wizard's
        #: Postgres-backed one); a run of its own remembers only for itself.
        self.store = store if store is not None else ProfileStore()
        self.executor = ThreadPoolExecutor(max_workers=max(parallel, 1)) if parallel > 1 else None

    def run(self, key: str) -> PhaseResult:
        return run_phase(
            key,
            self.seed,
            client=self.client,
            pool=self.pool,
            picked=self.picked,
            raw_dir=self.raw_dir,
            store=self.store,
            executor=self.executor,
            reviewer=self.reviewer,
        )

    def run_all(self) -> list[PhaseResult]:
        return [self.run(key) for key in PHASES]

    def close(self) -> None:
        """Persists the profile store and releases the workers / client."""
        self.store.save()
        if self.executor is not None:
            self.executor.shutdown(wait=True)
        if self._owns_client:
            self.client.close()


def compact_count(value: int | None) -> str:
    """«1.2M», «92K», «640», «—» for unknown. The unit is chosen from the ROUNDED figure:
    999 950 is «1M», never «1000K». Shared with `reels_discovery`."""
    if value is None:
        return "—"
    if value >= 999_950:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    return str(value)


def _compact(value: int | None) -> str:
    return compact_count(value or None)  # a candidate's 0 reads as unknown here


def _reason(candidate: Candidate) -> str:
    """Where the account came from, readable: `#cucutafood` or `«foodie Cúcuta»`."""
    for source in candidate.sources:
        parts = source.split(":", 2)
        if len(parts) != 3:
            continue
        if parts[1] == "hashtag":
            return parts[2]
        if parts[1] in {"keyword", "users", "reels", "google"}:
            return f"«{parts[2]}»"
        if parts[1] == "related":
            return f"similar a {parts[2]}"
        if parts[1] == "mirror":
            return "también en Instagram" if parts[0] == "tiktok" else "también en TikTok"
    return ""


def _likes_label(candidate: Candidate) -> str:
    """Lifetime likes when a profile read carried them, else the likes of the videos
    the search surfaced (per video, so "top" videos are not passed off as totals)."""
    if candidate.total_likes:
        return _compact(candidate.total_likes)
    if candidate.posts_seen and candidate.likes_seen:
        return f"{_compact(round(candidate.likes_seen / candidate.posts_seen))}/vídeo"
    return ""


def account_card(candidate: Candidate) -> dict[str, str]:
    """One account in the flat `dict[str, str]` shape the Reflex state stores.

    `blurb` is the bio when there is one, else the caption of the video the search
    surfaced: measured live 2026-09-11, the KEYWORD feed's `author.signature` is null
    for every author (only the hashtag feed and a profile read carry the bio), and
    what the account actually published is the better description anyway."""
    text = candidate.bio or next((t for t in candidate.texts if t.strip()), "")
    blurb = " ".join(text.split())
    return {
        "handle": f"@{candidate.username}",
        "network": "TikTok" if candidate.network == "tiktok" else "Instagram",
        "followers": _compact(candidate.followers),
        "likes": _likes_label(candidate),
        "url": candidate.profile_url,
        "blurb": blurb[:110] + ("…" if len(blurb) > 110 else ""),
        "reason": _reason(candidate),
        "avatar": candidate.avatar,
        "kind": candidate.account_kind,
        "kind_label": KIND_LABELS.get(candidate.account_kind, ""),
        "review": candidate.review_reason,
        "reviewed_by": candidate.reviewed_by,
        # § 2026-10-01: the bio in full (web addresses, contacts) and the profile's link
        "bio": " ".join(candidate.bio.split()),
        "external_url": candidate.external_url,
        # "3/5" when 3 of the 5 videos the search saw carried the AI label; "" otherwise
        "ai": _ai_share(candidate),
        # filled per phase by `phase_to_dict` (`reach_signals`): "" or the reason
        "signal": "",
    }


#: The card's flag for `Candidate.account_kind` (`otro` shows none).
KIND_LABELS = {"marca": "Marca", "creador": "Creador", "medio": "Medio"}


#: Where the backend serves the cards' pictures from (`avatar_proxy.py`) and where it
#: keeps the bytes it fetched. NOT under the repo, on purpose (2026-09-14): Reflex's
#: dev backend on this machine is granian (no gunicorn on Windows), whose hot reload
#: watches the whole checkout and ignores only a short list of extensions — every
#: `.jpg` written under `fixtures/` restarted the backend (~100 s each, the frontend
#: recompiles on every restart). The user's cache dir is outside every watcher;
#: `QUALIFY_AVATAR_DIR` overrides it.
AVATAR_ROUTE = "/avatar"
AVATAR_DIR = Path(
    os.environ.get("QUALIFY_AVATAR_DIR") or (Path.home() / ".cache" / "qualify" / "avatars")
)


def avatar_path(card: dict[str, str]) -> str:
    """The backend path a card's picture is served from: `/avatar/<network>/<handle>`,
    plus the vendor's own URL as `u` when the card carries one, so the proxy can
    fetch it the first time (while the signature is still valid) and serve its own
    copy from then on. Empty when there is no handle to name the picture by — a card
    from a cache written before pictures existed still gets a path: the proxy has
    other ways to find it."""
    handle = str(card.get("handle") or "").lstrip("@").strip()
    if not handle:
        return ""
    network = str(card.get("network") or "").lower()
    if network not in {"tiktok", "instagram"}:
        return ""
    path = f"{AVATAR_ROUTE}/{network}/{quote(handle, safe='')}"
    vendor_url = str(card.get("avatar") or "")
    if vendor_url:
        path += "?u=" + quote(vendor_url, safe="")
    return path


def _ai_share(candidate: Candidate) -> str:
    if not candidate.ai_posts_seen:
        return ""
    return f"{candidate.ai_posts_seen}/{candidate.posts_seen}"


#: An account whose videos reach far more than its peers' while being interacted with
#: far less: the signature of paid reach (ads deliver views, not likes) or of an
#: audience that does not react — `docs/crecimiento-organico-estimacion.md` §2.2, the
#: same test the organic growth estimate runs per post, here per account against the
#: phase. Views per post over `REACH_OUTLIER` x the phase median AND likes per view
#: under `ENGAGEMENT_DEFICIT` x the phase median.
REACH_OUTLIER = 3.0
ENGAGEMENT_DEFICIT = 0.4
REACH_SIGNAL = (
    "Mucho alcance con poca interacción: señal de alcance pagado o de audiencia que no reacciona"
)


def reach_signals(accounts: Sequence[Candidate]) -> dict[tuple[str, str], str]:
    """Per account, `REACH_SIGNAL` or "" — judged against the phase's own medians, with
    at least three accounts whose feed sightings carried views."""
    measured = [
        (c, c.views_seen / c.posts_seen, c.likes_seen / c.views_seen)
        for c in accounts
        if c.posts_seen and c.views_seen
    ]
    if len(measured) < 3:
        return {}
    views_med = _median([views for _c, views, _er in measured])
    er_med = _median([er for _c, _views, er in measured])
    return {
        c.key: (
            REACH_SIGNAL
            if views > REACH_OUTLIER * views_med and er < ENGAGEMENT_DEFICIT * er_med
            else ""
        )
        for c, views, er in measured
    }


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def phase_to_dict(result: PhaseResult) -> dict[str, Any]:
    signals = reach_signals(result.accounts)
    cards = []
    for candidate in result.accounts:
        card = account_card(candidate)
        card["signal"] = signals.get(candidate.key, "")
        cards.append(card)
    return {
        "key": result.key,
        "title": result.title,
        "note": result.note,
        "accounts": cards,
        "credits": result.credits,
        "errors": result.errors,
        "discarded": [
            {
                "handle": f"@{c.username}",
                "network": "TikTok" if c.network == "tiktok" else "Instagram",
                "reason": c.review_reason,
            }
            for c in result.discarded
        ],
    }


def phase_signature(key: str, seed: DiscoverySeed) -> str:
    """What one phase's result depends on — and nothing more, so a run that only
    changed the city reuses the sector's and the country's cached phases and
    searches the city alone ("si hace falta alguna categoría, ahí sí se hace la
    búsqueda, pero solo de esa categoría")."""
    parts = [
        f"v{PHASED_PLAN_VERSION}",
        key,
        _slug(seed.handle),
        ",".join(seed.niches),
        ",".join(seed.hashtags[:3]),
        ",".join(_slug(r) for r in seed.related[:3]),
        ",".join(_slug(t) for t in seed.terms),
    ]
    if key in ("sector", "local") and seed.chosen_hashtags:
        # Only the phases that search with them: changing the pills re-runs the
        # sector and the local phase, never the national one.
        parts.append(",".join(sorted(_slug(t) for t in seed.chosen_hashtags)))
    if key in ("national", "local"):
        parts.append(seed.country_code.upper())
    if key == "local":
        parts.append(_slug(seed.city))
    return "|".join(parts)


# --------------------------------------------------------------------------------------
# CLI — `uv run --no-sync python -m Qualify.creator_discovery --city Cucuta --niche food_drink`
# --------------------------------------------------------------------------------------


def _load_dotenv() -> None:
    """Reflex loads `.env` itself; a bare `python -m` does not. Walk up from this file to
    the first `.env` (the repo root, or the main checkout's root when running from a
    worktree that has none) and export only the vendor key if it is not already set."""
    if os.environ.get("SCRAPECREATORS_API_KEY"):
        return
    for parent in Path(__file__).resolve().parents:
        env = parent / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("SCRAPECREATORS_API_KEY="):
                    os.environ["SCRAPECREATORS_API_KEY"] = (
                        line.split("=", 1)[1].strip().strip('"').strip("'")
                    )
                    return


def _print_summary(result: DiscoveryResult, path: Path) -> None:
    print(
        f"credits used: {result.credits_used}  queries run: {len(result.queries_run)}"
        f"  skipped (budget): {len(result.queries_skipped)}  errors: {len(result.errors)}"
    )
    for err in result.errors:
        print(f"  ! {err}")
    print(f"\n--- matched ({len(result.matched)}) ---")
    for c in result.matched:
        er = f"{c.engagement_rate}%" if c.engagement_rate is not None else "ER ?"
        print(
            f"  {c.network:9} @{c.username:28} {c.followers or '?':>9} {c.follower_band or '-':6}"
            f" {er:>7}  {','.join(c.detected_niches)}  via {len(c.sources)} src"
        )
    print(f"\n--- excluded ({len(result.excluded)}), first 15 by rank ---")
    for c in result.excluded[:15]:
        print(
            f"  {c.network:9} @{c.username:28} {c.followers or '?':>9}  "
            f"{' '.join(c.exclusion_reasons)}"
        )
    if result.discovered_hashtags:
        top = ", ".join(f"#{t}×{n}" for t, n in list(result.discovered_hashtags.items())[:12])
        print(f"\n--- city hashtags seen (grow the nest with these) ---\n  {top}")
    print(f"\nwritten: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--filters-json", help="path to a JSON file in the agreed request shape")
    parser.add_argument("--country", default="CO")
    parser.add_argument("--city", default="Cucuta")
    parser.add_argument("--niche", action="append", default=[])
    parser.add_argument("--band", choices=sorted(FOLLOWER_BANDS))
    parser.add_argument("--min-followers", type=int)
    parser.add_argument("--max-followers", type=int)
    parser.add_argument("--er-min", type=float, help="minimum engagement rate, percent")
    parser.add_argument("--network", action="append", choices=("tiktok", "instagram"))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-credits", type=int, default=DEFAULT_MAX_CREDITS)
    parser.add_argument(
        "--per-niche", type=int, default=1, help="queries per niche per endpoint (each is 1 credit)"
    )
    parser.add_argument(
        "--enrich",
        type=int,
        default=0,
        help="extra credits for profile reads on candidates blocked only by unknown followers",
    )
    parser.add_argument(
        "--no-raw", action="store_true", help="do not keep the raw vendor payloads on disk"
    )
    parser.add_argument("--dry-run", action="store_true", help="print the query plan, spend 0")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # bios carry emoji; cp1252 consoles choke

    if args.filters_json:
        filters = DiscoveryFilters.from_dict(json.loads(Path(args.filters_json).read_text("utf-8")))
    else:
        low, high = FOLLOWER_BANDS[args.band] if args.band else (None, None)
        filters = DiscoveryFilters(
            country_code=args.country.upper(),
            city=args.city,
            niches=tuple(resolve_niche(n) for n in (args.niche or ["food_drink"])),
            follower_min=args.min_followers if args.min_followers is not None else low,
            follower_max=args.max_followers if args.max_followers is not None else high,
            engagement_rate_min=args.er_min,
            limit=args.limit,
            networks=tuple(args.network) if args.network else ("tiktok", "instagram"),
        )

    plan = build_queries(filters, per_niche=args.per_niche)
    print(
        f"plan: {len(plan)} queries, budget {args.max_credits} credits"
        f" (+{args.enrich} for enrichment)"
    )
    for i, q in enumerate(plan, 1):
        print(f"  {'*' if i <= args.max_credits else '-'} {q.label}")
    if args.dry_run:
        return 0

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _load_dotenv()
    result = discover(
        filters,
        max_credits=args.max_credits,
        per_niche=args.per_niche,
        enrich_budget=args.enrich,
        raw_dir=None if args.no_raw else DISCOVERY_DIR / "discovery_raw",
    )
    path = save_result(result)
    _print_summary(result, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
