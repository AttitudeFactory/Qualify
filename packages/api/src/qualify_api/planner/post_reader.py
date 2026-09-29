"""The seam between the Planificador and the POST (QUA-109).

This module defines what the calendar needs to READ about a POST — nothing more. It is
not a POST model: it owns no table, writes nothing, and defines no lifecycle. QUA-109
owns the POST; when it lands, it provides a `PostReader` implementation and the
temporary adapter (`draft_post_reader.py`) is deleted. Nothing else in the planner
changes.

Fields are optional wherever today's content model cannot supply them yet (category,
reuse type, multi-asset). The calendar renders "unknown" honestly instead of guessing.

`get_publishable` is QUA-111's read: the approved POST in the exact shape the publisher
takes (`PublishablePost`), or an explicit `NotPublishable` reason. The rule behind it
lives in `publishable.py`, not in any reader.
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
    # An http(s) URL, or a local upload-store key the UI resolves with
    # `rx.get_upload_url`. Never a video file nor an object-store (R2) key.
    thumbnail_url: str | None = None
    caption_excerpt: str = ""
    asset_count: int = 0
    asset_types: tuple[str, ...] = ()
    # Whether the assets are somewhere QUA-111 can publish them from (R2), and if not why.
    is_publishable: bool = False
    unpublishable_reason: str = ""
    detail_href: str = ""


class UnpublishableReason(StrEnum):
    """Why QUA-111 will not hand a POST to the publisher. One reason per refusal, the
    first rule that fails in `publishable.evaluate`'s fixed order."""

    POST_NOT_FOUND = "post_not_found"  # absent, or another tenant's (RLS: same answer)
    NOT_APPROVED = "not_approved"
    REVISION_NOT_APPROVED = "revision_not_approved"  # edited after approval
    APPROVED_COPY_MISSING = "approved_copy_missing"  # no readable selected variant
    CATEGORY_MISSING = "category_missing"
    CATEGORY_NOT_PUBLISHABLE = "category_not_publishable"  # e.g. tiktok_video
    NO_MEDIA = "no_media"
    TOO_MANY_MEDIA = "too_many_media"
    MEDIA_ORDER_AMBIGUOUS = "media_order_ambiguous"  # duplicate positions
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    UNSUPPORTED_SHAPE = "unsupported_shape"  # category + media the publisher cannot do
    MEDIA_NOT_IN_R2 = "media_not_in_r2"  # no key, or not under this tenant's prefix
    CONTENT_TYPE_MISSING = "content_type_missing"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"


@dataclass(frozen=True)
class PublishableMedia:
    """One item exactly as `PublishService` takes it. `media_type` is the publisher's
    vocabulary (`IMAGE`/`VIDEO`), `object_key` is under the tenant's R2 prefix."""

    object_key: str
    content_type: str
    media_type: str
    position: int


@dataclass(frozen=True)
class PublishablePost:
    """What QUA-111 publishes: the approved revision of a POST, already in a shape the
    publisher accepts. The executor needs nothing else from the POST — not how it was
    generated, not where its source files live.

    The object keys are validated against the tenant prefix, not probed in R2: that the
    object exists there is QUA-109/110's guarantee when they hand the POST over (a
    missing one fails the publish attempt, it never publishes something else).
    """

    tenant_id: UUID
    post_id: UUID
    brand_id: UUID
    approved_revision: int
    caption: str
    media_product_type: str  # IMAGE / CAROUSEL / REELS / STORIES
    media: tuple[PublishableMedia, ...]
    requires_ai_disclosure: bool = False
    provenance: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class NotPublishable:
    post_id: UUID
    reason: UnpublishableReason
    detail: str = ""


class PostReader(Protocol):
    """Read-only access to POSTs, tenant-scoped. Every method returns only POSTs the
    tenant can see (RLS), so "absent" and "belongs to another tenant" are the same answer.
    """

    def get(self, *, tenant_id: UUID, post_id: UUID) -> PostSummary | None: ...

    def get_publishable(
        self, *, tenant_id: UUID, post_id: UUID
    ) -> PublishablePost | NotPublishable:
        """The POST as QUA-111 may publish it, or the explicit reason it may not —
        decided by `publishable.evaluate`, the same rule the calendar card shows."""
        ...

    def get_many(self, *, tenant_id: UUID, post_ids: Iterable[UUID]) -> dict[UUID, PostSummary]: ...

    def list_schedulable(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        """POSTs of the brand that could be planned now (`approval.is_schedulable`),
        newest first."""
        ...
