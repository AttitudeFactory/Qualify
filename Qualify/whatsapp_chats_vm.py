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
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from typing import Any, Protocol

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
COMPOSE_IMAGE = "image"
COMPOSE_MODES: tuple[tuple[str, str], ...] = (
    (COMPOSE_TEXT, "Texto"),
    (COMPOSE_BUTTONS, "Botones"),
    (COMPOSE_IMAGE, "Imagen por enlace"),
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


def validate_image(url: str, caption: str) -> str:
    link = url.strip()
    if not link:
        return "Pega el enlace de la imagen."
    if not link.startswith("https://") or " " in link or len(link) < 12:
        return "El enlace debe empezar por https:// y ser público."
    if len(caption.strip()) > MAX_CAPTION_CHARS:
        return f"El pie de foto admite hasta {MAX_CAPTION_CHARS} caracteres."
    return ""


def validate_compose(mode: str, text: str, titles: Sequence[str], url: str, caption: str) -> str:
    if mode == COMPOSE_BUTTONS:
        return validate_buttons(text, titles)
    if mode == COMPOSE_IMAGE:
        return validate_image(url, caption)
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
CREATE_APPROVED_ROUTE = "/whatsapp?tab=plantillas"
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
