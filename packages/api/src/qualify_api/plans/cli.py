"""The team's plan commands (m-24852145). `admin_session`: run locally against the dev
database, in production through the `qualify-prod` session.

    just set-plan --tenant <uuid> --plan plus --reason "Pidió más videos" --by herwin@...
    just set-plan --tenant <uuid> --plan basico --from 2026-12 --reason "..." --by ...
    just plans --tenant <uuid>     # the subscription's plan history, oldest first
    just plans                     # the plans catalog in force (no prices)

The 90-day packs (m-24852129), fixed and named — never a free quantity:

    just add-pack --tenant <uuid> --paquete "+2 videos" --reason "Pidió más" --by herwin@...
                  [--support <request id>] [--usd 29] [--payment-ref "Zelle 1234"]
    just packs --tenant <uuid>     # the business's packs: left, expiry, paid
    just revoke-pack <pack id> --reason "..." --by ...
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from qualify_api.plans.catalog import PACK_NAMES, load_plans, owner_plan_text, pack_name
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
    add = sub.add_parser("add-pack", help="add one fixed 90-day pack after the payment")
    add.add_argument("--tenant", required=True, type=UUID)
    add.add_argument(
        "--paquete",
        "--pack",
        dest="pack",
        required=True,
        help=f"one of: {', '.join(PACK_NAMES.values())}",
    )
    add.add_argument("--reason", required=True)
    add.add_argument("--by", required=True, help="who added it (team email)")
    add.add_argument("--support", type=UUID, help="the «Pedir más» request it answers")
    add.add_argument("--brand", type=UUID, help="only when the business has several brands")
    add.add_argument("--usd", help="amount paid in USD (default: the price of the table)")
    add.add_argument("--payment-ref", default="", help="transfer / Zelle / pago móvil ref")
    add.add_argument("--key", help="idempotency key (to add a second identical pack)")
    packs = sub.add_parser("packs", help="the packs of a business")
    packs.add_argument("--tenant", required=True, type=UUID)
    revoke = sub.add_parser("revoke-pack", help="stop a pack counting (never deleted)")
    revoke.add_argument("pack_id", type=UUID)
    revoke.add_argument("--reason", required=True)
    revoke.add_argument("--by", required=True)
    return parser


def _pack_commands(args: argparse.Namespace) -> int:
    from qualify_api.plans import pack_service  # noqa: PLC0415 — DB config only when run

    if args.command == "add-pack":
        try:
            result = pack_service.add_pack(
                tenant_id=args.tenant,
                pack=args.pack,
                reason=args.reason,
                granted_by=args.by,
                brand_id=args.brand,
                support_request_id=args.support,
                usd_paid=args.usd,
                payment_ref=args.payment_ref,
                idempotency_key=args.key,
            )
        except (pack_service.PackRefused, pack_service.TenantNotFound) as exc:
            print(f"No se sumó el paquete: {exc}", file=sys.stderr)
            return 2
        name = pack_name(result.pack_code)
        if not result.changed:
            print(f"Sin cambios: ese paquete ya estaba sumado ({name}, {result.pack_id})")
            return 0
        print(
            f"Paquete «{name}» sumado · vence {result.expires_at:%Y-%m-%d %H:%M} UTC · "
            f"USD {result.usd_paid} [{result.prices_version}] · {result.pack_id}"
        )
        return 0
    if args.command == "revoke-pack":
        try:
            done = pack_service.revoke_pack(args.pack_id, reason=args.reason, revoked_by=args.by)
        except pack_service.PackRefused as exc:
            print(f"No se revocó: {exc}", file=sys.stderr)
            return 2
        print("Paquete revocado." if done else "Sin cambios: no existe o ya estaba revocado.")
        return 0
    now = datetime.now(UTC)
    rows = pack_service.list_packs(args.tenant)
    if not rows:
        print("Ese negocio no tiene paquetes.")
    for row in rows:
        left = ", ".join(
            f"{d} {row.left(d, now)}/{row.units[d]}" for d in row.units if row.units[d]
        )
        state = (
            "revocado"
            if row.revoked_at
            else "vencido"
            if now >= row.expires_at
            else f"vence {row.expires_at:%Y-%m-%d}"
        )
        paid = f"USD {row.usd_paid}" if row.usd_paid is not None else "sin pago"
        print(
            f"  {row.granted_at:%Y-%m-%d}  «{pack_name(row.pack_code)}»  quedan {left}  {state}  "
            f"{paid} [{row.prices_version}]  {row.source} por {row.granted_by}: {row.reason}  "
            f"{row.id}"
        )
    return 0


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
    if args.command in ("add-pack", "packs", "revoke-pack"):
        return _pack_commands(args)
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
