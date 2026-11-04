"""Advertising reads and optional consent stay credential-safe and fail closed."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_models.permission_capability import (
    Capability,
    ScopeKey,
    assess_capabilities,
    resolve_scope_keys,
)

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.ad_accounts import (
    AdAccountSummary,
    AdAccountUnavailable,
    AdConnection,
    GraphAdAccountReader,
    _permission_reason,
    account_block_reason,
)
from qualify_api.connections.meta_oauth import HttpMetaOAuthClient
from qualify_api.connections.resolver import build_authenticated_client
from qualify_api.connections.state_token import new_payload, sign_state, verify_state


@pytest.mark.asyncio
async def test_reader_paginates_both_edges_without_following_next_url_or_leaking_token() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Bearer secret"
        assert "secret" not in str(request.url)
        path, after = request.url.path, request.url.params.get("after")
        if path.endswith("/me/adaccounts"):
            if after is None:
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "account_id": "12",
                                "name": "First",
                                "currency": "COP",
                                "timezone_name": "America/Bogota",
                                "account_status": 1,
                                "disable_reason": 0,
                                "funding_source": "99",
                                "business": {"id": "8"},
                            }
                        ],
                        "paging": {
                            "next": "https://evil.invalid/?access_token=secret",
                            "cursors": {"after": "account-page2"},
                        },
                    },
                )
            assert after == "account-page2"
            return httpx.Response(200, json={"data": []})
        assert path.endswith("/act_12/connected_instagram_accounts")
        if after is None:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "1"}],
                    "paging": {
                        "next": "https://evil.invalid/secret",
                        "cursors": {"after": "ig-page2"},
                    },
                },
            )
        return httpx.Response(200, json={"data": [{"id": "42"}]})

    client = build_authenticated_client(
        "secret", scheme="Bearer", transport=httpx.MockTransport(respond)
    )
    try:
        result = await GraphAdAccountReader(client).list_accounts("42")
    finally:
        await client.aclose()
    assert len(calls) == 4
    assert all(r.url.host == "graph.facebook.com" for r in calls)
    assert result[0].instagram_assigned is True
    assert result[0].has_funding_source is True
    assert result[0].business_id == "8"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"error": {"message": "secret"}},
        {"data": None},
        {"data": [{"account_id": "../me", "currency": "COP"}]},
        {"data": [], "paging": {"next": "https://evil.invalid"}},
    ],
)
async def test_bad_or_incomplete_graph_reads_never_yield_authorized_accounts(payload: dict) -> None:
    client = build_authenticated_client(
        "secret",
        scheme="Bearer",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    try:
        with pytest.raises(AdAccountUnavailable) as error:
            await GraphAdAccountReader(client).list_accounts("42")
    finally:
        await client.aclose()
    assert "secret" not in str(error.value)
    assert error.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("funding,expected", [(None, None), ("0", False), ("99", True), ({}, None)])
async def test_missing_funding_is_unknown_not_permission_to_spend(
    funding: object, expected: bool | None
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"account_id": "12", "currency": "COP", "funding_source": funding}]}
            if request.url.path.endswith("/adaccounts")
            else {"data": []},
        )

    client = build_authenticated_client(
        "secret", scheme="Bearer", transport=httpx.MockTransport(respond)
    )
    try:
        rows = await GraphAdAccountReader(client).list_accounts("42")
    finally:
        await client.aclose()
    assert rows[0].has_funding_source is expected
    assert rows[0].instagram_assigned is False


def test_optional_ads_scopes_and_configuration_do_not_change_organic_login() -> None:
    settings = MetaOAuthSettings(
        app_id="app",
        app_secret="secret",
        redirect_uri="https://example.org/cb",
        state_secret="state",
        requested_scopes=("instagram_basic",),
        config_id="organic",
        ads_config_id="advertising",
    )
    oauth = HttpMetaOAuthClient(settings)
    organic = parse_qs(urlsplit(oauth.authorization_url(state="state")).query)
    ads = parse_qs(urlsplit(oauth.authorization_url(state="state", request_ads=True)).query)
    assert organic["scope"] == ["instagram_basic"]
    assert organic["config_id"] == ["organic"]
    assert ads["config_id"] == ["advertising"]
    assert {"ads_read", "ads_management", "business_management", "pages_manage_ads"} <= set(
        ads["scope"][0].split(",")
    )
    payload = new_payload(uuid4(), uuid4(), uuid4(), request_ads=True)
    assert (
        verify_state(sign_state(payload, "secret"), "secret", ttl_seconds=600).request_ads is True
    )
    assert new_payload(uuid4(), uuid4(), uuid4()).request_ads is False


def test_advertising_scope_does_not_mistake_read_permission_for_management() -> None:
    keys, _ = resolve_scope_keys(frozenset({"ads_read"}))
    assert ScopeKey.ADS not in keys
    assert (
        next(v for v in assess_capabilities(keys) if v.capability is Capability.ADVERTISE).enabled
        is False
    )
    keys, _ = resolve_scope_keys(frozenset({"ads_management"}))
    assert (
        next(v for v in assess_capabilities(keys) if v.capability is Capability.ADVERTISE).enabled
        is True
    )


def test_readiness_is_fail_closed_for_revoked_expired_unknown_stale_or_mismatched_assets() -> None:
    now = datetime.now(UTC)
    connection = AdConnection(uuid4(), uuid4(), "42", 1, "active", ("ads_management",), None, True)
    assert _permission_reason(connection) == ""
    for changes in (
        {"status": "revoked"},
        {"has_grant": False},
        {"scopes": ("ads_read",)},
        {"brand_id": None},
        {"expires_at": now - timedelta(seconds=1)},
    ):
        assert _permission_reason(replace(connection, **changes))
    account = AdAccountSummary(
        uuid4(),
        connection.connection_id,
        connection.brand_id,
        "12",
        "Account",
        "COP",
        "America/Bogota",
        1,
        0,
        True,
        True,
        None,
        now,
        True,
    )
    assert account_block_reason(account) == ""
    for changes in (
        {"account_status": None},
        {"disable_reason": None},
        {"disable_reason": 1},
        {"instagram_assigned": None},
        {"has_funding_source": None},
        {"last_checked_at": now - timedelta(hours=1)},
    ):
        assert account_block_reason(replace(account, **changes))
    for field in ("account_status", "disable_reason", "instagram_assigned", "has_funding_source"):
        assert "No pudimos comprobar" in account_block_reason(replace(account, **{field: None}))
    assert "Asigna" in account_block_reason(replace(account, instagram_assigned=False))
    assert "Revisa" in account_block_reason(replace(account, has_funding_source=False))


def test_empty_snapshot_guides_refresh_without_claiming_meta_returned_zero_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.connections import ad_accounts

    tenant, connection_id, brand = uuid4(), uuid4(), uuid4()

    @contextmanager
    def scoped_session(tenant_id: UUID) -> Iterator[object]:
        assert tenant_id == tenant
        yield object()

    connection = AdConnection(
        connection_id, brand, "42", 1, "active", ("ads_management",), None, True
    )
    monkeypatch.setattr(ad_accounts, "tenant_session", scoped_session)
    monkeypatch.setattr(ad_accounts, "_connection", lambda session, cid: connection)
    monkeypatch.setattr(ad_accounts, "list_ad_accounts", lambda **kwargs: ())
    availability = ad_accounts.ad_account_availability(
        tenant_id=tenant, connection_id=connection_id
    )
    assert not availability.enabled
    assert availability.brand_id == brand
    assert availability.reason == (
        "No hay cuentas publicitarias en la lista. "
        "Pulsa «Actualizar cuentas» para consultarlas con Meta."
    )
