"""Advertising setup keeps credentials server-side and actions scoped to the active business."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.ad_accounts import AdAccountUnavailable
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.meta_oauth import HttpMetaOAuthClient
from qualify_api.connections.service import ConnectService
from qualify_api.connections.state_token import binding_matches, verify_state
from qualify_api.tenancy.acting import current_acting_login

from . import ad_accounts_provider as provider
from . import ad_accounts_state as state_module
from .ad_accounts_state import AdAccountsState
from .ad_accounts_vm import AdAccountsVM, account_status
from .ad_health_vm import AccountHealthVM
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
        "account_health_for",
        lambda *args: AccountHealthVM(account_status_label="Activa"),
    )
    monkeypatch.setattr(
        provider,
        "ad_account_availability",
        lambda **kwargs: SimpleNamespace(
            enabled=False,
            reason="Falta comprobar el acceso a Instagram.",
            brand_id=TENANT,
            requires_reconnect=True,
        ),
    )
    result = provider.ad_accounts_for(TENANT, CONNECTION)
    serialized = dataclasses.asdict(result)
    assert "never-send" not in repr(serialized)
    assert result.accounts[0].reference == "Cuenta 123456789"
    assert result.accounts[0].currency == "COP"
    assert result.accounts[0].status_label == "Activa"
    assert not result.enabled  # An active Meta account alone does not enable advertising.
    assert result.requires_reconnect


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
    assert verdict.label == "Consultar tu cuenta publicitaria"
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
    monkeypatch.setattr(provider, "require_acting_member", lambda tenant: None)
    monkeypatch.setattr(provider, "require_ads_member", lambda tenant, user: None)
    assert (
        provider.begin_ads_connect(TENANT, CONNECTION, USER, "https://app.qualify.la") == "started"
    )
    assert seen == {
        "tenant_id": TENANT,
        "brand_id": None,
        "user_id": USER,
        "connection_id": CONNECTION,
        "request_ads": False,
        "rerequest": True,
        "browser_origin": "https://app.qualify.la",  # m-24947215: the page's host
    }


def test_account_recovery_uses_principal_config_even_with_separate_ads_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = MetaOAuthSettings(
        app_id="test-app",
        app_secret="test-secret",
        redirect_uri="https://app.qualify.la/api/connections/callback",
        state_secret="test-state-secret",
        config_id="principal-config",
        ads_config_id="legacy-ads-config",
    )
    issued = []
    membership = []
    service = ConnectService(
        settings=settings,
        oauth_client=HttpMetaOAuthClient(settings),
        repository=SimpleNamespace(),
        jti_store=SimpleNamespace(issue=issued.append),
        encryptor=DevEncryptor(),
        verifier=SimpleNamespace(),
        publisher=SimpleNamespace(),
    )
    monkeypatch.setattr(
        "qualify_api.connections.service.list_connections",
        lambda tenant: [
            SimpleNamespace(
                connection_id=CONNECTION,
                brand_id=TENANT,
                platform="instagram",
                external_account_id="17841400000000001",
                reconnect_reason=None,
            )
        ],
    )
    monkeypatch.setattr(provider, "start_connect", service.start_connect)
    monkeypatch.setattr(
        provider, "require_acting_member", lambda tenant: membership.append((tenant,))
    )
    monkeypatch.setattr(
        provider, "require_ads_member", lambda tenant, user: membership.append((tenant, user))
    )
    started = provider.begin_ads_connect(TENANT, CONNECTION, USER, "https://app.qualify.la")
    params = parse_qs(urlsplit(started.authorization_url).query)
    assert params["config_id"] == ["principal-config"]
    assert params["auth_type"] == ["rerequest"]
    payload = verify_state(params["state"][0], settings.state_secret, ttl_seconds=600)
    assert payload.connection_id == CONNECTION
    assert payload.tenant_id == TENANT and payload.user_id == USER
    assert payload.brand_id == TENANT
    assert payload.external_account_id == "17841400000000001"
    assert not payload.request_ads
    assert binding_matches(payload, started.binding_nonce)
    assert issued == [payload.jti]
    assert membership == [(TENANT,), (TENANT, USER)]


@pytest.mark.parametrize("gate", ["require_acting_member", "require_ads_member"])
def test_principal_recovery_rechecks_both_memberships_before_starting_oauth(
    monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    monkeypatch.setattr(provider, "require_acting_member", lambda tenant: None)
    monkeypatch.setattr(provider, "require_ads_member", lambda tenant, user: None)

    def removed(*args: object) -> None:
        raise AdAccountUnavailable("Ya no tienes acceso a este negocio.")

    def unexpected(**kwargs: object) -> None:
        pytest.fail("removed member must not start OAuth or issue a one-shot state")

    monkeypatch.setattr(provider, gate, removed)
    monkeypatch.setattr(provider, "start_connect", unexpected)
    with pytest.raises(AdAccountUnavailable, match="Ya no tienes acceso"):
        provider.begin_ads_connect(TENANT, CONNECTION, USER)


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
            requires_reconnect=False,
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


@pytest.mark.parametrize("requires_reconnect", [False, True])
def test_account_recovery_follows_stored_access_not_displayed_permissions(
    monkeypatch: pytest.MonkeyPatch, requires_reconnect: bool
) -> None:
    """A displayed OAuth capability does not prove a reusable user credential exists."""
    monkeypatch.setattr(provider, "list_ad_accounts", lambda **kwargs: ())
    monkeypatch.setattr(
        provider,
        "ad_account_availability",
        lambda **kwargs: SimpleNamespace(
            enabled=False,
            reason="Actualiza el acceso." if requires_reconnect else "Elige una cuenta.",
            brand_id=TENANT,
            requires_reconnect=requires_reconnect,
        ),
    )
    granted = build_connection_vm(
        connection_id=str(CONNECTION),
        platform="instagram",
        brand="Mi negocio",
        external_username="mi_negocio",
        status="active",
        last_verified_at="Hoy",
        granted_scope_labels=["Anuncios"],
        verdicts=assess_capabilities(frozenset({ScopeKey.BASIC, ScopeKey.ADS})),
    )
    panel = provider.ad_accounts_for(TENANT, CONNECTION)
    projected = provider.with_ad_accounts(granted, panel)
    assert projected.ad_accounts.requires_reconnect is requires_reconnect
    assert not projected.ad_accounts.enabled  # A credential alone cannot select an account.
    assert projected.granted_scopes == granted.granted_scopes


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
@pytest.mark.parametrize("revoked", [False, True])
async def test_verified_revocation_exposes_recovery_but_network_failure_does_not(
    monkeypatch: pytest.MonkeyPatch, revoked: bool
) -> None:
    context = ActionContext()
    context.connections.connections = [
        provider.with_ad_accounts(connection(), AdAccountsVM(enabled=True, brand_id=str(TENANT)))
    ]

    def fail(*args: object) -> None:
        raise AdAccountUnavailable(
            "Actualiza el acceso con Meta." if revoked else "Vuelve a consultar las cuentas.",
            requires_reconnect=revoked,
        )

    monkeypatch.setattr(state_module, "refresh_accounts", fail)
    await AdAccountsState._change(context, str(CONNECTION), account_id="")
    panel = context.connections.connections[0].ad_accounts
    assert panel.requires_reconnect is revoked
    assert panel.enabled is not revoked
    if revoked:
        assert panel.reason == context.errors[str(CONNECTION)]
    assert not context.busy_ids


@pytest.mark.asyncio
async def test_late_revocation_does_not_change_new_business_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()

    def fail(*args: object) -> None:
        context.auth.session_tenant_id = "a0000000-0000-4000-8000-000000000002"
        context.busy_ids = ["new-business-operation"]
        raise AdAccountUnavailable("Actualiza el acceso con Meta.", requires_reconnect=True)

    monkeypatch.setattr(state_module, "refresh_accounts", fail)
    await AdAccountsState._change(context, str(CONNECTION), account_id="")
    assert not context.connections.connections[0].ad_accounts.requires_reconnect
    assert context.errors[str(CONNECTION)] == ""
    assert context.busy_ids == ["new-business-operation"]


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
