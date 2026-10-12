"""HTTP routes for the Instagram `mentions` webhook receiver + read API (QUA-49, QUA-147).

The webhook GET/POST pair mirrors `connections_routes.py`'s shape for the OAuth
callback: Meta calls both directly, so this is the one HTTP surface in the
`mentions` module that must exist unauthenticated by Qualify's own `Principal`
scheme (`http/deps.py`) — the caller is Meta, not a Qualify user. Trust here comes
from Meta's own mechanisms instead: `hub.verify_token` for the GET challenge,
`X-Hub-Signature-256` for the POST body.

**The POST only RECORDS (QUA-147).** A signature-valid delivery is written — raw body
and one row per change — to the intake log (`qualify_api.webhooks.receiver`, the
INSERT-only `qualify_webhook` role) and only then answered with 200. Everything that
used to happen inline — resolving `entry[].id` to a tenant, the `mentioned_media`/
`mentioned_comment` Graph calls, persisting the mention — now runs in
`qualify_api.webhooks.processor`, outside the request, with retries. The route no longer
touches `admin_session`, any BYPASSRLS role, or Meta. The callback URL is unchanged: one
Meta callback receives every subscribed field, so `comments` changes land in the same
log (recorded, processed as `unsupported` until their handler exists).

`GET /api/mentions` and `POST /api/mentions/analyze-sentiment` are the read/analysis
routes the Dashboard de Menciones and its sentiment counters consume — `Principal`-based
identity (C1), same shape `inbox_routes.py`/`sentiment_routes.py` already establish for
their own reads/triggers.

Dependencies are injected through FastAPI's `dependency_overrides` seam, same
posture `connections_routes.py`/`inbox_routes.py` already establish: tests
substitute fakes and run the whole contract with no network and no database.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from qualify_api.http.deps import Principal, current_principal
from qualify_api.mentions.config import MentionsWebhookSettings
from qualify_api.mentions.repository import MentionRecord
from qualify_api.mentions.sentiment import MentionAnalysisSummary
from qualify_api.mentions.signature import verify_signature
from qualify_api.webhooks.envelope import MAX_BODY_BYTES
from qualify_api.webhooks.receiver import RecordedDelivery

router = APIRouter(prefix="/api/mentions", tags=["mentions"])

_LOGGER = logging.getLogger(__name__)

DeliveryRecorder = Callable[..., RecordedDelivery]
ListMentions = Callable[..., tuple[MentionRecord, ...]]
AnalyzeMentionSentiment = Callable[..., MentionAnalysisSummary]


def get_webhook_settings() -> MentionsWebhookSettings:
    """Overridden at app startup (to `.from_env()`) and in tests. Raising here
    (rather than building a default) keeps an unconfigured deployment from
    silently accepting an unverified webhook — same posture
    `connections_routes.get_connect_service` already establishes."""
    raise NotImplementedError("mentions webhook settings dependency is not configured")


def get_delivery_recorder() -> DeliveryRecorder:
    """Overridden at app startup (to `webhooks.receiver.record_delivery`) and in tests (to
    a fake, so the HTTP/HMAC contract tests never touch Postgres). Raising here keeps an
    unconfigured deployment from answering 200 to a delivery it never recorded."""
    raise NotImplementedError("webhook delivery recorder dependency is not configured")


def get_list_mentions() -> ListMentions:
    """Overridden at app startup (to `composition.list_mentions_for_tenant`) and in
    tests. Same raise-until-wired posture as every other dependency here."""
    raise NotImplementedError("mentions list dependency is not configured")


def get_analyze_mention_sentiment() -> AnalyzeMentionSentiment:
    """Overridden at app startup (to `composition.analyze_pending_mentions`) and in
    tests. Lazy at the composition layer, not here — see that module's docstring for
    why `qualify_models` stays out of this route's import graph until the trigger is
    actually exercised."""
    raise NotImplementedError("mention sentiment analysis dependency is not configured")


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
    record: DeliveryRecorder = Depends(get_delivery_recorder),
) -> Response:
    """Size check, signature, durable record — and stop (QUA-147).

    - `413` for a body over `MAX_BODY_BYTES`; `403` for a missing/invalid
      `X-Hub-Signature-256`. Neither writes anything.
    - `200` only AFTER the delivery and its changes are committed — including a
      malformed body (recorded as `unparseable`: a retry would not fix it) and a
      byte-identical redelivery (already recorded).
    - `500` if the record fails, so Meta retries (it does for up to 36h,
      `webhooks-for-instagram.md:191-193`) instead of the event being lost behind a 200.

    No tenant resolution, no Graph call, no mention persistence here: those run in
    `qualify_api.webhooks.processor`.
    """
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
        # Never log `body` (Meta's payload, not ours to log wholesale) — the type only.
        _LOGGER.error(
            "meta webhook: delivery NOT recorded (%s) — answering 500", type(exc).__name__
        )
        return Response(status_code=500)

    _LOGGER.info(
        "meta webhook: delivery=%s duplicate=%s parse=%s changes=%d new=%d",
        recorded.delivery_id,
        recorded.duplicate_delivery,
        recorded.parse_status,
        recorded.changes_total,
        recorded.changes_new,
    )
    return Response(status_code=200)


# --------------------------------------------------------------------------
# Read API — the Dashboard de Menciones' data source (QUA-49)
# --------------------------------------------------------------------------


class MentionResponse(BaseModel):
    """One mention, HTTP-facing shape. `sentiment` is the string label (`POS`/`NEG`/
    `NEU`) or `None` ('Sin analizar') — never a display string; that projection belongs
    to whichever UI renders this (Reflex's `mentions_provider.py`), same division
    `CandidateMedia`/`inbox_provider.py` already draw between a service shape and a
    display one. No `views`/`plays` field: Meta does not expose one for a mention on
    content the connected account does not own (`MENTIONED_MEDIA_NO_VIEWS_CITATION`)."""

    id: UUID
    connection_id: UUID
    platform: str
    external_account_id: str
    media_id: str
    comment_id: str | None
    caption: str | None
    text: str | None
    author_username: str | None
    like_count: int | None
    content_posted_at: str | None
    received_at: str
    enrichment_status: str
    sentiment: str | None


def _to_response(record: MentionRecord) -> MentionResponse:
    return MentionResponse(
        id=record.id,
        connection_id=record.connection_id,
        platform=record.platform,
        external_account_id=record.external_account_id,
        media_id=record.media_id,
        comment_id=record.comment_id,
        caption=record.caption,
        text=record.text,
        author_username=record.author_username,
        like_count=record.like_count,
        content_posted_at=(
            record.content_posted_at.isoformat() if record.content_posted_at else None
        ),
        received_at=record.received_at.isoformat(),
        enrichment_status=record.enrichment_status,
        sentiment=record.sentiment_label,
    )


@router.get("", response_model=list[MentionResponse])
def list_mentions(
    connection_id: UUID | None = Query(None),
    principal: Principal = Depends(current_principal),
    list_mentions_for: ListMentions = Depends(get_list_mentions),
) -> list[MentionResponse]:
    """Newest-first mentions for the caller's tenant, optionally narrowed to one
    connection. Read-only, no Meta call — pure Postgres read via `composition.
    list_mentions_for_tenant`."""
    records = list_mentions_for(tenant_id=principal.tenant_id, connection_id=connection_id)
    return [_to_response(r) for r in records]


class AnalyzeMentionSentimentResponse(BaseModel):
    mentions_checked: int
    new_results: int
    skipped_empty: int


@router.post("/analyze-sentiment", response_model=AnalyzeMentionSentimentResponse)
def analyze_mention_sentiment(
    principal: Principal = Depends(current_principal),
    analyze: AnalyzeMentionSentiment = Depends(get_analyze_mention_sentiment),
) -> AnalyzeMentionSentimentResponse:
    """Runs ONE sentiment-analysis pass over the caller's tenant's un-analyzed
    mentions. Manual trigger, same product decision QUA-21 already made for comments —
    see `mentions/sentiment.py`'s module docstring. Idempotent by construction: a
    mention already analyzed under the current model version is never re-analyzed."""
    summary = analyze(tenant_id=principal.tenant_id)
    return AnalyzeMentionSentimentResponse(
        mentions_checked=summary.mentions_checked,
        new_results=summary.new_results,
        skipped_empty=summary.skipped_empty,
    )
