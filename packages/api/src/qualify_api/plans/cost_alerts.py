"""D18 + ADR 43 §2.9.3: the plan's USD cap is an ALERT to the team, per subscription and
month, computed by a team job outside the request (m-24852145).

For each subscription: the month's real vendor cost of all its businesses
(`creative_usage_events.cost_usd`, UTC calendar month) against the cap of the plan in
force (Básico 120 / Plus 240 / Pro 480). Crossing it writes ONE
`subscription_cost_alerts` row per subscription and month (UNIQUE) and tells the team in
Lark; a channel that is down leaves `notified_at` NULL and the next run tries again.

**It never pauses, blocks or slows anything** (founder, 2026-10-24: the team reviews by
hand). This module reads costs and writes only its own alert rows: no ledger, no engine
config, no generation is touched. The cap sits above the worst case of a plan, so it
never stands between an owner and what their plan + packs paid for.

Runs daily inside the calendar worker's chore (`planner.worker`), and on demand:

    just plan-cost-alerts                 # every subscription
    just plan-cost-alerts --tenant <uuid> # the subscription of that business
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from qualify_shared.db.admin import admin_session
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.plans.catalog import PlansCatalog, load_plans
from qualify_api.plans.models import Subscription, SubscriptionCostAlert
from qualify_api.plans.notify import TeamNotifier, production_team_notifier
from qualify_api.plans.schedule import month_of, next_month, plan_code_at
from qualify_api.plans.service import _assignments, _history, ensure_subscription

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CostCheck:
    subscription_id: UUID
    period_month: date
    plan_code: str
    cap_usd: Decimal
    spent_usd: Decimal
    #: True when this run told the channel (and it accepted).
    notified: bool = False

    @property
    def crossed(self) -> bool:
        return self.spent_usd >= self.cap_usd


def alert_text(name: str, check: CostCheck, plan_name: str, businesses: int) -> str:
    return (
        f"Tope de gasto alcanzado · {name} (plan {plan_name}, {businesses} negocio(s)): "
        f"USD {check.spent_usd:.2f} de USD {check.cap_usd:.0f} en {check.period_month:%Y-%m}. "
        "Solo aviso: no se pausó nada. Revísenlo a mano."
    )


def _month_bounds(period: date) -> tuple[datetime, datetime]:
    end = next_month(period)
    return (
        datetime(period.year, period.month, 1, tzinfo=UTC),
        datetime(end.year, end.month, 1, tzinfo=UTC),
    )


def subscription_spend(session: Session, subscription_id: UUID, period: date) -> Decimal:
    start, end = _month_bounds(period)
    total = session.scalar(
        text(
            "SELECT COALESCE(SUM(e.cost_usd), 0) FROM creative_usage_events e "
            "JOIN tenants t ON t.id = e.tenant_id "
            "WHERE t.subscription_id = :sid AND e.occurred_at >= :start AND e.occurred_at < :end"
        ),
        {"sid": subscription_id, "start": start, "end": end},
    )
    return Decimal(total or 0)


def _scope(session: Session, tenant_ids: Iterable[UUID] | None) -> list[UUID]:
    if tenant_ids is None:
        orphans = session.scalars(text("SELECT id FROM tenants WHERE subscription_id IS NULL"))
        targets = list(orphans)
    else:
        targets = list(dict.fromkeys(tenant_ids))
    # a business created after 0093 has no subscription until a plan is assigned: give
    # it its 1:1 one so its spend is watched too (Básico)
    subs = {ensure_subscription(session, tid) for tid in targets}
    if tenant_ids is None:
        subs |= set(session.scalars(select(Subscription.id)))
    return sorted(subs)


def run_cost_alerts(
    *,
    now: datetime | None = None,
    tenant_ids: Iterable[UUID] | None = None,
    notifier: TeamNotifier | None = None,
    catalog: PlansCatalog | None = None,
) -> list[CostCheck]:
    """Check every subscription in scope; returns one `CostCheck` per subscription."""
    plans = catalog or load_plans()
    channel = notifier or production_team_notifier()
    period = month_of(now or datetime.now(UTC))
    with admin_session() as session:
        subscriptions = _scope(session, tenant_ids)
    checks: list[CostCheck] = []
    for subscription_id in subscriptions:
        try:
            checks.append(_check_one(subscription_id, period, plans, channel))
        except Exception:
            logger.exception("plans.cost_alert_failed subscription=%s", subscription_id)
    return checks


def _check_one(
    subscription_id: UUID, period: date, plans: PlansCatalog, channel: TeamNotifier
) -> CostCheck:
    with admin_session() as session:
        history = _assignments(_history(session, subscription_id))
        plan = plans.get(plan_code_at(history, period, plans.default_code))
        spent = subscription_spend(session, subscription_id, period)
        check = CostCheck(subscription_id, period, plan.code, plan.usd_alert_cap, spent)
        if not check.crossed:
            return check
        session.execute(
            insert(SubscriptionCostAlert)
            .values(
                subscription_id=subscription_id,
                period_month=period,
                plan_code=plan.code,
                plans_version=plans.version,
                cap_usd=plan.usd_alert_cap,
                spent_usd=spent,
            )
            .on_conflict_do_nothing(constraint="uq_cost_alerts_month")
        )
        alert = session.scalar(
            select(SubscriptionCostAlert)
            .where(
                SubscriptionCostAlert.subscription_id == subscription_id,
                SubscriptionCostAlert.period_month == period,
            )
            .with_for_update()
        )
        if alert is None or alert.notified_at is not None:
            return check
        name = session.scalar(
            select(Subscription.display_name).where(Subscription.id == subscription_id)
        )
        businesses = session.scalar(
            text("SELECT count(*) FROM tenants WHERE subscription_id = :sid"),
            {"sid": subscription_id},
        )
        accepted = channel.notify(alert_text(name or "", check, plan.name, int(businesses or 0)))
        if accepted:
            alert.notified_at = datetime.now(UTC)
        return CostCheck(
            subscription_id, period, plan.code, plan.usd_alert_cap, spent, notified=accepted
        )


def daily_cost_alerts(tenant_ids: Iterable[UUID] | None) -> Callable[[], object]:
    """The calendar worker's chore: the same scope as its ticks."""
    scope = list(tenant_ids) if tenant_ids is not None else None
    return lambda: run_cost_alerts(tenant_ids=scope)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tope de gasto por plan: avisos (equipo).")
    parser.add_argument("--tenant", action="append", type=UUID, dest="tenants")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    for check in run_cost_alerts(tenant_ids=args.tenants):
        mark = "AVISO" if check.crossed else "ok"
        print(
            f"{mark:5}  {check.subscription_id}  {check.period_month:%Y-%m}  {check.plan_code:<6} "
            f"USD {check.spent_usd:.2f} / {check.cap_usd:.0f}"
            + ("  (avisado)" if check.notified else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
