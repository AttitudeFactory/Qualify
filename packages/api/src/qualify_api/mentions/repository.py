"""Persistence for `mentions` (QUA-49): idempotent writes, tenant-scoped reads, and the
sentiment-analysis bookkeeping. Same two-implementation discipline `inbox/repository.py`
and `sentiment/repository.py` establish — `MemoryMentionsRepository` is real production
code (offline suite + any in-process dev path), not a second, drifting test double.

**Idempotency is enforced by the database, not by a SELECT-then-INSERT here.**
`upsert_mention` always attempts the INSERT and interprets an `IntegrityError` against
`uq_mention_natural_key` as "already persisted" (same posture
`sentiment.repository.PostgresSentimentRepository.record_sentiment_result` already takes
for its own versioned unique index) — a redelivered webhook is a silent no-op, never a
race between two concurrent deliveries of the same event.

**Sentiment stays a SEPARATE, versioned table (`mention_sentiment_results`), never a
column mutated on `Mention`.** Reading a mention's current sentiment is a join against the
CURRENT `AnalysisVersion`, reusing the exact same versioning type
`qualify_api.sentiment.repository.AnalysisVersion` already defines for comments — the type
is generic over "what was analyzed", nothing about it is comment-specific, so importing it
here is reuse, not a comment-shaped model deforming what a mention is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from qualify_api.mentions.models import Mention, MentionSentimentResult
from qualify_api.sentiment.repository import AnalysisVersion

ENRICHMENT_PENDING = "PENDING"
ENRICHMENT_OK = "ENRICHED"
ENRICHMENT_FAILED = "ENRICHMENT_FAILED"

DEFAULT_MENTION_PAGE_SIZE = 50


@dataclass(frozen=True)
class NewMention:
    """The repository's write input — everything needed to persist one resolved mention.
    Assembled by `mentions/composition.py` after resolution + (attempted) enrichment; this
    module never calls Meta and never resolves a tenant, it only stores what it is given.
    """

    tenant_id: UUID
    connection_id: UUID
    external_account_id: str
    media_id: str
    comment_id: str | None
    caption: str | None
    text: str | None
    author_username: str | None
    media_type: str | None
    like_count: int | None
    content_posted_at: datetime | None
    enrichment_status: str


@dataclass(frozen=True)
class MentionRecord:
    """One persisted mention, read-projected. `sentiment_label` is the CURRENT-version
    `mention_sentiment_results.label`, or `None` when not yet analyzed — structurally
    distinct from any real label the same way `AnalyzedComment.label` already is."""

    id: UUID
    connection_id: UUID
    platform: str
    external_account_id: str
    media_id: str
    comment_id: str | None
    caption: str | None
    text: str | None
    author_username: str | None
    like_count: int | None
    content_posted_at: datetime | None
    received_at: datetime
    enrichment_status: str
    sentiment_label: str | None


@dataclass(frozen=True)
class PendingMentionSentiment:
    """One mention with real text (caption or comment text) awaiting analysis under the
    current model version. `text` is guaranteed non-empty — callers never re-check."""

    mention_id: UUID
    text: str


class MentionsRepository(Protocol):
    def upsert_mention(self, mention: NewMention) -> tuple[UUID, bool]:
        """Insert a mention, idempotent on `(connection_id, media_id, comment_id)`
        (COALESCE-normalized — migration 0013). Returns `(mention_id, created)`:
        `created=False` means this exact event was already persisted, and the id
        returned is the EXISTING row's — a caller never has to branch on which
        happened to know which mention id to log/reference."""
        ...

    def list_mentions(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        version: AnalysisVersion,
        limit: int = DEFAULT_MENTION_PAGE_SIZE,
    ) -> tuple[MentionRecord, ...]:
        """Newest-first mentions for a tenant, optionally narrowed to one connection, each
        decorated with its CURRENT-version sentiment label if analyzed. Bounded by
        `limit` — same "never an unbounded read" discipline QUA-93 established for
        comments, at a scale where it does not yet need QUA-93's LATERAL treatment."""
        ...

    def list_pending_for_analysis(
        self, *, tenant_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingMentionSentiment, ...]: ...

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        """Returns `True` if a new row was inserted, `False` if this exact
        (mention, version) tuple was already recorded — never raises on a duplicate,
        same contract `sentiment.repository`'s own `record_sentiment_result` has."""
        ...


class MemoryMentionsRepository:
    """Mirrors the invariants above without a database. Lives in production code for the
    same reason `MemoryInboxRepository`/`MemorySentimentRepository` do."""

    def __init__(self) -> None:
        self._mentions: dict[UUID, Mention] = {}
        # (connection_id, media_id, comment_id-or-"") -> mention_id, mirroring the
        # COALESCE natural key Postgres enforces via `uq_mention_natural_key`.
        self._natural_keys: dict[tuple[UUID, str, str], UUID] = {}
        # (mention_id, detector_version, pipeline_version, model_id, model_revision or "")
        self._sentiment: dict[tuple[UUID, str, str, str, str], tuple[str, float]] = {}
        self._next_id = 1

    def _new_uuid(self) -> UUID:
        # Deterministic, not random — makes assertions in tests reproducible without
        # needing to capture a generated id first. Same trick `uuid5`-based helpers
        # elsewhere in this codebase's in-memory repositories use for the same reason.
        from uuid import uuid5

        self._next_id += 1
        return uuid5(UUID(int=0), f"mention-{self._next_id}")

    def upsert_mention(self, mention: NewMention) -> tuple[UUID, bool]:
        key = (mention.connection_id, mention.media_id, mention.comment_id or "")
        existing = self._natural_keys.get(key)
        if existing is not None:
            return existing, False
        mention_id = self._new_uuid()
        row = Mention(
            id=mention_id,
            tenant_id=mention.tenant_id,
            connection_id=mention.connection_id,
            platform="instagram",
            external_account_id=mention.external_account_id,
            media_id=mention.media_id,
            comment_id=mention.comment_id,
            caption=mention.caption,
            text=mention.text,
            author_username=mention.author_username,
            media_type=mention.media_type,
            like_count=mention.like_count,
            content_posted_at=mention.content_posted_at,
            enrichment_status=mention.enrichment_status,
            received_at=datetime.now().astimezone(),
        )
        self._mentions[mention_id] = row
        self._natural_keys[key] = mention_id
        return mention_id, True

    def _label_for(self, mention_id: UUID, version: AnalysisVersion) -> str | None:
        key = (
            mention_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
        result = self._sentiment.get(key)
        return result[0] if result is not None else None

    def list_mentions(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        version: AnalysisVersion,
        limit: int = DEFAULT_MENTION_PAGE_SIZE,
    ) -> tuple[MentionRecord, ...]:
        rows = [
            m
            for m in self._mentions.values()
            if m.tenant_id == tenant_id
            and (connection_id is None or m.connection_id == connection_id)
        ]
        rows.sort(key=lambda m: (m.received_at, m.id), reverse=True)
        return tuple(
            MentionRecord(
                id=m.id,
                connection_id=m.connection_id,
                platform=m.platform,
                external_account_id=m.external_account_id,
                media_id=m.media_id,
                comment_id=m.comment_id,
                caption=m.caption,
                text=m.text,
                author_username=m.author_username,
                like_count=m.like_count,
                content_posted_at=m.content_posted_at,
                received_at=m.received_at,
                enrichment_status=m.enrichment_status,
                sentiment_label=self._label_for(m.id, version),
            )
            for m in rows[:limit]
        )

    def list_pending_for_analysis(
        self, *, tenant_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingMentionSentiment, ...]:
        pending = []
        for mention_id, m in self._mentions.items():
            if m.tenant_id != tenant_id:
                continue
            text = m.text or m.caption
            # Only `is None` excludes here, deliberately NOT `.strip()` — a whitespace-
            # only mention must still be CHECKED and counted as skipped by the SERVICE
            # (`MentionSentimentService.analyze_pending_mentions`), same division of
            # responsibility `sentiment.repository`'s own `list_pending_for_analysis`
            # already establishes for comments (QUA-21 AC5, restriction 1).
            if text is None:
                continue
            if self._label_for(mention_id, version) is not None:
                continue
            pending.append(PendingMentionSentiment(mention_id=mention_id, text=text))
        return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        key = (
            mention_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
        if key in self._sentiment:
            return False
        self._sentiment[key] = (label, score)
        return True


class PostgresMentionsRepository:
    """All access through `tenant_session` — RLS scopes every statement, and the
    composite FKs keep a row's tenant agreeing with both its connection and (for
    sentiment) its mention."""

    def upsert_mention(self, mention: NewMention) -> tuple[UUID, bool]:
        try:
            with tenant_session(mention.tenant_id) as session:
                row = Mention(
                    tenant_id=mention.tenant_id,
                    connection_id=mention.connection_id,
                    external_account_id=mention.external_account_id,
                    media_id=mention.media_id,
                    comment_id=mention.comment_id,
                    caption=mention.caption,
                    text=mention.text,
                    author_username=mention.author_username,
                    media_type=mention.media_type,
                    like_count=mention.like_count,
                    content_posted_at=mention.content_posted_at,
                    enrichment_status=mention.enrichment_status,
                )
                session.add(row)
                session.flush()  # trips uq_mention_natural_key on a duplicate
                return row.id, True
        except IntegrityError:
            # Same (connection_id, media_id, comment_id) already persisted — a
            # redelivery, not an error. Look the existing row up in its own session:
            # the failed one above is unusable after rollback-on-exit.
            with tenant_session(mention.tenant_id) as session:
                existing_id = session.execute(
                    select(Mention.id).where(
                        Mention.connection_id == mention.connection_id,
                        Mention.media_id == mention.media_id,
                        Mention.comment_id.is_(mention.comment_id)
                        if mention.comment_id is None
                        else Mention.comment_id == mention.comment_id,
                    )
                ).scalar_one()
                return existing_id, False

    def list_mentions(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        version: AnalysisVersion,
        limit: int = DEFAULT_MENTION_PAGE_SIZE,
    ) -> tuple[MentionRecord, ...]:
        with tenant_session(tenant_id) as session:
            sentiment_subq = select(MentionSentimentResult.label).where(
                MentionSentimentResult.mention_id == Mention.id,
                MentionSentimentResult.detector_version == version.detector_version,
                MentionSentimentResult.pipeline_version == version.pipeline_version,
                MentionSentimentResult.model_id == version.model_id,
            )
            sentiment_subq = (
                sentiment_subq.where(MentionSentimentResult.model_revision.is_(None))
                if version.model_revision is None
                else sentiment_subq.where(
                    MentionSentimentResult.model_revision == version.model_revision
                )
            )
            stmt = (
                select(Mention, sentiment_subq.limit(1).scalar_subquery().label("sentiment_label"))
                .where(Mention.tenant_id == tenant_id)
                .order_by(Mention.received_at.desc(), Mention.id.desc())
                .limit(limit)
            )
            if connection_id is not None:
                stmt = stmt.where(Mention.connection_id == connection_id)
            rows = session.execute(stmt).all()
            return tuple(
                MentionRecord(
                    id=m.id,
                    connection_id=m.connection_id,
                    platform=m.platform,
                    external_account_id=m.external_account_id,
                    media_id=m.media_id,
                    comment_id=m.comment_id,
                    caption=m.caption,
                    text=m.text,
                    author_username=m.author_username,
                    like_count=m.like_count,
                    content_posted_at=m.content_posted_at,
                    received_at=m.received_at,
                    enrichment_status=m.enrichment_status,
                    sentiment_label=sentiment_label,
                )
                for m, sentiment_label in rows
            )

    def list_pending_for_analysis(
        self, *, tenant_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingMentionSentiment, ...]:
        with tenant_session(tenant_id) as session:
            already_analyzed = (
                select(MentionSentimentResult.mention_id)
                .where(
                    MentionSentimentResult.mention_id == Mention.id,
                    MentionSentimentResult.detector_version == version.detector_version,
                    MentionSentimentResult.pipeline_version == version.pipeline_version,
                    MentionSentimentResult.model_id == version.model_id,
                )
                .exists()
            )
            already_analyzed = (
                already_analyzed.where(MentionSentimentResult.model_revision.is_(None))
                if version.model_revision is None
                else already_analyzed.where(
                    MentionSentimentResult.model_revision == version.model_revision
                )
            )
            rows = session.execute(
                select(Mention.id, Mention.text, Mention.caption).where(
                    Mention.tenant_id == tenant_id,
                    ~already_analyzed,
                )
            ).all()
            pending = []
            for row in rows:
                text = row.text or row.caption
                # Only `is None` excludes — see `MemoryMentionsRepository`'s identical
                # comment for why a whitespace-only mention must still reach the service.
                if text is not None:
                    pending.append(PendingMentionSentiment(mention_id=row.id, text=text))
            return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        try:
            with tenant_session(tenant_id) as session:
                session.add(
                    MentionSentimentResult(
                        tenant_id=tenant_id,
                        mention_id=mention_id,
                        detector_version=version.detector_version,
                        pipeline_version=version.pipeline_version,
                        model_id=version.model_id,
                        model_revision=version.model_revision,
                        label=label,
                        score=score,
                    )
                )
                session.flush()  # trips uq_mention_sentiment_analysis on a duplicate
                return True
        except IntegrityError:
            return False
