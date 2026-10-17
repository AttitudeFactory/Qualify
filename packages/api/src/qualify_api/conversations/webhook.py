"""The Instagram `messages` handler of the webhook intake processor (QUA-226, E3).

Registered in `webhooks.processor.production_processor` under
`INSTAGRAM_MESSAGES_HANDLER_KEY` (`instagram:messages`), so a WhatsApp change — also
`field = "messages"`, object `whatsapp_business_account` — never reaches it (WA-07's rule).

One claimed change = one item of `entry[].messaging[]` of an `object: "instagram"`
delivery (`business-messaging/instagram-messaging/webhooks.md:53-81`; the envelope maps
each item to a change with `field = "messages"`, see `webhooks/envelope.py`):

    {"sender": {"id": IGSID}, "recipient": {"id": IGID}, "timestamp": 1569262485349,
     "message": {"mid": "…", "text": "…", "attachments": [...], "is_echo": true?}}

What one change does, in order:

1. `event.value` must be an object carrying a `message` with a string `mid`; a `read`,
   `reaction`, `postback` or any other item is settled `unsupported` (kept, replayable
   the day it has a handler); a `message` flagged `is_deleted` is `unsupported` too
   (`message_deleted` — nothing to show, nothing to re-read).
2. Resolve `entry[].id` (the Instagram professional account id) → `(tenant, connection)`
   through `mentions.resolve.resolve_external_account`. `ORPHAN` / `AMBIGUOUS` → settled
   as such, **nothing written** (QUA-97's invariant).
3. `is_echo` (the account itself wrote, from Instagram or from Qualify's own sender) →
   `outbound`, counterpart = `recipient.id`; otherwise `inbound`, counterpart =
   `sender.id`. Then `ConversationSyncService.ingest_message`: same upsert, same insert
   by `mid`, same bump as the poll — a replayed delivery, or the poll reaching the same
   `mid` later, is one row. An echo of a message the outbox already wrote under its
   `message_id` is the same `mid` and therefore a no-op.
4. `processed`.

No user text in logs: ids, kinds and outcomes only. `[V]`-pending like the adapter: the
shape is read from the corpus, not observed live.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
    RemoteRead,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import SHAPE_VERSION_IG_DM
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.mentions.resolve import (
    PLATFORM_INSTAGRAM,
    ResolutionOutcome,
    TenantResolution,
)
from qualify_api.webhooks.processor import Handler, Outcome
from qualify_api.webhooks.repository import (
    STATUS_AMBIGUOUS,
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)

logger = logging.getLogger("qualify_api.conversations.webhook")

INSTAGRAM_MESSAGES_HANDLER_KEY: Final = "instagram:messages"
NOT_A_MESSAGE: Final = "not_a_message"
MESSAGE_DELETED: Final = "message_deleted"
CONTRACT_VIOLATION: Final = "contract_violation"

TenantResolver = Callable[..., TenantResolution]

_ATTACHMENT_MEDIA_TYPES: Final = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "file": "document",
    "share": "other",
    "story_mention": "other",
    "reel": "video",
    "ig_reel": "video",
    "template": "interactive",
}


def _id_of(value: Any) -> str | None:
    if isinstance(value, Mapping):
        raw = value.get("id")
        if isinstance(raw, str | int) and not isinstance(raw, bool) and str(raw):
            return str(raw)
    return None


def _posted_at(timestamp: Any) -> datetime | None:
    """`timestamp` is documented in milliseconds; seconds are accepted too."""
    if isinstance(timestamp, bool) or not isinstance(timestamp, int | float):
        return None
    seconds = timestamp / 1000 if timestamp >= 10**11 else timestamp
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _media_type(message: Mapping[str, Any]) -> str | None:
    if message.get("is_unsupported") is True:
        return "other"
    attachments = message.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        return None
    first = attachments[0]
    kind = first.get("type") if isinstance(first, Mapping) else None
    return _ATTACHMENT_MEDIA_TYPES.get(str(kind), "other")


def _media_url_of(message: Mapping[str, Any]) -> str | None:
    attachments = message.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        return None
    first = attachments[0]
    payload = first.get("payload") if isinstance(first, Mapping) else None
    url = payload.get("url") if isinstance(payload, Mapping) else None
    return url if isinstance(url, str) and url else None


def parse_messaging_item(
    value: Any, *, own_account_id: str
) -> tuple[RemoteConversation, RemoteMessage] | RemoteRead | str:
    """The `(conversation, message)` an item carries, a `RemoteRead` for a `read`
    (`messaging_seen`) item, or the `unsupported` reason when it is neither. Raises
    `ValueError` for an item that claims to be one of those but breaks the shape."""
    if not isinstance(value, Mapping):
        raise ValueError("messaging item is not an object")
    read = value.get("read")
    if isinstance(read, Mapping):
        sender_id = _id_of(value.get("sender"))
        at = _posted_at(value.get("timestamp"))
        if sender_id is None or at is None:
            raise ValueError("read item lacks sender or timestamp")
        mid = read.get("mid")
        return RemoteRead(
            counterpart_external_id=sender_id,
            last_read_at=at,
            external_message_id=mid if isinstance(mid, str) and mid else None,
        )
    message = value.get("message")
    if not isinstance(message, Mapping):
        return NOT_A_MESSAGE
    if message.get("is_deleted") is True:
        return MESSAGE_DELETED
    mid = message.get("mid")
    sender_id, recipient_id = _id_of(value.get("sender")), _id_of(value.get("recipient"))
    if not isinstance(mid, str) or not mid or sender_id is None or recipient_id is None:
        raise ValueError("messaging item lacks mid, sender or recipient")
    is_echo = message.get("is_echo") is True or sender_id == own_account_id
    counterpart = recipient_id if is_echo else sender_id
    text = message.get("text")
    remote = RemoteMessage(
        external_message_id=mid,
        direction="outbound" if is_echo else "inbound",
        text=text if isinstance(text, str) and text else None,
        posted_at=_posted_at(value.get("timestamp")),
        shape_version=SHAPE_VERSION_IG_DM,
        author_external_id=sender_id,
        media_type=_media_type(message),
        media_url=_media_url_of(message),
    )
    return RemoteConversation(counterpart_external_id=counterpart), remote


def instagram_messages_handler(
    *, resolve: TenantResolver, sync: ConversationSyncService
) -> Handler:
    async def handle(event: ClaimedEvent) -> Outcome:
        try:
            parsed = parse_messaging_item(event.value, own_account_id=event.entry_id)
        except ValueError:
            logger.error("instagram messages webhook: event=%s item off-contract", event.id)
            return Outcome(STATUS_DEAD, CONTRACT_VIOLATION)
        if isinstance(parsed, str):
            return Outcome(STATUS_UNSUPPORTED, parsed)

        resolution = await asyncio.to_thread(
            resolve, platform=PLATFORM_INSTAGRAM, external_account_id=event.entry_id
        )
        if resolution.outcome is ResolutionOutcome.ORPHAN:
            logger.warning(
                "instagram messages webhook: orphan event, no connection for "
                "external_account_id=%s — not persisted",
                event.entry_id,
            )
            return Outcome(STATUS_ORPHAN)
        if (
            resolution.outcome is not ResolutionOutcome.RESOLVED
            or resolution.tenant_id is None
            or resolution.connection_id is None
        ):
            logger.error(
                "instagram messages webhook: AMBIGUOUS external_account_id=%s — dropped",
                event.entry_id,
            )
            return Outcome(STATUS_AMBIGUOUS)

        connection = SourceConnection(
            tenant_id=resolution.tenant_id,
            connection_id=resolution.connection_id,
            external_account_id=event.entry_id,
        )
        if isinstance(parsed, RemoteRead):
            changed = await asyncio.to_thread(
                sync.ingest_read, connection, channel=CHANNEL_DM, read=parsed
            )
            logger.info(
                "instagram messages webhook: seen tenant=%s connection=%s messages_read=%d",
                resolution.tenant_id,
                resolution.connection_id,
                changed,
            )
            return Outcome(STATUS_PROCESSED)
        conversation, message = parsed
        result = await asyncio.to_thread(
            sync.ingest_message,
            connection,
            channel=CHANNEL_DM,
            conversation=conversation,
            message=message,
        )
        logger.info(
            "instagram messages webhook: tenant=%s connection=%s direction=%s thread=%s "
            "thread_created=%s message_created=%s",
            resolution.tenant_id,
            resolution.connection_id,
            message.direction,
            result.thread_id,
            result.thread_created,
            result.message_created,
        )
        return Outcome(STATUS_PROCESSED)

    return handle


__all__ = [
    "CONTRACT_VIOLATION",
    "INSTAGRAM_MESSAGES_HANDLER_KEY",
    "MESSAGE_DELETED",
    "NOT_A_MESSAGE",
    "instagram_messages_handler",
    "parse_messaging_item",
]
