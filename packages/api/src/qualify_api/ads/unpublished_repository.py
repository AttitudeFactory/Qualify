"""Tenant-bound source reads and independently committed write-ahead upload claims."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import require_tenant_object
from sqlalchemy import text

from qualify_api.ads.client import MarketingSettings
from qualify_api.ads.unpublished import (
    UPLOAD_UNCERTAIN,
    ImageAdForm,
    ImageSelection,
    ImageSource,
    UnpublishedUnavailable,
    VideoSelection,
    recipe_hash,
)
from qualify_api.connections.ad_accounts import _connection, _permission_reason
from qualify_api.tenancy.acting import require_acting_member

CHANGED = "La pieza o la cuenta cambió. Vuelve a preparar el anuncio."
# A send claim idle this long lost its process (crash between claim and settle): it becomes
# `unknown`, never re-sent. Must match the 0161 trigger.
STALE_CLAIM_MINUTES = 30


def load_image_source(
    tenant: UUID,
    draft: UUID,
    account: UUID,
    feed_asset: UUID | None,
    vertical_asset: UUID,
    thumbnails: tuple[UUID | None, UUID | None] = (None, None),
) -> ImageSource:
    """Two images, or two MP4 videos each with the explicit cover image the owner chose.
    `feed_asset=None` loads a story ad (m-25026350): only the 9:16 asset and its cover."""
    require_acting_member(tenant)
    with tenant_session(tenant, independent=True) as session:
        row = (
            session.execute(
                text("""SELECT d.id,d.brand_id,d.active_version_id,d.revision,
              a.connection_id,a.ad_account_id,a.currency,a.timezone_name,a.credential_version,
              c.external_account_id,c.linked_page_id
            FROM content_drafts d JOIN piece_versions v ON v.id=d.active_version_id
              AND v.tenant_id=d.tenant_id AND v.draft_id=d.id AND v.status='active'
            JOIN ad_accounts a ON a.brand_id=d.brand_id AND a.tenant_id=d.tenant_id
            JOIN social_connections c ON c.id=a.connection_id AND c.tenant_id=d.tenant_id
              AND c.brand_id=d.brand_id
            WHERE d.id=:draft AND a.id=:account AND a.selected AND a.available
              AND a.credential_version=c.current_credential_version AND c.status='active'
              AND c.purged_at IS NULL AND c.purge_started_at IS NULL
              AND d.status='approved' AND d.approved_revision=d.revision
              AND d.published_media_id IS NULL AND d.parent_draft_id IS NULL
              AND d.media_purged_at IS NULL AND d.media_objects_pending_at IS NULL
              AND d.part_removed_at IS NULL FOR SHARE OF d,v,a,c"""),
                {"draft": draft, "account": account},
            )
            .mappings()
            .first()
        )
        if row is None or _permission_reason(_connection(session, row["connection_id"])):
            raise UnpublishedUnavailable(CHANGED)

        def asset(asset_id: UUID, media_type: str) -> dict:
            found = (
                session.execute(
                    text("""SELECT id,object_key,content_type,width,height FROM image_assets
                  WHERE id=:id AND draft_id=:draft AND version_id=:version
                    AND media_type=:media AND object_key IS NOT NULL FOR SHARE"""),
                    {
                        "id": asset_id,
                        "draft": draft,
                        "version": row["active_version_id"],
                        "media": media_type,
                    },
                )
                .mappings()
                .first()
            )
            if found is None:
                raise UnpublishedUnavailable(
                    "Elige archivos finales de la versión actual de la pieza."
                )
            require_tenant_object(tenant, found["object_key"])
            return dict(found)

        def image(asset_id: UUID) -> ImageSelection:
            found = asset(asset_id, "image")
            return ImageSelection(
                asset_id,
                found["object_key"],
                found["content_type"],
                found["width"],
                found["height"],
            )

        selections: list[ImageSelection | VideoSelection | None] = []
        for asset_id, cover in zip((feed_asset, vertical_asset), thumbnails, strict=True):
            if asset_id is None:
                if cover is not None:
                    raise UnpublishedUnavailable(
                        "Esta historia lleva un solo archivo; quita la portada del formato que "
                        "no usas."
                    )
                selections.append(None)
                continue
            kind = session.scalar(
                text("SELECT media_type FROM image_assets WHERE id=:id AND draft_id=:draft"),
                {"id": asset_id, "draft": draft},
            )
            if kind == "video":
                found = asset(asset_id, "video")
                selections.append(
                    VideoSelection(
                        asset_id,
                        found["object_key"],
                        found["content_type"],
                        found["width"],
                        found["height"],
                        None if cover is None else image(cover),
                    )
                )
            elif cover is not None:
                raise UnpublishedUnavailable("Solo los videos llevan portada.")
            else:
                selections.append(image(asset_id))
        source = ImageSource(
            tenant,
            draft,
            row["brand_id"],
            row["active_version_id"],
            row["revision"],
            account,
            row["connection_id"],
            row["credential_version"],
            row["ad_account_id"],
            row["external_account_id"],
            row["linked_page_id"],
            row["currency"],
            row["timezone_name"],
            *selections,
        )
        source.snapshot()
        if source.currency != "COP" or any(
            not isinstance(value, str) or not value.isascii() or not value.isdigit()
            for value in (source.meta_account_id, source.instagram_id, source.page_id)
        ):
            raise UnpublishedUnavailable(
                "Revisa la cuenta y la página conectadas. "
                "Por ahora, estos anuncios solo admiten pesos colombianos."
            )
        return source


def thumbnails(source: ImageSource | dict) -> tuple[UUID | None, UUID | None]:
    """The explicit covers of a source or of its stored snapshot (None for images)."""
    if isinstance(source, ImageSource):
        feed, vertical = (
            item.thumbnail.asset_id if isinstance(item, VideoSelection) and item.thumbnail else None
            for item in (source.feed, source.vertical)
        )
        return feed, vertical
    feed, vertical = (
        UUID(source[key]["thumbnail"]["asset_id"]) if (source[key] or {}).get("thumbnail") else None
        for key in ("feed", "vertical")
    )
    return feed, vertical


def guard_source(source: ImageSource) -> None:
    current = load_image_source(
        source.tenant_id,
        source.draft_id,
        source.account_id,
        source.feed and source.feed.asset_id,
        source.vertical.asset_id,
        thumbnails(source),
    )
    if current != source:
        raise UnpublishedUnavailable(CHANGED)


class UnpublishedRepository:
    def approve(self, source: ImageSource, form: ImageAdForm, actor: UUID, key: UUID) -> dict:
        guard_source(source)
        digest = recipe_hash(source, form, actor)
        with tenant_session(source.tenant_id, independent=True) as session:
            session.execute(
                text("""INSERT INTO ad_unpublished_sources
              (tenant_id,brand_id,connection_id,ad_account_id,draft_id,request_key,request_hash,
               source,form,approved_by,pipeline_version) VALUES
              (:tenant,:brand,:connection,:account,:draft,:key,:hash,CAST(:source AS jsonb),
               CAST(:form AS jsonb),:actor,:pipeline)
              ON CONFLICT(tenant_id,request_key) DO NOTHING"""),
                {
                    "tenant": source.tenant_id,
                    "brand": source.brand_id,
                    "connection": source.connection_id,
                    "account": source.account_id,
                    "draft": source.draft_id,
                    "key": key,
                    "hash": digest,
                    "source": json.dumps(source.snapshot()),
                    "pipeline": source.snapshot()["pipeline"],
                    "form": json.dumps(form.snapshot()),
                    "actor": actor,
                },
            )
            saved = dict(
                session.execute(
                    text("SELECT * FROM ad_unpublished_sources WHERE request_key=:key"),
                    {"key": key},
                )
                .mappings()
                .one()
            )
            if saved["request_hash"] != digest:
                raise UnpublishedUnavailable("Esta solicitud ya corresponde a otra aprobación.")
            return saved

    def recipe(self, tenant: UUID, recipe_id: UUID) -> dict[str, Any]:
        require_acting_member(tenant)
        with tenant_session(tenant, independent=True) as session:
            row = (
                session.execute(
                    text("SELECT * FROM ad_unpublished_sources WHERE id=:id"), {"id": recipe_id}
                )
                .mappings()
                .first()
            )
            if row is None:
                raise UnpublishedUnavailable(CHANGED)
            return dict(row)

    def link(self, tenant: UUID, recipe_id: UUID, promotion_id: UUID) -> None:
        with tenant_session(tenant, independent=True) as session:
            result = session.execute(
                text("""UPDATE ad_unpublished_sources SET promotion_id=:promotion
              WHERE id=:id AND (promotion_id IS NULL OR promotion_id=:promotion)"""),
                {"promotion": promotion_id, "id": recipe_id},
            )
            if result.rowcount != 1:
                raise UnpublishedUnavailable(CHANGED)

    def claim_upload(
        self, source: ImageSource, asset: ImageSelection, digest: str
    ) -> tuple[dict, bool]:
        claim = uuid4()
        params = {
            "id": claim,
            "tenant": source.tenant_id,
            "account": source.account_id,
            "connection": source.connection_id,
            "version": source.credential_version,
            "asset": asset.asset_id,
            "digest": digest,
            "api": MarketingSettings.from_env().api_version,
        }
        with tenant_session(source.tenant_id, independent=True) as session:
            inserted = session.scalar(
                text("""INSERT INTO ad_unpublished_uploads
              (id,tenant_id,ad_account_id,connection_id,credential_version,asset_id,digest,api_version)
              VALUES(:id,:tenant,:account,:connection,:version,:asset,:digest,:api)
              ON CONFLICT DO NOTHING RETURNING id"""),
                params,
            )
            row = (
                session.execute(
                    text("""SELECT * FROM ad_unpublished_uploads
              WHERE ad_account_id=:account AND credential_version=:version
                AND asset_id=:asset AND digest=:digest"""),
                    params,
                )
                .mappings()
                .one()
            )
            return dict(row), inserted == claim

    def finish_upload(self, tenant: UUID, upload_id: UUID, image_hash: str | None) -> None:
        with tenant_session(tenant, independent=True) as session:
            changed = session.execute(
                text("""UPDATE ad_unpublished_uploads
              SET state=:state,image_hash=:hash WHERE id=:id AND state='creating'"""),
                {
                    "state": "created" if image_hash else "unknown",
                    "hash": image_hash,
                    "id": upload_id,
                },
            )
            if changed.rowcount != 1:
                raise UnpublishedUnavailable(
                    "No pudimos confirmar la carga en Meta. "
                    "Pide ayuda para revisarla antes de continuar.",
                    reason=UPLOAD_UNCERTAIN,
                )

    def claim_video(
        self, source: ImageSource, asset: VideoSelection, digest: str, size: int
    ) -> tuple[dict, UUID | None]:
        """Record the measured video, then take the single send claim (committed before any
        POST). Returns the row and the claim token, or None when this caller did not get it."""
        params = {
            "tenant": source.tenant_id,
            "account": source.account_id,
            "connection": source.connection_id,
            "version": source.credential_version,
            "asset": asset.asset_id,
            "digest": digest,
            "size": size,
            "api": MarketingSettings.from_env().api_version,
            "token": uuid4(),
        }
        identity = """ad_account_id=:account AND credential_version=:version
                AND asset_id=:asset AND digest=:digest"""
        with tenant_session(source.tenant_id, independent=True) as session:
            session.execute(
                text("""INSERT INTO ad_unpublished_videos
              (tenant_id,ad_account_id,connection_id,credential_version,asset_id,digest,
               size_bytes,api_version)
              VALUES(:tenant,:account,:connection,:version,:asset,:digest,:size,:api)
              ON CONFLICT DO NOTHING"""),
                params,
            )
            session.execute(
                text(f"""UPDATE ad_unpublished_videos
              SET state='unknown',claim_token=NULL,detail='stale claim',updated_at=now()
              WHERE {identity} AND state='submitting'
                AND updated_at < now() - make_interval(mins => :stale)"""),
                params | {"stale": STALE_CLAIM_MINUTES},
            )
            claimed = (
                session.execute(
                    text(f"""UPDATE ad_unpublished_videos
              SET state='submitting',claim_token=:token,updated_at=now()
              WHERE {identity} AND state='ready' RETURNING *"""),
                    params,
                )
                .mappings()
                .first()
            )
            if claimed is not None:
                return dict(claimed), params["token"]
            row = session.execute(
                text(f"SELECT * FROM ad_unpublished_videos WHERE {identity}"), params
            )
            return dict(row.mappings().one()), None

    def video_named(self, tenant: UUID, row_id: UUID, token: UUID, video_id: str) -> None:
        self._video(
            tenant,
            "video_id=:video",
            "state='submitting' AND claim_token=:token AND video_id IS NULL",
            {"id": row_id, "token": token, "video": video_id},
        )

    def finish_video(
        self, tenant: UUID, row_id: UUID, token: UUID, state: str, detail: str | None = None
    ) -> None:
        """Settle this caller's claim: processing, unknown, failed, or back to ready when
        the fence refused before anything was sent."""
        self._video(
            tenant,
            "state=:state,detail=:detail,claim_token=NULL",
            "state='submitting' AND claim_token=:token",
            {"id": row_id, "token": token, "state": state, "detail": detail},
        )

    def video_checked(self, tenant: UUID, row_id: UUID, state: str) -> None:
        """Record one status read of a processing video (processing/ready_remote/failed)."""
        self._video(
            tenant,
            "state=:state,checked_at=now()",
            "state='processing'",
            {"id": row_id, "state": state},
        )

    def _video(self, tenant: UUID, assign: str, where: str, params: dict) -> None:
        with tenant_session(tenant, independent=True) as session:
            changed = session.execute(
                text(
                    f"UPDATE ad_unpublished_videos SET {assign},updated_at=now() "
                    f"WHERE id=:id AND {where}"
                ),
                params,
            )
            if changed.rowcount != 1:
                raise UnpublishedUnavailable(
                    "No pudimos confirmar la carga del video en Meta. "
                    "Pide ayuda para revisarla antes de continuar.",
                    reason=UPLOAD_UNCERTAIN,
                )
