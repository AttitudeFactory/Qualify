"""View-models for `/conversations` (QUA-226, E2) — the security boundary of the screen.

Same discipline as `whatsapp_chats_vm.py`: `ConversationsState` holds only the frozen
dataclasses below, every instant is PRE-FORMATTED here in the tenant's zone (the browser
never receives a raw `datetime`), and no field can carry a token, a ciphertext or a key
(`test_conversations_vm_has_no_credential_fields`). States are TONES (`ok`/`warn`/
`error`/`info`/`neutral`, docs/design-system.md §3.2), never a Radix colour.

Inputs are the backend's own read shapes — `ThreadView` / `ThreadRecord` /
`MessageRecord` / `SyncStateRecord` / `OutboxRecord` / `ConversationDraft` from
`qualify_api.conversations` — taken by duck type, so this module imports neither
SQLAlchemy nor Reflex and every mapping is asserted by plain unit tests
(`test_conversations_vm.py`).

What this module words, and never re-derives:

- the **attention state** («pendiente / leída / respondida») is `service.attention_state`,
  computed from the thread's instants; here it only gets a label and a tone;
- the **24 h window** is `window.window_state`; here it becomes plain words («Puedes
  responder hasta las 17:47», «Te quedan 12 min», «Ya no puedes responder»);
- the **access verdict** (`conversation_sync_state.access_status`) is the sync's; here it
  becomes the banner the person sees — and `unknown` is NEVER rendered as «no hay
  mensajes»: it is a «por verificar» state with its own words (§6.4). A failed sync is
  NOT a banner: it is a short toast, once per failure (`AccessVM.failure_key`);
- the **receipt** of an outbound message is `messages.delivery_status` (`sent` when Meta
  accepted it, `read` when the counterpart's `messaging_seen` arrived): «Enviado» /
  «Visto». Instagram exposes no «delivered», so there is none to word;
- the **counterpart's identity** is the thread's profile (name, handle, picture — the
  User Profile API, refreshed by the sync); without one, the handle of their latest
  message, then initials over a stable hue.

**Media.** An inbound attachment renders from the channel's CDN URL (`media_url`); an
outbound one from the R2 object Qualify sent, through the `/r2media/<token>` path the
provider issues (`media_src`). The view-model never builds a URL itself.

**Drafts (E4).** A model's suggestion is a `DraftVM` the composer shows as a chip; the
text lands in the box for the person to edit. `needs_review` is the generator's verdict
(it could not ground something), worded here, never decided here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any, Final, Protocol

from .whatsapp_chats_vm import format_day, message_time, relative_time

# ======================================================================================
# Copy and limits
# ======================================================================================

#: Instagram Messaging's text limit per message. The composer no longer caps the text:
#: a longer reply is sent as consecutive messages (`service.split_reply`); the UI only
#: says in how many (`reply_parts_hint`).
MAX_REPLY_CHARS = 1000
#: The newest page of a conversation. E1's repository exposes `limit` but no cursor:
#: «cargar anteriores» is a documented follow-up (see `docs/conversaciones-limitaciones-
#: meta.md`), not a button here.
MESSAGES_PAGE = 50
#: The thread list: one account's conversations, newest activity first.
THREADS_LIMIT = 200

#: Attachments a reply may carry (`send-message.md` «Limitations»): JPEG/PNG ≤ 8 MB,
#: audio (aac/m4a/wav/mp4) ≤ 25 MB, video (mp4/mov/webm/ogg/avi) ≤ 25 MB, PDF ≤ 25 MB.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 25 * 1024 * 1024
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
IMAGE_ACCEPT: dict[str, list[str]] = {"image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"]}
AUDIO_ACCEPT: dict[str, list[str]] = {
    "audio/mpeg": [".mp3"],
    "audio/mp4": [".m4a", ".mp4"],
    "audio/aac": [".aac"],
    "audio/wav": [".wav"],
    "audio/x-wav": [".wav"],
    "audio/wave": [".wav"],
    "audio/x-m4a": [".m4a"],
}
VIDEO_ACCEPT: dict[str, list[str]] = {
    "video/mp4": [".mp4"],
    "video/quicktime": [".mov"],
    "video/webm": [".webm"],
    "video/ogg": [".ogv"],
    "video/x-msvideo": [".avi"],
}
DOCUMENT_ACCEPT: dict[str, list[str]] = {"application/pdf": [".pdf"]}
#: The gallery button takes a photo or a video in one picker.
MEDIA_ACCEPT: dict[str, list[str]] = {**IMAGE_ACCEPT, **VIDEO_ACCEPT}
MAX_MEDIA_BYTES = max(MAX_IMAGE_BYTES, MAX_VIDEO_BYTES)
_AUDIO_TYPES = frozenset(AUDIO_ACCEPT)
_IMAGE_TYPES = frozenset(IMAGE_ACCEPT)
_VIDEO_TYPES = frozenset(VIDEO_ACCEPT)
_DOCUMENT_TYPES = frozenset(DOCUMENT_ACCEPT)
#: A voice note (`assets/qualify-voice.js`): 16 kHz mono WAV, at most this long.
MAX_VOICE_SECONDS = 180
VOICE_CONTENT_TYPE = "audio/wav"

CHANNEL_LABELS: dict[str, str] = {"dm": "Instagram Direct"}
NO_MESSAGES_YET = "Sin mensajes todavía"
OUTBOUND_PREFIX = "Tú: "
WINDOW_CLOSED_NOTICE = (
    "Ya no puedes responder: pasaron más de 24 h desde el último mensaje de la persona. "
    "Instagram solo permite contestar dentro de ese plazo; cuando vuelva a escribir, "
    "podrás responder de nuevo."
)
WINDOW_CLOSED_SHORT = "No se puede responder"
#: The rule itself, said once, so «hasta mañana a las 19:27» is never a bare deadline.
WINDOW_RULE = (
    "Instagram solo permite responder durante las 24 h siguientes al último mensaje de la persona."
)

FILTER_ALL = "all"
FILTER_PENDING = "pending"
FILTER_READ = "read"
FILTER_ANSWERED = "answered"
FILTERS: tuple[tuple[str, str], ...] = (
    (FILTER_ALL, "Todas"),
    (FILTER_PENDING, "Pendientes"),
    (FILTER_READ, "Leídas"),
    (FILTER_ANSWERED, "Respondidas"),
)
FILTER_KEYS = frozenset(key for key, _label in FILTERS)
DEFAULT_FILTER = FILTER_ALL

#: `service.AttentionState` value → (label, tone).
ATTENTION_PILLS: dict[str, tuple[str, str]] = {
    "pending": ("Pendiente", "warn"),
    "read": ("Leída", "info"),
    "answered": ("Respondida", "ok"),
    "none": ("Sin mensajes", "neutral"),
}

#: `messages.media_type` → (what the list says, the Lucide icon, the bubble control).
MEDIA_IMAGE = "image"
MEDIA_AUDIO = "audio"
MEDIA_VIDEO = "video"
MEDIA_FILE = "file"
MEDIA_STICKER = "sticker"
_MEDIA_KINDS: dict[str, tuple[str, str, str]] = {
    "image": ("Foto", "image", MEDIA_IMAGE),
    "sticker": ("Me gusta", "heart", MEDIA_STICKER),
    "audio": ("Audio", "mic", MEDIA_AUDIO),
    "video": ("Video", "video", MEDIA_VIDEO),
    "document": ("Archivo", "file-text", MEDIA_FILE),
    "interactive": ("Respuesta rápida", "mouse-pointer-click", ""),
    # Meta's `is_unsupported`: a voice note, or any content the API does not expose.
    # Verified 2026-10-16: EVERY audio comes back so — the person's and our own echoes.
    "other": (
        "Contenido que Instagram no muestra aquí (p. ej. una nota de voz)",
        "circle-slash",
        "",
    ),
}
UNSUPPORTED_PREVIEW = "Nota de voz u otro contenido"
#: What the attachment chip says per kind.
ATTACHMENT_READY: dict[str, str] = {
    MEDIA_IMAGE: "Foto lista para enviar",
    MEDIA_AUDIO: "Audio listo para enviar",
    MEDIA_VIDEO: "Video listo para enviar",
    "document": "PDF listo para enviar",
}

#: `conversation_outbox.error_code` → the line under a bubble that did not go out.
_FAILURE_LABELS: dict[str, str] = {
    "window_closed": "No se envió: ya habían pasado las 24 h para responder.",
    "no_sender": "No se envió: este canal no tiene envío configurado.",
    "no_media_linker": "No se envió: el servidor no puede publicar adjuntos todavía.",
    "auth_error": "No se envió: la conexión de la cuenta caducó. Reconéctala.",
    "thread_missing": "No se envió: la conversación ya no existe.",
    "connection_missing": "No se envió: la cuenta ya no está conectada.",
    "send_ambiguous": (
        "Instagram no confirmó este envío a tiempo. Puede haber salido: revisa la "
        "conversación antes de reenviarlo."
    ),
}

#: What the ❤️ button sends: the emoji as text. Instagram's `like_heart` sticker sent
#: through the API arrives as a WHITE heart in the person's app (observed 2026-10-16),
#: the emoji as the big red one.
HEART_TEXT = "❤️"

_TICK_LABELS: dict[str, str] = {
    "sent": "Enviado",
    "read": "Visto",
    "failed": "No se envió",
    "queued": "Pendiente de envío",
}

#: `suggest.GATE_*` → what the toast says when no suggestion is possible.
SUGGESTION_REFUSALS: dict[str, str] = {
    "last_message_outbound": "Ya respondiste el último mensaje: no hay nada nuevo que sugerir.",
    "inbound_without_text": "El último mensaje es un adjunto sin texto: no hay qué sugerir.",
    "window_closed": "Ya no se puede responder a esta conversación (pasaron 24 h).",
    "no_messages": "Esta conversación todavía no tiene mensajes.",
}
SUGGESTION_REFUSED_DEFAULT = "No se pudo sugerir una respuesta para este mensaje."
SUGGESTION_NOTE = "Sugerencia de IA · revísala y edítala antes de enviar"
SUGGESTION_REVIEW_NOTE = "Sugerencia de IA · requiere revisión: hay datos sin confirmar"


# ======================================================================================
# Input shapes (duck-typed: the backend's dataclasses satisfy them)
# ======================================================================================


class _Window(Protocol):
    @property
    def is_open(self) -> bool: ...

    @property
    def closes_at(self) -> datetime | None: ...


class ThreadLike(Protocol):
    id: Any
    connection_id: Any
    channel: str
    counterpart_external_id: str
    status: str
    last_message_at: datetime | None
    last_inbound_at: datetime | None


class ThreadViewLike(Protocol):
    thread: ThreadLike
    attention: Any  # `AttentionState` (a StrEnum) or its value
    window: _Window


class MessageLike(Protocol):
    id: Any
    direction: str
    text: str | None
    posted_at: datetime | None
    ingested_at: datetime
    delivery_status: str | None
    media_type: str | None
    author_username: str | None


class SyncStateLike(Protocol):
    access_status: str
    access_detail: str | None
    access_checked_at: datetime | None
    last_sync_finished_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None


class DraftLike(Protocol):
    id: Any
    generated_text: str
    needs_review: bool
    grounding: Mapping[str, Any]


@dataclass(frozen=True)
class ThreadExtra:
    """What the list needs beyond `ThreadRecord` and the provider reads from `messages`:
    the counterpart's handle (from their latest inbound) and the last message's preview."""

    username: str | None = None
    preview: str | None = None
    preview_direction: str | None = None
    preview_media_type: str | None = None


@dataclass(frozen=True)
class UnsentItem:
    """A `conversation_outbox` row of this thread that has not become a `messages` row
    yet (pending / sending / failed / dead). `text` is already extracted from the body."""

    id: str
    status: str
    text: str
    created_at: datetime
    error_code: str | None = None
    media_type: str | None = None
    media_src: str = ""


# ======================================================================================
# Identity: avatars
# ======================================================================================


def initials_of(handle: str, fallback_id: str = "") -> str:
    """`Alice Compras` / `@alice.compras` → `AC`, `@yesii_roa` → `YR`, `@maria` → `M`; an
    id alone → its last letter-or-digit. Two characters at most."""
    base = handle.lstrip("@").strip()
    words = [w for w in base.replace(".", " ").replace("_", " ").replace("-", " ").split() if w]
    if not words:
        tail = (fallback_id or "").strip()[-1:]
        return tail.upper() if tail else "?"
    if len(words) == 1:
        return words[0][:1].upper()
    return (words[0][0] + words[-1][0]).upper()


def avatar_hue(seed: str) -> int:
    """A stable hue (0-359) for an avatar's gradient — data, not a colour literal: the
    page hands it to the stylesheet as a CSS variable and the kit's own palette paints."""
    total = 0
    for i, ch in enumerate(seed or "?"):
        total = (total * 31 + ord(ch) * (i + 7)) % 100003
    return total % 360


# ======================================================================================
# Accounts (the connection selector)
# ======================================================================================


@dataclass(frozen=True)
class AccountVM:
    """One connected account the inbox can show. Built from `ConnectionVM` (already a
    credential-free projection); `can_manage_dms` is the C-05 matrix's verdict on the
    messages scope, `dm_reason` its words when it is missing."""

    connection_id: str
    label: str  # «@username»
    brand: str
    platform: str
    channel_label: str
    status: str  # active | degraded | revoked
    can_manage_dms: bool
    dm_reason: str

    @property
    def is_degraded(self) -> bool:
        return self.status == "degraded"


EMPTY_ACCOUNT = AccountVM(
    connection_id="",
    label="",
    brand="",
    platform="instagram",
    channel_label=CHANNEL_LABELS["dm"],
    status="active",
    can_manage_dms=False,
    dm_reason="",
)

MANAGE_DMS_KEY = "manage_dms"


class _CapabilityLike(Protocol):
    key: str
    enabled: bool
    reason: str


class _ConnectionLike(Protocol):
    id: str
    platform: str
    brand: str
    external_username: str
    status: str
    enabled_capabilities: list[Any]
    disabled_capabilities: list[Any]


def build_account_vm(connection: _ConnectionLike) -> AccountVM:
    enabled = {c.key for c in connection.enabled_capabilities}
    reason = ""
    for capability in connection.disabled_capabilities:
        if capability.key == MANAGE_DMS_KEY:
            reason = capability.reason
    handle = (connection.external_username or "").strip()
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"
    return AccountVM(
        connection_id=str(connection.id),
        label=handle or "Cuenta sin nombre",
        brand=connection.brand or "",
        platform=connection.platform,
        channel_label=CHANNEL_LABELS["dm"],
        status=connection.status,
        can_manage_dms=MANAGE_DMS_KEY in enabled,
        dm_reason=reason,
    )


def inbox_accounts(connections: Iterable[_ConnectionLike]) -> list[AccountVM]:
    """The Instagram connections that are not revoked, in the order given."""
    return [
        build_account_vm(c)
        for c in connections
        if c.platform == "instagram" and c.status != "revoked"
    ]


# ======================================================================================
# Access (the banner over the list)
# ======================================================================================

ACCESS_OK = "ok"
ACCESS_UNKNOWN = "unknown"
ACCESS_PERMISSION_MISSING = "permission_missing"
ACCESS_DISABLED = "access_disabled"
ACCESS_AUTH_EXPIRED = "auth_expired"
ACCESS_ERROR = "error"
ACCESS_SYNC_FAILED = "sync_failed"
ACCESS_NEVER_SYNCED = "never_synced"
#: Kinds that are NOT a banner: `ok` is nothing, `sync_failed` is a toast.
QUIET_ACCESS_KINDS = frozenset({ACCESS_OK, ACCESS_SYNC_FAILED})


@dataclass(frozen=True)
class AccessVM:
    """The one banner over the inbox. `kind` in `QUIET_ACCESS_KINDS` means no banner;
    `provisional` marks the «por verificar» badge (§6.4) — the list may be empty because
    nothing was read, not because nobody wrote. A failed sync carries `failure_key` (the
    failure's instant) so the state toasts each failure once, never on every refresh."""

    kind: str
    tone: str
    title: str
    message: str
    show_reconnect: bool = False
    provisional: bool = False
    last_sync_label: str = ""
    failure_key: str = ""


EMPTY_ACCESS = AccessVM(kind=ACCESS_OK, tone="neutral", title="", message="")

_TOGGLE_HINT = (
    "El dueño de la cuenta debe activar en Instagram: Configuración → Mensajes y "
    "respuestas a historias → Controles de mensajes → Herramientas conectadas → "
    "Permitir acceso a los mensajes."
)


def _sync_label(state: SyncStateLike | None, now: datetime, zone: tzinfo) -> str:
    if state is None or state.last_sync_finished_at is None:
        return "Sin sincronizar todavía"
    when = relative_time(state.last_sync_finished_at, now, zone)
    status = state.last_sync_status or ""
    if status == "failed":
        return f"Última sincronización fallida {when}"
    return f"Sincronizado {when}"


def build_access_vm(
    state: SyncStateLike | None, *, account: AccountVM, now: datetime, zone: tzinfo
) -> AccessVM:
    """Order matters: what the C-05 matrix and the connection FSM already know comes
    before anything the sync recorded, and «unknown» stays provisional."""
    last_sync = _sync_label(state, now, zone)
    if not account.can_manage_dms:
        return AccessVM(
            kind=ACCESS_PERMISSION_MISSING,
            tone="warn",
            title="Falta el permiso de mensajes",
            message=(
                (account.dm_reason + " ")
                if account.dm_reason
                else "Esta cuenta no concedió el permiso de mensajes directos. "
            )
            + "Reconecta la cuenta y concede el permiso para leer y responder mensajes.",
            show_reconnect=True,
            provisional=True,
            last_sync_label=last_sync,
        )
    if account.is_degraded:
        return AccessVM(
            kind=ACCESS_AUTH_EXPIRED,
            tone="warn",
            title="La conexión dejó de responder",
            message="Reconecta la cuenta para volver a leer y responder sus mensajes.",
            show_reconnect=True,
            provisional=True,
            last_sync_label=last_sync,
        )
    if state is None:
        return AccessVM(
            kind=ACCESS_NEVER_SYNCED,
            tone="info",
            title="Todavía no se ha sincronizado esta cuenta",
            message=(
                "Los mensajes aparecen cuando llega el primer aviso de Instagram o la "
                "primera sincronización. Una lista vacía ahora no significa que no haya "
                "mensajes."
            ),
            provisional=True,
            last_sync_label=last_sync,
        )
    status = (state.access_status or "").lower()
    detail = f" (código {state.access_detail})" if state.access_detail else ""
    if status == ACCESS_PERMISSION_MISSING:
        return AccessVM(
            kind=ACCESS_PERMISSION_MISSING,
            tone="warn",
            title="Instagram rechazó la lectura de mensajes",
            message="La cuenta no tiene el permiso de mensajes concedido" + detail + ". "
            "Reconecta la cuenta y concede el permiso.",
            show_reconnect=True,
            provisional=True,
            last_sync_label=last_sync,
        )
    if status == ACCESS_AUTH_EXPIRED:
        return AccessVM(
            kind=ACCESS_AUTH_EXPIRED,
            tone="warn",
            title="La conexión caducó",
            message="Instagram ya no acepta la credencial de esta cuenta" + detail + ". "
            "Reconéctala para volver a leer y responder mensajes.",
            show_reconnect=True,
            provisional=True,
            last_sync_label=last_sync,
        )
    if status == ACCESS_DISABLED:
        return AccessVM(
            kind=ACCESS_DISABLED,
            tone="info",
            title="El acceso a los mensajes está apagado en Instagram",
            message=_TOGGLE_HINT,
            provisional=True,
            last_sync_label=last_sync,
        )
    if status == ACCESS_ERROR:
        return AccessVM(
            kind=ACCESS_ERROR,
            tone="warn",
            title="No se pudo comprobar el acceso a los mensajes",
            message="Instagram respondió con un error" + detail + ". Se volverá a intentar "
            "en la próxima sincronización.",
            provisional=True,
            last_sync_label=last_sync,
        )
    if status == ACCESS_UNKNOWN or not status:
        return AccessVM(
            kind=ACCESS_UNKNOWN,
            tone="warn",
            title="Acceso a los mensajes por verificar",
            message=(
                "Instagram no confirma si esta cuenta puede leer mensajes. Si esperabas "
                "mensajes y no aparecen, revisa el permiso en Instagram. " + _TOGGLE_HINT
            ),
            provisional=True,
            last_sync_label=last_sync,
        )
    if (state.last_sync_status or "") == "failed":
        finished = state.last_sync_finished_at
        return AccessVM(
            kind=ACCESS_SYNC_FAILED,
            tone="warn",
            title="La última sincronización falló",
            message="La lista puede estar incompleta. Se vuelve a intentar enseguida.",
            last_sync_label=last_sync,
            failure_key=finished.isoformat() if finished is not None else "failed",
        )
    return AccessVM(kind=ACCESS_OK, tone="neutral", title="", message="", last_sync_label=last_sync)


# ======================================================================================
# The 24 h window, in plain words
# ======================================================================================


def _local(value: datetime, zone: tzinfo) -> datetime:
    return value.astimezone(zone) if value.tzinfo is not None else value


def window_words(
    is_open: bool, closes_at: datetime | None, now: datetime, zone: tzinfo
) -> tuple[str, str, str]:
    """(sentence for the header, short pill for the row — "" while comfortably open —,
    tone). «Puedes responder hasta las 17:47» / «Te quedan 12 min para responder» /
    «Ya no puedes responder…»."""
    if not is_open or closes_at is None:
        return WINDOW_CLOSED_NOTICE, WINDOW_CLOSED_SHORT, "neutral"
    remaining = closes_at - now
    if remaining < timedelta(hours=1):
        minutes = max(1, int(remaining.total_seconds() // 60))
        return (
            f"Te quedan {minutes} min para responder: {WINDOW_RULE}",
            f"Quedan {minutes} min",
            "warn",
        )
    local_close, local_now = _local(closes_at, zone), _local(now, zone)
    clock = local_close.strftime("%H:%M")
    when = (
        f"hasta las {clock}"
        if local_close.date() == local_now.date()
        else (f"hasta mañana a las {clock}")
    )
    return f"{WINDOW_RULE} En esta conversación, {when}.", "", "ok"


# ======================================================================================
# Thread list
# ======================================================================================


@dataclass(frozen=True)
class ThreadRowVM:
    thread_id: str
    title: str  # the person's name, else their handle, else «Persona ·id»
    handle: str  # «@username» or "" (never equal to the title)
    subtitle: str  # «@account · Instagram Direct»
    preview: str
    preview_icon: str  # "" or a Lucide name for a media preview
    time_label: str
    attention: str
    attention_label: str
    attention_tone: str
    window_label: str  # the sentence (header)
    window_short: str  # the pill (row), "" while comfortably open
    window_tone: str
    window_open: bool
    is_closed: bool
    initials: str
    hue: int
    avatar_url: str = ""
    # Set for ONE render after a refresh found a newer inbound: the row pulses.
    fresh: bool = False


EMPTY_THREAD = ThreadRowVM(
    thread_id="",
    title="",
    handle="",
    subtitle="",
    preview="",
    preview_icon="",
    time_label="",
    attention="none",
    attention_label="Sin mensajes",
    attention_tone="neutral",
    window_label=WINDOW_CLOSED_NOTICE,
    window_short=WINDOW_CLOSED_SHORT,
    window_tone="neutral",
    window_open=False,
    is_closed=False,
    initials="?",
    hue=0,
)


def attention_pill(attention: Any) -> tuple[str, str]:
    key = getattr(attention, "value", attention)
    return ATTENTION_PILLS.get(str(key), ATTENTION_PILLS["none"])


def counterpart_title(username: str | None, counterpart_external_id: str) -> str:
    handle = (username or "").strip()
    if handle:
        return handle if handle.startswith("@") else f"@{handle}"
    tail = counterpart_external_id[-6:] if counterpart_external_id else ""
    return f"Persona ·{tail}" if tail else "Persona"


def media_label(media_type: str | None) -> tuple[str, str, str]:
    """`messages.media_type` → (label, icon, control). ("", "", "") for text."""
    if not media_type:
        return "", "", ""
    return _MEDIA_KINDS.get(media_type.lower(), _MEDIA_KINDS["other"])


def build_thread_row(
    view: ThreadViewLike,
    extra: ThreadExtra | None,
    *,
    now: datetime,
    zone: tzinfo,
    account_label: str = "",
    fresh: bool = False,
) -> ThreadRowVM:
    thread = view.thread
    extra = extra or ThreadExtra()
    preview = (extra.preview or "").strip()
    icon = ""
    if not preview and extra.preview_media_type:
        label, icon, _control = media_label(extra.preview_media_type)
        preview = UNSUPPORTED_PREVIEW if extra.preview_media_type == "other" else label
    if not preview:
        preview = NO_MESSAGES_YET
    elif extra.preview_direction == "outbound":
        preview = OUTBOUND_PREFIX + preview
    label, tone = attention_pill(view.attention)
    window_label, window_short, window_tone = window_words(
        view.window.is_open, view.window.closes_at, now, zone
    )
    channel = CHANNEL_LABELS.get(thread.channel, thread.channel)
    subtitle = f"{account_label} · {channel}" if account_label else channel
    # Identity: the profile the sync fetched beats the handle of the latest message.
    username = (getattr(thread, "counterpart_username", None) or extra.username or "").strip()
    name = (getattr(thread, "counterpart_name", None) or "").strip()
    handle = counterpart_title(username, "") if username else ""
    title = name or handle or counterpart_title("", thread.counterpart_external_id)
    if handle == title:
        handle = ""
    avatar_url = (getattr(thread, "counterpart_avatar_url", None) or "").strip()
    return ThreadRowVM(
        thread_id=str(thread.id),
        title=title,
        handle=handle,
        subtitle=subtitle,
        preview=preview,
        preview_icon=icon,
        time_label=relative_time(thread.last_message_at, now, zone),
        attention=str(getattr(view.attention, "value", view.attention)),
        attention_label=label,
        attention_tone=tone,
        window_label=window_label,
        window_short=window_short,
        window_tone=window_tone,
        window_open=view.window.is_open,
        is_closed=thread.status == "closed",
        initials=initials_of(name or username, thread.counterpart_external_id),
        hue=avatar_hue(thread.counterpart_external_id),
        avatar_url=avatar_url,
        fresh=fresh,
    )


def filter_threads(rows: Iterable[ThreadRowVM], key: str) -> list[ThreadRowVM]:
    """Todas · Pendientes · Leídas · Respondidas, by the derived attention state. An
    unknown key falls back to Todas."""
    if key in (FILTER_PENDING, FILTER_READ, FILTER_ANSWERED):
        return [r for r in rows if r.attention == key]
    return list(rows)


def filter_counts(rows: Sequence[ThreadRowVM]) -> dict[str, int]:
    return {key: len(filter_threads(rows, key)) for key, _label in FILTERS}


def filter_label(key: str, count: int) -> str:
    label = dict(FILTERS).get(key, key)
    return f"{label} · {count}" if count else label


def newly_pending(previous: Sequence[ThreadRowVM], current: Sequence[ThreadRowVM]) -> list[str]:
    """Thread ids whose last activity moved AND that are pending now — what a refresh
    announces («Nuevo mensaje de …») and pulses. A first load announces nothing."""
    if not previous:
        return []
    before = {r.thread_id: r for r in previous}
    fresh: list[str] = []
    for row in current:
        old = before.get(row.thread_id)
        if row.attention != "pending":
            continue
        if old is None or old.time_label != row.time_label or old.preview != row.preview:
            if old is None or old.attention != "pending" or old.preview != row.preview:
                fresh.append(row.thread_id)
    return fresh


# ======================================================================================
# Conversation
# ======================================================================================


@dataclass(frozen=True)
class MessageVM:
    message_id: str
    is_outbound: bool
    text: str
    time_label: str
    tick: str  # "" | sent | read | queued | failed
    tick_label: str
    error_label: str
    # Media: `media_control` is "" or MEDIA_IMAGE/AUDIO/VIDEO/FILE/STICKER; `media_src`
    # the URL to render (CDN for inbound, /r2media for outbound) or "" when it cannot be
    # shown. A sticker has no source: the control alone draws it.
    media_control: str = ""
    media_label: str = ""
    media_src: str = ""
    # «Hoy» / «Ayer» / «12 oct» on the first message of each day.
    day_label: str = ""
    # «Visto» under the newest outbound message the counterpart has read (Instagram's
    # own convention: one footer, not one per bubble).
    seen_footer: str = ""
    # m-24789646 (B5): an inbound DM that replies to a story says so above the bubble,
    # with the story's link while Meta's (expiring) URL lasts.
    story_reply_label: str = ""
    story_reply_href: str = ""


STORY_REPLY_LABEL: Final = "Respondió a tu historia"


def failure_label(code: str | None) -> str:
    if not code:
        return "No se envió."
    if code in _FAILURE_LABELS:
        return _FAILURE_LABELS[code]
    if code.startswith("max_attempts"):
        return "No se envió tras varios intentos."
    return f"No se envió (código {code})."


def _day_of(value: datetime, zone: tzinfo, now: datetime) -> str:
    local = value.astimezone(zone) if value.tzinfo is not None else value
    today = (now.astimezone(zone) if now.tzinfo is not None else now).date()
    days = (today - local.date()).days
    if days == 0:
        return "Hoy"
    if days == 1:
        return "Ayer"
    return format_day(value, zone, now)


def build_message_vm(
    message: MessageLike,
    *,
    now: datetime,
    zone: tzinfo,
    media_src: str = "",
) -> MessageVM:
    outbound = message.direction == "outbound"
    text = (message.text or "").strip()
    label, _icon, control = media_label(message.media_type)
    if not text and not control:
        text = label or "Mensaje"
    tick = ""
    if outbound:
        status = (message.delivery_status or "").lower()
        tick = "read" if status == "read" else "sent"
    story = None if outbound else getattr(message, "story_reply_id", None)
    return MessageVM(
        message_id=str(message.id),
        is_outbound=outbound,
        text=text,
        time_label=message_time(message.posted_at or message.ingested_at, now, zone),
        tick=tick,
        tick_label=_TICK_LABELS.get(tick, ""),
        error_label="",
        media_control=control,
        media_label=label,
        media_src=media_src if control else "",
        story_reply_label=STORY_REPLY_LABEL if story else "",
        story_reply_href=(getattr(message, "story_reply_url", None) or "") if story else "",
    )


def build_unsent_vm(item: UnsentItem, *, now: datetime, zone: tzinfo) -> MessageVM:
    """An outbox row shown as an outbound bubble: «Enviando» (animated) while pending or
    sending, the `error` tone with the sender's code once failed or dead."""
    failed = item.status in {"failed", "dead"}
    tick = "failed" if failed else "queued"
    label, _icon, control = media_label(item.media_type)
    return MessageVM(
        message_id=f"outbox-{item.id}",
        is_outbound=True,
        text=item.text or ("" if control else "Mensaje"),
        time_label=message_time(item.created_at, now, zone),
        tick=tick,
        tick_label=_TICK_LABELS[tick],
        error_label=failure_label(item.error_code) if failed else "",
        media_control=control,
        media_label=label,
        media_src=item.media_src if control else "",
    )


def outbox_text(payload: Mapping[str, Any]) -> str:
    """The readable text of a queued Messenger-Platform body (`message.text`); "" for an
    attachment-only body (the caller words it by its media type)."""
    message = payload.get("message")
    if isinstance(message, Mapping):
        text = message.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        if isinstance(message.get("attachment"), Mapping):
            return ""
    return "Mensaje"


def build_conversation(
    messages: Sequence[MessageLike],
    unsent: Sequence[UnsentItem],
    *,
    now: datetime,
    zone: tzinfo,
    media_sources: Mapping[str, str] | None = None,
) -> list[MessageVM]:
    """Messages and not-yet-sent outbox rows, chronological (oldest first), with the day
    separators and the single «Visto» footer placed."""
    sources = media_sources or {}
    keyed: list[tuple[datetime, int, MessageVM]] = []
    for m in messages:
        vm = build_message_vm(m, now=now, zone=zone, media_src=sources.get(str(m.id), ""))
        keyed.append((m.posted_at or m.ingested_at, 0, vm))
    for item in unsent:
        keyed.append((item.created_at, 1, build_unsent_vm(item, now=now, zone=zone)))
    keyed.sort(key=lambda entry: (entry[0], entry[1]))

    out: list[MessageVM] = []
    last_day = ""
    for instant, _order, vm in keyed:
        day = _day_of(instant, zone, now)
        if day != last_day:
            vm = MessageVM(**{**vm.__dict__, "day_label": day})
            last_day = day
        out.append(vm)
    # The footer goes under the newest outbound that was read, only if no newer outbound
    # is still unread (then the person sees «Enviado» on that one instead).
    for i in range(len(out) - 1, -1, -1):
        vm = out[i]
        if not vm.is_outbound or vm.tick in ("queued", "failed"):
            continue
        if vm.tick == "read":
            out[i] = MessageVM(**{**vm.__dict__, "seen_footer": "Visto"})
        break
    return out


# ======================================================================================
# Composer (the UI's validation; the service and the channel re-check on send)
# ======================================================================================


def validate_reply(text: str) -> str:
    """'' when sendable, else the reason in Spanish. Length is not a reason any more: a
    long text goes out as several messages (`reply_parts_hint`)."""
    if not text.strip():
        return "Escribe una respuesta."
    return ""


def reply_parts(text: str) -> int:
    """In how many messages the text goes out (the channel's 1000-char limit)."""
    from qualify_api.conversations.service import split_reply  # noqa: PLC0415

    return len(split_reply(text))


def reply_parts_hint(text: str) -> str:
    """ "" while the text fits in one message; else how many it becomes and why."""
    if len(text.strip()) <= MAX_REPLY_CHARS:
        return ""
    n = reply_parts(text)
    if n <= 1:
        return ""
    return (
        f"Se enviará en {n} mensajes seguidos: Instagram admite {MAX_REPLY_CHARS} "
        "caracteres por mensaje."
    )


def composer_enabled(window_open: bool, has_thread: bool, account_ok: bool) -> bool:
    """A reply needs an open thread, an open 24 h window and an account that may
    message (the matrix's verdict and the FSM's status)."""
    return has_thread and window_open and account_ok


def reply_as_label(account: AccountVM) -> str:
    if not account.connection_id:
        return ""
    return f"Respondes como {account.label} · {account.channel_label}"


@dataclass(frozen=True)
class AttachmentVM:
    """A file the person attached to the reply being written: already in R2, not sent."""

    object_key: str
    media_type: str  # image | audio | video | document
    content_type: str
    name: str
    preview_src: str = ""

    @property
    def ready_label(self) -> str:
        return ATTACHMENT_READY.get(self.media_type, "Adjunto listo para enviar")


EMPTY_ATTACHMENT = AttachmentVM(object_key="", media_type="", content_type="", name="")


def classify_attachment(content_type: str, size: int) -> tuple[str, str]:
    """(media_type, error). Only the kinds the composer offers, within Meta's limits."""
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    if kind in _IMAGE_TYPES:
        if size > MAX_IMAGE_BYTES:
            return "", "La foto supera los 8 MB que admite Instagram."
        return MEDIA_IMAGE, ""
    if kind in _AUDIO_TYPES:
        if size > MAX_AUDIO_BYTES:
            return "", "El audio supera los 25 MB que admite Instagram."
        return MEDIA_AUDIO, ""
    if kind in _VIDEO_TYPES:
        if size > MAX_VIDEO_BYTES:
            return "", "El video supera los 25 MB que admite Instagram."
        return MEDIA_VIDEO, ""
    if kind in _DOCUMENT_TYPES:
        if size > MAX_DOCUMENT_BYTES:
            return "", "El PDF supera los 25 MB que admite Instagram."
        return "document", ""
    if kind.startswith("application/") or kind.startswith("text/"):
        return "", "Instagram solo admite PDF como archivo (hasta 25 MB)."
    return (
        "",
        "Solo se pueden enviar fotos (JPG, PNG), videos (MP4, MOV, WEBM), notas de voz "
        "o archivos PDF.",
    )


def voice_note_name(seconds: int, now: datetime, zone: tzinfo) -> str:
    """`Nota de voz 0:42 · 17:03` — what the chip shows for a recording."""
    minutes, rest = divmod(max(0, int(seconds)), 60)
    return f"Nota de voz {minutes}:{rest:02d} · {message_time(now, now, zone)}"


# ======================================================================================
# Drafts (E4)
# ======================================================================================


@dataclass(frozen=True)
class DraftVM:
    """A model's suggestion as the composer shows it. `text` is what landed in the box;
    `note` the chip's words; `claims` what the generator could not ground (joined)."""

    draft_id: str
    text: str
    needs_review: bool
    note: str
    claims: str = ""


EMPTY_DRAFT = DraftVM(draft_id="", text="", needs_review=False, note="")


def build_draft_vm(draft: DraftLike) -> DraftVM:
    claims = draft.grounding.get("unsupported_claims") if draft.grounding else None
    joined = " · ".join(str(c) for c in claims) if isinstance(claims, list) and claims else ""
    return DraftVM(
        draft_id=str(draft.id),
        text=draft.generated_text,
        needs_review=bool(draft.needs_review),
        note=SUGGESTION_REVIEW_NOTE if draft.needs_review else SUGGESTION_NOTE,
        claims=joined,
    )


def suggestion_refusal_label(reason: str) -> str:
    return SUGGESTION_REFUSALS.get(reason, SUGGESTION_REFUSED_DEFAULT)


# ======================================================================================
# Message templates (m-24789472, PR 1)
# ======================================================================================

#: Mirrors of `qualify_api.conversations.templates` (a test pins them equal): the form
#: counts characters as the person types, the service is still the one that refuses.
MAX_TEMPLATE_TITLE_CHARS = 60
MAX_TEMPLATE_BODY_CHARS = 1000
MAX_TEMPLATES_PER_ACCOUNT = 50
#: How much of a body the picker shows under the title (one line, «…» when cut).
TEMPLATE_PREVIEW_CHARS = 90

TEMPLATE_HELP = (
    "Escribe {nombre} y lo cambiamos por el nombre de la persona; {marca}, por el de tu "
    "negocio. Lo que pongas entre corchetes, como [precio], lo completas tú antes de enviar."
)
TEMPLATE_READY_NOTE = "Plantilla en el cuadro: revísala. Nada sale hasta que pulses «Responder»."


class TemplateLike(Protocol):
    id: Any
    title: str
    body: str
    default_key: str | None


@dataclass(frozen=True)
class TemplateVM:
    """One template of the account's library, as the picker and the manager show it."""

    template_id: str
    title: str
    body: str
    preview: str
    is_default: bool
    is_first: bool
    is_last: bool


def template_preview(body: str, limit: int = TEMPLATE_PREVIEW_CHARS) -> str:
    """The body on one line, cut at a word with «…» when longer than `limit`."""
    flat = " ".join(body.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0] or flat[:limit]
    return cut.rstrip(" ,.;:") + "…"


def build_template_rows(templates: Sequence[TemplateLike]) -> list[TemplateVM]:
    """The library in the order given (the service's picker order), with the ends marked
    so «Subir» / «Bajar» can be off on the first and the last."""
    last = len(templates) - 1
    return [
        TemplateVM(
            template_id=str(t.id),
            title=t.title,
            body=t.body,
            preview=template_preview(t.body),
            is_default=t.default_key is not None,
            is_first=i == 0,
            is_last=i == last,
        )
        for i, t in enumerate(templates)
    ]


def template_counter(count: int) -> str:
    """«12/50» — how many of the account's templates are used."""
    return f"{count}/{MAX_TEMPLATES_PER_ACCOUNT}"


def char_counter(text: str, limit: int) -> str:
    """«42/60» under a form field."""
    return f"{len(text)}/{limit}"


def moved_order(ids: Sequence[str], template_id: str, step: int) -> list[str] | None:
    """The whole library's ids after moving one a place up (`step` -1) or down (+1); None
    when it cannot move (unknown id, already at that end, or a step other than ±1)."""
    if step not in (-1, 1) or template_id not in ids:
        return None
    order = list(ids)
    index = order.index(template_id)
    target = index + step
    if target < 0 or target >= len(order):
        return None
    order[index], order[target] = order[target], order[index]
    return order


def _join_es(items: Sequence[str]) -> str:
    """`a` / `a y b` / `a, b y c`."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def pending_fill_ins(
    text: str, unresolved: Sequence[str], blanks: Sequence[str]
) -> tuple[list[str], list[str]]:
    """Which of a template's open spots are still in the box: a `{variable}` with no value
    and a `[fill-in]`. The ones the person already replaced drop out."""
    return [u for u in unresolved if u in text], [b for b in blanks if b in text]


def template_notice(text: str, unresolved: Sequence[str], blanks: Sequence[str]) -> str:
    """The gentle line over the box after a template is picked, while something is still
    to be completed. "" once everything was filled — sending is never blocked by it."""
    left_vars, left_blanks = pending_fill_ins(text, unresolved, blanks)
    sentences: list[str] = []
    if left_vars:
        sentences.append(
            f"Completa {_join_es(left_vars)} antes de enviar: no tenemos ese dato en esta "
            "conversación."
        )
    if left_blanks:
        sentences.append(f"Rellena {_join_es(left_blanks)} antes de enviar.")
    return " ".join(sentences)
