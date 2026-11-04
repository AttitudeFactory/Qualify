"""Advertising setup keeps credentials server-side and actions scoped to the active business."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.tenancy.acting import current_acting_login

from . import ad_accounts_provider as provider
from . import ad_accounts_state as state_module
from .ad_accounts_state import AdAccountsState
from .ad_accounts_vm import AdAccountsVM, account_status
from .auth_state import AuthState
from .capabilities import Capability, ScopeKey, assess_capabilities
from .connections_vm import build_connection_vm

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
CONNECTION = UUID("b0000000-0000-4000-8000-000000000001")
ACCOUNT = UUID("c0000000-0000-4000-8000-000000000001")
USER = UUID("d0000000-0000-4000-8000-000000000001")


def connection() -> object:
    return build_connection_vm(
        connection_id=str(CONNECTION),
        platform="instagram",
        brand="Mi negocio",
        external_username="mi_negocio",
        status="active",
        last_verified_at="Hoy",
        granted_scope_labels=[],
        verdicts=assess_capabilities(frozenset({ScopeKey.BASIC}), platform="instagram"),
    )


def test_account_projection_cannot_carry_backend_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = SimpleNamespace(
        id=ACCOUNT,
        name="Cuenta del negocio",
        ad_account_id="123456789",
        currency="COP",
        timezone_name="America/Bogota",
        account_status=1,
        selected=True,
        access_token="never-send-this",
        ciphertext="never-send-this-either",
    )
    monkeypatch.setattr(provider, "list_ad_accounts", lambda **kwargs: (summary,))
    monkeypatch.setattr(
        provider,
        "ad_account_availability",
        lambda **kwargs: SimpleNamespace(
            enabled=False, reason="Falta comprobar el acceso a Instagram.", brand_id=TENANT
        ),
    )
    result = provider.ad_accounts_for(TENANT, CONNECTION)
    serialized = dataclasses.asdict(result)
    assert "never-send" not in repr(serialized)
    assert result.accounts[0].reference == "Cuenta 123456789"
    assert result.accounts[0].currency == "COP"
    assert result.accounts[0].status_label == "Activa"
    assert not result.enabled  # An active Meta account alone does not enable advertising.


def test_runtime_capability_does_not_relax_organic_permissions() -> None:
    row = connection()
    before = [cap for cap in row.enabled_capabilities if cap.key != str(Capability.ADVERTISE)]
    panel = AdAccountsVM(enabled=False, reason="Elige una cuenta para este negocio.")
    blocked = provider.with_ad_accounts(row, panel)
    assert [
        cap for cap in blocked.enabled_capabilities if cap.key != str(Capability.ADVERTISE)
    ] == before
    verdict = next(
        cap for cap in blocked.disabled_capabilities if cap.key == str(Capability.ADVERTISE)
    )
    assert verdict.reason == panel.reason
    ready = provider.with_ad_accounts(blocked, AdAccountsVM(enabled=True))
    assert any(cap.key == str(Capability.ADVERTISE) for cap in ready.enabled_capabilities)
    assert not any(cap.key == str(Capability.ADVERTISE) for cap in ready.disabled_capabilities)


def test_optional_consent_uses_actual_actor_and_specific_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def start(**kwargs: object) -> str:
        seen.update(kwargs)
        return "started"

    monkeypatch.setattr(provider, "start_connect", start)
    assert provider.begin_ads_connect(TENANT, CONNECTION, USER) == "started"
    assert seen == {
        "tenant_id": TENANT,
        "brand_id": None,
        "user_id": USER,
        "connection_id": CONNECTION,
        "request_ads": True,
        "rerequest": True,
    }


def test_unknown_status_does_not_claim_disabled_or_active() -> None:
    assert account_status(None) == ("Estado por comprobar", "neutral")
    assert account_status(999) == ("Estado por comprobar", "neutral")


def test_connections_page_constructs_with_nested_brand_and_account_choices() -> None:
    from .connections_page import connections_index

    # Exercise actual Reflex Vars/foreach/cond composition, beyond pure view models.
    assert connections_index() is not None


def test_unbranded_connection_offers_explicit_existing_brand_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "list_ad_accounts", lambda **kwargs: ())
    monkeypatch.setattr(
        provider,
        "ad_account_availability",
        lambda **kwargs: SimpleNamespace(
            enabled=False,
            reason="Elige una marca.",
            brand_id=None,
        ),
    )
    monkeypatch.setattr(
        provider, "list_ad_brands", lambda **kwargs: (SimpleNamespace(id=TENANT, name="Mi marca"),)
    )
    result = provider.ad_accounts_for(TENANT, CONNECTION)
    assert result.brand_id == ""
    assert result.brands[0].id == str(TENANT)
    assert result.brands[0].name == "Mi marca"
    assert not result.enabled


class ActionContext:
    """Exercise background handler behavior without a running Reflex websocket."""

    def __init__(self) -> None:
        self.busy_ids = []
        self.errors = {}
        self.notices = {}
        self.working = {}
        self.auth = SimpleNamespace(
            session_tenant_id=str(TENANT), _session_user_id=str(USER), _auth_user_id=str(USER)
        )
        self.connections = SimpleNamespace(connections=[connection()])

    async def __aenter__(self) -> ActionContext:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        return self.auth if state_class is AuthState else self.connections


@pytest.mark.asyncio
async def test_choice_is_explicit_scoped_and_updates_its_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    calls = []

    def choose(*args: object) -> None:
        assert current_acting_login() == USER
        calls.append(args)

    monkeypatch.setattr(state_module, "choose_account", choose)
    panel = AdAccountsVM(enabled=True, selected_name="Mi cuenta")
    monkeypatch.setattr(state_module, "ad_accounts_for", lambda *args: panel)
    monkeypatch.setattr(
        state_module,
        "connections_for",
        lambda *args: [provider.with_ad_accounts(connection(), panel)],
    )
    await AdAccountsState._change(context, str(CONNECTION), account_id=str(ACCOUNT))
    assert calls == [(TENANT, CONNECTION, ACCOUNT)]
    assert context.connections.connections[0].ad_accounts == panel
    assert context.notices[str(CONNECTION)] == "Cuenta elegida para este negocio."
    assert not context.busy_ids


@pytest.mark.asyncio
async def test_late_refresh_cannot_repaint_another_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()

    def refresh(*args: object) -> None:
        context.auth.session_tenant_id = "a0000000-0000-4000-8000-000000000002"
        context.busy_ids = ["new-business-operation"]

    monkeypatch.setattr(state_module, "refresh_accounts", refresh)
    monkeypatch.setattr(
        state_module, "ad_accounts_for", lambda *args: AdAccountsVM(selected_name="Old")
    )
    await AdAccountsState._change(context, str(CONNECTION), account_id="")
    assert not context.connections.connections[0].ad_accounts.selected_name
    assert not context.notices[str(CONNECTION)]
    assert context.busy_ids == ["new-business-operation"]


@pytest.mark.asyncio
async def test_failure_clears_busy_and_never_exposes_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()

    def fail(*args: object) -> None:
        raise ValueError("sensitive-database-detail")

    monkeypatch.setattr(state_module, "refresh_accounts", fail)
    await AdAccountsState._change(context, str(CONNECTION), account_id="")
    assert context.errors[str(CONNECTION)] == state_module.REFRESH_FAILED
    assert "sensitive" not in repr(context.errors)
    assert not context.busy_ids
    assert not context.working[str(CONNECTION)]


@pytest.mark.asyncio
async def test_double_click_does_not_duplicate_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.busy_ids = [str(CONNECTION)]

    def unexpected(*args: object) -> None:
        raise AssertionError("service should not be called twice")

    monkeypatch.setattr(state_module, "refresh_accounts", unexpected)
    await AdAccountsState._change(context, str(CONNECTION), account_id="")
    assert context.busy_ids == [str(CONNECTION)]
