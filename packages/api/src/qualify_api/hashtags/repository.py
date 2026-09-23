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
            for item in items:
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
            for link in links:
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
