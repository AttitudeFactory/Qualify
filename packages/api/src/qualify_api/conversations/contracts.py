"""The channel seam of the Conversaciones module (QUA-226, E1): what a channel must offer
to be read into the inbox (`ConversationSource`) and to be answered from it
(`ConversationSender`), and the registry that resolves a channel name to both.

The inbox itself — `threads`/`messages`, the sync service, the outbox, the service the UI
reads — knows only these types. Adding a channel is implementing the two protocols and
registering them; nothing in the module's model or (later) UI is touched. The first real
pair is Instagram Direct (E3); `memory_source.py` is the second, test-only pair that proves
the seam holds.

## Identity rules a source must honour

- `RemoteConversation.counterpart_external_id` is THE thread key (`threads.
  external_thread_id` under `uq_thread_natural_key`). For Instagram it is the other
  person's IGSID — stable per app/account, NOT a portable identity
  (`ig_shapes.IGSID_IS_PORTABLE_IDENTITY is False`); never join it against another
  person identifier. A webhook change carries the counterpart id and the message id but
  no conversation id, so keying threads on the counterpart is what makes the webhook path
  and the poll path land on the same row.
- `RemoteMessage.external_message_id` is the channel's own message id (Meta's `mid`),
  identical on both paths — it is the dedup key (`uq_message_external_id`).
- `RemoteConversation.external_conversation_id` is the poll-side id (`t_…`), kept on the
  thread for paging, never used as identity.

## What a source must NOT do

Read a token, log user text, or decide what is "new". Dedup is the repository's
(`INSERT … ON CONFLICT DO NOTHING`); a source returns what the channel returns.

## Access is a verdict, not an exception

`check_access` answers the one question an empty poll cannot: is this connection able to
read messages at all? `AccessStatus.UNKNOWN` is a legitimate answer (the channel gives no
way to tell), and the sync service stores it as such — the UI must never render an
unknown as zero (`UNCOVERED_SURFACES["direct_messages_human_toggle"]`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal, Protocol
from uuid import UUID

CHANNEL_DM: Final = "dm"

Direction = Literal["inbound", "outbound"]


class AccessStatus(StrEnum):
    """Can this connection read the channel's private messages?"""

    UNKNOWN = "unknown"  # not checked yet, or the channel cannot tell (empty poll)
    OK = "ok"
    PERMISSION_MISSING = "permission_missing"  # the connection lacks the scope (C-05 matrix)
    ACCESS_DISABLED = "access_disabled"  # the owner's in-app toggle is off
    AUTH_EXPIRED = "auth_expired"  # runtime 401 / code 190 — the connection is degraded
    ERROR = "error"  # anything else; `detail` names it


@dataclass(frozen=True)
class AccessVerdict:
    status: AccessStatus
    # A code or a class name — never user text, never a token.
    detail: str | None = None


@dataclass(frozen=True)
class SourceConnection:
    """The connection as a source sees it: ids only, no credential. A real source
    obtains its authenticated client from `CredentialResolver` by `connection_id`."""

    tenant_id: UUID
    connection_id: UUID
    external_account_id: str
    linked_page_id: str | None = None


@dataclass(frozen=True)
class RemoteConversation:
    counterpart_external_id: str
    external_conversation_id: str | None = None
    counterpart_username: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RemoteMessage:
    external_message_id: str
    direction: Direction
    text: str | None
    posted_at: datetime | None
    # Which version of the channel's shape contract parsed this message.
    shape_version: str
    author_external_id: str | None = None
    author_username: str | None = None
    # The channel's media kind for a non-text message (`messages.media_type`'s CHECKed
    # list, `other` for anything new); `None` for text.
    media_type: str | None = None


@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    next_cursor: str | None = None


class ConversationSource(Protocol):
    """Reads one channel's private conversations for one connection."""

    @property
    def channel(self) -> str: ...

    async def check_access(self, connection: SourceConnection) -> AccessVerdict: ...

    async def list_conversations(
        self, connection: SourceConnection, *, cursor: str | None = None
    ) -> Page[RemoteConversation]: ...

    async def list_messages(
        self,
        connection: SourceConnection,
        conversation: RemoteConversation,
        *,
        cursor: str | None = None,
    ) -> Page[RemoteMessage]: ...


@dataclass(frozen=True)
class SendResult:
    external_message_id: str


class ConversationSender(Protocol):
    """Sends one channel's private messages for one connection. `build_payload` produces
    the already-built wire body the outbox stores (the channel's own shape, so the sender
    worker never re-derives it); `send` ships one such body."""

    @property
    def channel(self) -> str: ...

    def build_payload(self, *, recipient_external_id: str, text: str) -> dict[str, Any]: ...

    async def send(
        self, connection: SourceConnection, payload: Mapping[str, Any]
    ) -> SendResult: ...


class UnknownChannel(LookupError):
    """No source/sender registered for this channel name."""


class ChannelRegistry:
    """`channel name -> (source, sender)`. A channel may register either half: a
    read-only channel has a source and no sender, and `sender_for` says so."""

    def __init__(self) -> None:
        self._sources: dict[str, ConversationSource] = {}
        self._senders: dict[str, ConversationSender] = {}

    def register(
        self,
        *,
        source: ConversationSource | None = None,
        sender: ConversationSender | None = None,
    ) -> None:
        if source is None and sender is None:
            raise ValueError("register needs a source, a sender, or both")
        if source is not None and sender is not None and source.channel != sender.channel:
            raise ValueError(
                f"source channel {source.channel!r} and sender channel {sender.channel!r} differ"
            )
        if source is not None:
            self._sources[source.channel] = source
        if sender is not None:
            self._senders[sender.channel] = sender

    def source_for(self, channel: str) -> ConversationSource:
        try:
            return self._sources[channel]
        except KeyError:
            raise UnknownChannel(f"no conversation source for channel {channel!r}") from None

    def sender_for(self, channel: str) -> ConversationSender:
        try:
            return self._senders[channel]
        except KeyError:
            raise UnknownChannel(f"no conversation sender for channel {channel!r}") from None

    def channels(self) -> Iterable[str]:
        return sorted(set(self._sources) | set(self._senders))
