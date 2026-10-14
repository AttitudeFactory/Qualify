"""HTTP routes for the WhatsApp Cloud API webhook receiver (WA-03).

Mirrors `mentions_routes.py`'s webhook pair exactly, for the same reason: Meta calls
both endpoints directly, so this is an HTTP surface that must exist unauthenticated by
Qualify's own `Principal` scheme — trust comes from Meta's mechanisms instead
(`hub.verify_token` for the GET handshake, `X-Hub-Signature-256` over the raw body for
the POST). The HMAC primitive is the mentions module's own `verify_signature`: the
App Secret and the header are the same for every Meta product, and a second copy of
twelve lines would only be a second place to get `compare_digest` wrong.

Response policy, per Meta's webhook docs (retries with decreasing frequency for up to
**7 days** on anything but a 200, duplicates included): everything past signature
validation answers 200 — a malformed body, an unknown field, a change whose value breaks
the contract. None of those is a failure a retry fixes. Signature failure stays a 403:
an unsigned or mis-signed body is not a confirmed Meta event.

Dependencies go through FastAPI's `dependency_overrides` seam, raising until wired —
same posture as every other route module here, so an unconfigured deployment fails
loudly instead of accepting an unverified webhook with a dev default.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from qualify_shared.social.wa_shapes import parse_whatsapp_notification

from qualify_api.mentions.signature import verify_signature
from qualify_api.whatsapp.config import WhatsAppWebhookSettings
from qualify_api.whatsapp.sink import WhatsAppEventSink

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

_LOGGER = logging.getLogger(__name__)


def get_webhook_settings() -> WhatsAppWebhookSettings:
    """Overridden at app startup (to `.from_env()`) and in tests."""
    raise NotImplementedError("whatsapp webhook settings dependency is not configured")


def get_event_sink() -> WhatsAppEventSink:
    """Overridden at app startup (to `log_only_sink` until WA-07) and in tests."""
    raise NotImplementedError("whatsapp event sink dependency is not configured")


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
    sink: WhatsAppEventSink = Depends(get_event_sink),
) -> Response:
    """Validate signature on the RAW body, parse, hand the notification to the sink."""
    body = await request.body()
    if not verify_signature(
        body=body,
        signature_header=request.headers.get("x-hub-signature-256"),
        app_secret=settings.app_secret,
    ):
        raise HTTPException(status_code=403, detail="invalid signature")

    try:
        notification = parse_whatsapp_notification(json.loads(body))
    except (ValueError, ValidationError) as exc:
        # Never log `body`: genuine (signature-verified) but not ours to put in a log
        # line wholesale — it may carry a user's phone number and message text.
        _LOGGER.warning(
            "whatsapp webhook payload failed contract validation: %s", type(exc).__name__
        )
        return Response(status_code=200)

    await sink(notification=notification, raw_body=body)
    return Response(status_code=200)
