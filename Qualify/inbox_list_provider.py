"""Backend access of the single chat list (m-25017859, BU-A3), in process.

The list and its counts come from `qualify_api.inbox.unified` (one `tenant_session`
round trip each, RLS-scoped); the once-per-entry context (the tenant's time zone, the
members a chat can be assigned to, which chat channels are connected) from the
channels' existing gateways. Nothing here reads per row. Blocking — the state calls
every function through `asyncio.to_thread`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from qualify_api.inbox.unified import InboxCounts, InboxPage, inbox_counts, list_inbox

from .chat_row_vm import CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP
from .conversations_provider import gateway as conversations_gateway
from .inbox_list_vm import PAGE_SIZE, UI_TO_BACKEND, NumberVM
from .whatsapp_chats_provider import gateway as whatsapp_gateway
from .whatsapp_chats_vm import AgentVM
from .whatsapp_provider import numbers_for


@dataclass(frozen=True)
class InboxContext:
    zone_name: str
    agents: tuple[AgentVM, ...]
    #: The UI channels with a connected account (the empty state names only these).
    connected: tuple[str, ...]
    #: m-25029799: the business's WhatsApp numbers (RLS-scoped read), newest first — the
    #: number choice, and the check that a `?numero=` is one of them.
    numbers: tuple[NumberVM, ...] = ()


def page(
    tenant_id: UUID,
    *,
    filter_key: str,
    channel: str,
    cursor: str | None,
    now: datetime,
    limit: int = PAGE_SIZE,
    number: str = "",
) -> InboxPage:
    """One page; `number` (a connection id the state already checked is the business's)
    narrows it to that WhatsApp number."""
    return list_inbox(
        tenant_id,
        filter=filter_key,  # type: ignore[arg-type]
        channel=UI_TO_BACKEND.get(channel),
        cursor=cursor or None,
        limit=limit,
        now=now,
        connection_id=UUID(number) if number else None,
    )


def counts(tenant_id: UUID, *, now: datetime) -> InboxCounts:
    return inbox_counts(tenant_id, now=now)


def context(tenant_id: UUID) -> InboxContext:
    wa = whatsapp_gateway()
    connected: list[str] = []
    if conversations_gateway().accounts(tenant_id):
        connected.append(CHANNEL_INSTAGRAM)
    numbers = numbers_for(tenant_id)
    if numbers:
        connected.append(CHANNEL_WHATSAPP)
    return InboxContext(
        zone_name=wa.timezone(tenant_id),
        agents=tuple(wa.agents(tenant_id)),
        connected=tuple(connected),
        numbers=tuple(NumberVM(connection_id=n.connection_id, label=n.label) for n in numbers),
    )
