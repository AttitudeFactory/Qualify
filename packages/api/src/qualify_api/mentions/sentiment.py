"""Sentiment analysis for `mentions` (QUA-49) — the architecturally-correct reuse the
audit called for: SAME underlying model call `qualify_api.sentiment.service` already uses
for comments (`qualify_models.social.ig_comments.analyze_text`, one function that takes
raw text and returns a label/score — nothing about it is comment-shaped), over a
COMPLETELY SEPARATE persistence (`mention_sentiment_results`, `mentions/repository.py`).

## Why not just call `qualify_api.sentiment.service.analyze_pending_comments`

That function is hard-wired to `messages`/`comment_sentiment_results` end to end — its
repository protocol takes `message_id`, its versioning constant
(`OWNED_COMMENTS_PIPELINE_VERSION`) names the comments pipeline specifically, and its
`AnalyzedComment`/`ReelSummary` read shapes assume a `Thread`. Routing a mention through it
would require either forging a `messages` row for something that is not a conversational
message (no thread, no direction, no reply window — the exact conflation the audit
explicitly ruled out) or teaching that module to branch on "is this actually a comment",
which would make `messages`/`comment_sentiment_results` lie about what they hold. Neither
is "reuse" in any sense that keeps the schema honest.

## What IS reused, and why that is the right seam

`AnalysisVersion` (`qualify_api.sentiment.repository`) and the model identity itself
(`qualify_models.sentiment.DETECTOR_VERSION`/`MODEL_ID`) are genuinely generic — the same
`pysentimiento/robertuito-sentiment-analysis` checkpoint classifies any Spanish text, and
"which detector/model produced this label" is a fact about the MODEL, not about comments.
This module borrows both, mints its own `MENTIONS_PIPELINE_VERSION` (mentions are a
distinct content pipeline from owned comments — same reason `OWNED_COMMENTS_PIPELINE_VERSION`
exists as its own named constant rather than a shared unnamed one), and writes to its own
table. Bumping either the model constants or `MENTIONS_PIPELINE_VERSION` makes every
previously-analyzed mention "pending" again, same mechanism `sentiment/composition.py`
already documents for comments.

## Automatic since QUA-152 — after ingest, plus a sweep

The webhook intake processor analyzes a mention right after storing it, and its worker
sweeps every tenant's still-pending mentions periodically (`composition.
analyze_mention_after_ingest` / `sweep_pending_mention_sentiment`). The manual route
(`POST /api/mentions/analyze-sentiment`) runs this same pass. Three rules hold everywhere:

- **Never blocks ingestion.** Analysis runs only after the mention is committed; the
  after-ingest caller swallows any error, so the mention and its intake event are
  settled exactly as before.
- **Bounded retries, per mention.** A model call that raises on ONE mention is recorded in
  `mention_sentiment_failures` (class name only) and the pass moves on; after
  `MAX_SENTIMENT_ATTEMPTS` failures under the current version the mention is `ERROR` and
  is no longer offered. Idempotent: a result is unique per (mention, version), and an
  exhausted mention is never re-read.
- **Bound to the text it analyzed.** Each result and failed attempt carries the
  fingerprint of the text it was computed on (migration 0055). When "Actualizar menciones"
  stores an edited text, the old result stops counting, the mention is pending again and
  its attempts start from zero; an analysis still running on the old text is discarded
  at write time instead of passing for the new one.
- **An environment failure is not a mention failure.** When the model cannot run at all
  (`transformers`/`torch` missing, weights not loadable) the pass stops with
  `SentimentModelUnavailable` and records nothing — otherwise one bad deployment would
  burn every mention's attempts and mark them all `ERROR`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from qualify_api.mentions.repository import MentionsRepository, PendingMentionSentiment
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.sentiment.service import (
    ENABLED_ENV,
    SentimentDisabled,
    SentimentModelUnavailable,
    local_model_available,
    sentiment_enabled,
)

if TYPE_CHECKING:
    # Same TYPE_CHECKING-only import `sentiment/service.py` uses for the identical
    # reason: `qualify_models` lives in the `ml` dependency group, excluded from the
    # default install — this annotation is never evaluated at runtime
    # (`from __future__ import annotations` is active), so no real import happens here.
    from qualify_models.providers import SentimentProvider

# Mentions are their own content pipeline, distinct from
# `qualify_models.social.ig_comments.OWNED_COMMENTS_PIPELINE_VERSION` — bumping this
# re-queues every mention as pending under the new version, independent of comments.
MENTIONS_PIPELINE_VERSION = "mentions-text-1.0.0"

logger = logging.getLogger(__name__)

# Raised by the model call when the model itself cannot run here (missing runtime or
# weights): an environment failure, never charged to the mention being analyzed.
_ENVIRONMENT_ERRORS = (ImportError, OSError)
# ...except these OSError subclasses: a timeout or a dropped connection is about THIS call,
# so it is recorded against the mention (bounded retries) instead of stopping the pass.
_CALL_ERRORS = (ConnectionError, TimeoutError)


@dataclass(frozen=True)
class MentionAnalysisSummary:
    mentions_checked: int
    new_results: int
    skipped_empty: int
    failed: int = 0  # attempts recorded in `mention_sentiment_failures` this pass


class MentionSentimentService:
    def __init__(
        self,
        *,
        repository: MentionsRepository,
        version: AnalysisVersion,
        provider: SentimentProvider | None = None,
    ) -> None:
        self._repository = repository
        self._version = version
        self._provider = provider

    def analyze_pending_mentions(
        self, *, tenant_id: UUID, mention_id: UUID | None = None, limit: int | None = None
    ) -> MentionAnalysisSummary:
        """One pass over the tenant's pending mentions (or just `mention_id`). Raises
        `SentimentModelUnavailable` — having recorded nothing — when the model cannot run
        here; a failure on one mention is recorded and the pass continues."""
        # m-24854340: switched off before `qualify_models` is imported (default provider).
        if self._provider is None and not sentiment_enabled():
            raise SentimentDisabled(f"{ENABLED_ENV} is off")
        # Lazy, same reason `SentimentService.analyze_pending_comments` defers this same
        # import: the one real runtime dependency this module has on `qualify_models`
        # (the `ml` group), deferred to the moment analysis actually runs.
        from qualify_models.social.ig_comments import analyze_text  # noqa: PLC0415

        # Only the DEFAULT provider needs the local model; an injected one does not.
        if self._provider is None and not local_model_available():
            raise SentimentModelUnavailable("the sentiment model runtime is not installed")

        pending = self._repository.list_pending_for_analysis(
            tenant_id=tenant_id, version=self._version, mention_id=mention_id, limit=limit
        )

        checked = 0
        new_results = 0
        skipped = 0
        failed = 0
        for item in pending:
            checked += 1
            if not item.text.strip():
                skipped += 1
                continue
            try:
                result = analyze_text(
                    item.text,
                    source_id=str(item.mention_id),
                    pipeline_version=self._version.pipeline_version,
                    provider=self._provider,
                )
            except _CALL_ERRORS as exc:
                failed += 1
                self._record_failure(tenant_id, item, exc)
                continue
            except _ENVIRONMENT_ERRORS as exc:
                raise SentimentModelUnavailable(type(exc).__name__) from exc
            except Exception as exc:  # noqa: BLE001 — one mention's failure, recorded
                failed += 1
                self._record_failure(tenant_id, item, exc)
                continue
            inserted = self._repository.record_sentiment_result(
                tenant_id=tenant_id,
                mention_id=item.mention_id,
                version=self._version,
                label=result.label,
                score=result.score,
                text_md5=item.text_md5,
            )
            if inserted:
                new_results += 1

        return MentionAnalysisSummary(
            mentions_checked=checked,
            new_results=new_results,
            skipped_empty=skipped,
            failed=failed,
        )

    def _record_failure(
        self, tenant_id: UUID, item: PendingMentionSentiment, exc: Exception
    ) -> None:
        # Class name only: a message could echo the analyzed (user) text.
        self._repository.record_sentiment_failure(
            tenant_id=tenant_id,
            mention_id=item.mention_id,
            version=self._version,
            error_class=type(exc).__name__,
            text_md5=item.text_md5,
        )
        logger.warning(
            "mention sentiment failed: mention=%s error=%s", item.mention_id, type(exc).__name__
        )
