"""An approved, unpublished piece as a promotion source (m-24828982).

The read only proposes; `UnpublishedImageService` re-reads and validates everything
(version, account, sizes, durations) before any call to Meta.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.ads.unpublished import ImageAdForm
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from .ad_enhancements_provider import load_policy
from .ad_enhancements_vm import BrandEnhancementsVM
from .ad_health_provider import account_health_for, refresh_health
from .promotion_vm import (
    AdMediaVM,
    PromotionDraftVM,
    PromotionResultVM,
    PromotionReviewVM,
    PromotionSourceVM,
    cop_label,
    cop_minor,
    local_datetime,
    promotion_result,
)
from .r2_media import issue_view_path

logger = logging.getLogger(__name__)

ENHANCEMENTS_ON = (
    "Desactiva las mejoras automáticas de esta marca en Tu marca antes de anunciar esta pieza."
)
FEED, VERTICAL = (4, 5), (9, 16)

_PIECE = text("""SELECT d.brand_id,d.active_version_id,COALESCE(v.edited_copy,v.copy) AS ad_copy
FROM content_drafts d JOIN piece_versions pv ON pv.id=d.active_version_id
  AND pv.tenant_id=d.tenant_id AND pv.draft_id=d.id AND pv.status='active'
LEFT JOIN copy_variants v ON v.id=d.selected_variant_id AND v.tenant_id=d.tenant_id
  AND v.draft_id=d.id
WHERE d.id=:draft AND d.status='approved' AND d.approved_revision=d.revision
  AND d.published_media_id IS NULL AND d.parent_draft_id IS NULL
  AND d.media_purged_at IS NULL AND d.media_objects_pending_at IS NULL
  AND d.part_removed_at IS NULL""")
_ACCOUNTS = text("""SELECT a.id,COALESCE(a.name,'') AS name,COALESCE(a.currency,'') AS currency,
  COALESCE(a.timezone_name,'') AS timezone_name,
  COALESCE(c.external_username,c.external_account_id) AS account_label
FROM ad_accounts a JOIN social_connections c ON c.id=a.connection_id
  AND c.tenant_id=a.tenant_id AND c.brand_id=a.brand_id
WHERE a.brand_id=:brand AND a.selected AND a.available
  AND a.credential_version=c.current_credential_version AND c.status='active'
  AND c.purged_at IS NULL AND c.purge_started_at IS NULL
ORDER BY a.id""")
_ASSETS = text("""SELECT id,object_key,content_type,media_type,width,height
FROM image_assets WHERE draft_id=:draft AND version_id=:version AND object_key IS NOT NULL
ORDER BY position NULLS LAST,id""")


def _ratio(width: object, height: object, ratio: tuple[int, int]) -> bool:
    return (
        type(width) is int
        and type(height) is int
        and min(width, height) > 0
        and width * ratio[1] == height * ratio[0]
    )


def _media(tenant_id: UUID, row: dict, label: str) -> AdMediaVM:
    try:
        url = issue_view_path(tenant_id, row["object_key"], row["media_type"])
    except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth failing the step
        logger.warning("unpublished media token not issued: %s", type(exc).__name__)
        url = ""
    return AdMediaVM(id=str(row["id"]), url=url, media_type=row["media_type"], label=label)


def _pick(rows: list[dict], kind: str, ratio: tuple[int, int]) -> list[dict]:
    types = {"video/mp4"} if kind == "video" else {"image/jpeg", "image/png"}
    return [
        row
        for row in rows
        if row["media_type"] == kind
        and row["content_type"] in types
        and _ratio(row["width"], row["height"], ratio)
    ]


def unpublished_sources(
    tenant_id: UUID, draft_id: UUID, *, check_health: bool = False
) -> list[PromotionSourceVM]:
    """One source per selected ad account and kind (two images, or two videos with
    their covers) of the active approved version; [] when the piece does not qualify."""
    with tenant_session(tenant_id) as session:
        piece = session.execute(_PIECE, {"draft": draft_id}).mappings().first()
        if piece is None:
            return []
        accounts = [
            dict(row) for row in session.execute(_ACCOUNTS, {"brand": piece["brand_id"]}).mappings()
        ]
        assets = [
            dict(row)
            for row in session.execute(
                _ASSETS, {"draft": draft_id, "version": piece["active_version_id"]}
            ).mappings()
        ]
    feed_images, vertical_images = _pick(assets, "image", FEED), _pick(assets, "image", VERTICAL)
    feed_videos, vertical_videos = _pick(assets, "video", FEED), _pick(assets, "video", VERTICAL)
    kinds = []
    if feed_videos and vertical_videos and feed_images and vertical_images:
        kinds.append("videos")
    if feed_images and vertical_images:
        kinds.append("images")
    if not kinds or not accounts:
        return []
    copy = piece["ad_copy"] if isinstance(piece["ad_copy"], dict) else {}
    message = str(copy.get("ads_primary_text") or copy.get("caption") or "")
    headline = str(copy.get("ads_headline") or copy.get("hook") or "")[:100]
    link = str(copy.get("ads_destination_url") or "")
    brand = piece["brand_id"]
    try:
        policy = load_policy(tenant_id, brand)
    except Exception as exc:  # noqa: BLE001 — unknown permissions block, never assume off
        logger.warning("unpublished permissions read failed: %s", type(exc).__name__)
        policy = BrandEnhancementsVM()
    blocked = ENHANCEMENTS_ON if any(policy.values.values()) else ""

    def media(rows: list[dict], name: str) -> list[AdMediaVM]:
        return [_media(tenant_id, row, f"{name} {n}") for n, row in enumerate(rows, 1)]

    sources = []
    for account in accounts:
        health = (refresh_health if check_health else account_health_for)(
            tenant_id, account["id"], account["timezone_name"]
        )
        for kind in kinds:
            video = kind == "videos"
            sources.append(
                PromotionSourceVM(
                    # Stable and distinct per account and kind; never a publish attempt.
                    id=str(uuid.uuid5(account["id"], kind)),
                    account_label=account["account_label"],
                    caption=message,
                    account_name=account["name"],
                    currency=account["currency"],
                    default_link_url=link,
                    timezone_name=account["timezone_name"],
                    unavailable_reason=blocked,
                    health=health,
                    ad_account_id=str(account["id"]),
                    enhancements=policy,
                    brand_id=str(brand),
                    media_kind=kind,
                    feed_media=media(feed_videos if video else feed_images, "Opción"),
                    vertical_media=media(vertical_videos if video else vertical_images, "Opción"),
                    feed_covers=media(feed_images, "Portada") if video else [],
                    vertical_covers=media(vertical_images, "Portada") if video else [],
                    default_message=message[:2200],
                    default_headline=headline,
                )
            )
    return sources


def _service():  # noqa: ANN202 — production composition, built per call
    from qualify_api.ads.unpublished_service import UnpublishedImageService  # noqa: PLC0415
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return UnpublishedImageService(ObjectGate(R2ObjectStore(R2Settings.from_env())))


def _id(value: str) -> UUID | None:
    return UUID(value) if value else None


def prepare_unpublished(
    tenant_id: UUID,
    draft_id: UUID,
    actor: UUID,
    form: PromotionDraftVM,
    source: PromotionSourceVM,
    timezone_name: str,
    request_key: str,
) -> PromotionReviewVM:
    """Creates the ad paused and returns its two previews. While Meta processes a video
    this raises; the caller repeats it with the SAME `request_key` (never a re-upload)."""
    from .promotion_provider import safe_preview_url  # noqa: PLC0415

    video = form.media_kind == "videos"
    preview = asyncio.run(
        _service().prepare(
            tenant_id=tenant_id,
            draft_id=draft_id,
            ad_account_id=UUID(source.ad_account_id),
            feed_asset_id=UUID(form.feed_asset_id),
            vertical_asset_id=UUID(form.vertical_asset_id),
            feed_thumbnail_asset_id=_id(form.feed_cover_id) if video else None,
            vertical_thumbnail_asset_id=_id(form.vertical_cover_id) if video else None,
            form=ImageAdForm(
                message=form.message,
                headline=form.headline.strip(),
                link_url=form.link_url.strip(),
                budget_minor=cop_minor(form.budget),
                start_time=local_datetime(form.start_local, timezone_name),
                end_time=local_datetime(form.end_local, timezone_name),
                country=form.country,
            ),
            actor=actor,
            request_key=UUID(request_key),
            confirm_preparation=True,
        )
    )
    feed, vertical = safe_preview_url(preview.feed_html), safe_preview_url(preview.vertical_html)
    if not feed or not vertical:
        raise ValueError("unsafe or unavailable unpublished preview")
    expires: datetime = preview.expires_at
    return PromotionReviewVM(
        promotion_id=str(preview.promotion_id),
        review_id=str(preview.review_id),
        recipe_id=str(preview.recipe_id),
        preview_url=feed,
        vertical_preview_url=vertical,
        charge_notice=f"Si lo autorizas, Meta podrá cobrar hasta {cop_label(form.budget)} "
        "a tu método de pago.",
        expires_label=expires.astimezone(ZoneInfo(timezone_name)).strftime("%d/%m/%Y %H:%M"),
    )


def confirm_unpublished(
    tenant_id: UUID, actor: UUID, review: PromotionReviewVM
) -> PromotionResultVM:
    status = asyncio.run(
        _service().confirm(
            tenant_id=tenant_id,
            recipe_id=UUID(review.recipe_id),
            review_id=UUID(review.review_id),
            actor=actor,
            confirm_charge=True,
        )
    )
    return promotion_result(
        SimpleNamespace(status=status, promotion_id=review.promotion_id), review.promotion_id
    )
