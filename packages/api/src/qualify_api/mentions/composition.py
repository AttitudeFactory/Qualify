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
    MentionRecord,
    MentionsRepository,
    NewMention,
    PostgresMentionsRepository,
)
from qualify_api.mentions.resolve import TenantResolution
from qualify_api.mentions.sentiment import (
    MENTIONS_PIPELINE_VERSION,
    MentionAnalysisSummary,
    MentionSentimentService,
)
from qualify_api.sentiment.repository import AnalysisVersion


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
    except MentionedContentReadError:
        # Never re-raise: the mention itself is still a real fact worth persisting even
        # when Meta's content endpoint refuses/fails (see module docstring). The specific
        # error is intentionally swallowed here — a numeric platform code, never a body,
        # same discipline every sibling client already keeps; a caller wanting that detail
        # should log it at the client layer, not thread it through this seam.
        enrichment_status = ENRICHMENT_FAILED

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
