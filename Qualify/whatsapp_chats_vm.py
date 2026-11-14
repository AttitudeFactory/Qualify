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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlencode

from .ad_message_vm import ad_origin_href, ad_origin_label
from .catalog_vm import CHATS_RETURN_PATH, RETURN_PARAM
from .chat_row_vm import (
    CHANNEL_WHATSAPP,
    ChatRowVM,
    build_chat_row,
    letter_initials,
    minutes_left,
)
from .chat_thread_vm import mark_days, window_line
from .planner_vm import time_label_12h
from .seasonal_vm import CREATE_HREF as SEASONAL_LIBRARY_CREATE_HREF
from .seasonal_vm import PRODUCT_RECIPES, PRODUCT_SEASON_KEY, product_message

if TYPE_CHECKING:  # the reader's shapes; this module stays free of backend imports
    from qualify_api.whatsapp.orders import OrderLine, OrderSummary, PreviousOrder

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
    "template": "[mensaje de WhatsApp]",
    "reaction": "[reacción]",
}
#: m-25018684 (spec §3): an inbound catalog cart (`media_type = 'order'`). With its
#: order still on record the bubble says what came; without it (a cart older than the
#: archive) it says the detail is gone — never «[pedido]».
CART_BUBBLE = "Mandó un pedido desde tu catálogo: {detail}"
CART_BUBBLE_NO_DETAIL = "Mandó un pedido desde tu catálogo. El detalle ya no está guardado."
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
#: m-25017859: the chats that wait for the owner's reply under the ONE «Por responder»
#: rule (`ThreadSummary.awaiting_reply`) — the number on the menu's WhatsApp badge. The
#: key keeps its old value so old links (`?filtro=sin-leer`) still land here.
FILTER_UNREAD = "unread"
#: The chip's words, in ONE place: it lists the chats that wait for a reply, so it cannot
#: be «Sin leer». UX proposal (m-25017859) awaiting the founder's confirmation.
AWAITING_FILTER_LABEL = "Por responder"
#: `?filtro=` values that open the chats on that chip (the second one is its old name).
AWAITING_FILTER_SLUGS = frozenset({"por-responder", "sin-leer"})
#: m-25017859: every chip's `?filtro=`, so the address says the chip on screen (a reload
#: or «atrás» shows it) — the first slug of each is the one written.
FILTER_SLUG: dict[str, str] = {
    "open": "abiertos",
    "closed": "cerrados",
    "unread": "por-responder",
    "payment": "pago-por-revisar",
}


def filter_from_slug(slug: object) -> str:
    """The chip a navigation's `?filtro=` asks for; anything else (none, unknown) is the
    default «Abiertos»."""
    value = slug.strip().lower() if isinstance(slug, str) else ""
    if value in AWAITING_FILTER_SLUGS:
        return "unread"
    return next((k for k, s in FILTER_SLUG.items() if s == value), "open")


#: m-24971198: the chats whose customer answered after the payment card (spec §4).
FILTER_PAYMENT = "payment"
FILTERS: tuple[tuple[str, str], ...] = (
    (FILTER_OPEN, "Abiertos"),
    (FILTER_CLOSED, "Cerrados"),
    (FILTER_UNREAD, AWAITING_FILTER_LABEL),
    (FILTER_PAYMENT, "Pago por revisar"),
)
FILTER_KEYS = frozenset(key for key, _label in FILTERS)
DEFAULT_FILTER = FILTER_OPEN

COMPOSE_TEXT = "text"
COMPOSE_BUTTONS = "buttons"
#: m-24945888: «Imagen por enlace» left the selector; a photo or the menu goes through
#: the composer's «+» (the send panel below), never through a pasted address.
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


def bubble_clock(value: datetime | None, zone: tzinfo) -> str:
    """A bubble's time: the clock alone — the day separator above says the day
    (m-25027371, as Instagram's thread)."""
    return format_clock(value, zone) if value is not None else ""


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
        # m-25017844: the same count as the row's pill (`chat_row_vm.minutes_left`).
        minutes = minutes_left(is_open, closes_at, now)
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
    #: «Pago por revisar»: the filter's own test and the row's most urgent pill.
    payment_review: bool = False
    #: m-25017844 (UX review): «Esperando el pago» — the row's pill when nothing beats it.
    payment_awaiting: bool = False
    #: m-25017844: minutes until the window closes when under an hour, else 0 — the
    #: shared row's «Quedan N min para responder».
    window_minutes: int = 0
    #: m-25017859: the «Por responder» rule's verdict (`ThreadSummary.awaiting_reply`):
    #: the waiting dot and the «Por responder» chip.
    awaiting_reply: bool = False
    #: m-25027371: the open chat's header — the person's initials ("" → the person
    #: icon) and the shared window line («Puedes escribirle hasta las …»).
    initials: str = ""
    window_line: str = WINDOW_CLOSED_PILL
    window_line_tone: str = "neutral"


EMPTY_THREAD = ThreadRowVM(
    thread_id="",
    title="",
    subtitle="",
    preview="",
    time_label="",
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
    line, line_tone = window_line(
        thread.window.open, thread.window.closes_at, now, zone, closed_text=WINDOW_CLOSED_PILL
    )
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
        window_minutes=minutes_left(thread.window.open, thread.window.closes_at, now),
        awaiting_reply=bool(getattr(thread, "awaiting_reply", False)),
        initials=letter_initials(name),
        window_line=line,
        window_line_tone=line_tone,
    )


def as_chat_row(row: ThreadRowVM) -> ChatRowVM:
    """m-25017844: this channel's row in the shared shape (`chat_row_vm`). The «Por
    responder» rule (m-25017859) is the waiting dot; a closed chat is muted wherever a
    chip mixes open and closed ones («Pago por revisar»); «Responde el menú» /
    «Respondes tú» and «Cerrado» leave the row (the chat and the filter say them); the
    payment to check and the window about to close fold into the one pill («Esperando
    el pago» too). No second line (UX doc §2): the title is the profile name, else the
    number, as before; initials come only from the name's letters (a number-only
    contact gets the person icon)."""
    named = row.subtitle != ""
    return build_chat_row(
        thread_id=row.thread_id,
        channel=CHANNEL_WHATSAPP,
        title=row.title,
        preview=row.preview,
        time_label=row.time_label,
        waiting=row.awaiting_reply,
        closed=row.is_closed,
        initials_from=row.title if named else "",
        payment_review=row.payment_review,
        payment_awaiting=row.payment_awaiting,
        reply_within_minutes=row.window_minutes,
        agent_initials=row.agent_initials,
        agent_name=row.agent_name,
    )


def filter_threads(rows: Iterable[ThreadRowVM], key: str) -> list[ThreadRowVM]:
    """Abiertos = status open · Cerrados = status closed · Por responder = the rule's
    verdict (`awaiting_reply`, m-25017859: the same chats the menu's WhatsApp badge
    counts) · Pago por revisar. An unknown key falls back to Abiertos."""
    if key == FILTER_CLOSED:
        return [r for r in rows if r.is_closed]
    if key == FILTER_UNREAD:
        return [r for r in rows if r.awaiting_reply]
    if key == FILTER_PAYMENT:
        return [r for r in rows if r.payment_review]
    return [r for r in rows if not r.is_closed]


#: What the list says when a filter has nothing (m-24971198 gives «Pago por revisar»
#: its own words; the others keep the general line).
FILTER_EMPTY = "No hay conversaciones con este filtro."
FILTER_PAYMENT_EMPTY = (
    "No hay pagos por revisar. Cuando un cliente te mande su comprobante, su chat aparece aquí."
)


FILTER_PAYMENT_FAILED = "No pudimos revisar los pagos. Inténtalo otra vez en un momento."


def filter_empty_text(key: str, *, statuses_failed: bool = False) -> str:
    if key != FILTER_PAYMENT:
        return FILTER_EMPTY
    return FILTER_PAYMENT_FAILED if statuses_failed else FILTER_PAYMENT_EMPTY


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
    #: m-24945889: a location message (the pin «Cómo llegar» sends, or one a customer
    #: shares) — drawn with a pin icon and its text, never an empty bubble.
    is_location: bool = False
    #: «Ver en el mapa» for that pin — built ONLY from the stored numbers
    #: (`MessageRecord.latitude/longitude`), never from the text; "" without them.
    location_href: str = ""
    #: m-25018684: an inbound catalog cart — drawn with the shopping-bag icon.
    is_order: bool = False
    #: m-25027371: «Hoy» / «Ayer» / «12 oct» on the first message of each day (the same
    #: separators as Instagram's thread); the bubble then says only the clock.
    day_label: str = ""


VIEW_ON_MAP = "Ver en el mapa"
#: The text of a sent pin with no stored text (the backend's `LOCATION_SENT`).
LOCATION_SENT = "Ubicación enviada"


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


#: Sends the sender failed for good (m-24976894): one line per code, each with what to
#: do, so the owner never sees a bare «No se entregó» for them. The codes are the
#: backend's: `outbox.ERROR_*` imported; the file codes are the ones `seasonal_send`
#: raises as `SeasonalFileRefused(...)` (not exported as constants yet — a test pins
#: this mapping to exactly that set).
UNSENT_SEASONAL_WITHDRAWN = (
    "No se envió: la pieza dejó de estar aprobada o su temporada se archivó."
)
UNSENT_ATTACHMENT_REFUSED = (
    "No se envió: el archivo cambió o ya no está disponible. Elígelo otra vez y envíalo."
)
UNSENT_STICKER_SIZE = (
    "No se envió: el sticker no cumple el tamaño de WhatsApp (512 × 512, menos de 500 KB). "
    "Pide otro."
)
UNSENT_VIDEO_TOO_LARGE = "No se envió: el video pesa más de 16 MB. Pide otro."
UNSENT_BAD_FILE = "No se envió: el archivo no es válido. Pide otro."
#: `SeasonalFileRefused` codes (`whatsapp.seasonal_send.check_file`).
SEASONAL_FILE_FAILURES: dict[str, str] = {
    "not_sticker_size": UNSENT_STICKER_SIZE,
    "sticker_too_large": UNSENT_STICKER_SIZE,
    "video_too_large": UNSENT_VIDEO_TOO_LARGE,
    "not_a_sticker": UNSENT_BAD_FILE,
    "not_a_video": UNSENT_BAD_FILE,
}


def _unsent_lines() -> dict[str, str]:
    from qualify_api.whatsapp.outbox import (  # noqa: PLC0415
        ERROR_ATTACHMENT_REFUSED,
        ERROR_SEASONAL_WITHDRAWN,
    )

    return {
        ERROR_SEASONAL_WITHDRAWN: UNSENT_SEASONAL_WITHDRAWN,
        ERROR_ATTACHMENT_REFUSED: UNSENT_ATTACHMENT_REFUSED,
        **SEASONAL_FILE_FAILURES,
    }


def failure_label(code: str | None) -> str:
    """The `error`-tone line under a failed bubble. Neither Meta's text nor its code reach
    the owner (the code stays in the outbox row and the logs)."""
    if code == "window_closed" or code in {"131047", "131026"}:
        return "No se entregó: pasaron más de 24 horas desde su último mensaje."
    if code == "opted_out":
        return "No se entregó: esta persona pidió no recibir más promociones."
    lines = _unsent_lines()
    if code and code in lines:
        return lines[code]
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
    carts: Mapping[str, str] | None = None,
) -> MessageVM:
    """`carts` maps a cart message's `external_message_id` to its detail («3 productos ·
    COP 45.000», `cart_details`); a cart message not in it is worded without detail."""
    outbound = message.direction == "outbound"
    text = (message.text or "").strip()
    placeholder = False
    media_fields: dict[str, Any] = {}
    if not outbound and getattr(message, "has_media", False):
        media_fields = _media_fields(message, now=now, media=media or {}, loading=loading)
    location = (message.media_kind or "").lower() == "location"
    is_order = not outbound and (message.media_kind or "").lower() == "order"
    if not text and is_order:
        detail = (carts or {}).get(str(getattr(message, "external_message_id", "") or ""), "")
        text = CART_BUBBLE.format(detail=detail) if detail else CART_BUBBLE_NO_DETAIL
        placeholder = True
    elif not text:
        if outbound:
            from_kind = {
                "image": "[imagen]",
                "audio": "[audio]",
                "document": "[documento]",
                "video": "[video]",
                "location": LOCATION_SENT,
            }
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
        time_label=bubble_clock(message.posted_at, zone),
        tick=tick,
        tick_label=_TICK_LABELS.get(tick, ""),
        error_label=failure_label(message.delivery_error_code) if tick == "failed" else "",
        ad_origin_label=ad_origin_label(message),
        ad_origin_href=ad_origin_href(message),
        is_location=location,
        location_href=_pin_href(message) if location else "",
        is_order=is_order,
        **media_fields,
    )


def _pin_href(message: object) -> str:
    """Google Maps at a pin's stored coordinates ("" when the record has none or they are
    not numbers in range): the text is never used to build a link."""
    try:
        lat = float(str(getattr(message, "latitude", None)))
        lng = float(str(getattr(message, "longitude", None)))
    except (TypeError, ValueError):
        return ""
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or math.isnan(lat) or math.isnan(lng):
        return ""
    return map_href(f"{lat:.6f}", f"{lng:.6f}")


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
        time_label=bubble_clock(item.created_at, zone),
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
    if kind == "location":
        pin = payload.get("location")
        place = ""
        if isinstance(pin, Mapping):
            place = str(pin.get("name") or pin.get("address") or "")
        return f"Ubicación: {place}" if place else LOCATION_SENT
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
    carts: Mapping[str, str] | None = None,
) -> list[MessageVM]:
    """Messages and not-yet-sent outbox rows, chronological (oldest first). `media` /
    `loading` decorate the inbound media messages (see `MediaResolution`)."""
    keyed: list[tuple[datetime, int, MessageVM]] = []
    for m in messages:
        instant = m.posted_at or now
        vm = build_message_vm(m, now=now, zone=zone, media=media, loading=loading, carts=carts)
        keyed.append((instant, 0, vm))
    for item in unsent:
        keyed.append((item.created_at, 1, build_unsent_vm(item, now=now, zone=zone)))
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    # m-25027371: the day separators of the shared thread («Hoy», «Ayer», «12 oct»).
    return mark_days(
        [(instant, vm) for instant, _order, vm in keyed],
        zone,
        now,
        lambda vm, label: replace(vm, day_label=label),
    )


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


#: m-25018684 (spec `ux-carrito-pedido` §1–§2): the order card words where the order came
#: from. A menu order reads exactly as before; a catalog cart is not «confirmed» — the
#: customer sent it and the owner still has to look at it.
ORDER_TITLE_MENU = "Pedido confirmado"
ORDER_TITLE_CART = "Pedido desde tu catálogo"
UNLINKED_PRODUCT_NAME = "Producto sin nombre"
UNLINKED_CODE_LABEL = "Código en tu catálogo de WhatsApp:"
#: The backend does not cap a catalog code: the card shows at most this many characters.
MAX_CODE_CHARS = 64
#: A mismatched cart line names Galería's UNIT price when the record kept it
#: (`OrderLine.gallery_unit_price` / `gallery_currency`) — «cada uno» when the line has
#: more than one, so it is not read against the line total; an older record without it
#: says only that there is a difference.
PRICE_MISMATCH_LINE = "En tu Galería tiene otro precio"
PRICE_MISMATCH_AMOUNT = "En tu Galería: {price}"
PRICE_MISMATCH_AMOUNT_EACH = "En tu Galería: {price} cada uno"
#: A cart the backend cut to its first 100 lines (`OrderSummary.lines_truncated`).
ORDER_TRUNCATED_LINE = "Este pedido es muy largo: mostramos los primeros 100 productos."
PRICE_MISMATCH_LINK = "Revisar en tu Galería"
PRICE_MISMATCH_HREF = "/catalog"
CUSTOMER_NOTE_LABEL = "Nota del cliente"
NOTE_MORE_LABEL = "Ver el resto de la nota"
#: A note longer than this (characters or lines) shows its start and folds the rest.
NOTE_PREVIEW_CHARS = 160
NOTE_PREVIEW_LINES = 3
#: A cart with no payment yet: what the owner can do (nothing goes out by itself).
CART_CHARGE_HINT = "Para cobrarle, toca + y elige Formas de pago."
PREVIOUS_FROM_CART = "Desde tu catálogo"
PREVIOUS_FROM_MENU = "Por el menú"


def price_mismatch_notice(count: int) -> str:
    """The card's one warning for the lines whose catalog price is not Galería's."""
    if count <= 0:
        return ""
    what = "1 producto" if count == 1 else f"{count} productos"
    return (
        f"El precio de {what} en tu catálogo de WhatsApp no es el de tu Galería. "
        "El total usa el precio que vio tu cliente."
    )


def unlinked_notice(count: int) -> str:
    """By «Pedido listo»: the message names a product not in Galería by its code."""
    if count <= 0:
        return ""
    if count == 1:
        return "Un producto no está en tu Galería: en el mensaje saldrá con su código."
    return f"{count} productos no están en tu Galería: en el mensaje saldrán con su código."


def previous_orders_label(count: int, *, review: int = 0, awaiting: int = 0) -> str:
    """«2 pedidos anteriores · 1 pago por revisar» — the closed row names an unsettled
    payment, so it is not hidden inside the folded section (review first, else
    awaiting)."""
    if count <= 0:
        return ""
    label = "1 pedido anterior" if count == 1 else f"{count} pedidos anteriores"
    if review > 0:
        label += " · 1 pago por revisar" if review == 1 else f" · {review} pagos por revisar"
    elif awaiting > 0:
        label += f" · {awaiting} esperando el pago"
    return label


def split_note(note: str) -> tuple[str, str]:
    """(shown, folded) of a customer's note: a short note is all shown; a long one shows
    its first lines (cut at a space) and folds the rest behind «Ver el resto de la nota»."""
    lines = note.split("\n")
    head = "\n".join(lines[:NOTE_PREVIEW_LINES])
    if len(lines) <= NOTE_PREVIEW_LINES and len(note) <= NOTE_PREVIEW_CHARS:
        return note, ""
    if len(head) > NOTE_PREVIEW_CHARS:
        cut = head.rfind(" ", 0, NOTE_PREVIEW_CHARS)
        head = head[: cut if cut > 0 else NOTE_PREVIEW_CHARS]
    rest = note[len(head) :].lstrip()
    return (head.rstrip() + "…", rest) if rest else (note, "")


def short_code(code: str) -> str:
    return code if len(code) <= MAX_CODE_CHARS else code[:MAX_CODE_CHARS] + "…"


@dataclass(frozen=True)
class OrderLineVM:
    label: str
    amount: str
    #: An unlinked cart line: the raw catalog code (shown in the mono face).
    code: str = ""
    #: A cart line whose catalog price is not Galería's (muted second line).
    price_note: str = ""


@dataclass(frozen=True)
class OrderFieldVM:
    label: str
    value: str


@dataclass(frozen=True)
class PreviousOrderVM:
    """One archived order, read only: no actions (founder decision 3)."""

    origin_label: str  # «Desde tu catálogo · ayer 15:42»
    items_line: str  # «2 × Shawarma mixto, 1 × Producto sin nombre»
    summary_label: str  # «3 productos · COP 45.000»
    payment_label: str = ""
    payment_tone: str = "neutral"


@dataclass(frozen=True)
class OrderCardVM:
    present: bool
    lines: list[OrderLineVM] = field(default_factory=list)
    total_label: str = ""
    items_label: str = ""
    collected: list[OrderFieldVM] = field(default_factory=list)
    confirmed_label: str = ""
    title: str = ORDER_TITLE_MENU
    is_cart: bool = False
    #: The single warn notice for price differences ("" = none).
    price_notice: str = ""
    #: «Para cobrarle, …» — a cart with no payment yet ("" otherwise).
    charge_hint: str = ""
    #: «Este pedido es muy largo: …» — a cart the backend truncated ("" otherwise).
    truncated_line: str = ""
    #: The customer's note: what is shown, and the rest folded ("" = none).
    note: str = ""
    note_rest: str = ""
    #: By «Pedido listo»: lines not in Galería go out by their code ("" = none).
    unlinked_notice: str = ""
    previous: list[PreviousOrderVM] = field(default_factory=list)
    previous_label: str = ""


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


def order_total_label(order: OrderSummary) -> str:
    """The order's total; an order in several currencies gets one amount per currency
    («COP 15.000 + USD 10», as «Pedido listo» words it) — never a single made-up sum."""
    if order.mixed_currency:
        return " + ".join(
            format_money(amount, code or None) for code, amount in order.totals_by_currency.items()
        )
    return format_money(order.total, order.currency)


def _items_label(count: int) -> str:
    return f"{count} producto" if count == 1 else f"{count} productos"


def _unlinked(line: OrderLine) -> bool:
    return not line.linked and not line.name


def _line_name(line: OrderLine) -> str:
    return UNLINKED_PRODUCT_NAME if _unlinked(line) else (line.name or line.product_id)


def _price_note(line: OrderLine) -> str:
    """The muted mark of a mismatched cart line: Galería's unit price when known."""
    if line.gallery_unit_price is None:
        return PRICE_MISMATCH_LINE
    template = PRICE_MISMATCH_AMOUNT_EACH if line.qty > 1 else PRICE_MISMATCH_AMOUNT
    return template.format(price=format_money(line.gallery_unit_price, line.gallery_currency))


def order_summary_label(order: OrderSummary) -> str:
    """«3 productos · COP 45.000» — the cart bubble and a previous order's line."""
    return f"{_items_label(order.item_count)} · {order_total_label(order)}"


def build_order_card(
    order: OrderSummary | None,
    *,
    now: datetime,
    zone: tzinfo,
    previous: Sequence[PreviousOrder] = (),
    has_payment: bool = True,
) -> OrderCardVM:
    """`previous` are the thread's archived orders (newest first); `has_payment` is
    whether the chat has a payment record — `True` too when it could not be read, so a
    cart only gets the «Para cobrarle…» hint when there is certainly none."""
    if order is None:
        return EMPTY_ORDER
    cart = order.is_cart
    lines = []
    mismatches = 0
    for line in order.lines:
        total = line.line_total
        mismatch = cart and line.price_mismatch
        mismatches += 1 if mismatch else 0
        lines.append(
            OrderLineVM(
                label=f"{line.qty} × {_line_name(line)}",
                amount=format_money(total, line.currency or order.currency) if total else "",
                code=short_code(line.retailer_id or line.product_id) if _unlinked(line) else "",
                price_note=_price_note(line) if mismatch else "",
            )
        )
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
    # The customer's own words, as text (the page never interprets them).
    note = (order.note or "").strip() if cart else ""
    if note and order.note_truncated:
        note += "…"  # the backend kept only the first part of a very long note
    note_shown, note_rest = split_note(note) if note else ("", "")
    confirmed = ""
    if order.confirmed_at is not None:
        verb = "Llegó" if cart else "Confirmado"
        confirmed = f"{verb} {message_time(order.confirmed_at, now, zone)}"
    previous_vms = [build_previous_order(p, now=now, zone=zone) for p in previous]
    statuses = [p.payment.status if p.payment is not None else None for p in previous]
    return OrderCardVM(
        present=True,
        lines=lines,
        total_label=order_total_label(order),
        items_label=_items_label(order.item_count),
        collected=collected,
        confirmed_label=confirmed,
        title=ORDER_TITLE_CART if cart else ORDER_TITLE_MENU,
        is_cart=cart,
        price_notice=price_mismatch_notice(mismatches),
        charge_hint=CART_CHARGE_HINT if cart and not has_payment else "",
        truncated_line=ORDER_TRUNCATED_LINE if cart and order.lines_truncated else "",
        note=note_shown,
        note_rest=note_rest,
        unlinked_notice=unlinked_notice(sum(1 for line in order.lines if _unlinked(line))),
        previous=previous_vms,
        previous_label=previous_orders_label(
            len(previous_vms),
            review=statuses.count("review"),
            awaiting=statuses.count("awaiting"),
        ),
    )


def _status_labels() -> dict[str, str]:
    from qualify_api.whatsapp.payment_status import STATUS_LABELS  # noqa: PLC0415

    return dict(STATUS_LABELS)


def build_previous_order(
    previous: PreviousOrder, *, now: datetime, zone: tzinfo
) -> PreviousOrderVM:
    """The payment pill keeps the word it had when the order was replaced (no «only that
    day» rule here); an order without a payment status shows no pill."""
    order = previous.order
    origin = PREVIOUS_FROM_CART if order.is_cart else PREVIOUS_FROM_MENU
    when = message_time(order.confirmed_at, now, zone)
    status = (previous.payment.status or "") if previous.payment is not None else ""
    label = _status_labels().get(status, "")
    return PreviousOrderVM(
        origin_label=f"{origin} · {when}" if when else origin,
        items_line=", ".join(f"{line.qty} × {_line_name(line)}" for line in order.lines),
        summary_label=order_summary_label(order),
        payment_label=label,
        payment_tone=_PAYMENT_TONES.get(status, "neutral") if label else "neutral",
    )


def cart_details(
    order: OrderSummary | None,
    previous: Sequence[PreviousOrder] = (),
    cart_ids: Collection[str] = (),
) -> dict[str, str]:
    """`external_message_id` of each cart still on record → «3 productos · COP 45.000»,
    for its bubble. Only the ids `orders.cart_message_ids` names are kept."""
    out: dict[str, str] = {}
    for summary in [order, *(p.order for p in previous)]:
        if summary is None or not summary.is_cart:
            continue
        source = summary.source_message_id
        if source and source in cart_ids and source not in out:
            out[source] = order_summary_label(summary)
    return out


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
# The send panel (m-24945888; the «+» since m-24955785, docs/ux-whatsapp-menu-orbit.md)
# ======================================================================================
#
# A drawer with up to three steps — ① what to send → ② which one → ③ «Revisa y envía» —
# that queues nothing until the owner taps «Enviar». The backend
# (`qualify_api.whatsapp.attachments`) owns every rule (window, R2 copy, size/type,
# caption length, provenance); this section only words it and shapes the picks.

#: The composer's «+» (m-24955785, `ui.orbit_menu`): its accessible name.
PICK_MENU_LABEL = "Enviar algo al cliente"

#: The drawer's address (`?flujo=enviar&paso=N`, `ui/flow_history.py`): the phone's
#: «atrás» goes one step back; on step 1 it closes the drawer (N5).
PICK_FLOW = "enviar"
#: The address before m-24955785: only tidied away, never reopened.
LEGACY_PICK_FLOW = "foto-menu"
PICK_PRODUCTS = "products"
PICK_PIECES = "pieces"
PICK_MENU = "menu"
PICK_PHOTO = "photo"
#: m-24955648: the business's payment methods (`docs/ux-paso-de-pago.md` §5).
PICK_PAYMENTS = "payments"
#: m-24945889 (`docs/ux-whatsapp-atajos.md`): the marked piece, the shop's map point or
#: address, and «Fotos y videos» — whose first step «¿De dónde?» leads to Tus piezas or
#: De tu celular (no longer rows of the «+»).
PICK_OFFER = "offer"
PICK_DIRECTIONS = "directions"
PICK_MEDIA = "media"
#: m-24976895: the brand's approved stickers and videos (`docs/ux-stickers-videos.md` §3),
#: the third card of «¿De dónde?» — always shown since m-24986801 §4 (with nothing
#: approved it opens an empty state).
PICK_SEASONAL = "seasonal"
#: Every state the panel can be in.
PICK_SOURCES = frozenset(
    {
        PICK_PRODUCTS,
        PICK_PIECES,
        PICK_MENU,
        PICK_PHOTO,
        PICK_PAYMENTS,
        PICK_OFFER,
        PICK_DIRECTIONS,
        PICK_MEDIA,
        PICK_SEASONAL,
    }
)
#: What the «+» itself may open (the six rows); Tus piezas and De tu celular only
#: through «¿De dónde?».
PICK_ORBIT_SOURCES = frozenset(
    {PICK_PRODUCTS, PICK_OFFER, PICK_MENU, PICK_PAYMENTS, PICK_DIRECTIONS, PICK_MEDIA}
)
#: The sources reached through «Fotos y videos» (three steps: ¿De dónde? → elegir →
#: revisar).
MEDIA_SOURCES = frozenset({PICK_PIECES, PICK_PHOTO, PICK_SEASONAL})

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

#: The guarantee, on every «Revisa y envía» (m-24955785 §8).
NOTHING_SENT_UNTIL = "Nada sale sin que toques «Enviar»."
PICK_BACK_TO_CHAT = "Volver al chat"
PICK_BACK = "Atrás"

#: The «+»'s six rows (key, icon, text ≤ 16), top to bottom: what sells first (product,
#: offer, menu), then getting paid and getting there, the loose things last
#: (m-24945889 §1, approved by the founder 2026-11-08).
PICK_SOURCE_CARDS: tuple[tuple[str, str, str], ...] = (
    (PICK_PRODUCTS, "package", "Tus productos"),
    (PICK_OFFER, "tag", "Tu oferta"),
    (PICK_MENU, "list", "Tu menú"),
    (PICK_PAYMENTS, "wallet", "Formas de pago"),
    (PICK_DIRECTIONS, "map-pin", "Cómo llegar"),
    (PICK_MEDIA, "images", "Fotos y videos"),
)

#: «Fotos y videos» › «¿De dónde?» (key, icon, title, line).
MEDIA_TITLE = "¿De dónde?"
MEDIA_HELP = "Elige de dónde sale lo que le vas a mandar."
MEDIA_SOURCE_CARDS: tuple[tuple[str, str, str, str], ...] = (
    (PICK_PIECES, "images", "Tus piezas", "Lo que preparaste para tus redes."),
    (PICK_PHOTO, "smartphone", "De tu celular", "Una foto que ya tengas guardada."),
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
    "No es una foto: tu cliente toca el botón y elige. Nada sale sin que toques «Enviar»."
)
PHOTO_TITLE = "¿Qué foto?"
PHOTO_HELP = "Elige una foto que tengas guardada en tu celular."
PHOTO_PICK_LABEL = "Elegir una foto"
PHOTO_CHANGE_LABEL = "Elegir otra foto"
REVIEW_TITLE = "Revisa y envía"
REVIEW_HELP = (
    "Así le llega. Puedes cambiar el texto antes de enviar. Nada sale sin que toques «Enviar»."
)
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
#: WhatsApp → Tu número → Formas de pago (m-24955648).
PAYMENTS_ROUTE = "/whatsapp?tab=numero&sub=pagos"


def payments_href(return_to: str = "") -> str:
    """«Cambiar estos datos» (m-24971198): Formas de pago with `?volver=` — the chat's
    own address (`nav_url.conversation_href`: only the account and chat ids it already
    carries), so «‹ Volver al chat» leads back to that conversation."""
    from urllib.parse import urlencode  # noqa: PLC0415

    if not return_to:
        return PAYMENTS_ROUTE
    return f"{PAYMENTS_ROUTE}&{urlencode({'volver': return_to})}"


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
#: m-24945889 §4: a video over WhatsApp's 16 MB (`attachments.MAX_VIDEO_BYTES`).
VIDEO_TOO_LARGE = "Este archivo es muy pesado para WhatsApp. Créalo de nuevo más corto."
VIDEO_NOT_VIDEO = "Ese archivo no se puede enviar como video. Elige otra pieza."
VIDEO_BADGE = "Video"
VIDEO_HEAVY_PILL = "Muy pesado"
CREATE_AGAIN_LABEL = "Crear de nuevo"
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
    if reason == "video_too_large":
        return VIDEO_TOO_LARGE
    if reason == "not_a_video":
        return VIDEO_NOT_VIDEO
    if reason == "no_location":
        return DIRECTIONS_NO_LOCATION
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
    if source == PICK_DIRECTIONS:
        return SEND_TEXT_FAILED
    if source == PICK_SEASONAL:
        return SEASONAL_SEND_FAILED
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
    # m-24945889 (optional on older picks): "image" | "video", the MP4's size, > 16 MB
    # media_type: str; bytes: int | None; too_large: bool


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
    #: m-24945889 §4: a video piece (its poster is `thumb_url`; nothing plays by itself).
    is_video: bool = False
    size_label: str = ""  # «3,2 MB» when the store told its size
    #: Over WhatsApp's 16 MB: «Muy pesado» on the card, «Enviar» off on the review.
    too_large: bool = False
    #: The business's marked offer («Tu oferta» badge on the card).
    is_offer: bool = False


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


def size_label(size: int | None) -> str:
    """«3,2 MB» / «850 KB» (Spanish decimal comma); "" when unknown."""
    if not size or size <= 0:
        return ""
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


def build_piece_cards(
    picks: Iterable[PiecePickLike], zone: tzinfo | None = None, *, offer_id: str = ""
) -> list[PieceCardVM]:
    cards = []
    for p in picks:
        label, tone, unapproved = _piece_status(p.status, getattr(p, "approved_at", None), zone)
        count = int(p.image_count or 1)
        video = getattr(p, "media_type", "image") == "video"
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
                photos_label=f"1 de {count} fotos" if count > 1 and not video else "",
                alt=p.title or "Pieza",
                is_video=video,
                size_label=size_label(getattr(p, "bytes", None)) if video else "",
                too_large=video and bool(getattr(p, "too_large", False)),
                is_offer=bool(offer_id) and str(p.id) == offer_id,
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


def pick_total_steps(source: str, *, single: bool = False) -> int:
    """Steps after the «+» (m-24955785 §4): choose → «Revisa y envía»; Tu menú, Tu
    oferta, Cómo llegar and a single payment method, only the review; «Fotos y videos»
    adds «¿De dónde?» in front (m-24945889 §1)."""
    if source in (PICK_MENU, PICK_OFFER, PICK_DIRECTIONS) or (source == PICK_PAYMENTS and single):
        return 1
    if source == PICK_MEDIA or source in MEDIA_SOURCES:
        return 3
    return 2


SEASONAL_LINE = "Para saludar y celebrar con tu marca."
SEASONAL_TITLE = "¿Qué le mandas?"
SEASONAL_HELP = "Toca uno para ver cómo le llega."
SEASONAL_REVIEW_HELP = "Así le llega. Nada sale sin que toques «Enviar»."
SEASONAL_EARLIER = "De otras temporadas"
SEASONAL_STICKERS_TAB = "Stickers"
SEASONAL_VIDEOS_TAB = "Videos"
SEASONAL_STICKER_ALONE = "Los stickers llegan solos, sin texto."
SEASONAL_CAPTION_LABEL = "Texto que acompaña el video (opcional)"
SEASONAL_SEND_FAILED = (
    "No pudimos enviar el sticker o el video. Revisa tu conexión y vuelve a intentarlo."
)
SEASONAL_FAILED = "No pudimos traer tus stickers y videos. Vuelve a intentarlo en un momento."

# m-24986801 §4 a): the card is always there; with nothing approved it says so and its
# step is an empty state that leads to approving or creating them — nothing is sent.
SEASONAL_EMPTY_CARD = "Stickers y videos de tu marca"
SEASONAL_EMPTY_LINE = "Aún no tienes: créalos para esta temporada."
SEASONAL_PENDING_TITLE = "Tienes {n} {what} esperando tu aprobación"
SEASONAL_PENDING_TEXT = "Apruébalos y quedan listos para mandar desde aquí."
SEASONAL_PENDING_ACTION = "Revisarlos en Por aprobar"
SEASONAL_PENDING_HREF = "/drafts?ver=stickers"
SEASONAL_EMPTY_TITLE = "Aún no tienes stickers ni videos"
SEASONAL_EMPTY_TEXT = (
    "Los creamos con tu logo y tus colores en Tu marca. Tardan unos minutos: cuando los "
    "apruebes, aparecen aquí para mandarlos."
)
SEASONAL_CREATE_ACTION = "Crear para esta temporada"
#: Tu marca › «Stickers y videos de tu marca», with «Crear para esta temporada» open
#: (`SeasonalState.open_from_query`). m-25017173: WhatsApp › Chats no longer has a
#: stickers sub-tab; the library lives in Tu marca. `?volver=` gives the owner Tu marca's
#: way back («Volver a tus chats»), read there through `catalog_vm.safe_return_path`.
SEASONAL_CREATE_HREF = (
    f"{SEASONAL_LIBRARY_CREATE_HREF}&{urlencode({RETURN_PARAM: CHATS_RETURN_PATH})}"
)


def seasonal_pending_title(count: int) -> str:
    what = "sticker o video" if count == 1 else "stickers o videos"
    return SEASONAL_PENDING_TITLE.format(n=count, what=what)


def seasonal_card_title(stickers: int, videos: int) -> str:
    """«Stickers y videos de tu marca», or the one kind there is."""
    if stickers and not videos:
        return "Stickers de tu marca"
    if videos and not stickers:
        return "Videos de tu marca"
    return "Stickers y videos de tu marca"


@dataclass(frozen=True)
class SeasonalPickVM:
    """One approved sticker or video in «¿Qué le mandas?» (nothing unapproved ever)."""

    id: str = ""
    is_video: bool = False
    season_label: str = ""
    #: The current season (the most recently approved, first in the backend's order).
    current: bool = False
    src: str = ""
    alt: str = ""
    #: m-25017912: a sticker of the owner's product («De tus productos»), listed after the
    #: seasons (founder 2026-11-12).
    product: bool = False


EMPTY_SEASONAL = SeasonalPickVM()
#: The group title of the product stickers in «¿Qué le mandas?».
SEASONAL_PRODUCTS = "De tus productos"


def build_seasonal_picks(rows: Iterable[Any], src_for: Any = None) -> list[SeasonalPickVM]:
    """The backend's approved list (current season first) as cards; anything that is not
    `approved` is dropped here too."""
    picks: list[SeasonalPickVM] = []
    current = ""
    for row in rows:
        # the backend's list is approved-only; a row that says otherwise is dropped anyway
        if str(getattr(row, "status", "approved") or "approved") != "approved":
            continue
        key = str(getattr(row, "season_key", "") or getattr(row, "season_label", ""))
        product = key == PRODUCT_SEASON_KEY
        if not product:
            current = current or key
        video = str(getattr(row, "kind", "")) == "video"
        label = str(getattr(row, "season_label", "") or "")
        message = product_message(row)
        picks.append(
            SeasonalPickVM(
                id=str(row.id),
                is_video=video,
                season_label=label,
                current=not product and key == current,
                src=src_for(row) if src_for else "",
                alt=(
                    f"Sticker {PRODUCT_RECIPES.get(str(getattr(row, 'recipe', '')), '')} "
                    f"que dice «{message}»".replace("  ", " ")
                    if message
                    else f"{'Video' if video else 'Sticker'} de «{label}»"
                ),
                product=product,
            )
        )
    return picks


def pick_step_title(
    step: int, source: str, *, single: bool = False, seasonal_empty: bool = False
) -> str:
    if source == PICK_SEASONAL and seasonal_empty and step > 1:
        return SEASONAL_EMPTY_CARD  # the empty state carries its own title and words
    if source == PICK_MENU:
        return MENU_TITLE
    if source == PICK_DIRECTIONS:
        return DIRECTIONS_TITLE
    if source == PICK_MEDIA or (source in MEDIA_SOURCES and step <= 1):
        return MEDIA_TITLE
    if step >= pick_total_steps(source, single=single):
        return REVIEW_TITLE
    return {
        PICK_PRODUCTS: PRODUCTS_TITLE,
        PICK_PIECES: PIECES_TITLE,
        PICK_SEASONAL: SEASONAL_TITLE,
        PICK_PHOTO: PHOTO_TITLE,
        PICK_PAYMENTS: PAYMENTS_TITLE,
    }.get(source, REVIEW_TITLE)


def pick_step_help(
    step: int, source: str, *, single: bool = False, seasonal_empty: bool = False
) -> str:
    if source == PICK_SEASONAL and seasonal_empty and step > 1:
        return ""
    if source == PICK_MENU:
        return MENU_HELP
    if source == PICK_DIRECTIONS:
        return DIRECTIONS_HELP
    if source == PICK_MEDIA or (source in MEDIA_SOURCES and step <= 1):
        return MEDIA_HELP
    if step >= pick_total_steps(source, single=single):
        if source == PICK_SEASONAL:
            return SEASONAL_REVIEW_HELP
        return PAYMENT_REVIEW_HELP if source == PICK_PAYMENTS else REVIEW_HELP
    return {
        PICK_PRODUCTS: PRODUCTS_HELP,
        PICK_PIECES: PIECES_HELP,
        PICK_SEASONAL: SEASONAL_HELP,
        PICK_PHOTO: PHOTO_HELP,
        PICK_PAYMENTS: PAYMENTS_HELP,
    }.get(source, "")


# ======================================================================================
# Tu oferta and Cómo llegar (m-24945889, `docs/ux-whatsapp-atajos.md` §2–§3)
# ======================================================================================

OFFER_BADGE = "Tu oferta"
#: More days than this and the review asks «¿Sigue vigente?» (never blocks «Enviar»).
OFFER_STALE_DAYS = 14
OFFER_CHANGE = "Cambiar tu oferta"
OFFER_EMPTY = (
    "Aún no marcas tu oferta",
    "Elige una pieza aprobada en Por aprobar o en tu Planificador y toca «Usar como tu oferta».",
)
OFFER_GONE = (
    "Tu oferta ya no está disponible",
    "Elige otra pieza aprobada en Por aprobar y toca «Usar como tu oferta».",
)
OFFER_GO = "Ir a Por aprobar"
DRAFTS_ROUTE = "/drafts"
OFFER_FAILED = "No pudimos traer tu oferta. Vuelve a intentarlo en un momento."

DIRECTIONS_TITLE = "Así le llega tu ubicación"
DIRECTIONS_HELP = (
    "Le llega tu local en el mapa, o tu dirección con un enlace. Nada sale sin que toques «Enviar»."
)
DIRECTIONS_EMPTY = (
    "Aún no tienes la dirección de tu local",
    "Escríbela una vez en Tu número › Perfil y la mandas con un toque.",
)
DIRECTIONS_COMPLETE = "Completar mi dirección"
DIRECTIONS_NO_POINT = "Si pones tu local en el mapa, le llega el mapa con la ruta."
DIRECTIONS_PUT_ON_MAP = "Ponerlo en el mapa"
DIRECTIONS_FAILED = "No pudimos traer la dirección de tu local. Vuelve a intentarlo en un momento."
#: `AttachmentRefused("no_location")` at send time (the address was removed meanwhile).
DIRECTIONS_NO_LOCATION = (
    "Falta la dirección de tu local. Escríbela en Tu número › Perfil y vuelve a intentarlo."
)
#: WhatsApp → Tu número → Perfil (where the address and the map point live).
PROFILE_ROUTE = "/whatsapp?tab=numero&sub=perfil"


def offer_marked_label(marked_at: datetime | None, now: datetime, zone: tzinfo) -> str:
    """«marcada hoy» · «marcada ayer» · «marcada hace N días» (by local calendar day)."""
    days = offer_age_days(marked_at, now, zone)
    if days <= 0:
        return "marcada hoy"
    if days == 1:
        return "marcada ayer"
    return f"marcada hace {days} días"


def offer_age_days(marked_at: datetime | None, now: datetime, zone: tzinfo) -> int:
    if marked_at is None:
        return 0
    return max(0, (_local(now, zone).date() - _local(marked_at, zone).date()).days)


def offer_stale_note(days: int) -> str:
    """The non-blocking question past 14 days ("" before)."""
    if days <= OFFER_STALE_DAYS:
        return ""
    return f"La marcaste hace {days} días. ¿Sigue vigente?"


@dataclass(frozen=True)
class OfferVM:
    """«Tu oferta» in the panel: read, and either a piece to review or an empty state."""

    present: bool = False  # read (or failed: `pick_error` says so)
    marked: bool = False  # a piece is marked for this business
    gone: bool = False  # marked, but no longer sendable from here
    piece: PieceCardVM = PieceCardVM()
    marked_label: str = ""
    stale_note: str = ""


EMPTY_OFFER = OfferVM()


def build_offer(
    marked_id: str,
    marked_at: datetime | None,
    cards: Sequence[PieceCardVM],
    now: datetime,
    zone: tzinfo,
) -> OfferVM:
    if not marked_id:
        return OfferVM(present=True)
    card = next((c for c in cards if c.id == marked_id), None)
    if card is None or card.unapproved:
        return OfferVM(present=True, marked=True, gone=True)
    days = offer_age_days(marked_at, now, zone)
    return OfferVM(
        present=True,
        marked=True,
        piece=replace(card, is_offer=True),
        marked_label=offer_marked_label(marked_at, now, zone),
        stale_note=offer_stale_note(days),
    )


@dataclass(frozen=True)
class DirectionsVM:
    """«Cómo llegar»: what goes out — the map pin (with a point) or the address text."""

    present: bool = False
    empty: bool = True  # neither a point nor an address: the empty state
    has_point: bool = False
    name: str = ""
    address: str = ""
    #: The exact text a customer gets without a point (the backend's builder).
    text: str = ""
    #: Google Maps at the point, for the owner to check (never sent from here).
    map_href: str = ""


EMPTY_DIRECTIONS = DirectionsVM()


def map_href(latitude: Any, longitude: Any) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"


# ======================================================================================
# Payment (m-24955648, `docs/ux-paso-de-pago.md` §4–§5)
# ======================================================================================

#: The picker's «Formas de pago».
PAYMENTS_TITLE = "¿Cuál forma de pago?"
PAYMENTS_HELP = "Toca una para ver cómo le llega."
PAYMENT_REVIEW_HELP = (
    "Así le llega. Estos datos se cambian en Formas de pago, no aquí, para no cambiar una "
    "cuenta por error. Nada sale sin que toques «Enviar»."
)
PAYMENTS_EMPTY_TITLE = "Aún no cargas tus formas de pago"
PAYMENTS_EMPTY_TEXT = "Cárgalas una vez y desde aquí se las mandas a tu cliente con un toque."
PAYMENTS_ADD = "Agregar forma de pago"
PAYMENTS_CHANGE = "Cambiar estos datos"
PAYMENTS_FAILED = "No pudimos traer tus formas de pago. Inténtalo otra vez."
PAYMENT_GONE = "Esa forma de pago ya no se ofrece. Elige otra."

#: The order card and its sheet (§4).
PAYMENT_RECEIVED_BUTTON = "Pago recibido"
PAYMENT_NOT_FOUND_BUTTON = "No lo encuentro"
PAYMENT_CONFIRM_HINT = "Busca la referencia en tu banco antes de confirmar."
PAYMENT_CONFIRM_SEND = "Enviar y marcar pagado"
PAYMENT_CONFIRM_NOT_YET = "Todavía no"
PAYMENT_MESSAGE_LABEL = "El mensaje que le llega"
PAYMENT_WINDOW_CLOSED = (
    "Pasaron más de 24 horas desde su último mensaje y WhatsApp ya no deja escribirle libre. "
    "Márcalo pagado y avísale con un mensaje aprobado."
)
PAYMENT_MARK_SILENT = "Marcar pagado sin avisar"
PAYMENT_PAID_TOAST = "Listo: lo marcamos pagado y le avisamos a tu cliente."
PAYMENT_PAID_SILENT_TOAST = "Listo: lo marcamos pagado. Avísale con un mensaje aprobado."
PAYMENT_CONFIRM_FAILED = "No pudimos marcar el pago. Inténtalo otra vez en un minuto."
PAYMENT_ALREADY = "Este pago ya estaba marcado como recibido."
PAYMENT_MESSAGE_EMPTY = "Escribe el mensaje para tu cliente."
PAYMENT_NOT_FOUND_NOTE = "Revisa el mensaje y toca «Enviar» para mandarlo."

_PAYMENT_TONES: dict[str, str] = {
    "awaiting": "neutral",
    "review": "warn",
    "on_delivery": "neutral",
    "received": "ok",
}
_CHOICE_WORDS: dict[str, str] = {"other": "quiere otra", "none": "no eligió"}
_CURRENCY_WORDS: dict[str, str] = {
    "VES": "en bolívares",
    "COP": "en pesos",
    "UYU": "en pesos",
    "USD": "en dólares",
    "USDT": "en USDT",
    "EUR": "en euros",
}


def payment_confirm_title(name: str) -> str:
    """«¿Ya te llegó el pago de María?»."""
    clean = (name or "").strip()
    return f"¿Ya te llegó el pago de {clean}?" if clean else "¿Ya te llegó el pago?"


@dataclass(frozen=True)
class PaymentVM:
    """The chat's payment, for the list pill, the header and the order card."""

    present: bool = False
    status: str = ""
    label: str = ""
    tone: str = "neutral"
    method_line: str = ""  # «Paga con: Pago móvil (en bolívares)»
    can_confirm: bool = False
    confirmed_line: str = ""  # «Pago recibido · lo confirmó Ana · 15:42»
    #: The message «Pago recibido» starts with — per order (pay on delivery gets its own).
    confirm_text: str = ""


EMPTY_PAYMENT = PaymentVM()


def payment_pill(
    status: str | None, label: str, confirmed_at: datetime | None, now: datetime, zone: tzinfo
) -> tuple[str, str]:
    """(label, tone) of the chat's pill: «Pago recibido» only the day it was confirmed."""
    if not status:
        return "", "neutral"
    if status == "received":
        if confirmed_at is None or _local(confirmed_at, zone).date() != _local(now, zone).date():
            return "", "neutral"
    return label, _PAYMENT_TONES.get(status, "neutral")


def build_payment(
    payment: Any | None,
    *,
    now: datetime,
    zone: tzinfo,
    agents: Mapping[str, AgentVM] | None = None,
) -> PaymentVM:
    """`payment` is `qualify_api.whatsapp.payment_status.PaymentStatus` (or None)."""
    if payment is None:
        return EMPTY_PAYMENT
    status = payment.status or ""
    label, tone = payment_pill(payment.status, payment.label, payment.confirmed_at, now, zone)
    if payment.method_name:
        how = (
            "al recibir"
            if payment.pay_on_delivery
            else _CURRENCY_WORDS.get((payment.currency or "").upper(), "")
        )
        method_line = f"Paga con: {payment.method_name}" + (f" ({how})" if how else "")
    else:
        method_line = f"Forma de pago: {_CHOICE_WORDS.get(payment.choice, 'no eligió')}"
    confirmed = ""
    if status == "received":
        who = ""
        if payment.confirmed_by is not None:
            agent = (agents or {}).get(str(payment.confirmed_by))
            who = f" · lo confirmó {agent.name}" if agent is not None else ""
        when = message_time(payment.confirmed_at, now, zone)
        confirmed = "Pago recibido" + who + (f" · {when}" if when else "")
    return PaymentVM(
        present=True,
        status=status,
        label=label,
        tone=tone,
        method_line=method_line,
        can_confirm=status != "received",
        confirmed_line=confirmed,
        confirm_text=str(getattr(payment, "confirm_text", "") or ""),
    )


def with_payment_pills(
    rows: Sequence[ThreadRowVM], statuses: Mapping[str, Any]
) -> list[ThreadRowVM]:
    """The list's rows with their payment marks (one `payment_statuses` read for all):
    «Pago por revisar» and «Esperando el pago» are what the row can show; «Pago
    recibido» / «Paga al recibir» stay in the chat's header."""
    out: list[ThreadRowVM] = []
    for row in rows:
        payment = statuses.get(row.thread_id)
        if payment is None:
            out.append(row)
            continue
        out.append(
            replace(
                row,
                payment_review=payment.status == "review",
                payment_awaiting=payment.status == "awaiting",
            )
        )
    return out


def carry_payment_marks(
    rows: Sequence[ThreadRowVM], previous: Sequence[ThreadRowVM]
) -> list[ThreadRowVM]:
    """When the statuses read fails: each chat keeps the payment pill and mark it had
    (by thread id), so a refresh never makes «Pago por revisar» flicker."""
    before = {r.thread_id: r for r in previous}
    out: list[ThreadRowVM] = []
    for row in rows:
        old = before.get(row.thread_id)
        if old is None:
            out.append(row)
            continue
        out.append(
            replace(
                row,
                payment_review=old.payment_review,
                payment_awaiting=old.payment_awaiting,
            )
        )
    return out


@dataclass(frozen=True)
class PaymentCardVM:
    """«¿Cuál forma de pago?»: one `choice_card`."""

    id: str = ""
    name: str = ""
    currency_label: str = ""
    updated_label: str = ""
    thumb_url: str = ""
    has_qr: bool = False
    alt: str = ""


def build_payment_cards(picks: Sequence[Any], zone: tzinfo, now: datetime) -> list[PaymentCardVM]:
    return [
        PaymentCardVM(
            id=p.id,
            name=p.name,
            currency_label=p.currency_label,
            updated_label=f"Actualizado el {format_day(p.updated_at, zone, now)}"
            if p.updated_at
            else "",
            thumb_url=p.thumb_url,
            has_qr=p.has_qr,
            alt=f"QR de {p.name}",
        )
        for p in picks
    ]
