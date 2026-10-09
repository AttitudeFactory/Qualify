"""`db`-marked test for a regeneration's copy (2026-10-09): the second
`finish_generation` of a draft writes variants with the same ordinals as the first, and
`uq_copy_variant_ordinal` (0009) refused them — after the vendor had been paid. The
Postgres repository now replaces the draft's variants, like it already replaced its
media, and drops a selection that pointed at a replaced one.

The in-memory repository of `test_content_service.py` has no unique constraint, which is
why this only shows against the real schema."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import models as creative
from qualify_api.creative.fsm import DRAFTING, GENERATED
from qualify_api.creative.media import MediaWrite
from qualify_api.creative.service import PostgresContentRepository, VariantWrite
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


def test_a_regeneration_replaces_the_copy_variants_and_clears_the_selection() -> None:
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
        assert [(v.ordinal, v.copy["hook"]) for v in variants] == [(0, "segunda")]
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None
        assert draft.status == GENERATED and draft.selected_variant_id is None
        # the media rows are the new revision's only (0047: the app role may DELETE)
        assets = session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == draft_id)
        ).all()
        assert [a.object_key.rsplit("/", 2)[1] for a in assets] == ["r2"]
        assert draft.preview_key == assets[0].object_key
