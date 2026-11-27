"""`db`-marked tests of «Sugerir con IA» the line of a character's scene (m-25129386,
migration 0192) against Postgres: the new `subject_key` column and its index, the
reservation with the brand's spend, the settle and the void, the caps (10 a scene, 30 a
business, per day of the business) under the advisory locks across connections, the
repeated tap, and RLS keeping every row and read to its own business.

Every test makes its own business (`uuid4()`): no deletes, no shared state. No model is
called."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text

from qualify_api.catalog.models import BrandProduct
from qualify_api.creative import character_line_ai as cl
from qualify_api.creative import models as orm
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

BOUND = cl.LINE_MAX_USD


def _business(*, cap: str | None = None, hard_stop: bool = True) -> tuple[UUID, UUID]:
    tenant = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name=f"m25129386-{tenant.hex[:6]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        brand = Brand(tenant_id=tenant, name=f"m25129386-{tenant.hex[:6]}")
        session.add(brand)
        session.flush()
        brand_id = brand.id
    if cap is not None:
        with tenant_session(tenant) as session:
            session.add(
                orm.CreativeEngineConfig(
                    tenant_id=tenant,
                    brand_id=brand_id,
                    monthly_budget_cap_usd=Decimal(cap),
                    budget_spent_usd=Decimal("1.000000"),
                    hard_stop_on_cap=hard_stop,
                )
            )
    return tenant, brand_id


def _reserve(tenant: UUID, brand: UUID, scene: UUID, tap: str | None = None) -> cl.Reservation:
    return cl.PostgresLineLedger().reserve(
        tenant_id=tenant,
        brand_id=brand,
        scene_key=scene,
        event_id=cl.usage_event_id(tenant, scene, tap or str(uuid4())),
        bound_usd=BOUND,
        now=datetime.now(UTC),
    )


def _spent(tenant: UUID, brand: UUID) -> Decimal:
    with tenant_session(tenant) as session:
        return Decimal(
            session.scalar(
                select(orm.CreativeEngineConfig.budget_spent_usd).where(
                    orm.CreativeEngineConfig.brand_id == brand
                )
            )
        )


def _row(tenant: UUID, event_id: UUID) -> orm.CreativeUsageEvent | None:
    with tenant_session(tenant) as session:
        row = session.get(orm.CreativeUsageEvent, event_id)
        if row is not None:
            session.expunge(row)
        return row


def _refused(tenant: UUID, brand: UUID, scene: UUID, tap: str | None = None) -> str:
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _reserve(tenant, brand, scene, tap)
    return refused.value.code


# -- the schema ------------------------------------------------------------------------------


def test_the_column_and_its_index_exist_and_rls_is_still_forced() -> None:
    with admin_session() as session:
        column = session.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'creative_usage_events' AND column_name = 'subject_key'"
            )
        ).one()
        index = session.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_usage_event_tenant_unit_subject'"
            )
        )
        forced = session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'creative_usage_events'"
            )
        ).one()
    assert tuple(column) == ("uuid", "YES")
    assert "(tenant_id, unit, subject_key, created_at)" in index
    assert "subject_key IS NOT NULL" in index
    assert tuple(forced) == (True, True)


# -- the reservation, the settle and the void -------------------------------------------------


def test_reserve_settle_and_void_keep_the_row_and_the_brand_spend_in_step() -> None:
    tenant, brand = _business(cap="10.00")
    scene = uuid4()
    ledger = cl.PostgresLineLedger()
    got = _reserve(tenant, brand, scene, "tap-1")
    assert got.left_today == 9
    row = _row(tenant, got.event_id)
    assert row is not None
    assert (row.unit, row.subject_key, row.provider, row.draft_id) == (
        "character_line",
        scene,
        "anthropic",
        None,
    )
    assert Decimal(row.cost_usd) == BOUND and row.model_id == "claude-haiku-5-5"
    assert _spent(tenant, brand) == Decimal("1.01")
    for _ in range(2):  # idempotent
        ledger.settle(
            tenant_id=tenant,
            brand_id=brand,
            event_id=got.event_id,
            cost_usd=Decimal("0.000112"),
            input_tokens=820,
            output_tokens=60,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model_id="claude-haiku-5-5",
        )
    row = _row(tenant, got.event_id)
    assert row is not None and Decimal(row.cost_usd) == Decimal("0.000112")
    assert (row.input_tokens, row.output_tokens) == (820, 60)
    # `budget_spent_usd` is numeric(10,2) in the database (0009): the brand's spend keeps
    # cents, so a sub-cent call rounds away there; the event row (numeric(12,6)) is exact
    assert _spent(tenant, brand) == Decimal("1.00")
    # a second tap that billed nothing: voided, its dollars back, not counted
    other = _reserve(tenant, brand, scene, "tap-2")
    assert other.left_today == 8
    for _ in range(2):  # idempotent
        ledger.release(tenant_id=tenant, brand_id=brand, event_id=other.event_id)
    voided = _row(tenant, other.event_id)
    assert voided is not None
    assert (voided.unit, Decimal(voided.cost_usd)) == ("character_line_released", Decimal(0))
    assert _spent(tenant, brand) == Decimal("1.00")
    # the same tap may ask again once it was given back; a third tap sees 2 used
    assert _reserve(tenant, brand, scene, "tap-2").left_today == 8
    assert _reserve(tenant, brand, scene).left_today == 7


def test_a_repeated_tap_is_refused_and_writes_nothing() -> None:
    tenant, brand = _business()
    scene = uuid4()
    _reserve(tenant, brand, scene, "tap")
    assert _refused(tenant, brand, scene, "tap") == cl.SUGGESTION_REPEATED
    with tenant_session(tenant) as session:
        assert session.scalar(select(func.count()).select_from(orm.CreativeUsageEvent)) == 1


def test_the_brand_hard_cap_refuses_and_a_soft_one_does_not() -> None:
    tenant, brand = _business(cap="1.00")  # 1.00 spent: nothing left for a reservation
    assert _refused(tenant, brand, uuid4()) == cl.LINE_BUDGET_CAP
    assert _spent(tenant, brand) == Decimal("1.0")
    tenant, brand = _business(cap="1.00", hard_stop=False)
    assert _reserve(tenant, brand, uuid4()).left_today == 9


# -- the caps --------------------------------------------------------------------------------


def test_ten_a_scene_per_day_of_the_business() -> None:
    tenant, brand = _business()
    scene = uuid4()
    left = [_reserve(tenant, brand, scene).left_today for _ in range(10)]
    assert left == [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    assert _refused(tenant, brand, scene) == cl.LINE_DAILY_CAP
    assert _reserve(tenant, brand, uuid4()).left_today == 9  # another scene
    # yesterday's (in the business's own day) do not count
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE creative_usage_events SET created_at = created_at - interval '2 days' "
                "WHERE subject_key = :s"
            ),
            {"s": scene},
        )
    assert _reserve(tenant, brand, scene).left_today == 9


def test_thirty_a_business_whatever_the_scene_keys() -> None:
    tenant, brand = _business()
    for _ in range(30):
        _reserve(tenant, brand, uuid4())
    assert _refused(tenant, brand, uuid4()) == cl.LINE_BUSINESS_DAILY_CAP


def test_two_taps_for_the_last_place_take_it_once() -> None:
    """The count and the insert are one step under the locks, across connections."""
    tenant, brand = _business()
    scene = uuid4()
    for _ in range(9):
        _reserve(tenant, brand, scene)
    outcomes: list[str] = []
    start = threading.Barrier(2)

    def run() -> None:
        start.wait()
        try:
            _reserve(tenant, brand, scene)
            outcomes.append("ok")
        except cl.CharacterLineRefused as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(outcomes) == [cl.LINE_DAILY_CAP, "ok"]


# -- RLS -------------------------------------------------------------------------------------


def test_another_business_neither_sees_nor_shares_the_rows() -> None:
    tenant, brand = _business()
    other, other_brand = _business()
    scene = uuid4()
    for _ in range(10):
        _reserve(tenant, brand, scene)
    with tenant_session(other) as session:
        seen = session.scalar(
            select(func.count())
            .select_from(orm.CreativeUsageEvent)
            .where(orm.CreativeUsageEvent.subject_key == scene)
        )
    assert seen == 0
    # the same scene key in another business has its own 10
    assert _reserve(other, other_brand, scene).left_today == 9


def test_the_reads_only_see_this_brands_active_product() -> None:
    tenant, brand = _business()
    other, other_brand = _business()
    with tenant_session(tenant) as session:
        product = BrandProduct(
            tenant_id=tenant,
            brand_id=brand,
            name="Copa de mango",
            slug=f"copa-{uuid4().hex[:6]}",
            description="Mango fresco con crema.",
            category="Helados",
            price_amount=Decimal("9000"),
            price_currency="COP",
        )
        hidden = BrandProduct(
            tenant_id=tenant,
            brand_id=brand,
            name="Retirado",
            slug=f"retirado-{uuid4().hex[:6]}",
            is_active=False,
        )
        session.add_all([product, hidden])
        session.flush()
        product_id, hidden_id = product.id, hidden.id
    reads = cl.PostgresLineReads()
    got = reads.product(tenant_id=tenant, brand_id=brand, product_id=product_id)
    assert got == cl.LineProduct(
        name="Copa de mango", category="Helados", description="Mango fresco con crema."
    )
    assert reads.product(tenant_id=tenant, brand_id=brand, product_id=hidden_id) is None
    assert reads.product(tenant_id=other, brand_id=other_brand, product_id=product_id) is None
    assert reads.product(tenant_id=tenant, brand_id=other_brand, product_id=product_id) is None
    assert reads.character(tenant_id=tenant, brand_id=brand, character_id=uuid4()) is None
