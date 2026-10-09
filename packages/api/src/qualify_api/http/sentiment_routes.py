"""HTTP route for the manual sentiment-analysis trigger (QUA-21) — mirrors
`inbox_routes.py`'s shape exactly: Principal-based identity (C1), a `Depends` that
raises until wired at app assembly, typed errors mapped to status codes.

Deliberately manual and deliberately not chained after `POST /api/inbox/sync` —
that is a separate, explicit design decision this route does not make on its own.
The handler is a plain `def`, not `async def`: `analyze_pending_comments` is
synchronous (no network I/O), so FastAPI thread-pools it the same way it already
does for `connections_routes.start_connect`.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from qualify_api.http.deps import Principal, current_principal
from qualify_api.sentiment.composition import UnknownSentimentConnection
from qualify_api.sentiment.service import AnalysisSummary, SentimentModelUnavailable

router = APIRouter(prefix="/api", tags=["sentiment"])

AnalyzePendingComments = Callable[..., AnalysisSummary]


def get_analyze_pending_comments() -> AnalyzePendingComments:
    """Overridden at app startup (to `sentiment.composition.analyze_pending_comments`)
    and in tests — same posture `inbox_routes.get_sync_comments` establishes."""
    raise NotImplementedError("sentiment analysis dependency is not configured")


class AnalyzeRequest(BaseModel):
    """No `tenant_id` — identity is the Principal's (C1), same discipline
    `inbox_routes.SyncRequest` documents."""

    connection_id: UUID


class AnalyzeResponse(BaseModel):
    comments_checked: int
    new_results: int
    skipped_empty: int


@router.post("/sentiment/analyze", response_model=AnalyzeResponse)
def analyze_sentiment(
    body: AnalyzeRequest,
    principal: Principal = Depends(current_principal),
    analyze: AnalyzePendingComments = Depends(get_analyze_pending_comments),
) -> AnalyzeResponse:
    """Runs ONE analysis pass for one connection. Idempotent by construction — a
    comment already analyzed under the current model version is never re-analyzed
    (the repository's versioned unique index), so calling this twice in a row is
    safe and cheap, same discipline `sync_inbox` already documents for itself."""
    try:
        summary = analyze(tenant_id=principal.tenant_id, connection_id=body.connection_id)
    except UnknownSentimentConnection:
        raise HTTPException(status_code=404, detail="unknown connection") from None
    except SentimentModelUnavailable:
        raise HTTPException(status_code=503, detail="sentiment model unavailable") from None
    return AnalyzeResponse(
        comments_checked=summary.comments_checked,
        new_results=summary.new_results,
        skipped_empty=summary.skipped_empty,
    )
