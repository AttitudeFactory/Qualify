"""m-24852145: Configuración › «Tu plan» — the plan's name and what it brings, per plan,
the «Pedir más a Qualify» request, and the balance each plan starts the month with."""

from __future__ import annotations

import pathlib
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.creations import InMemoryCreationsLedger
from qualify_api.plans.catalog import load_plans

from . import settings_provider
from .creative_vm import creations_left_label
from .settings_vm import ASK_MORE_BUTTON, plan_label

_HERE = pathlib.Path(__file__).resolve().parent
PLANS = load_plans()


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("basico", "Tu plan: Básico · 30 creaciones, 4 videos y 20 vistas previas al mes"),
        ("plus", "Tu plan: Plus · 60 creaciones, 8 videos y 40 vistas previas al mes"),
        ("pro", "Tu plan: Pro · 120 creaciones, 16 videos y 80 vistas previas al mes"),
    ],
)
def test_the_plan_row_reads_literally(code: str, text: str) -> None:
    assert plan_label(PLANS.get(code)) == text


def test_the_button_says_pedir_mas_a_qualify() -> None:
    assert ASK_MORE_BUTTON == "Pedir más a Qualify"
    page = (_HERE / "settings_page.py").read_text(encoding="utf-8")
    assert "SV.ASK_MORE_BUTTON" in page and "SettingsState.request_more" in page


@pytest.mark.parametrize(("code", "quota"), [("plus", 60), ("pro", 120)])
def test_the_month_starts_with_the_plans_quota(code: str, quota: int) -> None:
    balance = InMemoryCreationsLedger(plan=PLANS.get(code)).balance(
        tenant_id=uuid4(), brand_id=uuid4()
    )
    assert creations_left_label(balance.left, balance.quota) == (
        f"Te quedan {quota} de {quota} este mes"
    )


def test_pedir_mas_creates_the_more_creations_request(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_create(**kwargs: object) -> str:
        seen.update(kwargs)
        return "ticket"

    monkeypatch.setattr(settings_provider, "create_support_request", fake_create)
    tenant = UUID("00000000-0000-4000-8000-000000000145")
    assert settings_provider.request_more(tenant, email="dueno@negocio.co", plan_code="plus")
    assert seen == {
        "tenant_id": tenant,
        "topic": "more_creations",
        "contact_email": "dueno@negocio.co",
        "context": {"screen": "settings", "plan": "plus"},
    }


def test_the_notice_after_pedir_mas_is_d13() -> None:
    # D13 (docs/modelo-cobro-generacion.md): the owner learns what will reach them
    from .settings_vm import ASK_MORE_SENT

    assert ASK_MORE_SENT == "Listo. Te escribimos a tu correo con el enlace de pago."


def test_the_plan_is_read_in_the_business_month_not_utc(monkeypatch) -> None:
    from datetime import UTC, date, datetime

    from qualify_api.tenancy.locale import BusinessLocale

    seen: dict[str, object] = {}

    def fake_plan(tenant_id: UUID, period: date) -> object:
        seen["period"] = period
        return PLANS.default

    monkeypatch.setattr(
        settings_provider,
        "read_business_locale",
        lambda _t: BusinessLocale(country="CO", timezone="America/Bogota", currency="COP"),
    )
    monkeypatch.setattr(settings_provider, "business_plan", fake_plan)
    # 31 Oct 23:30 in Bogotá is already 1 Nov in UTC: the ledger still counts October
    settings_provider.read_plan(uuid4(), now=datetime(2026, 11, 1, 4, 30, tzinfo=UTC))
    assert seen["period"] == date(2026, 10, 1)


def test_the_plan_falls_back_to_utc_without_a_locale(monkeypatch) -> None:
    from datetime import UTC, date, datetime

    seen: dict[str, object] = {}
    monkeypatch.setattr(settings_provider, "read_business_locale", lambda _t: None)
    monkeypatch.setattr(
        settings_provider,
        "business_plan",
        lambda _t, period: seen.setdefault("period", period) and PLANS.default,
    )
    settings_provider.read_plan(uuid4(), now=datetime(2026, 11, 1, 4, 30, tzinfo=UTC))
    assert seen["period"] == date(2026, 11, 1)
