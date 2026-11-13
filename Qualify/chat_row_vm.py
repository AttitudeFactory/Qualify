"""One chat row for every channel (m-25017844, epic m-25017839 «Bandeja única», BU-A2).

WhatsApp → Chats and Conversaciones (Instagram Direct) keep their own data source, state
and `ThreadRowVM`; what they draw in the list is THIS shape, built by each channel's
adapter (`whatsapp_chats_vm.as_chat_row`, `conversations_vm.as_chat_row`) and rendered by
`chat_row.chat_row`. A later story (m-25017859) puts both channels in one list with this
same row.

The anatomy (docs/ux-chats-unificados.md §2): picture or initial with the channel's glyph
on its corner, a breathing dot while the customer waits, name, time, a second line
(@handle or phone), the preview («Tú: » when the business wrote last) and **one** attention
pill — the most urgent of «Pago por revisar» › «Responde en N min» › «Quiere comprar»,
chosen here, never in the view. «Cerrado» is not on the row: the filter already says it.

Pure: no state, no I/O; imports neither channel module (they import this one).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from .ui.tokens import PLATFORM_LABEL

CHANNEL_WHATSAPP: Final = "whatsapp"
CHANNEL_INSTAGRAM: Final = "instagram"

#: The three pills a row may carry, most urgent first (ticket m-25017844). The words are
#: the ones the product already uses: WhatsApp's filter, the reply drafts' badge.
PAYMENT_REVIEW_PILL: Final = "Pago por revisar"
WANTS_TO_BUY_PILL: Final = "Quiere comprar"
#: A window closing within this shows «Responde en N min» (both channels' warn threshold).
REPLY_SOON_WITHIN: Final = timedelta(hours=1)

#: What the waiting dot says (the Instagram row's existing words).
WAITING_LABEL: Final = "Sin responder"


def reply_soon_pill(minutes: int) -> str:
    """«Responde en 12 min» — the row's short form of a window about to close."""
    return f"Responde en {max(1, minutes)} min"


def minutes_left(is_open: bool, closes_at: datetime | None, now: datetime) -> int:
    """Whole minutes (rounded up) until the 24 h window closes, when that is under
    `REPLY_SOON_WITHIN`; 0 while the window is comfortably open or already closed."""
    if not is_open or closes_at is None:
        return 0
    remaining = closes_at - now
    if remaining <= timedelta(0) or remaining >= REPLY_SOON_WITHIN:
        return 0
    return max(1, math.ceil(remaining.total_seconds() / 60))


def attention_pill(
    *, payment_review: bool, reply_within_minutes: int, wants_to_buy: bool
) -> tuple[str, str]:
    """(label, tone) of the row's ONE pill; ("", "neutral") when nothing asks for it.
    A payment to check beats a window about to close, which beats a purchase intent."""
    if payment_review:
        return PAYMENT_REVIEW_PILL, "warn"
    if reply_within_minutes > 0:
        return reply_soon_pill(reply_within_minutes), "warn"
    if wants_to_buy:
        return WANTS_TO_BUY_PILL, "info"
    return "", "neutral"


def channel_label(channel: str) -> str:
    return PLATFORM_LABEL.get(channel, channel)


def unknown_contact(channel: str) -> str:
    """The name of a person the channel told us nothing about (m-25017852):
    «Cliente de Instagram», «Cliente de WhatsApp»."""
    return f"Cliente de {channel_label(channel)}"


def accessible_name(title: str, channel: str, *, waiting: bool, pill: str) -> str:
    """The row's one accessible name: «Ana, por WhatsApp, sin responder, Pago por
    revisar» — the channel always, the rest only when it applies."""
    parts = [title or unknown_contact(channel), f"por {channel_label(channel)}"]
    if waiting:
        parts.append(WAITING_LABEL.lower())
    if pill:
        parts.append(pill)
    return ", ".join(parts)


@dataclass(frozen=True)
class ChatRowVM:
    """What one chat row draws — the same fields for every channel."""

    thread_id: str
    channel: str  # CHANNEL_WHATSAPP | CHANNEL_INSTAGRAM
    title: str  # the person's name, else @handle / phone, else «Cliente de …»
    second_line: str  # «@handle» or «+57…» ("" when it would repeat the title)
    preview: str  # «Tú: …» when the business wrote last
    preview_icon: str  # "" or a Lucide name for a media / tapped preview
    time_label: str
    waiting: bool  # the customer wrote and nobody has seen it yet: the breathing dot
    pill_label: str  # "" or the ONE attention pill
    pill_tone: str
    initials: str
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
    second_line: str,
    preview: str,
    time_label: str,
    waiting: bool,
    initials: str,
    payment_review: bool = False,
    reply_within_minutes: int = 0,
    wants_to_buy: bool = False,
    preview_icon: str = "",
    avatar_url: str = "",
    agent_initials: str = "",
    agent_name: str = "",
    fresh: bool = False,
) -> ChatRowVM:
    """The one place the pill is chosen and the accessible name is worded."""
    title = title.strip() or unknown_contact(channel)
    pill_label, pill_tone = attention_pill(
        payment_review=payment_review,
        reply_within_minutes=reply_within_minutes,
        wants_to_buy=wants_to_buy,
    )
    return ChatRowVM(
        thread_id=thread_id,
        channel=channel,
        title=title,
        second_line="" if second_line == title else second_line,
        preview=preview,
        preview_icon=preview_icon,
        time_label=time_label,
        waiting=waiting,
        pill_label=pill_label,
        pill_tone=pill_tone,
        initials=initials or "?",
        avatar_url=avatar_url,
        agent_initials=agent_initials,
        agent_name=agent_name,
        fresh=fresh,
        aria_label=accessible_name(title, channel, waiting=waiting, pill=pill_label),
    )
