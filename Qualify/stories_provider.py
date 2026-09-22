"""The seam between the Stories screens and the real `qualify_api.stories` backend
(QUA-106). Same split `replies_provider.py`/`publishing_provider.py` establish: direct
in-process projections over the published seam — no HTTP hop, same posture
`http/app.py`'s own module docstring documents for the Reflex CRM in general.

`active_connections` is NOT duplicated here — `publishing_provider.active_connections`
already does exactly this read (the tenant's connections that can receive a publish
right now); `stories_state.py` imports it directly.
"""

from __future__ import annotations

from typing import IO
from uuid import UUID

from qualify_api.stories import ProposalRecord
from qualify_api.stories import decide_proposal as _decide_proposal
from qualify_api.stories import get_proposal as _get_proposal
from qualify_api.stories import list_proposals as _list_proposals
from qualify_api.stories import publish_proposal as _publish_proposal
from qualify_api.stories import refresh_proposal as _refresh_proposal
from qualify_api.stories import stage_and_propose_story as _stage_and_propose_story
from qualify_api.stories import suggest_trend_audio as _suggest_trend_audio
from qualify_api.stories.trend_audio_client import TrendAudioOption

from .stories_vm import StoryProposalVM, TrendAudioOptionVM, build_proposal_vm, build_trend_audio_vm

__all__ = [
    "decide_proposal",
    "get_proposal",
    "list_proposals",
    "propose_story",
    "publish_proposal",
    "refresh_proposal",
    "suggest_trend_audio",
]


def _to_vm(record: ProposalRecord) -> StoryProposalVM:
    return build_proposal_vm(
        id=str(record.id),
        connection_id=str(record.connection_id),
        caption=record.display_caption,
        trend_audio_id=record.trend_audio_id or "",
        trend_audio_title=record.trend_audio_title or "",
        status=record.status,
        publish_error_code=record.publish_error_code or "",
        created_label=record.created_at.strftime("%d %b %Y, %H:%M"),
    )


def _trend_to_vm(option: TrendAudioOption) -> TrendAudioOptionVM:
    return build_trend_audio_vm(
        audio_id=option.audio_id,
        title=option.title,
        artist_or_creator=option.artist_or_creator,
        duration_ms=option.duration_ms,
        rank=option.rank,
        preview_url=option.preview_url,
    )


def list_proposals(tenant_id: UUID) -> list[StoryProposalVM]:
    """Blocking DB call — callers on the event loop must run it off-thread, same
    convention `publishing_provider.active_connections` already documents."""
    return [_to_vm(p) for p in _list_proposals(tenant_id=tenant_id)]


def get_proposal(*, tenant_id: UUID, proposal_id: UUID) -> StoryProposalVM:
    """Raises `UnknownProposal` — NOT caught here, same posture
    `publishing_provider`'s own reads let `UnknownConnection`/`UnknownAttempt`
    propagate."""
    return _to_vm(_get_proposal(tenant_id=tenant_id, proposal_id=proposal_id))


async def propose_story(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    fileobj: IO[bytes],
    content_type: str,
    caption: str,
    trend_audio_id: str = "",
    trend_audio_title: str = "",
) -> StoryProposalVM:
    """Stage the operator's own upload (the ONLY media source in this v1) and write
    the proposal row. Already `async def` — the one blocking call (R2) is wrapped in
    `asyncio.to_thread` INSIDE the seam (`qualify_api.stories.composition`), same
    posture `publishing_provider.start_publish` documents for its own staging call."""
    record = await _stage_and_propose_story(
        tenant_id=tenant_id,
        connection_id=connection_id,
        fileobj=fileobj,
        content_type=content_type,
        caption=caption or None,
        trend_audio_id=trend_audio_id or None,
        trend_audio_title=trend_audio_title or None,
    )
    return _to_vm(record)


def decide_proposal(
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    decision: str,
    final_caption: str | None,
    decided_by_user_id: UUID,
) -> StoryProposalVM:
    """`decision` in `('approved', 'edited', 'rejected')`. Blocking DB call. Raises
    `ValueError` if the proposal is not `'proposed'` (already decided)."""
    return _to_vm(
        _decide_proposal(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            decision=decision,
            final_caption=final_caption,
            decided_by_user_id=decided_by_user_id,
        )
    )


async def publish_proposal(*, tenant_id: UUID, proposal_id: UUID) -> StoryProposalVM:
    """The real write to Meta — `async def`, same posture `publishing_provider.
    start_publish`/`replies_provider.send_draft` have for their own Meta calls. Only
    reachable for an `'approved'`/`'edited'` proposal; raises `ValueError` otherwise
    and `UnknownProposal` if the id is not visible to this tenant — both propagate."""
    record = await _publish_proposal(tenant_id=tenant_id, proposal_id=proposal_id)
    return _to_vm(record)


async def refresh_proposal(*, tenant_id: UUID, proposal_id: UUID) -> StoryProposalVM:
    """One `PublishService.advance()` step, mirrored onto the proposal — the
    client-driven poll, same shape `publishing_provider.poll_publish` already has."""
    record = await _refresh_proposal(tenant_id=tenant_id, proposal_id=proposal_id)
    return _to_vm(record)


async def suggest_trend_audio(
    *, tenant_id: UUID, connection_id: UUID, audio_type: str = "music"
) -> list[TrendAudioOptionVM]:
    """Never raises — a failed lookup is an empty list (see `StoryProposalService.
    suggest_trend_audio`'s own degrade-don't-block posture)."""
    options = await _suggest_trend_audio(
        tenant_id=tenant_id, connection_id=connection_id, audio_type=audio_type
    )
    return [_trend_to_vm(o) for o in options]
