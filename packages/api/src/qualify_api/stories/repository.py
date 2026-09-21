"""Persistence for QUA-106's Story-proposal lifecycle (`story_proposals`, migration
0021). Same two-implementation discipline `replies/repository.py` establishes —
`MemoryStoryProposalRepository` is real production-usable code (the offline test suite,
any in-process dev path), not a second, drifting mock of `PostgresStoryProposalRepository`.

**Lifecycle, in one sentence:** `proposed` (write-ahead, right after staging) ->
`approved`/`edited`/`rejected` (human decision) -> for a non-rejected decision only,
`publishing` (write-ahead, right after `PublishService.start()` is called) ->
`published`/`publish_failed` (terminal, `settled_at` set, copied from the linked
`publish_attempts` row's own verdict by `StoryProposalService.refresh()`). `rejected` is
terminal directly from `proposed`.

**Idempotency.** Unlike `comment_reply_drafts`, there is no natural dedup key for a
Story proposal (no "one draft per comment" — every proposal is its own operator-
initiated act), so `propose()` always creates a new row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.stories.models import StoryProposal

#: Decisions a human may record against a `'proposed'` proposal.
DECISIONS = ("approved", "edited", "rejected")
#: Terminal statuses — `settled_at` is non-null for exactly these (mirrors migration
#: 0021's own `ck_story_proposal_settled_matches_status`).
TERMINAL_STATUSES = ("rejected", "published", "publish_failed")


@dataclass(frozen=True)
class ProposalRecord:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    media_object_key: str
    media_content_type: str
    caption: str | None
    final_caption: str | None
    trend_audio_id: str | None
    trend_audio_title: str | None
    status: str
    publish_attempt_id: UUID | None
    publish_error_code: str | None
    created_at: datetime
    decided_at: datetime | None
    decided_by_user_id: UUID | None
    settled_at: datetime | None

    @property
    def is_settled(self) -> bool:
        return self.settled_at is not None

    @property
    def display_caption(self) -> str:
        """What a human sees/edits — the decided text once there is one, the proposed
        text before that. Never a third, independently-stored copy."""
        return self.final_caption if self.final_caption is not None else (self.caption or "")


class UnknownProposal(Exception):
    """No `story_proposals` row with that id is visible in this tenant (missing or
    RLS-filtered — indistinguishable on purpose, same as `UnknownConnection`)."""


class StoryProposalRepository(Protocol):
    def propose(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        media_object_key: str,
        media_content_type: str,
        caption: str | None,
        trend_audio_id: str | None,
        trend_audio_title: str | None,
    ) -> ProposalRecord: ...

    def get(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord | None: ...

    def list_proposals(self, *, tenant_id: UUID) -> tuple[ProposalRecord, ...]:
        """Every proposal for the tenant, most recent first — the `/stories` list."""
        ...

    def list_pending(self, *, tenant_id: UUID, connection_id: UUID) -> tuple[ProposalRecord, ...]:
        """`status = 'proposed'` only — the human review queue for one connection."""
        ...

    def decide(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        decision: str,
        final_caption: str | None,
        decided_by_user_id: UUID,
    ) -> ProposalRecord:
        """`decision` in `DECISIONS`. Raises `ValueError` if the proposal is not
        `'proposed'` — a decision is made exactly once."""
        ...

    def mark_publishing(
        self, *, tenant_id: UUID, proposal_id: UUID, publish_attempt_id: UUID
    ) -> ProposalRecord:
        """Write-ahead marker, unsettled. Raises `ValueError` if the proposal is not
        `'approved'`/`'edited'`."""
        ...

    def mark_published(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord: ...

    def mark_publish_failed(
        self, *, tenant_id: UUID, proposal_id: UUID, error_code: str
    ) -> ProposalRecord: ...


def _row_to_record(row: StoryProposal) -> ProposalRecord:
    return ProposalRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        connection_id=row.connection_id,
        media_object_key=row.media_object_key,
        media_content_type=row.media_content_type,
        caption=row.caption,
        final_caption=row.final_caption,
        trend_audio_id=row.trend_audio_id,
        trend_audio_title=row.trend_audio_title,
        status=row.status,
        publish_attempt_id=row.publish_attempt_id,
        publish_error_code=row.publish_error_code,
        created_at=row.created_at,
        decided_at=row.decided_at,
        decided_by_user_id=row.decided_by_user_id,
        settled_at=row.settled_at,
    )


class PostgresStoryProposalRepository:
    def propose(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        media_object_key: str,
        media_content_type: str,
        caption: str | None,
        trend_audio_id: str | None,
        trend_audio_title: str | None,
    ) -> ProposalRecord:
        row = StoryProposal(
            tenant_id=tenant_id,
            connection_id=connection_id,
            media_object_key=media_object_key,
            media_content_type=media_content_type,
            caption=caption,
            trend_audio_id=trend_audio_id,
            trend_audio_title=trend_audio_title,
            status="proposed",
        )
        with tenant_session(tenant_id) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def get(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(StoryProposal, proposal_id)
        return _row_to_record(row) if row is not None else None

    def list_proposals(self, *, tenant_id: UUID) -> tuple[ProposalRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = (
                session.execute(select(StoryProposal).order_by(StoryProposal.created_at.desc()))
                .scalars()
                .all()
            )
        return tuple(_row_to_record(r) for r in rows)

    def list_pending(self, *, tenant_id: UUID, connection_id: UUID) -> tuple[ProposalRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = (
                session.execute(
                    select(StoryProposal)
                    .where(
                        StoryProposal.connection_id == connection_id,
                        StoryProposal.status == "proposed",
                    )
                    .order_by(StoryProposal.created_at)
                )
                .scalars()
                .all()
            )
        return tuple(_row_to_record(r) for r in rows)

    def _require(self, session, tenant_id: UUID, proposal_id: UUID) -> StoryProposal:
        row = session.get(StoryProposal, proposal_id)
        if row is None:
            raise UnknownProposal(str(proposal_id))
        return row

    def decide(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        decision: str,
        final_caption: str | None,
        decided_by_user_id: UUID,
    ) -> ProposalRecord:
        if decision not in DECISIONS:
            raise ValueError(f"invalid decision {decision!r}")
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, proposal_id)
            if row.status != "proposed":
                raise ValueError(
                    f"proposal {proposal_id} is {row.status!r}, not 'proposed' — already decided"
                )
            row.status = decision
            row.final_caption = None if decision == "rejected" else (final_caption or row.caption)
            row.decided_at = datetime.now(UTC)
            row.decided_by_user_id = decided_by_user_id
            if decision == "rejected":
                row.settled_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def mark_publishing(
        self, *, tenant_id: UUID, proposal_id: UUID, publish_attempt_id: UUID
    ) -> ProposalRecord:
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, proposal_id)
            if row.status not in ("approved", "edited"):
                raise ValueError(f"proposal {proposal_id} is {row.status!r}, cannot publish")
            row.status = "publishing"
            row.publish_attempt_id = publish_attempt_id
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def mark_published(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, proposal_id)
            row.status = "published"
            row.settled_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)

    def mark_publish_failed(
        self, *, tenant_id: UUID, proposal_id: UUID, error_code: str
    ) -> ProposalRecord:
        with tenant_session(tenant_id) as session:
            row = self._require(session, tenant_id, proposal_id)
            row.status = "publish_failed"
            row.publish_error_code = error_code
            row.settled_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)


class MemoryStoryProposalRepository:
    """Real production-usable implementation over a plain dict — same role
    `MemoryReplyRepository` plays for its own module: the offline test suite's
    repository, not a second drifting mock."""

    def __init__(self) -> None:
        self._proposals: dict[UUID, ProposalRecord] = {}

    def propose(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        media_object_key: str,
        media_content_type: str,
        caption: str | None,
        trend_audio_id: str | None,
        trend_audio_title: str | None,
    ) -> ProposalRecord:
        record = ProposalRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            media_object_key=media_object_key,
            media_content_type=media_content_type,
            caption=caption,
            final_caption=None,
            trend_audio_id=trend_audio_id,
            trend_audio_title=trend_audio_title,
            status="proposed",
            publish_attempt_id=None,
            publish_error_code=None,
            created_at=datetime.now(UTC),
            decided_at=None,
            decided_by_user_id=None,
            settled_at=None,
        )
        self._proposals[record.id] = record
        return record

    def get(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord | None:
        del tenant_id
        return self._proposals.get(proposal_id)

    def list_proposals(self, *, tenant_id: UUID) -> tuple[ProposalRecord, ...]:
        del tenant_id
        return tuple(sorted(self._proposals.values(), key=lambda p: p.created_at, reverse=True))

    def list_pending(self, *, tenant_id: UUID, connection_id: UUID) -> tuple[ProposalRecord, ...]:
        del tenant_id
        return tuple(
            p
            for p in self._proposals.values()
            if p.connection_id == connection_id and p.status == "proposed"
        )

    def _require(self, proposal_id: UUID) -> ProposalRecord:
        record = self._proposals.get(proposal_id)
        if record is None:
            raise UnknownProposal(str(proposal_id))
        return record

    def decide(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        decision: str,
        final_caption: str | None,
        decided_by_user_id: UUID,
    ) -> ProposalRecord:
        del tenant_id
        if decision not in DECISIONS:
            raise ValueError(f"invalid decision {decision!r}")
        record = self._require(proposal_id)
        if record.status != "proposed":
            raise ValueError(f"proposal {proposal_id} is {record.status!r}, not 'proposed'")
        updated = replace(
            record,
            status=decision,
            final_caption=None if decision == "rejected" else (final_caption or record.caption),
            decided_at=datetime.now(UTC),
            decided_by_user_id=decided_by_user_id,
            settled_at=datetime.now(UTC) if decision == "rejected" else record.settled_at,
        )
        self._proposals[proposal_id] = updated
        return updated

    def mark_publishing(
        self, *, tenant_id: UUID, proposal_id: UUID, publish_attempt_id: UUID
    ) -> ProposalRecord:
        del tenant_id
        record = self._require(proposal_id)
        if record.status not in ("approved", "edited"):
            raise ValueError(f"proposal {proposal_id} is {record.status!r}, cannot publish")
        updated = replace(record, status="publishing", publish_attempt_id=publish_attempt_id)
        self._proposals[proposal_id] = updated
        return updated

    def mark_published(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
        del tenant_id
        record = self._require(proposal_id)
        updated = replace(record, status="published", settled_at=datetime.now(UTC))
        self._proposals[proposal_id] = updated
        return updated

    def mark_publish_failed(
        self, *, tenant_id: UUID, proposal_id: UUID, error_code: str
    ) -> ProposalRecord:
        del tenant_id
        record = self._require(proposal_id)
        updated = replace(
            record,
            status="publish_failed",
            publish_error_code=error_code,
            settled_at=datetime.now(UTC),
        )
        self._proposals[proposal_id] = updated
        return updated
