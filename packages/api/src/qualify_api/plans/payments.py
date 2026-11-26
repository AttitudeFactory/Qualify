"""The monthly fee: what the team asks a subscription to pay for a month and the payments
it receives, by hand (D19, m-25129422). Team only: `admin_session`, nothing is sent.

    just plan-invoice --month 2026-11 [--tenant <uuid>]   # prints lines, total, message
    just plan-payment --tenant <uuid> --month 2026-11 --usd 149 --method zelle \
        --payment-ref "Zelle 4471" --by herwin@attitudefactory.co \
        [--local 470000 --currency COP] [--paid-on 2026-11-03]

Idempotency of a manual payment: `provider = 'manual'` and `provider_payment_id` = the
payment reference the bank/Zelle/pago móvil gave (required), with spaces collapsed and
case folded — the same receipt recorded twice is one row (`ON CONFLICT DO NOTHING` on
`UNIQUE (provider, provider_payment_id)`). A provider webhook will later insert into the
same table with its own provider name and payment id.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from qualify_api.plans.billing import (
    LINE_FIRST_MONTH,
    LINE_MONTHLY,
    LINE_PACK,
    LINE_UPGRADE,
    ChargeLine,
)
from qualify_api.plans.catalog import load_plans, pack_name
from qualify_api.plans.report import _LINE_LABELS, SubscriptionMonth
from qualify_api.plans.schedule import month_of

PROVIDER_MANUAL = "manual"
PIPELINE_VERSION = "plan-payment-cli-v1"
METHODS = ("transfer", "zelle", "mobile_payment", "payment_link", "cash", "other")

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def reference(subscription_id: UUID, period: date) -> str:
    """Our reference for a subscription's month — what a payment link will carry."""
    return f"{subscription_id}:{period:%Y-%m}"


def manual_payment_id(payment_ref: str) -> str:
    return " ".join(payment_ref.split()).casefold()


def money(usd: Decimal) -> str:
    """«US$ 149» — whole when it is whole (qualify-copy-es §5), else «US$ 149,50»."""
    if usd == usd.to_integral_value():
        return f"US$ {int(usd):,}".replace(",", ".")
    whole, cents = f"{usd:.2f}".split(".")
    return f"US$ {int(whole):,}".replace(",", ".") + f",{cents}"


def _line_text(line: ChargeLine) -> str:
    if line.kind == LINE_PACK:
        return f"Paquete «{pack_name(line.code)}»"
    name = load_plans().get(line.code).name
    if line.kind == LINE_FIRST_MONTH:
        return f"Plan {name}, primer mes a mitad de precio"
    if line.kind == LINE_MONTHLY:
        return f"Plan {name}, mensualidad"
    if line.kind == LINE_UPGRADE:
        return f"Cambio al plan {name}, diferencia de este mes"
    return name


def invoice_text(month: SubscriptionMonth) -> str:
    """The message the team pastes into WhatsApp or the email: Spanish, no internal ids.
    Empty when there is nothing to ask for."""
    if month.pending_usd <= 0:
        return ""
    period = f"{_MONTHS[month.period_month.month - 1]} de {month.period_month.year}"
    out = [f"Hola. Te compartimos el cobro de Qualify de {period} para {month.name}:"]
    out += [f"• {_line_text(line)}: {money(line.usd)}" for line in month.lines]
    out.append(f"Total del mes: {money(month.charged_usd)}")
    if month.paid_usd > 0:
        out.append(f"Ya recibimos: {money(month.paid_usd)}")
    out.append(f"Por pagar: {money(month.pending_usd)}")
    out.append("Cuando hagas el pago, envíanos el comprobante por este medio. ¡Gracias!")
    return "\n".join(out)


def render_invoices(months: Sequence[SubscriptionMonth]) -> str:
    out = ["Cobro del mes (equipo; no se envía nada, copia el mensaje a mano):"]
    for m in months:
        out.append("")
        out.append(
            f"{m.period_month:%Y-%m}  {m.name}  plan {m.plan_code}  "
            f"referencia {reference(m.subscription_id, m.period_month)}"
        )
        for line in m.lines:
            label = _LINE_LABELS.get(line.kind, line.kind)
            out.append(f"    {label:<22} {line.code:<12} USD {line.usd:>8.2f}")
        out.append(
            f"    total USD {m.charged_usd:.2f} · pagado USD {m.paid_usd:.2f} · "
            f"pendiente USD {m.pending_usd:.2f}"
        )
        message = invoice_text(m)
        if not message:
            out.append("    sin nada por cobrar")
            continue
        out.append("    --- mensaje ---")
        out += [f"    {row}" for row in message.splitlines()]
    return "\n".join(out)


# --- recording a payment --------------------------------------------------------------


class PaymentRefused(ValueError):
    pass


@dataclass(frozen=True)
class RecordedPayment:
    payment_id: UUID
    subscription_id: UUID
    period_month: date
    usd_paid: Decimal
    #: False when the same provider payment was already recorded (nothing written).
    changed: bool


def record_payment(
    *,
    tenant_id: UUID,
    period: date,
    usd_paid: Decimal,
    method: str,
    payment_ref: str,
    recorded_by: str,
    paid_at: datetime,
    local_amount: Decimal | None = None,
    local_currency: str | None = None,
) -> RecordedPayment:
    """Record one manual payment for the month of the business's subscription, once."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — DB only when run
    from sqlalchemy import select, text  # noqa: PLC0415
    from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

    from qualify_api.plans.models import SubscriptionPayment  # noqa: PLC0415

    provider_id = manual_payment_id(payment_ref)
    if not provider_id:
        raise PaymentRefused("falta --payment-ref: es lo que evita registrar un pago dos veces")
    if not recorded_by.strip():
        raise PaymentRefused("falta --by")
    if usd_paid <= 0:
        raise PaymentRefused("el monto en USD debe ser mayor que cero")
    if method not in METHODS:
        raise PaymentRefused(f"método desconocido {method!r}; usa uno de {', '.join(METHODS)}")
    if (local_amount is None) != (local_currency is None):
        raise PaymentRefused("--local y --currency van juntos")
    with admin_session() as session:
        sid = session.scalar(
            text("SELECT subscription_id FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
        if sid is None:
            raise PaymentRefused("ese negocio no tiene suscripción: asígnale un plan primero")
        new_id = session.scalar(
            insert(SubscriptionPayment)
            .values(
                subscription_id=sid,
                period_month=period,
                reference=reference(sid, period),
                usd_paid=usd_paid,
                local_amount=local_amount,
                local_currency=local_currency.upper() if local_currency else None,
                method=method,
                payment_ref=payment_ref.strip(),
                provider=PROVIDER_MANUAL,
                provider_payment_id=provider_id,
                paid_at=paid_at,
                recorded_by=recorded_by.strip(),
                pipeline_version=PIPELINE_VERSION,
            )
            .on_conflict_do_nothing(constraint="uq_subscription_payments_provider")
            .returning(SubscriptionPayment.id)
        )
        if new_id is not None:
            return RecordedPayment(new_id, sid, period, usd_paid, changed=True)
        existing = session.scalars(
            select(SubscriptionPayment).where(
                SubscriptionPayment.provider == PROVIDER_MANUAL,
                SubscriptionPayment.provider_payment_id == provider_id,
            )
        ).one()
        if (existing.subscription_id, existing.period_month, existing.usd_paid) != (
            sid,
            period,
            usd_paid,
        ):
            raise PaymentRefused(
                f"esa referencia de pago ya está registrada para {existing.reference} "
                f"por USD {existing.usd_paid}; revisa antes de registrarla de nuevo"
            )
        return RecordedPayment(existing.id, sid, period, existing.usd_paid, changed=False)


# --- CLI ---------------------------------------------------------------------------------


def _month(value: str) -> date:
    parsed = datetime.strptime(value, "%Y-%m")
    return date(parsed.year, parsed.month, 1)


def _amount(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"monto inválido: {value!r}") from exc


def _day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(hour=12, tzinfo=UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m qualify_api.plans.payments")
    sub = parser.add_subparsers(dest="command", required=True)
    invoice = sub.add_parser("invoice", help="lines, total and message per subscription")
    invoice.add_argument("--month", type=_month, help="YYYY-MM (default: this month)")
    invoice.add_argument("--tenant", type=UUID, help="only the subscription of this business")
    pay = sub.add_parser("payment", help="record one manual monthly payment (idempotent)")
    pay.add_argument("--tenant", required=True, type=UUID)
    pay.add_argument("--month", required=True, type=_month, help="YYYY-MM the payment covers")
    pay.add_argument("--usd", required=True, type=_amount)
    pay.add_argument("--method", required=True, choices=METHODS)
    pay.add_argument("--payment-ref", required=True, help="the receipt / Zelle / pago móvil ref")
    pay.add_argument("--by", required=True, help="who recorded it (team email)")
    pay.add_argument("--local", type=_amount, help="amount in local currency, if any")
    pay.add_argument("--currency", help="ISO code of --local: COP, UYU, VES")
    pay.add_argument("--paid-on", type=_day, help="YYYY-MM-DD (default: today)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "invoice":
        from qualify_api.plans.report import fetch  # noqa: PLC0415

        print(render_invoices(fetch(args.month or month_of(datetime.now(UTC)), args.tenant)))
        return 0
    try:
        result = record_payment(
            tenant_id=args.tenant,
            period=args.month,
            usd_paid=args.usd,
            method=args.method,
            payment_ref=args.payment_ref,
            recorded_by=args.by,
            paid_at=args.paid_on or datetime.now(UTC),
            local_amount=args.local,
            local_currency=args.currency,
        )
    except PaymentRefused as exc:
        print(f"No se registró el pago: {exc}", file=sys.stderr)
        return 2
    if not result.changed:
        print(f"Sin cambios: ese pago ya estaba registrado ({result.payment_id})")
        return 0
    print(
        f"Pago registrado: USD {result.usd_paid} para {result.period_month:%Y-%m} · "
        f"suscripción {result.subscription_id} · {result.payment_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
