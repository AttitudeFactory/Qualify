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
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.events import DomainEventName, InMemoryEventPublisher
from qualify_api.connections.meta_oauth import LinkedPage, TokenGrant
from qualify_api.connections.repository import ConnectionRecord, GrantInput
from qualify_api.connections.service import ConnectOutcome, ConnectService
from qualify_api.connections.state_token import InvalidState, JtiStore, new_payload, sign_state
from qualify_api.http import connections_routes
from qualify_api.http.app import create_app

TENANT = UUID("11111111-1111-4111-8111-111111111111")
BRAND = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
APP_ROW_ID = UUID("44444444-4444-4444-8444-444444444444")

TOKEN = "SUPER_SECRET_ACCESS_TOKEN"
GRANTED_LITERALS = ("scope_alpha", "scope_beta")

IG_PAGE = LinkedPage(
    page_id="page-1",
    page_name="PuntoServis",
    instagram_account_id="17841400000000000",
    instagram_username="@puntoservis",
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

    def authorization_url(self, *, state: str) -> str:
        self.issued_states.append(state)
        return f"https://platform.example/dialog?state={state}"

    async def exchange_code(self, code: str) -> TokenGrant:
        self.exchanged_codes.append(code)
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
    ) -> None:
        for stored in self.connections.values():
            if stored.connection_id == connection_id:
                stored.status = status
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


def build_harness(
    *,
    pages: tuple[LinkedPage, ...] = (IG_PAGE,),
    scopes: tuple[str, ...] = GRANTED_LITERALS,
    verify_ok: bool = True,
    repo: FakeRepository | None = None,
) -> Harness:
    settings = MetaOAuthSettings(
        app_id="app-1",
        app_secret="secret",
        redirect_uri="https://qualify.test/api/connections/callback",
        state_secret="state-secret",
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
    )
    return Harness(service, repository, oauth, publisher, verifier, settings, jti_store)


def start_and_extract_state(harness: Harness) -> str:
    harness.service.start_connect(tenant_id=TENANT, brand_id=BRAND, user_id=USER)
    return harness.oauth.issued_states[-1]


# --------------------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_connect_becomes_active() -> None:
    harness = build_harness()
    state = start_and_extract_state(harness)

    result = await harness.service.complete_connect(code="code-1", state=state)

    assert result.outcome is ConnectOutcome.ACTIVE
    assert result.external_username == "@puntoservis"
    stored = harness.repo.only()
    assert stored.status == "active"
    assert stored.credential_version == 1
    assert stored.last_verified_at is not None


@pytest.mark.asyncio
async def test_connect_records_granted_literals_verbatim() -> None:
    """C-04.3: what was GRANTED, not what was requested, and uninterpreted."""
    partial = ("scope_alpha",)  # user declined the rest
    harness = build_harness(scopes=partial)
    result = await harness.service.complete_connect(
        code="c", state=start_and_extract_state(harness)
    )

    assert result.outcome is ConnectOutcome.ACTIVE
    assert harness.repo.only().grant.granted_scopes == partial


@pytest.mark.asyncio
async def test_verification_runs_through_the_resolver_seam() -> None:
    harness = build_harness()
    await harness.service.complete_connect(code="c", state=start_and_extract_state(harness))
    # The verifier is handed ids only — there is no parameter through which a token could
    # travel, which is the structural half of "verify never sees a raw token".
    assert harness.verifier.calls == [(TENANT, harness.repo.only().connection_id)]


# --------------------------------------------------------------------------------------
# R4 — the login fork
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_linked_page_yields_link_required_and_persists_nothing() -> None:
    harness = build_harness(pages=())

    result = await harness.service.complete_connect(
        code="c", state=start_and_extract_state(harness)
    )

    assert result.outcome is ConnectOutcome.LINK_REQUIRED
    assert result.connection_id is None
    # The invariant R4 preserves: zero connection, zero credential, token dropped.
    assert harness.repo.connections == {}
    assert harness.repo.credentials == []
    assert harness.publisher.events == []


@pytest.mark.asyncio
async def test_page_without_linked_instagram_also_yields_link_required() -> None:
    """Administering a Page is not enough — it must have an IG account linked to it."""
    harness = build_harness(pages=(PAGE_WITHOUT_IG,))
    result = await harness.service.complete_connect(
        code="c", state=start_and_extract_state(harness)
    )
    assert result.outcome is ConnectOutcome.LINK_REQUIRED
    assert harness.repo.connections == {}


@pytest.mark.asyncio
async def test_link_required_still_consumes_the_jti() -> None:
    """R4: the state is spent either way, so recovery means starting a fresh flow."""
    harness = build_harness(pages=())
    state = start_and_extract_state(harness)
    await harness.service.complete_connect(code="c", state=state)
    with pytest.raises(InvalidState):
        await harness.service.complete_connect(code="c", state=state)


# --------------------------------------------------------------------------------------
# state: forgery, replay, expiry
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replayed_state_is_rejected_and_writes_nothing() -> None:
    harness = build_harness()
    state = start_and_extract_state(harness)
    await harness.service.complete_connect(code="c", state=state)
    before = len(harness.repo.credentials)

    with pytest.raises(InvalidState):
        await harness.service.complete_connect(code="c", state=state)

    assert len(harness.repo.credentials) == before  # replay appended no credential


@pytest.mark.asyncio
async def test_forged_state_never_reaches_the_token_exchange() -> None:
    """A bad signature must cost nothing: no code exchange, no platform call, no row."""
    harness = build_harness()
    forged = sign_state(new_payload(TENANT, BRAND, USER), "attacker-secret")

    with pytest.raises(InvalidState):
        await harness.service.complete_connect(code="c", state=forged)

    assert harness.oauth.exchanged_codes == []
    assert harness.repo.connections == {}


# --------------------------------------------------------------------------------------
# Verification failure and idempotency
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_verification_is_born_degraded_not_active() -> None:
    harness = build_harness(verify_ok=False)

    result = await harness.service.complete_connect(
        code="c", state=start_and_extract_state(harness)
    )

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
    await first.service.complete_connect(code="c1", state=start_and_extract_state(first))
    original_id = repo.only().connection_id

    second = build_harness(repo=repo, scopes=("scope_alpha", "scope_beta", "scope_gamma"))
    await second.service.complete_connect(code="c2", state=start_and_extract_state(second))

    assert len(repo.connections) == 1
    assert repo.only().connection_id == original_id  # same row, not a duplicate
    assert repo.only().credential_version == 2  # append-only version bump
    assert repo.only().grant.granted_scopes == ("scope_alpha", "scope_beta", "scope_gamma")
    assert [v for _, v, _ in repo.credentials] == [1, 2]


@pytest.mark.asyncio
async def test_reconnect_of_a_degraded_connection_recovers_it() -> None:
    repo = FakeRepository()
    broken = build_harness(repo=repo, verify_ok=False)
    await broken.service.complete_connect(code="c1", state=start_and_extract_state(broken))
    assert repo.only().status == "degraded"

    fixed = build_harness(repo=repo, verify_ok=True)
    result = await fixed.service.complete_connect(code="c2", state=start_and_extract_state(fixed))

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
    await first.service.complete_connect(code="c1", state=start_and_extract_state(first))
    repo.only().status = "revoked"  # the user disconnected in the CRM (C-06)

    broken = build_harness(repo=repo, verify_ok=False)
    result = await broken.service.complete_connect(code="c2", state=start_and_extract_state(broken))

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

    result = await harness.service.complete_connect(
        code="c", state=start_and_extract_state(harness)
    )

    stored = harness.repo.only()
    assert TOKEN.encode() not in stored.grant.ciphertext
    assert TOKEN not in repr(stored.grant)
    assert TOKEN not in repr(result)
    assert all(TOKEN not in record.getMessage() for record in caplog.records)
    # And the ciphertext genuinely round-trips, so "encrypted" is not "mangled".
    assert DevEncryptor().decrypt(stored.grant.ciphertext, key_id=stored.grant.key_id) == TOKEN


def test_token_grant_repr_redacts() -> None:
    assert TOKEN not in repr(TokenGrant(access_token=TOKEN, token_type="bearer", expires_in=1))


# --------------------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------------------


@pytest.fixture
def client_and_harness() -> tuple[TestClient, Harness]:
    harness = build_harness()
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: harness.service
    return TestClient(app), harness


def test_callback_route_returns_outcome(client_and_harness: tuple[TestClient, Harness]) -> None:
    client, harness = client_and_harness
    state = start_and_extract_state(harness)

    response = client.get("/api/connections/callback", params={"code": "c", "state": state})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "active"
    assert body["connection_id"] is not None
    assert TOKEN not in response.text


def test_callback_route_rejects_bad_state_with_403(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    client, _ = client_and_harness
    response = client.get(
        "/api/connections/callback", params={"code": "c", "state": "not-a-real-state"}
    )
    assert response.status_code == 403
    assert TOKEN not in response.text


def test_callback_route_link_required_has_no_connection_id(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    harness = build_harness(pages=())
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: harness.service
    client = TestClient(app)

    response = client.get(
        "/api/connections/callback",
        params={"code": "c", "state": start_and_extract_state(harness)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "link_required",
        "connection_id": None,
        "external_username": None,
    }


def test_start_route_requires_an_active_tenant(
    client_and_harness: tuple[TestClient, Harness],
) -> None:
    """The tenant comes from the session/dev selector, never from the request body."""
    client, _ = client_and_harness
    response = client.post("/api/connections/start", json={"user_id": str(USER)})
    assert response.status_code == 409


def test_start_request_model_has_no_tenant_field() -> None:
    """Structural: there is no field through which a client could name its own tenant."""
    assert "tenant_id" not in connections_routes.StartConnectRequest.model_fields
