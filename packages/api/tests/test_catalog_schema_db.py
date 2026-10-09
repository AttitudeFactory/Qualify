"""`db`-marked schema tests for migration 0038 (product catalog + template runs): a
roundtrip of `brand_products`, `product_media` and `template_runs` through the sanctioned
`tenant_session` door, the RLS isolation read from a second tenant, and the three widened
columns (`image_assets.output_port`/`template_run_id`, `content_drafts.campaign_id`).

The root `conftest.py` creates/migrates `qualify_test` forward to head before any `db` test
runs, so "upgrade to head" is the harness's job, not this module's. Needs the compose
Postgres — runs in the integration pass, never as a pure unit test."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text

from qualify_api.catalog.models import MEDIA_TYPE_IMAGE, BrandProduct, ProductMedia
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.models import (
    Campaign,
    ContentBrief,
    ContentDraft,
    ImageAsset,
    TemplateRun,
)
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

# Distinct from the tenants of the other schema-test modules so suites stay independent.
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000d1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000d2")


@pytest.fixture
def seeded_brands() -> tuple[UUID, UUID, UUID, UUID]:
    """Two tenants, each with a brand, plus a user in A — provisioned through the
    BYPASSRLS admin door (R8). Everything the tests assert goes through `tenant_session`.
    Idempotent for local re-runs. Returns (tenant_a, brand_a, user_a, tenant_b)."""
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"catalog-t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        brand_ids: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"catalog-brand-{name}")
                session.add(brand)
                session.flush()
            brand_ids[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"catalog-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id
    return TENANT_A, brand_ids[TENANT_A], user_id, TENANT_B


def _new_draft(session, tenant_id: UUID, brand_id: UUID, user_id: UUID) -> ContentDraft:
    brief = ContentBrief(
        tenant_id=tenant_id,
        brand_id=brand_id,
        objective="sale",
        topic="shawarma mixto",
        product_ref="shawarma-mixto",
        platform="instagram",
        format="reel_9_16",
        intent="organic",
        content_type="product",
        image_route="template_only",
        created_by=user_id,
    )
    session.add(brief)
    session.flush()
    draft = ContentDraft(
        tenant_id=tenant_id,
        brand_id=brand_id,
        brief_id=brief.id,
        status=DRAFTING,
        pipeline_version="creative-v2",
        template_id="promo-producto",
        template_version=1,
    )
    session.add(draft)
    session.flush()
    return draft


def test_product_media_and_template_run_roundtrip(
    seeded_brands: tuple[UUID, UUID, UUID, UUID],
) -> None:
    tenant_a, brand_a, user_a, _ = seeded_brands
    slug = f"shawarma-mixto-{uuid4().hex[:8]}"  # UNIQUE(brand_id, slug); fresh per run
    with tenant_session(tenant_a) as session:
        # Since 0045 `campaign_id` has a real FK: the campaign must exist (QUA-143).
        campaign = Campaign(
            tenant_id=tenant_a,
            brand_id=brand_a,
            name=f"Lanzamiento {uuid4().hex[:8]}",
            color="violet",
        )
        session.add(campaign)
        session.flush()
        campaign_id = campaign.id
        product = BrandProduct(
            tenant_id=tenant_a,
            brand_id=brand_a,
            name="Shawarma mixto",
            slug=slug,
            description="Pollo y carne, pan árabe recién hecho",
            price_amount=Decimal("18000.00"),
            price_currency="COP",
            category="shawarmas",
            tags=["popular", "combo"],
            created_by=user_a,
        )
        session.add(product)
        session.flush()
        media = ProductMedia(
            tenant_id=tenant_a,
            brand_id=brand_a,
            product_id=product.id,
            media_type=MEDIA_TYPE_IMAGE,
            object_key=f"t/{tenant_a}/brand/{brand_a}/products/{product.id}/hero.jpg",
            filename="hero.jpg",
            content_type="image/jpeg",
            width=1080,
            height=1350,
            bytes=412_000,
            normalized=True,
            is_primary=True,
        )
        session.add(media)
        draft = _new_draft(session, tenant_a, brand_a, user_a)
        draft.campaign_id = campaign_id
        run = TemplateRun(
            tenant_id=tenant_a,
            brand_id=brand_a,
            draft_id=draft.id,
            template_id="promo-producto",
            template_version=1,
            prompt_id="shawarma/producto",
            prompt_version=1,
            engine="remotion",
            router_rule="has_product_photos",
            status="pending",
            outputs={"reel_9_16": "pending", "feed_4_5": "pending", "story_9_16": "pending"},
            estimated_eta_sec=Decimal("45.00"),
            estimated_cost_usd=Decimal("0.0300"),
            props={"product_slug": slug, "price_line": "$18.000"},
        )
        session.add(run)
        session.flush()
        asset = ImageAsset(
            tenant_id=tenant_a,
            draft_id=draft.id,
            media_url="https://render.local/out/reel.mp4",
            media_type="video",
            position=0,
            output_port="reel_9_16",
            template_run_id=run.id,
        )
        session.add(asset)
        session.flush()
        product_id, media_id, run_id, draft_id, asset_id = (
            product.id,
            media.id,
            run.id,
            draft.id,
            asset.id,
        )

    with tenant_session(tenant_a) as session:
        got_product = session.get(BrandProduct, product_id)
        assert got_product is not None
        assert got_product.slug == slug
        assert got_product.price_amount == Decimal("18000.00")
        assert got_product.tags == ["popular", "combo"]
        assert got_product.is_active is True  # server default
        assert got_product.position == 0  # server default
        assert got_product.created_at is not None and got_product.updated_at is not None

        got_media = session.scalar(
            select(ProductMedia).where(ProductMedia.product_id == product_id)
        )
        assert got_media is not None and got_media.id == media_id
        assert got_media.media_type == "image"
        assert got_media.is_primary is True and got_media.normalized is True
        assert got_media.bytes == 412_000

        got_run = session.get(TemplateRun, run_id)
        assert got_run is not None
        assert got_run.engine == "remotion" and got_run.status == "pending"
        assert got_run.outputs["feed_4_5"] == "pending"
        assert got_run.estimated_cost_usd == Decimal("0.0300")
        assert got_run.actual_cost_usd is None and got_run.started_at is None

        got_asset = session.get(ImageAsset, asset_id)
        assert got_asset is not None
        assert got_asset.output_port == "reel_9_16"
        assert got_asset.template_run_id == run_id

        got_draft = session.get(ContentDraft, draft_id)
        assert got_draft is not None and got_draft.campaign_id == campaign_id


def test_rls_hides_catalog_and_runs_from_another_tenant(
    seeded_brands: tuple[UUID, UUID, UUID, UUID],
) -> None:
    tenant_a, brand_a, user_a, tenant_b = seeded_brands
    with tenant_session(tenant_a) as session:
        product = BrandProduct(
            tenant_id=tenant_a,
            brand_id=brand_a,
            name="Helado de pistacho",
            slug=f"pistacho-{uuid4().hex[:8]}",
        )
        session.add(product)
        session.flush()
        session.add(
            ProductMedia(
                tenant_id=tenant_a,
                brand_id=brand_a,
                product_id=product.id,
                media_type="image",
                object_key=f"t/{tenant_a}/products/{product.id}/1.jpg",
            )
        )
        draft = _new_draft(session, tenant_a, brand_a, user_a)
        session.add(
            TemplateRun(
                tenant_id=tenant_a,
                brand_id=brand_a,
                draft_id=draft.id,
                template_id="promo-producto",
                template_version=1,
                engine="heygen",
                status="pending",
            )
        )
        session.flush()
        product_id = product.id

    with tenant_session(tenant_b) as session:
        # No explicit WHERE — RLS is the only thing scoping these reads.
        assert session.get(BrandProduct, product_id) is None
        assert session.scalars(select(BrandProduct)).all() == []
        assert session.scalars(select(ProductMedia)).all() == []
        assert session.scalars(select(TemplateRun)).all() == []

    with tenant_session(tenant_a) as session:
        assert session.get(BrandProduct, product_id) is not None


def test_deleting_a_product_cascades_to_its_media(
    seeded_brands: tuple[UUID, UUID, UUID, UUID],
) -> None:
    tenant_a, brand_a, _, _ = seeded_brands
    with tenant_session(tenant_a) as session:
        product = BrandProduct(
            tenant_id=tenant_a, brand_id=brand_a, name="Combo", slug=f"combo-{uuid4().hex[:8]}"
        )
        session.add(product)
        session.flush()
        session.add(
            ProductMedia(
                tenant_id=tenant_a,
                brand_id=brand_a,
                product_id=product.id,
                media_type="video",
                object_key=f"t/{tenant_a}/products/{product.id}/clip.mp4",
                duration_sec=Decimal("6.50"),
            )
        )
        session.flush()
        product_id = product.id

    with tenant_session(tenant_a) as session:
        session.delete(session.get(BrandProduct, product_id))
        session.flush()
        assert (
            session.scalars(select(ProductMedia).where(ProductMedia.product_id == product_id)).all()
            == []
        )


def test_widened_columns_exist_with_the_contracted_types() -> None:
    """The three ALTERs of 0038, read from the catalog: name, type, nullability."""
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND ("
                "  (table_name = 'image_assets'"
                "   AND column_name IN ('output_port', 'template_run_id'))"
                "  OR (table_name = 'content_drafts' AND column_name = 'campaign_id'))"
            )
        ).all()
    by_col = {(r.table_name, r.column_name): (r.data_type, r.is_nullable) for r in rows}
    assert by_col == {
        ("image_assets", "output_port"): ("text", "YES"),
        ("image_assets", "template_run_id"): ("uuid", "YES"),
        ("content_drafts", "campaign_id"): ("uuid", "YES"),
    }


def test_campaign_id_gets_its_foreign_key_in_0045() -> None:
    """0038 left the column bare on purpose; 0045 (QUA-143) declares the `campaigns` FK.

    Read from `pg_constraint`, not `information_schema`: the latter only lists
    constraints of tables the role owns or may write, and `qualify_admin` only has
    SELECT — it would report zero FKs whatever the schema says."""
    with admin_session() as session:
        defs = session.scalars(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'public.content_drafts'::regclass AND contype = 'f' "
                "  AND conname = 'fk_content_draft_campaign'"
            )
        ).all()
    assert len(defs) == 1
    assert "(campaign_id, tenant_id, brand_id)" in defs[0]
    assert "campaigns(id, tenant_id, brand_id)" in defs[0]
    assert "ON DELETE SET NULL (campaign_id)" in defs[0]
