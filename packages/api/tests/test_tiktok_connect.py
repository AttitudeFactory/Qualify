"""TikTok Login Kit connect flow (m-24921091), fully offline: httpx mocked, fakes for the
repository / Redis / verifier. Mirrors `test_oauth_callback.py` for Meta."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from qualify_api.config import TikTokSettings
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.events import InMemoryEventPublisher
from qualify_api.connections.repository import ConnectionRecord, GrantInput
from qualify_api.connections.service import ConnectOutcome, ConnectResult
from qualify_api.connections.state_token import (
    InvalidState,
    JtiStore,
    StartedConnect,
    binding_hash,
    new_payload,
    sign_state,
)
from qualify_api.connections.tiktok_oauth import (
    HttpTikTokOAuthClient,
    TikTokOAuthError,
    TikTokTokens,
    code_challenge_for,
    new_code_verifier,
    parse_token_response,
)
from qualify_api.connections.tiktok_service import (
    PkceStore,
    TikTokConnectService,
    state_secret,
    tiktok_access_notice,
)
from qualify_api.http import connections_routes, deps, tiktok_routes
from qualify_api.http.app import create_app

TENANT = UUID("11111111-1111-4111-8111-111111111111")
BRAND = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
APP_ROW = UUID("44444444-4444-4444-8444-444444444444")
ACCESS = "ACCESS_TOKEN_SECRET"
REFRESH = "REFRESH_TOKEN_SECRET"
OPEN_ID = "open-id-123"
PAGE_URL = "https://qualify.test/connections"

SETTINGS = TikTokSettings(
    client_key="ck-test",
    client_secret="cs-test-secret",
    redirect_uri="https://qualify.test/api/connections/tiktok/callback",
    state_secret="state-secret",
)


def _token_payload(scope: str = "user.info.basic,video.upload") -> dict[str, object]:
    return {
        "access_token": ACCESS,
        "refresh_token": REFRESH,
        "open_id": OPEN_ID,
        "expires_in": 86400,
        "refresh_expires_in": 31536000,
        "scope": scope,
        "token_type": "Bearer",
    }


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, name: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    def getdel(self, name: str) -> str | None:
        return self.store.pop(name, None)


def _mock_transport(scope: str = "user.info.basic,video.upload", open_id: str = OPEN_ID):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v2/oauth/token/":
            payload = _token_payload(scope)
            payload["open_id"] = open_id
            return httpx.Response(200, json=payload)
        if request.url.path == "/v2/user/info/":
            return httpx.Response(
                200,
                json={
                    "data": {"user": {"open_id": open_id, "display_name": "Tienda Ana"}},
                    "error": {"code": "ok", "message": "", "log_id": "x"},
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


@dataclass
class FakeRepo:
    grants: list[GrantInput] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    reasons: list[str | None] = field(default_factory=list)

    def platform_app_id(self, app_id: str, *, tenant_id: UUID) -> UUID:
        assert app_id == SETTINGS.client_key
        return APP_ROW

    def persist_grant(self, grant: GrantInput) -> ConnectionRecord:
        previous = "active" if self.grants else None
        self.grants.append(grant)
        return ConnectionRecord(
            connection_id=uuid(),
            tenant_id=grant.tenant_id,
            credential_version=len(self.grants),
            previous_status=previous,
        )

    def record_status(self, *, status: str, reconnect_reason: str | None = None, **_: object):
        self.statuses.append(status)
        self.reasons.append(reconnect_reason)


_CONNECTION_ID = uuid4()


def uuid() -> UUID:
    return _CONNECTION_ID


class FakeVerifier:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    async def verify(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        return self.ok


def build(*, scope="user.info.basic,video.upload", open_id=OPEN_ID, verify_ok=True):
    transport, calls = _mock_transport(scope, open_id)
    redis = FakeRedis()
    repo = FakeRepo()
    service = TikTokConnectService(
        settings=SETTINGS,
        oauth_client=HttpTikTokOAuthClient(SETTINGS, transport=transport),
        repository=repo,
        jti_store=JtiStore(redis),
        pkce_store=PkceStore(redis),
        encryptor=DevEncryptor(),
        verifier=FakeVerifier(verify_ok),
        publisher=InMemoryEventPublisher(),
    )
    return service, repo, redis, calls


# m-24921205: what each start handed its browser, keyed by state — the test's browser jar.
_BOUND: dict[str, StartedConnect] = {}


def _state_of(started: StartedConnect) -> str:
    state = dict(parse_qsl(urlsplit(started.authorization_url).query))["state"]
    _BOUND[state] = started
    return state


async def complete(service: TikTokConnectService, *, code: str, state: str) -> ConnectResult:
    """`complete_connect` as presented by the browser that started the flow."""
    started = _BOUND.get(state)
    return await service.complete_connect(
        code=code, state=state, binding_nonce=started.binding_nonce if started else None
    )


def test_authorization_url_carries_scopes_pkce_and_never_video_publish() -> None:
    service, _, _, _ = build()
    url = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER).authorization_url
    query = dict(parse_qsl(urlsplit(url).query))
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/?")
    assert query["client_key"] == "ck-test"
    assert query["scope"] == "user.info.basic,video.upload"
    assert "video.publish" not in url
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 64  # hex sha256
    assert "client_secret" not in url and SETTINGS.client_secret not in url


def test_code_challenge_is_hex_sha256_of_the_verifier() -> None:
    verifier = new_code_verifier()
    assert 43 <= len(verifier) <= 128
    assert (
        code_challenge_for(verifier) == __import__("hashlib").sha256(verifier.encode()).hexdigest()
    )


async def test_successful_connect_persists_encrypted_tokens_and_pkce_verifier_is_sent() -> None:
    service, repo, redis, calls = build()
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    verifier = next(v for k, v in redis.store.items() if k.startswith("oauth:pkce:"))
    result = await complete(service, code="auth-code", state=state)

    assert result.outcome is ConnectOutcome.ACTIVE
    grant = repo.grants[0]
    assert (grant.platform, grant.account_type) == ("tiktok", "creator")
    assert grant.external_account_id == OPEN_ID and grant.linked_page_id is None
    assert grant.granted_scopes == ("user.info.basic", "video.upload")
    assert grant.access_posture == "development" and grant.token_type == "tiktok"
    assert ACCESS.encode() not in grant.ciphertext and REFRESH.encode() not in grant.ciphertext
    blob = TikTokTokens.from_blob(DevEncryptor().decrypt(grant.ciphertext, key_id=grant.key_id))
    assert blob.refresh_token == REFRESH
    token_call = next(c for c in calls if c.url.path == "/v2/oauth/token/")
    form = dict(parse_qsl(token_call.content.decode()))
    assert form["code_verifier"] == verifier and form["grant_type"] == "authorization_code"
    assert repo.statuses == ["active"]
    assert not any(k.startswith("oauth:pkce:") for k in redis.store)  # verifier spent


async def test_replayed_state_is_rejected_before_any_platform_call() -> None:
    service, repo, _, calls = build()
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    await complete(service, code="c", state=state)
    n = len(calls)
    with pytest.raises(InvalidState):
        await complete(service, code="c", state=state)
    assert len(calls) == n and len(repo.grants) == 1


async def test_a_meta_state_is_not_valid_on_the_tiktok_flow() -> None:
    service, repo, _, calls = build()
    meta_state = sign_state(new_payload(TENANT, BRAND, USER), "state-secret")  # Meta's key
    with pytest.raises(InvalidState):
        await complete(service, code="c", state=meta_state)
    assert calls == [] and repo.grants == []
    assert state_secret(SETTINGS) != SETTINGS.state_secret


async def test_missing_upload_scope_is_permission_missing_and_degraded() -> None:
    service, repo, _, _ = build(scope="user.info.basic")
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    result = await complete(service, code="c", state=state)
    assert result.outcome is ConnectOutcome.PERMISSION_MISSING
    assert repo.grants[0].granted_scopes == ("user.info.basic",)  # recorded as GRANTED
    assert repo.statuses == ["degraded"] and repo.reasons == ["permission_missing"]


async def test_failed_verification_is_degraded() -> None:
    service, repo, _, _ = build(verify_ok=False)
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    result = await complete(service, code="c", state=state)
    assert result.outcome is ConnectOutcome.DEGRADED and repo.statuses == ["degraded"]


async def test_reconnect_with_a_different_account_persists_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    service, repo, _, _ = build(open_id="someone-else")
    target = uuid4()
    monkeypatch.setattr(
        "qualify_api.connections.tiktok_service.list_connections",
        lambda tenant: [
            SimpleNamespace(
                connection_id=target,
                brand_id=BRAND,
                platform="tiktok",
                external_account_id=OPEN_ID,
                reconnect_reason=None,
            )
        ],
    )
    state = _state_of(
        service.start_connect(tenant_id=TENANT, brand_id=None, user_id=USER, connection_id=target)
    )
    result = await complete(service, code="c", state=state)
    assert result.outcome is ConnectOutcome.ACCOUNT_ACCESS_REQUIRED and repo.grants == []


async def test_token_exchange_error_surfaces_code_never_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "secret": ACCESS})

    client = HttpTikTokOAuthClient(SETTINGS, transport=httpx.MockTransport(handler))
    with pytest.raises(TikTokOAuthError) as err:
        await client.exchange_code(code="x", code_verifier="v")
    assert err.value.code == "invalid_grant" and err.value.is_permanent_auth_failure
    assert ACCESS not in str(err.value)


def test_tokens_and_settings_repr_redact() -> None:
    tokens = parse_token_response(_token_payload(), now=datetime.now(UTC))
    assert ACCESS not in repr(tokens) and REFRESH not in repr(tokens)
    assert SETTINGS.client_secret not in repr(SETTINGS)
    assert json.loads(tokens.to_blob())["refresh_token"] == REFRESH


def test_unaudited_app_notice_is_spanish_and_goes_away_when_live() -> None:
    assert "TikTok" in tiktok_access_notice("development")
    assert tiktok_access_notice("live") == ""


def test_settings_from_env_defaults_never_ask_for_video_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://x.test/cb")
    assert TikTokSettings.is_configured()
    s = TikTokSettings.from_env()
    assert s.requested_scopes == ("user.info.basic", "video.upload")
    assert s.access_posture == "development" and s.upload_mode == "FILE_UPLOAD"
    monkeypatch.delenv("TIKTOK_CLIENT_SECRET")
    assert not TikTokSettings.is_configured()


# --- HTTP routes ---------------------------------------------------------------------------


def _client(service: TikTokConnectService, *, bound: bool = True) -> TestClient:
    """A browser. `bound=True` holds the binding cookie of every flow started so far (the
    browser that started them); `bound=False` is somebody else's browser."""
    app = create_app(configure_production=False)
    app.dependency_overrides[tiktok_routes.get_tiktok_connect_service] = lambda: service
    app.dependency_overrides[connections_routes.get_connections_page_url] = lambda: PAGE_URL
    app.dependency_overrides[deps.current_principal] = lambda: deps.Principal(TENANT, USER)
    client = TestClient(app, follow_redirects=False)
    if bound:
        for started in _BOUND.values():
            _give_cookie(client, started.binding_cookie_name, started.binding_nonce)
    return client


def _give_cookie(client: TestClient, name: str, value: str) -> None:
    client.cookies.set(name, value, domain="testserver.local", path="/api/connections")


def _landing(response: httpx.Response) -> dict[str, str]:
    assert response.status_code == 303
    return dict(parse_qsl(urlsplit(response.headers["location"]).query))


def test_callback_route_redirects_with_outcome_and_platform() -> None:
    service, _, _, _ = build()
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    query = _landing(_client(service).get(f"/api/connections/tiktok/callback?code=c&state={state}"))
    assert query == {"connect": "active", "platform": "tiktok"}


def test_callback_denied_and_forged_states() -> None:
    service, _, _, _ = build()
    client = _client(service)
    assert (
        _landing(client.get("/api/connections/tiktok/callback?error=access_denied"))["connect"]
        == "denied"
    )
    assert (
        _landing(client.get("/api/connections/tiktok/callback?code=c&state=forged.sig"))["connect"]
        == "invalid_state"
    )


def test_denied_consent_with_state_spends_the_jti_and_drops_the_pkce_verifier() -> None:
    service, _, redis, _ = build()
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    assert any(k.startswith("oauth:pkce:") for k in redis.store)
    query = _landing(
        _client(service).get(f"/api/connections/tiktok/callback?error=access_denied&state={state}")
    )
    assert query["connect"] == "denied"
    assert not any(k.startswith("oauth:pkce:") for k in redis.store)


def test_missing_platform_app_row_redirects_degraded_not_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.connections.repository import PlatformAppMissing

    service, repo, _, _ = build()

    def missing(app_id: str, *, tenant_id: UUID) -> UUID:
        raise PlatformAppMissing("no platform_apps row")

    monkeypatch.setattr(repo, "platform_app_id", missing)
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    query = _landing(_client(service).get(f"/api/connections/tiktok/callback?code=c&state={state}"))
    assert query == {"connect": "degraded", "platform": "tiktok"}


def test_start_route_refuses_when_tiktok_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    service, _, _, _ = build()
    assert _client(service).post("/api/connections/tiktok/start", json={}).status_code == 503


def test_start_route_returns_consent_url_for_the_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://x.test/cb")
    service, _, _, _ = build()
    response = _client(service).post("/api/connections/tiktok/start", json={})
    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://www.tiktok.com/v2/auth/")


def test_start_request_has_no_identity_fields() -> None:
    assert "tenant_id" not in tiktok_routes.StartTikTokRequest.model_fields
    assert "user_id" not in tiktok_routes.StartTikTokRequest.model_fields


# --- m-24921205: the callback is bound to the browser that started the flow ---------------


def _pkce_keys(redis: FakeRedis) -> list[str]:
    return [k for k in redis.store if k.startswith("oauth:pkce:")]


def _cleared(response: httpx.Response) -> list[str]:
    return [
        h.split("=", 1)[0]
        for h in response.headers.get_list("set-cookie")
        if "max-age=0" in h.lower()
    ]


def test_tiktok_binding_cookie_is_its_own_namespace() -> None:
    service, _, _, _ = build()
    started = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    payload = service.callback_context(_state_of(started))
    assert started.binding_cookie_name == f"qoauth_tiktok_{payload.jti[:16]}"
    assert payload.binding == binding_hash(started.binding_nonce)
    assert started.callback_url == SETTINGS.redirect_uri


def test_bound_tiktok_callback_connects_and_clears_the_cookie() -> None:
    service, repo, _, _ = build()
    started = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    state = _state_of(started)
    response = _client(service).get(f"/api/connections/tiktok/callback?code=c&state={state}")
    assert _landing(response) == {"connect": "active", "platform": "tiktok"}
    assert len(repo.grants) == 1
    assert started.binding_cookie_name in _cleared(response)


def test_missing_cookie_is_invalid_state_drops_pkce_and_burns_the_state() -> None:
    service, repo, redis, calls = build()
    started = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    state = _state_of(started)
    response = _client(service, bound=False).get(
        f"/api/connections/tiktok/callback?code=victim&state={state}"
    )
    assert _landing(response) == {"connect": "invalid_state", "platform": "tiktok"}
    assert calls == [] and repo.grants == []  # no code exchange, nothing persisted
    assert _pkce_keys(redis) == []
    assert started.binding_cookie_name in _cleared(response)
    again = _client(service).get(f"/api/connections/tiktok/callback?code=c&state={state}")
    assert _landing(again)["connect"] == "invalid_state"
    assert calls == []


async def test_cookie_of_another_flow_never_binds_on_tiktok() -> None:
    service, repo, redis, calls = build()
    first = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    second = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    state = _state_of(first)
    client = _client(service, bound=False)
    _give_cookie(client, first.binding_cookie_name, second.binding_nonce)
    response = client.get(f"/api/connections/tiktok/callback?code=c&state={state}")
    assert _landing(response)["connect"] == "invalid_state"
    assert calls == [] and repo.grants == []
    assert len(_pkce_keys(redis)) == 1  # only the second, untouched flow remains
    with pytest.raises(InvalidState):
        await service.complete_connect(code="c", state=state, binding_nonce=first.binding_nonce)
    with pytest.raises(InvalidState):
        await service.complete_connect(code="c", state=_state_of(second), binding_nonce="wrong")
    assert calls == [] and _pkce_keys(redis) == []


async def test_tiktok_replay_with_the_right_cookie_is_invalid_state() -> None:
    service, _, _, calls = build()
    started = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    state = _state_of(started)
    await service.complete_connect(code="c", state=state, binding_nonce=started.binding_nonce)
    exchanged = len(calls)
    with pytest.raises(InvalidState):
        await service.complete_connect(code="c", state=state, binding_nonce=started.binding_nonce)
    assert len(calls) == exchanged


def test_unbound_tiktok_cancel_is_plain_invalid_state_and_drops_pkce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    service, _, redis, _ = build()
    target = uuid4()
    monkeypatch.setattr(
        "qualify_api.connections.tiktok_service.list_connections",
        lambda tenant: [
            SimpleNamespace(
                connection_id=target,
                brand_id=BRAND,
                platform="tiktok",
                external_account_id=OPEN_ID,
                reconnect_reason=None,
            )
        ],
    )
    state = _state_of(
        service.start_connect(
            tenant_id=TENANT,
            brand_id=None,
            user_id=USER,
            connection_id=target,
            return_to="/planner",
        )
    )
    response = _client(service, bound=False).get(
        f"/api/connections/tiktok/callback?error=access_denied&state={state}"
    )
    assert urlsplit(response.headers["location"]).path == "/connections"
    assert _landing(response) == {"connect": "invalid_state", "platform": "tiktok"}
    assert _pkce_keys(redis) == []


def test_bound_tiktok_reconnect_returns_to_its_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    service, repo, _, _ = build()
    target = uuid4()
    monkeypatch.setattr(
        "qualify_api.connections.tiktok_service.list_connections",
        lambda tenant: [
            SimpleNamespace(
                connection_id=target,
                brand_id=BRAND,
                platform="tiktok",
                external_account_id=OPEN_ID,
                reconnect_reason=None,
            )
        ],
    )
    state = _state_of(
        service.start_connect(
            tenant_id=TENANT,
            brand_id=None,
            user_id=USER,
            connection_id=target,
            return_to="/planner",
        )
    )
    response = _client(service).get(f"/api/connections/tiktok/callback?code=c&state={state}")
    assert urlsplit(response.headers["location"]).path == "/planner"
    assert _landing(response)["connect"] == "active"
    assert len(repo.grants) == 1


def test_tiktok_start_route_sets_the_httponly_binding_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://x.test/cb")
    service, _, _, _ = build()
    response = _client(service, bound=False).post("/api/connections/tiktok/start", json={})
    assert response.status_code == 200
    (cookie,) = response.headers.get_list("set-cookie")
    attrs = {part.strip().lower() for part in cookie.split(";")}
    name, value = cookie.split(";", 1)[0].split("=", 1)
    assert name.startswith("qoauth_tiktok_")
    assert {"httponly", "secure", "path=/api/connections", "samesite=lax"} <= attrs
    assert f"max-age={SETTINGS.state_ttl_seconds}" in attrs
    state = dict(parse_qsl(urlsplit(response.json()["authorization_url"]).query))["state"]
    assert service.callback_context(state).binding == binding_hash(value)


# --- same host (m-24947215) ----------------------------------------------------------------


def _two_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", SETTINGS.redirect_uri)
    monkeypatch.setenv("QUALIFY_PUBLIC_URL", "https://qualify.test")
    monkeypatch.setenv("QUALIFY_PUBLIC_HOSTS", "app.qualify.la")
    monkeypatch.setenv("QUALIFY_APP_URL", "https://qualify.test")


def _two_host_service(transport: httpx.MockTransport) -> TikTokConnectService:
    settings = replace(SETTINGS, redirect_hosts=frozenset({"app.qualify.la", "qualify.test"}))
    redis = FakeRedis()
    return TikTokConnectService(
        settings=settings,
        oauth_client=HttpTikTokOAuthClient(settings, transport=transport),
        repository=FakeRepo(),
        jti_store=JtiStore(redis),
        pkce_store=PkceStore(redis),
        encryptor=DevEncryptor(),
        verifier=FakeVerifier(True),
        publisher=InMemoryEventPublisher(),
    )


def _browser_on(host: str, service: TikTokConnectService) -> TestClient:
    """A real browser on `host`: no page-URL override, cookies kept per host."""
    app = create_app(configure_production=False)
    app.dependency_overrides[tiktok_routes.get_tiktok_connect_service] = lambda: service
    app.dependency_overrides[deps.current_principal] = lambda: deps.Principal(TENANT, USER)
    return TestClient(app, base_url=f"https://{host}", follow_redirects=False)


def test_flow_started_on_app_qualify_la_stays_on_that_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _two_host_env(monkeypatch)
    transport, calls = _mock_transport()
    service = _two_host_service(transport)
    browser = _browser_on("app.qualify.la", service)

    started = browser.post("/api/connections/tiktok/start", json={})
    assert started.status_code == 200
    consent = dict(parse_qsl(urlsplit(started.json()["authorization_url"]).query))
    assert consent["redirect_uri"] == "https://app.qualify.la/api/connections/tiktok/callback"
    cookie = started.headers["set-cookie"]
    assert "Path=/api/connections" in cookie and "domain=" not in cookie.lower()  # host-only

    back = browser.get(f"/api/connections/tiktok/callback?code=c&state={consent['state']}")
    assert back.status_code == 303
    assert back.headers["location"] == (
        "https://app.qualify.la/connections?connect=active&platform=tiktok"
    )
    exchange = next(c for c in calls if c.url.path == "/v2/oauth/token/")
    sent = dict(parse_qsl(exchange.content.decode()))
    assert sent["redirect_uri"] == "https://app.qualify.la/api/connections/tiktok/callback"


def test_an_arbitrary_host_never_becomes_the_callback_or_the_landing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _two_host_env(monkeypatch)
    transport, _ = _mock_transport()
    service = _two_host_service(transport)
    browser = _browser_on("evil.example", service)

    started = browser.post("/api/connections/tiktok/start", json={})
    consent = dict(parse_qsl(urlsplit(started.json()["authorization_url"]).query))
    assert consent["redirect_uri"] == SETTINGS.redirect_uri  # the configured one
    back = browser.get("/api/connections/tiktok/callback?error=access_denied")
    assert back.headers["location"].startswith("https://qualify.test/connections?")


def test_in_process_start_from_app_host_signs_that_redirect_uri() -> None:
    transport, _ = _mock_transport()
    service = _two_host_service(transport)
    started = service.start_connect(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, browser_origin="https://app.qualify.la"
    )
    assert started.callback_url == "https://app.qualify.la/api/connections/tiktok/callback"
    state = dict(parse_qsl(urlsplit(started.authorization_url).query))["state"]
    assert service.callback_context(state).redirect_uri == started.callback_url
    other = service.start_connect(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, browser_origin="https://evil.example"
    )
    assert other.callback_url == SETTINGS.redirect_uri
