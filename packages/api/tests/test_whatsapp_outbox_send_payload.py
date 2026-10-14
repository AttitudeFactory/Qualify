"""WA-08 — `WhatsAppClient.send_payload`: the stored outbox body goes to `/messages`
VERBATIM. Same offline rig as `test_whatsapp_client.py` (real client, `MockTransport`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.whatsapp.client import (
    ButtonSpec,
    HttpWhatsAppClient,
    WhatsAppApiError,
    build_buttons_body,
    build_text_body,
)

FIXTURES = Path(__file__).parent / "fixtures" / "whatsapp"
GRAPH = "https://graph.facebook.com/v21.0"
PHONE_NUMBER_ID = "1393787420477981"
TO = "+15550001234"


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / name).read_text())
    payload.pop("_fixture_note")
    return payload


class _Recorder:
    def __init__(self, fixture: str, status: int = 200) -> None:
        self._payload, self._status = _fixture(fixture), status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status, json=self._payload)


def _client(handler: _Recorder) -> HttpWhatsAppClient:
    return HttpWhatsAppClient(
        graph_client=_InjectedAuthClient(
            "T", scheme="Bearer", transport=httpx.MockTransport(handler)
        ),
        graph_url=GRAPH,
        phone_number_id=PHONE_NUMBER_ID,
    )


async def test_send_payload_posts_the_stored_body_unchanged_and_returns_the_wamid() -> None:
    rec = _Recorder("send_message_response.json")
    body = build_buttons_body(TO, "Que deseas?", [ButtonSpec("menu", "Ver menu")], None, None)
    wamid = await _client(rec).send_payload(body)
    assert wamid == _fixture("send_message_response.json")["messages"][0]["id"]
    (request,) = rec.requests
    assert request.method == "POST"
    assert request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/messages"
    assert json.loads(request.content) == body


async def test_send_payload_surfaces_a_window_refusal_as_the_api_error() -> None:
    rec = _Recorder("error_window_131047.json", status=400)
    with pytest.raises(WhatsAppApiError) as exc_info:
        await _client(rec).send_payload(build_text_body(TO, "hola", False))
    assert exc_info.value.code == 131047
    assert exc_info.value.status == 400
    assert not exc_info.value.is_auth_error


@pytest.mark.parametrize("payload", [{}, None, "not-a-dict"])
async def test_send_payload_refuses_an_empty_or_non_object_body_before_any_request(
    payload: Any,
) -> None:
    rec = _Recorder("send_message_response.json")
    with pytest.raises(ValueError):
        await _client(rec).send_payload(payload)
    assert rec.requests == []
