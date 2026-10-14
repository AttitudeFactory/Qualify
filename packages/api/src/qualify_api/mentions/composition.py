"""Production assembly for the `mentions` module (QUA-49) — the analogue of
`inbox/composition.py` and `sentiment/composition.py`.

`ingest_mention` is the seam `mentions_routes.py`'s POST handler calls for every
`RESOLVED` event: build a credential-resolved client for THAT connection, attempt
enrichment (`mentioned_media` for a caption mention, `mentioned_comment` for a comment
mention — never both, decided by whether the event carries a `comment_id`), and persist
the result either way. **Enrichment failing is not an ingestion failure** — a mention
whose Meta call errored (still-pending Advanced Access, a transient 5xx) is persisted with
`enrichment_status="ENRICHMENT_FAILED"` and null content fields rather than being dropped;
the fact that Instagram mentioned this account IS the fact worth keeping, independent of
whether Meta's content API cooperated at that moment. Same "persist the fact, degrade the
content" posture already established across this codebase (`InboxService.sync_comments`
persists what it got before a mid-pagination truncation, rather than discarding it).

No enrichment retry path exists for an already-persisted mention (module docstring of
`repository.py`) — a redelivered webhook for the same event is a silent no-op via the
natural-key idempotency, it does not re-attempt a previously-failed enrichment. This is a
disclosed, deliberate gap (same class as QUA-88's "only `sync_comments`'s calls are
logged" scoping note), not an oversight: closing it is a scheduled-retry feature, out of
this slice's scope.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.mentions.meta_client import (
    HttpMentionedContentClient,
    MentionedContentReadError,
)
from qualify_api.mentions.repository import (
    DEFAULT_MENTION_PAGE_SIZE,
    ENRICHMENT_FAILED,
    ENRICHMENT_OK,
    MentionContent,
    MentionCounts,
    MentionPage,
    MentionQuery,
    MentionRecord,
    MentionsRepository,
    NewMention,
    PostgresMentionsRepository,
)
from qualify_api.mentions.resolve import TenantResolution, instagram_tenant_ids
from qualify_api.mentions.sentiment import (
    MENTIONS_PIPELINE_VERSION,
    MentionAnalysisSummary,
    MentionSentimentService,
)
from qualify_api.sentiment.repository import AnalysisVersion

_LOGGER = logging.getLogger(__name__)


class _ConnectionIgUserIdReader:
    """Reads only `external_account_id` from `social_connections` — duplicated from
    `inbox.composition.PostgresIgUserIdReader` rather than imported, same
    self-containment discipline every composition module in this codebase already
    follows independently of its siblings."""

    def read(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        with tenant_session(tenant_id) as session:
            return session.scalar(
                select(SocialConnection.external_account_id).where(
                    SocialConnection.id == connection_id
                )
            )


@cache
def production_mentions_repository() -> MentionsRepository:
    return PostgresMentionsRepository()


async def _content_client_for(
    *, tenant_id: UUID, connection_id: UUID
) -> tuple[HttpMentionedContentClient, str] | None:
    """Builds an authenticated `mentioned_media`/`mentioned_comment` client for one
    connection, plus that connection's own `ig_user_id` (the node these endpoints are
    queried against). Returns `None` if the connection is not visible to this tenant —
    should not happen in practice (`resolve_external_account` just produced this exact
    pair), but a defensive `None` here is cheaper than trusting that invariant blindly."""
    ig_user_id = _ConnectionIgUserIdReader().read(tenant_id=tenant_id, connection_id=connection_id)
    if ig_user_id is None:
        return None
    settings = MetaOAuthSettings.from_env()
    encryptor = DevEncryptor()
    resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), encryptor)
    graph_client = await resolver.client_for(connection_id, scheme=settings.graph_auth_scheme)
    return (
        HttpMentionedContentClient(graph_client=graph_client, graph_url=settings.graph_url),
        ig_user_id,
    )


async def ingest_mention(
    *,
    media_id: str,
    comment_id: str | None,
    resolution: TenantResolution,
) -> UUID | None:
    """Enrich (best-effort) and persist one `RESOLVED` mention event. Returns the
    persisted mention's id, or `None` if the connection turned out not to be resolvable
    to a live client (see `_content_client_for`).

    Enrichment picks exactly one endpoint: `mentioned_comment` when `comment_id` is
    present (a mention inside a comment), `mentioned_media` otherwise (a caption
    mention) — mirrors `MentionsChangeValue`'s own caption-vs-comment split, never both.
    """
    assert resolution.tenant_id is not None and resolution.connection_id is not None

    client_and_user = await _content_client_for(
        tenant_id=resolution.tenant_id, connection_id=resolution.connection_id
    )
    if client_and_user is None:
        return None
    client, ig_user_id = client_and_user

    caption: str | None = None
    text: str | None = None
    author_username: str | None = None
    media_type: str | None = None
    like_count: int | None = None
    content_posted_at = None
    enrichment_status = ENRICHMENT_OK

    try:
        if comment_id is not None:
            comment = await client.get_mentioned_comment(
                ig_user_id=ig_user_id, comment_id=comment_id
            )
            text = comment.text
            like_count = comment.like_count
            content_posted_at = comment.timestamp
        else:
            media = await client.get_mentioned_media(ig_user_id=ig_user_id, media_id=media_id)
            caption = media.caption
            author_username = media.username
            media_type = media.media_type
            like_count = media.like_count
            content_posted_at = media.timestamp
    except MentionedContentReadError as exc:
        # Never re-raise: the mention itself is still a real fact worth persisting even
        # when Meta's content endpoint refuses/fails (see module docstring). The mention
        # is still persisted below with ENRICHMENT_FAILED — this log line exists so an
        # operator can tell WHY without querying the DB and cross-referencing Meta's error
        # code table by hand; only the numeric platform code/subcode/http_status are
        # logged, never a body or any user-generated text, same discipline every sibling
        # client already keeps for its own `*ReadError`.
        enrichment_status = ENRICHMENT_FAILED
        _LOGGER.warning(
            "mentions enrichment failed, mention will be persisted as %s: media_id=%s "
            "comment_id=%s platform_code=%s platform_subcode=%s http_status=%s (%s)",
            ENRICHMENT_FAILED,
            media_id,
            comment_id,
            exc.platform_code,
            exc.platform_subcode,
            exc.http_status,
            type(exc).__name__,
        )

    permalink: str | None = None
    if enrichment_status == ENRICHMENT_OK:
        # QUA-152: best-effort, AFTER the content read and in its own call — a refusal
        # leaves the mention exactly as it would be without a link, never ENRICHMENT_FAILED.
        try:
            permalink = await client.get_mentioned_permalink(
                ig_user_id=ig_user_id, media_id=media_id, comment_id=comment_id
            )
        except MentionedContentReadError as exc:
            _LOGGER.info(
                "mentions permalink unavailable: media_id=%s comment_id=%s platform_code=%s "
                "http_status=%s",
                media_id,
                comment_id,
                exc.platform_code,
                exc.http_status,
            )

    mention = NewMention(
        tenant_id=resolution.tenant_id,
        connection_id=resolution.connection_id,
        external_account_id=ig_user_id,
        media_id=media_id,
        comment_id=comment_id,
        caption=caption,
        text=text,
        author_username=author_username,
        media_type=media_type,
        like_count=like_count,
        content_posted_at=content_posted_at,
        enrichment_status=enrichment_status,
        permalink=permalink,
    )
    mention_id, _created = production_mentions_repository().upsert_mention(mention)
    return mention_id


def list_mentions_for_tenant(
    *, tenant_id: UUID, connection_id: UUID | None = None, limit: int = DEFAULT_MENTION_PAGE_SIZE
) -> tuple[MentionRecord, ...]:
    """The published read seam for both the HTTP route and the Reflex Dashboard de
    Menciones — in-process, no HTTP hop for the Reflex caller, same role
    `inbox.composition.list_candidate_media` plays for its own module."""
    return production_mentions_repository().list_mentions(
        tenant_id=tenant_id,
        connection_id=connection_id,
        version=current_mention_analysis_version(),
        limit=limit,
    )


@dataclass(frozen=True)
class ContentRefreshReport:
    refreshed: int
    failed: int  # kept as they were: the network refused or the read failed


async def refresh_mentions_content(
    *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
) -> ContentRefreshReport:
    """ "Actualizar" (QUA-152): re-read each mention from its network and write back what
    changed — likes, text, author, link. One read per mention plus the best-effort link,
    for at most the visible page (12). A mention whose read fails keeps its stored data;
    nothing raises out of here."""
    repo = production_mentions_repository()
    targets = repo.list_refresh_targets(tenant_id=tenant_id, mention_ids=mention_ids)
    clients: dict[UUID, tuple[HttpMentionedContentClient, str] | None] = {}
    refreshed = failed = 0
    for target in targets:
        try:
            if target.connection_id not in clients:
                clients[target.connection_id] = await _content_client_for(
                    tenant_id=tenant_id, connection_id=target.connection_id
                )
            client_and_user = clients[target.connection_id]
            if client_and_user is None:
                failed += 1
                continue
            client, ig_user_id = client_and_user
            content = await _read_content(
                client,
                ig_user_id=ig_user_id,
                media_id=target.media_id,
                comment_id=target.comment_id,
            )
            if repo.refresh_content(
                tenant_id=tenant_id, mention_id=target.mention_id, content=content
            ):
                refreshed += 1
        except Exception as exc:  # noqa: BLE001 — keep the stored data, log the type only
            failed += 1
            _LOGGER.info(
                "mentions refresh kept stored content: mention=%s (%s)",
                target.mention_id,
                type(exc).__name__,
            )
    return ContentRefreshReport(refreshed=refreshed, failed=failed)


async def _read_content(
    client: HttpMentionedContentClient, *, ig_user_id: str, media_id: str, comment_id: str | None
) -> MentionContent:
    """The mention's content as the network gives it NOW. Raises on a refused content read
    (the caller keeps what it had); the link stays best-effort."""
    if comment_id is not None:
        comment = await client.get_mentioned_comment(ig_user_id=ig_user_id, comment_id=comment_id)
        caption, text, author, media_type = None, comment.text, None, None
        like_count, posted_at = comment.like_count, comment.timestamp
    else:
        media = await client.get_mentioned_media(ig_user_id=ig_user_id, media_id=media_id)
        caption, text, author, media_type = media.caption, None, media.username, media.media_type
        like_count, posted_at = media.like_count, media.timestamp
    try:
        permalink = await client.get_mentioned_permalink(
            ig_user_id=ig_user_id, media_id=media_id, comment_id=comment_id
        )
    except MentionedContentReadError:
        permalink = None
    return MentionContent(
        caption=caption,
        text=text,
        author_username=author,
        media_type=media_type,
        like_count=like_count,
        content_posted_at=posted_at,
        permalink=permalink,
    )


def list_mentions_page_for_tenant(
    *,
    tenant_id: UUID,
    query: MentionQuery,
    page: int,
    as_of: datetime | None = None,
) -> MentionPage:
    """The Dashboard de Menciones' read seam (QUA-152): one page of 12 over ALL stored
    mentions, with counts over the whole filtered set, under the snapshot `as_of`."""
    return production_mentions_repository().list_mentions_page(
        tenant_id=tenant_id,
        version=current_mention_analysis_version(),
        query=query,
        page=page,
        as_of=as_of,
    )


def summarize_mentions_for_tenant(
    *, tenant_id: UUID, query: MentionQuery, as_of: datetime
) -> MentionCounts:
    """The dashboard's summary cards (QUA-152): counts for the SCOPE query (account +
    period), under the same snapshot as the page — a search never moves them."""
    return production_mentions_repository().summarize(
        tenant_id=tenant_id,
        version=current_mention_analysis_version(),
        query=query,
        as_of=as_of,
    )


def count_new_mentions_for_tenant(*, tenant_id: UUID, query: MentionQuery, after: datetime) -> int:
    """Mentions matching `query` that arrived after the dashboard's snapshot, up to
    `NEW_MENTIONS_CAP` — what the new-mention notice shows (QUA-152)."""
    return production_mentions_repository().count_received_after(
        tenant_id=tenant_id,
        version=current_mention_analysis_version(),
        query=query,
        after=after,
    )


@cache
def current_mention_analysis_version() -> AnalysisVersion:
    """The version this deployment analyzes mentions under today. Lazy import, cached,
    same posture `sentiment.composition.current_analysis_version` documents for the
    identical reason (`qualify_models` lives in the `ml` group)."""
    from qualify_models.sentiment import DETECTOR_VERSION, MODEL_ID  # noqa: PLC0415

    return AnalysisVersion(
        detector_version=DETECTOR_VERSION,
        pipeline_version=MENTIONS_PIPELINE_VERSION,
        model_id=MODEL_ID,
        model_revision=None,
    )


@cache
def _production_mention_sentiment_service() -> MentionSentimentService:
    return MentionSentimentService(
        repository=production_mentions_repository(), version=current_mention_analysis_version()
    )


def analyze_pending_mentions(*, tenant_id: UUID) -> MentionAnalysisSummary:
    """The published seam for the manual sentiment trigger — mirrors
    `sentiment.composition.analyze_pending_comments`'s role for its own module."""
    return _production_mention_sentiment_service().analyze_pending_mentions(tenant_id=tenant_id)


def analyze_mention_after_ingest(*, tenant_id: UUID, mention_id: UUID) -> None:
    """Analyze the mention the intake processor just stored (QUA-152). NEVER raises: the
    mention is already committed and its intake event must settle exactly as it would
    without this call, so any failure — including the model being unavailable — is
    logged (class name only) and left to the worker's sweep."""
    try:
        _production_mention_sentiment_service().analyze_pending_mentions(
            tenant_id=tenant_id, mention_id=mention_id
        )
    except Exception as exc:  # noqa: BLE001 — sentiment must never fail an ingestion
        _LOGGER.warning(
            "mention sentiment after ingest skipped: mention=%s (%s)",
            mention_id,
            type(exc).__name__,
        )


@dataclass(frozen=True)
class SentimentSweepReport:
    tenants: int
    new_results: int
    failed: int
    tenants_errored: int  # the pass raised for that tenant (model unavailable, DB error)


def sweep_pending_mention_sentiment() -> SentimentSweepReport:
    """One pass over every tenant with an Instagram connection (QUA-152): analyzes what is
    still pending (never-analyzed, or failed below the attempt limit). One tenant's error
    never stops the others; nothing here raises."""
    try:
        tenant_ids = instagram_tenant_ids()
    except Exception as exc:  # noqa: BLE001 — a sweep must never crash its worker
        _LOGGER.warning("mention sentiment sweep: tenant listing failed (%s)", type(exc).__name__)
        return SentimentSweepReport(tenants=0, new_results=0, failed=0, tenants_errored=1)

    service = _production_mention_sentiment_service()
    new_results = failed = errored = 0
    for tenant_id in tenant_ids:
        try:
            summary = service.analyze_pending_mentions(tenant_id=tenant_id)
        except Exception as exc:  # noqa: BLE001 — next tenant
            errored += 1
            _LOGGER.warning(
                "mention sentiment sweep: tenant=%s skipped (%s)", tenant_id, type(exc).__name__
            )
            continue
        new_results += summary.new_results
        failed += summary.failed
    return SentimentSweepReport(
        tenants=len(tenant_ids), new_results=new_results, failed=failed, tenants_errored=errored
    )
