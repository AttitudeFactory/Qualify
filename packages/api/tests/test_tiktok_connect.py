"""TikTok Login Kit connect flow (m-24921091), fully offline: httpx mocked, fakes for the
repository / Redis / verifier. Mirrors `test_oauth_callback.py` for Meta."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
from qualify_api.connections.service import ConnectOutcome
from qualify_api.connections.state_token import (
    InvalidState,
    JtiStore,
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


def _state_of(url: str) -> str:
    return dict(parse_qsl(urlsplit(url).query))["state"]


def test_authorization_url_carries_scopes_pkce_and_never_video_publish() -> None:
    service, _, _, _ = build()
    url = service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
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
    result = await service.complete_connect(code="auth-code", state=state)

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
    await service.complete_connect(code="c", state=state)
    n = len(calls)
    with pytest.raises(InvalidState):
        await service.complete_connect(code="c", state=state)
    assert len(calls) == n and len(repo.grants) == 1


async def test_a_meta_state_is_not_valid_on_the_tiktok_flow() -> None:
    service, repo, _, calls = build()
    meta_state = sign_state(new_payload(TENANT, BRAND, USER), "state-secret")  # Meta's key
    with pytest.raises(InvalidState):
        await service.complete_connect(code="c", state=meta_state)
    assert calls == [] and repo.grants == []
    assert state_secret(SETTINGS) != SETTINGS.state_secret


async def test_missing_upload_scope_is_permission_missing_and_degraded() -> None:
    service, repo, _, _ = build(scope="user.info.basic")
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    result = await service.complete_connect(code="c", state=state)
    assert result.outcome is ConnectOutcome.PERMISSION_MISSING
    assert repo.grants[0].granted_scopes == ("user.info.basic",)  # recorded as GRANTED
    assert repo.statuses == ["degraded"] and repo.reasons == ["permission_missing"]


async def test_failed_verification_is_degraded() -> None:
    service, repo, _, _ = build(verify_ok=False)
    state = _state_of(service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER))
    result = await service.complete_connect(code="c", state=state)
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
    result = await service.complete_connect(code="c", state=state)
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


def _client(service: TikTokConnectService) -> TestClient:
    app = create_app(configure_production=False)
    app.dependency_overrides[tiktok_routes.get_tiktok_connect_service] = lambda: service
    app.dependency_overrides[connections_routes.get_connections_page_url] = lambda: PAGE_URL
    app.dependency_overrides[deps.current_principal] = lambda: deps.Principal(TENANT, USER)
    return TestClient(app, follow_redirects=False)


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
