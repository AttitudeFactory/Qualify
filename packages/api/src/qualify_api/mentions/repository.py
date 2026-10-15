"""Persistence for `mentions` (QUA-49): idempotent writes, tenant-scoped reads, and the
sentiment-analysis bookkeeping. Same two-implementation discipline `inbox/repository.py`
and `sentiment/repository.py` establish — `MemoryMentionsRepository` is real production
code (offline suite + any in-process dev path), not a second, drifting test double.

**Idempotency is enforced by the database, not by a SELECT-then-INSERT here.**
`upsert_mention` always attempts the INSERT and interprets an `IntegrityError` against
`uq_mention_natural_key` as "already persisted" (same posture
`sentiment.repository.PostgresSentimentRepository.record_sentiment_result` already takes
for its own versioned unique index) — a redelivered webhook is a silent no-op, never a
race between two concurrent deliveries of the same event.

**Sentiment stays a SEPARATE, versioned table (`mention_sentiment_results`), never a
column mutated on `Mention`.** Reading a mention's current sentiment is a join against the
CURRENT `AnalysisVersion`, reusing the exact same versioning type
`qualify_api.sentiment.repository.AnalysisVersion` already defines for comments — the type
is generic over "what was analyzed", nothing about it is comment-specific, so importing it
here is reuse, not a comment-shaped model deforming what a mention is.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import (
    ColumnElement,
    Subquery,
    and_,
    case,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qualify_api.mentions.models import (
    Mention,
    MentionSentimentFailure,
    MentionSentimentResult,
)
from qualify_api.sentiment.repository import AnalysisVersion

ENRICHMENT_PENDING = "PENDING"
ENRICHMENT_OK = "ENRICHED"
ENRICHMENT_FAILED = "ENRICHMENT_FAILED"

DEFAULT_MENTION_PAGE_SIZE = 50

# QUA-152: the Dashboard de Menciones pages through EVERY stored mention, 12 at a time.
# `DEFAULT_MENTION_PAGE_SIZE` above stays as the bound of the legacy `list_mentions` read
# (the HTTP route still uses it); the dashboard no longer does.
MENTIONS_PAGE_SIZE = 12
# The new-mention notice counts at most this many ("50+"). It bounds the NOTICE only —
# never the paginated set.
NEW_MENTIONS_CAP = 50

# Where the @mention was made: in the caption of a media, or inside a comment on it.
ORIGIN_POST = "post"
ORIGIN_COMMENT = "comment"
ORIGINS = (ORIGIN_POST, ORIGIN_COMMENT)

# The sentiment state of one mention under the CURRENT analysis version. Only a real
# `mention_sentiment_results` row yields POS/NEU/NEG; everything else is its own state and
# is never counted as a polarity.
SENTIMENT_POS = "POS"
SENTIMENT_NEU = "NEU"
SENTIMENT_NEG = "NEG"
SENTIMENT_PENDING = "PENDING"  # has text, no result yet (includes "failed, will retry")
SENTIMENT_NO_TEXT = "NO_TEXT"  # nothing to analyze (no caption/text, or blank)
SENTIMENT_ERROR = "ERROR"  # every allowed attempt failed under the current version
SENTIMENT_STATES = (
    SENTIMENT_POS,
    SENTIMENT_NEU,
    SENTIMENT_NEG,
    SENTIMENT_PENDING,
    SENTIMENT_NO_TEXT,
    SENTIMENT_ERROR,
)

# A removed mention (migration 0062) is re-read at most once per this window, with the
# capacity a refresh run has left: "no longer available" can end (an account made public
# again, a block lifted), and a successful read shows it again.
REMOVED_RECHECK_SECONDS = 24 * 60 * 60
# At most this many removed mentions are re-checked per run: optional work the person is
# waiting behind, so it stays small however much room the run has left.
REMOVED_RECHECK_PER_RUN = 20
# A mention removed longer ago than this is no longer re-checked (QUA-152, 2026-10-15):
# after a month, coming back is rare and every recheck spends Meta budget. The row and its
# content stay as they are — what happens to them later is QUA-127's retention decision.
# Measured from `removed_at`, the FIRST removal (a repeated removal keeps that stamp; a
# successful read clears it, so a later removal starts a new window).
REMOVED_RECHECK_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

# A mention is analyzed at most this many times per analysis version (migration 0051
# records each failed attempt). After that it is `ERROR` and no longer retried, until a
# new model/pipeline version starts its attempts from zero.
MAX_SENTIMENT_ATTEMPTS = 3


# What a bounded sentiment pass treats as blank, in SQL: exactly the characters Python's
# `str.isspace()` accepts — the service skips a text whose `strip()` is empty — listed
# explicitly because Postgres' `\s` follows the locale and may miss the Unicode ones.
_BLANK_CHARS = r"[\s\u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"


def analysis_text_md5(text: str | None, caption: str | None) -> str | None:
    """Python twin of the generated column `mentions.analysis_text_md5` (migration 0055):
    MD5 of what the analyzer reads (comment text, else caption), or None without either.
    A change detector, not a security primitive."""
    content = text if text is not None else caption
    if content is None:
        return None
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class NewMention:
    """The repository's write input — everything needed to persist one resolved mention.
    Assembled by `mentions/composition.py` after resolution + (attempted) enrichment; this
    module never calls Meta and never resolves a tenant, it only stores what it is given.
    """

    tenant_id: UUID
    connection_id: UUID
    external_account_id: str
    media_id: str
    comment_id: str | None
    caption: str | None
    text: str | None
    author_username: str | None
    media_type: str | None
    like_count: int | None
    content_posted_at: datetime | None
    enrichment_status: str
    permalink: str | None = None  # QUA-152: best-effort link to the media on Instagram


@dataclass(frozen=True)
class MentionRecord:
    """One persisted mention, read-projected. `sentiment_label` is the CURRENT-version
    `mention_sentiment_results.label`, or `None` when not yet analyzed — structurally
    distinct from any real label the same way `AnalyzedComment.label` already is."""

    id: UUID
    connection_id: UUID
    platform: str
    external_account_id: str
    media_id: str
    comment_id: str | None
    caption: str | None
    text: str | None
    author_username: str | None
    like_count: int | None
    content_posted_at: datetime | None
    received_at: datetime
    enrichment_status: str
    sentiment_label: str | None
    # QUA-152 additions, filled by `list_mentions_page`. Defaulted so the legacy
    # `list_mentions` projection (and its callers) stay unchanged.
    media_type: str | None = None
    sentiment_state: str = SENTIMENT_PENDING
    permalink: str | None = None


@dataclass(frozen=True)
class RefreshTarget:
    """What re-reading one stored mention from its network needs (QUA-152)."""

    mention_id: UUID
    connection_id: UUID
    media_id: str
    comment_id: str | None
    has_permalink: bool = False  # a stored link is never re-requested (it does not change)
    # A removed mention re-read to see whether it is available again (migration 0062). It
    # is outside the scope's counts: a run reports it only when it comes back.
    removed: bool = False


@dataclass(frozen=True)
class RefreshPlan:
    """One bounded refresh run over a scope (QUA-152): what to re-read now, and how the
    scope stands. `in_scope - fresh - len(targets)` mentions are left for a later run."""

    targets: tuple[RefreshTarget, ...]
    in_scope: int  # every mention of the scope
    fresh: int  # re-read successfully within the freshness window — not requested again
    # Attempted within the window and failed (e.g. by the visible pass of the same click):
    # not requested again, reported as failed.
    recently_failed: int = 0


@dataclass(frozen=True)
class MentionContent:
    """A fresh, SUCCESSFUL read of a mention's content — what "Actualizar" writes back.

    `None` means "the network did not give this field in this read", and the stored value
    is KEPT: an omitted field is not evidence that the value is gone. An explicit value is
    always written, `like_count=0` included. A failed read never reaches the repository, so
    it can never erase anything either."""

    caption: str | None
    text: str | None
    author_username: str | None
    media_type: str | None
    like_count: int | None
    content_posted_at: datetime | None
    permalink: str | None


@dataclass(frozen=True)
class MentionQuery:
    """The dashboard's filters (QUA-152). Every field narrows; `None`/`""` means "all".

    `search` matches caption, comment text and the publication author's username, case-
    insensitively, with any leading "@" ignored — Meta strips the "@" from third-party
    captions, so "@marca" and "marca" must find the same rows.
    """

    connection_id: UUID | None = None
    origin: str | None = None  # ORIGIN_POST / ORIGIN_COMMENT
    sentiment_state: str | None = None  # one of SENTIMENT_STATES
    search: str = ""
    # Only mentions whose date (publication, or reception when unknown) is on/after this.
    # A VIEW window: nothing is deleted or hidden from storage.
    since: datetime | None = None

    def __post_init__(self) -> None:
        if self.origin is not None and self.origin not in ORIGINS:
            raise ValueError(f"invalid origin: {self.origin!r}")
        if self.sentiment_state is not None and self.sentiment_state not in SENTIMENT_STATES:
            raise ValueError(f"invalid sentiment_state: {self.sentiment_state!r}")

    @property
    def search_term(self) -> str:
        return self.search.strip().lstrip("@").strip()


@dataclass(frozen=True)
class MentionCounts:
    """Aggregates over the WHOLE filtered set inside the snapshot — never over one page."""

    total: int = 0
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    pending: int = 0
    no_text: int = 0
    error: int = 0


@dataclass(frozen=True)
class MentionPage:
    """One page of the dashboard. `as_of` is the snapshot every page of this listing is
    read under (`received_at <= as_of`): paging with the same `as_of` walks a fixed set,
    so a mention arriving meanwhile can neither duplicate nor shift a row."""

    rows: tuple[MentionRecord, ...]
    counts: MentionCounts
    page: int
    page_size: int
    as_of: datetime
    total_pages: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "total_pages", max(1, math.ceil(self.counts.total / self.page_size))
        )


def sentiment_state_for(
    *,
    label: str | None,
    text: str | None,
    caption: str | None,
    failed_attempts: int = 0,
    max_attempts: int = MAX_SENTIMENT_ATTEMPTS,
) -> str:
    """The one definition of a mention's sentiment state; the Postgres query mirrors it
    in SQL (`PostgresMentionsRepository._filtered`). A real result wins; otherwise no
    analyzable text is `NO_TEXT` (never sent to the model); otherwise every allowed attempt
    having failed is `ERROR`; otherwise it is still `PENDING` (possibly retrying)."""
    if label is not None:
        return label
    content = text if text is not None else caption
    if content is None or not content.strip():
        return SENTIMENT_NO_TEXT
    if failed_attempts >= max_attempts:
        return SENTIMENT_ERROR
    return SENTIMENT_PENDING


def _clamp_page(page: int, total: int, page_size: int) -> int:
    """Pages are 1-based; a page past the end (rows deleted meanwhile, a stale link)
    lands on the last valid page instead of an empty one."""
    last = max(1, math.ceil(total / page_size))
    return min(max(1, page), last)


def _record(m: Mention, *, sentiment_label: str | None, sentiment_state: str) -> MentionRecord:
    return MentionRecord(
        id=m.id,
        connection_id=m.connection_id,
        platform=m.platform,
        external_account_id=m.external_account_id,
        media_id=m.media_id,
        comment_id=m.comment_id,
        caption=m.caption,
        text=m.text,
        author_username=m.author_username,
        like_count=m.like_count,
        content_posted_at=m.content_posted_at,
        received_at=m.received_at,
        enrichment_status=m.enrichment_status,
        sentiment_label=sentiment_label,
        media_type=m.media_type,
        sentiment_state=sentiment_state,
        permalink=m.permalink,
    )


@dataclass(frozen=True)
class PendingMentionSentiment:
    """One mention with real text (caption or comment text) awaiting analysis under the
    current model version. `text` is guaranteed non-empty — callers never re-check."""

    mention_id: UUID
    text: str
    # `analysis_text_md5` of `text` (migration 0055): the result is recorded against it, so
    # a result computed on a text that has since changed never passes for the new one.
    text_md5: str | None = None


class MentionsRepository(Protocol):
    def upsert_mention(self, mention: NewMention) -> tuple[UUID, bool]:
        """Insert a mention, idempotent on `(connection_id, media_id, comment_id)`
        (COALESCE-normalized — migration 0013). Returns `(mention_id, created)`:
        `created=False` means this exact event was already persisted, and the id
        returned is the EXISTING row's — a caller never has to branch on which
        happened to know which mention id to log/reference."""
        ...

    def list_mentions(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        version: AnalysisVersion,
        limit: int = DEFAULT_MENTION_PAGE_SIZE,
    ) -> tuple[MentionRecord, ...]:
        """Newest-first mentions for a tenant, optionally narrowed to one connection, each
        decorated with its CURRENT-version sentiment label if analyzed. Bounded by
        `limit` — same "never an unbounded read" discipline QUA-93 established for
        comments, at a scale where it does not yet need QUA-93's LATERAL treatment."""
        ...

    def list_mentions_page(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        page: int,
        as_of: datetime | None = None,
        page_size: int = MENTIONS_PAGE_SIZE,
    ) -> MentionPage:
        """One page of the tenant's mentions matching `query`, read under the snapshot
        `as_of` (`received_at <= as_of`; `None` = take a new snapshot now). Ordered by
        publication date (reception date when unknown), newest first, ties broken by
        `id` — a total order, so walking every page yields every row exactly once. No
        overall cap: this pages through ALL stored mentions (QUA-152)."""
        ...

    def count_received_after(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        after: datetime,
        cap: int = NEW_MENTIONS_CAP,
    ) -> int:
        """How many mentions matching `query` arrived after `after`, counted up to `cap`
        (the new-mention notice shows "50+"). Never changes the paginated set."""
        ...

    def summarize(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        as_of: datetime,
    ) -> MentionCounts:
        """The same counts as a page, for `query` alone under the snapshot `as_of` — the
        dashboard's summary cards use it with the SCOPE only (account + period), so a
        search or a type/sentiment filter never moves them (founder review 2026-10-13)."""
        ...

    def list_pending_for_analysis(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        mention_id: UUID | None = None,
        max_attempts: int = MAX_SENTIMENT_ATTEMPTS,
        limit: int | None = None,
    ) -> tuple[PendingMentionSentiment, ...]:
        """Mentions with text and no current-version result whose failed attempts are
        below `max_attempts` — an exhausted mention is never offered again (QUA-152).
        `mention_id` narrows to that one mention (the after-ingest analysis); `limit` bounds
        one pass, oldest first."""
        ...

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
        text_md5: str | None = None,
    ) -> bool:
        """Returns `True` if a new row was inserted, `False` if this exact
        (mention, version, text) tuple was already recorded — never raises on a duplicate,
        same contract `sentiment.repository`'s own `record_sentiment_result` has.

        With `text_md5` (QUA-152, migration 0055) nothing is written when the mention's text
        has changed since it was read for analysis: a stale result never lands."""
        ...

    def record_sentiment_failure(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        error_class: str,
        text_md5: str | None = None,
    ) -> None:
        """Append one failed attempt (migration 0051). `error_class` is an exception class
        name, never a message (a message could echo the analyzed text)."""
        ...

    def list_refresh_targets(
        self, *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
    ) -> tuple[RefreshTarget, ...]:
        """The ids "Actualizar" needs to re-read these mentions — tenant-scoped."""
        ...

    def plan_scope_refresh(
        self,
        *,
        tenant_id: UUID,
        query: MentionQuery,
        fresh_seconds: int,
        limit: int,
        recheck_removed_seconds: int = REMOVED_RECHECK_SECONDS,
        recheck_removed_max_age_seconds: int = REMOVED_RECHECK_MAX_AGE_SECONDS,
    ) -> RefreshPlan:
        """The next bounded run over the SCOPE of `query` — its account and period only
        (`connection_id`, `since`); origin, sentiment and search never narrow a refresh.
        Skips mentions re-read successfully in the last `fresh_seconds`, and those whose
        last attempt in that window failed (`recently_failed`); of the rest, takes
        the `limit` least recently ATTEMPTED (never-attempted first), so mentions the
        network keeps refusing cannot starve the others (migration 0054).

        Removed mentions never count in the scope. Only when the live ones leave room
        under `limit`, up to REMOVED_RECHECK_PER_RUN of those not attempted for
        `recheck_removed_seconds` are appended (`RefreshTarget.removed`), least recently
        attempted first — and only while removed for at most
        `recheck_removed_max_age_seconds` (`removed_at` on or after now minus that age,
        on the same clock that stamped it)."""
        ...

    def refresh_content(
        self, *, tenant_id: UUID, mention_id: UUID, content: MentionContent
    ) -> bool:
        """Write a fresh read (QUA-152, migrations 0053/0054): every field the read GAVE is
        stored — `like_count=0` included — and every field it omitted (`None`) keeps its
        stored value. Marks the row ENRICHED and stamps both refresh timestamps. A
        successful read proves the content exists, so a removed mention shows again
        (`removed_at` cleared). Returns False when the mention is not this tenant's."""
        ...

    def mark_refresh_attempt(self, *, tenant_id: UUID, mention_id: UUID) -> None:
        """A re-read was attempted and failed: stamp the attempt only (fair ordering of
        the next run). Content and `content_refreshed_at` are untouched."""
        ...

    def mark_removed(
        self, *, tenant_id: UUID, mention_id: UUID, unless_read_after: datetime | None = None
    ) -> bool:
        """The network says the mentioned content is no longer available (migration 0062):
        stamp `removed_at` (and the attempt), so every read excludes the mention until a
        successful read clears it. Content is kept. Idempotent: an already-removed mention
        keeps its first stamp and still returns True (another run removed it first).

        Returns False — nothing written — when the mention is not this tenant's, or was
        read successfully AFTER `unless_read_after` (the moment the refusing read started):
        another tab or the comments webhook read it meanwhile, and that newer evidence
        says it exists. A read from before that moment never protects it."""
        ...

    def fill_missing_comment_fields(
        self, *, tenant_id: UUID, mention_id: UUID, text: str | None, author_username: str | None
    ) -> bool:
        """Complete a COMMENT mention already stored by another path (the `mentions` webhook
        stores no author): each given value is written only where the column is still
        NULL — never over a stored value. Writing a text where there was none also marks
        the row ENRICHED. Returns True when anything changed."""
        ...


def _error_class(name: str) -> str:
    """Bound to the 0051 CHECK (1..200 chars) so recording a failure can never itself fail."""
    return (name or "Exception")[:200]


def _failure_version_filter(version: AnalysisVersion) -> list[ColumnElement[bool]]:
    """Failures of `version` on the mention's CURRENT text (migration 0055)."""
    return [
        MentionSentimentFailure.text_md5.is_not_distinct_from(Mention.analysis_text_md5),
        MentionSentimentFailure.detector_version == version.detector_version,
        MentionSentimentFailure.pipeline_version == version.pipeline_version,
        MentionSentimentFailure.model_id == version.model_id,
        MentionSentimentFailure.model_revision.is_(None)
        if version.model_revision is None
        else MentionSentimentFailure.model_revision == version.model_revision,
    ]


def _result_version_filter(version: AnalysisVersion) -> list[ColumnElement[bool]]:
    """The result of `version` computed on the mention's CURRENT text (migration 0055):
    a result on an older text no longer counts, so the mention is pending again."""
    return [
        MentionSentimentResult.mention_id == Mention.id,
        MentionSentimentResult.text_md5.is_not_distinct_from(Mention.analysis_text_md5),
        MentionSentimentResult.detector_version == version.detector_version,
        MentionSentimentResult.pipeline_version == version.pipeline_version,
        MentionSentimentResult.model_id == version.model_id,
        MentionSentimentResult.model_revision.is_(None)
        if version.model_revision is None
        else MentionSentimentResult.model_revision == version.model_revision,
    ]


def _version_key(version: AnalysisVersion) -> tuple[str, str, str, str]:
    return (
        version.detector_version,
        version.pipeline_version,
        version.model_id,
        version.model_revision or "",
    )


def _sql_counts(
    session: Session, inner: Subquery, conditions: list[ColumnElement[bool]]
) -> MentionCounts:
    state = inner.c.sentiment_state
    totals = session.execute(
        select(
            func.count(),
            func.count().filter(state == SENTIMENT_POS),
            func.count().filter(state == SENTIMENT_NEU),
            func.count().filter(state == SENTIMENT_NEG),
            func.count().filter(state == SENTIMENT_PENDING),
            func.count().filter(state == SENTIMENT_NO_TEXT),
            func.count().filter(state == SENTIMENT_ERROR),
        ).where(*conditions)
    ).one()
    return MentionCounts(
        total=totals[0],
        positive=totals[1],
        neutral=totals[2],
        negative=totals[3],
        pending=totals[4],
        no_text=totals[5],
        error=totals[6],
    )


def _counts_of(states: list[str]) -> MentionCounts:
    return MentionCounts(
        total=len(states),
        positive=states.count(SENTIMENT_POS),
        neutral=states.count(SENTIMENT_NEU),
        negative=states.count(SENTIMENT_NEG),
        pending=states.count(SENTIMENT_PENDING),
        no_text=states.count(SENTIMENT_NO_TEXT),
        error=states.count(SENTIMENT_ERROR),
    )


def _target(m: Mention) -> RefreshTarget:
    return RefreshTarget(
        mention_id=m.id,
        connection_id=m.connection_id,
        media_id=m.media_id,
        comment_id=m.comment_id,
        has_permalink=m.permalink is not None,
        removed=m.removed_at is not None,
    )


def _given_content(content: MentionContent) -> dict[str, object]:
    """The columns a fresh read actually GAVE. An omitted field (`None`) is left out, so
    the stored value is kept; an explicit value — `like_count=0` included — is written."""
    values = {
        "caption": content.caption,
        "text": content.text,
        "author_username": content.author_username,
        "media_type": content.media_type,
        "like_count": content.like_count,
        "content_posted_at": content.content_posted_at,
        "permalink": content.permalink,
    }
    return {column: value for column, value in values.items() if value is not None}


class MemoryMentionsRepository:
    """Mirrors the invariants above without a database. Lives in production code for the
    same reason `MemoryInboxRepository`/`MemorySentimentRepository` do."""

    def __init__(self) -> None:
        self._mentions: dict[UUID, Mention] = {}
        # (connection_id, media_id, comment_id-or-"") -> mention_id, mirroring the
        # COALESCE natural key Postgres enforces via `uq_mention_natural_key`.
        self._natural_keys: dict[tuple[UUID, str, str], UUID] = {}
        # (mention_id, *version key, text md5 or "") -> (label, score): one row per text,
        # mirroring 0055's unique index.
        self._sentiment: dict[tuple[UUID, str, str, str, str, str], tuple[str, float]] = {}
        # (mention_id, *version key, text md5 or "") -> failed attempts (0051 rows, per text)
        self._failures: dict[tuple[UUID, str, str, str, str, str], int] = {}
        self._next_id = 1
        self._last_stamp: datetime | None = None

    def _text_md5(self, mention_id: UUID) -> str | None:
        m = self._mentions[mention_id]
        return analysis_text_md5(m.text, m.caption)

    def _failed_attempts(self, mention_id: UUID, version: AnalysisVersion) -> int:
        key = (mention_id, *_version_key(version), self._text_md5(mention_id) or "")
        return self._failures.get(key, 0)

    def _stamp(self) -> datetime:
        """A strictly increasing clock for `received_at` and snapshots. Postgres stamps
        each insert with its own transaction's `now()`; a coarse OS clock (Windows) can
        hand two consecutive calls the same instant, which would put a mention received
        AFTER a snapshot inside it."""
        stamp = datetime.now().astimezone()
        if self._last_stamp is not None and stamp <= self._last_stamp:
            stamp = self._last_stamp + timedelta(microseconds=1)
        self._last_stamp = stamp
        return stamp

    def _new_uuid(self) -> UUID:
        # Deterministic, not random — makes assertions in tests reproducible without
        # needing to capture a generated id first. Same trick `uuid5`-based helpers
        # elsewhere in this codebase's in-memory repositories use for the same reason.
        from uuid import uuid5

        self._next_id += 1
        return uuid5(UUID(int=0), f"mention-{self._next_id}")

    def upsert_mention(self, mention: NewMention) -> tuple[UUID, bool]:
        key = (mention.connection_id, mention.media_id, mention.comment_id or "")
        existing = self._natural_keys.get(key)
        if existing is not None:
            return existing, False
        mention_id = self._new_uuid()
        row = Mention(
            id=mention_id,
            tenant_id=mention.tenant_id,
            connection_id=mention.connection_id,
            platform="instagram",
            external_account_id=mention.external_account_id,
            media_id=mention.media_id,
            comment_id=mention.comment_id,
            caption=mention.caption,
            text=mention.text,
            author_username=mention.author_username,
            media_type=mention.media_type,
            like_count=mention.like_count,
            content_posted_at=mention.content_posted_at,
            enrichment_status=mention.enrichment_status,
            permalink=mention.permalink,
            received_at=self._stamp(),
        )
        self._mentions[mention_id] = row
        self._natural_keys[key] = mention_id
        return mention_id, True

    def _label_for(self, mention_id: UUID, version: AnalysisVersion) -> str | None:
        """The result on the mention's CURRENT text only (migration 0055)."""
        key = (mention_id, *_version_key(version), self._text_md5(mention_id) or "")
        result = self._sentiment.get(key)
        return result[0] if result is not None else None

    def list_mentions(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        version: AnalysisVersion,
        limit: int = DEFAULT_MENTION_PAGE_SIZE,
    ) -> tuple[MentionRecord, ...]:
        rows = [
            m
            for m in self._mentions.values()
            if m.tenant_id == tenant_id
            and m.removed_at is None
            and (connection_id is None or m.connection_id == connection_id)
        ]
        rows.sort(key=lambda m: (m.received_at, m.id), reverse=True)
        return tuple(
            MentionRecord(
                id=m.id,
                connection_id=m.connection_id,
                platform=m.platform,
                external_account_id=m.external_account_id,
                media_id=m.media_id,
                comment_id=m.comment_id,
                caption=m.caption,
                text=m.text,
                author_username=m.author_username,
                like_count=m.like_count,
                content_posted_at=m.content_posted_at,
                received_at=m.received_at,
                enrichment_status=m.enrichment_status,
                sentiment_label=self._label_for(m.id, version),
                media_type=m.media_type,
                permalink=m.permalink,
            )
            for m in rows[:limit]
        )

    def _matching(
        self, *, tenant_id: UUID, version: AnalysisVersion, query: MentionQuery
    ) -> list[tuple[Mention, str | None, str]]:
        term = query.search_term.lower()
        matched = []
        for m in self._mentions.values():
            if m.tenant_id != tenant_id or m.removed_at is not None:
                continue
            if query.connection_id is not None and m.connection_id != query.connection_id:
                continue
            if query.origin == ORIGIN_POST and m.comment_id is not None:
                continue
            if query.origin == ORIGIN_COMMENT and m.comment_id is None:
                continue
            if term and not any(
                term in (value or "").lower() for value in (m.caption, m.text, m.author_username)
            ):
                continue
            if query.since is not None and (m.content_posted_at or m.received_at) < query.since:
                continue
            label = self._label_for(m.id, version)
            state = sentiment_state_for(
                label=label,
                text=m.text,
                caption=m.caption,
                failed_attempts=self._failed_attempts(m.id, version),
            )
            if query.sentiment_state is not None and state != query.sentiment_state:
                continue
            matched.append((m, label, state))
        return matched

    def list_mentions_page(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        page: int,
        as_of: datetime | None = None,
        page_size: int = MENTIONS_PAGE_SIZE,
    ) -> MentionPage:
        snapshot = as_of if as_of is not None else self._stamp()
        rows = [
            item
            for item in self._matching(tenant_id=tenant_id, version=version, query=query)
            if item[0].received_at <= snapshot
        ]
        counts = _counts_of([state for _m, _label, state in rows])
        # Same total order as the SQL: (publication date or reception date, id), desc.
        rows.sort(
            key=lambda item: (item[0].content_posted_at or item[0].received_at, item[0].id),
            reverse=True,
        )
        current = _clamp_page(page, counts.total, page_size)
        start = (current - 1) * page_size
        return MentionPage(
            rows=tuple(
                _record(m, sentiment_label=label, sentiment_state=state)
                for m, label, state in rows[start : start + page_size]
            ),
            counts=counts,
            page=current,
            page_size=page_size,
            as_of=snapshot,
        )

    def summarize(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        as_of: datetime,
    ) -> MentionCounts:
        return _counts_of(
            [
                state
                for m, _label, state in self._matching(
                    tenant_id=tenant_id, version=version, query=query
                )
                if m.received_at <= as_of
            ]
        )

    def count_received_after(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        after: datetime,
        cap: int = NEW_MENTIONS_CAP,
    ) -> int:
        newer = sum(
            1
            for m, _label, _state in self._matching(
                tenant_id=tenant_id, version=version, query=query
            )
            if m.received_at > after
        )
        return min(newer, cap)

    def list_pending_for_analysis(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        mention_id: UUID | None = None,
        max_attempts: int = MAX_SENTIMENT_ATTEMPTS,
        limit: int | None = None,
    ) -> tuple[PendingMentionSentiment, ...]:
        pending = []
        ordered = sorted(self._mentions.items(), key=lambda item: (item[1].received_at, item[0]))
        for candidate_id, m in ordered:
            if limit is not None and len(pending) >= limit:
                break
            if m.tenant_id != tenant_id or m.removed_at is not None:
                continue
            if mention_id is not None and candidate_id != mention_id:
                continue
            if self._failed_attempts(candidate_id, version) >= max_attempts:
                continue
            # Same choice as the fingerprint and `sentiment_state_for` (comment text when
            # it exists, else caption) — never `or`, which would read the caption of a row
            # whose text is "".
            text = m.text if m.text is not None else m.caption
            # Only `is None` excludes here, deliberately NOT `.strip()` — a whitespace-
            # only mention must still be CHECKED and counted as skipped by the SERVICE
            # (`MentionSentimentService.analyze_pending_mentions`), same division of
            # responsibility `sentiment.repository`'s own `list_pending_for_analysis`
            # already establishes for comments (QUA-21 AC5, restriction 1).
            if text is None:
                continue
            if limit is not None and not text.strip():
                continue  # mirrors the SQL: a bounded pass takes analyzable text only
            if self._label_for(candidate_id, version) is not None:
                continue
            pending.append(
                PendingMentionSentiment(
                    mention_id=candidate_id, text=text, text_md5=self._text_md5(candidate_id)
                )
            )
        return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
        text_md5: str | None = None,
    ) -> bool:
        m = self._mentions.get(mention_id)
        if m is None or m.tenant_id != tenant_id:
            return False
        current = self._text_md5(mention_id)
        if text_md5 is not None and text_md5 != current:
            return False  # the text changed since it was read: a stale result never lands
        key = (mention_id, *_version_key(version), current or "")
        if key in self._sentiment:
            return False
        self._sentiment[key] = (label, score)
        return True

    def record_sentiment_failure(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        error_class: str,
        text_md5: str | None = None,
    ) -> None:
        md5 = text_md5 if text_md5 is not None else self._text_md5(mention_id)
        key = (mention_id, *_version_key(version), md5 or "")
        self._failures[key] = self._failures.get(key, 0) + 1

    def list_refresh_targets(
        self, *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
    ) -> tuple[RefreshTarget, ...]:
        return tuple(
            _target(m)
            for mention_id in mention_ids
            if (m := self._mentions.get(mention_id)) is not None
            and m.tenant_id == tenant_id
            and m.removed_at is None
        )

    def plan_scope_refresh(
        self,
        *,
        tenant_id: UUID,
        query: MentionQuery,
        fresh_seconds: int,
        limit: int,
        recheck_removed_seconds: int = REMOVED_RECHECK_SECONDS,
        recheck_removed_max_age_seconds: int = REMOVED_RECHECK_MAX_AGE_SECONDS,
    ) -> RefreshPlan:
        now = datetime.now().astimezone()
        window_start = now - timedelta(seconds=fresh_seconds)
        in_query = [
            m
            for m in self._mentions.values()
            if m.tenant_id == tenant_id
            and (query.connection_id is None or m.connection_id == query.connection_id)
            and (query.since is None or (m.content_posted_at or m.received_at) >= query.since)
        ]
        scope = [m for m in in_query if m.removed_at is None]
        fresh = [
            m
            for m in scope
            if m.content_refreshed_at is not None and m.content_refreshed_at >= window_start
        ]
        recently_failed = [
            m
            for m in scope
            if m not in fresh
            and m.content_refresh_attempted_at is not None
            and m.content_refresh_attempted_at >= window_start
        ]
        stale = [m for m in scope if m not in fresh and m not in recently_failed]
        # Never-attempted first, then the least recently attempted; id breaks ties.
        stale.sort(
            key=lambda m: (
                m.content_refresh_attempted_at is not None,
                m.content_refresh_attempted_at or m.received_at,
                m.id,
            )
        )
        live = stale[:limit]
        recheck_before = now - timedelta(seconds=recheck_removed_seconds)
        removed_since = now - timedelta(seconds=recheck_removed_max_age_seconds)
        recheck = sorted(
            (
                m
                for m in in_query
                if m.removed_at is not None
                and m.removed_at >= removed_since
                and (m.content_refresh_attempted_at or m.removed_at) <= recheck_before
            ),
            key=lambda m: (m.content_refresh_attempted_at or m.removed_at, m.id),
        )
        return RefreshPlan(
            targets=tuple(
                _target(m)
                for m in [*live, *recheck[: min(limit - len(live), REMOVED_RECHECK_PER_RUN)]]
            ),
            in_scope=len(scope),
            fresh=len(fresh),
            recently_failed=len(recently_failed),
        )

    def refresh_content(
        self, *, tenant_id: UUID, mention_id: UUID, content: MentionContent
    ) -> bool:
        m = self._mentions.get(mention_id)
        if m is None or m.tenant_id != tenant_id:
            return False
        for column, value in _given_content(content).items():
            setattr(m, column, value)
        m.enrichment_status = ENRICHMENT_OK
        m.removed_at = None
        m.content_refreshed_at = m.content_refresh_attempted_at = self._stamp()
        return True

    def mark_refresh_attempt(self, *, tenant_id: UUID, mention_id: UUID) -> None:
        m = self._mentions.get(mention_id)
        if m is not None and m.tenant_id == tenant_id:
            m.content_refresh_attempted_at = self._stamp()

    def mark_removed(
        self, *, tenant_id: UUID, mention_id: UUID, unless_read_after: datetime | None = None
    ) -> bool:
        m = self._mentions.get(mention_id)
        if m is None or m.tenant_id != tenant_id:
            return False
        if (
            unless_read_after is not None
            and m.content_refreshed_at is not None
            and m.content_refreshed_at > unless_read_after
        ):
            return False
        stamp = self._stamp()
        m.removed_at = m.removed_at or stamp
        m.content_refresh_attempted_at = stamp
        return True

    def fill_missing_comment_fields(
        self, *, tenant_id: UUID, mention_id: UUID, text: str | None, author_username: str | None
    ) -> bool:
        m = self._mentions.get(mention_id)
        if m is None or m.tenant_id != tenant_id or m.comment_id is None:
            return False
        changed = False
        if author_username is not None and m.author_username is None:
            m.author_username = author_username
            changed = True
        if text is not None and m.text is None:
            m.text = text
            m.enrichment_status = ENRICHMENT_OK
            changed = True
        return changed


class PostgresMentionsRepository:
    """All access through `tenant_session` — RLS scopes every statement, and the
    composite FKs keep a row's tenant agreeing with both its connection and (for
    sentiment) its mention."""

    def upsert_mention(self, mention: NewMention) -> tuple[UUID, bool]:
        try:
            with tenant_session(mention.tenant_id) as session:
                row = Mention(
                    tenant_id=mention.tenant_id,
                    connection_id=mention.connection_id,
                    external_account_id=mention.external_account_id,
                    media_id=mention.media_id,
                    comment_id=mention.comment_id,
                    caption=mention.caption,
                    text=mention.text,
                    author_username=mention.author_username,
                    media_type=mention.media_type,
                    like_count=mention.like_count,
                    content_posted_at=mention.content_posted_at,
                    enrichment_status=mention.enrichment_status,
                    permalink=mention.permalink,
                )
                session.add(row)
                session.flush()  # trips uq_mention_natural_key on a duplicate
                return row.id, True
        except IntegrityError:
            # Same (connection_id, media_id, comment_id) already persisted — a
            # redelivery, not an error. Look the existing row up in its own session:
            # the failed one above is unusable after rollback-on-exit.
            with tenant_session(mention.tenant_id) as session:
                existing_id = session.execute(
                    select(Mention.id).where(
                        Mention.connection_id == mention.connection_id,
                        Mention.media_id == mention.media_id,
                        Mention.comment_id.is_(mention.comment_id)
                        if mention.comment_id is None
                        else Mention.comment_id == mention.comment_id,
                    )
                ).scalar_one()
                return existing_id, False

    def list_mentions(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        version: AnalysisVersion,
        limit: int = DEFAULT_MENTION_PAGE_SIZE,
    ) -> tuple[MentionRecord, ...]:
        with tenant_session(tenant_id) as session:
            sentiment_subq = select(MentionSentimentResult.label).where(
                *_result_version_filter(version)
            )
            stmt = (
                select(Mention, sentiment_subq.limit(1).scalar_subquery().label("sentiment_label"))
                .where(Mention.tenant_id == tenant_id, Mention.removed_at.is_(None))
                .order_by(Mention.received_at.desc(), Mention.id.desc())
                .limit(limit)
            )
            if connection_id is not None:
                stmt = stmt.where(Mention.connection_id == connection_id)
            rows = session.execute(stmt).all()
            return tuple(
                MentionRecord(
                    id=m.id,
                    connection_id=m.connection_id,
                    platform=m.platform,
                    external_account_id=m.external_account_id,
                    media_id=m.media_id,
                    comment_id=m.comment_id,
                    caption=m.caption,
                    text=m.text,
                    author_username=m.author_username,
                    like_count=m.like_count,
                    content_posted_at=m.content_posted_at,
                    received_at=m.received_at,
                    enrichment_status=m.enrichment_status,
                    sentiment_label=sentiment_label,
                    media_type=m.media_type,
                    permalink=m.permalink,
                )
                for m, sentiment_label in rows
            )

    @staticmethod
    def _filtered(
        *, tenant_id: UUID, version: AnalysisVersion, query: MentionQuery
    ) -> tuple[Subquery, list[ColumnElement[bool]]]:
        """The filtered set as a subquery: one row per mention with its current-version
        label, derived sentiment state, sort key and reception time. Every dashboard read
        (page, counts, new-mention count) is a SELECT over this, so they cannot disagree
        about which rows match."""
        label = (
            select(MentionSentimentResult.label)
            .where(*_result_version_filter(version))
            .limit(1)
            .scalar_subquery()
        )
        failed = (
            select(func.count())
            .select_from(MentionSentimentFailure)
            .where(
                MentionSentimentFailure.mention_id == Mention.id,
                *_failure_version_filter(version),
            )
            .scalar_subquery()
        )

        # Mirrors `sentiment_state_for`: comment text first, else caption; blank = no text.
        content = func.coalesce(Mention.text, Mention.caption)
        no_text = or_(
            content.is_(None),
            func.length(func.regexp_replace(content, r"\s", "", "g")) == 0,
        )
        state = case(
            (label.is_not(None), label),
            (no_text, literal(SENTIMENT_NO_TEXT)),
            (failed >= MAX_SENTIMENT_ATTEMPTS, literal(SENTIMENT_ERROR)),
            else_=literal(SENTIMENT_PENDING),
        )

        conditions = [Mention.tenant_id == tenant_id, Mention.removed_at.is_(None)]
        if query.connection_id is not None:
            conditions.append(Mention.connection_id == query.connection_id)
        if query.origin == ORIGIN_POST:
            conditions.append(Mention.comment_id.is_(None))
        elif query.origin == ORIGIN_COMMENT:
            conditions.append(Mention.comment_id.is_not(None))
        if query.since is not None:
            conditions.append(
                func.coalesce(Mention.content_posted_at, Mention.received_at) >= query.since
            )
        term = query.search_term
        if term:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            conditions.append(
                or_(
                    Mention.caption.ilike(pattern, escape="\\"),
                    Mention.text.ilike(pattern, escape="\\"),
                    Mention.author_username.ilike(pattern, escape="\\"),
                )
            )

        inner = (
            select(
                Mention.id.label("mention_id"),
                Mention.received_at.label("received_at"),
                func.coalesce(Mention.content_posted_at, Mention.received_at).label("sort_at"),
                label.label("sentiment_label"),
                state.label("sentiment_state"),
            )
            .where(and_(*conditions))
            .subquery()
        )
        state_filter = (
            [inner.c.sentiment_state == query.sentiment_state]
            if query.sentiment_state is not None
            else []
        )
        return inner, state_filter

    def list_mentions_page(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        page: int,
        as_of: datetime | None = None,
        page_size: int = MENTIONS_PAGE_SIZE,
    ) -> MentionPage:
        inner, state_filter = self._filtered(tenant_id=tenant_id, version=version, query=query)
        with tenant_session(tenant_id) as session:
            # The snapshot comes from the database clock — the same clock that stamps
            # `received_at` — never from this process's.
            snapshot = as_of if as_of is not None else session.scalar(select(func.now()))
            in_snapshot = [inner.c.received_at <= snapshot, *state_filter]

            counts = _sql_counts(session, inner, in_snapshot)

            current = _clamp_page(page, counts.total, page_size)
            rows = session.execute(
                select(Mention, inner.c.sentiment_label, inner.c.sentiment_state)
                .join(inner, inner.c.mention_id == Mention.id)
                .where(*in_snapshot)
                .order_by(inner.c.sort_at.desc(), inner.c.mention_id.desc())
                .limit(page_size)
                .offset((current - 1) * page_size)
            ).all()
            return MentionPage(
                rows=tuple(
                    _record(m, sentiment_label=label, sentiment_state=state_value)
                    for m, label, state_value in rows
                ),
                counts=counts,
                page=current,
                page_size=page_size,
                as_of=snapshot,
            )

    def summarize(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        as_of: datetime,
    ) -> MentionCounts:
        inner, state_filter = self._filtered(tenant_id=tenant_id, version=version, query=query)
        with tenant_session(tenant_id) as session:
            return _sql_counts(session, inner, [inner.c.received_at <= as_of, *state_filter])

    def count_received_after(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        query: MentionQuery,
        after: datetime,
        cap: int = NEW_MENTIONS_CAP,
    ) -> int:
        inner, state_filter = self._filtered(tenant_id=tenant_id, version=version, query=query)
        with tenant_session(tenant_id) as session:
            newest = (
                select(inner.c.mention_id)
                .where(inner.c.received_at > after, *state_filter)
                .limit(cap)
                .subquery()
            )
            return session.scalar(select(func.count()).select_from(newest)) or 0

    def list_pending_for_analysis(
        self,
        *,
        tenant_id: UUID,
        version: AnalysisVersion,
        mention_id: UUID | None = None,
        max_attempts: int = MAX_SENTIMENT_ATTEMPTS,
        limit: int | None = None,
    ) -> tuple[PendingMentionSentiment, ...]:
        failed = (
            select(func.count())
            .select_from(MentionSentimentFailure)
            .where(
                MentionSentimentFailure.mention_id == Mention.id,
                *_failure_version_filter(version),
            )
            .scalar_subquery()
        )
        with tenant_session(tenant_id) as session:
            already_analyzed = (
                select(MentionSentimentResult.mention_id)
                .where(*_result_version_filter(version))
                .exists()
            )
            stmt = select(
                Mention.id, Mention.text, Mention.caption, Mention.analysis_text_md5
            ).where(
                Mention.tenant_id == tenant_id,
                Mention.removed_at.is_(None),
                ~already_analyzed,
                failed < max_attempts,
            )
            if mention_id is not None:
                stmt = stmt.where(Mention.id == mention_id)
            if limit is not None:
                # A bounded pass (the sweep) only takes mentions with analyzable text: a
                # NULL or blank text is never sent to the model and never recorded, so it
                # would sit at the head of every oldest-first batch forever.
                analyzable = func.coalesce(Mention.text, Mention.caption)
                stmt = (
                    stmt.where(
                        func.length(func.regexp_replace(analyzable, _BLANK_CHARS, "", "g")) > 0
                    )
                    .order_by(Mention.received_at.asc(), Mention.id.asc())
                    .limit(limit)
                )
            rows = session.execute(stmt).all()
            pending = []
            for row in rows:
                text = row.text if row.text is not None else row.caption
                # Only `is None` excludes — see `MemoryMentionsRepository`'s identical
                # comment for why a whitespace-only mention must still reach the service.
                if text is not None:
                    pending.append(
                        PendingMentionSentiment(
                            mention_id=row.id, text=text, text_md5=row.analysis_text_md5
                        )
                    )
            return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
        text_md5: str | None = None,
    ) -> bool:
        # INSERT ... SELECT from the mention itself: the row is stamped with the mention's
        # CURRENT fingerprint, and with `text_md5` given nothing is inserted at all when
        # the text changed after it was read — one statement, no read-then-write race.
        source = select(
            literal(tenant_id),
            Mention.id,
            literal(version.detector_version),
            literal(version.pipeline_version),
            literal(version.model_id),
            literal(version.model_revision, type_=MentionSentimentResult.model_revision.type),
            literal(label),
            literal(score),
            Mention.analysis_text_md5,
        ).where(Mention.id == mention_id, Mention.tenant_id == tenant_id)
        if text_md5 is not None:
            source = source.where(Mention.analysis_text_md5 == text_md5)
        try:
            with tenant_session(tenant_id) as session:
                inserted = session.execute(
                    insert(MentionSentimentResult)
                    .from_select(
                        [
                            "tenant_id",
                            "mention_id",
                            "detector_version",
                            "pipeline_version",
                            "model_id",
                            "model_revision",
                            "label",
                            "score",
                            "text_md5",
                        ],
                        source,
                    )
                    .returning(MentionSentimentResult.id)
                ).first()
                # RETURNING, not rowcount: an ORM-enabled INSERT reports rowcount -1.
                return inserted is not None
        except IntegrityError:  # uq_mention_sentiment_analysis: this text already has one
            return False

    def record_sentiment_failure(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        error_class: str,
        text_md5: str | None = None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            md5 = (
                text_md5
                if text_md5 is not None
                else session.scalar(
                    select(Mention.analysis_text_md5).where(Mention.id == mention_id)
                )
            )
            session.add(
                MentionSentimentFailure(
                    tenant_id=tenant_id,
                    mention_id=mention_id,
                    detector_version=version.detector_version,
                    pipeline_version=version.pipeline_version,
                    model_id=version.model_id,
                    model_revision=version.model_revision,
                    error_class=_error_class(error_class),
                    text_md5=md5,
                )
            )

    def list_refresh_targets(
        self, *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
    ) -> tuple[RefreshTarget, ...]:
        if not mention_ids:
            return ()
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(Mention).where(
                    Mention.tenant_id == tenant_id,
                    Mention.id.in_(mention_ids),
                    Mention.removed_at.is_(None),
                )
            ).all()
            return tuple(_target(m) for m in rows)

    def plan_scope_refresh(
        self,
        *,
        tenant_id: UUID,
        query: MentionQuery,
        fresh_seconds: int,
        limit: int,
        recheck_removed_seconds: int = REMOVED_RECHECK_SECONDS,
        recheck_removed_max_age_seconds: int = REMOVED_RECHECK_MAX_AGE_SECONDS,
    ) -> RefreshPlan:
        conditions = [Mention.tenant_id == tenant_id]
        if query.connection_id is not None:
            conditions.append(Mention.connection_id == query.connection_id)
        if query.since is not None:
            conditions.append(
                func.coalesce(Mention.content_posted_at, Mention.received_at) >= query.since
            )
        # The database clock, the same one that stamps the refresh timestamps.
        window_start = func.now() - timedelta(seconds=fresh_seconds)
        is_fresh = func.coalesce(Mention.content_refreshed_at >= window_start, False)
        attempted_recently = func.coalesce(
            Mention.content_refresh_attempted_at >= window_start, False
        )
        recently_failed = and_(~is_fresh, attempted_recently)
        live = [*conditions, Mention.removed_at.is_(None)]
        last_seen = func.coalesce(Mention.content_refresh_attempted_at, Mention.removed_at)
        with tenant_session(tenant_id) as session:
            in_scope, fresh, failed = session.execute(
                select(
                    func.count(),
                    func.count().filter(is_fresh),
                    func.count().filter(recently_failed),
                ).where(*live)
            ).one()
            targets = list(
                session.scalars(
                    select(Mention)
                    .where(*live, ~is_fresh, ~attempted_recently)
                    .order_by(
                        Mention.content_refresh_attempted_at.asc().nulls_first(),
                        Mention.received_at.asc(),
                        Mention.id.asc(),
                    )
                    .limit(limit)
                ).all()
            )
            room = min(limit - len(targets), REMOVED_RECHECK_PER_RUN)
            if room > 0:
                targets += session.scalars(
                    select(Mention)
                    .where(
                        *conditions,
                        Mention.removed_at.is_not(None),
                        # Database clock on both sides: it is the one that stamped them.
                        Mention.removed_at
                        >= func.now() - timedelta(seconds=recheck_removed_max_age_seconds),
                        last_seen <= func.now() - timedelta(seconds=recheck_removed_seconds),
                    )
                    .order_by(last_seen.asc(), Mention.id.asc())
                    .limit(room)
                ).all()
            return RefreshPlan(
                targets=tuple(_target(m) for m in targets),
                in_scope=in_scope,
                fresh=fresh,
                recently_failed=failed,
            )

    def refresh_content(
        self, *, tenant_id: UUID, mention_id: UUID, content: MentionContent
    ) -> bool:
        with tenant_session(tenant_id) as session:
            updated = session.execute(
                update(Mention)
                .where(Mention.id == mention_id, Mention.tenant_id == tenant_id)
                .values(
                    **_given_content(content),
                    enrichment_status=ENRICHMENT_OK,
                    removed_at=None,
                    content_refreshed_at=func.now(),
                    content_refresh_attempted_at=func.now(),
                )
            ).rowcount
            return updated == 1

    def mark_refresh_attempt(self, *, tenant_id: UUID, mention_id: UUID) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                update(Mention)
                .where(Mention.id == mention_id, Mention.tenant_id == tenant_id)
                .values(content_refresh_attempted_at=func.now())
            )

    def mark_removed(
        self, *, tenant_id: UUID, mention_id: UUID, unless_read_after: datetime | None = None
    ) -> bool:
        guard = (
            [~func.coalesce(Mention.content_refreshed_at > unless_read_after, False)]
            if unless_read_after is not None
            else []
        )
        with tenant_session(tenant_id) as session:
            updated = session.execute(
                update(Mention)
                .where(Mention.id == mention_id, Mention.tenant_id == tenant_id, *guard)
                .values(
                    removed_at=func.coalesce(Mention.removed_at, func.now()),
                    content_refresh_attempted_at=func.now(),
                )
            ).rowcount
            return updated == 1

    def fill_missing_comment_fields(
        self, *, tenant_id: UUID, mention_id: UUID, text: str | None, author_username: str | None
    ) -> bool:
        changed = 0
        scope = (
            Mention.id == mention_id,
            Mention.tenant_id == tenant_id,
            Mention.comment_id.is_not(None),
        )
        with tenant_session(tenant_id) as session:
            if author_username is not None:
                changed += session.execute(
                    update(Mention)
                    .where(*scope, Mention.author_username.is_(None))
                    .values(author_username=author_username)
                ).rowcount
            if text is not None:
                changed += session.execute(
                    update(Mention)
                    .where(*scope, Mention.text.is_(None))
                    .values(text=text, enrichment_status=ENRICHMENT_OK)
                ).rowcount
        return changed > 0
