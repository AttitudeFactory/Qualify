"""Pinterest HTTP boundary: principal-owned start and browser-bound callback."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from qualify_api.connections.state_token import InvalidState
from qualify_api.http.connections_routes import (
    drop_binding_cookie,
    get_connections_page_url,
    read_binding,
    set_binding_cookie,
)
from qualify_api.http.deps import Principal, current_principal
from qualify_api.pinterest.client import PinterestError
from qualify_api.pinterest.service import PinterestService

router = APIRouter(prefix="/api/connections/pinterest", tags=["pinterest"])


def get_pinterest_service() -> PinterestService:
    from qualify_api.pinterest.composition import production_pinterest_service

    try:
        return production_pinterest_service()
    except ValueError:
        raise HTTPException(503, detail="pinterest_not_configured") from None


@router.post("/start")
def start(
    response: Response,
    principal: Principal = Depends(current_principal),
    service: PinterestService = Depends(get_pinterest_service),
) -> dict[str, str]:
    try:
        started = service.start_connect(tenant_id=principal.tenant_id, user_id=principal.user_id)
    except PinterestError:
        raise HTTPException(403, detail="pinterest_permission") from None
    set_binding_cookie(response, started)
    return {"authorization_url": started.authorization_url}


@router.get("/handoff")
def handoff(
    request: Request,
    state: str = Query(""),
    service: PinterestService = Depends(get_pinterest_service),
) -> Response:
    cookie_name = None
    try:
        cookie_name = service.binding_cookie(state)
        started = service.handoff(state, binding_nonce=read_binding(request, cookie_name))
        response = RedirectResponse(started.authorization_url, status_code=303)
        set_binding_cookie(response, started)
    except (InvalidState, RedisError):
        response = Response(
            "Vuelve al catálogo e intenta conectar Pinterest de nuevo.", status_code=400
        )
        drop_binding_cookie(response, cookie_name)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.delete("")
def disconnect(
    principal: Principal = Depends(current_principal),
    service: PinterestService = Depends(get_pinterest_service),
) -> dict[str, str]:
    try:
        service.disconnect(principal.tenant_id, principal.user_id)
    except PinterestError:
        raise HTTPException(403, detail="pinterest_permission") from None
    return {"status": "disconnected"}


@router.get("/callback")
def callback(
    request: Request,
    state: str | None = Query(None),
    code: str | None = Query(None),
    error: str | None = Query(None),
    service: PinterestService = Depends(get_pinterest_service),
    page_url: str = Depends(get_connections_page_url),
) -> RedirectResponse:
    cookie_name = None
    outcome = "invalid_state"
    if state:
        try:
            cookie_name = service.binding_cookie(state)
            nonce = read_binding(request, cookie_name)
            if not code or error:
                service.abandon_callback(state, binding_nonce=nonce)
                outcome = "denied"
            else:
                service.complete_connect(code=code, state=state, binding_nonce=nonce)
                outcome = "connected"
        except InvalidState:
            outcome = "invalid_state"
        except (PinterestError, SQLAlchemyError, RedisError):
            outcome = "degraded"
    parsed = urlsplit(page_url)
    destination = urlunsplit(
        (parsed.scheme, parsed.netloc, "/catalog", "connect=" + outcome + "&platform=pinterest", "")
    )
    response = RedirectResponse(destination, status_code=303)
    drop_binding_cookie(response, cookie_name)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
