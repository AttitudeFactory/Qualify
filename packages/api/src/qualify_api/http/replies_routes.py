"""HTTP routes for QUA-22's comments tranche — mirrors `sentiment_routes.py`'s shape:
Principal-based identity (C1), a `Depends` per seam that raises until wired at app
assembly, typed errors mapped to status codes.

Four routes, one per stage of the pipeline documented in `replies/__init__.py`:
generate (manual trigger, same posture `POST /api/sentiment/analyze` already has),
list pending (the review queue), decide (human approves/edits/discards), send (the one
transition forbidden a blind retry).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.http.deps import Principal, current_principal
from qualify_api.replies.repository import DraftRecord
from qualify_api.replies.service import DecisionResult, GenerationSummary, UnknownDraft

router = APIRouter(prefix="/api", tags=["replies"])

GenerateDrafts = Callable[..., GenerationSummary]
ListPendingDrafts = Callable[..., tuple[DraftRecord, ...]]
DecideDraft = Callable[..., DecisionResult]
SendDraft = Callable[..., object]


def get_generate_drafts() -> GenerateDrafts:
    raise NotImplementedError("reply-draft generation dependency is not configured")


def get_list_pending_drafts() -> ListPendingDrafts:
    raise NotImplementedError("reply-draft listing dependency is not configured")


def get_decide_draft() -> DecideDraft:
    raise NotImplementedError("reply-draft decision dependency is not configured")


def get_send_draft() -> SendDraft:
    raise NotImplementedError("reply-draft send dependency is not configured")


class GenerateRequest(BaseModel):
    connection_id: UUID


class GenerateResponse(BaseModel):
    candidates_seen: int
    drafts_created: int
    gate_rejected: int


class DraftView(BaseModel):
    """One draft, as the Reflex/HTTP caller sees it — a flat projection of
    `DraftRecord`, never the ORM row."""

    id: UUID
    message_id: UUID
    source_id: str
    sentiment_label: str
    comment_text: str
    generated_text: str
    final_text: str | None
    status: str
    created_at: str


def _to_view(record: DraftRecord) -> DraftView:
    return DraftView(
        id=record.id,
        message_id=record.message_id,
        source_id=record.source_id,
        sentiment_label=record.sentiment_label,
        comment_text=record.comment_text,
        generated_text=record.generated_text,
        final_text=record.final_text,
        status=record.status,
        created_at=record.created_at.isoformat(),
    )


class DecideRequest(BaseModel):
    decision: Literal["accepted", "edited", "discarded"]
    # Required when decision == "edited"; ignored otherwise (the route validates this,
    # the service/repository do not re-derive it).
    final_text: str | None = None


class DecideResponse(BaseModel):
    draft: DraftView
    diff: list[str]


class SendResponse(BaseModel):
    draft: DraftView


@router.post("/replies/generate", response_model=GenerateResponse)
def generate(
    body: GenerateRequest,
    principal: Principal = Depends(current_principal),
    generate_drafts: GenerateDrafts = Depends(get_generate_drafts),
) -> GenerateResponse:
    """Runs ONE generation pass over pending POS comments for one connection. Same
    idempotency posture `analyze_sentiment` documents: `UNIQUE(message_id)` means a
    comment that already has a draft is simply skipped, never re-generated — calling
    this twice in a row is safe."""
    summary = generate_drafts(tenant_id=principal.tenant_id, connection_id=body.connection_id)
    return GenerateResponse(
        candidates_seen=summary.candidates_seen,
        drafts_created=summary.drafts_created,
        gate_rejected=summary.gate_rejected,
    )


@router.get("/replies/pending", response_model=list[DraftView])
def list_pending(
    connection_id: UUID,
    principal: Principal = Depends(current_principal),
    list_drafts: ListPendingDrafts = Depends(get_list_pending_drafts),
) -> list[DraftView]:
    drafts = list_drafts(tenant_id=principal.tenant_id, connection_id=connection_id)
    return [_to_view(d) for d in drafts]


@router.post("/replies/{draft_id}/decide", response_model=DecideResponse)
def decide(
    draft_id: UUID,
    body: DecideRequest,
    principal: Principal = Depends(current_principal),
    decide_draft: DecideDraft = Depends(get_decide_draft),
) -> DecideResponse:
    """QUA-22's own criterion: every draft records aceptado/editado/descartado —
    enforced here as the ONLY route that may transition a `'proposed'` draft, and as a
    `Literal` on the request body so an invalid decision is a 422, not a 500 from a
    `ValueError` three layers down."""
    if body.decision == "edited" and not body.final_text:
        raise HTTPException(status_code=422, detail="final_text is required for an edited decision")
    try:
        result = decide_draft(
            tenant_id=principal.tenant_id,
            draft_id=draft_id,
            decision=body.decision,
            final_text=body.final_text,
            decided_by_user_id=principal.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return DecideResponse(draft=_to_view(result.draft), diff=list(result.diff))


@router.post("/replies/{draft_id}/send", response_model=SendResponse)
async def send(
    draft_id: UUID,
    principal: Principal = Depends(current_principal),
    send_draft: SendDraft = Depends(get_send_draft),
) -> SendResponse:
    """The real write to Meta. Only reachable for an `'accepted'`/`'edited'` draft —
    QUA-22's "ninguna respuesta se envía sin acción humana explícita" has no code path
    from `/generate` straight to this route. The authenticated person's request IS the
    approval (m-24789645): it becomes a `HumanApproval` naming this draft, the object
    `ReplyService.send` demands."""
    approval = HumanApproval(
        user_id=principal.user_id, approved_at=datetime.now(UTC), draft_id=draft_id
    )
    try:
        record = await send_draft(
            tenant_id=principal.tenant_id, draft_id=draft_id, approval=approval
        )
    except ApprovalRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except UnknownDraft:
        raise HTTPException(status_code=404, detail="unknown draft") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return SendResponse(draft=_to_view(record))
