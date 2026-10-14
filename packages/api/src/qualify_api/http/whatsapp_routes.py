"""HTTP routes for the WhatsApp Cloud API webhook receiver (WA-03).

Mirrors `mentions_routes.py`'s webhook pair exactly, for the same reason: Meta calls
both endpoints directly, so this is an HTTP surface that must exist unauthenticated by
Qualify's own `Principal` scheme — trust comes from Meta's mechanisms instead
(`hub.verify_token` for the GET handshake, `X-Hub-Signature-256` over the raw body for
the POST). The HMAC primitive is the mentions module's own `verify_signature`: the
App Secret and the header are the same for every Meta product, and a second copy of
twelve lines would only be a second place to get `compare_digest` wrong.

**Where a delivery goes: the SAME intake log as the mentions webhook** (QUA-147,
migration 0050 — `meta_webhook_deliveries` + `meta_webhook_events`, written through
`qualify_api.webhooks.receiver.record_delivery` as `qualify_webhook`). Meta's envelope is
product-agnostic (`object` + `entry[].id` + `changes[].field/value`), the intake is keyed
by it, and dedup (`body_sha256`, `dedup_key`) and retention already exist there. A
WhatsApp change (`object = whatsapp_business_account`, `field = messages`) is therefore
recorded durably BEFORE Meta gets its 200 and settled later by
`qualify_api.webhooks.processor` — today as `unsupported` (kept 29 days, replayable), and
as a real `threads`/`messages` write once WA-07 registers its handler there. The typed
view the handler will use is `qualify_shared.social.wa_shapes`.

Response policy, per Meta's WhatsApp webhook docs (retries with decreasing frequency for
up to **7 days** on anything but a 200, duplicates included): `413` over the size cap and
`403` on a missing/invalid signature write nothing; `200` only after the record is
committed, including a malformed body (recorded `unparseable`, a retry would not fix it);
`500` if the record fails, so the retry does its job instead of the event being lost.

Dependencies go through FastAPI's `dependency_overrides` seam, raising until wired —
same posture as every other route module here, so an unconfigured deployment fails
loudly instead of accepting an unverified webhook with a dev default.

**WA-10 (QUA-209) adds the chats API** below the webhook pair, over
`qualify_api.whatsapp.chats.ChatService`: list threads, read a thread, answer it
(`kind='reply'` into `whatsapp_outbox`, 409 `window_closed` outside the 24 h window),
assign / close / reopen / takeover / resume, and the media endpoint (501
`media_not_captured` until inbound media ids are persisted — see `chats.py`). Unlike the
webhook these are Qualify's own routes: identity is the `Principal` (C1) and the tenant
is always the principal's, never a parameter. A thread of another tenant answers 404,
exactly like an unknown id. Responses carry ids, statuses and message text — never a
credential, a raw payload or an outbox body.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from qualify_api.http.deps import Principal, current_principal
from qualify_api.mentions.signature import verify_signature
from qualify_api.webhooks.envelope import MAX_BODY_BYTES
from qualify_api.webhooks.receiver import RecordedDelivery
from qualify_api.whatsapp.chats import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ChatService,
    MediaLocator,
    MessageRecord,
    SendBody,
    ThreadNotFound,
    ThreadSummary,
    UnknownAgent,
    WindowClosed,
)
from qualify_api.whatsapp.config import WhatsAppWebhookSettings

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

_LOGGER = logging.getLogger(__name__)

# `(body=..., signature_header=...) -> RecordedDelivery` — the same seam the mentions
# route exposes, so production wires ONE recorder for both.
DeliveryRecorder = Callable[..., RecordedDelivery]


def get_webhook_settings() -> WhatsAppWebhookSettings:
    """Overridden at app startup (to `.from_env()`) and in tests."""
    raise NotImplementedError("whatsapp webhook settings dependency is not configured")


def get_delivery_recorder() -> DeliveryRecorder:
    """Overridden at app startup (to `webhooks.receiver.record_delivery`) and in tests (to
    a fake, so the HTTP/HMAC contract tests never touch Postgres)."""
    raise NotImplementedError("whatsapp delivery recorder dependency is not configured")


@router.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    settings: WhatsAppWebhookSettings = Depends(get_webhook_settings),
) -> Response:
    """Meta's verification handshake: echo `hub.challenge` back as plain text iff
    `hub.verify_token` matches ours. `hub.mode` is always `"subscribe"`; accepted but
    not branched on (same reasoning as the mentions handshake)."""
    if hub_verify_token != settings.verify_token:
        raise HTTPException(status_code=403, detail="invalid verify token")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    settings: WhatsAppWebhookSettings = Depends(get_webhook_settings),
    record: DeliveryRecorder = Depends(get_delivery_recorder),
) -> Response:
    """Size check, signature on the RAW body, durable record — and stop."""
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    signature_header = request.headers.get("x-hub-signature-256")
    if not verify_signature(
        body=body,
        signature_header=signature_header,
        app_secret=settings.app_secret,
    ):
        raise HTTPException(status_code=403, detail="invalid signature")

    try:
        # The record is synchronous DB work; keep it off the event loop.
        recorded = await run_in_threadpool(
            record, body=body, signature_header=signature_header or ""
        )
    except Exception as exc:  # noqa: BLE001 — any failure must become a retryable 500
        # Never log `body`: genuine (signature-verified) but it may carry a user's phone
        # number and message text — the exception type only.
        _LOGGER.error(
            "whatsapp webhook: delivery NOT recorded (%s) — answering 500", type(exc).__name__
        )
        return Response(status_code=500)

    _LOGGER.info(
        "whatsapp webhook: delivery=%s duplicate=%s parse=%s changes=%d new=%d",
        recorded.delivery_id,
        recorded.duplicate_delivery,
        recorded.parse_status,
        recorded.changes_total,
        recorded.changes_new,
    )
    return Response(status_code=200)


# ======================================================================================
# WA-10 — chats API
# ======================================================================================


def get_chat_service() -> ChatService:
    """Overridden at app startup (to `chats.production_chat_service()`) and in tests (to a
    service over the in-memory repositories)."""
    raise NotImplementedError("whatsapp chat service dependency is not configured")


def get_media_locator() -> MediaLocator:
    """Overridden at app startup (to `chats.NotCapturedMediaLocator`) and in tests."""
    raise NotImplementedError("whatsapp media locator dependency is not configured")


class WindowOut(BaseModel):
    open: bool
    # Set only while open: the instant the window shuts (the UI's "abierta hasta HH:MM").
    closes_at: datetime | None


class ThreadOut(BaseModel):
    id: UUID
    connection_id: UUID
    wa_id: str
    contact_name: str | None
    last_message_preview: str | None
    last_message_direction: Literal["inbound", "outbound"] | None
    last_message_at: datetime | None
    last_inbound_at: datetime | None
    unread_count: int
    status: Literal["open", "closed"]
    assigned_agent_id: UUID | None
    automation_paused: bool
    window: WindowOut

    @classmethod
    def of(cls, summary: ThreadSummary) -> ThreadOut:
        return cls.model_validate(
            {
                "id": summary.id,
                "connection_id": summary.connection_id,
                "wa_id": summary.wa_id,
                "contact_name": summary.contact_name,
                "last_message_preview": summary.last_message_preview,
                "last_message_direction": summary.last_message_direction,
                "last_message_at": summary.last_message_at,
                "last_inbound_at": summary.last_inbound_at,
                "unread_count": summary.unread_count,
                "status": summary.status,
                "assigned_agent_id": summary.assigned_agent_id,
                "automation_paused": summary.automation_paused,
                "window": {"open": summary.window.open, "closes_at": summary.window.closes_at},
            }
        )


class ThreadListOut(BaseModel):
    threads: list[ThreadOut]
    # Pass as `before` for the next (older) page; `None` = this was the last page.
    next_before: datetime | None


class MessageOut(BaseModel):
    id: UUID
    direction: Literal["inbound", "outbound"]
    text: str | None
    posted_at: datetime | None
    delivery_status: Literal["sent", "delivered", "read", "failed"] | None
    delivery_error_code: str | None
    external_message_id: str
    # Outbound only: the sent body's type (`text`, `image`, `interactive`, …); always
    # `None` inbound (the inbound type is not persisted — `chats.py` docstring).
    media_kind: str | None

    @classmethod
    def of(cls, record: MessageRecord) -> MessageOut:
        return cls.model_validate(
            {
                "id": record.id,
                "direction": record.direction,
                "text": record.text,
                "posted_at": record.posted_at,
                "delivery_status": record.delivery_status,
                "delivery_error_code": record.delivery_error_code,
                "external_message_id": record.external_message_id,
                "media_kind": record.media_kind,
            }
        )


class MessageListOut(BaseModel):
    # Chronological (oldest first) — the order a chat renders.
    messages: list[MessageOut]
    # Pass as `before` to load the previous (older) page; `None` = start of the thread.
    next_before: datetime | None


class SendOut(BaseModel):
    outbox_id: UUID


class AssignIn(BaseModel):
    # `None` unassigns.
    agent_user_id: UUID | None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "thread_not_found"})


def _thread_out(service: ChatService, tenant_id: UUID, thread_id: UUID) -> ThreadOut:
    try:
        return ThreadOut.of(service.get_thread_summary(tenant_id, thread_id))
    except ThreadNotFound:
        raise _not_found() from None


def _cursor(page_size: int, limit: int, stamp: datetime | None) -> datetime | None:
    """A full page may have more behind it; a short one is the end."""
    return stamp if page_size >= limit else None


@router.get("/threads", response_model=ThreadListOut)
def list_threads(
    connection_id: UUID | None = Query(default=None),
    status: Literal["open", "closed"] | None = Query(default=None),
    before: datetime | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> ThreadListOut:
    """The caller's WhatsApp conversations, most recent activity first."""
    summaries = service.list_threads(
        principal.tenant_id,
        connection_id=connection_id,
        status=status,
        limit=limit,
        before=before,
    )
    last: Sequence[ThreadSummary] = summaries[-1:]
    return ThreadListOut(
        threads=[ThreadOut.of(s) for s in summaries],
        next_before=_cursor(len(summaries), limit, last[0].last_message_at if last else None),
    )


@router.get("/threads/{thread_id}/messages", response_model=MessageListOut)
def list_messages(
    thread_id: UUID,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> MessageListOut:
    """One page of a thread, chronological. Older pages: pass `next_before` back."""
    try:
        records = service.list_messages(principal.tenant_id, thread_id, before=before, limit=limit)
    except ThreadNotFound:
        raise _not_found() from None
    # The page is chronological, so the cursor to older messages is its FIRST instant.
    first = records[0].posted_at if records else None
    return MessageListOut(
        messages=[MessageOut.of(r) for r in records],
        next_before=_cursor(len(records), limit, first),
    )


@router.post("/threads/{thread_id}/messages", response_model=SendOut, status_code=201)
def send_message(
    thread_id: UUID,
    body: SendBody = Body(...),
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> SendOut:
    """Queue a person's reply (`text` | `image` | `buttons`) and pause the thread's menu
    automation. 201 = queued, not yet delivered: the delivery state arrives on the
    message row through the status webhook."""
    try:
        outbox_id = service.send(principal.tenant_id, thread_id, principal.user_id, body)
    except ThreadNotFound:
        raise _not_found() from None
    except WindowClosed as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "window_closed",
                "closes_at": exc.closes_at.isoformat() if exc.closes_at else None,
            },
        ) from None
    except ValueError as exc:
        # A Cloud API limit (button title length, body size…) from the client builders.
        # Their messages name the limit, never echo the user's text.
        raise HTTPException(
            status_code=422, detail={"code": "invalid_message", "reason": str(exc)}
        ) from None
    return SendOut(outbox_id=outbox_id)


@router.post("/threads/{thread_id}/assign", response_model=ThreadOut)
def assign_thread(
    thread_id: UUID,
    body: AssignIn,
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> ThreadOut:
    try:
        service.assign(principal.tenant_id, thread_id, body.agent_user_id)
    except ThreadNotFound:
        raise _not_found() from None
    except UnknownAgent:
        raise HTTPException(status_code=422, detail={"code": "unknown_agent"}) from None
    return _thread_out(service, principal.tenant_id, thread_id)


@router.post("/threads/{thread_id}/close", response_model=ThreadOut)
def close_thread(
    thread_id: UUID,
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> ThreadOut:
    try:
        service.close(principal.tenant_id, thread_id)
    except ThreadNotFound:
        raise _not_found() from None
    return _thread_out(service, principal.tenant_id, thread_id)


@router.post("/threads/{thread_id}/reopen", response_model=ThreadOut)
def reopen_thread(
    thread_id: UUID,
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> ThreadOut:
    try:
        service.reopen(principal.tenant_id, thread_id)
    except ThreadNotFound:
        raise _not_found() from None
    return _thread_out(service, principal.tenant_id, thread_id)


@router.post("/threads/{thread_id}/takeover", response_model=ThreadOut)
def takeover_thread(
    thread_id: UUID,
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> ThreadOut:
    """Pause the menu automation on this thread; the caller owns the pause."""
    try:
        service.takeover(principal.tenant_id, thread_id, principal.user_id)
    except ThreadNotFound:
        raise _not_found() from None
    return _thread_out(service, principal.tenant_id, thread_id)


@router.post("/threads/{thread_id}/resume", response_model=ThreadOut)
def resume_thread(
    thread_id: UUID,
    principal: Principal = Depends(current_principal),
    service: ChatService = Depends(get_chat_service),
) -> ThreadOut:
    """Hand the thread back to the menu: clear the pause and the node cursor, keep the
    order in progress (`context`)."""
    try:
        service.resume(principal.tenant_id, thread_id)
    except ThreadNotFound:
        raise _not_found() from None
    return _thread_out(service, principal.tenant_id, thread_id)


@router.get("/media/{message_id}")
def get_media(
    message_id: UUID,
    principal: Principal = Depends(current_principal),
    locator: MediaLocator = Depends(get_media_locator),
) -> Response:
    """Redirect to the bytes of an inbound media message — or 501 `media_not_captured`,
    which is every inbound media message today (no `media_id` is persisted; the gap is
    documented in `chats.py`)."""
    url = locator.locate(tenant_id=principal.tenant_id, message_id=message_id)
    if url is None:
        raise HTTPException(status_code=501, detail={"code": "media_not_captured"})
    return RedirectResponse(url=url, status_code=307)
