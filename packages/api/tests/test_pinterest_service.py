"""OAuth lifecycle/tenant/callback/refresh tests with no network or real credentials."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.locks import RefreshLock
from qualify_api.connections.state_token import InvalidState, JtiStore
from qualify_api.pinterest.client import Board, FakePinterestClient, Pin, PinterestError
from qualify_api.pinterest.oauth import HttpOAuthClient, Tokens
from qualify_api.pinterest.repository import MemoryRepository
from qualify_api.pinterest.service import PendingFlows, PinterestService
from qualify_api.pinterest.settings import PinterestSettings

SCOPES = ("boards:read", "pins:read", "user_accounts:read")


class RedisFake:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, name: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    def getdel(self, name: str) -> str | None:
        return self.values.pop(name, None)

    def eval(self, script: str, numkeys: int, *args: str) -> object:
        if "getdel" in script:
            return self.values.pop(args[0], None)
        if "then return 1" in script:
            return int(self.values.get(args[0]) == args[1])
        if len(args) == 1:
            return int(self.values.pop(args[0], None) is not None)
        if self.values.get(args[0]) == args[1]:
            self.values.pop(args[0], None)
            return 1
        return 0


class OAuthFake:
    def __init__(self) -> None:
        self.refresh_count = 0
        self.exchange_count = 0
        self.error: PinterestError | None = None
        self.tokens = Tokens(
            "access-fixture",
            "refresh-fixture",
            datetime.now(UTC) + timedelta(days=1),
            datetime.now(UTC) + timedelta(days=60),
            SCOPES,
        )

    def authorization_url(self, state: str) -> str:
        return "https://www.pinterest.com/oauth/?state=" + state

    def exchange(self, code: str) -> Tokens:
        self.exchange_count += 1
        if self.error:
            raise self.error
        return self.tokens

    def refresh(self, refresh_token: str) -> Tokens:
        self.refresh_count += 1
        if self.error:
            raise self.error
        return self.tokens


@pytest.fixture
def rig() -> tuple[PinterestService, MemoryRepository, OAuthFake, RedisFake]:
    settings = PinterestSettings(
        "app", "app-secret", "https://app.example/api/connections/pinterest/callback", "s" * 32
    )
    repo, oauth, redis = MemoryRepository(), OAuthFake(), RedisFake()
    service = PinterestService(
        settings=settings,
        repository=repo,
        oauth=oauth,
        jti=JtiStore(redis),
        encryptor=DevEncryptor(),
        refresh_lock=RefreshLock(redis),
        pending=PendingFlows(redis),
        client_factory=lambda _: FakePinterestClient(
            boards=(Board("12", "Ideas"),), pins={"12": (Pin("123"),)}
        ),
    )
    return service, repo, oauth, redis


def connect(service: PinterestService, tenant: UUID) -> tuple[str, str]:
    started = service.start_connect(tenant_id=tenant, user_id=uuid4())
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    service.handoff(state, binding_nonce=started.binding_nonce)
    service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    return state, started.binding_nonce


def test_grant_encrypts_per_tenant_and_selection_checks_authorized_page(rig: tuple) -> None:
    service, repo, oauth, _ = rig
    a, b = uuid4(), uuid4()
    connect(service, a)
    assert service.connection(a).status == "active"
    assert b"access-fixture" not in repo.credentials[a].ciphertext
    assert "access-fixture" not in repr(repo.credentials[a])
    assert service.boards(a).items == (Board("12", "Ideas"),)
    assert service.resolve_pin(a, "12", "123").id == "123"
    with pytest.raises(PinterestError, match="not_found"):
        service.resolve_pin(a, "12", "999")
    with pytest.raises(PinterestError, match="not_found"):
        service.pins(a, "999")
    with pytest.raises(PinterestError, match="authentication"):
        service.boards(b)
    assert oauth.exchange_count == 1


def test_callback_requires_binding_and_burns_state_before_exchange(rig: tuple) -> None:
    service, _, oauth, _ = rig
    started = service.start_connect(tenant_id=uuid4(), user_id=uuid4())
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    with pytest.raises(InvalidState):
        service.complete_connect(code="fixture", state=state, binding_nonce="foreign")
    with pytest.raises(InvalidState):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert oauth.exchange_count == 0


def test_replay_tamper_and_disconnect_invalidate_callback(rig: tuple) -> None:
    service, repo, _, _ = rig
    tenant = uuid4()
    state, nonce = connect(service, tenant)
    with pytest.raises(InvalidState):
        service.complete_connect(code="again", state=state, binding_nonce=nonce)
    started = service.start_connect(tenant_id=tenant, user_id=uuid4())
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    with pytest.raises(InvalidState):
        service.complete_connect(
            code="fixture", state=state + "x", binding_nonce=started.binding_nonce
        )
    service.disconnect(tenant, uuid4())
    with pytest.raises(InvalidState):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert tenant not in repo.credentials
    with pytest.raises(PinterestError):
        service.boards(tenant)


def test_cancel_and_failed_reconnect_preserve_existing_grant(rig: tuple) -> None:
    service, repo, oauth, _ = rig
    tenant = uuid4()
    connect(service, tenant)
    old = repo.credentials[tenant]
    started = service.start_connect(tenant_id=tenant, user_id=uuid4())
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    service.handoff(state, binding_nonce=started.binding_nonce)
    service.abandon_callback(state, binding_nonce=started.binding_nonce)
    assert repo.credentials[tenant] == old
    oauth.error = PinterestError("permission", 403)
    with pytest.raises(PinterestError):
        connect(service, tenant)
    assert repo.credentials[tenant] == old
    assert service.connection(tenant).status == "active"


def test_refresh_rotates_once_and_does_not_refresh_fresh_tokens(rig: tuple) -> None:
    service, repo, oauth, _ = rig
    tenant = uuid4()
    oauth.tokens = Tokens(
        "stale",
        "old-refresh",
        datetime.now(UTC) - timedelta(seconds=1),
        datetime.now(UTC) + timedelta(days=30),
        SCOPES,
    )
    connect(service, tenant)
    oauth.tokens = Tokens(
        "new-access",
        "new-refresh",
        datetime.now(UTC) + timedelta(days=30),
        datetime.now(UTC) + timedelta(days=60),
        SCOPES,
    )
    service.boards(tenant)
    service.boards(tenant)
    assert oauth.refresh_count == 1
    assert repo.credentials[tenant].version == 2


def test_refresh_lock_busy_and_revoked_refresh_require_clear_outcomes(rig: tuple) -> None:
    service, repo, oauth, redis = rig
    tenant = uuid4()
    oauth.tokens = Tokens(
        "stale",
        "old",
        datetime.now(UTC) - timedelta(seconds=1),
        datetime.now(UTC) + timedelta(days=1),
        SCOPES,
    )
    connect(service, tenant)
    key = RefreshLock._key(tenant, service.connection(tenant).id)
    redis.values[key] = "another-worker"
    with pytest.raises(PinterestError, match="busy"):
        service.boards(tenant)
    assert oauth.refresh_count == 0
    redis.values.pop(key)
    oauth.error = PinterestError("authentication", 401)
    with pytest.raises(PinterestError, match="authentication"):
        service.boards(tenant)
    assert repo.connection(tenant).status == "reconnect"


def test_disconnect_during_read_discards_private_result(rig: tuple) -> None:
    service, repo, _, _ = rig
    tenant = uuid4()
    connect(service, tenant)

    class Reader(FakePinterestClient):
        def boards(self, *, page_size: int = 25, bookmark: str | None = None):
            repo.disconnect(tenant, uuid4())
            return super().boards(page_size=page_size, bookmark=bookmark)

    service._client = lambda _: Reader(boards=(Board("12", "private"),))
    with pytest.raises(PinterestError, match="authentication"):
        service.boards(tenant)


def test_oauth_exchange_uses_basic_auth_and_validates_granted_scopes() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == "https://api.pinterest.com/v5/oauth/token"
        assert request.method == "POST"
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "refresh_token_expires_in": 5184000,
                "scope": ",".join(SCOPES),
                "token_type": "bearer",
            },
        )

    settings = PinterestSettings(
        "app", "secret", "https://app.example/api/connections/pinterest/callback", "s" * 32
    )
    client = HttpOAuthClient(settings, transport=httpx.MockTransport(handler))
    tokens = client.exchange("code")
    assert "secret" not in repr(settings)
    assert "access" not in repr(tokens).split("access_expires_at")[0]
    assert tokens.scopes == SCOPES
    assert parse_qs(requests[0].content.decode())["grant_type"] == ["authorization_code"]
    client.refresh("refresh")
    assert parse_qs(requests[1].content.decode())["grant_type"] == ["refresh_token"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"access_token": "secret"},
        {
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": True,
            "refresh_token_expires_in": 1,
            "scope": "boards:read",
        },
    ],
)
def test_bad_oauth_payload_is_sanitized(payload: dict) -> None:
    settings = PinterestSettings(
        "app", "secret", "https://app.example/api/connections/pinterest/callback", "s" * 32
    )
    client = HttpOAuthClient(
        settings, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    with pytest.raises(PinterestError, match="invalid_response") as error:
        client.exchange("code")
    assert error.value.__context__ is None
    assert "secret" not in str(error.value)


def test_logout_or_business_switch_cancels_only_that_users_pending_flow(rig: tuple) -> None:
    service, _, oauth, _ = rig
    tenant, user = uuid4(), uuid4()
    started = service.start_connect(tenant_id=tenant, user_id=user)
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    service.cancel_pending(tenant, user)
    with pytest.raises(InvalidState):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert oauth.exchange_count == 0


def test_handoff_replay_missing_binding_and_cancel_fail_closed(rig: tuple) -> None:
    service, _, oauth, _ = rig
    tenant, user = uuid4(), uuid4()
    started = service.start_connect(tenant_id=tenant, user_id=user)
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    with pytest.raises(InvalidState):
        service.handoff(state, binding_nonce=None)
    with pytest.raises(InvalidState):
        service.handoff(state, binding_nonce=started.binding_nonce)
    started = service.start_connect(tenant_id=tenant, user_id=user)
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    service.handoff(state, binding_nonce=started.binding_nonce)
    with pytest.raises(InvalidState):
        service.handoff(state, binding_nonce=started.binding_nonce)
    service.cancel_pending(tenant, user)
    with pytest.raises(InvalidState):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert oauth.exchange_count == 0


def test_expired_handoff_and_callback_reject_before_exchange(rig: tuple, monkeypatch) -> None:
    import time

    from qualify_api.connections import state_token

    service, _, oauth, _ = rig
    started = service.start_connect(tenant_id=uuid4(), user_id=uuid4())
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    future = time.time() + 601
    monkeypatch.setattr(state_token.time, "time", lambda: future)
    with pytest.raises(InvalidState):
        service.handoff(state, binding_nonce=started.binding_nonce)
    with pytest.raises(InvalidState):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert oauth.exchange_count == 0


def test_membership_removed_before_callback_never_exchanges_code(rig: tuple) -> None:
    service, repo, oauth, _ = rig
    tenant, user = uuid4(), uuid4()
    started = service.start_connect(tenant_id=tenant, user_id=user)
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    service.handoff(state, binding_nonce=started.binding_nonce)
    repo.denied_users.add((tenant, user))
    with pytest.raises(PinterestError, match="permission"):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert oauth.exchange_count == 0


@pytest.mark.parametrize("stage", ["exchange", "profile"])
def test_logout_during_provider_io_prevents_grant_persistence(rig: tuple, stage: str) -> None:
    from qualify_api.pinterest.client import Profile

    service, repo, oauth, _ = rig
    tenant, user = uuid4(), uuid4()
    started = service.start_connect(tenant_id=tenant, user_id=user)
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    service.handoff(state, binding_nonce=started.binding_nonce)
    if stage == "exchange":
        original = oauth.exchange

        def exchange(code: str) -> Tokens:
            service.cancel_pending(tenant, user)
            return original(code)

        oauth.exchange = exchange
    else:

        class Reader(FakePinterestClient):
            def profile(self) -> Profile:
                service.cancel_pending(tenant, user)
                return Profile("fixture")

        service._client = lambda _: Reader()
    with pytest.raises(InvalidState):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert repo.connection(tenant).status == "disconnected"
    assert tenant not in repo.credentials


def test_http_lifecycle_denies_unauthorized_actor_with_403(rig: tuple) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qualify_api.http.deps import Principal, current_principal
    from qualify_api.pinterest.routes import get_pinterest_service, router

    service, repo, _, _ = rig
    tenant, user = uuid4(), uuid4()
    repo.denied_users.add((tenant, user))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_pinterest_service] = lambda: service
    app.dependency_overrides[current_principal] = lambda: Principal(tenant, user)
    with TestClient(app) as client:
        assert client.post("/api/connections/pinterest/start").status_code == 403
        assert client.delete("/api/connections/pinterest").status_code == 403


def test_http_callback_cookie_and_closed_redirect(rig: tuple) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qualify_api.http.connections_routes import get_connections_page_url
    from qualify_api.http.deps import Principal, current_principal
    from qualify_api.pinterest.routes import get_pinterest_service, router

    service, _, _, _ = rig
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_pinterest_service] = lambda: service
    app.dependency_overrides[current_principal] = lambda: Principal(uuid4(), uuid4())
    app.dependency_overrides[get_connections_page_url] = lambda: "https://app.example/connections"
    with TestClient(app, base_url="https://app.example") as client:
        response = client.post("/api/connections/pinterest/start")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
        handed = client.get(
            "/api/connections/pinterest/handoff", params={"state": state}, follow_redirects=False
        )
        assert handed.status_code == 303
        assert handed.headers["location"].startswith("https://www.pinterest.com/oauth/")
        assert "HttpOnly" in handed.headers["set-cookie"]
        callback = client.get(
            "/api/connections/pinterest/callback",
            params={"state": state, "code": "fixture"},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert (
            callback.headers["location"]
            == "https://app.example/catalog?connect=connected&platform=pinterest"
        )
        replay = client.get(
            "/api/connections/pinterest/callback",
            params={"state": state, "code": "fixture"},
            follow_redirects=False,
        )
        assert "connect=invalid_state" in replay.headers["location"]
