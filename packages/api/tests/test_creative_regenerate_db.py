"""PostgreSQL regressions for saved publication versions (m-24828906).

Regeneration preserves copy and media, activation selects the approved artifact, and
failed/pending/stale attempts cannot replace the last completed version.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative import models as creative
from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.media import MediaWrite
from qualify_api.creative.service import ContentService, PostgresContentRepository, VariantWrite
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_R = UUID("c0000000-0000-4000-8000-000000001010")


def _brand(tenant_id: UUID) -> UUID:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"regen-{tenant_id}",
                    country="VE",
                    timezone="America/Caracas",
                    currency="USD",
                )
            )
            session.flush()
        brand = session.scalars(select(Brand).where(Brand.tenant_id == tenant_id)).first()
        if brand is None:
            brand = Brand(tenant_id=tenant_id, name="brand-regen")
            session.add(brand)
            session.flush()
        return brand.id


def _drafting_draft(tenant_id: UUID, brand_id: UUID) -> UUID:
    with tenant_session(tenant_id) as session:
        brief = creative.ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic="Promo flash",
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="promotion",
            image_route="template_only",
        )
        session.add(brief)
        session.flush()
        draft = creative.ContentDraft(
            tenant_id=tenant_id,
            brief_id=brief.id,
            brand_id=brand_id,
            status=DRAFTING,
            category="galeria",
            pipeline_version="test",
        )
        session.add(draft)
        session.flush()
        return draft.id


def _variant(text: str) -> VariantWrite:
    return VariantWrite(
        ordinal=0,
        copy={"hook": text, "caption": "c", "cta": "Pide ya"},
        fidelity={"passed": True, "hard_failures": []},
        model_id="test",
        model_revision=None,
    )


def _image(tenant_id: UUID, draft_id: UUID, revision: int) -> MediaWrite:
    key = f"t/{tenant_id}/generated/{draft_id}/r{revision}/slide-1.jpg"
    return MediaWrite(
        position=0,
        media_type="image",
        media_url=key,
        object_key=key,
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="test",
        provider="test",
        content_type="image/jpeg",
    )


def _finish(tenant_id: UUID, draft_id: UUID, brand_id: UUID, text: str, revision: int) -> None:
    PostgresContentRepository().finish_generation(
        tenant_id=tenant_id,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status=GENERATED,
        failure_reason=None,
        variants=(_variant(text),),
        usage=(),
        spent_usd=Decimal("0"),
        media=(_image(tenant_id, draft_id, revision),),
    )


def test_a_regeneration_preserves_the_copy_variants_and_clears_the_selection() -> None:
    brand_id = _brand(TENANT_R)
    draft_id = _drafting_draft(TENANT_R, brand_id)
    _finish(TENANT_R, draft_id, brand_id, "primera", 1)
    with tenant_session(TENANT_R) as session:
        first = session.scalars(
            select(creative.CopyVariant).where(creative.CopyVariant.draft_id == draft_id)
        ).one()
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None and draft.status == GENERATED
        draft.selected_variant_id = first.id  # the operator picked it
        # «Regenerar»: back to drafting, a new revision (what `ContentService.reject` does)
        draft.status = DRAFTING
        draft.revision = 2

    _finish(TENANT_R, draft_id, brand_id, "segunda", 2)  # used to raise IntegrityError

    with tenant_session(TENANT_R) as session:
        variants = session.scalars(
            select(creative.CopyVariant).where(creative.CopyVariant.draft_id == draft_id)
        ).all()
        assert sorted((v.ordinal, v.copy["hook"]) for v in variants) == [
            (0, "primera"),
            (0, "segunda"),
        ]
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None
        assert draft.status == GENERATED and draft.selected_variant_id is None
        # Both generations remain stored; operational reads select only the active one.
        assets = session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == draft_id)
        ).all()
        assert sorted(a.object_key.rsplit("/", 2)[1] for a in assets) == ["r1", "r2"]
        current = PostgresContentRepository().media_for(tenant_id=TENANT_R, draft_id=draft_id)
        assert len(current) == 1 and "/r2/" in current[0].object_key
        assert draft.preview_key == current[0].object_key


def _assets(session: Session, draft_id: UUID) -> list[creative.ImageAsset]:
    return list(
        session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == draft_id)
        ).all()
    )


def test_a_failed_regeneration_preserves_previous_media_and_the_successful_label() -> None:
    """PR #100 review: (3) a regeneration whose copy came out but whose media failed used
    to leave the previous revision's images under the new text; (1) the AI-disclosure
    label is recomputed from the media each generation actually made."""
    brand_id = _brand(TENANT_R)
    draft_id = _drafting_draft(TENANT_R, brand_id)
    repo = PostgresContentRepository()
    _finish(TENANT_R, draft_id, brand_id, "primera", 1)
    with tenant_session(TENANT_R) as session:
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None and draft.requires_ai_disclosure is False
        draft.status, draft.revision = DRAFTING, 2  # «Regenerar»

    repo.finish_generation(
        tenant_id=TENANT_R,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status=FAILED,
        failure_reason="provider_error",
        variants=(_variant("segunda"),),
        usage=(),
        spent_usd=Decimal("0"),
        media=(),  # the vendor failed after the copy was written
        failure_detail="boom",
        requires_ai_disclosure=False,
    )
    with tenant_session(TENANT_R) as session:
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None
        assert draft.status == FAILED and "/r1/" in draft.preview_key
        assert len(_assets(session, draft_id)) == 1  # previous version survives
        hooks = [
            v.copy["hook"]
            for v in session.scalars(
                select(creative.CopyVariant).where(creative.CopyVariant.draft_id == draft_id)
            )
        ]
        assert sorted(hooks) == ["primera", "segunda"]
        draft.status, draft.revision = DRAFTING, 3

    seedream = replace(_image(TENANT_R, draft_id, 3), provider="seedream", ai_generated=True)
    repo.finish_generation(
        tenant_id=TENANT_R,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status=GENERATED,
        failure_reason=None,
        variants=(_variant("tercera"),),
        usage=(),
        spent_usd=Decimal("0"),
        media=(seedream,),
        requires_ai_disclosure=True,  # what the service derives from `seedream`
    )
    with tenant_session(TENANT_R) as session:
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None
        assert draft.status == GENERATED and draft.requires_ai_disclosure is True
        assert len(_assets(session, draft_id)) == 2
        assert [a.object_key for a in repo.media_for(tenant_id=TENANT_R, draft_id=draft_id)] == [
            seedream.object_key
        ]
        assert draft.preview_key == seedream.object_key


def _version_service() -> ContentService:
    service = object.__new__(ContentService)
    service._repo = PostgresContentRepository()
    service._vendor_tasks = None
    return service


def test_version_preview_is_read_only_and_restore_reuses_existing_content() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    _finish(TENANT_R, draft, brand, "first", 1)
    repo = PostgresContentRepository()
    first_id = repo.get_draft(tenant_id=TENANT_R, draft_id=draft).active_version_id
    repo.update_status(tenant_id=TENANT_R, draft_id=draft, new_status=DRAFTING, failure_reason=None)
    repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
    _finish(TENANT_R, draft, brand, "second", 2)
    service = _version_service()
    current = service.get_draft(tenant_id=TENANT_R, draft_id=draft)
    assert [version.revision for version in current.versions] == [1, 2]
    assert current.variants[0].copy["hook"] == "second"
    preview = service.preview_version(tenant_id=TENANT_R, draft_id=draft, version_id=first_id)
    assert preview.variants[0].copy["hook"] == "first"
    assert preview.viewed_version_id == first_id
    assert preview.active_version_id == current.active_version_id
    assert (
        service.get_draft(tenant_id=TENANT_R, draft_id=draft).variants[0].copy["hook"] == "second"
    )
    restored = service.restore_version(tenant_id=TENANT_R, draft_id=draft, version_id=first_id)
    assert restored.active_version_id == first_id
    assert restored.variants[0].copy["hook"] == "first"
    assert "/r1/" in restored.media[0].object_key
    assert restored.status == GENERATED and restored.approved_revision is None
    assert len(restored.versions) == 2
    from qualify_api.planner.draft_post_reader import _images

    with tenant_session(TENANT_R) as session:
        assert len(_images(session, draft)) == 1
        assert "/r1/" in _images(session, draft)[0].object_key
        assert (
            list(
                session.scalars(
                    select(creative.CreativeUsageEvent).where(
                        creative.CreativeUsageEvent.draft_id == draft
                    )
                )
            )
            == []
        )


def test_a_version_from_another_draft_cannot_be_previewed_or_restored() -> None:
    brand = _brand(TENANT_R)
    draft, other = _drafting_draft(TENANT_R, brand), _drafting_draft(TENANT_R, brand)
    _finish(TENANT_R, draft, brand, "one", 1)
    _finish(TENANT_R, other, brand, "two", 1)
    service = _version_service()
    other_id = service.get_draft(tenant_id=TENANT_R, draft_id=other).active_version_id
    with pytest.raises(ValueError):
        service.preview_version(tenant_id=TENANT_R, draft_id=draft, version_id=other_id)
    with pytest.raises(ValueError):
        service.restore_version(tenant_id=TENANT_R, draft_id=draft, version_id=other_id)
    with tenant_session(uuid4()) as session:
        from qualify_api.creative.versions import version_row

        with pytest.raises(ValueError):
            version_row(session, other, other_id)


def test_failed_version_does_not_replace_the_selected_successful_version() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    _finish(TENANT_R, draft, brand, "first", 1)
    repo = PostgresContentRepository()
    first = repo.get_draft(tenant_id=TENANT_R, draft_id=draft).active_version_id
    repo.update_status(tenant_id=TENANT_R, draft_id=draft, new_status=DRAFTING, failure_reason=None)
    repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
    repo.finish_generation(
        tenant_id=TENANT_R,
        draft_id=draft,
        brand_id=brand,
        new_status=FAILED,
        failure_reason="provider_error",
        variants=(),
        usage=(),
        spent_usd=Decimal(0),
    )
    assert repo.get_draft(tenant_id=TENANT_R, draft_id=draft).active_version_id == first
    versions = repo.versions_for(tenant_id=TENANT_R, draft_id=draft)
    assert [v.revision for v in versions] == [1, 2]
    assert [v.status for v in versions] == ["active", "failed"]
    assert repo.variants_for(tenant_id=TENANT_R, draft_id=draft)[0].copy["hook"] == "first"


def test_existing_content_gets_a_version_without_changing_the_publication() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    with tenant_session(TENANT_R) as session:
        row = session.get(creative.ContentDraft, draft)
        row.status, row.revision = FAILED, 2
        row.failure_reason = "timeout"
        session.add(
            creative.CopyVariant(
                tenant_id=TENANT_R,
                draft_id=draft,
                ordinal=0,
                copy={"hook": "legacy"},
                fidelity={"passed": True},
                model_id="test",
            )
        )
    repo = PostgresContentRepository()
    record = repo.get_draft(tenant_id=TENANT_R, draft_id=draft)
    assert record.status == FAILED and record.revision == 2
    assert record.active_version_id is not None
    assert len(repo.versions_for(tenant_id=TENANT_R, draft_id=draft)) == 1
    service = _version_service()
    preview = service.preview_version(
        tenant_id=TENANT_R, draft_id=draft, version_id=record.active_version_id
    )
    assert preview.is_version_preview and preview.can_restore_version
    assert preview.variants[0].copy["hook"] == "legacy"
    assert repo.get_draft(tenant_id=TENANT_R, draft_id=draft).status == FAILED


def test_restoring_is_refused_while_generating_or_already_published() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    _finish(TENANT_R, draft, brand, "first", 1)
    repo = PostgresContentRepository()
    version = repo.get_draft(tenant_id=TENANT_R, draft_id=draft).active_version_id
    for status in (DRAFTING, "staged", "published"):
        with tenant_session(TENANT_R) as session:
            session.get(creative.ContentDraft, draft).status = status
        with pytest.raises(ValueError):
            _version_service().restore_version(
                tenant_id=TENANT_R, draft_id=draft, version_id=version
            )
        assert repo.get_draft(tenant_id=TENANT_R, draft_id=draft).status == status


def _approval_service() -> ContentService:
    service = _version_service()
    service._approval_guard = None
    service._creations = None
    service.dispatcher = None
    return service


def _reviewer() -> UUID:
    from qualify_api.tenancy.models import User

    with admin_session() as session:
        user = User(tenant_id=TENANT_R, email=f"version-{uuid4()}@test.local", display_name="Owner")
        session.add(user)
        session.flush()
        return user.id


def test_approving_a_selected_old_variant_approves_its_version_and_media() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    repo = PostgresContentRepository()
    _finish(TENANT_R, draft, brand, "old copy", 1)
    old = repo.get_draft(tenant_id=TENANT_R, draft_id=draft).active_version_id
    with tenant_session(TENANT_R) as session:
        variant = creative.CopyVariant(
            tenant_id=TENANT_R,
            draft_id=draft,
            version_id=old,
            ordinal=1,
            copy={"hook": "selected second variant", "caption": "c", "cta": "Pide ya"},
            fidelity={"passed": True},
            model_id="test",
        )
        session.add(variant)
        session.flush()
        selected = variant.id
    repo.update_status(tenant_id=TENANT_R, draft_id=draft, new_status=DRAFTING, failure_reason=None)
    repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
    _finish(TENANT_R, draft, brand, "new copy", 2)
    approved = _approval_service().approve_version(
        tenant_id=TENANT_R, draft_id=draft, version_id=old, variant_id=selected, user_id=_reviewer()
    )
    assert approved.status == "approved"
    assert approved.active_version_id == old and approved.selected_variant_id == selected
    assert approved.variants[1].copy["hook"] == "selected second variant"
    assert "/r1/" in approved.media[0].object_key
    assert approved.approved_revision == approved.revision
    from qualify_api.canva.repository import PostgresCanvaRepository
    from qualify_api.planner.draft_post_reader import DraftPostReader
    from qualify_api.planner.post_reader import PublishablePost

    publishable = DraftPostReader().get_publishable(tenant_id=TENANT_R, post_id=draft)
    assert isinstance(publishable, PublishablePost)
    assert publishable.caption.startswith("selected second variant\n\nc")
    assert len(publishable.media) == 1 and "/r1/" in publishable.media[0].object_key
    exported = PostgresCanvaRepository().draft_media(tenant_id=TENANT_R, draft_id=draft)
    assert len(exported) == 1 and "/r1/" in exported[0].object_key


def test_refused_approval_leaves_the_previously_active_version_unchanged() -> None:
    from qualify_api.creative.service import UnknownVariant

    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    repo = PostgresContentRepository()
    _finish(TENANT_R, draft, brand, "old copy", 1)
    old = repo.get_draft(tenant_id=TENANT_R, draft_id=draft).active_version_id
    repo.update_status(tenant_id=TENANT_R, draft_id=draft, new_status=DRAFTING, failure_reason=None)
    repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
    _finish(TENANT_R, draft, brand, "new copy", 2)
    before = repo.get_draft(tenant_id=TENANT_R, draft_id=draft)
    # A variant from the current version cannot be approved as a variant of the old one.
    wrong = repo.variants_for(tenant_id=TENANT_R, draft_id=draft)[0].id
    with pytest.raises(UnknownVariant):
        _approval_service().approve_version(
            tenant_id=TENANT_R,
            draft_id=draft,
            version_id=old,
            variant_id=wrong,
            user_id=_reviewer(),
        )
    after = repo.get_draft(tenant_id=TENANT_R, draft_id=draft)
    assert after.status == before.status and after.revision == before.revision
    assert after.active_version_id == before.active_version_id


def test_each_version_keeps_its_own_model_revision_pipeline_and_cost() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    repo = PostgresContentRepository()
    for number, cost in ((1, Decimal("0.12")), (2, Decimal("0.34"))):
        if number > 1:
            repo.update_status(
                tenant_id=TENANT_R, draft_id=draft, new_status=DRAFTING, failure_reason=None
            )
            repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
        repo.finish_generation(
            tenant_id=TENANT_R,
            draft_id=draft,
            brand_id=brand,
            new_status=GENERATED,
            failure_reason=None,
            variants=(_variant(f"copy {number}"),),
            usage=(),
            spent_usd=cost,
            media=(
                replace(
                    _image(TENANT_R, draft, number),
                    model_id=f"image-model-{number}",
                    params={"model_revision": f"build-{number}"},
                ),
            ),
        )
    history = repo.versions_for(tenant_id=TENANT_R, draft_id=draft)
    assert [(row.revision, row.model_id, row.model_revision, row.spent_usd) for row in history] == [
        (1, "image-model-1", "build-1", Decimal("0.12")),
        (2, "image-model-2", "build-2", Decimal("0.34")),
    ]
    with tenant_session(TENANT_R) as session:
        versions = session.scalars(
            select(creative.PieceVersion).where(creative.PieceVersion.draft_id == draft)
        ).all()
        assert all(version.pipeline_version == "test" for version in versions)


def test_a_pending_vendor_checkpoint_does_not_create_a_failed_version() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    repo = PostgresContentRepository()
    repo.finish_generation(
        tenant_id=TENANT_R,
        draft_id=draft,
        brand_id=brand,
        new_status=DRAFTING,
        failure_reason=None,
        variants=(),
        usage=(),
        spent_usd=Decimal(0),
        expected_revision=1,
    )
    assert repo.versions_for(tenant_id=TENANT_R, draft_id=draft) == ()
    _finish(TENANT_R, draft, brand, "completed", 1)
    assert len(repo.versions_for(tenant_id=TENANT_R, draft_id=draft)) == 1
    assert repo.get_draft(tenant_id=TENANT_R, draft_id=draft).status == GENERATED


def test_a_late_worker_cannot_finish_or_fail_a_newer_regeneration() -> None:
    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    repo = PostgresContentRepository()
    _finish(TENANT_R, draft, brand, "first", 1)
    repo.update_status(tenant_id=TENANT_R, draft_id=draft, new_status=DRAFTING, failure_reason=None)
    repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
    service = _version_service()
    old = repo.get_draft(tenant_id=TENANT_R, draft_id=draft)
    repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
    service._finish_generation(
        old,
        tenant_id=TENANT_R,
        draft_id=draft,
        brand_id=brand,
        new_status=GENERATED,
        failure_reason=None,
        variants=(_variant("late old result"),),
        usage=(),
        spent_usd=Decimal(0),
    )
    service._fail(tenant_id=TENANT_R, draft_id=draft, reason="provider_error", expected_revision=2)
    current = repo.get_draft(tenant_id=TENANT_R, draft_id=draft)
    assert current.status == DRAFTING and current.revision == 3
    assert repo.variants_for(tenant_id=TENANT_R, draft_id=draft)[0].copy["hook"] == "first"
    assert len(repo.versions_for(tenant_id=TENANT_R, draft_id=draft)) == 1


def test_reapproving_a_saved_video_does_not_consume_the_video_quota_again() -> None:
    from datetime import UTC, date, datetime

    brand = _brand(TENANT_R)
    draft = _drafting_draft(TENANT_R, brand)
    repo = PostgresContentRepository()
    _finish(TENANT_R, draft, brand, "first", 1)
    old = repo.get_draft(tenant_id=TENANT_R, draft_id=draft).active_version_id
    selected = repo.variants_for(tenant_id=TENANT_R, draft_id=draft)[0].id
    with tenant_session(TENANT_R) as session:
        session.add(
            creative.CreationCharge(
                tenant_id=TENANT_R,
                brand_id=brand,
                draft_id=draft,
                revision=1,
                request_kind="generated_video",
                weight=1,
                monthly_quota=30,
                weights_version="test",
                pricing_table_version="test",
                period_month=date.today().replace(day=1),
                videos=1,
                videos_period_month=date.today().replace(day=1),
                videos_charged_at=datetime.now(UTC),
            )
        )
    repo.update_status(tenant_id=TENANT_R, draft_id=draft, new_status=DRAFTING, failure_reason=None)
    repo.bump_revision(tenant_id=TENANT_R, draft_id=draft)
    _finish(TENANT_R, draft, brand, "second", 2)
    service = _approval_service()
    service._creations = object()  # Any ledger access would mean charging again.
    approved = service.approve_version(
        tenant_id=TENANT_R, draft_id=draft, version_id=old, variant_id=selected, user_id=_reviewer()
    )
    assert approved.status == "approved"
    with tenant_session(TENANT_R) as session:
        charges = session.scalars(
            select(creative.CreationCharge).where(creative.CreationCharge.draft_id == draft)
        ).all()
        assert len(charges) == 1 and charges[0].revision == 1 and charges[0].videos == 1
