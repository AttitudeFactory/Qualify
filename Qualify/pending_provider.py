"""Backend access of the menu's pending counters (m-24842963, NAV-6).

Two reads, both read-only and both through `tenant_session` (RLS scopes every table to
the tenant; nothing filters by `tenant_id` by hand):

- `read_attention` — who waits for an answer, through `qualify_api.attention` (the same
  count «Por responder» shows, m-24842990): one SQL round trip;
- `read_publications` — how many publications wait for approval and how many approved
  ones have no day yet, through the planner service the gallery and Tu semana read.

Blocking — the state calls them with `asyncio.to_thread`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_api.attention import PendingCounts, pending_counts
from qualify_api.planner.composition import production_planner_service

from .creative_provider import default_brand_id
from .pending_vm import count_to_approve


@dataclass(frozen=True)
class PublicationCounts:
    approve: int = 0
    schedule: int = 0


def read_attention(tenant_id: UUID) -> PendingCounts:
    return pending_counts(tenant_id)


def read_publications(tenant_id: UUID) -> PublicationCounts:
    brand_id = default_brand_id(tenant_id)
    if brand_id is None:  # no brand yet: nothing can wait for approval or a day
        return PublicationCounts()
    service = production_planner_service()
    posts = service.list_posts(tenant_id=tenant_id, brand_id=brand_id)
    unscheduled = service.list_unscheduled(tenant_id=tenant_id, brand_id=brand_id)
    return PublicationCounts(approve=count_to_approve(posts), schedule=len(unscheduled))


__all__ = ["PublicationCounts", "read_attention", "read_publications"]
