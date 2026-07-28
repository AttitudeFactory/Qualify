"""Sentiment over comments on a client's own Instagram media.

This is the near-term win identified in `docs/fase0-zernio-mercado.md` §4.3 and
confirmed stage-by-stage in `oauth_scope.py`: comments on owned media are the
one surface where a Fase 1 cascade stage transfers **unchanged**. It needs no
scraping, no ClickHouse, no VLM and no GPU — a connected account, the comments
edge, and the existing robertuito sentiment stage.

PROVISIONAL FIELD SHAPES. `InstagramComment` is deliberately minimal and is NOT
grounded in the harvested Meta reference — that is task D1's job. Only fields
needed to compute and attribute polarity are modeled. Do not extend this into a
full payload contract here; extend it in D1 against the real reference.

NOT A CRM ENTITY. Nothing here names a table, column or CRM entity. How a
comment and its author map onto CRM records is the architect's call (task A2).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel

from qualify_models.providers import SentimentProvider
from qualify_models.schemas import SentimentResult
from qualify_models.sentiment import run_sentiment

# Bumped independently of the cascade's PIPELINE_VERSION: this path runs the
# sentiment stage alone, not the full cascade, so conflating the two would
# misattribute provenance.
OWNED_COMMENTS_PIPELINE_VERSION = "owned-comments-0.1.0"

POSITIVE_LABEL = "POS"
NEGATIVE_LABEL = "NEG"
NEUTRAL_LABEL = "NEU"


class InstagramComment(BaseModel):
    """One comment on a client's own media. Provisional shape — see module docstring."""

    id: str
    text: str
    timestamp: str | None = None
    username: str | None = None
    like_count: int | None = None
    parent_id: str | None = None


class CommentSentimentSummary(BaseModel):
    """Polarity roll-up for the comments on one piece of owned media."""

    media_id: str | None
    total_comments: int
    analyzed_comments: int
    skipped_empty: int
    label_counts: dict[str, int]
    net_sentiment: float | None
    results: list[SentimentResult]

    @property
    def negative_share(self) -> float | None:
        """Share of analyzed comments classified NEG.

        The number a crisis-alert threshold would eventually key on. Left as a
        plain ratio: no alerting threshold is proposed here, because no labelled
        data exists to calibrate one (same discipline as the F2 filter defect,
        NOTES_fase0_oauth_crm.md §2.4).
        """
        if self.analyzed_comments == 0:
            return None
        return self.label_counts.get(NEGATIVE_LABEL, 0) / self.analyzed_comments


def parse_comments_payload(payload: dict[str, Any]) -> list[InstagramComment]:
    """Parse a Graph-API-shaped `{"data": [...]}` envelope into typed comments.

    Unknown keys are ignored rather than rejected: the real payload carries more
    fields than polarity needs, and D1 owns the full contract.
    """
    raw = payload.get("data", [])
    if not isinstance(raw, list):
        raise ValueError("comments payload 'data' must be a list")
    return [InstagramComment.model_validate(item) for item in raw]


def analyze_comment(
    comment: InstagramComment,
    pipeline_version: str = OWNED_COMMENTS_PIPELINE_VERSION,
    provider: SentimentProvider | None = None,
) -> SentimentResult:
    """Polarity of one comment, attributed to that comment's own id.

    `source_id` is the Instagram comment id, so every derived signal traces back
    to the exact fragment it came from — the provenance rule in CLAUDE.md.
    """
    return run_sentiment(
        comment.text,
        source_id=comment.id,
        pipeline_version=pipeline_version,
        provider=provider,
    )


def analyze_comments(
    comments: list[InstagramComment],
    media_id: str | None = None,
    pipeline_version: str = OWNED_COMMENTS_PIPELINE_VERSION,
    provider: SentimentProvider | None = None,
) -> CommentSentimentSummary:
    """Polarity roll-up over the comments on one piece of owned media.

    Comments whose text is empty or whitespace-only are skipped rather than
    classified: an image-only or emoji-stripped comment carries no text for the
    model to read, and feeding it one would manufacture a label from nothing.
    They are counted in `skipped_empty` so the total still reconciles.
    """
    results: list[SentimentResult] = []
    skipped = 0

    for comment in comments:
        if not comment.text.strip():
            skipped += 1
            continue
        results.append(
            analyze_comment(comment, pipeline_version=pipeline_version, provider=provider)
        )

    counts = Counter(result.label for result in results)
    analyzed = len(results)
    net: float | None = None
    if analyzed:
        net = (counts.get(POSITIVE_LABEL, 0) - counts.get(NEGATIVE_LABEL, 0)) / analyzed

    return CommentSentimentSummary(
        media_id=media_id,
        total_comments=len(comments),
        analyzed_comments=analyzed,
        skipped_empty=skipped,
        label_counts=dict(counts),
        net_sentiment=net,
        results=results,
    )
