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

**Idempotency.** At most one LIVE draft exists per comment (0080's partial unique index
`uq_reply_draft_live_message`; `models.LIVE_STATUSES`) — `create_draft` returns `None`
(not an exception) when one already exists, same "no raw IntegrityError leaks upstream"
discipline `record_sentiment_result` already follows for its own unique index. A
discarded or refused (`send_failed`) draft leaves room for a new one; the automatic batch
still skips any comment with ANY draft (`list_reply_candidates`), so nothing is
regenerated automatically — a new draft after a discard is a deliberate act
(`supersede_draft`, behind `ReplyService.regenerate`, m-24789645 «Regenerar»).

**Candidates (m-24789645 PR 2).** A comment is a candidate when it has a current-version
POS sentiment row OR a current-version commercial-intent row (Fase A). Sentiment and
intent are independent analyses, so either may be missing; the candidate carries both
(ids, label, intent classes) plus the comment's Fase C followup status, and the gate
decides.

**Provenance (0080).** `create_draft` takes an optional `DraftProvenance` — grounding,
review verdict, unsupported claims, model/cost, the Fase A intent result — and every
`DraftRecord` carries it back. The sentiment-era path passes none: those columns stay
NULL / false.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import Text, and_, column, false, func, or_, select, table, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.models import Message, Thread
from qualify_api.intent.models import CommentIntentResult
from qualify_api.replies.models import DEAD_STATUSES, CommentReplyDraft
from qualify_api.sentiment.models import CommentSentimentResult
from qualify_api.sentiment.repository import AnalysisVersion

_COMMENT_CHANNEL = "comment"
_INBOUND = "inbound"
_LIVE_INDEX = "uq_reply_draft_live_message"

# Fase C's `interaction_followups` (0071), read as a bare table: the gate needs only the
# status of a comment's followup, and importing the `followups` package here would tie
# the two modules together for one column. RLS scopes it like every other read here.
_FOLLOWUPS = table(
    "interaction_followups",
    column("origin_message_id", PGUUID(as_uuid=True)),
    column("status", Text),
)


@dataclass(frozen=True)
class CandidateComment:
    """One inbound comment and the signals that may earn it a public reply — what
    `ReplyService.generate_drafts` / `regenerate` hand to the gate.

    Every signal is the CURRENT-version one or absent: `sentiment_*` from
    `comment_sentiment_results`, `intent_*` from `comment_intent_results` (Fase A).
    `sentiment_label` is `""` when the comment has no current sentiment row."""

    message_id: UUID
    source_id: str
    text: str
    sentiment_result_id: UUID | None = None
    sentiment_label: str = ""
    intent_result_id: UUID | None = None
    # Assigned intent classes (`IntentClass` values), most confident first.
    intent_classes: tuple[str, ...] = ()
    commercial_intent: bool = False
    # The version the intent row was recorded under (None without an intent row).
    intent_version: AnalysisVersion | None = None
    # `interaction_followups.status` of the comment's Fase C followup, None if none.
    followup_status: str | None = None


@dataclass(frozen=True)
class DraftProvenance:
    """What 0080 lets a draft record about how it was made. All optional: the
    sentiment-era generator reports none of it. `unsupported_claims=None` means "not
    judged"; `()` means "judged, nothing unsupported"."""

    grounding: Mapping[str, Any] | None = None
    needs_review: bool = False
    unsupported_claims: tuple[str, ...] | None = None
    model_id: str | None = None
    model_revision: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    intent_result_id: UUID | None = None


_NO_PROVENANCE = DraftProvenance()


@dataclass(frozen=True)
class DraftRecord:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    message_id: UUID
    source_id: str
    # None / `""` when the draft stands on a commercial-intent signal alone (0081).
    sentiment_result_id: UUID | None
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
    # 0080 (m-24789645) — NULL/false/empty on sentiment-era drafts.
    grounding: Mapping[str, Any] | None = None
    needs_review: bool = False
    unsupported_claims: tuple[str, ...] = ()
    model_id: str | None = None
    model_revision: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    intent_result_id: UUID | None = None

    @property
    def is_settled(self) -> bool:
        return self.settled_at is not None

    @property
    def is_live(self) -> bool:
        """Holds the comment's one live draft (0080) — see `models.LIVE_STATUSES`."""
        return self.status not in DEAD_STATUSES


class ReplyRepository(Protocol):
    def list_reply_candidates(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        sentiment_version: AnalysisVersion,
        intent_version: AnalysisVersion | None,
    ) -> tuple[CandidateComment, ...]:
        """Every inbound, comment-channel message of the connection, not soft-deleted
        (QUA-101: a comment Meta no longer returns never becomes a NEW draft candidate),
        with no `comment_reply_drafts` row at all (a discarded draft is NOT regenerated
        by the batch — that is `supersede_draft`'s explicit act), and with a
        `sentiment_version` POS row OR an `intent_version` commercial row. With
        `intent_version=None` only the POS half applies (the QUA-22 behaviour)."""
        ...

    def get_reply_candidate(
        self,
        *,
        tenant_id: UUID,
        message_id: UUID,
        sentiment_version: AnalysisVersion,
        intent_version: AnalysisVersion | None,
    ) -> CandidateComment | None:
        """One comment with its current signals, whatever they are and whatever drafts
        it has (for `regenerate`, which lets the gate judge). None if it is not an
        inbound, non-deleted comment visible to this tenant."""
        ...

    def has_draft(self, *, tenant_id: UUID, message_id: UUID) -> bool:
        """Whether the comment has ANY draft, live or not — what generation skips on."""
        ...

    def get_live_draft(self, *, tenant_id: UUID, message_id: UUID) -> DraftRecord | None:
        """The comment's one live draft (status not in `DEAD_STATUSES`), if any."""
        ...

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
        provenance: DraftProvenance | None = None,
    ) -> DraftRecord | None:
        """Returns the new row, or `None` if the comment already has a LIVE draft
        (`uq_reply_draft_live_message`) — same never-raises-on-duplicate discipline
        `record_sentiment_result` follows. Any other integrity error (a foreign key, a
        CHECK) propagates: it is a bug, not a race."""
        ...

    def supersede_draft(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        decided_by_user_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
        provenance: DraftProvenance | None = None,
    ) -> DraftRecord | None:
        """In ONE transaction: discard `draft_id` (only while it is still `'proposed'`,
        recording who) and create the comment's new `'proposed'` draft. Returns the new
        row, or None when it lost a race — the old draft was no longer `'proposed'` (a
        double click: the other request already replaced it) or another live draft holds
        the comment. Nothing is written in that case, so the live index never trips."""
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
        sentiment_label=row.sentiment_label or "",
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
        grounding=dict(row.grounding) if isinstance(row.grounding, dict) else None,
        needs_review=bool(row.needs_review),
        unsupported_claims=tuple(str(c) for c in (row.unsupported_claims or [])),
        model_id=row.model_id,
        model_revision=row.model_revision,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        intent_result_id=row.intent_result_id,
    )


def _provenance_columns(provenance: DraftProvenance) -> dict[str, Any]:
    claims = provenance.unsupported_claims
    return {
        "grounding": dict(provenance.grounding) if provenance.grounding is not None else None,
        "needs_review": provenance.needs_review,
        "unsupported_claims": list(claims) if claims is not None else None,
        "model_id": provenance.model_id,
        "model_revision": provenance.model_revision,
        "input_tokens": provenance.input_tokens,
        "output_tokens": provenance.output_tokens,
        "cost_usd": provenance.cost_usd,
        "intent_result_id": provenance.intent_result_id,
    }


def _with_candidate_signal(
    provenance: DraftProvenance | None, candidate: CandidateComment
) -> DraftProvenance:
    """The draft names the intent result it was judged on, like it names the sentiment
    result: from the provenance when the generator set it, else from the candidate."""
    p = provenance or _NO_PROVENANCE
    if p.intent_result_id is None and candidate.intent_result_id is not None:
        return replace(p, intent_result_id=candidate.intent_result_id)
    return p


def _is_live_duplicate(exc: IntegrityError) -> bool:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    return constraint == _LIVE_INDEX


def _version_match(model: Any, version: AnalysisVersion) -> Any:
    """Same COALESCE as the results' unique indexes: a NULL revision equals NULL."""
    return and_(
        model.detector_version == version.detector_version,
        model.pipeline_version == version.pipeline_version,
        model.model_id == version.model_id,
        func.coalesce(model.model_revision, "") == (version.model_revision or ""),
    )


def _candidate_select(
    *, sentiment_version: AnalysisVersion, intent_version: AnalysisVersion | None
) -> Any:
    """Inbound, non-deleted comments with their CURRENT sentiment row, CURRENT intent row
    and Fase C followup status, all LEFT-joined (each is unique per comment and
    version, and `interaction_followups.origin_message_id` is UNIQUE)."""
    intent_on = (
        _version_match(CommentIntentResult, intent_version)
        if intent_version is not None
        else false()
    )
    return (
        select(
            Message.id,
            Message.external_message_id,
            Message.text,
            CommentSentimentResult.id.label("sentiment_result_id"),
            CommentSentimentResult.label.label("sentiment_label"),
            CommentIntentResult.id.label("intent_result_id"),
            CommentIntentResult.confidences,
            CommentIntentResult.commercial_intent,
            CommentIntentResult.detector_version,
            CommentIntentResult.pipeline_version,
            CommentIntentResult.model_id,
            CommentIntentResult.model_revision,
            _FOLLOWUPS.c.status.label("followup_status"),
        )
        .join(Thread, Thread.id == Message.thread_id)
        .outerjoin(
            CommentSentimentResult,
            and_(
                CommentSentimentResult.message_id == Message.id,
                _version_match(CommentSentimentResult, sentiment_version),
            ),
        )
        .outerjoin(
            CommentIntentResult,
            and_(CommentIntentResult.message_id == Message.id, intent_on),
        )
        .outerjoin(_FOLLOWUPS, _FOLLOWUPS.c.origin_message_id == Message.id)
        .where(
            Thread.channel == _COMMENT_CHANNEL,
            Message.direction == _INBOUND,
            # QUA-101: a comment Meta no longer returns (`InboxRepository.
            # reconcile_media_comments`) is not a candidate for a NEW reply draft. A
            # draft proposed before the deletion is untouched (`list_pending_drafts`).
            Message.deleted_at.is_(None),
        )
    )


def _candidate_from_row(row: Any) -> CandidateComment:
    confidences = row.confidences if isinstance(row.confidences, dict) else {}
    ranked = sorted(confidences.items(), key=lambda item: (-float(item[1]), str(item[0])))
    intent_version = (
        AnalysisVersion(
            detector_version=row.detector_version,
            pipeline_version=row.pipeline_version,
            model_id=row.model_id,
            model_revision=row.model_revision,
        )
        if row.intent_result_id is not None
        else None
    )
    return CandidateComment(
        message_id=row.id,
        source_id=row.external_message_id,
        text=row.text or "",
        sentiment_result_id=row.sentiment_result_id,
        sentiment_label=row.sentiment_label or "",
        intent_result_id=row.intent_result_id,
        intent_classes=tuple(str(name) for name, _ in ranked),
        commercial_intent=bool(row.commercial_intent),
        intent_version=intent_version,
        followup_status=row.followup_status,
    )


def _new_row(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    candidate: CandidateComment,
    gate_reason: str,
    generator_version: str,
    generated_text: str,
    provenance: DraftProvenance | None,
) -> CommentReplyDraft:
    return CommentReplyDraft(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=candidate.message_id,
        source_id=candidate.source_id,
        sentiment_result_id=candidate.sentiment_result_id,
        # `""` (no sentiment row) is stored as NULL — 0081's sentiment-pair CHECK.
        sentiment_label=candidate.sentiment_label or None,
        gate_reason=gate_reason,
        generator_version=generator_version,
        generated_text=generated_text,
        status="proposed",
        **_provenance_columns(_with_candidate_signal(provenance, candidate)),
    )


class PostgresReplyRepository:
    def list_reply_candidates(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        sentiment_version: AnalysisVersion,
        intent_version: AnalysisVersion | None,
    ) -> tuple[CandidateComment, ...]:
        has_any_draft = (
            select(CommentReplyDraft.id).where(CommentReplyDraft.message_id == Message.id).exists()
        )
        commercial = (
            CommentIntentResult.commercial_intent.is_(True)
            if intent_version is not None
            else false()
        )
        stmt = (
            _candidate_select(sentiment_version=sentiment_version, intent_version=intent_version)
            .where(
                Message.connection_id == connection_id,
                ~has_any_draft,
                or_(CommentSentimentResult.label == "POS", commercial),
            )
            .order_by(Message.posted_at.asc().nulls_last(), Message.id)
        )
        with tenant_session(tenant_id) as session:
            rows = session.execute(stmt).all()
        return tuple(_candidate_from_row(row) for row in rows)

    def get_reply_candidate(
        self,
        *,
        tenant_id: UUID,
        message_id: UUID,
        sentiment_version: AnalysisVersion,
        intent_version: AnalysisVersion | None,
    ) -> CandidateComment | None:
        stmt = _candidate_select(
            sentiment_version=sentiment_version, intent_version=intent_version
        ).where(Message.id == message_id)
        with tenant_session(tenant_id) as session:
            row = session.execute(stmt).first()
        return _candidate_from_row(row) if row is not None else None

    def has_draft(self, *, tenant_id: UUID, message_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            existing = session.execute(
                select(CommentReplyDraft.id).where(CommentReplyDraft.message_id == message_id)
            ).first()
        return existing is not None

    def get_live_draft(self, *, tenant_id: UUID, message_id: UUID) -> DraftRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(CommentReplyDraft).where(
                    CommentReplyDraft.message_id == message_id,
                    CommentReplyDraft.status.not_in(DEAD_STATUSES),
                )
            ).one_or_none()
        return _row_to_record(row) if row is not None else None

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
        provenance: DraftProvenance | None = None,
    ) -> DraftRecord | None:
        row = _new_row(
            tenant_id=tenant_id,
            connection_id=connection_id,
            candidate=candidate,
            gate_reason=gate_reason,
            generator_version=generator_version,
            generated_text=generated_text,
            provenance=provenance,
        )
        with tenant_session(tenant_id) as session:
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                if _is_live_duplicate(exc):
                    return None
                raise
            session.commit()
            session.refresh(row)
            # The candidate already carries the comment's text — no extra query needed
            # to populate `DraftRecord.comment_text` here.
            return _row_to_record(row, comment_text=candidate.text)

    def supersede_draft(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        decided_by_user_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
        provenance: DraftProvenance | None = None,
    ) -> DraftRecord | None:
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            # The guarded UPDATE is the race arbiter: under READ COMMITTED a concurrent
            # second request blocks on the row lock, then re-checks `status = 'proposed'`
            # against the committed discard and matches nothing — so only one request
            # ever reaches the INSERT below.
            discarded = session.execute(
                update(CommentReplyDraft)
                .where(
                    CommentReplyDraft.id == draft_id,
                    CommentReplyDraft.message_id == candidate.message_id,
                    CommentReplyDraft.status == "proposed",
                )
                .values(
                    status="discarded",
                    final_text=None,
                    decided_at=now,
                    decided_by_user_id=decided_by_user_id,
                    settled_at=now,
                )
                .returning(CommentReplyDraft.connection_id)
                .execution_options(synchronize_session=False)
            ).first()
            if discarded is None:
                session.rollback()
                return None
            row = _new_row(
                tenant_id=tenant_id,
                connection_id=discarded.connection_id,
                candidate=candidate,
                gate_reason=gate_reason,
                generator_version=generator_version,
                generated_text=generated_text,
                provenance=provenance,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()  # the discard goes with it: nothing changed
                if _is_live_duplicate(exc):
                    return None
                raise
            session.commit()
            session.refresh(row)
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
        # Every draft ever made per comment, oldest first (live or not).
        self._by_message: dict[UUID, list[UUID]] = {}
        self._candidates: dict[UUID, tuple[CandidateComment, ...]] = {}

    def seed_candidates(
        self, *, connection_id: UUID, candidates: tuple[CandidateComment, ...]
    ) -> None:
        """Test/dev seam — the Memory repo has no `messages`/`comment_sentiment_results`
        tables to query, so a caller populates the candidate list directly.

        QUA-101: unlike `MemorySentimentRepository` (which mirrors `messages` row-by-row,
        `deleted_at` included, because it independently re-derives what a real query
        would compute), this repo works one level of abstraction higher — a caller
        already hands it the exact `CandidateComment` tuple `list_reply_candidates`
        should return, signals included (the gate judges them). Excluding a soft-deleted
        comment is therefore the SEEDING caller's job (simply don't include it), not
        something this method needs to filter — there is no separate "deleted" concept to
        consult here."""
        self._candidates[connection_id] = candidates

    def list_reply_candidates(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        sentiment_version: AnalysisVersion,
        intent_version: AnalysisVersion | None,
    ) -> tuple[CandidateComment, ...]:
        del tenant_id, sentiment_version, intent_version  # seeded candidates are current
        candidates = self._candidates.get(connection_id, ())
        return tuple(c for c in candidates if c.message_id not in self._by_message)

    def get_reply_candidate(
        self,
        *,
        tenant_id: UUID,
        message_id: UUID,
        sentiment_version: AnalysisVersion,
        intent_version: AnalysisVersion | None,
    ) -> CandidateComment | None:
        del tenant_id, sentiment_version, intent_version
        for candidates in self._candidates.values():
            for candidate in candidates:
                if candidate.message_id == message_id:
                    return candidate
        return None

    def supersede_draft(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        decided_by_user_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
        provenance: DraftProvenance | None = None,
    ) -> DraftRecord | None:
        old = self._drafts.get(draft_id)
        if old is None or old.status != "proposed" or old.message_id != candidate.message_id:
            return None
        now = datetime.now(UTC)
        self._drafts[draft_id] = replace(
            old,
            status="discarded",
            final_text=None,
            decided_at=now,
            decided_by_user_id=decided_by_user_id,
            settled_at=now,
        )
        created = self.create_draft(
            tenant_id=tenant_id,
            connection_id=old.connection_id,
            candidate=candidate,
            gate_reason=gate_reason,
            generator_version=generator_version,
            generated_text=generated_text,
            provenance=provenance,
        )
        if created is None:  # another live draft holds the comment: undo, change nothing
            self._drafts[draft_id] = old
        return created

    def has_draft(self, *, tenant_id: UUID, message_id: UUID) -> bool:
        del tenant_id
        return bool(self._by_message.get(message_id))

    def get_live_draft(self, *, tenant_id: UUID, message_id: UUID) -> DraftRecord | None:
        del tenant_id
        for draft_id in self._by_message.get(message_id, []):
            record = self._drafts[draft_id]
            if record.is_live:
                return record
        return None

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        gate_reason: str,
        generator_version: str,
        generated_text: str,
        provenance: DraftProvenance | None = None,
    ) -> DraftRecord | None:
        if self.get_live_draft(tenant_id=tenant_id, message_id=candidate.message_id):
            return None
        p = _with_candidate_signal(provenance, candidate)
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
            grounding=dict(p.grounding) if p.grounding is not None else None,
            needs_review=p.needs_review,
            unsupported_claims=tuple(p.unsupported_claims or ()),
            model_id=p.model_id,
            model_revision=p.model_revision,
            input_tokens=p.input_tokens,
            output_tokens=p.output_tokens,
            cost_usd=p.cost_usd,
            intent_result_id=p.intent_result_id,
        )
        self._drafts[record.id] = record
        self._by_message.setdefault(candidate.message_id, []).append(record.id)
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
