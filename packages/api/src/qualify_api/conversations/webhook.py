"""The Instagram `messages` handler of the webhook intake processor (QUA-226, E3).

Registered in `webhooks.processor.production_processor` under
`INSTAGRAM_MESSAGES_HANDLER_KEY` (`instagram:messages`), so a WhatsApp change — also
`field = "messages"`, object `whatsapp_business_account` — never reaches it (WA-07's rule).

One claimed change = one item of `entry[].messaging[]` of an `object: "instagram"`
delivery (`business-messaging/instagram-messaging/webhooks.md:53-81`; the envelope maps
each item to a change with `field = "messages"`, see `webhooks/envelope.py`):

    {"sender": {"id": IGSID}, "recipient": {"id": IGID}, "timestamp": 1569262485349,
     "message": {"mid": "…", "text": "…", "attachments": [...], "is_echo": true?,
                 "reply_to": {"story": {"id": STORY-ID, "url": CDN-URL}}?}}

`reply_to.story` (m-24789646, B5) marks a DM that replies to one of the account's stories
(`webhooks.md:110-115`): its id and CDN URL are kept on the message, inbound only. A
`reply_to` with a `mid` instead (an inline reply to another message) is not a story and
is ignored. Corpus-only until R3 observes it live.

## Taps (m-24789472, PR 2)

A person may answer by tapping instead of typing (`conversations.choices`):

- a **quick reply** is a normal `message` with `quick_reply.payload` and the button's title
  as `text` (`features/quick-replies.md`): it is stored like any message, plus
  `choice_kind = 'quick_reply'` and the payload;
- an **Ice Breaker**, a **template button** or a **persistent-menu item** is a `postback`
  item (`webhooks.md` «Messaging postbacks», `features/ice-breakers.md`):

      {"sender": {"id": IGSID}, "recipient": {"id": IGID}, "timestamp": …,
       "postback": {"mid": "…", "title": "…", "payload": "…"}}

  It becomes an INBOUND message: text = `title`, kind by the payload prefix
  (`choices.postback_kind`), payload kept. Meta adds `mid` from Graph v11.0 on
  (`webhooks.md:40`; the `features/ice-breakers.md` sample still omits it), so a postback
  without one gets a deterministic synthetic id, `SYNTHETIC_POSTBACK_PREFIX` + the
  sha256 of `sender | timestamp | payload | title` (`synthetic_postback_mid`): a replay of
  the same item is the same row. Such a row cannot meet the poll's copy of the message,
  which carries Meta's real `mid` — accepted, because a webhook subscription on Graph
  v11.0 or later always sends one; the prefix makes such rows easy to find.
  A postback whose sender is the account itself is not a person's tap: settled
  `unsupported` (`postback_echo`), nothing written. A postback with neither title nor
  payload, or without sender/recipient (or, lacking a `mid`, without a timestamp) is off
  contract.

Nothing here answers a tap: the message lands in the inbox like a typed one, and any reply
is still a draft a person approves (`suggest.py`, `outbox.enqueue(approval=…)`).

What one change does, in order:

1. `event.value` must be an object carrying a `message` with a string `mid`, a
   `postback`, or a `read`; a `reaction` or any other item is settled `unsupported`
   (kept, replayable the day it has a handler); a `message` flagged `is_deleted` is
   `unsupported` too (`message_deleted` — nothing to show, nothing to re-read). Postbacks
   settled `unsupported` before this handler read them are replayed with
   `python -m qualify_api.webhooks.worker --requeue-postbacks`.
2. Resolve `entry[].id` (the Instagram professional account id) → `(tenant, connection)`
   through `mentions.resolve.resolve_external_account`. `ORPHAN` / `AMBIGUOUS` → settled
   as such, **nothing written** (QUA-97's invariant).
3. `is_echo` (the account itself wrote, from Instagram or from Qualify's own sender) →
   `outbound`, counterpart = `recipient.id`; otherwise `inbound`, counterpart =
   `sender.id`. Then `ConversationSyncService.ingest_message`: same upsert, same insert
   by `mid`, same bump as the poll — a replayed delivery, or the poll reaching the same
   `mid` later, is one row. An echo of a message the outbox already wrote under its
   `message_id` is the same `mid` and therefore a no-op. An echo of a button template
   (m-24789472) has no `text`: its text is read from the template attachment, and it is
   stored as `media_type = 'interactive'`. A webhook that reaches a `mid`
   the poll stored first adds the tap's kind and payload (only while the row has none).
4. `processed`.

No user text in logs: ids, kinds and outcomes only. `[V]`-pending like the adapter: the
shape is read from the corpus, not observed live.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from qualify_api.conversations.choices import (
    CHOICE_QUICK_REPLY,
    normalize_payload,
    postback_kind,
)
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
    RemoteRead,
    SourceConnection,
    story_reference,
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
POSTBACK_ECHO: Final = "postback_echo"
CONTRACT_VIOLATION: Final = "contract_violation"

#: The shape contract a postback item is parsed under (a quick reply is a `message`, so it
#: keeps `SHAPE_VERSION_IG_DM`).
SHAPE_VERSION_IG_POSTBACK: Final = "ig-dm-postback-1.0.0"
#: The `external_message_id` of a postback Meta sent without `mid`.
SYNTHETIC_POSTBACK_PREFIX: Final = "qf-postback:"

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


def _story_reply_of(message: Mapping[str, Any]) -> tuple[str, str | None] | None:
    reply_to = message.get("reply_to")
    return story_reference(reply_to.get("story")) if isinstance(reply_to, Mapping) else None


def _template_text(message: Mapping[str, Any]) -> str | None:
    """The text above the buttons of a template attachment (`attachments[0].payload.
    text`) — what an echo of Qualify's own button template carries instead of `text`
    (m-24789472). `[CORPUS]`: the echo's attachment shape is read from the send body."""
    attachments = message.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        return None
    first = attachments[0]
    if not isinstance(first, Mapping) or first.get("type") != "template":
        return None
    payload = first.get("payload")
    text = payload.get("text") if isinstance(payload, Mapping) else None
    return text if isinstance(text, str) and text else None


def _quick_reply_payload(message: Mapping[str, Any]) -> str | None:
    quick_reply = message.get("quick_reply")
    if not isinstance(quick_reply, Mapping):
        return None
    return normalize_payload(quick_reply.get("payload"))


def synthetic_postback_mid(
    *, sender_id: str, timestamp: Any, payload: str | None, title: str | None
) -> str:
    """A stable id for a postback Meta sent without `mid`: the same item, replayed,
    always maps to the same row. Never mistaken for Meta's (`SYNTHETIC_POSTBACK_PREFIX`)."""
    material = "\x1f".join([sender_id, str(timestamp), payload or "", title or ""])
    return SYNTHETIC_POSTBACK_PREFIX + hashlib.sha256(material.encode("utf-8")).hexdigest()


def parse_postback(
    value: Mapping[str, Any], postback: Mapping[str, Any], *, own_account_id: str
) -> tuple[RemoteConversation, RemoteMessage] | str:
    """A `postback` item (an Ice Breaker, a template button, a menu item) as the inbound
    message it is, or `POSTBACK_ECHO` for one the account itself sent. Raises `ValueError`
    for one that breaks the documented shape."""
    sender_id, recipient_id = _id_of(value.get("sender")), _id_of(value.get("recipient"))
    if sender_id is None or recipient_id is None:
        raise ValueError("postback item lacks sender or recipient")
    if sender_id == own_account_id:
        return POSTBACK_ECHO
    raw_title = postback.get("title")
    title = raw_title if isinstance(raw_title, str) and raw_title.strip() else None
    payload = normalize_payload(postback.get("payload"))
    if title is None and payload is None:
        raise ValueError("postback item carries neither title nor payload")
    mid = postback.get("mid")
    if not isinstance(mid, str) or not mid:
        timestamp = value.get("timestamp")
        if _posted_at(timestamp) is None:
            raise ValueError("postback item lacks both mid and timestamp")
        mid = synthetic_postback_mid(
            sender_id=sender_id, timestamp=timestamp, payload=payload, title=title
        )
    remote = RemoteMessage(
        external_message_id=mid,
        direction="inbound",
        text=title,
        posted_at=_posted_at(value.get("timestamp")),
        shape_version=SHAPE_VERSION_IG_POSTBACK,
        author_external_id=sender_id,
        choice_kind=postback_kind(payload),
        choice_payload=payload,
    )
    return RemoteConversation(counterpart_external_id=sender_id), remote


def parse_messaging_item(
    value: Any, *, own_account_id: str
) -> tuple[RemoteConversation, RemoteMessage] | RemoteRead | str:
    """The `(conversation, message)` an item carries — a `message` or a `postback` —, a
    `RemoteRead` for a `read` (`messaging_seen`) item, or the `unsupported` reason when it
    is none of them. Raises `ValueError` for an item that claims to be one of those but
    breaks the shape."""
    if not isinstance(value, Mapping):
        raise ValueError("messaging item is not an object")
    postback = value.get("postback")
    if isinstance(postback, Mapping):
        return parse_postback(value, postback, own_account_id=own_account_id)
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
    if not isinstance(text, str) or not text:
        text = _template_text(message)
    story = None if is_echo else _story_reply_of(message)
    # A quick reply is the person's tap: an echo (the business's own message) never is one.
    quick_reply = None if is_echo else _quick_reply_payload(message)
    tapped = not is_echo and isinstance(message.get("quick_reply"), Mapping)
    remote = RemoteMessage(
        external_message_id=mid,
        direction="outbound" if is_echo else "inbound",
        text=text if isinstance(text, str) and text else None,
        posted_at=_posted_at(value.get("timestamp")),
        shape_version=SHAPE_VERSION_IG_DM,
        author_external_id=sender_id,
        media_type=_media_type(message),
        media_url=_media_url_of(message),
        story_reply_id=story[0] if story else None,
        story_reply_url=story[1] if story else None,
        choice_kind=CHOICE_QUICK_REPLY if tapped else None,
        choice_payload=quick_reply if tapped else None,
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
        # Ids, kinds and outcomes only: never the text, never the payload.
        logger.info(
            "instagram messages webhook: tenant=%s connection=%s direction=%s thread=%s "
            "thread_created=%s message_created=%s choice=%s",
            resolution.tenant_id,
            resolution.connection_id,
            message.direction,
            result.thread_id,
            result.thread_created,
            result.message_created,
            message.choice_kind or "-",
        )
        return Outcome(STATUS_PROCESSED)

    return handle


__all__ = [
    "CONTRACT_VIOLATION",
    "INSTAGRAM_MESSAGES_HANDLER_KEY",
    "MESSAGE_DELETED",
    "NOT_A_MESSAGE",
    "POSTBACK_ECHO",
    "SHAPE_VERSION_IG_POSTBACK",
    "SYNTHETIC_POSTBACK_PREFIX",
    "instagram_messages_handler",
    "parse_messaging_item",
    "parse_postback",
    "synthetic_postback_mid",
]
