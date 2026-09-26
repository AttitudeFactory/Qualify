"""The seam between the Planificador and the POST (QUA-109).

This module defines what the calendar needs to READ about a POST — nothing more. It is
not a POST model: it owns no table, writes nothing, and defines no lifecycle. QUA-109
owns the POST; when it lands, it provides a `PostReader` implementation and the
temporary adapter (`draft_post_reader.py`) is deleted. Nothing else in the planner
changes.

Fields are optional wherever today's content model cannot supply them yet (category,
reuse type, multi-asset). The calendar renders "unknown" honestly instead of guessing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ApprovalStatus(StrEnum):
    """The POST's approval as the calendar sees it. Execution requires APPROVED
    (`rules.py`); every other value blocks it."""

    NOT_READY = "not_ready"  # still being produced (or failed) — cannot be planned
    PENDING = "pending"  # ready for human review, not yet approved
    APPROVED = "approved"
    REJECTED = "rejected"

    @property
    def is_schedulable(self) -> bool:
        """Whether the calendar may assign this POST. A pending POST can be planned —
        planning and approval are separate decisions; the approval gate is at execution."""
        return self in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED)


@dataclass(frozen=True)
class PostSummary:
    """Everything the Planificador needs to show and plan a POST, and nothing it would
    have to keep in sync. No assets, no full caption, no script: those stay on the POST.
    """

    post_id: UUID
    brand_id: UUID
    title: str
    approval: ApprovalStatus
    approved_at: str | None = None  # ISO-8601, display only
    # What the POST is, as a publishing format (galería/story/reel…) — QUA-109 decides
    # the vocabulary. `media_product_type` is its translation to what Meta receives.
    category: str | None = None
    media_product_type: str | None = None
    # What the POST is about (creative's `ContentType`, e.g. "promotion").
    content_type: str | None = None
    # How the POST is reused over time (RECURRENTE/PROMOCIONAL…) — QUA-109.
    reuse_type: str | None = None
    lifecycle_status: str = ""
    thumbnail_url: str | None = None
    caption_excerpt: str = ""
    asset_count: int = 0
    asset_types: tuple[str, ...] = ()
    # Whether the assets are somewhere QUA-111 can publish them from (R2), and if not why.
    is_publishable: bool = False
    unpublishable_reason: str = ""
    detail_href: str = ""


class PostReader(Protocol):
    """Read-only access to POSTs, tenant-scoped. Every method returns only POSTs the
    tenant can see (RLS), so "absent" and "belongs to another tenant" are the same answer.
    """

    def get(self, *, tenant_id: UUID, post_id: UUID) -> PostSummary | None: ...

    def get_many(self, *, tenant_id: UUID, post_ids: Iterable[UUID]) -> dict[UUID, PostSummary]: ...

    def list_schedulable(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        """POSTs of the brand that could be planned now (`approval.is_schedulable`),
        newest first."""
        ...
