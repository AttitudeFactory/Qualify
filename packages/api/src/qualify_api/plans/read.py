"""The request path's view of a business's plan (m-24852145): `business_plans`, under
the tenant's RLS, read-only. Never imports `admin_session`; never reads a subscription
row, a price or a cap the owner should not see (ADR 43 §2.8).

No row = the catalog's default plan, Básico (D15: every subscription starts in Básico).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.plans.catalog import Plan, PlansCatalog, UnknownPlan, load_plans
from qualify_api.plans.models import BusinessPlan
from qualify_api.plans.schedule import PlanSchedule


def schedule_in_session(session: Session, tenant_id: UUID) -> PlanSchedule | None:
    """The business's projection, inside the caller's transaction (the ledger's lock)."""
    row = session.scalar(select(BusinessPlan).where(BusinessPlan.tenant_id == tenant_id))
    if row is None:
        return None
    return PlanSchedule(
        plan_code=row.plan_code, next_plan_code=row.next_plan_code, next_from=row.next_plan_from
    )


def plan_from_schedule(
    schedule: PlanSchedule | None, period: date, catalog: PlansCatalog | None = None
) -> Plan:
    plans = catalog or load_plans()
    if schedule is None:
        return plans.default
    try:
        return plans.get(schedule.code_at(period))
    except UnknownPlan:
        # a code a newer catalog defined but this process does not know: never more
        # than the default, never an error on the owner's screen
        return plans.default


def plan_in_session(
    session: Session, tenant_id: UUID, period: date, catalog: PlansCatalog | None = None
) -> Plan:
    return plan_from_schedule(schedule_in_session(session, tenant_id), period, catalog)


def business_plan(tenant_id: UUID, period: date, catalog: PlansCatalog | None = None) -> Plan:
    """The plan in force for the business in `period` (blocking: off the event loop)."""
    with tenant_session(tenant_id) as session:
        return plan_in_session(session, tenant_id, period, catalog)


__all__ = ["business_plan", "plan_from_schedule", "plan_in_session", "schedule_in_session"]
