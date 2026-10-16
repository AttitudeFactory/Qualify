"""The person-facing side of private conversations (QUA-226, E1): list the inbox, read a
thread, mark it read, and answer it — the seam the Reflex UI (E2) will consume.

## What this module decides, and what it delegates

- **Attention state** («pendiente» / «leído» / «respondido») is `attention_state`, a pure
  function over the thread's three instants. Derived at read time, never stored.
- **The 24 h window** is `conversations.window.window_state` — never re-derived here. A
  reply outside the window raises `WindowClosed` BEFORE anything is written. The sender
  (not yet built) will apply the window AGAIN at send time: it may have closed while the
  row waited, and the ticket's criterion is "validated at the moment of sending".
- **The wire body** is the channel's `ConversationSender.build_payload`, resolved through
  the `ChannelRegistry` by the thread's channel — this module never knows a channel's
  shape.
- **Sending** is `ConversationOutboxRepository.enqueue(..., approval=HumanApproval)`.
  Nothing is sent inline. `reply` has no overload without `approval`: the person's id and
  instant are the price of admission, and the outbox column they land in is NOT NULL.

## Tenancy

Every method takes `tenant_id`; the repositories open `tenant_session(tenant_id)` per
call, so another tenant's thread reads as missing (`ThreadNotFound`), never as forbidden.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from qualify_api.conversations.contracts import ChannelRegistry
from qualify_api.conversations.outbox import ConversationOutboxRepository, HumanApproval
from qualify_api.conversations.repository import (
    ConversationRepository,
    MessageRecord,
    ThreadRecord,
)
from qualify_api.conversations.window import WindowState, window_state

MAX_REPLY_CHARS: Final = 1000  # Instagram Messaging's text limit (send-message.md: 1000 UTF-8)


class AttentionState(StrEnum):
    PENDING = "pending"  # an inbound nobody has read or answered
    READ = "read"  # a person opened it after the last inbound, no answer yet
    ANSWERED = "answered"  # the last outbound is at or after the last inbound
    NONE = "none"  # no inbound ever (a thread we opened, or still empty)


class ThreadNotFound(LookupError):
    """No thread with this id for this tenant (another tenant's included — RLS makes the
    two indistinguishable, and this module keeps it that way)."""


class WindowClosed(PermissionError):
    """The 24 h window for this thread is closed; the channel would refuse the send."""

    def __init__(self, window: WindowState) -> None:
        super().__init__("the 24 h messaging window is closed")
        self.window = window


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def attention_state(thread: ThreadRecord) -> AttentionState:
    inbound = thread.last_inbound_at
    if inbound is None:
        return AttentionState.NONE
    inbound = _as_utc(inbound)
    if thread.last_outbound_at is not None and _as_utc(thread.last_outbound_at) >= inbound:
        return AttentionState.ANSWERED
    if thread.last_read_at is not None and _as_utc(thread.last_read_at) >= inbound:
        return AttentionState.READ
    return AttentionState.PENDING


@dataclass(frozen=True)
class ThreadView:
    thread: ThreadRecord
    attention: AttentionState
    window: WindowState


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConversationService:
    def __init__(
        self,
        *,
        repository: ConversationRepository,
        outbox: ConversationOutboxRepository,
        registry: ChannelRegistry,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repository
        self._outbox = outbox
        self._registry = registry
        self._clock = clock

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        channels: Sequence[str] | None = None,
        connection_id: UUID | None = None,
        limit: int = 50,
    ) -> list[ThreadView]:
        wanted = list(channels) if channels is not None else list(self._registry.channels())
        now = self._clock()
        return [
            self._view(thread, now)
            for thread in self._repo.list_threads(
                tenant_id=tenant_id, channels=wanted, connection_id=connection_id, limit=limit
            )
        ]

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadView:
        return self._view(self._thread(tenant_id, thread_id), self._clock())

    def list_messages(
        self, *, tenant_id: UUID, thread_id: UUID, limit: int = 50
    ) -> list[MessageRecord]:
        self._thread(tenant_id, thread_id)
        return self._repo.list_messages(tenant_id=tenant_id, thread_id=thread_id, limit=limit)

    def mark_read(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadView:
        self._thread(tenant_id, thread_id)
        self._repo.mark_read(tenant_id=tenant_id, thread_id=thread_id, now=self._clock())
        return self.get_thread(tenant_id=tenant_id, thread_id=thread_id)

    def reply(
        self, *, tenant_id: UUID, thread_id: UUID, text: str, approval: HumanApproval
    ) -> UUID:
        """Queue a human-approved text reply on `thread_id`. Raises `ThreadNotFound`,
        `ValueError` (empty / too long), `WindowClosed`, `UnknownChannel` (the thread's
        channel has no sender) or `ApprovalRequired`. Returns the outbox row id."""
        if not isinstance(approval, HumanApproval):
            # Reached only by a caller that bypassed the type: `enqueue` repeats the check.
            from qualify_api.conversations.outbox import ApprovalRequired  # noqa: PLC0415

            raise ApprovalRequired("a private reply needs a human approval")
        body = text.strip()
        if not body:
            raise ValueError("an empty reply cannot be sent")
        if len(body) > MAX_REPLY_CHARS:
            raise ValueError(f"a reply is at most {MAX_REPLY_CHARS} characters")
        thread = self._thread(tenant_id, thread_id)
        window = window_state(thread.last_inbound_at, self._clock())
        if not window.is_open:
            raise WindowClosed(window)
        sender = self._registry.sender_for(thread.channel)
        payload = sender.build_payload(
            recipient_external_id=thread.counterpart_external_id, text=body
        )
        return self._outbox.enqueue(
            tenant_id=tenant_id,
            connection_id=thread.connection_id,
            thread_id=thread.id,
            channel=thread.channel,
            payload=payload,
            approval=approval,
        )

    # -- internals ----------------------------------------------------------------------

    def _thread(self, tenant_id: UUID, thread_id: UUID) -> ThreadRecord:
        thread = self._repo.get_thread(tenant_id=tenant_id, thread_id=thread_id)
        if thread is None:
            raise ThreadNotFound(str(thread_id))
        return thread

    def _view(self, thread: ThreadRecord, now: datetime) -> ThreadView:
        return ThreadView(
            thread=thread,
            attention=attention_state(thread),
            window=window_state(thread.last_inbound_at, now),
        )
