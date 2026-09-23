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
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .scrapecreators_client import (
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

#: Niche taxonomy — PROVISIONAL. `keywords` are regexes matched against bio / caption
#: (lower-cased, accents stripped); `queries` are the free-text searches — by
#: position: [0] the head term (local phase, city appended), [1] the national term
#: (country appended), [2:] extra sector terms (`sector_terms`); `hashtags` are the
#: hashtag searches (the city is composed in, see `hashtags_for`). Measured
#: 2026-09-11: "aprende a programar" surfaces the programming creators (mouredev,
#: brujeriatech…) that "programación" alone never did.
NICHE_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "food_drink": {
        "keywords": [
            r"foodie",
            r"comida",
            r"restaurante",
            r"gastronom",
            r"cafeter",
            r"cocina",
            r"receta",
            r"chef",
            r"brunch",
            r"postre",
            r"🍽",
            r"🍔",
            r"🍕",
        ],
        "queries": ["foodie", "comida", "restaurantes", "recetas"],
        "hashtags": ["food", "foodie", "comida"],
    },
    "fashion_beauty": {
        "keywords": [
            r"\bmodas?\b",
            r"fashion",
            r"makeup",
            r"maquillaje",
            r"outfit",
            r"\bstyle\b",
            r"belleza",
            r"beauty",
            r"skincare",
            r"peluquer",
            r"barber",
        ],
        "queries": ["moda", "makeup", "outfit", "belleza"],
        "hashtags": ["moda", "fashion", "makeup"],
    },
    "fitness_health": {
        "keywords": [
            r"\bfit",
            r"\bgym\b",
            r"entrenad",
            r"saludable",
            r"gimnasio",
            r"crossfit",
            r"nutrici",
            r"yoga",
            r"running",
            r"🏋",
            r"💪",
        ],
        "queries": ["fitness", "gym", "entrenador personal", "rutina de ejercicio"],
        "hashtags": ["fitness", "gym", "fit"],
    },
    "travel_lifestyle": {
        "keywords": [
            r"viaj",
            r"travel",
            r"blogger",
            r"turismo",
            r"estilo de vida",
            r"lifestyle",
            r"aventura",
            r"✈",
            r"🌎",
        ],
        "queries": ["viajes", "turismo", "lifestyle", "viajero"],
        "hashtags": ["travel", "viajes", "turismo"],
    },
    "real_estate": {
        "keywords": [
            r"inmobiliar",
            r"inmueble",
            r"apartamento",
            r"\bcasa[s]?\b",
            r"bienes raices",
            r"real estate",
            r"arriendo",
            r"venta de",
            r"🏠",
            r"🏡",
        ],
        "queries": [
            "inmobiliaria",
            "apartamentos en venta",
            "bienes raíces",
            "agente inmobiliario",
        ],
        "hashtags": ["inmobiliaria", "bienesraices", "apartamentos"],
    },
    # Added 2026-09-11 with the Brand Kit integration: a brand choosing its sector
    # needs more than the five niches the Cúcuta experiment started from.
    "technology": {
        "keywords": [
            r"tecnolog",
            r"technolog",
            r"software",
            r"programaci",
            r"\bprograma(?:r|dor)",
            r"programming",
            r"desarrollador",
            r"developer",
            r"javascript",
            r"python",
            r"inteligencia artificial",
            r"\bia\b",
            r"💻",
        ],
        "queries": ["programación", "tecnología", "aprende a programar", "programador"],
        "hashtags": ["tecnologia", "programacion", "tech"],
    },
    "education": {
        "keywords": [
            r"educaci",
            r"education",
            r"\bcursos?\b",
            r"profesor",
            r"docente",
            r"academ",
            r"school",
            r"colegio",
            r"📚",
        ],
        "queries": ["educación", "cursos", "aprende", "profesor"],
        "hashtags": ["educacion", "aprende", "cursos"],
    },
    "entertainment": {
        "keywords": [
            r"humor",
            r"comedia",
            r"comedian",
            r"entreten",
            r"entertain",
            r"musica",
            r"musician",
            r"cantante",
            r"artista",
            r"😂",
        ],
        "queries": ["humor", "comedia", "música", "comediante"],
        "hashtags": ["humor", "comedia", "musica"],
    },
}

#: Instagram's own business `category_name` values are English ("Restaurant",
#: "Clothing (Brand)", "Gym/Physical Fitness Center"...). Extra patterns per niche so
#: the category reads through the same `detect_niches` as a Spanish bio does.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "food_drink": [r"restaurant", r"bakery", r"\bcafe\b", r"\bfood", r"coffee", r"beverage"],
    "fashion_beauty": [r"clothing", r"cosmetic", r"salon", r"jewelry"],
    "fitness_health": [r"fitness", r"trainer", r"\bsport", r"health"],
    "travel_lifestyle": [r"hotel", r"\btour", r"travel"],
    "real_estate": [r"real estate", r"property"],
    "technology": [r"computer", r"internet", r"\bapp\b", r"electronics"],
    "education": [r"\bschool", r"tutor", r"university"],
    "entertainment": [r"music", r"artist", r"\bband\b"],
}
for _niche, _patterns in _CATEGORY_KEYWORDS.items():
    NICHE_TAXONOMY[_niche]["keywords"].extend(_patterns)

#: Spanish label per niche — what the Brand Kit's rubro select shows.
NICHE_LABELS: dict[str, str] = {
    "food_drink": "Comida y bebida",
    "fashion_beauty": "Moda y belleza",
    "fitness_health": "Fitness y salud",
    "travel_lifestyle": "Viajes y estilo de vida",
    "real_estate": "Inmobiliaria",
    "technology": "Tecnología",
    "education": "Educación",
    "entertainment": "Entretenimiento y humor",
}

#: Aliases so the filter JSON can use market spellings ("travel", "beauty", ...).
NICHE_ALIASES: dict[str, str] = {
    "food": "food_drink",
    "foodie": "food_drink",
    "gastronomia": "food_drink",
    "fashion": "fashion_beauty",
    "beauty": "fashion_beauty",
    "moda": "fashion_beauty",
    "fitness": "fitness_health",
    "health": "fitness_health",
    "gym": "fitness_health",
    "travel": "travel_lifestyle",
    "lifestyle": "travel_lifestyle",
    "viajes": "travel_lifestyle",
    "inmobiliaria": "real_estate",
    "realestate": "real_estate",
    "tech": "technology",
    "tecnologia": "technology",
    "educacion": "education",
    "humor": "entertainment",
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


def _fold(text: str) -> str:
    """Lower-case + strip accents, so `Cúcuta`, `cucuta` and `CÚCUTA` all match one
    pattern and the taxonomy regexes stay ASCII."""
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(text))


def _hashtags_in(text: str) -> list[str]:
    return [tag.lower() for tag in re.findall(r"#(\w+)", text or "")]


def resolve_niche(name: str) -> str:
    """`food_drink`, `Food & Drink`, `travel`, `Viajes` → a taxonomy key, or ValueError."""
    key = re.sub(r"[^a-z0-9]+", "_", _fold(name)).strip("_")
    if key in NICHE_TAXONOMY:
        return key
    alias = key.replace("_", "")
    if alias in NICHE_ALIASES:
        return NICHE_ALIASES[alias]
    raise ValueError(f"unknown niche {name!r}; known: {sorted(NICHE_TAXONOMY)}")


def detect_niches(text: str) -> list[str]:
    folded = _fold(text)
    return [
        niche
        for niche, spec in NICHE_TAXONOMY.items()
        if any(re.search(pattern, folded) for pattern in spec["keywords"])
    ]


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

    @property
    def key(self) -> tuple[str, str]:
        return (self.network, self.username.lower())

    def evidence_text(self) -> str:
        return " ".join([self.bio, *self.texts])

    def absorb_post(self, *, likes: object, comments: object, views: object, text: str) -> None:
        self.posts_seen += 1
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
        self.avatar = self.avatar or other.avatar
        self.posts_seen += other.posts_seen
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
        )
        out.append(candidate)
    return out


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


def _get_retry(client: httpx.Client, path: str, params: dict[str, str]) -> dict[str, Any]:
    try:
        return _get(client, path, params)
    except ScrapeCreatorsError as exc:
        if exc.status_code is not None and exc.status_code < 500:
            raise
        time.sleep(_RETRY_DELAY_SECONDS)
        return _get(client, path, params)


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
    )


def _apply_facts(candidate: Candidate, facts: ProfileFacts, source: str) -> None:
    candidate.followers = facts.followers
    candidate.total_likes = (
        facts.total_likes if facts.total_likes is not None else candidate.total_likes
    )
    candidate.bio = facts.bio or candidate.bio
    candidate.full_name = candidate.full_name or facts.full_name
    # a profile read is the freshest sighting: its (signed, expiring) URL wins
    candidate.avatar = facts.avatar or candidate.avatar
    candidate.is_private = candidate.is_private or facts.is_private
    candidate.is_verified = candidate.is_verified or facts.is_verified
    if facts.category and facts.category not in candidate.texts:
        candidate.texts.append(facts.category)
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

#: Bumped when the phase plan changes (queries, ranking, filters, the tables they read)
#: so a cached or stored result computed under the old plan is a miss instead of a stale
#: answer. Not left to memory: `test_creator_discovery_version.py` fingerprints the
#: algorithm's code and fails when it changes without a bump (5 = the 2026-09-15
#: country aliases / city lists, which shipped still stamped 4; 6 = the shared hashtag
#: catalog: the rubro's catalog hashtags join the sector queries, the local hashtag
#: query and the relevance stems — `hashtag_catalog.catalog_hashtags_for`).
PHASED_PLAN_VERSION = 6


@dataclass(frozen=True)
class Country:
    """One country the location detection and the rubro step know.

    `aliases` is what a bio calls the country when it does not spell its name: the
    demonym above all ("venezolana", "colombiano") plus the short forms people
    actually type ("vzla", "eeuu"). Matched as whole words and only from four
    characters up — "col", "mx" and "rd" appear inside too much ordinary text to be
    evidence of anything. The flag emoji is handled separately, from the ISO code.

    `cities` is the display list AND the evidence list. Keep it to the real metros:
    every name added is a name that can collide, and the ambiguity indexes below are
    what keep a collision from inventing a country.
    """

    name: str
    aliases: tuple[str, ...]
    cities: tuple[str, ...]


#: Countries the location detection and the rubro step know. PROVISIONAL, same status
#: as the taxonomy — LatAm first because that is where the first customers are, plus
#: Spain / US for the Spanish-speaking accounts a sector search surfaces anyway.
#:
#: Coverage is deliberately EVEN across countries (§ 2026-09-15): the list used to run
#: from 15 cities for Colombia down to one for Panamá, which made "is this account
#: from country X" a question whose answer depended on how well X happened to be
#: typed up rather than on the account. A country entered with two cities silently
#: loses every creator from its third city — `test_every_country_carries_enough_cities`
#: is the guard against adding the next one that way.
COUNTRIES: dict[str, Country] = {
    "CO": Country(
        "Colombia",
        ("colombiano", "colombiana", "colombianos", "colombianas"),
        (
            "Bogotá",
            "Medellín",
            "Cali",
            "Barranquilla",
            "Cartagena",
            "Bucaramanga",
            "Cúcuta",
            "Pereira",
            "Santa Marta",
            "Manizales",
            "Ibagué",
            "Villavicencio",
            "Pasto",
            "Montería",
            "Neiva",
        ),
    ),
    "VE": Country(
        "Venezuela",
        ("venezolano", "venezolana", "venezolanos", "venezolanas", "vzla"),
        (
            "Caracas",
            "Maracaibo",
            "Valencia",
            "Barquisimeto",
            "Maracay",
            "Ciudad Guayana",
            "Puerto Ordaz",
            "San Cristóbal",
            "Puerto La Cruz",
            "Mérida",
            "Barcelona",
            "Maturín",
            "Barinas",
            "Cumaná",
            "Punto Fijo",
        ),
    ),
    "MX": Country(
        "México",
        ("mexicano", "mexicana", "mexicanos", "mexicanas"),
        (
            "Ciudad de México",
            "Guadalajara",
            "Monterrey",
            "Puebla",
            "Tijuana",
            "Cancún",
            "Mérida",
            "Querétaro",
            "León",
            "Toluca",
            "Ciudad Juárez",
            "Mexicali",
            "Culiacán",
            "Aguascalientes",
            "Morelia",
        ),
    ),
    "AR": Country(
        "Argentina",
        ("argentino", "argentina", "argentinos", "argentinas"),
        (
            "Buenos Aires",
            "Córdoba",
            "Rosario",
            "Mendoza",
            "La Plata",
            "Mar del Plata",
            "San Miguel de Tucumán",
            "Salta",
            "Santa Fe",
            "Neuquén",
            "Bariloche",
        ),
    ),
    "CL": Country(
        "Chile",
        ("chileno", "chilena", "chilenos", "chilenas"),
        (
            "Santiago de Chile",
            "Valparaíso",
            "Viña del Mar",
            "Concepción",
            "Antofagasta",
            "La Serena",
            "Temuco",
            "Iquique",
            "Puerto Montt",
        ),
    ),
    "PE": Country(
        "Perú",
        ("peruano", "peruana", "peruanos", "peruanas"),
        (
            "Lima",
            "Arequipa",
            "Cusco",
            "Trujillo",
            "Chiclayo",
            "Piura",
            "Iquitos",
            "Huancayo",
            "Tacna",
        ),
    ),
    "EC": Country(
        "Ecuador",
        ("ecuatoriano", "ecuatoriana", "ecuatorianos", "ecuatorianas"),
        (
            "Quito",
            "Guayaquil",
            "Cuenca",
            "Ambato",
            "Manta",
            "Machala",
            "Portoviejo",
            "Loja",
            "Esmeraldas",
        ),
    ),
    "PA": Country(
        "Panamá",
        ("panameño", "panameña", "panameños", "panameñas"),
        (
            "Ciudad de Panamá",
            "Colón",
            "David",
            "Chitré",
            "Penonomé",
            "Bocas del Toro",
            "La Chorrera",
            "Arraiján",
        ),
    ),
    "DO": Country(
        "República Dominicana",
        ("dominicano", "dominicana", "dominicanos", "dominicanas", "quisqueya"),
        (
            "Santo Domingo",
            "Santiago de los Caballeros",
            "Punta Cana",
            "La Romana",
            "Puerto Plata",
            "San Pedro de Macorís",
            "Bávaro",
            "San Francisco de Macorís",
        ),
    ),
    "ES": Country(
        "España",
        ("español", "española", "españoles", "españolas", "spain"),
        (
            "Madrid",
            "Barcelona",
            "Sevilla",
            "Valencia",
            "Málaga",
            "Bilbao",
            "Zaragoza",
            "Murcia",
            "Alicante",
            "Córdoba",
            "Valladolid",
            "Granada",
            "Vigo",
            "San Sebastián",
            "Palma de Mallorca",
        ),
    ),
    "US": Country(
        "Estados Unidos",
        # NOT "usa": three letters, and in Spanish it is the verb ("usa este código").
        ("eeuu", "estadounidense", "united states"),
        (
            "Miami",
            "Nueva York",
            "Los Ángeles",
            "Houston",
            "Chicago",
            "Orlando",
            "Dallas",
            "Atlanta",
            "San Francisco",
            "Las Vegas",
            "Phoenix",
            "Boston",
            "Seattle",
            "San Antonio",
            "San Diego",
        ),
    ),
}

#: City names too generic to name a country BY THEMSELVES — either because more than
#: one country in the table has them (computed: Valencia and Barcelona are Spanish and
#: Venezuelan, Mérida is Mexican and Venezuelan, Córdoba is Argentine and Spanish,
#: Santiago… is three countries' prefix) or because the word is ordinary Spanish or a
#: person's name (listed: `salta` is a verb, `david` and `rosario` are names, `granada`
#: and `palma` are fruit and tree, `manta` is a blanket).
#:
#: This is THE generalization (§ 2026-09-15): a weak name never decides a country on
#: its own — it needs the country named alongside it. Adding a country later cannot
#: reintroduce the bug, because the ambiguous half of this set is DERIVED from the
#: table rather than listed.
_COMMON_WORD_CITY_SLUGS = frozenset(
    {"salta", "david", "colon", "rosario", "mendoza", "manta", "granada", "leon", "concepcion"}
)


def _city_country_index() -> dict[str, frozenset[str]]:
    index: dict[str, set[str]] = {}
    for code, country in COUNTRIES.items():
        for city in country.cities:
            index.setdefault(_slug(city), set()).add(code)
    return {slug: frozenset(codes) for slug, codes in index.items()}


#: City slug → the countries claiming it. Derived, never hand-maintained.
CITY_COUNTRIES: dict[str, frozenset[str]] = _city_country_index()

#: The slugs that may not decide a country alone: shared by two countries, or an
#: ordinary word.
WEAK_CITY_SLUGS: frozenset[str] = frozenset(
    {slug for slug, codes in CITY_COUNTRIES.items() if len(codes) > 1} | _COMMON_WORD_CITY_SLUGS
)

#: Hashtags that say nothing about what an account is about — dropped from the
#: account's own vocabulary before it seeds a search.
_GENERIC_HASHTAGS = frozenset(
    {
        "capcut",
        "explore",
        "explorepage",
        "follow",
        "foryou",
        "foryoupage",
        "fy",
        "fyp",
        "instagood",
        "instagram",
        "like",
        "love",
        "parati",
        "paratii",
        "reel",
        "reels",
        "tendencia",
        "tiktok",
        "trend",
        "trending",
        "viral",
        "viralvideo",
        "xyzbca",
    }
)

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

#: The whole-result cache — one entry per seed signature, so walking the wizard again
#: with the same account and answers costs zero credits. Gitignored with the other
#: `discovery_*.json` outputs.
DISCOVERY_CACHE_PATH = DISCOVERY_DIR / "discovery_cache.json"
_CACHE_TTL_SECONDS = 7 * 24 * 3600
_CACHE_MAX_ENTRIES = 60

#: Profile reads remembered on disk ("de manera provisional por ahora" — a JSON under
#: `fixtures/` until a table exists): an account's size, bio and related accounts
#: change slowly, and a walk repeated with a different city should not re-read the
#: sector's accounts. Same 30 days the vendor's own cache keeps.
PROFILE_CACHE_PATH = DISCOVERY_DIR / "discovery_profiles.json"
_PROFILE_CACHE_TTL_SECONDS = 30 * 24 * 3600

#: Vendor calls in flight at once. A phase used to be ~40 sequential calls of 1-5 s
#: each — minutes; the vendor has no rate limit and the calls are independent.
PARALLEL_CALLS = 6


def _flag(code: str) -> str:
    """ISO code → flag emoji (`CO` → the Colombian flag): bios mark a country with it
    as often as with the name."""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code.upper())


def country_name(code: str) -> str:
    country = COUNTRIES.get(code.upper())
    return country.name if country else ""


#: Below this, an alias is a substring of too much ordinary text to be evidence —
#: see `Country.aliases`.
_MIN_ALIAS_LENGTH = 4


def _mentions_country(text: str, code: str) -> bool:
    """Whether the text names `code` explicitly — by name, by demonym or short form,
    or by flag emoji. Never by a city: a city is circumstantial (`_city_evidence`),
    a name is not."""
    country = COUNTRIES.get(code.upper())
    if country is None:
        return False
    folded = _fold(text)
    name = _fold(country.name)
    if name and (re.search(rf"\b{re.escape(name)}\b", folded) or _slug(name) in _slug(text)):
        return True
    for alias in country.aliases:
        folded_alias = _fold(alias)
        if len(folded_alias) >= _MIN_ALIAS_LENGTH and re.search(
            rf"\b{re.escape(folded_alias)}\b", folded
        ):
            return True
    return _flag(code) in text


def named_countries(text: str) -> list[str]:
    """Every country the text names explicitly, in table order. Empty for a text that
    only drops a city name."""
    return [code for code in COUNTRIES if _mentions_country(text, code)]


def _city_in(text: str, tag_slugs: list[str], city: str) -> bool:
    """Word match on the folded text, or — for names long enough not to collide with
    ordinary words (`cali` is in `calidad`) — a substring of a hashtag
    (`#cucutafood`)."""
    key = _fold(city)
    slug = _slug(city)
    if re.search(rf"\b{re.escape(key)}\b", _fold(text)):
        return True
    return len(slug) >= 6 and any(slug in tag for tag in tag_slugs)


def detect_location(
    text: str,
    hashtags: list[str] | tuple[str, ...] = (),
    *,
    country_hint: str = "",
) -> tuple[str, str]:
    """`(country code, city)` read from a bio / category / hashtags, `""` for what is
    not there.

    A named country narrows the city search to that country — `Valencia` next to
    "España" is not ambiguous, and neither is it next to "Venezuela". A city alone
    implies its country ONLY when the name belongs to one country and is not an
    ordinary word (`WEAK_CITY_SLUGS`): a bare "Valencia" yields `("", "Valencia")`,
    the city kept because it still scopes a local search, the country left blank
    rather than guessed. Guessing is what used to file Venezuelan accounts under
    Spain, and it would file Argentine ones under Spain the moment Córdoba appeared
    in both lists (§ 2026-09-15).

    `country_hint` is the country the OPERATOR already answered. It settles the
    ambiguity the same way naming the country in the text would — a Venezuelan
    business that wrote only "Valencia" in its bio is in the Venezuelan Valencia."""
    tag_slugs = [_slug(tag) for tag in hashtags]
    named = next(iter(named_countries(text)), "")
    hint = country_hint.upper() if country_hint.upper() in COUNTRIES else ""
    scope = named or hint
    for code, info in COUNTRIES.items():
        if scope and code != scope:
            continue
        for city in info.cities:
            if not _city_in(text, tag_slugs, city):
                continue
            if scope or _slug(city) not in WEAK_CITY_SLUGS:
                return code, city
            # An ambiguous name with no country named and none answered: the city is
            # real, the country is not knowable from this text.
            return "", city
    # No city matched — only what the text itself named counts, never the hint.
    return named, ""


@dataclass(frozen=True)
class DiscoverySeed:
    """Everything the phased search reads, and nothing else — so its `signature` is a
    sound cache key."""

    handle: str
    niches: tuple[str, ...]
    hashtags: tuple[str, ...] = ()
    country_code: str = ""
    city: str = ""
    #: Instagram's related accounts of the seed profile (`relatedProfiles`), the free
    #: starting point of the Instagram sector walk.
    related: tuple[str, ...] = ()
    #: The operator's own words for the rubro ("peluquería canina", "fisioterapia
    #: deportiva") — searched as typed and used as relevance stems, so the discovery
    #: works for any rubro, not only the taxonomy's. Filled by the Brand Kit's rubro
    #: step (`rubro_text`); empty when only a taxonomy category was chosen.
    terms: tuple[str, ...] = ()
    #: Hashtags the shared catalog (`hashtag_catalog.catalog_hashtags_for`, migration 0023)
    #: knows for this rubro — what the operator's words resolve to even when they are
    #: misspelled, plus the niche's most seen tags. Set by the wizard AFTER
    #: `seed_from_profile`; deliberately NOT part of `signature` / `phase_signature`: the
    #: catalog grows with every search, and a cache key that followed it would throw away
    #: a stored phase (and spend its credits again) each time it did. A result is reused
    #: for the answers that produced it; the catalog's improvements land on the next
    #: search that is not a cache hit (a new city, the weekly TTL, a version bump).
    catalog_hashtags: tuple[str, ...] = ()

    def signature(self) -> str:
        return "|".join(
            [
                f"v{PHASED_PLAN_VERSION}",
                _slug(self.handle),
                ",".join(self.niches),
                ",".join(self.hashtags[:3]),
                self.country_code.upper(),
                _slug(self.city),
                ",".join(_slug(r) for r in self.related[:3]),
                ",".join(_slug(t) for t in self.terms),
            ]
        )

    def chips(self) -> list[str]:
        """What the insights screen shows under "Buscamos con": the signals, readable."""
        out = list(self.terms)
        out.extend(NICHE_LABELS.get(n, n) for n in self.niches)
        shown: list[str] = []
        for tag in (*self.hashtags[:3], *self.catalog_hashtags[:3]):
            if tag not in shown:
                shown.append(tag)
        out.extend(f"#{tag}" for tag in shown)
        place = ", ".join(p for p in (self.city, country_name(self.country_code)) if p)
        if place:
            out.append(place)
        return out


def split_terms(text: str) -> tuple[str, ...]:
    """Free text → search terms: split on commas / slashes / "y", trimmed, de-duplicated,
    at most three ("peluquería canina, spa para mascotas" → two terms)."""
    parts = re.split(r"\s*(?:,|/|;|\by\b|\be\b|&)\s*", text or "")
    out: list[str] = []
    for part in parts:
        term = " ".join(part.split())
        if len(term) >= 3 and _slug(term) not in {_slug(t) for t in out}:
            out.append(term)
    return tuple(out[:3])


def seed_from_profile(
    profile: dict[str, Any],
    *,
    sector: str = "",
    rubro_text: str = "",
    country_code: str = "",
    city: str = "",
) -> DiscoverySeed:
    """Read the account's own signals — bio, Instagram's business category, and the
    hashtags it actually uses (`topHashtags`, `scrapecreators_client.
    fetch_profile_and_posts`) — and let explicit answers from the Brand Kit's rubro
    step override what was detected. An explicit `sector` replaces the detected
    niches outright (the operator knows their business better than a regex over
    their bio); an explicit country keeps a detected city only if it is in that
    country."""
    handle = str(profile.get("username") or "")
    own = _slug(handle)
    raw_tags = [str(t).lower() for t in profile.get("topHashtags") or [] if isinstance(t, str)]
    tags = tuple(
        tag for tag in raw_tags if tag not in _GENERIC_HASHTAGS and not (own and own in _slug(tag))
    )
    text = " ".join(
        [str(profile.get("bio") or ""), str(profile.get("category") or "")]
        + [f"#{tag}" for tag in tags]
    )
    terms = split_terms(rubro_text)
    if sector:
        niches: tuple[str, ...] = (resolve_niche(sector),)
    elif terms:
        # Free text only: the taxonomy is consulted, never required — an unknown rubro
        # simply searches with its own words.
        niches = tuple(detect_niches(" ".join(terms)))
    else:
        niches = tuple(detect_niches(text))
    if sector or terms:
        # An explicit rubro overrides the detected one — so hashtags about another
        # topic must not steer the search (a food brand seeded from a programming
        # account's snapshot, measured 2026-09-11). Place tags stay: they locate.
        stems = _stems(" ".join(terms))
        tags = tuple(
            t
            for t in tags
            if (niches and set(detect_niches(f"#{t}")) & set(niches))
            or any(stem in _slug(t) for stem in stems)
            or _is_place_tag_anywhere(t)
        )
    detected_country, detected_city = detect_location(text, tags, country_hint=country_code)
    country = (country_code or detected_country).upper()
    if not city and detected_city and detected_country == country:
        city = detected_city
    related = tuple(
        str(r)
        for r in profile.get("relatedProfiles") or []
        if isinstance(r, str) and r and _slug(r) != own
    )
    return DiscoverySeed(
        handle=handle,
        niches=niches,
        hashtags=tags,
        country_code=country,
        city=city,
        related=related,
        terms=terms,
    )


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


def _is_place_tag_anywhere(tag: str) -> bool:
    """A hashtag naming any known country or city (`#cucutafood`, `#comidacolombia`,
    `#comidavzla`). Aliases count here too — a short form is still a place."""
    slug = _slug(tag)
    for country in COUNTRIES.values():
        if _slug(country.name) in slug:
            return True
        if any(len(_slug(a)) >= _MIN_ALIAS_LENGTH and _slug(a) in slug for a in country.aliases):
            return True
        if any(len(_slug(city)) >= 6 and _slug(city) in slug for city in country.cities):
            return True
    return False


def _is_place_tag(tag: str, seed: DiscoverySeed) -> bool:
    """`#cucutafood` / `#comidacolombia` name a place — they belong to the national /
    local phases, not to a location-free sector search."""
    slug = _slug(tag)
    places = [_slug(seed.city), _slug(country_name(seed.country_code))]
    return any(place and place in slug for place in places)


#: Search terms per sector phase — the account's own topical hashtags first, then the
#: taxonomy's sector terms, de-duplicated. Four TikTok queries at 2 pages and three
#: Google pages is the widest net a run casts.
SECTOR_OWN_TAGS = 2
#: Catalog hashtags (`DiscoverySeed.catalog_hashtags`) the sector phase adds after the
#: account's own. They EXTEND the `SECTOR_TERMS` cap instead of competing for it — each
#: one found is one more query, none found is the same plan as before the catalog — so
#: they never crowd out the taxonomy phrasings that surface a sector's biggest creators.
SECTOR_CATALOG_TAGS = 2
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
        for tag in seed.catalog_hashtags
        if not _is_place_tag(tag, seed) and _slug(tag) not in {_slug(t) for t in terms}
    ]
    from_catalog = catalog_tags[:SECTOR_CATALOG_TAGS]
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
    head = head_term(seed)
    return [f"{head} {seed.city}"] if seed.city and head else []


def phase_title(key: str, seed: DiscoverySeed) -> str:
    if key == "sector":
        return "Referentes del sector"
    if key == "national":
        name = country_name(seed.country_code)
        return f"Referentes en {name}" if name else "Referentes nacionales"
    return f"Referentes en {seed.city}" if seed.city else "Referentes locales"


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
    - local: the niche's head term + the city, `region` pinned, plus ONE city hashtag
      — the account's own city hashtag when it has one (`#cucutafood` from its own
      captions), else the provisional composed one (`hashtags_for`).
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
    plan = [(Query("tiktok", "keyword", f"{head} {seed.city}", label), region)]
    if own_city_tags:
        plan.append((Query("tiktok", "hashtag", own_city_tags[0], label), region))
    elif niches:
        composed = hashtags_for(niches[0], seed.city)[0]
        plan.append((Query("tiktok", "hashtag", composed, label), region))
    else:
        # A rubro outside the taxonomy has no niche to compose a city hashtag from: the
        # catalog's best hashtag for it stands in (`cucutaburgers`).
        catalog_tags = [t for t in seed.catalog_hashtags if not _is_place_tag(t, seed)]
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


_STOPWORDS = frozenset(
    {"para", "con", "sin", "del", "las", "los", "una", "uno", "por", "que", "and", "the", "for"}
)


def _stems(text: str) -> set[str]:
    """Word stems (first five letters, accents stripped) of the words worth matching in
    a rubro's own words — `peluquería canina` → {"peluq", "canin"}, so "peluquero",
    "peluquerías" and "canino" all count as the same rubro."""
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", _fold(text)):
        if len(word) >= 4 and word not in _STOPWORDS:
            out.add(word[:5])
    return out


def relevance_stems(seed: DiscoverySeed) -> set[str]:
    stems = _stems(" ".join(seed.terms))
    for tag in (*seed.hashtags, *seed.catalog_hashtags):
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


class ProfileStore:
    """The on-disk memory of profile reads (`PROFILE_CACHE_PATH`): `network:handle` →
    the `ProfileFacts` read, or the fact that the handle does not exist (a 404 is
    worth remembering too — mirrored handles miss often). Loaded once per run,
    written once at `save()`; `path=None` keeps it in memory only (tests)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._entries: dict[str, dict[str, Any]] = {}
        self._dirty = False
        if path is not None:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._entries = loaded
            except (OSError, ValueError):
                self._entries = {}

    @staticmethod
    def _key(network: str, handle: str) -> str:
        return f"{network}:{_slug(handle)}"

    def get(
        self, network: str, handle: str, *, now: float | None = None
    ) -> tuple[bool, ProfileFacts | None]:
        """`(known, facts)`: known+facts for a remembered account, known+None for a
        remembered 404, unknown for anything else or anything expired."""
        entry = self._entries.get(self._key(network, handle))
        if not isinstance(entry, dict):
            return False, None
        if (now or time.time()) - float(entry.get("fetchedAt", 0)) > _PROFILE_CACHE_TTL_SECONDS:
            return False, None
        if entry.get("missing"):
            return True, None
        facts = entry.get("facts")
        if not isinstance(facts, dict):
            return False, None
        return True, ProfileFacts(
            followers=_int(facts.get("followers")),
            bio=str(facts.get("bio") or ""),
            total_likes=_int(facts.get("total_likes")),
            is_private=bool(facts.get("is_private")),
            is_verified=bool(facts.get("is_verified")),
            category=str(facts.get("category") or ""),
            related=tuple(str(r) for r in facts.get("related") or []),
            full_name=str(facts.get("full_name") or ""),
            avatar=str(facts.get("avatar") or ""),
        )

    def put(
        self, network: str, handle: str, facts: ProfileFacts | None, *, now: float | None = None
    ) -> None:
        entry: dict[str, Any] = {"fetchedAt": now or time.time()}
        if facts is None:
            entry["missing"] = True
        else:
            entry["facts"] = {**asdict(facts), "related": list(facts.related)}
        self._entries[self._key(network, handle)] = entry
        self._dirty = True

    def save(self) -> None:
        if self.path is None or not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._entries, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        self._dirty = False


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


def _run_parallel(executor: ThreadPoolExecutor | None, fn: Any, items: list[Any]) -> list[Any]:
    """`[fn(item) for item in items]`, on the executor when there is one — results in
    the items' order, so credits, queries and errors stay deterministic."""
    if executor is None or len(items) <= 1:
        return [fn(item) for item in items]
    return list(executor.map(fn, items))


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
    person. The lookups run in parallel."""
    own = _slug(seed.handle)
    twins = sorted(
        (c for c in pool.values() if c.network == _other(network) and c.followers),
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
) -> PhaseResult:
    """Run one phase's TikTok searches and Instagram walk into the shared `pool`, then
    pick its most influential accounts from EVERYTHING seen so far (a national account
    surfaced by the sector search still counts) that no earlier phase already picked.
    Influence = followers, then interactions per post seen; `_pick_accounts` keeps
    both networks represented. A search the vendor answers with 404 is an empty
    result, not an error (the Instagram reels 404s of the first run)."""
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

    for network in ("tiktok", "instagram"):
        expand_accounts(
            key,
            seed,
            network,
            client=client,
            pool=pool,
            result=result,
            raw_dir=raw_dir,
            store=store,
            executor=executor,
        )
    for network in ("tiktok", "instagram"):
        mirror_accounts(
            seed,
            network,
            client=client,
            pool=pool,
            result=result,
            raw_dir=raw_dir,
            store=store,
            executor=executor,
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

    result.accounts = _pick_accounts(eligible)
    picked.update(c.key for c in result.accounts)
    if not result.accounts:
        result.note = "Todavía no encontramos cuentas para esta fase."
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
        profile_cache: Path | None = None,
        parallel: int = PARALLEL_CALLS,
    ) -> None:
        self.seed = seed
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=_DISCOVERY_TIMEOUT_SECONDS)
        self.raw_dir = raw_dir
        self.pool: dict[tuple[str, str], Candidate] = {}
        self.picked: set[tuple[str, str]] = set()
        self.store = ProfileStore(profile_cache)
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


def _compact(value: int | None) -> str:
    if not value:
        return "—"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    return str(value)


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
    }


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


def phase_to_dict(result: PhaseResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "title": result.title,
        "note": result.note,
        "accounts": [account_card(c) for c in result.accounts],
        "credits": result.credits,
        "errors": result.errors,
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
    if key in ("national", "local"):
        parts.append(seed.country_code.upper())
    if key == "local":
        parts.append(_slug(seed.city))
    return "|".join(parts)


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cache if isinstance(cache, dict) else {}


def _write_cache(path: Path, cache: dict[str, Any]) -> None:
    newest = sorted(cache.items(), key=lambda kv: kv[1].get("fetchedAt", 0), reverse=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(newest[:_CACHE_MAX_ENTRIES]), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_cached_phase(
    key: str, seed: DiscoverySeed, *, path: Path = DISCOVERY_CACHE_PATH, now: float | None = None
) -> dict[str, Any] | None:
    """One phase's cached result for this seed, or None (missing, expired, unreadable).
    Read BEFORE any vendor call — the file is the provisional store."""
    entry = _read_cache(path).get(phase_signature(key, seed))
    if not isinstance(entry, dict):
        return None
    if (now or time.time()) - float(entry.get("fetchedAt", 0)) > _CACHE_TTL_SECONDS:
        return None
    phase = entry.get("phase")
    return phase if isinstance(phase, dict) else None


def save_cached_phase(
    key: str,
    seed: DiscoverySeed,
    phase: dict[str, Any],
    *,
    path: Path = DISCOVERY_CACHE_PATH,
    now: float | None = None,
) -> None:
    """Upsert one phase, keeping the newest `_CACHE_MAX_ENTRIES` entries. A phase that
    found accounts is worth keeping even if some vendor call failed along the way
    (a single profile read answering 500 used to void the whole run — measured
    2026-09-11 — so every walk searched everything again); only a phase with
    errors AND nothing found is left uncached so the next walk retries it."""
    if phase.get("errors") and not phase.get("accounts"):
        return
    cache = _read_cache(path)
    cache[phase_signature(key, seed)] = {"fetchedAt": now or time.time(), "phase": phase}
    _write_cache(path, cache)


def load_cached_phases(
    seed: DiscoverySeed, *, path: Path = DISCOVERY_CACHE_PATH, now: float | None = None
) -> list[dict[str, Any]] | None:
    """Every phase of a run from the cache, or None when any is missing."""
    phases = [load_cached_phase(key, seed, path=path, now=now) for key in PHASES]
    return None if any(p is None for p in phases) else [p for p in phases if p]


def save_cached_phases(
    seed: DiscoverySeed,
    phases: list[dict[str, Any]],
    *,
    path: Path = DISCOVERY_CACHE_PATH,
    now: float | None = None,
) -> None:
    for phase in phases:
        key = str(phase.get("key", ""))
        if key in PHASES:
            save_cached_phase(key, seed, phase, path=path, now=now)


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
