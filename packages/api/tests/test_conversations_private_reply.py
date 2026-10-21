"""The private reply's channel contract (m-24789646, PR 2), offline: the 7-day limit, the
wire body Instagram gets (`features/private-replies.md`: the COMMENT as recipient, on the
same `/{page-id}/messages` as every DM) and Meta's `recipient_id` kept from the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from qualify_api.conversations.contracts import SourceConnection
from qualify_api.conversations.instagram_source import (
    InstagramDirectError,
    InstagramDirectSender,
    parse_send_response,
)
from qualify_api.conversations.window import (
    PRIVATE_REPLY_WINDOW,
    private_reply_deadline,
    private_reply_window,
)

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def test_the_private_reply_window_is_seven_days_closed_at_the_instant() -> None:
    assert PRIVATE_REPLY_WINDOW == timedelta(days=7)
    assert private_reply_deadline(T0) == T0 + timedelta(days=7)
    just_before = private_reply_window(T0, T0 + timedelta(days=7) - timedelta(seconds=1))
    assert just_before.is_open and just_before.closes_at == T0 + timedelta(days=7)
    assert not private_reply_window(T0, T0 + timedelta(days=7)).is_open
    assert private_reply_window(T0, T0).is_open


def test_a_comment_without_a_creation_time_is_closed() -> None:
    state = private_reply_window(None, T0)
    assert not state.is_open and state.closes_at is None


def _sender(requests: list[httpx.Request]) -> InstagramDirectSender:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"recipient_id": "igsid-ana", "message_id": "aWdfZ"})

    async def factory(_tenant, _connection):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return InstagramDirectSender(client_factory=factory, graph_url="https://graph.test/v21.0/")


def test_the_body_is_addressed_to_the_comment() -> None:
    sender = _sender([])
    assert sender.build_private_reply_payload(comment_id="1789", text="  Hola  ") == {
        "recipient": {"comment_id": "1789"},
        "message": {"text": "Hola"},
    }


@pytest.mark.parametrize(
    ("comment_id", "text"), [("", "hola"), ("1789", "   "), ("1789", "é" * 501)]
)
def test_an_invalid_private_reply_is_refused(comment_id: str, text: str) -> None:
    with pytest.raises(ValueError):
        _sender([]).build_private_reply_payload(comment_id=comment_id, text=text)


async def test_it_goes_to_the_pages_messages_edge_and_keeps_the_recipient() -> None:
    requests: list[httpx.Request] = []
    sender = _sender(requests)
    connection = SourceConnection(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        external_account_id="ig-1",
        linked_page_id="page-1",
    )
    body = sender.build_private_reply_payload(comment_id="1789", text="Hola")
    result = await sender.send(connection, body)
    [request] = requests
    assert request.url.path == "/v21.0/page-1/messages"
    assert request.read() == b'{"recipient":{"comment_id":"1789"},"message":{"text":"Hola"}}'
    assert (result.external_message_id, result.recipient_external_id) == ("aWdfZ", "igsid-ana")


def test_the_send_response_keeps_the_recipient_when_meta_gives_it() -> None:
    assert parse_send_response({"message_id": "m1"}).recipient_external_id is None
    assert parse_send_response({"message_id": "m1", "recipient_id": ""}).recipient_external_id is (
        None
    )
    with pytest.raises(InstagramDirectError):
        parse_send_response({"recipient_id": "igsid"})
