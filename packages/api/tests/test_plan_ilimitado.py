"""Offline tests for the internal plan «Ilimitado» (founder, 2026-11-02, m-24921124): no
monthly limit in the ledger, never billed, never offered to a client, the USD cap still
an alert, and the owner's words."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from qualify_creative.creations import CreationPrice, load_weights

from qualify_api.creative.creations import (
    InMemoryCreationsLedger,
    allocation_rows,
    compose_state,
    quota_for,
)
from qualify_api.meegle.plan_request import InvalidPlanRequest, plan_code_for
from qualify_api.plans import billing, cli
from qualify_api.plans.billing import PackPurchase, charges_for_month, total
from qualify_api.plans.catalog import load_plans, owner_plan_text
from qualify_api.plans.cost_alerts import CostCheck, alert_text
from qualify_api.plans.packs import CREATIONS, PREVIEWS, SOURCE_PLAN, VIDEOS
from qualify_api.plans.read import plan_from_schedule
from qualify_api.plans.report import build_month, render
from qualify_api.plans.schedule import Assignment, PlanSchedule, effective_month_for

PLANS = load_plans()
BASICO, PRO, ILIMITADO = PLANS.get("basico"), PLANS.get("pro"), PLANS.get("ilimitado")
OCT, NOV, DEC = date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)


def _at(day: int, month: int = 11, hour: int = 12) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def _usd(lines: list[billing.ChargeLine]) -> list[tuple[str, str, Decimal]]:
    return [(line.kind, line.code, line.usd) for line in lines]


# --- the owner's words ------------------------------------------------------------------


def test_owner_plan_text_of_ilimitado_says_no_limit_and_no_money() -> None:
    assert (
        owner_plan_text(ILIMITADO)
        == "Tu plan: Ilimitado · creaciones, videos y vistas previas sin límite"
    )


def test_the_business_reads_ilimitado_from_its_projection() -> None:
    assert plan_from_schedule(PlanSchedule(plan_code="ilimitado"), NOV) is ILIMITADO


# --- the ledger never refuses -----------------------------------------------------------


def test_quota_for_ilimitado_is_unlimited_not_a_huge_number() -> None:
    got = quota_for(
        tenant_id=uuid4(), brand_id=uuid4(), period=NOV, weights=load_weights(), plan=ILIMITADO
    )
    assert got.unlimited and (got.creations, got.videos, got.previews) == (0, 0, 0)
    assert not quota_for(
        tenant_id=uuid4(), brand_id=uuid4(), period=NOV, weights=load_weights(), plan=PRO
    ).unlimited


def test_an_unlimited_month_never_refuses_creations_previews_or_videos() -> None:
    ledger = InMemoryCreationsLedger(used=500, videos_used=90, previews_used=300, plan=ILIMITADO)
    tenant, brand = uuid4(), uuid4()
    for revision in range(1, 41):
        draft = uuid4()
        assert (
            ledger.charge(
                tenant_id=tenant,
                brand_id=brand,
                draft_id=draft,
                revision=revision,
                price=CreationPrice("generated_video", 3, videos=2),
            )
            is not None
        )
        assert (
            ledger.charge_videos(
                tenant_id=tenant, brand_id=brand, draft_id=draft, revision=revision, videos=2
            )
            is not None
        )
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert balance.unlimited
    assert balance.can_pay(10_000, 10_000)
    assert balance.shortfall(CreationPrice("image", 99, videos=99)) is None
    assert balance.video_shortfall(99) is None
    # every unit is paid by the plan, so the month's use stays on record
    row = next(iter(ledger.rows.values()))
    assert {(a.dimension, a.source, a.units) for a in row.allocations} == {
        (CREATIONS, SOURCE_PLAN, 3),
        (PREVIEWS, SOURCE_PLAN, 2),
        (VIDEOS, SOURCE_PLAN, 2),
    }


def test_the_allocations_of_an_unlimited_charge_name_the_plan_and_its_version() -> None:
    state = compose_state(
        quota=quota_for(
            tenant_id=uuid4(), brand_id=uuid4(), period=NOV, weights=load_weights(), plan=ILIMITADO
        ),
        used={CREATIONS: 1000, VIDEOS: 100, PREVIEWS: 100},
        packs=[],
        plan=ILIMITADO,
        weights_version="w",
        renews_on=None,
        zone="UTC",
    )
    assert state.plan_left == {CREATIONS: None, VIDEOS: None, PREVIEWS: None}
    rows = allocation_rows(uuid4(), uuid4(), state.split(CREATIONS, 7), NOV, ILIMITADO, {})
    assert [(r["plan_code"], r["plans_version"], r["units"]) for r in rows] == [
        ("ilimitado", "planes-v2", 7)
    ]


def test_a_limited_plan_still_refuses_when_its_month_is_used_up() -> None:
    ledger = InMemoryCreationsLedger(used=30, plan=BASICO)
    balance = ledger.balance(tenant_id=uuid4(), brand_id=uuid4())
    assert not balance.unlimited and not balance.can_pay(1)


# --- schedule: going to it and leaving it -----------------------------------------------


def test_going_to_ilimitado_applies_at_once_and_leaving_it_next_month() -> None:
    assert effective_month_for(current=PRO, new=ILIMITADO, now_month=NOV) == NOV
    assert effective_month_for(current=ILIMITADO, new=BASICO, now_month=NOV) == DEC


# --- billing: never charged -------------------------------------------------------------


def test_a_subscription_on_ilimitado_is_never_charged() -> None:
    history = [Assignment("ilimitado", NOV, _at(3))]
    assert charges_for_month(history, NOV) == []
    assert charges_for_month(history, DEC) == []


def test_moving_to_ilimitado_mid_month_charges_no_difference() -> None:
    history = [Assignment("basico", OCT, _at(2, 10)), Assignment("ilimitado", NOV, _at(15))]
    assert _usd(charges_for_month(history, NOV)) == [(billing.LINE_MONTHLY, "basico", Decimal(79))]
    assert charges_for_month(history, DEC) == []


def test_leaving_ilimitado_bills_the_paid_plan_from_its_month() -> None:
    history = [Assignment("ilimitado", NOV, _at(3)), Assignment("plus", DEC, _at(20))]
    assert charges_for_month(history, NOV) == []
    assert _usd(charges_for_month(history, DEC)) == [(billing.LINE_MONTHLY, "plus", Decimal(149))]


def test_a_pack_on_ilimitado_is_still_a_line_at_what_was_paid() -> None:
    history = [Assignment("ilimitado", NOV, _at(3))]
    pack = PackPurchase("videos_2", _at(10), usd=Decimal("29"))
    lines = charges_for_month(history, NOV, packs=[pack])
    assert _usd(lines) == [(billing.LINE_PACK, "videos_2", Decimal("29"))]


def test_the_report_shows_the_cost_of_ilimitado_and_says_it_is_not_charged() -> None:
    month = build_month(
        subscription_id=uuid4(),
        name="Bianki",
        period=NOV,
        assignments=[Assignment("ilimitado", NOV, _at(3))],
        cost_by_business={"Bianki": Decimal("212.40")},
    )
    assert month.plan_code == "ilimitado" and not month.plan_sellable
    assert total(month.lines) == 0 and month.margin_usd == Decimal("-212.40")
    text = render([month])
    assert "plan interno Ilimitado, sin cobro" in text and "212.40" in text
    assert "sin plan asignado" not in text


# --- the USD cap is still an alert ------------------------------------------------------


def test_ilimitado_keeps_a_usd_alert_that_never_pauses() -> None:
    assert ILIMITADO.usd_alert_cap == PRO.usd_alert_cap == Decimal(480)
    check = CostCheck(uuid4(), NOV, "ilimitado", ILIMITADO.usd_alert_cap, Decimal("500"))
    assert check.crossed
    text = alert_text("Bianki", check, ILIMITADO.name, 1)
    assert "plan Ilimitado" in text and "no se pausó nada" in text


# --- never offered to a client ----------------------------------------------------------


def test_a_clients_alta_cannot_ask_for_ilimitado() -> None:
    with pytest.raises(InvalidPlanRequest) as raised:
        plan_code_for("Ilimitado", PLANS)
    assert raised.value.message == "«Ilimitado» no es un plan. Los planes son: Básico, Plus, Pro."


def test_the_team_can_set_ilimitado_and_the_catalog_marks_it_internal(capsys) -> None:
    args = cli.build_parser().parse_args(
        ["set", "--tenant", str(uuid4()), "--plan", "ilimitado", "--reason", "r", "--by", "h"]
    )
    assert args.plan == "ilimitado"
    assert cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert "ilimitado" in out and "INTERNO: no se vende ni se cobra" in out
