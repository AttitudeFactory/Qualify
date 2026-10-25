"""Offline tests for plans Básico / Plus / Pro (m-24852145): the versioned catalogs,
when a change applies, what the team charges a month (the founder's three rules, each
with its case), the quota the ledger reads, and the owner's words."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from qualify_creative.creations import CreationPrice, load_weights

from qualify_api.creative.creations import InMemoryCreationsLedger, quota_for
from qualify_api.plans import billing, catalog, cli
from qualify_api.plans.billing import PackPurchase, charges_for_month, total
from qualify_api.plans.catalog import load_plans, load_prices, owner_plan_text
from qualify_api.plans.cost_alerts import CostCheck, alert_text
from qualify_api.plans.read import plan_from_schedule
from qualify_api.plans.report import build_month, render
from qualify_api.plans.schedule import (
    Assignment,
    PlanChangeRefused,
    PlanSchedule,
    check_pending,
    effective_month_for,
    pending_months,
    plan_code_at,
    schedule_for,
)

PLANS = load_plans()
BASICO, PLUS, PRO = PLANS.get("basico"), PLANS.get("plus"), PLANS.get("pro")
OCT, NOV, DEC = date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)
REPO = Path(__file__).resolve().parents[3]


def _at(day: int, month: int = 10, hour: int = 12) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


# --- the catalogs -----------------------------------------------------------------------


def test_planes_v1_is_pinned() -> None:
    assert catalog.PLANS_VERSION == "planes-v1"
    assert PLANS.default_code == "basico"
    got = {
        c: (p.creations, p.videos, p.previews, p.usd_alert_cap, p.included_businesses)
        for c, p in PLANS.plans.items()
    }
    assert got == {
        "basico": (30, 4, 20, Decimal(120), 2),
        "plus": (60, 8, 40, Decimal(240), 3),
        "pro": (120, 16, 80, Decimal(480), 5),
    }
    assert PLANS.businesses_ceiling == 8
    assert PLANS.codes() == ("basico", "plus", "pro")


def test_precios_planes_v1_is_pinned() -> None:
    prices = load_prices()
    assert catalog.PRICES_VERSION == prices.version == "precios-planes-v1"
    assert prices.plans_version == "planes-v1" and prices.currency == "USD"
    assert {c: (p.monthly, p.first_month) for c, p in prices.plans.items()} == {
        "basico": (Decimal(79), Decimal(39)),
        "plus": (Decimal(149), Decimal(75)),
        "pro": (Decimal(279), Decimal(139)),
    }
    assert {c: (p.creations, p.videos, p.previews, p.price) for c, p in prices.packs.items()} == {
        "videos_2": (0, 2, 0, Decimal(29)),
        "creations_20": (20, 0, 0, Decimal(12)),
        "previews_10": (0, 0, 10, Decimal(19)),
    }


def test_basico_equals_the_weights_quota_so_nothing_changes_for_todays_businesses() -> None:
    weights = load_weights()
    assert (BASICO.creations, BASICO.videos, BASICO.previews) == (
        weights.monthly_quota,
        weights.monthly_video_quota,
        weights.monthly_preview_quota,
    )


def test_an_unknown_plan_is_refused() -> None:
    with pytest.raises(catalog.UnknownPlan):
        PLANS.get("gold")


# --- the owner's words ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("basico", "Tu plan: Básico · 30 creaciones, 4 videos y 20 vistas previas al mes"),
        ("plus", "Tu plan: Plus · 60 creaciones, 8 videos y 40 vistas previas al mes"),
        ("pro", "Tu plan: Pro · 120 creaciones, 16 videos y 80 vistas previas al mes"),
    ],
)
def test_owner_plan_text_is_literal(code: str, text: str) -> None:
    assert owner_plan_text(PLANS.get(code)) == text


# --- when a change applies --------------------------------------------------------------


def test_an_upgrade_applies_this_month() -> None:
    assert effective_month_for(current=BASICO, new=PLUS, now_month=OCT) == OCT


def test_a_downgrade_applies_next_month_and_never_this_one() -> None:
    assert effective_month_for(current=PRO, new=BASICO, now_month=OCT) == NOV
    assert effective_month_for(current=PRO, new=BASICO, now_month=DEC) == date(2027, 1, 1)
    with pytest.raises(PlanChangeRefused):
        effective_month_for(current=PRO, new=BASICO, now_month=OCT, requested=OCT)


def test_a_past_or_mid_month_start_is_refused() -> None:
    with pytest.raises(PlanChangeRefused):
        effective_month_for(current=BASICO, new=PLUS, now_month=NOV, requested=OCT)
    with pytest.raises(PlanChangeRefused):
        effective_month_for(current=BASICO, new=PLUS, now_month=OCT, requested=date(2026, 10, 15))


def test_the_plan_of_a_month_is_the_latest_assignment_in_force() -> None:
    history = [
        Assignment("basico", OCT, _at(1)),
        Assignment("plus", OCT, _at(15)),
        Assignment("basico", NOV, _at(20)),  # downgrade, next month
    ]
    assert plan_code_at([], OCT, "basico") == "basico"
    assert plan_code_at(history, OCT, "basico") == "plus"
    assert plan_code_at(history, NOV, "basico") == "basico"
    assert schedule_for(history, OCT, PLANS) == PlanSchedule("plus", "basico", NOV)
    assert schedule_for(history, NOV, PLANS) == PlanSchedule("basico")


def test_an_upgrade_after_a_pending_downgrade_supersedes_it() -> None:
    history = [
        Assignment("plus", OCT, _at(1)),
        Assignment("basico", NOV, _at(10)),
        Assignment("pro", OCT, _at(20)),
    ]
    assert pending_months(history, OCT) == []
    assert schedule_for(history, OCT, PLANS) == PlanSchedule("pro")
    check_pending(history, DEC, OCT)  # nothing live is pending: a new change may come


def test_only_one_pending_change_at_a_time() -> None:
    history = [Assignment("pro", OCT, _at(1)), Assignment("plus", NOV, _at(10))]
    check_pending(history, NOV, OCT)  # the same month: allowed (replaces)
    with pytest.raises(PlanChangeRefused):
        check_pending(history, DEC, OCT)


def test_the_business_reads_the_pending_plan_once_its_month_comes() -> None:
    schedule = PlanSchedule("pro", "basico", NOV)
    assert plan_from_schedule(schedule, OCT).code == "pro"
    assert plan_from_schedule(schedule, NOV).code == "basico"
    assert plan_from_schedule(None, OCT).code == "basico"  # no row = Básico
    assert plan_from_schedule(PlanSchedule("gold"), OCT).code == "basico"


# --- what the team charges (rules of 2026-10-24/25, one case each) -----------------------


def _usd(lines: list[billing.ChargeLine]) -> list[tuple[str, str, Decimal]]:
    return [(line.kind, line.code, line.usd) for line in lines]


def test_plus_first_month_is_75_and_the_second_149() -> None:
    history = [Assignment("plus", OCT, _at(3))]
    first = charges_for_month(history, OCT)
    second = charges_for_month(history, NOV)
    assert _usd(first) == [(billing.LINE_FIRST_MONTH, "plus", Decimal(75))]
    assert _usd(second) == [(billing.LINE_MONTHLY, "plus", Decimal(149))]
    assert {line.prices_version for line in first + second} == {"precios-planes-v1"}
    assert charges_for_month(history, date(2026, 9, 1)) == []


def test_upgrade_mid_month_in_a_normal_month_charges_the_difference_70() -> None:
    history = [Assignment("basico", date(2026, 9, 1), _at(2, 9)), Assignment("plus", OCT, _at(15))]
    lines = charges_for_month(history, OCT)
    assert _usd(lines) == [
        (billing.LINE_MONTHLY, "basico", Decimal(79)),
        (billing.LINE_UPGRADE, "plus", Decimal(70)),
    ]
    assert total(lines) == Decimal(149)
    assert _usd(charges_for_month(history, NOV)) == [(billing.LINE_MONTHLY, "plus", Decimal(149))]


def test_upgrade_in_the_first_month_pays_the_new_plan_full_110() -> None:
    history = [Assignment("basico", OCT, _at(2)), Assignment("plus", OCT, _at(15))]
    lines = charges_for_month(history, OCT)
    assert _usd(lines) == [
        (billing.LINE_FIRST_MONTH, "basico", Decimal(39)),
        (billing.LINE_UPGRADE, "plus", Decimal(110)),
    ]
    assert total(lines) == Decimal(149)


def test_two_upgrades_in_one_month_never_charge_twice() -> None:
    history = [
        Assignment("basico", date(2026, 9, 1), _at(2, 9)),
        Assignment("plus", OCT, _at(10)),
        Assignment("pro", OCT, _at(20)),
    ]
    assert total(charges_for_month(history, OCT)) == Decimal(279)


def test_a_downgrade_charges_nothing_mid_month_and_the_lower_price_next_month() -> None:
    history = [Assignment("pro", date(2026, 9, 1), _at(2, 9)), Assignment("basico", NOV, _at(20))]
    assert _usd(charges_for_month(history, OCT)) == [(billing.LINE_MONTHLY, "pro", Decimal(279))]
    assert _usd(charges_for_month(history, NOV)) == [(billing.LINE_MONTHLY, "basico", Decimal(79))]


def test_packs_are_full_price_even_in_the_first_month() -> None:
    history = [Assignment("basico", OCT, _at(2))]
    packs = [PackPurchase("videos_2", _at(20)), PackPurchase("creations_20", _at(3, 11))]
    october = charges_for_month(history, OCT, packs=packs)
    assert _usd(october) == [
        (billing.LINE_FIRST_MONTH, "basico", Decimal(39)),
        (billing.LINE_PACK, "videos_2", Decimal(29)),
    ]
    assert (billing.LINE_PACK, "creations_20", Decimal(12)) in _usd(
        charges_for_month(history, NOV, packs=packs)
    )


def test_a_subscription_without_assignments_is_not_billed() -> None:
    assert charges_for_month([], OCT) == []


def test_the_report_names_the_prices_version_and_shows_cost_against_charge() -> None:
    month = build_month(
        subscription_id=uuid4(),
        name="Bianki",
        period=OCT,
        assignments=[Assignment("plus", OCT, _at(3))],
        cost_by_business={"Bianki": Decimal("31.50"), "Polette": Decimal("12.25")},
    )
    assert month.charged_usd == Decimal(75) and month.cost_usd == Decimal("43.75")
    assert month.margin_usd == Decimal("31.25")
    assert month.prices_versions == "precios-planes-v1"
    text = render([month])
    assert "primer mes" in text and "[precios-planes-v1]" in text and "Polette" in text


# --- the quota the ledger reads ---------------------------------------------------------


def test_quota_for_reads_the_plan() -> None:
    weights = load_weights()
    ids = {"tenant_id": uuid4(), "brand_id": uuid4(), "period": OCT, "weights": weights}
    assert quota_for(**ids) == quota_for(**ids, plan=BASICO)
    got = quota_for(**ids, plan=PRO)
    assert (got.creations, got.videos, got.previews) == (120, 16, 80)


def test_a_weights_table_without_video_quota_keeps_videos_uncapped_on_any_plan() -> None:
    got = quota_for(
        tenant_id=uuid4(),
        brand_id=uuid4(),
        period=OCT,
        weights=load_weights("pesos-creaciones-v1"),
        plan=PRO,
    )
    assert (got.creations, got.videos, got.previews) == (120, 0, 0)


@pytest.mark.parametrize(("code", "quota"), [("basico", 30), ("plus", 60), ("pro", 120)])
def test_the_balance_at_the_start_of_the_month_is_the_plans(code: str, quota: int) -> None:
    ledger = InMemoryCreationsLedger(plan=PLANS.get(code))
    balance = ledger.balance(tenant_id=uuid4(), brand_id=uuid4())
    assert (balance.left, balance.quota) == (quota, quota)


def test_after_an_upgrade_what_was_used_counts_against_the_new_plan() -> None:
    ledger = InMemoryCreationsLedger(used=20, plan=BASICO)
    tenant, brand = uuid4(), uuid4()
    assert ledger.balance(tenant_id=tenant, brand_id=brand).left == 10
    ledger.plan = PLUS
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.left, balance.quota) == (40, 60)


def test_the_plan_quota_pays_the_whole_month_in_the_worst_case_of_the_weights() -> None:
    """D18: the USD cap never blocks — the ledger has no cap at all; a Plus month spends
    its 60 creations and 8 videos whatever they cost. And the cap sits above a month's
    worst case of the CREAR-5 weights (creations at their USD ceiling, every video 10 s
    with a reference video), so the alert means something went off-plan."""
    weights = load_weights()
    for plan in (BASICO, PLUS, PRO):
        ledger = InMemoryCreationsLedger(plan=plan)
        tenant, brand = uuid4(), uuid4()
        for _ in range(plan.creations):
            ledger.charge(
                tenant_id=tenant,
                brand_id=brand,
                draft_id=uuid4(),
                revision=1,
                price=CreationPrice("image", 1),
            )
        for _ in range(plan.videos):
            draft = uuid4()
            ledger.charge(
                tenant_id=tenant,
                brand_id=brand,
                draft_id=draft,
                revision=1,
                price=CreationPrice("generated_video", 0, videos=1),
            )
            assert ledger.charge_videos(
                tenant_id=tenant, brand_id=brand, draft_id=draft, revision=1, videos=1
            )
        balance = ledger.balance(tenant_id=tenant, brand_id=brand)
        assert (balance.left, balance.videos_left) == (0, 0)
        worst = plan.creations * weights.usd_per_creation + plan.videos * (
            weights.generated_video_usd(10, reference_videos=1)
        )
        assert worst < plan.usd_alert_cap, (plan.code, worst)


def test_the_cost_alert_never_touches_the_ledger_or_the_engine_brake() -> None:
    source = (REPO / "packages/api/src/qualify_api/plans/cost_alerts.py").read_text()
    for forbidden in ("creation_charges", "creative_engine_config", "hard_stop", "pause"):
        assert forbidden not in source.split('"""', 2)[2], forbidden


def test_the_alert_says_nothing_was_paused() -> None:
    check = CostCheck(uuid4(), OCT, "basico", Decimal(120), Decimal("121.4"))
    text = alert_text("Bianki", check, "Básico", 2)
    assert check.crossed
    assert "USD 121.40 de USD 120" in text and "no se pausó nada" in text


# --- the owner never sees plans outside Configuración, nor money ---------------------------


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_only_configuracion_reads_the_plan_in_the_app() -> None:
    readers = sorted(
        p.name
        for p in (REPO / "Qualify").glob("*.py")
        if not p.name.startswith("test_")
        and any(m.startswith("qualify_api.plans") for m in _imports_of(p))
    )
    # m-24852129: «Pedir más a Qualify» (ask_more_*) is shared by Configuración and Crear
    assert readers == ["ask_more_provider.py", "settings_provider.py", "settings_vm.py"]
    for path in (REPO / "Qualify").glob("*.py"):
        if path.name.startswith(("test_", "settings_", "ask_more_")):
            continue
        body = path.read_text(encoding="utf-8")
        assert "Tu plan:" not in body and "Pedir más a Qualify" not in body, path.name


def test_the_app_never_imports_the_teams_plan_doors() -> None:
    for path in (REPO / "Qualify").glob("*.py"):
        imports = _imports_of(path)
        for door in ("service", "pack_service", "cli", "report", "cost_alerts", "billing"):
            assert f"qualify_api.plans.{door}" not in imports, (path.name, door)
    assert "qualify_shared.db.admin" not in _imports_of(
        REPO / "packages/api/src/qualify_api/plans/read.py"
    )


def test_configuracion_shows_no_money() -> None:
    # (the locale card's «Moneda de tus precios» and its currency labels are about the
    # owner's own products, not Qualify's plans)
    for name in ("settings_page.py", "settings_state.py", "settings_vm.py"):
        body = (REPO / "Qualify" / name).read_text(encoding="utf-8")
        for word in ("usd_alert_cap", "load_prices", "first_month", "PriceList", "monthly"):
            assert word not in body, (name, word)
    plan_part = (REPO / "Qualify/settings_vm.py").read_text(encoding="utf-8").split("«Tu plan»")[1]
    assert "USD" not in plan_part and "$" not in plan_part


# --- the team's commands ----------------------------------------------------------------


def test_set_plan_needs_reason_and_who() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["set", "--tenant", str(uuid4()), "--plan", "plus"])
    args = parser.parse_args(
        [
            "set",
            "--tenant",
            str(uuid4()),
            "--plan",
            "plus",
            "--reason",
            "r",
            "--by",
            "h@x.co",
            "--from",
            "2026-12",
        ]
    )
    assert args.from_month == DEC
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["set", "--tenant", str(uuid4()), "--plan", "gold", "--reason", "r", "--by", "h"]
        )


def test_plans_without_tenant_prints_the_catalog_without_prices(capsys) -> None:
    assert cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert "Tu plan: Plus · 60 creaciones" in out and "techo de negocios" in out
    assert "149" not in out and "79" not in out
