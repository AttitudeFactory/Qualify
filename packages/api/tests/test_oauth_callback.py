"""End-to-end tests for the OAuth connect flow (C-04), fully offline.

Every collaborator is a fake — platform, repository, jti store, verifier — so this
exercises the real `ConnectService` decision tree and the real FastAPI routes with zero
network and zero database, which is the "suite offline, cero red en CI" criterion.

The scope literals here are deliberately SYNTHETIC (`scope_alpha`, `scope_beta`). Meta's
real spellings are `[V]` (ADR 25 counted four in circulation), and pinning a guess in a
test would quietly turn a guess into a requirement. Using invented literals proves the
property that actually matters: whatever the platform returns is stored verbatim and never
interpreted here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.events import DomainEventName, InMemoryEventPublisher
from qualify_api.connections.meta_oauth import (
    HttpMetaOAuthClient,
    LinkedPage,
    TokenGrant,
    _parse_accounts_response,
)
from qualify_api.connections.page_subscription import (
    EVENT_PAGE_SUBSCRIBE_FAILED,
    EVENT_PAGE_SUBSCRIBED,
    PageSubscriptions,
    SubscriptionResult,
)
from qualify_api.connections.repository import ConnectionRecord, GrantInput
from qualify_api.connections.service import ConnectOutcome, ConnectResult, ConnectService
from qualify_api.connections.state_token import (
    InvalidState,
    JtiStore,
    StartedConnect,
    binding_hash,
    binding_matches,
    new_payload,
    sign_state,
)
from qualify_api.http import connections_routes, deps
from qualify_api.http.app import create_app

TENANT = UUID("11111111-1111-4111-8111-111111111111")
BRAND = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
APP_ROW_ID = UUID("44444444-4444-4444-8444-444444444444")

TOKEN = "SUPER_SECRET_ACCESS_TOKEN"
PAGE_TOKEN = "SUPER_SECRET_PAGE_TOKEN"
GRANTED_LITERALS = ("scope_alpha", "scope_beta")

IG_PAGE = LinkedPage(
    page_id="page-1",
    page_name="PuntoServis",
    instagram_account_id="17841400000000000",
    instagram_username="@puntoservis",
    page_access_token=PAGE_TOKEN,
)
PAGE_WITHOUT_IG = LinkedPage(
    page_id="page-2", page_name="No IG", instagram_account_id=None, instagram_username=None
)


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


class FakeMetaOAuthClient:
    """Stands in for Meta's authorization/token endpoints. Records the tokens it was
    asked about so a test can prove which calls happened."""

    def __init__(
        self,
        *,
        pages: tuple[LinkedPage, ...] = (IG_PAGE,),
        scopes: tuple[str, ...] = GRANTED_LITERALS,
    ) -> None:
        self.pages = pages
        self.scopes = scopes
        self.exchanged_codes: list[str] = []
        self.issued_states: list[str] = []
        self.authorize_redirects: list[str] = []
        self.exchange_redirects: list[str] = []

    def authorization_url(
        self,
        *,
        state: str,
        rerequest: bool = False,
        request_ads: bool = False,
        redirect_uri: str = "",
    ) -> str:
        self.issued_states.append(state)
        self.authorize_redirects.append(redirect_uri)
        suffix = "&auth_type=rerequest" if rerequest else ""
        return f"https://platform.example/dialog?state={state}{suffix}"

    async def exchange_code(self, code: str, *, redirect_uri: str = "") -> TokenGrant:
        self.exchanged_codes.append(code)
        self.exchange_redirects.append(redirect_uri)
        return TokenGrant(access_token=TOKEN, token_type="bearer", expires_in=5184000)

    async def list_linked_pages(self, access_token: str) -> tuple[LinkedPage, ...]:
        return self.pages

    async def list_granted_scopes(self, access_token: str) -> tuple[str, ...]:
        return self.scopes


@dataclass
class StoredConnection:
    connection_id: UUID
    grant: GrantInput
    status: str
    credential_version: int
    last_verified_at: datetime | None = None
    reconnect_reason: str | None = None


@dataclass
class FakeRepository:
    """In-memory stand-in that preserves the two invariants that matter: the natural key
    is unique, and credentials are append-only."""

    connections: dict[tuple[UUID, str, str], StoredConnection] = field(default_factory=dict)
    credentials: list[tuple[UUID, int, bytes]] = field(default_factory=list)
    events: list[tuple[UUID, str]] = field(default_factory=list)

    def platform_app_id(self, app_id: str, *, tenant_id: UUID) -> UUID:
        return APP_ROW_ID

    def persist_grant(self, grant: GrantInput) -> ConnectionRecord:
        key = (grant.tenant_id, grant.platform, grant.external_account_id)
        existing = self.connections.get(key)
        previous_status = existing.status if existing else None
        if existing is None:
            existing = StoredConnection(
                connection_id=uuid4(), grant=grant, status="pending", credential_version=0
            )
            self.connections[key] = existing
        else:
            existing.grant = grant  # a reconnect refreshes scopes/username/page
        version = existing.credential_version + 1
        existing.credential_version = version
        self.credentials.append((existing.connection_id, version, grant.ciphertext))
        self.events.append(
            (existing.connection_id, "granted" if previous_status is None else "reconnected")
        )
        return ConnectionRecord(
            connection_id=existing.connection_id,
            tenant_id=grant.tenant_id,
            credential_version=version,
            previous_status=previous_status,
        )

    def record_status(
        self,
        *,
        connection_id: UUID,
        tenant_id: UUID,
        status: str,
        verified_at: datetime | None,
        event_type: str,
        credential_version: int,
        reconnect_reason: str | None = None,
    ) -> None:
        for stored in self.connections.values():
            if stored.connection_id == connection_id:
                stored.status = status
                stored.reconnect_reason = reconnect_reason
                if verified_at is not None:
                    stored.last_verified_at = verified_at
        self.events.append((connection_id, event_type))

    def only(self) -> StoredConnection:
        assert len(self.connections) == 1, f"expected one connection, got {len(self.connections)}"
        return next(iter(self.connections.values()))


class FakeVerifier:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[UUID, UUID]] = []

    async def verify(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        self.calls.append((tenant_id, connection_id))
        return self.ok


@dataclass
class Harness:
    service: ConnectService
    repo: FakeRepository
    oauth: FakeMetaOAuthClient
    publisher: InMemoryEventPublisher
    verifier: FakeVerifier
    settings: MetaOAuthSettings
    jti_store: JtiStore
    # m-24921205: what the starting browser was handed, per flow. `nonces` maps a state to
    # its binding nonce; every client built by `_client_for` holds the cookies, the way the
    # browser that started the flow would.
    nonces: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    clients: list[TestClient] = field(default_factory=list)


def build_harness(
    *,
    pages: tuple[LinkedPage, ...] = (IG_PAGE,),
    scopes: tuple[str, ...] = GRANTED_LITERALS,
    verify_ok: bool = True,
    repo: FakeRepository | None = None,
    page_subscriptions: PageSubscriptions | None = None,
    redirect_hosts: frozenset[str] = frozenset(),
) -> Harness:
    settings = MetaOAuthSettings(
        app_id="app-1",
        app_secret="secret",
        redirect_uri="https://qualify.test/api/connections/callback",
        state_secret="state-secret",
        redirect_hosts=redirect_hosts,
    )
    repository = repo if repo is not None else FakeRepository()
    oauth = FakeMetaOAuthClient(pages=pages, scopes=scopes)
    publisher = InMemoryEventPublisher()
    verifier = FakeVerifier(ok=verify_ok)
    jti_store = JtiStore(FakeRedis(), ttl_seconds=settings.state_ttl_seconds)
    service = ConnectService(
        settings=settings,
        oauth_client=oauth,
        repository=repository,
        jti_store=jti_store,
        encryptor=DevEncryptor(),
        verifier=verifier,
        publisher=publisher,
        page_subscriptions=page_subscriptions,
    )
    harness = Harness(service, repository, oauth, publisher, verifier, settings, jti_store)
    start = service.start_connect

    def recording_start(**kwargs: object) -> StartedConnect:
        started = start(**kwargs)  # type: ignore[arg-type]
        harness.nonces[oauth.issued_states[-1]] = started.binding_nonce
        harness.cookies[started.binding_cookie_name] = started.binding_nonce
        for client in harness.clients:
            _give_cookie(client, started.binding_cookie_name, started.binding_nonce)
        return started

    service.start_connect = recording_start  # type: ignore[method-assign]
    return harness


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scopes,expected",
    [
        (("instagram_basic", "ads_management"), ConnectOutcome.ADS_ACTIVE),
        (("instagram_basic",), ConnectOutcome.ADS_PERMISSION_MISSING),
    ],
)
async def test_optional_ads_callback_keeps_user_and_page_tokens_separate(
    monkeypatch: pytest.MonkeyPatch, scopes: tuple[str, ...], expected: ConnectOutcome
) -> None:
    harness = build_harness(scopes=scopes)
    await complete(harness, code="organic", state=start_and_extract_state(harness))
    records = []

    class Recorder:
        def record(self, **kwargs: object) -> None:
            records.append(kwargs)

    harness.service._ads_grants = Recorder()
    harness.service._ads_membership_check = lambda tenant, user: None
    target = harness.repo.only().connection_id
    monkeypatch.setattr(
        "qualify_api.connections.service.list_connections",
        lambda tenant: [
            SimpleNamespace(
                connection_id=target,
                brand_id=BRAND,
                platform="instagram",
                external_account_id=IG_PAGE.instagram_account_id,
                reconnect_reason=None,
            )
        ],
    )
    harness.service.start_connect(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, connection_id=target, request_ads=True
    )
    state = harness.oauth.issued_states[-1]
    result = await complete(harness, code="advertising", state=state)
    assert result.outcome is expected
    assert len(records) == 1
    encryptor = DevEncryptor()
    assert encryptor.decrypt(records[0]["ciphertext"], key_id=records[0]["key_id"]) == TOKEN
    stored = harness.repo.only()
    assert encryptor.decrypt(stored.grant.ciphertext, key_id=stored.grant.key_id) == PAGE_TOKEN
    assert records[0]["version"] == stored.credential_version
    assert records[0]["granted_scopes"] == scopes


@pytest.mark.asyncio
async def test_removed_member_cannot_finish_ads_consent_or_exchange_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.connections.ad_accounts import AdAccountUnavailable

    harness = build_harness(scopes=("ads_management",))
    await complete(harness, code="organic", state=start_and_extract_state(harness))
    target = harness.repo.only().connection_id
    monkeypatch.setattr(
        "qualify_api.connections.service.list_connections",
        lambda tenant: [
            SimpleNamespace(
                connection_id=target,
                brand_id=BRAND,
                platform="instagram",
                external_account_id=IG_PAGE.instagram_account_id,
                reconnect_reason=None,
            )
        ],
    )
    harness.service._ads_membership_check = lambda tenant, user: None
    harness.service.start_connect(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, connection_id=target, request_ads=True
    )
    state = harness.oauth.issued_states[-1]

    def removed(tenant: UUID, user: UUID) -> None:
        raise AdAccountUnavailable("Ya no tienes acceso a este negocio. Vuelve a entrar.")

    harness.service._ads_membership_check = removed
    with pytest.raises(AdAccountUnavailable):
        await complete(harness, code="must-not-exchange", state=state)
    assert harness.oauth.exchanged_codes == ["organic"]
    assert len(harness.repo.credentials) == 1


def _give_cookie(client: TestClient, name: str, value: str) -> None:
    client.cookies.set(name, value, domain="testserver.local", path="/api/connections")


async def complete(harness: Harness, *, code: str, state: str) -> ConnectResult:
    """`complete_connect` as the browser that started the flow presents it."""
    return await harness.service.complete_connect(
        code=code, state=state, binding_nonce=harness.nonces.get(state)
    )


def start_and_extract_state(harness: Harness) -> str:
    harness.service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    return harness.oauth.issued_states[-1]


def start_targeted_reconnect(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> str:
    target_id = harness.repo.only().connection_id
    monkeypatch.setattr(
        "qualify_api.connections.service.list_connections",
        lambda tenant: (
            [
                SimpleNamespace(
                    connection_id=target_id,
                    brand_id=BRAND,
                    platform="instagram",
                    external_account_id=IG_PAGE.instagram_account_id,
                    reconnect_reason="permission_missing",
                )
            ]
            if tenant == TENANT
            else []
        ),
    )
    harness.service.start_connect(
        tenant_id=TENANT,
        brand_id=None,
        user_id=USER,
        connection_id=target_id,
        return_to="/inbox",
        cause="permission_missing",
    )
    return harness.oauth.issued_states[-1]


@pytest.mark.asyncio
async def test_reconnect_matches_target_instead_of_first_facebook_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(scopes=("instagram_manage_comments",))
    await complete(harness, code="first", state=start_and_extract_state(harness))
    harness.repo.only().status = "degraded"
    other = LinkedPage("other", "Other", "other-ig", "other-account", "other-token")
    harness.oauth.pages = (other, IG_PAGE)
    result = await complete(
        harness, code="reconnect", state=start_targeted_reconnect(harness, monkeypatch)
    )
    assert result.outcome is ConnectOutcome.ACTIVE
    assert result.return_to == "/inbox"
    assert harness.repo.only().credential_version == 2
    assert harness.repo.only().status == "active"


@pytest.mark.asyncio
async def test_wrong_facebook_never_creates_or_rotates_an_unrelated_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness()
    await complete(harness, code="first", state=start_and_extract_state(harness))
    harness.repo.only().status = "degraded"
    state = start_targeted_reconnect(harness, monkeypatch)
    harness.oauth.pages = (LinkedPage("other", "Other", "other-ig", "other-account"),)
    result = await complete(harness, code="reconnect", state=state)
    assert result.outcome is ConnectOutcome.ACCOUNT_ACCESS_REQUIRED
    assert result.return_to == "/inbox"
    assert harness.repo.only().credential_version == 1
    assert harness.repo.only().status == "degraded"


@pytest.mark.asyncio
async def test_partial_reconsent_does_not_claim_comments_are_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness()
    await complete(harness, code="first", state=start_and_extract_state(harness))
    harness.repo.only().status = "degraded"
    result = await complete(
        harness, code="reconnect", state=start_targeted_reconnect(harness, monkeypatch)
    )
    assert result.outcome is ConnectOutcome.PERMISSION_MISSING
    assert harness.repo.only().status == "degraded"
    assert harness.repo.only().reconnect_reason == "permission_missing"


@pytest.mark.asyncio
async def test_targeted_reconnect_callback_returns_directly_to_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(scopes=("instagram_manage_comments",))
    await complete(harness, code="first", state=start_and_extract_state(harness))
    state = start_targeted_reconnect(harness, monkeypatch)
    response = _client_for(harness).get(
        "/api/connections/callback", params={"code": "reconnect", "state": state}
    )
    page, query = _landing(response)
    assert page == "https://qualify.test/inbox"
    assert query == {"connect": "active", "reconnect": str(harness.repo.only().connection_id)}


@pytest.mark.asyncio
async def test_cancelled_reconnect_returns_to_origin_and_spends_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness()
    await complete(harness, code="first", state=start_and_extract_state(harness))
    state = start_targeted_reconnect(harness, monkeypatch)
    response = _client_for(harness).get(
        "/api/connections/callback", params={"error": "access_denied", "state": state}
    )
    page, query = _landing(response)
    assert page == "https://qualify.test/inbox"
    assert query["connect"] == "denied"
    with pytest.raises(InvalidState):
        await complete(harness, code="replay", state=state)


@pytest.mark.asyncio
async def test_failed_token_exchange_returns_to_origin_without_reusing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.connections.meta_oauth import MetaOAuthError

    harness = build_harness()
    await complete(harness, code="first", state=start_and_extract_state(harness))
    state = start_targeted_reconnect(harness, monkeypatch)

    async def unavailable(code: str, *, redirect_uri: str = "") -> TokenGrant:
        raise MetaOAuthError("unavailable")

    monkeypatch.setattr(harness.oauth, "exchange_code", unavailable)
    page, query = _landing(
        _client_for(harness).get(
            "/api/connections/callback", params={"code": "reconnect", "state": state}
        )
    )
    assert page == "https://qualify.test/inbox"
    assert query["connect"] == "degraded"
    with pytest.raises(InvalidState):
        await complete(harness, code="replay", state=state)


def test_cannot_start_reconnect_for_another_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.connections.revoke import ConnectionNotFound

    harness = build_harness()
    monkeypatch.setattr("qualify_api.connections.service.list_connections", lambda tenant: [])
    with pytest.raises(ConnectionNotFound):
        harness.service.start_connect(
            tenant_id=TENANT,
            brand_id=None,
            user_id=USER,
            connection_id=uuid4(),
            return_to="/inbox",
        )
    assert harness.oauth.issued_states == []


def test_reconnect_uses_persisted_permission_cause_over_stale_ui_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness()
    connection_id = uuid4()
    monkeypatch.setattr(
        "qualify_api.connections.service.list_connections",
        lambda tenant: [
            SimpleNamespace(
                connection_id=connection_id,
                brand_id=BRAND,
                platform="instagram",
                external_account_id="expected-ig",
                reconnect_reason="permission_missing",
            )
        ],
    )
    url = harness.service.start_connect(
        tenant_id=TENANT,
        brand_id=None,
        user_id=USER,
        connection_id=connection_id,
        cause="auth_expired",
        return_to="/conversations",
    )
    assert "auth_type=rerequest" in url.authorization_url


# --------------------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_connect_becomes_active() -> None:
    harness = build_harness()
    state = start_and_extract_state(harness)

    result = await complete(harness, code="code-1", state=state)

    assert result.outcome is ConnectOutcome.ACTIVE
    assert result.external_username == "@puntoservis"
    stored = harness.repo.only()
    assert stored.status == "active"
    assert stored.credential_version == 1
    assert stored.last_verified_at is not None


@pytest.mark.asyncio
async def test_connect_records_granted_literals_verbatim() -> None:
    """C-04.3: what was GRANTED, not what was requested, and uninterpreted.

    Also A1's shield: with `config_id`, what the dialog asks for is decided by a console
    artifact outside version control, so `/me/permissions` → `granted_scopes` persistence
    is the only in-repo truth about what was conceded. If this stops persisting, that
    truth is gone — this test failing is the alarm.
    """
    partial = ("scope_alpha",)  # user declined the rest
    harness = build_harness(scopes=partial)
    result = await complete(harness, code="c", state=start_and_extract_state(harness))

    assert result.outcome is ConnectOutcome.ACTIVE
    assert harness.repo.only().grant.granted_scopes == partial


@pytest.mark.asyncio
async def test_verification_runs_through_the_resolver_seam() -> None:
    harness = build_harness()
    await complete(harness, code="c", state=start_and_extract_state(harness))
    # The verifier is handed ids only — there is no parameter through which a token could
    # travel, which is the structural half of "verify never sees a raw token".
    assert harness.verifier.calls == [(TENANT, harness.repo.only().connection_id)]


# --------------------------------------------------------------------------------------
# R4 — the login fork
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_pages_yields_page_access_required_and_persists_nothing() -> None:
    """R9(f): zero Pages is NOT `link_required`.

    Meta filters `/me/accounts` by TASKS, not ownership, so an operator who administers the
    Business Portfolio owning the Page still sees nothing here. Telling them to "link your
    Instagram" would send them to a setting that is already correct; they need Page access.
    """
    harness = build_harness(pages=())

    result = await complete(harness, code="c", state=start_and_extract_state(harness))

    assert result.outcome is ConnectOutcome.PAGE_ACCESS_REQUIRED
    assert result.connection_id is None
    # The invariant R4 preserves, unchanged by the split: zero connection, zero credential.
    assert harness.repo.connections == {}
    assert harness.repo.credentials == []
    assert harness.publisher.events == []


@pytest.mark.asyncio
async def test_page_without_linked_instagram_yields_link_required() -> None:
    """The genuine R4 case: the Page IS reachable, it just has no IG account linked."""
    harness = build_harness(pages=(PAGE_WITHOUT_IG,))
    result = await complete(harness, code="c", state=start_and_extract_state(harness))
    assert result.outcome is ConnectOutcome.LINK_REQUIRED
    assert harness.repo.connections == {}


@pytest.mark.asyncio
async def test_the_two_dead_ends_are_distinguishable() -> None:
    """The whole point of R9(f), asserted directly: these two situations demand OPPOSITE
    instructions from the operator, so they must not compare equal."""
    empty = build_harness(pages=())
    no_pages = await complete(empty, code="c", state=start_and_extract_state(empty))

    unlinked_harness = build_harness(pages=(PAGE_WITHOUT_IG,))
    unlinked = await complete(
        unlinked_harness, code="c", state=start_and_extract_state(unlinked_harness)
    )

    assert no_pages.outcome is not unlinked.outcome
    # Both are still dead ends — the split must not have accidentally made one succeed.
    assert no_pages.connection_id is None and unlinked.connection_id is None


@pytest.mark.asyncio
async def test_counts_are_recorded_for_zero_pages() -> None:
    """R9(e.1): the two integers that let step 1 of the empirical test conclude."""
    harness = build_harness(pages=())
    result = await complete(harness, code="c", state=start_and_extract_state(harness))
    assert (result.page_count, result.linked_page_count) == (0, 0)


@pytest.mark.asyncio
async def test_counts_distinguish_pages_present_from_pages_linked() -> None:
    """Two Pages reachable, neither linked — the counts say so without a second live run."""
    harness = build_harness(pages=(PAGE_WITHOUT_IG, PAGE_WITHOUT_IG))
    result = await complete(harness, code="c", state=start_and_extract_state(harness))
    assert (result.page_count, result.linked_page_count) == (2, 0)


@pytest.mark.asyncio
async def test_dead_end_log_carries_counts_but_no_identifiers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log is evidence for the empirical test, so it must contain the counts — and it
    must NOT contain the token, page id, page name or username, which are all in scope at
    that point in the flow."""
    harness = build_harness(pages=(PAGE_WITHOUT_IG,))
    with caplog.at_level("WARNING"):
        await complete(harness, code="c", state=start_and_extract_state(harness))

    text = caplog.text
    assert "pages=1" in text and "pages_with_ig=0" in text
    assert TOKEN not in text
    assert PAGE_WITHOUT_IG.page_id not in text
    assert PAGE_WITHOUT_IG.page_name not in text


@pytest.mark.asyncio
async def test_a_dead_end_still_consumes_the_jti() -> None:
    """R4: the state is spent on every path, so recovery means starting a fresh flow."""
    harness = build_harness(pages=())
    state = start_and_extract_state(harness)
    await complete(harness, code="c", state=state)
    with pytest.raises(InvalidState):
        await complete(harness, code="c", state=state)


# --------------------------------------------------------------------------------------
# state: forgery, replay, expiry
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replayed_state_is_rejected_and_writes_nothing() -> None:
    harness = build_harness()
    state = start_and_extract_state(harness)
    await complete(harness, code="c", state=state)
    before = len(harness.repo.credentials)

    with pytest.raises(InvalidState):
        await complete(harness, code="c", state=state)

    assert len(harness.repo.credentials) == before  # replay appended no credential


@pytest.mark.asyncio
async def test_forged_state_never_reaches_the_token_exchange() -> None:
    """A bad signature must cost nothing: no code exchange, no platform call, no row."""
    harness = build_harness()
    forged = sign_state(new_payload(TENANT, BRAND, USER), "attacker-secret")

    with pytest.raises(InvalidState):
        await complete(harness, code="c", state=forged)

    assert harness.oauth.exchanged_codes == []
    assert harness.repo.connections == {}


# --------------------------------------------------------------------------------------
# Verification failure and idempotency
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_verification_is_born_degraded_not_active() -> None:
    harness = build_harness(verify_ok=False)

    result = await complete(harness, code="c", state=start_and_extract_state(harness))

    assert result.outcome is ConnectOutcome.DEGRADED
    stored = harness.repo.only()
    assert stored.status == "degraded"
    assert stored.last_verified_at is None  # never verified, so no timestamp claiming it was
    assert DomainEventName.ACTIVATED not in harness.publisher.names()
    assert DomainEventName.DEGRADED in harness.publisher.names()


@pytest.mark.asyncio
async def test_reconnect_updates_the_row_and_appends_a_credential_version() -> None:
    """C-04.4: unique(tenant_id, platform, external_account_id) — never a second row."""
    repo = FakeRepository()
    first = build_harness(repo=repo)
    await complete(first, code="c1", state=start_and_extract_state(first))
    original_id = repo.only().connection_id

    second = build_harness(repo=repo, scopes=("scope_alpha", "scope_beta", "scope_gamma"))
    await complete(second, code="c2", state=start_and_extract_state(second))

    assert len(repo.connections) == 1
    assert repo.only().connection_id == original_id  # same row, not a duplicate
    assert repo.only().credential_version == 2  # append-only version bump
    assert repo.only().grant.granted_scopes == ("scope_alpha", "scope_beta", "scope_gamma")
    assert [v for _, v, _ in repo.credentials] == [1, 2]


@pytest.mark.asyncio
async def test_reconnect_of_a_degraded_connection_recovers_it() -> None:
    repo = FakeRepository()
    broken = build_harness(repo=repo, verify_ok=False)
    await complete(broken, code="c1", state=start_and_extract_state(broken))
    assert repo.only().status == "degraded"

    fixed = build_harness(repo=repo, verify_ok=True)
    result = await complete(fixed, code="c2", state=start_and_extract_state(fixed))

    assert result.outcome is ConnectOutcome.ACTIVE
    assert repo.only().status == "active"
    assert DomainEventName.RECONNECTED in fixed.publisher.names()


@pytest.mark.asyncio
async def test_reconnect_of_a_revoked_connection_that_fails_verify_degrades() -> None:
    """C-04 Q2: the row now carries a rotated credential, so `revoked` would be a lie.

    This is the callback-level half of the FSM edge `(revoked, verify_fail) → degraded`:
    a credential version WAS appended, so the status has to describe the row as it now is.
    """
    repo = FakeRepository()
    first = build_harness(repo=repo)
    await complete(first, code="c1", state=start_and_extract_state(first))
    repo.only().status = "revoked"  # the user disconnected in the CRM (C-06)

    broken = build_harness(repo=repo, verify_ok=False)
    result = await complete(broken, code="c2", state=start_and_extract_state(broken))

    assert result.outcome is ConnectOutcome.DEGRADED
    assert repo.only().status == "degraded"
    assert repo.only().credential_version == 2  # a credential really was appended
    assert DomainEventName.DEGRADED in broken.publisher.names()
    assert DomainEventName.RECONNECTED not in broken.publisher.names()


# --------------------------------------------------------------------------------------
# Token containment
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_is_never_persisted_in_plaintext_or_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A token in an archived payload or a log line is a PERSISTENT leak (§2.6)."""
    caplog.set_level(logging.DEBUG)
    harness = build_harness()

    result = await complete(harness, code="c", state=start_and_extract_state(harness))

    stored = harness.repo.only()
    for secret in (TOKEN, PAGE_TOKEN):
        assert secret.encode() not in stored.grant.ciphertext
        assert secret not in repr(stored.grant)
        assert secret not in repr(result)
        assert all(secret not in record.getMessage() for record in caplog.records)
    # And the ciphertext genuinely round-trips, so "encrypted" is not "mangled". What
    # round-trips is the PAGE token — the credential publishing actually accepts (A0).
    assert DevEncryptor().decrypt(stored.grant.ciphertext, key_id=stored.grant.key_id) == PAGE_TOKEN


def test_token_grant_repr_redacts() -> None:
    assert TOKEN not in repr(TokenGrant(access_token=TOKEN, token_type="bearer", expires_in=1))


def test_linked_page_repr_redacts() -> None:
    assert PAGE_TOKEN not in repr(IG_PAGE)


@pytest.mark.asyncio
async def test_page_token_is_custodied_with_token_type_page() -> None:
    """A0: the credential in custody is the Page's, and `token_type` says so — the row
    stays distinguishable forever from pre-A0 rows that hold a user token."""
    harness = build_harness()

    await complete(harness, code="c", state=start_and_extract_state(harness))

    stored = harness.repo.only()
    assert stored.grant.token_type == "page"
    assert DevEncryptor().decrypt(stored.grant.ciphertext, key_id=stored.grant.key_id) == PAGE_TOKEN


@pytest.mark.asyncio
async def test_missing_page_token_falls_back_to_user_token_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`[V]` guard: until the live response is observed, a Page without `access_token`
    must not kill the connect — the user token is custodied as before, the fallback is
    logged, and `token_type` keeps the two cases distinguishable."""
    caplog.set_level(logging.WARNING)
    page = LinkedPage(
        page_id="page-1",
        page_name="PuntoServis",
        instagram_account_id="17841400000000000",
        instagram_username="@puntoservis",
        page_access_token=None,
    )
    harness = build_harness(pages=(page,))

    result = await complete(harness, code="c", state=start_and_extract_state(harness))

    assert result.outcome is ConnectOutcome.ACTIVE
    stored = harness.repo.only()
    assert stored.grant.token_type == "bearer"
    assert DevEncryptor().decrypt(stored.grant.ciphertext, key_id=stored.grant.key_id) == TOKEN
    assert any("USER token as fallback" in record.getMessage() for record in caplog.records)


def test_accounts_parser_reads_the_page_access_token() -> None:
    """[V] parser: `access_token` is picked up when present and None when absent —
    absence is an observation for the service, not a parse error."""
    pages = _parse_accounts_response(
        {
            "data": [
                {
                    "id": "1",
                    "name": "With token",
                    "access_token": PAGE_TOKEN,
                    "instagram_business_account": {"id": "9", "username": "u"},
                },
                {"id": "2", "name": "Without token"},
            ]
        }
    )
    assert pages[0].page_access_token == PAGE_TOKEN
    assert pages[1].page_access_token is None


@pytest.mark.asyncio
async def test_live_accounts_request_asks_for_the_access_token_field() -> None:
    """A0: Meta only returns the Page token if the request NAMES it — no tolerant parser
    can recover a field that was never sent, so the query itself is the criterion."""
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": []})

    client = HttpMetaOAuthClient(
        MetaOAuthSettings(app_id="a", app_secret="s", redirect_uri="https://cb", state_secret="k"),
        transport=httpx.MockTransport(capture),
    )
    await client.list_linked_pages("user-token")
    assert "access_token" in seen["fields"].split(",")


def _dialog_params(*, config_id: str | None) -> dict[str, str]:
    client = HttpMetaOAuthClient(
        MetaOAuthSettings(
            app_id="a",
            app_secret="s",
            redirect_uri="https://cb",
            state_secret="k",
            requested_scopes=("scope_alpha", "scope_beta"),
            config_id=config_id,
        )
    )
    query = urlsplit(client.authorization_url(state="st")).query
    return dict(parse_qsl(query))


def test_authorization_url_carries_config_id_alongside_scope() -> None:
    """A1: `config_id` and `scope` coexist — neither cancels the other."""
    params = _dialog_params(config_id="cfg-from-env")
    assert params["config_id"] == "cfg-from-env"
    assert params["scope"] == "scope_alpha,scope_beta"


def test_authorization_url_omits_config_id_entirely_when_unset() -> None:
    """A1: absent means ABSENT — an empty `config_id=` is not equivalent to omission
    for an authorization endpoint (same rule the scope already follows)."""
    params = _dialog_params(config_id=None)
    assert "config_id" not in params
    assert params["scope"] == "scope_alpha,scope_beta"


def test_authorization_url_rerequest_is_a_retry_only_parameter() -> None:
    """QUA-202: a first visit never carries `auth_type`; the retry after
    `page_access_required` carries `auth_type=rerequest` so Meta shows the Page picker
    again instead of skipping what was left unticked."""
    client = HttpMetaOAuthClient(
        MetaOAuthSettings(app_id="a", app_secret="s", redirect_uri="https://cb", state_secret="k")
    )
    first = dict(parse_qsl(urlsplit(client.authorization_url(state="st")).query))
    retry = dict(parse_qsl(urlsplit(client.authorization_url(state="st", rerequest=True)).query))
    assert "auth_type" not in first
    assert retry["auth_type"] == "rerequest"
    assert {k: v for k, v in retry.items() if k != "auth_type"} == first


def test_start_connect_passes_rerequest_through_to_the_dialog() -> None:
    harness = build_harness()
    plain = harness.service.start_connect(tenant_id=TENANT, brand_id=None, user_id=USER)
    retry = harness.service.start_connect(
        tenant_id=TENANT, brand_id=None, user_id=USER, rerequest=True
    )
    assert "auth_type=rerequest" not in plain.authorization_url
    assert "auth_type=rerequest" in retry.authorization_url


# --------------------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------------------


PAGE_URL = "https://qualify.test/connections"


def _client_for(harness: Harness) -> TestClient:
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: harness.service
    app.dependency_overrides[connections_routes.get_connections_page_url] = lambda: PAGE_URL
    client = TestClient(app, follow_redirects=False)
    for name, value in harness.cookies.items():
        _give_cookie(client, name, value)
    harness.clients.append(client)
    return client


@pytest.fixture
def client_and_harness() -> tuple[TestClient, Harness]:
    harness = build_harness()
    return _client_for(harness), harness


def _landing(response: httpx.Response) -> tuple[str, dict[str, str]]:
    """(page the browser is sent to, its query) — asserting on the parsed query, not the
    raw string, so the test pins the contract and not urlencode's formatting."""
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    return f"{location.scheme}://{location.netloc}{location.path}", dict(parse_qsl(location.query))


def test_callback_route_redirects_to_connections_with_outcome(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    """QUA-123: the browser Meta sent here lands on the UI, not on a JSON body."""
    client, harness = client_and_harness
    state = start_and_extract_state(harness)

    response = client.get("/api/connections/callback", params={"code": "c", "state": state})

    assert _landing(response) == (PAGE_URL, {"connect": "active"})
    assert len(harness.repo.connections) == 1
    assert TOKEN not in response.text
    assert TOKEN not in response.headers["location"]


def test_callback_redirect_carries_no_identifier(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    """Only the closed outcome code travels in the URL on success: no connection id, no
    username, no counts. The page re-reads the list from Postgres."""
    client, harness = client_and_harness
    response = client.get(
        "/api/connections/callback",
        params={"code": "c", "state": start_and_extract_state(harness)},
    )

    location = response.headers["location"]
    (stored,) = harness.repo.connections.values()
    assert str(stored.connection_id) not in location
    assert "puntoservis" not in location.lower()
    assert set(_landing(response)[1]) == {"connect"}


def test_dead_end_redirects_carry_counts_and_nothing_else() -> None:
    """QUA-202: the two outcomes the operator must act on carry the R9(e.1) counts —
    integers only — so the page can say "Meta nos mostró 2 Páginas, ninguna con tu
    Instagram". The Page's id and name from `/me/accounts` never reach the URL."""
    harness = build_harness(pages=(PAGE_WITHOUT_IG, PAGE_WITHOUT_IG))
    response = _client_for(harness).get(
        "/api/connections/callback",
        params={"code": "c", "state": start_and_extract_state(harness)},
    )

    page_url, query = _landing(response)
    assert page_url == PAGE_URL
    assert query == {"connect": "link_required", "pages": "2", "linked": "0"}
    location = response.headers["location"].lower()
    assert PAGE_WITHOUT_IG.page_id not in location
    assert PAGE_WITHOUT_IG.page_name.lower() not in location
    assert TOKEN not in location


def test_callback_route_bad_state_redirects_as_invalid_state(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    client, harness = client_and_harness
    response = client.get(
        "/api/connections/callback", params={"code": "c", "state": "not-a-real-state"}
    )
    assert _landing(response) == (PAGE_URL, {"connect": "invalid_state"})
    assert harness.oauth.exchanged_codes == []  # a forged state costs nothing
    assert TOKEN not in response.text


def test_callback_route_replayed_state_redirects_as_invalid_state(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    """A browser refresh on the callback URL replays the state: the second hit must land
    on the same calm page, not on an error body, and must not exchange the code twice."""
    client, harness = client_and_harness
    params = {"code": "c", "state": start_and_extract_state(harness)}

    first = client.get("/api/connections/callback", params=params)
    second = client.get("/api/connections/callback", params=params)

    assert _landing(first)[1] == {"connect": "active"}
    assert _landing(second)[1] == {"connect": "invalid_state"}
    assert harness.oauth.exchanged_codes == ["c"]


def test_callback_route_user_cancel_redirects_as_denied(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    """Meta's cancel comes back with `error=...` and no `code`; that used to be a 422."""
    client, harness = client_and_harness
    response = client.get(
        "/api/connections/callback",
        params={
            "error": "access_denied",
            "error_reason": "user_denied",
            "error_description": "Permissions error",
            "state": start_and_extract_state(harness),
        },
    )
    assert _landing(response) == (PAGE_URL, {"connect": "denied"})
    assert harness.oauth.exchanged_codes == []
    assert harness.repo.connections == {}


def test_callback_route_without_code_or_error_is_invalid_state(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    client, _ = client_and_harness
    assert _landing(client.get("/api/connections/callback"))[1] == {"connect": "invalid_state"}
    assert _landing(client.get("/api/connections/callback", params={"code": "c"}))[1] == {
        "connect": "invalid_state"
    }


def test_callback_route_zero_pages_redirects_as_page_access_required() -> None:
    harness = build_harness(pages=())
    response = _client_for(harness).get(
        "/api/connections/callback",
        params={"code": "c", "state": start_and_extract_state(harness)},
    )
    assert _landing(response) == (
        PAGE_URL,
        {"connect": "page_access_required", "pages": "0", "linked": "0"},
    )
    assert harness.repo.connections == {}


def test_callback_route_unlinked_page_redirects_as_link_required() -> None:
    harness = build_harness(pages=(PAGE_WITHOUT_IG,))
    response = _client_for(harness).get(
        "/api/connections/callback",
        params={"code": "c", "state": start_and_extract_state(harness)},
    )
    assert _landing(response) == (
        PAGE_URL,
        {"connect": "link_required", "pages": "1", "linked": "0"},
    )
    assert harness.repo.connections == {}


def test_callback_redirect_codes_are_exactly_the_ui_vocabulary() -> None:
    """Every code the route can emit has a notice in the UI, and vice versa — the table in
    `Qualify/connections_vm.py` is the other half of this contract."""
    emitted = {str(o) for o in ConnectOutcome} | {
        connections_routes.INVALID_STATE,
        connections_routes.DENIED,
        connections_routes.ADS_DENIED,
    }
    assert emitted == {
        "active",
        "degraded",
        "link_required",
        "page_access_required",
        "invalid_state",
        "denied",
        "permission_missing",
        "account_access_required",
        "ads_active",
        "ads_permission_missing",
        "ads_denied",
    }


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "http://localhost:3000/connections"),
        ({"REFLEX_DEPLOY_URL": "https://qualify.example/"}, "https://qualify.example/connections"),
        (
            {"REFLEX_DEPLOY_URL": "https://a.example", "QUALIFY_APP_URL": "https://b.example"},
            "https://b.example/connections",
        ),
    ],
)
def test_connections_page_url_from_env(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    monkeypatch.delenv("QUALIFY_APP_URL", raising=False)
    monkeypatch.delenv("REFLEX_DEPLOY_URL", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert connections_routes.configured_connections_page_url() == expected


def test_start_route_rejects_unauthenticated_with_401() -> None:
    """C1: identity comes from the authenticated Principal. No credential -> 401 — "you
    are not authenticated" is a fact about the request, not a 409 about server state."""
    harness = build_harness()
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: harness.service
    app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    client = TestClient(app)

    response = client.post("/api/connections/start", json={})
    assert response.status_code == 401


def test_start_request_model_has_no_identity_fields() -> None:
    """Structural: no field through which a client could name its own tenant OR choose
    the user the connection is attributed to (C1 removed `user_id` — same bypass)."""
    assert "tenant_id" not in connections_routes.StartConnectRequest.model_fields
    assert "user_id" not in connections_routes.StartConnectRequest.model_fields


# --------------------------------------------------------------------------------------
# m-24789549: Page subscription to the app's webhooks
# --------------------------------------------------------------------------------------


class _SubscriptionClient:
    def __init__(self, result: SubscriptionResult | None = None, *, raises: bool = False):
        self.result = result or SubscriptionResult(ok=True)
        self.raises = raises
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def subscribe(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> SubscriptionResult:
        self.calls.append((tenant_id, connection_id, page_id))
        if self.raises:
            raise RuntimeError("graph exploded")
        return self.result

    def unsubscribe(self, *, page_id: str) -> SubscriptionResult:
        raise AssertionError("connect never unsubscribes")


class _SubscriptionRecorder:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.rows.append(kwargs)

    def page_shared_by_live_connection(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> bool:
        return False


@pytest.mark.asyncio
async def test_connect_subscribes_the_linked_page_and_records_it() -> None:
    client, recorder = _SubscriptionClient(), _SubscriptionRecorder()
    harness = build_harness(page_subscriptions=PageSubscriptions(client=client, recorder=recorder))
    state = start_and_extract_state(harness)

    result = await complete(harness, code="code-1", state=state)

    assert result.outcome is ConnectOutcome.ACTIVE
    assert client.calls == [(TENANT, result.connection_id, IG_PAGE.page_id)]
    assert [(r["event_type"], r["credential_version"]) for r in recorder.rows] == [
        (EVENT_PAGE_SUBSCRIBED, 1)
    ]


@pytest.mark.parametrize(
    "client",
    [
        _SubscriptionClient(SubscriptionResult(ok=False, error_code="200")),
        _SubscriptionClient(raises=True),
    ],
)
@pytest.mark.asyncio
async def test_subscription_failure_never_fails_the_connection(
    client: _SubscriptionClient,
) -> None:
    recorder = _SubscriptionRecorder()
    harness = build_harness(page_subscriptions=PageSubscriptions(client=client, recorder=recorder))
    state = start_and_extract_state(harness)

    result = await complete(harness, code="code-1", state=state)

    assert result.outcome is ConnectOutcome.ACTIVE
    assert harness.repo.only().status == "active"
    assert [r["event_type"] for r in recorder.rows] == [EVENT_PAGE_SUBSCRIBE_FAILED]


@pytest.mark.asyncio
async def test_no_connection_means_no_subscription_attempt() -> None:
    client, recorder = _SubscriptionClient(), _SubscriptionRecorder()
    harness = build_harness(
        pages=(PAGE_WITHOUT_IG,),
        page_subscriptions=PageSubscriptions(client=client, recorder=recorder),
    )
    state = start_and_extract_state(harness)

    result = await complete(harness, code="code-1", state=state)

    assert result.outcome is ConnectOutcome.LINK_REQUIRED
    assert client.calls == []
    assert recorder.rows == []


# --------------------------------------------------------------------------------------
# m-24921205: the callback is bound to the browser that started the flow
# --------------------------------------------------------------------------------------


def _foreign_client(harness: Harness) -> TestClient:
    """Somebody else's browser: same app, none of the starting browser's cookies."""
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: harness.service
    app.dependency_overrides[connections_routes.get_connections_page_url] = lambda: PAGE_URL
    return TestClient(app, follow_redirects=False)


def _start_bound(harness: Harness) -> tuple[str, StartedConnect]:
    started = harness.service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    return harness.oauth.issued_states[-1], started


def _cleared_cookies(response: httpx.Response) -> list[str]:
    return [
        header.split("=", 1)[0]
        for header in response.headers.get_list("set-cookie")
        if "max-age=0" in header.lower()
    ]


def test_the_signed_state_carries_only_the_hash_of_the_binding_nonce() -> None:
    harness = build_harness()
    state, started = _start_bound(harness)
    payload = harness.service.callback_context(state)
    assert payload.binding == binding_hash(started.binding_nonce)
    assert started.binding_nonce not in state
    assert started.binding_cookie_name == f"qoauth_meta_{payload.jti[:16]}"
    assert started.max_age == harness.settings.state_ttl_seconds
    assert started.callback_url == harness.settings.redirect_uri
    assert started.binding_nonce not in repr(started)


def test_binding_matches_is_strict() -> None:
    nonce = "n" * 43
    bound = new_payload(TENANT, BRAND, USER, binding=binding_hash(nonce))
    assert binding_matches(bound, nonce)
    assert not binding_matches(bound, nonce + "x")
    assert not binding_matches(bound, None)
    assert not binding_matches(bound, "")
    legacy = new_payload(TENANT, BRAND, USER)  # minted before the binding existed
    assert not binding_matches(legacy, "")
    assert not binding_matches(legacy, nonce)


def test_bound_browser_connects_and_the_cookie_is_cleared() -> None:
    harness = build_harness()
    client = _client_for(harness)
    state, started = _start_bound(harness)
    response = client.get("/api/connections/callback", params={"code": "c", "state": state})
    assert _landing(response) == (PAGE_URL, {"connect": "active"})
    assert started.binding_cookie_name in _cleared_cookies(response)


@pytest.mark.asyncio
async def test_missing_cookie_is_invalid_state_and_burns_the_state() -> None:
    """The attack: the victim's browser arrives with the attacker's state and no cookie."""
    harness = build_harness()
    state, started = _start_bound(harness)
    response = _foreign_client(harness).get(
        "/api/connections/callback", params={"code": "victim-code", "state": state}
    )
    assert _landing(response) == (PAGE_URL, {"connect": "invalid_state"})
    assert harness.oauth.exchanged_codes == []  # the victim's code is never exchanged
    assert harness.repo.connections == {} and harness.repo.credentials == []
    assert started.binding_cookie_name in _cleared_cookies(response)
    # Spent: not even the starting browser can complete it afterwards.
    again = _client_for(harness).get(
        "/api/connections/callback", params={"code": "c", "state": state}
    )
    assert _landing(again) == (PAGE_URL, {"connect": "invalid_state"})
    assert harness.oauth.exchanged_codes == []


@pytest.mark.asyncio
async def test_cookie_of_another_flow_or_a_wrong_value_never_binds() -> None:
    harness = build_harness()
    state_a, started_a = _start_bound(harness)
    _state_b, started_b = _start_bound(harness)
    # A valid nonce, but of another flow, under A's cookie name.
    client = _foreign_client(harness)
    _give_cookie(client, started_a.binding_cookie_name, started_b.binding_nonce)
    response = client.get("/api/connections/callback", params={"code": "c", "state": state_a})
    assert _landing(response) == (PAGE_URL, {"connect": "invalid_state"})
    assert harness.oauth.exchanged_codes == [] and harness.repo.connections == {}
    with pytest.raises(InvalidState):
        await harness.service.complete_connect(
            code="c", state=state_a, binding_nonce=started_a.binding_nonce
        )
    # Service level, directly: a wrong value is rejected before the exchange.
    state_c, _ = _start_bound(harness)
    with pytest.raises(InvalidState):
        await harness.service.complete_connect(code="c", state=state_c, binding_nonce="forged")
    assert harness.oauth.exchanged_codes == []


@pytest.mark.asyncio
async def test_replay_with_the_right_cookie_is_still_invalid_state() -> None:
    harness = build_harness()
    state, started = _start_bound(harness)
    await harness.service.complete_connect(
        code="c", state=state, binding_nonce=started.binding_nonce
    )
    with pytest.raises(InvalidState):
        await harness.service.complete_connect(
            code="c", state=state, binding_nonce=started.binding_nonce
        )
    assert harness.oauth.exchanged_codes == ["c"]


@pytest.mark.asyncio
async def test_unbound_cancel_spends_the_state_and_trusts_no_return_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness()
    await complete(harness, code="first", state=start_and_extract_state(harness))
    state = start_targeted_reconnect(harness, monkeypatch)
    response = _foreign_client(harness).get(
        "/api/connections/callback", params={"error": "access_denied", "state": state}
    )
    assert _landing(response) == (PAGE_URL, {"connect": "invalid_state"})  # not /inbox
    with pytest.raises(InvalidState):
        await complete(harness, code="late", state=state)


def test_start_route_sets_the_httponly_binding_cookie() -> None:
    harness = build_harness()
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: harness.service
    app.dependency_overrides[deps.current_principal] = lambda: deps.Principal(TENANT, USER)
    response = TestClient(app).post("/api/connections/start", json={})
    assert response.status_code == 200
    (cookie,) = response.headers.get_list("set-cookie")
    attrs = [part.strip().lower() for part in cookie.split(";")]
    name, value = cookie.split(";", 1)[0].split("=", 1)
    assert name.startswith("qoauth_meta_")
    assert {"httponly", "secure", "path=/api/connections", "samesite=lax"} <= set(attrs)
    assert f"max-age={harness.settings.state_ttl_seconds}" in attrs
    assert not any(attr.startswith("domain=") for attr in attrs)  # host-only
    payload = harness.service.callback_context(harness.oauth.issued_states[-1])
    assert binding_hash(value) == payload.binding
    assert value not in response.json()["authorization_url"]


# --------------------------------------------------------------------------------------
# Same host (m-24947215)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meta_flow_runs_on_the_page_host_once_its_callback_is_registered() -> None:
    harness = build_harness(redirect_hosts=frozenset({"app.qualify.la"}))
    started = harness.service.start_connect(
        tenant_id=TENANT, brand_id=None, user_id=USER, browser_origin="https://app.qualify.la"
    )
    expected = "https://app.qualify.la/api/connections/callback"
    assert started.callback_url == expected
    assert harness.oauth.authorize_redirects[-1] == expected
    state = harness.oauth.issued_states[-1]
    await harness.service.complete_connect(
        code="code-1", state=state, binding_nonce=harness.nonces[state]
    )
    assert harness.oauth.exchange_redirects[-1] == expected  # the exchange repeats it


@pytest.mark.parametrize(
    "origin", ["https://app.qualify.la", "https://evil.example", "http://qualify.test", ""]
)
def test_meta_stays_on_its_registered_callback_by_default(origin: str) -> None:
    """Without `QUALIFY_META_REDIRECT_HOSTS` Meta keeps its one registered redirect URI —
    a URI Meta does not know would fail at its dialog."""
    harness = build_harness()
    started = harness.service.start_connect(
        tenant_id=TENANT, brand_id=None, user_id=USER, browser_origin=origin
    )
    assert started.callback_url == "https://qualify.test/api/connections/callback"
    assert harness.oauth.authorize_redirects[-1] == started.callback_url


@pytest.mark.asyncio
async def test_a_legacy_state_without_redirect_uri_exchanges_with_the_configured_one() -> None:
    harness = build_harness()
    harness.service.start_connect(tenant_id=TENANT, brand_id=None, user_id=USER)
    state = harness.oauth.issued_states[-1]
    await harness.service.complete_connect(
        code="code-1", state=state, binding_nonce=harness.nonces[state]
    )
    assert harness.oauth.exchange_redirects[-1] == "https://qualify.test/api/connections/callback"


def test_meta_callback_lands_on_the_public_host_it_arrived_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_PUBLIC_URL", "https://qualify.test")
    monkeypatch.setenv("QUALIFY_PUBLIC_HOSTS", "app.qualify.la")
    monkeypatch.setenv("QUALIFY_APP_URL", "https://qualify.test")
    harness = build_harness()
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: harness.service
    for host, landing in (
        ("app.qualify.la", "https://app.qualify.la/connections?connect=denied"),
        ("evil.example", "https://qualify.test/connections?connect=denied"),
    ):
        client = TestClient(app, base_url=f"https://{host}", follow_redirects=False)
        response = client.get("/api/connections/callback?error=access_denied")
        assert response.headers["location"] == landing
