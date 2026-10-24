"""`InstagramIceBreakersClient` over a mocked transport (m-24789472, PR 3): the real
credential door (`_InjectedAuthClient`) wrapped around `httpx.MockTransport`, so what is
asserted is exactly what would leave the process. Everything here is the CORPUS's contract
(`features/ice-breakers.md`, `page/messenger_profile.md`) — `[V]`-pending until R6.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest

from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.conversations.contracts import SourceConnection
from qualify_api.conversations.ice_breakers_client import (
    CATEGORY_AMBIGUOUS,
    CATEGORY_AUTH_EXPIRED,
    CATEGORY_META_UNAVAILABLE,
    CATEGORY_PERMISSION_MISSING,
    CATEGORY_RATE_LIMITED,
    CATEGORY_REJECTED,
    CATEGORY_UNEXPECTED_RESPONSE,
    SHAPE_VERSION_IG_ICE_BREAKERS,
    IceBreakerItem,
    IceBreakersApiError,
    InstagramIceBreakersClient,
    RemoteIceBreakers,
    build_set_body,
    parse_ice_breakers,
)
from qualify_api.conversations.instagram_source import READ_TIMEOUT_S, SEND_TIMEOUT_S

TOKEN = "PAGE_TOKEN_SECRET_123"
GRAPH = "https://graph.facebook.com/v25.0"
TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = SourceConnection(
    tenant_id=TENANT,
    connection_id=UUID("22222222-2222-4222-8222-222222222222"),
    external_account_id="17841400000001",
    linked_page_id="page-77",
)
ITEMS = (
    IceBreakerItem("¿Qué producto te interesa?", "QF_PRODUCTO"),
    IceBreakerItem("¿Quieres consultar un precio?", "QF_PRECIO"),
)


class Recorder:
    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


def _client(
    respond: Callable[[httpx.Request], httpx.Response],
) -> tuple[InstagramIceBreakersClient, Recorder, list[dict[str, Any]]]:
    recorder = Recorder(respond)
    timeouts: list[dict[str, Any]] = []

    class TimeoutSpy(_InjectedAuthClient):
        async def get(self, url: str, **kwargs: Any) -> httpx.Response:
            timeouts.append({"GET": kwargs.get("timeout")})
            return await super().get(url, **kwargs)

        async def post(self, url: str, **kwargs: Any) -> httpx.Response:
            timeouts.append({"POST": kwargs.get("timeout")})
            return await super().post(url, **kwargs)

        async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
            timeouts.append({"DELETE": kwargs.get("timeout")})
            return await super().delete(url, **kwargs)

    async def factory(tenant_id: UUID, connection_id: UUID) -> _InjectedAuthClient:
        assert (tenant_id, connection_id) == (CONNECTION.tenant_id, CONNECTION.connection_id)
        return TimeoutSpy(TOKEN, scheme="Bearer", transport=httpx.MockTransport(recorder))

    return InstagramIceBreakersClient(client_factory=factory, graph_url=GRAPH), recorder, timeouts


def _ok(body: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json=body)


def _error(status: int, code: int | None = None, **extra: Any):
    def respond(request: httpx.Request) -> httpx.Response:
        error: dict[str, Any] = {"message": "¿Qué producto te interesa? is invalid", **extra}
        if code is not None:
            error["code"] = code
        return httpx.Response(status, json={"error": error})

    return respond


# --- the wire ---------------------------------------------------------------------------


async def test_publish_posts_the_corpus_body_with_the_page_token_as_a_header() -> None:
    client, recorder, timeouts = _client(_ok({"result": "success"}))
    await client.publish(CONNECTION, ITEMS)
    (request,) = recorder.requests
    assert request.method == "POST"
    assert request.url.path == "/v25.0/page-77/messenger_profile"
    assert dict(request.url.params) == {"platform": "instagram"}
    assert json.loads(request.content) == {
        "platform": "instagram",
        "ice_breakers": [
            {
                "call_to_actions": [
                    {"question": "¿Qué producto te interesa?", "payload": "QF_PRODUCTO"},
                    {"question": "¿Quieres consultar un precio?", "payload": "QF_PRECIO"},
                ],
                "locale": "default",
            }
        ],
    }
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)
    assert timeouts == [{"POST": SEND_TIMEOUT_S}]


def test_the_set_body_always_has_the_required_default_locale_and_at_most_four() -> None:
    body = build_set_body(ITEMS)
    assert [block["locale"] for block in body["ice_breakers"]] == ["default"]
    with pytest.raises(ValueError):
        build_set_body(())
    with pytest.raises(ValueError):
        build_set_body([IceBreakerItem(f"q{i}", f"QF_{i}") for i in range(5)])


async def test_the_instagram_login_success_shape_is_accepted_too() -> None:
    client, _, _ = _client(_ok({"success": True}))
    await client.publish(CONNECTION, ITEMS)


async def test_a_200_without_success_is_an_unexpected_response() -> None:
    client, _, _ = _client(_ok({"result": "nope"}))
    with pytest.raises(IceBreakersApiError) as caught:
        await client.publish(CONNECTION, ITEMS)
    assert caught.value.category == CATEGORY_UNEXPECTED_RESPONSE
    assert caught.value.is_retryable is False


async def test_fetch_gets_the_ice_breakers_field_and_parses_the_feature_doc_shape() -> None:
    body = {
        "data": [
            {
                "call_to_actions": [
                    {"question": "¿Qué producto te interesa?", "payload": "QF_PRODUCTO"},
                    {"question": "¿Quieres consultar un precio?", "payload": "QF_PRECIO"},
                ],
                "locale": "default",
            },
            {
                "call_to_actions": [{"question": "Price?", "payload": "QF_PRECIO"}],
                "locale": "en_GB",
            },
        ]
    }
    client, recorder, timeouts = _client(_ok(body))
    remote = await client.fetch(CONNECTION)
    (request,) = recorder.requests
    assert request.method == "GET"
    assert request.url.path == "/v25.0/page-77/messenger_profile"
    assert dict(request.url.params) == {"fields": "ice_breakers", "platform": "instagram"}
    assert timeouts == [{"GET": READ_TIMEOUT_S}]
    assert remote.default_items == ITEMS
    assert [b.locale for b in remote.locales] == ["default", "en_GB"]
    assert remote.shape_version == SHAPE_VERSION_IG_ICE_BREAKERS


def test_parse_accepts_the_property_keyed_shape_of_the_page_reference() -> None:
    body = {
        "data": [
            {
                "ice_breakers": [
                    {
                        "call_to_actions": [
                            {"question": "¿Qué producto te interesa?", "payload": "QF_PRODUCTO"}
                        ],
                        "locale": "default",
                    }
                ]
            }
        ]
    }
    remote = parse_ice_breakers(body)
    assert remote.default_items == (ITEMS[0],)


def test_parse_reads_nothing_configured_and_a_block_without_locale_as_default() -> None:
    assert parse_ice_breakers({"data": []}).is_empty
    remote = parse_ice_breakers(
        {"data": [{"call_to_actions": [{"question": "Hola", "payload": "QF_X"}, {"x": 1}, "bad"]}]}
    )
    assert remote.default_items == (IceBreakerItem("Hola", "QF_X"),)
    with pytest.raises(ValueError):
        parse_ice_breakers({"error": {}})


def test_snapshot_round_trip() -> None:
    remote = parse_ice_breakers({"data": [{"call_to_actions": [ITEMS[0].as_wire()]}]})
    again = RemoteIceBreakers.from_snapshot(remote.to_snapshot())
    assert again == remote
    assert remote.to_snapshot()["shape_version"] == SHAPE_VERSION_IG_ICE_BREAKERS


async def test_fetch_without_a_data_list_is_unexpected() -> None:
    client, _, _ = _client(_ok({"something": "else"}))
    with pytest.raises(IceBreakersApiError) as caught:
        await client.fetch(CONNECTION)
    assert caught.value.category == CATEGORY_UNEXPECTED_RESPONSE


async def test_remove_deletes_only_the_ice_breakers_field() -> None:
    client, recorder, timeouts = _client(_ok({"result": "success"}))
    await client.remove(CONNECTION)
    (request,) = recorder.requests
    assert request.method == "DELETE"
    assert request.url.path == "/v25.0/page-77/messenger_profile"
    assert dict(request.url.params) == {"platform": "instagram"}
    assert json.loads(request.content) == {"fields": ["ice_breakers"]}
    assert timeouts == [{"DELETE": SEND_TIMEOUT_S}]


async def test_an_account_without_a_linked_page_falls_back_to_me() -> None:
    client, recorder, _ = _client(_ok({"result": "success"}))
    bare = SourceConnection(
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
        external_account_id="x",
        linked_page_id=None,
    )
    await client.remove(bare)
    assert recorder.requests[0].url.path == "/v25.0/me/messenger_profile"


# --- typed errors -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("respond", "category", "retryable", "detail"),
    [
        (_error(401, 190), CATEGORY_AUTH_EXPIRED, False, "http_401_code_190"),
        (_error(400, 190), CATEGORY_AUTH_EXPIRED, False, "http_400_code_190"),
        (_error(403, 10), CATEGORY_PERMISSION_MISSING, False, "http_403_code_10"),
        (_error(400, 230), CATEGORY_PERMISSION_MISSING, False, "http_400_code_230"),
        (_error(400, 613), CATEGORY_RATE_LIMITED, True, "http_400_code_613"),
        (_error(429), CATEGORY_RATE_LIMITED, True, "http_429"),
        (_error(503), CATEGORY_META_UNAVAILABLE, True, "http_503"),
        (
            _error(400, 100, error_subcode=2018001),
            CATEGORY_REJECTED,
            False,
            "http_400_code_100_sub_2018001",
        ),
    ],
)
async def test_meta_errors_are_typed(respond, category: str, retryable: bool, detail: str) -> None:
    client, _, _ = _client(respond)
    with pytest.raises(IceBreakersApiError) as caught:
        await client.publish(CONNECTION, ITEMS)
    assert caught.value.category == category
    assert caught.value.is_retryable is retryable
    assert caught.value.detail == detail
    assert "¿" not in str(caught.value)  # the body (which echoes the questions) is never kept


def _raises(exc: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        raise exc

    return respond


async def test_a_failure_before_the_request_left_is_retryable() -> None:
    client, _, _ = _client(_raises(httpx.ConnectError("refused")))
    with pytest.raises(IceBreakersApiError) as caught:
        await client.publish(CONNECTION, ITEMS)
    assert caught.value.category == CATEGORY_META_UNAVAILABLE
    assert caught.value.is_retryable is True
    assert caught.value.is_ambiguous is False
    assert caught.value.detail == "transport_connecterror"


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("dropped"), httpx.ReadError("x")]
)
async def test_a_failure_after_the_request_may_have_landed_is_ambiguous(exc: Exception) -> None:
    client, _, _ = _client(_raises(exc))
    with pytest.raises(IceBreakersApiError) as caught:
        await client.publish(CONNECTION, ITEMS)
    assert caught.value.category == CATEGORY_AMBIGUOUS
    assert caught.value.is_retryable is False


async def test_nothing_secret_or_textual_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client, _, _ = _client(_error(400, 100))
    with pytest.raises(IceBreakersApiError):
        await client.publish(CONNECTION, ITEMS)
    client, _, _ = _client(_raises(httpx.ReadTimeout("slow")))
    with pytest.raises(IceBreakersApiError):
        await client.fetch(CONNECTION)
    logged = caplog.text
    assert "category=rejected" in logged and "category=ambiguous" in logged
    assert TOKEN not in logged
    for item in ITEMS:
        assert item.question not in logged
        assert item.payload not in logged
    assert "is invalid" not in logged
