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
from typing import Any, Final

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

# QUA-21 AC4. Named, documented boundaries — not proposed as calibrated against
# labelled data, same discipline `CommentSentimentSummary.negative_share` already
# establishes for not proposing an alert threshold. (name, min_len, max_len|None).
COMMENT_LENGTH_BUCKETS: Final[tuple[tuple[str, int, int | None], ...]] = (
    ("short", 0, 39),
    ("medium", 40, 120),
    ("long", 121, None),
)


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
    # QUA-21 AC4: label counts grouped by `COMMENT_LENGTH_BUCKETS`. Computed, never
    # persisted as its own row — it is derivable from the per-comment `results`
    # (and their source text) at any time, so storing it separately would be a
    # second copy of the same fact.
    length_stratified: dict[str, dict[str, int]]

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


def analyze_text(
    text: str,
    source_id: str,
    pipeline_version: str = OWNED_COMMENTS_PIPELINE_VERSION,
    provider: SentimentProvider | None = None,
) -> SentimentResult:
    """Classify polarity of one text fragment, attributed to `source_id`.

    This is the primitive QUA-21's real service (`qualify_api.sentiment`) calls
    directly against `Message` rows (`text` + `external_message_id`) — deliberately
    NOT against an `IGComment`/`InstagramComment` object. `messages` does not
    retain the full `IGComment` shape (no `hidden`/`media`/`replies`/etc. survive
    `upsert_comment`), so reconstructing a fake `IGComment` just to satisfy a
    richer signature would be inventing fields QUA-67's contract exists to
    prevent. `analyze_comment` below is a thin convenience wrapper over this,
    kept for the offline fixture-based tests.

    Callers with a possibly-`None` text (e.g. a real `Message.text`, nullable in
    the DB) must check before calling — this function assumes `text` is a real
    string, same as `run_sentiment` always has.
    """
    return run_sentiment(
        text,
        source_id=source_id,
        pipeline_version=pipeline_version,
        provider=provider,
    )


def analyze_comment(
    comment: InstagramComment,
    pipeline_version: str = OWNED_COMMENTS_PIPELINE_VERSION,
    provider: SentimentProvider | None = None,
) -> SentimentResult:
    """Polarity of one comment, attributed to that comment's own id.

    `source_id` is the Instagram comment id, so every derived signal traces back
    to the exact fragment it came from — the provenance rule in CLAUDE.md.
    Convenience wrapper over `analyze_text` for the offline/fixture-based path;
    see that function's docstring for why the real service does not use this.
    """
    return analyze_text(
        comment.text,
        source_id=comment.id,
        pipeline_version=pipeline_version,
        provider=provider,
    )


def _length_bucket(text: str) -> str:
    length = len(text.strip())
    for name, lo, hi in COMMENT_LENGTH_BUCKETS:
        if length >= lo and (hi is None or length <= hi):
            return name
    return COMMENT_LENGTH_BUCKETS[-1][0]  # unreachable: the last bucket's hi is None


def stratify_by_length(pairs: list[tuple[str, SentimentResult]]) -> dict[str, dict[str, int]]:
    """Label counts grouped by comment-length bucket (QUA-21 AC4).

    Takes `(text, result)` pairs rather than re-deriving text from `result` —
    `SentimentResult` does not carry the source text, only `source_id`. Works
    equally over the offline fixture path and the real `Message`-backed path,
    since both ultimately have a text string and the `SentimentResult` it produced.
    """
    buckets: dict[str, dict[str, int]] = {name: {} for name, _, _ in COMMENT_LENGTH_BUCKETS}
    for text, result in pairs:
        bucket = buckets[_length_bucket(text)]
        bucket[result.label] = bucket.get(result.label, 0) + 1
    return buckets


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
    analyzed_pairs: list[tuple[str, SentimentResult]] = []
    skipped = 0

    for comment in comments:
        if not comment.text.strip():
            skipped += 1
            continue
        result = analyze_comment(comment, pipeline_version=pipeline_version, provider=provider)
        results.append(result)
        analyzed_pairs.append((comment.text, result))

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
        length_stratified=stratify_by_length(analyzed_pairs),
    )
