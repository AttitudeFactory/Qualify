"""The origin of a followup, read back (m-24789646): the interaction a person may continue
in private — a comment, or a DM that replied to a story — with what continuing it needs:
its author's IGSID (the key of their DM thread), the comment id (the address of a private
reply) and its creation time (the base of Meta's 7-day limit). For the card a person
reviews it also carries the post it was written on (caption, link, surface) and the
author's existing DM thread, if any, with its last inbound (the 24 h window) — all in one
query for a whole page of followups.

`CommercialIntentReader` finds the comments a commercial analysis flagged that have no
followup yet: what `FollowupWorkspace.open_from_intents` opens automatically (B1).

Read-only, through `tenant_session` (RLS). The memory classes are the same contracts for
the offline suite.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import bindparam, text

from qualify_api.sentiment.repository import AnalysisVersion


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
    # The post a comment was written on (its comment thread is keyed by the media id).
    media_id: str | None = None
    media_caption: str | None = None
    media_permalink: str | None = None
    media_product_type: str | None = None
    # The author's DM thread when it already exists (a story reply's is its own thread),
    # and its last inbound — the base of the 24 h window.
    dm_thread_id: UUID | None = None
    dm_last_inbound_at: datetime | None = None


class OriginReader(Protocol):
    def get(self, *, tenant_id: UUID, message_id: UUID) -> OriginMessage | None: ...

    def get_many(
        self, *, tenant_id: UUID, message_ids: Iterable[UUID]
    ) -> dict[UUID, OriginMessage]: ...


class MemoryOriginReader:
    def __init__(self) -> None:
        self.rows: dict[UUID, OriginMessage] = {}

    def add(self, origin: OriginMessage) -> OriginMessage:
        self.rows[origin.id] = origin
        return origin

    def get(self, *, tenant_id: UUID, message_id: UUID) -> OriginMessage | None:
        row = self.rows.get(message_id)
        return row if row is not None and row.tenant_id == tenant_id else None

    def get_many(
        self, *, tenant_id: UUID, message_ids: Iterable[UUID]
    ) -> dict[UUID, OriginMessage]:
        found = (self.get(tenant_id=tenant_id, message_id=i) for i in message_ids)
        return {o.id: o for o in found if o is not None}


_SELECT = """
    SELECT m.id, m.tenant_id, m.connection_id, m.thread_id, t.channel, m.external_message_id,
           m.direction, m.author_external_id, m.author_username, m.text, m.posted_at,
           m.deleted_at IS NOT NULL AS deleted,
           CASE WHEN t.channel = 'comment' THEN t.external_thread_id END AS media_id,
           mm.caption AS media_caption, mm.permalink AS media_permalink,
           mm.media_product_type,
           CASE WHEN t.channel = 'dm' THEN t.id ELSE dm.id END AS dm_thread_id,
           CASE WHEN t.channel = 'dm' THEN t.last_inbound_at ELSE dm.last_inbound_at END
               AS dm_last_inbound_at
      FROM messages m
      JOIN threads t ON t.id = m.thread_id
      LEFT JOIN monitored_media mm
        ON t.channel = 'comment'
       AND mm.connection_id = m.connection_id
       AND mm.external_media_id = t.external_thread_id
      LEFT JOIN threads dm
        ON t.channel = 'comment'
       AND dm.connection_id = m.connection_id
       AND dm.channel = 'dm'
       AND dm.external_thread_id = m.author_external_id
"""

_GET = text(_SELECT + " WHERE m.id = :message_id")

_GET_MANY = text(_SELECT + " WHERE m.id IN :ids").bindparams(bindparam("ids", expanding=True))


def _origin(r: Any) -> OriginMessage:
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
        media_id=r.media_id,
        media_caption=r.media_caption,
        media_permalink=r.media_permalink,
        media_product_type=r.media_product_type,
        dm_thread_id=r.dm_thread_id,
        dm_last_inbound_at=r.dm_last_inbound_at,
    )


class PostgresOriginReader:
    def get(self, *, tenant_id: UUID, message_id: UUID) -> OriginMessage | None:
        with tenant_session(tenant_id) as session:
            r = session.execute(_GET, {"message_id": message_id}).first()
        return _origin(r) if r is not None else None

    def get_many(
        self, *, tenant_id: UUID, message_ids: Iterable[UUID]
    ) -> dict[UUID, OriginMessage]:
        ids = list(dict.fromkeys(message_ids))
        if not ids:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(_GET_MANY, {"ids": ids}).all()
        return {r.id: _origin(r) for r in rows}


# --- commercial comments without a followup ------------------------------------------------


@dataclass(frozen=True)
class CommercialComment:
    message_id: UUID
    # The analysis that flagged it (`comment_intent_results.id`) — the followup's provenance.
    intent_result_id: UUID


class CommercialIntentReader(Protocol):
    def unfollowed(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        version: AnalysisVersion,
        posted_since: datetime,
        limit: int,
    ) -> list[CommercialComment]:
        """Inbound, not deleted comments of the connection, posted since `posted_since`,
        whose analysis under `version` is commercial and that have no followup yet —
        newest first."""
        ...


class MemoryCommercialIntentReader:
    """Seed `flagged` with (comment origin, intent_result_id); `opened` is consulted
    through the followup repository the workspace was given."""

    def __init__(self, origins: MemoryOriginReader, followed: Any) -> None:
        self._origins = origins
        self._followed = followed  # MemoryFollowupRepository
        self.flagged: list[CommercialComment] = []

    def unfollowed(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        version: AnalysisVersion,
        posted_since: datetime,
        limit: int,
    ) -> list[CommercialComment]:
        rows: list[tuple[datetime, CommercialComment]] = []
        for flag in self.flagged:
            origin = self._origins.get(tenant_id=tenant_id, message_id=flag.message_id)
            if (
                origin is None
                or origin.connection_id != connection_id
                or origin.channel != "comment"
                or origin.direction != "inbound"
                or origin.deleted
                or origin.posted_at is None
                or origin.posted_at < posted_since
                or self._followed.get_for_message(
                    tenant_id=tenant_id, origin_message_id=flag.message_id
                )
                is not None
            ):
                continue
            rows.append((origin.posted_at, flag))
        rows.sort(key=lambda item: item[0], reverse=True)
        return [flag for _, flag in rows[:limit]]


_UNFOLLOWED = text(
    """
    SELECT cir.id AS intent_result_id, cir.message_id
      FROM comment_intent_results cir
      JOIN messages m ON m.id = cir.message_id
      JOIN threads t ON t.id = m.thread_id
     WHERE cir.connection_id = :connection_id
       AND cir.commercial_intent
       AND cir.detector_version = :detector_version
       AND cir.pipeline_version = :pipeline_version
       AND cir.model_id = :model_id
       AND COALESCE(cir.model_revision, '') = COALESCE(CAST(:model_revision AS text), '')
       AND t.channel = 'comment'
       AND m.direction = 'inbound'
       AND m.deleted_at IS NULL
       AND m.posted_at >= :posted_since
       AND NOT EXISTS (
           SELECT 1 FROM interaction_followups f WHERE f.origin_message_id = cir.message_id
       )
     ORDER BY m.posted_at DESC, m.id
     LIMIT :limit
    """
)


class PostgresCommercialIntentReader:
    def unfollowed(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        version: AnalysisVersion,
        posted_since: datetime,
        limit: int,
    ) -> list[CommercialComment]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                _UNFOLLOWED,
                {
                    "connection_id": connection_id,
                    "detector_version": version.detector_version,
                    "pipeline_version": version.pipeline_version,
                    "model_id": version.model_id,
                    "model_revision": version.model_revision,
                    "posted_since": posted_since,
                    "limit": limit,
                },
            ).all()
        return [CommercialComment(r.message_id, r.intent_result_id) for r in rows]
