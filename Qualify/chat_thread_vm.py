"""The open chat both channels draw (m-25027371, BU-A5) — pure decisions, no Reflex.

WhatsApp → Chats (`whatsapp_tab_chats.py`) and Conversaciones (`conversations_page.py`)
draw ONE thread: the same header (back to «Por responder», name, channel, until when the
owner can write), the same «⋯» with the actions used seldom, the same bubbles, day
separators and status marks. This module words what both share; `chat_thread.py` draws
it. Each channel's VM still decides what only it knows (the 24 h window's closing time,
its own state words) and hands the result here.

Words fixed elsewhere and NOT changed here: «Cerrar» / «Reabrir» and the «Cerrado» tag
(m-25026457), «Quedan {N} min para responder» (`chat_row_vm`, founder 2026-11-13),
«Puedes escribirle hasta las {hora}» (WhatsApp's header since m-24842994).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, tzinfo
from typing import Final

from .chat_row_vm import (
    CHANNEL_INSTAGRAM,
    CHANNEL_WHATSAPP,
    channel_label,
    minutes_left,
    reply_soon_pill,
)
from .ui.tokens import platform_scale

# ======================================================================================
# Words
# ======================================================================================

#: The «⋯» button's accessible name (it has no visible text).
MORE_ACTIONS_LABEL: Final = "Más acciones de este chat"
#: The menu's group of people the chat can be given to (ticket «Asignar»).
ASSIGN_LABEL: Final = "Asignar"
UNASSIGNED_LABEL: Final = "Sin asignar"
#: m-25026457: the founder chose these words for both channels; the ticket's «Cerrar
#: chat» is NOT applied (reported to the lead).
CLOSE_LABEL: Final = "Cerrar"
REOPEN_LABEL: Final = "Reabrir"
CLOSED_TAG: Final = "Cerrado"
#: Ticket m-25027371 «Texto para el cliente».
SETTINGS_LABEL: Final = "Ajustes de este canal"
#: The order strip's first word (ticket: «Pedido · {N} productos · {total} · …»).
ORDER_STRIP_WORD: Final = "Pedido"
#: The thread with no message yet (both channels already said this).
NO_MESSAGES: Final = "Aún no hay mensajes en esta conversación."
#: The day separators.
TODAY: Final = "Hoy"
YESTERDAY: Final = "Ayer"
_MONTHS: Final = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

#: UX PROPOSAL (m-25017860 «D2 medido» (c), awaiting the founder): links inside a bubble
#: in `--accent-12` (`rx.link(high_contrast=True)`) instead of Radix's default
#: `--accent-a11`, which measured under 4.5:1 on the tinted bubble. One line to flip.
BUBBLE_LINK_HIGH_CONTRAST: Final = True

#: Where «Ajustes de este canal» goes until «Ajustes de chats» exists (m-25017861). On
#: WhatsApp, the automatic reply — what the owner wants to fix when the menu answered
#: wrong (D1's reason). Instagram's own setting today is «Preguntas iniciales», which the
#: page opens in its drawer (no route).
WHATSAPP_SETTINGS_HREF: Final = "/whatsapp?tab=respuesta"


# ======================================================================================
# The «⋯» menu
# ======================================================================================


def show_assign(people_with_access: int) -> bool:
    """«Asignar» only when the business has more than one person with access (ticket
    m-25027371; UX §6 1: a one-person shop has nobody to give the chat to)."""
    return people_with_access > 1


# ======================================================================================
# The header's window line
# ======================================================================================


def window_line(
    is_open: bool,
    closes_at: datetime | None,
    now: datetime,
    zone: tzinfo,
    *,
    closed_text: str = "",
) -> tuple[str, str]:
    """(text, tone) of the header line that says until when the owner can write.

    Open with more than an hour left → «Puedes escribirle hasta las 17:47» (`ok`), or
    «… hasta mañana a las 01:18» when it closes on another day of the tenant's calendar
    — the bubbles' 24 h clock, and the clock of Instagram's composer line;
    under an hour → the row's own «Quedan 12 min para responder» (`warn`), the same
    count (`chat_row_vm.minutes_left`); closed → `closed_text` (each channel says what
    the owner can still do) with the `neutral` tone, "" for no line."""
    minutes = minutes_left(is_open, closes_at, now)
    if not is_open or closes_at is None or closes_at <= now:
        return closed_text, "neutral"
    if minutes:
        return reply_soon_pill(minutes), "warn"
    local_close = _local(closes_at, zone)
    # The bubbles' clock (24 h, «17:47»): one fact, one way of saying the time.
    clock = local_close.strftime("%H:%M")
    if local_close.date() == _local(now, zone).date():
        return f"Puedes escribirle hasta las {clock}", "ok"
    return f"Puedes escribirle hasta mañana a las {clock}", "ok"


def _local(value: datetime, zone: tzinfo) -> datetime:
    return value.astimezone(zone) if value.tzinfo is not None else value


# ======================================================================================
# Day separators
# ======================================================================================


def day_label(value: datetime, zone: tzinfo, now: datetime) -> str:
    """«Hoy» · «Ayer» · «12 oct» (same year) · «12 oct 2025», in the tenant's calendar."""
    local, today = _local(value, zone), _local(now, zone)
    days = (today.date() - local.date()).days
    if days == 0:
        return TODAY
    if days == 1:
        return YESTERDAY
    label = f"{local.day} {_MONTHS[local.month - 1]}"
    if local.year != today.year:
        label += f" {local.year}"
    return label


def mark_days[T](
    items: Sequence[tuple[datetime, T]],
    zone: tzinfo,
    now: datetime,
    with_day: Callable[[T, str], T],
) -> list[T]:
    """Chronological `(instant, vm)` pairs → the vms, the first of each day carrying its
    separator (`with_day(vm, label)`); the rest unchanged."""
    out: list[T] = []
    last = ""
    for instant, vm in items:
        label = day_label(instant, zone, now)
        if label != last:
            vm = with_day(vm, label)
            last = label
        out.append(vm)
    return out


# ======================================================================================
# The order strip (WhatsApp)
# ======================================================================================


def order_strip_label(items_label: str, total_label: str, payment_label: str = "") -> str:
    """«Pedido · 3 productos · COP 45.000 · Pago por revisar» — the folded order. Empty
    parts are left out (an order with no payment yet has no payment part)."""
    parts = [ORDER_STRIP_WORD, items_label, total_label, payment_label]
    return " · ".join(p.strip() for p in parts if p and p.strip())


# ======================================================================================
# The channel's colour (D2 measured, m-25017860)
# ======================================================================================


def thread_style(channel: str) -> dict[str, str]:
    """The CSS custom properties `.q-chat-thread` paints with: the channel's scale from
    `T.PLATFORM_SCALE` (whatsapp green, instagram pink) at the measured alpha steps —
    the business bubble `a4 → a3` with an `a5` ring, the header's wash `a3`. One rule
    set in `assets/qualify-inbox.css` reads them; no channel has its own rules."""
    scale = platform_scale(channel)
    return {
        "--q-chat-tint-2": f"var(--{scale}-a2)",
        "--q-chat-tint-3": f"var(--{scale}-a3)",
        "--q-chat-tint-4": f"var(--{scale}-a4)",
        "--q-chat-tint-5": f"var(--{scale}-a5)",
        "--q-chat-solid": f"var(--{scale}-9)",
        "--q-chat-contrast": f"var(--{scale}-contrast)",
    }


def channel_name(channel: str) -> str:
    """«WhatsApp» / «Instagram» — the header's channel word."""
    return channel_label(channel)


__all__ = [
    "ASSIGN_LABEL",
    "CHANNEL_INSTAGRAM",
    "CHANNEL_WHATSAPP",
    "CLOSED_TAG",
    "CLOSE_LABEL",
    "MORE_ACTIONS_LABEL",
    "NO_MESSAGES",
    "ORDER_STRIP_WORD",
    "REOPEN_LABEL",
    "SETTINGS_LABEL",
    "TODAY",
    "UNASSIGNED_LABEL",
    "WHATSAPP_SETTINGS_HREF",
    "YESTERDAY",
    "channel_name",
    "day_label",
    "mark_days",
    "order_strip_label",
    "show_assign",
    "thread_style",
    "window_line",
]
