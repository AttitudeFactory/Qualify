"""HTTP routes for publishing (A7) — three routes that mirror the client-driven poll.

The shape IS the design: `POST /api/media` stages bytes durably (A3), `POST
/api/publishing/attempts` runs `start()` and answers 202 — accepted, not finished — and
`GET /api/publishing/attempts/{id}` runs ONE `advance()` step. The client repeats the GET
at the `poll_interval_seconds` the response advertises; no route blocks longer than its
own step.

Identity comes from the authenticated `Principal` (C1) — no request model here has a
`tenant_id` field, asserted structurally by a test. The `idempotency_key` is the CLIENT's
and it is mandatory: a server-generated key would make every retry a fresh operation,
which is the double-post with extra steps.

Dependencies default to raising (pattern of `connections_routes.get_connect_service`):
an unconfigured deployment must not talk to the real Meta silently. Error responses carry
reasons and codes, never tokens, ciphertext or Meta response bodies.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from qualify_shared.objects.gate import ObjectSizeExceeded
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.http.deps import Principal, current_principal
from qualify_api.publishing.client import PublishError
from qualify_api.publishing.service import (
    PublishService,
    PublishState,
    UnknownAttempt,
    UnknownConnection,
)
from qualify_api.publishing.staging import MediaStagingService

router = APIRouter(prefix="/api", tags=["publishing"])


def get_publish_service() -> PublishService:
    """Overridden at app startup and in tests. Raising keeps an unconfigured deployment
    from silently talking to the real Meta."""
    raise NotImplementedError("publish service dependency is not configured")


def get_staging_service() -> MediaStagingService:
    raise NotImplementedError("staging service dependency is not configured")


class StageMediaResponse(BaseModel):
    media_object_key: str
    media_product_type: str


class StartAttemptRequest(BaseModel):
    """No `tenant_id`, no `user_id` — identity is the Principal's (C1)."""

    connection_id: UUID
    media_object_key: str
    media_product_type: str
    idempotency_key: str  # mandatory and client-chosen; its absence is a 422
    caption: str | None = None
    thumb_offset: int | None = None
    # QUA-68: only meaningful when media_product_type='IMAGE' — PublishService.start()
    # needs it to mint the public link's Content-Type. Optional and ignored for every
    # existing (VIDEO) caller, so no pre-existing request body needs to change.
    content_type: str | None = None


class AttemptStateResponse(BaseModel):
    attempt_id: UUID
    status: str
    settled: bool
    published_media_id: str | None
    reason: str | None
    container_status: str | None
    awaiting_confirmation: bool
    poll_interval_seconds: int


def _response(state: PublishState) -> AttemptStateResponse:
    return AttemptStateResponse(
        attempt_id=state.attempt_id,
        status=state.status,
        settled=state.settled,
        published_media_id=state.published_media_id,
        reason=state.reason,
        container_status=state.container_status,
        awaiting_confirmation=state.awaiting_confirmation,
        poll_interval_seconds=state.poll_interval_seconds,
    )


@router.post("/media", response_model=StageMediaResponse)
async def stage_media(
    file: UploadFile = File(...),
    connection_id: UUID = Form(...),
    media_product_type: str = Form(...),
    principal: Principal = Depends(current_principal),
    staging: MediaStagingService = Depends(get_staging_service),
) -> StageMediaResponse:
    """Bytes land durably BEFORE anything touches the platform — a failed publish must
    never cost the operator a re-upload (A3)."""
    try:
        staged = staging.stage_media(
            tenant_id=principal.tenant_id,
            connection_id=connection_id,
            media_id=uuid4().hex,  # server-owned: the media key is not client input
            fileobj=file.file,
            content_type=file.content_type or "",
            media_product_type=media_product_type,
        )
    except ObjectSizeExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except (ValueError, TenantPrefixViolation) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return StageMediaResponse(
        media_object_key=staged.media_object_key,
        media_product_type=staged.media_product_type,
    )


@router.post("/publishing/attempts", response_model=AttemptStateResponse, status_code=202)
async def start_attempt(
    body: StartAttemptRequest,
    principal: Principal = Depends(current_principal),
    service: PublishService = Depends(get_publish_service),
) -> AttemptStateResponse:
    """202: accepted and in flight — `advance` (the GET) is where outcomes appear.
    Repeating this POST with the same idempotency_key returns the same attempt and
    publishes nothing new; that guarantee is the database's, not this handler's."""
    try:
        state = await service.start(
            tenant_id=principal.tenant_id,
            connection_id=body.connection_id,
            media_object_key=body.media_object_key,
            media_product_type=body.media_product_type,
            idempotency_key=body.idempotency_key,
            caption=body.caption,
            thumb_offset=body.thumb_offset,
            content_type=body.content_type,
        )
    except UnknownConnection:
        raise HTTPException(status_code=404, detail="unknown connection") from None
    except TenantPrefixViolation:
        raise HTTPException(status_code=422, detail="media key outside tenant prefix") from None
    except ValueError as exc:
        # QUA-68: today the only source is `_start_image`'s missing-content_type check —
        # a caller-side mistake (an IMAGE request without content_type), not a platform
        # or infrastructure failure, so 422 rather than the 502 below.
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except PublishError as exc:
        # The write-ahead row survives in 'pending' (A4); the message carries status and
        # numeric codes only, never a Meta body.
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return _response(state)


@router.get("/publishing/attempts/{attempt_id}", response_model=AttemptStateResponse)
async def read_attempt(
    attempt_id: UUID,
    principal: Principal = Depends(current_principal),
    service: PublishService = Depends(get_publish_service),
) -> AttemptStateResponse:
    """ONE advance step per GET — never a wait. The response advertises the cadence."""
    try:
        state = await service.advance(tenant_id=principal.tenant_id, attempt_id=attempt_id)
    except UnknownAttempt:
        raise HTTPException(status_code=404, detail="unknown attempt") from None
    except PublishError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return _response(state)
