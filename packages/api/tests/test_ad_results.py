"""Strict Meta observation parsing and exact paid-edit consent, entirely offline."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.promotions import fingerprint
from qualify_api.ads.results import ResultsUnavailable, nonnegative, parse_insight, review_reason
from qualify_api.ads.results_management import PromotionEdit, VerifiedEditApproval, edit_scope_hash
from qualify_api.ads.results_service import ResultScope, _verify_delivery
from qualify_api.connections.ad_accounts import AdConnection
from qualify_api.tenancy.acting import acting_login


@pytest.mark.parametrize(
    "unsafe",
    [
        "<script>robar()</script>",
        "access_token=SECRET",
        "Bearer abc",
        "Motivo\ncon controles",
        "Motivo\u202econ dirección oculta",
        "x" * 301,
        "Consulta https://example.org/?secret=1",
        "Tarjeta 1234 5678 9012 3456",
    ],
)
def test_review_specific_reason_discards_unsafe_provider_text(unsafe):
    from qualify_api.ads.results import safe_review_text

    assert safe_review_text([{"error_summary": unsafe}]) == ""


def test_review_specific_reason_uses_only_bounded_typed_primary_fields():
    from qualify_api.ads.results import review_reason, safe_review_text

    reason = safe_review_text(
        [{"error_code": 100, "error_summary": "El enlace no está disponible.", "mid": "PRIVATE-ID"}]
    )
    assert review_reason("DISAPPROVED", reason) == (
        "Motivo informado por Meta: El enlace no está disponible."
    )
    for invalid in ({"error_summary": "Texto"}, [{}] * 6, [{"error_summary": {"html": "no"}}]):
        assert safe_review_text(invalid) == ""
    assert "Consulta el motivo detallado" in review_reason("DISAPPROVED")


def insight(**changes):
    return {
        "ad_id": "3",
        "account_id": "12",
        "account_currency": "COP",
        "date_start": "2026-11-04",
        "date_stop": "2026-11-04",
        "spend": "1523.45",
        "clicks": "0",
        "reach": "345",
        "impressions": "456",
        "cpc": "0",
        "actions": [{"action_type": "link_click", "value": "0"}],
        **changes,
    }


def scope():
    return ResultScope(
        uuid4(),
        uuid4(),
        uuid4(),
        AdConnection(
            uuid4(),
            uuid4(),
            "42",
            1,
            "active",
            ("ads_management",),
            datetime.now(UTC) + timedelta(days=1),
            True,
        ),
        "12",
        "3",
        "2",
        "1",
        "COP",
        "America/Bogota",
    )


def parse(row):
    return parse_insight(row, ad_id="3", account_id="12", currency="COP")


def test_insights_decimal_money_missing_not_zero_and_actions():
    row = parse(insight())
    assert row.spend == Decimal("1523.45")  # major COP, never divide by100
    assert row.clicks == 0 and row.ctr is None and row.cpc == 0
    assert row.day == date(2026, 11, 4) and row.actions[0]["value"] == "0"
    assert parse(insight(spend="nan", clicks="1.5", reach=True)).spend is None
    assert parse(insight(spend="nan", clicks="1.5", reach=True)).clicks is None
    assert parse(insight(spend="nan", clicks="1.5", reach=True)).reach is None


@pytest.mark.parametrize(
    "changes",
    [
        {"ad_id": "4"},
        {"account_id": "99"},
        {"account_currency": "USD"},
        {"date_stop": "2026-11-05"},
        {"date_start": "invalid", "date_stop": "invalid"},
    ],
)
def test_insights_reject_mismatched_identity_currency_or_day(changes):
    with pytest.raises(ResultsUnavailable):
        parse(insight(**changes))


@pytest.mark.parametrize("value", [True, False, None, "NaN", "Infinity", "-1", {}, []])
def test_missing_or_invalid_metric_is_unknown(value):
    assert nonnegative(value) is None


def test_delivery_requires_exact_parents_and_never_invents_active():
    target = scope()
    payload = {
        "id": "3",
        "account_id": "12",
        "campaign_id": "1",
        "adset_id": "2",
        "status": "ACTIVE",
        "effective_status": "CAMPAIGN_PAUSED",
    }
    assert _verify_delivery(target, payload) == ("CAMPAIGN_PAUSED", "ACTIVE")
    assert _verify_delivery(target, {**payload, "effective_status": "NEW_STATUS"})[0] == "UNKNOWN"
    for key in ("id", "account_id", "campaign_id", "adset_id"):
        with pytest.raises(ResultsUnavailable):
            _verify_delivery(target, {**payload, key: "99"})
    assert "Administrador" in review_reason("DISAPPROVED")
    assert review_reason("ACTIVE") == ""


@pytest.mark.asyncio
async def test_delivery_client_requests_verified_fields_readonly():
    api = FakeMarketingClient(account_id="12")
    api.responses["GET", "3"] = {"id": "3", "account_id": "12"}
    await api.delivery("3")
    assert api.calls[0][0:2] == ("GET", "3")
    assert "ad_review_feedback" in api.calls[0][2]["fields"]


def approval(target, edit, login, now):
    return VerifiedEditApproval(
        target.tenant_id,
        target.promotion_id,
        target.account_id,
        target.connection.version,
        login,
        fingerprint({"action": edit.action, "payload": edit.payload()}),
        now + timedelta(seconds=30),
        True,
        True,
        True,
        "lifetime",
        100,
        500,
        now - timedelta(days=1),
        "fixture-only-v1",
        edit_scope_hash(target),
    )


def test_verified_edit_budget_consent_expiry_currency_units_and_spent_floor():
    now, login, target = datetime.now(UTC), uuid4(), scope()
    edit = PromotionEdit("budget", "lifetime", 1000)
    verified = approval(target, edit, login, now)
    with acting_login(login):
        verified.validate(target, edit, now)
        for changed in (
            replace(verified, confirmed=False),
            replace(verified, eligible=False),
            replace(verified, billing_ready=False),
            replace(verified, spend_minor=2000),
            replace(verified, minimum_budget_minor=2000),
            replace(verified, credential_version=2),
            replace(verified, account_id=uuid4()),
            replace(verified, expires_at=now),
            replace(verified, intent_hash="other"),
        ):
            with pytest.raises(ResultsUnavailable):
                changed.validate(target, edit, now)
        with pytest.raises(ResultsUnavailable):
            verified.validate(target, replace(edit, budget_minor=2000), now)


@pytest.mark.parametrize(
    "edit",
    [
        PromotionEdit("budget", "lifetime", -1),
        PromotionEdit("budget", "daily", True),
        PromotionEdit("bad"),
        PromotionEdit("end_time", end_time=datetime(2026, 1, 1)),
        PromotionEdit("resume", budget_minor=100),
    ],
)
def test_edit_rejects_unsupported_or_unconfirmed_structures(edit):
    with pytest.raises(ResultsUnavailable):
        edit.payload()


def test_end_edit_must_be_future_after_current_start():
    now, login, target = datetime.now(UTC), uuid4(), scope()
    edit = PromotionEdit("end_time", end_time=now - timedelta(seconds=1))
    with acting_login(login), pytest.raises(ResultsUnavailable):
        approval(target, edit, login, now).validate(target, edit, now)
