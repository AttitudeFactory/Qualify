"""Persistence for commercial intent (m-24789644): which comments still need an intent
analysis under the current version, recording an `IntentSignal`, and reading signals
back. Same two-implementation discipline as `sentiment/repository.py` —
`MemoryIntentRepository` is real production code for the offline suite and in-process dev
paths, not a drifting test double.

Idempotency + versioning are 0012's, unchanged: a `(message_id, detector_version,
pipeline_version, model_id, model_revision)` tuple is recorded at most once (a second
`record_intent_result` returns `False`); a different version for the same message is a
NEW row and the old one is never touched. Reuses sentiment's `AnalysisVersion` and
`PendingComment` on purpose: both are about "a comment under a model version", not about
sentiment.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.models import Message, Thread
from qualify_api.intent.contract import IntentSignal
from qualify_api.intent.models import CommentIntentResult
from qualify_api.sentiment.repository import AnalysisVersion, PendingComment

_COMMENT_CHANNEL = "comment"
_INBOUND = "inbound"

# (message_id, detector_version, pipeline_version, model_id, model_revision or "")
_VersionKey = tuple[UUID, str, str, str, str]


def signal_version(signal: IntentSignal) -> AnalysisVersion:
    return AnalysisVersion(
        detector_version=signal.detector_version,
        pipeline_version=signal.pipeline_version,
        model_id=signal.model_id,
        model_revision=signal.model_revision,
    )


def _key(message_id: UUID, version: AnalysisVersion) -> _VersionKey:
    return (
        message_id,
        version.detector_version,
        version.pipeline_version,
        version.model_id,
        version.model_revision or "",
    )


class IntentRepository(Protocol):
    def list_pending_for_intent(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]:
        """Every inbound comment of the connection with text, not deleted at the source
        (QUA-101: a deleted comment is never resurrected nor analyzed), and with no
        signal recorded under `version`."""
        ...

    def record_intent_result(
        self, *, tenant_id: UUID, connection_id: UUID, signal: IntentSignal
    ) -> bool:
        """`True` if a new row was inserted, `False` if this (comment, version) was
        already recorded — never raises on a duplicate."""
        ...

    def get_signals(
        self, *, tenant_id: UUID, message_ids: Iterable[UUID], version: AnalysisVersion
    ) -> dict[UUID, IntentSignal]:
        """The signal of each requested comment under `version`; a comment without one
        (not analyzed yet, or another tenant's) is simply absent from the result."""
        ...


class MemoryIntentRepository:
    """Mirrors the invariants above without a database."""

    def __init__(self) -> None:
        # message_id -> (connection_id, source_id, text, deleted)
        self._messages: dict[UUID, tuple[UUID, str, str | None, bool]] = {}
        self._signals: dict[_VersionKey, IntentSignal] = {}

    def seed_message(
        self,
        *,
        message_id: UUID,
        connection_id: UUID,
        source_id: str,
        text: str | None,
        deleted: bool = False,
    ) -> None:
        """Test/dev helper: in Postgres `messages` rows come from the inbox sync, not
        from this module. `deleted` mirrors `messages.deleted_at IS NOT NULL`."""
        self._messages[message_id] = (connection_id, source_id, text, deleted)

    def list_pending_for_intent(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]:
        return tuple(
            PendingComment(message_id=message_id, source_id=source_id, text=text)
            for message_id, (conn_id, source_id, text, deleted) in self._messages.items()
            if conn_id == connection_id
            and text is not None
            and not deleted
            and _key(message_id, version) not in self._signals
        )

    def record_intent_result(
        self, *, tenant_id: UUID, connection_id: UUID, signal: IntentSignal
    ) -> bool:
        key = _key(signal.comment_id, signal_version(signal))
        if key in self._signals:
            return False
        self._signals[key] = signal
        return True

    def get_signals(
        self, *, tenant_id: UUID, message_ids: Iterable[UUID], version: AnalysisVersion
    ) -> dict[UUID, IntentSignal]:
        found = {}
        for message_id in message_ids:
            signal = self._signals.get(_key(message_id, version))
            if signal is not None:
                found[message_id] = signal
        return found


class PostgresIntentRepository:
    """All access through `tenant_session`: RLS scopes every statement, and the composite
    FKs keep a row's tenant agreeing with its message and its connection."""

    def list_pending_for_intent(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]:
        with tenant_session(tenant_id) as session:
            already_analyzed = (
                select(CommentIntentResult.message_id)
                .where(
                    CommentIntentResult.message_id == Message.id,
                    CommentIntentResult.detector_version == version.detector_version,
                    CommentIntentResult.pipeline_version == version.pipeline_version,
                    CommentIntentResult.model_id == version.model_id,
                    # Same COALESCE as the unique index: NULL revision equals NULL.
                    func.coalesce(CommentIntentResult.model_revision, "")
                    == (version.model_revision or ""),
                )
                .exists()
            )
            rows = session.execute(
                select(Message.id, Message.external_message_id, Message.text)
                .join(Thread, Thread.id == Message.thread_id)
                .where(
                    Thread.channel == _COMMENT_CHANNEL,
                    Message.direction == _INBOUND,
                    Message.connection_id == connection_id,
                    Message.text.is_not(None),
                    Message.deleted_at.is_(None),
                    ~already_analyzed,
                )
            ).all()
            return tuple(
                PendingComment(message_id=row.id, source_id=row.external_message_id, text=row.text)
                for row in rows
            )

    def record_intent_result(
        self, *, tenant_id: UUID, connection_id: UUID, signal: IntentSignal
    ) -> bool:
        try:
            with tenant_session(tenant_id) as session:
                session.add(
                    CommentIntentResult(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        message_id=signal.comment_id,
                        source_id=signal.source_id,
                        detector_version=signal.detector_version,
                        pipeline_version=signal.pipeline_version,
                        model_id=signal.model_id,
                        model_revision=signal.model_revision,
                        confidences=signal.model_dump(mode="json")["classes"],
                        commercial_intent=signal.commercial_intent,
                    )
                )
                session.flush()  # trips uq_comment_intent_analysis on a duplicate
                return True
        except IntegrityError:
            # Same (comment, version) already recorded: the append-only shape of "done".
            return False

    def get_signals(
        self, *, tenant_id: UUID, message_ids: Iterable[UUID], version: AnalysisVersion
    ) -> dict[UUID, IntentSignal]:
        ids = list(message_ids)
        if not ids:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(CommentIntentResult).where(
                    CommentIntentResult.message_id.in_(ids),
                    CommentIntentResult.detector_version == version.detector_version,
                    CommentIntentResult.pipeline_version == version.pipeline_version,
                    CommentIntentResult.model_id == version.model_id,
                    func.coalesce(CommentIntentResult.model_revision, "")
                    == (version.model_revision or ""),
                )
            ).all()
            return {
                row.message_id: IntentSignal(
                    comment_id=row.message_id,
                    source_id=row.source_id,
                    classes=row.confidences,
                    detector_version=row.detector_version,
                    pipeline_version=row.pipeline_version,
                    model_id=row.model_id,
                    model_revision=row.model_revision,
                )
                for row in rows
            }
