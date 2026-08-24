"""The sentiment service (QUA-21): analyzes pending comments for one connection and
persists results, versioned. Manual trigger only, by product decision — no scheduler,
no automatic run chained after `inbox.sync_comments()`. That decision lives in the
composition/HTTP layer (there is nothing here that could call itself on a timer);
this module only knows how to run one pass when asked.

Synchronous throughout, same posture `connections.composition.check_connection_health`/
`revoke_connection` already establish: nothing here awaits network I/O (the model runs
locally via `SentimentProvider`, Postgres access is the ordinary blocking `tenant_session`
pattern every repository in this codebase uses). A caller off the event loop (a Reflex
background event, if this is ever wired to one) is responsible for `asyncio.to_thread`;
an HTTP route handler is not, since FastAPI already thread-pools a sync `def` endpoint —
see `connections_routes.start_connect` for the precedent this mirrors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from qualify_api.sentiment.repository import AnalysisVersion, SentimentRepository

if TYPE_CHECKING:
    # `qualify_models` lives in the `ml` dependency group, deliberately excluded from
    # the default `backend` install (CI included) — see `composition.py`'s
    # `current_analysis_version` docstring. This import is type-checking-only: with
    # `from __future__ import annotations` active, the `provider: SentimentProvider |
    # None` annotation below is never evaluated at runtime, so no real import is
    # needed to run this module — only for mypy/pyright.
    from qualify_models.providers import SentimentProvider


@dataclass(frozen=True)
class AnalysisSummary:
    comments_checked: int
    new_results: int
    # Same restriction `analyze_comments` already enforces (QUA-21 AC5): a
    # whitespace-only comment is never classified, only counted.
    skipped_empty: int


class SentimentService:
    def __init__(
        self,
        *,
        repository: SentimentRepository,
        version: AnalysisVersion,
        provider: SentimentProvider | None = None,
    ) -> None:
        self._repository = repository
        self._version = version
        self._provider = provider

    def analyze_pending_comments(self, *, tenant_id: UUID, connection_id: UUID) -> AnalysisSummary:
        # Lazy on purpose, same reason `SentimentProvider` above is TYPE_CHECKING-only:
        # this is the one real runtime dependency this module has on `qualify_models`
        # (the `ml` group), deferred to the moment analysis actually runs rather than
        # to module import time.
        from qualify_models.social.ig_comments import analyze_text  # noqa: PLC0415

        pending = self._repository.list_pending_for_analysis(
            tenant_id=tenant_id, connection_id=connection_id, version=self._version
        )

        checked = 0
        new_results = 0
        skipped = 0

        for comment in pending:
            checked += 1
            # `PendingComment.text` is guaranteed non-None by the repository — this is
            # the whitespace-only check `analyze_comments` already applies, kept
            # identical here rather than re-derived (QUA-21 AC5, restriction 1).
            if not comment.text.strip():
                skipped += 1
                continue

            result = analyze_text(
                comment.text,
                source_id=comment.source_id,
                pipeline_version=self._version.pipeline_version,
                provider=self._provider,
            )
            inserted = self._repository.record_sentiment_result(
                tenant_id=tenant_id,
                connection_id=connection_id,
                message_id=comment.message_id,
                source_id=comment.source_id,
                version=self._version,
                label=result.label,
                score=result.score,
            )
            if inserted:
                new_results += 1

        return AnalysisSummary(
            comments_checked=checked, new_results=new_results, skipped_empty=skipped
        )
