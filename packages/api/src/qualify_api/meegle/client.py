"""A thin, typed httpx client over the Meegle Open API — no SDK (house style).

The calls the onboarding engine needs (plan §3) plus what the ticket notifier adds (one
read of the space's `simple_name` for links), each a method returning plain dataclasses.
Every item call takes an optional `work_item_type`: the onboarding engine lives on the
configured "Alta de cliente" type (the default), the ticket notifier reads Features /
Issues / Tasks of the same space. Authentication is the plugin token:
`POST /open_api/authen/plugin_token` with `{plugin_id, plugin_secret, type: 0}` →
`data.token` valid `data.expire_time` seconds (2 h), cached here and renewed
`TOKEN_MARGIN` before it expires. Every call carries
`X-Plugin-Token` and `X-User-Key` (plan D1: the writes are signed by the configured member
of the space).

Response envelope (Open API v2, `core.CodeError` in the official Go SDK): `err_code` /
`err_msg` at the top level (0 = ok), `data` with the payload; the token endpoint answers
with `error.code` / `error.msg` instead. Both are checked. A non-zero code, a non-2xx
status or a transport failure is `MeegleApiError` — one exception type, carrying the code
and Meegle's message (never a token, never a secret).

Logging discipline: exception types and error codes only. The token and the plugin secret
never reach a log line, an exception message or a repr.

Paths (`docs/plan-altas-meegle.md` §1, verified against the Go SDK):

    PUT  /open_api/{project_key}/work_item/{type}/{id}                 update_fields
    POST /open_api/{project_key}/workflow/{type}/{id}/node/{node_id}/operate   operate_node
    POST /open_api/{project_key}/work_item/{type}/{id}/comment/create  comment
    POST /open_api/{project_key}/work_item/{type}/{id}/workflow/query  workflow
    POST /open_api/{project_key}/work_item/{type}/query                query
    POST /open_api/{project_key}/field/all                             fields_meta
    POST /open_api/projects/detail                                     space_simple_name
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from qualify_api.meegle.settings import MeegleSettings

logger = logging.getLogger("qualify_api.meegle.client")

TOKEN_PATH = "/open_api/authen/plugin_token"
TOKEN_MARGIN_SECONDS = 300.0
DEFAULT_TOKEN_TTL_SECONDS = 7200
_TIMEOUT_SECONDS = 15.0

NodeAction = Literal["confirm", "rollback"]


class MeegleApiError(RuntimeError):
    """Meegle refused or could not be reached. `code` is Meegle's `err_code` (or the HTTP
    status when the body carried none); `message` is Meegle's own text."""

    def __init__(self, message: str, *, code: int | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass(frozen=True)
class WorkItem:
    id: int
    name: str
    fields: dict[str, Any]  # field_key -> field_value, as Meegle returned it
    current_nodes: tuple[str, ...] = ()  # node ids the item currently sits on
    current_node_names: tuple[str, ...] = ()  # their display names, same order
    work_item_type_key: str = ""
    status_key: str = ""  # `work_item_status.state_key` (status-flow items), else ""


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    state_key: str
    name: str
    status: int | None = None


@dataclass(frozen=True)
class FieldMeta:
    key: str
    name: str
    type_key: str
    options: tuple[tuple[str, str], ...] = ()  # (label, value)

    def option_value(self, label: str) -> str | None:
        wanted = label.strip().casefold()
        for option_label, value in self.options:
            if option_label.strip().casefold() == wanted:
                return value
        return None


def _str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


class MeegleClient:
    """`transport` lets tests plug an `httpx.MockTransport`; `clock` a fake monotonic
    clock for the token cache. The client is synchronous: the worker runs it off the
    event loop (`asyncio.to_thread`), the signup path calls it after its transaction."""

    def __init__(
        self,
        settings: MeegleSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = _TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._http = httpx.Client(base_url=settings.base_url, transport=transport, timeout=timeout)
        self._token: str | None = None
        self._token_deadline = 0.0

    def close(self) -> None:
        self._http.close()

    # -- auth ----------------------------------------------------------------------------

    def _token_value(self) -> str:
        if self._token is not None and self._clock() < self._token_deadline:
            return self._token
        try:
            response = self._http.post(
                TOKEN_PATH,
                json={
                    "plugin_id": self._settings.plugin_id,
                    "plugin_secret": self._settings.plugin_secret,
                    "type": 0,
                },
            )
        except httpx.HTTPError as exc:
            logger.error("meegle token: transport failure (%s)", type(exc).__name__)
            raise MeegleApiError("could not reach Meegle for a plugin token") from exc
        payload = self._payload(response, what="token")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise MeegleApiError(
                "plugin token response carried no token", status=response.status_code
            )
        ttl = data.get("expire_time")
        if not isinstance(ttl, int | float) or isinstance(ttl, bool) or ttl <= 0:
            ttl = DEFAULT_TOKEN_TTL_SECONDS
        self._token = token
        self._token_deadline = self._clock() + max(float(ttl) - TOKEN_MARGIN_SECONDS, 1.0)
        logger.info("meegle token: renewed, valid %ss", int(ttl))
        return token

    def _payload(self, response: httpx.Response, *, what: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            logger.error("meegle %s: non-JSON answer status=%s", what, response.status_code)
            raise MeegleApiError(
                f"Meegle answered {response.status_code} without a JSON body",
                status=response.status_code,
            )
        code = payload.get("err_code")
        msg = _str(payload.get("err_msg"))
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code", code)
            msg = _str(error.get("msg"), msg)
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            logger.error("meegle %s: err_code=%s status=%s", what, code, response.status_code)
            raise MeegleApiError(
                f"Meegle refused ({code}): {msg or 'no message'}",
                code=code,
                status=response.status_code,
            )
        if response.status_code >= 400:
            logger.error("meegle %s: status=%s", what, response.status_code)
            raise MeegleApiError(
                f"Meegle answered {response.status_code}: {msg or 'no message'}",
                status=response.status_code,
            )
        return payload

    def _call(self, method: str, path: str, *, json: Any = None, what: str) -> Any:
        headers = {
            "X-Plugin-Token": self._token_value(),
            "X-User-Key": self._settings.user_key,
        }
        try:
            response = self._http.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("meegle %s: transport failure (%s)", what, type(exc).__name__)
            raise MeegleApiError(f"could not reach Meegle ({what})") from exc
        return self._payload(response, what=what).get("data")

    # -- paths ---------------------------------------------------------------------------

    def _type(self, work_item_type: str | None) -> str:
        return work_item_type or self._settings.work_item_type

    def _item_path(
        self, work_item_id: int, suffix: str = "", *, work_item_type: str | None = None
    ) -> str:
        s = self._settings
        return (
            f"/open_api/{s.project_key}/work_item/{self._type(work_item_type)}"
            f"/{work_item_id}{suffix}"
        )

    # -- writes --------------------------------------------------------------------------

    def update_fields(self, work_item_id: int, pairs: Mapping[str, Any]) -> None:
        """Set field values by field key (select values, not labels — the resolver maps)."""
        body = {
            "update_fields": [
                {"field_key": key, "field_value": value} for key, value in pairs.items()
            ]
        }
        self._call("PUT", self._item_path(work_item_id), json=body, what="update_fields")

    def operate_node(
        self,
        work_item_id: int,
        node_id: str,
        *,
        action: NodeAction = "confirm",
        rollback_reason: str = "",
    ) -> None:
        s = self._settings
        path = (
            f"/open_api/{s.project_key}/workflow/{s.work_item_type}/{work_item_id}"
            f"/node/{node_id}/operate"
        )
        body: dict[str, Any] = {"action": action}
        if action == "rollback":
            body["rollback_reason"] = rollback_reason
        self._call("POST", path, json=body, what=f"operate_node:{action}")

    def comment(self, work_item_id: int, markdown: str) -> int | None:
        data = self._call(
            "POST",
            self._item_path(work_item_id, "/comment/create"),
            json={"content": markdown},
            what="comment",
        )
        return data if isinstance(data, int) and not isinstance(data, bool) else None

    # -- reads ---------------------------------------------------------------------------

    def workflow(
        self, work_item_id: int, *, work_item_type: str | None = None
    ) -> list[WorkflowNode]:
        data = self._call(
            "POST",
            self._item_path(work_item_id, "/workflow/query", work_item_type=work_item_type),
            json={},
            what="workflow",
        )
        nodes = data.get("workflow_nodes") if isinstance(data, dict) else None
        out: list[WorkflowNode] = []
        for raw in nodes or []:
            if not isinstance(raw, dict):
                continue
            node_id = _str(raw.get("id"))
            state_key = _str(raw.get("state_key"), node_id)
            status = raw.get("status")
            if not isinstance(status, int) or isinstance(status, bool):
                status = None
            out.append(
                WorkflowNode(
                    id=node_id or state_key,
                    state_key=state_key,
                    name=_str(raw.get("name")),
                    status=status,
                )
            )
        return out

    def query(
        self, work_item_ids: Iterable[int], *, work_item_type: str | None = None
    ) -> list[WorkItem]:
        s = self._settings
        ids = [int(i) for i in work_item_ids]
        data = self._call(
            "POST",
            f"/open_api/{s.project_key}/work_item/{self._type(work_item_type)}/query",
            json={"work_item_ids": ids, "expand": {"need_multi_text": True}},
            what="query",
        )
        items: list[WorkItem] = []
        for raw in data if isinstance(data, list) else []:
            if not isinstance(raw, dict):
                continue
            item_id = raw.get("id")
            if not isinstance(item_id, int) or isinstance(item_id, bool):
                continue
            fields: dict[str, Any] = {}
            for pair in raw.get("fields") or []:
                if isinstance(pair, dict) and isinstance(pair.get("field_key"), str):
                    fields[pair["field_key"]] = pair.get("field_value")
            # `expand.need_multi_text` returns rich-text fields separately, with `doc_text`.
            for pair in raw.get("multi_texts") or []:
                if isinstance(pair, dict) and isinstance(pair.get("field_key"), str):
                    fields[pair["field_key"]] = pair.get("field_value")
            nodes = [
                node
                for node in raw.get("current_nodes") or []
                if isinstance(node, dict) and isinstance(node.get("id"), str)
            ]
            status = raw.get("work_item_status")
            status_key = _str(status.get("state_key")) if isinstance(status, dict) else ""
            items.append(
                WorkItem(
                    id=item_id,
                    name=_str(raw.get("name")),
                    fields=fields,
                    current_nodes=tuple(_str(node.get("id")) for node in nodes),
                    current_node_names=tuple(_str(node.get("name")) for node in nodes),
                    work_item_type_key=_str(raw.get("work_item_type_key")),
                    status_key=status_key,
                )
            )
        return items

    def fields_meta(self, *, work_item_type: str | None = None) -> list[FieldMeta]:
        s = self._settings
        data = self._call(
            "POST",
            f"/open_api/{s.project_key}/field/all",
            json={"work_item_type_key": self._type(work_item_type)},
            what="fields_meta",
        )
        out: list[FieldMeta] = []
        for raw in data if isinstance(data, list) else []:
            if not isinstance(raw, dict) or not isinstance(raw.get("field_key"), str):
                continue
            options = tuple(
                (_str(opt.get("label")), _str(opt.get("value")))
                for opt in raw.get("options") or []
                if isinstance(opt, dict)
            )
            out.append(
                FieldMeta(
                    key=raw["field_key"],
                    name=_str(raw.get("field_name")) or _str(raw.get("field_alias")),
                    type_key=_str(raw.get("field_type_key")),
                    options=options,
                )
            )
        return out

    def space_simple_name(self) -> str:
        """The space's `simple_name` (the first path segment of every Meegle link), or ""
        when Meegle does not return it — the notifier then links without it."""
        s = self._settings
        data = self._call(
            "POST",
            "/open_api/projects/detail",
            json={"project_keys": [s.project_key]},
            what="space_simple_name",
        )
        if isinstance(data, dict):
            spaces = data.values()
        elif isinstance(data, list):
            spaces = data
        else:
            spaces = []
        for space in spaces:
            if isinstance(space, dict) and space.get("project_key") == s.project_key:
                return _str(space.get("simple_name"))
        return ""
