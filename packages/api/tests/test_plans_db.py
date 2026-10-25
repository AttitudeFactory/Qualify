"""`db`-marked tests for plans on the subscription (0093, m-24852145): `set_plan` and its
history, the ledger reading the plan, the isolation of the subscription tables from the
request path (GRANT, ADR 43 §2.8) and of `business_plans` between tenants (RLS), the
USD-cap alert (once per subscription and month, never a pause), and the team report.

The root `conftest.py` migrates the test database to head before any `db` test runs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import CreationPrice
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from qualify_api.creative.creations import PostgresCreationsLedger
from qualify_api.creative.models import CreativeUsageEvent
from qualify_api.plans import report
from qualify_api.plans.cost_alerts import run_cost_alerts
from qualify_api.plans.models import BusinessPlan
from qualify_api.plans.notify import RecordingTeamNotifier
from qualify_api.plans.read import business_plan
from qualify_api.plans.schedule import PlanChangeRefused
from qualify_api.plans.service import plan_history, set_plan
from qualify_api.support.service import create_support_request
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)


def _now(day: int = 15, month: int = 10) -> datetime:
    return datetime(2026, month, day, 15, tzinfo=UTC)


def _tenant() -> tuple[UUID, UUID]:
    """A fresh tenant with one brand (each test owns its subscription)."""
    with admin_session() as session:
        tenant = Tenant(
            name=f"plans-{uuid4().hex[:6]}",
            country="CO",
            timezone="America/Bogota",
            currency="COP",
        )
        session.add(tenant)
        session.flush()
        brand = Brand(tenant_id=tenant.id, name="plans-brand")
        session.add(brand)
        session.flush()
        return tenant.id, brand.id


def _set(tenant: UUID, plan: str, now: datetime, **kw: object):  # noqa: ANN202
    return set_plan(
        tenant_id=tenant,
        plan_code=plan,
        reason=kw.pop("reason", "prueba"),
        assigned_by="equipo@attitudefactory.co",
        now=now,
        notifier=RecordingTeamNotifier(),
        **kw,
    )


def test_a_business_without_a_plan_is_basico() -> None:
    tenant, brand = _tenant()
    assert business_plan(tenant, OCT).code == "basico"
    balance = PostgresCreationsLedger().balance(tenant_id=tenant, brand_id=brand)
    assert (balance.quota, balance.video_quota, balance.preview_quota) == (30, 4, 20)


def test_set_plan_records_history_and_the_ledger_reads_it() -> None:
    tenant, brand = _tenant()
    notifier = RecordingTeamNotifier()
    result = set_plan(
        tenant_id=tenant,
        plan_code="plus",
        reason="Pidió más videos",
        assigned_by="herwin@attitudefactory.co",
        notifier=notifier,
    )
    assert result.changed and result.previous_plan_code is None and result.businesses == 1
    assert "Plus" in notifier.sent[0] and "Pidió más videos" in notifier.sent[0]
    balance = PostgresCreationsLedger().balance(tenant_id=tenant, brand_id=brand)
    assert (balance.quota, balance.video_quota, balance.preview_quota) == (60, 8, 40)
    subscription, rows = plan_history(tenant)
    assert subscription == result.subscription_id
    assert [(r.previous_plan_code, r.plan_code, r.reason, r.assigned_by) for r in rows] == [
        (None, "plus", "Pidió más videos", "herwin@attitudefactory.co")
    ]
    assert rows[0].plans_version == "planes-v1" and rows[0].prices_version == "precios-planes-v1"


def test_the_charge_records_the_plans_quota_as_provenance() -> None:
    tenant, brand = _tenant()
    set_plan(
        tenant_id=tenant,
        plan_code="pro",
        reason="r",
        assigned_by="e",
        notifier=RecordingTeamNotifier(),
    )
    draft = uuid4()
    PostgresCreationsLedger().charge(
        tenant_id=tenant,
        brand_id=brand,
        draft_id=draft,
        revision=1,
        price=CreationPrice("image", 1),
    )
    with tenant_session(tenant) as session:
        quota = session.scalar(
            text("SELECT monthly_quota FROM creation_charges WHERE draft_id = :d"), {"d": draft}
        )
    assert quota == 120


def test_rerunning_the_same_change_is_a_no_op() -> None:
    tenant, _ = _tenant()
    assert _set(tenant, "plus", _now(3)).changed
    assert not _set(tenant, "plus", _now(4)).changed
    assert _set(tenant, "basico", _now(10)).effective_month == NOV
    assert not _set(tenant, "basico", _now(11)).changed
    assert len(plan_history(tenant)[1]) == 2


def test_a_downgrade_waits_for_next_month_and_the_business_sees_it_then() -> None:
    tenant, _ = _tenant()
    _set(tenant, "pro", _now(2))
    result = _set(tenant, "basico", _now(20))
    assert (result.previous_plan_code, result.effective_month) == ("pro", NOV)
    with admin_session() as session:
        row = session.get(BusinessPlan, tenant)
        assert (row.plan_code, row.next_plan_code, row.next_plan_from) == ("pro", "basico", NOV)
    assert business_plan(tenant, OCT).code == "pro"
    assert business_plan(tenant, NOV).code == "basico"
    with pytest.raises(PlanChangeRefused):
        _set(tenant, "plus", _now(21), requested_from=date(2026, 12, 1))


def test_an_upgrade_counts_what_was_used_against_the_new_plan() -> None:
    tenant, brand = _tenant()
    ledger = PostgresCreationsLedger()
    for _ in range(20):
        ledger.charge(
            tenant_id=tenant,
            brand_id=brand,
            draft_id=uuid4(),
            revision=1,
            price=CreationPrice("image", 1),
        )
    assert ledger.balance(tenant_id=tenant, brand_id=brand).left == 10
    set_plan(
        tenant_id=tenant,
        plan_code="plus",
        reason="r",
        assigned_by="e",
        notifier=RecordingTeamNotifier(),
    )
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.left, balance.quota) == (40, 60)


def test_set_plan_aligns_the_engine_brake_with_the_plan_and_never_hard_stops() -> None:
    tenant, brand = _tenant()
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO creative_engine_config (tenant_id, brand_id, monthly_budget_cap_usd,"
                " hard_stop_on_cap) VALUES (:t, :b, 10, true)"
            ),
            {"t": tenant, "b": brand},
        )
    _set(tenant, "plus", _now())
    with admin_session() as session:
        cap, hard = session.execute(
            text(
                "SELECT monthly_budget_cap_usd, hard_stop_on_cap FROM creative_engine_config "
                "WHERE tenant_id = :t"
            ),
            {"t": tenant},
        ).one()
    assert (Decimal(cap), hard) == (Decimal(240), False)


# --- isolation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table", ["subscriptions", "subscription_plan_assignments", "subscription_cost_alerts"]
)
def test_the_request_path_cannot_read_the_subscription_tables(table: str) -> None:
    tenant, _ = _tenant()
    _set(tenant, "plus", _now())
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(tenant) as session:
            session.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def test_the_owner_reads_only_their_own_plan_and_cannot_change_it() -> None:
    a, _ = _tenant()
    b, _ = _tenant()
    _set(a, "pro", _now())
    _set(b, "plus", _now())
    with tenant_session(a) as session:
        rows = session.scalars(select(BusinessPlan.plan_code)).all()
    assert rows == ["pro"]
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(a) as session:
            session.execute(text("UPDATE business_plans SET plan_code = 'pro'"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(b) as session:
            session.execute(
                text(
                    "INSERT INTO business_plans (tenant_id, subscription_id, plan_code, "
                    "plans_version, assignment_id) SELECT :t, gen_random_uuid(), 'pro', "
                    "'planes-v1', gen_random_uuid()"
                ),
                {"t": b},
            )


def test_the_owner_cannot_move_their_business_to_another_subscription() -> None:
    tenant, _ = _tenant()
    _set(tenant, "basico", _now())
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE tenants SET subscription_id = NULL WHERE id = :t"), {"t": tenant}
            )
    with tenant_session(tenant) as session:  # what the owner may edit still works
        session.execute(text("UPDATE tenants SET country = 'UY' WHERE id = :t"), {"t": tenant})


def test_business_plans_with_an_empty_tenant_guc_sees_nothing(app_engine) -> None:  # noqa: ANN001
    tenant, _ = _tenant()
    _set(tenant, "plus", _now())
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert conn.execute(text("SELECT count(*) FROM business_plans")).scalar() == 0


# --- the USD cap: an alert, once, never a pause ----------------------------------------------


def _spend(tenant: UUID, brand: UUID, usd: str, when: datetime) -> None:
    with tenant_session(tenant) as session:
        session.add(
            CreativeUsageEvent(
                tenant_id=tenant,
                brand_id=brand,
                provider="byteplus",
                model_id="test",
                unit="piece",
                pieces=1,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                cost_usd=Decimal(usd),
                paid_by="platform",
                pricing_table_version="v7",
                occurred_at=when,
            )
        )


def test_crossing_the_cap_alerts_once_per_month_and_pauses_nothing() -> None:
    tenant, brand = _tenant()
    _set(tenant, "basico", _now(1))
    _spend(tenant, brand, "119.50", _now(5))
    notifier = RecordingTeamNotifier()
    (check,) = run_cost_alerts(now=_now(6), tenant_ids=[tenant], notifier=notifier)
    assert not check.crossed and notifier.sent == []
    _spend(tenant, brand, "1.00", _now(7))
    (check,) = run_cost_alerts(now=_now(8), tenant_ids=[tenant], notifier=notifier)
    assert check.crossed and check.notified and check.cap_usd == Decimal(120)
    run_cost_alerts(now=_now(9), tenant_ids=[tenant], notifier=notifier)
    assert len(notifier.sent) == 1 and "no se pausó nada" in notifier.sent[0]
    # nothing paused: the business keeps creating within its plan
    assert PostgresCreationsLedger().charge(
        tenant_id=tenant,
        brand_id=brand,
        draft_id=uuid4(),
        revision=1,
        price=CreationPrice("image", 1),
    )


def test_a_channel_that_is_down_is_retried_on_the_next_run() -> None:
    tenant, brand = _tenant()
    _spend(tenant, brand, "130", _now(5))
    down = RecordingTeamNotifier(accept=False)
    (first,) = run_cost_alerts(now=_now(6), tenant_ids=[tenant], notifier=down)
    assert first.crossed and not first.notified
    up = RecordingTeamNotifier()
    (second,) = run_cost_alerts(now=_now(7), tenant_ids=[tenant], notifier=up)
    assert second.notified and len(up.sent) == 1


def test_the_cap_follows_the_plan() -> None:
    tenant, brand = _tenant()
    _set(tenant, "pro", _now(1))
    _spend(tenant, brand, "300", _now(5))
    (check,) = run_cost_alerts(now=_now(6), tenant_ids=[tenant], notifier=RecordingTeamNotifier())
    assert (check.plan_code, check.cap_usd, check.crossed) == ("pro", Decimal(480), False)


# --- the team report -----------------------------------------------------------------------


def test_the_report_charges_plus_75_then_149_against_the_real_cost() -> None:
    tenant, brand = _tenant()
    _set(tenant, "plus", _now(3))
    _spend(tenant, brand, "12.5", _now(9))
    (october,) = report.fetch(OCT, tenant)
    assert october.charged_usd == Decimal(75) and october.cost_usd == Decimal("12.5")
    assert october.prices_versions == "precios-planes-v1"
    (november,) = report.fetch(NOV, tenant)
    assert november.charged_usd == Decimal(149) and november.cost_usd == Decimal(0)


def test_more_creations_is_a_support_topic() -> None:
    tenant, _ = _tenant()

    class _Quiet:
        def notify(self, notification: object) -> bool:
            return False

    ticket = create_support_request(
        tenant_id=tenant,
        topic="more_creations",
        contact_email="dueno@negocio.co",
        context={"screen": "settings", "plan": "basico"},
        notifier=_Quiet(),
    )
    with tenant_session(tenant) as session:
        topic = session.scalar(
            text("SELECT topic FROM support_requests WHERE id = :id"), {"id": ticket.id}
        )
    assert topic == "more_creations"


def test_a_missing_tenant_is_refused() -> None:
    from qualify_api.plans.service import TenantNotFound

    with pytest.raises((TenantNotFound, DBAPIError)):
        _set(uuid4(), "plus", _now())
