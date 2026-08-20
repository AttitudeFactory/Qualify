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
from qualify_api.inbox.composition import UnknownInboxConnection
from qualify_api.inbox.service import (
    CommentsAuthExpired,
    CommentsPermissionMissing,
    SyncBudgetExhausted,
    SyncSummary,
)

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
    """
    try:
        summary = await sync_comments(
            tenant_id=principal.tenant_id, connection_id=body.connection_id
        )
    except UnknownInboxConnection:
        raise HTTPException(status_code=404, detail="unknown connection") from None
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
    )
