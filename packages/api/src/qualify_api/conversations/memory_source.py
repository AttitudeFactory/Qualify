"""The second channel: an in-memory `ConversationSource` + `ConversationSender` pair
(QUA-226, acceptance criterion 8 — "a second source, without touching the UI").

Not a mock of Instagram: a channel whose conversations live in dictionaries the test
sets up. It exists so the sync service, the repository, the outbox and (later) the UI are
exercised against a source that is NOT the first real one — if they work only for
Instagram, this pair fails. It is also the fixture for the offline tests, since the
Instagram adapter (E3) needs Meta and the `db` tests need Postgres.

Paging is real (`page_size`), so a consumer that forgets to follow `next_cursor` is caught
here, not in production.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    REPLY_MEDIA_TYPES,
    REPLY_STICKERS,
    SENDER_ACTIONS,
    AccessStatus,
    AccessVerdict,
    Page,
    RemoteConversation,
    RemoteMessage,
    RemoteProfile,
    SendResult,
    SourceConnection,
)

SHAPE_VERSION_MEMORY = "memory-conversations-1.0.0"


def _slice[T](items: list[T], cursor: str | None, page_size: int) -> Page[T]:
    start = int(cursor) if cursor else 0
    end = start + page_size
    chunk = tuple(items[start:end])
    return Page(items=chunk, next_cursor=str(end) if end < len(items) else None)


class MemoryConversationSource:
    """`conversations[counterpart_id]` and `messages[counterpart_id]` are what the channel
    "has"; `access` is what `check_access` answers. A test mutates them between syncs to
    simulate new messages arriving — or `fail_with` to make every call raise."""

    def __init__(self, *, channel: str = CHANNEL_DM, page_size: int = 50) -> None:
        self._channel = channel
        self.page_size = page_size
        self.conversations: dict[str, RemoteConversation] = {}
        self.messages: dict[str, list[RemoteMessage]] = {}
        self.profiles: dict[str, RemoteProfile] = {}
        self.access = AccessVerdict(AccessStatus.OK)
        self.fail_with: Exception | None = None
        self.calls: list[str] = []

    @property
    def channel(self) -> str:
        return self._channel

    def add_message(self, conversation: RemoteConversation, message: RemoteMessage) -> None:
        key = conversation.counterpart_external_id
        self.conversations.setdefault(key, conversation)
        self.messages.setdefault(key, []).append(message)

    def _check(self, call: str) -> None:
        self.calls.append(call)
        if self.fail_with is not None:
            raise self.fail_with

    async def check_access(self, connection: SourceConnection) -> AccessVerdict:
        self._check("check_access")
        return self.access

    async def list_conversations(
        self, connection: SourceConnection, *, cursor: str | None = None
    ) -> Page[RemoteConversation]:
        self._check("list_conversations")
        return _slice(list(self.conversations.values()), cursor, self.page_size)

    async def list_messages(
        self,
        connection: SourceConnection,
        conversation: RemoteConversation,
        *,
        cursor: str | None = None,
    ) -> Page[RemoteMessage]:
        self._check("list_messages")
        items = self.messages.get(conversation.counterpart_external_id, [])
        return _slice(list(items), cursor, self.page_size)

    async def fetch_profile(
        self, connection: SourceConnection, counterpart_external_id: str
    ) -> RemoteProfile | None:
        self._check("fetch_profile")
        return self.profiles.get(counterpart_external_id)


@dataclass
class SentRecord:
    connection: SourceConnection
    payload: dict[str, Any]
    external_message_id: str


@dataclass(frozen=True)
class ActionRecord:
    connection: SourceConnection
    recipient_external_id: str
    action: str


@dataclass
class MemoryConversationSender:
    """Records what it is asked to send; `fail_with` makes `send` raise. The payload shape
    is the Messenger Platform's (`{"recipient": {"id"}, "message": {"text"}}`,
    `features/send-message.md:46`) so the outbox stores the same shape the Instagram
    sender (E3) will — only the transport differs. Presence signals land in `actions`."""

    channel: str = CHANNEL_DM
    sent: list[SentRecord] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)
    fail_with: Exception | None = None
    # The IGSID a private reply reaches, per comment id; unknown comments answer None.
    comment_authors: dict[str, str] = field(default_factory=dict)
    _ids: Any = field(default_factory=lambda: count(1), repr=False)

    def build_payload(self, *, recipient_external_id: str, text: str) -> dict[str, Any]:
        if not recipient_external_id:
            raise ValueError("a recipient is required")
        if not text.strip():
            raise ValueError("an empty message cannot be sent")
        return {"recipient": {"id": recipient_external_id}, "message": {"text": text}}

    def build_private_reply_payload(self, *, comment_id: str, text: str) -> dict[str, Any]:
        if not comment_id:
            raise ValueError("a private reply needs the comment it answers")
        if not text.strip():
            raise ValueError("an empty message cannot be sent")
        return {"recipient": {"comment_id": comment_id}, "message": {"text": text}}

    def build_media_payload(self, *, recipient_external_id: str, media_type: str) -> dict[str, Any]:
        if not recipient_external_id:
            raise ValueError("a recipient is required")
        if media_type not in REPLY_MEDIA_TYPES:
            raise ValueError(f"media_type {media_type!r} is not one of {REPLY_MEDIA_TYPES}")
        return {
            "recipient": {"id": recipient_external_id},
            "message": {"attachment": {"type": media_type, "payload": {}}},
        }

    def with_media_url(self, payload: Mapping[str, Any], url: str) -> dict[str, Any]:
        body = copy.deepcopy(dict(payload))
        body["message"]["attachment"]["payload"] = {"url": url}
        return body

    def build_sticker_payload(self, *, recipient_external_id: str, sticker: str) -> dict[str, Any]:
        if not recipient_external_id:
            raise ValueError("a recipient is required")
        if sticker not in REPLY_STICKERS:
            raise ValueError(f"sticker {sticker!r} is not one of {REPLY_STICKERS}")
        return {
            "recipient": {"id": recipient_external_id},
            "message": {"attachment": {"type": sticker}},
        }

    async def send(self, connection: SourceConnection, payload: Mapping[str, Any]) -> SendResult:
        if self.fail_with is not None:
            raise self.fail_with
        external_message_id = f"mid.memory.{next(self._ids)}"
        self.sent.append(SentRecord(connection, dict(payload), external_message_id))
        recipient = payload.get("recipient") or {}
        recipient_id = recipient.get("id") or self.comment_authors.get(
            recipient.get("comment_id", "")
        )
        return SendResult(
            external_message_id=external_message_id, recipient_external_id=recipient_id
        )

    async def send_action(
        self, connection: SourceConnection, *, recipient_external_id: str, action: str
    ) -> None:
        if action not in SENDER_ACTIONS:
            raise ValueError(f"unknown sender action {action!r}")
        if self.fail_with is not None:
            raise self.fail_with
        self.actions.append(ActionRecord(connection, recipient_external_id, action))
