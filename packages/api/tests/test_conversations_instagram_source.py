"""The Instagram Direct channel (QUA-226, E3), offline: a fake authenticated client
answers canned Graph responses, so what is pinned here is the adapter's reading of the
corpus — the shapes it parses, the direction it derives, the verdicts it returns and the
errors it classifies — never Meta itself (nothing here has been observed live).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    AccessStatus,
    RemoteConversation,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import (
    SHAPE_VERSION_IG_DM,
    InstagramDirectError,
    InstagramDirectSender,
    InstagramDirectSource,
    has_messages_scope,
    parse_conversations_page,
    parse_graph_time,
    parse_messages_page,
    parse_send_response,
)

GRAPH = "https://graph.facebook.com/v21.0"
TENANT = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT,
    connection_id=uuid4(),
    external_account_id="17841400000001",
    linked_page_id="p1",
)


class FakeGraph:
    """`AuthenticatedClient` double: `routes` maps `(method, path-suffix)` → a response
    builder; every call is recorded (url + params/json) and no token is involved."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Any] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _respond(self, method: str, url: str, kwargs: dict[str, Any]) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        for (m, suffix), answer in self.routes.items():
            if m == method and url.endswith(suffix):
                if isinstance(answer, Exception):
                    raise answer
                status, body = answer
                return httpx.Response(status, json=body, request=httpx.Request(method, url))
        return httpx.Response(
            404, json={"error": {"code": 803}}, request=httpx.Request(method, url)
        )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._respond("GET", url, kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._respond("POST", url, kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._respond("DELETE", url, kwargs)


def _factory(graph: FakeGraph):
    built: list[UUID] = []

    async def factory(tenant_id: UUID, connection_id: UUID):
        built.append(connection_id)
        return graph

    factory.built = built  # type: ignore[attr-defined]
    return factory


CONVERSATIONS_BODY = {
    "data": [
        {
            "id": "t_1",
            "updated_time": "2026-10-16T12:00:00+0000",
            "participants": {
                "data": [
                    {"id": "17841400000001", "username": "qualifymkt.co"},
                    {"id": "igsid-alice", "username": "alice"},
                ]
            },
        },
        {"id": "t_self_only", "participants": {"data": [{"id": "17841400000001"}]}},
        {"id": "t_no_participants", "updated_time": 1760616000},
    ],
    "paging": {"cursors": {"after": "AFTER"}, "next": "https://…"},
}

MESSAGES_BODY = {
    "data": [
        {
            "id": "m_2",
            "created_time": "2026-10-16T12:00:00+0000",
            "from": {"id": "17841400000001", "username": "qualifymkt.co"},
            "to": {"data": [{"id": "igsid-alice", "username": "alice"}]},
            "message": "¡Hola! Sí, queda una.",
        },
        {
            "id": "m_1",
            "created_time": "2026-10-16T11:58:00+0000",
            "from": {"id": "igsid-alice", "username": "alice"},
            "to": {"data": [{"id": "17841400000001"}]},
            "message": "¿Tienen talla M?",
        },
        {
            "id": "m_0",
            "created_time": 1760615000,
            "from": {"id": "igsid-alice", "username": "alice"},
            "message": "",
            "attachments": {"data": [{"image_data": {"url": "https://…"}}]},
        },
    ]
}


# --- parsing --------------------------------------------------------------------------


def test_graph_time_accepts_colonless_offsets_and_epochs() -> None:
    assert parse_graph_time("2022-07-12T19:11:07+0000") == datetime(
        2022, 7, 12, 19, 11, 7, tzinfo=UTC
    )
    assert parse_graph_time("2022-07-12T19:11:07Z") == datetime(2022, 7, 12, 19, 11, 7, tzinfo=UTC)
    assert parse_graph_time(1569262485349) == datetime.fromtimestamp(1569262485.349, UTC)
    assert parse_graph_time(1569262485) == datetime.fromtimestamp(1569262485, UTC)
    assert parse_graph_time("not a time") is None
    assert parse_graph_time(True) is None


def test_conversations_page_keys_threads_on_the_counterpart() -> None:
    page = parse_conversations_page(CONVERSATIONS_BODY, own_account_id="17841400000001")
    assert [c.counterpart_external_id for c in page.items] == ["igsid-alice"]
    alice = page.items[0]
    assert alice.external_conversation_id == "t_1"
    assert alice.counterpart_username == "alice"
    assert alice.updated_at == datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    assert page.next_cursor == "AFTER"


def test_conversations_page_without_next_has_no_cursor() -> None:
    body = {"data": [], "paging": {"cursors": {"after": "X"}}}
    assert parse_conversations_page(body, own_account_id="1").next_cursor is None
    with pytest.raises(InstagramDirectError):
        parse_conversations_page({"nope": []}, own_account_id="1")


def test_messages_page_derives_direction_from_the_sender() -> None:
    page = parse_messages_page(MESSAGES_BODY, own_account_id="17841400000001")
    by_id = {m.external_message_id: m for m in page.items}
    assert by_id["m_2"].direction == "outbound"
    assert by_id["m_1"].direction == "inbound"
    assert by_id["m_1"].author_username == "alice"
    assert by_id["m_1"].text == "¿Tienen talla M?"
    assert by_id["m_0"].text is None and by_id["m_0"].media_type == "image"
    assert all(m.shape_version == SHAPE_VERSION_IG_DM for m in page.items)


def test_send_response_needs_a_message_id() -> None:
    assert (
        parse_send_response({"recipient_id": "x", "message_id": "m_9"}).external_message_id == "m_9"
    )
    with pytest.raises(InstagramDirectError):
        parse_send_response({"recipient_id": "x"})


def test_messages_scope_spellings() -> None:
    assert has_messages_scope(("instagram_manage_messages",))
    assert has_messages_scope(["instagram_business_manage_messages"])
    assert not has_messages_scope(("instagram_manage_comments",))
    assert not has_messages_scope(None)
    assert not has_messages_scope(())


# --- access verdict -------------------------------------------------------------------


async def test_access_is_permission_missing_without_the_scope_and_without_calling_meta() -> None:
    graph = FakeGraph()
    source = InstagramDirectSource(
        client_factory=_factory(graph),
        graph_url=GRAPH,
        scope_reader=lambda t, c: ("instagram_manage_comments",),
    )
    verdict = await source.check_access(CONNECTION)
    assert verdict.status is AccessStatus.PERMISSION_MISSING
    assert verdict.detail == "scope_not_granted"
    assert graph.calls == []


@pytest.mark.parametrize(
    ("status", "body", "expected", "detail"),
    [
        (200, {"data": []}, AccessStatus.OK, None),
        (401, {"error": {"code": 190}}, AccessStatus.AUTH_EXPIRED, "http_401_code_190"),
        (400, {"error": {"code": 190}}, AccessStatus.AUTH_EXPIRED, "http_400_code_190"),
        (403, {"error": {"code": 10}}, AccessStatus.PERMISSION_MISSING, "http_403_code_10"),
        (403, {"error": {"code": 230}}, AccessStatus.PERMISSION_MISSING, "http_403_code_230"),
        (500, {"error": {"code": 1}}, AccessStatus.ERROR, "http_500_code_1"),
    ],
)
async def test_access_probe_maps_meta_answers_to_verdicts(
    status: int, body: dict[str, Any], expected: AccessStatus, detail: str | None
) -> None:
    graph = FakeGraph()
    graph.routes[("GET", "/p1/conversations")] = (status, body)
    source = InstagramDirectSource(
        client_factory=_factory(graph),
        graph_url=GRAPH,
        scope_reader=lambda t, c: ("instagram_manage_messages",),
    )
    verdict = await source.check_access(CONNECTION)
    assert verdict.status is expected
    assert verdict.detail == detail
    method, url, kwargs = graph.calls[0]
    assert url == f"{GRAPH}/p1/conversations"
    assert kwargs["params"] == {"platform": "instagram", "limit": 1}


async def test_access_probe_transport_failure_is_an_error_verdict() -> None:
    graph = FakeGraph()
    graph.routes[("GET", "/p1/conversations")] = httpx.ConnectError("boom")
    source = InstagramDirectSource(client_factory=_factory(graph), graph_url=GRAPH)
    verdict = await source.check_access(CONNECTION)
    assert verdict.status is AccessStatus.ERROR
    assert verdict.detail == "transport_ConnectError"


# --- listing --------------------------------------------------------------------------


async def test_listing_uses_the_page_node_and_passes_the_cursor_through() -> None:
    graph = FakeGraph()
    graph.routes[("GET", "/p1/conversations")] = (200, CONVERSATIONS_BODY)
    graph.routes[("GET", "/t_1/messages")] = (200, MESSAGES_BODY)
    factory = _factory(graph)
    source = InstagramDirectSource(client_factory=factory, graph_url=GRAPH)

    page = await source.list_conversations(CONNECTION, cursor="C1")
    assert page.items[0].counterpart_external_id == "igsid-alice"
    _m, _u, kwargs = graph.calls[-1]
    assert kwargs["params"]["after"] == "C1"
    assert kwargs["params"]["platform"] == "instagram"

    messages = await source.list_messages(CONNECTION, page.items[0])
    assert {m.external_message_id for m in messages.items} == {"m_0", "m_1", "m_2"}
    assert messages.next_cursor is None  # the ~20-message horizon: one page, by design
    assert graph.calls[-1][1] == f"{GRAPH}/t_1/messages"
    assert factory.built == [CONNECTION.connection_id]  # one client per connection, cached


async def test_listing_a_conversation_without_id_reads_nothing() -> None:
    graph = FakeGraph()
    source = InstagramDirectSource(client_factory=_factory(graph), graph_url=GRAPH)
    page = await source.list_messages(CONNECTION, RemoteConversation(counterpart_external_id="x"))
    assert page.items == () and graph.calls == []


async def test_listing_failure_carries_codes_only() -> None:
    graph = FakeGraph()
    graph.routes[("GET", "/p1/conversations")] = (
        400,
        {"error": {"code": 100, "error_subcode": 33, "message": "secret echo"}},
    )
    source = InstagramDirectSource(client_factory=_factory(graph), graph_url=GRAPH)
    with pytest.raises(InstagramDirectError) as info:
        await source.list_conversations(CONNECTION)
    assert info.value.http_status == 400
    assert info.value.platform_code == 100
    assert info.value.platform_subcode == 33
    assert "secret echo" not in str(info.value)
    assert not info.value.is_retryable


# --- sending --------------------------------------------------------------------------


def test_sender_builds_the_messenger_platform_body() -> None:
    sender = InstagramDirectSender(client_factory=_factory(FakeGraph()), graph_url=GRAPH)
    assert sender.channel == CHANNEL_DM
    assert sender.build_payload(recipient_external_id="igsid", text="  hola ") == {
        "recipient": {"id": "igsid"},
        "message": {"text": "hola"},
    }
    with pytest.raises(ValueError):
        sender.build_payload(recipient_external_id="", text="hola")
    with pytest.raises(ValueError):
        sender.build_payload(recipient_external_id="igsid", text="   ")
    with pytest.raises(ValueError):
        sender.build_payload(recipient_external_id="igsid", text="ñ" * 501)  # 1002 bytes


async def test_sender_posts_to_the_page_and_returns_the_message_id() -> None:
    graph = FakeGraph()
    graph.routes[("POST", "/p1/messages")] = (200, {"recipient_id": "igsid", "message_id": "m_9"})
    sender = InstagramDirectSender(client_factory=_factory(graph), graph_url=GRAPH)
    payload = sender.build_payload(recipient_external_id="igsid", text="hola")
    result = await sender.send(CONNECTION, payload)
    assert result.external_message_id == "m_9"
    method, url, kwargs = graph.calls[0]
    assert (method, url) == ("POST", f"{GRAPH}/p1/messages")
    assert kwargs["json"] == payload


@pytest.mark.parametrize(
    ("status", "body", "auth", "retryable"),
    [
        (401, {"error": {"code": 190}}, True, False),
        (429, {"error": {"code": 4}}, False, True),
        (503, {"error": {"code": 2}}, False, True),
        (400, {"error": {"code": 10, "error_subcode": 2534022}}, False, False),
    ],
)
async def test_sender_classifies_meta_refusals(
    status: int, body: dict[str, Any], auth: bool, retryable: bool
) -> None:
    graph = FakeGraph()
    graph.routes[("POST", "/p1/messages")] = (status, body)
    sender = InstagramDirectSender(client_factory=_factory(graph), graph_url=GRAPH)
    with pytest.raises(InstagramDirectError) as info:
        await sender.send(CONNECTION, {"recipient": {"id": "igsid"}, "message": {"text": "x"}})
    assert info.value.is_auth_error is auth
    assert info.value.is_retryable is retryable


def test_an_unsupported_node_is_other_content_not_a_bare_message() -> None:
    """Verified live 2026-10-16: audio (the person's voice notes and our own echoes) comes
    back as `is_unsupported: true` with an empty `message` and no `attachments`."""
    page = parse_messages_page(
        {
            "data": [
                {
                    "id": "m.voice",
                    "created_time": "2026-10-17T00:39:13+0000",
                    "from": {"id": "17841400000001"},
                    "message": "",
                    "is_unsupported": True,
                }
            ]
        },
        own_account_id="17841400000001",
    )
    (voice,) = page.items
    assert voice.direction == "outbound" and voice.text is None
    assert voice.media_type == "other" and voice.media_url is None


async def test_sender_transport_failure_before_sending_is_retryable() -> None:
    graph = FakeGraph()
    graph.routes[("POST", "/p1/messages")] = httpx.ConnectError("down")
    sender = InstagramDirectSender(client_factory=_factory(graph), graph_url=GRAPH)
    with pytest.raises(InstagramDirectError) as info:
        await sender.send(CONNECTION, {"recipient": {"id": "igsid"}, "message": {"text": "x"}})
    assert info.value.is_transport and info.value.is_retryable and not info.value.is_auth_error
    assert not info.value.is_ambiguous


@pytest.mark.parametrize(
    "exc",
    [httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("dropped"), httpx.WriteTimeout("w")],
)
async def test_sender_timeout_after_the_request_went_out_is_ambiguous_not_retryable(
    exc: Exception,
) -> None:
    """2026-10-16: a photo send read-timed out, was retried and reached the person twice.
    Meta may have processed the request, so the outcome is unknown — never a blind retry."""
    graph = FakeGraph()
    graph.routes[("POST", "/p1/messages")] = exc
    sender = InstagramDirectSender(client_factory=_factory(graph), graph_url=GRAPH)
    with pytest.raises(InstagramDirectError) as info:
        await sender.send(CONNECTION, {"recipient": {"id": "igsid"}, "message": {"text": "x"}})
    assert info.value.is_transport and info.value.is_ambiguous
    assert not info.value.is_retryable and not info.value.is_auth_error
