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

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from uuid import UUID

from qualify_api.conversations.contracts import (
    REPLY_STICKERS,
    SENDER_ACTIONS,
    ChannelRegistry,
    SourceConnection,
)
from qualify_api.conversations.interactive import (
    QuickReply,
    TemplateButton,
    clean_button_text,
    clean_buttons,
    clean_quick_replies,
)
from qualify_api.conversations.outbox import (
    ConversationOutboxRepository,
    HumanApproval,
    OutboxMedia,
)
from qualify_api.conversations.repository import (
    ConversationRepository,
    MessageRecord,
    ThreadRecord,
)
from qualify_api.conversations.window import WindowState, window_state

if TYPE_CHECKING:
    # Runtime imports are lazy: `qualify_api.followups` imports this module's package.
    from qualify_api.followups.capabilities import Availability, Capabilities, Capability

logger = logging.getLogger("qualify_api.conversations.service")

MAX_REPLY_CHARS: Final = 1000  # Instagram Messaging's text limit (send-message.md: 1000 UTF-8)


class AttentionState(StrEnum):
    PENDING = "pending"  # an inbound nobody has read or answered
    READ = "read"  # a person opened it after the last inbound, no answer yet
    ANSWERED = "answered"  # the last outbound is at or after the last inbound
    NONE = "none"  # no inbound ever (a thread we opened, or still empty)


class ThreadNotFound(LookupError):
    """No thread with this id for this tenant (another tenant's included — RLS makes the
    two indistinguishable, and this module keeps it that way)."""


#: m-24789472: what the person reads when a quick reply / button template is refused
#: because its capability is off (the registry's reason follows it).
UNAVAILABLE_MESSAGES: Final[dict[str, str]] = {
    "quick_replies": "Las respuestas rápidas no están disponibles todavía.",
    "structured_templates": "Los mensajes con botones no están disponibles todavía.",
}


class CapabilityUnavailable(PermissionError):
    """A quick reply or a button template was asked for while its capability is off
    (m-24789472). `message` — also `str(error)` — is the Spanish «no disponible todavía»
    sentence; `reason` the registry's (its state and switch), `state_label` its state."""

    def __init__(self, availability: Availability) -> None:
        self.availability = availability
        self.capability = str(availability.capability)
        self.reason = availability.reason
        self.state_label = availability.state_label
        self.message = UNAVAILABLE_MESSAGES.get(
            self.capability, "Esta función no está disponible todavía."
        )
        super().__init__(self.message)


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


def split_reply(text: str, limit: int = MAX_REPLY_CHARS) -> list[str]:
    """Cut `text` into chunks of at most `limit` characters, preferring (in order) a blank
    line, a line break, the end of a sentence, a space — and only then a hard cut. Each
    chunk is stripped; empty chunks vanish."""
    body = text.strip()
    if not body:
        return []
    parts: list[str] = []
    while len(body) > limit:
        window = body[: limit + 1]
        cut = -1
        for marker in ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "):
            idx = window.rfind(marker)
            if idx > 0:
                cut = idx + len(marker.rstrip())
                break
        if cut <= 0:
            cut = limit
        parts.append(body[:cut].strip())
        body = body[cut:].strip()
    if body:
        parts.append(body)
    return [p for p in parts if p]


class ConversationService:
    def __init__(
        self,
        *,
        repository: ConversationRepository,
        outbox: ConversationOutboxRepository,
        registry: ChannelRegistry,
        clock: Callable[[], datetime] = _utcnow,
        capabilities: Capabilities | None = None,
    ) -> None:
        self._repo = repository
        self._outbox = outbox
        self._registry = registry
        self._clock = clock
        # None = every capability off (the registry's default), never "all on".
        self._capabilities = capabilities

    def availability(self, capability: Capability) -> Availability:
        """Whether this deployment may send `capability` (`quick_replies`,
        `structured_templates`) and, when not, the Spanish reason — what the composer
        shows next to «no disponible todavía»."""
        from qualify_api.followups.capabilities import Capabilities  # noqa: PLC0415

        return (self._capabilities or Capabilities()).availability(capability)

    def _require(self, capability_name: str) -> None:
        from qualify_api.followups.capabilities import Capability  # noqa: PLC0415

        availability = self.availability(Capability(capability_name))
        if not availability.enabled:
            raise CapabilityUnavailable(availability)

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

    def hide_message(self, *, tenant_id: UUID, thread_id: UUID, message_id: UUID) -> bool:
        """«Eliminar para mí»: the message leaves this tenant's inbox and nothing else —
        Instagram's API lets a business neither unsend nor edit a message, so there is no
        «para todos». Returns whether a visible message was hidden."""
        self._thread(tenant_id, thread_id)
        return self._repo.hide_message(
            tenant_id=tenant_id, thread_id=thread_id, message_id=message_id, now=self._clock()
        )

    def mark_read(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadView:
        self._thread(tenant_id, thread_id)
        self._repo.mark_read(tenant_id=tenant_id, thread_id=thread_id, now=self._clock())
        return self.get_thread(tenant_id=tenant_id, thread_id=thread_id)

    def reply(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        text: str,
        approval: HumanApproval,
        quick_replies: Sequence[QuickReply] | None = None,
    ) -> UUID:
        """Queue a human-approved text reply on `thread_id`. Raises `ThreadNotFound`,
        `ValueError` (empty / too long), `WindowClosed`, `UnknownChannel` (the thread's
        channel has no sender) or `ApprovalRequired`. Returns the outbox row id.

        `quick_replies` (m-24789472) ride on this message: `CapabilityUnavailable` while
        `quick_replies` is off, `InteractiveMessageError` (Spanish) when invalid — both
        before anything is written."""
        if not isinstance(approval, HumanApproval):
            # Reached only by a caller that bypassed the type: `enqueue` repeats the check.
            from qualify_api.conversations.outbox import ApprovalRequired  # noqa: PLC0415

            raise ApprovalRequired("a private reply needs a human approval")
        body = text.strip()
        if not body:
            raise ValueError("an empty reply cannot be sent")
        if len(body) > MAX_REPLY_CHARS:
            raise ValueError(f"a reply is at most {MAX_REPLY_CHARS} characters")
        replies = clean_quick_replies(quick_replies or ())
        if replies:
            self._require("quick_replies")
        thread = self._thread(tenant_id, thread_id)
        window = window_state(thread.last_inbound_at, self._clock())
        if not window.is_open:
            raise WindowClosed(window)
        sender = self._registry.sender_for(thread.channel)
        if replies:
            payload = sender.build_payload(
                recipient_external_id=thread.counterpart_external_id,
                text=body,
                quick_replies=replies,
            )
        else:
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

    def reply_media(
        self, *, tenant_id: UUID, thread_id: UUID, media: OutboxMedia, approval: HumanApproval
    ) -> UUID:
        """Queue a human-approved media reply (an image, an audio or a video already in
        R2). Same gates as `reply`: window checked before anything is written, the
        channel's own body, the outbox as the only way out. Raises the same exceptions."""
        if not isinstance(approval, HumanApproval):
            from qualify_api.conversations.outbox import ApprovalRequired  # noqa: PLC0415

            raise ApprovalRequired("a private reply needs a human approval")
        thread = self._thread(tenant_id, thread_id)
        window = window_state(thread.last_inbound_at, self._clock())
        if not window.is_open:
            raise WindowClosed(window)
        sender = self._registry.sender_for(thread.channel)
        payload = sender.build_media_payload(
            recipient_external_id=thread.counterpart_external_id, media_type=media.media_type
        )
        return self._outbox.enqueue(
            tenant_id=tenant_id,
            connection_id=thread.connection_id,
            thread_id=thread.id,
            channel=thread.channel,
            payload=payload,
            approval=approval,
            media=media,
        )

    def reply_sticker(
        self, *, tenant_id: UUID, thread_id: UUID, sticker: str, approval: HumanApproval
    ) -> UUID:
        """Queue a human-approved sticker (`like_heart`). Same gates as `reply`."""
        if not isinstance(approval, HumanApproval):
            from qualify_api.conversations.outbox import ApprovalRequired  # noqa: PLC0415

            raise ApprovalRequired("a private reply needs a human approval")
        if sticker not in REPLY_STICKERS:
            raise ValueError(f"sticker {sticker!r} is not one of {REPLY_STICKERS}")
        thread = self._thread(tenant_id, thread_id)
        window = window_state(thread.last_inbound_at, self._clock())
        if not window.is_open:
            raise WindowClosed(window)
        sender = self._registry.sender_for(thread.channel)
        payload = sender.build_sticker_payload(
            recipient_external_id=thread.counterpart_external_id, sticker=sticker
        )
        return self._outbox.enqueue(
            tenant_id=tenant_id,
            connection_id=thread.connection_id,
            thread_id=thread.id,
            channel=thread.channel,
            payload=payload,
            approval=approval,
            media=OutboxMedia.sticker(),
        )

    def reply_text(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        text: str,
        approval: HumanApproval,
        quick_replies: Sequence[QuickReply] | None = None,
    ) -> list[UUID]:
        """`reply` for a text of any length: split into consecutive messages of at most
        `MAX_REPLY_CHARS` (the channel's limit) at paragraph, sentence or word boundaries,
        each queued with the same approval, in order. The window is checked once, before
        the first row is written (`reply` re-checks each, cheaply).

        `quick_replies` (m-24789472) attach to the LAST message only — Instagram shows
        them under the newest message and drops them when another arrives. They are
        validated and their capability checked before the first row is written."""
        parts = split_reply(text)
        if not parts:
            raise ValueError("an empty reply cannot be sent")
        if not isinstance(approval, HumanApproval):
            from qualify_api.conversations.outbox import ApprovalRequired  # noqa: PLC0415

            raise ApprovalRequired("a private reply needs a human approval")
        replies = clean_quick_replies(quick_replies or ())
        if replies:
            self._require("quick_replies")
        thread = self._thread(tenant_id, thread_id)
        window = window_state(thread.last_inbound_at, self._clock())
        if not window.is_open:
            raise WindowClosed(window)
        last = len(parts) - 1
        return [
            self.reply(
                tenant_id=tenant_id,
                thread_id=thread_id,
                text=part,
                approval=approval,
                quick_replies=replies if index == last else None,
            )
            for index, part in enumerate(parts)
        ]

    def reply_buttons(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        text: str,
        buttons: Sequence[TemplateButton],
        approval: HumanApproval,
    ) -> UUID:
        """Queue a human-approved button template (m-24789472): a text of 1–640
        characters with 1–3 buttons, as ONE message — it is never split, so a longer
        text is refused (`InteractiveMessageError(button_text_too_long)`). Same gates as
        `reply`, plus `CapabilityUnavailable` while `structured_templates` is off; every
        check runs before anything is written."""
        if not isinstance(approval, HumanApproval):
            from qualify_api.conversations.outbox import ApprovalRequired  # noqa: PLC0415

            raise ApprovalRequired("a private reply needs a human approval")
        self._require("structured_templates")
        body = clean_button_text(text)
        cleaned = clean_buttons(buttons)
        thread = self._thread(tenant_id, thread_id)
        window = window_state(thread.last_inbound_at, self._clock())
        if not window.is_open:
            raise WindowClosed(window)
        sender = self._registry.sender_for(thread.channel)
        payload = sender.build_button_template_payload(
            recipient_external_id=thread.counterpart_external_id, text=body, buttons=cleaned
        )
        return self._outbox.enqueue(
            tenant_id=tenant_id,
            connection_id=thread.connection_id,
            thread_id=thread.id,
            channel=thread.channel,
            payload=payload,
            approval=approval,
        )

    async def signal(
        self, *, tenant_id: UUID, thread_id: UUID, connection: SourceConnection, action: str
    ) -> bool:
        """Show the counterpart a presence signal (`mark_seen` when a person opens the
        thread, `typing_on` while they write). Best-effort and ephemeral: never queued,
        never approved, never retried; a channel without a sender, a closed window or a
        channel error all answer `False`. `connection` carries the ids the channel needs
        (the caller resolves it — this service holds no connection reader)."""
        if action not in SENDER_ACTIONS:
            raise ValueError(f"unknown sender action {action!r}")
        thread = self._thread(tenant_id, thread_id)
        if thread.connection_id != connection.connection_id:
            raise ThreadNotFound(str(thread_id))
        if not window_state(thread.last_inbound_at, self._clock()).is_open:
            return False
        try:
            sender = self._registry.sender_for(thread.channel)
            await sender.send_action(
                connection, recipient_external_id=thread.counterpart_external_id, action=action
            )
        except Exception as exc:  # noqa: BLE001 — a presence signal never breaks the screen
            logger.info(
                "conversations.signal.skipped thread=%s action=%s reason=%s",
                thread_id,
                action,
                type(exc).__name__,
            )
            return False
        return True

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
