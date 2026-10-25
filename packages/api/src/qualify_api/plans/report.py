"""The team's cost-against-charge report (m-24852145, brought from m-24828915): per
subscription and month, the vendor cost really spent by its businesses next to what the
team charges by hand — plan + upgrade differences + packs — computed with the versioned
prices (`precios-planes-v1`), each line naming the version it used. Team only: it reads
through `admin_session`, and the tables it reads are invisible to `qualify_app`.

    just plan-report                          # this month, every subscription
    just plan-report --month 2026-10
    just plan-report --tenant <uuid> --month 2026-11

Packs (m-24852129) are not built yet: the report charges them full price as soon as
their purchases exist; until then it shows none.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from qualify_api.plans.billing import ChargeLine, PackPurchase, charges_for_month, total
from qualify_api.plans.catalog import PlansCatalog, load_plans
from qualify_api.plans.schedule import Assignment, month_of, plan_code_at

_LINE_LABELS = {
    "plan_first_month": "primer mes",
    "plan_monthly": "mensual",
    "upgrade_difference": "diferencia por subir",
    "pack": "paquete",
}


@dataclass(frozen=True)
class SubscriptionMonth:
    subscription_id: UUID
    name: str
    period_month: date
    plan_code: str
    lines: list[ChargeLine]
    #: Vendor cost per business of the subscription (name → USD).
    cost_by_business: dict[str, Decimal] = field(default_factory=dict)

    @property
    def charged_usd(self) -> Decimal:
        return total(self.lines)

    @property
    def cost_usd(self) -> Decimal:
        return sum(self.cost_by_business.values(), Decimal(0))

    @property
    def margin_usd(self) -> Decimal:
        return self.charged_usd - self.cost_usd

    @property
    def prices_versions(self) -> str:
        return ", ".join(sorted({line.prices_version for line in self.lines})) or "—"


def build_month(
    *,
    subscription_id: UUID,
    name: str,
    period: date,
    assignments: Sequence[Assignment],
    packs: Sequence[PackPurchase] = (),
    cost_by_business: dict[str, Decimal] | None = None,
    catalog: PlansCatalog | None = None,
) -> SubscriptionMonth:
    plans = catalog or load_plans()
    return SubscriptionMonth(
        subscription_id=subscription_id,
        name=name,
        period_month=period,
        plan_code=plan_code_at(assignments, period, plans.default_code),
        lines=charges_for_month(assignments, period, packs=packs, catalog=plans),
        cost_by_business=dict(cost_by_business or {}),
    )


def render(months: Sequence[SubscriptionMonth]) -> str:
    out = ["Costo contra cobro (equipo; precios fuera de la app):"]
    for m in months:
        out.append(
            f"{m.period_month:%Y-%m}  {m.name}  [{str(m.subscription_id)[:8]}]  plan {m.plan_code}"
        )
        if not m.lines:
            out.append("    cobro: sin plan asignado todavía (Básico, sin cobro registrado)")
        for line in m.lines:
            out.append(
                f"    cobro  {_LINE_LABELS.get(line.kind, line.kind):<22} {line.code:<12} "
                f"USD {line.usd:>8.2f}  [{line.prices_version}]"
            )
        for business, usd in sorted(m.cost_by_business.items()):
            out.append(f"    costo  {business:<35} USD {usd:>8.2f}")
        out.append(
            f"    total  cobro USD {m.charged_usd:.2f} · costo USD {m.cost_usd:.2f} · "
            f"margen USD {m.margin_usd:.2f}  [{m.prices_versions}]"
        )
    return "\n".join(out)


def fetch(period: date, tenant_id: UUID | None = None) -> list[SubscriptionMonth]:
    from qualify_shared.db.admin import admin_session
    from sqlalchemy import select, text

    from qualify_api.plans.cost_alerts import _month_bounds
    from qualify_api.plans.models import Subscription
    from qualify_api.plans.service import _assignments, _history

    start, end = _month_bounds(period)
    months: list[SubscriptionMonth] = []
    with admin_session() as session:
        query = select(Subscription).order_by(Subscription.created_at)
        if tenant_id is not None:
            sid = session.scalar(
                text("SELECT subscription_id FROM tenants WHERE id = :id"), {"id": tenant_id}
            )
            query = query.where(Subscription.id == sid)
        for sub in session.scalars(query):
            costs = {
                row.name: Decimal(row.usd or 0)
                for row in session.execute(
                    text(
                        "SELECT t.name, COALESCE(SUM(e.cost_usd), 0) AS usd FROM tenants t "
                        "LEFT JOIN creative_usage_events e ON e.tenant_id = t.id "
                        "AND e.occurred_at >= :start AND e.occurred_at < :end "
                        "WHERE t.subscription_id = :sid GROUP BY t.id, t.name"
                    ),
                    {"sid": sub.id, "start": start, "end": end},
                )
            }
            months.append(
                build_month(
                    subscription_id=sub.id,
                    name=sub.display_name,
                    period=period,
                    assignments=_assignments(_history(session, sub.id)),
                    cost_by_business=costs,
                )
            )
    return months


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Costo contra cobro por suscripción (equipo).")
    parser.add_argument("--month", help="YYYY-MM (por defecto, el mes en curso)")
    parser.add_argument("--tenant", type=UUID, help="solo la suscripción de este negocio")
    args = parser.parse_args(argv)
    if args.month:
        parsed = datetime.strptime(args.month, "%Y-%m")
        period = date(parsed.year, parsed.month, 1)
    else:
        period = month_of(datetime.now(UTC))
    print(render(fetch(period, args.tenant)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
