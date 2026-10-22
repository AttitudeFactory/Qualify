"""The files of the pieces a brand already made — what a carousel's «de una pieza
existente» slide picks from (§ request 2026-10-09), and the check that a key a brief
names IS one of them.

`owned_by` (media.py) only proves a key sits under the caller's TENANT prefix; a tenant
holds several brands, and a key from the browser must never pull another brand's piece
into this brand's carousel. So the producer asks this reader — through the tenant door,
so RLS scopes it too — whether the key is a file of one of THIS brand's drafts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.models import ContentBrief, ContentDraft, CopyVariant, ImageAsset

#: How many files the picker offers — the most recent first.
DEFAULT_PIECE_LIMIT = 60


@dataclass(frozen=True)
class PieceFile:
    """One stored file of one of the brand's drafts."""

    draft_id: UUID
    object_key: str
    media_type: str  # "image" | "video"
    content_type: str | None
    width: int | None
    height: int | None
    position: int
    #: A video's thumbnail (`params.thumbnail_key`), when it has one.
    poster_key: str | None
    #: What the piece is about (the brief's topic).
    topic: str
    created_at: datetime | None = None
    #: The piece's title — its chosen copy's hook (§ request 2026-10-14: a picker shows
    #: a piece by its title, not by the prompt it was made from); "" when it has none.
    title: str = ""


class PieceFiles(Protocol):
    def file(self, *, tenant_id: UUID, brand_id: UUID, object_key: str) -> PieceFile | None: ...

    def files(
        self, *, tenant_id: UUID, brand_id: UUID, limit: int = DEFAULT_PIECE_LIMIT
    ) -> list[PieceFile]: ...


def _piece(asset: ImageAsset, draft: ContentDraft, topic: str | None) -> PieceFile:
    params = asset.params or {}
    poster = params.get("thumbnail_key")
    return PieceFile(
        draft_id=draft.id,
        object_key=str(asset.object_key),
        media_type=asset.media_type,
        content_type=asset.content_type,
        width=asset.width,
        height=asset.height,
        position=asset.position,
        poster_key=str(poster) if poster else None,
        topic=topic or "",
        created_at=asset.created_at,
    )


class DbPieceFiles:
    def file(self, *, tenant_id: UUID, brand_id: UUID, object_key: str) -> PieceFile | None:
        """The brand's file stored under `object_key`, or None — not this brand's, or
        not a piece's file at all."""
        if not object_key:
            return None
        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(ImageAsset, ContentDraft, ContentBrief.topic)
                .join(ContentDraft, ContentDraft.id == ImageAsset.draft_id)
                .join(ContentBrief, ContentBrief.id == ContentDraft.brief_id)
                .where(
                    ContentDraft.brand_id == brand_id,
                    ImageAsset.object_key == object_key,
                    # m-24828907: a purged piece's files are gone from R2
                    ContentDraft.media_purged_at.is_(None),
                )
                .limit(1)
            ).first()
            return _piece(*row) if row is not None else None

    def files(
        self, *, tenant_id: UUID, brand_id: UUID, limit: int = DEFAULT_PIECE_LIMIT
    ) -> list[PieceFile]:
        """The brand's stored images and videos, the most recent piece first and each
        piece's files in their order."""
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(ImageAsset, ContentDraft, ContentBrief.topic)
                .join(ContentDraft, ContentDraft.id == ImageAsset.draft_id)
                .join(ContentBrief, ContentBrief.id == ContentDraft.brief_id)
                .where(
                    ContentDraft.brand_id == brand_id,
                    ImageAsset.object_key.is_not(None),
                    ImageAsset.media_type.in_(("image", "video")),
                    ContentDraft.media_purged_at.is_(None),  # m-24828907
                )
                .order_by(ContentDraft.created_at.desc(), ImageAsset.position)
                .limit(limit)
            ).all()
            titles = _titles(session, {draft.id: draft.selected_variant_id for _, draft, _ in rows})
            return [replace(_piece(*row), title=titles.get(row[1].id, "")) for row in rows]


def _titles(session: Any, drafts: dict[UUID, UUID | None]) -> dict[UUID, str]:
    """Each draft's title: the hook of its chosen copy variant, else of its first."""
    if not drafts:
        return {}
    variants = session.execute(
        select(CopyVariant.draft_id, CopyVariant.id, CopyVariant.copy, CopyVariant.edited_copy)
        .where(CopyVariant.draft_id.in_(list(drafts)))
        .order_by(CopyVariant.draft_id, CopyVariant.ordinal)
    ).all()
    titles: dict[UUID, str] = {}
    for draft_id, variant_id, copy, edited in variants:
        chosen = drafts.get(draft_id)
        if draft_id in titles and variant_id != chosen:
            continue
        hook = str(((edited or copy) or {}).get("hook") or "").strip()
        if hook and (draft_id not in titles or variant_id == chosen):
            titles[draft_id] = " ".join(hook.split())
    return titles
