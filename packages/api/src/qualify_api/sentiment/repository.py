"""Persistence for QUA-21: which comments still need analysis under the current model
version, and recording a result. Same two-implementation discipline `inbox/repository.py`
establishes — `MemorySentimentRepository` is real production code (used by the offline
suite and any in-process dev path), not a test double with a second, drifting copy.

**Idempotency + versioning, in one sentence:** a `(message_id, detector_version,
pipeline_version, model_id, model_revision)` tuple is analyzed at most once — recording
the same tuple twice is a silent no-op (`record_sentiment_result` returns `False`);
recording a DIFFERENT tuple for the same message is a NEW row, and the old one is never
touched. See migration 0012 for the `COALESCE(model_revision, '')` reasoning that makes
this hold even when `model_revision` is `NULL`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment.models import CommentSentimentResult

_COMMENT_CHANNEL = "comment"
_INBOUND = "inbound"


@dataclass(frozen=True)
class PendingComment:
    """One `messages` row eligible for analysis under the current model version.
    `text` is guaranteed non-`None` here — callers never need to check again."""

    message_id: UUID
    source_id: str
    text: str


@dataclass(frozen=True)
class AnalysisVersion:
    """The four-part key `list_pending_for_analysis`/`record_sentiment_result` key
    against. Grouped so callers cannot pass the pieces in the wrong order — the same
    reasoning `connections.composition`'s keyword-only signatures document."""

    detector_version: str
    pipeline_version: str
    model_id: str
    model_revision: str | None


class SentimentRepository(Protocol):
    def list_pending_for_analysis(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]: ...

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        message_id: UUID,
        source_id: str,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        """Returns `True` if a new row was inserted, `False` if this exact
        (message, version) tuple was already recorded — never raises on a duplicate."""
        ...


class MemorySentimentRepository:
    """Mirrors the two invariants above without a database. Lives in production code
    for the same reason `MemoryInboxRepository` does."""

    def __init__(self) -> None:
        # (message_id, detector_version, pipeline_version, model_id, model_revision or "")
        self._recorded: set[tuple[UUID, str, str, str, str]] = set()
        # message_id -> (connection_id, source_id, text)
        self._messages: dict[UUID, tuple[UUID, str, str | None]] = {}

    def seed_message(
        self, *, message_id: UUID, connection_id: UUID, source_id: str, text: str | None
    ) -> None:
        """Test-only helper — the Postgres implementation has no analogue because
        `messages` rows there come from the real inbox sync, not from this module."""
        self._messages[message_id] = (connection_id, source_id, text)

    def list_pending_for_analysis(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]:
        key_suffix = (version.detector_version, version.pipeline_version, version.model_id)
        revision_key = version.model_revision or ""
        pending = []
        for message_id, (conn_id, source_id, text) in self._messages.items():
            if conn_id != connection_id or text is None:
                continue
            if (message_id, *key_suffix, revision_key) in self._recorded:
                continue
            pending.append(PendingComment(message_id=message_id, source_id=source_id, text=text))
        return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        message_id: UUID,
        source_id: str,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        key = (
            message_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
        if key in self._recorded:
            return False
        self._recorded.add(key)
        return True


class PostgresSentimentRepository:
    """All access through `tenant_session` — RLS scopes every statement, and the
    composite FKs keep a row's tenant agreeing with both its message and its
    connection."""

    def list_pending_for_analysis(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]:
        with tenant_session(tenant_id) as session:
            already_analyzed = (
                select(CommentSentimentResult.message_id)
                .where(
                    CommentSentimentResult.message_id == Message.id,
                    CommentSentimentResult.detector_version == version.detector_version,
                    CommentSentimentResult.pipeline_version == version.pipeline_version,
                    CommentSentimentResult.model_id == version.model_id,
                )
                .exists()
            )
            # COALESCE mirrors the migration's unique index: NULL model_revision must
            # compare equal to NULL model_revision for "already analyzed" to hold.
            if version.model_revision is None:
                already_analyzed = already_analyzed.where(
                    CommentSentimentResult.model_revision.is_(None)
                )
            else:
                already_analyzed = already_analyzed.where(
                    CommentSentimentResult.model_revision == version.model_revision
                )

            rows = session.execute(
                select(Message.id, Message.external_message_id, Message.text)
                .join(Thread, Thread.id == Message.thread_id)
                .where(
                    Thread.channel == _COMMENT_CHANNEL,
                    Message.direction == _INBOUND,
                    Message.connection_id == connection_id,
                    Message.text.is_not(None),
                    ~already_analyzed,
                )
            ).all()
            return tuple(
                PendingComment(message_id=row.id, source_id=row.external_message_id, text=row.text)
                for row in rows
                if row.text is not None  # belt-and-suspenders; the query already filters this
            )

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        message_id: UUID,
        source_id: str,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        try:
            with tenant_session(tenant_id) as session:
                session.add(
                    CommentSentimentResult(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        message_id=message_id,
                        source_id=source_id,
                        detector_version=version.detector_version,
                        pipeline_version=version.pipeline_version,
                        model_id=version.model_id,
                        model_revision=version.model_revision,
                        label=label,
                        score=score,
                    )
                )
                session.flush()  # trips uq_comment_sentiment_analysis on a duplicate
                return True
        except IntegrityError:
            # Same (message, version) tuple already recorded. Not an error — the
            # append-only design means this is the expected shape of "already done".
            return False
