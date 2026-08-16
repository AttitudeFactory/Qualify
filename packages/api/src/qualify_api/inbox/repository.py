"""Persistence for the inbox: the monitored-media toggle and idempotent comment storage,
in one file by deliberate choice — same precedent `connections/repository.py` sets by
persisting multiple related entities (`SocialConnection`, `OAuthCredential`,
`ConnectionEvent`, `PlatformApp`) in a single module per domain. Split into two files if
this one grows unwieldy; not before.

Two invariants live here, both database-owned, both merely TRANSLATED by this code:

**Monitoring is a toggle, never a second row.** `uq_monitored_media_natural_key
(connection_id, external_media_id)` — `set_media_monitored` is a get-or-create-then-UPDATE,
the same "reconnect = UPDATE" discipline `connections/repository.py` already uses for
`social_connections`.

**A comment is stored once.** `uq_message_external_id (connection_id, external_message_id)`
— `upsert_comment` returns `False` on a duplicate rather than raising; the sync service
(B2) uses that boolean to know what's actually new, and running it twice on the same page
must be silently correct, not merely non-crashing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.social.ig_shapes import SHAPE_VERSION, IGComment
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.models import Message, MonitoredMedia, Thread

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
    ) -> bool: ...


class MemoryInboxRepository:
    """In-memory implementation mirroring the two database-owned invariants above.
    Lives in production code for the same reason `MemoryPublishAttemptRepository` does:
    the offline suite and the in-process dev path both need it, and two copies would
    drift."""

    def __init__(self) -> None:
        self._monitored: dict[tuple[UUID, str], bool] = {}
        self._threads: dict[tuple[UUID, str], UUID] = {}  # (connection_id, media_id) -> thread_id
        self._messages: set[tuple[UUID, str]] = set()  # (connection_id, external_message_id)

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
            return False
        self._messages.add(key)
        return True


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
            return False
