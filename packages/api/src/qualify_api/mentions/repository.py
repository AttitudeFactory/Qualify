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

# A mention is analyzed at most this many times per analysis version (migration 0051
# records each failed attempt). After that it is `ERROR` and no longer retried, until a
# new model/pipeline version starts its attempts from zero.
MAX_SENTIMENT_ATTEMPTS = 3


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


@dataclass(frozen=True)
class MentionContent:
    """A fresh read of a mention's content — what "Actualizar" writes back. Every field is
    the network's CURRENT answer: `like_count=None` means it no longer gives one (the
    owner hid it), so the row shows that, not a stale number. Built only from a SUCCESSFUL
    read; a failed read never reaches the repository, so stored data is never erased."""

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
    ) -> tuple[PendingMentionSentiment, ...]:
        """Mentions with text and no current-version result whose failed attempts are
        below `max_attempts` — an exhausted mention is never offered again (QUA-152).
        `mention_id` narrows to that one mention (the after-ingest analysis)."""
        ...

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        """Returns `True` if a new row was inserted, `False` if this exact
        (mention, version) tuple was already recorded — never raises on a duplicate,
        same contract `sentiment.repository`'s own `record_sentiment_result` has."""
        ...

    def record_sentiment_failure(
        self, *, tenant_id: UUID, mention_id: UUID, version: AnalysisVersion, error_class: str
    ) -> None:
        """Append one failed attempt (migration 0051). `error_class` is an exception class
        name, never a message (a message could echo the analyzed text)."""
        ...

    def list_refresh_targets(
        self, *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
    ) -> tuple[RefreshTarget, ...]:
        """The ids "Actualizar" needs to re-read these mentions — tenant-scoped."""
        ...

    def refresh_content(
        self, *, tenant_id: UUID, mention_id: UUID, content: MentionContent
    ) -> bool:
        """Overwrite the content columns with a fresh read (QUA-152, migration 0053) and mark
        the row ENRICHED. A `permalink=None` keeps the stored link (a link does not expire;
        a missing one in a later read is not evidence it is gone). Returns False when the
        mention is not this tenant's."""
        ...


def _error_class(name: str) -> str:
    """Bound to the 0051 CHECK (1..200 chars) so recording a failure can never itself fail."""
    return (name or "Exception")[:200]


def _failure_version_filter(version: AnalysisVersion) -> list[ColumnElement[bool]]:
    return [
        MentionSentimentFailure.detector_version == version.detector_version,
        MentionSentimentFailure.pipeline_version == version.pipeline_version,
        MentionSentimentFailure.model_id == version.model_id,
        MentionSentimentFailure.model_revision.is_(None)
        if version.model_revision is None
        else MentionSentimentFailure.model_revision == version.model_revision,
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


class MemoryMentionsRepository:
    """Mirrors the invariants above without a database. Lives in production code for the
    same reason `MemoryInboxRepository`/`MemorySentimentRepository` do."""

    def __init__(self) -> None:
        self._mentions: dict[UUID, Mention] = {}
        # (connection_id, media_id, comment_id-or-"") -> mention_id, mirroring the
        # COALESCE natural key Postgres enforces via `uq_mention_natural_key`.
        self._natural_keys: dict[tuple[UUID, str, str], UUID] = {}
        # (mention_id, detector_version, pipeline_version, model_id, model_revision or "")
        self._sentiment: dict[tuple[UUID, str, str, str, str], tuple[str, float]] = {}
        # (mention_id, *version key) -> failed attempts (rows in 0051's table)
        self._failures: dict[tuple[UUID, str, str, str, str], int] = {}
        self._next_id = 1
        self._last_stamp: datetime | None = None

    def _failed_attempts(self, mention_id: UUID, version: AnalysisVersion) -> int:
        return self._failures.get((mention_id, *_version_key(version)), 0)

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
        key = (
            mention_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
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
            if m.tenant_id != tenant_id:
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
    ) -> tuple[PendingMentionSentiment, ...]:
        pending = []
        for candidate_id, m in self._mentions.items():
            if m.tenant_id != tenant_id:
                continue
            if mention_id is not None and candidate_id != mention_id:
                continue
            if self._failed_attempts(candidate_id, version) >= max_attempts:
                continue
            text = m.text or m.caption
            # Only `is None` excludes here, deliberately NOT `.strip()` — a whitespace-
            # only mention must still be CHECKED and counted as skipped by the SERVICE
            # (`MentionSentimentService.analyze_pending_mentions`), same division of
            # responsibility `sentiment.repository`'s own `list_pending_for_analysis`
            # already establishes for comments (QUA-21 AC5, restriction 1).
            if text is None:
                continue
            if self._label_for(candidate_id, version) is not None:
                continue
            pending.append(PendingMentionSentiment(mention_id=candidate_id, text=text))
        return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        key = (
            mention_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
        if key in self._sentiment:
            return False
        self._sentiment[key] = (label, score)
        return True

    def record_sentiment_failure(
        self, *, tenant_id: UUID, mention_id: UUID, version: AnalysisVersion, error_class: str
    ) -> None:
        key = (mention_id, *_version_key(version))
        self._failures[key] = self._failures.get(key, 0) + 1

    def list_refresh_targets(
        self, *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
    ) -> tuple[RefreshTarget, ...]:
        return tuple(
            RefreshTarget(
                mention_id=m.id,
                connection_id=m.connection_id,
                media_id=m.media_id,
                comment_id=m.comment_id,
            )
            for mention_id in mention_ids
            if (m := self._mentions.get(mention_id)) is not None and m.tenant_id == tenant_id
        )

    def refresh_content(
        self, *, tenant_id: UUID, mention_id: UUID, content: MentionContent
    ) -> bool:
        m = self._mentions.get(mention_id)
        if m is None or m.tenant_id != tenant_id:
            return False
        m.caption = content.caption
        m.text = content.text
        m.author_username = content.author_username
        m.media_type = content.media_type
        m.like_count = content.like_count
        m.content_posted_at = content.content_posted_at
        if content.permalink is not None:
            m.permalink = content.permalink
        m.enrichment_status = ENRICHMENT_OK
        return True


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
                MentionSentimentResult.mention_id == Mention.id,
                MentionSentimentResult.detector_version == version.detector_version,
                MentionSentimentResult.pipeline_version == version.pipeline_version,
                MentionSentimentResult.model_id == version.model_id,
            )
            sentiment_subq = (
                sentiment_subq.where(MentionSentimentResult.model_revision.is_(None))
                if version.model_revision is None
                else sentiment_subq.where(
                    MentionSentimentResult.model_revision == version.model_revision
                )
            )
            stmt = (
                select(Mention, sentiment_subq.limit(1).scalar_subquery().label("sentiment_label"))
                .where(Mention.tenant_id == tenant_id)
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
        label = select(MentionSentimentResult.label).where(
            MentionSentimentResult.mention_id == Mention.id,
            MentionSentimentResult.detector_version == version.detector_version,
            MentionSentimentResult.pipeline_version == version.pipeline_version,
            MentionSentimentResult.model_id == version.model_id,
        )
        label = (
            label.where(MentionSentimentResult.model_revision.is_(None))
            if version.model_revision is None
            else label.where(MentionSentimentResult.model_revision == version.model_revision)
        )
        label = label.limit(1).scalar_subquery()
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

        conditions = [Mention.tenant_id == tenant_id]
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
                .where(
                    MentionSentimentResult.mention_id == Mention.id,
                    MentionSentimentResult.detector_version == version.detector_version,
                    MentionSentimentResult.pipeline_version == version.pipeline_version,
                    MentionSentimentResult.model_id == version.model_id,
                )
                .exists()
            )
            already_analyzed = (
                already_analyzed.where(MentionSentimentResult.model_revision.is_(None))
                if version.model_revision is None
                else already_analyzed.where(
                    MentionSentimentResult.model_revision == version.model_revision
                )
            )
            stmt = select(Mention.id, Mention.text, Mention.caption).where(
                Mention.tenant_id == tenant_id,
                ~already_analyzed,
                failed < max_attempts,
            )
            if mention_id is not None:
                stmt = stmt.where(Mention.id == mention_id)
            rows = session.execute(stmt).all()
            pending = []
            for row in rows:
                text = row.text or row.caption
                # Only `is None` excludes — see `MemoryMentionsRepository`'s identical
                # comment for why a whitespace-only mention must still reach the service.
                if text is not None:
                    pending.append(PendingMentionSentiment(mention_id=row.id, text=text))
            return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        mention_id: UUID,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        try:
            with tenant_session(tenant_id) as session:
                session.add(
                    MentionSentimentResult(
                        tenant_id=tenant_id,
                        mention_id=mention_id,
                        detector_version=version.detector_version,
                        pipeline_version=version.pipeline_version,
                        model_id=version.model_id,
                        model_revision=version.model_revision,
                        label=label,
                        score=score,
                    )
                )
                session.flush()  # trips uq_mention_sentiment_analysis on a duplicate
                return True
        except IntegrityError:
            return False

    def record_sentiment_failure(
        self, *, tenant_id: UUID, mention_id: UUID, version: AnalysisVersion, error_class: str
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.add(
                MentionSentimentFailure(
                    tenant_id=tenant_id,
                    mention_id=mention_id,
                    detector_version=version.detector_version,
                    pipeline_version=version.pipeline_version,
                    model_id=version.model_id,
                    model_revision=version.model_revision,
                    error_class=_error_class(error_class),
                )
            )

    def list_refresh_targets(
        self, *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
    ) -> tuple[RefreshTarget, ...]:
        if not mention_ids:
            return ()
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(
                    Mention.id, Mention.connection_id, Mention.media_id, Mention.comment_id
                ).where(Mention.tenant_id == tenant_id, Mention.id.in_(mention_ids))
            ).all()
            return tuple(
                RefreshTarget(
                    mention_id=row.id,
                    connection_id=row.connection_id,
                    media_id=row.media_id,
                    comment_id=row.comment_id,
                )
                for row in rows
            )

    def refresh_content(
        self, *, tenant_id: UUID, mention_id: UUID, content: MentionContent
    ) -> bool:
        values: dict = {
            "caption": content.caption,
            "text": content.text,
            "author_username": content.author_username,
            "media_type": content.media_type,
            "like_count": content.like_count,
            "content_posted_at": content.content_posted_at,
            "enrichment_status": ENRICHMENT_OK,
        }
        if content.permalink is not None:
            values["permalink"] = content.permalink
        with tenant_session(tenant_id) as session:
            updated = session.execute(
                update(Mention)
                .where(Mention.id == mention_id, Mention.tenant_id == tenant_id)
                .values(**values)
            ).rowcount
            return updated == 1
