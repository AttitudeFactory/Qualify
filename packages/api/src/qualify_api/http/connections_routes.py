"""HTTP routes for the connect flow (C-04).

Only two endpoints, and only one of them strictly needs to be HTTP: **Meta redirects a
real browser to the callback**, so that URL must exist. `start` is exposed for symmetry
and for a browser-initiated connect, but the Reflex CRM does not have to use it — it can
call `ConnectService.start_connect(...)` directly in an event handler and issue its own
redirect, which avoids a pointless local HTTP hop.

Dependencies are injected through FastAPI's `dependency_overrides` seam rather than
imported at module scope, so the tests substitute a fully faked service and run the entire
callback with no network and no database.

**Tenant provenance.** `start` takes the tenant from the dev selector
(`qualify_shared.dev`), never from the request body — a tenant id accepted from a client
is an authorization bypass with extra steps. The callback does not read tenant from the
request at all; it reconstitutes it from the signed `state`. Real session-derived tenancy
replaces the dev stub at QUA-66.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from qualify_shared.dev import get_dev_tenant

from qualify_api.connections.service import ConnectOutcome, ConnectService
from qualify_api.connections.state_token import InvalidState

router = APIRouter(prefix="/api/connections", tags=["connections"])


def get_connect_service() -> ConnectService:
    """Overridden in tests and wired at app startup. Raising here (rather than building a
    default) keeps an unconfigured deployment from silently talking to the real Meta."""
    raise NotImplementedError("connect service dependency is not configured")


class StartConnectRequest(BaseModel):
    """Note the absence of `tenant_id` — it is deliberate, not an oversight."""

    brand_id: UUID | None = None
    user_id: UUID


class StartConnectResponse(BaseModel):
    authorization_url: str


class CallbackResponse(BaseModel):
    """`connection_id` is null for `link_required`: no row was created (R4)."""

    outcome: str
    connection_id: UUID | None = None
    external_username: str | None = None


@router.post("/start", response_model=StartConnectResponse)
def start_connect(
    body: StartConnectRequest,
    service: ConnectService = Depends(get_connect_service),
) -> StartConnectResponse:
    tenant_id = get_dev_tenant()
    if tenant_id is None:
        raise HTTPException(status_code=409, detail="no active tenant selected")
    return StartConnectResponse(
        authorization_url=service.start_connect(
            tenant_id=tenant_id, brand_id=body.brand_id, user_id=body.user_id
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
        external_username=result.external_username
        if result.outcome is not ConnectOutcome.LINK_REQUIRED
        else None,
    )
