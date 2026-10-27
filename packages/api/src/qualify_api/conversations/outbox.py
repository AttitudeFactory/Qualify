"""The outbound side of private conversations (QUA-226, E1): the `conversation_outbox`
queue (0065) and the ONE way into it — `enqueue`, which requires a `HumanApproval`.

ADR 21c in code: nothing in this repository can enqueue a send without the person who
approved it. `HumanApproval` is a required, non-optional argument; the row's
`approved_by_user_id` is NOT NULL; and the static guard
`test_conversations_outbox_sanctity.py` fails if any module other than this one writes
the table. The webhook worker role holds no privilege on it at all (0065), so the only
automated path into the system — a Meta delivery — cannot produce a send even by a bug.

What this module does NOT contain yet: the sender loop and the worker (the plan's E1
listed them; the approved scope for this delivery stops at the queue and its contracts,
nothing sends). The queue shape is `whatsapp_outbox`'s (WA-08) so that loop, when it
comes, is the same claim → window → send → settle with the same guarantees:

- `claim` takes due `pending` rows and stale `sending` rows (a dead worker's) with `FOR
  UPDATE SKIP LOCKED` inside a MATERIALIZED CTE — see `whatsapp/outbox.py` for the
  measured reason the CTE form is required. A reclaimed stale row counts an attempt.
- Every settle is guarded by `status = 'sending'`, so a late or duplicate settle is a
  no-op. `mark_sent` also writes the outbound `messages` row under the channel's message
  id (`ON CONFLICT DO NOTHING` on `uq_message_external_id`) and bumps the thread's
  `last_message_at` — never `last_inbound_at` (0004's B2 condition).

**Private replies (m-24789646, 0073).** A `private_reply` row is Meta's one-off DM to
the author of a comment, addressed by the comment (`PrivateReplyTarget`). Same queue, same
approval, same settles; it also carries the comment and the 7-day deadline the sender
revalidates, and there is at most one live row per comment (`PrivateReplyExists`).
`mark_sent` records, for every send, whom the channel says it reached.

`enqueue(..., on_enqueued=)` lets the caller write its own record of the decision in the
SAME transaction as the insert (Fase C's followup): the callback gets the open session
and the new row's id, and if it raises, the row is never queued. This module stays the
only writer of the queue; the callback writes only its own table.

No user text in logs: ids, statuses and codes only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# `HumanApproval` / `ApprovalRequired` live in `qualify_api.assisted.approval` since
# m-24789645 (the public comment reply demands the same object); re-exported here.
from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.conversations.contracts import MEDIA_TYPE_STICKER, REPLY_MEDIA_TYPES
from qualify_api.conversations.interactive import template_payload
from qualify_api.conversations.models import OUTBOX_CHANNELS, OUTBOX_KINDS

logger = logging.getLogger("qualify_api.conversations.outbox")

KIND_REPLY: Final = "reply"
KIND_PRIVATE_REPLY: Final = "private_reply"
MAX_ATTEMPTS: Final = 5
BACKOFF_BASE_SECONDS: Final = 4
STALE_AFTER: Final = timedelta(minutes=10)
DEFAULT_BATCH: Final = 50
ERROR_STALE_EXHAUSTED: Final = "stale_lock_attempts_exhausted"
# `shape_version` of the outbound `messages` row `mark_sent` writes.
OUTBOX_SHAPE_VERSION: Final = "conversation-outbox-1.0.0"


def backoff(attempts: int) -> timedelta:
    """Delay before the next try after `attempts` failures: `4^attempts` seconds."""
    return timedelta(seconds=BACKOFF_BASE_SECONDS**attempts)


def payload_text(payload: Mapping[str, Any]) -> str | None:
    """The human-readable text of a Messenger-Platform body (`message.text`, or — for a
    button template, m-24789472 — the text above its buttons), or None."""
    message = payload.get("message")
    if isinstance(message, Mapping):
        value = message.get("text")
        if isinstance(value, str):
            return value
        template = template_payload(payload)
        text_above = template.get("text") if template is not None else None
        return text_above if isinstance(text_above, str) else None
    return None


#: Called inside `enqueue`'s transaction with `(session, item_id)` — `session` is None
#: for the in-memory repository. Raising aborts the enqueue.
OnEnqueued = Callable[[Any, UUID], None]


class PrivateReplyExists(ValueError):
    """The comment already has a private reply queued, sending or sent: Meta allows one."""


@dataclass(frozen=True)
class PrivateReplyTarget:
    """What makes a queued message a private reply: the comment it answers and the
    instant Meta stops accepting it (`conversations.window.private_reply_deadline`)."""

    comment_id: str
    deadline: datetime

    def __post_init__(self) -> None:
        if not self.comment_id:
            raise ValueError("a private reply needs the comment it answers")
        if not isinstance(self.deadline, datetime):
            raise ValueError("a private reply needs its deadline")


@dataclass(frozen=True)
class OutboxMedia:
    """The R2 object a media reply sends (0065's three columns). The public URL Meta
    fetches is minted by the sender at send time, never stored here."""

    object_key: str
    media_type: str  # image | audio | video | document (`REPLY_MEDIA_TYPES`) | sticker
    content_type: str

    def __post_init__(self) -> None:
        if self.media_type == MEDIA_TYPE_STICKER:
            if self.object_key or self.content_type:
                raise ValueError("a sticker carries no object: it is the channel's own")
            return
        if not self.object_key:
            raise ValueError("a media reply needs the object key of what it sends")
        if self.media_type not in REPLY_MEDIA_TYPES:
            raise ValueError(f"media_type {self.media_type!r} is not one of {REPLY_MEDIA_TYPES}")

    @classmethod
    def sticker(cls) -> OutboxMedia:
        """The marker of a sticker reply: the outbound message records
        `media_type = 'sticker'`, and the sender has nothing to link."""
        return cls(object_key="", media_type=MEDIA_TYPE_STICKER, content_type="")

    @property
    def needs_link(self) -> bool:
        return bool(self.object_key)
        if not self.content_type:
            raise ValueError("a media reply needs its content type")


@dataclass(frozen=True)
class ClaimedOutboxItem:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    thread_id: UUID
    channel: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    created_at: datetime
    media: OutboxMedia | None = None
    # Set on a private reply: the sender sends only before it (0073).
    reply_deadline: datetime | None = None


@dataclass(frozen=True)
class OutboxRecord:
    id: UUID
    thread_id: UUID
    channel: str
    status: str
    attempts: int
    payload: dict[str, Any]
    approved_by_user_id: UUID
    approved_at: datetime
    draft_id: UUID | None
    external_message_id: str | None
    error_code: str | None
    created_at: datetime
    sent_at: datetime | None
    media_type: str | None = None
    media_object_key: str | None = None
    kind: str = KIND_REPLY
    comment_id: str | None = None
    reply_deadline: datetime | None = None
    recipient_external_id: str | None = None


class ConversationOutboxRepository(Protocol):
    def enqueue(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        channel: str,
        payload: Mapping[str, Any],
        approval: HumanApproval,
        media: OutboxMedia | None = None,
        private_reply: PrivateReplyTarget | None = None,
        on_enqueued: OnEnqueued | None = None,
    ) -> UUID: ...

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int = DEFAULT_BATCH
    ) -> list[ClaimedOutboxItem]: ...

    def mark_sent(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        external_message_id: str,
        now: datetime,
        recipient_external_id: str | None = None,
    ) -> None: ...

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        attempts: int,
        error_code: str | None,
        next_attempt_at: datetime,
    ) -> None: ...

    def mark_failed(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None: ...

    def mark_dead(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None: ...

    def list_for_thread(self, *, tenant_id: UUID, thread_id: UUID) -> list[OutboxRecord]: ...

    def status_of(self, *, tenant_id: UUID, item_id: UUID) -> str | None: ...


def _validate_enqueue(
    channel: str,
    payload: Mapping[str, Any],
    thread_id: UUID,
    approval: HumanApproval | None,
    private_reply: PrivateReplyTarget | None = None,
) -> None:
    if approval is None or not isinstance(approval, HumanApproval):
        raise ApprovalRequired("a private reply cannot be queued without a human approval")
    if channel not in OUTBOX_CHANNELS:
        raise ValueError(f"channel {channel!r} is not one of {OUTBOX_CHANNELS}")
    if not isinstance(thread_id, UUID):
        raise ValueError("a reply answers a thread: thread_id is required")
    if not isinstance(payload, Mapping) or not payload:
        raise ValueError("payload must be a non-empty, already-built wire body")
    recipient = payload.get("recipient")
    addressed_to = recipient.get("comment_id") if isinstance(recipient, Mapping) else None
    if private_reply is not None:
        if not isinstance(private_reply, PrivateReplyTarget):
            raise ValueError("private_reply must be a PrivateReplyTarget")
        if addressed_to != private_reply.comment_id:
            raise ValueError("a private reply's body must be addressed to its comment")
    elif addressed_to is not None:
        raise ValueError("a body addressed to a comment must be queued as a private reply")


def _kind(private_reply: PrivateReplyTarget | None) -> str:
    return KIND_PRIVATE_REPLY if private_reply is not None else KIND_REPLY


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------

_ENQUEUE = text(
    """
    INSERT INTO conversation_outbox (id, tenant_id, connection_id, thread_id, channel, kind,
                                     payload, approved_by_user_id, approved_at, draft_id,
                                     media_object_key, media_type, media_content_type,
                                     comment_id, reply_deadline)
    VALUES (:id, :tenant_id, :connection_id, :thread_id, :channel, :kind,
            CAST(:payload AS jsonb), :approved_by, :approved_at, :draft_id,
            :media_object_key, :media_type, :media_content_type,
            :comment_id, :reply_deadline)
    """
)

_CLAIM_DEAD_STALE = text(
    """
    UPDATE conversation_outbox
       SET status = 'dead', error_code = :error, locked_at = NULL, locked_by = NULL
     WHERE status = 'sending' AND locked_at < :stale AND attempts >= :max
    """
)

# MATERIALIZED, for the reason measured in `whatsapp/outbox.py` (a `LIMIT 2` claim in the
# `IN (subquery)` form returned 3 rows on Postgres 16).
CLAIM_SQL = text(
    """
    WITH due AS MATERIALIZED (
        SELECT id FROM conversation_outbox
         WHERE ((status = 'pending' AND next_attempt_at <= :now)
            OR (status = 'sending' AND locked_at < :stale))
           AND EXISTS (
               SELECT 1 FROM social_connections AS connection
                WHERE connection.id = conversation_outbox.connection_id
                  AND connection.tenant_id = conversation_outbox.tenant_id
                  AND connection.status = 'active')
         ORDER BY created_at, id
         LIMIT :limit
         FOR UPDATE SKIP LOCKED)
    UPDATE conversation_outbox AS o
       SET status = 'sending', locked_by = :worker, locked_at = :now,
           attempts = CASE WHEN o.status = 'sending' THEN o.attempts + 1 ELSE o.attempts END
      FROM due
     WHERE o.id = due.id
    RETURNING o.id, o.tenant_id, o.connection_id, o.thread_id, o.channel, o.kind, o.payload,
              o.attempts, o.created_at, o.media_object_key, o.media_type, o.media_content_type,
              o.reply_deadline
    """
)

_MARK_SENT = text(
    """
    UPDATE conversation_outbox
       SET status = 'sent', external_message_id = :mid, sent_at = :now, error_code = NULL,
           recipient_external_id = :recipient, locked_by = NULL, locked_at = NULL
     WHERE id = :item_id AND status = 'sending'
    RETURNING connection_id, thread_id, payload, media_object_key, media_type,
              media_content_type
    """
)

_INSERT_OUTBOUND_MESSAGE = text(
    """
    INSERT INTO messages (id, tenant_id, thread_id, connection_id, external_message_id,
                          direction, text, posted_at, shape_version, delivery_status,
                          media_type, media_object_key, media_mime)
    VALUES (:id, :tenant_id, :thread_id, :connection_id, :mid, 'outbound', :text, :now,
            :shape_version, 'sent', :media_type, :media_object_key, :media_mime)
    ON CONFLICT (connection_id, external_message_id) DO NOTHING
    """
)

_BUMP_LAST_MESSAGE = text(
    """
    UPDATE threads SET last_message_at = GREATEST(last_message_at, CAST(:now AS timestamptz))
     WHERE id = :thread_id
    """
)

_MARK_RETRY = text(
    """
    UPDATE conversation_outbox
       SET status = 'pending', attempts = :attempts, error_code = :error,
           next_attempt_at = :next, locked_by = NULL, locked_at = NULL
     WHERE id = :item_id AND status = 'sending'
    """
)

_MARK_TERMINAL = text(
    """
    UPDATE conversation_outbox
       SET status = :status, error_code = :error,
           attempts = COALESCE(CAST(:attempts AS integer), attempts),
           locked_by = NULL, locked_at = NULL
     WHERE id = :item_id AND status = 'sending'
    """
)

_LIST_FOR_THREAD = text(
    """
    SELECT id, thread_id, channel, status, attempts, payload, approved_by_user_id, approved_at,
           draft_id, external_message_id, error_code, created_at, sent_at, media_type,
           media_object_key, kind, comment_id, reply_deadline, recipient_external_id
      FROM conversation_outbox
     WHERE thread_id = :thread_id
     ORDER BY created_at, id
    """
)


# m-24849131 (ATENDER-10): where one queued send stands, for the screen that approved it.
_STATUS_OF = text("SELECT status FROM conversation_outbox WHERE id = :item_id")


class PostgresConversationOutboxRepository:
    def enqueue(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        channel: str,
        payload: Mapping[str, Any],
        approval: HumanApproval,
        media: OutboxMedia | None = None,
        private_reply: PrivateReplyTarget | None = None,
        on_enqueued: OnEnqueued | None = None,
    ) -> UUID:
        _validate_enqueue(channel, payload, thread_id, approval, private_reply)
        item_id = uuid4()
        try:
            with tenant_session(tenant_id) as session:
                session.execute(
                    _ENQUEUE,
                    {
                        "id": item_id,
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                        "thread_id": thread_id,
                        "channel": channel,
                        "kind": _kind(private_reply),
                        "payload": json.dumps(dict(payload)),
                        "approved_by": approval.user_id,
                        "approved_at": approval.approved_at,
                        "draft_id": approval.draft_id,
                        "media_object_key": (media.object_key or None) if media else None,
                        "media_type": media.media_type if media else None,
                        "media_content_type": media.content_type if media else None,
                        "comment_id": private_reply.comment_id if private_reply else None,
                        "reply_deadline": private_reply.deadline if private_reply else None,
                    },
                )
                if on_enqueued is not None:
                    on_enqueued(session, item_id)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if private_reply is not None and constraint == "uq_conv_outbox_private_reply":
                raise PrivateReplyExists(private_reply.comment_id) from exc
            raise
        return item_id

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int = DEFAULT_BATCH
    ) -> list[ClaimedOutboxItem]:
        stale = now - STALE_AFTER
        with tenant_session(tenant_id) as session:
            session.execute(
                _CLAIM_DEAD_STALE,
                {"error": ERROR_STALE_EXHAUSTED, "stale": stale, "max": MAX_ATTEMPTS},
            )
            rows = session.execute(
                CLAIM_SQL, {"now": now, "stale": stale, "limit": limit, "worker": worker_id}
            ).all()
        return [
            ClaimedOutboxItem(
                id=r.id,
                tenant_id=r.tenant_id,
                connection_id=r.connection_id,
                thread_id=r.thread_id,
                channel=r.channel,
                kind=r.kind,
                payload=dict(r.payload),
                attempts=r.attempts,
                created_at=r.created_at,
                media=_media_of(r.media_object_key, r.media_type, r.media_content_type),
                reply_deadline=r.reply_deadline,
            )
            for r in rows
        ]

    def mark_sent(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        external_message_id: str,
        now: datetime,
        recipient_external_id: str | None = None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                _MARK_SENT,
                {
                    "item_id": item_id,
                    "mid": external_message_id,
                    "now": now,
                    "recipient": recipient_external_id,
                },
            ).one_or_none()
            if row is None:
                logger.warning(
                    "conversations.outbox.settle_skipped item_id=%s outcome=sent", item_id
                )
                return
            session.execute(
                _INSERT_OUTBOUND_MESSAGE,
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "thread_id": row.thread_id,
                    "connection_id": row.connection_id,
                    "mid": external_message_id,
                    "text": payload_text(row.payload),
                    "now": now,
                    "shape_version": OUTBOX_SHAPE_VERSION,
                    "media_type": row.media_type,
                    "media_object_key": row.media_object_key,
                    "media_mime": row.media_content_type,
                },
            )
            session.execute(_BUMP_LAST_MESSAGE, {"thread_id": row.thread_id, "now": now})

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        attempts: int,
        error_code: str | None,
        next_attempt_at: datetime,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _MARK_RETRY,
                {
                    "item_id": item_id,
                    "attempts": attempts,
                    "error": error_code,
                    "next": next_attempt_at,
                },
            )

    def mark_failed(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        self._terminal(tenant_id, item_id, "failed", error_code, attempts)

    def mark_dead(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        self._terminal(tenant_id, item_id, "dead", error_code, attempts)

    def _terminal(
        self, tenant_id: UUID, item_id: UUID, status: str, error_code: str, attempts: int | None
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _MARK_TERMINAL,
                {"item_id": item_id, "status": status, "error": error_code, "attempts": attempts},
            )

    def status_of(self, *, tenant_id: UUID, item_id: UUID) -> str | None:
        """The row's status (`pending`/`sending`/`sent`/`failed`/`dead`), or None when this
        tenant has no such row (RLS scopes the read). Read-only."""
        with tenant_session(tenant_id) as session:
            return session.execute(_STATUS_OF, {"item_id": item_id}).scalar_one_or_none()

    def list_for_thread(self, *, tenant_id: UUID, thread_id: UUID) -> list[OutboxRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_LIST_FOR_THREAD, {"thread_id": thread_id}).all()
        return [
            OutboxRecord(
                id=r.id,
                thread_id=r.thread_id,
                channel=r.channel,
                status=r.status,
                attempts=r.attempts,
                payload=dict(r.payload),
                approved_by_user_id=r.approved_by_user_id,
                approved_at=r.approved_at,
                draft_id=r.draft_id,
                external_message_id=r.external_message_id,
                error_code=r.error_code,
                created_at=r.created_at,
                sent_at=r.sent_at,
                media_type=r.media_type,
                media_object_key=r.media_object_key,
                kind=r.kind,
                comment_id=r.comment_id,
                reply_deadline=r.reply_deadline,
                recipient_external_id=r.recipient_external_id,
            )
            for r in rows
        ]


def _media_of(object_key: str | None, media_type: str | None, content_type: str | None):
    if media_type == MEDIA_TYPE_STICKER:
        return OutboxMedia.sticker()
    if not object_key or not media_type or not content_type:
        return None
    return OutboxMedia(object_key=object_key, media_type=media_type, content_type=content_type)


# --------------------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class MemoryOutboxRow:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    thread_id: UUID
    channel: str
    kind: str
    payload: dict[str, Any]
    approved_by_user_id: UUID
    approved_at: datetime
    draft_id: UUID | None
    created_at: datetime
    next_attempt_at: datetime
    seq: int
    status: str = "pending"
    attempts: int = 0
    locked_by: str | None = None
    locked_at: datetime | None = None
    external_message_id: str | None = None
    error_code: str | None = None
    sent_at: datetime | None = None
    media: OutboxMedia | None = None
    comment_id: str | None = None
    reply_deadline: datetime | None = None
    recipient_external_id: str | None = None


# The statuses under which a private reply blocks another for the same comment (0073).
_LIVE_STATUSES = frozenset({"pending", "sending", "sent"})


@dataclass(frozen=True)
class MemoryOutboundMessage:
    tenant_id: UUID
    thread_id: UUID
    connection_id: UUID
    external_message_id: str
    text: str | None
    posted_at: datetime
    media_type: str | None = None
    media_object_key: str | None = None


class MemoryConversationOutboxRepository:
    """Same contract, in dictionaries. `messages` is what `mark_sent` wrote;
    `thread_last_message_at` the bump it made."""

    def __init__(self, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock
        self._seq = count()
        self.rows: dict[UUID, MemoryOutboxRow] = {}
        self.messages: list[MemoryOutboundMessage] = []
        self.thread_last_message_at: dict[UUID, datetime] = {}

    def enqueue(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        channel: str,
        payload: Mapping[str, Any],
        approval: HumanApproval,
        media: OutboxMedia | None = None,
        private_reply: PrivateReplyTarget | None = None,
        on_enqueued: OnEnqueued | None = None,
    ) -> UUID:
        _validate_enqueue(channel, payload, thread_id, approval, private_reply)
        if private_reply is not None and any(
            r.kind == KIND_PRIVATE_REPLY
            and r.connection_id == connection_id
            and r.comment_id == private_reply.comment_id
            and r.status in _LIVE_STATUSES
            for r in self.rows.values()
        ):
            raise PrivateReplyExists(private_reply.comment_id)
        now = self._clock()
        row = MemoryOutboxRow(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            thread_id=thread_id,
            channel=channel,
            kind=_kind(private_reply),
            payload=dict(payload),
            approved_by_user_id=approval.user_id,
            approved_at=approval.approved_at,
            draft_id=approval.draft_id,
            created_at=now,
            next_attempt_at=now,
            seq=next(self._seq),
            media=media,
            comment_id=private_reply.comment_id if private_reply else None,
            reply_deadline=private_reply.deadline if private_reply else None,
        )
        if on_enqueued is not None:
            on_enqueued(None, row.id)  # raising leaves nothing queued, like a rollback
        self.rows[row.id] = row
        return row.id

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int = DEFAULT_BATCH
    ) -> list[ClaimedOutboxItem]:
        stale = now - STALE_AFTER
        claimed: list[ClaimedOutboxItem] = []
        for row in sorted(self.rows.values(), key=lambda r: (r.created_at, r.seq)):
            if row.tenant_id != tenant_id or len(claimed) >= limit:
                continue
            is_stale = (
                row.status == "sending" and row.locked_at is not None and row.locked_at < stale
            )
            if is_stale and row.attempts >= MAX_ATTEMPTS:
                row.status, row.error_code = "dead", ERROR_STALE_EXHAUSTED
                row.locked_by = row.locked_at = None
                continue
            due = row.status == "pending" and row.next_attempt_at <= now
            if not (due or is_stale):
                continue
            if is_stale:
                row.attempts += 1
            row.status, row.locked_by, row.locked_at = "sending", worker_id, now
            claimed.append(
                ClaimedOutboxItem(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    connection_id=row.connection_id,
                    thread_id=row.thread_id,
                    channel=row.channel,
                    kind=row.kind,
                    payload=dict(row.payload),
                    attempts=row.attempts,
                    created_at=row.created_at,
                    media=row.media,
                    reply_deadline=row.reply_deadline,
                )
            )
        return claimed

    def _sending(self, tenant_id: UUID, item_id: UUID) -> MemoryOutboxRow | None:
        row = self.rows.get(item_id)
        if row is None or row.tenant_id != tenant_id or row.status != "sending":
            return None
        return row

    def mark_sent(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        external_message_id: str,
        now: datetime,
        recipient_external_id: str | None = None,
    ) -> None:
        row = self._sending(tenant_id, item_id)
        if row is None:
            return
        row.status, row.external_message_id, row.sent_at = "sent", external_message_id, now
        row.recipient_external_id = recipient_external_id
        row.error_code = row.locked_by = row.locked_at = None
        if any(
            m.connection_id == row.connection_id and m.external_message_id == external_message_id
            for m in self.messages
        ):
            return
        self.messages.append(
            MemoryOutboundMessage(
                tenant_id=tenant_id,
                thread_id=row.thread_id,
                connection_id=row.connection_id,
                external_message_id=external_message_id,
                text=payload_text(row.payload),
                posted_at=now,
                media_type=row.media.media_type if row.media else None,
                media_object_key=row.media.object_key if row.media else None,
            )
        )
        previous = self.thread_last_message_at.get(row.thread_id)
        if previous is None or previous < now:
            self.thread_last_message_at[row.thread_id] = now

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        attempts: int,
        error_code: str | None,
        next_attempt_at: datetime,
    ) -> None:
        row = self._sending(tenant_id, item_id)
        if row is None:
            return
        row.status, row.attempts, row.error_code = "pending", attempts, error_code
        row.next_attempt_at = next_attempt_at
        row.locked_by = row.locked_at = None

    def mark_failed(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        self._terminal(tenant_id, item_id, "failed", error_code, attempts)

    def mark_dead(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        self._terminal(tenant_id, item_id, "dead", error_code, attempts)

    def _terminal(
        self, tenant_id: UUID, item_id: UUID, status: str, error_code: str, attempts: int | None
    ) -> None:
        row = self._sending(tenant_id, item_id)
        if row is None:
            return
        row.status, row.error_code = status, error_code
        if attempts is not None:
            row.attempts = attempts
        row.locked_by = row.locked_at = None

    def status_of(self, *, tenant_id: UUID, item_id: UUID) -> str | None:
        row = self.rows.get(item_id)
        return row.status if row is not None and row.tenant_id == tenant_id else None

    def list_for_thread(self, *, tenant_id: UUID, thread_id: UUID) -> list[OutboxRecord]:
        return [
            OutboxRecord(
                id=r.id,
                thread_id=r.thread_id,
                channel=r.channel,
                status=r.status,
                attempts=r.attempts,
                payload=dict(r.payload),
                approved_by_user_id=r.approved_by_user_id,
                approved_at=r.approved_at,
                draft_id=r.draft_id,
                external_message_id=r.external_message_id,
                error_code=r.error_code,
                created_at=r.created_at,
                sent_at=r.sent_at,
                media_type=r.media.media_type if r.media else None,
                media_object_key=r.media.object_key if r.media else None,
                kind=r.kind,
                comment_id=r.comment_id,
                reply_deadline=r.reply_deadline,
                recipient_external_id=r.recipient_external_id,
            )
            for r in sorted(self.rows.values(), key=lambda r: (r.created_at, r.seq))
            if r.tenant_id == tenant_id and r.thread_id == thread_id
        ]


__all__ = [
    "BACKOFF_BASE_SECONDS",
    "CLAIM_SQL",
    "DEFAULT_BATCH",
    "ERROR_STALE_EXHAUSTED",
    "KIND_PRIVATE_REPLY",
    "KIND_REPLY",
    "MAX_ATTEMPTS",
    "OUTBOX_KINDS",
    "OUTBOX_SHAPE_VERSION",
    "OnEnqueued",
    "STALE_AFTER",
    "ApprovalRequired",
    "ClaimedOutboxItem",
    "ConversationOutboxRepository",
    "HumanApproval",
    "MemoryConversationOutboxRepository",
    "MemoryOutboundMessage",
    "MemoryOutboxRow",
    "OutboxMedia",
    "OutboxRecord",
    "PostgresConversationOutboxRepository",
    "PrivateReplyExists",
    "PrivateReplyTarget",
    "backoff",
    "payload_text",
]
