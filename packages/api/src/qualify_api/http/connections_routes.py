"""HTTP routes for the connect flow (C-04).

Only two endpoints, and only one of them strictly needs to be HTTP: **Meta redirects a
real browser to the callback**, so that URL must exist. `start` is exposed for symmetry
and for a browser-initiated connect, but the Reflex CRM does not have to use it — it can
call `ConnectService.start_connect(...)` directly in an event handler and issue its own
redirect, which avoids a pointless local HTTP hop.

Dependencies are injected through FastAPI's `dependency_overrides` seam rather than
imported at module scope, so the tests substitute a fully faked service and run the entire
callback with no network and no database.

**Identity provenance (C1).** `start` takes BOTH the tenant and the acting user from the
authenticated `Principal` — never from the request body. A tenant id accepted from a
client is an authorization bypass with extra steps, and a body-supplied `user_id` is the
same bypass one layer down: the caller choosing who the connection is attributed to, an
id that ends up in `connection_events` as the actor. The callback reads neither from the
request; it reconstitutes them from the signed `state`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from qualify_api.connections.service import ConnectService
from qualify_api.connections.state_token import InvalidState
from qualify_api.http.deps import Principal, current_principal

router = APIRouter(prefix="/api/connections", tags=["connections"])


def get_connect_service() -> ConnectService:
    """Overridden in tests and wired at app startup. Raising here (rather than building a
    default) keeps an unconfigured deployment from silently talking to the real Meta."""
    raise NotImplementedError("connect service dependency is not configured")


class StartConnectRequest(BaseModel):
    """Note the absence of BOTH `tenant_id` and `user_id` — deliberate, not an oversight:
    identity comes from the authenticated `Principal` (C1), never from the body."""

    brand_id: UUID | None = None


class StartConnectResponse(BaseModel):
    authorization_url: str


class CallbackResponse(BaseModel):
    """`connection_id` is null for both dead-end outcomes: no row was created (R4).

    `page_count`/`linked_page_count` are the two integers R9(e.1) ordered recorded. They are
    returned as well as logged so step 1 of the empirical test can be read straight off the
    callback response — the operator running it is looking at a browser, not at a log tail.
    Counts carry no ids, no names and no token, so exposing them costs nothing.
    """

    outcome: str
    connection_id: UUID | None = None
    external_username: str | None = None
    page_count: int = 0
    linked_page_count: int = 0


@router.post("/start", response_model=StartConnectResponse)
def start_connect(
    body: StartConnectRequest,
    principal: Principal = Depends(current_principal),
    service: ConnectService = Depends(get_connect_service),
) -> StartConnectResponse:
    return StartConnectResponse(
        authorization_url=service.start_connect(
            tenant_id=principal.tenant_id, brand_id=body.brand_id, user_id=principal.user_id
        )
    )


@router.get("/callback", response_model=CallbackResponse)
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    service: ConnectService = Depends(get_connect_service),
) -> CallbackResponse:
    try:
        result = await service.complete_connect(code=code, state=state)
    except InvalidState:
        # One 403 for every state failure — forged, expired, replayed. Telling the caller
        # which one would help them work out what to forge next.
        raise HTTPException(status_code=403, detail="invalid or expired state") from None
    return CallbackResponse(
        outcome=str(result.outcome),
        connection_id=result.connection_id,
        # Keyed off `connection_id` rather than off a list of dead-end outcomes: R9(f) added
        # one such outcome and a future ruling may add another, and an enum check would have
        # to be remembered each time. No connection, no username — that holds by definition.
        external_username=result.external_username if result.connection_id is not None else None,
        page_count=result.page_count,
        linked_page_count=result.linked_page_count,
    )
