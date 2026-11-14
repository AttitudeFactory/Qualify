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
  reopens a closed thread (the WhatsApp rule, `whatsapp/repository.py`). An outbound
  (sent or echoed) never reopens, nor does a replay of an inbound already stored.
- `close_if_unseen` / `set_status` (m-25026457, «Cerrar» / «Reabrir» on Instagram):
  bounded by the thread's channel; setting the status a thread already has is a no-op.
  Closing is a compare-and-set on the `last_inbound_at` the owner saw; only a message
  `store_message` actually inserted reopens a closed chat, never a duplicate.

`last_inbound_at` is the base of the 24 h window (0004's B2 condition) and is bumped
ONLY from inbound messages; `last_message_at` is inbox ordering only.

`last_outbound_at` on `ThreadRecord` is computed at read time from `messages` — the
«pendiente / leído / respondido» state (`service.attention_state`) is derived, never
stored, so it cannot drift.

## Unsent messages (m-25018661, 0157)

`unsend_message` erases one unsent inbound DM in one transaction: tombstone in
`message_unsends`, the row redacted in place (`unsent_at`, hidden by `deleted_at`), its
`proposed` drafts discarded, the thread's instants recomputed from what remains.
`insert_message` refuses a tombstoned `mid` under the same per-message advisory lock, so
neither the poll nor a late webhook brings it back. `list_threads` leaves out a thread whose
every message was unsent.

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
from qualify_api.conversations.contracts import (
    STORY_MENTION_ATTACHMENT_BASIS,
    STORY_MENTION_GRAPH,
    STORY_MENTION_HEURISTIC,
    AccessVerdict,
    RemoteMessage,
    RemoteProfile,
)
from qualify_api.inbox.awaiting import (
    MessageFact,
    ThreadSnapshot,
    awaiting_reply_sql,
    awaits_reply,
)

THREAD_OPEN = "open"
THREAD_CLOSED = "closed"
# `ck_thread_status` (0004): the same two values on every channel.
THREAD_STATUSES = (THREAD_OPEN, THREAD_CLOSED)
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
    # fetched it. `counterpart_profile_at` is when the next lookup is due from: the last
    # lookup's instant, or one back-dated so a nameless thread is retried sooner than the
    # 24 h TTL (m-25017852, `sync.NAMELESS_RETRY_AFTER`).
    counterpart_name: str | None = None
    counterpart_username: str | None = None
    counterpart_avatar_url: str | None = None
    counterpart_profile_at: datetime | None = None
    # m-25017859: the «Por responder» rule's verdict (`inbox.awaiting`), set by the list
    # reads only; `None` where it was not computed (a single-thread read).
    awaiting_reply: bool | None = None


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
    # 0156 (m-25017817): the inbound DM is a mention of the account in the person's OWN
    # story — never also a story reply. `story_mention_basis`: `graph` / `attachment`
    # (confirmed) or `heuristic` (a bare `reply_to.story`, inferred). The id/URL are the
    # mentioner's story; the URL expires with it (24 h).
    story_mention: bool = False
    story_mention_id: str | None = None
    story_mention_url: str | None = None
    story_mention_basis: str | None = None
    ad_promotion_id: UUID | None = None
    ad_origin_label: str | None = None
    ad_origin_at: datetime | None = None

    @property
    def choice_label(self) -> str | None:
        """Where a tapped message came from, for the thread («Pregunta inicial: Precio»,
        «Respuesta rápida: Sí», «Botón: Ver catálogo»); `None` for a typed one."""
        return choice_label(self.choice_kind, self.choice_payload, self.text)


STORE_CREATED = "created"
STORE_DUPLICATE = "duplicate"
STORE_UNSENT = "unsent"


@dataclass(frozen=True)
class StoreResult:
    """`store_message`'s outcome. `thread_id` is None only for `STORE_UNSENT`, which
    touched nothing — no thread created, no instant moved."""

    outcome: str  # STORE_CREATED | STORE_DUPLICATE | STORE_UNSENT
    thread_id: UUID | None
    thread_created: bool = False


@dataclass(frozen=True)
class UnsendResult:
    """What erasing one unsent message did (m-25018661). Ids and counts only."""

    tombstone_created: bool  # False = this `mid` was already unsent (a redelivery)
    message_redacted: bool  # a stored inbound row was erased by THIS call
    outbound: bool  # the `mid` is a message the account sent: nothing was touched
    thread_id: UUID | None  # the thread recomputed, when a row was found
    drafts_discarded: int = 0


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

    def store_message(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
        external_conversation_id: str | None,
        message: RemoteMessage,
        at: datetime | None,
    ) -> StoreResult: ...

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
        status: str | None = None,
    ) -> list[ThreadRecord]: ...

    def set_status(
        self, *, tenant_id: UUID, thread_id: UUID, channel: str, status: str
    ) -> bool: ...

    def close_if_unseen(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        channel: str,
        seen_last_inbound_at: datetime | None,
    ) -> bool: ...

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRecord | None: ...

    def get_listed_thread(
        self, *, tenant_id: UUID, thread_id: UUID, channel: str
    ) -> ThreadRecord | None:
        """m-25017859: one thread of `channel` as `list_threads` would return it (with
        `awaiting_reply`), or None when it is another tenant's, another channel's, or a
        thread the lists hide (every message unsent)."""
        ...

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

    def unsent_ids(
        self, *, tenant_id: UUID, connection_id: UUID, external_message_ids: Sequence[str]
    ) -> set[str]: ...

    def unsend_message(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_message_id: str,
        now: datetime,
        source_event_id: UUID | None,
        pipeline_version: str,
    ) -> UnsendResult: ...

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


def _coalesce(value: str | None, stored: str | None) -> str | None:
    return stored if value is None else value


def _check_thread_status(status: str | None) -> None:
    if status is not None and status not in THREAD_STATUSES:
        raise ValueError(f"thread status {status!r} is not one of {THREAD_STATUSES}")


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
# - the story kind (m-25017817, 0156), mention vs reply, settled by strength:
#   * CM — a confirmed mention arrives (`graph` or `attachment`): the row becomes a
#     mention, any story reply on it moves out (a legacy row stored before 0156 gives its
#     story id/URL to the mention), a `graph` basis is never lowered to `attachment`;
#   * HM — a heuristic mention arrives: it flags only a row with no story kind at all;
#   * RD — the Message node says `reply_to` (`:story_reply_confirmed`) on a row that is
#     only a heuristic mention: it becomes that story reply (the only downgrade, and only
#     of an inference);
#   * RF — the 0075 fill above, never onto a mention.
#   A confirmed kind is never replaced by a weaker reading; id / URL are fill-only.
# - the author's handle (m-25017852): the webhook carries only the sender's id, so a row it
#   stored first has `author_username` NULL; the poll's reading (`from.username`) fills it.
# A pair already stored is never replaced, nothing else is ever rewritten, and `created`
# is only true for a real insert.
_CM = "EXCLUDED.story_mention_basis IN ('graph', 'attachment')"
_HM = (
    "(EXCLUDED.story_mention_basis = 'heuristic' AND NOT messages.story_mention"
    " AND messages.story_reply_id IS NULL)"
)
_RD = (
    "(CAST(:story_reply_confirmed AS boolean) AND EXCLUDED.story_reply_id IS NOT NULL"
    " AND messages.story_mention_basis = 'heuristic')"
)
_RF = (
    "(messages.story_reply_id IS NULL AND EXCLUDED.story_reply_id IS NOT NULL"
    " AND NOT messages.story_mention)"
)
_CM_CHANGES = f"""({_CM} AND (NOT messages.story_mention
       OR messages.story_reply_id IS NOT NULL
       OR messages.story_mention_basis = 'heuristic'
       OR (messages.story_mention_basis <> 'graph'
           AND EXCLUDED.story_mention_basis = 'graph')
       OR (messages.story_mention_id IS NULL AND EXCLUDED.story_mention_id IS NOT NULL)
       OR (messages.story_mention_url IS NULL AND EXCLUDED.story_mention_url IS NOT NULL)))"""
_INSERT_MESSAGE = text(
    f"""
    INSERT INTO messages (id, tenant_id, thread_id, connection_id, external_message_id,
                          direction, author_external_id, author_username, text, posted_at,
                          shape_version, media_type, media_url, story_reply_id,
                          story_reply_url, choice_kind, choice_payload, story_mention,
                          story_mention_id, story_mention_url, story_mention_basis)
    VALUES (:id, :tenant_id, :thread_id, :connection_id, :external_message_id, :direction,
            :author_external_id, :author_username, :text, :posted_at, :shape_version,
            :media_type, :media_url, :story_reply_id, :story_reply_url, :choice_kind,
            :choice_payload, :story_mention, :story_mention_id, :story_mention_url,
            :story_mention_basis)
    ON CONFLICT (connection_id, external_message_id) DO UPDATE
       SET story_reply_id = CASE WHEN {_CM} THEN NULL
                                 WHEN {_RD} OR {_RF} THEN EXCLUDED.story_reply_id
                                 ELSE messages.story_reply_id END,
           story_reply_url = CASE WHEN {_CM} THEN NULL
                                  WHEN {_RD} OR {_RF} THEN EXCLUDED.story_reply_url
                                  ELSE messages.story_reply_url END,
           author_username = COALESCE(messages.author_username, EXCLUDED.author_username),
           choice_kind = COALESCE(messages.choice_kind, EXCLUDED.choice_kind),
           choice_payload = CASE WHEN messages.choice_kind IS NULL
                                 THEN EXCLUDED.choice_payload
                                 ELSE messages.choice_payload END,
           story_mention = CASE WHEN {_CM} OR {_HM} THEN true
                                WHEN {_RD} THEN false
                                ELSE messages.story_mention END,
           story_mention_basis = CASE
               WHEN {_CM} THEN CASE WHEN messages.story_mention_basis = 'graph'
                                    THEN 'graph' ELSE EXCLUDED.story_mention_basis END
               WHEN {_HM} THEN 'heuristic'
               WHEN {_RD} THEN NULL
               ELSE messages.story_mention_basis END,
           story_mention_id = CASE
               WHEN {_CM} THEN COALESCE(messages.story_mention_id,
                                        EXCLUDED.story_mention_id, messages.story_reply_id)
               WHEN {_HM} THEN EXCLUDED.story_mention_id
               WHEN {_RD} THEN NULL
               ELSE messages.story_mention_id END,
           story_mention_url = CASE
               WHEN {_CM} THEN COALESCE(messages.story_mention_url,
                                        EXCLUDED.story_mention_url, messages.story_reply_url)
               WHEN {_HM} THEN EXCLUDED.story_mention_url
               WHEN {_RD} THEN NULL
               ELSE messages.story_mention_url END
     WHERE messages.direction = 'inbound'
       AND ({_RF}
            OR (messages.choice_kind IS NULL AND EXCLUDED.choice_kind IS NOT NULL)
            OR (messages.author_username IS NULL AND EXCLUDED.author_username IS NOT NULL)
            OR {_CM_CHANGES} OR {_HM} OR {_RD})
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
# `:reopen` (m-25026457) is false when `store_message` found the `mid` already stored: a
# duplicate never reopens a closed chat, even when it carries a LATER instant than the
# stored copy (the poll keeps Graph's whole seconds, the webhook brings milliseconds).
_BUMP_THREAD = text(
    """
    UPDATE threads
       SET last_inbound_at = GREATEST(last_inbound_at, CAST(:inbound AS timestamptz)),
           last_message_at = GREATEST(last_message_at, CAST(:message_at AS timestamptz)),
           status = CASE
                        WHEN CAST(:reopen AS boolean)
                         AND CAST(:inbound AS timestamptz) IS NOT NULL
                         AND (last_inbound_at IS NULL
                              OR CAST(:inbound AS timestamptz) > last_inbound_at)
                        THEN :open
                        ELSE status
                    END
     WHERE id = :thread_id
    """
)

# --- Unsent messages (m-25018661, 0157) ------------------------------------------------
#
# One advisory lock per `(connection, mid)`, taken by the insert AND by the unsend in their
# own transactions: whichever commits first, the other sees it. Without it an unsend could
# commit between the insert's tombstone check and its INSERT (poll and webhook run in
# different processes), and the message would be stored with its text after the unsend.
_LOCK_MESSAGE_KEY = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")

_IS_UNSENT = text(
    """
    SELECT 1 FROM message_unsends
     WHERE connection_id = :connection_id AND external_message_id = :mid
    """
)

_UNSENT_IDS = text(
    """
    SELECT external_message_id FROM message_unsends
     WHERE connection_id = :connection_id AND external_message_id IN :mids
    """
).bindparams(bindparam("mids", expanding=True))

_FIND_FOR_UNSEND = text(
    """
    SELECT id, thread_id, direction, unsent_at FROM messages
     WHERE connection_id = :connection_id AND external_message_id = :mid
       FOR UPDATE
    """
)

_INSERT_UNSEND = text(
    """
    INSERT INTO message_unsends (tenant_id, connection_id, external_message_id, unsent_at,
                                 source_event_id, pipeline_version)
    VALUES (:tenant_id, :connection_id, :mid, :now, :source_event_id, :pipeline_version)
    ON CONFLICT (connection_id, external_message_id) DO NOTHING
    RETURNING id
    """
)

# Every column that carries what the person wrote or sent goes; ids and instants stay
# (`ck_message_unsent_redacted` in 0157 enforces it). `deleted_at` hides the row from every
# listing that already hides «Eliminar para mí».
_REDACT_MESSAGE = text(
    """
    UPDATE messages
       SET text = NULL, author_username = NULL, media_type = NULL, media_url = NULL,
           media_object_key = NULL, media_id = NULL, media_mime = NULL,
           raw_payload_r2_key = NULL, story_reply_id = NULL, story_reply_url = NULL,
           story_mention = false, story_mention_id = NULL, story_mention_url = NULL,
           story_mention_basis = NULL, choice_kind = NULL, choice_payload = NULL,
           deleted_at = COALESCE(deleted_at, CAST(:now AS timestamptz)),
           unsent_at = CAST(:now AS timestamptz)
     WHERE id = :message_id AND direction = 'inbound' AND unsent_at IS NULL
    """
)

# A suggested reply nobody decided yet answers a message that no longer exists: it is
# discarded and its text erased (it was written from the unsent message), and so is the
# tapped option its grounding carries (`suggest.py`, `choice`), like the row's `choice_*`.
# A draft a person already accepted, edited or sent is the business's own message.
_DISCARD_DRAFTS = text(
    """
    UPDATE conversation_drafts
       SET status = 'discarded', generated_text = '', final_text = NULL,
           grounding = grounding - 'choice',
           decided_at = CAST(:now AS timestamptz)
     WHERE message_id = :message_id AND status = 'proposed'
    """
)

# The thread's instants from what remains. Unlike `_BUMP_THREAD` this may move them
# BACKWARDS (or to NULL): the unsent message no longer opens the 24 h window nor orders the
# inbox. `status` is left alone (a person's choice): an unsend neither closes nor reopens a
# chat (m-25026457). A closed chat whose `last_inbound_at` moved back stays closed, and a
# later `close_if_unseen` compares the screen's instant against the recomputed value.
_RECOMPUTE_THREAD = text(
    """
    UPDATE threads
       SET last_inbound_at = (SELECT max(COALESCE(m.posted_at, m.ingested_at)) FROM messages m
                               WHERE m.thread_id = :thread_id AND m.direction = 'inbound'
                                 AND m.unsent_at IS NULL),
           last_message_at = (SELECT max(COALESCE(m.posted_at, m.ingested_at)) FROM messages m
                               WHERE m.thread_id = :thread_id AND m.unsent_at IS NULL)
     WHERE id = :thread_id
    """
)


_LOCK_THREAD = text("SELECT 1 FROM threads WHERE id = :thread_id FOR NO KEY UPDATE")


def _message_lock_key(connection_id: UUID, external_message_id: str) -> str:
    return f"qualify:message:{connection_id}:{external_message_id}"


_THREAD_COLUMNS = """
    t.id, t.tenant_id, t.connection_id, t.channel, t.external_thread_id,
    t.external_conversation_id, t.status, t.assigned_agent_id, t.last_message_at,
    t.last_inbound_at, t.last_read_at, t.created_at, t.counterpart_name,
    t.counterpart_username, t.counterpart_avatar_url, t.counterpart_profile_at,
    (SELECT max(COALESCE(m.posted_at, m.ingested_at)) FROM messages m
      WHERE m.thread_id = t.id AND m.direction = 'outbound') AS last_outbound_at
"""

# A thread whose every message was unsent (m-25018661) is not listed: nothing of it is left
# to show. A thread with no messages at all (e.g. created by an Ice Breaker setup) still is.
# `NOT_ONLY_UNSENT_SQL` is the boolean over the `threads` row aliased `t`; the unified
# inbox (`inbox.unified`) filters with this SAME text, so it never lists or counts a chat
# this screen hides (m-25017859).
NOT_ONLY_UNSENT_SQL = """(NOT EXISTS (SELECT 1 FROM messages u
                         WHERE u.thread_id = t.id AND u.unsent_at IS NOT NULL)
            OR EXISTS (SELECT 1 FROM messages v
                        WHERE v.thread_id = t.id AND v.unsent_at IS NULL))"""
_NOT_ONLY_UNSENT = f"""
       AND {NOT_ONLY_UNSENT_SQL}
"""

# `:status` NULL lists both statuses; 'open' / 'closed' only those (m-25026457: «Cerrados»).
_STATUS_FILTER = "AND (CAST(:status AS text) IS NULL OR t.status = CAST(:status AS text))"

# m-25017859: the lists also carry the ONE «Por responder» rule's verdict
# (`inbox.awaiting`, judged at the database's `now()`) — what «Pendientes» must list so it
# matches the menu counter. Only the lists: a single-thread read does not pay for it.
_LIST_THREAD_COLUMNS = f"""{_THREAD_COLUMNS},
    {awaiting_reply_sql("t")} AS awaiting_reply
"""

_LIST_THREADS = text(
    f"""
    SELECT {_LIST_THREAD_COLUMNS}
      FROM threads t
     WHERE t.channel IN :channels
       {_STATUS_FILTER}
       {_NOT_ONLY_UNSENT}
     ORDER BY t.last_message_at DESC NULLS LAST, t.created_at DESC, t.id
     LIMIT :limit
    """
).bindparams(bindparam("channels", expanding=True))

_LIST_THREADS_FOR_CONNECTION = text(
    f"""
    SELECT {_LIST_THREAD_COLUMNS}
      FROM threads t
     WHERE t.channel IN :channels AND t.connection_id = :connection_id
       {_STATUS_FILTER}
       {_NOT_ONLY_UNSENT}
     ORDER BY t.last_message_at DESC NULLS LAST, t.created_at DESC, t.id
     LIMIT :limit
    """
).bindparams(bindparam("channels", expanding=True))

# m-25026457: «Cerrar» / «Reabrir». Bounded by channel like WhatsApp's own `_SET_STATUS`
# (`whatsapp/chats.py`), so this door never moves a thread of another channel; RLS bounds
# the tenant. Nothing else changes: no instant moves and, as on WhatsApp, nothing records
# who closed it.
_SET_STATUS = text(
    "UPDATE threads SET status = :status WHERE id = :thread_id AND channel = :channel"
)

# «Cerrar» as a compare-and-set (m-25026457): closes only if no inbound that would REOPEN
# the chat (`_BUMP_THREAD`: strictly newer than `last_inbound_at`) arrived after the
# instant the owner's screen showed. One statement: under READ COMMITTED an UPDATE that
# waits on a concurrent `store_message` re-evaluates this WHERE against the committed row,
# so bump-then-close refuses and close-then-bump reopens — never closed over an unseen
# inbound. A chat already closed stays closed (idempotent); one with no inbound closes.
_CLOSE_IF_UNSEEN = text(
    """
    UPDATE threads SET status = :closed
     WHERE id = :thread_id AND channel = :channel
       AND (status = :closed
            OR last_inbound_at IS NULL
            OR last_inbound_at <= CAST(:seen AS timestamptz))
    """
)

_GET_THREAD = text(f"SELECT {_THREAD_COLUMNS} FROM threads t WHERE t.id = :thread_id")

# m-25017859: ONE thread exactly as the lists show it — the same columns (the rule's
# `awaiting_reply` included) and the same visibility (`_NOT_ONLY_UNSENT`), so a chat
# opened from the unified list beyond the newest 200 reads like a listed one.
_GET_LISTED_THREAD = text(
    f"""
    SELECT {_LIST_THREAD_COLUMNS}
      FROM threads t
     WHERE t.id = :thread_id AND t.channel = :channel
       {_NOT_ONLY_UNSENT}
    """
)

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
           choice_payload, story_mention, story_mention_id, story_mention_url,
           story_mention_basis
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


def _insert_params(
    tenant_id: UUID, thread_id: UUID, connection_id: UUID, message: RemoteMessage
) -> dict[str, object]:
    return {
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
        "story_mention": message.story_mention,
        "story_mention_id": message.story_mention_id,
        "story_mention_url": message.story_mention_url,
        "story_mention_basis": message.story_mention_basis,
        "story_reply_confirmed": message.story_reply_confirmed,
    }


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
        awaiting_reply=(
            bool(r.awaiting_reply)  # type: ignore[attr-defined]
            if "awaiting_reply" in r._fields  # type: ignore[attr-defined]
            else None
        ),
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
            # m-25018661: an unsent `mid` is never stored again, whichever path brings it.
            session.execute(
                _LOCK_MESSAGE_KEY,
                {"key": _message_lock_key(connection_id, message.external_message_id)},
            )
            if (
                session.execute(
                    _IS_UNSENT,
                    {"connection_id": connection_id, "mid": message.external_message_id},
                ).first()
                is not None
            ):
                return False
            result = session.execute(
                _INSERT_MESSAGE, _insert_params(tenant_id, thread_id, connection_id, message)
            ).first()
            return bool(result is not None and result.created)

    def store_message(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
        external_conversation_id: str | None,
        message: RemoteMessage,
        at: datetime | None,
    ) -> StoreResult:
        """Thread upsert + insert + activity bump of ONE message, in one transaction under
        the message's advisory lock (m-25018661). An `unsend_message` of the same `mid`
        takes that lock too, so it commits either wholly before (this refuses: no thread,
        no bump) or wholly after (its recompute is absolute and runs on a locked thread
        row). No ordering leaves the thread pointing at an unsent message."""
        if not counterpart_external_id:
            raise ValueError("a thread needs the counterpart's external id")
        with tenant_session(tenant_id) as session:
            session.execute(
                _LOCK_MESSAGE_KEY,
                {"key": _message_lock_key(connection_id, message.external_message_id)},
            )
            if (
                session.execute(
                    _IS_UNSENT,
                    {"connection_id": connection_id, "mid": message.external_message_id},
                ).first()
                is not None
            ):
                return StoreResult(outcome=STORE_UNSENT, thread_id=None)
            thread = session.execute(
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
            inserted = session.execute(
                _INSERT_MESSAGE, _insert_params(tenant_id, thread.id, connection_id, message)
            ).first()
            created = bool(inserted is not None and inserted.created)
            session.execute(
                _BUMP_THREAD,
                {
                    "thread_id": thread.id,
                    "inbound": at if message.direction == "inbound" else None,
                    "message_at": at,
                    "open": THREAD_OPEN,
                    # Only a row THIS call inserted may reopen a closed chat (m-25026457).
                    "reopen": created,
                },
            )
        return StoreResult(
            outcome=STORE_CREATED if created else STORE_DUPLICATE,
            thread_id=thread.id,
            thread_created=bool(thread.created),
        )

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
                    "reopen": True,
                },
            )

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        channels: Sequence[str],
        connection_id: UUID | None = None,
        limit: int = 50,
        status: str | None = None,
    ) -> list[ThreadRecord]:
        _check_thread_status(status)
        if not channels:
            return []
        params: dict[str, object] = {"channels": list(channels), "limit": limit, "status": status}
        statement = _LIST_THREADS
        if connection_id is not None:
            statement = _LIST_THREADS_FOR_CONNECTION
            params["connection_id"] = connection_id
        with tenant_session(tenant_id) as session:
            rows = session.execute(statement, params).all()
        return [_thread_record(row) for row in rows]

    def set_status(self, *, tenant_id: UUID, thread_id: UUID, channel: str, status: str) -> bool:
        """True if a thread of this tenant and channel matched, whatever its status was."""
        _check_thread_status(status)
        with tenant_session(tenant_id) as session:
            result = session.execute(
                _SET_STATUS, {"thread_id": thread_id, "channel": channel, "status": status}
            )
        return bool(result.rowcount)

    def close_if_unseen(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        channel: str,
        seen_last_inbound_at: datetime | None,
    ) -> bool:
        """Close unless an inbound newer than `seen_last_inbound_at` is stored. False when
        refused OR when no thread of this tenant and channel matched (the caller tells
        the two apart by reading the thread)."""
        with tenant_session(tenant_id) as session:
            result = session.execute(
                _CLOSE_IF_UNSEEN,
                {
                    "thread_id": thread_id,
                    "channel": channel,
                    "closed": THREAD_CLOSED,
                    "seen": seen_last_inbound_at,
                },
            )
        return bool(result.rowcount)

    def get_listed_thread(
        self, *, tenant_id: UUID, thread_id: UUID, channel: str
    ) -> ThreadRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                _GET_LISTED_THREAD, {"thread_id": thread_id, "channel": channel}
            ).one_or_none()
        return _thread_record(row) if row is not None else None

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
                story_mention=bool(r.story_mention),
                story_mention_id=r.story_mention_id,
                story_mention_url=r.story_mention_url,
                story_mention_basis=r.story_mention_basis,
            )
            for r in rows
        ]
        records.reverse()
        from qualify_api.ads.messaging_attribution import attach_ad_origins

        return attach_ad_origins(tenant_id, records)

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

    def unsent_ids(
        self, *, tenant_id: UUID, connection_id: UUID, external_message_ids: Sequence[str]
    ) -> set[str]:
        if not external_message_ids:
            return set()
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                _UNSENT_IDS,
                {"connection_id": connection_id, "mids": list(external_message_ids)},
            ).all()
        return {row.external_message_id for row in rows}

    def unsend_message(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_message_id: str,
        now: datetime,
        source_event_id: UUID | None,
        pipeline_version: str,
    ) -> UnsendResult:
        """Erase one unsent inbound message, in ONE transaction: the tombstone, the row's
        content, its undecided drafts, the thread's instants. Idempotent: a redelivery
        finds the tombstone and an already redacted row and changes nothing. A `mid` the
        account itself sent is left untouched (no tombstone either)."""
        if not external_message_id:
            raise ValueError("an unsend needs the message's external id")
        params = {"connection_id": connection_id, "mid": external_message_id}
        with tenant_session(tenant_id) as session:
            session.execute(
                _LOCK_MESSAGE_KEY, {"key": _message_lock_key(connection_id, external_message_id)}
            )
            row = session.execute(_FIND_FOR_UNSEND, params).first()
            if row is not None and row.direction != "inbound":
                return UnsendResult(
                    tombstone_created=False,
                    message_redacted=False,
                    outbound=True,
                    thread_id=row.thread_id,
                )
            created = (
                session.execute(
                    _INSERT_UNSEND,
                    {
                        **params,
                        "tenant_id": tenant_id,
                        "now": now,
                        "source_event_id": source_event_id,
                        "pipeline_version": pipeline_version,
                    },
                ).first()
                is not None
            )
            if row is None:
                return UnsendResult(
                    tombstone_created=created,
                    message_redacted=False,
                    outbound=False,
                    thread_id=None,
                )
            redacted = (
                session.execute(_REDACT_MESSAGE, {"message_id": row.id, "now": now}).rowcount == 1
            )
            drafts = 0
            if redacted:
                drafts = session.execute(
                    _DISCARD_DRAFTS, {"message_id": row.id, "now": now}
                ).rowcount
                # Lock the thread FIRST, in its own statement: a concurrent `store_message`
                # of another message that holds the row commits before the recompute takes
                # its snapshot, so its message is counted (READ COMMITTED, per statement).
                session.execute(_LOCK_THREAD, {"thread_id": row.thread_id})
                session.execute(_RECOMPUTE_THREAD, {"thread_id": row.thread_id})
        return UnsendResult(
            tombstone_created=created,
            message_redacted=redacted,
            outbound=False,
            thread_id=row.thread_id,
            drafts_discarded=drafts,
        )

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


def merge_story_kind(stored: MessageRecord, incoming: RemoteMessage) -> MessageRecord:
    """A later reading of an inbound message against its stored row — mention vs story
    reply (m-25017817), the Python twin of `_INSERT_MESSAGE`'s conflict branch."""
    confirmed = incoming.story_mention_basis in (
        STORY_MENTION_GRAPH,
        STORY_MENTION_ATTACHMENT_BASIS,
    )
    if confirmed:
        return replace(
            stored,
            story_mention=True,
            story_mention_basis=(
                STORY_MENTION_GRAPH
                if stored.story_mention_basis == STORY_MENTION_GRAPH
                else incoming.story_mention_basis
            ),
            story_mention_id=stored.story_mention_id
            or incoming.story_mention_id
            or stored.story_reply_id,
            story_mention_url=stored.story_mention_url
            or incoming.story_mention_url
            or stored.story_reply_url,
            story_reply_id=None,
            story_reply_url=None,
        )
    if (
        incoming.story_mention_basis == STORY_MENTION_HEURISTIC
        and not stored.story_mention
        and stored.story_reply_id is None
    ):
        return replace(
            stored,
            story_mention=True,
            story_mention_basis=STORY_MENTION_HEURISTIC,
            story_mention_id=incoming.story_mention_id,
            story_mention_url=incoming.story_mention_url,
        )
    if (
        incoming.story_reply_confirmed
        and incoming.story_reply_id is not None
        and stored.story_mention_basis == STORY_MENTION_HEURISTIC
    ):
        return replace(
            stored,
            story_mention=False,
            story_mention_basis=None,
            story_mention_id=None,
            story_mention_url=None,
            story_reply_id=incoming.story_reply_id,
            story_reply_url=incoming.story_reply_url,
        )
    if (
        stored.story_reply_id is None
        and incoming.story_reply_id is not None
        and not stored.story_mention
    ):
        return replace(
            stored,
            story_reply_id=incoming.story_reply_id,
            story_reply_url=incoming.story_reply_url,
        )
    return stored


@dataclass
class _MemoryThread:
    record: ThreadRecord
    messages: list[MessageRecord] = field(default_factory=list)


def _memory_awaits(entry: _MemoryThread, now: datetime) -> bool:
    """The list's `awaiting_reply` in memory: the rule's twin over the stored messages
    (no outbox here, so every outbound is a person's reply)."""
    record = entry.record
    return awaits_reply(
        ThreadSnapshot(
            status=record.status,
            channel=record.channel,
            last_inbound_at=record.last_inbound_at,
            messages=tuple(
                MessageFact(m.direction, _as_utc(m.posted_at or m.ingested_at))
                for m in entry.messages
            ),
        ),
        now,
    )


class MemoryConversationRepository:
    """Mirrors every rule above. Threads are keyed by the natural key; messages by
    `(connection_id, external_message_id)`; a tenant only ever sees its own rows."""

    def __init__(self) -> None:
        self._threads: dict[UUID, _MemoryThread] = {}
        self._by_natural_key: dict[tuple[UUID, str, str], UUID] = {}
        self._message_keys: set[tuple[UUID, str]] = set()
        # m-25018661: the tombstones `(connection_id, mid)` with their tenant, and the
        # threads that lost a message to an unsend (listed only while something remains).
        self.unsends: dict[tuple[UUID, str], UUID] = {}
        self._threads_with_unsent: set[UUID] = set()
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
        if self.unsends.get(key) == tenant_id:
            return False
        if key in self._message_keys:
            self._merge_story(entry, message)
            self._fill_choice(entry, message)
            self._fill_author(entry, message)
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
                story_mention=message.story_mention,
                story_mention_id=message.story_mention_id,
                story_mention_url=message.story_mention_url,
                story_mention_basis=message.story_mention_basis,
            )
        )
        return True

    @staticmethod
    def _merge_story(entry: _MemoryThread, message: RemoteMessage) -> None:
        """The Postgres `ON CONFLICT` story rules (`_INSERT_MESSAGE`: CM / HM / RD / RF)."""
        for index, stored in enumerate(entry.messages):
            if (
                stored.external_message_id == message.external_message_id
                and stored.direction == "inbound"
            ):
                entry.messages[index] = merge_story_kind(stored, message)

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

    @staticmethod
    def _fill_author(entry: _MemoryThread, message: RemoteMessage) -> None:
        """The Postgres `ON CONFLICT` author fill (m-25017852): a NULL handle on an inbound
        row takes the one a later reading carries; a stored handle is never replaced."""
        if message.author_username is None:
            return
        for index, stored in enumerate(entry.messages):
            if (
                stored.external_message_id == message.external_message_id
                and stored.author_username is None
                and stored.direction == "inbound"
            ):
                entry.messages[index] = replace(stored, author_username=message.author_username)

    def store_message(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        channel: str,
        counterpart_external_id: str,
        external_conversation_id: str | None,
        message: RemoteMessage,
        at: datetime | None,
    ) -> StoreResult:
        """The Postgres rules (one transaction there; one call here)."""
        if self.unsends.get((connection_id, message.external_message_id)) == tenant_id:
            return StoreResult(outcome=STORE_UNSENT, thread_id=None)
        upsert = self.upsert_thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel=channel,
            counterpart_external_id=counterpart_external_id,
            external_conversation_id=external_conversation_id,
        )
        created = self.insert_message(
            tenant_id=tenant_id,
            thread_id=upsert.thread_id,
            connection_id=connection_id,
            message=message,
        )
        self._bump(
            tenant_id=tenant_id,
            thread_id=upsert.thread_id,
            last_inbound_at=at if message.direction == "inbound" else None,
            last_message_at=at,
            reopen=created,
        )
        return StoreResult(
            outcome=STORE_CREATED if created else STORE_DUPLICATE,
            thread_id=upsert.thread_id,
            thread_created=upsert.created,
        )

    def bump_thread_activity(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        last_inbound_at: datetime | None,
        last_message_at: datetime | None,
    ) -> None:
        self._bump(
            tenant_id=tenant_id,
            thread_id=thread_id,
            last_inbound_at=last_inbound_at,
            last_message_at=last_message_at,
            reopen=True,
        )

    def _bump(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        last_inbound_at: datetime | None,
        last_message_at: datetime | None,
        reopen: bool,
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
                if reopen:
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
        status: str | None = None,
    ) -> list[ThreadRecord]:
        _check_thread_status(status)
        wanted = set(channels)
        now = datetime.now(UTC)
        rows = [
            replace(self._with_outbound(entry), awaiting_reply=_memory_awaits(entry, now))
            for entry in self._threads.values()
            if entry.record.tenant_id == tenant_id
            and entry.record.channel in wanted
            and (connection_id is None or entry.record.connection_id == connection_id)
            and (status is None or entry.record.status == status)
            and (entry.messages or entry.record.id not in self._threads_with_unsent)
        ]
        rows.sort(
            key=lambda r: (
                r.last_message_at is None,
                -(_as_utc(r.last_message_at).timestamp() if r.last_message_at else 0),
                -_as_utc(r.created_at).timestamp(),
            )
        )
        return rows[:limit]

    def get_listed_thread(
        self, *, tenant_id: UUID, thread_id: UUID, channel: str
    ) -> ThreadRecord | None:
        entry = self._visible(tenant_id, thread_id)
        if entry is None or entry.record.channel != channel:
            return None
        if not entry.messages and entry.record.id in self._threads_with_unsent:
            return None
        return replace(
            self._with_outbound(entry),
            awaiting_reply=_memory_awaits(entry, datetime.now(UTC)),
        )

    def set_status(self, *, tenant_id: UUID, thread_id: UUID, channel: str, status: str) -> bool:
        _check_thread_status(status)
        entry = self._visible(tenant_id, thread_id)
        if entry is None or entry.record.channel != channel:
            return False
        entry.record = replace(entry.record, status=status)
        return True

    def close_if_unseen(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        channel: str,
        seen_last_inbound_at: datetime | None,
    ) -> bool:
        entry = self._visible(tenant_id, thread_id)
        if entry is None or entry.record.channel != channel:
            return False
        rec = entry.record
        stored, seen = rec.last_inbound_at, seen_last_inbound_at
        if not (
            rec.status == THREAD_CLOSED
            or stored is None
            or (seen is not None and _as_utc(stored) <= _as_utc(seen))
        ):
            return False
        entry.record = replace(rec, status=THREAD_CLOSED)
        return True

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
            # `COALESCE` twins: only None keeps the stored value (as in `_SAVE_PROFILE`).
            counterpart_name=_coalesce(profile.name, rec.counterpart_name),
            counterpart_username=_coalesce(profile.username, rec.counterpart_username),
            counterpart_avatar_url=_coalesce(profile.avatar_url, rec.counterpart_avatar_url),
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

    def unsent_ids(
        self, *, tenant_id: UUID, connection_id: UUID, external_message_ids: Sequence[str]
    ) -> set[str]:
        return {
            mid
            for mid in external_message_ids
            if self.unsends.get((connection_id, mid)) == tenant_id
        }

    def unsend_message(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_message_id: str,
        now: datetime,
        source_event_id: UUID | None,
        pipeline_version: str,
    ) -> UnsendResult:
        """The Postgres rules, in memory: the unsent row leaves the thread (what Postgres
        redacts and hides), the thread's instants are recomputed from what remains."""
        if not external_message_id:
            raise ValueError("an unsend needs the message's external id")
        key = (connection_id, external_message_id)
        found: tuple[_MemoryThread, MessageRecord] | None = None
        for entry in self._threads.values():
            if entry.record.tenant_id != tenant_id or entry.record.connection_id != connection_id:
                continue
            for message in entry.messages:
                if message.external_message_id == external_message_id:
                    found = (entry, message)
        if found is not None and found[1].direction != "inbound":
            return UnsendResult(
                tombstone_created=False,
                message_redacted=False,
                outbound=True,
                thread_id=found[0].record.id,
            )
        created = key not in self.unsends
        if created:
            self.unsends[key] = tenant_id
        if found is None:
            return UnsendResult(
                tombstone_created=created, message_redacted=False, outbound=False, thread_id=None
            )
        entry, message = found
        entry.messages = [m for m in entry.messages if m.id != message.id]
        self._threads_with_unsent.add(entry.record.id)
        inbound = [
            _as_utc(m.posted_at or m.ingested_at)
            for m in entry.messages
            if m.direction == "inbound"
        ]
        every = [_as_utc(m.posted_at or m.ingested_at) for m in entry.messages]
        entry.record = replace(
            entry.record,
            last_inbound_at=max(inbound) if inbound else None,
            last_message_at=max(every) if every else None,
        )
        return UnsendResult(
            tombstone_created=created,
            message_redacted=True,
            outbound=False,
            thread_id=entry.record.id,
        )

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
