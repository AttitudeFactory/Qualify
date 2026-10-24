"""Persistence of private conversations (QUA-226, E1): `threads`/`messages` (0004 + 0065)
and `conversation_sync_state` (0065), channel-agnostic.

Every method is tenant-scoped by `tenant_id`; the Postgres implementation opens
`tenant_session(tenant_id)` per call (the `qualify_app` role), so RLS bounds every
statement and another tenant's thread reads as missing — not as forbidden.

## Idempotency, at INSERT time

- `upsert_thread` — `uq_thread_natural_key (connection_id, channel, external_thread_id)`,
  where `external_thread_id` is the COUNTERPART's id (IGSID). A replay or a second path
  (webhook after poll, poll after webhook) returns the same thread; the only thing the
  conflict branch may change is filling a missing `external_conversation_id`.
- `insert_message` — `uq_message_external_id (connection_id, external_message_id)`, `ON
  CONFLICT DO NOTHING`, returns `False` on the duplicate. The same `mid` arriving by
  webhook and by poll is one row, whichever came first.
- `bump_thread_activity` — `GREATEST`, so a late or replayed batch never moves
  `last_inbound_at`/`last_message_at` backwards; an inbound newer than the stored one
  reopens a closed thread (the WhatsApp rule, `whatsapp/repository.py`).

`last_inbound_at` is the base of the 24 h window (0004's B2 condition) and is bumped
ONLY from inbound messages; `last_message_at` is inbox ordering only.

`last_outbound_at` on `ThreadRecord` is computed at read time from `messages` — the
«pendiente / leído / respondido» state (`service.attention_state`) is derived, never
stored, so it cannot drift.

The sync-state methods are three narrow upserts (`save_access`, `sync_started`,
`sync_finished`) rather than one "save everything": a crash between them leaves a row
that says exactly how far the sync got.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import bindparam, text

from qualify_api.conversations.choices import choice_label
from qualify_api.conversations.contracts import AccessVerdict, RemoteMessage, RemoteProfile

THREAD_OPEN = "open"
THREAD_CLOSED = "closed"
SYNC_OK = "ok"
SYNC_PARTIAL = "partial"
SYNC_FAILED = "failed"


@dataclass(frozen=True)
class ThreadUpsert:
    thread_id: UUID
    created: bool  # True = this call inserted the thread


@dataclass(frozen=True)
class ThreadRecord:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    channel: str
    # `threads.external_thread_id`: the counterpart's id on the channel.
    counterpart_external_id: str
    external_conversation_id: str | None
    status: str
    assigned_agent_id: UUID | None
    last_message_at: datetime | None
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    last_read_at: datetime | None
    created_at: datetime
    # The counterpart's profile as the channel reported it (0065); all None until a sync
    # fetched it. `counterpart_profile_at` says how fresh the (expiring) picture is.
    counterpart_name: str | None = None
    counterpart_username: str | None = None
    counterpart_avatar_url: str | None = None
    counterpart_profile_at: datetime | None = None


@dataclass(frozen=True)
class MessageRecord:
    id: UUID
    thread_id: UUID
    connection_id: UUID
    external_message_id: str
    direction: str
    author_external_id: str | None
    author_username: str | None
    text: str | None
    posted_at: datetime | None
    ingested_at: datetime
    delivery_status: str | None
    media_type: str | None
    # Inbound: the channel's CDN URL (0065). Outbound: the R2 object Qualify sent (0061).
    media_url: str | None = None
    media_object_key: str | None = None
    # 0075 (m-24789646): the story an inbound DM replies to, if it does.
    story_reply_id: str | None = None
    story_reply_url: str | None = None
    # 0082 (m-24789472): the option an inbound DM was tapped from, if it was.
    choice_kind: str | None = None
    choice_payload: str | None = None

    @property
    def choice_label(self) -> str | None:
        """Where a tapped message came from, for the thread («Pregunta inicial: Precio»,
        «Respuesta rápida: Sí», «Botón: Ver catálogo»); `None` for a typed one."""
        return choice_label(self.choice_kind, self.choice_payload, self.text)


@dataclass(frozen=True)
class SyncStateRecord:
    connection_id: UUID
    channel: str
    access_status: str
    access_detail: str | None
    access_checked_at: datetime | None
    sync_cursor: str | None
    last_sync_started_at: datetime | None
    last_sync_finished_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None


class ConversationRepository(Protocol):
    def upsert_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
        external_conversation_id: str | None = None,
    ) -> ThreadUpsert: ...

    def insert_message(
        self, *, tenant_id: UUID, thread_id: UUID, connection_id: UUID, message: RemoteMessage
    ) -> bool: ...

    def bump_thread_activity(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        last_inbound_at: datetime | None,
        last_message_at: datetime | None,
    ) -> None: ...

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        channels: Sequence[str],
        connection_id: UUID | None = None,
        limit: int = 50,
    ) -> list[ThreadRecord]: ...

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRecord | None: ...

    def find_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
    ) -> ThreadRecord | None: ...

    def list_messages(
        self, *, tenant_id: UUID, thread_id: UUID, limit: int = 50
    ) -> list[MessageRecord]: ...

    def mark_read(self, *, tenant_id: UUID, thread_id: UUID, now: datetime) -> bool: ...

    def mark_outbound_read(self, *, tenant_id: UUID, thread_id: UUID, up_to: datetime) -> int: ...

    def save_profile(
        self, *, tenant_id: UUID, thread_id: UUID, profile: RemoteProfile, now: datetime
    ) -> None: ...

    def hide_message(
        self, *, tenant_id: UUID, thread_id: UUID, message_id: UUID, now: datetime
    ) -> bool: ...

    def get_sync_state(
        self, *, tenant_id: UUID, connection_id: UUID, channel: str
    ) -> SyncStateRecord | None: ...

    def save_access(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        verdict: AccessVerdict,
        now: datetime,
    ) -> None: ...

    def sync_started(
        self, *, tenant_id: UUID, connection_id: UUID, channel: str, now: datetime
    ) -> None: ...

    def sync_finished(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        now: datetime,
        status: str,
        error: str | None,
        cursor: str | None,
    ) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------

# `xmax = 0` is true only for a row this statement inserted (the WhatsApp repository's
# idiom). The conflict branch may only FILL a missing conversation id, never replace one.
_UPSERT_THREAD = text(
    """
    INSERT INTO threads (id, tenant_id, connection_id, channel, external_thread_id,
                         external_conversation_id, status)
    VALUES (:id, :tenant_id, :connection_id, :channel, :counterpart, :conversation_id, :open)
    ON CONFLICT (connection_id, channel, external_thread_id) DO UPDATE
       SET external_conversation_id = COALESCE(threads.external_conversation_id,
                                               EXCLUDED.external_conversation_id)
    RETURNING id, (xmax = 0) AS created
    """
)

# A replay is a no-op, with two exceptions, both FILL-only on an inbound row:
# - the story a DM replies to (m-24789646) is filled in when a later reading carries it and
#   the stored row does not (the poll may reach a `mid` before the webhook, or without
#   asking for `story`);
# - the option a DM was tapped from (m-24789472, 0082): the poll never carries it (the
#   Message node has no postback/quick-reply field), so a webhook — first delivery or a
#   replay — that reaches a `mid` the poll stored adds kind and payload, together.
# A pair already stored is never replaced, nothing else is ever rewritten, and `created`
# is only true for a real insert.
_INSERT_MESSAGE = text(
    """
    INSERT INTO messages (id, tenant_id, thread_id, connection_id, external_message_id,
                          direction, author_external_id, author_username, text, posted_at,
                          shape_version, media_type, media_url, story_reply_id,
                          story_reply_url, choice_kind, choice_payload)
    VALUES (:id, :tenant_id, :thread_id, :connection_id, :external_message_id, :direction,
            :author_external_id, :author_username, :text, :posted_at, :shape_version,
            :media_type, :media_url, :story_reply_id, :story_reply_url, :choice_kind,
            :choice_payload)
    ON CONFLICT (connection_id, external_message_id) DO UPDATE
       SET story_reply_id = CASE WHEN messages.story_reply_id IS NULL
                                 THEN EXCLUDED.story_reply_id
                                 ELSE messages.story_reply_id END,
           story_reply_url = CASE WHEN messages.story_reply_id IS NULL
                                  THEN EXCLUDED.story_reply_url
                                  ELSE messages.story_reply_url END,
           choice_kind = COALESCE(messages.choice_kind, EXCLUDED.choice_kind),
           choice_payload = CASE WHEN messages.choice_kind IS NULL
                                 THEN EXCLUDED.choice_payload
                                 ELSE messages.choice_payload END
     WHERE messages.direction = 'inbound'
       AND ((messages.story_reply_id IS NULL AND EXCLUDED.story_reply_id IS NOT NULL)
            OR (messages.choice_kind IS NULL AND EXCLUDED.choice_kind IS NOT NULL))
    RETURNING (xmax = 0) AS created
    """
)

# The counterpart read up to an instant (`messaging_seen`): every outbound at or before it
# becomes `read`. Idempotent and monotonic — a `read` row never goes back to `sent`.
_MARK_OUTBOUND_READ = text(
    """
    UPDATE messages
       SET delivery_status = 'read'
     WHERE thread_id = :thread_id
       AND direction = 'outbound'
       AND COALESCE(posted_at, ingested_at) <= CAST(:up_to AS timestamptz)
       AND delivery_status IS DISTINCT FROM 'read'
    """
)

# `GREATEST` ignores NULLs, so a batch with no inbound leaves `last_inbound_at` alone.
_BUMP_THREAD = text(
    """
    UPDATE threads
       SET last_inbound_at = GREATEST(last_inbound_at, CAST(:inbound AS timestamptz)),
           last_message_at = GREATEST(last_message_at, CAST(:message_at AS timestamptz)),
           status = CASE
                        WHEN CAST(:inbound AS timestamptz) IS NOT NULL
                         AND (last_inbound_at IS NULL
                              OR CAST(:inbound AS timestamptz) > last_inbound_at)
                        THEN :open
                        ELSE status
                    END
     WHERE id = :thread_id
    """
)

_THREAD_COLUMNS = """
    t.id, t.tenant_id, t.connection_id, t.channel, t.external_thread_id,
    t.external_conversation_id, t.status, t.assigned_agent_id, t.last_message_at,
    t.last_inbound_at, t.last_read_at, t.created_at, t.counterpart_name,
    t.counterpart_username, t.counterpart_avatar_url, t.counterpart_profile_at,
    (SELECT max(COALESCE(m.posted_at, m.ingested_at)) FROM messages m
      WHERE m.thread_id = t.id AND m.direction = 'outbound') AS last_outbound_at
"""

_LIST_THREADS = text(
    f"""
    SELECT {_THREAD_COLUMNS}
      FROM threads t
     WHERE t.channel IN :channels
     ORDER BY t.last_message_at DESC NULLS LAST, t.created_at DESC, t.id
     LIMIT :limit
    """
).bindparams(bindparam("channels", expanding=True))

_LIST_THREADS_FOR_CONNECTION = text(
    f"""
    SELECT {_THREAD_COLUMNS}
      FROM threads t
     WHERE t.channel IN :channels AND t.connection_id = :connection_id
     ORDER BY t.last_message_at DESC NULLS LAST, t.created_at DESC, t.id
     LIMIT :limit
    """
).bindparams(bindparam("channels", expanding=True))

_GET_THREAD = text(f"SELECT {_THREAD_COLUMNS} FROM threads t WHERE t.id = :thread_id")

_FIND_THREAD = text(
    f"""
    SELECT {_THREAD_COLUMNS}
      FROM threads t
     WHERE t.connection_id = :connection_id AND t.channel = :channel
       AND t.external_thread_id = :counterpart
    """
)

# Newest first in SQL (that is what `LIMIT` must cut), reversed in Python so the caller
# reads the conversation top-down.
_LIST_MESSAGES = text(
    """
    SELECT id, thread_id, connection_id, external_message_id, direction, author_external_id,
           author_username, text, posted_at, ingested_at, delivery_status, media_type,
           media_url, media_object_key, story_reply_id, story_reply_url, choice_kind,
           choice_payload
      FROM messages
     WHERE thread_id = :thread_id AND deleted_at IS NULL
     ORDER BY COALESCE(posted_at, ingested_at) DESC, id DESC
     LIMIT :limit
    """
)

_MARK_READ = text(
    """
    UPDATE threads
       SET last_read_at = GREATEST(last_read_at, CAST(:now AS timestamptz))
     WHERE id = :thread_id
    """
)

# «Eliminar para mí»: the row stays (the channel still has the message, and so does the
# other person); it just leaves every listing of this tenant. Idempotent.
_HIDE_MESSAGE = text(
    """
    UPDATE messages
       SET deleted_at = CAST(:now AS timestamptz)
     WHERE id = :message_id AND thread_id = :thread_id AND deleted_at IS NULL
    """
)

# A profile refresh never erases what a previous one knew: a NULL field keeps the old.
_SAVE_PROFILE = text(
    """
    UPDATE threads
       SET counterpart_name = COALESCE(:name, counterpart_name),
           counterpart_username = COALESCE(:username, counterpart_username),
           counterpart_avatar_url = COALESCE(:avatar_url, counterpart_avatar_url),
           counterpart_profile_at = :now
     WHERE id = :thread_id
    """
)

_GET_SYNC_STATE = text(
    """
    SELECT connection_id, channel, access_status, access_detail, access_checked_at,
           sync_cursor, last_sync_started_at, last_sync_finished_at, last_sync_status,
           last_sync_error
      FROM conversation_sync_state
     WHERE connection_id = :connection_id AND channel = :channel
    """
)

_SAVE_ACCESS = text(
    """
    INSERT INTO conversation_sync_state (connection_id, channel, tenant_id, access_status,
                                         access_detail, access_checked_at, updated_at)
    VALUES (:connection_id, :channel, :tenant_id, :status, :detail, :now, now())
    ON CONFLICT (connection_id, channel) DO UPDATE
       SET access_status = EXCLUDED.access_status,
           access_detail = EXCLUDED.access_detail,
           access_checked_at = EXCLUDED.access_checked_at,
           updated_at = now()
    """
)

_SYNC_STARTED = text(
    """
    INSERT INTO conversation_sync_state (connection_id, channel, tenant_id,
                                         last_sync_started_at, updated_at)
    VALUES (:connection_id, :channel, :tenant_id, :now, now())
    ON CONFLICT (connection_id, channel) DO UPDATE
       SET last_sync_started_at = EXCLUDED.last_sync_started_at,
           updated_at = now()
    """
)

_SYNC_FINISHED = text(
    """
    INSERT INTO conversation_sync_state (connection_id, channel, tenant_id,
                                         last_sync_finished_at, last_sync_status,
                                         last_sync_error, sync_cursor, updated_at)
    VALUES (:connection_id, :channel, :tenant_id, :now, :status, :error, :cursor, now())
    ON CONFLICT (connection_id, channel) DO UPDATE
       SET last_sync_finished_at = EXCLUDED.last_sync_finished_at,
           last_sync_status = EXCLUDED.last_sync_status,
           last_sync_error = EXCLUDED.last_sync_error,
           sync_cursor = EXCLUDED.sync_cursor,
           updated_at = now()
    """
)


def _thread_record(row: object) -> ThreadRecord:
    r = row  # a SQLAlchemy Row; attribute access by column label
    return ThreadRecord(
        id=r.id,  # type: ignore[attr-defined]
        tenant_id=r.tenant_id,  # type: ignore[attr-defined]
        connection_id=r.connection_id,  # type: ignore[attr-defined]
        channel=r.channel,  # type: ignore[attr-defined]
        counterpart_external_id=r.external_thread_id,  # type: ignore[attr-defined]
        external_conversation_id=r.external_conversation_id,  # type: ignore[attr-defined]
        status=r.status,  # type: ignore[attr-defined]
        assigned_agent_id=r.assigned_agent_id,  # type: ignore[attr-defined]
        last_message_at=r.last_message_at,  # type: ignore[attr-defined]
        last_inbound_at=r.last_inbound_at,  # type: ignore[attr-defined]
        last_outbound_at=r.last_outbound_at,  # type: ignore[attr-defined]
        last_read_at=r.last_read_at,  # type: ignore[attr-defined]
        created_at=r.created_at,  # type: ignore[attr-defined]
        counterpart_name=r.counterpart_name,  # type: ignore[attr-defined]
        counterpart_username=r.counterpart_username,  # type: ignore[attr-defined]
        counterpart_avatar_url=r.counterpart_avatar_url,  # type: ignore[attr-defined]
        counterpart_profile_at=r.counterpart_profile_at,  # type: ignore[attr-defined]
    )


class PostgresConversationRepository:
    def upsert_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
        external_conversation_id: str | None = None,
    ) -> ThreadUpsert:
        if not counterpart_external_id:
            raise ValueError("a thread needs the counterpart's external id")
        with tenant_session(tenant_id) as session:
            row = session.execute(
                _UPSERT_THREAD,
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "channel": channel,
                    "counterpart": counterpart_external_id,
                    "conversation_id": external_conversation_id,
                    "open": THREAD_OPEN,
                },
            ).one()
        return ThreadUpsert(thread_id=row.id, created=bool(row.created))

    def insert_message(
        self, *, tenant_id: UUID, thread_id: UUID, connection_id: UUID, message: RemoteMessage
    ) -> bool:
        with tenant_session(tenant_id) as session:
            result = session.execute(
                _INSERT_MESSAGE,
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "connection_id": connection_id,
                    "external_message_id": message.external_message_id,
                    "direction": message.direction,
                    "author_external_id": message.author_external_id,
                    "author_username": message.author_username,
                    "text": message.text,
                    "posted_at": message.posted_at,
                    "shape_version": message.shape_version,
                    "media_type": message.media_type,
                    "media_url": message.media_url,
                    "story_reply_id": message.story_reply_id,
                    "story_reply_url": message.story_reply_url,
                    "choice_kind": message.choice_kind,
                    "choice_payload": message.choice_payload,
                },
            ).first()
            return bool(result is not None and result.created)

    def bump_thread_activity(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        last_inbound_at: datetime | None,
        last_message_at: datetime | None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _BUMP_THREAD,
                {
                    "thread_id": thread_id,
                    "inbound": last_inbound_at,
                    "message_at": last_message_at,
                    "open": THREAD_OPEN,
                },
            )

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        channels: Sequence[str],
        connection_id: UUID | None = None,
        limit: int = 50,
    ) -> list[ThreadRecord]:
        if not channels:
            return []
        params: dict[str, object] = {"channels": list(channels), "limit": limit}
        statement = _LIST_THREADS
        if connection_id is not None:
            statement = _LIST_THREADS_FOR_CONNECTION
            params["connection_id"] = connection_id
        with tenant_session(tenant_id) as session:
            rows = session.execute(statement, params).all()
        return [_thread_record(row) for row in rows]

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(_GET_THREAD, {"thread_id": thread_id}).one_or_none()
        return None if row is None else _thread_record(row)

    def find_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
    ) -> ThreadRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                _FIND_THREAD,
                {
                    "connection_id": connection_id,
                    "channel": channel,
                    "counterpart": counterpart_external_id,
                },
            ).one_or_none()
        return None if row is None else _thread_record(row)

    def list_messages(
        self, *, tenant_id: UUID, thread_id: UUID, limit: int = 50
    ) -> list[MessageRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_LIST_MESSAGES, {"thread_id": thread_id, "limit": limit}).all()
        records = [
            MessageRecord(
                id=r.id,
                thread_id=r.thread_id,
                connection_id=r.connection_id,
                external_message_id=r.external_message_id,
                direction=r.direction,
                author_external_id=r.author_external_id,
                author_username=r.author_username,
                text=r.text,
                posted_at=r.posted_at,
                ingested_at=r.ingested_at,
                delivery_status=r.delivery_status,
                media_type=r.media_type,
                media_url=r.media_url,
                media_object_key=r.media_object_key,
                story_reply_id=r.story_reply_id,
                story_reply_url=r.story_reply_url,
                choice_kind=r.choice_kind,
                choice_payload=r.choice_payload,
            )
            for r in rows
        ]
        records.reverse()
        return records

    def mark_read(self, *, tenant_id: UUID, thread_id: UUID, now: datetime) -> bool:
        with tenant_session(tenant_id) as session:
            result = session.execute(_MARK_READ, {"thread_id": thread_id, "now": now})
            return result.rowcount == 1

    def mark_outbound_read(self, *, tenant_id: UUID, thread_id: UUID, up_to: datetime) -> int:
        with tenant_session(tenant_id) as session:
            result = session.execute(_MARK_OUTBOUND_READ, {"thread_id": thread_id, "up_to": up_to})
            return result.rowcount

    def save_profile(
        self, *, tenant_id: UUID, thread_id: UUID, profile: RemoteProfile, now: datetime
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _SAVE_PROFILE,
                {
                    "thread_id": thread_id,
                    "name": profile.name,
                    "username": profile.username,
                    "avatar_url": profile.avatar_url,
                    "now": now,
                },
            )

    def hide_message(
        self, *, tenant_id: UUID, thread_id: UUID, message_id: UUID, now: datetime
    ) -> bool:
        with tenant_session(tenant_id) as session:
            result = session.execute(
                _HIDE_MESSAGE, {"message_id": message_id, "thread_id": thread_id, "now": now}
            )
            return result.rowcount == 1

    def get_sync_state(
        self, *, tenant_id: UUID, connection_id: UUID, channel: str
    ) -> SyncStateRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                _GET_SYNC_STATE, {"connection_id": connection_id, "channel": channel}
            ).one_or_none()
        if row is None:
            return None
        return SyncStateRecord(
            connection_id=row.connection_id,
            channel=row.channel,
            access_status=row.access_status,
            access_detail=row.access_detail,
            access_checked_at=row.access_checked_at,
            sync_cursor=row.sync_cursor,
            last_sync_started_at=row.last_sync_started_at,
            last_sync_finished_at=row.last_sync_finished_at,
            last_sync_status=row.last_sync_status,
            last_sync_error=row.last_sync_error,
        )

    def save_access(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        verdict: AccessVerdict,
        now: datetime,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _SAVE_ACCESS,
                {
                    "connection_id": connection_id,
                    "channel": channel,
                    "tenant_id": tenant_id,
                    "status": verdict.status.value,
                    "detail": verdict.detail,
                    "now": now,
                },
            )

    def sync_started(
        self, *, tenant_id: UUID, connection_id: UUID, channel: str, now: datetime
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _SYNC_STARTED,
                {
                    "connection_id": connection_id,
                    "channel": channel,
                    "tenant_id": tenant_id,
                    "now": now,
                },
            )

    def sync_finished(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        now: datetime,
        status: str,
        error: str | None,
        cursor: str | None,
    ) -> None:
        if status not in (SYNC_OK, SYNC_PARTIAL, SYNC_FAILED):
            raise ValueError(f"unknown sync status {status!r}")
        with tenant_session(tenant_id) as session:
            session.execute(
                _SYNC_FINISHED,
                {
                    "connection_id": connection_id,
                    "channel": channel,
                    "tenant_id": tenant_id,
                    "now": now,
                    "status": status,
                    "error": error,
                    "cursor": cursor,
                },
            )


# --------------------------------------------------------------------------------------
# Memory — the same rules, in dictionaries, for offline tests
# --------------------------------------------------------------------------------------


@dataclass
class _MemoryThread:
    record: ThreadRecord
    messages: list[MessageRecord] = field(default_factory=list)


class MemoryConversationRepository:
    """Mirrors every rule above. Threads are keyed by the natural key; messages by
    `(connection_id, external_message_id)`; a tenant only ever sees its own rows."""

    def __init__(self) -> None:
        self._threads: dict[UUID, _MemoryThread] = {}
        self._by_natural_key: dict[tuple[UUID, str, str], UUID] = {}
        self._message_keys: set[tuple[UUID, str]] = set()
        self.sync_states: dict[tuple[UUID, str], SyncStateRecord] = {}
        # Which tenant a connection's sync state belongs to (the FK's job in Postgres).
        self._tenant_of: dict[UUID, UUID] = {}

    # -- threads / messages -------------------------------------------------------------

    def upsert_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
        external_conversation_id: str | None = None,
    ) -> ThreadUpsert:
        if not counterpart_external_id:
            raise ValueError("a thread needs the counterpart's external id")
        key = (connection_id, channel, counterpart_external_id)
        existing_id = self._by_natural_key.get(key)
        if existing_id is not None:
            entry = self._threads[existing_id]
            if entry.record.tenant_id != tenant_id:
                # The composite FK makes this unbuildable in Postgres; here it is a bug.
                raise PermissionError("thread belongs to another tenant")
            if entry.record.external_conversation_id is None and external_conversation_id:
                entry.record = replace(
                    entry.record, external_conversation_id=external_conversation_id
                )
            return ThreadUpsert(thread_id=existing_id, created=False)
        thread_id = uuid4()
        record = ThreadRecord(
            id=thread_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel=channel,
            counterpart_external_id=counterpart_external_id,
            external_conversation_id=external_conversation_id,
            status=THREAD_OPEN,
            assigned_agent_id=None,
            last_message_at=None,
            last_inbound_at=None,
            last_outbound_at=None,
            last_read_at=None,
            created_at=_utcnow(),
        )
        self._threads[thread_id] = _MemoryThread(record=record)
        self._by_natural_key[key] = thread_id
        return ThreadUpsert(thread_id=thread_id, created=True)

    def insert_message(
        self, *, tenant_id: UUID, thread_id: UUID, connection_id: UUID, message: RemoteMessage
    ) -> bool:
        entry = self._visible(tenant_id, thread_id)
        if entry is None:
            raise LookupError(f"no thread {thread_id} in tenant {tenant_id}")
        key = (connection_id, message.external_message_id)
        if key in self._message_keys:
            self._fill_story_reply(entry, message)
            self._fill_choice(entry, message)
            return False
        self._message_keys.add(key)
        entry.messages.append(
            MessageRecord(
                id=uuid4(),
                thread_id=thread_id,
                connection_id=connection_id,
                external_message_id=message.external_message_id,
                direction=message.direction,
                author_external_id=message.author_external_id,
                author_username=message.author_username,
                text=message.text,
                posted_at=message.posted_at,
                ingested_at=_utcnow(),
                delivery_status=None,
                media_type=message.media_type,
                media_url=message.media_url,
                story_reply_id=message.story_reply_id,
                story_reply_url=message.story_reply_url,
                choice_kind=message.choice_kind,
                choice_payload=message.choice_payload,
            )
        )
        return True

    @staticmethod
    def _fill_story_reply(entry: _MemoryThread, message: RemoteMessage) -> None:
        """The Postgres `ON CONFLICT` exception: a later reading may add the story."""
        if message.story_reply_id is None:
            return
        for index, stored in enumerate(entry.messages):
            if (
                stored.external_message_id == message.external_message_id
                and stored.story_reply_id is None
                and stored.direction == "inbound"
            ):
                entry.messages[index] = replace(
                    stored,
                    story_reply_id=message.story_reply_id,
                    story_reply_url=message.story_reply_url,
                )

    @staticmethod
    def _fill_choice(entry: _MemoryThread, message: RemoteMessage) -> None:
        """The Postgres `ON CONFLICT` exception: a later webhook may add the tapped option."""
        if message.choice_kind is None:
            return
        for index, stored in enumerate(entry.messages):
            if (
                stored.external_message_id == message.external_message_id
                and stored.choice_kind is None
                and stored.direction == "inbound"
            ):
                entry.messages[index] = replace(
                    stored,
                    choice_kind=message.choice_kind,
                    choice_payload=message.choice_payload,
                )

    def bump_thread_activity(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        last_inbound_at: datetime | None,
        last_message_at: datetime | None,
    ) -> None:
        entry = self._visible(tenant_id, thread_id)
        if entry is None:
            return
        rec = entry.record
        inbound = rec.last_inbound_at
        status = rec.status
        if last_inbound_at is not None:
            if inbound is None or _as_utc(last_inbound_at) > _as_utc(inbound):
                inbound = last_inbound_at
                status = THREAD_OPEN
        message_at = rec.last_message_at
        if last_message_at is not None and (
            message_at is None or _as_utc(last_message_at) > _as_utc(message_at)
        ):
            message_at = last_message_at
        entry.record = replace(
            rec, last_inbound_at=inbound, last_message_at=message_at, status=status
        )

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        channels: Sequence[str],
        connection_id: UUID | None = None,
        limit: int = 50,
    ) -> list[ThreadRecord]:
        wanted = set(channels)
        rows = [
            self._with_outbound(entry)
            for entry in self._threads.values()
            if entry.record.tenant_id == tenant_id
            and entry.record.channel in wanted
            and (connection_id is None or entry.record.connection_id == connection_id)
        ]
        rows.sort(
            key=lambda r: (
                r.last_message_at is None,
                -(_as_utc(r.last_message_at).timestamp() if r.last_message_at else 0),
                -_as_utc(r.created_at).timestamp(),
            )
        )
        return rows[:limit]

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRecord | None:
        entry = self._visible(tenant_id, thread_id)
        return None if entry is None else self._with_outbound(entry)

    def find_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
    ) -> ThreadRecord | None:
        thread_id = self._by_natural_key.get((connection_id, channel, counterpart_external_id))
        if thread_id is None:
            return None
        return self.get_thread(tenant_id=tenant_id, thread_id=thread_id)

    def list_messages(
        self, *, tenant_id: UUID, thread_id: UUID, limit: int = 50
    ) -> list[MessageRecord]:
        entry = self._visible(tenant_id, thread_id)
        if entry is None:
            return []
        ordered = sorted(entry.messages, key=lambda m: _as_utc(m.posted_at or m.ingested_at))
        return copy.deepcopy(ordered[-limit:])

    def mark_read(self, *, tenant_id: UUID, thread_id: UUID, now: datetime) -> bool:
        entry = self._visible(tenant_id, thread_id)
        if entry is None:
            return False
        current = entry.record.last_read_at
        if current is None or _as_utc(now) > _as_utc(current):
            entry.record = replace(entry.record, last_read_at=now)
        return True

    def mark_outbound_read(self, *, tenant_id: UUID, thread_id: UUID, up_to: datetime) -> int:
        entry = self._visible(tenant_id, thread_id)
        if entry is None:
            return 0
        changed = 0
        for i, m in enumerate(entry.messages):
            if (
                m.direction == "outbound"
                and m.delivery_status != "read"
                and _as_utc(m.posted_at or m.ingested_at) <= _as_utc(up_to)
            ):
                entry.messages[i] = replace(m, delivery_status="read")
                changed += 1
        return changed

    def save_profile(
        self, *, tenant_id: UUID, thread_id: UUID, profile: RemoteProfile, now: datetime
    ) -> None:
        entry = self._visible(tenant_id, thread_id)
        if entry is None:
            return
        rec = entry.record
        entry.record = replace(
            rec,
            counterpart_name=profile.name or rec.counterpart_name,
            counterpart_username=profile.username or rec.counterpart_username,
            counterpart_avatar_url=profile.avatar_url or rec.counterpart_avatar_url,
            counterpart_profile_at=now,
        )

    def hide_message(
        self, *, tenant_id: UUID, thread_id: UUID, message_id: UUID, now: datetime
    ) -> bool:
        entry = self._visible(tenant_id, thread_id)
        if entry is None:
            return False
        before = len(entry.messages)
        entry.messages = [m for m in entry.messages if m.id != message_id]
        return len(entry.messages) < before

    # -- sync state -----------------------------------------------------------------

    def get_sync_state(
        self, *, tenant_id: UUID, connection_id: UUID, channel: str
    ) -> SyncStateRecord | None:
        state = self.sync_states.get((connection_id, channel))
        if state is None or self._tenant_of.get(connection_id) != tenant_id:
            return None
        return state

    def save_access(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        verdict: AccessVerdict,
        now: datetime,
    ) -> None:
        state = self._state(tenant_id, connection_id, channel)
        self.sync_states[(connection_id, channel)] = replace(
            state,
            access_status=verdict.status.value,
            access_detail=verdict.detail,
            access_checked_at=now,
        )

    def sync_started(
        self, *, tenant_id: UUID, connection_id: UUID, channel: str, now: datetime
    ) -> None:
        state = self._state(tenant_id, connection_id, channel)
        self.sync_states[(connection_id, channel)] = replace(state, last_sync_started_at=now)

    def sync_finished(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        now: datetime,
        status: str,
        error: str | None,
        cursor: str | None,
    ) -> None:
        if status not in (SYNC_OK, SYNC_PARTIAL, SYNC_FAILED):
            raise ValueError(f"unknown sync status {status!r}")
        state = self._state(tenant_id, connection_id, channel)
        self.sync_states[(connection_id, channel)] = replace(
            state,
            last_sync_finished_at=now,
            last_sync_status=status,
            last_sync_error=error,
            sync_cursor=cursor,
        )

    # -- internals ----------------------------------------------------------------------

    def _state(self, tenant_id: UUID, connection_id: UUID, channel: str) -> SyncStateRecord:
        self._tenant_of[connection_id] = tenant_id
        return self.sync_states.get((connection_id, channel)) or SyncStateRecord(
            connection_id=connection_id,
            channel=channel,
            access_status="unknown",
            access_detail=None,
            access_checked_at=None,
            sync_cursor=None,
            last_sync_started_at=None,
            last_sync_finished_at=None,
            last_sync_status=None,
            last_sync_error=None,
        )

    def _visible(self, tenant_id: UUID, thread_id: UUID) -> _MemoryThread | None:
        entry = self._threads.get(thread_id)
        if entry is None or entry.record.tenant_id != tenant_id:
            return None
        return entry

    @staticmethod
    def _with_outbound(entry: _MemoryThread) -> ThreadRecord:
        outbound = [
            _as_utc(m.posted_at or m.ingested_at)
            for m in entry.messages
            if m.direction == "outbound"
        ]
        return replace(entry.record, last_outbound_at=max(outbound) if outbound else None)
