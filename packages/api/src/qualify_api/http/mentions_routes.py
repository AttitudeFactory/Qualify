"""HTTP routes for the Instagram `mentions` webhook receiver (QUA-49).

Two endpoints, same URL, mirroring `connections_routes.py`'s shape for the OAuth
callback: Meta calls both directly, so this is the one HTTP surface in the
`mentions` module that must exist. Deliberately UNAUTHENTICATED by Qualify's own
`Principal` scheme (`http/deps.py`) — the caller is Meta, not a Qualify user.
Trust here comes from Meta's own mechanisms instead: `hub.verify_token` for the
GET challenge, `X-Hub-Signature-256` for the POST body.

Scope, deliberately narrow (QUA-49's first cut): verify, parse, resolve tenant,
log. No persistence, no call to `mentioned_media`/`mentioned_comment`, no UI, no
`Capability` — those are later slices once this receptor is proven against real
Meta traffic. See `qualify_api.mentions.resolve` for why tenant resolution is
safe despite the payload carrying no `tenant_id`.

Dependencies are injected through FastAPI's `dependency_overrides` seam, same
posture `connections_routes.py`/`inbox_routes.py` already establish: tests
substitute fakes and run the whole contract with no network and no database.
`get_tenant_resolver`'s default IS the real `resolve_external_account` — unlike
`get_connect_service`/`get_sync_comments`, this one is a plain, side-effect-free
function (a single `SELECT`), not a stateful service, so there is nothing to
build lazily and nothing wrong with wiring the real thing as the default and
letting tests override it with a fake instead.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from qualify_shared.social.ig_shapes import MentionEvent, parse_mentions_notification

from qualify_api.mentions.config import MentionsWebhookSettings
from qualify_api.mentions.resolve import (
    PLATFORM_INSTAGRAM,
    ResolutionOutcome,
    TenantResolution,
)
from qualify_api.mentions.signature import verify_signature

router = APIRouter(prefix="/api/mentions", tags=["mentions"])

_LOGGER = logging.getLogger(__name__)

TenantResolver = Callable[..., TenantResolution]


def get_webhook_settings() -> MentionsWebhookSettings:
    """Overridden at app startup (to `.from_env()`) and in tests. Raising here
    (rather than building a default) keeps an unconfigured deployment from
    silently accepting an unverified webhook — same posture
    `connections_routes.get_connect_service` already establishes."""
    raise NotImplementedError("mentions webhook settings dependency is not configured")


def get_tenant_resolver() -> TenantResolver:
    """Overridden at app startup (to the real `resolve_external_account`) and in
    tests (to a fake, so the HTTP/HMAC contract tests never touch Postgres).
    Raising here, like every other dependency in this module, rather than
    defaulting to the real one directly — same reasoning
    `connections_routes.get_connect_service` gives: an unconfigured app should
    fail loudly, not silently pick a default. `test_mentions_resolve.py` covers
    `resolve_external_account` itself directly, against real Postgres."""
    raise NotImplementedError("mentions tenant resolver dependency is not configured")


@router.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    settings: MentionsWebhookSettings = Depends(get_webhook_settings),
) -> Response:
    """Meta's verification handshake
    (`docs/graph-api/webhooks/getting-started/webhooks-for-instagram.md:98-126`):
    echo `hub.challenge` back, plain text, iff `hub.verify_token` matches ours.
    `hub.mode` is always `"subscribe"` per that same doc; accepted but not
    branched on, since a wrong `hub.mode` with a right token carries no risk this
    check needs to distinguish.
    """
    if hub_verify_token != settings.verify_token:
        raise HTTPException(status_code=403, detail="invalid verify token")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    settings: MentionsWebhookSettings = Depends(get_webhook_settings),
    resolve: TenantResolver = Depends(get_tenant_resolver),
) -> Response:
    """Validate signature, parse, resolve tenant, log — and stop.

    Responds `200` for every case past signature validation, including a
    malformed body and an unresolved/ambiguous tenant
    (`webhooks-for-instagram.md:191-193`: "Your endpoint should respond to all
    Event Notifications with 200 OK"; Meta retries for up to 36h otherwise, and
    none of those failure modes are the kind a retry fixes). Signature failure is
    the one case that stays a 403: an unsigned/mis-signed body is not a confirmed
    Meta event, so treating it as untrusted and rejecting it costs nothing.
    """
    body = await request.body()
    if not verify_signature(
        body=body,
        signature_header=request.headers.get("x-hub-signature-256"),
        app_secret=settings.app_secret,
    ):
        raise HTTPException(status_code=403, detail="invalid signature")

    try:
        events = parse_mentions_notification(json.loads(body))
    except (ValueError, ValidationError) as exc:
        # Never log `body`: it is Meta's payload, already signature-verified as
        # genuine, but still not ours to put in a log line wholesale (same
        # discipline `CommentsReadError` establishes for a failed Graph response).
        _LOGGER.warning(
            "mentions webhook payload failed contract validation: %s", type(exc).__name__
        )
        return Response(status_code=200)

    for event in events:
        _resolve_and_log(event, resolve)
    return Response(status_code=200)


def _resolve_and_log(event: MentionEvent, resolve: TenantResolver) -> None:
    """One event's worth of resolution + logging. A free function (not inlined in
    the route) so `test_mentions_webhook.py` can also exercise it directly
    against a fake resolver without going through HTTP, if that turns out to be
    the more convenient shape for a given test.
    """
    resolution = resolve(platform=PLATFORM_INSTAGRAM, external_account_id=event.ig_user_id)
    # Numeric ids only, never `event.ig_user_id`'s surrounding context or any text field
    # (mentions events carry none, but the discipline matches `CommentsReadError`'s).
    if resolution.outcome is ResolutionOutcome.RESOLVED:
        _LOGGER.info(
            "mentions webhook: resolved tenant=%s connection=%s media_id=%s comment_id=%s",
            resolution.tenant_id,
            resolution.connection_id,
            event.media_id,
            event.comment_id,
        )
    elif resolution.outcome is ResolutionOutcome.ORPHAN:
        _LOGGER.warning(
            "mentions webhook: orphan event, no connection for external_account_id=%s",
            event.ig_user_id,
        )
    else:
        _LOGGER.error(
            "mentions webhook: AMBIGUOUS external_account_id=%s matches more than one "
            "tenant — event dropped, not associated with any of them",
            event.ig_user_id,
        )
