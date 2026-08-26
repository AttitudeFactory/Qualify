"""Production assembly for the sentiment module (QUA-21) — the analogue of
`inbox/composition.py`.

`analyze_pending_comments` below is the published seam: a plain function over ids, no
HTTP hop, same role `inbox.composition.sync_comments`/`connections.composition.
check_connection_health` have for their own modules. Its only caller today is
`http/sentiment_routes.py` — deliberately manual, deliberately not chained after
`inbox.composition.sync_comments()`. Adding that chaining, or a scheduler, is an
explicit, separate design decision this module does not make for itself.
"""

from __future__ import annotations

from functools import cache
from uuid import UUID

from qualify_shared.db.session import tenant_session

from qualify_api.connections.models import SocialConnection
from qualify_api.sentiment.repository import (
    DEFAULT_COMMENT_PAGE_SIZE,
    DEFAULT_REEL_PAGE_SIZE,
    AnalysisVersion,
    AnalyzedComment,
    CommentListCursor,
    GlobalSentimentSummary,
    PostgresSentimentRepository,
    ReelListCursor,
    ReelSummary,
)
from qualify_api.sentiment.service import AnalysisSummary, SentimentService


@cache
def current_analysis_version() -> AnalysisVersion:
    """The version this deployment analyzes under today. Lazy on purpose, like
    `build_production_publish_service`/`build_production_content_service` in
    `http/app.py`: `qualify_models` lives in the `ml` dependency group, deliberately
    excluded from the default `backend` install (CI included — see the root
    `pyproject.toml`'s `default-groups`), so `qualify_api` must never import it at
    module load time. `sentiment/__init__.py` re-exports this function, not a
    constant, for the same reason.

    `model_revision=None` is the honest value — `LocalRobertuitoSentimentProvider`
    does not pin a revision (see `qualify_models.schemas.SentimentResult`'s
    docstring). Bumping any of these fields makes every previously-analyzed comment
    "pending" again under the new version, by construction of
    `list_pending_for_analysis` — no backfill flag needed.
    """
    from qualify_models.sentiment import DETECTOR_VERSION, MODEL_ID  # noqa: PLC0415
    from qualify_models.social.ig_comments import (  # noqa: PLC0415
        OWNED_COMMENTS_PIPELINE_VERSION,
    )

    return AnalysisVersion(
        detector_version=DETECTOR_VERSION,
        pipeline_version=OWNED_COMMENTS_PIPELINE_VERSION,
        model_id=MODEL_ID,
        model_revision=None,
    )


class UnknownSentimentConnection(Exception):
    """No connection with this id is visible to this tenant. Deliberately duplicated
    rather than imported from `inbox`/`publishing` — same self-containment discipline
    every client module in this codebase already follows (see `inbox/composition.py`'s
    `PostgresIgUserIdReader` docstring)."""


def _require_connection_visible(*, tenant_id: UUID, connection_id: UUID) -> None:
    """Same shape as `inbox.composition.PostgresIgUserIdReader.read` and
    `publishing.composition.PostgresConnectionTargetReader.read` — read straight from
    `social_connections` through `tenant_session`, so RLS filters out another tenant's
    connection before this code ever sees it (missing and cross-tenant are the same
    case, on purpose)."""
    with tenant_session(tenant_id) as session:
        connection_row = session.get(SocialConnection, connection_id)
    if connection_row is None:
        raise UnknownSentimentConnection(
            f"connection {connection_id} is not visible to tenant {tenant_id}"
        )


@cache
def production_sentiment_service() -> SentimentService:
    """Cached like `production_publish_service()` — rebuilding per call would be
    pointless since nothing here holds a per-request credential (this module never
    talks to Meta)."""
    return SentimentService(
        repository=PostgresSentimentRepository(), version=current_analysis_version()
    )


def analyze_pending_comments(*, tenant_id: UUID, connection_id: UUID) -> AnalysisSummary:
    """The published seam. Synchronous — see `service.py`'s module docstring for why.
    Raises `UnknownSentimentConnection` if the connection id is not visible to this
    tenant."""
    _require_connection_visible(tenant_id=tenant_id, connection_id=connection_id)
    return production_sentiment_service().analyze_pending_comments(
        tenant_id=tenant_id, connection_id=connection_id
    )


def list_reel_summaries(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    cursor: ReelListCursor | None = None,
    limit: int = DEFAULT_REEL_PAGE_SIZE,
) -> tuple[ReelSummary, ...]:
    """QUA-93's published read seam for the Reel summary-card list — in-process, no HTTP
    hop, same role `analyze_pending_comments` has for the write side. Read-only: never
    analyzes, never calls Meta, never chains after a sync. Raises
    `UnknownSentimentConnection` if the connection id is not visible to this tenant."""
    _require_connection_visible(tenant_id=tenant_id, connection_id=connection_id)
    return production_sentiment_service().list_reel_summaries(
        tenant_id=tenant_id, connection_id=connection_id, cursor=cursor, limit=limit
    )


def global_sentiment_summary(*, tenant_id: UUID, connection_id: UUID) -> GlobalSentimentSummary:
    """QUA-93's published read seam for the top-of-page summary widget."""
    _require_connection_visible(tenant_id=tenant_id, connection_id=connection_id)
    return production_sentiment_service().global_sentiment_summary(
        tenant_id=tenant_id, connection_id=connection_id
    )


def list_comments_for_thread(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    thread_id: UUID,
    sentiment_filter: str | None = None,
    search: str | None = None,
    cursor: CommentListCursor | None = None,
    limit: int = DEFAULT_COMMENT_PAGE_SIZE,
) -> tuple[AnalyzedComment, ...]:
    """QUA-93's published read seam for the Reel detail view."""
    _require_connection_visible(tenant_id=tenant_id, connection_id=connection_id)
    return production_sentiment_service().list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        sentiment_filter=sentiment_filter,
        search=search,
        cursor=cursor,
        limit=limit,
    )
