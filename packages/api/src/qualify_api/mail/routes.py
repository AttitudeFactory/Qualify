"""`POST /api/mail/resend` — the Resend delivery webhook (`docs/plan-altas-meegle.md` §3, M2).

Same posture as the Meta and Meegle webhook routes: a public surface Resend calls
directly, so trust comes from Resend's own mechanism (the Svix signature headers, see
`qualify_api.mail.webhook`) and never from Qualify's `Principal`. Response policy:

- `413` over `MAX_EVENT_BYTES`; `401` for missing or invalid signature headers, or a
  stale timestamp. Neither writes.
- `503` when `QUALIFY_RESEND_WEBHOOK_SECRET` is not set — loudly logged, and NEVER a 200:
  an unsigned event is not an event. Resend retries, which is what we want once the
  secret is configured.
- `200` only after the delivery is committed — including a body that is not a Resend
  event (recorded `unparseable`) and a redelivery (already recorded, nothing added).
- `500` if the record fails, so Resend's retry does its job instead of the event being lost.

Nothing here touches `signup_invites` or Meegle: that is the processor's job, outside the
request (`qualify_api.mail.handlers`, run by the `webhook-worker`).

Dependencies raise until wired, like every route module here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from qualify_api.mail.webhook import (
    MAX_EVENT_BYTES,
    ResendWebhookNotConfigured,
    ResendWebhookSettings,
    SvixHeaders,
)
from qualify_api.webhooks.receiver import RecordedDelivery

router = APIRouter(prefix="/api/mail", tags=["mail"])

_LOGGER = logging.getLogger(__name__)

# `(body=..., headers=SvixHeaders) -> RecordedDelivery`
ResendDeliveryRecorder = Callable[..., RecordedDelivery]


def get_webhook_settings() -> ResendWebhookSettings:
    """Overridden at app startup (to `build_production_resend_webhook_settings`) and in
    tests."""
    raise NotImplementedError("resend webhook settings dependency is not configured")


def get_delivery_recorder() -> ResendDeliveryRecorder:
    """Overridden at app startup (to `mail.webhook.record_resend_delivery`) and in tests
    (to a fake, so the HTTP contract tests never touch Postgres)."""
    raise NotImplementedError("resend delivery recorder dependency is not configured")


def build_production_resend_webhook_settings() -> ResendWebhookSettings:
    """Env read only. An unset secret is a 503 on EVERY event, logged as an error each
    time — the endpoint must never fall back to accepting unsigned bodies."""
    try:
        return ResendWebhookSettings.from_env()
    except ResendWebhookNotConfigured as exc:
        _LOGGER.error("resend webhook: REFUSING event — %s", exc)
        raise HTTPException(status_code=503, detail="resend webhook not configured") from exc


@router.post("/resend")
async def receive_resend_event(
    request: Request,
    settings: ResendWebhookSettings = Depends(get_webhook_settings),
    record: ResendDeliveryRecorder = Depends(get_delivery_recorder),
) -> Response:
    body = await request.body()
    if len(body) > MAX_EVENT_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    headers = SvixHeaders.from_headers(request.headers)
    if headers is None or not settings.verify(headers, body):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        recorded = await run_in_threadpool(record, body=body, headers=headers)
    except Exception as exc:  # noqa: BLE001 — any failure must become a retryable 500
        _LOGGER.error(
            "resend webhook: delivery NOT recorded (%s) — answering 500", type(exc).__name__
        )
        return Response(status_code=500)

    _LOGGER.info(
        "resend webhook: svix_id=%s delivery=%s duplicate=%s parse=%s new=%d",
        headers.message_id,
        recorded.delivery_id,
        recorded.duplicate_delivery,
        recorded.parse_status,
        recorded.changes_new,
    )
    return Response(status_code=200)


# Scoped capability: permits only changing this person's morning-mail preference.
# GET is deliberately read-only so link previews/scanners never unsubscribe a person.
@router.get("/finals/preferences/{tenant_id}/{user_id}/{token}")
def final_preference_page(tenant_id: UUID, user_id: UUID, token: UUID) -> HTMLResponse:
    from qualify_api.mail.final_summary import preference

    try:
        enabled, _ = preference(tenant_id, user_id, token=token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Enlace no disponible") from exc
    return HTMLResponse(
        _preference_html(enabled=enabled, saved=False),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/finals/preferences/{tenant_id}/{user_id}/{token}")
async def final_preference_update(
    tenant_id: UUID,
    user_id: UUID,
    token: UUID,
    request: Request,
) -> HTMLResponse:
    from urllib.parse import parse_qs

    from qualify_api.mail.final_summary import preference

    # RFC 8058's one-click POST carries List-Unsubscribe=One-Click. An explicit
    # form action enables again; arbitrary data cannot change any other preference.
    raw = b""
    async for part in request.stream():
        if len(raw) + len(part) > 256:
            raise HTTPException(status_code=413)
        raw += part
    form = parse_qs(raw.decode("utf-8", errors="replace"))
    enabled = form.get("enabled") == ["true"]
    try:
        await run_in_threadpool(preference, tenant_id, user_id, token=token, enabled=enabled)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Enlace no disponible") from exc
    return HTMLResponse(
        _preference_html(enabled=enabled, saved=True),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _preference_html(*, enabled: bool, saved: bool) -> str:
    from qualify_api.mail.final_template import UNSUBSCRIBED

    message = (
        ("Listo. Volverás a recibir el correo de tus videos listos." if enabled else UNSUBSCRIBED)
        if saved
        else (
            "¿Quieres dejar de recibir el correo de tus videos listos?" if enabled else UNSUBSCRIBED
        )
    )
    label = "Deja de recibir estos correos" if enabled else "Volver a recibirlos"
    value = "false" if enabled else "true"
    return f'''<!doctype html><html lang="es"><head><meta name="viewport"
        content="width=device-width, initial-scale=1"><title>Qualify · Tus correos</title></head>
        <body style="margin:0;background:#f0f0f3;color:#1c2024;font-family:Arial,sans-serif;
        padding:24px">
        <main style="max-width:480px;margin:40px
        auto;background:#fff;padding:24px;border-radius:20px">
        <h1 style="font-size:24px">Tus correos de Qualify</h1><p>{message}</p>
        <form method="post"><input type="hidden" name="enabled" value="{value}">
        <button style="min-height:44px;padding:12px;background:#008573;color:#fff;
        border:0;border-radius:12px"
        type="submit">{label}</button></form><p><a href="/settings">Ir a Configuración</a></p>
        </main></body></html>'''
