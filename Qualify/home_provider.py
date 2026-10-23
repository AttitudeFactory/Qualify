"""Inicio's backend door (m-24842962): the counts through `tenant_session`, as a VM.

Blocking (DB) — the state runs it with `asyncio.to_thread`.

«Publicaciones que esperan tu revisión» opens the gallery on «Por completar», so it is
counted with the gallery's own rule (`planner.gallery.gallery_state` over the planner's
`list_posts`): the number on Inicio is the number the owner finds on arrival (N11). The
SQL count of `read_home_counts` stays only as the fallback when the brand or the planner
cannot be read.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from uuid import UUID

from qualify_api.home import HomeCounts, read_home_counts
from qualify_api.planner.composition import production_planner_service
from qualify_api.planner.gallery import GalleryState, gallery_state
from qualify_api.planner.post_reader import PostSummary

from .creative_provider import default_brand_id
from .home_vm import HomeVM, build_home_vm

logger = logging.getLogger(__name__)


def count_needs_review(posts: Iterable[PostSummary]) -> int:
    """How many POSTs the gallery's «Por completar» filter shows (pure)."""
    return sum(1 for post in posts if gallery_state(post) is GalleryState.NEEDS_ACTION)


def _drafts_to_review(tenant_id: UUID) -> int | None:
    brand_id = default_brand_id(tenant_id)
    if brand_id is None:
        return None
    posts = production_planner_service().list_posts(tenant_id=tenant_id, brand_id=brand_id)
    return count_needs_review(posts)


def load_home(tenant_id: UUID) -> HomeVM:
    counts: HomeCounts = read_home_counts(tenant_id)
    try:
        to_review = _drafts_to_review(tenant_id)
    except Exception as exc:  # the rest of Inicio still loads; keep the SQL figure
        logger.warning("home drafts-to-review count failed: %s", type(exc).__name__)
        to_review = None
    if to_review is not None:
        counts = replace(counts, drafts_to_approve=to_review)
    return build_home_vm(counts)


__all__ = ["count_needs_review", "load_home"]
