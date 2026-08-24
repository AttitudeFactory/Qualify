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
"""

from qualify_api.sentiment.composition import (
    UnknownSentimentConnection,
    analyze_pending_comments,
    current_analysis_version,
)
from qualify_api.sentiment.repository import (
    AnalysisVersion,
    MemorySentimentRepository,
    PendingComment,
    PostgresSentimentRepository,
    SentimentRepository,
)
from qualify_api.sentiment.service import AnalysisSummary, SentimentService

__all__ = [
    "AnalysisSummary",
    "AnalysisVersion",
    "MemorySentimentRepository",
    "PendingComment",
    "PostgresSentimentRepository",
    "SentimentRepository",
    "SentimentService",
    "UnknownSentimentConnection",
    "analyze_pending_comments",
    "current_analysis_version",
]
