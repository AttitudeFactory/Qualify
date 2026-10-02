"""The Reflex side of the shared creator pool (`qualify_api.creators`, migration 0036 —
§ request 2026-10-01: "primero busca en la db las cuentas que estaban ya scrapeadas y
luego, si no hay coincidencias o hacen falta, va al scraper").

Two things a search run gets from here:

- a `payload_cache` for its vendor client (`creator_discovery.PoolClient`): every call
  the search would make — a keyword or hashtag page, a Google query, a profile read —
  is asked of `vendor_payloads` first and only goes to Scrape Creators when the pool
  has no live answer (7 days for searches, 30 for profiles). The same query any tenant
  ran inside that time costs nothing and takes no network.
- `record_pool`: after a phase, every account the run saw (the whole pool, not the
  eight it showed) goes into `creators`, and which query surfaced it into
  `creator_sightings` — what lets the next search, or a screen, ask "qué cuentas
  aparecieron para `programacion`" without the vendor.

Without a session (no tenant to open the door with) nothing is read or written and the
search runs as before, live.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from qualify_api.creators import (
    CachedPayload,
    CreatorFacts,
    CreatorPoolRepository,
    PostgresCreatorPoolRepository,
    Sighting,
)
from sqlalchemy.exc import SQLAlchemyError

from .creator_discovery import Candidate, DiscoverySeed, _slug

logger = logging.getLogger(__name__)

#: Which `Candidate.sources` labels count as a sighting, and under which kind.
_SIGHTING_KINDS = {"keyword", "hashtag", "google", "related", "mirror", "manual"}


class PayloadCache:
    """`creator_discovery._get_retry`'s two methods over the pool's `vendor_payloads`.
    A database failure is a miss on `get` and a dropped row on `put`: the search goes
    on with the vendor, as it always could."""

    def __init__(self, repository: CreatorPoolRepository) -> None:
        self._repository = repository
        self.hits = 0
        self.misses = 0

    def get(self, path: str, params: Mapping[str, Any]) -> CachedPayload | None:
        try:
            hit = self._repository.get_payload(path, params)
        except SQLAlchemyError as exc:
            logger.warning("creator pool: payload not read: %s", exc)
            return None
        if hit is None:
            self.misses += 1
        else:
            self.hits += 1
        return hit

    def put(
        self,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int = 200,
        credits_charged: int = 0,
    ) -> None:
        try:
            self._repository.put_payload(
                path, params, payload, status=status, credits_charged=credits_charged
            )
        except SQLAlchemyError as exc:
            logger.warning("creator pool: payload not written: %s", exc)


def payload_cache(tenant_id: UUID | None) -> PayloadCache | None:
    """The cache a search run carries, or none without a session."""
    if tenant_id is None:
        return None
    return PayloadCache(PostgresCreatorPoolRepository(tenant_id))


def facts_from_candidate(candidate: Candidate, *, now: float | None = None) -> CreatorFacts:
    """One account of a run's pool as the shared pool keeps it. `read_at` only when a
    profile read backed it (its sources say so): a feed sighting carries the author's
    size on TikTok's keyword feed, nothing on the hashtag feed."""
    moment = now if now is not None else time.time()
    read = any(src.endswith(":profile") for src in candidate.sources)
    return CreatorFacts(
        network=candidate.network,
        handle=candidate.username,
        full_name=candidate.full_name,
        bio=" ".join(candidate.bio.split()),
        external_url=candidate.external_url,
        profile_url=candidate.profile_url,
        avatar_url=candidate.avatar,
        category="",  # a candidate keeps its category among its texts; not told apart here
        country_code=candidate.country_code or "",
        followers=candidate.followers,
        total_likes=candidate.total_likes,
        is_private=candidate.is_private,
        is_verified=candidate.is_verified,
        related=(),
        hashtags=tuple(candidate.hashtags_seen),
        posts_seen=candidate.posts_seen,
        ai_posts_seen=min(candidate.ai_posts_seen, candidate.posts_seen),
        likes_seen=candidate.likes_seen,
        comments_seen=candidate.comments_seen,
        views_seen=candidate.views_seen,
        read_at=moment if read else None,
        seen_at=moment,
    )


def sightings_from_candidate(
    candidate: Candidate, seed: DiscoverySeed, *, now: float | None = None
) -> list[Sighting]:
    """Which searches surfaced the account, from its `sources` labels
    (`tiktok:keyword:foodie`, `tiktok:hashtag:#cucutafood`, `instagram:google:foodie
    Cúcuta`, `instagram:related:@mouredev`, `tiktok:mirror:@x`, `tiktok:manual`)."""
    moment = now if now is not None else time.time()
    out: list[Sighting] = []
    for source in candidate.sources:
        parts = source.split(":", 2)
        if len(parts) < 2 or parts[1] not in _SIGHTING_KINDS:
            continue
        kind = parts[1]
        term = parts[2].lstrip("#@") if len(parts) == 3 else kind
        term = " ".join(term.split()).lower()
        if not term:
            continue
        out.append(
            Sighting(
                network=candidate.network,
                handle=candidate.username,
                kind=kind,
                term=term,
                country_code=seed.country_code or "",
                city_slug=_slug(seed.city) if seed.city else "",
                seen_at=moment,
            )
        )
    return out


def record_pool(
    tenant_id: UUID,
    candidates: Iterable[Candidate],
    seed: DiscoverySeed,
    *,
    repository: CreatorPoolRepository | None = None,
    now: float | None = None,
) -> tuple[int, int]:
    """Everything a run saw, into the shared pool: `(accounts, sightings)` written. A
    failure here loses the next search's shortcut, never this one's result."""
    repo = repository or PostgresCreatorPoolRepository(tenant_id)
    rows: list[CreatorFacts] = []
    seen: list[Sighting] = []
    for candidate in candidates:
        if candidate.network not in ("tiktok", "instagram") or not candidate.username.strip():
            continue
        try:
            rows.append(facts_from_candidate(candidate, now=now))
        except ValueError:
            continue
        seen.extend(sightings_from_candidate(candidate, seed, now=now))
    try:
        written = repo.upsert_creators(rows)
        sighted = repo.record_sightings(seen)
    except SQLAlchemyError as exc:
        logger.warning("creator pool: run not recorded: %s", exc)
        return 0, 0
    return written, sighted
