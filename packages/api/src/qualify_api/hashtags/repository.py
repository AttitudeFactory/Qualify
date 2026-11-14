"""Persistence for the shared hashtag catalog (migration 0023).

Two questions the referentes search asks of it, and one thing it gives back:

- **"What hashtags mean this rubro?"** — `resolve(term)`. The operator's typed words are
  folded (`peluquería canina` → `peluqueriacanina`) and looked up in three tiers: an exact
  match on a known term, then a fuzzy match on known terms (a typo), then a fuzzy match on
  the hashtags themselves. Each hit says which tier found it and how sure it is, so the
  caller can tell "we know this rubro" from "this is the closest guess". An empty answer
  is an honest answer — the point is to stop searching with garbage silently.
- **"What is already known about this tag?"** — `get`, `for_niche`.
- **What every search teaches** — `upsert_hashtags` (a tag was seen) and `link_terms`
  (this term led to this tag). The catalog grows from the searches themselves.

Same two-implementation discipline as `referentes/repository.py`: `MemoryHashtagRepository`
mirrors the database's rules and one contract suite runs against both.

Every method takes a `tenant_id` and it is used for one thing only: it is the key to the
sanctioned DB door (`tenant_session`). The catalog itself is not tenant data and no row
carries a tenant (see 0023's docstring).

Two rules the callers can rely on:

- **Classification is never downgraded.** `kind`/`niche`/`country_code` are decided by
  `classified_by`, ranked `manual` > `ai` > `rule`. A later observation replaces a
  classification only when it is not `unknown` AND either nothing was decided yet or it
  comes from a stronger classifier. So an AI pass can re-decide what a rule decided, and
  nothing overwrites what a person decided. `source` (where the tag first came from) never
  changes.
- **Seeding is idempotent, observing accumulates.** A `NewTermLink` with `accumulate=False`
  (the taxonomy seed) leaves an existing link alone; with `accumulate=True` (a real search
  saw it again) its weight grows.
- **A post counts once per tag** (m-25026377, migration 0162). `record_post_sightings`
  keeps one row per (tag, network, post): seeing the same post again keeps the higher
  view count and the first known date, never a second row. «Popular» is
  `recent_views` — the views of the posts carrying the tag that were posted in the last
  `POPULAR_WINDOW_DAYS` — and `resolve_popular` is `resolve` re-ordered by it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

KINDS = ("topic", "place", "generic", "noise", "unknown")
SOURCES = ("taxonomy", "observed", "manual", "ai")
CLASSIFIERS = ("rule", "manual", "ai")

#: What `resolve` returns unless told otherwise: a tag classified as generic (`fyp`) or
#: noise says nothing about a rubro and must not steer a search.
DEFAULT_KINDS = ("topic", "place", "unknown")

#: A typed term shorter than this (folded) resolves to nothing: three letters match half
#: the catalog by trigram and mean nothing.
MIN_TERM_LENGTH = 3

#: Trigram / difflib similarity a fuzzy hit needs. 0.5 keeps "peluqeria canina" →
#: "peluqueriacanina" (a typo) and drops unrelated words.
DEFAULT_MIN_SIMILARITY = 0.5

#: «Popular» = views of the posts posted in this many days (m-25026377, founder 2026-11-13).
POPULAR_WINDOW_DAYS = 90

#: `resolve_popular` re-orders a pool this many times `limit` (at least
#: `POPULAR_MIN_POOL`) from `resolve`, so a well-watched tag a few places down the
#: relevance order can still reach the top.
POPULAR_POOL_FACTOR = 4
POPULAR_MIN_POOL = 20

#: Where a post sighting came from (0162 `ck_hashtag_sighting_source`).
SIGHTING_SOURCES = ("referentes", "public_reels")
NETWORKS = ("tiktok", "instagram")
#: `<network>:<kind>` and nothing else (0162 `ck_hashtag_sighting_source_ref`): no room
#: for a search's words.
SOURCE_REF = re.compile(r"(tiktok|instagram):[a-z_]{1,32}")

MATCH_TERM = "term"
MATCH_FUZZY_TERM = "fuzzy_term"
MATCH_FUZZY_TAG = "fuzzy_tag"

_CLASSIFIER_RANK = {"rule": 1, "ai": 2, "manual": 3}
_TAG_FORBIDDEN = re.compile(r"[#\s]")


def normalize_tag(tag: str) -> str:
    """The one spelling a hashtag is stored under: trimmed, no leading `#`, lowercase.
    Matches migration 0023's CHECK, so a value that passed here cannot be rejected there."""
    cleaned = tag.strip().lstrip("#").strip().lower()
    if not cleaned:
        raise ValueError("hashtag is empty")
    if _TAG_FORBIDDEN.search(cleaned):
        raise ValueError(f"hashtag must be a single token, got {tag!r}")
    return cleaned


def fold(value: str) -> str:
    """Accent-folded, alphanumeric-only lowercase — how typed text is compared. The same
    function as `creator_discovery._slug`; duplicated because this package must not
    import the Reflex app."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", ascii_only.lower())


def _check(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {allowed}, got {value!r}")
    return value


# --------------------------------------------------------------------------------------
# write inputs / read projections
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewHashtag:
    tag: str
    source: str
    kind: str = "unknown"
    niche: str | None = None
    country_code: str | None = None
    classified_by: str = "rule"
    #: The network it was seen on (`tiktok` / `instagram`); None for a seed.
    network: str | None = None
    #: How many sightings this write stands for.
    seen: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "tag", normalize_tag(self.tag))
        if not fold(self.tag):
            raise ValueError(f"hashtag {self.tag!r} has no letters or digits")
        _check(self.source, SOURCES, "source")
        _check(self.kind, KINDS, "kind")
        _check(self.classified_by, CLASSIFIERS, "classified_by")
        if self.seen < 0:
            raise ValueError("seen cannot be negative")
        if self.country_code is not None:
            code = self.country_code.strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", code):
                raise ValueError(f"country_code must be ISO alpha-2, got {self.country_code!r}")
            object.__setattr__(self, "country_code", code)
        if self.network is not None:
            network = self.network.strip().lower()
            object.__setattr__(self, "network", network or None)


@dataclass(frozen=True)
class NewTermLink:
    """`term` (how people write the rubro) → `tag` (a hashtag that means it)."""

    term: str
    tag: str
    source: str
    weight: int = 1
    #: True when a real search saw the link again (its weight grows); False for a seed,
    #: which must be safe to re-run.
    accumulate: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "term", " ".join(self.term.split()))
        object.__setattr__(self, "tag", normalize_tag(self.tag))
        if not fold(self.term):
            raise ValueError("term has no letters or digits")
        _check(self.source, SOURCES, "source")
        if self.weight <= 0:
            raise ValueError("weight must be positive")


@dataclass(frozen=True)
class Classification:
    """A decision about what an already-stored tag is — written by
    `apply_classifications`, which (unlike `upsert_hashtags`) is not a sighting: it never
    touches `seen_count`, `networks` or `last_seen_at`."""

    tag: str
    kind: str
    niche: str | None = None
    country_code: str | None = None
    classified_by: str = "ai"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tag", normalize_tag(self.tag))
        _check(self.kind, KINDS, "kind")
        if self.kind == "unknown":
            raise ValueError("a classification must decide something, got kind='unknown'")
        _check(self.classified_by, CLASSIFIERS, "classified_by")
        if self.country_code is not None:
            code = self.country_code.strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", code):
                raise ValueError(f"country_code must be ISO alpha-2, got {self.country_code!r}")
            object.__setattr__(self, "country_code", code)


@dataclass(frozen=True)
class NewPostSighting:
    """`tag` was on public post `post_id` of `network`, which had `views` and was posted at
    `posted_at` (both None when the provider did not say). Provenance: `source` (which
    read), `source_ref` (the KIND of read only — `<network>:<kind>`, e.g. `tiktok:hashtag`,
    `instagram:public_reels`; never a query's words, which a business typed, in a table
    with no RLS) and `parser_version` (the reader that produced the numbers). The post
    itself, `(network, post_id)`, is the source id."""

    tag: str
    network: str
    post_id: str
    source: str
    source_ref: str
    parser_version: str
    posted_at: datetime | None = None
    views: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tag", normalize_tag(self.tag))
        if not fold(self.tag):
            raise ValueError(f"hashtag {self.tag!r} has no letters or digits")
        object.__setattr__(self, "network", self.network.strip().lower())
        _check(self.network, NETWORKS, "network")
        object.__setattr__(self, "post_id", str(self.post_id).strip())
        if not self.post_id:
            raise ValueError("post_id is empty")
        _check(self.source, SIGHTING_SOURCES, "source")
        if not SOURCE_REF.fullmatch(self.source_ref):
            raise ValueError(f"source_ref must be '<network>:<kind>', got {self.source_ref!r}")
        if not self.parser_version.strip():
            raise ValueError("a sighting needs its parser_version")
        if self.views is not None and self.views < 0:
            raise ValueError("views cannot be negative")
        if self.posted_at is not None and self.posted_at.tzinfo is None:
            raise ValueError("posted_at must be timezone-aware")


@dataclass(frozen=True)
class RecentViews:
    """What the catalog knows of a tag's last `POPULAR_WINDOW_DAYS`: the summed views of
    the distinct posts carrying it, and how many such posts there were."""

    views: int = 0
    posts: int = 0


@dataclass(frozen=True)
class ReelPost:
    """One `public_reels` row (0117) as the catalog reads it — a reels read already paid
    for, re-read for its caption, views and date."""

    network: str
    reel_id: str
    taken_at: datetime
    caption: str
    views: int | None
    parser_version: int


@dataclass(frozen=True)
class StoredHashtag:
    tag: str
    slug: str
    kind: str
    niche: str | None
    country_code: str | None
    source: str
    classified_by: str
    networks: tuple[str, ...]
    seen_count: int
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class ResolvedHashtag:
    hashtag: StoredHashtag
    #: `term` (exact known term), `fuzzy_term` (a typo of one) or `fuzzy_tag` (close to a
    #: hashtag itself) — strongest first.
    match: str
    #: 1.0 for an exact match, the similarity otherwise.
    score: float
    #: Views of the distinct posts carrying the tag posted in the last
    #: `POPULAR_WINDOW_DAYS` (0162), and how many posts — 0 when nothing recent is known.
    #: Filled by `resolve_popular`; `resolve` leaves them at 0.
    recent_views: int = 0
    recent_posts: int = 0


class HashtagRepository(Protocol):
    def upsert_hashtags(self, tenant_id: UUID, items: Iterable[NewHashtag]) -> int:
        """Insert new tags; for known ones add `seen`, refresh `last_seen_at`, union the
        networks, and apply the classification rule in the module docstring. Returns how
        many distinct tags were written."""
        ...

    def link_terms(self, tenant_id: UUID, links: Iterable[NewTermLink]) -> int:
        """Record term → tag links, creating a tag the catalog has not seen yet (kind
        `unknown`). Returns how many distinct links were written."""
        ...

    def resolve(
        self,
        tenant_id: UUID,
        term: str,
        *,
        limit: int = 10,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        kinds: Sequence[str] = DEFAULT_KINDS,
    ) -> tuple[ResolvedHashtag, ...]:
        """The hashtags that mean `term`, best first, from the strongest tier that has any
        (exact term → fuzzy term → fuzzy tag). `()` when nothing is close enough."""
        ...

    def get(self, tenant_id: UUID, tag: str) -> StoredHashtag | None: ...

    def for_niche(
        self, tenant_id: UUID, niche: str, *, limit: int = 20
    ) -> tuple[StoredHashtag, ...]:
        """Tags classified under `niche` (a taxonomy key), most seen first."""
        ...

    def top_tags(
        self, tenant_id: UUID, *, kinds: Sequence[str] = DEFAULT_KINDS, limit: int = 100
    ) -> tuple[StoredHashtag, ...]:
        """The most seen tags of `kinds`, whatever their niche — the wide net a
        rubro outside the taxonomy is matched against."""
        ...

    def needs_classification(
        self, tenant_id: UUID, *, limit: int = 200
    ) -> tuple[StoredHashtag, ...]:
        """Tags only a rule has looked at and the rule could not settle: `unknown`, or a
        `topic` without a niche. Taxonomy tags are excluded (a person wrote them), and so
        is anything an AI or a person already decided — a pass never repeats itself.
        Also excluded (m-25026377): a tag only ever met in a reel caption — never counted
        by a search (`seen_count` 0), never linked to a term, with a `public_reels`
        sighting — so reels reads never grow the paid batch. Most seen first."""
        ...

    def apply_classifications(self, tenant_id: UUID, items: Iterable[Classification]) -> int:
        """Store decisions about existing tags under the never-downgrade rule (module
        docstring). Unknown tags are ignored. Returns how many rows changed."""
        ...

    def record_post_sightings(self, tenant_id: UUID, items: Iterable[NewPostSighting]) -> int:
        """Store which public posts each tag was on, with their views and date — one row per
        (tag, network, post), creating a tag the catalog has not seen yet (kind
        `unknown`, no sighting counted). A post seen again keeps the higher view count and
        its first known date. Returns how many distinct (tag, network, post) were written."""
        ...

    def recent_views(
        self,
        tenant_id: UUID,
        tags: Iterable[str],
        *,
        window_days: int = POPULAR_WINDOW_DAYS,
        now: datetime | None = None,
    ) -> dict[str, RecentViews]:
        """Per tag, the views of its posts posted in the last `window_days` before `now`.
        A post with no known date never counts (it cannot be shown to be recent); a tag
        with nothing recent is absent from the answer."""
        ...

    def resolve_popular(
        self,
        tenant_id: UUID,
        term: str,
        *,
        limit: int = 10,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        kinds: Sequence[str] = DEFAULT_KINDS,
        window_days: int = POPULAR_WINDOW_DAYS,
        now: datetime | None = None,
    ) -> tuple[ResolvedHashtag, ...]:
        """`resolve` over a wider pool, with recent views as a tie-breaker of relevance,
        never a replacement for it:

        - a weaker match tier never outranks a stronger one (`MATCH_TERM` before
          `MATCH_FUZZY_TERM` before `MATCH_FUZZY_TAG`);
        - inside the `MATCH_TERM` tier (the rubro's own linked tags) the most watched go
          first;
        - inside a fuzzy tier `resolve`'s similarity order is kept untouched — a typo
          neighbour with many views (`#carnet` for «carne») never pushes out the closer
          match;
        - ties keep `resolve`'s order, so with no views known the answer is exactly
          `resolve`'s.

        Each hit carries `recent_views`/`recent_posts` whatever its tier."""
        ...

    def public_reels_since(self, tenant_id: UUID, since: datetime) -> tuple[ReelPost, ...]:
        """The stored public reels (0117) posted at or after `since` — what a reels read
        already brought, for `catalog.backfill_public_reels`."""
        ...


def _rank_by_recent_views(
    repo: HashtagRepository,
    tenant_id: UUID,
    term: str,
    *,
    limit: int,
    min_similarity: float,
    kinds: Sequence[str],
    window_days: int,
    now: datetime | None,
) -> tuple[ResolvedHashtag, ...]:
    pool = repo.resolve(
        tenant_id,
        term,
        limit=max(limit * POPULAR_POOL_FACTOR, POPULAR_MIN_POOL),
        min_similarity=min_similarity,
        kinds=kinds,
    )
    if not pool:
        return ()
    recent = repo.recent_views(
        tenant_id, [hit.hashtag.tag for hit in pool], window_days=window_days, now=now
    )
    enriched = []
    for hit in pool:
        known = recent.get(hit.hashtag.tag, RecentViews())
        enriched.append(replace(hit, recent_views=known.views, recent_posts=known.posts))
    # Stable sort: a weaker match tier never outranks a stronger one; inside the term tier
    # the most watched go first; inside a fuzzy tier `resolve`'s similarity order stays
    # (a well-watched `#carnet` must not push the exact `#carne` out); ties keep
    # `resolve`'s order.
    enriched.sort(
        key=lambda hit: (
            _TIER_RANK.get(hit.match, len(_TIER_RANK)),
            -hit.recent_views if hit.match in _VIEWS_REORDER else 0,
        )
    )
    return tuple(enriched[:limit])


#: `resolve`'s tiers, strongest first, and the ones inside which recent views may reorder.
_TIER_RANK = {MATCH_TERM: 0, MATCH_FUZZY_TERM: 1, MATCH_FUZZY_TAG: 2}
_VIEWS_REORDER = frozenset({MATCH_TERM})


def lock_key(item: NewHashtag | NewTermLink | Classification | NewPostSighting) -> str:
    """THE lock order of every writer of `hashtags`: the tag by Unicode code point — what
    Python's `str` comparison does and what SQL's `COLLATE "C"` does on UTF-8. Never the
    database's default collation (`en_US.utf8` sorts `ñoquis` before `pizza`, code point
    after), or two writers sharing tags could still take their row locks in opposite
    orders and deadlock."""
    return item.tag


def merge_sighting(current: NewPostSighting, item: NewPostSighting) -> NewPostSighting:
    """Two reads of the same (tag, network, post), as 0162's upsert merges them: the
    higher view count wins and names the provenance, a known date stays."""
    newer = item.views is not None and (current.views is None or item.views >= current.views)
    views = [v for v in (current.views, item.views) if v is not None]
    return replace(
        item if newer else current,
        views=max(views) if views else None,
        posted_at=current.posted_at or item.posted_at,
    )


def sighting_batch(
    items: Iterable[NewPostSighting],
) -> tuple[list[tuple[str, tuple[str, ...]]], list[NewPostSighting]]:
    """`(tags, sightings)` for one write: each (tag, network, post) once (merged with
    `merge_sighting`), sorted by (tag, network, post); and each tag once with the networks
    it was seen on, sorted by tag. The sort is the deadlock rule: every writer locks
    `hashtags` rows in tag order, by code point (`lock_key`; plain `str` tuples here)."""
    merged: dict[tuple[str, str, str], NewPostSighting] = {}
    for item in items:
        key = (item.tag, item.network, item.post_id)
        current = merged.get(key)
        merged[key] = item if current is None else merge_sighting(current, item)
    sightings = [merged[key] for key in sorted(merged)]
    networks: dict[str, set[str]] = {}
    for s in sightings:
        networks.setdefault(s.tag, set()).add(s.network)
    tags = [(tag, tuple(sorted(networks[tag]))) for tag in sorted(networks)]
    return tags, sightings


def _cutoff(window_days: int, now: datetime | None) -> datetime:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    return (now or datetime.now(UTC)) - timedelta(days=window_days)


# --------------------------------------------------------------------------------------
# in-memory
# --------------------------------------------------------------------------------------


def _takes_classification(
    existing_kind: str, existing_by: str, incoming_kind: str, incoming_by: str
) -> bool:
    if incoming_kind == "unknown":
        return False
    if existing_kind == "unknown":
        return True
    return _CLASSIFIER_RANK[incoming_by] > _CLASSIFIER_RANK[existing_by]


@dataclass
class _Link:
    term_slug: str
    term: str
    tag: str
    weight: int
    source: str


@dataclass
class MemoryHashtagRepository:
    """Mirrors migration 0023's rules without a database. Fuzzy matching uses `difflib`,
    the database uses trigram similarity — both agree on clear typos and clear misses,
    which is all the contract suite asserts."""

    _tags: dict[str, StoredHashtag] = field(default_factory=dict)
    _links: dict[tuple[str, str], _Link] = field(default_factory=dict)
    _last: datetime | None = None
    #: (tag, network, post_id) → the stored sighting (0162's natural key).
    _sightings: dict[tuple[str, str, str], NewPostSighting] = field(default_factory=dict)
    #: What `public_reels` (0117) holds, for `public_reels_since`; tests fill it.
    public_reels: list[ReelPost] = field(default_factory=list)

    def _now(self) -> datetime:
        # Strictly increasing, like `now()` across transactions (two writes in one clock
        # tick are common on Windows).
        now = datetime.now(UTC)
        if self._last is not None and now <= self._last:
            now = self._last + timedelta(microseconds=1)
        self._last = now
        return now

    def upsert_hashtags(self, tenant_id: UUID, items: Iterable[NewHashtag]) -> int:
        written: set[str] = set()
        for item in items:
            self._upsert_one(item)
            written.add(item.tag)
        return len(written)

    def _upsert_one(self, item: NewHashtag) -> None:
        now = self._now()
        current = self._tags.get(item.tag)
        networks = (item.network,) if item.network else ()
        if current is None:
            self._tags[item.tag] = StoredHashtag(
                tag=item.tag,
                slug=fold(item.tag),
                kind=item.kind,
                niche=item.niche,
                country_code=item.country_code,
                source=item.source,
                classified_by=item.classified_by,
                networks=tuple(sorted(set(networks))),
                seen_count=item.seen,
                first_seen_at=now,
                last_seen_at=now,
            )
            return
        takes = _takes_classification(
            current.kind, current.classified_by, item.kind, item.classified_by
        )
        self._tags[item.tag] = replace(
            current,
            kind=item.kind if takes else current.kind,
            niche=item.niche if takes else current.niche,
            country_code=item.country_code if takes else current.country_code,
            classified_by=item.classified_by if takes else current.classified_by,
            networks=tuple(sorted(set(current.networks) | set(networks))),
            seen_count=current.seen_count + item.seen,
            last_seen_at=now,
        )

    def link_terms(self, tenant_id: UUID, links: Iterable[NewTermLink]) -> int:
        written: set[tuple[str, str]] = set()
        for link in links:
            if link.tag not in self._tags:
                self._upsert_one(NewHashtag(tag=link.tag, source=link.source))
            key = (fold(link.term), link.tag)
            existing = self._links.get(key)
            if existing is None:
                self._links[key] = _Link(key[0], link.term, link.tag, link.weight, link.source)
            elif link.accumulate:
                existing.weight += link.weight
            written.add(key)
        return len(written)

    def resolve(
        self,
        tenant_id: UUID,
        term: str,
        *,
        limit: int = 10,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        kinds: Sequence[str] = DEFAULT_KINDS,
    ) -> tuple[ResolvedHashtag, ...]:
        slug = fold(term)
        if len(slug) < MIN_TERM_LENGTH:
            return ()

        def keep(tag: str) -> StoredHashtag | None:
            stored = self._tags.get(tag)
            return stored if stored is not None and stored.kind in kinds else None

        exact = sorted(
            (link for link in self._links.values() if link.term_slug == slug),
            key=lambda link: -link.weight,
        )
        hits = [(keep(link.tag), MATCH_TERM, 1.0) for link in exact]
        hits = [(tag, match, score) for tag, match, score in hits if tag is not None]
        if not hits:
            best: dict[str, float] = {}
            for link in self._links.values():
                score = SequenceMatcher(None, link.term_slug, slug).ratio()
                if score >= min_similarity and score > best.get(link.tag, 0.0):
                    best[link.tag] = score
            fuzzy = sorted(best.items(), key=lambda kv: -kv[1])
            hits = [(keep(tag), MATCH_FUZZY_TERM, score) for tag, score in fuzzy]
            hits = [(tag, match, score) for tag, match, score in hits if tag is not None]
        if not hits:
            scored = [
                (stored, SequenceMatcher(None, stored.slug, slug).ratio())
                for stored in self._tags.values()
                if stored.kind in kinds
            ]
            scored = [(s, score) for s, score in scored if score >= min_similarity]
            scored.sort(key=lambda pair: (-pair[1], -pair[0].seen_count))
            hits = [(s, MATCH_FUZZY_TAG, score) for s, score in scored]
        return tuple(ResolvedHashtag(tag, match, score) for tag, match, score in hits[:limit])

    def get(self, tenant_id: UUID, tag: str) -> StoredHashtag | None:
        return self._tags.get(normalize_tag(tag))

    def for_niche(
        self, tenant_id: UUID, niche: str, *, limit: int = 20
    ) -> tuple[StoredHashtag, ...]:
        rows = [t for t in self._tags.values() if t.niche == niche]
        rows.sort(key=lambda t: (-t.seen_count, t.tag))
        return tuple(rows[:limit])

    def top_tags(
        self, tenant_id: UUID, *, kinds: Sequence[str] = DEFAULT_KINDS, limit: int = 100
    ) -> tuple[StoredHashtag, ...]:
        rows = [t for t in self._tags.values() if t.kind in kinds]
        rows.sort(key=lambda t: (-t.seen_count, t.tag))
        return tuple(rows[:limit])

    def needs_classification(
        self, tenant_id: UUID, *, limit: int = 200
    ) -> tuple[StoredHashtag, ...]:
        rows = [
            t
            for t in self._tags.values()
            if t.classified_by == "rule"
            and t.source != "taxonomy"
            and (t.kind == "unknown" or (t.kind == "topic" and t.niche is None))
            and not self._reel_only(t)
        ]
        rows.sort(key=lambda t: (-t.seen_count, t.tag))
        return tuple(rows[:limit])

    def _reel_only(self, stored: StoredHashtag) -> bool:
        """As `_NOT_REEL_ONLY`: created as `observed`, never counted by a search, never
        linked to a term, and met in at least one reel caption."""
        if stored.source != "observed" or stored.seen_count > 0:
            return False
        if any(link.tag == stored.tag for link in self._links.values()):
            return False
        return any(
            tag == stored.tag and s.source == "public_reels"
            for (tag, _n, _p), s in self._sightings.items()
        )

    def apply_classifications(self, tenant_id: UUID, items: Iterable[Classification]) -> int:
        changed = 0
        for item in items:
            current = self._tags.get(item.tag)
            if current is None or not _takes_classification(
                current.kind, current.classified_by, item.kind, item.classified_by
            ):
                continue
            self._tags[item.tag] = replace(
                current,
                kind=item.kind,
                niche=item.niche,
                country_code=item.country_code,
                classified_by=item.classified_by,
            )
            changed += 1
        return changed

    def record_post_sightings(self, tenant_id: UUID, items: Iterable[NewPostSighting]) -> int:
        tags, sightings = sighting_batch(items)
        for tag, networks in tags:
            for network in networks:  # as the SQL: no sighting counted, networks unioned
                self._upsert_one(NewHashtag(tag=tag, source="observed", network=network))
        for item in sightings:
            key = (item.tag, item.network, item.post_id)
            current = self._sightings.get(key)
            self._sightings[key] = item if current is None else merge_sighting(current, item)
        return len(sightings)

    def recent_views(
        self,
        tenant_id: UUID,
        tags: Iterable[str],
        *,
        window_days: int = POPULAR_WINDOW_DAYS,
        now: datetime | None = None,
    ) -> dict[str, RecentViews]:
        cutoff = _cutoff(window_days, now)
        wanted = {normalize_tag(t) for t in tags}
        out: dict[str, RecentViews] = {}
        for (tag, _network, _post), sighting in self._sightings.items():
            if tag not in wanted or sighting.posted_at is None or sighting.posted_at < cutoff:
                continue
            seen = out.get(tag, RecentViews())
            out[tag] = RecentViews(seen.views + (sighting.views or 0), seen.posts + 1)
        return out

    def resolve_popular(
        self,
        tenant_id: UUID,
        term: str,
        *,
        limit: int = 10,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        kinds: Sequence[str] = DEFAULT_KINDS,
        window_days: int = POPULAR_WINDOW_DAYS,
        now: datetime | None = None,
    ) -> tuple[ResolvedHashtag, ...]:
        return _rank_by_recent_views(
            self,
            tenant_id,
            term,
            limit=limit,
            min_similarity=min_similarity,
            kinds=kinds,
            window_days=window_days,
            now=now,
        )

    def public_reels_since(self, tenant_id: UUID, since: datetime) -> tuple[ReelPost, ...]:
        return tuple(r for r in self.public_reels if r.taken_at >= since)


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------

_COLUMNS = (
    "tag, slug, kind, niche, country_code, source, classified_by, networks, seen_count, "
    "first_seen_at, last_seen_at"
)

_RANK = "CASE {col} WHEN 'manual' THEN 3 WHEN 'ai' THEN 2 ELSE 1 END"

_TAKES = (
    "(EXCLUDED.kind <> 'unknown' AND (hashtags.kind = 'unknown' OR "
    + _RANK.format(col="EXCLUDED.classified_by")
    + " > "
    + _RANK.format(col="hashtags.classified_by")
    + "))"
)

_UPSERT_HASHTAG = text(
    f"""
    INSERT INTO hashtags
        (tag, slug, kind, niche, country_code, source, classified_by, networks, seen_count)
    VALUES
        (:tag, :slug, :kind, :niche, :country_code, :source, :classified_by,
         CAST(:networks AS text[]), :seen)
    ON CONFLICT (tag) DO UPDATE SET
        seen_count = hashtags.seen_count + EXCLUDED.seen_count,
        last_seen_at = now(),
        networks = ARRAY(
            SELECT DISTINCT n FROM unnest(hashtags.networks || EXCLUDED.networks) AS n ORDER BY n
        ),
        kind = CASE WHEN {_TAKES} THEN EXCLUDED.kind ELSE hashtags.kind END,
        niche = CASE WHEN {_TAKES} THEN EXCLUDED.niche ELSE hashtags.niche END,
        country_code = CASE WHEN {_TAKES}
            THEN EXCLUDED.country_code ELSE hashtags.country_code END,
        classified_by = CASE WHEN {_TAKES}
            THEN EXCLUDED.classified_by ELSE hashtags.classified_by END
    """
)

_LINK_ACCUMULATE = text(
    """
    INSERT INTO hashtag_terms (term_slug, term, hashtag_id, weight, source)
    SELECT :term_slug, :term, id, :weight, :source FROM hashtags WHERE tag = :tag
    ON CONFLICT (term_slug, hashtag_id) DO UPDATE SET
        weight = hashtag_terms.weight + EXCLUDED.weight, updated_at = now()
    """
)

_LINK_SEED = text(
    """
    INSERT INTO hashtag_terms (term_slug, term, hashtag_id, weight, source)
    SELECT :term_slug, :term, id, :weight, :source FROM hashtags WHERE tag = :tag
    ON CONFLICT (term_slug, hashtag_id) DO NOTHING
    """
)

_RESOLVE_EXACT = text(
    f"""
    SELECT {", ".join("h." + c.strip() for c in _COLUMNS.split(","))}, 1.0 AS score
    FROM hashtag_terms t JOIN hashtags h ON h.id = t.hashtag_id
    WHERE t.term_slug = :slug AND h.kind = ANY(:kinds)
    ORDER BY t.weight DESC, h.seen_count DESC, h.tag
    LIMIT :limit
    """
)

_RESOLVE_FUZZY_TERM = text(
    f"""
    SELECT {", ".join("h." + c.strip() for c in _COLUMNS.split(","))},
           max(similarity(t.term_slug, :slug)) AS score
    FROM hashtag_terms t JOIN hashtags h ON h.id = t.hashtag_id
    WHERE t.term_slug % :slug AND similarity(t.term_slug, :slug) >= :min
      AND h.kind = ANY(:kinds)
    GROUP BY h.id
    ORDER BY score DESC, h.seen_count DESC, h.tag
    LIMIT :limit
    """
)

_RESOLVE_FUZZY_TAG = text(
    f"""
    SELECT {_COLUMNS}, similarity(slug, :slug) AS score
    FROM hashtags
    WHERE slug % :slug AND similarity(slug, :slug) >= :min AND kind = ANY(:kinds)
    ORDER BY score DESC, seen_count DESC, tag
    LIMIT :limit
    """
)


_APPLY_CLASSIFICATION = text(
    f"""
    UPDATE hashtags SET
        kind = :kind, niche = :niche, country_code = :country_code, classified_by = :by
    WHERE tag = :tag
      AND (kind = 'unknown'
           OR {_RANK.format(col="CAST(:by AS text)")} > {_RANK.format(col="classified_by")})
    """
)

#: m-25026377: a tag only ever met in a reel caption (`public_reels` sighting, never
#: counted by a search, never linked to a term) stays out of the paid classification
#: queue — reels reads must not grow the Haiku batch billed to the next search.
#: Only an `observed` tag can be reel-only: one created by `ai` (`remember_created`),
#: `manual` or `taxonomy` keeps its behaviour even when a reel caption carries it.
_NOT_REEL_ONLY = (
    "(h.source <> 'observed' OR h.seen_count > 0 "
    "OR EXISTS (SELECT 1 FROM hashtag_terms t WHERE t.hashtag_id = h.id) "
    "OR NOT EXISTS (SELECT 1 FROM hashtag_post_sightings s "
    "WHERE s.hashtag_id = h.id AND s.source = 'public_reels'))"
)

_NEEDS_CLASSIFICATION = text(
    f"""
    SELECT {", ".join("h." + c.strip() for c in _COLUMNS.split(","))} FROM hashtags h
    WHERE h.classified_by = 'rule' AND h.source <> 'taxonomy'
      AND (h.kind = 'unknown' OR (h.kind = 'topic' AND h.niche IS NULL))
      AND {_NOT_REEL_ONLY}
    ORDER BY h.seen_count DESC, h.tag
    LIMIT :limit
    """
)


#: The read that brought a higher (or first) view count is the one the row's provenance
#: names; a read with no views never takes it over.
_SIGHTING_NEWER = (
    "(EXCLUDED.views IS NOT NULL AND (hashtag_post_sightings.views IS NULL "
    "OR EXCLUDED.views >= hashtag_post_sightings.views))"
)

# The tags of one `record_post_sightings` call, in ONE statement, locked in tag order
# (one row per tag — `networks` comes comma-joined): two writers sharing tags always take
# their row locks in the same order, so they wait for each other instead of deadlocking.
# A new tag is `unknown`/`observed` with no sighting counted (`seen_count` 0).
_UPSERT_SIGHTING_TAGS = text(
    """
    INSERT INTO hashtags
        (tag, slug, kind, niche, country_code, source, classified_by, networks, seen_count)
    SELECT u.tag, u.slug, 'unknown', NULL, NULL, 'observed', 'rule',
           string_to_array(u.nets, ','), 0
    FROM unnest(CAST(:tags AS text[]), CAST(:slugs AS text[]), CAST(:nets AS text[]))
         AS u(tag, slug, nets)
    ORDER BY u.tag COLLATE "C"
    ON CONFLICT (tag) DO UPDATE SET
        last_seen_at = now(),
        networks = ARRAY(
            SELECT DISTINCT n FROM unnest(hashtags.networks || EXCLUDED.networks) AS n ORDER BY n
        )
    """
)

# All the sightings of one call in ONE statement, in (tag, network, post) order. One row
# per (tag, network, post) — the caller deduplicates, a statement cannot touch a row twice.
# Views only grow (`GREATEST` skips NULLs) and a known date stays.
_UPSERT_SIGHTINGS = text(
    f"""
    INSERT INTO hashtag_post_sightings
        (hashtag_id, network, post_id, posted_at, views, source, source_ref, parser_version)
    SELECT h.id, u.network, u.post_id, u.posted_at, u.views, u.source, u.source_ref,
           u.parser_version
    FROM unnest(
        CAST(:tags AS text[]), CAST(:networks AS text[]), CAST(:post_ids AS text[]),
        CAST(:posted_ats AS timestamptz[]), CAST(:views AS bigint[]),
        CAST(:sources AS text[]), CAST(:source_refs AS text[]),
        CAST(:parser_versions AS text[])
    ) AS u(tag, network, post_id, posted_at, views, source, source_ref, parser_version)
    JOIN hashtags h ON h.tag = u.tag
    ORDER BY u.tag COLLATE "C", u.network COLLATE "C", u.post_id COLLATE "C"
    ON CONFLICT (hashtag_id, network, post_id) DO UPDATE SET
        views = GREATEST(hashtag_post_sightings.views, EXCLUDED.views),
        posted_at = COALESCE(hashtag_post_sightings.posted_at, EXCLUDED.posted_at),
        source = CASE WHEN {_SIGHTING_NEWER}
            THEN EXCLUDED.source ELSE hashtag_post_sightings.source END,
        source_ref = CASE WHEN {_SIGHTING_NEWER}
            THEN EXCLUDED.source_ref ELSE hashtag_post_sightings.source_ref END,
        parser_version = CASE WHEN {_SIGHTING_NEWER}
            THEN EXCLUDED.parser_version ELSE hashtag_post_sightings.parser_version END,
        last_seen_at = now()
    """
)

_RECENT_VIEWS = text(
    """
    SELECT h.tag, COALESCE(sum(s.views), 0) AS views, count(*) AS posts
    FROM hashtag_post_sightings s JOIN hashtags h ON h.id = s.hashtag_id
    WHERE h.tag = ANY(:tags) AND s.posted_at >= :cutoff
    GROUP BY h.tag
    """
)

_PUBLIC_REELS_SINCE = text(
    """
    SELECT network, reel_id, taken_at, caption, views, parser_version
    FROM public_reels WHERE taken_at >= :since
    ORDER BY taken_at, network, reel_id
    """
)


def _stored(row: object) -> StoredHashtag:
    return StoredHashtag(
        tag=row.tag,  # type: ignore[attr-defined]
        slug=row.slug,  # type: ignore[attr-defined]
        kind=row.kind,  # type: ignore[attr-defined]
        niche=row.niche,  # type: ignore[attr-defined]
        country_code=row.country_code,  # type: ignore[attr-defined]
        source=row.source,  # type: ignore[attr-defined]
        classified_by=row.classified_by,  # type: ignore[attr-defined]
        networks=tuple(row.networks),  # type: ignore[attr-defined]
        seen_count=row.seen_count,  # type: ignore[attr-defined]
        first_seen_at=row.first_seen_at,  # type: ignore[attr-defined]
        last_seen_at=row.last_seen_at,  # type: ignore[attr-defined]
    )


class PostgresHashtagRepository:
    """All access through `tenant_session` — the sanctioned door. The tables carry no
    tenant, so RLS has nothing to scope; the session is used for its role and pooling."""

    def upsert_hashtags(self, tenant_id: UUID, items: Iterable[NewHashtag]) -> int:
        written: set[str] = set()
        with tenant_session(tenant_id) as session:
            # tag order (stable for repeats): the same lock order as every writer
            for item in sorted(items, key=lock_key):
                session.execute(
                    _UPSERT_HASHTAG,
                    {
                        "tag": item.tag,
                        "slug": fold(item.tag),
                        "kind": item.kind,
                        "niche": item.niche,
                        "country_code": item.country_code,
                        "source": item.source,
                        "classified_by": item.classified_by,
                        "networks": [item.network] if item.network else [],
                        "seen": item.seen,
                    },
                )
                written.add(item.tag)
        return len(written)

    def link_terms(self, tenant_id: UUID, links: Iterable[NewTermLink]) -> int:
        written: set[tuple[str, str]] = set()
        with tenant_session(tenant_id) as session:
            for link in sorted(links, key=lock_key):
                session.execute(
                    _UPSERT_HASHTAG,
                    {
                        "tag": link.tag,
                        "slug": fold(link.tag),
                        "kind": "unknown",
                        "niche": None,
                        "country_code": None,
                        "source": link.source,
                        "classified_by": "rule",
                        "networks": [],
                        "seen": 0,
                    },
                )
                session.execute(
                    _LINK_ACCUMULATE if link.accumulate else _LINK_SEED,
                    {
                        "term_slug": fold(link.term),
                        "term": link.term,
                        "weight": link.weight,
                        "source": link.source,
                        "tag": link.tag,
                    },
                )
                written.add((fold(link.term), link.tag))
        return len(written)

    def resolve(
        self,
        tenant_id: UUID,
        term: str,
        *,
        limit: int = 10,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        kinds: Sequence[str] = DEFAULT_KINDS,
    ) -> tuple[ResolvedHashtag, ...]:
        slug = fold(term)
        if len(slug) < MIN_TERM_LENGTH:
            return ()
        params = {"slug": slug, "kinds": list(kinds), "limit": limit, "min": min_similarity}
        with tenant_session(tenant_id) as session:
            for statement, match in (
                (_RESOLVE_EXACT, MATCH_TERM),
                (_RESOLVE_FUZZY_TERM, MATCH_FUZZY_TERM),
                (_RESOLVE_FUZZY_TAG, MATCH_FUZZY_TAG),
            ):
                rows = session.execute(statement, params).all()
                if rows:
                    return tuple(ResolvedHashtag(_stored(r), match, float(r.score)) for r in rows)
        return ()

    def get(self, tenant_id: UUID, tag: str) -> StoredHashtag | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(f"SELECT {_COLUMNS} FROM hashtags WHERE tag = :tag"),
                {"tag": normalize_tag(tag)},
            ).first()
        return _stored(row) if row is not None else None

    def for_niche(
        self, tenant_id: UUID, niche: str, *, limit: int = 20
    ) -> tuple[StoredHashtag, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM hashtags WHERE niche = :niche "
                    "ORDER BY seen_count DESC, tag LIMIT :limit"
                ),
                {"niche": niche, "limit": limit},
            ).all()
        return tuple(_stored(r) for r in rows)

    def top_tags(
        self, tenant_id: UUID, *, kinds: Sequence[str] = DEFAULT_KINDS, limit: int = 100
    ) -> tuple[StoredHashtag, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM hashtags WHERE kind = ANY(:kinds) "
                    "ORDER BY seen_count DESC, tag LIMIT :limit"
                ),
                {"kinds": list(kinds), "limit": limit},
            ).all()
        return tuple(_stored(r) for r in rows)

    def needs_classification(
        self, tenant_id: UUID, *, limit: int = 200
    ) -> tuple[StoredHashtag, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_NEEDS_CLASSIFICATION, {"limit": limit}).all()
        return tuple(_stored(r) for r in rows)

    def apply_classifications(self, tenant_id: UUID, items: Iterable[Classification]) -> int:
        changed = 0
        with tenant_session(tenant_id) as session:
            for item in sorted(items, key=lock_key):
                result = session.execute(
                    _APPLY_CLASSIFICATION,
                    {
                        "tag": item.tag,
                        "kind": item.kind,
                        "niche": item.niche,
                        "country_code": item.country_code,
                        "by": item.classified_by,
                    },
                )
                changed += result.rowcount or 0
        return changed

    def record_post_sightings(self, tenant_id: UUID, items: Iterable[NewPostSighting]) -> int:
        """Two statements per call, whatever its size (`sighting_batch`)."""
        tags, sightings = sighting_batch(items)
        if not sightings:
            return 0
        with tenant_session(tenant_id) as session:
            session.execute(
                _UPSERT_SIGHTING_TAGS,
                {
                    "tags": [tag for tag, _ in tags],
                    "slugs": [fold(tag) for tag, _ in tags],
                    "nets": [",".join(nets) for _, nets in tags],
                },
            )
            session.execute(
                _UPSERT_SIGHTINGS,
                {
                    "tags": [s.tag for s in sightings],
                    "networks": [s.network for s in sightings],
                    "post_ids": [s.post_id for s in sightings],
                    "posted_ats": [s.posted_at for s in sightings],
                    "views": [s.views for s in sightings],
                    "sources": [s.source for s in sightings],
                    "source_refs": [s.source_ref for s in sightings],
                    "parser_versions": [s.parser_version for s in sightings],
                },
            )
        return len(sightings)

    def recent_views(
        self,
        tenant_id: UUID,
        tags: Iterable[str],
        *,
        window_days: int = POPULAR_WINDOW_DAYS,
        now: datetime | None = None,
    ) -> dict[str, RecentViews]:
        cutoff = _cutoff(window_days, now)
        wanted = sorted({normalize_tag(t) for t in tags})
        if not wanted:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(_RECENT_VIEWS, {"tags": wanted, "cutoff": cutoff}).all()
        return {r.tag: RecentViews(int(r.views), int(r.posts)) for r in rows}

    def resolve_popular(
        self,
        tenant_id: UUID,
        term: str,
        *,
        limit: int = 10,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        kinds: Sequence[str] = DEFAULT_KINDS,
        window_days: int = POPULAR_WINDOW_DAYS,
        now: datetime | None = None,
    ) -> tuple[ResolvedHashtag, ...]:
        return _rank_by_recent_views(
            self,
            tenant_id,
            term,
            limit=limit,
            min_similarity=min_similarity,
            kinds=kinds,
            window_days=window_days,
            now=now,
        )

    def public_reels_since(self, tenant_id: UUID, since: datetime) -> tuple[ReelPost, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_PUBLIC_REELS_SINCE, {"since": since}).all()
        return tuple(
            ReelPost(
                network=r.network,
                reel_id=r.reel_id,
                taken_at=r.taken_at,
                caption=r.caption or "",
                views=r.views,
                parser_version=int(r.parser_version),
            )
            for r in rows
        )
