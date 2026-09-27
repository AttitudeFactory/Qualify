"""TEMPORARY `PostReader` over the creative module's `content_drafts` (QUA-108).

**This is a seam, not a POST model.** QUA-109 (Deivid) defines the real POST. Until it
lands, the only content in the repo that looks like a POST is a creative draft, so this
adapter lets the Planificador be built and tested now. When QUA-109 ships its reader,
delete this file and swap the one line in `composition.py` that constructs it.

Rules this adapter keeps so it can never become a second POST definition:
- **Read-only.** It never writes to `content_drafts` (or any creative table), never runs
  the creative FSM, and adds no columns anywhere.
- **No invented fields.** What the draft model does not have (reuse type, R2 existence)
  is returned as unknown, not guessed. `category` is the POST's own (0027, QUA-109) —
  never the brief's render format, and never a default.
- **One publishability rule.** Whether a POST can be published — for the calendar card
  and for QUA-111's executor alike — is `publishable.evaluate` over one candidate built
  by `_candidate`; nothing here decides it on its own.
- **Drafts are read directly, not through `ContentService.list_drafts`**, because that
  call runs the draft reaper (a write) as a side effect.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from qualify_creative.schemas import CopyPayload
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative import fsm as draft_fsm
from qualify_api.creative import models as creative
from qualify_api.planner.post_reader import (
    ApprovalStatus,
    NotPublishable,
    PostSummary,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.publishable import (
    REASON_TEXT,
    MediaCandidate,
    PostCandidate,
    evaluate,
)

# Draft status → approval as the calendar sees it. STAGED/PUBLISHED drafts were approved
# first (creative FSM), so they read as approved.
_APPROVAL_BY_DRAFT_STATUS: dict[str, ApprovalStatus] = {
    draft_fsm.DRAFTING: ApprovalStatus.NOT_READY,
    draft_fsm.FAILED: ApprovalStatus.NOT_READY,
    draft_fsm.GENERATED: ApprovalStatus.PENDING,
    draft_fsm.APPROVED: ApprovalStatus.APPROVED,
    draft_fsm.STAGED: ApprovalStatus.APPROVED,
    draft_fsm.PUBLISHED: ApprovalStatus.APPROVED,
    draft_fsm.REJECTED: ApprovalStatus.REJECTED,
}

_SCHEDULABLE_DRAFT_STATUSES: tuple[str, ...] = tuple(
    status for status, approval in _APPROVAL_BY_DRAFT_STATUS.items() if approval.is_schedulable
)

_EXCERPT_CHARS = 140
_SCHEDULABLE_LIMIT = 100


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _EXCERPT_CHARS else text[: _EXCERPT_CHARS - 1].rstrip() + "…"


def _caption(variant: creative.CopyVariant | None) -> str:
    if variant is None:
        return ""
    payload = variant.edited_copy or variant.copy or {}
    caption = payload.get("caption") if isinstance(payload, dict) else None
    return caption if isinstance(caption, str) else ""


def _approved_caption(session: Session, draft: creative.ContentDraft) -> str | None:
    """The organic caption of the variant the human approved (`selected_variant_id`),
    through `CopyPayload.rendered_caption` — the one concatenation the creative module
    defines for the publisher. None when there is no readable selected variant."""
    if draft.selected_variant_id is None:
        return None
    variant = session.get(creative.CopyVariant, draft.selected_variant_id)
    if variant is None or variant.draft_id != draft.id:
        return None
    try:
        return CopyPayload.model_validate(variant.edited_copy or variant.copy).rendered_caption()
    except ValidationError:
        return None


def _candidate(
    session: Session,
    tenant_id: UUID,
    draft: creative.ContentDraft,
    images: Sequence[creative.ImageAsset],
) -> PostCandidate:
    return PostCandidate(
        tenant_id=tenant_id,
        post_id=draft.id,
        brand_id=draft.brand_id,
        approval=_APPROVAL_BY_DRAFT_STATUS.get(draft.status, ApprovalStatus.NOT_READY),
        revision=draft.revision,
        approved_revision=draft.approved_revision,
        category=draft.category,
        caption=_approved_caption(session, draft),
        media=tuple(
            MediaCandidate(
                object_key=image.object_key,
                content_type=image.content_type,
                media_type=image.media_type,
                position=image.position,
            )
            for image in images
        ),
        requires_ai_disclosure=draft.requires_ai_disclosure,
        provenance=(
            ("pipeline_version", draft.pipeline_version),
            ("selected_variant_id", str(draft.selected_variant_id)),
        ),
    )


def _images(session: Session, draft_id: UUID) -> list[creative.ImageAsset]:
    """In creation order (the card's thumbnail is the first); `evaluate` orders the
    publishable media by `position` itself."""
    return list(
        session.scalars(
            select(creative.ImageAsset)
            .where(creative.ImageAsset.draft_id == draft_id)
            .order_by(creative.ImageAsset.created_at)
        ).all()
    )


class DraftPostReader:
    """`PostReader` backed by `content_drafts` + `content_briefs` + `copy_variants` +
    `image_assets`, all through `tenant_session` (RLS-scoped)."""

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock

    def get(self, *, tenant_id: UUID, post_id: UUID) -> PostSummary | None:
        return self.get_many(tenant_id=tenant_id, post_ids=[post_id]).get(post_id)

    def get_many(self, *, tenant_id: UUID, post_ids: Iterable[UUID]) -> dict[UUID, PostSummary]:
        ids = list(dict.fromkeys(post_ids))
        if not ids:
            return {}
        with tenant_session(tenant_id) as session:
            drafts = session.scalars(
                select(creative.ContentDraft).where(creative.ContentDraft.id.in_(ids))
            ).all()
            return {draft.id: self._summarize(session, tenant_id, draft) for draft in drafts}

    def list_schedulable(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        with tenant_session(tenant_id) as session:
            drafts = session.scalars(
                select(creative.ContentDraft)
                .where(
                    creative.ContentDraft.brand_id == brand_id,
                    creative.ContentDraft.status.in_(_SCHEDULABLE_DRAFT_STATUSES),
                )
                .order_by(creative.ContentDraft.created_at.desc())
                .limit(_SCHEDULABLE_LIMIT)
            ).all()
            return [self._summarize(session, tenant_id, draft) for draft in drafts]

    def get_publishable(
        self, *, tenant_id: UUID, post_id: UUID
    ) -> PublishablePost | NotPublishable:
        with tenant_session(tenant_id) as session:
            draft = session.get(creative.ContentDraft, post_id)
            if draft is None:
                return NotPublishable(post_id=post_id, reason=UnpublishableReason.POST_NOT_FOUND)
            return evaluate(_candidate(session, tenant_id, draft, _images(session, draft.id)))

    def _summarize(
        self, session: Session, tenant_id: UUID, draft: creative.ContentDraft
    ) -> PostSummary:
        brief = session.get(creative.ContentBrief, draft.brief_id)
        variant = None
        if draft.selected_variant_id is not None:
            variant = session.get(creative.CopyVariant, draft.selected_variant_id)
        if variant is None:
            # Not approved yet: show the first generated variant so the card has text.
            variant = session.scalars(
                select(creative.CopyVariant)
                .where(creative.CopyVariant.draft_id == draft.id)
                .order_by(creative.CopyVariant.ordinal)
            ).first()
        images = _images(session, draft.id)

        now = self._clock()
        thumbnail = None
        if images:
            first = images[0]
            expired = first.media_expires_at is not None and first.media_expires_at < now
            if first.media_url and not expired:
                thumbnail = first.media_url

        verdict = evaluate(_candidate(session, tenant_id, draft, images))
        publishable = isinstance(verdict, PublishablePost)
        title = (brief.topic if brief is not None else "") or _excerpt(_caption(variant))[:60]
        return PostSummary(
            post_id=draft.id,
            brand_id=draft.brand_id,
            title=title or "(sin tema)",
            approval=_APPROVAL_BY_DRAFT_STATUS.get(draft.status, ApprovalStatus.NOT_READY),
            approved_at=draft.approved_at.isoformat() if draft.approved_at else None,
            category=draft.category,
            media_product_type=verdict.media_product_type if publishable else None,
            content_type=brief.content_type if brief is not None else None,
            reuse_type=None,  # the draft model has no such concept — QUA-109
            lifecycle_status=draft.status,
            thumbnail_url=thumbnail,
            caption_excerpt=_excerpt(_caption(variant)),
            asset_count=len(images),
            asset_types=tuple("IMAGE" for _ in images),
            is_publishable=publishable,
            unpublishable_reason="" if publishable else REASON_TEXT[verdict.reason],
            detail_href=f"/drafts/{draft.id}",
        )
