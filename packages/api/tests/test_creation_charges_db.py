"""`db`-marked tests for `creation_charges` (0088, CREAR-5 m-24848531) through
`PostgresCreationsLedger`: the month's 4 generated videos apart from the 30 creations
(founder, 2026-10-24), the per-video refund of a failed 1080p final, idempotency by
(`draft_id`, `revision`), the CHECKs, and RLS isolation (also with an empty
`app.tenant_id` — the NULLIF).

The root `conftest.py` migrates the test database to head before any `db` test runs."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import CreationPrice
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from qualify_api.creative.creations import CHARGED, NotEnoughCreations, PostgresCreationsLedger
from qualify_api.creative.models import CreationCharge
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

# Distinct from the tenants of the other schema-test modules so suites stay independent.
TENANT_A = UUID("a0000000-0000-4000-8000-000000000881")
TENANT_B = UUID("b0000000-0000-4000-8000-000000000882")

CLIP = CreationPrice("generated_video", 0, videos=1)


def _brand(tenant_id: UUID) -> UUID:
    """A fresh brand (so each test starts on an empty month), its tenant created once."""
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"creations-{str(tenant_id)[:1]}",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        brand = Brand(tenant_id=tenant_id, name=f"creations-brand-{uuid4()}")
        session.add(brand)
        session.flush()
        return brand.id


def _charge(ledger: PostgresCreationsLedger, brand: UUID, price: CreationPrice) -> UUID:
    draft = uuid4()
    assert ledger.charge(
        tenant_id=TENANT_A, brand_id=brand, draft_id=draft, revision=1, price=price
    )
    return draft


def test_four_videos_then_blocked_and_the_creations_untouched() -> None:
    ledger = PostgresCreationsLedger()
    brand = _brand(TENANT_A)
    drafts = [_charge(ledger, brand, CLIP) for _ in range(4)]
    balance = ledger.balance(tenant_id=TENANT_A, brand_id=brand)
    assert (balance.left, balance.videos_left, balance.video_quota) == (30, 0, 4)
    with pytest.raises(NotEnoughCreations) as refused:
        _charge(ledger, brand, CLIP)
    assert (refused.value.missing, refused.value.missing_videos) == (0, 1)
    # the same generation is never charged twice
    assert not ledger.charge(
        tenant_id=TENANT_A, brand_id=brand, draft_id=drafts[0], revision=1, price=CLIP
    )
    # an image still goes through: creations and videos are apart
    _charge(ledger, brand, CreationPrice("image", 1))
    assert ledger.balance(tenant_id=TENANT_A, brand_id=brand).left == 29
    with tenant_session(TENANT_A) as session:
        row = session.scalar(select(CreationCharge).where(CreationCharge.draft_id == drafts[0]))
        assert row is not None
        assert (row.videos, row.weight, row.monthly_video_quota, row.monthly_quota) == (1, 0, 4, 30)
        assert (row.weights_version, row.pricing_table_version) == ("pesos-creaciones-v2", "v7")
        assert row.final_refunded_assets == []


def test_a_failed_final_gives_back_one_video_per_asset_once() -> None:
    ledger = PostgresCreationsLedger()
    brand = _brand(TENANT_A)
    draft = _charge(ledger, brand, CreationPrice("carousel", 1, videos=2))
    first, second = uuid4(), uuid4()
    assert ledger.refund_final(
        tenant_id=TENANT_A, draft_id=draft, revision=1, reason="ModelArk falló.", asset_ids=(first,)
    )
    assert not ledger.refund_final(
        tenant_id=TENANT_A, draft_id=draft, revision=1, reason="again", asset_ids=(first,)
    )
    balance = ledger.balance(tenant_id=TENANT_A, brand_id=brand)
    assert (balance.left, balance.videos_left) == (29, 3)
    assert ledger.refund_final(
        tenant_id=TENANT_A, draft_id=draft, revision=1, reason="x", asset_ids=(second, uuid4())
    )
    assert ledger.balance(tenant_id=TENANT_A, brand_id=brand).videos_left == 4
    with tenant_session(TENANT_A) as session:
        row = session.scalar(select(CreationCharge).where(CreationCharge.draft_id == draft))
        assert row is not None and row.status == CHARGED
        assert row.final_refunded_assets == [first, second]
        assert row.final_refunded_at is not None and row.final_refund_reason == "x"


def test_more_refunded_finals_than_videos_is_refused_by_the_database() -> None:
    ledger = PostgresCreationsLedger()
    brand = _brand(TENANT_A)
    draft = _charge(ledger, brand, CLIP)
    with pytest.raises(IntegrityError), tenant_session(TENANT_A) as session:
        session.execute(
            update(CreationCharge)
            .where(CreationCharge.draft_id == draft)
            .values(final_refunded_assets=[uuid4(), uuid4()], final_refunded_at=text("now()"))
        )


def test_another_tenant_never_sees_the_charges() -> None:
    ledger = PostgresCreationsLedger()
    brand = _brand(TENANT_A)
    draft = _charge(ledger, brand, CLIP)
    _brand(TENANT_B)
    with tenant_session(TENANT_B) as session:
        assert (
            session.scalar(select(CreationCharge).where(CreationCharge.draft_id == draft)) is None
        )
    # nor a session with no tenant at all (the NULLIF)
    with tenant_session(TENANT_A) as session:
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert (
            session.scalar(select(CreationCharge).where(CreationCharge.draft_id == draft)) is None
        )
