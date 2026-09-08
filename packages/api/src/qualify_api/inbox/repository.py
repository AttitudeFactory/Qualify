"""Persistence for the inbox: the monitored-media toggle, idempotent comment storage, and
the Meta call ledger (QUA-88), in one file by deliberate choice — same precedent
`connections/repository.py` sets by persisting multiple related entities
(`SocialConnection`, `OAuthCredential`, `ConnectionEvent`, `PlatformApp`) in a single
module per domain. Split into two files if this one grows unwieldy; not before.

Four invariants live here, all database-owned, all merely TRANSLATED by this code:

**Monitoring is a toggle, never a second row.** `uq_monitored_media_natural_key
(connection_id, external_media_id)` — `set_media_monitored` is a get-or-create-then-UPDATE,
the same "reconnect = UPDATE" discipline `connections/repository.py` already uses for
`social_connections`.

**A comment is stored once.** `uq_message_external_id (connection_id, external_message_id)`
— `upsert_comment` returns `False` on a duplicate rather than raising; the sync service
(B2) uses that boolean to know what's actually new, and running it twice on the same page
must be silently correct, not merely non-crashing.

**A comment Meta stops returning is soft-deleted, never physically removed (QUA-101).**
`reconcile_media_comments` sets `messages.deleted_at`, the same "flag on the row, not a
deletion" treatment `monitored_media.is_monitored` already gives a desmonitoreado Reel
(migration 0005) — `comment_sentiment_results`/`comment_reply_drafts` (0012/0014) both FK
to `messages.id` and must survive. `upsert_comment` clears the flag if the SAME comment id
reappears — see both methods' docstrings for why a partial comment-page walk must never
call `reconcile_media_comments`.

**A Meta call, once made, is a permanent fact.** `calls_in_last_hour`/`record_call`
(QUA-88) are append-only — see `InboxMetaCallLog`'s docstring and migration `0010`.
Both `PostgresInboxRepository`'s and `MemoryInboxRepository`'s halves are real production
code (same reasoning as everything else in this class); the former is exercised by
`db`-marked tests, the latter by the offline suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.social.ig_shapes import SHAPE_VERSION, IGComment
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.models import InboxMetaCallLog, Message, MonitoredMedia, Thread

_COMMENT_CHANNEL = "comment"


class InboxRepository(Protocol):
    def list_monitored_media_ids(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> frozenset[str]: ...

    def set_media_monitored(
        self, *, tenant_id: UUID, connection_id: UUID, external_media_id: str, monitored: bool
    ) -> None: ...

    def upsert_comment(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_media_id: str,
        comment: IGComment,
    ) -> bool:
        """Inserts a new comment, or, on a duplicate `external_message_id`, restores it
        (QUA-101) if it had been soft-deleted (`reconcile_media_comments`) — Meta showing
        it again means it was never truly gone. Returns `True` only for a genuine
        insert; a duplicate (restored or not) returns `False`, same semantics as before
        this fix."""
        ...

    def reconcile_media_comments(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_media_id: str,
        current_external_ids: frozenset[str],
    ) -> int:
        """QUA-101: soft-deletes (`messages.deleted_at`) every stored inbound comment for
        this media whose `external_message_id` is NOT in `current_external_ids`, and
        restores (clears `deleted_at`) any already-soft-deleted comment that IS in it.
        Never a physical DELETE — `comment_sentiment_results`/`comment_reply_drafts`
        (0012/0014) both FK to `messages.id` and must survive a comment's disappearance
        on Instagram exactly as they survive a Reel being desmonitoreado (0005's
        "orthogonal facts" ruling, one level down). Callers MUST only call this after a
        COMPLETE walk of the media's comments (Meta's own cursor exhausted, no
        `CommentsReadError`, not the missing-media path) — a partial walk cannot prove a
        comment absent; see `InboxService.sync_comments`. Returns how many were newly
        marked deleted (a restore does not count)."""
        ...

    def calls_in_last_hour(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int:
        """How many Meta calls this connection has logged in the hour ending at `now` —
        a true sliding window (`called_at > now - 1h`), not a calendar-hour bucket."""
        ...

    def record_call(self, *, tenant_id: UUID, connection_id: UUID, called_at: datetime) -> None:
        """Log one real Meta call. Called immediately BEFORE the call it accounts for,
        never after — a call that Meta counted against the quota but that failed on our
        side must still be counted."""
        ...


class MemoryInboxRepository:
    """In-memory implementation mirroring the two database-owned invariants above.
    Lives in production code for the same reason `MemoryPublishAttemptRepository` does:
    the offline suite and the in-process dev path both need it, and two copies would
    drift."""

    def __init__(self) -> None:
        self._monitored: dict[tuple[UUID, str], bool] = {}
        self._threads: dict[tuple[UUID, str], UUID] = {}  # (connection_id, media_id) -> thread_id
        self._messages: set[tuple[UUID, str]] = set()  # (connection_id, external_message_id)
        # (connection_id, external_message_id) -> external_media_id — which media a
        # stored comment belongs to, so `reconcile_media_comments` can find "every
        # comment stored for this media" the way the Postgres side does via `Thread`.
        self._comment_media: dict[tuple[UUID, str], str] = {}
        # (connection_id, external_message_id) currently soft-deleted (QUA-101) —
        # mirrors `messages.deleted_at IS NOT NULL` without a database.
        self._deleted: set[tuple[UUID, str]] = set()
        self._calls: list[tuple[UUID, datetime]] = []  # (connection_id, called_at)

    def list_monitored_media_ids(self, *, tenant_id: UUID, connection_id: UUID) -> frozenset[str]:
        return frozenset(
            media_id
            for (conn_id, media_id), monitored in self._monitored.items()
            if conn_id == connection_id and monitored
        )

    def set_media_monitored(
        self, *, tenant_id: UUID, connection_id: UUID, external_media_id: str, monitored: bool
    ) -> None:
        self._monitored[(connection_id, external_media_id)] = monitored

    def upsert_comment(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_media_id: str,
        comment: IGComment,
    ) -> bool:
        self._threads.setdefault((connection_id, external_media_id), UUID(int=0))
        key = (connection_id, comment.id)
        if key in self._messages:
            # QUA-101: reappeared — if it had been soft-deleted, restore it.
            self._deleted.discard(key)
            return False
        self._messages.add(key)
        self._comment_media[key] = external_media_id
        return True

    def reconcile_media_comments(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_media_id: str,
        current_external_ids: frozenset[str],
    ) -> int:
        newly_deleted = 0
        for (conn_id, comment_id), media_id in self._comment_media.items():
            if conn_id != connection_id or media_id != external_media_id:
                continue
            key = (conn_id, comment_id)
            if comment_id in current_external_ids:
                self._deleted.discard(key)
            elif key not in self._deleted:
                self._deleted.add(key)
                newly_deleted += 1
        return newly_deleted

    def is_comment_deleted(self, *, connection_id: UUID, external_message_id: str) -> bool:
        """Test-only introspection mirroring a `SELECT deleted_at FROM messages ...`
        against the real table — `InboxRepository`'s protocol has no read methods
        (`sentiment/repository.py` owns every read path), so tests exercising
        `InboxService.sync_comments` against this fake need a way to assert the
        outcome directly."""
        return (connection_id, external_message_id) in self._deleted

    def calls_in_last_hour(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int:
        window_start = now - timedelta(hours=1)
        return sum(
            1
            for conn_id, called_at in self._calls
            if conn_id == connection_id and called_at > window_start
        )

    def record_call(self, *, tenant_id: UUID, connection_id: UUID, called_at: datetime) -> None:
        self._calls.append((connection_id, called_at))


class PostgresInboxRepository:
    """All access through `tenant_session` — RLS scopes every statement, and the
    composite FKs keep a row's tenant agreeing with its connection's."""

    def list_monitored_media_ids(self, *, tenant_id: UUID, connection_id: UUID) -> frozenset[str]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(MonitoredMedia.external_media_id).where(
                    MonitoredMedia.connection_id == connection_id,
                    MonitoredMedia.is_monitored.is_(True),
                )
            ).all()
            return frozenset(rows)

    def set_media_monitored(
        self, *, tenant_id: UUID, connection_id: UUID, external_media_id: str, monitored: bool
    ) -> None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(MonitoredMedia).where(
                    MonitoredMedia.connection_id == connection_id,
                    MonitoredMedia.external_media_id == external_media_id,
                )
            )
            if row is None:
                session.add(
                    MonitoredMedia(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        external_media_id=external_media_id,
                        is_monitored=monitored,
                    )
                )
            else:
                row.is_monitored = monitored
                row.updated_at = datetime.now(UTC)
            session.flush()

    def upsert_comment(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_media_id: str,
        comment: IGComment,
    ) -> bool:
        now = datetime.now(UTC)
        try:
            with tenant_session(tenant_id) as session:
                thread = session.scalar(
                    select(Thread).where(
                        Thread.connection_id == connection_id,
                        Thread.channel == _COMMENT_CHANNEL,
                        Thread.external_thread_id == external_media_id,
                    )
                )
                if thread is None:
                    thread = Thread(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        channel=_COMMENT_CHANNEL,
                        external_thread_id=external_media_id,
                        status="open",
                    )
                    session.add(thread)
                    session.flush()  # need thread.id for the message FK below

                posted_at = comment.timestamp
                session.add(
                    Message(
                        tenant_id=tenant_id,
                        thread_id=thread.id,
                        connection_id=connection_id,
                        external_message_id=comment.id,
                        # Every comment synced today is audience-authored — B4 (assisted
                        # replies) is what would ever write 'outbound', and it does not
                        # exist yet.
                        direction="inbound",
                        author_external_id=comment.from_.id if comment.from_ else None,
                        author_username=comment.username,
                        text=comment.text,
                        posted_at=posted_at,
                        shape_version=SHAPE_VERSION,
                    )
                )
                session.flush()  # trips uq_message_external_id on a duplicate

                # `ingested_at` is always known even when `posted_at` is absent by
                # contract (0004's docstring) — never fabricate a timestamp.
                thread.last_message_at = posted_at or now
                thread.last_inbound_at = posted_at or now
                return True
        except IntegrityError:
            # The comment already exists (uq_message_external_id) or, less likely, a
            # concurrent insert won the thread's natural key. Either way: not new.
            #
            # QUA-101: if the existing row was soft-deleted, Meta returning it again
            # means it was never truly gone (most likely the pagination-shift race
            # `ig_shapes.INCREMENTAL_POLLING_NOTE` documents) — restore it. A fresh
            # `tenant_session`: the one above already rolled back and released its
            # connection on the `IntegrityError` (`Engine.begin()`'s own contract, see
            # `qualify_shared.db.session.tenant_session`'s docstring), so this is a
            # normal second transaction, not a recovery from a broken one.
            with tenant_session(tenant_id) as session:
                existing = session.scalar(
                    select(Message).where(
                        Message.connection_id == connection_id,
                        Message.external_message_id == comment.id,
                    )
                )
                if existing is not None and existing.deleted_at is not None:
                    existing.deleted_at = None
            return False

    def reconcile_media_comments(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_media_id: str,
        current_external_ids: frozenset[str],
    ) -> int:
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            thread = session.scalar(
                select(Thread).where(
                    Thread.connection_id == connection_id,
                    Thread.channel == _COMMENT_CHANNEL,
                    Thread.external_thread_id == external_media_id,
                )
            )
            if thread is None:
                # Nothing was ever synced for this media — nothing to reconcile.
                return 0
            stored = session.scalars(
                select(Message).where(
                    Message.thread_id == thread.id,
                    Message.direction == "inbound",
                )
            ).all()
            newly_deleted = 0
            for message in stored:
                is_present = message.external_message_id in current_external_ids
                if is_present:
                    if message.deleted_at is not None:
                        message.deleted_at = None
                elif message.deleted_at is None:
                    message.deleted_at = now
                    newly_deleted += 1
            return newly_deleted

    def calls_in_last_hour(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int:
        """Backed by migration `0010` (`inbox_meta_call_log`)."""
        window_start = now - timedelta(hours=1)
        with tenant_session(tenant_id) as session:
            count = session.scalar(
                select(func.count())
                .select_from(InboxMetaCallLog)
                .where(
                    InboxMetaCallLog.connection_id == connection_id,
                    InboxMetaCallLog.called_at > window_start,
                )
            )
            return int(count or 0)

    def record_call(self, *, tenant_id: UUID, connection_id: UUID, called_at: datetime) -> None:
        """Backed by migration `0010` — see `calls_in_last_hour`."""
        with tenant_session(tenant_id) as session:
            session.add(
                InboxMetaCallLog(
                    tenant_id=tenant_id, connection_id=connection_id, called_at=called_at
                )
            )
            session.flush()
