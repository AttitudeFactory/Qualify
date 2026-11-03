"""HTTP routes for the TikTok connect flow (m-24921091), beside the Meta ones.

`POST /api/connections/tiktok/start` returns the consent URL; `GET .../tiktok/callback` is
the redirect URI registered in the TikTok developer portal (`TIKTOK_REDIRECT_URI`).
Same rules as `connections_routes`: identity comes from the authenticated `Principal`, never
the body; every callback outcome is a `303` to `/connections?connect=<code>&platform=tiktok`
with a closed code set and nothing credential-bearing in the URL.

**Browser binding (m-24921205).** Exactly as for Meta: the starting browser holds a per-flow
nonce in the host-only cookie `qoauth_tiktok_<jti prefix>` (Path `/api/connections`,
SameSite=Lax, Secure, Max-Age = the state TTL) and the signed `state` only its sha256. The
callback passes the cookie to the service, which spends the jti, drops the PKCE verifier
and answers plain `invalid_state` when it is missing or foreign — before any code exchange.
Every callback response deletes the cookie.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from qualify_api.config import TikTokSettings
from qualify_api.connections.purge import ConnectionPurgeInProgress
from qualify_api.connections.repository import PlatformAppMissing
from qualify_api.connections.revoke import ConnectionNotFound
from qualify_api.connections.state_token import InvalidState, safe_return_path
from qualify_api.connections.tiktok_oauth import TikTokOAuthError
from qualify_api.connections.tiktok_service import TikTokConnectService
from qualify_api.http.connections_routes import (
    DENIED,
    INVALID_STATE,
    drop_binding_cookie,
    get_connections_page_url,
    read_binding,
    set_binding_cookie,
)
from qualify_api.http.deps import Principal, current_principal

router = APIRouter(prefix="/api/connections/tiktok", tags=["connections", "tiktok"])


def get_tiktok_connect_service() -> TikTokConnectService:
    """Overridden at app startup and in tests; raising keeps an unconfigured deployment
    from silently talking to the real TikTok."""
    raise NotImplementedError("tiktok connect service dependency is not configured")


class StartTikTokRequest(BaseModel):
    """No `tenant_id`/`user_id`: identity is the Principal's."""

    brand_id: UUID | None = None
    connection_id: UUID | None = None
    return_to: str = ""
    cause: str = ""


class StartTikTokResponse(BaseModel):
    authorization_url: str


def _back(
    page_url: str, code: str, *, return_to: str = "", connection_id: UUID | None = None
) -> RedirectResponse:
    query: dict[str, str] = {"connect": code, "platform": "tiktok"}
    origin = safe_return_path(return_to)
    if origin:
        parsed = urlsplit(page_url)
        page_url = urlunsplit((parsed.scheme, parsed.netloc, origin, "", ""))
        if connection_id is not None:
            query["reconnect"] = str(connection_id)
    return RedirectResponse(f"{page_url}?{urlencode(query)}", status_code=303)


@router.post("/start", response_model=StartTikTokResponse)
def start_tiktok(
    body: StartTikTokRequest,
    response: Response,
    principal: Principal = Depends(current_principal),
    service: TikTokConnectService = Depends(get_tiktok_connect_service),
) -> StartTikTokResponse:
    if not TikTokSettings.is_configured():
        raise HTTPException(status_code=503, detail="tiktok_not_configured")
    try:
        started = service.start_connect(
            tenant_id=principal.tenant_id,
            brand_id=body.brand_id,
            user_id=principal.user_id,
            connection_id=body.connection_id,
            return_to=body.return_to if body.connection_id else "",
            cause=body.cause if body.connection_id else "",
        )
    except ConnectionNotFound:
        raise HTTPException(status_code=404, detail="connection_not_found") from None
    set_binding_cookie(response, started)
    return StartTikTokResponse(authorization_url=started.authorization_url)


@router.get("/callback", response_class=RedirectResponse, status_code=303)
async def tiktok_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    service: TikTokConnectService = Depends(get_tiktok_connect_service),
    page_url: str = Depends(get_connections_page_url),
) -> RedirectResponse:
    cookie_name: str | None = None
    if state is not None:
        try:
            cookie_name = service.binding_cookie(state)
        except InvalidState:
            cookie_name = None
    response = await _callback_outcome(
        code=code,
        state=state,
        error=error,
        binding_nonce=read_binding(request, cookie_name),
        service=service,
        page_url=page_url,
    )
    drop_binding_cookie(response, cookie_name)
    return response


async def _callback_outcome(
    *,
    code: str | None,
    state: str | None,
    error: str | None,
    binding_nonce: str | None,
    service: TikTokConnectService,
    page_url: str,
) -> RedirectResponse:
    if code is None:
        if state is not None:
            try:
                # Spends the jti and the PKCE verifier; an unbound state raises here, so
                # its `return_to` is never trusted.
                payload = service.abandon_callback(state, binding_nonce=binding_nonce)
            except InvalidState:
                return _back(page_url, INVALID_STATE)
            return _back(
                page_url,
                DENIED if error else INVALID_STATE,
                return_to=payload.return_to,
                connection_id=payload.connection_id,
            )
        return _back(page_url, DENIED if error else INVALID_STATE)
    if state is None:
        return _back(page_url, INVALID_STATE)
    try:
        context = service.callback_context(state)  # verify-only; spends nothing
        result = await service.complete_connect(code=code, state=state, binding_nonce=binding_nonce)
    except InvalidState:
        return _back(page_url, INVALID_STATE)
    except (
        TikTokOAuthError,
        httpx.HTTPError,
        SQLAlchemyError,
        ConnectionPurgeInProgress,
        PlatformAppMissing,  # TikTok's `platform_apps` row not seeded: a config gap, not a 500
    ):
        # The jti is spent: retrying means a new consent. Never echo a provider error.
        return _back(
            page_url,
            "degraded",
            return_to=context.return_to,
            connection_id=context.connection_id,
        )
    return _back(
        page_url,
        str(result.outcome),
        return_to=result.return_to,
        connection_id=result.connection_id,
    )
