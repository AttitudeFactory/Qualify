"""Ticket changes in the Qualify space → one line in the Lark group (plan §3bis).

The second thing the Meegle engine does, next to onboarding: when a Feature / Issue / Task
of the space changes, tell the team in `Qualify-devs`. Meegle itself notifies nobody by
default (only @mentions and the rules an admin configures), and the Free plan caps native
automation rules at 10 per space — this handler is the generic path those rules cannot be:
one message for ANY field change, naming who, what changed (field: before → after), the
item and its link. The native rules remain the right tool for the few cases they cover
cheaply (created, status changed); the plan documents the split and the budget.

What is trusted, and from where. The item's NAME, TYPE and STATUS are re-read through the
authenticated Open API (`MeegleClient.query`), never taken from the event: the event
signature does not cover the body (`envelope.py`), and reading the item also proves it
exists in the configured space. The DELTA (who, before → after) exists only in the event
(`user_info`, `field_info`, `node_info`); the alternative — the operation-records endpoint
— costs one more API call per event against a 500/day budget for the same strings. So the
delta is rendered from the event, with the field metadata of the item's type (names,
option labels) resolved through `SchemaResolver`, one resolver per type, cached.

Cost per notice: one Open API call (`query`) — `fields_meta` and the space's
`simple_name` are read once per type / per process. One Lark request.

The Lark side is a custom bot webhook (`QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL`), `msg_type`
`text` only — Lark auto-links URLs, and a plain text survives any later move to another
chat. Lark answers HTTP 200 even when it rejects a message, so the JSON `code` is checked:
0 is delivered; a rejection (keyword rule, malformed body) is permanent and settles the
event with `lark_rejected:<code>`; a transport failure, a 5xx or the rate limit (11232)
raises `LarkDeliveryError` so the queue retries with backoff. The webhook URL is a secret
on Lark's side (anyone holding it can post): it never reaches a log line.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from qualify_api.meegle.client import FieldMeta, MeegleApiError, MeegleClient, WorkItem
from qualify_api.meegle.envelope import (
    EVENT_FIELD_MODIFIED,
    EVENT_NODE_COMPLETED,
    EVENT_NODE_ROLLED_BACK,
    EVENT_STATUS_CHANGED,
    EVENT_WORK_ITEM_CREATED,
    EVENT_WORK_ITEM_TERMINATED,
)
from qualify_api.meegle.events import FieldChange, MeegleEvent, NodeInfo
from qualify_api.meegle.onboarding import WorkItemNotFound
from qualify_api.meegle.schema import MeegleSchemaError, SchemaResolver

logger = logging.getLogger("qualify_api.meegle.tickets")

# Work item types of the space the notifier covers, and how a notice names them.
TICKET_TYPE_LABELS: Mapping[str, str] = {"story": "Feature", "issue": "Issue", "sub_task": "Tarea"}
DEFAULT_TICKET_TYPES: frozenset[str] = frozenset(TICKET_TYPE_LABELS)

# The status field of every work item type; its options are the status names.
STATUS_FIELD_KEY = "work_item_status"

# Lark custom bot: rate limited → retry later; anything else non-zero is a rejection.
LARK_RATE_LIMITED = 11232
_LARK_TIMEOUT_SECONDS = 5.0
_MAX_VALUE_CHARS = 80
_MAX_LINES = 12

NOTICE_SENT = "sent"
LARK_REJECTED = "lark_rejected"


class LarkDeliveryError(RuntimeError):
    """Lark could not be reached, answered 5xx or rate-limited the bot — retryable."""


class LarkPoster(Protocol):
    def post(self, text: str) -> int:
        """Send one text message. Returns Lark's `code` (0 = delivered). Raises
        `LarkDeliveryError` for a transient failure."""
        ...


class LarkWebhookPoster:
    def __init__(
        self,
        url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = _LARK_TIMEOUT_SECONDS,
    ) -> None:
        self._url = url
        self._transport = transport
        self._timeout = timeout

    def post(self, text: str) -> int:
        payload = {"msg_type": "text", "content": {"text": text}}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(self._url, json=payload)
        except httpx.HTTPError as exc:
            # Type only: a transport error's text can carry the webhook URL.
            logger.error("lark notice: transport failure (%s)", type(exc).__name__)
            raise LarkDeliveryError("could not reach the Lark webhook") from exc
        if response.status_code >= 500:
            logger.error("lark notice: HTTP %d", response.status_code)
            raise LarkDeliveryError(f"Lark answered {response.status_code}")
        if response.status_code >= 400:
            logger.error("lark notice: HTTP %d (rejected)", response.status_code)
            return response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, int) or isinstance(code, bool):
            return 0
        if code == LARK_RATE_LIMITED:
            logger.warning("lark notice: rate limited (%d)", code)
            raise LarkDeliveryError("Lark rate-limited the bot")
        if code != 0:
            logger.error("lark notice: rejected code=%d", code)
        return code


@dataclass(frozen=True)
class TicketNotice:
    """What the group is told, as data — formatted by `as_text`, pinned by tests."""

    actor: str
    verb: str
    type_label: str
    name: str
    lines: tuple[str, ...] = ()
    link: str = ""

    def as_text(self) -> str:
        out = [f"🎫 {self.actor} {self.verb} · {self.type_label} «{self.name}»"]
        out.extend(self.lines)
        if self.link:
            out.append(self.link)
        return "\n".join(out)


@dataclass
class _TypeSchema:
    """`SchemaResolver` bound to one work item type of the space (the resolver's source
    protocol has no type argument: the onboarding engine lives on a single type)."""

    client: MeegleClient
    work_item_type: str
    resolver: SchemaResolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = SchemaResolver(self)

    def fields_meta(self) -> list[FieldMeta]:
        return self.client.fields_meta(work_item_type=self.work_item_type)

    def workflow(self, work_item_id: int):  # noqa: ANN202 — SchemaSource protocol
        return self.client.workflow(work_item_id, work_item_type=self.work_item_type)


def _shorten(text: str, limit: int = _MAX_VALUE_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _render_value(meta: FieldMeta | None, raw: str | None) -> str:
    """A `field_info` value for humans: option labels for selects, joined lists, `—` for
    empty. Meegle sends everything as a string, lists as JSON text."""
    if raw is None or raw == "" or raw == "[]":
        return "—"
    values: list[Any]
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = raw
    if isinstance(parsed, list):
        values = parsed
    elif isinstance(parsed, dict):
        # e.g. the 1005 `aborted` payload `{"isAborted": true, "reason": "…"}`
        reason = parsed.get("reason")
        values = [reason] if isinstance(reason, str) and reason else [raw]
    else:
        values = [parsed]
    labels: list[str] = []
    for value in values:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if isinstance(value, dict):
            text = str(value.get("name") or value.get("label") or value.get("user_key") or text)
        if meta is not None and meta.options:
            for label, option_value in meta.options:
                if option_value == text:
                    text = label
                    break
        labels.append(text)
    return _shorten(", ".join(labels))


class TicketNotifier:
    """Build and post one notice per event. Synchronous (httpx): the handler runs it in a
    worker thread, like the onboarding engine."""

    def __init__(
        self,
        client: MeegleClient,
        poster: LarkPoster,
        *,
        web_url: str,
        type_labels: Mapping[str, str] = TICKET_TYPE_LABELS,
    ) -> None:
        self._client = client
        self._poster = poster
        self._web_url = web_url.rstrip("/")
        self._type_labels = dict(type_labels)
        self._lock = threading.Lock()
        self._schemas: dict[str, _TypeSchema] = {}
        self._simple_name: str | None = None

    # -- cached lookups ------------------------------------------------------------------

    def _schema(self, work_item_type: str) -> _TypeSchema:
        with self._lock:
            schema = self._schemas.get(work_item_type)
            if schema is None:
                schema = _TypeSchema(self._client, work_item_type)
                self._schemas[work_item_type] = schema
            return schema

    def _space_simple_name(self) -> str:
        with self._lock:
            if self._simple_name is None:
                try:
                    self._simple_name = self._client.space_simple_name()
                except MeegleApiError as exc:
                    logger.warning("meegle space simple_name unavailable (%s)", exc.code)
                    return ""
            return self._simple_name

    def link(self, work_item_type: str, work_item_id: int) -> str:
        simple_name = self._space_simple_name()
        if not simple_name:
            return ""
        return f"{self._web_url}/{simple_name}/{work_item_type}/detail/{work_item_id}"

    # -- rendering -----------------------------------------------------------------------

    def _field_meta(self, schema: _TypeSchema, key: str) -> FieldMeta | None:
        try:
            return schema.resolver.field(key)
        except (MeegleSchemaError, MeegleApiError):
            return None

    def _field_lines(self, schema: _TypeSchema, changes: list[FieldChange]) -> list[str]:
        lines: list[str] = []
        for change in changes:
            if not change.field_key or change.before_field_value == change.after_field_value:
                continue
            meta = self._field_meta(schema, change.field_key)
            label = (meta.name if meta is not None and meta.name else "") or change.field_key
            before = _render_value(meta, change.before_field_value)
            after = _render_value(meta, change.after_field_value)
            lines.append(f"{label}: {before} → {after}")
        return lines

    def _status_label(self, schema: _TypeSchema, state_key: str) -> str:
        meta = self._field_meta(schema, STATUS_FIELD_KEY)
        return _render_value(meta, state_key) if state_key else "—"

    def _node_names(self, schema: _TypeSchema, work_item_id: int, keys: list[str]) -> list[str]:
        names: list[str] = []
        for key in keys:
            try:
                names.append(schema.resolver.node_name(work_item_id, key) or key)
            except MeegleApiError:
                names.append(key)
        return names

    def _node_verb(
        self, verb: str, schema: _TypeSchema, work_item_id: int, node_info: NodeInfo | None
    ) -> str:
        keys = (node_info.update_nodes if node_info else None) or []
        names = self._node_names(schema, work_item_id, keys)
        if not names:
            return f"{verb} un nodo"
        return f"{verb} el nodo " + ", ".join(f"«{n}»" for n in names)

    def describe(self, event: MeegleEvent, item: WorkItem) -> TicketNotice:
        data = event.data
        work_item_type = data.work_item_type_key or item.work_item_type_key
        schema = self._schema(work_item_type)
        code = data.event_type
        lines: list[str] = []
        if code == EVENT_WORK_ITEM_CREATED:
            verb = "creó"
            if item.status_key:
                lines.append(f"Estado: {self._status_label(schema, item.status_key)}")
            elif item.current_node_names:
                lines.append(f"Nodo: {', '.join(n for n in item.current_node_names if n)}")
        elif code == EVENT_FIELD_MODIFIED:
            verb = "modificó"
            lines.extend(self._field_lines(schema, data.field_info))
        elif code == EVENT_STATUS_CHANGED:
            verb = "cambió el estado"
            status_changes = [c for c in data.field_info if c.field_key == STATUS_FIELD_KEY]
            if status_changes:
                lines.extend(self._field_lines(schema, status_changes))
            else:
                lines.append(f"Estado → {self._status_label(schema, item.status_key)}")
            other = [c for c in data.field_info if c.field_key != STATUS_FIELD_KEY]
            lines.extend(self._field_lines(schema, other))
        elif code == EVENT_NODE_COMPLETED:
            verb = self._node_verb("completó", schema, item.id, data.node_info)
        elif code == EVENT_NODE_ROLLED_BACK:
            verb = self._node_verb("revirtió", schema, item.id, data.node_info)
            reason = (data.node_info.reason if data.node_info else None) or ""
            if reason.strip():
                lines.append(f"Motivo: {_shorten(reason)}")
        elif code == EVENT_WORK_ITEM_TERMINATED:
            verb = "terminó"
            if data.reason and data.reason.strip():
                lines.append(f"Motivo: {_shorten(data.reason)}")
        else:
            verb = f"evento {code}"
        event_name = data.work_item_info[0].work_item_name if data.work_item_info else ""
        return TicketNotice(
            actor=event.actor,
            verb=verb,
            type_label=self._type_labels.get(work_item_type, work_item_type),
            name=item.name or event_name,
            lines=tuple(lines[:_MAX_LINES]),
            link=self.link(work_item_type, item.id),
        )

    # -- the use case --------------------------------------------------------------------

    def notify(self, event: MeegleEvent) -> str:
        """Re-read the item, describe the change, post it. Returns `NOTICE_SENT` or
        `lark_rejected:<code>`. Raises `WorkItemNotFound` when the item is not in the
        space, `LarkDeliveryError` / `MeegleApiError` for what the queue should retry."""
        work_item_id = event.work_item_id
        work_item_type = event.data.work_item_type_key
        if work_item_id is None or not work_item_type:
            raise WorkItemNotFound(str(work_item_id))
        items = self._client.query([work_item_id], work_item_type=work_item_type)
        if not items:
            raise WorkItemNotFound(str(work_item_id))
        notice = self.describe(event, items[0])
        code = self._poster.post(notice.as_text())
        if code != 0:
            return f"{LARK_REJECTED}:{code}"
        logger.info(
            "meegle ticket notice sent type=%s item=%s event=%s",
            work_item_type,
            work_item_id,
            event.data.event_type,
        )
        return NOTICE_SENT
