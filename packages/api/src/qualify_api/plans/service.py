"""The team's write path for plans (m-24852145): assign a plan to a business's
subscription, read the history. Only through `admin_session`, only from the team's CLI
(`just set-plan`, `just plans`) — and, later, the Meegle Alta (m-24852131). Never the
request path: the owner cannot change their plan nor read its history (ADR 43 §2.8).

`set_plan`, in ONE transaction:

1. locks the tenant row, creates its subscription when it has none (1:1, ADR 43 §2.8),
   and locks the subscription row — two assignments at once are serialized;
2. reads the subscription's history and decides when the change applies
   (`schedule.effective_month_for`: upgrade now, downgrade next month);
3. appends the assignment (`INSERT … ON CONFLICT (idempotency_key) DO NOTHING`);
4. rewrites `business_plans` — the projection every business of the subscription reads;
5. aligns the brands' dollar safety net of `creative_engine_config` with the plan (D18,
   principal-architect 2026-10-24): `monthly_budget_cap_usd` = the plan's USD cap and
   `hard_stop_on_cap = false`, so the cap only alerts and never stops what was paid for.

Then it tells the team channel. Re-running the same command is a no-op.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from qualify_shared.db.admin import admin_session
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.plans.catalog import (
    PLANS_VERSION,
    PRICES_VERSION,
    PlansCatalog,
    load_plans,
)
from qualify_api.plans.models import BusinessPlan, Subscription, SubscriptionPlanAssignment
from qualify_api.plans.notify import TeamNotifier, production_team_notifier
from qualify_api.plans.schedule import (
    Assignment,
    PlanChangeRefused,
    check_pending,
    effective_month_for,
    month_of,
    pending_months,
    plan_code_at,
    schedule_for,
)

SOURCES = ("manual", "meegle_alta", "support_request")


class TenantNotFound(LookupError):
    pass


@dataclass(frozen=True)
class SetPlanResult:
    subscription_id: UUID
    plan_code: str
    previous_plan_code: str | None
    effective_month: date
    #: False when nothing was written (already on that plan / already scheduled).
    changed: bool
    assignment_id: UUID | None = None
    businesses: int = 0


@dataclass(frozen=True)
class HistoryRow:
    assigned_at: datetime
    plan_code: str
    previous_plan_code: str | None
    effective_month: date
    source: str
    reason: str
    assigned_by: str
    plans_version: str
    prices_version: str


def ensure_subscription(session: Session, tenant_id: UUID) -> UUID:
    """The tenant's subscription id, creating a 1:1 one when it has none. Locks the
    tenant row (admin session, inside the caller's transaction)."""
    row = session.execute(
        text("SELECT name, subscription_id FROM tenants WHERE id = :id FOR UPDATE"),
        {"id": tenant_id},
    ).one_or_none()
    if row is None:
        raise TenantNotFound(f"no tenant {tenant_id}")
    if row.subscription_id is not None:
        return row.subscription_id
    subscription = Subscription(display_name=row.name)
    session.add(subscription)
    session.flush()
    session.execute(
        text("UPDATE tenants SET subscription_id = :sid WHERE id = :id"),
        {"sid": subscription.id, "id": tenant_id},
    )
    return subscription.id


def _history(session: Session, subscription_id: UUID) -> list[SubscriptionPlanAssignment]:
    return list(
        session.scalars(
            select(SubscriptionPlanAssignment)
            .where(SubscriptionPlanAssignment.subscription_id == subscription_id)
            .order_by(SubscriptionPlanAssignment.assigned_at, SubscriptionPlanAssignment.id)
        )
    )


def _assignments(rows: Sequence[SubscriptionPlanAssignment]) -> list[Assignment]:
    return [
        Assignment(
            plan_code=r.plan_code,
            effective_month=r.effective_month,
            assigned_at=r.assigned_at,
            plans_version=r.plans_version,
            prices_version=r.prices_version,
            id=r.id,
        )
        for r in rows
    ]


def subscription_tenants(session: Session, subscription_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            text("SELECT id FROM tenants WHERE subscription_id = :sid ORDER BY created_at"),
            {"sid": subscription_id},
        )
    )


def _project(
    session: Session,
    subscription_id: UUID,
    history: list[Assignment],
    now_month: date,
    catalog: PlansCatalog,
) -> int:
    """Rewrite `business_plans` for every business of the subscription."""
    schedule = schedule_for(history, now_month, catalog)
    last = max(history, key=lambda a: a.assigned_at)
    tenants = subscription_tenants(session, subscription_id)
    for tenant_id in tenants:
        values = {
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "plan_code": schedule.plan_code,
            "plans_version": catalog.version,
            "next_plan_code": schedule.next_plan_code,
            "next_plan_from": schedule.next_from,
            "assignment_id": last.id,
        }
        statement = insert(BusinessPlan).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[BusinessPlan.tenant_id],
                set_={
                    **{k: statement.excluded[k] for k in values if k != "tenant_id"},
                    "updated_at": text("now()"),
                },
            )
        )
        cap = catalog.get(schedule.plan_code).usd_alert_cap
        session.execute(
            text(
                "UPDATE creative_engine_config SET monthly_budget_cap_usd = :cap, "
                "hard_stop_on_cap = false WHERE tenant_id = :tid"
            ),
            {"cap": cap, "tid": tenant_id},
        )
    return len(tenants)


def set_plan(
    *,
    tenant_id: UUID,
    plan_code: str,
    reason: str,
    assigned_by: str,
    requested_from: date | None = None,
    source: str = "manual",
    meegle_work_item_id: int | None = None,
    support_request_id: UUID | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
    catalog: PlansCatalog | None = None,
    notifier: TeamNotifier | None = None,
) -> SetPlanResult:
    plans = catalog or load_plans(PLANS_VERSION)
    new = plans.get(plan_code)
    if not reason.strip() or not assigned_by.strip():
        raise PlanChangeRefused("a plan change needs a reason and who made it")
    if source not in SOURCES:
        raise PlanChangeRefused(f"source must be one of {SOURCES}")
    moment = now or datetime.now(UTC)
    now_month = month_of(moment)
    with admin_session() as session:
        subscription_id = ensure_subscription(session, tenant_id)
        session.execute(
            text("SELECT id FROM subscriptions WHERE id = :sid FOR UPDATE"),
            {"sid": subscription_id},
        )
        rows = _history(session, subscription_id)
        history = _assignments(rows)
        current_code = plan_code_at(history, now_month, plans.default_code)
        if history:
            effective = effective_month_for(
                current=plans.get(current_code),
                new=new,
                now_month=now_month,
                requested=requested_from,
            )
            already = plan_code_at(history, effective, plans.default_code) == new.code
            if already and (effective > now_month or not pending_months(history, now_month)):
                return SetPlanResult(
                    subscription_id=subscription_id,
                    plan_code=new.code,
                    previous_plan_code=current_code,
                    effective_month=effective,
                    changed=False,
                )
            check_pending(history, effective, now_month)
            previous: str | None = current_code
        else:
            # the opening assignment: where billing starts; never "a downgrade"
            effective = effective_month_for(
                current=new, new=new, now_month=now_month, requested=requested_from
            )
            previous = None
        key = idempotency_key or (
            f"{source}:{subscription_id}:{len(history)}:{new.code}:{effective:%Y-%m}"
        )
        assignment_id = session.scalar(
            insert(SubscriptionPlanAssignment)
            .values(
                subscription_id=subscription_id,
                plan_code=new.code,
                previous_plan_code=previous,
                plans_version=plans.version,
                prices_version=PRICES_VERSION,
                effective_month=effective,
                source=source,
                meegle_work_item_id=meegle_work_item_id,
                support_request_id=support_request_id,
                reason=reason.strip()[:500],
                assigned_by=assigned_by.strip()[:200],
                assigned_at=moment,
                idempotency_key=key,
            )
            .on_conflict_do_nothing(constraint="uq_plan_assignments_key")
            .returning(SubscriptionPlanAssignment.id)
        )
        if assignment_id is None:
            return SetPlanResult(
                subscription_id=subscription_id,
                plan_code=new.code,
                previous_plan_code=previous,
                effective_month=effective,
                changed=False,
            )
        history.append(
            Assignment(
                plan_code=new.code,
                effective_month=effective,
                assigned_at=moment,
                plans_version=plans.version,
                prices_version=PRICES_VERSION,
                id=assignment_id,
            )
        )
        businesses = _project(session, subscription_id, history, now_month, plans)
        name = session.scalar(
            select(Subscription.display_name).where(Subscription.id == subscription_id)
        )
    result = SetPlanResult(
        subscription_id=subscription_id,
        plan_code=new.code,
        previous_plan_code=previous,
        effective_month=effective,
        changed=True,
        assignment_id=assignment_id,
        businesses=businesses,
    )
    before = plans.get(previous).name if previous else "sin plan"
    (notifier or production_team_notifier()).notify(
        f"Plan asignado · {name}: {before} → {new.name} desde {effective:%Y-%m} "
        f"({businesses} negocio(s)). Motivo: {reason.strip()[:200]} · por {assigned_by.strip()}"
    )
    return result


def plan_history(tenant_id: UUID) -> tuple[UUID | None, list[HistoryRow]]:
    """The subscription of a business and its plan history, oldest first (team only)."""
    with admin_session() as session:
        subscription_id = session.scalar(
            text("SELECT subscription_id FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
        if subscription_id is None:
            return None, []
        return subscription_id, [
            HistoryRow(
                assigned_at=r.assigned_at,
                plan_code=r.plan_code,
                previous_plan_code=r.previous_plan_code,
                effective_month=r.effective_month,
                source=r.source,
                reason=r.reason,
                assigned_by=r.assigned_by,
                plans_version=r.plans_version,
                prices_version=r.prices_version,
            )
            for r in _history(session, subscription_id)
        ]


__all__ = [
    "SOURCES",
    "HistoryRow",
    "SetPlanResult",
    "TenantNotFound",
    "ensure_subscription",
    "plan_history",
    "set_plan",
    "subscription_tenants",
]
