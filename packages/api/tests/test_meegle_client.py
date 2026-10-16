"""`qualify_api.meegle.client` against `httpx.MockTransport` — paths, bodies, headers, the
token cache, the error envelope, and the logging discipline (no token, no secret)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from qualify_api.meegle.client import (
    TOKEN_MARGIN_SECONDS,
    TOKEN_PATH,
    MeegleApiError,
    MeegleClient,
)
from qualify_api.meegle.settings import MeegleSettings

SETTINGS = MeegleSettings(
    base_url="https://meegle.test",
    plugin_id="MII_TEST",
    plugin_secret="plugin-s3cret-value",
    callback_token="cb",
    project_key="proj",
    work_item_type="alta",
    user_key="u-herwin",
)
TOKEN = "p-token-value-0001"


class FakeMeegle:
    """Scripted Open API. Records every request; answers by path."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.token_ttl: Any = 7200
        self.answers: dict[str, Any] = {}
        self.status: dict[str, int] = {}
        self.raw: dict[str, bytes] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == TOKEN_PATH:
            self.token_calls += 1
            return httpx.Response(
                200,
                json={
                    "data": {"token": f"{TOKEN}-{self.token_calls}", "expire_time": self.token_ttl},
                    "error": {"code": 0, "msg": "success"},
                },
            )
        path = request.url.path
        if path in self.raw:
            return httpx.Response(self.status.get(path, 200), content=self.raw[path])
        body = self.answers.get(path, {"err_code": 0, "err_msg": "", "data": None})
        return httpx.Response(self.status.get(path, 200), json=body)

    def api_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path != TOKEN_PATH]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def fake() -> FakeMeegle:
    return FakeMeegle()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(fake: FakeMeegle, clock: Clock) -> MeegleClient:
    return MeegleClient(SETTINGS, transport=httpx.MockTransport(fake.handler), clock=clock)


def _json(request: httpx.Request) -> Any:
    return json.loads(request.content)


# --------------------------------------------------------------------------------------
# Token
# --------------------------------------------------------------------------------------


def test_token_is_fetched_once_and_sent_with_the_user_key(
    client: MeegleClient, fake: FakeMeegle
) -> None:
    client.update_fields(1, {"f": "v"})
    client.update_fields(1, {"f": "w"})
    token_request = fake.requests[0]
    assert token_request.url.path == TOKEN_PATH
    assert _json(token_request) == {
        "plugin_id": "MII_TEST",
        "plugin_secret": "plugin-s3cret-value",
        "type": 0,
    }
    assert fake.token_calls == 1
    for request in fake.api_requests():
        assert request.headers["X-Plugin-Token"] == f"{TOKEN}-1"
        assert request.headers["X-User-Key"] == "u-herwin"


def test_token_is_renewed_a_margin_before_it_expires(
    client: MeegleClient, fake: FakeMeegle, clock: Clock
) -> None:
    client.update_fields(1, {"f": "v"})
    clock.now += 7200 - TOKEN_MARGIN_SECONDS - 1
    client.update_fields(1, {"f": "v"})
    assert fake.token_calls == 1
    clock.now += 2
    client.update_fields(1, {"f": "v"})
    assert fake.token_calls == 2
    assert fake.api_requests()[-1].headers["X-Plugin-Token"] == f"{TOKEN}-2"


def test_a_token_refusal_is_a_meegle_api_error(fake: FakeMeegle, clock: Clock) -> None:
    def refusing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {}, "error": {"code": 10001, "msg": "invalid plugin secret"}}
        )

    client = MeegleClient(SETTINGS, transport=httpx.MockTransport(refusing), clock=clock)
    with pytest.raises(MeegleApiError) as exc:
        client.comment(1, "x")
    assert exc.value.code == 10001 and "invalid plugin secret" in str(exc.value)


# --------------------------------------------------------------------------------------
# The six calls
# --------------------------------------------------------------------------------------


def test_update_fields_puts_field_value_pairs(client: MeegleClient, fake: FakeMeegle) -> None:
    client.update_fields(42, {"field_a": "invitada", "field_b": 1730184005453})
    (request,) = fake.api_requests()
    assert request.method == "PUT"
    assert request.url.path == "/open_api/proj/work_item/alta/42"
    assert _json(request) == {
        "update_fields": [
            {"field_key": "field_a", "field_value": "invitada"},
            {"field_key": "field_b", "field_value": 1730184005453},
        ]
    }


def test_operate_node_confirm_and_rollback(client: MeegleClient, fake: FakeMeegle) -> None:
    client.operate_node(42, "state_2")
    client.operate_node(42, "state_0", action="rollback", rollback_reason="correo inválido")
    confirm, rollback = fake.api_requests()
    assert confirm.method == "POST"
    assert confirm.url.path == "/open_api/proj/workflow/alta/42/node/state_2/operate"
    assert _json(confirm) == {"action": "confirm"}
    assert rollback.url.path == "/open_api/proj/workflow/alta/42/node/state_0/operate"
    assert _json(rollback) == {"action": "rollback", "rollback_reason": "correo inválido"}


def test_comment_posts_content_and_returns_the_id(client: MeegleClient, fake: FakeMeegle) -> None:
    fake.answers["/open_api/proj/work_item/alta/42/comment/create"] = {
        "err_code": 0,
        "err_msg": "",
        "data": 987654,
    }
    assert client.comment(42, "Invitación enviada a a@b.co") == 987654
    (request,) = fake.api_requests()
    assert _json(request) == {"content": "Invitación enviada a a@b.co"}


def test_workflow_lists_nodes_with_id_state_key_and_name(
    client: MeegleClient, fake: FakeMeegle
) -> None:
    fake.answers["/open_api/proj/work_item/alta/42/workflow/query"] = {
        "err_code": 0,
        "data": {
            "workflow_nodes": [
                {"id": "started", "state_key": "started", "name": "Datos", "status": 3},
                {"id": "state_0", "state_key": "state_0", "name": "Invitada", "status": 2},
                {"id": "state_1", "name": "Registrada", "status": "weird"},
                "garbage",
            ],
            "connections": [],
        },
    }
    nodes = client.workflow(42)
    assert [(n.id, n.state_key, n.name, n.status) for n in nodes] == [
        ("started", "started", "Datos", 3),
        ("state_0", "state_0", "Invitada", 2),
        ("state_1", "state_1", "Registrada", None),
    ]
    (request,) = fake.api_requests()
    assert request.method == "POST" and _json(request) == {}


def test_query_returns_items_with_fields_by_key(client: MeegleClient, fake: FakeMeegle) -> None:
    fake.answers["/open_api/proj/work_item/alta/query"] = {
        "err_code": 0,
        "data": [
            {
                "id": 42,
                "name": "Arepera La Nona",
                "fields": [
                    {"field_key": "field_mail", "field_value": "maria@arepera.com"},
                    {"field_key": "field_note", "field_value": None},
                    {"no_key": True},
                ],
                "multi_texts": [
                    {"field_key": "field_note", "field_value": {"doc_text": "Como hablamos"}}
                ],
                "current_nodes": [{"id": "state_0", "name": "Invitada"}],
            },
            {"id": "not-an-int"},
        ],
    }
    (item,) = client.query([42])
    assert item.id == 42 and item.name == "Arepera La Nona"
    assert item.fields == {
        "field_mail": "maria@arepera.com",
        "field_note": {"doc_text": "Como hablamos"},
    }
    assert item.current_nodes == ("state_0",)
    (request,) = fake.api_requests()
    assert request.url.path == "/open_api/proj/work_item/alta/query"
    assert _json(request) == {"work_item_ids": [42], "expand": {"need_multi_text": True}}


def test_fields_meta_maps_names_types_and_options(client: MeegleClient, fake: FakeMeegle) -> None:
    fake.answers["/open_api/proj/field/all"] = {
        "err_code": 0,
        "data": [
            {
                "field_key": "field_estado",
                "field_name": "Estado Qualify",
                "field_type_key": "select",
                "options": [
                    {"label": "pendiente", "value": "option_1"},
                    {"label": "invitada", "value": "option_2"},
                ],
            },
            {"field_key": "field_mail", "field_alias": "Correo", "field_type_key": "text"},
            {"field_name": "no key"},
        ],
    }
    estado, correo = client.fields_meta()
    assert estado.key == "field_estado" and estado.type_key == "select"
    assert estado.option_value("Invitada") == "option_2"
    assert estado.option_value("vencida") is None
    assert correo.name == "Correo" and correo.options == ()
    (request,) = fake.api_requests()
    assert _json(request) == {"work_item_type_key": "alta"}


# --------------------------------------------------------------------------------------
# Errors and logging discipline
# --------------------------------------------------------------------------------------


def test_a_non_zero_err_code_is_an_error_with_meegles_message(
    client: MeegleClient, fake: FakeMeegle
) -> None:
    fake.answers["/open_api/proj/work_item/alta/42"] = {"err_code": 30003, "err_msg": "no perm"}
    with pytest.raises(MeegleApiError) as exc:
        client.update_fields(42, {"a": 1})
    assert exc.value.code == 30003 and exc.value.message == "Meegle refused (30003): no perm"


def test_http_errors_and_non_json_bodies_are_errors(client: MeegleClient, fake: FakeMeegle) -> None:
    path = "/open_api/proj/work_item/alta/42/comment/create"
    fake.status[path] = 502
    fake.raw[path] = b"<html>bad gateway</html>"
    with pytest.raises(MeegleApiError) as exc:
        client.comment(42, "x")
    assert exc.value.status == 502
    fake.raw.pop(path)
    fake.answers[path] = {"err_code": 0, "data": 1}
    with pytest.raises(MeegleApiError):  # 5xx with a clean envelope is still an error
        client.comment(42, "x")


def test_transport_failures_are_errors(clock: Clock) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = MeegleClient(SETTINGS, transport=httpx.MockTransport(boom), clock=clock)
    with pytest.raises(MeegleApiError):
        client.query([1])


def test_logs_never_carry_the_token_or_the_secret(
    client: MeegleClient, fake: FakeMeegle, caplog: pytest.LogCaptureFixture
) -> None:
    fake.answers["/open_api/proj/work_item/alta/42"] = {"err_code": 1, "err_msg": "nope"}
    with caplog.at_level(logging.DEBUG, logger="qualify_api.meegle.client"):
        with pytest.raises(MeegleApiError) as exc:
            client.update_fields(42, {"a": 1})
    text = caplog.text + str(exc.value) + repr(exc.value)
    assert TOKEN not in text
    assert "plugin-s3cret-value" not in text
    assert "renewed" in caplog.text  # the token lifecycle IS logged, by event only
