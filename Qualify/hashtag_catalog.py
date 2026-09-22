"""The bridge between the referentes search (`creator_discovery`) and the shared hashtag
catalog (`qualify_api.hashtags`, migration 0022).

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
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from qualify_api.hashtags import (
    HashtagRepository,
    NewHashtag,
    NewTermLink,
    PostgresHashtagRepository,
)

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
