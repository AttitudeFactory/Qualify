"""Offline tests of the monthly-fee charge and its reconciliation (m-25129422):
`plan-invoice` totals are `charges_for_month`, and expected / paid / pending for a full,
partial and missing payment."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from qualify_api.plans import payments
from qualify_api.plans.billing import PackPurchase, charges_for_month, total
from qualify_api.plans.report import build_month, render
from qualify_api.plans.schedule import Assignment

OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)


def _at(day: int, month: int = 10) -> datetime:
    return datetime(2026, month, day, 12, tzinfo=UTC)


PLUS_SINCE_OCT = [Assignment("plus", OCT, _at(3))]
PACK = PackPurchase("videos_2", _at(10, 11), usd=Decimal(29))


def _month(fee_paid: str = "0", packs: tuple[PackPurchase, ...] = ()):  # noqa: ANN202
    return build_month(
        subscription_id=uuid4(),
        name="Bianki",
        period=NOV,
        assignments=PLUS_SINCE_OCT,
        packs=packs,
        fee_paid_usd=Decimal(fee_paid),
    )


def test_the_invoice_total_is_charges_for_month() -> None:
    month = _month(packs=(PACK,))
    expected = total(charges_for_month(PLUS_SINCE_OCT, NOV, packs=(PACK,)))
    assert month.charged_usd == expected == Decimal(178)
    assert "Total del mes: US$ 178" in payments.invoice_text(month)
    assert "total USD 178.00" in payments.render_invoices([month])


def test_a_missing_payment_is_all_pending() -> None:
    month = _month()
    assert (month.paid_usd, month.pending_usd, month.payment_status) == (0, 149, "sin pago")
    text = payments.invoice_text(month)
    assert "Plan Plus, mensualidad: US$ 149" in text and "Por pagar: US$ 149" in text
    assert "Ya recibimos" not in text and "noviembre de 2026" in text


def test_a_partial_payment_asks_only_for_the_rest() -> None:
    month = _month("100")
    assert (month.pending_usd, month.payment_status) == (49, "pago parcial")
    text = payments.invoice_text(month)
    assert "Ya recibimos: US$ 100" in text and "Por pagar: US$ 49" in text


def test_a_full_payment_has_nothing_to_ask() -> None:
    month = _month("149")
    assert (month.pending_usd, month.payment_status) == (0, "pagado")
    assert payments.invoice_text(month) == ""
    assert "sin nada por cobrar" in payments.render_invoices([month])
    assert "pendiente USD 0.00 · pagado" in render([month])


def test_a_pack_already_paid_counts_as_paid() -> None:
    month = _month("149", packs=(PACK,))
    assert (month.packs_paid_usd, month.pending_usd, month.payment_status) == (29, 0, "pagado")


def test_paying_more_than_expected_is_flagged() -> None:
    assert _month("200").payment_status == "pagó de más"


def test_an_unbilled_subscription_has_no_charge_and_no_message() -> None:
    month = build_month(subscription_id=uuid4(), name="Nuevo", period=NOV, assignments=[])
    assert month.payment_status == "sin cobro" and payments.invoice_text(month) == ""


def test_the_first_month_and_an_upgrade_read_in_spanish() -> None:
    month = build_month(
        subscription_id=uuid4(),
        name="Polette",
        period=OCT,
        assignments=[Assignment("basico", OCT, _at(3)), Assignment("plus", OCT, _at(15))],
    )
    text = payments.invoice_text(month)
    assert "Plan Básico, primer mes a mitad de precio: US$ 39" in text
    assert "Cambio al plan Plus, diferencia de este mes: US$ 110" in text
    assert "Total del mes: US$ 149" in text
    # no internal id, no English in what the client reads
    assert str(month.subscription_id) not in text
    for word in ("upgrade", "plan_monthly", "pack ", "invoice", "USD"):
        assert word not in text


def test_money_is_whole_when_whole() -> None:
    assert payments.money(Decimal("149.00")) == "US$ 149"
    assert payments.money(Decimal("1250.5")) == "US$ 1.250,50"


def test_the_reference_is_subscription_and_month() -> None:
    sid = uuid4()
    assert payments.reference(sid, NOV) == f"{sid}:2026-11"


def test_the_manual_payment_id_ignores_case_and_spacing() -> None:
    assert payments.manual_payment_id("  Zelle   4471 ") == payments.manual_payment_id("zelle 4471")


def test_a_payment_needs_a_reference_and_a_known_method() -> None:
    parser = payments.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["payment", "--tenant", str(uuid4()), "--month", "2026-11", "--usd", "149"]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "payment",
                "--tenant",
                str(uuid4()),
                "--month",
                "2026-11",
                "--usd",
                "149",
                "--method",
                "bitcoin",
                "--payment-ref",
                "x",
                "--by",
                "a@b.co",
            ]
        )


def test_an_empty_reference_is_refused_before_touching_the_database() -> None:
    with pytest.raises(payments.PaymentRefused, match="payment-ref"):
        payments.record_payment(
            tenant_id=uuid4(),
            period=NOV,
            usd_paid=Decimal(149),
            method="zelle",
            payment_ref="   ",
            recorded_by="a@b.co",
            paid_at=_at(3, 11),
        )


@pytest.mark.parametrize(
    ("usd", "local", "currency"),
    [
        ("1.250", None, None),  # 1.250 dólares escrito con punto de miles
        ("149", "470.000", "COP"),  # 470 mil pesos, never stored as 470
        ("149", "0", "COP"),
        ("NaN", None, None),
        ("149", "470000", "pesos"),
    ],
)
def test_an_ambiguous_amount_or_currency_is_refused(
    usd: str, local: str | None, currency: str | None
) -> None:
    with pytest.raises(payments.PaymentRefused):
        payments.record_payment(
            tenant_id=uuid4(),
            period=NOV,
            usd_paid=Decimal(usd),
            method="transfer",
            payment_ref="Bancolombia 991",
            recorded_by="a@b.co",
            paid_at=_at(3, 11),
            local_amount=Decimal(local) if local else None,
            local_currency=currency,
        )
