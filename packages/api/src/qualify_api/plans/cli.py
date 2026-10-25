"""The team's plan commands (m-24852145). `admin_session`: run locally against the dev
database, in production through the `qualify-prod` session.

    just set-plan --tenant <uuid> --plan plus --reason "Pidió más videos" --by herwin@...
    just set-plan --tenant <uuid> --plan basico --from 2026-12 --reason "..." --by ...
    just plans --tenant <uuid>     # the subscription's plan history, oldest first
    just plans                     # the plans catalog in force (no prices)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from qualify_api.plans.catalog import load_plans, owner_plan_text
from qualify_api.plans.schedule import PlanChangeRefused


def _month(value: str) -> date:
    parsed = datetime.strptime(value, "%Y-%m")
    return date(parsed.year, parsed.month, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m qualify_api.plans.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    set_plan = sub.add_parser("set", help="assign a plan to a business's subscription")
    set_plan.add_argument("--tenant", required=True, type=UUID)
    set_plan.add_argument("--plan", required=True, choices=load_plans().codes())
    set_plan.add_argument("--reason", required=True)
    set_plan.add_argument("--by", required=True, help="who decided it (team email)")
    set_plan.add_argument(
        "--from",
        dest="from_month",
        type=_month,
        help="YYYY-MM (default: upgrade now, downgrade next month)",
    )
    set_plan.add_argument("--support", type=UUID, help="the support request it answers")
    history = sub.add_parser("history", help="plan history of a business's subscription")
    history.add_argument("--tenant", type=UUID)
    return parser


def _catalog_text() -> str:
    plans = load_plans()
    lines = [f"Catálogo {plans.version} (sin precios; el cobro es a mano):"]
    for code in plans.codes():
        plan = plans.get(code)
        lines.append(
            f"  {code:<7} {owner_plan_text(plan)} · tope de aviso USD {plan.usd_alert_cap} · "
            f"{plan.included_businesses} negocios incluidos"
        )
    lines.append(f"  techo de negocios por suscripción: {plans.businesses_ceiling}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from qualify_api.plans import service  # noqa: PLC0415 — DB config only when run

    if args.command == "set":
        try:
            result = service.set_plan(
                tenant_id=args.tenant,
                plan_code=args.plan,
                reason=args.reason,
                assigned_by=args.by,
                requested_from=args.from_month,
                source="support_request" if args.support else "manual",
                support_request_id=args.support,
            )
        except (PlanChangeRefused, service.TenantNotFound) as exc:
            print(f"No se cambió el plan: {exc}", file=sys.stderr)
            return 2
        if not result.changed:
            since = f"{result.effective_month:%Y-%m}"
            print(f"Sin cambios: ya está en {result.plan_code} desde {since}")
            return 0
        print(
            f"Plan {result.previous_plan_code or 'inicial'} → {result.plan_code} desde "
            f"{result.effective_month:%Y-%m} · suscripción {result.subscription_id} · "
            f"{result.businesses} negocio(s)"
        )
        return 0
    if args.tenant is None:
        print(_catalog_text())
        return 0
    subscription_id, rows = service.plan_history(args.tenant)
    if subscription_id is None:
        print("Ese negocio no tiene suscripción todavía: está en Básico, sin plan asignado.")
        return 0
    print(f"Suscripción {subscription_id}:")
    if not rows:
        print("  sin cambios de plan: Básico, sin cobro registrado")
    for row in rows:
        print(
            f"  {row.assigned_at:%Y-%m-%d %H:%M}  {row.previous_plan_code or '—':<7} → "
            f"{row.plan_code:<7} desde {row.effective_month:%Y-%m}  {row.source:<15} "
            f"por {row.assigned_by}: {row.reason}  [{row.plans_version}/{row.prices_version}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
