"""`db`-marked tests for PR 5 of ticket 24803289 (coherencia de precio): on the real
engine, the price guard's lookup (draft → the set's frozen catalog price) through the
tenant door and inside RLS; an approval from `/drafts/{id}` (`ContentService.approve`)
held to that price while every other draft approves as before; and the composition's
warnings surviving `image_assets.params` into `get_draft` and `get_drafts`.

The root `conftest.py` migrates `qualify_test` to head before any `db` test runs."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.catalog.models import BrandProduct
from qualify_api.creative.angle_sets import AnglePriceGuard, set_price_label_for_draft
from qualify_api.creative.fsm import APPROVED, DRAFTING, GENERATED
from qualify_api.creative.media import (
    PRICE_NOT_PRINTED,
    PRICE_NOT_PRINTED_TEXT,
    MediaWarning,
    MediaWrite,
)
from qualify_api.creative.models import (
    ContentBrief,
    ContentDraft,
    CopyVariant,
    CreativeAngle,
    CreativeAngleSet,
)
from qualify_api.creative.service import (
    ApprovalBlocked,
    ContentService,
    DraftWarning,
    PostgresContentRepository,
    with_composition_warnings,
)
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

# Distinct from the tenants of the other schema-test modules so suites stay independent.
TENANT_A = UUID("a0000000-0000-4000-8000-0000000008a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000008b2")


@pytest.fixture
def seeded() -> tuple[UUID, UUID]:
    """Two tenants with a brand each and a user in A. Returns (brand_a, user_a)."""
    with admin_session() as session:
        brands: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"price-guard-t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"price-guard-brand-{name}")
                session.add(brand)
                session.flush()
            brands[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"price-guard-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id
    return brands[TENANT_A], user_id


def _draft(brand_id: UUID, user_id: UUID, *, hook: str, status: str = GENERATED) -> UUID:
    """A draft of tenant A with one copy variant quoting `hook`."""
    with tenant_session(TENANT_A) as session:
        brief = ContentBrief(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            objective="sale",
            topic="shawarma mixto",
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="product",
            image_route="template_only",
            kind="static_flyer",
            created_by=user_id,
        )
        session.add(brief)
        session.flush()
        draft = ContentDraft(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            brief_id=brief.id,
            status=status,
            pipeline_version="creative-v2",
        )
        session.add(draft)
        session.flush()
        session.add(
            CopyVariant(
                tenant_id=TENANT_A,
                draft_id=draft.id,
                ordinal=0,
                copy={"hook": hook, "caption": "Hoy, en la barra.", "cta": "Pide ya"},
                model_id="claude-opus-5",
            )
        )
        return draft.id


def _variant(draft_id: UUID) -> UUID:
    with tenant_session(TENANT_A) as session:
        return session.scalar(select(CopyVariant.id).where(CopyVariant.draft_id == draft_id))


def _as_angle_piece(brand_id: UUID, user_id: UUID, draft_id: UUID, price_label: str) -> None:
    """Make `draft_id` the piece of an angle in a set that froze `price_label`."""
    with tenant_session(TENANT_A) as session:
        product = BrandProduct(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            name="Shawarma mixto",
            slug=f"shawarma-{uuid4().hex[:8]}",
            price_amount=Decimal("18000.00") if price_label else None,
            price_currency="COP" if price_label else "",
        )
        session.add(product)
        session.flush()
        angle_set = CreativeAngleSet(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            product_id=product.id,
            preset_key="escena_producto",
            requested_count=10,
            status="generating",
            product_name="Shawarma mixto",
            price_label=price_label,
            price_missing=not price_label,
            created_by=user_id,
        )
        session.add(angle_set)
        session.flush()
        session.add(
            CreativeAngle(
                tenant_id=TENANT_A,
                set_id=angle_set.id,
                position=1,
                title="En la barra",
                scene="El shawarma sobre la barra",
                status="queued",
                draft_id=draft_id,
            )
        )


def _service() -> ContentService:
    """Only `approve` and the reads are exercised: no router, vendor or key is touched."""
    return ContentService(
        router=None,  # type: ignore[arg-type]
        pricing=None,  # type: ignore[arg-type]
        credentials=None,  # type: ignore[arg-type]
        voice_service=None,  # type: ignore[arg-type]
        brand_service=None,  # type: ignore[arg-type]
        repository=PostgresContentRepository(),
        approval_guard=AnglePriceGuard(),
    )


def _status(draft_id: UUID) -> str:
    with tenant_session(TENANT_A) as session:
        return session.get(ContentDraft, draft_id).status


def test_the_lookup_reads_the_sets_frozen_price_inside_the_tenant(
    seeded: tuple[UUID, UUID],
) -> None:
    brand_id, user_id = seeded
    priced = _draft(brand_id, user_id, hook="a")
    unpriced = _draft(brand_id, user_id, hook="b")
    plain = _draft(brand_id, user_id, hook="c")
    _as_angle_piece(brand_id, user_id, priced, "$18.000")
    _as_angle_piece(brand_id, user_id, unpriced, "")

    assert set_price_label_for_draft(TENANT_A, priced) == "$18.000"
    assert set_price_label_for_draft(TENANT_A, unpriced) == ""  # an angle's, without price
    assert set_price_label_for_draft(TENANT_A, plain) is None  # no angle's: never checked
    # another tenant sees no angle at all (RLS), so it is never held to A's price
    assert set_price_label_for_draft(TENANT_B, priced) is None


def test_an_approval_from_the_drafts_screen_is_held_to_the_catalog_price(
    seeded: tuple[UUID, UUID],
) -> None:
    brand_id, user_id = seeded
    service = _service()

    wrong = _draft(brand_id, user_id, hook="Shawarma mixto a $15.000")
    _as_angle_piece(brand_id, user_id, wrong, "$18.000")
    with pytest.raises(ApprovalBlocked, match=r"\$15\.000"):
        service.approve(
            tenant_id=TENANT_A, draft_id=wrong, variant_id=_variant(wrong), user_id=user_id
        )
    assert _status(wrong) == GENERATED  # nothing written

    invented = _draft(brand_id, user_id, hook="Solo $9.900 hoy")
    _as_angle_piece(brand_id, user_id, invented, "")
    with pytest.raises(ApprovalBlocked, match="no tiene precio en el catálogo"):
        service.approve(
            tenant_id=TENANT_A, draft_id=invented, variant_id=_variant(invented), user_id=user_id
        )
    assert _status(invented) == GENERATED

    right = _draft(brand_id, user_id, hook="Shawarma mixto a $18.000")
    _as_angle_piece(brand_id, user_id, right, "$18.000")
    detail = service.approve(
        tenant_id=TENANT_A, draft_id=right, variant_id=_variant(right), user_id=user_id
    )
    assert detail.status == APPROVED


def test_a_generator_draft_quoting_any_figure_approves_as_before(
    seeded: tuple[UUID, UUID],
) -> None:
    brand_id, user_id = seeded
    draft_id = _draft(brand_id, user_id, hook="Promo: 2 por $30.000 este fin de semana")
    detail = _service().approve(
        tenant_id=TENANT_A, draft_id=draft_id, variant_id=_variant(draft_id), user_id=user_id
    )
    assert detail.status == APPROVED


def test_composition_warnings_survive_the_media_rows_into_both_reads(
    seeded: tuple[UUID, UUID],
) -> None:
    brand_id, user_id = seeded
    repo = PostgresContentRepository()
    draft_id = _draft(brand_id, user_id, hook="h", status=DRAFTING)
    cover = MediaWrite(
        position=0,
        media_type="image",
        media_url=f"generated/{TENANT_A}/{draft_id}/slide-1.jpg",
        object_key=f"generated/{TENANT_A}/{draft_id}/slide-1.jpg",
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="qualify-compose-v1",
        provider="local",
    )
    warning = MediaWarning(
        code=PRICE_NOT_PRINTED, detail=PRICE_NOT_PRINTED_TEXT, fields={"reason": "too_long"}
    )
    repo.finish_generation(
        tenant_id=TENANT_A,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status=GENERATED,
        failure_reason=None,
        variants=(),
        usage=(),
        spent_usd=Decimal(0),
        media=with_composition_warnings((cover,), (warning,)),
    )
    service = _service()
    expected = (DraftWarning(PRICE_NOT_PRINTED, PRICE_NOT_PRINTED_TEXT),)
    single = service.get_draft(tenant_id=TENANT_A, draft_id=draft_id)
    assert single is not None and single.warnings == expected
    batch = service.get_drafts(tenant_id=TENANT_A, draft_ids=[draft_id])
    assert batch[draft_id].warnings == expected
