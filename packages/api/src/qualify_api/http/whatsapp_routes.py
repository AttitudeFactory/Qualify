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
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from qualify_api.mentions.signature import verify_signature
from qualify_api.webhooks.envelope import MAX_BODY_BYTES
from qualify_api.webhooks.receiver import RecordedDelivery
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
