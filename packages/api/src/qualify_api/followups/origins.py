"""The origin of a followup, read back (m-24789646): the interaction a person may continue
in private — a comment, or a DM that replied to a story — with what continuing it needs:
its author's IGSID (the key of their DM thread), the comment id (the address of a private
reply) and its creation time (the base of Meta's 7-day limit).

Read-only, through `tenant_session` (RLS), joined to the thread for its channel.
`MemoryOriginReader` is the same contract for the offline suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text


@dataclass(frozen=True)
class OriginMessage:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    thread_id: UUID
    # The thread's channel: `comment` for a comment, `dm` for a story reply.
    channel: str
    # The comment id (a private reply's address) or the DM's `mid`.
    external_message_id: str
    direction: str
    # The author's IGSID — a comment's `from.id`, the key of their DM thread.
    author_external_id: str | None
    author_username: str | None
    text: str | None
    posted_at: datetime | None
    deleted: bool = False


class OriginReader(Protocol):
    def get(self, *, tenant_id: UUID, message_id: UUID) -> OriginMessage | None: ...


class MemoryOriginReader:
    def __init__(self) -> None:
        self.rows: dict[UUID, OriginMessage] = {}

    def add(self, origin: OriginMessage) -> OriginMessage:
        self.rows[origin.id] = origin
        return origin

    def get(self, *, tenant_id: UUID, message_id: UUID) -> OriginMessage | None:
        row = self.rows.get(message_id)
        return row if row is not None and row.tenant_id == tenant_id else None


_GET = text(
    """
    SELECT m.id, m.tenant_id, m.connection_id, m.thread_id, t.channel, m.external_message_id,
           m.direction, m.author_external_id, m.author_username, m.text, m.posted_at,
           m.deleted_at IS NOT NULL AS deleted
      FROM messages m
      JOIN threads t ON t.id = m.thread_id
     WHERE m.id = :message_id
    """
)


class PostgresOriginReader:
    def get(self, *, tenant_id: UUID, message_id: UUID) -> OriginMessage | None:
        with tenant_session(tenant_id) as session:
            r = session.execute(_GET, {"message_id": message_id}).first()
        if r is None:
            return None
        return OriginMessage(
            id=r.id,
            tenant_id=r.tenant_id,
            connection_id=r.connection_id,
            thread_id=r.thread_id,
            channel=r.channel,
            external_message_id=r.external_message_id,
            direction=r.direction,
            author_external_id=r.author_external_id,
            author_username=r.author_username,
            text=r.text,
            posted_at=r.posted_at,
            deleted=bool(r.deleted),
        )
