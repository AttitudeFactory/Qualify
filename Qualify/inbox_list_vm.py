"""The single chat list under «Por responder» › «Mensajes» (m-25017859, BU-A3).

Every connected chat channel in ONE list (`qualify_api.inbox.unified.list_inbox`),
newest activity first, drawn with the shared row (`chat_row_vm.ChatRowVM`) through the
adapter here (`as_chat_row`). The chips and the channel filter read `inbox_counts` — the
same SQL text the list filters by — so each chip's number is the length of its list.

Tree (docs/ux-chats-unificados.md §2):

    Por responder › Mensajes
      [Todos] [Instagram] [WhatsApp]          only with chats on 2+ channels; no TikTok
      [Por responder · N] [Todos · N] [Cerrados · N] (+ [Pago por revisar · N] if N ≥ 1)
      «Se te pasaron N chats de Instagram · Ver»   (inside «Por responder», dismissible)
      the rows · «Ver más»

Pure: no Reflex, no database.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any, Final, Protocol

from .chat_row_vm import (
    CHANNEL_INSTAGRAM,
    CHANNEL_WHATSAPP,
    ChatRowVM,
    build_chat_row,
    channel_label,
    minutes_left,
    unknown_contact,
)
from .conversations_vm import NO_MESSAGES_YET, OUTBOUND_PREFIX, UNSUPPORTED_PREVIEW, media_label
from .nav_url import conversation_href, scalar_param, with_query
from .whatsapp_chats_vm import FILTER_PAYMENT_EMPTY, phone_label, relative_time

ROUTE: Final = "/responder"
TAB: Final = "mensajes"

# --------------------------------------------------------------------------------------
# Channels: the UI's names ↔ the backend's (`qualify_api.inbox.channels`)
# --------------------------------------------------------------------------------------

#: `threads.channel` → the row's channel. TikTok is not drawn until it exists (UX §4.6).
BACKEND_TO_UI: Final[Mapping[str, str]] = {"dm": CHANNEL_INSTAGRAM, "whatsapp": CHANNEL_WHATSAPP}
UI_TO_BACKEND: Final[Mapping[str, str]] = {ui: be for be, ui in BACKEND_TO_UI.items()}
#: The channel filter's order: Instagram, then WhatsApp (the UX doc's mockup).
CHANNELS: Final[tuple[str, ...]] = (CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP)
CHANNEL_PARAM: Final = "canal"
ALL_CHANNELS: Final = ""
ALL_CHANNELS_LABEL: Final = "Todos"

# --------------------------------------------------------------------------------------
# Filters (`qualify_api.inbox.unified.INBOX_FILTERS`)
# --------------------------------------------------------------------------------------

FILTER_AWAITING: Final = "por_responder"
FILTER_ALL: Final = "todos"
FILTER_CLOSED: Final = "cerrados"
FILTER_PAYMENT: Final = "pago_por_revisar"
FILTER_EXPIRED: Final = "ventana_vencida"
DEFAULT_FILTER: Final = FILTER_AWAITING

FILTER_LABELS: Final[Mapping[str, str]] = {
    FILTER_AWAITING: "Por responder",
    FILTER_ALL: "Todos",
    FILTER_CLOSED: "Cerrados",
    FILTER_PAYMENT: "Pago por revisar",
    # Only drawn while it is the filter on screen (opened from the notice), so the owner
    # sees what is listed and has the way back. UX proposal awaiting the founder.
    FILTER_EXPIRED: "Se te pasaron",
}
FILTER_KEYS: Final = frozenset(FILTER_LABELS)
#: The chips always drawn, in order; «Pago por revisar» joins only with N ≥ 1.
BASE_FILTERS: Final[tuple[str, ...]] = (FILTER_AWAITING, FILTER_ALL, FILTER_CLOSED)

FILTER_PARAM: Final = "filtro"
FILTER_SLUGS: Final[Mapping[str, str]] = {
    "por-responder": FILTER_AWAITING,
    "todos": FILTER_ALL,
    "cerrados": FILTER_CLOSED,
    "pago-por-revisar": FILTER_PAYMENT,
    "se-te-pasaron": FILTER_EXPIRED,
    # The Instagram-only chips this list replaces (old links, Inicio's old card): the
    # chats that waited («Pendientes», «Leídas» — read but not answered) wait under the
    # rule; «Abiertas» / «Todas» / «Respondidas» are open chats; «Cerradas» closed ones.
    "pendientes": FILTER_AWAITING,
    "leidas": FILTER_AWAITING,
    "sin-leer": FILTER_AWAITING,
    "abiertas": FILTER_ALL,
    "todas": FILTER_ALL,
    "respondidas": FILTER_ALL,
    "cerradas": FILTER_CLOSED,
}
_KEY_TO_SLUG: Final[Mapping[str, str]] = {
    FILTER_AWAITING: "por-responder",
    FILTER_ALL: "todos",
    FILTER_CLOSED: "cerrados",
    FILTER_PAYMENT: "pago-por-revisar",
    FILTER_EXPIRED: "se-te-pasaron",
}

PAGE_SIZE: Final = 50

# --------------------------------------------------------------------------------------
# Words (qualify-copy-es). Founder-decided: «Por responder», «Todos», «Cerrados»,
# «Pago por revisar · {N}», «WhatsApp», «Instagram», the empty «Por responder» text.
# UX proposals awaiting the founder: the expired notice, «Se te pasaron», the other
# empty texts.
# --------------------------------------------------------------------------------------

MORE_LABEL: Final = "Ver más"
FILTERS_ARIA: Final = "Qué chats ver"
CHANNELS_ARIA: Final = "De qué red"

NOTICE_ONE: Final = "Se te pasó 1 chat de Instagram"
NOTICE_MANY: Final = "Se te pasaron {n} chats de Instagram"
NOTICE_ACTION: Final = "Ver"
NOTICE_DISMISS: Final = "Ocultar este aviso"

EMPTY_AWAITING_TITLE: Final = "Ya respondiste a todos."
EMPTY_AWAITING_BODY: Final = "Aquí verás a quien te escriba por {channels}."
EMPTY_ALL: Final = "Todavía no tienes chats. Aquí verás a quien te escriba por {channels}."
EMPTY_CLOSED: Final = "No tienes chats cerrados."
EMPTY_EXPIRED: Final = "No se te pasó ningún chat de Instagram en la última semana."
EMPTY_BACK: Final = "Ver por responder"

NOTHING_CONNECTED_TITLE: Final = "Aún no tienes WhatsApp ni Instagram conectados"
NOTHING_CONNECTED_BODY: Final = (
    "Conéctalos en Tus redes y aquí verás, en una sola lista, a quien te escriba."
)
NOTHING_CONNECTED_ACTION: Final = "Ir a Tus redes"
NOTHING_CONNECTED_HREF: Final = "/connections"

LIST_FAILED: Final = "No pudimos cargar tus chats. Revisa tu conexión y toca «Reintentar»."
MORE_FAILED: Final = "No pudimos traer más chats. Toca «Ver más» otra vez."

#: WhatsApp's media kinds (inbound `media_type`, outbound payload `type`) → (words, icon).
_WHATSAPP_KINDS: Final[Mapping[str, tuple[str, str]]] = {
    "image": ("Foto", "image"),
    "video": ("Video", "video"),
    "audio": ("Audio", "mic"),
    "voice": ("Audio", "mic"),
    "document": ("Archivo", "file-text"),
    "sticker": ("Sticker", "sticker"),
    "interactive": ("Mensaje con botones", "mouse-pointer-click"),
    "template": ("Mensaje aprobado", "file-check"),
    "location": ("Ubicación", "map-pin"),
}
_WHATSAPP_OTHER: Final = ("[foto, audio o archivo]", "")


# ======================================================================================
# Parameters and addresses
# ======================================================================================


def filter_from_params(params: Mapping[str, object]) -> str | None:
    """`?filtro=` → a filter key; absent or unknown → None (keep the one on screen)."""
    slug = scalar_param(params, FILTER_PARAM).strip().lower()
    return FILTER_SLUGS.get(slug) if slug else None


def channel_from_params(params: Mapping[str, object]) -> str | None:
    """`?canal=instagram|whatsapp` → that channel; `todos` → every channel; absent →
    None (keep); anything else → every channel (never a channel that is not listed)."""
    if CHANNEL_PARAM not in params:
        return None
    value = scalar_param(params, CHANNEL_PARAM).strip().lower()
    return value if value in CHANNELS else ALL_CHANNELS


def list_href(filter_key: str = DEFAULT_FILTER, channel: str = ALL_CHANNELS) -> str:
    """The single list's address: `/responder?tab=mensajes&filtro=…&canal=…`."""
    slug = _KEY_TO_SLUG.get(filter_key, _KEY_TO_SLUG[DEFAULT_FILTER])
    canal = channel if channel in CHANNELS else ""
    return with_query(ROUTE, tab=TAB, **{FILTER_PARAM: slug, CHANNEL_PARAM: canal})


def whatsapp_chat_href(connection_id: str, thread_id: str) -> str:
    """Today's WhatsApp chat (`/whatsapp?tab=chats&cuenta=…&chat=…`), marked as opened
    from this list so its «‹ Por responder» comes back here."""
    return conversation_href("whatsapp", connection_id, thread_id, from_inbox=True)


# ======================================================================================
# Chips
# ======================================================================================


class CountsLike(Protocol):
    """`qualify_api.inbox.unified.InboxCounts` (backend channel names)."""

    by_channel: Mapping[str, Mapping[str, int]]


@dataclass(frozen=True)
class ChipVM:
    key: str
    label: str
    pressed: bool


def count_of(counts: CountsLike | None, filter_key: str, channel: str = ALL_CHANNELS) -> int:
    """How many chats `filter_key` lists on `channel` (every channel with "")."""
    if counts is None:
        return 0
    backend = [UI_TO_BACKEND[channel]] if channel in UI_TO_BACKEND else list(counts.by_channel)
    return sum(max(0, int(counts.by_channel.get(c, {}).get(filter_key, 0))) for c in backend)


def chip_label(filter_key: str, count: int) -> str:
    """«Por responder · 3»; the bare name at 0."""
    label = FILTER_LABELS.get(filter_key, filter_key)
    return f"{label} · {count}" if count > 0 else label


def filter_chips(counts: CountsLike | None, active: str, channel: str) -> list[ChipVM]:
    """«Por responder» · «Todos» · «Cerrados», plus «Pago por revisar · N» only with N ≥ 1
    and «Se te pasaron · N» only while it is the filter on screen. Counted on the
    channel the list shows."""
    keys = list(BASE_FILTERS)
    if count_of(counts, FILTER_PAYMENT, channel) > 0 or active == FILTER_PAYMENT:
        keys.append(FILTER_PAYMENT)
    if active == FILTER_EXPIRED:
        keys.append(FILTER_EXPIRED)
    return [
        ChipVM(key=k, label=chip_label(k, count_of(counts, k, channel)), pressed=k == active)
        for k in keys
    ]


def channels_with_chats(counts: CountsLike | None) -> list[str]:
    """The UI channels that hold at least one chat, open or closed."""
    return [
        c
        for c in CHANNELS
        if count_of(counts, FILTER_ALL, c) + count_of(counts, FILTER_CLOSED, c) > 0
    ]


def show_channel_filter(counts: CountsLike | None) -> bool:
    """[Todos] [Instagram] [WhatsApp] only with chats on two or more channels."""
    return len(channels_with_chats(counts)) >= 2


def channel_chips(active: str) -> list[ChipVM]:
    return [ChipVM(key=ALL_CHANNELS, label=ALL_CHANNELS_LABEL, pressed=active == ALL_CHANNELS)] + [
        ChipVM(key=c, label=channel_label(c), pressed=active == c) for c in CHANNELS
    ]


# ======================================================================================
# The expired notice («tell them once»)
# ======================================================================================


def notice_text(count: int) -> str:
    return NOTICE_ONE if count == 1 else NOTICE_MANY.format(n=count)


def show_notice(*, filter_key: str, channel: str, expired: int, dismissed: int) -> bool:
    """Inside «Por responder» (every channel or Instagram), while some Instagram chat
    expired unanswered and the number grew past the one the owner dismissed."""
    return (
        filter_key == FILTER_AWAITING
        and channel in (ALL_CHANNELS, CHANNEL_INSTAGRAM)
        and expired > 0
        and expired > dismissed
    )


def remembered_dismissal(dismissed: int, expired: int) -> int:
    """What stays remembered after a new count: never above the current number, so a
    later growth from a lower number shows the notice again."""
    return max(0, min(dismissed, expired))


# ======================================================================================
# Empty states
# ======================================================================================


def channels_words(connected: Sequence[str]) -> str:
    """«WhatsApp o Instagram», «WhatsApp», «Instagram» — only what the business has."""
    names = [channel_label(c) for c in (CHANNEL_WHATSAPP, CHANNEL_INSTAGRAM) if c in connected]
    return (
        " o ".join(names)
        if names
        else " o ".join(channel_label(c) for c in (CHANNEL_WHATSAPP, CHANNEL_INSTAGRAM))
    )


@dataclass(frozen=True)
class EmptyVM:
    title: str
    body: str
    #: The way out: "" (none), "create" (the next publication) or "awaiting" (back to
    #: «Por responder»).
    action: str


def empty_for(filter_key: str, connected: Sequence[str]) -> EmptyVM:
    words = channels_words(connected)
    if filter_key == FILTER_AWAITING:
        return EmptyVM(EMPTY_AWAITING_TITLE, EMPTY_AWAITING_BODY.format(channels=words), "create")
    if filter_key == FILTER_ALL:
        return EmptyVM("", EMPTY_ALL.format(channels=words), "create")
    if filter_key == FILTER_CLOSED:
        return EmptyVM("", EMPTY_CLOSED, "awaiting")
    if filter_key == FILTER_PAYMENT:
        return EmptyVM("", FILTER_PAYMENT_EMPTY, "awaiting")
    return EmptyVM("", EMPTY_EXPIRED, "awaiting")


# ======================================================================================
# The adapter: one `InboxRow` → the shared row
# ======================================================================================


class InboxRowLike(Protocol):
    """`qualify_api.inbox.unified.InboxRow`."""

    thread_id: Any
    channel: str
    connection_id: Any
    counterpart_name: str | None
    counterpart_username: str | None
    counterpart_avatar_url: str | None
    counterpart_phone: str | None
    last_message_at: datetime | None
    last_message_text: str | None
    last_message_kind: str | None
    last_message_direction: str | None
    awaiting_reply: bool
    window_open: bool
    window_closes_at: datetime | None
    assigned_agent_id: Any
    window_expired_unanswered: bool

    @property
    def is_closed(self) -> bool: ...

    @property
    def payment_review(self) -> bool: ...

    @property
    def payment_awaiting(self) -> bool: ...


class AgentLike(Protocol):
    name: str
    initials: str


def _preview(row: InboxRowLike, channel: str) -> tuple[str, str]:
    text = (row.last_message_text or "").strip()
    icon = ""
    kind = (row.last_message_kind or "").strip().lower()
    if not text and kind and kind != "text":
        if channel == CHANNEL_INSTAGRAM:
            label, icon, _control = media_label(kind)
            text = UNSUPPORTED_PREVIEW if kind == "other" else label
        else:
            text, icon = _WHATSAPP_KINDS.get(kind, _WHATSAPP_OTHER)
    if not text:
        return NO_MESSAGES_YET, ""
    if row.last_message_direction == "outbound":
        return OUTBOUND_PREFIX + text, icon
    return text, icon


def _title(row: InboxRowLike, channel: str) -> tuple[str, str]:
    """(title, what the initials come from). A number gives no initials."""
    name = (row.counterpart_name or "").strip()
    handle = (row.counterpart_username or "").strip().lstrip("@")
    if name:
        return name, name
    if handle:
        return f"@{handle}", handle
    phone = (row.counterpart_phone or "").strip()
    if phone:
        return phone_label(phone), ""
    return unknown_contact(channel), ""


def as_chat_row(
    row: InboxRowLike,
    *,
    now: datetime,
    zone: tzinfo,
    agents: Mapping[str, AgentLike] | None = None,
) -> ChatRowVM | None:
    """The shared row for one chat of the unified list; None for a channel the screen
    does not draw (TikTok before it exists)."""
    channel = BACKEND_TO_UI.get(row.channel)
    if channel is None:
        return None
    title, initials_from = _title(row, channel)
    preview, icon = _preview(row, channel)
    agent_id = str(row.assigned_agent_id) if row.assigned_agent_id else ""
    agent = (agents or {}).get(agent_id) if agent_id else None
    agent_initials = agent.initials if agent else ("?" if agent_id else "")
    agent_name = agent.name if agent else ("Otra persona" if agent_id else "")
    return build_chat_row(
        thread_id=str(row.thread_id),
        channel=channel,
        title=title,
        preview=preview,
        preview_icon=icon,
        time_label=relative_time(row.last_message_at, now, zone),
        waiting=bool(row.awaiting_reply) and not row.is_closed,
        initials_from=initials_from,
        payment_review=row.payment_review,
        payment_awaiting=row.payment_awaiting,
        reply_within_minutes=(
            minutes_left(row.window_open, row.window_closes_at, now) if row.awaiting_reply else 0
        ),
        expired=bool(row.window_expired_unanswered),
        avatar_url=(row.counterpart_avatar_url or "").strip(),
        agent_initials=agent_initials,
        agent_name=agent_name,
        closed=row.is_closed,
        connection_id=str(row.connection_id),
    )


def as_chat_rows(
    rows: Sequence[InboxRowLike],
    *,
    now: datetime,
    zone: tzinfo,
    agents: Mapping[str, AgentLike] | None = None,
) -> list[ChatRowVM]:
    built = (as_chat_row(r, now=now, zone=zone, agents=agents) for r in rows)
    return [r for r in built if r is not None]
