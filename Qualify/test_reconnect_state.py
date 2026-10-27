"""Exercise the shared handlers with a state-context double, no DB or provider calls."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from . import reconnect_state
from .reconnect_state import ReconnectState

TENANT = "11111111-1111-4111-8111-111111111111"
CONNECTION = "22222222-2222-4222-8222-222222222222"


class Context:
    def __init__(self, params: dict[str, str] | None = None) -> None:
        self.auth = SimpleNamespace(session_tenant_id=TENANT)
        self.router = SimpleNamespace(
            url=SimpleNamespace(path="/inbox", query_parameters=params or {})
        )
        self.is_starting = False

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, cls: object) -> SimpleNamespace:
        return self.auth


@pytest.mark.asyncio
async def test_shared_action_goes_directly_to_provider_with_session_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    def begin(tenant: UUID, connection: UUID, *, cause: str, origin: str) -> str:
        seen.append((tenant, connection, cause, origin))
        return "https://facebook.example/consent"

    monkeypatch.setattr(reconnect_state, "begin_reconnect", begin)
    state = Context()
    events = [
        event
        async for event in ReconnectState.start_reconnect.fn(
            state, CONNECTION, "permission_missing", "/inbox"
        )
    ]
    assert seen == [(UUID(TENANT), UUID(CONNECTION), "permission_missing", "/inbox")]
    assert len(events) == 1
    assert state.is_starting is False


@pytest.mark.asyncio
async def test_shared_action_refuses_external_origin_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> str:
        raise AssertionError("must not call provider")

    monkeypatch.setattr(reconnect_state, "begin_reconnect", forbidden)
    assert [
        event
        async for event in ReconnectState.start_reconnect.fn(
            Context(), CONNECTION, "auth_expired", "https://evil.example"
        )
    ] == []


@pytest.mark.asyncio
async def test_callback_result_rereads_scoped_account_and_restores_permission_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    def accounts(tenant: UUID) -> list[SimpleNamespace]:
        seen.append(tenant)
        return [
            SimpleNamespace(
                id=CONNECTION,
                platform="instagram",
                external_username="@test",
                status="degraded",
                reconnect_reason="permission_missing",
            )
        ]

    monkeypatch.setattr(reconnect_state, "connections_for", accounts)
    state = Context({"connect": "permission_missing", "reconnect": CONNECTION})
    await ReconnectState.read_result.fn(state)
    assert seen == [UUID(TENANT)]
    assert state.cause == "permission_missing"
    assert state.origin == "/inbox"
    assert "@test" in state.notice
    assert state.show_retry is True


@pytest.mark.asyncio
async def test_result_for_other_tenants_account_displays_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reconnect_state, "connections_for", lambda tenant: [])
    state = Context({"connect": "active", "reconnect": CONNECTION})
    await ReconnectState.read_result.fn(state)
    assert state.notice == ""
    assert state.has_target is False


@pytest.mark.asyncio
async def test_multiple_accounts_never_guess_reconnect_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconnect_state,
        "connections_for",
        lambda tenant: [
            SimpleNamespace(id=CONNECTION, platform="instagram"),
            SimpleNamespace(id="other", platform="instagram"),
        ],
    )
    state = Context()
    await ReconnectState.read_result.fn(state)
    assert state.has_target is False
