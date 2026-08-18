"""`db`-marked schema tests for the creative migration (MC-01): a roundtrip of
`brand_kits` and `content_drafts` through the sanctioned `tenant_session` door, plus the
RLS isolation read. Needs the compose Postgres with the creative migration applied — runs
in the integration pass, never as a pure unit test."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.fsm import DRAFTING, GENERATED
from qualify_api.creative.models import BrandKit, ContentBrief, ContentDraft
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

# Distinct from the tenants of the other schema-test modules so suites stay independent.
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000c1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000c2")


@pytest.fixture
def seeded_brands() -> tuple[UUID, UUID, UUID, UUID]:
    """Two tenants, each with a brand, plus a user in A. Provisioning goes through the
    BYPASSRLS admin door (R8); everything the tests assert goes through
    `tenant_session`, the real production door. Idempotent for local re-runs.

    Returns (tenant_a, brand_a, user_a, tenant_b).
    """
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"creative-t-{name}",
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
                brand = Brand(tenant_id=tid, name=f"creative-brand-{name}")
                session.add(brand)
                session.flush()
            brand_ids[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"creative-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id
    return TENANT_A, brand_ids[TENANT_A], user_id, TENANT_B


def test_brand_kit_roundtrip(seeded_brands: tuple[UUID, UUID, UUID, UUID]) -> None:
    tenant_a, brand_a, _, _ = seeded_brands
    with tenant_session(tenant_a) as session:
        # Idempotent re-run (same standard test_connections_schema.py adopted): a prior
        # run's kit would trip UNIQUE(brand_id). The app role has no DELETE grant (repo
        # convention, audit-preserving), so idempotency is insert-if-absent, not wipe.
        if session.scalar(select(BrandKit).where(BrandKit.brand_id == brand_a)) is None:
            session.add(
                BrandKit(
                    tenant_id=tenant_a,
                    brand_id=brand_a,
                    positioning="artisan arepas, zero shortcuts",
                    audience="walk-in customers in Cali",
                    language="es",
                    regional_variant="es-CO",
                    tone_axes={"formal": 0.2, "playful": 0.8},
                    do_examples=["¡Llegó la arepa de chócolo!"],
                    dont_examples=["Estimado cliente, le informamos..."],
                    banned_words=["gourmet"],
                    forbidden_claims=["la mejor de Colombia"],
                    emoji_policy="sparse",
                    hashtag_policy={"max": 5},
                    cta_patterns=["Pide por WhatsApp"],
                    length_targets={"caption": 400},
                    palette_rgb=["#FFD100", "#1A1A1A"],
                    logo_asset_key="brand/logo.png",
                    reference_image_keys=["brand/ref-1.jpg"],
                    image_policy={"allowed_routes": ["template_only", "from_upload"]},
                    photo_recipe={"warmth": 1.04},
                )
            )
            session.flush()

    with tenant_session(tenant_a) as session:
        kit = session.scalar(select(BrandKit).where(BrandKit.brand_id == brand_a))
        assert kit is not None
        assert kit.language == "es"
        assert kit.tone_axes == {"formal": 0.2, "playful": 0.8}
        assert kit.banned_words == ["gourmet"]
        assert kit.created_at is not None
        assert kit.updated_at is not None
        kit_id = kit.id

    with tenant_session(TENANT_B) as session:
        # No explicit WHERE — RLS is the only thing scoping this read.
        assert session.get(BrandKit, kit_id) is None


def test_content_draft_roundtrip_and_isolation(
    seeded_brands: tuple[UUID, UUID, UUID, UUID],
) -> None:
    tenant_a, brand_a, user_a, tenant_b = seeded_brands
    with tenant_session(tenant_a) as session:
        brief = ContentBrief(
            tenant_id=tenant_a,
            brand_id=brand_a,
            objective="sale",
            topic="arepa de chócolo nueva",
            product_ref="arepa-chocolo",
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="product",
            image_route="from_upload",
            source_media_key="t/media/arepa.jpg",
            constraints={"must_mention": ["precio"]},
            created_by=user_a,
        )
        session.add(brief)
        session.flush()
        draft = ContentDraft(
            tenant_id=tenant_a,
            brand_id=brand_a,  # denormalized from the brief for the listing index
            brief_id=brief.id,
            status=DRAFTING,
            voice_profile_version=1,
            pipeline_version="creative-v1",
            template_id="promo-basic",
            template_version=1,
            requires_ai_disclosure=False,
        )
        session.add(draft)
        session.flush()
        draft_id = draft.id

    with tenant_session(tenant_a) as session:
        row = session.get(ContentDraft, draft_id)
        assert row is not None
        assert row.status == DRAFTING
        assert row.brand_id == brand_a
        assert row.selected_variant_id is None
        assert row.staged_container_id is None
        assert row.published_media_id is None
        # Status writes go through the FSM's vocabulary; persist a legal successor.
        row.status = GENERATED
        session.flush()

    with tenant_session(tenant_a) as session:
        row = session.get(ContentDraft, draft_id)
        assert row is not None
        assert row.status == GENERATED

    with tenant_session(tenant_b) as session:
        assert session.get(ContentDraft, draft_id) is None
        assert session.scalars(select(ContentDraft)).all() == []
