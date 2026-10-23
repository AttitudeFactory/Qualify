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
    # The channel's own CDN URL of the attachment (signed, expiring); `None` for text.
    media_url: str | None = None
    # m-24789646 (B5): the story an inbound DM replies to — Meta's story id and the CDN
    # URL it gave (signed, expiring). `None` for any message that is not a story reply.
    story_reply_id: str | None = None
    story_reply_url: str | None = None
    # m-24789472 (PR 2): the option an inbound DM was tapped from instead of typed —
    # `conversations.choices.CHOICE_KINDS` and the payload Meta sent back. Only the
    # webhook knows them (the Message node has neither): `None` from the poll.
    choice_kind: str | None = None
    choice_payload: str | None = None


def story_reference(value: Any) -> tuple[str, str | None] | None:
    """`(story id, CDN URL)` from Meta's story object — `{"id", "url"}` in the webhook's
    `reply_to.story`, `{"id", "link"}` in the Message node's `story.reply_to` — or None
    when it carries no id."""
    if not isinstance(value, Mapping):
        return None
    raw_id = value.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, str | int) or not str(raw_id):
        return None
    for key in ("url", "link"):
        url = value.get(key)
        if isinstance(url, str) and url:
            return str(raw_id), url
    return str(raw_id), None


@dataclass(frozen=True)
class RemoteProfile:
    """What the channel says about the counterpart (Instagram's User Profile API: the
    person consented by messaging the business). `avatar_url` expires after days."""

    name: str | None = None
    username: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True)
class RemoteRead:
    """The counterpart read the conversation up to `last_read_at` (Instagram's
    `messaging_seen`: `read.mid` + the event's timestamp). Keyed on the counterpart like
    a message, so it lands on the same thread."""

    counterpart_external_id: str
    last_read_at: datetime
    external_message_id: str | None = None


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

    async def fetch_profile(
        self, connection: SourceConnection, counterpart_external_id: str
    ) -> RemoteProfile | None:
        """The counterpart's profile, or `None` when the channel has none to give (no
        API, no consent, a blocked business, an error). Best-effort by contract."""
        ...


@dataclass(frozen=True)
class SendResult:
    external_message_id: str
    # Whom the channel says it delivered to (Meta's `recipient_id`), when it says.
    recipient_external_id: str | None = None


#: Ephemeral presence signals a channel may show the counterpart (Messenger Platform's
#: `sender_action`). Never a message, never queued, never approved: they carry no content.
ACTION_MARK_SEEN: Final = "mark_seen"
ACTION_TYPING_ON: Final = "typing_on"
ACTION_TYPING_OFF: Final = "typing_off"
SENDER_ACTIONS: Final = frozenset({ACTION_MARK_SEEN, ACTION_TYPING_ON, ACTION_TYPING_OFF})

#: The media kinds a reply may attach (`messages.media_type`'s CHECKed list, narrowed to
#: what the Messenger Platform sends from a URL — `send-message.md` «Limitations»: image
#: png/jpeg ≤ 8 MB, audio aac/m4a/wav/mp4 ≤ 25 MB, video mp4/ogg/avi/mov/webm ≤ 25 MB,
#: file pdf ≤ 25 MB). Qualify's `document` is the channel's `file`: a sender maps it.
REPLY_MEDIA_TYPES: Final = frozenset({"image", "audio", "video", "document"})

#: Stickers a reply may send without any object of its own (`send-message.md` «Send a
#: heart sticker»): the wire body is `attachment.type` alone. Stored on the outbound
#: message as `media_type = 'sticker'`.
STICKER_LIKE_HEART: Final = "like_heart"
REPLY_STICKERS: Final = frozenset({STICKER_LIKE_HEART})
MEDIA_TYPE_STICKER: Final = "sticker"


class ConversationSender(Protocol):
    """Sends one channel's private messages for one connection. `build_payload` /
    `build_media_payload` produce the already-built wire body the outbox stores (the
    channel's own shape, so the sender worker never re-derives it); `send` ships one such
    body. A media body is built WITHOUT its URL: the worker fills it in at send time
    (`with_media_url`) from the R2 object the outbox row carries, because the public URL
    Meta fetches is short-lived. `send_action` shows a presence signal (seen / typing)
    and is best-effort: a channel without one may raise `NotImplementedError`."""

    @property
    def channel(self) -> str: ...

    def build_payload(self, *, recipient_external_id: str, text: str) -> dict[str, Any]: ...

    def build_private_reply_payload(self, *, comment_id: str, text: str) -> dict[str, Any]:
        """The one-off DM to a comment's author, addressed by the COMMENT (m-24789646)."""
        ...

    def build_media_payload(
        self, *, recipient_external_id: str, media_type: str
    ) -> dict[str, Any]: ...

    def with_media_url(self, payload: Mapping[str, Any], url: str) -> dict[str, Any]: ...

    def build_sticker_payload(
        self, *, recipient_external_id: str, sticker: str
    ) -> dict[str, Any]: ...

    async def send(
        self, connection: SourceConnection, payload: Mapping[str, Any]
    ) -> SendResult: ...

    async def send_action(
        self, connection: SourceConnection, *, recipient_external_id: str, action: str
    ) -> None: ...


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
