"""HTTP routes for the Instagram `mentions` webhook receiver + read API (QUA-49).

The webhook GET/POST pair mirrors `connections_routes.py`'s shape for the OAuth
callback: Meta calls both directly, so this is the one HTTP surface in the
`mentions` module that must exist unauthenticated by Qualify's own `Principal`
scheme (`http/deps.py`) — the caller is Meta, not a Qualify user. Trust here comes
from Meta's own mechanisms instead: `hub.verify_token` for the GET challenge,
`X-Hub-Signature-256` for the POST body.

A `RESOLVED` event is now enriched (`mentioned_media`/`mentioned_comment`) and
persisted — see `qualify_api.mentions.composition.ingest_mention` for the
orchestration. `ORPHAN`/`AMBIGUOUS` are still never persisted: a mention this
receiver could not confidently attribute to exactly one tenant must never become
a row associated with any tenant, correct or not (`resolve.py`'s own "no fuzzy
matching" discipline, now load-bearing for a WRITE, not just a log line).

`GET /api/mentions` and `POST /api/mentions/analyze-sentiment` are the read/analysis
routes the Dashboard de Menciones and its sentiment counters consume — `Principal`-based
identity (C1), same shape `inbox_routes.py`/`sentiment_routes.py` already establish for
their own reads/triggers.

Dependencies are injected through FastAPI's `dependency_overrides` seam, same
posture `connections_routes.py`/`inbox_routes.py` already establish: tests
substitute fakes and run the whole contract with no network and no database.
`get_tenant_resolver`'s default IS the real `resolve_external_account` — unlike
`get_mention_ingestor`/`get_list_mentions`/`get_analyze_mention_sentiment`, this one is a
plain, side-effect-free function (a single `SELECT`), not a stateful/Meta-calling
service, so there is nothing to build lazily and nothing wrong with wiring the real
thing as the default and letting tests override it with a fake instead.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ValidationError
from qualify_shared.social.ig_shapes import MentionEvent, parse_mentions_notification

from qualify_api.http.deps import Principal, current_principal
from qualify_api.mentions.config import MentionsWebhookSettings
from qualify_api.mentions.repository import MentionRecord
from qualify_api.mentions.resolve import (
    PLATFORM_INSTAGRAM,
    ResolutionOutcome,
    TenantResolution,
)
from qualify_api.mentions.sentiment import MentionAnalysisSummary
from qualify_api.mentions.signature import verify_signature

router = APIRouter(prefix="/api/mentions", tags=["mentions"])

_LOGGER = logging.getLogger(__name__)

TenantResolver = Callable[..., TenantResolution]
MentionIngestor = Callable[..., Awaitable[UUID | None]]
ListMentions = Callable[..., tuple[MentionRecord, ...]]
AnalyzeMentionSentiment = Callable[..., MentionAnalysisSummary]


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


def get_mention_ingestor() -> MentionIngestor:
    """Overridden at app startup (to `composition.ingest_mention`) and in tests (to a
    fake, so the webhook contract tests never touch Meta or Postgres). Raising here
    keeps an unconfigured deployment from silently discarding — or half-persisting — a
    real mention."""
    raise NotImplementedError("mention ingestor dependency is not configured")


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
    resolve: TenantResolver = Depends(get_tenant_resolver),
    ingest: MentionIngestor = Depends(get_mention_ingestor),
) -> Response:
    """Validate signature, parse, resolve tenant, enrich + persist — and stop.

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
        await _resolve_and_ingest(event, resolve, ingest)
    return Response(status_code=200)


async def _resolve_and_ingest(
    event: MentionEvent, resolve: TenantResolver, ingest: MentionIngestor
) -> None:
    """One event's worth of resolution, then either ingestion (RESOLVED) or a log-only
    refusal (ORPHAN/AMBIGUOUS). A free function (not inlined in the route) so
    `test_mentions_webhook.py` can also exercise it directly against fakes without going
    through HTTP.

    **ORPHAN/AMBIGUOUS never reach `ingest`.** This is the one invariant this function
    exists to hold: a mention this receiver could not confidently attribute to exactly
    one tenant must never become a persisted row associated with any tenant, correct or
    not — the same "no fuzzy matching" discipline `resolve.py` already documents for its
    own return value, now enforced here as a write-path guard, not merely a read-path
    guarantee.
    """
    resolution = resolve(platform=PLATFORM_INSTAGRAM, external_account_id=event.ig_user_id)
    # Numeric ids only, never `event.ig_user_id`'s surrounding context or any text field
    # (mentions events carry none, but the discipline matches `CommentsReadError`'s).
    if resolution.outcome is ResolutionOutcome.RESOLVED:
        mention_id = await ingest(
            media_id=event.media_id, comment_id=event.comment_id, resolution=resolution
        )
        if mention_id is None:
            # A tenant/connection WAS resolved but the mention was never persisted — the
            # defensive `None` branch `composition._content_client_for` documents ("should
            # not happen in practice"). Distinct from the happy path so this never reads
            # as a success in the logs: nothing was written for this event, and that is
            # the one thing worth an operator's attention here.
            _LOGGER.warning(
                "mentions webhook: tenant=%s connection=%s media_id=%s comment_id=%s "
                "resolved but NOT persisted — connection has no readable "
                "external_account_id (see composition._content_client_for)",
                resolution.tenant_id,
                resolution.connection_id,
                event.media_id,
                event.comment_id,
            )
        else:
            _LOGGER.info(
                "mentions webhook: resolved tenant=%s connection=%s media_id=%s comment_id=%s "
                "mention_id=%s",
                resolution.tenant_id,
                resolution.connection_id,
                event.media_id,
                event.comment_id,
                mention_id,
            )
    elif resolution.outcome is ResolutionOutcome.ORPHAN:
        _LOGGER.warning(
            "mentions webhook: orphan event, no connection for external_account_id=%s — "
            "not persisted",
            event.ig_user_id,
        )
    else:
        _LOGGER.error(
            "mentions webhook: AMBIGUOUS external_account_id=%s matches more than one "
            "tenant — event dropped, not associated with any of them, not persisted",
            event.ig_user_id,
        )


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
