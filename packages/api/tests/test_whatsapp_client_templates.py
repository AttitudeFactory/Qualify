"""WA-18 — the WABA-level template endpoints of `HttpWhatsAppClient`, fully offline.

Same harness as `test_whatsapp_client.py`: the REAL client behind an `httpx.MockTransport`
and a real `_InjectedAuthClient`, answering with doc-derived fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.whatsapp.client import (
    HttpWhatsAppClient,
    TemplateCreateResult,
    WhatsAppApiError,
    build_template_create_body,
)

FIXTURES = Path(__file__).parent / "fixtures" / "whatsapp"
TOKEN = "SUPER_SECRET_WA_SYSTEM_USER_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
PHONE_NUMBER_ID = "1393787420477981"
WABA_ID = "2338576026889338"
BODY = [{"type": "BODY", "text": "Hola {{1}}, hoy 2x1"}]


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / name).read_text())
    assert "DOC-DERIVED" in payload.pop("_fixture_note")
    return payload


class _Script:
    """Answers each request with the next (status, payload) and records it."""

    def __init__(self, *responses: tuple[int, dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._responses.pop(0)
        return httpx.Response(status, json=payload)


def _client(script: _Script, *, waba_id: str | None = WABA_ID) -> HttpWhatsAppClient:
    return HttpWhatsAppClient(
        graph_client=_InjectedAuthClient(
            TOKEN, scheme="Bearer", transport=httpx.MockTransport(script)
        ),
        graph_url=GRAPH,
        phone_number_id=PHONE_NUMBER_ID,
        waba_id=waba_id,
    )


async def test_create_template_posts_the_body_and_parses_the_result() -> None:
    script = _Script((200, _fixture("template_create_response.json")))
    result = await _client(script).create_template(WABA_ID, "promo_2x1", "es", "marketing", BODY)
    assert result == TemplateCreateResult(
        id="594425479261596", status="PENDING", category="marketing"
    )
    (request,) = script.requests
    assert request.method == "POST"
    assert request.url.path == f"/v21.0/{WABA_ID}/message_templates"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "name": "promo_2x1",
        "language": "es",
        "category": "MARKETING",
        "components": BODY,
    }


async def test_list_templates_follows_the_after_cursor_and_skips_broken_rows() -> None:
    script = _Script(
        (200, _fixture("template_list_page1.json")),
        (200, _fixture("template_list_page2.json")),
    )
    templates = await _client(script).list_templates(WABA_ID)
    assert [(t.name, t.status, t.category, t.quality) for t in templates] == [
        ("reservation_confirmation", "APPROVED", "utility", "GREEN"),
        ("promo_viernes", "REJECTED", "marketing", None),
        ("order_ready", "PAUSED", "utility", "RED"),
    ]
    assert templates[1].rejected_reason == "PROMOTIONAL"
    assert templates[0].components[0]["type"] == "BODY"
    first, second = script.requests
    assert first.url.params["fields"].split(",")[:2] == ["id", "name"]
    assert "after" not in first.url.params
    assert second.url.params["after"] == "QVFIUafter1"


async def test_delete_template_by_name() -> None:
    script = _Script((200, {"success": True}))
    await _client(script).delete_template(WABA_ID, "promo_2x1")
    (request,) = script.requests
    assert request.method == "DELETE"
    assert request.url.path == f"/v21.0/{WABA_ID}/message_templates"
    assert request.url.params["name"] == "promo_2x1"


async def test_a_waba_other_than_the_clients_is_refused_before_any_request() -> None:
    script = _Script()
    client = _client(script)
    with pytest.raises(ValueError, match="does not match"):
        await client.list_templates("another-waba")
    with pytest.raises(ValueError, match="does not match"):
        await client.delete_template("another-waba", "x")
    assert script.requests == []


async def test_a_client_without_a_bound_waba_accepts_the_argument() -> None:
    script = _Script((200, {"success": True}))
    await _client(script, waba_id=None).delete_template("any-waba", "promo")
    assert script.requests[0].url.path == "/v21.0/any-waba/message_templates"


async def test_create_error_maps_to_whatsapp_api_error_without_the_body() -> None:
    script = _Script((400, {"error": {"code": 100, "error_subcode": 2388023, "message": "dup"}}))
    with pytest.raises(WhatsAppApiError) as excinfo:
        await _client(script).create_template(WABA_ID, "promo", "es", "marketing", BODY)
    assert (excinfo.value.status, excinfo.value.code, excinfo.value.subcode) == (400, 100, 2388023)
    assert "dup" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("name", "language", "category", "components", "match"),
    [
        ("Promo", "es", "marketing", BODY, "lowercase"),
        ("promo-2x1", "es", "marketing", BODY, "lowercase"),
        ("", "es", "marketing", BODY, "template name"),
        ("p" * 513, "es", "marketing", BODY, "template name"),
        ("promo", "", "marketing", BODY, "language"),
        ("promo", "es", "service", BODY, "category"),
        ("promo", "es", "marketing", [], "component"),
    ],
)
def test_template_create_body_limits(name, language, category, components, match) -> None:
    with pytest.raises(ValueError, match=match):
        build_template_create_body(name, language, category, components)


def test_category_is_accepted_in_any_case() -> None:
    assert build_template_create_body("promo", "es", "Utility", BODY)["category"] == "UTILITY"
