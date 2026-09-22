"""HTTP routes for QUA-106's Story proposals — mirrors `replies_routes.py`'s shape:
Principal-based identity (C1), a `Depends` per seam that raises until wired at app
assembly, typed errors mapped to status codes.

Five routes: propose (stages the operator's upload + writes the row), list (the
`/stories` screen), decide (human approves/edits/rejects — the ONLY route that may
transition a `'proposed'` proposal), publish (the real Meta call, only reachable for
`approved`/`edited`), and read (one `refresh()` step, the client-driven poll — same
shape `GET /api/publishing/attempts/{id}` already has).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from qualify_shared.objects.gate import ObjectSizeExceeded
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.http.deps import Principal, current_principal
from qualify_api.stories.repository import ProposalRecord, UnknownProposal
from qualify_api.stories.trend_audio_client import TrendAudioOption

router = APIRouter(prefix="/api", tags=["stories"])

ProposeStory = Callable[..., Coroutine[Any, Any, ProposalRecord]]
ListProposals = Callable[..., tuple[ProposalRecord, ...]]
DecideProposal = Callable[..., ProposalRecord]
PublishProposal = Callable[..., Coroutine[Any, Any, ProposalRecord]]
RefreshProposal = Callable[..., Coroutine[Any, Any, ProposalRecord]]
SuggestTrendAudio = Callable[..., Coroutine[Any, Any, tuple[TrendAudioOption, ...]]]


def get_propose_story() -> ProposeStory:
    raise NotImplementedError("story-proposal creation dependency is not configured")


def get_list_proposals() -> ListProposals:
    raise NotImplementedError("story-proposal listing dependency is not configured")


def get_decide_proposal() -> DecideProposal:
    raise NotImplementedError("story-proposal decision dependency is not configured")


def get_publish_proposal() -> PublishProposal:
    raise NotImplementedError("story-proposal publish dependency is not configured")


def get_refresh_proposal() -> RefreshProposal:
    raise NotImplementedError("story-proposal refresh dependency is not configured")


def get_suggest_trend_audio() -> SuggestTrendAudio:
    raise NotImplementedError("trend-audio suggestion dependency is not configured")


class ProposalView(BaseModel):
    """One proposal, as the Reflex/HTTP caller sees it — a flat projection of
    `ProposalRecord`, never the ORM row."""

    id: UUID
    connection_id: UUID
    media_object_key: str
    caption: str
    trend_audio_id: str
    trend_audio_title: str
    status: str
    publish_attempt_id: UUID | None
    publish_error_code: str
    created_at: str


def _to_view(record: ProposalRecord) -> ProposalView:
    return ProposalView(
        id=record.id,
        connection_id=record.connection_id,
        media_object_key=record.media_object_key,
        caption=record.display_caption,
        trend_audio_id=record.trend_audio_id or "",
        trend_audio_title=record.trend_audio_title or "",
        status=record.status,
        publish_attempt_id=record.publish_attempt_id,
        publish_error_code=record.publish_error_code or "",
        created_at=record.created_at.isoformat(),
    )


class TrendAudioOptionView(BaseModel):
    audio_id: str
    title: str
    artist_or_creator: str
    audio_type: str
    duration_ms: int | None
    rank: int


def _trend_to_view(option: TrendAudioOption) -> TrendAudioOptionView:
    return TrendAudioOptionView(
        audio_id=option.audio_id,
        title=option.title,
        artist_or_creator=option.artist_or_creator,
        audio_type=option.audio_type,
        duration_ms=option.duration_ms,
        rank=option.rank,
    )


class DecideRequest(BaseModel):
    decision: Literal["approved", "edited", "rejected"]
    # Required when decision == "edited"; ignored otherwise — same posture
    # `replies_routes.DecideRequest` already takes for its own `final_text`.
    final_caption: str | None = None


class DecideResponse(BaseModel):
    proposal: ProposalView


class PublishResponse(BaseModel):
    proposal: ProposalView


@router.post("/story-proposals", response_model=ProposalView, status_code=201)
async def propose(
    connection_id: UUID = Form(...),
    caption: str = Form(""),
    trend_audio_id: str = Form(""),
    trend_audio_title: str = Form(""),
    file: UploadFile = File(...),
    principal: Principal = Depends(current_principal),
    propose_story: ProposeStory = Depends(get_propose_story),
) -> ProposalView:
    """Bytes land durably (R2) BEFORE the row exists — same A3 guarantee `POST
    /api/media` already gives a regular publish."""
    try:
        record = await propose_story(
            tenant_id=principal.tenant_id,
            connection_id=connection_id,
            fileobj=file.file,
            content_type=file.content_type or "",
            caption=caption or None,
            trend_audio_id=trend_audio_id or None,
            trend_audio_title=trend_audio_title or None,
        )
    except ObjectSizeExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except (ValueError, TenantPrefixViolation) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _to_view(record)


@router.get("/story-proposals", response_model=list[ProposalView])
def list_all(
    principal: Principal = Depends(current_principal),
    list_proposals: ListProposals = Depends(get_list_proposals),
) -> list[ProposalView]:
    return [_to_view(p) for p in list_proposals(tenant_id=principal.tenant_id)]


@router.get("/story-proposals/trend-audio", response_model=list[TrendAudioOptionView])
async def trend_audio(
    connection_id: UUID,
    audio_type: str = "music",
    principal: Principal = Depends(current_principal),
    suggest: SuggestTrendAudio = Depends(get_suggest_trend_audio),
) -> list[TrendAudioOptionView]:
    """Never errors to the caller — a failed/empty lookup is a normal, empty list
    (see `StoryProposalService.suggest_trend_audio`'s own degrade-don't-block
    posture)."""
    options = await suggest(
        tenant_id=principal.tenant_id, connection_id=connection_id, audio_type=audio_type
    )
    return [_trend_to_view(o) for o in options]


@router.post("/story-proposals/{proposal_id}/decide", response_model=DecideResponse)
def decide(
    proposal_id: UUID,
    body: DecideRequest,
    principal: Principal = Depends(current_principal),
    decide_proposal: DecideProposal = Depends(get_decide_proposal),
) -> DecideResponse:
    if body.decision == "edited" and not body.final_caption:
        raise HTTPException(
            status_code=422, detail="final_caption is required for an edited decision"
        )
    try:
        record = decide_proposal(
            tenant_id=principal.tenant_id,
            proposal_id=proposal_id,
            decision=body.decision,
            final_caption=body.final_caption,
            decided_by_user_id=principal.user_id,
        )
    except UnknownProposal:
        raise HTTPException(status_code=404, detail="unknown proposal") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return DecideResponse(proposal=_to_view(record))


@router.post("/story-proposals/{proposal_id}/publish", response_model=PublishResponse)
async def publish(
    proposal_id: UUID,
    principal: Principal = Depends(current_principal),
    publish_proposal: PublishProposal = Depends(get_publish_proposal),
) -> PublishResponse:
    """The real write to Meta. Only reachable for an `'approved'`/`'edited'` proposal —
    QUA-106's mandatory-human-approval requirement has no code path from `/story-
    proposals` (propose) straight to this route."""
    try:
        record = await publish_proposal(tenant_id=principal.tenant_id, proposal_id=proposal_id)
    except UnknownProposal:
        raise HTTPException(status_code=404, detail="unknown proposal") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return PublishResponse(proposal=_to_view(record))


@router.get("/story-proposals/{proposal_id}", response_model=ProposalView)
async def read(
    proposal_id: UUID,
    principal: Principal = Depends(current_principal),
    refresh_proposal: RefreshProposal = Depends(get_refresh_proposal),
) -> ProposalView:
    """One `refresh()` step per GET — never a wait. Same client-driven-poll shape `GET
    /api/publishing/attempts/{id}` already has."""
    try:
        record = await refresh_proposal(tenant_id=principal.tenant_id, proposal_id=proposal_id)
    except UnknownProposal:
        raise HTTPException(status_code=404, detail="unknown proposal") from None
    return _to_view(record)
