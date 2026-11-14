"""Account observations cannot authorize payment or leak provider payment material."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.ads.wizard import PromotionSource
from qualify_api.tenancy.acting import acting_login, current_acting_login

from . import ad_accounts_provider as accounts_provider
from . import ad_accounts_state as accounts_state
from . import ad_health_provider as health_provider
from . import connections_provider, connections_state, promotion_provider
from . import promotion_state as promotion_state
from .ad_accounts_state import AdAccountsState
from .ad_accounts_vm import AdAccountsVM, AdAccountVM
from .ad_health_vm import HEALTH_REFRESH_FAILED, AccountHealthVM, checked_label, safe_billing_url
from .promotion_page import _blocked_preparation, promotion_index
from .promotion_state import PromotionState
from .test_ad_accounts_ui import ACCOUNT, CONNECTION, TENANT, USER, ActionContext, connection
from .test_promotion_wizard import ActionContext as PromotionContext


def healthy(**changes: object) -> SimpleNamespace:
    values = dict(
        account_id=ACCOUNT,
        status="active",
        label="Cuenta activa",
        tone="ok",
        reason="La cuenta tiene un método de pago registrado.",
        checked_at=datetime(2026, 11, 4, 15, tzinfo=UTC),
        stale=False,
        can_promote=True,
        blocks_preparation=False,
        account_status_label="Activa",
        disable_reason_label="Sin restricciones informadas",
        amount_spent_label="$25.000 COP",
        spend_cap_label="Sin límite informado",
        amount_spent_minor=2_500_000,
        spend_cap_minor=0,
        billing_url="https://business.facebook.com/billing_hub/payment_settings/?asset_id=123",
        action_url="https://business.facebook.com/billing_hub/payment_settings/?asset_id=123",
        action_label="Revisar pagos",
        refresh_error=False,
        card_number="never-send-card-number",
        funding_source_details={"card": "never-send-details"},
        access_token="never-send-token",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def account(health: AccountHealthVM = AccountHealthVM()) -> AdAccountVM:
    return AdAccountVM(
        str(ACCOUNT),
        "Mi cuenta",
        "Cuenta 123",
        "COP",
        "America/Bogota",
        "Activa",
        "ok",
        True,
        health,
    )


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "http://business.facebook.com/billing_hub/payment_settings/",
        "https://business.facebook.com.evil.example/billing_hub/payment_settings/",
        "https://business.facebook.com:8443/billing_hub/payment_settings/",
        "https://user:password@business.facebook.com/billing_hub/payment_settings/",
        "https://business.facebook.com/billing_hub/?access_token=secret",
        "https://business.facebook.com/billing_hub/?next=https://evil.example",
        "https://business.facebook.com/billing_hub/?ACCESS_TOKEN=secret",
        "https://business.facebook.com/unrelated",
    ],
)
def test_payment_action_cannot_redirect_or_carry_login_material(value: str) -> None:
    assert safe_billing_url(value) == ""


def test_health_projection_is_a_whitelist_and_dates_have_explicit_zone() -> None:
    result = health_provider.project_health(healthy(), "America/Bogota")
    assert result.checked_label == "04/11/2026 · 10:00 (America/Bogota)"
    assert result.billing_url.startswith("https://business.facebook.com/")
    assert "never-send" not in repr(asdict(result))
    assert not {"card_number", "funding_source_details", "access_token"}.intersection(
        asdict(result)
    )
    assert checked_label(datetime(2026, 11, 4, 15, tzinfo=UTC), "unknown") == (
        "04/11/2026 · 15:00 (UTC)"
    )
    assert checked_label(datetime(2026, 11, 4, 15)) == "Todavía no se ha comprobado"


@pytest.mark.parametrize("changes", [{"stale": True}, {"refresh_error": True}])
def test_stale_or_failed_refresh_never_becomes_promotable(changes: dict) -> None:
    assert not health_provider.project_health(healthy(**changes)).can_promote


def test_unverified_money_is_not_projected_as_an_account_amount() -> None:
    result = health_provider.project_health(healthy(amount_spent_minor=None, spend_cap_minor=None))
    assert result.amount_spent_label == result.spend_cap_label == ""


def test_restriction_action_is_account_review_rather_than_payment_settings() -> None:
    result = health_provider.project_health(
        healthy(
            status="restricted",
            action_label="Revisar cuenta",
            action_url="https://business.facebook.com/ads/manager/account_settings/?act=123",
        )
    )
    assert result.action_label == "Revisar cuenta en Meta"
    assert "account_settings" in result.action_url


def test_selected_account_health_can_restrict_but_never_replace_permission_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        id=ACCOUNT,
        name="Mi cuenta",
        ad_account_id="123",
        currency="COP",
        timezone_name="America/Bogota",
        account_status=1,
        selected=True,
    )
    monkeypatch.setattr(accounts_provider, "list_ad_accounts", lambda **kw: (row,))
    verdict = SimpleNamespace(enabled=True, reason="", brand_id=TENANT, requires_reconnect=False)
    monkeypatch.setattr(accounts_provider, "ad_account_availability", lambda **kw: verdict)
    monkeypatch.setattr(accounts_provider, "account_health_for", lambda *args: AccountHealthVM())
    assert not accounts_provider.ad_accounts_for(TENANT, CONNECTION).enabled
    monkeypatch.setattr(
        accounts_provider,
        "account_health_for",
        lambda *args: health_provider.project_health(healthy()),
    )
    assert accounts_provider.ad_accounts_for(TENANT, CONNECTION).enabled
    verdict.enabled = False
    verdict.reason = "Falta el permiso para anunciar."
    panel = accounts_provider.ad_accounts_for(TENANT, CONNECTION)
    assert not panel.enabled and panel.reason == verdict.reason


@pytest.mark.asyncio
async def test_health_refresh_uses_authenticated_actor_and_local_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.connections.connections[0].ad_accounts = AdAccountsVM(accounts=[account()])
    seen = []

    def refresh(*args: object) -> AccountHealthVM:
        assert current_acting_login() == USER
        seen.append(args)
        return health_provider.project_health(healthy())

    panel = AdAccountsVM(accounts=[account()], selected_name="Mi cuenta")
    monkeypatch.setattr(accounts_state, "refresh_health", refresh)
    monkeypatch.setattr(accounts_state, "ad_accounts_for", lambda *args: panel)
    await AdAccountsState.refresh_health.fn(context, str(CONNECTION), str(ACCOUNT))
    assert seen == [(TENANT, ACCOUNT, "America/Bogota")]
    assert context.connections.connections[0].ad_accounts == panel
    assert context.notices[str(CONNECTION)] == "Estado de la cuenta actualizado."
    assert not context.busy_ids


@pytest.mark.asyncio
async def test_foreign_card_account_never_reaches_refresh_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    calls = []
    monkeypatch.setattr(accounts_state, "refresh_health", lambda *args: calls.append(args))
    await AdAccountsState.refresh_health.fn(context, str(CONNECTION), str(ACCOUNT))
    assert not calls and not context.busy_ids


@pytest.mark.asyncio
async def test_late_health_refresh_cannot_repaint_or_clear_another_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    original = AdAccountsVM(accounts=[account()])
    context.connections.connections[0].ad_accounts = original

    def refresh(*args: object) -> AccountHealthVM:
        context.auth.session_tenant_id = str(ACCOUNT)
        context.busy_ids = ["new-business-operation"]
        return health_provider.project_health(healthy())

    monkeypatch.setattr(accounts_state, "refresh_health", refresh)
    monkeypatch.setattr(accounts_state, "ad_accounts_for", lambda *args: AdAccountsVM())
    await AdAccountsState.refresh_health.fn(context, str(CONNECTION), str(ACCOUNT))
    assert context.connections.connections[0].ad_accounts == original
    assert context.busy_ids == ["new-business-operation"]
    assert not context.notices[str(CONNECTION)]


@pytest.mark.asyncio
async def test_failed_health_read_is_not_a_success_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.connections.connections[0].ad_accounts = AdAccountsVM(accounts=[account()])
    health = health_provider.project_health(healthy(refresh_error=True))
    monkeypatch.setattr(accounts_state, "refresh_health", lambda *args: health)
    monkeypatch.setattr(accounts_state, "ad_accounts_for", lambda *args: AdAccountsVM())
    await AdAccountsState.refresh_health.fn(context, str(CONNECTION), str(ACCOUNT))
    assert context.errors[str(CONNECTION)] == HEALTH_REFRESH_FAILED
    assert not context.notices[str(CONNECTION)] and not context.busy_ids


def source(source_id: UUID, account_id: UUID | None = ACCOUNT) -> PromotionSource:
    return PromotionSource(
        publish_attempt_id=source_id,
        content_draft_id=USER,
        connection_id=CONNECTION,
        brand_id=TENANT,
        instagram_user_id="123",
        source_media_id="456",
        ad_account_id=account_id,
        account_label="@negocio",
        caption="Una oferta",
        account_name="Mi cuenta",
        currency="COP",
        default_link_url="",
        timezone_name="America/Bogota",
        published_at=None,
        unavailable_reason="Falta comprobar la integración con Meta.",
    )


def test_direct_wizard_entry_refreshes_each_selected_account_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = (source(USER), source(CONNECTION))
    calls = []
    monkeypatch.setattr(promotion_provider, "messaging_destinations", lambda *args: [])
    monkeypatch.setattr(promotion_provider, "list_promotion_sources", lambda **kw: sources)
    monkeypatch.setattr(
        promotion_provider,
        "read_business_locale",
        lambda *args: SimpleNamespace(timezone="America/Bogota"),
    )
    missing = AccountHealthVM(blocks_preparation=True, label="Revisa el método de pago")
    monkeypatch.setattr(
        promotion_provider,
        "refresh_health",
        lambda *args: calls.append(args) or missing,
    )
    rows, zone = promotion_provider.load_sources(TENANT, USER, None, True)
    assert calls == [(TENANT, ACCOUNT, "America/Bogota")]
    assert all(row.health.blocks_preparation for row in rows)
    assert zone == "America/Bogota"


def test_no_ad_account_still_allows_local_preparation_without_a_remote_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(promotion_provider, "messaging_destinations", lambda *args: [])
    monkeypatch.setattr(
        promotion_provider, "list_promotion_sources", lambda **kw: (source(USER, None),)
    )
    monkeypatch.setattr(promotion_provider, "read_business_locale", lambda *args: None)
    calls = []
    monkeypatch.setattr(promotion_provider, "refresh_health", lambda *args: calls.append(args))
    rows, _ = promotion_provider.load_sources(TENANT, USER, None, True)
    assert not calls and not rows[0].health.blocks_preparation


@pytest.mark.asyncio
async def test_direct_deep_link_checks_health_before_presenting_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = PromotionContext()
    context._loaded_context = ("", "", "")
    context.draft_id = str(USER)
    context.router = SimpleNamespace(url=SimpleNamespace(query_parameters={"paso": "4"}))
    context.read_step = lambda: PromotionState.read_step.fn(context)
    context.choose_source = lambda value: PromotionState.choose_source.fn(context, value)
    blocked = replace(context.sources[0], health=AccountHealthVM(blocks_preparation=True))
    calls = []

    def load(*args: object, **_: object) -> tuple[list, str]:
        calls.append(args)
        return [blocked], "America/Bogota"

    monkeypatch.setattr(promotion_state, "load_sources", load)
    _ = [event async for event in PromotionState.load.fn(context)]
    assert calls[0][-1] is True
    assert context.preparation_blocked
    assert not context.reviewed and not context.loading


@pytest.mark.asyncio
async def test_connections_health_read_inherits_actual_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.is_loading = False
    context.load_error = ""
    calls = []

    def load(tenant_id: UUID, *, refresh_ad_health: bool = False) -> list:
        assert current_acting_login() == USER
        assert refresh_ad_health is True
        calls.append(tenant_id)
        return []

    monkeypatch.setattr(connections_state, "connections_for", load)
    await connections_state.ConnectionsState.load_connections.fn(context)
    assert calls == [TENANT] and context.connections == []
    assert not context.is_loading and not context.load_error


@pytest.mark.parametrize("refresh_due", [False, True])
def test_shared_connection_projection_never_gains_an_implicit_remote_refresh(
    monkeypatch: pytest.MonkeyPatch, refresh_due: bool
) -> None:
    """Planner/inbox label reads stay cached; Tus redes opts in under a real login."""

    @contextmanager
    def session(tenant_id: UUID) -> Iterator[SimpleNamespace]:
        assert tenant_id == TENANT
        yield SimpleNamespace(
            execute=lambda *args: SimpleNamespace(all=lambda: [(object(), "Mi marca", None)])
        )

    row = SimpleNamespace(
        id=ACCOUNT,
        name="Mi cuenta",
        ad_account_id="123",
        currency="COP",
        timezone_name="America/Bogota",
        account_status=1,
        selected=True,
    )
    monkeypatch.setattr(connections_provider, "tenant_session", session)
    monkeypatch.setattr(connections_provider, "_to_vm", lambda *args: connection())
    monkeypatch.setattr(accounts_provider, "list_ad_accounts", lambda **kw: (row,))
    monkeypatch.setattr(
        accounts_provider,
        "ad_account_availability",
        lambda **kw: SimpleNamespace(
            enabled=True, reason="", brand_id=TENANT, requires_reconnect=False
        ),
    )
    calls = []
    health = AccountHealthVM(can_promote=True, stale=False)
    monkeypatch.setattr(
        accounts_provider, "account_health_for", lambda *args: calls.append("cached") or health
    )

    def daily(*args: object) -> AccountHealthVM:
        assert current_acting_login() == USER
        calls.append("remote")
        return health

    monkeypatch.setattr(accounts_provider, "daily_health_for", daily)
    if refresh_due:
        with acting_login(USER):
            result = connections_provider.connections_for(TENANT, refresh_ad_health=True)
    else:
        assert current_acting_login() is None
        result = connections_provider.connections_for(TENANT)
    assert len(result) == 1
    assert calls == (["remote"] if refresh_due else ["cached"])


def test_explicit_ui_health_refresh_rejects_missing_login_before_remote_access() -> None:
    assert current_acting_login() is None
    with pytest.raises(connections_provider.NoActingUser):
        connections_provider.connections_for(TENANT, refresh_ad_health=True)


@pytest.mark.asyncio
async def test_confirmed_payment_attention_blocks_steps_and_remote_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = PromotionContext()
    context.sources = [replace(context.sources[0], health=AccountHealthVM(blocks_preparation=True))]
    context.confirm_charge = True
    calls = []
    monkeypatch.setattr(promotion_state, "confirm_review", lambda *args: calls.append(args))
    assert PromotionState.next_step.fn(context) is None
    await context._remote(confirm=True)
    assert not calls


def test_blocked_route_has_fix_action_without_presenting_the_four_step_form() -> None:
    blocked = repr(_blocked_preparation().render())
    assert "Revisa la cuenta publicitaria" in blocked
    assert "action_label" in blocked
    assert "Volver a comprobar" in blocked
    assert "promotion-link_url" not in blocked
    assert promotion_index() is not None
