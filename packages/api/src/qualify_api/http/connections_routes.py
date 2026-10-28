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

**The callback ends in the UI, not in JSON (QUA-123).** Meta sends a real browser here, and
whoever is in that browser — the operator, or Meta's App Reviewer — must land back on
`/connections` with a readable result, not on a raw JSON body. So every outcome, failures
included, is a `303 See Other` to `/connections?connect=<code>`. The code is a closed
vocabulary (`ConnectOutcome` plus `invalid_state` / `denied`): no id and no username
travels in the URL — the page re-reads the connection list from Postgres on load.

**The two dead ends also carry their counts (QUA-202).** `link_required` and
`page_access_required` add `pages=<n>&linked=<n>` — the two integers R9(e.1) declared safe
(counts only: no Page id, no name, no token) — so the page can tell the operator "Meta nos
mostró 2 Páginas, ninguna con tu Instagram" instead of a sentence they cannot act on. A
successful outcome carries nothing but its code.

For an account-specific reconnection (m-24854865), the signed state carries a safe
internal origin and the intended account. The callback returns there with the closed
`connect` code and a public `reconnect` UUID. The screen re-reads that UUID through its
tenant-scoped provider for the account label; usernames and credentials stay out of URLs.
Legacy /inbox and /conversations routes preserve those query values when forwarding to
the corresponding /responder tab.
"""

from __future__ import annotations

import os
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from qualify_api.connections.meta_oauth import MetaOAuthError
from qualify_api.connections.purge import ConnectionPurgeInProgress
from qualify_api.connections.revoke import ConnectionNotFound
from qualify_api.connections.service import ConnectOutcome, ConnectService
from qualify_api.connections.state_token import InvalidState, safe_return_path
from qualify_api.http.deps import Principal, current_principal

router = APIRouter(prefix="/api/connections", tags=["connections"])

# The two callback results that are not a `ConnectOutcome`. `invalid_state` deliberately
# covers forged, expired AND replayed alike — naming which one would tell a caller what
# to forge next (the reason the JSON version answered one 403 for all three).
INVALID_STATE = "invalid_state"
# The operator pressed "Cancel" in Meta's dialog: Meta comes back with `error=...` and no
# `code`. Not an attack and not a bug, so it gets its own, calm message in the UI.
DENIED = "denied"

# Where the browser lands after the callback. In production the UI and the API share one
# origin behind Caddy and `REFLEX_DEPLOY_URL` is that origin; in local dev the API runs on
# :8000 and the UI on :3000, so the redirect has to be absolute.
_DEV_APP_URL = "http://localhost:3000"


def get_connect_service() -> ConnectService:
    """Overridden in tests and wired at app startup. Raising here (rather than building a
    default) keeps an unconfigured deployment from silently talking to the real Meta."""
    raise NotImplementedError("connect service dependency is not configured")


class StartConnectRequest(BaseModel):
    """Note the absence of BOTH `tenant_id` and `user_id` — deliberate, not an oversight:
    identity comes from the authenticated `Principal` (C1), never from the body."""

    brand_id: UUID | None = None
    connection_id: UUID | None = None
    return_to: str = ""
    cause: str = ""


class StartConnectResponse(BaseModel):
    authorization_url: str


def get_connections_page_url() -> str:
    """Absolute URL of the Reflex `/connections` page. `QUALIFY_APP_URL` wins, then
    `REFLEX_DEPLOY_URL` (set to the public origin by `deploy/docker-compose.prod.yml`),
    then the local dev frontend. A dependency so tests can pin it."""
    base = (
        os.environ.get("QUALIFY_APP_URL", "").strip()
        or os.environ.get("REFLEX_DEPLOY_URL", "").strip()
        or _DEV_APP_URL
    )
    return f"{base.rstrip('/')}/connections"


def _back_to_connections(
    page_url: str,
    code: str,
    *,
    pages: int | None = None,
    linked: int | None = None,
    return_to: str = "",
    connection_id: UUID | None = None,
) -> RedirectResponse:
    # 303, not 302/307: the browser must follow with a GET and never replay the callback
    # (the `state` is single-use; a replay would only ever produce `invalid_state`).
    query: dict[str, str] = {"connect": code}
    origin = safe_return_path(return_to)
    if origin:
        parsed = urlsplit(page_url)
        page_url = urlunsplit((parsed.scheme, parsed.netloc, origin, "", ""))
        if connection_id is not None:
            query["reconnect"] = str(connection_id)
    if pages is not None and linked is not None:
        query["pages"] = str(pages)
        query["linked"] = str(linked)
    return RedirectResponse(f"{page_url}?{urlencode(query)}", status_code=303)


# The outcomes whose redirect carries the R9(e.1) counts — the ones the operator must act
# on. The counts are the only non-code values ever placed in this URL.
_GUIDED_OUTCOMES = frozenset({ConnectOutcome.LINK_REQUIRED, ConnectOutcome.PAGE_ACCESS_REQUIRED})


@router.post("/start", response_model=StartConnectResponse)
def start_connect(
    body: StartConnectRequest,
    principal: Principal = Depends(current_principal),
    service: ConnectService = Depends(get_connect_service),
) -> StartConnectResponse:
    kwargs = {}
    if body.connection_id is not None:
        kwargs = {
            "connection_id": body.connection_id,
            "return_to": body.return_to,
            "cause": body.cause,
        }
    try:
        authorization_url = service.start_connect(
            tenant_id=principal.tenant_id,
            brand_id=body.brand_id,
            user_id=principal.user_id,
            **kwargs,
        )
    except ConnectionNotFound:
        raise HTTPException(status_code=404, detail="connection_not_found") from None
    return StartConnectResponse(authorization_url=authorization_url)


@router.get("/callback", response_class=RedirectResponse, status_code=303)
async def oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    service: ConnectService = Depends(get_connect_service),
    page_url: str = Depends(get_connections_page_url),
) -> RedirectResponse:
    if code is None:
        if state is not None:
            try:
                payload = service.consume_callback_state(state)
            except InvalidState:
                return _back_to_connections(page_url, INVALID_STATE)
            return _back_to_connections(
                page_url,
                DENIED if error else INVALID_STATE,
                return_to=payload.return_to,
                connection_id=payload.connection_id,
            )
        # No code: either Meta reports the operator declined (`error=access_denied`), or the
        # request is not a real callback at all. Nothing is exchanged and no `state` is spent
        # — an unspent jti simply expires on its TTL.
        return _back_to_connections(page_url, DENIED if error else INVALID_STATE)
    if state is None:
        return _back_to_connections(page_url, INVALID_STATE)
    try:
        context = service.callback_context(state)
        result = await service.complete_connect(code=code, state=state)
    except InvalidState:
        return _back_to_connections(page_url, INVALID_STATE)
    except (MetaOAuthError, httpx.HTTPError, SQLAlchemyError, ConnectionPurgeInProgress):
        # complete_connect has already spent its jti. Retry means a new consent flow;
        # keep only the authenticated original route, never a provider error or token.
        return _back_to_connections(
            page_url,
            "degraded",
            return_to=context.return_to,
            connection_id=context.connection_id,
        )
    if result.outcome in _GUIDED_OUTCOMES:
        return _back_to_connections(
            page_url,
            str(result.outcome),
            pages=result.page_count,
            linked=result.linked_page_count,
        )
    return _back_to_connections(
        page_url,
        str(result.outcome),
        return_to=result.return_to,
        connection_id=result.connection_id,
    )
