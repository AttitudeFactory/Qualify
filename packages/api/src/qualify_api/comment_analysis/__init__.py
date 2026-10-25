"""Automatic comment prioritization (m-24852204): sentiment + commercial intent + the
queries they open, run after every comment sync and on the webhook worker's sweep. See
`runner.py` for the guarantees and `composition.py` for where each trigger lives."""

from qualify_api.comment_analysis.composition import (
    analyze_after_sync,
    sweep_pending_comment_analysis,
)
from qualify_api.comment_analysis.runner import (
    DEFAULT_BATCH,
    CommentAnalysisRunner,
    ConnectionAnalysisReport,
    SweepReport,
)

__all__ = [
    "DEFAULT_BATCH",
    "CommentAnalysisRunner",
    "ConnectionAnalysisReport",
    "SweepReport",
    "analyze_after_sync",
    "sweep_pending_comment_analysis",
]
