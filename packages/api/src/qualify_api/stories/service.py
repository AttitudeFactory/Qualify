"""The Story-proposal service (QUA-106, first slice): propose -> decide -> publish.

**No code path from `'proposed'` straight into `publish()`.** Same structural
guarantee `ReplyService.send()` documents for its own module: `publish()` refuses
(raises `ValueError`) any proposal not already `'approved'`/`'edited'` by a human.
There is no autonomous trigger anywhere in this module — every method here runs only
when a caller (the HTTP route, or the Reflex provider) invokes it.

**Publishing itself is NOT reimplemented here.** `publish()`/`refresh()` are thin
callers of the EXISTING `qualify_api.publishing.PublishService` — the write-ahead,
container polling, reconciliation and "never a blind retry on send" guarantees all
stay exactly where they already live. This module only ever remembers WHICH
`publish_attempts` row a proposal started (`publish_attempt_id`) and copies that row's
eventual verdict (`published`/`failed`) back onto the proposal — it never re-derives
Meta's state on its own.

**`suggest_trend_audio` never blocks a proposal.** A `TrendAudioError` (network,
permission, anything) degrades to an empty tuple — Meta's trending-audio list is a
reference for the human, not a dependency the propose/decide/publish flow needs.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from qualify_api.publishing.client import MEDIA_TYPE_STORIES
from qualify_api.publishing.service import (
    ConnectionTarget,
    ConnectionTargetReader,
    PublishService,
    UnknownConnection,
)
from qualify_api.stories.repository import ProposalRecord, StoryProposalRepository, UnknownProposal
from qualify_api.stories.trend_audio_client import (
    AUDIO_TYPE_MUSIC,
    TrendAudioClient,
    TrendAudioError,
    TrendAudioOption,
)

__all__ = [
    "StoryProposalService",
    "TrendAudioClientFactory",
    "UnknownConnection",
    "UnknownProposal",
]


class TrendAudioClientFactory(Protocol):
    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> TrendAudioClient: ...


def _idempotency_key(proposal_id: UUID) -> str:
    """Deterministic per proposal — calling `publish()` twice on the SAME proposal
    (a double click, a retried request) converges on the SAME `publish_attempts` row
    via `PublishService.start()`'s own idempotency guarantee, never a second publish.
    The proposal's own status guard (only `'approved'`/`'edited'` may reach this) is
    the first line of defense; this key is the second, at the Meta-call layer."""
    return f"story-proposal:{proposal_id}"


class StoryProposalService:
    def __init__(
        self,
        *,
        repository: StoryProposalRepository,
        publish_service: PublishService,
        connections: ConnectionTargetReader,
        trend_client_factory: TrendAudioClientFactory | None = None,
    ) -> None:
        self._repo = repository
        self._publish = publish_service
        self._connections = connections
        self._trend_clients = trend_client_factory

    def propose(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        media_object_key: str,
        media_content_type: str,
        caption: str | None,
        trend_audio_id: str | None = None,
        trend_audio_title: str | None = None,
    ) -> ProposalRecord:
        return self._repo.propose(
            tenant_id=tenant_id,
            connection_id=connection_id,
            media_object_key=media_object_key,
            media_content_type=media_content_type,
            caption=caption,
            trend_audio_id=trend_audio_id,
            trend_audio_title=trend_audio_title,
        )

    def get(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
        record = self._repo.get(tenant_id=tenant_id, proposal_id=proposal_id)
        if record is None:
            raise UnknownProposal(str(proposal_id))
        return record

    def list_proposals(self, *, tenant_id: UUID) -> tuple[ProposalRecord, ...]:
        return self._repo.list_proposals(tenant_id=tenant_id)

    def list_pending(self, *, tenant_id: UUID, connection_id: UUID) -> tuple[ProposalRecord, ...]:
        return self._repo.list_pending(tenant_id=tenant_id, connection_id=connection_id)

    def decide(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        decision: str,
        final_caption: str | None,
        decided_by_user_id: UUID,
    ) -> ProposalRecord:
        """`decision` in `('approved', 'edited', 'rejected')` — every proposal records
        which of the three a human chose, mirroring QUA-22's own criterion for
        replies."""
        return self._repo.decide(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            decision=decision,
            final_caption=final_caption,
            decided_by_user_id=decided_by_user_id,
        )

    async def publish(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
        """The one transition here that reaches Meta. Never called on a proposal that
        has not been `approved`/`edited` by a human — structurally enforced, not just
        documented: there is no branch in this method that accepts `'proposed'`."""
        record = self.get(tenant_id=tenant_id, proposal_id=proposal_id)
        if record.status not in ("approved", "edited"):
            raise ValueError(f"proposal {proposal_id} is {record.status!r}, cannot publish")

        state = await self._publish.start(
            tenant_id=tenant_id,
            connection_id=record.connection_id,
            media_object_key=record.media_object_key,
            media_product_type=MEDIA_TYPE_STORIES,
            idempotency_key=_idempotency_key(proposal_id),
            caption=record.display_caption or None,
        )
        return self._repo.mark_publishing(
            tenant_id=tenant_id, proposal_id=proposal_id, publish_attempt_id=state.attempt_id
        )

    async def refresh(self, *, tenant_id: UUID, proposal_id: UUID) -> ProposalRecord:
        """One `PublishService.advance()` step for the linked attempt, mirrored back
        onto the proposal. A no-op — returns the row unchanged — for a proposal that
        is not currently `'publishing'`, same "idempotent, reads from the row" posture
        `PublishService._advance` itself already has for a settled attempt."""
        record = self.get(tenant_id=tenant_id, proposal_id=proposal_id)
        if record.status != "publishing" or record.publish_attempt_id is None:
            return record

        state = await self._publish.advance(
            tenant_id=tenant_id, attempt_id=record.publish_attempt_id
        )
        if state.status == "published":
            return self._repo.mark_published(tenant_id=tenant_id, proposal_id=proposal_id)
        if state.status == "failed":
            return self._repo.mark_publish_failed(
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                error_code=state.reason or "unknown",
            )
        # uploading / processing — Meta is still working; nothing to settle yet.
        return record

    async def suggest_trend_audio(
        self, *, tenant_id: UUID, connection_id: UUID, audio_type: str = AUDIO_TYPE_MUSIC
    ) -> tuple[TrendAudioOption, ...]:
        """Best-effort reference list — see module docstring. Returns `()` rather than
        raising for every failure mode (no client factory configured, unknown
        connection, `TrendAudioError`): the propose/decide/publish flow must never be
        blocked by a trending-audio lookup failing."""
        if self._trend_clients is None:
            return ()
        target: ConnectionTarget | None = self._connections.read(
            tenant_id=tenant_id, connection_id=connection_id
        )
        if target is None:
            return ()
        try:
            client = await self._trend_clients.client_for(
                tenant_id=tenant_id, connection_id=connection_id
            )
            return await client.trending_audio(ig_user_id=target.ig_user_id, audio_type=audio_type)
        except TrendAudioError:
            return ()
