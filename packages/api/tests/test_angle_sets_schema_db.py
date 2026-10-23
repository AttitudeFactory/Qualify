"""`db`-marked tests for the «10 variaciones» migration (`creative_angle_sets`,
`creative_angles`, 0070, ticket 24803289): a roundtrip through `PostgresAngleSetRepository`
(the sanctioned `tenant_session` door), RLS isolation (also with an empty `app.tenant_id`
— the NULLIF), the CHECKs and the unique position, that the app role cannot DELETE a set
or an angle, and that a product with a set cannot be deleted from under it (RESTRICT).

The root `conftest.py` migrates `qualify_test` to head before any `db` test runs."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_creative.angles import CreativeAngle
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.catalog.models import BrandProduct
from qualify_api.creative.angle_sets import (
    ANGLE_DISCARDED,
    ANGLE_PROPOSED,
    ANGLE_QUEUED,
    ANGLE_RESERVED,
    SET_ANGLES_READY,
    SET_DRAFTING,
    AngleSetWrite,
    PostgresAngleSetRepository,
)
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.models import ContentBrief, ContentDraft
from qualify_api.creative.models import CreativeAngle as AngleRow
from qualify_api.creative.models import CreativeAngleSet as AngleSetRow
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

# Distinct from the tenants of the other schema-test modules so suites stay independent.
TENANT_A = UUID("a0000000-0000-4000-8000-0000000006a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000006b2")


@pytest.fixture
def seeded() -> tuple[UUID, UUID]:
    """Two tenants, each with a brand, plus a user in A — through the BYPASSRLS admin door.
    Idempotent for local re-runs. Returns (brand_a, user_a)."""
    with admin_session() as session:
        brand_ids: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"angles-t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"angles-brand-{name}")
                session.add(brand)
                session.flush()
            brand_ids[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"angles-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id
    return brand_ids[TENANT_A], user_id


def _product(brand_id: UUID) -> UUID:
    with tenant_session(TENANT_A) as session:
        product = BrandProduct(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            name="Shawarma mixto",
            slug=f"shawarma-{uuid4().hex[:8]}",
            price_amount=Decimal("18000.00"),
            price_currency="COP",
        )
        session.add(product)
        session.flush()
        return product.id


def _draft(brand_id: UUID, user_id: UUID) -> UUID:
    with tenant_session(TENANT_A) as session:
        brief = ContentBrief(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            objective="sale",
            topic="shawarma mixto",
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
            tenant_id=TENANT_A,
            brand_id=brand_id,
            brief_id=brief.id,
            status=DRAFTING,
            pipeline_version="creative-v2",
        )
        session.add(draft)
        session.flush()
        return draft.id


def _angles(count: int) -> list[CreativeAngle]:
    return [
        CreativeAngle(
            position=i,
            title=f"Ángulo {i}",
            scene=f"Escena número {i} con el producto",
            composition="plano medio",
            hook="Hoy se antoja",
            cta="Pide ya",
            rationale="porque sí",
        )
        for i in range(1, count + 1)
    ]


def _new_set(repo: PostgresAngleSetRepository, brand_id: UUID, user_id: UUID) -> UUID:
    return repo.insert_set(
        AngleSetWrite(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            product_id=_product(brand_id),
            preset_key="escena_producto",
            requested_count=3,
            product_name="Shawarma mixto",
            price_label="$ 18.000",
            price_missing=False,
            created_by=user_id,
        )
    )


def test_a_set_and_its_angles_roundtrip_through_the_repository(
    seeded: tuple[UUID, UUID],
) -> None:
    brand_a, user_a = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_a, user_a)
    record = repo.get_set(tenant_id=TENANT_A, set_id=set_id)
    assert record is not None
    assert record.status == SET_DRAFTING and record.price_label == "$ 18.000"
    assert record.price_missing is False and record.created_by == user_a

    repo.update_set(
        tenant_id=TENANT_A,
        set_id=set_id,
        status=SET_ANGLES_READY,
        model_id="claude-sonnet-5",
        prompt_fingerprint="abc123",
        input_tokens=1200,
        output_tokens=900,
        cost_usd=Decimal("0.0171"),
    )
    ids = repo.insert_angles(tenant_id=TENANT_A, set_id=set_id, angles=list(reversed(_angles(3))))
    assert len(ids) == 3

    record = repo.get_set(tenant_id=TENANT_A, set_id=set_id)
    assert record is not None and record.status == SET_ANGLES_READY
    assert record.model_id == "claude-sonnet-5" and record.cost_usd == Decimal("0.017100")
    assert (record.input_tokens, record.output_tokens) == (1200, 900)
    assert set_id in {s.id for s in repo.list_sets(tenant_id=TENANT_A, brand_id=brand_a)}

    angles = repo.list_angles(tenant_id=TENANT_A, set_id=set_id)
    assert [a.position for a in angles] == [1, 2, 3]  # ordered, whatever the insert order
    assert all(a.status == ANGLE_PROPOSED and a.draft_id is None for a in angles)
    assert angles[0].angle.scene == "Escena número 1 con el producto"

    draft_id = _draft(brand_a, user_a)
    repo.update_angle(
        tenant_id=TENANT_A,
        angle_id=angles[0].id,
        status=ANGLE_QUEUED,
        draft_id=draft_id,
        attempts=1,
        brief={"topic": "shawarma"},
    )
    repo.update_angle(tenant_id=TENANT_A, angle_id=angles[1].id, status=ANGLE_DISCARDED)
    first = repo.get_angle(tenant_id=TENANT_A, angle_id=angles[0].id)
    assert first is not None
    assert (first.status, first.draft_id, first.attempts) == (ANGLE_QUEUED, draft_id, 1)
    assert first.brief == {"topic": "shawarma"}
    second = repo.get_angle(tenant_id=TENANT_A, angle_id=angles[1].id)
    assert second is not None and second.status == ANGLE_DISCARDED


def test_rls_isolates_tenants_and_an_empty_tenant_sees_nothing(
    seeded: tuple[UUID, UUID],
) -> None:
    brand_a, user_a = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_a, user_a)
    (angle_id, *_) = repo.insert_angles(tenant_id=TENANT_A, set_id=set_id, angles=_angles(2))

    assert repo.get_set(tenant_id=TENANT_B, set_id=set_id) is None
    assert repo.get_angle(tenant_id=TENANT_B, angle_id=angle_id) is None
    assert repo.list_angles(tenant_id=TENANT_B, set_id=set_id) == ()
    with tenant_session(TENANT_B) as session:
        # no WHERE — RLS is the only thing scoping these reads
        assert session.scalars(select(AngleSetRow)).all() == []
        assert session.scalars(select(AngleRow)).all() == []
    with tenant_session(TENANT_A) as session:
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert session.scalar(text("SELECT count(*) FROM creative_angle_sets")) == 0
        assert session.scalar(text("SELECT count(*) FROM creative_angles")) == 0
    assert repo.get_set(tenant_id=TENANT_A, set_id=set_id) is not None


@pytest.mark.parametrize("table", ["creative_angle_sets", "creative_angles"])
def test_the_app_role_cannot_delete_a_set_or_an_angle(
    seeded: tuple[UUID, UUID], table: str
) -> None:
    with pytest.raises(DBAPIError) as exc:
        with tenant_session(TENANT_A) as session:
            session.execute(text(f"DELETE FROM {table} WHERE false"))
    assert "permission denied" in str(exc.value).lower()


def test_checks_refuse_an_unknown_status_and_a_repeated_position(
    seeded: tuple[UUID, UUID],
) -> None:
    brand_a, user_a = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_a, user_a)
    with pytest.raises(IntegrityError):
        repo.update_set(tenant_id=TENANT_A, set_id=set_id, status="done")
    (angle_id,) = repo.insert_angles(tenant_id=TENANT_A, set_id=set_id, angles=_angles(1))
    with pytest.raises(IntegrityError):
        repo.update_angle(tenant_id=TENANT_A, angle_id=angle_id, status="generated")
    with pytest.raises(IntegrityError):
        repo.insert_angles(tenant_id=TENANT_A, set_id=set_id, angles=_angles(1))


def test_a_product_with_a_set_cannot_be_deleted(seeded: tuple[UUID, UUID]) -> None:
    brand_a, user_a = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_a, user_a)
    record = repo.get_set(tenant_id=TENANT_A, set_id=set_id)
    assert record is not None
    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_A) as session:
            session.execute(
                text("DELETE FROM brand_products WHERE id = :id"), {"id": record.product_id}
            )


# -- 0070: the generation lock and the draft's idempotency key, against real Postgres ------


def test_two_sessions_racing_for_one_angle_reserve_it_once(seeded: tuple[UUID, UUID]) -> None:
    brand_id, user_id = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_id, user_id)
    (angle_id,) = repo.insert_angles(tenant_id=TENANT_A, set_id=set_id, angles=_angles(1))
    barrier = threading.Barrier(2)
    results: list[bool] = []

    def claim() -> None:
        barrier.wait()  # both UPDATEs leave at the same moment, each in its own session
        results.append(
            repo.reserve_angle(
                tenant_id=TENANT_A,
                angle_id=angle_id,
                from_statuses=(ANGLE_PROPOSED,),
                request_key=uuid4(),
                at=datetime.now(UTC),
            )
        )

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]
    stored = repo.get_angle(tenant_id=TENANT_A, angle_id=angle_id)
    assert stored is not None and stored.status == ANGLE_RESERVED
    assert stored.request_key is not None and stored.reserved_at is not None


def test_an_archived_set_is_not_listed(seeded: tuple[UUID, UUID]) -> None:
    """0078: «eliminar grupo» is a filter on the list, never a DELETE."""
    brand_id, user_id = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_id, user_id)
    assert set_id in {s.id for s in repo.list_sets(tenant_id=TENANT_A, brand_id=brand_id)}
    repo.update_set(tenant_id=TENANT_A, set_id=set_id, archived_at=datetime.now(UTC))
    assert set_id not in {s.id for s in repo.list_sets(tenant_id=TENANT_A, brand_id=brand_id)}
    stored = repo.get_set(tenant_id=TENANT_A, set_id=set_id)
    assert stored is not None and stored.archived_at is not None  # the row stays


def test_saved_at_round_trips_through_the_repository(seeded: tuple[UUID, UUID]) -> None:
    """0077: «guardar para después» is a timestamp beside the status, not a status."""
    brand_id, user_id = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_id, user_id)
    (angle_id,) = repo.insert_angles(tenant_id=TENANT_A, set_id=set_id, angles=_angles(1))
    repo.update_angle(tenant_id=TENANT_A, angle_id=angle_id, saved_at=datetime.now(UTC))
    stored = repo.get_angle(tenant_id=TENANT_A, angle_id=angle_id)
    assert stored is not None and stored.saved_at is not None and stored.status == ANGLE_PROPOSED
    repo.update_angle(tenant_id=TENANT_A, angle_id=angle_id, saved_at=None)
    stored = repo.get_angle(tenant_id=TENANT_A, angle_id=angle_id)
    assert stored is not None and stored.saved_at is None


def test_only_the_holder_of_the_key_settles_a_reservation(seeded: tuple[UUID, UUID]) -> None:
    brand_id, user_id = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_id, user_id)
    (angle_id,) = repo.insert_angles(tenant_id=TENANT_A, set_id=set_id, angles=_angles(1))
    key = uuid4()
    assert repo.reserve_angle(
        tenant_id=TENANT_A,
        angle_id=angle_id,
        from_statuses=(ANGLE_PROPOSED,),
        request_key=key,
        at=datetime.now(UTC),
    )
    draft_id = _draft(brand_id, user_id)
    assert not repo.settle_angle(
        tenant_id=TENANT_A, angle_id=angle_id, request_key=uuid4(), status=ANGLE_QUEUED
    )
    assert repo.settle_angle(
        tenant_id=TENANT_A,
        angle_id=angle_id,
        request_key=key,
        status=ANGLE_QUEUED,
        draft_id=draft_id,
    )
    stored = repo.get_angle(tenant_id=TENANT_A, angle_id=angle_id)
    assert stored is not None and stored.status == ANGLE_QUEUED and stored.draft_id == draft_id
    assert stored.reserved_at is None and stored.request_key == key
    # settled once: the same key cannot settle it again
    assert not repo.settle_angle(
        tenant_id=TENANT_A, angle_id=angle_id, request_key=key, status=ANGLE_QUEUED
    )


def test_the_first_campaign_claimed_stays_on_the_set(seeded: tuple[UUID, UUID]) -> None:
    from qualify_api.creative.campaigns import create_campaign

    brand_id, user_id = seeded
    repo = PostgresAngleSetRepository()
    set_id = _new_set(repo, brand_id, user_id)
    first = create_campaign(TENANT_A, brand_id, f"Variaciones {uuid4().hex[:6]}").id
    second = create_campaign(TENANT_A, brand_id, f"Variaciones {uuid4().hex[:6]}").id
    assert repo.claim_campaign(tenant_id=TENANT_A, set_id=set_id, campaign_id=first) == first
    assert repo.claim_campaign(tenant_id=TENANT_A, set_id=set_id, campaign_id=second) == first
    record = repo.get_set(tenant_id=TENANT_A, set_id=set_id)
    assert record is not None and record.campaign_id == first


def test_the_set_stores_the_brand_kit_fingerprint(seeded: tuple[UUID, UUID]) -> None:
    brand_id, user_id = seeded
    repo = PostgresAngleSetRepository()
    set_id = repo.insert_set(
        AngleSetWrite(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            product_id=_product(brand_id),
            preset_key="escena_producto",
            requested_count=3,
            product_name="Shawarma mixto",
            price_label="$ 18.000",
            price_missing=False,
            created_by=user_id,
            brand_kit_fingerprint="0123456789abcdef",
        )
    )
    record = repo.get_set(tenant_id=TENANT_A, set_id=set_id)
    assert record is not None and record.brand_kit_fingerprint == "0123456789abcdef"


def _keyed_draft(brand_id: UUID, user_id: UUID, key: UUID | None) -> UUID:
    with tenant_session(TENANT_A) as session:
        brief = ContentBrief(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            objective="sale",
            topic="shawarma mixto",
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
            tenant_id=TENANT_A,
            brand_id=brand_id,
            brief_id=brief.id,
            status=DRAFTING,
            pipeline_version="creative-v2",
            request_key=key,
        )
        session.add(draft)
        session.flush()
        return draft.id


def test_a_request_key_is_unique_per_tenant_and_null_is_free(seeded: tuple[UUID, UUID]) -> None:
    brand_id, user_id = seeded
    key = uuid4()
    _keyed_draft(brand_id, user_id, key)
    with pytest.raises(IntegrityError):
        _keyed_draft(brand_id, user_id, key)
    # drafts without a key (every other caller) are never constrained
    _keyed_draft(brand_id, user_id, None)
    _keyed_draft(brand_id, user_id, None)


def test_the_content_repository_answers_a_repeated_key_with_the_existing_draft(
    seeded: tuple[UUID, UUID],
) -> None:
    from qualify_creative.angles import AngleProduct, angle_brief, preset_by_key

    from qualify_api.creative.service import DuplicateDraftRequest, PostgresContentRepository

    brand_id, user_id = seeded
    brief = angle_brief(
        angle=_angles(1)[0],
        preset=preset_by_key("escena_producto"),
        product=AngleProduct(
            product_id=uuid4(),
            name="Shawarma mixto",
            price_label="$ 18.000",
            photo_keys=(f"uploads/{TENANT_A}/p1.jpg",),
        ),
        brand_id=brand_id,
    )
    repo = PostgresContentRepository()
    key = uuid4()
    first = repo.insert_brief_and_draft(
        tenant_id=TENANT_A,
        user_id=user_id,
        brief=brief,
        voice_profile_version=1,
        pipeline_version="creative-v2",
        request_key=key,
    )
    assert repo.draft_id_for_request(tenant_id=TENANT_A, request_key=key) == first
    with pytest.raises(DuplicateDraftRequest) as duplicate:
        repo.insert_brief_and_draft(
            tenant_id=TENANT_A,
            user_id=user_id,
            brief=brief,
            voice_profile_version=1,
            pipeline_version="creative-v2",
            request_key=key,
        )
    assert duplicate.value.draft_id == first
    # the losing insert rolled back whole: no orphan brief nor second draft
    with tenant_session(TENANT_A) as session:
        keyed = session.scalars(select(ContentDraft).where(ContentDraft.request_key == key)).all()
        assert [d.id for d in keyed] == [first]
    # another tenant never sees this key
    assert repo.draft_id_for_request(tenant_id=TENANT_B, request_key=key) is None
