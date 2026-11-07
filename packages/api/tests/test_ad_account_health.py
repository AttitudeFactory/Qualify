"""Safe reads, conservative evidence and actionable account health, with no network."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from qualify_api.ads.account_health import (
    PIPELINE_VERSION,
    GraphAccountHealthReader,
    HealthTarget,
    project_health,
)
from qualify_api.ads.health_models import (
    ACCOUNT_STATUS_LABELS,
    HEALTH_FIELDS,
    HealthObservation,
    account_status_label,
    ad_delivery_label,
    disable_reason_label,
)
from qualify_api.connections.ad_accounts import AdAccountUnavailable, AdConnection
from qualify_api.connections.resolver import build_authenticated_client

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def target(observation: HealthObservation | None = None, **changes) -> HealthTarget:
    connection = AdConnection(
        uuid4(), uuid4(), "42", 1, "active", ("ads_management",), NOW + timedelta(days=1), True
    )
    snapshot = (
        asdict(observation)
        | {
            "source_id": "act_12",
            "api_version": "v26.0",
            "pipeline_version": PIPELINE_VERSION,
        }
        if observation
        else None
    )
    return replace(
        HealthTarget(
            uuid4(),
            uuid4(),
            connection,
            "12",
            "My account",
            "COP",
            True,
            snapshot,
            NOW if observation else None,
            1,
            False,
        ),
        **changes,
    )


def observation(**changes) -> HealthObservation:
    return replace(HealthObservation("COP", 1, 0, True, None, None), **changes)


@pytest.mark.parametrize("status", ACCOUNT_STATUS_LABELS)
def test_all_verified_account_codes_have_spanish_labels(status) -> None:
    assert account_status_label(status) == ACCOUNT_STATUS_LABELS[status]
    health = project_health(target(observation(account_status=status)), now=NOW)
    assert health.can_promote is (status == 1)
    assert health.blocks_preparation is (status != 1)
    assert health.action_url.startswith("https://business.facebook.com/")
    assert health.checked_at == NOW


@pytest.mark.parametrize("code", [None, -1, True, "1", 8, 201, 202, 555])
def test_unknown_account_codes_never_claim_ready_or_permanent_closure(code) -> None:
    assert account_status_label(code) == "Estado pendiente de comprobar"
    if code is None or type(code) is int and code >= 0:
        health = project_health(target(observation(account_status=code)), now=NOW)
        assert not health.can_promote
        assert not health.blocks_preparation
    assert account_status_label(101) == "No disponible"


@pytest.mark.parametrize("code", list(range(16)) + [None, -1, 999, True, "0"])
def test_disable_codes_have_safe_spanish_not_invented_diagnoses(code) -> None:
    label = disable_reason_label(code)
    assert label
    assert "POLICY" not in label and "comprometida" not in label


@pytest.mark.parametrize("funding", [None, "0", 0, "", {}, {"card": "bad"}, -1, True, "abc"])
def test_absent_zero_malformed_funding_is_unknown_not_missing_card(funding) -> None:
    normalized = HealthObservation.from_graph(
        {
            "account_id": "12",
            "currency": "COP",
            "account_status": 1,
            "disable_reason": 0,
            "funding_source": funding,
            "amount_spent": "1200",
            "spend_cap": "5000",
        },
        account_id="12",
        currency="COP",
    )
    assert normalized.funding_present is None
    assert normalized.amount_spent_minor is None
    assert normalized.amount_spent_raw == "1200"
    health = project_health(target(normalized), now=NOW)
    assert not health.can_promote and not health.blocks_preparation
    assert health.amount_spent_label == "Importe pendiente de comprobar"


def test_presence_is_not_payment_guarantee_and_cap_is_not_inferred_exhausted() -> None:
    normalized = HealthObservation.from_graph(
        {
            "account_id": "12",
            "currency": "COP",
            "account_status": 1,
            "disable_reason": 0,
            "funding_source": "888",
            "amount_spent": "9000",
            "spend_cap": "5000",
            "funding_source_details": {"card_number": "NEVER_COPY_THIS"},
        },
        account_id="12",
        currency="COP",
    )
    health = project_health(target(normalized), now=NOW)
    assert health.can_promote
    assert "no garantiza" in health.reason
    assert health.spend_cap_minor is None
    assert "NEVER_COPY_THIS" not in repr(normalized)
    assert "888" not in repr(normalized)


def test_verified_normalized_missing_or_billing_attention_blocks_form() -> None:
    for normalized in (observation(funding_present=False), observation(pending_billing=True)):
        health = project_health(target(normalized), now=NOW)
        assert health.blocks_preparation and not health.can_promote
        assert health.action_label == "Revisar pagos"
        assert "/billing_hub/" in health.action_url
    assert ad_delivery_label("PENDING_BILLING_INFO") == "Falta información de pago"


@pytest.mark.parametrize(
    "change",
    [
        {"health_version": 0},
        {"checked_at": NOW - timedelta(days=1)},
        {"checked_at": NOW + timedelta(seconds=1)},
        {"snapshot": None},
    ],
)
def test_stale_old_version_future_or_absent_evidence_never_enables_ads(change) -> None:
    health = project_health(target(observation(), **change), now=NOW)
    assert not health.can_promote and health.stale and not health.blocks_preparation


def test_failed_read_retains_last_observed_time_but_not_green_status() -> None:
    health = project_health(target(observation(), read_failed=True), now=NOW)
    assert health.checked_at == NOW and health.refresh_error
    assert not health.can_promote and health.tone == "warn" and health.status == "unavailable"


def test_snapshot_allowlist_and_types_reject_nested_provider_or_card_payload() -> None:
    base = target(observation())
    for extra in ({"card_number": "bad"}, {"funding_present": {"card": "bad"}}):
        health = project_health(replace(base, snapshot=base.snapshot | extra), now=NOW)
        assert health.stale and not health.can_promote
    with pytest.raises(ValueError):
        observation(funding_present={"card": "bad"})


@pytest.mark.asyncio
async def test_graph_adapter_only_selects_allowlist_and_owned_ad_status_gets() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/act_12"):
            assert request.url.params["fields"] == HEALTH_FIELDS
            assert "funding_source_details" not in request.url.params["fields"]
            return httpx.Response(
                200,
                json={
                    "account_id": "12",
                    "currency": "COP",
                    "account_status": 1,
                    "disable_reason": 0,
                    "funding_source": "88",
                    "amount_spent": "10",
                    "spend_cap": "0",
                    "funding_source_details": {"card_number": "bad"},
                },
            )
        assert request.url.path.endswith("/123")
        assert request.url.params["fields"] == "id,account_id,effective_status"
        return httpx.Response(
            200,
            json={
                "id": "123",
                "account_id": "12",
                "effective_status": "PENDING_BILLING_INFO",
            },
        )

    client = build_authenticated_client(
        "fixture", scheme="Bearer", transport=httpx.MockTransport(handler)
    )
    try:
        result = await GraphAccountHealthReader(client).read(target(owned_ad_ids=("123",)))
    finally:
        await client.aclose()
    assert result.pending_billing is True and len(calls) == 2
    assert "card_number" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"account_id": "13", "currency": "COP"},
        {"account_id": "12", "currency": "USD"},
        {"error": {"message": "private token details"}},
    ],
)
async def test_graph_identity_currency_and_provider_errors_are_redacted(payload) -> None:
    client = build_authenticated_client(
        "fixture",
        scheme="Bearer",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    try:
        with pytest.raises(AdAccountUnavailable) as caught:
            await GraphAccountHealthReader(client).read(target())
        assert "private token" not in str(caught.value)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_green_health_does_not_enable_real_preview_or_activation(monkeypatch) -> None:
    from qualify_api.ads import account_health, live_wizard, wizard

    source = wizard.PromotionSource(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "42",
        "99",
        "text",
        "IG",
        ad_account_id=uuid4(),
        currency="COP",
        timezone_name="America/Bogota",
        unavailable_reason="",
    )
    monkeypatch.setattr(wizard, "require_acting_member", lambda tenant: None)
    monkeypatch.setattr(wizard, "list_promotion_sources", lambda **kwargs: (source,))

    async def green(**kwargs):
        return project_health(target(observation()), now=NOW)

    monkeypatch.setattr(account_health, "refresh_account_health", green)

    def no_gateway_without_actor(**kwargs):
        pytest.fail("Green account health cannot bypass authenticated actor authorization")

    monkeypatch.setattr(live_wizard, "LiveWizardGateway", no_gateway_without_actor)
    form = wizard.WizardForm(
        "https://example.com",
        "Cúcuta",
        NOW + timedelta(days=1),
        NOW + timedelta(days=2),
        budget_minor=10000,
    )
    with pytest.raises(wizard.WizardUnavailable, match="Vuelve a entrar"):
        await wizard.prepare_promotion_preview(
            tenant_id=uuid4(),
            content_draft_id=source.content_draft_id,
            publish_attempt_id=source.publish_attempt_id,
            form=form,
            approved_by=uuid4(),
            request_key="health",
        )
    with pytest.raises(wizard.WizardUnavailable, match="Vuelve a entrar"):
        await wizard.confirm_promotion(
            tenant_id=uuid4(),
            promotion_id=uuid4(),
            review_id=uuid4(),
            approved_by=uuid4(),
            confirm_charge=True,
        )


def test_read_only_cli_requires_explicit_tenant_and_uses_system_context(
    monkeypatch, capsys
) -> None:
    from qualify_api.ads import health_cli
    from qualify_api.tenancy.acting import current_acting_login, require_acting_member

    tenant = uuid4()
    seen = []

    async def daily(*, tenant_id):
        assert current_acting_login() is None
        require_acting_member(tenant_id)  # Established trusted system/worker semantics.
        seen.append(tenant_id)
        return ()

    monkeypatch.setattr(health_cli, "refresh_daily_account_health", daily)
    monkeypatch.setattr("sys.argv", ["health_cli", "--tenant", str(tenant)])
    health_cli.main()
    assert seen == [tenant] and '"checked": 0' in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["health_cli"])
    with pytest.raises(SystemExit) as caught:
        health_cli.main()
    assert caught.value.code == 2


@pytest.mark.asyncio
async def test_optional_ad_read_failure_never_erases_account_restriction_or_claims_ready() -> None:
    def handler(request):
        if request.url.path.endswith("/act_12"):
            return httpx.Response(
                200,
                json={
                    "account_id": "12",
                    "currency": "COP",
                    "account_status": 1,
                    "disable_reason": 0,
                    "funding_source": "55",
                },
            )
        return httpx.Response(403, json={"error": {"message": "do not expose"}})

    client = build_authenticated_client(
        "fixture", scheme="Bearer", transport=httpx.MockTransport(handler)
    )
    try:
        normalized = await GraphAccountHealthReader(client).read(target(owned_ad_ids=("123",)))
    finally:
        await client.aclose()
    assert normalized.account_status == 1 and normalized.pending_billing is None
    assert not project_health(target(normalized), now=NOW).can_promote
