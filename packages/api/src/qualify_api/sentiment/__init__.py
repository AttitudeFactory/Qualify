"""Persisted, versioned sentiment analysis over a tenant's own Instagram comments
(QUA-21). Manual trigger only — no scheduler, no automatic run after
`inbox.sync_comments()`; both are explicit, separate design decisions this module
does not make on its own.

Reads `messages` rows QUA-20/88/89 already ingest (never re-parses a raw Meta
payload — `messages` does not retain the full `IGComment` shape, so this module
works with `text` + `source_id` directly, not a reconstructed comment object). The
model/type layer is `qualify_models.social.ig_comments.analyze_text`.

`analyze_pending_comments` is the published seam for HTTP (`http/sentiment_routes.py`)
— a plain function over ids, no HTTP hop internally, same role
`inbox.composition.sync_comments` has for its own module.

QUA-93 adds three read seams — `list_reel_summaries`, `global_sentiment_summary`,
`list_comments_for_thread` — replacing QUA-92's single unbounded
`list_comments_with_sentiment`. See `repository.py`'s module docstring for why: the
naive version of these queries silently regresses into a 28.5-second plan at real
scale, and the fix (`LATERAL` for the page/thread-bounded ones) is load-bearing, not
a style choice.
"""

from qualify_api.sentiment.composition import (
    UnknownSentimentConnection,
    analyze_pending_comments,
    current_analysis_version,
    global_sentiment_summary,
    list_comments_for_thread,
    list_reel_summaries,
)
from qualify_api.sentiment.repository import (
    DEFAULT_COMMENT_PAGE_SIZE,
    DEFAULT_REEL_PAGE_SIZE,
    NULL_POSTED_AT_SENTINEL,
    SENTIMENT_FILTER_PENDING,
    AnalysisVersion,
    AnalyzedComment,
    CommentListCursor,
    GlobalSentimentSummary,
    MemorySentimentRepository,
    PendingComment,
    PostgresSentimentRepository,
    ReelListCursor,
    ReelSummary,
    SentimentRepository,
)
from qualify_api.sentiment.service import AnalysisSummary, SentimentService

__all__ = [
    "DEFAULT_COMMENT_PAGE_SIZE",
    "DEFAULT_REEL_PAGE_SIZE",
    "NULL_POSTED_AT_SENTINEL",
    "SENTIMENT_FILTER_PENDING",
    "AnalysisSummary",
    "AnalysisVersion",
    "AnalyzedComment",
    "CommentListCursor",
    "GlobalSentimentSummary",
    "MemorySentimentRepository",
    "PendingComment",
    "PostgresSentimentRepository",
    "ReelListCursor",
    "ReelSummary",
    "SentimentRepository",
    "SentimentService",
    "UnknownSentimentConnection",
    "analyze_pending_comments",
    "current_analysis_version",
    "global_sentiment_summary",
    "list_comments_for_thread",
    "list_reel_summaries",
]
