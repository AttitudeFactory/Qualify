"""The single chat list under «Por responder» › «Mensajes» (m-25017859, BU-A3).

Every connected chat channel in ONE list (`qualify_api.inbox.unified.list_inbox`),
newest activity first, drawn with the shared row (`chat_row_vm.ChatRowVM`) through the
adapter here (`as_chat_row`). The chips and the channel filter read `inbox_counts` — the
same SQL text the list filters by — so each chip's number is the length of its list.

Tree (docs/ux-chats-unificados.md §2):

    Por responder › Mensajes
      [Todos] [Instagram] [WhatsApp]          only with chats on 2+ channels; no TikTok
      [Todos los números ▾]                   one select, only with 2+ WhatsApp numbers
      [Por responder · N] [Todos · N] [Cerrados · N] (+ [Pago por revisar · N] if N ≥ 1)
      «N chats de Instagram ya no se pueden responder aquí · Ver»   (in «Por responder»)
      the rows · «Ver más»

**WhatsApp's own list, retired (m-25029799).** Its chips land here: «Abiertos» (the
open chats of the number on screen, answered or not) is «Todos» — the same rule
(`status = 'open'`), proven against WhatsApp's own read in
`packages/api/tests/test_inbox_unified_numbers_db.py`; its old `sin-leer` is «Por
responder»; and its «Elige un número» is the number choice above the chips, drawn only
for a business with two or more WhatsApp numbers (`?numero=<connection id>`), counted by
`inbox_counts` per account. Instagram accounts are never split: the list has always
shown them together, as it shows every number together until one is picked.

Pure: no Reflex, no database.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
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
from .nav_url import scalar_param, uuid_param, with_query
from .whatsapp_chats_vm import phone_label, relative_time

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
#: m-25029799: one WhatsApp number (a connection id). "" = every number.
NUMBER_PARAM: Final = "numero"
ALL_NUMBERS: Final = ""

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
    FILTER_EXPIRED: "Sin responder a tiempo",
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
    "sin-responder-a-tiempo": FILTER_EXPIRED,
    # m-25029799: WhatsApp's retired list. Its «Abiertos» (open chats, answered or not)
    # is this list's «Todos»; its «Sin leer» became «Por responder» (m-25017859).
    "abiertos": FILTER_ALL,
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
    FILTER_EXPIRED: "sin-responder-a-tiempo",
}

PAGE_SIZE: Final = 50
#: m-25017859 (review): a heartbeat tick re-reads at most this many pages — the first
#: page plus one more — however far «Ver más» went: one `inbox_counts` + at most two
#: page statements per 15 s, on a 4 GB server with one Reflex worker.
REFRESH_PAGES: Final = 2


def sort_key(last_message_at: datetime | None, thread_id: str) -> str:
    """The row's place in `list_inbox`'s order (`last_message_at DESC NULLS LAST, id
    DESC`) as a string: «1|<UTC instant, fixed width>|<uuid>» for a dated chat, «0||<uuid>»
    for an undated one. A plain string comparison is the list order reversed: a GREATER
    key comes FIRST (canonical lowercase UUID hex compares as Postgres orders uuid)."""
    if last_message_at is None:
        return f"0||{thread_id}"
    instant = last_message_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return f"1|{instant}|{thread_id}"


def merge_refreshed(
    head: Sequence[ChatRowVM], current: Sequence[ChatRowVM], *, complete: bool
) -> list[ChatRowVM]:
    """A capped tick's rows: the re-read `head` (the first pages, in list order), then
    every row already listed that sorts AFTER the head's last row and is not in the head,
    in order. A row pushed across the seam by newer chats stays (nothing between head
    and tail vanishes), one that moved into the head appears once, and «Ver más» goes on
    from the tail's own cursor. `complete`: the head reached the end of the list, so it
    IS the list. A retained row may be stale until the view changes; it still opens."""
    if complete or not head:
        return list(head)
    seen = {r.thread_id for r in head}
    last = head[-1].sort_key
    return [*head, *[r for r in current if r.thread_id not in seen and r.sort_key < last]]


# --------------------------------------------------------------------------------------
# Words (qualify-copy-es). Founder-decided: «Por responder», «Todos», «Cerrados»,
# «Pago por revisar · {N}», «WhatsApp», «Instagram», the empty «Por responder» text.
# Founder-decided 2026-11-13 («Sí, los de UX»): the expired notice and pill. Applied with
# them by the coordinator, to confirm: «Sin responder a tiempo». UX proposals: the other
# empty texts.
# --------------------------------------------------------------------------------------

#: The one-time explanation of why the numbers moved (founder, 2026-11-14: «Solo dos
#: semanas»). Shown on «Mensajes» until `EXPLAINER_UNTIL` (excluded), the day judged in
#: the business's time zone; «Entendido» hides it for the session of that business.
EXPLAINER_TEXT: Final = (
    'Ahora "Por responder" muestra solo a quien espera que una persona le conteste. '
    "Los chats que ya resolvió tu menú no cuentan."
)
EXPLAINER_ACTION: Final = "Entendido"
#: m-25017859: from this day on the explanation never renders — delete it, its state
#: (`InboxListState.explainer_*`) and its tests after this date.
EXPLAINER_UNTIL: Final = date(2026, 11, 28)


def explainer_shown(today: date, *, dismissed: bool) -> bool:
    """Before `EXPLAINER_UNTIL` and not dismissed in this session."""
    return not dismissed and today < EXPLAINER_UNTIL


MORE_LABEL: Final = "Ver más"
FILTERS_ARIA: Final = "Qué chats ver"
CHANNELS_ARIA: Final = "De qué red"
#: m-25029799 — NEW TEXTS, NOT DECIDED BY THE FOUNDER: the number choice that replaces
#: WhatsApp's «Elige un número» inside «Por responder».
NUMBERS_ARIA: Final = "De qué número de WhatsApp"
ALL_NUMBERS_LABEL: Final = "Todos los números"

NOTICE_ONE: Final = "1 chat de Instagram ya no se puede responder aquí"
NOTICE_MANY: Final = "{n} chats de Instagram ya no se pueden responder aquí"
NOTICE_ACTION: Final = "Ver"
NOTICE_DISMISS: Final = "Ocultar este aviso"

EMPTY_AWAITING_TITLE: Final = "Ya respondiste a todos."
EMPTY_AWAITING_BODY: Final = "Aquí verás a quien te escriba por {channels}."
EMPTY_ALL: Final = "Todavía no tienes chats. Aquí verás a quien te escriba por {channels}."
EMPTY_CLOSED: Final = "No tienes chats cerrados."
#: m-24971198's own words for an empty «Pago por revisar» (moved here from WhatsApp's
#: retired list, m-25029799; unchanged).
EMPTY_PAYMENT: Final = (
    "No hay pagos por revisar. Cuando un cliente te mande su comprobante, su chat aparece aquí."
)
EMPTY_EXPIRED: Final = (
    "Ningún chat de Instagram se quedó sin responder a tiempo en la última semana."
)
EMPTY_BACK: Final = "Ver por responder"
#: m-25029799 (UX review): the WhatsApp view's way out — WhatsApp's own empty list's
#: words («Crear un código QR», unchanged) and «Ajustes de chats › Códigos QR» (its own
#: page since m-25027373).
EMPTY_QR_ACTION: Final = "qr"
EMPTY_QR_LABEL: Final = "Crear un código QR"
EMPTY_QR_HREF: Final = "/chats/ajustes/whatsapp/codigos-qr"

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


def number_from_params(params: Mapping[str, object]) -> str:
    """`?numero=` → a canonical connection id, else "" (every number). Whether it is one
    of THIS business's numbers is the state's check (`known_number`)."""
    return uuid_param(params, NUMBER_PARAM)


def known_number(number: str, numbers: Sequence[NumberVM]) -> str:
    """`number` when it is one of the business's WhatsApp numbers AND the choice is drawn
    (two or more numbers), else "" — an id from an address or the browser never narrows
    the list to an account it does not own, nor to a number the owner cannot un-pick."""
    if not number or len(numbers) < 2:
        return ""
    return number if any(n.connection_id == number for n in numbers) else ""


def list_href(
    filter_key: str = DEFAULT_FILTER, channel: str = ALL_CHANNELS, number: str = ALL_NUMBERS
) -> str:
    """The single list's address: `/responder?tab=mensajes&filtro=…&canal=…&numero=…`
    (a number is a WhatsApp one: it always rides with `canal=whatsapp`)."""
    slug = _KEY_TO_SLUG.get(filter_key, _KEY_TO_SLUG[DEFAULT_FILTER])
    numero = uuid_param({NUMBER_PARAM: number}, NUMBER_PARAM)
    canal = CHANNEL_WHATSAPP if numero else (channel if channel in CHANNELS else "")
    return with_query(
        ROUTE, tab=TAB, **{FILTER_PARAM: slug, CHANNEL_PARAM: canal, NUMBER_PARAM: numero}
    )


# ======================================================================================
# Chips
# ======================================================================================


class CountsLike(Protocol):
    """`qualify_api.inbox.unified.InboxCounts` (backend channel names; per account since
    m-25029799)."""

    by_channel: Mapping[str, Mapping[str, int]]
    by_connection: Mapping[str, Mapping[str, int]]


@dataclass(frozen=True)
class ChipVM:
    key: str
    label: str
    pressed: bool


def count_of(
    counts: CountsLike | None,
    filter_key: str,
    channel: str = ALL_CHANNELS,
    number: str = ALL_NUMBERS,
) -> int:
    """How many chats `filter_key` lists on `channel` (every channel with ""), or on one
    WhatsApp `number` (m-25029799: that number's own count, whatever `channel` says — a
    number is always a WhatsApp one)."""
    if counts is None:
        return 0
    if number:
        by_number = getattr(counts, "by_connection", None) or {}
        return max(0, int(by_number.get(number, {}).get(filter_key, 0)))
    backend = [UI_TO_BACKEND[channel]] if channel in UI_TO_BACKEND else list(counts.by_channel)
    return sum(max(0, int(counts.by_channel.get(c, {}).get(filter_key, 0))) for c in backend)


def chip_label(filter_key: str, count: int) -> str:
    """«Por responder · 3»; the bare name at 0."""
    label = FILTER_LABELS.get(filter_key, filter_key)
    return f"{label} · {count}" if count > 0 else label


def filter_chips(
    counts: CountsLike | None, active: str, channel: str, number: str = ALL_NUMBERS
) -> list[ChipVM]:
    """«Por responder» · «Todos» · «Cerrados», plus «Pago por revisar · N» only with N ≥ 1
    and «Sin responder a tiempo · N» only while it is the filter on screen. Counted on the
    channel the list shows — on the number, when one is picked (m-25029799)."""
    keys = list(BASE_FILTERS)
    if count_of(counts, FILTER_PAYMENT, channel, number) > 0 or active == FILTER_PAYMENT:
        keys.append(FILTER_PAYMENT)
    if active == FILTER_EXPIRED:
        keys.append(FILTER_EXPIRED)
    return [
        ChipVM(
            key=k, label=chip_label(k, count_of(counts, k, channel, number)), pressed=k == active
        )
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
# The number choice (m-25029799: WhatsApp's «Elige un número», now in «Por responder»)
# ======================================================================================


@dataclass(frozen=True)
class NumberVM:
    """One WhatsApp number of the business: its connection id and its words
    («+57 300 000 0000 · Arepera», `whatsapp_vm.build_number_vm`'s label)."""

    connection_id: str
    label: str


def show_number_filter(numbers: Sequence[NumberVM], channel: str) -> bool:
    """Only for a business with two or more WhatsApp numbers, and never on the Instagram
    view (a number lists no Instagram chat)."""
    return len(numbers) >= 2 and channel != CHANNEL_INSTAGRAM


#: The select's value for «Todos los números» (a Radix select item cannot be "").
ALL_NUMBERS_KEY: Final = "todos"


def number_options(numbers: Sequence[NumberVM]) -> list[NumberVM]:
    """The one-line select (UX review of m-25029799, as `/whatsapp`'s own number
    picker): «Todos los números», then each number in the business's own order."""
    return [NumberVM(connection_id=ALL_NUMBERS_KEY, label=ALL_NUMBERS_LABEL), *numbers]


def number_select_value(number: str) -> str:
    """The select's value for the number on screen ("" = every number)."""
    return number or ALL_NUMBERS_KEY


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
    #: The way out: "" (none), "create" (the next publication), "qr" (a WhatsApp QR
    #: code, on the WhatsApp view) or "awaiting" (back to «Por responder»).
    action: str


def empty_for(filter_key: str, connected: Sequence[str], channel: str = ALL_CHANNELS) -> EmptyVM:
    """The empty list's words and way out. On the WhatsApp view (m-25029799, UX review)
    the way out is a QR code — how customers start writing on WhatsApp — as WhatsApp's
    own list offered, instead of the next publication."""
    words = channels_words(connected)
    # The WhatsApp view, or a business whose only chat channel is WhatsApp.
    whatsapp = channel == CHANNEL_WHATSAPP or list(connected) == [CHANNEL_WHATSAPP]
    first = EMPTY_QR_ACTION if whatsapp else "create"
    if filter_key == FILTER_AWAITING:
        return EmptyVM(EMPTY_AWAITING_TITLE, EMPTY_AWAITING_BODY.format(channels=words), first)
    if filter_key == FILTER_ALL:
        return EmptyVM("", EMPTY_ALL.format(channels=words), first)
    if filter_key == FILTER_CLOSED:
        return EmptyVM("", EMPTY_CLOSED, "awaiting")
    if filter_key == FILTER_PAYMENT:
        return EmptyVM("", EMPTY_PAYMENT, "awaiting")
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
        sort_key=sort_key(row.last_message_at, str(row.thread_id)),
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
