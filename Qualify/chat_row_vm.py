"""One chat row for every channel (m-25017844, epic m-25017839 «Bandeja única», BU-A2).

WhatsApp → Chats and Conversaciones (Instagram Direct) keep their own data source, state
and `ThreadRowVM`; what they draw in the list is THIS shape, built by each channel's
adapter (`whatsapp_chats_vm.as_chat_row`, `conversations_vm.as_chat_row`) and rendered by
`chat_row.chat_row`. A later story (m-25017859) puts both channels in one list with this
same row.

The anatomy (docs/ux-chats-unificados.md §2): picture or initial with the channel's glyph
on its corner, a breathing dot while the customer waits, name, time, the preview («Tú: »
when the business wrote last) and **one** attention
pill — the most urgent one, chosen here, never in the view. «Cerrado» is not on the row:
the filter already says it.

Pure: no state, no I/O; imports neither channel module (they import this one).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from .ui.tokens import PLATFORM_LABEL

CHANNEL_WHATSAPP: Final = "whatsapp"
CHANNEL_INSTAGRAM: Final = "instagram"

#: The pills a row may carry, most urgent first (ticket m-25017844 + its UX review). The
#: words are the ones the product already uses: WhatsApp's payment states, the reply
#: drafts' badge. «Pago recibido» and «Paga al recibir» never reach the row.
PAYMENT_REVIEW_PILL: Final = "Pago por revisar"
WANTS_TO_BUY_PILL: Final = "Quiere comprar"
AWAITING_PAYMENT_PILL: Final = "Esperando el pago"
#: A window closing within this shows the reply-soon pill (both channels' warn threshold).
REPLY_SOON_WITHIN: Final = timedelta(hours=1)
#: The reply-soon pill's words, in ONE place (wording pending the founder's call).
REPLY_SOON_TEMPLATE: Final = "Responde en {minutes} min"

#: What the waiting dot means, per channel, in each screen's own filter words: WhatsApp's
#: dot is unread messages («Sin leer»); Instagram's is «Pendiente» (not answered yet).
WAITING_LABELS: Final[dict[str, str]] = {
    CHANNEL_WHATSAPP: "sin leer",
    CHANNEL_INSTAGRAM: "sin responder",
}


def reply_soon_pill(minutes: int) -> str:
    """«Responde en 12 min» — the row's short form of a window about to close."""
    return REPLY_SOON_TEMPLATE.format(minutes=max(1, minutes))


def minutes_left(is_open: bool, closes_at: datetime | None, now: datetime) -> int:
    """Whole minutes until the 24 h window closes, when that is under
    `REPLY_SOON_WITHIN`; 0 while the window is comfortably open or already closed.
    Rounded DOWN (59:59 → 59, never «60 min» under an hour) with a floor of 1 (0:30 →
    1). The one count the rows and the chat headers of both channels use."""
    if not is_open or closes_at is None:
        return 0
    remaining = closes_at - now
    if remaining <= timedelta(0) or remaining >= REPLY_SOON_WITHIN:
        return 0
    return max(1, int(remaining.total_seconds() // 60))


def attention_pill(
    *,
    payment_review: bool,
    reply_within_minutes: int,
    wants_to_buy: bool = False,
    payment_awaiting: bool = False,
) -> tuple[str, str]:
    """(label, tone) of the row's ONE pill; ("", "neutral") when nothing asks for it.
    «Pago por revisar» › «Quiere comprar» › «Responde en N min» › «Esperando el pago»:
    a window about to close outranks a payment that is only being waited for."""
    if payment_review:
        return PAYMENT_REVIEW_PILL, "warn"
    if wants_to_buy:
        return WANTS_TO_BUY_PILL, "info"
    if reply_within_minutes > 0:
        return reply_soon_pill(reply_within_minutes), "warn"
    if payment_awaiting:
        return AWAITING_PAYMENT_PILL, "neutral"
    return "", "neutral"


_WORD_BREAKS = str.maketrans({ch: " " for ch in "._-@"})


def letter_initials(name: str) -> str:
    """Up to two initials from the first LETTER of the first and last words that have
    one: «Laura Gómez» → «LG», «@yesii_roa» → «YR», «🇨🇴 Laura» → «L», «~Juan» → «J».
    Emoji, symbols, digits and combining marks never count; "" when there is no letter
    (the avatar then shows the person icon)."""
    letters: list[str] = []
    for word in name.translate(_WORD_BREAKS).split():
        letter = next((ch for ch in word if unicodedata.category(ch).startswith("L")), "")
        if letter:
            letters.append(letter.upper())
    if not letters:
        return ""
    return letters[0] if len(letters) == 1 else letters[0] + letters[-1]


def channel_label(channel: str) -> str:
    return PLATFORM_LABEL.get(channel, channel)


def unknown_contact(channel: str) -> str:
    """The name of a person the channel told us nothing about (m-25017852):
    «Cliente de Instagram»; «Cliente de WhatsApp» for a chat with neither name nor number."""
    return f"Cliente de {channel_label(channel)}"


def accessible_name(title: str, channel: str, *, waiting: bool, pill: str) -> str:
    """The row's one accessible name: «Ana, por WhatsApp, sin leer, Pago por revisar» —
    the channel always, the rest only when it applies."""
    parts = [title or unknown_contact(channel), f"por {channel_label(channel)}"]
    if waiting:
        parts.append(WAITING_LABELS.get(channel, "sin responder"))
    if pill:
        parts.append(pill)
    return ", ".join(parts)


@dataclass(frozen=True)
class ChatRowVM:
    """What one chat row draws — the same fields for every channel."""

    thread_id: str
    channel: str  # CHANNEL_WHATSAPP | CHANNEL_INSTAGRAM
    title: str  # the person's name, else @handle / phone, else «Cliente de …»
    preview: str  # «Tú: …» when the business wrote last
    preview_icon: str  # "" or a Lucide name for a media / tapped preview
    time_label: str
    waiting: bool  # the breathing dot (WhatsApp: unread; Instagram: «Pendiente»)
    pill_label: str  # "" or the ONE attention pill
    pill_tone: str
    initials: str  # "" → the avatar shows the person icon
    avatar_url: str
    agent_initials: str  # who attends it, when a team shares the number
    agent_name: str
    fresh: bool  # one pulse after a refresh brought a newer inbound
    aria_label: str


def build_chat_row(
    *,
    thread_id: str,
    channel: str,
    title: str,
    preview: str,
    time_label: str,
    waiting: bool,
    initials_from: str,
    payment_review: bool = False,
    payment_awaiting: bool = False,
    reply_within_minutes: int = 0,
    # A slot with no backend signal yet: no channel knows a chat's purchase intent today.
    wants_to_buy: bool = False,
    preview_icon: str = "",
    avatar_url: str = "",
    agent_initials: str = "",
    agent_name: str = "",
    fresh: bool = False,
) -> ChatRowVM:
    """The one place the pill is chosen, the initials are taken and the accessible name
    is worded. `initials_from` is the person's name or handle ("" when only a number or
    nothing is known)."""
    title = title.strip() or unknown_contact(channel)
    pill_label, pill_tone = attention_pill(
        payment_review=payment_review,
        reply_within_minutes=reply_within_minutes,
        wants_to_buy=wants_to_buy,
        payment_awaiting=payment_awaiting,
    )
    return ChatRowVM(
        thread_id=thread_id,
        channel=channel,
        title=title,
        preview=preview,
        preview_icon=preview_icon,
        time_label=time_label,
        waiting=waiting,
        pill_label=pill_label,
        pill_tone=pill_tone,
        initials=letter_initials(initials_from),
        avatar_url=avatar_url,
        agent_initials=agent_initials,
        agent_name=agent_name,
        fresh=fresh,
        aria_label=accessible_name(title, channel, waiting=waiting, pill=pill_label),
    )
