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
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from qualify_creative.schemas import CopyPayload
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qualify_api.creative import fsm as draft_fsm
from qualify_api.creative import models as creative
from qualify_api.planner.fsm import EventStatus
from qualify_api.planner.models import CalendarEvent
from qualify_api.planner.post_reader import (
    ApprovalStatus,
    NotPublishable,
    PostOutput,
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
_GALLERY_LIMIT = 200

# Every object-store key starts with the tenant prefix (`qualify_shared.objects.keys`):
# `t/{tenant_id}/…`. Local upload-store keys (`generated/…`, `uploads/…`) never do.
_OBJECT_STORE_PREFIX = "t/"


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
    output_port: str | None = None,
) -> PostCandidate:
    """The whole POST, or — with `output_port` (MP-11) — the candidate for ONE of its
    template outputs. All assets are handed over either way; `evaluate` keeps the port's
    own and re-numbers them, so the filter lives in the one rule, not here."""
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
                output_port=image.output_port,
            )
            for image in images
        ),
        requires_ai_disclosure=draft.requires_ai_disclosure,
        provenance=(
            ("pipeline_version", draft.pipeline_version),
            ("selected_variant_id", str(draft.selected_variant_id)),
        ),
        output_port=output_port,
    )


def output_ports_of(images: Sequence[creative.ImageAsset]) -> tuple[str, ...]:
    """The POST's template ports, distinct, in `position` order (`reel`, `feed`, `story`
    for a `promo_producto` run). Empty for a POST rendered before the template engine —
    such a POST is planned whole."""
    ordered = sorted(images, key=lambda image: image.position)
    return tuple(dict.fromkeys(image.output_port for image in ordered if image.output_port))


def _outputs(
    session: Session,
    tenant_id: UUID,
    draft: creative.ContentDraft,
    images: Sequence[creative.ImageAsset],
) -> tuple[PostOutput, ...]:
    outputs: list[PostOutput] = []
    for port in output_ports_of(images):
        first = min(
            (image for image in images if image.output_port == port),
            key=lambda image: image.position,
        )
        verdict = evaluate(_candidate(session, tenant_id, draft, images, output_port=port))
        publishable = isinstance(verdict, PublishablePost)
        outputs.append(
            PostOutput(
                port=port,
                media_type=first.media_type,
                media_product_type=verdict.media_product_type if publishable else None,
                is_publishable=publishable,
                unpublishable_reason="" if publishable else REASON_TEXT[verdict.reason],
            )
        )
    return tuple(outputs)


class _AssetView(Protocol):
    media_type: str
    media_url: str
    object_key: str | None
    media_expires_at: datetime | None
    params: dict | None
    position: int


def thumbnail_source(
    *, preview_key: str | None, assets: Sequence[_AssetView], now: datetime
) -> str | None:
    """What the calendar card can show in an `<img>`: an `http(s)` URL, or a key of the
    local upload store (the UI turns it into a URL with `rx.get_upload_url`, as the
    creative screens do). The POST's own `preview_key` (0027) comes first — a video's
    poster or the first image — then the first asset.

    Never a video file (an `<img>` cannot show one; a video without a poster gets the
    placeholder), never an R2 key (`t/{tenant}/…`: nothing serves the object store to a
    browser), never a provider URL that already expired. `None` → the card's placeholder.
    """
    ordered = sorted(assets, key=lambda asset: asset.position)
    video_files = {
        key
        for asset in ordered
        if asset.media_type == "video"
        for key in (asset.object_key, asset.media_url)
        if key
    }
    expired = {
        asset.media_url
        for asset in ordered
        if asset.media_expires_at is not None and asset.media_expires_at < now
    }
    candidates: list[str | None] = [preview_key]
    if ordered:
        first = ordered[0]
        if first.media_type == "video":
            poster = (first.params or {}).get("thumbnail_key")
            candidates.append(str(poster) if poster else None)
        else:
            candidates.append(first.media_url)
    for candidate in candidates:
        if (
            candidate
            and candidate not in video_files
            and candidate not in expired
            and not candidate.startswith(_OBJECT_STORE_PREFIX)
        ):
            return candidate
    return None


# "Live" = planned and not yet out (scheduled / publishing). A published event is history,
# counted by `times_published`; the gallery's «En calendario» badge reads only this.
_LIVE_STATUSES: tuple[str, ...] = (EventStatus.SCHEDULED.value, EventStatus.PUBLISHING.value)


def _history(session: Session, post_ids: Sequence[UUID]) -> dict[UUID, tuple[int, bool]]:
    """Per POST, how many of its events were published and whether one is live
    (scheduled or publishing — not yet out) — one aggregate over `calendar_events` for
    the whole batch (QUA-118 D2). Read-only, under the same RLS session as the drafts."""
    if not post_ids:
        return {}
    rows = session.execute(
        select(
            CalendarEvent.post_id,
            func.count().filter(CalendarEvent.status == EventStatus.PUBLISHED.value),
            func.count().filter(CalendarEvent.status.in_(_LIVE_STATUSES)),
        )
        .where(CalendarEvent.post_id.in_(list(post_ids)))
        .group_by(CalendarEvent.post_id)
    ).all()
    return {post_id: (int(published), int(live) > 0) for post_id, published, live in rows}


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
            history = _history(session, [draft.id for draft in drafts])
            return {
                draft.id: self._summarize(session, tenant_id, draft, history.get(draft.id))
                for draft in drafts
            }

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
            history = _history(session, [draft.id for draft in drafts])
            return [
                self._summarize(session, tenant_id, draft, history.get(draft.id))
                for draft in drafts
            ]

    def list_for_brand(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        with tenant_session(tenant_id) as session:
            drafts = session.scalars(
                select(creative.ContentDraft)
                .where(creative.ContentDraft.brand_id == brand_id)
                .order_by(creative.ContentDraft.created_at.desc())
                .limit(_GALLERY_LIMIT)
            ).all()
            history = _history(session, [draft.id for draft in drafts])
            return [
                self._summarize(session, tenant_id, draft, history.get(draft.id))
                for draft in drafts
            ]

    def get_publishable(
        self, *, tenant_id: UUID, post_id: UUID, output_port: str | None = None
    ) -> PublishablePost | NotPublishable:
        with tenant_session(tenant_id) as session:
            draft = session.get(creative.ContentDraft, post_id)
            if draft is None:
                return NotPublishable(
                    post_id=post_id,
                    reason=UnpublishableReason.POST_NOT_FOUND,
                    output_port=output_port,
                )
            images = _images(session, draft.id)
            return evaluate(_candidate(session, tenant_id, draft, images, output_port))

    def _summarize(
        self,
        session: Session,
        tenant_id: UUID,
        draft: creative.ContentDraft,
        history: tuple[int, bool] | None = None,
    ) -> PostSummary:
        times_published, has_live_event = history or (0, False)
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
        thumbnail = thumbnail_source(
            preview_key=draft.preview_key, assets=images, now=self._clock()
        )

        outputs = _outputs(session, tenant_id, draft, images)
        if outputs:
            # MP-11: a POST with template outputs is published one output at a time, so
            # "publishable" means at least one output is; the whole-POST verdict would
            # refuse the package (`reel` + video + two images is no single shape).
            publishable = any(output.is_publishable for output in outputs)
            media_product_type = None
            reason = "" if publishable else outputs[0].unpublishable_reason
        else:
            verdict = evaluate(_candidate(session, tenant_id, draft, images))
            publishable = isinstance(verdict, PublishablePost)
            media_product_type = verdict.media_product_type if publishable else None
            reason = "" if publishable else REASON_TEXT[verdict.reason]
        first = min(images, key=lambda image: image.position) if images else None
        video_object_key = (
            first.object_key
            if first is not None
            and first.media_type == "video"
            and first.object_key
            and first.object_key.startswith(_OBJECT_STORE_PREFIX + f"{tenant_id}/")
            else None
        )
        title = (brief.topic if brief is not None else "") or _excerpt(_caption(variant))[:60]
        return PostSummary(
            post_id=draft.id,
            brand_id=draft.brand_id,
            title=title or "(sin tema)",
            approval=_APPROVAL_BY_DRAFT_STATUS.get(draft.status, ApprovalStatus.NOT_READY),
            approved_at=draft.approved_at.isoformat() if draft.approved_at else None,
            category=draft.category,
            media_product_type=media_product_type,
            content_type=brief.content_type if brief is not None else None,
            reuse_type=draft.reuse_type,  # `ReuseType` (0027, QUA-109); None until set
            lifecycle_status=draft.status,
            thumbnail_url=thumbnail,
            video_object_key=video_object_key,
            caption_excerpt=_excerpt(_caption(variant)),
            asset_count=len(images),
            asset_types=tuple("IMAGE" for _ in images),
            is_publishable=publishable,
            unpublishable_reason=reason,
            detail_href=f"/drafts/{draft.id}",
            outputs=outputs,
            times_published=times_published,
            has_live_event=has_live_event,
        )
