"""Why a piece cannot become a story ad yet (HIS-2, m-25130282).

The story-only ad (`/drafts/<id>/promote?formato=historia`) used to fall into one empty
state whatever the cause. `story_block` names the first cause the owner can act on, in
the order they would fix it: the piece, its files, its button, the brand's permissions,
then the ad account. It only reads; `UnpublishedImageService.prepare` still re-checks
everything (sizes, durations, Meta) before any call. The screen maps each cause to its
Spanish text (`Qualify/promotion_vm.py`, `STORY_BLOCKS`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.enhancements_service import read_policy
from qualify_api.ads.wizard import _saved_ad_destination
from qualify_api.connections.ad_accounts import (
    AdAccountUnavailable,
    _connection,
    _permission_reason,
)


class StoryBlock(StrEnum):
    MISSING = "missing"  # no such top-level piece for this business, or no active version
    NOT_APPROVED = "not_approved"
    EDITED = "edited"  # changed after its approval
    # The wizard's rule today (`content_drafts.published_media_id`); HIS-3 (m-25130283)
    # may move «published» elsewhere — keep both reads in step.
    PUBLISHED = "published"
    FILES_DELETED = "files_deleted"  # retention purge (ADR 39), its objects deleted or pending
    NO_VERTICAL = "no_vertical"  # no 9:16 JPG/PNG image nor 9:16 MP4 video
    VIDEO_WITHOUT_COVER = "video_without_cover"  # a 9:16 video with no 9:16 image as cover
    BUTTON = "button"  # the saved button is a chat/call one, or the saved link is invalid
    ENHANCEMENTS = "enhancements"  # the brand lets Meta change its ads
    NO_AD_ACCOUNT = "no_ad_account"  # no ad account selected for the brand
    RECONNECT = "reconnect"  # the selected account or its connection is no longer usable
    AD_PERMISSION = "ad_permission"  # ads_management missing or expired
    CURRENCY = "currency"  # only non-COP accounts (the unpublished flow is COP-only)


VERTICAL = (9, 16)
_IMAGE_TYPES, _VIDEO_TYPES = {"image/jpeg", "image/png"}, {"video/mp4"}

_PIECE = text("""SELECT d.brand_id,d.status,d.revision,d.approved_revision,d.media_purged_at,
  d.published_media_id,pv.id AS version_id,COALESCE(v.edited_copy,v.copy) AS ad_copy
FROM content_drafts d LEFT JOIN piece_versions pv ON pv.id=d.active_version_id
  AND pv.tenant_id=d.tenant_id AND pv.draft_id=d.id AND pv.status='active'
LEFT JOIN copy_variants v ON v.id=d.selected_variant_id AND v.tenant_id=d.tenant_id
  AND v.draft_id=d.id
WHERE d.id=:draft AND d.parent_draft_id IS NULL AND d.part_removed_at IS NULL""")
_ASSETS = text("""SELECT content_type,media_type,width,height FROM image_assets
WHERE draft_id=:draft AND version_id=:version AND object_key IS NOT NULL""")
_ACCOUNTS = text("""SELECT a.connection_id,a.available,COALESCE(a.currency,'') AS currency,
  (a.credential_version=c.current_credential_version AND c.status='active'
   AND c.purged_at IS NULL AND c.purge_started_at IS NULL) AS connected
FROM ad_accounts a JOIN social_connections c ON c.id=a.connection_id
  AND c.tenant_id=a.tenant_id AND c.brand_id=a.brand_id
WHERE a.brand_id=:brand AND a.selected""")


def _vertical(row: Mapping[str, Any], kind: str, types: set[str]) -> bool:
    width, height = row["width"], row["height"]
    return (
        row["media_type"] == kind
        and row["content_type"] in types
        and type(width) is int
        and type(height) is int
        and min(width, height) > 0
        and width * VERTICAL[1] == height * VERTICAL[0]
    )


def files_block(assets: Iterable[Mapping[str, Any]]) -> StoryBlock | None:
    """The same rule as the wizard's `story_kinds`: a 9:16 image is required, as the ad
    itself or as the cover of a 9:16 video."""
    rows = list(assets)
    if any(_vertical(row, "image", _IMAGE_TYPES) for row in rows):
        return None
    if any(_vertical(row, "video", _VIDEO_TYPES) for row in rows):
        return StoryBlock.VIDEO_WITHOUT_COVER
    return StoryBlock.NO_VERTICAL


def piece_block(piece: Mapping[str, Any] | None) -> StoryBlock | None:
    if piece is None or piece["version_id"] is None:
        return StoryBlock.MISSING
    if piece["status"] != "approved":
        return StoryBlock.NOT_APPROVED
    if piece["approved_revision"] != piece["revision"]:
        return StoryBlock.EDITED
    if piece.get("published_media_id") is not None:
        return StoryBlock.PUBLISHED
    # `media_objects_pending_at` never exists without `media_purged_at` (0139's check).
    if piece["media_purged_at"] is not None:
        return StoryBlock.FILES_DELETED
    return None


def _permitted(session: Any, connection_id: UUID) -> bool:
    try:
        return not _permission_reason(_connection(session, connection_id))
    except AdAccountUnavailable:
        return False


def story_block(tenant_id: UUID, draft_id: UUID) -> StoryBlock | None:
    """The first reason this business's piece cannot be a story ad, or None. Read under
    the tenant's RLS: another business's piece is MISSING, never described."""
    with tenant_session(tenant_id) as session:
        piece = session.execute(_PIECE, {"draft": draft_id}).mappings().first()
        if block := piece_block(piece):
            return block
        assets = session.execute(
            _ASSETS, {"draft": draft_id, "version": piece["version_id"]}
        ).mappings()
        if block := files_block(assets):
            return block
        if _saved_ad_destination(piece["ad_copy"])[2]:
            return StoryBlock.BUTTON
        if read_policy(session, tenant_id, piece["brand_id"]).enabled:
            return StoryBlock.ENHANCEMENTS
        accounts = list(session.execute(_ACCOUNTS, {"brand": piece["brand_id"]}).mappings())
        if not accounts:
            return StoryBlock.NO_AD_ACCOUNT
        usable = [row for row in accounts if row["available"] and row["connected"]]
        if not usable:
            return StoryBlock.RECONNECT
        permitted = [row for row in usable if _permitted(session, row["connection_id"])]
        if not permitted:
            return StoryBlock.AD_PERMISSION
        if all(row["currency"] != "COP" for row in permitted):
            return StoryBlock.CURRENCY
    return None
