"""`qualify_api.meegle.tickets` — offline: a scripted Meegle Open API and a scripted Lark
custom bot, both `httpx.MockTransport`. Pins the rendering of every event the notifier
covers, what is re-read vs taken from the event, the Lark outcome mapping and the
settings."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from qualify_api.meegle.client import TOKEN_PATH, MeegleClient
from qualify_api.meegle.events import MeegleEvent
from qualify_api.meegle.onboarding import WorkItemNotFound
from qualify_api.meegle.settings import MeegleSettings, TicketSettings
from qualify_api.meegle.tickets import (
    LARK_RATE_LIMITED,
    LarkDeliveryError,
    LarkWebhookPoster,
    TicketNotifier,
)

SETTINGS = MeegleSettings(
    base_url="https://meegle.test",
    plugin_id="MII_TEST",
    plugin_secret="plugin-s3cret-value",
    callback_token="cb",
    project_key="proj",
    work_item_type="alta_cliente",
    user_key="u-herwin",
)
ITEM = 24789637
ISSUE_FIELDS = [
    {
        "field_key": "work_item_status",
        "field_name": "Status",
        "field_type_key": "_work_item_status",
        "options": [
            {"label": "Backlog", "value": "OPEN"},
            {"label": "In Progress", "value": "IN PROGRESS"},
            {"label": "Done", "value": "CLOSED"},
        ],
    },
    {
        "field_key": "priority",
        "field_name": "Priority",
        "field_type_key": "select",
        "options": [{"label": "P0", "value": "0"}, {"label": "P1", "value": "1"}],
    },
    {"field_key": "name", "field_name": "Name", "field_type_key": "_name"},
    {
        "field_key": "tags",
        "field_name": "Label",
        "field_type_key": "multi-select",
        "options": [{"label": "Bug", "value": "pcbvjwpb0"}, {"label": "UI", "value": "vhm8_ftor"}],
    },
]


class FakeMeegle:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.items: list[dict[str, Any]] = [
            {
                "id": ITEM,
                "name": "WA-21 · Analítica de la WABA",
                "work_item_type_key": "issue",
                "work_item_status": {"state_key": "CLOSED"},
                "fields": [],
            }
        ]
        self.simple_name: str | None = "5h2wsx"
        self.workflow_nodes = [
            {"id": "started", "state_key": "started", "name": "Start"},
            {"id": "end", "state_key": "end", "name": "Finished"},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == TOKEN_PATH:
            return httpx.Response(
                200, json={"data": {"token": "t", "expire_time": 7200}, "error": {"code": 0}}
            )
        if path.endswith("/field/all"):
            return httpx.Response(200, json={"err_code": 0, "data": ISSUE_FIELDS})
        if path.endswith("/workflow/query"):
            return httpx.Response(
                200, json={"err_code": 0, "data": {"workflow_nodes": self.workflow_nodes}}
            )
        if path.endswith("/query"):
            return httpx.Response(200, json={"err_code": 0, "data": self.items})
        if path == "/open_api/projects/detail":
            data = (
                {
                    "proj": {
                        "project_key": "proj",
                        "name": "Qualify",
                        "simple_name": self.simple_name,
                    }
                }
                if self.simple_name is not None
                else {}
            )
            return httpx.Response(200, json={"err_code": 0, "data": data})
        return httpx.Response(404, json={"err_code": 404, "err_msg": "no such path"})


class FakeLark:
    def __init__(self) -> None:
        self.posted: list[dict[str, Any]] = []
        self.code = 0
        self.status = 200
        self.raise_transport = False
        self.body: Any = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.raise_transport:
            raise httpx.ConnectError("down")
        self.posted.append(json.loads(request.content))
        if self.body is not None:
            return httpx.Response(self.status, content=self.body)
        return httpx.Response(self.status, json={"code": self.code, "msg": "x", "data": {}})


@pytest.fixture
def meegle() -> FakeMeegle:
    return FakeMeegle()


@pytest.fixture
def lark() -> FakeLark:
    return FakeLark()


@pytest.fixture
def notifier(meegle: FakeMeegle, lark: FakeLark) -> TicketNotifier:
    client = MeegleClient(SETTINGS, transport=httpx.MockTransport(meegle.handler))
    poster = LarkWebhookPoster(
        "https://lark.test/hook/abc", transport=httpx.MockTransport(lark.handler)
    )
    return TicketNotifier(client, poster, web_url="https://project.larksuite.test")


def event(
    event_type: int,
    *,
    work_item_type: str = "issue",
    source: str = "normal",
    field_info: list[dict[str, Any]] | None = None,
    node_info: dict[str, Any] | None = None,
    user: dict[str, Any] | None = {"user_key": "u1", "name_en": "Herwin Rey"},
    reason: str | None = None,
    work_item_id: int | None = ITEM,
) -> MeegleEvent:
    data: dict[str, Any] = {
        "event_type": event_type,
        "idempotent_key": "k",
        "project_key": "proj",
        "work_item_type_key": work_item_type,
    }
    if work_item_id is not None:
        data["work_item_info"] = [
            {
                "work_item_id": work_item_id,
                "work_item_name": "from-event",
                "work_item_type_key": work_item_type,
            }
        ]
    if field_info is not None:
        data["field_info"] = field_info
    if node_info is not None:
        data["node_info"] = node_info
    if user is not None:
        data["user_info"] = user
    if reason is not None:
        data["reason"] = reason
    return MeegleEvent.model_validate({"source": source, "data": data})


# -- rendering ---------------------------------------------------------------------------


def test_status_change_names_who_old_new_item_and_link(
    notifier: TicketNotifier, lark: FakeLark
) -> None:
    ev = event(
        3001,
        field_info=[
            {
                "field_key": "work_item_status",
                "before_field_value": "OPEN",
                "after_field_value": "CLOSED",
            },
            {
                "field_key": "archiving_status",
                "before_field_value": "false",
                "after_field_value": "true",
            },
        ],
    )
    assert notifier.notify(ev) == "sent"
    text = lark.posted[0]["content"]["text"]
    assert lark.posted[0]["msg_type"] == "text"
    assert "text" not in lark.posted[0]  # Lark only: no Cliq/Slack top-level `text`
    assert text.splitlines() == [
        "🎫 Herwin Rey cambió el estado · Issue «WA-21 · Analítica de la WABA»",
        "Status: Backlog → Done",
        "archiving_status: false → true",
        "https://project.larksuite.test/5h2wsx/issue/detail/24789637",
    ]


def test_the_item_name_and_status_come_from_meegle_not_the_event(
    notifier: TicketNotifier, lark: FakeLark, meegle: FakeMeegle
) -> None:
    ev = event(3001, field_info=[])  # no status in the event: the re-read item has it
    notifier.notify(ev)
    text = lark.posted[0]["content"]["text"]
    assert "«WA-21 · Analítica de la WABA»" in text and "from-event" not in text
    assert "Estado → Done" in text
    query = [r for r in meegle.requests if r.url.path.endswith("/query")]
    assert query[0].url.path == "/open_api/proj/work_item/issue/query"
    assert json.loads(query[0].content)["work_item_ids"] == [ITEM]


def test_field_changes_render_labels_options_lists_and_empties(
    notifier: TicketNotifier, lark: FakeLark
) -> None:
    ev = event(
        1009,
        field_info=[
            {"field_key": "priority", "before_field_value": "", "after_field_value": "0"},
            {
                "field_key": "tags",
                "before_field_value": '["pcbvjwpb0"]',
                "after_field_value": '["pcbvjwpb0","vhm8_ftor"]',
            },
            {
                "field_key": "name",
                "before_field_value": "old",
                "after_field_value": "new " + "x" * 200,
            },
            {"field_key": "unknown_key", "before_field_value": "a", "after_field_value": "b"},
            {"field_key": "same", "before_field_value": "1", "after_field_value": "1"},
        ],
    )
    notifier.notify(ev)
    lines = lark.posted[0]["content"]["text"].splitlines()
    assert lines[0].startswith("🎫 Herwin Rey modificó · Issue ")
    assert lines[1] == "Priority: — → P0"
    assert lines[2] == "Label: Bug → Bug, UI"
    assert lines[3].startswith("Name: old → new xxx") and lines[3].endswith("…")
    assert lines[4] == "unknown_key: a → b"
    assert len(lines) == 6  # unchanged field skipped; link last


def test_created_terminated_and_node_events(
    notifier: TicketNotifier, lark: FakeLark, meegle: FakeMeegle
) -> None:
    notifier.notify(event(1001, field_info=[]))
    notifier.notify(event(1005, reason="Duplicado", field_info=[]))
    meegle.items[0] = {
        "id": ITEM,
        "name": "Épica — Publicar",
        "work_item_type_key": "story",
        "current_nodes": [{"id": "started", "name": "Start"}],
    }
    notifier.notify(event(2001, work_item_type="story", node_info={"update_nodes": ["end"]}))
    notifier.notify(
        event(
            2004, work_item_type="story", node_info={"update_nodes": ["end"], "reason": "falta QA"}
        )
    )
    notifier.notify(event(1001, work_item_type="story", user=None, source="automation"))
    texts = [p["content"]["text"] for p in lark.posted]
    assert texts[0].splitlines()[:2] == [
        "🎫 Herwin Rey creó · Issue «WA-21 · Analítica de la WABA»",
        "Estado: Done",
    ]
    assert texts[1].splitlines()[:2] == [
        "🎫 Herwin Rey terminó · Issue «WA-21 · Analítica de la WABA»",
        "Motivo: Duplicado",
    ]
    assert texts[2].splitlines() == [
        "🎫 Herwin Rey completó el nodo «Finished» · Feature «Épica — Publicar»",
        "https://project.larksuite.test/5h2wsx/story/detail/24789637",
    ]
    assert texts[3].splitlines()[:2] == [
        "🎫 Herwin Rey revirtió el nodo «Finished» · Feature «Épica — Publicar»",
        "Motivo: falta QA",
    ]
    assert texts[4].splitlines()[:2] == [
        "🎫 una automatización creó · Feature «Épica — Publicar»",
        "Nodo: Start",
    ]


def test_metadata_is_read_once_per_type_and_the_space_once(
    notifier: TicketNotifier, meegle: FakeMeegle
) -> None:
    for _ in range(3):
        notifier.notify(event(3001, field_info=[]))
    paths = [r.url.path for r in meegle.requests]
    assert paths.count("/open_api/proj/field/all") == 1
    assert paths.count("/open_api/projects/detail") == 1
    assert paths.count("/open_api/proj/work_item/issue/query") == 3


def test_without_a_simple_name_the_notice_has_no_link(
    notifier: TicketNotifier, meegle: FakeMeegle, lark: FakeLark
) -> None:
    meegle.simple_name = None
    notifier.notify(event(3001, field_info=[]))
    assert "https://" not in lark.posted[0]["content"]["text"]


def test_a_vanished_item_is_work_item_not_found(
    notifier: TicketNotifier, meegle: FakeMeegle
) -> None:
    meegle.items = []
    with pytest.raises(WorkItemNotFound):
        notifier.notify(event(3001, field_info=[]))
    with pytest.raises(WorkItemNotFound):
        notifier.notify(event(3001, field_info=[], work_item_id=None))


# -- Lark outcomes -----------------------------------------------------------------------


def test_a_lark_rejection_is_settled_not_retried(notifier: TicketNotifier, lark: FakeLark) -> None:
    lark.code = 19024  # keyword rule
    assert notifier.notify(event(3001, field_info=[])) == "lark_rejected:19024"
    lark.code = 0
    lark.status = 400
    assert notifier.notify(event(3001, field_info=[])) == "lark_rejected:400"


def test_transient_lark_failures_raise_for_a_retry(
    notifier: TicketNotifier, lark: FakeLark
) -> None:
    lark.code = LARK_RATE_LIMITED
    with pytest.raises(LarkDeliveryError):
        notifier.notify(event(3001, field_info=[]))
    lark.code = 0
    lark.status = 502
    with pytest.raises(LarkDeliveryError):
        notifier.notify(event(3001, field_info=[]))
    lark.status = 200
    lark.raise_transport = True
    with pytest.raises(LarkDeliveryError):
        notifier.notify(event(3001, field_info=[]))


def test_a_200_without_a_json_code_counts_as_delivered(lark: FakeLark) -> None:
    lark.body = b""
    poster = LarkWebhookPoster(
        "https://lark.test/hook/x", transport=httpx.MockTransport(lark.handler)
    )
    assert poster.post("hola") == 0


def test_logs_never_carry_the_webhook_url(lark: FakeLark, caplog: pytest.LogCaptureFixture) -> None:
    lark.raise_transport = True
    poster = LarkWebhookPoster(
        "https://lark.test/hook/sEcReT-token", transport=httpx.MockTransport(lark.handler)
    )
    with caplog.at_level("DEBUG"), pytest.raises(LarkDeliveryError):
        poster.post("hola")
    assert "sEcReT-token" not in caplog.text


# -- settings ----------------------------------------------------------------------------


def test_ticket_settings_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL",
        "QUALIFY_MEEGLE_TICKET_TYPES",
        "QUALIFY_MEEGLE_WEB_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    off = TicketSettings.from_env()
    assert off.enabled is False
    assert off.ticket_types == frozenset({"story", "issue", "sub_task"})
    assert off.web_url == "https://project.larksuite.com"
    monkeypatch.setenv("QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL", " https://open.larksuite.com/hook/x ")
    monkeypatch.setenv("QUALIFY_MEEGLE_TICKET_TYPES", "issue, story,,")
    monkeypatch.setenv("QUALIFY_MEEGLE_WEB_URL", "https://meegle.com/")
    on = TicketSettings.from_env()
    assert on.enabled is True
    assert on.webhook_url == "https://open.larksuite.com/hook/x"
    assert on.ticket_types == frozenset({"issue", "story"})
    assert on.web_url == "https://meegle.com"
