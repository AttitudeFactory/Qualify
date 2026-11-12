"""Real PostgreSQL fences for advertising edits, revision and approval."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import CopyPayload
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session, tenant_unit_of_work

from qualify_api.creative import models as orm
from qualify_api.creative.service import (
    ContentService,
    DraftEditConflict,
    PostgresContentRepository,
    UnknownVariant,
)
from qualify_api.tenancy.models import Brand, Tenant, User

from . import test_content_service as base

pytestmark = pytest.mark.db
AdPiece = tuple[UUID, UUID, UUID, UUID, UUID]


@pytest.fixture
def ad_piece() -> AdPiece:
    with admin_session() as session:
        tenant = Tenant(
            name="Ad fields test", country="CO", timezone="America/Bogota", currency="COP"
        )
        session.add(tenant)
        session.flush()
        brand = Brand(tenant_id=tenant.id, name="Ad fields brand")
        user = User(
            tenant_id=tenant.id, email=f"ad-fields-{uuid4()}@example.test", display_name="U"
        )
        session.add_all([brand, user])
        session.flush()
        tenant_id, brand_id, user_id = tenant.id, brand.id, user.id
    with tenant_session(tenant_id) as session:
        brief = orm.ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic="Arepas",
            platform="instagram",
            format="feed_4_5",
            intent="ads",
            content_type="promotion",
            image_route="template_only",
            created_by=user_id,
        )
        session.add(brief)
        session.flush()
        draft = orm.ContentDraft(
            tenant_id=tenant_id,
            brand_id=brand_id,
            brief_id=brief.id,
            status="approved",
            pipeline_version="test-ad-fields",
            revision=1,
            approved_revision=1,
            approved_by=user_id,
            approved_at=datetime.now(UTC),
        )
        session.add(draft)
        session.flush()
        variant = orm.CopyVariant(
            tenant_id=tenant_id,
            draft_id=draft.id,
            ordinal=0,
            copy=base.copy_dict() | {"ads_cta_type": "Más información"},
            model_id="fixture",
            fidelity={"passed": True},
        )
        session.add(variant)
        session.flush()
        draft.selected_variant_id = variant.id
        draft_id, variant_id = draft.id, variant.id
    return tenant_id, brand_id, user_id, draft_id, variant_id


def _service(brand: UUID) -> tuple[ContentService, PostgresContentRepository]:
    repo = PostgresContentRepository()
    service, _, _ = base.make_service(repo=repo, kit=base.make_kit(brand_id=brand))
    return service, repo


def _copy(url: str = "https://example.com/menu") -> CopyPayload:
    return CopyPayload.model_validate(
        base.copy_dict() | {"ads_cta_type": "GET_QUOTE", "ads_destination_url": url},
        context={"strict_ad_cta": True},
    )


def test_copy_write_rolls_back_if_revision_transition_fails(
    ad_piece: AdPiece, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, brand, user, draft_id, variant = ad_piece
    service, repo = _service(brand)

    def fail(**kwargs: object) -> None:
        raise RuntimeError("revision write failed")

    monkeypatch.setattr(repo, "bump_revision", fail)
    with pytest.raises(RuntimeError, match="revision write"):
        service.edit_variant(
            tenant_id=tenant, variant_id=variant, user_id=user, copy=_copy(), expected_revision=1
        )
    with tenant_session(tenant) as session:
        assert session.get(orm.CopyVariant, variant).edited_copy is None
        draft = session.get(orm.ContentDraft, draft_id)
        assert draft.revision == 1 and draft.status == "approved"


def test_locked_compare_refreshes_an_already_cached_draft(ad_piece: AdPiece) -> None:
    tenant, brand, user, draft_id, variant = ad_piece
    service, _ = _service(brand)
    with tenant_unit_of_work(tenant) as session:
        cached = session.get(orm.ContentDraft, draft_id)
        assert cached.revision == 1
        with tenant_session(tenant, independent=True) as concurrent:
            concurrent.get(orm.ContentDraft, draft_id).revision = 2
        with pytest.raises(DraftEditConflict):
            service.edit_variant(
                tenant_id=tenant,
                variant_id=variant,
                user_id=user,
                copy=_copy(),
                expected_revision=1,
            )
        assert cached.revision == 2
        assert session.get(orm.CopyVariant, variant).edited_copy is None


def test_only_one_editor_with_same_revision_can_commit(ad_piece: AdPiece) -> None:
    tenant, brand, user, draft_id, variant = ad_piece

    def edit(index: int) -> str:
        service, _ = _service(brand)
        try:
            service.edit_variant(
                tenant_id=tenant,
                variant_id=variant,
                user_id=user,
                copy=_copy(f"https://example.com/menu-{index}"),
                expected_revision=1,
            )
        except DraftEditConflict:
            return "stale"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(edit, [1, 2]))
    assert sorted(results) == ["saved", "stale"]
    with tenant_session(tenant) as session:
        draft = session.get(orm.ContentDraft, draft_id)
        assert draft.revision == 2 and draft.status == "generated"
        assert draft.approved_revision == 1
        assert session.get(orm.CopyVariant, variant).edited_copy["ads_cta_type"] == "GET_QUOTE"


def test_foreign_tenant_cannot_edit_piece(ad_piece: AdPiece) -> None:
    _, brand, user, _, variant = ad_piece
    service, _ = _service(brand)
    with pytest.raises(UnknownVariant):
        service.edit_variant(
            tenant_id=uuid4(), variant_id=variant, user_id=user, copy=_copy(), expected_revision=1
        )
