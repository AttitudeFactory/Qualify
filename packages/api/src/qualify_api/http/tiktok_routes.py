"""HTTP routes for the TikTok connect flow (m-24921091), beside the Meta ones.

`POST /api/connections/tiktok/start` returns the consent URL; `GET .../tiktok/callback` is
the redirect URI registered in the TikTok developer portal (`TIKTOK_REDIRECT_URI`).
Same rules as `connections_routes`: identity comes from the authenticated `Principal`, never
the body; every callback outcome is a `303` to `/connections?connect=<code>&platform=tiktok`
with a closed code set and nothing credential-bearing in the URL.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from qualify_api.config import TikTokSettings
from qualify_api.connections.purge import ConnectionPurgeInProgress
from qualify_api.connections.revoke import ConnectionNotFound
from qualify_api.connections.state_token import InvalidState, safe_return_path
from qualify_api.connections.tiktok_oauth import TikTokOAuthError
from qualify_api.connections.tiktok_service import TikTokConnectService
from qualify_api.http.connections_routes import (
    DENIED,
    INVALID_STATE,
    get_connections_page_url,
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
    principal: Principal = Depends(current_principal),
    service: TikTokConnectService = Depends(get_tiktok_connect_service),
) -> StartTikTokResponse:
    if not TikTokSettings.is_configured():
        raise HTTPException(status_code=503, detail="tiktok_not_configured")
    try:
        url = service.start_connect(
            tenant_id=principal.tenant_id,
            brand_id=body.brand_id,
            user_id=principal.user_id,
            connection_id=body.connection_id,
            return_to=body.return_to if body.connection_id else "",
            cause=body.cause if body.connection_id else "",
        )
    except ConnectionNotFound:
        raise HTTPException(status_code=404, detail="connection_not_found") from None
    return StartTikTokResponse(authorization_url=url)


@router.get("/callback", response_class=RedirectResponse, status_code=303)
async def tiktok_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    service: TikTokConnectService = Depends(get_tiktok_connect_service),
    page_url: str = Depends(get_connections_page_url),
) -> RedirectResponse:
    if code is None:
        if state is not None:
            try:
                payload = service.consume_callback_state(state)
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
        context = service.callback_context(state)
        result = await service.complete_connect(code=code, state=state)
    except InvalidState:
        return _back(page_url, INVALID_STATE)
    except (TikTokOAuthError, httpx.HTTPError, SQLAlchemyError, ConnectionPurgeInProgress):
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
