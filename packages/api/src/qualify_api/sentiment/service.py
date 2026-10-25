"""The sentiment service (QUA-21): analyzes pending comments for one connection and
persists results, versioned. This module only knows how to run one pass when asked;
who asks lives outside it. Since m-24852204 (founder, 2026-10-24) that is automatic:
`qualify_api.comment_analysis` runs a bounded pass after every comment sync and on the
webhook worker's periodic sweep — the manual button is gone.

Synchronous throughout, same posture `connections.composition.check_connection_health`/
`revoke_connection` already establish: nothing here awaits network I/O (the model runs
locally via `SentimentProvider`, Postgres access is the ordinary blocking `tenant_session`
pattern every repository in this codebase uses). A caller off the event loop (a Reflex
background event, if this is ever wired to one) is responsible for `asyncio.to_thread`;
an HTTP route handler is not, since FastAPI already thread-pools a sync `def` endpoint —
see `connections_routes.start_connect` for the precedent this mirrors.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from qualify_api.sentiment.repository import (
    DEFAULT_COMMENT_PAGE_SIZE,
    DEFAULT_REEL_PAGE_SIZE,
    AnalysisVersion,
    AnalyzedComment,
    CommentListCursor,
    GlobalSentimentSummary,
    ReelListCursor,
    ReelSummary,
    SentimentRepository,
)

if TYPE_CHECKING:
    # `qualify_models` lives in the `ml` dependency group, deliberately excluded from
    # the default `backend` install (CI included) — see `composition.py`'s
    # `current_analysis_version` docstring. This import is type-checking-only: with
    # `from __future__ import annotations` active, the `provider: SentimentProvider |
    # None` annotation below is never evaluated at runtime, so no real import is
    # needed to run this module — only for mypy/pyright.
    from qualify_models.providers import SentimentProvider


# The packages `LocalRobertuitoSentimentProvider` (the default provider) imports when it
# first runs — the `ml` dependency group.
_LOCAL_MODEL_RUNTIME_MODULES = ("transformers", "torch")


logger = logging.getLogger(__name__)

# Raised by the model call when the model itself cannot run here (missing runtime or
# weights): an environment failure, never charged to one comment — it propagates, as
# before. Same split `mentions.sentiment` uses.
_ENVIRONMENT_ERRORS = (ImportError, OSError)
# ...except these OSError subclasses, which are about THIS call: isolated per comment.
_CALL_ERRORS = (ConnectionError, TimeoutError)


class SentimentModelUnavailable(Exception):
    """The local sentiment model cannot run here: its runtime (`transformers`/`torch`,
    the `ml` dependency group) is not installed. The production image deliberately ships
    without it (`deploy/Dockerfile`); without this check analysis would fail mid-pass, on
    the first non-empty comment, with a bare `ModuleNotFoundError`."""


#: m-24854340 (founder, 2026-10-25): the local model (robertuito: torch + ~435 MB of
#: weights) peaks at ~904 MiB RSS (m-24852538), far above the webhook worker's memory cap,
#: so the worker was OOM-killed whenever comments were pending. Sentiment is OFF unless
#: this is `1`/`true`/`yes`/`on`; temporary, until sentiment moves to Claude Haiku.
ENABLED_ENV = "QUALIFY_SENTIMENT_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def sentiment_enabled() -> bool:
    """Whether the local sentiment model may run in this process (off by default)."""
    return os.environ.get(ENABLED_ENV, "").strip().lower() in _TRUTHY


class SentimentDisabled(SentimentModelUnavailable):
    """Sentiment is switched off here (`QUALIFY_SENTIMENT_ENABLED`). A subclass of
    `SentimentModelUnavailable` on purpose: every caller already degrades on that one
    (skipped, never an error), and it is raised before anything imports the model."""


def local_model_available() -> bool:
    """Whether the default provider's runtime is installed — a `find_spec` probe, so
    nothing heavy is imported to answer it."""
    return all(importlib.util.find_spec(name) is not None for name in _LOCAL_MODEL_RUNTIME_MODULES)


@dataclass(frozen=True)
class AnalysisSummary:
    comments_checked: int
    new_results: int
    # Same restriction `analyze_comments` already enforces (QUA-21 AC5): a
    # whitespace-only comment is never classified, only counted.
    skipped_empty: int
    # m-24852236: comments whose classification raised this pass. Nothing is recorded
    # for them, so they stay pending and the next pass retries them; the rest of the
    # batch is analyzed regardless.
    failed: int = 0


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

    def analyze_pending_comments(
        self, *, tenant_id: UUID, connection_id: UUID, limit: int | None = None
    ) -> AnalysisSummary:
        """One pass over the connection's pending comments — the newest `limit` of them
        when bounded (m-24852204's automatic analysis), every one when `None`."""
        # m-24854340: the switch comes first, before `qualify_models` is even imported.
        # Only the DEFAULT (local) provider is switched off; an injected one is not.
        if self._provider is None and not sentiment_enabled():
            raise SentimentDisabled(f"{ENABLED_ENV} is off")
        # Lazy on purpose, same reason `SentimentProvider` above is TYPE_CHECKING-only:
        # this is the one real runtime dependency this module has on `qualify_models`
        # (the `ml` group), deferred to the moment analysis actually runs rather than
        # to module import time.
        from qualify_models.social.ig_comments import analyze_text  # noqa: PLC0415

        # Only the DEFAULT provider needs the local model; an injected one (a hosted
        # model, a test stub) does not. Checked before any read, so a deployment without
        # the `ml` group refuses cleanly instead of failing on the first comment.
        if self._provider is None and not local_model_available():
            raise SentimentModelUnavailable("the `ml` dependency group is not installed")

        pending = self._repository.list_pending_for_analysis(
            tenant_id=tenant_id, connection_id=connection_id, version=self._version, limit=limit
        )

        checked = 0
        new_results = 0
        skipped = 0
        failed = 0

        for comment in pending:
            checked += 1
            # `PendingComment.text` is guaranteed non-None by the repository — this is
            # the whitespace-only check `analyze_comments` already applies, kept
            # identical here rather than re-derived (QUA-21 AC5, restriction 1).
            if not comment.text.strip():
                skipped += 1
                continue

            try:
                result = analyze_text(
                    comment.text,
                    source_id=comment.source_id,
                    pipeline_version=self._version.pipeline_version,
                    provider=self._provider,
                )
            except _CALL_ERRORS as exc:
                failed += 1
                self._log_failure(comment.message_id, exc)
                continue
            except _ENVIRONMENT_ERRORS:
                raise
            except Exception as exc:  # noqa: BLE001 — one comment's failure, isolated
                failed += 1
                self._log_failure(comment.message_id, exc)
                continue
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
            comments_checked=checked,
            new_results=new_results,
            skipped_empty=skipped,
            failed=failed,
        )

    @staticmethod
    def _log_failure(message_id: UUID, exc: Exception) -> None:
        # Class name only: an exception message could echo the comment's text.
        logger.warning(
            "comment sentiment failed: message=%s error=%s", message_id, type(exc).__name__
        )

    def list_reel_summaries(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        cursor: ReelListCursor | None = None,
        limit: int = DEFAULT_REEL_PAGE_SIZE,
    ) -> tuple[ReelSummary, ...]:
        """QUA-93's read seam for the summary-card list: a page of Reels with their
        sentiment counts. Pure passthrough — no model, no network, no write — kept as a
        method for the same reason `list_pending_for_analysis` is: only
        `production_sentiment_service()` decides which `AnalysisVersion` backs it."""
        return self._repository.list_reel_summaries(
            tenant_id=tenant_id,
            connection_id=connection_id,
            version=self._version,
            cursor=cursor,
            limit=limit,
        )

    def global_sentiment_summary(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> GlobalSentimentSummary:
        """QUA-93's read seam for the top-of-page summary widget."""
        return self._repository.global_sentiment_summary(
            tenant_id=tenant_id, connection_id=connection_id, version=self._version
        )

    def list_comments_for_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        sentiment_filter: str | None = None,
        search: str | None = None,
        cursor: CommentListCursor | None = None,
        limit: int = DEFAULT_COMMENT_PAGE_SIZE,
        commercial_intent: AnalysisVersion | None = None,
    ) -> tuple[AnalyzedComment, ...]:
        """QUA-93's read seam for the Reel detail view: one Reel's comments, filtered,
        searched, paginated."""
        return self._repository.list_comments_for_thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            thread_id=thread_id,
            version=self._version,
            sentiment_filter=sentiment_filter,
            search=search,
            cursor=cursor,
            limit=limit,
            commercial_intent=commercial_intent,
        )
