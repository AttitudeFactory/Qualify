"""HTTP route for the inbox comment sync (B2's `POST /api/inbox/sync` acceptance
criterion) — mirrors `publishing_routes.py`'s shape: Principal-based identity (C1), a
`Depends` that raises until wired at app assembly, typed errors mapped to status codes,
never a Meta body.

This is the pull that IS the production route, not a backstop for a webhook that does
not exist (`service.py`'s module docstring). It is deliberately a thin HTTP seam over
`qualify_api.inbox.composition.sync_comments` — all the real logic (which media, paging,
dedup) stays in `InboxService`/`PostgresInboxRepository`; this module owns only request
parsing, identity, and error-to-status mapping. Swapping this route's transport (e.g. a
future webhook) would not require touching the service or the repository — that
independence is `test_the_seam_does_not_depend_on_http` in `test_inbox_routes.py`.

Deliberately the only inbox route in this module: candidate listing and the monitoring
toggle stay in-process-only Reflex calls for now (`inbox_provider.py` -> `qualify_api.
inbox.composition`), the same posture `http/app.py`'s own module docstring documents for
the Reflex CRM in general. B2's acceptance criteria singles out `sync` as needing a
route; the other two were never asked for one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from qualify_api.http.deps import Principal, current_principal
from qualify_api.inbox.client import CommentsReadError
from qualify_api.inbox.composition import InboxConnectionInactive, UnknownInboxConnection
from qualify_api.inbox.service import (
    CommentsAuthExpired,
    CommentsPermissionMissing,
    SyncBudgetExhausted,
    SyncSummary,
)
from qualify_api.inbox.sync_guard import SyncAlreadyRunning

router = APIRouter(prefix="/api", tags=["inbox"])

SyncComments = Callable[..., Awaitable[SyncSummary]]


def get_sync_comments() -> SyncComments:
    """Overridden at app startup (to `composition.sync_comments`) and in tests. Raising
    keeps an unconfigured deployment from silently talking to the real Meta — same
    posture `publishing_routes.get_publish_service` establishes."""
    raise NotImplementedError("inbox sync dependency is not configured")


class SyncRequest(BaseModel):
    """No `tenant_id` — identity is the Principal's (C1), same discipline
    `publishing_routes.StartAttemptRequest` documents."""

    connection_id: UUID


class SyncResponse(BaseModel):
    media_checked: int
    new_comments: int
    truncated: bool = False
    # Bug fix, 2026-09-01: media ids Meta confirmed no longer exist — see
    # `InboxService.sync_comments`'s `_is_missing_media_error`. A non-empty list here is
    # still a 200 (the sync as a whole succeeded), never folded into the 502 branch below
    # — that branch is reserved for a REAL failed call, not a per-media id Meta confirmed
    # is gone and the service already handled.
    skipped_missing_media: list[str] = []
    # QUA-101: individual comments soft-deleted this pass because a COMPLETE walk of
    # their (still-existing) media no longer returned them — the sibling case to
    # `skipped_missing_media` above, at the comment level instead of the whole Reel.
    # Also always a 200, same reasoning.
    deleted_comments: int = 0
    # QUA-149: see `SyncSummary` — expired media skipped without a Meta call, and this
    # pass's legacy-metadata reads. Counts only.
    expired_skipped: int = 0
    metadata_backfilled: int = 0
    metadata_failed: int = 0
    metadata_deferred: int = 0


@router.post("/inbox/sync", response_model=SyncResponse)
async def sync_inbox(
    body: SyncRequest,
    principal: Principal = Depends(current_principal),
    sync_comments: SyncComments = Depends(get_sync_comments),
) -> SyncResponse:
    """Runs ONE sync pass for one connection. Idempotent: de-duplication is the
    repository's job (`UNIQUE(connection_id, external_message_id)`), not this handler's
    — calling this twice in a row is safe and cheap, by design (B2).

    Two refusals added by QUA-88, both distinct from `CommentsReadError`'s 502 (a failed
    call vs. a call deliberately never attempted): `CommentsPermissionMissing` -> 403
    (`cannot_observe` — the connection cannot read the edge at all, never confused with a
    genuinely empty result) and `SyncBudgetExhausted` -> 429 (not enough of the real Meta
    call budget remains for this sync). Both detail messages carry only numbers
    (needed/remaining) or a connection id — never a Meta response body, same discipline
    `CommentsReadError` already established.

    `CommentsAuthExpired` (QUA-90) -> 401: a real runtime 401/190 from Meta on an
    already-`active` connection, distinct from `CommentsReadError`'s generic 502 the same
    way the two refusals above already are — by the time this reaches the caller the
    connection has already been degraded (`InboxService.sync_comments`), so 401 here is
    "your session expired", not "something went wrong".

    Bug fix (2026-09-01): a monitored medium Meta confirms no longer exists is NOT a
    502 — `InboxService.sync_comments` already handles it per-medium (skip, auto-
    unmonitor, keep going) and returns a normal `SyncSummary` with `skipped_missing_
    media` populated. This route stays a thin passthrough of that field; see
    `SyncResponse.skipped_missing_media` and `_is_missing_media_error`'s docstring.
    """
    try:
        summary = await sync_comments(
            tenant_id=principal.tenant_id, connection_id=body.connection_id
        )
    except UnknownInboxConnection:
        raise HTTPException(status_code=404, detail="unknown connection") from None
    except InboxConnectionInactive as exc:
        # 409, not 404: the connection exists and is the caller's — it is just not
        # `active`, so reading it is refused until it is reconnected.
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SyncAlreadyRunning:
        # Also 409: another pass on this connection is running right now — retry later.
        raise HTTPException(status_code=409, detail="sync already running") from None
    except CommentsPermissionMissing as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except SyncBudgetExhausted as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    except CommentsAuthExpired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    except CommentsReadError as exc:
        # Status and numeric platform codes only — same reason as PublishError: a failed
        # Graph call's body can echo request parameters or user-generated text.
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return SyncResponse(
        media_checked=summary.media_checked,
        new_comments=summary.new_comments,
        truncated=summary.truncated,
        skipped_missing_media=list(summary.skipped_missing_media),
        deleted_comments=summary.deleted_comments,
        expired_skipped=summary.expired_skipped,
        metadata_backfilled=summary.metadata_backfilled,
        metadata_failed=summary.metadata_failed,
        metadata_deferred=summary.metadata_deferred,
    )
