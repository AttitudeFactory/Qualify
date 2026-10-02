"""The Reflex side of the creator read history (`qualify_api.growth`, migration 0034):
what the Brand Kit reads about a creator is recorded as a row the moment it is read —
the brand's own profile and posts on Analizar, every referente's figures when a search
phase lands — so the series exists for the organic growth estimate. Nothing here is
read back on screen yet; this is the base that estimate needs (2026-10-01)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from qualify_api.growth import GrowthRepository, PostgresGrowthRepository, PostRead, ProfileRead

from .creator_discovery import Candidate

logger = logging.getLogger(__name__)

REPOSITORY: GrowthRepository = PostgresGrowthRepository()


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def reads_from_profile(
    network: str, handle: str, profile: Mapping[str, Any]
) -> tuple[ProfileRead, list[PostRead]]:
    """The profile read (`fetch_profile_and_posts`' dict) as rows: the account's figures
    at `fetchedAt`, and one row per post that carries an id (a post without one cannot
    be followed over time, so it is not a series point)."""
    fetched_at = profile.get("fetchedAt")
    moment = float(fetched_at) if isinstance(fetched_at, (int, float)) else time.time()
    read = ProfileRead(
        network,
        handle,
        moment,
        source="profile",
        followers=_int(profile.get("followers")),
        following=_int(profile.get("following")),
        posts_count=_int(profile.get("postsCount")),
        total_likes=_int(profile.get("totalLikes")),
    )
    posts: list[PostRead] = []
    for item in profile.get("recentPosts") or []:
        if not isinstance(item, Mapping) or not item.get("postId"):
            continue
        taken_at = _int(item.get("takenAt"))
        if taken_at is None:
            continue
        posts.append(
            PostRead(
                network,
                handle,
                str(item["postId"]),
                taken_at,
                moment,
                views=_int(item.get("views")),
                likes=_int(item.get("likes")),
                comments=_int(item.get("comments")),
                shares=_int(item.get("shares")),
                ai_generated=item.get("aiGenerated")
                if isinstance(item.get("aiGenerated"), bool)
                else None,
                ai_label=str(item.get("aiLabel") or ""),
                ai_source=str(item.get("aiSource") or ""),
            )
        )
    return read, posts


def record_profile_read(
    tenant_id: UUID,
    network: str,
    handle: str,
    profile: Mapping[str, Any],
    *,
    repository: GrowthRepository | None = None,
) -> int:
    """Record one live profile read; the number of post rows written."""
    read, posts = reads_from_profile(network, handle, profile)
    (repository or REPOSITORY).record(tenant_id, [read], posts)
    return len(posts)


def reads_from_candidates(
    accounts: Iterable[Candidate], *, now: float | None = None
) -> list[ProfileRead]:
    """A search phase's accounts as discovery rows — only the ones whose size was read
    (a candidate without a follower count was never read, there is nothing to keep)."""
    moment = now if now is not None else time.time()
    return [
        ProfileRead(
            c.network,
            c.username,
            moment,
            source="discovery",
            followers=c.followers,
            total_likes=c.total_likes,
        )
        for c in accounts
        if c.followers is not None and c.network in ("tiktok", "instagram") and c.username.strip()
    ]


def record_discovered(
    tenant_id: UUID,
    accounts: Iterable[Candidate],
    *,
    repository: GrowthRepository | None = None,
    now: float | None = None,
) -> int:
    """Record the referentes a search phase found; the number of rows written."""
    reads = reads_from_candidates(accounts, now=now)
    if reads:
        (repository or REPOSITORY).record(tenant_id, reads)
    return len(reads)
