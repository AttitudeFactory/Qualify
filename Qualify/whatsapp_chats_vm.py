"""View-models for the Chats tab of `/whatsapp` (WA-11, QUA-210) — the security boundary.

Same discipline as `whatsapp_vm.py`: `WhatsAppChatsState` holds only the frozen
dataclasses below, every instant is PRE-FORMATTED here in the tenant's zone (the browser
never receives a raw `datetime`), and no field can carry a token, a ciphertext or a key
(`test_whatsapp_chats_vm_has_no_credential_fields`). States are TONES (`ok`/`warn`/
`error`/`info`/`neutral`, docs/design-system.md §3.2), never a Radix colour.

Inputs are the backend's own read shapes — `ThreadSummary` / `MessageRecord` from
`qualify_api.whatsapp.chats` and `OrderSummary` from `qualify_api.whatsapp.orders` — taken
by duck type, so this module imports neither SQLAlchemy nor Reflex and every mapping is
asserted by plain unit tests (`test_whatsapp_chats.py`). The 24 h window itself is NOT
re-derived here: the service already computed `window.open` / `window.closes_at` through
`window.window_state`; this module only words it.

**Inbound media (0061, `chats.py` "Media").** A message whose record says `has_media`
(Meta gave a `media_id`) renders a media CONTROL keyed by its WhatsApp type — image and
sticker → «Ver imagen» (thumbnail + lightbox), audio → «Escuchar audio» (an `<audio>`
player), video → «Ver video», document → «Descargar …» — and nothing is fetched until
the person clicks it. The state then asks the in-process media locator for a URL and
hands this module a `MediaResolution` per message: the URL while it is fresh
(`MEDIA_URL_TTL`, under the public-media token's 15 minutes), or the outcome, which maps
to a TONE (`media_expired` → `neutral`, `media_unavailable` → `warn` + retry,
`media_not_captured` → the old neutral chip). A text-less inbound message WITHOUT
`has_media` is either a non-file kind (location, contact…, worded by kind) or a file that
arrived before capture existed (`MEDIA_NOT_CAPTURED`).
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from typing import Any, Protocol

from .ad_message_vm import ad_origin_href, ad_origin_label
from .planner_vm import time_label_12h

# ======================================================================================
# Copy and limits
# ======================================================================================

#: Meta's limits, mirrored for UI validation only — the client builders
#: (`qualify_api.whatsapp.client`) stay the authority and re-check on send.
MAX_TEXT_CHARS = 4096
MAX_BUTTONS = 3
MAX_BUTTON_TITLE_CHARS = 20
MAX_BUTTONS_BODY_CHARS = 1024
MAX_CAPTION_CHARS = 1024

#: The newest page of a conversation, and of «cargar anteriores».
MESSAGES_PAGE = 50
#: The thread list: one number's conversations, newest activity first.
THREADS_LIMIT = 200

MEDIA_NOT_CAPTURED = "[foto, audio o archivo — no se guardó una copia para verlo aquí]"

# -- inbound media (0061) ----------------------------------------------------------------

#: The UI controls a media message can render as ("" = no control).
MEDIA_IMAGE = "image"
MEDIA_AUDIO = "audio"
MEDIA_VIDEO = "video"
MEDIA_DOCUMENT = "document"
#: WhatsApp message `type` → control. Anything else that still carries a `media_id` is
#: offered as a download.
_MEDIA_CONTROLS: dict[str, str] = {
    "image": MEDIA_IMAGE,
    "sticker": MEDIA_IMAGE,
    "audio": MEDIA_AUDIO,
    "voice": MEDIA_AUDIO,
    "video": MEDIA_VIDEO,
    "document": MEDIA_DOCUMENT,
}
_MEDIA_ACTIONS: dict[str, str] = {
    MEDIA_IMAGE: "Ver imagen",
    MEDIA_AUDIO: "Escuchar audio",
    MEDIA_VIDEO: "Ver video",
}
#: Document MIME → the word after «Descargar». Meta's webhook carries a filename, but
#: the chats read model (`MessageRecord`) does not expose it yet, so the type names it.
_DOCUMENT_LABELS: dict[str, str] = {
    "application/pdf": "PDF",
    "application/msword": "Word",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/vnd.ms-excel": "Excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.ms-powerpoint": "PowerPoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "text/plain": "TXT",
    "text/csv": "CSV",
    "application/zip": "ZIP",
}
#: Text-less inbound messages that are not files: worded by kind (`chats.MEDIA_PREVIEWS`).
_KIND_LABELS: dict[str, str] = {
    "location": "[ubicación]",
    "contacts": "[contacto]",
    "button": "[botón]",
    "interactive": "[respuesta]",
    "order": "[pedido]",
    "template": "[mensaje de WhatsApp]",
    "reaction": "[reacción]",
}
#: How long a resolved URL is reused. The public-media token lives 15 min
#: (`publishing.media_token.TOKEN_TTL_SECONDS`); the margin keeps a player started near
#: the end from hitting a dead link mid-stream.
MEDIA_URL_TTL = timedelta(minutes=13)

#: Outcomes of a media request (the route's codes, minus the 307).
MEDIA_EXPIRED = "media_expired"
MEDIA_UNAVAILABLE = "media_unavailable"
MEDIA_NOT_CAPTURED_CODE = "media_not_captured"
MEDIA_NOT_FOUND = "message_not_found"
MEDIA_EXPIRED_NOTICE = "El archivo ya no está disponible en WhatsApp"
MEDIA_UNAVAILABLE_NOTICE = "No se pudo traer el archivo; reintentar"
MEDIA_GONE_NOTICE = "Este mensaje ya no está disponible"
MEDIA_RETRY = "Reintentar"
# m-24842993: the owner never reads «ventana» or «plantillas» — say what happened and
# what comes next. m-24848535 adds the way out, «Enviar un mensaje aprobado», in the chat
# itself (copy: docs/ux-auditoria-2026-10/m6-whatsapp.md hallazgo 1).
WINDOW_CLOSED_NOTICE = (
    "Pasaron más de 24 horas desde su último mensaje. "
    "WhatsApp solo deja escribirle con un mensaje aprobado."
)
WINDOW_CLOSED_PILL = "Solo con mensaje aprobado"
NO_MESSAGES_YET = "Sin mensajes todavía"
OUTBOUND_PREFIX = "Tú: "

FILTER_OPEN = "open"
FILTER_CLOSED = "closed"
FILTER_UNREAD = "unread"
FILTERS: tuple[tuple[str, str], ...] = (
    (FILTER_OPEN, "Abiertos"),
    (FILTER_CLOSED, "Cerrados"),
    (FILTER_UNREAD, "Sin leer"),
)
FILTER_KEYS = frozenset(key for key, _label in FILTERS)
DEFAULT_FILTER = FILTER_OPEN

COMPOSE_TEXT = "text"
COMPOSE_BUTTONS = "buttons"
#: m-24945888: «Imagen por enlace» left the selector; a photo or the menu goes through
#: «Foto o menú» (the picker below), never through a pasted address.
COMPOSE_MODES: tuple[tuple[str, str], ...] = (
    (COMPOSE_TEXT, "Texto"),
    (COMPOSE_BUTTONS, "Botones"),
)
COMPOSE_KEYS = frozenset(key for key, _label in COMPOSE_MODES)

#: A window that closes within this is a `warn`, worded «cierra en 42 min».
WINDOW_WARN_WITHIN = timedelta(hours=1)

_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

# `whatsapp_thread_state.context["_order"]["collected"]` keys the menus use today → the
# label a person reads. Anything else is shown humanized rather than dropped.
_COLLECTED_LABELS: dict[str, str] = {
    "direccion": "Dirección",
    "dirección": "Dirección",
    "address": "Dirección",
    "nombre": "Nombre",
    "name": "Nombre",
    "telefono": "Teléfono",
    "teléfono": "Teléfono",
    "phone": "Teléfono",
    "notas": "Notas",
    "nota": "Nota",
    "barrio": "Barrio",
    "ciudad": "Ciudad",
    "pago": "Pago",
    "metodo_pago": "Método de pago",
}
_FIELD_ORDER = ("Dirección", "Barrio", "Ciudad", "Nombre", "Teléfono", "Pago", "Método de pago")


# ======================================================================================
# Input shapes (duck-typed: the backend's dataclasses satisfy them)
# ======================================================================================


class _Window(Protocol):
    open: bool
    closes_at: datetime | None


class ThreadLike(Protocol):
    id: Any
    wa_id: str
    contact_name: str | None
    last_message_preview: str | None
    last_message_direction: str | None
    last_message_at: datetime | None
    unread_count: int
    status: str
    assigned_agent_id: Any
    automation_paused: bool
    window: _Window


class MessageLike(Protocol):
    id: Any
    direction: str
    text: str | None
    posted_at: datetime | None
    delivery_status: str | None
    delivery_error_code: str | None
    media_kind: str | None
    has_media: bool
    media_mime: str | None


@dataclass(frozen=True)
class MediaResolution:
    """What the state learned about one message's media — held BACKEND-side only (the
    state's `_media`), turned into `MessageVM` fields by `build_message_vm`. Either a
    URL with its local expiry, or one of the `MEDIA_*` outcome codes."""

    url: str = ""
    expires_at: datetime | None = None
    error: str = ""

    def fresh_url(self, now: datetime) -> str:
        if self.url and self.expires_at is not None and now < self.expires_at:
            return self.url
        return ""


@dataclass(frozen=True)
class UnsentItem:
    """A `whatsapp_outbox` row of this thread that has not become a `messages` row yet
    (pending / sending / failed / dead) — the provider reads it so a person sees what
    they queued, and why it did not go out. `text` is already extracted from the body."""

    id: str
    status: str
    text: str
    created_at: datetime
    error_code: str | None = None


# ======================================================================================
# Formatting
# ======================================================================================


def _local(value: datetime, zone: tzinfo) -> datetime:
    return value.astimezone(zone) if value.tzinfo is not None else value


def format_clock(value: datetime, zone: tzinfo) -> str:
    return _local(value, zone).strftime("%H:%M")


def format_day(value: datetime, zone: tzinfo, now: datetime) -> str:
    """`12 oct` (same year) / `12 oct 2025`."""
    local = _local(value, zone)
    label = f"{local.day} {_MONTHS[local.month - 1]}"
    if local.year != _local(now, zone).year:
        label += f" {local.year}"
    return label


def relative_time(value: datetime | None, now: datetime, zone: tzinfo) -> str:
    """The thread list's time: `ahora` · `hace 5 min` · `hace 3 h` · `ayer` · `mié` ·
    `12 oct`. Calendar words (`ayer`, the weekday) are decided in the tenant's zone."""
    if value is None:
        return ""
    delta = now - value
    if delta < timedelta(minutes=1):
        return "ahora"
    if delta < timedelta(hours=1):
        return f"hace {int(delta.total_seconds() // 60)} min"
    days = (_local(now, zone).date() - _local(value, zone).date()).days
    if days == 0:
        return f"hace {int(delta.total_seconds() // 3600)} h"
    if days == 1:
        return "ayer"
    if days < 7:
        return _WEEKDAYS[_local(value, zone).weekday()]
    return format_day(value, zone, now)


def message_time(value: datetime | None, now: datetime, zone: tzinfo) -> str:
    """A bubble's time: `14:32` today, `ayer 14:32`, else `12 oct 14:32`."""
    if value is None:
        return ""
    days = (_local(now, zone).date() - _local(value, zone).date()).days
    clock = format_clock(value, zone)
    if days == 0:
        return clock
    if days == 1:
        return f"ayer {clock}"
    return f"{format_day(value, zone, now)} {clock}"


def window_pill(
    is_open: bool, closes_at: datetime | None, now: datetime, zone: tzinfo
) -> tuple[str, str]:
    """(label, tone) of the 24 h window: `ok` open, `warn` closing within the hour
    («Responde en los próximos 42 min»), `neutral` closed («Solo con mensaje aprobado»).
    Worded by what the owner can do, never «ventana»."""
    if not is_open or closes_at is None:
        return WINDOW_CLOSED_PILL, "neutral"
    remaining = closes_at - now
    if remaining <= timedelta(0):
        return WINDOW_CLOSED_PILL, "neutral"
    if remaining < WINDOW_WARN_WITHIN:
        minutes = max(1, math.ceil(remaining.total_seconds() / 60))
        if minutes == 1:
            return "Responde en el próximo minuto", "warn"
        return f"Responde en los próximos {minutes} min", "warn"
    return deadline_label(_local(closes_at, zone)), "ok"


def deadline_label(local_close: datetime) -> str:
    """«Puedes escribirle hasta las 5:00 p. m.» — «la» for one o'clock (m-24842994)."""
    clock = time_label_12h(local_close)
    article = "la" if clock.startswith("1:") else "las"
    return f"Puedes escribirle hasta {article} {clock}"


#: m-24842994: the chat's badge says who answers, in the owner's words.
MODE_MENU = "Responde el menú"
MODE_PERSON = "Respondes tú"


def mode_pill(automation_paused: bool) -> tuple[str, str]:
    """«Respondes tú» when someone took over (the menu stays quiet), else «Responde el
    menú»."""
    return (MODE_PERSON, "info") if automation_paused else (MODE_MENU, "neutral")


def initials(name: str) -> str:
    """`Ana María Pérez` → `AP`; `ana@x.co` → `A`. Two letters at most."""
    base = name.split("@", 1)[0] if "@" in name and " " not in name.strip() else name
    words = [w for w in base.replace(".", " ").replace("_", " ").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][0].upper()
    return (words[0][0] + words[-1][0]).upper()


def phone_label(wa_id: str) -> str:
    """`573001234567` → `+573001234567` (the wa_id is E.164 without the `+`)."""
    digits = wa_id.strip()
    return digits if digits.startswith("+") or not digits.isdigit() else f"+{digits}"


def unread_label(count: int) -> str:
    if count <= 0:
        return ""
    return "99+" if count > 99 else str(count)


def collected_label(key: str) -> str:
    lowered = key.strip().lower()
    if lowered in _COLLECTED_LABELS:
        return _COLLECTED_LABELS[lowered]
    words = lowered.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else key


# ======================================================================================
# Agents
# ======================================================================================


@dataclass(frozen=True)
class AgentVM:
    """A member of the tenant a thread can be assigned to."""

    user_id: str
    name: str
    initials: str


def build_agent_vm(user_id: str, display_name: str | None, email: str | None) -> AgentVM:
    name = (display_name or "").strip() or (email or "").strip() or "Sin nombre"
    return AgentVM(user_id=user_id, name=name, initials=initials(name))


# ======================================================================================
# Thread list
# ======================================================================================


@dataclass(frozen=True)
class ThreadRowVM:
    thread_id: str
    title: str
    subtitle: str
    preview: str
    time_label: str
    unread_label: str
    has_unread: bool
    window_label: str
    window_tone: str
    window_open: bool
    mode_label: str
    mode_tone: str
    automation_paused: bool
    agent_id: str
    agent_name: str
    agent_initials: str
    status: str
    is_closed: bool


EMPTY_THREAD = ThreadRowVM(
    thread_id="",
    title="",
    subtitle="",
    preview="",
    time_label="",
    unread_label="",
    has_unread=False,
    window_label=WINDOW_CLOSED_PILL,
    window_tone="neutral",
    window_open=False,
    mode_label=MODE_MENU,
    mode_tone="neutral",
    automation_paused=False,
    agent_id="",
    agent_name="",
    agent_initials="",
    status="open",
    is_closed=False,
)


def build_thread_row(
    thread: ThreadLike,
    *,
    now: datetime,
    zone: tzinfo,
    agents: Mapping[str, AgentVM] | None = None,
) -> ThreadRowVM:
    number = phone_label(thread.wa_id)
    name = (thread.contact_name or "").strip()
    preview = thread.last_message_preview or ""
    if not preview:
        preview = NO_MESSAGES_YET
    elif thread.last_message_direction == "inbound" and preview == "[mensaje]":
        preview = "[foto, audio o archivo]"
    elif thread.last_message_direction == "outbound":
        preview = OUTBOUND_PREFIX + preview
    window_label, window_tone = window_pill(thread.window.open, thread.window.closes_at, now, zone)
    mode_label, mode_tone = mode_pill(thread.automation_paused)
    agent_id = str(thread.assigned_agent_id) if thread.assigned_agent_id else ""
    agent = (agents or {}).get(agent_id) if agent_id else None
    if agent_id and agent is None:
        agent = AgentVM(user_id=agent_id, name="Otra persona", initials="?")
    return ThreadRowVM(
        thread_id=str(thread.id),
        title=name or number,
        subtitle=number if name else "",
        preview=preview,
        time_label=relative_time(thread.last_message_at, now, zone),
        unread_label=unread_label(thread.unread_count),
        has_unread=thread.unread_count > 0,
        window_label=window_label,
        window_tone=window_tone,
        window_open=window_tone != "neutral",
        mode_label=mode_label,
        mode_tone=mode_tone,
        automation_paused=thread.automation_paused,
        agent_id=agent_id,
        agent_name=agent.name if agent else "",
        agent_initials=agent.initials if agent else "",
        status=thread.status,
        is_closed=thread.status == "closed",
    )


def filter_threads(rows: Iterable[ThreadRowVM], key: str) -> list[ThreadRowVM]:
    """Abiertos = status open · Cerrados = status closed · Sin leer = any status with
    unread inbound messages. An unknown key falls back to Abiertos."""
    if key == FILTER_CLOSED:
        return [r for r in rows if r.is_closed]
    if key == FILTER_UNREAD:
        return [r for r in rows if r.has_unread]
    return [r for r in rows if not r.is_closed]


def filter_counts(rows: Sequence[ThreadRowVM]) -> dict[str, int]:
    return {key: len(filter_threads(rows, key)) for key, _label in FILTERS}


def filter_label(key: str, count: int) -> str:
    label = dict(FILTERS).get(key, key)
    return f"{label} · {count}" if count else label


# ======================================================================================
# Conversation
# ======================================================================================

# tick: "" (inbound / unknown), sent, delivered, read, failed, queued.
_TICK_LABELS: dict[str, str] = {
    "sent": "Enviado",
    "delivered": "Entregado",
    "read": "Leído",
    "failed": "No entregado",
    "queued": "Por enviar",
}


@dataclass(frozen=True)
class MessageVM:
    message_id: str
    is_outbound: bool
    text: str
    is_media_placeholder: bool
    time_label: str
    tick: str
    tick_label: str
    error_label: str
    ad_origin_label: str = ""
    ad_origin_href: str = ""
    # Inbound media (0061). `media_control` is "" (none) or one of `MEDIA_IMAGE/AUDIO/
    # VIDEO/DOCUMENT`; `media_action` is the button's label; `media_src` is set only
    # while a resolved URL is fresh; `media_notice` + `media_notice_tone` word a failed
    # request; `media_can_request` says whether the button is shown (no URL yet, or a
    # retryable failure).
    media_control: str = ""
    media_action: str = ""
    media_src: str = ""
    media_loading: bool = False
    media_can_request: bool = False
    media_notice: str = ""
    media_notice_tone: str = "neutral"


def media_control_for(kind: str | None) -> str:
    """WhatsApp message `type` → the control that renders it (download by default)."""
    return _MEDIA_CONTROLS.get((kind or "").lower(), MEDIA_DOCUMENT)


def document_label(mime: str | None) -> str:
    """«Descargar PDF» / «Descargar Word» / … / «Descargar archivo»."""
    base = (mime or "").split(";", 1)[0].strip().lower()
    word = _DOCUMENT_LABELS.get(base)
    return f"Descargar {word}" if word else "Descargar archivo"


def media_action_label(control: str, mime: str | None) -> str:
    if control == MEDIA_DOCUMENT:
        return document_label(mime)
    return _MEDIA_ACTIONS.get(control, "Ver archivo")


def media_notice(error: str) -> tuple[str, str]:
    """(copy, tone) of a failed media request; ("", "neutral") when there is none or it
    is `media_not_captured` (that one falls back to the chip, not a notice)."""
    if error == MEDIA_EXPIRED:
        return MEDIA_EXPIRED_NOTICE, "neutral"
    if error == MEDIA_NOT_FOUND:
        return MEDIA_GONE_NOTICE, "neutral"
    if error == MEDIA_UNAVAILABLE:
        return MEDIA_UNAVAILABLE_NOTICE, "warn"
    return "", "neutral"


def resolution_after(url: str, now: datetime) -> MediaResolution:
    """A freshly resolved URL, valid for `MEDIA_URL_TTL` from `now`."""
    return MediaResolution(url=url, expires_at=now + MEDIA_URL_TTL)


def failure_label(code: str | None) -> str:
    """The `error`-tone line under a failed bubble. Neither Meta's text nor its code reach
    the owner (the code stays in the outbox row and the logs)."""
    if code == "window_closed" or code in {"131047", "131026"}:
        return "No se entregó: pasaron más de 24 horas desde su último mensaje."
    if code == "opted_out":
        return "No se entregó: esta persona pidió no recibir más promociones."
    return "No se entregó"


def _media_fields(
    message: MessageLike,
    *,
    now: datetime,
    media: Mapping[str, MediaResolution],
    loading: Collection[str],
) -> dict[str, Any]:
    """The `media_*` fields of an inbound message that `has_media` ({} when the request
    came back `media_not_captured`: the caller falls back to the chip)."""
    message_id = str(message.id)
    resolution = media.get(message_id, MediaResolution())
    if resolution.error == MEDIA_NOT_CAPTURED_CODE:
        return {}
    control = media_control_for(message.media_kind)
    src = resolution.fresh_url(now)
    notice, tone = media_notice(resolution.error) if not src else ("", "neutral")
    retryable = resolution.error in ("", MEDIA_UNAVAILABLE)
    return {
        "media_control": control,
        "media_action": (
            MEDIA_RETRY
            if resolution.error == MEDIA_UNAVAILABLE
            else media_action_label(control, message.media_mime)
        ),
        "media_src": src,
        "media_loading": message_id in loading,
        "media_can_request": not src and retryable,
        "media_notice": notice,
        "media_notice_tone": tone,
    }


def build_message_vm(
    message: MessageLike,
    *,
    now: datetime,
    zone: tzinfo,
    media: Mapping[str, MediaResolution] | None = None,
    loading: Collection[str] = (),
) -> MessageVM:
    outbound = message.direction == "outbound"
    text = (message.text or "").strip()
    placeholder = False
    media_fields: dict[str, Any] = {}
    if not outbound and getattr(message, "has_media", False):
        media_fields = _media_fields(message, now=now, media=media or {}, loading=loading)
    if not text:
        if outbound:
            from_kind = {"image": "[imagen]", "audio": "[audio]", "document": "[documento]"}
            text = from_kind.get(message.media_kind or "", "[mensaje]")
        elif not media_fields:
            kind_label = _KIND_LABELS.get((message.media_kind or "").lower())
            text, placeholder = (kind_label or MEDIA_NOT_CAPTURED), True
    tick = ""
    if outbound:
        status = (message.delivery_status or "").lower()
        tick = status if status in _TICK_LABELS else ("sent" if not status else "")
    return MessageVM(
        message_id=str(message.id),
        is_outbound=outbound,
        text=text,
        is_media_placeholder=placeholder,
        time_label=message_time(message.posted_at, now, zone),
        tick=tick,
        tick_label=_TICK_LABELS.get(tick, ""),
        error_label=failure_label(message.delivery_error_code) if tick == "failed" else "",
        ad_origin_label=ad_origin_label(message),
        ad_origin_href=ad_origin_href(message),
        **media_fields,
    )


def build_unsent_vm(item: UnsentItem, *, now: datetime, zone: tzinfo) -> MessageVM:
    """An outbox row shown as an outbound bubble: «Por enviar» while pending/sending, the
    `error` tone with Meta's code once failed/dead."""
    failed = item.status in {"failed", "dead"}
    tick = "failed" if failed else "queued"
    return MessageVM(
        message_id=f"outbox-{item.id}",
        is_outbound=True,
        text=item.text or "[mensaje]",
        is_media_placeholder=False,
        time_label=message_time(item.created_at, now, zone),
        tick=tick,
        tick_label=_TICK_LABELS[tick],
        error_label=failure_label(item.error_code) if failed else "",
    )


def outbox_text(payload: Mapping[str, Any]) -> str:
    """The readable text of a queued `/messages` body (text / image / interactive)."""
    kind = payload.get("type")
    if kind == "text":
        body = payload.get("text")
        return str(body.get("body") or "") if isinstance(body, Mapping) else ""
    if kind in {"image", "audio", "document", "video"}:
        media = payload.get(kind)
        caption = media.get("caption") if isinstance(media, Mapping) else None
        label = {"image": "[imagen]", "audio": "[audio]", "document": "[documento]"}.get(
            str(kind), "[video]"
        )
        return f"{label} {caption}" if caption else label
    if kind == "interactive":
        inter = payload.get("interactive")
        if not isinstance(inter, Mapping):
            return "[mensaje]"
        body = inter.get("body")
        text = str(body.get("text") or "") if isinstance(body, Mapping) else ""
        action = inter.get("action")
        buttons = action.get("buttons") if isinstance(action, Mapping) else None
        titles = [
            str(b.get("reply", {}).get("title", ""))
            for b in buttons or []
            if isinstance(b, Mapping) and isinstance(b.get("reply"), Mapping)
        ]
        if titles:
            text += "\n" + " · ".join(f"[{t}]" for t in titles if t)
        return text.strip() or "[mensaje]"
    return "[mensaje]"


def build_conversation(
    messages: Sequence[MessageLike],
    unsent: Sequence[UnsentItem],
    *,
    now: datetime,
    zone: tzinfo,
    media: Mapping[str, MediaResolution] | None = None,
    loading: Collection[str] = (),
) -> list[MessageVM]:
    """Messages and not-yet-sent outbox rows, chronological (oldest first). `media` /
    `loading` decorate the inbound media messages (see `MediaResolution`)."""
    keyed: list[tuple[datetime, int, MessageVM]] = []
    for m in messages:
        instant = m.posted_at or now
        vm = build_message_vm(m, now=now, zone=zone, media=media, loading=loading)
        keyed.append((instant, 0, vm))
    for item in unsent:
        keyed.append((item.created_at, 1, build_unsent_vm(item, now=now, zone=zone)))
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    return [vm for _instant, _order, vm in keyed]


def merge_pages(older: Sequence[Any], newest: Sequence[Any]) -> list[Any]:
    """A refresh re-reads only the newest page; the older pages the person already
    loaded with «cargar anteriores» are kept (everything strictly before the new page's
    first message). Both inputs chronological; ids dedupe the overlap."""
    if not newest:
        return list(older)
    first = newest[0].posted_at
    seen = {m.id for m in newest}
    kept = [
        m
        for m in older
        if m.id not in seen and (m.posted_at is None or first is None or m.posted_at < first)
    ]
    return [*kept, *newest]


# ======================================================================================
# Order card
# ======================================================================================


@dataclass(frozen=True)
class OrderLineVM:
    label: str
    amount: str


@dataclass(frozen=True)
class OrderFieldVM:
    label: str
    value: str


@dataclass(frozen=True)
class OrderCardVM:
    present: bool
    lines: list[OrderLineVM] = field(default_factory=list)
    total_label: str = ""
    items_label: str = ""
    collected: list[OrderFieldVM] = field(default_factory=list)
    confirmed_label: str = ""


EMPTY_ORDER = OrderCardVM(present=False)


def format_money(amount: Decimal, currency: str | None) -> str:
    """Same format as the menu engine's `format_money` (`COP 12.500` / `USD 9,99`) —
    duplicated so this module stays import-free; `test_whatsapp_chats.py` pins they
    agree."""
    q = amount.quantize(Decimal("0.01"))
    if q == q.to_integral_value():
        num = f"{int(q):,}".replace(",", ".")
    else:
        num = f"{q:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{currency} {num}" if currency else num


def build_order_card(order: Any | None, *, now: datetime, zone: tzinfo) -> OrderCardVM:
    """`order` is `qualify_api.whatsapp.orders.OrderSummary` (or `None`)."""
    if order is None:
        return EMPTY_ORDER
    lines = []
    for line in order.lines:
        total = line.line_total
        lines.append(
            OrderLineVM(
                label=f"{line.qty} × {line.name or line.product_id}",
                amount=format_money(total, line.currency or order.currency) if total else "",
            )
        )
    count = order.item_count
    fields = [
        OrderFieldVM(label=collected_label(str(k)), value=str(v))
        for k, v in order.collected.items()
        if v not in (None, "") and not str(k).startswith("_")
    ]
    # jsonb does not keep insertion order: the address (what the courier needs) first,
    # then the known fields in `_FIELD_ORDER`, then anything else as it came.
    collected = sorted(
        fields,
        key=lambda f: _FIELD_ORDER.index(f.label) if f.label in _FIELD_ORDER else len(_FIELD_ORDER),
    )
    confirmed = ""
    if order.confirmed_at is not None:
        confirmed = f"Confirmado {message_time(order.confirmed_at, now, zone)}"
    return OrderCardVM(
        present=True,
        lines=lines,
        total_label=format_money(order.total, order.currency),
        items_label=f"{count} producto" if count == 1 else f"{count} productos",
        collected=collected,
        confirmed_label=confirmed,
    )


# ======================================================================================
# Composer validation (the UI's; the client builders re-check on send)
# ======================================================================================


def validate_text(text: str) -> str:
    """'' when sendable, else the reason in Spanish."""
    body = text.strip()
    if not body:
        return "Escribe un mensaje."
    if len(body) > MAX_TEXT_CHARS:
        return f"El mensaje admite hasta {MAX_TEXT_CHARS} caracteres."
    return ""


def clean_titles(titles: Sequence[str]) -> list[str]:
    return [t.strip() for t in titles if t.strip()]


def validate_buttons(text: str, titles: Sequence[str]) -> str:
    body = text.strip()
    if not body:
        return "Escribe el texto que acompaña a los botones."
    if len(body) > MAX_BUTTONS_BODY_CHARS:
        return (
            f"El texto de un mensaje con botones admite hasta {MAX_BUTTONS_BODY_CHARS} caracteres."
        )
    cleaned = clean_titles(titles)
    if not cleaned:
        return "Añade al menos un botón."
    if len(cleaned) > MAX_BUTTONS:
        return f"WhatsApp admite hasta {MAX_BUTTONS} botones."
    for title in cleaned:
        if len(title) > MAX_BUTTON_TITLE_CHARS:
            return f"«{title}» pasa de {MAX_BUTTON_TITLE_CHARS} caracteres."
    if len({t.casefold() for t in cleaned}) != len(cleaned):
        return "Cada botón necesita un texto distinto."
    return ""


def validate_compose(mode: str, text: str, titles: Sequence[str]) -> str:
    if mode == COMPOSE_BUTTONS:
        return validate_buttons(text, titles)
    return validate_text(text)


def composer_enabled(window_open: bool, has_thread: bool) -> bool:
    """Free-form sends need the 24 h window open; outside it the composer gives way to
    «Enviar un mensaje aprobado» (m-24848535)."""
    return has_thread and window_open


# ======================================================================================
# Approved messages from an expired chat (m-24848535, WHATSAPP-2)
# ======================================================================================

SEND_APPROVED_LABEL = "Enviar un mensaje aprobado"
SEND_APPROVED_DESCRIPTION = (
    "Elige uno de tus mensajes que WhatsApp ya aprobó. Solo se envía cuando tocas «Enviar»."
)
#: Founder decision 2026-10-23 (epic §2b-4): the exact notice and button.
PROMOTIONS_NEED_CONSENT = "Para enviarle promociones, esta persona tiene que aceptar recibirlas."
ASK_CONSENT_LABEL = "Pedirle que acepte"
NO_FOLLOWUPS = (
    "Todavía no tienes un mensaje aprobado para retomar una conversación. "
    "Crea uno y, cuando WhatsApp lo apruebe, podrás enviarlo desde aquí."
)
CREATE_APPROVED_LABEL = "Crear un mensaje aprobado"
#: N5: the link lands on the tab where approved messages are created.
CREATE_APPROVED_ROUTE = "/whatsapp?tab=promociones&sub=aprobados"
NO_PERMISSION_NOTICE = (
    "Esta persona todavía no te ha escrito ni aceptó recibir tus mensajes. "
    "Cuando te escriba, podrás responderle desde este chat."
)
TEMPLATE_PICK_HINT = "Elige un mensaje para ver cómo le llega."
TEMPLATE_FILL_HINT = "Completa los datos del mensaje para poder enviarlo."
TEMPLATE_PREVIEW_LABEL = "Así le llega"
TEMPLATE_FIELDS_LABEL = "Datos del mensaje"
#: Two steps inside the drawer (UX review): pick, then fill and review.
TEMPLATE_STEP_PICK = "Paso 1 de 2 · Elige el mensaje"
TEMPLATE_STEP_REVIEW = "Paso 2 de 2 · Completa y revisa"
TEMPLATE_BACK_LABEL = "Atrás"
TEMPLATE_EXAMPLE_PREFIX = "Ejemplo: "
#: The two categories the chat can send, in the owner's words (Meta: utility / marketing).
_TEMPLATE_KIND: dict[str, tuple[str, str]] = {
    "utility": ("Seguimiento", "info"),
    "marketing": ("Promoción", "neutral"),
}
_NAME_WORDS = frozenset({"nombre", "name", "cliente", "first_name", "nombre_cliente"})


@dataclass(frozen=True)
class TemplateChoiceVM:
    """One approved message the owner may pick. Never the template's JSON."""

    template_id: str = ""
    title: str = ""
    kind_label: str = ""
    kind_tone: str = "neutral"
    preview: str = ""
    is_consent_request: bool = False


@dataclass(frozen=True)
class TemplateFieldVM:
    """One value the chosen message needs (`id` = `component:key`)."""

    id: str = ""
    label: str = ""
    value: str = ""
    #: «Ejemplo: …» from the example Meta stored for the variable ("" when none).
    example: str = ""


class TemplateOptionLike(Protocol):
    template_id: Any
    name: str
    category: str
    preview: str
    is_consent_request: bool


class TemplateVariableLike(Protocol):
    component: str
    key: str
    named: bool

    @property
    def id(self) -> str: ...


def template_title(name: str) -> str:
    """`seguimiento_pedido` → «Seguimiento pedido»: Meta's internal name, readable."""
    words = " ".join(part for part in (name or "").replace("-", "_").split("_") if part)
    return words[:1].upper() + words[1:] if words else "Mensaje aprobado"


def template_kind(category: str) -> tuple[str, str]:
    return _TEMPLATE_KIND.get(category, ("Mensaje aprobado", "neutral"))


def build_template_choice(
    option: TemplateOptionLike, preview: str | None = None
) -> TemplateChoiceVM:
    """`preview` overrides the service's one (the state passes it with «[label]» gaps)."""
    label, tone = template_kind(option.category)
    return TemplateChoiceVM(
        template_id=str(option.template_id),
        title=template_title(option.name),
        kind_label=label,
        kind_tone=tone,
        preview=option.preview if preview is None else preview,
        is_consent_request=bool(option.is_consent_request),
    )


def template_field_label(variable: TemplateVariableLike) -> str:
    """«Nombre del cliente» for the name; «Pedido» for a named `{{pedido}}`; «Dato 2 del
    mensaje» for a positional one («(arriba del mensaje)» when it lives in the header)."""
    key = variable.key
    if variable.named and key.lower() in _NAME_WORDS:
        label = "Nombre del cliente"
    elif variable.named:
        label = template_title(key)
    else:
        label = f"Dato {key} del mensaje"
    return f"{label} (arriba del mensaje)" if variable.component == "header" else label


def build_template_fields(
    variables: Sequence[TemplateVariableLike],
    values: Mapping[str, str],
    examples: Mapping[str, str] | None = None,
) -> list[TemplateFieldVM]:
    examples = examples or {}
    return [
        TemplateFieldVM(
            id=v.id,
            label=template_field_label(v),
            value=values.get(v.id, ""),
            example=f"{TEMPLATE_EXAMPLE_PREFIX}{examples[v.id]}" if examples.get(v.id) else "",
        )
        for v in variables
    ]


def preview_values(
    variables: Sequence[TemplateVariableLike], values: Mapping[str, str]
) -> dict[str, str]:
    """The values for the preview: what the owner typed, and «[label]» in every gap, so
    the preview never shows a raw `{{1}}` and says which field fills which gap. Only the
    preview uses it; the send still refuses an empty value (`MissingValues`)."""
    out = {k: v for k, v in values.items() if isinstance(v, str) and v.strip()}
    for variable in variables:
        if variable.id not in out:
            out[variable.id] = f"[{template_field_label(variable)}]"
    return out


def template_fields_complete(fields: Sequence[TemplateFieldVM]) -> bool:
    return all(f.value.strip() for f in fields)


# ======================================================================================
# «Foto o menú» (m-24945888, docs/ux-whatsapp-enviar-imagen.md)
# ======================================================================================
#
# A drawer with up to three steps — ① what to send → ② which one → ③ «Revisa y envía» —
# that queues nothing until the owner taps «Enviar». The backend
# (`qualify_api.whatsapp.attachments`) owns every rule (window, R2 copy, size/type,
# caption length, provenance); this section only words it and shapes the picks.

PICK_BUTTON_LABEL = "Foto o menú"
PICK_BUTTON_ARIA = "Enviar una foto de tus productos, una pieza, tu menú o una foto"

#: The drawer's address (`?flujo=foto-menu&paso=N`, `ui/flow_history.py`): the phone's
#: «atrás» goes one step back; on step 1 it closes the drawer (N5).
PICK_FLOW = "foto-menu"
PICK_PRODUCTS = "products"
PICK_PIECES = "pieces"
PICK_MENU = "menu"
PICK_PHOTO = "photo"
PICK_SOURCES = frozenset({PICK_PRODUCTS, PICK_PIECES, PICK_MENU, PICK_PHOTO})

PIECES_APPROVED = "approved"
PIECES_UNAPPROVED = "unapproved"
PIECE_TABS: tuple[tuple[str, str], ...] = (
    (PIECES_APPROVED, "Aprobadas"),
    (PIECES_UNAPPROVED, "Sin aprobar"),
)
PIECE_TAB_KEYS = frozenset(key for key, _label in PIECE_TABS)

#: The photo from the phone: what the backend takes on the way in
#: (`attachments.PHONE_PHOTO_TYPES`, `MAX_INPUT_BYTES`, `MAX_IMAGE_PIXELS`), mirrored so
#: the screen refuses before keeping it; the backend re-encodes it within WhatsApp's 5 MB.
MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_PHOTO_PIXELS = 40_000_000
PHOTO_TYPES: dict[str, tuple[str, ...]] = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}
#: More than this many products and the grid gets «Buscar en tus productos».
PRODUCT_SEARCH_FROM = 8

PICK_HELP_SOURCE = "Elige y revisa antes de enviar. Nada sale sin que toques «Enviar»."
PICK_BACK_TO_CHAT = "Volver al chat"
PICK_BACK = "Atrás"

#: (title, one line) of each source on step 1, in the spec's order.
PICK_SOURCE_CARDS: tuple[tuple[str, str, str, str], ...] = (
    (PICK_PRODUCTS, "package", "Tus productos", "Una foto con su precio, para que te lo pida."),
    (PICK_PIECES, "images", "Tus piezas", "Lo que ya preparaste para tus redes."),
    (PICK_MENU, "list", "Tu menú", "La lista de tus productos para que elija y te pida."),
    (PICK_PHOTO, "smartphone", "Una foto de tu celular", "Una que ya tengas guardada."),
)

PRODUCTS_TITLE = "¿Cuál producto?"
PRODUCTS_HELP = "Toca uno para ver cómo le llega."
PRODUCTS_SEARCH = "Buscar en tus productos"
PRODUCTS_NO_MATCH = "Ningún producto se llama así."
PRODUCTS_SHOW_ALL = "Ver todos"
PIECES_TITLE = "¿Cuál pieza?"
PIECES_HELP = "Toca una para ver cómo le llega."
MENU_TITLE = "Así le llega tu menú"
MENU_HELP = (
    "Es lo mismo que reciben cuando tocan «Ver menú y pedir». "
    "No es una foto: tu cliente toca el botón y elige."
)
PHOTO_TITLE = "¿Qué foto?"
PHOTO_HELP = "Elige una foto que tengas guardada en tu celular."
PHOTO_PICK_LABEL = "Elegir una foto"
PHOTO_CHANGE_LABEL = "Elegir otra foto"
REVIEW_TITLE = "Revisa y envía"
REVIEW_HELP = "Así le llega. Puedes cambiar el texto antes de enviar."
CAPTION_LABEL = "Texto que acompaña la foto"
TEXT_ONLY_LABEL = "Texto del mensaje"
SEND_LABEL = "Enviar"
SEND_MENU_LABEL = "Enviar el menú"
SENDING_LABEL = "Enviando…"

NO_PHOTO_PILL = "Sin foto"
UNAPPROVED_PILL = "Sin aprobar"
NO_PHOTO_NOTICE = "Este producto no tiene foto: le llegará solo el texto."
ADD_PHOTO_LABEL = "Agregar una foto"
ADD_PHOTOS_LABEL = "Agregar fotos"
ADD_PRODUCT_LABEL = "Agregar un producto"
CREATE_PIECE_LABEL = "Crear una pieza"
SEE_UNAPPROVED_LABEL = "Ver sin aprobar"
ALL_WITHOUT_PHOTO = "Tus productos no tienen foto: se enviarán como texto."
CAPTION_SHORTENED = "Acortamos el texto para que quepa en WhatsApp."
UNAPPROVED_WARNING = (
    "Todavía no aprobaste esta pieza: al enviarla, la apruebas solo para este chat."
)
CAPTION_TOO_LONG = f"El texto admite hasta {MAX_CAPTION_CHARS} caracteres."

#: (title, line) of the empty states (spec §4).
NO_PRODUCTS_EMPTY = ("Todavía no tienes productos.", "Agrégalos una vez y los mandas en un toque.")
NO_PIECES_EMPTY = ("Todavía no tienes piezas.", "Crea una con la foto de tu producto en un minuto.")
NO_APPROVED_EMPTY = (
    "Todavía no tienes piezas aprobadas.",
    "Revisa las que tienes por aprobar o crea una.",
)
NO_UNAPPROVED_EMPTY = ("No tienes piezas sin aprobar.", "Todo lo que preparaste ya está aprobado.")
MENU_EMPTY = "Tu menú está vacío: agrega productos para poder enviarlo."
#: `AttachmentRefused("no_menu")` (founder decision 2026-11-04: «Tu menú» hands the chat
#: back to the automation, so it needs a live one with a products step) — the backend's
#: own `REFUSAL_TEXT`, verbatim.
MENU_NOT_ACTIVE = (
    "Todavía no tienes una respuesta automática con tus productos activa. "
    "Créala en Respuesta automática para poder enviar tu menú."
)
MENU_SETUP_LABEL = "Ir a Respuesta automática"
MENU_SETUP_ROUTE = "/whatsapp?tab=menu"
#: After «Enviar el menú» the chat is the automation's again: the customer's pick goes on
#: with the order by itself.
MENU_RESUMES_NOTE = "Al enviarlo, la respuesta automática vuelve a atender este chat."

PRODUCTS_ROUTE = "/catalog"
NEW_PRODUCT_ROUTE = "/catalog?nuevo=1"
CREATE_PIECE_ROUTE = "/create"

# Loading and sending failures, in the owner's terms with the next step.
PRODUCTS_FAILED = "No pudimos cargar tus productos. Vuelve a intentarlo en un momento."
PIECES_FAILED = "No pudimos cargar tus piezas. Vuelve a intentarlo en un momento."
MENU_FAILED = "No pudimos preparar tu menú. Vuelve a intentarlo en un momento."
SEND_PHOTO_FAILED = "No pudimos enviar la foto. Revisa tu conexión y vuelve a intentarlo."
SEND_MENU_FAILED = "No pudimos enviar el menú. Revisa tu conexión y vuelve a intentarlo."
SEND_TEXT_FAILED = "No pudimos enviar el mensaje. Revisa tu conexión y vuelve a intentarlo."
PICK_WINDOW_CLOSED = "No se entregó: pasaron más de 24 horas desde su último mensaje."
#: The backend's own `REFUSAL_TEXT["too_large"]`, verbatim.
PHOTO_TOO_LARGE = "La foto es demasiado grande. Elige una de menos de 15 MB."
PHOTO_WRONG_TYPE = "Esa foto no se puede enviar. Elige una en JPG, PNG o WEBP."
PHOTO_UNREADABLE = "No pudimos leer esa foto. Elige otra."
#: The dropzone refused the file before reading it (type or size: it does not say which).
PHOTO_REJECTED = "Esa foto no se puede enviar. Elige una en JPG, PNG o WEBP de menos de 15 MB."
#: `AttachmentRefused("no_brand")`: the number is not tied to a business with products.
NO_BRAND = "Este número no tiene una marca con productos. Agrégalos en la Galería."
SAVED_PHOTO_UNREADABLE = "No pudimos abrir esa foto. Elige otra o vuelve a intentarlo."
PRODUCT_GONE = "Ese producto ya no está en la Galería. Elige otro."
PIECE_GONE = "Esa pieza ya no se puede enviar. Elige otra."
PIECE_NOT_PHOTO = "Por ahora solo se pueden enviar piezas de foto. Elige otra."
RETRY_LABEL = "Reintentar"

_FOOD_WORDS = (
    "comida",
    "restaur",
    "gastronom",
    "cocina",
    "shawarma",
    "helad",
    "yogur",
    "cafe",
    "panader",
    "pasteler",
    "reposter",
    "postre",
    "pizz",
    "hamburgues",
    "arepa",
    "empanad",
    "ensalad",
    "almuerzo",
    "sushi",
    "pollo",
    "parrill",
    "asado",
    "bebida",
    "jugo",
)
#: `brand_kit_details.connect.sector` niche key (`referentes.discovery_seed.NICHE_LABELS`).
FOOD_SECTOR = "food_drink"


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def is_food_business(sector: str, rubro: str = "") -> bool:
    """«¿Te lo preparo?» or «¿Te interesa?» (spec §2.1): a food business is one whose
    «Tu marca» niche is «Comida y bebida», or whose own words for its rubro name food.
    Unknown means not food — the neutral question never sounds wrong."""
    if (sector or "").strip() == FOOD_SECTOR:
        return True
    plain = _fold(rubro)
    return any(word in plain for word in _FOOD_WORDS)


def product_caption(name: str, price: str, *, food: bool, description: str = "") -> str:
    """The caption a product arrives with: «{nombre} — {precio}. ¿Te lo preparo?» (food)
    or «… ¿Te interesa?»; no price, no «— {precio}»; the description on a second line
    when it still fits in `MAX_CAPTION_CHARS`."""
    head = f"{name.strip()} — {price.strip()}" if price.strip() else name.strip()
    question = "¿Te lo preparo?" if food else "¿Te interesa?"
    first = f"{head}. {question}"
    extra = " ".join((description or "").split())
    if extra and len(first) + 1 + len(extra) <= MAX_CAPTION_CHARS:
        return f"{first}\n{extra}"
    return first[:MAX_CAPTION_CHARS]


def caption_count(caption: str) -> str:
    return f"{len(caption.strip())}/{MAX_CAPTION_CHARS}"


def caption_error(caption: str) -> str:
    return CAPTION_TOO_LONG if len(caption.strip()) > MAX_CAPTION_CHARS else ""


def pick_heading(title: str) -> str:
    """Step 1's question, with the person's first name when the chat has one (a chat
    titled by its phone number keeps the whole number)."""
    name = (title or "").strip()
    first = name.split()[0] if name else ""
    if first and any(ch.isalpha() for ch in first):
        name = first
    return f"¿Qué le quieres mandar a {name}?" if name else "¿Qué le quieres mandar?"


def photo_refusal(content_type: str, size: int) -> str:
    """'' when the phone photo can go on, else why not (the backend re-checks)."""
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared not in PHOTO_TYPES:
        return PHOTO_WRONG_TYPE
    if size <= 0:
        return PHOTO_UNREADABLE
    if size > MAX_PHOTO_BYTES:
        return PHOTO_TOO_LARGE
    return ""


#: `AttachmentRefused.reason` → the owner's words, per source (the photo's own limits
#: are its to state; a saved photo that cannot be read is another fix).
def refusal_message(reason: str, source: str) -> str:
    if reason == "empty_menu":
        return MENU_EMPTY
    if reason == "no_menu":
        return MENU_NOT_ACTIVE
    if reason == "no_brand":
        return NO_BRAND
    if reason == "not_photo":
        return PIECE_NOT_PHOTO
    if source == PICK_PHOTO:
        if reason == "too_large":
            return PHOTO_TOO_LARGE
        if reason == "unsupported_type":
            return PHOTO_WRONG_TYPE
        return PHOTO_UNREADABLE
    return SAVED_PHOTO_UNREADABLE


def send_failed_message(source: str, *, as_text: bool = False) -> str:
    if source == PICK_MENU:
        return SEND_MENU_FAILED
    return SEND_TEXT_FAILED if as_text else SEND_PHOTO_FAILED


class ProductPickLike(Protocol):
    id: str
    name: str
    price_label: str
    description: str
    thumb_url: str
    has_photo: bool
    thumb_key: str


class PiecePickLike(Protocol):
    id: str
    status: str
    caption_suggestion: str
    caption_shortened: bool
    thumb_url: str
    title: str
    image_count: int
    approved_at: datetime | None


class MenuPreviewLike(Protocol):
    body: str
    button_label: str
    header: str | None
    footer: str | None
    product_count: int
    rows_shown: int
    overflows: bool


@dataclass(frozen=True)
class ProductCardVM:
    """One product in the grid. `thumb_url` is a ready public URL; `thumb_key` an
    upload-store key the page resolves with `rx.get_upload_url` (one of the two)."""

    id: str = ""
    name: str = ""
    price_label: str = ""
    description: str = ""
    thumb_url: str = ""
    thumb_key: str = ""
    has_photo: bool = False
    alt: str = ""


@dataclass(frozen=True)
class PieceCardVM:
    id: str = ""
    title: str = ""
    status_label: str = ""  # «Publicada» · «Aprobada» · «Sin aprobar»
    status_tone: str = "neutral"
    unapproved: bool = False
    group: str = PIECES_APPROVED
    thumb_url: str = ""
    caption: str = ""
    shortened: bool = False
    photos_label: str = ""  # «1 de 4 fotos» for a carousel
    alt: str = ""


@dataclass(frozen=True)
class MenuPreviewVM:
    present: bool = False
    empty: bool = True
    #: No live «Respuesta automática» with a products step (`no_menu`): nothing to send.
    not_active: bool = False
    header: str = ""
    body: str = ""
    footer: str = ""
    button_label: str = ""
    count_label: str = ""
    overflow_note: str = ""


EMPTY_PRODUCT = ProductCardVM()
EMPTY_PIECE = PieceCardVM()
EMPTY_MENU = MenuPreviewVM()
MENU_NOT_ACTIVE_VM = MenuPreviewVM(present=True, empty=True, not_active=True)


def build_product_cards(picks: Iterable[ProductPickLike]) -> list[ProductCardVM]:
    """The grid, those with a photo first and «Sin foto» last (stable: the menu's order
    stays inside each group)."""
    cards = [
        ProductCardVM(
            id=str(p.id),
            name=p.name,
            price_label=p.price_label,
            description=p.description,
            thumb_url=p.thumb_url,
            thumb_key="" if p.thumb_url else (p.thumb_key or ""),
            has_photo=bool(p.has_photo),
            alt=p.name,
        )
        for p in picks
    ]
    return [c for c in cards if c.has_photo] + [c for c in cards if not c.has_photo]


def filter_products(cards: Sequence[ProductCardVM], query: str) -> list[ProductCardVM]:
    needle = _fold(query).strip()
    if not needle:
        return list(cards)
    return [c for c in cards if needle in _fold(c.name)]


def _piece_status(
    status: str, approved_at: datetime | None, zone: tzinfo | None
) -> tuple[str, str, bool]:
    """«Publicada» (the backend gives no publish date) · «Aprobada el 2 nov.» (or
    «Aprobada» without a date) · «Sin aprobar»."""
    if status == "published":
        return "Publicada", "ok", False
    if status == "approved":
        if approved_at is not None and zone is not None:
            day = _local(approved_at, zone)
            return f"Aprobada el {day.day} {_MONTHS[day.month - 1]}.", "ok", False
        return "Aprobada", "ok", False
    return UNAPPROVED_PILL, "warn", True


def build_piece_cards(
    picks: Iterable[PiecePickLike], zone: tzinfo | None = None
) -> list[PieceCardVM]:
    cards = []
    for p in picks:
        label, tone, unapproved = _piece_status(p.status, getattr(p, "approved_at", None), zone)
        count = int(p.image_count or 1)
        cards.append(
            PieceCardVM(
                id=str(p.id),
                title=p.title or "Pieza sin título",
                status_label=label,
                status_tone=tone,
                unapproved=unapproved,
                group=PIECES_UNAPPROVED if unapproved else PIECES_APPROVED,
                thumb_url=p.thumb_url,
                caption=p.caption_suggestion,
                shortened=bool(p.caption_shortened),
                photos_label=f"1 de {count} fotos" if count > 1 else "",
                alt=p.title or "Pieza",
            )
        )
    return cards


def pieces_in(cards: Sequence[PieceCardVM], group: str) -> list[PieceCardVM]:
    return [c for c in cards if c.group == group]


def products_count_label(count: int) -> str:
    return f"{count} producto de la Galería" if count == 1 else (f"{count} productos de la Galería")


def build_menu_preview(preview: MenuPreviewLike) -> MenuPreviewVM:
    count = int(preview.product_count or 0)
    overflow = ""
    if count and not preview.rows_shown:
        # Categories first (m-24955838): the list's rows are the categories, not
        # products, and no «Ver más» runs over the whole catalog.
        overflow = (
            f"Tu menú tiene {count} productos: tu cliente primero elige una categoría y "
            "luego ve sus productos."
        )
    elif preview.overflows:
        overflow = (
            f"Tu menú tiene {count} productos: la lista muestra los primeros "
            f"{preview.rows_shown} y tu cliente toca «Ver más» para ver el resto."
        )
    return MenuPreviewVM(
        present=True,
        empty=count == 0,
        header=preview.header or "",
        body=preview.body,
        footer=preview.footer or "",
        button_label=preview.button_label,
        count_label=products_count_label(count) if count else "",
        overflow_note=overflow,
    )


def pick_total_steps(source: str) -> int:
    """Tu menú has nothing to choose: two steps; the others three (spec §2)."""
    return 2 if source == PICK_MENU else 3


def pick_step_title(step: int, source: str, heading: str) -> str:
    if step <= 1:
        return heading
    if source == PICK_MENU:
        return MENU_TITLE
    if step >= 3:
        return REVIEW_TITLE
    return {PICK_PRODUCTS: PRODUCTS_TITLE, PICK_PIECES: PIECES_TITLE, PICK_PHOTO: PHOTO_TITLE}.get(
        source, heading
    )


def pick_step_help(step: int, source: str) -> str:
    if step <= 1:
        return PICK_HELP_SOURCE
    if source == PICK_MENU:
        return MENU_HELP
    if step >= 3:
        return REVIEW_HELP
    return {PICK_PRODUCTS: PRODUCTS_HELP, PICK_PIECES: PIECES_HELP, PICK_PHOTO: PHOTO_HELP}.get(
        source, ""
    )
