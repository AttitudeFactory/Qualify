"""Page ↔ app webhook subscription (m-24789549), fully offline.

Graph is an `httpx.MockTransport`; the credential resolver and the audit recorder are
fakes. Proves: the right URL/verb/body on the configured Graph version, Graph errors become
recorded codes rather than exceptions, a failure never fails the connect, and revoke
unsubscribes best-effort with the app token (no credential read).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.events import InMemoryEventPublisher
from qualify_api.connections.page_subscription import (
    ERROR_CREDENTIAL,
    ERROR_TRANSPORT,
    ERROR_UNEXPECTED,
    EVENT_PAGE_SUBSCRIBE_FAILED,
    EVENT_PAGE_SUBSCRIBED,
    EVENT_PAGE_UNSUBSCRIBE_FAILED,
    EVENT_PAGE_UNSUBSCRIBED,
    PAGE_SUBSCRIBED_FIELDS,
    GraphPageSubscriptionClient,
    PageSubscriptions,
    SubscriptionResult,
    subscription_state,
)
from qualify_api.connections.resolver import AuthenticatedClient, _InjectedAuthClient
from qualify_api.connections.revoke import RevocationTarget, RevokeService

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("55555555-5555-4555-8555-555555555555")
PAGE_TOKEN = "SUPER_SECRET_PAGE_TOKEN"

SETTINGS = MetaOAuthSettings(
    app_id="app-1",
    app_secret="app-secret",
    redirect_uri="https://qualify.test/api/connections/callback",
    state_secret="state-secret",
    graph_base_url="https://graph.example",
    api_version="v99.0",
)


class FakeResolver:
    def __init__(self, transport: httpx.AsyncBaseTransport, *, fail: bool = False) -> None:
        self._transport = transport
        self._fail = fail
        self.asked: list[UUID] = []

    async def client_for(self, connection_id: UUID, *, scheme: str) -> AuthenticatedClient:
        self.asked.append(connection_id)
        if self._fail:
            raise LookupError("no credential")
        return _InjectedAuthClient(PAGE_TOKEN, scheme=scheme, transport=self._transport)


def _recording_transport(status: int, body: Any, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _client(
    status: int = 200, body: Any = None, *, fail_credential: bool = False
) -> tuple[GraphPageSubscriptionClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    transport = _recording_transport(status, {"success": True} if body is None else body, seen)
    client = GraphPageSubscriptionClient(
        SETTINGS,
        DevEncryptor(),
        resolver=FakeResolver(transport, fail=fail_credential),
        transport=transport,
    )
    return client, seen


# --- Graph client ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_posts_messages_field_with_the_page_token() -> None:
    client, seen = _client()

    result = await client.subscribe(tenant_id=TENANT, connection_id=CONNECTION, page_id="page-1")

    assert result == SubscriptionResult(ok=True)
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://graph.example/v99.0/page-1/subscribed_apps"
    assert parse_qs(request.content.decode()) == {"subscribed_fields": ["messages"]}
    assert request.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
    assert PAGE_TOKEN not in str(request.url)


def test_subscribed_fields_are_page_fields_only() -> None:
    """Instagram fields cannot go through this edge (Meta docs); `messages` is the one
    verified live to open the DM window."""
    assert PAGE_SUBSCRIBED_FIELDS == ("messages",)


@pytest.mark.asyncio
async def test_graph_error_becomes_a_code_not_an_exception() -> None:
    body = {"error": {"code": 200, "error_subcode": 1234, "message": f"bad {PAGE_TOKEN}"}}
    client, _ = _client(403, body)

    result = await client.subscribe(tenant_id=TENANT, connection_id=CONNECTION, page_id="p")

    assert result == SubscriptionResult(ok=False, error_code="200/1234")
    assert PAGE_TOKEN not in (result.error_code or "")


@pytest.mark.asyncio
async def test_non_graph_error_body_records_the_http_status() -> None:
    client, _ = _client(500, {"oops": True})
    result = await client.subscribe(tenant_id=TENANT, connection_id=CONNECTION, page_id="p")
    assert result.error_code == "http_500"


@pytest.mark.asyncio
async def test_200_without_success_true_is_a_failure() -> None:
    client, _ = _client(200, {"success": False})
    result = await client.subscribe(tenant_id=TENANT, connection_id=CONNECTION, page_id="p")
    assert result == SubscriptionResult(ok=False, error_code=ERROR_UNEXPECTED)


@pytest.mark.asyncio
async def test_missing_credential_is_a_failure_and_makes_no_call() -> None:
    client, seen = _client(fail_credential=True)
    result = await client.subscribe(tenant_id=TENANT, connection_id=CONNECTION, page_id="p")
    assert result == SubscriptionResult(ok=False, error_code=ERROR_CREDENTIAL)
    assert seen == []


@pytest.mark.asyncio
async def test_transport_error_is_a_failure() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    transport = httpx.MockTransport(boom)
    client = GraphPageSubscriptionClient(
        SETTINGS, DevEncryptor(), resolver=FakeResolver(transport), transport=transport
    )
    result = await client.subscribe(tenant_id=TENANT, connection_id=CONNECTION, page_id="p")
    assert result == SubscriptionResult(ok=False, error_code=ERROR_TRANSPORT)
    assert client.unsubscribe(page_id="p") == SubscriptionResult(
        ok=False, error_code=ERROR_TRANSPORT
    )


def test_unsubscribe_deletes_with_the_app_token_in_a_header() -> None:
    client, seen = _client(200, {"success": True, "messaging_success": True})

    result = client.unsubscribe(page_id="page-1")

    assert result.ok
    (request,) = seen
    assert request.method == "DELETE"
    assert str(request.url) == "https://graph.example/v99.0/page-1/subscribed_apps"
    assert request.headers["Authorization"] == "Bearer app-1|app-secret"
    assert "app-secret" not in str(request.url)


# --- PageSubscriptions (orchestration + audit) --------------------------------------


@dataclass
class FakeRecorder:
    rows: list[dict[str, Any]] = field(default_factory=list)
    shared_pages: set[str] = field(default_factory=set)
    fail: bool = False

    def record(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("db down")
        self.rows.append(kwargs)

    def page_shared_by_live_connection(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> bool:
        return page_id in self.shared_pages


class FakeClient:
    def __init__(self, result: SubscriptionResult | None = None, *, raises: bool = False):
        self.result = result or SubscriptionResult(ok=True)
        self.raises = raises
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    async def subscribe(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> SubscriptionResult:
        self.subscribed.append(page_id)
        if self.raises:
            raise RuntimeError("bug")
        return self.result

    def unsubscribe(self, *, page_id: str) -> SubscriptionResult:
        self.unsubscribed.append(page_id)
        if self.raises:
            raise RuntimeError("bug")
        return self.result


@pytest.mark.asyncio
async def test_successful_subscription_is_recorded_with_provenance() -> None:
    recorder = FakeRecorder()
    subs = PageSubscriptions(client=FakeClient(), recorder=recorder)

    await subs.subscribe_after_connect(
        tenant_id=TENANT, connection_id=CONNECTION, page_id="page-1", credential_version=4
    )

    assert recorder.rows == [
        {
            "tenant_id": TENANT,
            "connection_id": CONNECTION,
            "credential_version": 4,
            "event_type": EVENT_PAGE_SUBSCRIBED,
            "actor": "system",
            "error_code": None,
        }
    ]


@pytest.mark.asyncio
async def test_failed_or_crashing_subscription_is_recorded_never_raised() -> None:
    recorder = FakeRecorder()
    failing = PageSubscriptions(
        client=FakeClient(SubscriptionResult(ok=False, error_code="10/2534022")),
        recorder=recorder,
    )
    crashing = PageSubscriptions(client=FakeClient(raises=True), recorder=recorder)

    await failing.subscribe_after_connect(
        tenant_id=TENANT, connection_id=CONNECTION, page_id="p", credential_version=1
    )
    await crashing.subscribe_after_connect(
        tenant_id=TENANT, connection_id=CONNECTION, page_id="p", credential_version=1
    )

    assert [(r["event_type"], r["error_code"]) for r in recorder.rows] == [
        (EVENT_PAGE_SUBSCRIBE_FAILED, "10/2534022"),
        (EVENT_PAGE_SUBSCRIBE_FAILED, ERROR_UNEXPECTED),
    ]


@pytest.mark.asyncio
async def test_recorder_failure_does_not_raise() -> None:
    subs = PageSubscriptions(client=FakeClient(), recorder=FakeRecorder(fail=True))
    result = await subs.subscribe_after_connect(
        tenant_id=TENANT, connection_id=CONNECTION, page_id="p", credential_version=1
    )
    assert result.ok


def test_unsubscribe_skips_without_page_or_when_page_is_shared() -> None:
    client = FakeClient()
    recorder = FakeRecorder(shared_pages={"shared"})
    subs = PageSubscriptions(client=client, recorder=recorder)

    for page_id in (None, "shared"):
        assert (
            subs.unsubscribe_after_revoke(
                tenant_id=TENANT,
                connection_id=CONNECTION,
                page_id=page_id,
                credential_version=1,
                actor="user",
            )
            is None
        )
    assert client.unsubscribed == []
    assert recorder.rows == []


def test_subscription_state_mapping() -> None:
    assert subscription_state(None) is None
    assert subscription_state("granted") is None
    assert subscription_state(EVENT_PAGE_SUBSCRIBED) == "subscribed"
    assert subscription_state(EVENT_PAGE_SUBSCRIBE_FAILED) == "failed"
    assert subscription_state(EVENT_PAGE_UNSUBSCRIBED) == "unsubscribed"
    assert subscription_state(EVENT_PAGE_UNSUBSCRIBE_FAILED) == "failed"


# --- RevokeService wiring -----------------------------------------------------------


@dataclass
class FakeRevocationRepository:
    target: RevocationTarget
    writes: int = 0

    def load(self, *, tenant_id: UUID, connection_id: UUID) -> RevocationTarget | None:
        return self.target

    def persist_revocation(self, **kwargs: Any) -> None:
        self.writes += 1
        self.target = RevocationTarget(
            status=kwargs["status"],
            credential_version=kwargs["credential_version"],
            linked_page_id=self.target.linked_page_id,
        )


@pytest.mark.parametrize("raises", [False, True])
def test_revoke_unsubscribes_once_and_survives_meta_failure(raises: bool) -> None:
    repo = FakeRevocationRepository(
        RevocationTarget(status="active", credential_version=3, linked_page_id="page-1")
    )
    client = FakeClient(raises=raises)
    recorder = FakeRecorder()
    service = RevokeService(
        repository=repo,
        publisher=InMemoryEventPublisher(),
        page_subscriptions=PageSubscriptions(client=client, recorder=recorder),
    )
    now = datetime.now(UTC)

    first = service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=now)
    second = service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=now)

    assert first.changed and not second.changed
    assert repo.writes == 1
    assert client.unsubscribed == ["page-1"]  # the idempotent second revoke calls nothing
    assert [r["event_type"] for r in recorder.rows] == [
        EVENT_PAGE_UNSUBSCRIBE_FAILED if raises else EVENT_PAGE_UNSUBSCRIBED
    ]
    assert recorder.rows[0]["actor"] == "user"
    assert recorder.rows[0]["credential_version"] == 3
