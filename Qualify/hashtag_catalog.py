"""The bridge between the referentes search (`creator_discovery`) and the shared hashtag
catalog (`qualify_api.hashtags`, migration 0023).

Two Claude-backed jobs sit on top of the three below (`qualify_api.hashtags.ai`):

- `ai_hashtags_for` — the READ side used by the wizard since plan 7: Claude gets the
  brand's profile, a starting list of catalog tags and two catalog TOOLS (`CatalogTools`:
  search by word, list a niche), explores the catalog itself, and returns through a
  third tool only the tags that fit THIS brand's business (a restaurant does not get
  `#streetfood`). Stateless: the choice is stored with the phase
  that used it (provenance), never written back into the catalog, so nothing is learned
  per rubro. Without a key, or on any failure, it falls back to `catalog_hashtags_for`.
- `classify_pending` — what the rule in `classify_tag` left `unknown` (or a topic with no
  niche) is classified by Claude, a batch at a time, after each capture and by
  `just classify-hashtags`. What a tag is does not depend on who searches, so this one IS
  stored on the shared catalog (`classified_by='ai'`, never over a person's decision).

Three jobs:

- `seed_taxonomy` — the hand-written `NICHE_TAXONOMY` (3 hashtags per niche) becomes data:
  every niche's hashtags are stored classified, and every way the taxonomy names the niche
  (its search queries and its label) is linked to them. Idempotent (`ensure_seeded` runs
  it once per process).
- `capture` — after a phase ran, the hashtags its accounts were seen using are stored, so
  the catalog grows from real searches instead of from a guess.
- `catalog_hashtags_for` — the READ side, used before a run: what the operator's rubro
  (typos included) and the seed's niches resolve to in the catalog. The wizard puts the
  answer in `DiscoverySeed.catalog_hashtags`, which `creator_discovery` (plan version 6)
  adds to the sector queries, the local hashtag query and the relevance stems.

Only the read side changes which accounts a run finds, and it does so through the seed —
`creator_discovery` itself stays free of any database. The two writers live here, outside
that module, because how the catalog is fed is not part of which accounts a phase finds
(its code is fingerprinted as "the algorithm", `test_creator_discovery_version.py`).

Blocking DB calls: callers on the event loop run them through `asyncio.to_thread`.
`REPOSITORY` is module-level so tests swap in `MemoryHashtagRepository`. Neither writer
raises for a bad catalog row — a hashtag the vendor returned that the repository rejects
is skipped and counted, never allowed to fail a search that already succeeded.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from qualify_api.hashtags import (
    Classification,
    HashtagRepository,
    NewHashtag,
    NewTermLink,
    PostgresHashtagRepository,
    StoredHashtag,
)
from qualify_api.hashtags import ai as hashtag_ai

from . import creator_discovery
from .creator_discovery import Candidate, DiscoverySeed

logger = logging.getLogger(__name__)

REPOSITORY: HashtagRepository = PostgresHashtagRepository()

#: A hashtag becomes a link from the rubro's words only when at least this many DISTINCT
#: accounts of the sector phase used it. One account's hashtag is that account's habit;
#: two independent ones are what the rubro is called.
MIN_ACCOUNTS_FOR_LINK = 2

#: The one phase whose accounts are filtered for being about the rubro
#: (`creator_discovery._about_the_sector`). The national and local phases are scoped by
#: place, so an account there proves nothing about the rubro's hashtags.
LINKING_PHASE = "sector"


@dataclass(frozen=True)
class CaptureSummary:
    hashtags: int = 0
    links: int = 0
    skipped: int = 0


def classify_tag(tag: str, seed: DiscoverySeed) -> tuple[str, str | None, str | None]:
    """`(kind, niche, country_code)` a rule can decide from the tag alone — the same
    heuristics the search already trusts (`creator_discovery._GENERIC_HASHTAGS`, the place
    tables, the taxonomy's keywords). What no rule can decide stays `unknown`, for a later
    (AI or manual) pass to settle."""
    slug = creator_discovery._slug(tag)
    if slug in creator_discovery._GENERIC_HASHTAGS or tag in creator_discovery._GENERIC_HASHTAGS:
        return "generic", None, None
    if creator_discovery._is_place_tag(tag, seed) or creator_discovery._is_place_tag_anywhere(tag):
        country = seed.country_code.upper() if seed.country_code else None
        return "place", None, country
    niches = creator_discovery.detect_niches(f"#{tag}")
    if niches:
        return "topic", niches[0], None
    return "unknown", None, None


def seed_taxonomy(
    tenant_id: UUID, *, repository: HashtagRepository | None = None
) -> CaptureSummary:
    """Store `NICHE_TAXONOMY` as catalog data. Each niche's hashtags are `topic` tags of
    that niche; each of the niche's queries and its label links to all of them. Links are
    written with `accumulate=False`, so re-running never inflates a weight."""
    repo = repository or REPOSITORY
    tags: list[NewHashtag] = []
    links: list[NewTermLink] = []
    for niche, spec in creator_discovery.NICHE_TAXONOMY.items():
        terms = [*spec["queries"], creator_discovery.NICHE_LABELS.get(niche, "")]
        for tag in spec["hashtags"]:
            tags.append(NewHashtag(tag=tag, source="taxonomy", kind="topic", niche=niche))
            for term in terms:
                if term.strip():
                    links.append(
                        NewTermLink(term=term, tag=tag, source="taxonomy", accumulate=False)
                    )
    return CaptureSummary(
        hashtags=repo.upsert_hashtags(tenant_id, tags),
        links=repo.link_terms(tenant_id, links),
    )


_seeded = False


def ensure_seeded(tenant_id: UUID, *, repository: HashtagRepository | None = None) -> bool:
    """`seed_taxonomy` once per process. The catalog is shared, so one run seeds it for
    every tenant; running it again is harmless (idempotent) but pointless. A failed seed
    is retried on the next call. Returns whether THIS call seeded."""
    global _seeded
    if _seeded:
        return False
    seed_taxonomy(tenant_id, repository=repository)
    _seeded = True
    return True


#: How many catalog hashtags one seed carries. The sector phase uses two
#: (`creator_discovery.SECTOR_CATALOG_TAGS`) and the chips show three; the rest is the
#: reserve for tags the place/own-tag filters drop.
CATALOG_HASHTAGS = 4

#: Only topic-like tags steer a rubro search: places belong to the national / local phases
#: (which compose them with the city themselves) and generic / noise say nothing.
_STEERING_KINDS = ("topic", "unknown")

#: Stricter than the repository's default: a hashtag suggested for the operator's words is
#: shown to them, and a loose fuzzy match reads as the search making things up.
_MIN_SIMILARITY = 0.55


def catalog_hashtags_for(
    tenant_id: UUID, seed: DiscoverySeed, *, repository: HashtagRepository | None = None
) -> tuple[str, ...]:
    """The catalog's hashtags for this rubro — what the operator's words resolve to (a
    typo included: "hamburgesas" reaches what people tag as hamburguesas once a search
    taught it) and the most seen tags of the seed's niches — best first, at most
    `CATALOG_HASHTAGS`, minus what the seed already has.

    Empty is a normal answer: a rubro nothing has searched yet resolves to nothing, and
    the search then runs exactly as before. It gets taught by that very search
    (`capture`), so the next operator who types it is recognised."""
    repo = repository or REPOSITORY
    ensure_seeded(tenant_id, repository=repo)
    own = {creator_discovery._slug(t) for t in seed.hashtags}
    handle = creator_discovery._slug(seed.handle)
    found: list[str] = []

    def take(tag: str) -> None:
        slug = creator_discovery._slug(tag)
        if slug in own or (handle and handle in slug) or tag in found:
            return
        found.append(tag)

    for term in seed.terms:
        for hit in repo.resolve(
            tenant_id,
            term,
            limit=CATALOG_HASHTAGS,
            min_similarity=_MIN_SIMILARITY,
            kinds=_STEERING_KINDS,
        ):
            take(hit.hashtag.tag)
    for niche in seed.niches[:2]:
        for stored in repo.for_niche(tenant_id, niche, limit=CATALOG_HASHTAGS):
            if stored.kind in _STEERING_KINDS:
                take(stored.tag)
    return tuple(found[:CATALOG_HASHTAGS])


# --------------------------------------------------------------------------------------
# Claude: which catalog hashtags fit THIS brand
# --------------------------------------------------------------------------------------

#: How many catalog tags Claude is shown before it starts searching on its own: the
#: operator's words, the seed's niches and the most used tags, so a run that needs no
#: search is one turn. Everything else it finds with the tools (`CatalogTools`).
STARTING_POOL = 40

#: Loose on purpose (the rule path uses 0.55): Claude judges the fit, so a search may
#: return near misses — it must not MISS the variant the model is looking for.
_SEARCH_MIN_SIMILARITY = 0.35

#: One selection per seed and profile is reused this long in the process: the wizard
#: runs discovery on every visit, and the answer for the same brand does not change
#: within a day (stored phases keep theirs for a week anyway).
_CHOICE_TTL_SECONDS = 12 * 3600


@dataclass(frozen=True)
class HashtagChoice:
    """What the seed's `catalog_hashtags` become, and why."""

    tags: tuple[str, ...]
    #: `ai` (Claude chose), `rule` (the fallback: `catalog_hashtags_for`).
    by: str
    #: For AI-chosen tags: tag → `{"model", "fit", "reason"}` — stored with the phase.
    picks: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


_choices: dict[tuple[str, ...], tuple[float, HashtagChoice]] = {}
_choices_lock = threading.Lock()


def _steers(stored: StoredHashtag, seed: DiscoverySeed) -> bool:
    """A catalog tag worth offering: topic-like, not a place (the national / local phases
    compose places themselves), not generic, not the brand's own name or tags."""
    if stored.kind not in _STEERING_KINDS:
        return False
    slug = creator_discovery._slug(stored.tag)
    if slug in creator_discovery._GENERIC_HASHTAGS:
        return False
    if slug in {creator_discovery._slug(t) for t in seed.hashtags}:
        return False
    handle = creator_discovery._slug(seed.handle)
    if handle and handle in slug:
        return False
    return not (
        creator_discovery._is_place_tag(stored.tag, seed)
        or creator_discovery._is_place_tag_anywhere(stored.tag)
    )


def _as_candidate(stored: StoredHashtag) -> hashtag_ai.Candidate:
    return hashtag_ai.Candidate(stored.tag, stored.seen_count, stored.niche)


@dataclass
class CatalogTools:
    """The catalog side of Claude's tools (`hashtag_ai.CatalogSearch`) for one brand:
    what `buscar_hashtags` and `hashtags_del_nicho` return, with the same filter as the
    starting pool — so the model can never be shown a place, a generic tag or the
    brand's own tag, whatever it searches for."""

    tenant_id: UUID
    seed: DiscoverySeed
    repository: HashtagRepository

    def search(self, query: str) -> list[hashtag_ai.Candidate]:
        hits = self.repository.resolve(
            self.tenant_id,
            query,
            limit=hashtag_ai.TOOL_RESULTS * 2,
            min_similarity=_SEARCH_MIN_SIMILARITY,
            kinds=_STEERING_KINDS,
        )
        # Best match first (the repository's order), not most used: a popular near miss
        # must not bury the variant the model searched for.
        return [_as_candidate(h.hashtag) for h in hits if _steers(h.hashtag, self.seed)]

    def niche(self, key: str) -> list[hashtag_ai.Candidate]:
        rows = self.repository.for_niche(self.tenant_id, key, limit=hashtag_ai.TOOL_RESULTS * 2)
        return [_as_candidate(s) for s in rows if _steers(s, self.seed)]


def candidate_pool(
    tenant_id: UUID,
    seed: DiscoverySeed,
    *,
    repository: HashtagRepository | None = None,
    limit: int = STARTING_POOL,
) -> list[StoredHashtag]:
    """The catalog hashtags Claude is shown to start with: what the operator's words
    resolve to, then the seed's niches, then the most seen topic tags of the whole
    catalog — minus places, generic tags and what the brand already uses. A starting
    point, not the limit of what it can choose: the tools reach the rest."""
    repo = repository or REPOSITORY
    ensure_seeded(tenant_id, repository=repo)
    pool: dict[str, StoredHashtag] = {}

    def add(stored: StoredHashtag) -> None:
        if stored.tag not in pool and _steers(stored, seed):
            pool[stored.tag] = stored

    for term in seed.terms:
        for hit in repo.resolve(
            tenant_id, term, limit=20, min_similarity=_SEARCH_MIN_SIMILARITY, kinds=_STEERING_KINDS
        ):
            add(hit.hashtag)
    for niche in seed.niches[:2]:
        for stored in repo.for_niche(tenant_id, niche, limit=20):
            add(stored)
    for stored in repo.top_tags(tenant_id, kinds=_STEERING_KINDS, limit=limit * 3):
        if len(pool) >= limit:
            break
        add(stored)
    return list(pool.values())[:limit]


def _brand_profile(seed: DiscoverySeed, bio: str, category: str) -> hashtag_ai.BrandProfile:
    return hashtag_ai.BrandProfile(
        handle=seed.handle,
        bio=bio,
        category=category,
        rubro=seed.terms,
        niches=tuple(creator_discovery.NICHE_LABELS.get(n, n) for n in seed.niches),
        city=seed.city,
        country=creator_discovery.country_name(seed.country_code),
        own_hashtags=seed.hashtags,
    )


def ai_hashtags_for(
    tenant_id: UUID,
    seed: DiscoverySeed,
    *,
    bio: str = "",
    category: str = "",
    repository: HashtagRepository | None = None,
    api_key: str | None = None,
    selector: Callable[..., tuple[list[hashtag_ai.HashtagPick], hashtag_ai.CallStats]]
    | None = None,
    now: float | None = None,
) -> HashtagChoice:
    """The catalog hashtags that fit this brand, chosen by Claude with its catalog tools
    (`hashtag_ai.select_hashtags` over `CatalogTools`, at most `SECTOR_CATALOG_TAGS`). An
    empty choice is a valid answer — nothing in the catalog fits — and is respected, not
    papered over.

    Falls back to the rule path (`catalog_hashtags_for`) when there is no key, the SDK
    is not installed, or the run fails for any reason: the AI improves the search, it is
    never allowed to stop it. Database errors are NOT swallowed here — the caller already
    treats an unreadable catalog as "search without it"."""
    repo = repository or REPOSITORY
    cache_key = (str(tenant_id), seed.signature(), bio, category)
    moment = now if now is not None else time.time()
    with _choices_lock:
        hit = _choices.get(cache_key)
        if hit is not None and moment - hit[0] < _CHOICE_TTL_SECONDS:
            return hit[1]

    def fallback() -> HashtagChoice:
        return HashtagChoice(catalog_hashtags_for(tenant_id, seed, repository=repo), "rule")

    try:
        key = api_key or hashtag_ai.api_key_from_env()
    except hashtag_ai.MissingAPIKey:
        return fallback()
    starting = [_as_candidate(s) for s in candidate_pool(tenant_id, seed, repository=repo)]
    select = selector or hashtag_ai.select_hashtags
    try:
        picks, stats = select(
            _brand_profile(seed, bio, category),
            CatalogTools(tenant_id, seed, repo),
            creator_discovery.NICHE_LABELS,
            api_key=key,
            starting=starting,
            max_picks=creator_discovery.SECTOR_CATALOG_TAGS,
        )
    except Exception as exc:  # noqa: BLE001 — SDK/transport/model errors all fall back
        logger.warning("hashtags: AI selection failed, using the rule path: %s", exc)
        return fallback()
    logger.info(
        "hashtags: %s chose %s for @%s in %d turns / %d tool calls ($%.4f)",
        stats.model_revision or stats.model_id,
        [p.tag for p in picks],
        seed.handle,
        stats.turns,
        stats.tool_calls,
        stats.cost_usd,
    )
    model = stats.model_revision or stats.model_id
    choice = HashtagChoice(
        tags=tuple(p.tag for p in picks),
        by="ai",
        picks={p.tag: {"model": model, "fit": p.fit, "reason": p.reason} for p in picks},
    )
    with _choices_lock:
        _choices[cache_key] = (moment, choice)
    return choice


# --------------------------------------------------------------------------------------
# Claude: what a tag IS (stored on the shared catalog)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifySummary:
    asked: int = 0
    changed: int = 0
    cost_usd: float = 0.0


def classify_pending(
    tenant_id: UUID,
    *,
    limit: int = hashtag_ai.CLASSIFY_BATCH,
    repository: HashtagRepository | None = None,
    api_key: str | None = None,
    classifier: Callable[..., tuple[list[hashtag_ai.TagClassification], hashtag_ai.CallStats]]
    | None = None,
) -> ClassifySummary:
    """One batch of what the rule could not settle (`needs_classification`), classified
    by Claude and stored under the never-downgrade rule. A no-op without a key, and while
    another pass is running in this process (the three phases of one search each trigger
    one — they would pay to classify the same batch); a failed call is logged and changes
    nothing (the tags stay pending for the next pass)."""
    if not _classify_lock.acquire(blocking=False):
        return ClassifySummary()
    try:
        return _classify_batch(tenant_id, limit, repository or REPOSITORY, api_key, classifier)
    finally:
        _classify_lock.release()


_classify_lock = threading.Lock()


def _classify_batch(
    tenant_id: UUID,
    limit: int,
    repo: HashtagRepository,
    api_key: str | None,
    classifier: Callable[..., tuple[list[hashtag_ai.TagClassification], hashtag_ai.CallStats]]
    | None,
) -> ClassifySummary:
    pending = repo.needs_classification(tenant_id, limit=min(limit, hashtag_ai.CLASSIFY_BATCH))
    if not pending:
        return ClassifySummary()
    try:
        key = api_key or hashtag_ai.api_key_from_env()
    except hashtag_ai.MissingAPIKey:
        return ClassifySummary()
    classify = classifier or hashtag_ai.classify_hashtags
    try:
        results, stats = classify(
            [p.tag for p in pending], creator_discovery.NICHE_LABELS, api_key=key
        )
    except Exception as exc:  # noqa: BLE001 — the catalog only ever gains; never raise
        logger.warning("hashtags: AI classification failed: %s", exc)
        return ClassifySummary(asked=len(pending))
    decisions = [Classification(r.tag, r.kind, r.niche, r.country_code) for r in results]
    changed = repo.apply_classifications(tenant_id, decisions)
    logger.info(
        "hashtags: classified %d/%d pending tags with %s ($%.4f)",
        changed,
        len(pending),
        stats.model_revision or stats.model_id,
        stats.cost_usd,
    )
    return ClassifySummary(asked=len(pending), changed=changed, cost_usd=stats.cost_usd)


def _rubro_terms(seed: DiscoverySeed) -> list[str]:
    """How the operator (and the taxonomy) name the rubro this run searched for."""
    terms = list(seed.terms)
    for niche in seed.niches[:2]:
        terms.append(creator_discovery.NICHE_TAXONOMY[niche]["queries"][0])
    seen: set[str] = set()
    return [
        t
        for t in terms
        if not (creator_discovery._slug(t) in seen or seen.add(creator_discovery._slug(t)))
    ]


def capture(
    tenant_id: UUID,
    seed: DiscoverySeed,
    phase_key: str,
    accounts: list[Candidate],
    *,
    repository: HashtagRepository | None = None,
) -> CaptureSummary:
    """Store what a finished phase saw: every hashtag its accounts used (with the network,
    a sighting per account), and — for the sector phase only — a link from each of the
    rubro's words to the hashtags at least `MIN_ACCOUNTS_FOR_LINK` distinct accounts used.

    The link is the whole point: it is how "peluquería canina" comes to mean
    `#peluqueriacanina` and `#groomingperros` the next time anyone types it. A typo'd
    rubro links nothing on its own — its accounts never passed the sector filter — which
    is the safe direction: the catalog only learns from searches that found the rubro."""
    repo = repository or REPOSITORY
    per_network: dict[tuple[str, str], set[str]] = defaultdict(set)
    accounts_per_tag: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for candidate in accounts:
        for raw in candidate.hashtags_seen:
            tag = raw.strip().lstrip("#").lower()
            if not tag:
                continue
            per_network[(tag, candidate.network)].add(candidate.username.lower())
            accounts_per_tag[tag].add(candidate.key)

    new_tags: list[NewHashtag] = []
    kinds: dict[str, str] = {}
    skipped = 0
    for (tag, network), users in per_network.items():
        kind, niche, country = classify_tag(tag, seed)
        try:
            new_tags.append(
                NewHashtag(
                    tag=tag,
                    source="observed",
                    kind=kind,
                    niche=niche,
                    country_code=country,
                    network=network,
                    seen=len(users),
                )
            )
        except ValueError:
            skipped += 1
            continue
        kinds[tag] = kind
    stored = repo.upsert_hashtags(tenant_id, new_tags) if new_tags else 0

    links: list[NewTermLink] = []
    if phase_key == LINKING_PHASE:
        for term in _rubro_terms(seed):
            for tag, owners in accounts_per_tag.items():
                if len(owners) < MIN_ACCOUNTS_FOR_LINK or kinds.get(tag) in (
                    None,
                    "generic",
                    "place",
                ):
                    continue
                try:
                    links.append(NewTermLink(term=term, tag=tag, source="observed"))
                except ValueError:
                    skipped += 1
    written = repo.link_terms(tenant_id, links) if links else 0
    return CaptureSummary(hashtags=stored, links=written, skipped=skipped)
