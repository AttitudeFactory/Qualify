"""`POST /api/meegle/events` — the Meegle Event Listener callback (`docs/plan-altas-meegle.md` §3).

Same posture as the Meta webhook routes: a public surface that Meegle calls directly, so
trust comes from Meegle's own mechanism (the body's `signature`, see
`qualify_api.meegle.envelope`) and never from Qualify's `Principal`. Response policy:

- `413` over `MAX_EVENT_BYTES`; `401` for a missing or invalid signature. Neither writes.
- `200` only after the delivery is committed — including a body that is not a Meegle
  event (recorded `unparseable`, a retry would not fix it) and a redelivery (already
  recorded by `idempotent_key`, nothing added). Meegle retries on anything else, four
  times, so a 200 for a duplicate is what stops the retries.
- `500` if the record fails, so the retry does its job instead of the event being lost.

Nothing here reads the work item, sends mail or writes back to Meegle: that is the
processor's job, outside the request (`qualify_api.meegle.handlers`).

Dependencies raise until wired, like every route module here: an unconfigured deployment
(`MeegleNotConfigured`) fails the request loudly rather than accepting unverified events.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from qualify_api.meegle.envelope import MAX_EVENT_BYTES
from qualify_api.meegle.receiver import MeegleEventSettings
from qualify_api.webhooks.receiver import RecordedDelivery

router = APIRouter(prefix="/api/meegle", tags=["meegle"])

_LOGGER = logging.getLogger(__name__)

# `(body=..., signature=...) -> RecordedDelivery`
MeegleDeliveryRecorder = Callable[..., RecordedDelivery]


def get_event_settings() -> MeegleEventSettings:
    """Overridden at app startup (to `.from_env()`) and in tests."""
    raise NotImplementedError("meegle event settings dependency is not configured")


def get_delivery_recorder() -> MeegleDeliveryRecorder:
    """Overridden at app startup (to `meegle.receiver.record_meegle_delivery`) and in
    tests (to a fake, so the HTTP contract tests never touch Postgres)."""
    raise NotImplementedError("meegle delivery recorder dependency is not configured")


def _body_signature(body: bytes) -> str:
    """The `signature` field as sent (already verified), for the delivery log."""
    try:
        value = json.loads(body).get("signature")
    except (ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


@router.post("/events")
async def receive_event(
    request: Request,
    settings: MeegleEventSettings = Depends(get_event_settings),
    record: MeegleDeliveryRecorder = Depends(get_delivery_recorder),
) -> Response:
    body = await request.body()
    if len(body) > MAX_EVENT_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    if not settings.verify(body):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        recorded = await run_in_threadpool(record, body=body, signature=_body_signature(body))
    except Exception as exc:  # noqa: BLE001 — any failure must become a retryable 500
        _LOGGER.error(
            "meegle event: delivery NOT recorded (%s) — answering 500", type(exc).__name__
        )
        return Response(status_code=500)

    _LOGGER.info(
        "meegle event: delivery=%s duplicate=%s parse=%s new=%d",
        recorded.delivery_id,
        recorded.duplicate_delivery,
        recorded.parse_status,
        recorded.changes_new,
    )
    return Response(status_code=200)
