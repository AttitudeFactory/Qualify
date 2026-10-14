"""WA-06 — the WhatsApp Cloud API client, fully offline.

Every call drives the REAL `HttpWhatsAppClient` through an `httpx.MockTransport` behind a
real `_InjectedAuthClient` (exactly what `CredentialResolver.client_for(...,
scheme="Bearer")` returns), so URL construction, the bearer header, the JSON body and the
parser all run — zero network. Response payloads come from
`tests/fixtures/whatsapp/*.json`, each doc-derived and saying so in `_fixture_note`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.whatsapp.client import (
    MAX_BUTTONS,
    MAX_COMMANDS,
    MAX_ICE_BREAKERS,
    MAX_LIST_ROWS_TOTAL,
    MAX_LIST_SECTIONS,
    BusinessProfileUpdate,
    ButtonSpec,
    Command,
    ConversationalAutomation,
    HttpWhatsAppClient,
    ListRow,
    ListSection,
    WhatsAppApiError,
    _parse_conversational_automation,
    _parse_send_response,
)

FIXTURES = Path(__file__).parent / "fixtures" / "whatsapp"
TOKEN = "SUPER_SECRET_WA_SYSTEM_USER_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
PHONE_NUMBER_ID = "1393787420477981"
TO = "+15550001234"
WAMID = "wamid.HBgLMTU1NTAwMDEyMzQVAgARGBI5QUREQkY4RkE0QzM0MjlFNDMA"


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / name).read_text())
    assert "DOC-DERIVED" in payload.pop("_fixture_note")
    return payload


class _Recorder:
    """Captures the single request a method makes and answers it with a fixture."""

    def __init__(self, fixture: str | dict[str, Any], status: int = 200, raw: bytes | None = None):
        self._payload = _fixture(fixture) if isinstance(fixture, str) else fixture
        self._status = status
        self._raw = raw
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._raw is not None:
            return httpx.Response(self._status, content=self._raw)
        return httpx.Response(self._status, json=self._payload)

    @property
    def request(self) -> httpx.Request:
        assert len(self.requests) == 1, "expected exactly one request"
        return self.requests[0]

    @property
    def json(self) -> Any:
        return json.loads(self.request.content)


def _client(handler: _Recorder) -> HttpWhatsAppClient:
    transport = httpx.MockTransport(handler)
    return HttpWhatsAppClient(
        graph_client=_InjectedAuthClient(TOKEN, scheme="Bearer", transport=transport),
        graph_url=GRAPH,
        phone_number_id=PHONE_NUMBER_ID,
    )


# --------------------------------------------------------------------------------------
# messages
# --------------------------------------------------------------------------------------


async def test_send_text_posts_the_documented_body_and_returns_wamid() -> None:
    rec = _Recorder("send_message_response.json")
    wamid = await _client(rec).send_text(TO, "hola", preview_url=True)
    assert wamid == WAMID
    assert rec.request.method == "POST"
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/messages"
    assert rec.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert rec.json == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": TO,
        "type": "text",
        "text": {"preview_url": True, "body": "hola"},
    }


async def test_send_interactive_buttons_body() -> None:
    rec = _Recorder("send_message_response.json")
    buttons = [ButtonSpec("menu", "Ver menu"), ButtonSpec("order", "Pedir")]
    wamid = await _client(rec).send_interactive_buttons(
        TO, "Elige", buttons, header="Hola", footer="Qualify"
    )
    assert wamid == WAMID
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/messages"
    assert rec.json == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": TO,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": "Hola"},
            "body": {"text": "Elige"},
            "footer": {"text": "Qualify"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "menu", "title": "Ver menu"}},
                    {"type": "reply", "reply": {"id": "order", "title": "Pedir"}},
                ]
            },
        },
    }


async def test_send_interactive_buttons_omits_header_and_footer_when_absent() -> None:
    rec = _Recorder("send_message_response.json")
    await _client(rec).send_interactive_buttons(TO, "Elige", [ButtonSpec("a", "A")])
    interactive = rec.json["interactive"]
    assert "header" not in interactive and "footer" not in interactive


async def test_send_interactive_list_body() -> None:
    rec = _Recorder("send_message_response.json")
    sections = [
        ListSection(
            title="Hamburguesas",
            rows=[ListRow("h1", "Clasica", "Carne 150 g"), ListRow("h2", "Doble")],
        ),
        ListSection(title="Bebidas", rows=[ListRow("b1", "Gaseosa")]),
    ]
    wamid = await _client(rec).send_interactive_list(
        TO, "Nuestro menu", "Ver opciones", sections, header="Menu", footer="Qualify"
    )
    assert wamid == WAMID
    assert rec.json == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": TO,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "Menu"},
            "body": {"text": "Nuestro menu"},
            "footer": {"text": "Qualify"},
            "action": {
                "button": "Ver opciones",
                "sections": [
                    {
                        "title": "Hamburguesas",
                        "rows": [
                            {"id": "h1", "title": "Clasica", "description": "Carne 150 g"},
                            {"id": "h2", "title": "Doble"},
                        ],
                    },
                    {"title": "Bebidas", "rows": [{"id": "b1", "title": "Gaseosa"}]},
                ],
            },
        },
    }


@pytest.mark.parametrize(
    ("kind", "kwargs", "expected"),
    [
        ("image", {"media_id": "m1", "caption": "foto"}, {"id": "m1", "caption": "foto"}),
        ("video", {"link": "https://x/v.mp4"}, {"link": "https://x/v.mp4"}),
        (
            "document",
            {"media_id": "m2", "caption": "carta", "filename": "carta.pdf"},
            {"id": "m2", "caption": "carta", "filename": "carta.pdf"},
        ),
        ("audio", {"media_id": "m3"}, {"id": "m3"}),
    ],
)
async def test_send_media_bodies(kind: str, kwargs: dict[str, Any], expected: dict) -> None:
    rec = _Recorder("send_message_response.json")
    wamid = await _client(rec).send_media(TO, kind, **kwargs)  # type: ignore[arg-type]
    assert wamid == WAMID
    assert rec.json == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": TO,
        "type": kind,
        kind: expected,
    }


async def test_send_template_body_and_message_status_tolerated() -> None:
    rec = _Recorder("send_template_response.json")
    components = [{"type": "body", "parameters": [{"type": "text", "text": "Herwin"}]}]
    wamid = await _client(rec).send_template(TO, "confirmacion_pedido", "es", components)
    assert wamid.startswith("wamid.")
    assert rec.json == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": TO,
        "type": "template",
        "template": {
            "name": "confirmacion_pedido",
            "language": {"code": "es"},
            "components": components,
        },
    }


async def test_send_template_without_components_omits_the_key() -> None:
    rec = _Recorder("send_template_response.json")
    await _client(rec).send_template(TO, "hello_world", "en_US")
    assert "components" not in rec.json["template"]


async def test_mark_read_body() -> None:
    rec = _Recorder("success_response.json")
    await _client(rec).mark_read("wamid.IN")
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/messages"
    assert rec.json == {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.IN"}


async def test_mark_read_with_typing_indicator() -> None:
    rec = _Recorder("success_response.json")
    await _client(rec).mark_read("wamid.IN", typing=True)
    assert rec.json == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.IN",
        "typing_indicator": {"type": "text"},
    }


async def test_mark_read_without_success_true_raises() -> None:
    rec = _Recorder({"success": False})
    with pytest.raises(WhatsAppApiError):
        await _client(rec).mark_read("wamid.IN")


# --------------------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------------------


async def test_upload_media_is_multipart_with_type_and_product() -> None:
    rec = _Recorder("media_upload_response.json")
    media_id = await _client(rec).upload_media(b"\xff\xd8\xffdata", "image/jpeg", "foto.jpg")
    assert media_id == "1234567890123456"
    req = rec.request
    assert req.method == "POST"
    assert req.url.path == f"/v21.0/{PHONE_NUMBER_ID}/media"
    assert req.headers["Content-Type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="messaging_product"\r\n\r\nwhatsapp' in body
    assert b'name="type"\r\n\r\nimage/jpeg' in body
    assert b'name="file"; filename="foto.jpg"' in body
    assert b"Content-Type: image/jpeg" in body
    assert b"\xff\xd8\xffdata" in body


async def test_media_url_passes_phone_number_id_and_parses_info() -> None:
    rec = _Recorder("media_info_response.json")
    info = await _client(rec).media_url("1234567890123456")
    assert rec.request.method == "GET"
    assert rec.request.url.path == "/v21.0/1234567890123456"
    assert rec.request.url.params["phone_number_id"] == PHONE_NUMBER_ID
    assert info.id == "1234567890123456"
    assert info.url.startswith("https://lookaside.fbsbx.com/")
    assert info.mime_type == "image/jpeg"
    assert info.file_size == 303833
    assert info.sha256 is not None and len(info.sha256) == 64


async def test_download_media_sends_bearer_and_returns_bytes() -> None:
    rec = _Recorder({}, raw=b"binary-jpeg")
    url = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1&ext=2&hash=3"
    content = await _client(rec).download_media(url)
    assert content == b"binary-jpeg"
    assert str(rec.request.url) == url
    assert rec.request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_download_media_404_is_an_api_error_with_status() -> None:
    rec = _Recorder({}, status=404, raw=b"")
    with pytest.raises(WhatsAppApiError) as info:
        await _client(rec).download_media("https://lookaside.fbsbx.com/x")
    assert info.value.status == 404
    assert not info.value.is_auth_error


# --------------------------------------------------------------------------------------
# phone number / business profile / automation / QR
# --------------------------------------------------------------------------------------


async def test_get_phone_number_requests_fields_and_parses() -> None:
    rec = _Recorder("phone_number_response.json")
    info = await _client(rec).get_phone_number()
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}"
    assert rec.request.url.params["fields"] == (
        "verified_name,display_phone_number,quality_rating,messaging_limit_tier,"
        "name_status,status,code_verification_status"
    )
    assert info.id == PHONE_NUMBER_ID
    assert info.verified_name == "Qualify Test"
    assert info.display_phone_number == "+1 555-000-1234"
    assert info.quality_rating == "GREEN"
    assert info.messaging_limit_tier == "TIER_250"
    assert info.name_status == "AVAILABLE_WITHOUT_REVIEW"
    assert info.status == "CONNECTED"
    assert info.code_verification_status == "VERIFIED"


async def test_get_business_profile_unwraps_data_zero() -> None:
    rec = _Recorder("business_profile_response.json")
    profile = await _client(rec).get_business_profile()
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/whatsapp_business_profile"
    assert rec.request.url.params["fields"] == (
        "about,address,description,email,profile_picture_url,websites,vertical"
    )
    assert profile.about == "Pedidos por WhatsApp"
    assert profile.vertical == "RESTAURANT"
    assert profile.websites == ("https://example.com",)
    assert profile.profile_picture_url is not None


async def test_update_business_profile_sends_only_set_fields() -> None:
    rec = _Recorder("success_response.json")
    await _client(rec).update_business_profile(
        BusinessProfileUpdate(about="Abierto 24/7", websites=["https://example.com"])
    )
    assert rec.request.method == "POST"
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/whatsapp_business_profile"
    assert rec.json == {
        "messaging_product": "whatsapp",
        "about": "Abierto 24/7",
        "websites": ["https://example.com"],
    }


async def test_get_conversational_automation_parses_prompts_commands_and_welcome() -> None:
    rec = _Recorder("conversational_automation_response.json")
    automation = await _client(rec).get_conversational_automation()
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}"
    assert rec.request.url.params["fields"] == "conversational_automation"
    assert automation.ice_breakers == ["Ver el menu", "Horario de hoy"]
    assert automation.commands == [
        Command("menu", "Ver el menu del dia"),
        Command("pedido", "Estado de mi pedido"),
    ]
    assert automation.enable_welcome_message is True


def test_conversational_automation_absent_block_reads_as_empty() -> None:
    automation = _parse_conversational_automation({"id": PHONE_NUMBER_ID})
    assert automation == ConversationalAutomation()


async def test_set_conversational_automation_body() -> None:
    rec = _Recorder("success_response.json")
    await _client(rec).set_conversational_automation(
        ConversationalAutomation(
            ice_breakers=["Ver el menu"],
            commands=[Command("menu", "Ver el menu del dia")],
            enable_welcome_message=True,
        )
    )
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/conversational_automation"
    assert rec.json == {
        "enable_welcome_message": True,
        "prompts": ["Ver el menu"],
        "commands": [{"command_name": "menu", "command_description": "Ver el menu del dia"}],
    }


async def test_create_qr_code_body_and_parse() -> None:
    rec = _Recorder("qr_create_response.json")
    qr = await _client(rec).create_qr_code("Hola, quiero pedir")
    assert rec.request.method == "POST"
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/message_qrdls"
    assert rec.json == {"prefilled_message": "Hola, quiero pedir", "generate_qr_image": "PNG"}
    assert qr.code == "ABCDEFGH"
    assert qr.deep_link_url == "https://wa.me/message/ABCDEFGH"
    assert qr.qr_image_url is not None and qr.qr_image_url.endswith(".png")


async def test_list_qr_codes() -> None:
    rec = _Recorder("qr_list_response.json")
    codes = await _client(rec).list_qr_codes()
    assert rec.request.method == "GET"
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/message_qrdls"
    assert [c.code for c in codes] == ["ABCDEFGH", "IJKLMNOP"]
    assert all(c.qr_image_url is None for c in codes)


async def test_delete_qr_code_uses_http_delete() -> None:
    rec = _Recorder("success_response.json")
    await _client(rec).delete_qr_code("ABCDEFGH")
    assert rec.request.method == "DELETE"
    assert rec.request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/message_qrdls/ABCDEFGH"
    assert rec.request.headers["Authorization"] == f"Bearer {TOKEN}"


# --------------------------------------------------------------------------------------
# error mapping
# --------------------------------------------------------------------------------------


async def test_graph_error_190_maps_to_auth_error_without_the_body() -> None:
    rec = _Recorder("error_auth_190.json", status=401)
    with pytest.raises(WhatsAppApiError) as info:
        await _client(rec).send_text(TO, "hola")
    err = info.value
    assert err.status == 401
    assert err.code == 190
    assert err.subcode == 463
    assert err.is_auth_error
    assert err.error_data_details is None
    assert "Session has expired" not in str(err)
    assert "hola" not in str(err)


async def test_code_190_on_a_400_is_still_an_auth_error() -> None:
    rec = _Recorder("error_auth_190.json", status=400)
    with pytest.raises(WhatsAppApiError) as info:
        await _client(rec).get_phone_number()
    assert info.value.is_auth_error


async def test_window_error_carries_meta_details_but_not_user_text() -> None:
    rec = _Recorder("error_window_131047.json", status=400)
    with pytest.raises(WhatsAppApiError) as info:
        await _client(rec).send_text(TO, "texto privado del operador")
    err = info.value
    assert err.code == 131047
    assert not err.is_auth_error
    assert err.error_data_details is not None and "24 hours" in err.error_data_details
    assert "texto privado" not in str(err)
    assert "texto privado" not in (err.error_data_details or "")


async def test_transport_failure_is_flagged_ambiguous() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    transport = httpx.MockTransport(handler)
    client = HttpWhatsAppClient(
        graph_client=_InjectedAuthClient(TOKEN, scheme="Bearer", transport=transport),
        graph_url=GRAPH,
        phone_number_id=PHONE_NUMBER_ID,
    )
    with pytest.raises(WhatsAppApiError) as info:
        await client.send_text(TO, "hola")
    assert info.value.is_transport
    assert info.value.status is None


async def test_non_json_200_is_an_api_error() -> None:
    rec = _Recorder({}, raw=b"<html>oops</html>")
    with pytest.raises(WhatsAppApiError):
        await _client(rec).send_text(TO, "hola")


def test_parse_send_response_without_messages_raises() -> None:
    with pytest.raises(WhatsAppApiError):
        _parse_send_response({"messaging_product": "whatsapp", "contacts": []})


# --------------------------------------------------------------------------------------
# limit validation — raised BEFORE any request is made
# --------------------------------------------------------------------------------------


class _NeverCalled:
    def __call__(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request was made despite a validation failure")


def _strict() -> HttpWhatsAppClient:
    transport = httpx.MockTransport(_NeverCalled())
    return HttpWhatsAppClient(
        graph_client=_InjectedAuthClient(TOKEN, scheme="Bearer", transport=transport),
        graph_url=GRAPH,
        phone_number_id=PHONE_NUMBER_ID,
    )


async def test_more_than_three_buttons_rejected() -> None:
    buttons = [ButtonSpec(f"b{i}", f"B{i}") for i in range(MAX_BUTTONS + 1)]
    with pytest.raises(ValueError, match="1..3 buttons"):
        await _strict().send_interactive_buttons(TO, "x", buttons)


async def test_button_title_over_20_chars_rejected() -> None:
    with pytest.raises(ValueError, match="button title exceeds 20"):
        await _strict().send_interactive_buttons(TO, "x", [ButtonSpec("a", "x" * 21)])


async def test_duplicate_button_titles_rejected() -> None:
    with pytest.raises(ValueError, match="titles must be unique"):
        await _strict().send_interactive_buttons(
            TO, "x", [ButtonSpec("a", "Igual"), ButtonSpec("b", "Igual")]
        )


async def test_list_over_ten_rows_total_rejected() -> None:
    rows = [ListRow(f"r{i}", f"R{i}") for i in range(MAX_LIST_ROWS_TOTAL + 1)]
    with pytest.raises(ValueError, match="1..10 rows in total"):
        await _strict().send_interactive_list(TO, "x", "Ver", [ListSection(rows=rows)])


async def test_list_over_ten_sections_rejected() -> None:
    sections = [
        ListSection(title=f"S{i}", rows=[ListRow(f"r{i}", "R")])
        for i in range(MAX_LIST_SECTIONS + 1)
    ]
    with pytest.raises(ValueError, match="1..10 sections"):
        await _strict().send_interactive_list(TO, "x", "Ver", sections)


async def test_list_row_title_over_24_chars_rejected() -> None:
    with pytest.raises(ValueError, match="row title exceeds 24"):
        await _strict().send_interactive_list(
            TO, "x", "Ver", [ListSection(rows=[ListRow("r", "y" * 25)])]
        )


async def test_list_button_label_over_20_chars_rejected() -> None:
    with pytest.raises(ValueError, match="list button label exceeds 20"):
        await _strict().send_interactive_list(
            TO, "x", "z" * 21, [ListSection(rows=[ListRow("r", "R")])]
        )


async def test_multi_section_list_requires_section_titles() -> None:
    sections = [ListSection(rows=[ListRow("a", "A")]), ListSection(rows=[ListRow("b", "B")])]
    with pytest.raises(ValueError, match="section title is required"):
        await _strict().send_interactive_list(TO, "x", "Ver", sections)


async def test_media_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError, match="exactly one of media_id or link"):
        await _strict().send_media(TO, "image")
    with pytest.raises(ValueError, match="exactly one of media_id or link"):
        await _strict().send_media(TO, "image", media_id="m", link="https://x")


async def test_audio_caption_and_non_document_filename_rejected() -> None:
    with pytest.raises(ValueError, match="audio messages do not support a caption"):
        await _strict().send_media(TO, "audio", media_id="m", caption="no")
    with pytest.raises(ValueError, match="filename is only valid for document"):
        await _strict().send_media(TO, "image", media_id="m", filename="x.jpg")


async def test_caption_over_1024_rejected() -> None:
    with pytest.raises(ValueError, match="caption exceeds 1024"):
        await _strict().send_media(TO, "image", media_id="m", caption="c" * 1025)


async def test_ice_breakers_limits() -> None:
    too_many = ConversationalAutomation(ice_breakers=["a"] * (MAX_ICE_BREAKERS + 1))
    with pytest.raises(ValueError, match="at most 4 ice breakers"):
        await _strict().set_conversational_automation(too_many)
    too_long = ConversationalAutomation(ice_breakers=["x" * 81])
    with pytest.raises(ValueError, match="ice breaker exceeds 80"):
        await _strict().set_conversational_automation(too_long)
    emoji = ConversationalAutomation(ice_breakers=["Ver el menu \U0001f354"])
    with pytest.raises(ValueError, match="do not support emoji"):
        await _strict().set_conversational_automation(emoji)


async def test_command_limits() -> None:
    too_many = ConversationalAutomation(
        commands=[Command(f"c{i}", "h") for i in range(MAX_COMMANDS + 1)]
    )
    with pytest.raises(ValueError, match="at most 30 commands"):
        await _strict().set_conversational_automation(too_many)
    long_name = ConversationalAutomation(commands=[Command("n" * 33, "h")])
    with pytest.raises(ValueError, match="command name exceeds 32"):
        await _strict().set_conversational_automation(long_name)
    long_hint = ConversationalAutomation(commands=[Command("menu", "h" * 257)])
    with pytest.raises(ValueError, match="command hint exceeds 256"):
        await _strict().set_conversational_automation(long_hint)
    slash = ConversationalAutomation(commands=[Command("/menu", "h")])
    with pytest.raises(ValueError, match="leading slash"):
        await _strict().set_conversational_automation(slash)
    duplicate = ConversationalAutomation(commands=[Command("menu", "a"), Command("menu", "b")])
    with pytest.raises(ValueError, match="command names must be unique"):
        await _strict().set_conversational_automation(duplicate)


async def test_accented_ice_breaker_is_not_an_emoji() -> None:
    """Spanish text with tildes and the ñ must pass the emoji check — only pictographs
    (Unicode `So`) are rejected."""
    rec = _Recorder("success_response.json")
    await _client(rec).set_conversational_automation(
        ConversationalAutomation(ice_breakers=["¿Qué hay de menú? ¡Años!"])
    )
    assert rec.json["prompts"] == ["¿Qué hay de menú? ¡Años!"]


async def test_business_profile_update_limits() -> None:
    with pytest.raises(ValueError, match="about exceeds 139"):
        await _strict().update_business_profile(BusinessProfileUpdate(about="a" * 140))
    with pytest.raises(ValueError, match="at most 2 websites"):
        await _strict().update_business_profile(
            BusinessProfileUpdate(websites=["https://a", "https://b", "https://c"])
        )
    with pytest.raises(ValueError, match="must start with http"):
        await _strict().update_business_profile(BusinessProfileUpdate(websites=["ftp://a"]))
    with pytest.raises(ValueError, match="no field to change"):
        await _strict().update_business_profile(BusinessProfileUpdate())


async def test_qr_prefilled_message_limits() -> None:
    with pytest.raises(ValueError, match="prefilled_message exceeds 140"):
        await _strict().create_qr_code("m" * 141)
    with pytest.raises(ValueError, match="PNG or SVG"):
        await _strict().create_qr_code("hola", image_format="JPG")  # type: ignore[arg-type]


async def test_text_body_over_4096_rejected() -> None:
    with pytest.raises(ValueError, match="text body exceeds 4096"):
        await _strict().send_text(TO, "t" * 4097)


def test_empty_phone_number_id_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        HttpWhatsAppClient(
            graph_client=_InjectedAuthClient(TOKEN, scheme="Bearer"),
            graph_url=GRAPH,
            phone_number_id="",
        )
