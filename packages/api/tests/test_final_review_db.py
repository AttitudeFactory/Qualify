"""Real RLS, identity fencing and idempotence for the second human approval."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import models as orm
from qualify_api.creative.final_review import (
    FinalIdentity,
    FinalReviewUnavailable,
    confirm_final,
    final_confirmed,
    review_manifest,
)
from qualify_api.creative.service import PostgresContentRepository
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.post_reader import NotPublishable, PublishablePost, UnpublishableReason
from qualify_api.tenancy.models import TenantMember, User

from .test_creative_final_db import _video
from .test_creative_regenerate_db import _brand, _drafting_draft, _variant

pytestmark = pytest.mark.db


def _fixture(*, status: str = "final_ready", role: str = "owner") -> tuple[UUID, UUID, UUID]:
    tenant_id, user_id = uuid4(), uuid4()
    brand_id = _brand(tenant_id)
    with admin_session() as session:
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"{user_id}@example.invalid",
                display_name="Test",
            )
        )
        session.flush()
        session.add(TenantMember(tenant_id=tenant_id, user_id=user_id, role=role))
    draft_id = _drafting_draft(tenant_id, brand_id)
    repo = PostgresContentRepository()
    repo.finish_generation(
        tenant_id=tenant_id,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status="generated",
        failure_reason=None,
        variants=(_variant("hola"),),
        usage=(),
        spent_usd=Decimal(0),
        media=(_video(tenant_id, draft_id, "final.mp4", status),),
    )
    with tenant_session(tenant_id) as session:
        draft = session.get(orm.ContentDraft, draft_id)
        variant = session.scalar(
            select(orm.CopyVariant).where(orm.CopyVariant.draft_id == draft_id)
        )
        draft.status = "approved"
        draft.category = "reel"
        draft.selected_variant_id = variant.id
        draft.approved_revision = draft.revision
    return tenant_id, draft_id, user_id


def _manifest(tenant_id: UUID, draft_id: UUID, user_id: UUID) -> tuple[FinalIdentity, ...]:
    return review_manifest(
        tenant_id=tenant_id,
        draft_id=draft_id,
        user_id=user_id,
        read_object=lambda key: b"the exact final",
    )


def test_legacy_panel_backfill_does_not_confirm_and_confirmation_is_idempotent() -> None:
    tenant, draft, owner = _fixture(status="final")
    seen = _manifest(tenant, draft, owner)
    reader = DraftPostReader(verify_digest=lambda tid, key: seen[0].sha256)
    verdict = reader.get_publishable(tenant_id=tenant, post_id=draft)
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.MEDIA_FINAL_UNCONFIRMED
    first = datetime(2026, 10, 26, 15, tzinfo=UTC)
    confirm_final(tenant_id=tenant, draft_id=draft, user_id=owner, expected=seen, now=first)
    confirm_final(tenant_id=tenant, draft_id=draft, user_id=owner, expected=seen)
    with tenant_session(tenant) as session:
        asset = session.get(orm.ImageAsset, seen[0].asset_id)
        assert asset.params["draft"]["confirmed_at"] == first.isoformat()
        assert final_confirmed(asset.params, object_key=asset.object_key, revision=1)
    assert isinstance(reader.get_publishable(tenant_id=tenant, post_id=draft), PublishablePost)


def test_stale_panel_cannot_confirm_replaced_object_or_new_revision() -> None:
    tenant, draft, owner = _fixture()
    seen = _manifest(tenant, draft, owner)
    with tenant_session(tenant) as session:
        asset = session.get(orm.ImageAsset, seen[0].asset_id)
        asset.object_key += "-new"
    with pytest.raises(FinalReviewUnavailable):
        confirm_final(tenant_id=tenant, draft_id=draft, user_id=owner, expected=seen)
    with tenant_session(tenant) as session:
        asset = session.get(orm.ImageAsset, seen[0].asset_id)
        asset.object_key = seen[0].object_key
        row = session.get(orm.ContentDraft, draft)
        row.revision += 1
    with pytest.raises(FinalReviewUnavailable):
        confirm_final(tenant_id=tenant, draft_id=draft, user_id=owner, expected=seen)


def test_viewer_and_other_tenant_cannot_confirm() -> None:
    tenant, draft, viewer = _fixture(role="viewer")
    with pytest.raises(PermissionError):
        _manifest(tenant, draft, viewer)
    other, _, owner = _fixture()
    with pytest.raises(FinalReviewUnavailable):
        _manifest(other, draft, owner)
    with pytest.raises(PermissionError):
        _manifest(other, draft, viewer)


def test_actual_storage_bytes_changed_after_confirm_never_publish() -> None:
    tenant, draft, owner = _fixture()
    seen = _manifest(tenant, draft, owner)
    confirm_final(tenant_id=tenant, draft_id=draft, user_id=owner, expected=seen)
    reader = DraftPostReader(verify_digest=lambda tid, key: "different current binary")
    verdict = reader.get_publishable(tenant_id=tenant, post_id=draft)
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.MEDIA_FINAL_UNCONFIRMED


def test_cannot_confirm_only_one_scene_of_a_carousel() -> None:
    tenant, draft, owner = _fixture()
    seen = _manifest(tenant, draft, owner)
    with tenant_session(tenant) as session:
        original = session.get(orm.ImageAsset, seen[0].asset_id)
        session.add(
            orm.ImageAsset(
                tenant_id=tenant,
                draft_id=draft,
                media_url=original.media_url,
                object_key=original.object_key,
                media_type="video",
                position=1,
                params=dict(original.params),
            )
        )
    with pytest.raises(FinalReviewUnavailable):
        confirm_final(tenant_id=tenant, draft_id=draft, user_id=owner, expected=seen)
    with tenant_session(tenant) as session:
        assert (
            session.get(orm.ImageAsset, seen[0].asset_id).params["draft"]["status"] == "final_ready"
        )


def test_home_counts_follow_confirmation_and_stale_revision_under_rls() -> None:
    from qualify_api.home import read_home_counts

    tenant, draft, owner = _fixture()
    other, _, _ = _fixture(status="failed")
    seen = _manifest(tenant, draft, owner)
    assert read_home_counts(tenant).videos_to_confirm == 1
    assert read_home_counts(tenant).finals_failed == 0
    assert read_home_counts(other).finals_failed == 1
    assert read_home_counts(other).videos_to_confirm == 0
    confirm_final(tenant_id=tenant, draft_id=draft, user_id=owner, expected=seen)
    assert read_home_counts(tenant).videos_to_confirm == 0
    with tenant_session(tenant) as session:
        session.get(orm.ContentDraft, draft).revision += 1
    assert read_home_counts(tenant).videos_to_confirm == 1


def test_home_late_confirmation_excludes_failed_and_unprepared_finals() -> None:
    """The owner is asked to confirm only a complete, reviewable final."""
    from datetime import timedelta

    from qualify_api.connections.models import PlatformApp, SocialConnection
    from qualify_api.home import read_home_counts
    from qualify_api.planner.models import CalendarEvent

    tenant, draft, owner = _fixture(status="failed")
    now = datetime.now(UTC)
    with admin_session() as session:
        app = PlatformApp(app_id=f"home-night-{uuid4()}", secret_ref="test", api_version="v21.0")
        session.add(app)
        session.flush()
        app_id = app.id
    with tenant_session(tenant) as session:
        piece = session.get(orm.ContentDraft, draft)
        connection = SocialConnection(
            tenant_id=tenant,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=str(uuid4()),
            linked_page_id="test",
            granted_scopes=[],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=owner,
        )
        session.add(connection)
        session.flush()
        session.add(
            CalendarEvent(
                tenant_id=tenant,
                brand_id=piece.brand_id,
                post_id=draft,
                connection_id=connection.id,
                scheduled_at=now - timedelta(hours=1),
                scheduled_tz="UTC",
                status="scheduled",
            )
        )
    counts = read_home_counts(tenant, now=now)
    assert counts.finals_failed == 1
    assert counts.videos_to_confirm == counts.videos_late == counts.videos_ready_late == 0
    for status in ("rendering", "final_scheduled", "final_ready"):
        with tenant_session(tenant) as session:
            asset = session.scalar(select(orm.ImageAsset).where(orm.ImageAsset.draft_id == draft))
            asset.params = {**asset.params, "draft": {**asset.params["draft"], "status": status}}
        counts = read_home_counts(tenant, now=now)
        expected = int(status == "final_ready")
        assert counts.videos_to_confirm == counts.videos_late == expected
        assert counts.videos_ready_late == expected
