"""The owner's own media as a piece (`ContentKind.OWN_MEDIA`, m-25019217; founder
2026-11-13): what «Publicar» sent to Instagram becomes a reusable piece of the owner,
shown under «Aprobados» and plannable again from the calendar.

`create_own_media_piece(session, ...)` writes, in the CALLER's `tenant_session`
transaction (so the planner can create the piece and its calendar event atomically):

- a `content_briefs` row of kind `own_media` (route `from_upload`: the owner's file, used
  as it is; nothing generated, nothing priced);
- a `content_drafts` row born APPROVED (`approved_revision == revision == 1`), approved by
  the acting user at the time Instagram accepted the publication, `reuse_type`
  `recurrente` (a one-shot piece would read USED in the gallery and never be offered
  again, `planner.gallery`), `pipeline_version` `publish-now-v1`;
- one active `piece_versions` row (revision 1) the copy and the media belong to;
- one selected `copy_variants` row whose payload reproduces the published caption
  exactly through `CopyPayload.rendered_caption()` (an empty hook, CTA and hashtags; the
  whole caption — hashtags included, as the owner typed it — in `caption`);
- one `image_assets` row per item, in order, pointing at the object «Publicar» already
  staged (`t/{tenant}/media/{connection}/{uuid}`): no copy, no Galería row.

**Provenance.** An owner upload is manual input (exception of 2026-11-04,
`docs/arquitectura.md` §1.6): no model wrote anything, so `model_id` is `OWNER_MODEL_ID`.
The source publication stays traceable through `content_drafts.request_key` (a UUIDv5 of
the source id, `request_key_for`) and the calendar event's `publish_attempt_id`.

**Idempotency.** `request_key` is unique per tenant (`uq_content_drafts_request_key`,
0070): a second call with the same source returns the existing piece. Callers that may
race take a transaction-scoped advisory lock on the source first
(`planner.immediate.record_publication`); the unique index is the last word.

**Retention.** These files live outside `generated/` and the piece is exempt from ADR
39's 90 days (`creative.retention`, ADR 39 amendment of 2026-11-13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4, uuid5

from qualify_creative.enums import (
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentKind,
    ContentType,
    ImageRoute,
    Platform,
    PostCategory,
    ReuseType,
)
from qualify_creative.schemas import CopyPayload
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative import fsm as draft_fsm
from qualify_api.creative import models as orm

#: `content_drafts.pipeline_version` / `piece_versions.pipeline_version` of these pieces.
PIPELINE_VERSION = "publish-now-v1"
#: `model_id` of an owner's input: no model made it (manual-input exception, 2026-11-04).
OWNER_MODEL_ID = "owner"
#: The namespace of `request_key_for` — fixed forever: changing it would let a source
#: that already has a piece get a second one.
REQUEST_KEY_NAMESPACE = UUID("6f3a2c1e-8b4d-5e7f-9a10-2b3c4d5e6f70")

#: `content_drafts.title` is short (the gallery card); the caption's first line, cut.
TITLE_MAX = 80
#: The title when the publication had no caption.
UNTITLED = "Publicación desde Publicar"

_MEDIA_TYPES = frozenset({"image", "video"})


@dataclass(frozen=True)
class OwnMediaItem:
    """One file of the piece, as the owner published it."""

    object_key: str
    content_type: str
    media_type: str  # "image" / "video" — `image_assets.media_type`
    position: int


@dataclass(frozen=True)
class OwnMediaPiece:
    """Everything the piece is made of. `request_key` names its source (`request_key_for`)."""

    brand_id: UUID
    user_id: UUID
    caption: str
    category: PostCategory
    format: ContentFormat
    approved_at: datetime
    items: tuple[OwnMediaItem, ...]
    request_key: UUID

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("an own-media piece has at least one file")
        positions = [item.position for item in self.items]
        if len(set(positions)) != len(positions):
            raise ValueError("an own-media piece's files have distinct positions")
        if any(item.media_type not in _MEDIA_TYPES for item in self.items):
            raise ValueError("an own-media file is an image or a video")
        if self.format not in ContentKind.OWN_MEDIA.formats:
            raise ValueError(f"format {self.format} is not offered for own media")


def request_key_for(source_id: UUID) -> UUID:
    """The piece's idempotency key for one source (a publish attempt's id): the same
    source always maps to the same key, so it never gets a second piece."""
    return uuid5(REQUEST_KEY_NAMESPACE, str(source_id))


def own_copy(caption: str) -> CopyPayload:
    """The variant that reproduces `caption` exactly: `rendered_caption()` joins the
    non-empty blocks of hook, caption, CTA and hashtags, and only `caption` is set."""
    return CopyPayload(hook="", caption=caption)


def title_of(caption: str) -> str:
    """The card's title: the caption's first non-empty line, cut to `TITLE_MAX`."""
    first = next((line.strip() for line in caption.splitlines() if line.strip()), "")
    if not first:
        return UNTITLED
    return first if len(first) <= TITLE_MAX else first[: TITLE_MAX - 1].rstrip() + "…"


def find_own_media_piece(session: Session, request_key: UUID) -> UUID | None:
    """The piece already recorded for this key, under the caller's RLS session."""
    return session.scalar(
        select(orm.ContentDraft.id).where(orm.ContentDraft.request_key == request_key)
    )


def create_own_media_piece(
    session: Session, *, tenant_id: UUID, piece: OwnMediaPiece
) -> tuple[UUID, bool]:
    """`(draft_id, created)`: the piece for `piece.request_key`, created now or found.

    Runs inside the caller's `tenant_session` and never commits: the caller's
    transaction decides. See the module docstring for what is written."""
    existing = find_own_media_piece(session, piece.request_key)
    if existing is not None:
        return existing, False

    ordered = sorted(piece.items, key=lambda item: item.position)
    brief = orm.ContentBrief(
        tenant_id=tenant_id,
        brand_id=piece.brand_id,
        objective=BriefObjective.AWARENESS.value,
        topic=title_of(piece.caption),
        product_ref=None,
        platform=Platform.INSTAGRAM.value,
        format=piece.format.value,
        intent=BriefIntent.ORGANIC.value,
        content_type=ContentType.PRODUCT.value,
        image_route=ImageRoute.FROM_UPLOAD.value,
        source_media_key=ordered[0].object_key,
        video_plan=None,
        variants_requested=1,
        constraints={},
        kind=ContentKind.OWN_MEDIA.value,
        media={},
        created_by=piece.user_id,
    )
    session.add(brief)
    session.flush()

    first_image = next((item for item in ordered if item.media_type == "image"), None)
    draft = orm.ContentDraft(
        tenant_id=tenant_id,
        brand_id=piece.brand_id,
        brief_id=brief.id,
        status=draft_fsm.APPROVED,
        voice_profile_version=None,
        pipeline_version=PIPELINE_VERSION,
        requires_ai_disclosure=False,
        approved_by=piece.user_id,
        approved_at=piece.approved_at,
        request_key=piece.request_key,
        title=title_of(piece.caption),
        category=piece.category.value,
        reuse_type=ReuseType.RECURRENTE.value,
        # a still the calendar card can show; a video's card keeps its placeholder
        preview_key=first_image.object_key if first_image is not None else None,
        revision=1,
        approved_revision=1,
    )
    session.add(draft)
    session.flush()

    version = orm.PieceVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        brand_id=piece.brand_id,
        draft_id=draft.id,
        revision=1,
        status="active",
        model_id=OWNER_MODEL_ID,
        pipeline_version=PIPELINE_VERSION,
        requires_ai_disclosure=False,
        brief_id=brief.id,
        created_at=piece.approved_at,
    )
    session.add(version)
    session.flush()

    variant = orm.CopyVariant(
        tenant_id=tenant_id,
        draft_id=draft.id,
        version_id=version.id,
        ordinal=0,
        copy=own_copy(piece.caption).model_dump(mode="json"),
        model_id=OWNER_MODEL_ID,
    )
    session.add(variant)
    session.add_all(
        orm.ImageAsset(
            tenant_id=tenant_id,
            draft_id=draft.id,
            version_id=version.id,
            media_url=item.object_key,
            object_key=item.object_key,
            content_type=item.content_type,
            media_type=item.media_type,
            position=item.position,
            model_id=OWNER_MODEL_ID,
            provider=OWNER_MODEL_ID,
            params={"source": "publish_now", "pipeline_version": PIPELINE_VERSION},
        )
        for item in ordered
    )
    session.flush()
    draft.selected_variant_id = variant.id
    draft.active_version_id = version.id
    session.flush()
    return draft.id, True


__all__ = [
    "OWNER_MODEL_ID",
    "PIPELINE_VERSION",
    "REQUEST_KEY_NAMESPACE",
    "OwnMediaItem",
    "OwnMediaPiece",
    "create_own_media_piece",
    "find_own_media_piece",
    "own_copy",
    "request_key_for",
    "title_of",
]
