"""An approved message sent from an expired chat (m-24848535, WHATSAPP-2; migration 0087).

Once 24 hours have passed since a person's last message, WhatsApp only delivers an
approved template (`window.py`). This module lets the owner pick one IN THE CHAT and send
it: `options` says which templates this person may receive, `send` queues the chosen one
as a `template_reply` row of `whatsapp_outbox`, which the WA-08 sender drains. Nothing is
sent inline and nothing is sent without the owner pressing «Enviar» (N13: assisted, never
autonomous) — `send` is only ever called from that button.

## Who may receive what (founder decision 2026-10-23, epic §2b-4)

| The person… | Follow-up (`utility`) | Promotion (`marketing`) |
|---|---|---|
| wrote before (`threads.last_inbound_at` set) | yes | **only with an active opt-in** |
| holds an explicit, active opt-in (`whatsapp_opt_ins`) | yes | yes |
| never wrote and holds no opt-in | no | no |

Authentication templates are never offered here (one-time codes are not a conversation).
The origin of the permission is a RULE evaluated now, not a stored column: "wrote before"
is the thread's inbound history, "explicit" is `OptInService.is_opted_in`. The server
enforces it in `send` (`PromotionNeedsConsent`) whatever the screen offered, and the
sender re-checks the opt-in of a promotion at send time (`outbox.ClaimedOutboxItem.
needs_opt_in`), so a STOP that arrives after «Enviar» still stops it.

## «Pedirle que acepte»

A person who wrote but did not accept promotions can be ASKED, with an approved follow-up
template whose name starts with `CONSENT_REQUEST_PREFIX` (`pedir_permiso…`). Creating that
template is out of scope (the story says so): when none is approved, `consent_request` is
`None` and the screen shows no button. Choosing it still goes through `send` and the
owner's «Enviar». Recording the person's «sí» as an opt-in is not this module's job (the
menu's collect node and the opt-in import already do it).

## Variables

A template body may carry variables (`{{1}}` positional, or `{{nombre}}` named — Meta's
two parameter formats). `options` lists them per template and pre-fills the one that
asks for the person's name when the chat knows it (`NAME_KEYS`, or `{{1}}` of the body);
the owner fills the rest. `send` builds the `/messages` components SERVER-SIDE from the
stored template and the values — never from a body sent by the browser — and refuses a
missing value (`MissingValues`). Templates the chat cannot fill (a header with an image,
video or document; a button with a variable link) are left out of the list: the campaign
wizard has the same limits (`whatsapp_templates_vm.wizard_block`).

## Idempotency

`send` takes a `request_key` (the screen makes one per «Enviar» intent). The outbox
enqueue is `INSERT … ON CONFLICT (tenant_id, request_key) DO NOTHING`, so a double tap or
a retried request returns the row already queued instead of a second message.

## Price

Meta charges each delivered template by country and category, but the rate table
(`pricing.py`) is still a placeholder for every country and has no rate at all for
Venezuela (+58) or Uruguay (+598). This module therefore shows NO price; a price on this
screen waits for the real rate card.

Logs carry ids, categories and outcomes — never a phone number or a message text.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_api.whatsapp.chats import ChatService, ThreadNotFound, ThreadSummary
from qualify_api.whatsapp.client import build_template_body
from qualify_api.whatsapp.outbox import KIND_TEMPLATE_REPLY, OutboxRepository, recipient_e164
from qualify_api.whatsapp.templates import TemplateRecord, TemplateRepository

logger = logging.getLogger("qualify_api.whatsapp.template_reply")

CATEGORY_UTILITY: Final = "utility"
CATEGORY_MARKETING: Final = "marketing"
#: The approved follow-up template that asks a person to accept promotions.
CONSENT_REQUEST_PREFIX: Final = "pedir_permiso"
#: Variable names that mean "the person's name" (named templates).
NAME_KEYS: Final = frozenset({"nombre", "name", "cliente", "first_name", "nombre_cliente"})
MAX_VALUE_CHARS: Final = 1024
MAX_REQUEST_KEY_CHARS: Final = 128

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
_SENDABLE_BUTTONS: Final = frozenset({"QUICK_REPLY", "URL", "PHONE_NUMBER"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ======================================================================================
# Permission
# ======================================================================================


class Permission(StrEnum):
    """What the person allowed, decided now (module docstring table)."""

    NONE = "none"
    CHAT = "chat"  # wrote before: follow-ups only
    EXPLICIT = "explicit"  # accepted to receive messages: follow-ups and promotions


def permission_for(*, has_written: bool, opted_in: bool) -> Permission:
    if opted_in:
        return Permission.EXPLICIT
    if has_written:
        return Permission.CHAT
    return Permission.NONE


def allowed_categories(permission: Permission) -> frozenset[str]:
    if permission is Permission.EXPLICIT:
        return frozenset({CATEGORY_UTILITY, CATEGORY_MARKETING})
    if permission is Permission.CHAT:
        return frozenset({CATEGORY_UTILITY})
    return frozenset()


def is_consent_request(template: TemplateRecord) -> bool:
    return template.category == CATEGORY_UTILITY and template.name.startswith(
        CONSENT_REQUEST_PREFIX
    )


# ======================================================================================
# Template components: variables, fillability, preview, send components
# ======================================================================================


@dataclass(frozen=True)
class TemplateVariable:
    """One value a send must carry. `component` is `header`/`body`; `key` is the
    positional number (`"1"`) or the parameter name (`"nombre"`)."""

    component: str
    key: str
    named: bool

    @property
    def id(self) -> str:
        return f"{self.component}:{self.key}"


def _component(components: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any] | None:
    for component in components:
        if isinstance(component, Mapping) and str(component.get("type", "")).upper() == kind:
            return component
    return None


def _text(component: Mapping[str, Any] | None) -> str:
    value = component.get("text") if component is not None else None
    return value if isinstance(value, str) else ""


def _buttons(components: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    block = _component(components, "BUTTONS")
    raw = block.get("buttons") if block else None
    return [b for b in raw if isinstance(b, Mapping)] if isinstance(raw, list) else []


def unfillable_reason(components: Sequence[Mapping[str, Any]]) -> str:
    """Why the chat cannot fill this template ("" when it can). Internal wording (logs
    and tests), never shown to the owner: an unfillable template is simply not listed."""
    header = _component(components, "HEADER")
    if header is not None and str(header.get("format", "TEXT")).upper() != "TEXT":
        return "media_header"
    for button in _buttons(components):
        kind = str(button.get("type", "")).upper()
        if kind not in _SENDABLE_BUTTONS:
            return "button_kind"
        url = button.get("url")
        if kind == "URL" and isinstance(url, str) and "{{" in url:
            return "button_variable"
    return ""


def template_variables(components: Sequence[Mapping[str, Any]]) -> list[TemplateVariable]:
    """Header (TEXT) and body variables, in send order: positional by number, named by
    first appearance."""
    out: list[TemplateVariable] = []
    for kind in ("HEADER", "BODY"):
        component = _component(components, kind)
        if component is None:
            continue
        if kind == "HEADER" and str(component.get("format", "TEXT")).upper() != "TEXT":
            continue
        keys: list[str] = []
        for match in _PLACEHOLDER.finditer(_text(component)):
            if match.group(1) not in keys:
                keys.append(match.group(1))
        if keys and all(k.isdigit() for k in keys):
            keys.sort(key=int)
            out.extend(TemplateVariable(kind.lower(), k, False) for k in keys)
        else:
            out.extend(TemplateVariable(kind.lower(), k, True) for k in keys)
    return out


def _named_examples(raw: Any, kind: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, Mapping):
            name, example = item.get("param_name"), item.get("example")
            if isinstance(name, str) and isinstance(example, str) and example.strip():
                out[f"{kind}:{name}"] = example.strip()
    return out


def variable_examples(components: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """The example Meta stored for each variable (`id` → text), so the screen can show
    the owner what a valid value looks like. Missing or malformed examples are skipped:
    Meta only requires them at review time and older templates may lack them."""
    out: dict[str, str] = {}
    for kind in ("HEADER", "BODY"):
        component = _component(components, kind)
        example = component.get("example") if component is not None else None
        if not isinstance(example, Mapping):
            continue
        lower = kind.lower()
        out.update(_named_examples(example.get(f"{lower}_text_named_params"), lower))
        positional = example.get(f"{lower}_text")
        if kind == "BODY" and isinstance(positional, list) and positional:
            positional = positional[0]
        if isinstance(positional, list):
            for index, value in enumerate(positional, start=1):
                if isinstance(value, str) and value.strip():
                    out[f"{lower}:{index}"] = value.strip()
    return out


def _first_name(contact_name: str | None) -> str:
    name = (contact_name or "").strip()
    return name.split()[0] if name else ""


def prefill(variables: Sequence[TemplateVariable], contact_name: str | None) -> dict[str, str]:
    """The person's first name into the variable that asks for it: a named one in
    `NAME_KEYS`, else the body's `{{1}}`. Nothing when the chat has no name."""
    name = _first_name(contact_name)
    if not name:
        return {}
    named = [v for v in variables if v.named and v.key.lower() in NAME_KEYS]
    if named:
        return {v.id: name for v in named}
    first = next((v for v in variables if v.component == "body" and v.key == "1"), None)
    return {first.id: name} if first else {}


def _clean(values: Mapping[str, str]) -> dict[str, str]:
    return {
        str(k): str(v).strip()[:MAX_VALUE_CHARS]
        for k, v in values.items()
        if isinstance(v, str) and v.strip()
    }


def render_preview(components: Sequence[Mapping[str, Any]], values: Mapping[str, str]) -> str:
    """What the person reads: header, body and footer with the values in place (an
    unfilled variable keeps its `{{…}}`; the screen passes a «[label]» per empty value
    instead, so the owner never sees the raw placeholder)."""
    filled = _clean(values)
    parts: list[str] = []
    for kind in ("HEADER", "BODY", "FOOTER"):
        component = _component(components, kind)
        if component is None:
            continue
        if kind == "HEADER" and str(component.get("format", "TEXT")).upper() != "TEXT":
            continue
        lower = kind.lower()
        text = _PLACEHOLDER.sub(
            lambda m, lower=lower: filled.get(f"{lower}:{m.group(1)}", m.group(0)),
            _text(component),
        ).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def send_components(
    variables: Sequence[TemplateVariable], values: Mapping[str, str]
) -> list[dict[str, Any]]:
    """The `template.components` of the send (`client.build_template_body` passes them
    through). Raises `MissingValues` naming the variable ids left empty."""
    filled = _clean(values)
    missing = [v.id for v in variables if v.id not in filled]
    if missing:
        raise MissingValues(missing)
    out: list[dict[str, Any]] = []
    for component in ("header", "body"):
        params: list[dict[str, Any]] = []
        for variable in variables:
            if variable.component != component:
                continue
            param: dict[str, Any] = {"type": "text", "text": filled[variable.id]}
            if variable.named:
                param["parameter_name"] = variable.key
            params.append(param)
        if params:
            out.append({"type": component, "parameters": params})
    return out


# ======================================================================================
# Errors
# ======================================================================================


class TemplateReplyError(Exception):
    """Base for the refusals of `send` (the screen maps each to a message)."""


class TemplateNotAvailable(TemplateReplyError):
    """Not this tenant's, not this number's account, not approved, an authentication
    template, or one the chat cannot fill."""


class PromotionNeedsConsent(TemplateReplyError):
    """A promotion to a person without an explicit, active opt-in (§2b-4)."""


class NoPermission(TemplateReplyError):
    """The person never wrote and holds no opt-in: nothing may be sent from this chat."""


class MissingValues(TemplateReplyError, ValueError):
    def __init__(self, variable_ids: Sequence[str]) -> None:
        super().__init__(f"missing template values: {', '.join(variable_ids)}")
        self.variable_ids = list(variable_ids)


# ======================================================================================
# Read shapes
# ======================================================================================


@dataclass(frozen=True)
class TemplateOption:
    template_id: UUID
    name: str
    language: str
    category: str
    #: The template's text (header, body, footer) with the pre-filled values in place.
    preview: str
    variables: list[TemplateVariable] = field(default_factory=list)
    prefill: dict[str, str] = field(default_factory=dict)
    is_consent_request: bool = False
    #: The stored components, so the screen can re-render `preview` as values change.
    components: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TemplateReplyOptions:
    thread_id: UUID
    permission: Permission
    #: Templates this person may receive now, follow-ups first.
    options: list[TemplateOption]
    #: The person wrote but did not accept promotions: the screen says why none is listed.
    promotions_blocked: bool
    #: The approved follow-up that asks to accept promotions, when one exists.
    consent_request: TemplateOption | None
    #: No approved follow-up at all: the screen links to creating one.
    has_followups: bool


class OptInChecker(Protocol):
    def is_opted_in(self, *, tenant_id: UUID, phone: str) -> bool: ...


# ======================================================================================
# Service
# ======================================================================================


class TemplateReplyService:
    """Every method takes the caller's `tenant_id` (RLS bounds the repositories) and
    raises `ThreadNotFound` for a thread that tenant cannot see."""

    def __init__(
        self,
        chats: ChatService,
        templates: TemplateRepository,
        opt_ins: OptInChecker,
        outbox: OutboxRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._chats = chats
        self._templates = templates
        self._opt_ins = opt_ins
        self._outbox = outbox
        self._clock = clock

    def _permission(self, tenant_id: UUID, thread: ThreadSummary) -> Permission:
        opted_in = self._opt_ins.is_opted_in(
            tenant_id=tenant_id, phone=recipient_e164(thread.wa_id)
        )
        return permission_for(has_written=thread.last_inbound_at is not None, opted_in=opted_in)

    def _sendable(self, tenant_id: UUID, thread: ThreadSummary) -> list[TemplateRecord]:
        """Approved, fillable, utility/marketing templates of the thread's own account."""
        waba = self._templates.waba_for_connection(
            tenant_id=tenant_id, connection_id=thread.connection_id
        )
        if waba is None:
            return []
        return [
            t
            for t in self._templates.list(tenant_id=tenant_id, waba_id=waba.waba_id)
            if t.is_sendable
            and t.category in (CATEGORY_UTILITY, CATEGORY_MARKETING)
            and not unfillable_reason(t.components)
        ]

    @staticmethod
    def _option(template: TemplateRecord, contact_name: str | None) -> TemplateOption:
        variables = template_variables(template.components)
        values = prefill(variables, contact_name)
        return TemplateOption(
            template_id=template.id,
            name=template.name,
            language=template.language,
            category=template.category,
            preview=render_preview(template.components, values),
            variables=variables,
            prefill=values,
            is_consent_request=is_consent_request(template),
            components=[dict(c) for c in template.components if isinstance(c, Mapping)],
        )

    def options(self, tenant_id: UUID, thread_id: UUID) -> TemplateReplyOptions:
        thread = self._chats.get_thread_summary(tenant_id, thread_id)
        permission = self._permission(tenant_id, thread)
        allowed = allowed_categories(permission)
        templates = self._sendable(tenant_id, thread)
        listed = sorted(
            (t for t in templates if t.category in allowed),
            key=lambda t: (t.category != CATEGORY_UTILITY, t.name, t.language),
        )
        options = [self._option(t, thread.contact_name) for t in listed]
        promotions_blocked = permission is Permission.CHAT
        consent = (
            next((o for o in options if o.is_consent_request), None) if promotions_blocked else None
        )
        return TemplateReplyOptions(
            thread_id=thread_id,
            permission=permission,
            options=options,
            promotions_blocked=promotions_blocked,
            consent_request=consent,
            has_followups=any(o.category == CATEGORY_UTILITY for o in options),
        )

    def send(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        *,
        template_id: UUID,
        values: Mapping[str, str],
        request_key: str,
    ) -> UUID:
        """Queue the chosen template for this person; returns the `whatsapp_outbox` id
        (the SAME id for a repeated `request_key`). Every check runs before anything is
        written: the thread, the template (this account, approved, fillable), the
        permission, the values. Then the menu automation is paused (a person took the
        chat, as with any reply) and the row is queued."""
        key = (request_key or "").strip()
        if not key or len(key) > MAX_REQUEST_KEY_CHARS:
            raise ValueError("request_key must be 1..128 characters")
        thread = self._chats.get_thread_summary(tenant_id, thread_id)
        template = self._templates.get(tenant_id=tenant_id, template_id=template_id)
        sendable = {t.id for t in self._sendable(tenant_id, thread)}
        if template is None or template.id not in sendable:
            raise TemplateNotAvailable(str(template_id))
        permission = self._permission(tenant_id, thread)
        if template.category not in allowed_categories(permission):
            logger.info(
                "whatsapp.template_reply.refused thread_id=%s category=%s permission=%s",
                thread_id,
                template.category,
                permission.value,
            )
            if permission is Permission.NONE:
                raise NoPermission(str(thread_id))
            raise PromotionNeedsConsent(str(thread_id))
        variables = template_variables(template.components)
        components = send_components(variables, values)
        payload = build_template_body(thread.wa_id, template.name, template.language, components)
        preview = render_preview(template.components, values)
        self._chats.takeover(tenant_id, thread_id, user_id)
        outbox_id = self._outbox.enqueue(
            tenant_id=tenant_id,
            connection_id=thread.connection_id,
            thread_id=thread_id,
            kind=KIND_TEMPLATE_REPLY,
            payload=payload,
            created_by_user_id=user_id,
            request_key=key,
            template_id=template.id,
            template_category=template.category,
            preview_text=preview or None,
        )
        logger.info(
            "whatsapp.template_reply.queued thread_id=%s outbox_id=%s category=%s",
            thread_id,
            outbox_id,
            template.category,
        )
        return outbox_id


def production_template_reply_service() -> TemplateReplyService:
    """Postgres repositories under `tenant_session` (the `qualify_app` role)."""
    from qualify_api.whatsapp.chats import production_chat_service  # noqa: PLC0415
    from qualify_api.whatsapp.optins import (  # noqa: PLC0415
        OptInService,
        PostgresOptInRepository,
    )
    from qualify_api.whatsapp.outbox import PostgresOutboxRepository  # noqa: PLC0415
    from qualify_api.whatsapp.templates import PostgresTemplateRepository  # noqa: PLC0415

    return TemplateReplyService(
        production_chat_service(),
        PostgresTemplateRepository(),
        OptInService(PostgresOptInRepository()),
        PostgresOutboxRepository(),
    )


__all__ = [
    "CONSENT_REQUEST_PREFIX",
    "MissingValues",
    "NoPermission",
    "Permission",
    "PromotionNeedsConsent",
    "TemplateNotAvailable",
    "TemplateOption",
    "TemplateReplyError",
    "TemplateReplyOptions",
    "TemplateReplyService",
    "TemplateVariable",
    "ThreadNotFound",
    "allowed_categories",
    "permission_for",
    "prefill",
    "production_template_reply_service",
    "render_preview",
    "send_components",
    "template_variables",
    "unfillable_reason",
    "variable_examples",
]
