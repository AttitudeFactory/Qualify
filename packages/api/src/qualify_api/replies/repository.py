"""Persistence for QUA-22's comments tranche: which POS-sentiment comments still need a
draft, and the draft's own lifecycle (`comment_reply_drafts`, migration 0014). Same
two-implementation discipline `sentiment/repository.py`/`inbox/repository.py` already
establish — `MemoryCommentReplyRepository` is real production code (used by the
offline suite and any in-process dev path), not a test double with a second, drifting
copy.

**Lifecycle, in one sentence:** `proposed` (write-ahead, right after generation) →
`accepted`/`edited`/`discarded` (human decision) → for a non-discarded decision only,
`sending` (write-ahead, right before the Meta call) → `sent`/`send_failed` (terminal,
`settled_at` set) or `send_ambiguous` (deliberately NOT terminal — see migration
0014's docstring). `discarded` is terminal directly from `proposed`.

**Idempotency.** `UNIQUE(message_id)` means at most one draft ever exists per comment
in this v1 — `create_draft` returns `None` (not an exception) when one already exists,
same "no raw IntegrityError leaks upstream" discipline `record_sentiment_result`
already follows for its own unique index.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.models import Message, Thread
from qualify_api.replies.models import CommentReplyDraft
from qualify_api.sentiment.models import CommentSentimentResult
from qualify_api.sentiment.repository import AnalysisVersion

_COMMENT_CHANNEL = "comment"
_INBOUND = "inbound"


@dataclass(frozen=True)
class CandidateComment:
    """One POS-sentiment comment, current `AnalysisVersion`, with no draft yet — what
    `ReplyService.generate_drafts` iterates over."""

    message_id: UUID
    source_id: str
    text: str
    sentiment_result_id: UUID
    sentiment_label: str


@dataclass(frozen=True)
class DraftRecord:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    message_id: UUID
    source_id: str
    sentiment_result_id: UUID
    sentiment_label: str
    gate_reason: str
    generator_version: str
    generated_text: str
    final_text: str | None
    status: str
    # The ORIGINAL comment text this draft answers — a human cannot judge a drafted
    # reply without seeing what it replies to. Denormalized at read time from
    # `messages.text` (never stored on `comment_reply_drafts` itself — see migration
    # 0014, which has no such column); `""` where a caller did not join for it
    # (`get_draft`/`decide_draft`/the `mark_*` transitions do not need it and leave it
    # empty on purpose — only `create_draft`, which already holds the comment's text
    # from the `CandidateComment` it was generated from, and `list_pending_drafts`,
    # the actual review queue, populate it for real).
    comment_text: str
    created_at: datetime
    decided_at: datetime | None
    decided_by_user_id: UUID | None
    sent_at: datetime | None
    external_reply_id: str | None
    send_error_code: str | None
    settled_at: datetime | None

    @property
    def is_settled(self) -> bool:
        return self.settled_at is not None


class ReplyRepository(Protocol):
    def list_positive_comments_without_draft(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[CandidateComment, ...]:
        """Every inbound, comment-channel message with a CURRENT-version `POS`
        `comment_sentiment_results` row and no `comment_reply_drafts` row yet — and not
        soft-deleted (QUA-101, `messages.deleted_at`): a comment Meta no longer returns
        must never become a NEW draft candidate. Does not retroactively affect a draft
        already `proposed` before its comment was deleted — see `list_pending_drafts`."""
        ...

    def has_draft(self, *, tenant_id: UUID, message_id: UUID) -> bool: ...

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
    ) -> DraftRecord | None:
        """Returns the new row, or `None` if `UNIQUE(message_id)` already holds — same
        never-raises-on-duplicate discipline `record_sentiment_result` follows."""
        ...

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None: ...

    def list_pending_drafts(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> tuple[DraftRecord, ...]:
        """`status = 'proposed'` only — the human review queue."""
        ...

    def decide_draft(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        decision: str,
        final_text: str | None,
        decided_by_user_id: UUID,
    ) -> DraftRecord:
        """`decision` in `('accepted', 'edited', 'discarded')`. Raises `ValueError` if
        the draft is not `'proposed'` — a decision is made exactly once."""
        ...

    def mark_sending(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord:
        """Write-ahead marker, unsettled. Raises `ValueError` if the draft is not
        `'accepted'`/`'edited'`."""
        ...

    def mark_sent(
        self, *, tenant_id: UUID, draft_id: UUID, external_reply_id: str
    ) -> DraftRecord: ...

    def mark_send_failed(
        self, *, tenant_id: UUID, draft_id: UUID, error_code: str
    ) -> DraftRecord: ...

    def mark_send_ambiguous(
        self, *, tenant_id: UUID, draft_id: UUID, error_code: str
    ) -> DraftRecord:
        """Deliberately does NOT set `settled_at` — see migration 0014's docstring."""
        ...


def _row_to_record(row: CommentReplyDraft, *, comment_text: str = "") -> DraftRecord:
    """`comment_text` defaults to `""` — see `DraftRecord.comment_text`'s own docstring
    for which callers bother to join for it and which do not."""
    return DraftRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        connection_id=row.connection_id,
        message_id=row.message_id,
        source_id=row.source_id,
        sentiment_result_id=row.sentiment_result_id,
        sentiment_label=row.sentiment_label,
        gate_reason=row.gate_reason,
        generator_version=row.generator_version,
        generated_text=row.generated_text,
        final_text=row.final_text,
        status=row.status,
        comment_text=comment_text,
        created_at=row.created_at,
        decided_at=row.decided_at,
        decided_by_user_id=row.decided_by_user_id,
        sent_at=row.sent_at,
        external_reply_id=row.external_reply_id,
        send_error_code=row.send_error_code,
        settled_at=row.settled_at,
    )


class PostgresReplyRepository:
    def list_positive_comments_without_draft(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[CandidateComment, ...]:
        with tenant_session(tenant_id) as session:
            stmt = (
                select(Message, CommentSentimentResult)
                .join(Thread, Thread.id == Message.thread_id)
                .join(CommentSentimentResult, CommentSentimentResult.message_id == Message.id)
                .outerjoin(CommentReplyDraft, CommentReplyDraft.message_id == Message.id)
                .where(
                    Thread.channel == _COMMENT_CHANNEL,
                    Message.direction == _INBOUND,
                    Message.connection_id == connection_id,
                    # QUA-101: a comment Meta no longer returns (`InboxRepository.
                    # reconcile_media_comments`) is not a candidate for a NEW reply
                    # draft — same exclusion `sentiment/repository.py`'s four read
                    # methods already apply. Deliberately does NOT touch a draft that
                    # already exists for a comment deleted AFTER drafting
                    # (`list_pending_drafts` is unchanged) — hiding/flagging an
                    # already-proposed draft is a separate product decision, not this
                    # fix's job.
                    Message.deleted_at.is_(None),
                    CommentSentimentResult.label == "POS",
                    CommentSentimentResult.detector_version == version.detector_version,
                    CommentSentimentResult.pipeline_version == version.pipeline_version,
                    CommentSentimentResult.model_id == version.model_id,
                    CommentReplyDraft.id.is_(None),
                )
            )
            rows = session.execute(stmt).all()
        return tuple(
            CandidateComment(
                message_id=message.id,
                source_id=message.external_message_id,
                text=message.text or "",
                sentiment_result_id=result.id,
                sentiment_label=result.label,
            )
            for message, result in rows
        )

    def has_draft(self, *, tenant_id: UUID, message_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            existing = session.execute(
                select(CommentReplyDraft.id).where(CommentReplyDraft.message_id == message_id)
            ).first()
        return existing is not None

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
    ) -> DraftRecord | None:
        row = CommentReplyDraft(
            tenant_id=tenant_id,
            connection_id=connection_id,
            message_id=candidate.message_id,
            source_id=candidate.source_id,
            sentiment_result_id=candidate.sentiment_result_id,
            sentiment_label=candidate.sentiment_label,
            gate_reason=gate_reason,
            generator_version=generator_version,
            generated_text=generated_text,
            status="proposed",
        )
        with tenant_session(tenant_id) as session:
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return None
            session.commit()
            session.refresh(row)
            # The candidate already carries the comment's text — no extra query needed
            # to populate `DraftRecord.comment_text` here.
            return _row_to_record(row, comment_text=candidate.text)

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(CommentReplyDraft, draft_id)
        return _row_to_record(row) if row is not None else None

    def list_pending_drafts(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> tuple[DraftRecord, ...]:
        """The review queue — joined to `messages` so `DraftRecord.comment_text` is the
        REAL original comment, not the empty default: a human cannot judge a drafted
        reply without seeing what it answers."""
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(CommentReplyDraft, Message)
                .join(Message, Message.id == CommentReplyDraft.message_id)
                .where(
                    CommentReplyDraft.connection_id == connection_id,
                    CommentReplyDraft.status == "proposed",
                )
                .order_by(CommentReplyDraft.created_at)
            ).all()
        return tuple(
            _row_to_record(draft, comment_text=message.text or "") for draft, message in rows
        )

    def _require(self, session, tenant_id: UUID, draft_id: UUID) -> CommentReplyDraft:
        row = session.get(CommentReplyDraft, draft_id)
        if row is None:
            raise ValueError(
                f"no comment_reply_drafts row {draft_id} visible to tenant {tenant_id}"
            )
        return row

    def decide_draft(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        decision: str,
        final_text: str | None,
        decided_by_user_id: UUID,
    ) -> DraftRecord:
        if decision not in ("accepted", "edited", "discarded"):
            raise ValueError(f"invalid decision {decision!r}")
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, draft_id)
            if row.status != "proposed":
                raise ValueError(
                    f"draft {draft_id} is {row.status!r}, not 'proposed' — already decided"
                )
            row.status = decision
            row.final_text = None if decision == "discarded" else (final_text or row.generated_text)
            row.decided_at = datetime.now(UTC)
            row.decided_by_user_id = decided_by_user_id
            if decision == "discarded":
                row.settled_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def mark_sending(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord:
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, draft_id)
            if row.status not in ("accepted", "edited"):
                raise ValueError(f"draft {draft_id} is {row.status!r}, cannot send")
            row.status = "sending"
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def mark_sent(self, *, tenant_id: UUID, draft_id: UUID, external_reply_id: str) -> DraftRecord:
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, draft_id)
            row.status = "sent"
            row.sent_at = datetime.now(UTC)
            row.external_reply_id = external_reply_id
            row.settled_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def mark_send_failed(self, *, tenant_id: UUID, draft_id: UUID, error_code: str) -> DraftRecord:
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, draft_id)
            row.status = "send_failed"
            row.send_error_code = error_code
            row.settled_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def mark_send_ambiguous(
        self, *, tenant_id: UUID, draft_id: UUID, error_code: str
    ) -> DraftRecord:
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, draft_id)
            row.status = "send_ambiguous"
            row.send_error_code = error_code
            # settled_at stays NULL — see migration 0014's docstring.
            session.commit()
            session.refresh(row)
            return _row_to_record(row)


class MemoryReplyRepository:
    """Real production-usable implementation over a plain dict — same role
    `MemorySentimentRepository`/in-memory `InboxRepository` already play: the offline
    test suite's repository, not a second drifting mock of `PostgresReplyRepository`'s
    behavior."""

    def __init__(self) -> None:
        self._drafts: dict[UUID, DraftRecord] = {}
        self._by_message: dict[UUID, UUID] = {}
        self._candidates: dict[UUID, tuple[CandidateComment, ...]] = {}

    def seed_candidates(
        self, *, connection_id: UUID, candidates: tuple[CandidateComment, ...]
    ) -> None:
        """Test/dev seam — the Memory repo has no `messages`/`comment_sentiment_results`
        tables to query, so a caller populates the candidate list directly.

        QUA-101: unlike `MemorySentimentRepository` (which mirrors `messages` row-by-row,
        `deleted_at` included, because it independently re-derives what a real query
        would compute), this repo works one level of abstraction higher — a caller
        already hands it the exact `CandidateComment` tuple `list_positive_comments_
        without_draft` should return. Excluding a soft-deleted comment is therefore the
        SEEDING caller's job (simply don't include it), not something this method needs
        to filter — there is no separate "deleted" concept to consult here."""
        self._candidates[connection_id] = candidates

    def list_positive_comments_without_draft(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[CandidateComment, ...]:
        del tenant_id, version  # unused in-memory: seeded candidates are already POS/current
        candidates = self._candidates.get(connection_id, ())
        return tuple(c for c in candidates if c.message_id not in self._by_message)

    def has_draft(self, *, tenant_id: UUID, message_id: UUID) -> bool:
        del tenant_id
        return message_id in self._by_message

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
    ) -> DraftRecord | None:
        if candidate.message_id in self._by_message:
            return None
        record = DraftRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            message_id=candidate.message_id,
            source_id=candidate.source_id,
            sentiment_result_id=candidate.sentiment_result_id,
            sentiment_label=candidate.sentiment_label,
            gate_reason=gate_reason,
            generator_version=generator_version,
            generated_text=generated_text,
            final_text=None,
            status="proposed",
            comment_text=candidate.text,
            created_at=datetime.now(UTC),
            decided_at=None,
            decided_by_user_id=None,
            sent_at=None,
            external_reply_id=None,
            send_error_code=None,
            settled_at=None,
        )
        self._drafts[record.id] = record
        self._by_message[candidate.message_id] = record.id
        return record

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None:
        del tenant_id
        return self._drafts.get(draft_id)

    def list_pending_drafts(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> tuple[DraftRecord, ...]:
        del tenant_id
        return tuple(
            d
            for d in self._drafts.values()
            if d.connection_id == connection_id and d.status == "proposed"
        )

    def _require(self, draft_id: UUID) -> DraftRecord:
        record = self._drafts.get(draft_id)
        if record is None:
            raise ValueError(f"no draft {draft_id}")
        return record

    def decide_draft(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        decision: str,
        final_text: str | None,
        decided_by_user_id: UUID,
    ) -> DraftRecord:
        del tenant_id
        if decision not in ("accepted", "edited", "discarded"):
            raise ValueError(f"invalid decision {decision!r}")
        record = self._require(draft_id)
        if record.status != "proposed":
            raise ValueError(f"draft {draft_id} is {record.status!r}, not 'proposed'")
        updated = replace(
            record,
            status=decision,
            final_text=None if decision == "discarded" else (final_text or record.generated_text),
            decided_at=datetime.now(UTC),
            decided_by_user_id=decided_by_user_id,
            settled_at=datetime.now(UTC) if decision == "discarded" else record.settled_at,
        )
        self._drafts[draft_id] = updated
        return updated

    def mark_sending(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord:
        del tenant_id
        record = self._require(draft_id)
        if record.status not in ("accepted", "edited"):
            raise ValueError(f"draft {draft_id} is {record.status!r}, cannot send")
        updated = replace(record, status="sending")
        self._drafts[draft_id] = updated
        return updated

    def mark_sent(self, *, tenant_id: UUID, draft_id: UUID, external_reply_id: str) -> DraftRecord:
        del tenant_id
        record = self._require(draft_id)
        updated = replace(
            record,
            status="sent",
            sent_at=datetime.now(UTC),
            external_reply_id=external_reply_id,
            settled_at=datetime.now(UTC),
        )
        self._drafts[draft_id] = updated
        return updated

    def mark_send_failed(self, *, tenant_id: UUID, draft_id: UUID, error_code: str) -> DraftRecord:
        del tenant_id
        record = self._require(draft_id)
        updated = replace(
            record, status="send_failed", send_error_code=error_code, settled_at=datetime.now(UTC)
        )
        self._drafts[draft_id] = updated
        return updated

    def mark_send_ambiguous(
        self, *, tenant_id: UUID, draft_id: UUID, error_code: str
    ) -> DraftRecord:
        del tenant_id
        record = self._require(draft_id)
        # settled_at stays untouched (None) — see migration 0014's docstring.
        updated = replace(record, status="send_ambiguous", send_error_code=error_code)
        self._drafts[draft_id] = updated
        return updated
