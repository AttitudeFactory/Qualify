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

Manual trigger only, same product decision QUA-21 already made for comments (no scheduler,
no chaining after webhook receipt) — see `mentions_routes.py`'s module docstring for why
persistence itself stays synchronous-and-cheap inside the webhook handler, with analysis
deferred to an explicit, separate call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from qualify_api.mentions.repository import MentionsRepository
from qualify_api.sentiment.repository import AnalysisVersion

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


@dataclass(frozen=True)
class MentionAnalysisSummary:
    mentions_checked: int
    new_results: int
    skipped_empty: int


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

    def analyze_pending_mentions(self, *, tenant_id: UUID) -> MentionAnalysisSummary:
        # Lazy, same reason `SentimentService.analyze_pending_comments` defers this same
        # import: the one real runtime dependency this module has on `qualify_models`
        # (the `ml` group), deferred to the moment analysis actually runs.
        from qualify_models.social.ig_comments import analyze_text  # noqa: PLC0415

        pending = self._repository.list_pending_for_analysis(
            tenant_id=tenant_id, version=self._version
        )

        checked = 0
        new_results = 0
        skipped = 0
        for item in pending:
            checked += 1
            if not item.text.strip():
                skipped += 1
                continue
            result = analyze_text(
                item.text,
                source_id=str(item.mention_id),
                pipeline_version=self._version.pipeline_version,
                provider=self._provider,
            )
            inserted = self._repository.record_sentiment_result(
                tenant_id=tenant_id,
                mention_id=item.mention_id,
                version=self._version,
                label=result.label,
                score=result.score,
            )
            if inserted:
                new_results += 1

        return MentionAnalysisSummary(
            mentions_checked=checked, new_results=new_results, skipped_empty=skipped
        )
