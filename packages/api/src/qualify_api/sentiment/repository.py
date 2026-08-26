"""Persistence for QUA-21: which comments still need analysis under the current model
version, and recording a result. Same two-implementation discipline `inbox/repository.py`
establishes — `MemorySentimentRepository` is real production code (used by the offline
suite and any in-process dev path), not a test double with a second, drifting copy.

**Idempotency + versioning, in one sentence:** a `(message_id, detector_version,
pipeline_version, model_id, model_revision)` tuple is analyzed at most once — recording
the same tuple twice is a silent no-op (`record_sentiment_result` returns `False`);
recording a DIFFERENT tuple for the same message is a NEW row, and the old one is never
touched. See migration 0012 for the `COALESCE(model_revision, '')` reasoning that makes
this hold even when `model_revision` is `NULL`.

**QUA-93 replaces QUA-92's `list_comments_with_sentiment`** (one unbounded query per
connection — correct at today's volume, but a 1,000-Reel × 100-comment connection would
mean 100,000 rows in one `SELECT`, one Reflex state list, one `rx.foreach`) **with three
queries that never touch more than a page or a single Reel:**

- `list_reel_summaries` — a page of Reels (cursor keyset on `threads.last_message_at,
  id`) plus a sentiment-count aggregation bounded to THAT page's Reels only.
- `global_sentiment_summary` — the one deliberate exception: a pure `COUNT`-style
  aggregate over the whole connection, for the 5-number summary widget. It touches every
  comment (there is no way to count without touching), but never materializes one — see
  its docstring for the measured cost.
- `list_comments_for_thread` — one Reel's comments, cursor-paginated, sentiment-filtered,
  text-searched. Replaces the flat list's role, now bounded to a single `thread_id`.

**Why these three are raw SQL (`text()`), not `select()`/ORM, unlike every other query in
this module.** QUA-93's pre-implementation validation (2026-08-25, seeded 1,000 Reels ×
100 comments in real Postgres) found that the "obvious" `LEFT JOIN
comment_sentiment_results ... AND model_revision IS NOT DISTINCT FROM :mrev` — exactly
the shape `list_comments_with_sentiment` above already used — makes Postgres materialize
ALL of a connection's sentiment rows and nested-loop them against a 20-Reel page: 28.5
SECONDS at 50,000 sentiment rows, `Rows Removed by Join Filter: 99,999,000`. The fix,
confirmed by `EXPLAIN (ANALYZE, BUFFERS)`, is `LEFT JOIN LATERAL (...) ON true` for the
page/thread-bounded queries (forces one indexed lookup via `ix_comment_sentiment_message`
per row, independent of total table size — 23ms, ~1,200x faster) and a plain `JOIN` with
`COALESCE(model_revision, '') = COALESCE(:mrev, '')` (not `IS NOT DISTINCT FROM`, which is
what pushed the planner toward the bad plan in the first place) for the one query that
legitimately scans everything. SQLAlchemy Core's `Select.lateral()` was not used here
because getting a `LATERAL` translation subtly wrong is exactly the kind of mistake that
silently regresses back to the 28.5s plan — these three strings were validated character
for character against a real `EXPLAIN` output, and any edit to them must be re-validated
the same way, not "cleaned up" into query-builder calls on faith.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid5

from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment.models import CommentSentimentResult

_COMMENT_CHANNEL = "comment"
_INBOUND = "inbound"

# QUA-93: the sentinel a cursor's sort key carries when the row it was cut from had
# `posted_at IS NULL` — bound as a PARAMETER everywhere (the query's `COALESCE` default
# and the cursor comparison), never a SQL literal, so both sides always agree on the
# exact same point. `messages.posted_at` is nullable by contract (migration 0004); a
# comment can genuinely have no timestamp.
NULL_POSTED_AT_SENTINEL: datetime = datetime(1, 1, 1, tzinfo=UTC)

# QUA-93: valid values for `list_comments_for_thread`'s `sentiment_filter`. "PENDING" is
# the filter's name for "Sin analizar" — a message with no current-version
# `comment_sentiment_results` row, never confused with a real `NEU` label.
SENTIMENT_FILTER_PENDING = "PENDING"
_VALID_SENTIMENT_FILTERS = frozenset({"POS", "NEG", "NEU", SENTIMENT_FILTER_PENDING})

# QUA-93 default/max page sizes — named, not a magic number scattered across callers.
DEFAULT_REEL_PAGE_SIZE = 20
DEFAULT_COMMENT_PAGE_SIZE = 20


def _escape_ilike(raw: str) -> str:
    """Escapes `\\`, `%`, `_` so a search term is matched literally, never interpreted
    as an ILIKE wildcard the operator (a person searching for "50%_off" must not get a
    pattern match)."""
    return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Accent-insensitive search (bug reported after QUA-93 shipped): a comment search must
# match "llego" against "llegó" — mobile keyboards routinely drop accents, and a person
# typing a search box does not reliably reproduce one either way. Applied via the SAME
# two constants on BOTH sides of the comparison (the Postgres `translate()` call below
# and `_normalize_for_search` here) via bound parameters, never hand-duplicated SQL
# literals, so the two can never drift out of sync. Case-folding is `lower()`/`.lower()`
# on each side for the same reason — this replaces the bare `ILIKE`'s case-insensitivity,
# now redundant once both sides are already lower-cased.
_ACCENT_FROM = "áéíóúüàèìòùâêîôûëïñç"
_ACCENT_TO = "aeiouuaeiouaeioueinc"
_ACCENT_TABLE = str.maketrans(_ACCENT_FROM, _ACCENT_TO)


def _normalize_for_search(raw: str) -> str:
    """Lower-cases and strips accents, so a search term and the text it is matched
    against can be compared accent- and case-insensitively. Used by
    `MemorySentimentRepository` directly (Python `str.translate`) and mirrored in SQL
    by `PostgresSentimentRepository` via `translate(lower(m.text), :accent_from,
    :accent_to)` — same `_ACCENT_FROM`/`_ACCENT_TO` constants, bound as parameters."""
    return raw.lower().translate(_ACCENT_TABLE)


@dataclass(frozen=True)
class PendingComment:
    """One `messages` row eligible for analysis under the current model version.
    `text` is guaranteed non-`None` here — callers never need to check again."""

    message_id: UUID
    source_id: str
    text: str


@dataclass(frozen=True)
class AnalysisVersion:
    """The four-part key `list_pending_for_analysis`/`record_sentiment_result` key
    against. Grouped so callers cannot pass the pieces in the wrong order — the same
    reasoning `connections.composition`'s keyword-only signatures document."""

    detector_version: str
    pipeline_version: str
    model_id: str
    model_revision: str | None


@dataclass(frozen=True)
class AnalyzedComment:
    """One `messages` row (channel=comment, inbound) for display, plus its CURRENT-version
    sentiment if any. `label`/`score` are `None` together — never one without the other —
    when no `comment_sentiment_results` row exists yet for the version this was read
    under; that is "Sin analizar", structurally distinct from any real label the CHECK
    constraint on `comment_sentiment_results.label` (`POS`/`NEG`/`NEU`) allows.

    `external_thread_id` is the Reel's `external_media_id` (comment-channel threads use
    the Reel id as their natural key) — carried through so the UI can show SOME reference
    to the Reel without a live Meta call (opción A, QUA-92 — QUA-93 keeps it)."""

    message_id: UUID
    source_id: str
    text: str | None
    author_username: str | None
    posted_at: datetime | None
    external_thread_id: str
    label: str | None
    score: float | None


@dataclass(frozen=True)
class ReelSummary:
    """One Reel's comment-sentiment roll-up (QUA-93) — what a summary card in `/inbox`
    shows. `total` always equals `positive + neutral + negative + not_analyzed`.
    `last_message_at` is never `None` in practice: a `Thread` row is only created inside
    `InboxRepository.upsert_comment`, which always sets it (`posted_at or now`)."""

    thread_id: UUID
    external_thread_id: str
    last_message_at: datetime
    total: int
    positive: int
    neutral: int
    negative: int
    not_analyzed: int


@dataclass(frozen=True)
class GlobalSentimentSummary:
    """The 5-number widget at the top of `/inbox` — one connection's sentiment roll-up
    across every Reel, not just the visible page."""

    positive: int
    neutral: int
    negative: int
    not_analyzed: int
    total: int


@dataclass(frozen=True)
class ReelListCursor:
    """Keyset cursor for `list_reel_summaries` — the last row's `(last_message_at, id)`
    from the previous page. Omit (`cursor=None`) for the first page."""

    last_message_at: datetime
    thread_id: UUID


@dataclass(frozen=True)
class CommentListCursor:
    """Keyset cursor for `list_comments_for_thread`. `sort_key` is always a real
    `datetime` — pass `NULL_POSTED_AT_SENTINEL` when the previous page's last row had
    `posted_at IS NULL`, mirroring the query's own `COALESCE` default; never pass a raw
    `None` here. A cursor is valid only under the SAME `sentiment_filter`/`search` that
    produced it — changing either resets pagination to the first page."""

    sort_key: datetime
    message_id: UUID


class SentimentRepository(Protocol):
    def list_pending_for_analysis(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]: ...

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        message_id: UUID,
        source_id: str,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        """Returns `True` if a new row was inserted, `False` if this exact
        (message, version) tuple was already recorded — never raises on a duplicate."""
        ...

    def list_reel_summaries(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        version: AnalysisVersion,
        cursor: ReelListCursor | None,
        limit: int = DEFAULT_REEL_PAGE_SIZE,
    ) -> tuple[ReelSummary, ...]:
        """A page of Reels with comments, newest-active first, each with its
        CURRENT-version sentiment counts. Bounded by `limit` — never returns, and never
        internally computes over, more than this page's Reels' comments (QUA-93)."""
        ...

    def global_sentiment_summary(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> GlobalSentimentSummary:
        """The one query in this module that deliberately touches every comment in the
        connection — a pure aggregate for the summary widget, never a list."""
        ...

    def list_comments_for_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        version: AnalysisVersion,
        sentiment_filter: str | None,
        search: str | None,
        cursor: CommentListCursor | None,
        limit: int = DEFAULT_COMMENT_PAGE_SIZE,
    ) -> tuple[AnalyzedComment, ...]:
        """One Reel's comments, newest first, optionally filtered by sentiment state
        (`"POS"`/`"NEG"`/`"NEU"`/`SENTIMENT_FILTER_PENDING`/`None` for all) and/or a
        case-insensitive text search. Bounded to `thread_id` — never touches another
        Reel's comments."""
        ...


class MemorySentimentRepository:
    """Mirrors the invariants above without a database. Lives in production code for the
    same reason `MemoryInboxRepository` does."""

    def __init__(self) -> None:
        # (message_id, detector_version, pipeline_version, model_id, model_revision or "")
        self._recorded: set[tuple[UUID, str, str, str, str]] = set()
        # Same key as `_recorded` -> (label, score). A second dict, not a merge into
        # `_recorded`'s tuples, so `_recorded`'s role as a pure idempotency set stays
        # unchanged for every caller that only needs membership (list_pending_for_analysis).
        self._results: dict[tuple[UUID, str, str, str, str], tuple[str, float]] = {}
        # message_id -> (connection_id, source_id, text, author_username, posted_at,
        # external_thread_id, thread_id)
        self._messages: dict[
            UUID, tuple[UUID, str, str | None, str | None, datetime | None, str, UUID]
        ] = {}

    def seed_message(
        self,
        *,
        message_id: UUID,
        connection_id: UUID,
        source_id: str,
        text: str | None,
        author_username: str | None = None,
        posted_at: datetime | None = None,
        external_thread_id: str = "",
        thread_id: UUID | None = None,
    ) -> None:
        """Test-only helper — the Postgres implementation has no analogue because
        `messages` rows there come from the real inbox sync, not from this module.
        `thread_id` defaults to a UUID DERIVED from `(connection_id,
        external_thread_id)` (stable, deterministic — same inputs always produce the
        same id) so pre-QUA-93 call sites that never passed one still group correctly
        by Reel without having to be updated."""
        resolved_thread_id = thread_id or uuid5(connection_id, external_thread_id or "no-thread")
        self._messages[message_id] = (
            connection_id,
            source_id,
            text,
            author_username,
            posted_at,
            external_thread_id,
            resolved_thread_id,
        )

    def list_pending_for_analysis(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]:
        key_suffix = (version.detector_version, version.pipeline_version, version.model_id)
        revision_key = version.model_revision or ""
        pending = []
        for message_id, (conn_id, source_id, comment_text, *_rest) in self._messages.items():
            if conn_id != connection_id or comment_text is None:
                continue
            if (message_id, *key_suffix, revision_key) in self._recorded:
                continue
            pending.append(
                PendingComment(message_id=message_id, source_id=source_id, text=comment_text)
            )
        return tuple(pending)

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        message_id: UUID,
        source_id: str,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        key = (
            message_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
        if key in self._recorded:
            return False
        self._recorded.add(key)
        self._results[key] = (label, score)
        return True

    def _label_for(self, message_id: UUID, version: AnalysisVersion) -> str | None:
        key = (
            message_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
        result = self._results.get(key)
        return result[0] if result is not None else None

    def _score_for(self, message_id: UUID, version: AnalysisVersion) -> float | None:
        key = (
            message_id,
            version.detector_version,
            version.pipeline_version,
            version.model_id,
            version.model_revision or "",
        )
        result = self._results.get(key)
        return result[1] if result is not None else None

    def list_reel_summaries(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        version: AnalysisVersion,
        cursor: ReelListCursor | None,
        limit: int = DEFAULT_REEL_PAGE_SIZE,
    ) -> tuple[ReelSummary, ...]:
        by_thread: dict[UUID, list[UUID]] = {}
        thread_external_id: dict[UUID, str] = {}
        for message_id, (
            conn_id,
            _source_id,
            _text,
            _author_username,
            _posted_at,
            external_thread_id,
            thread_id,
        ) in self._messages.items():
            if conn_id != connection_id:
                continue
            by_thread.setdefault(thread_id, []).append(message_id)
            thread_external_id[thread_id] = external_thread_id

        summaries = []
        for thread_id, message_ids in by_thread.items():
            last_message_at = NULL_POSTED_AT_SENTINEL
            positive = neutral = negative = not_analyzed = 0
            for message_id in message_ids:
                posted_at = self._messages[message_id][4]
                if posted_at is not None and posted_at > last_message_at:
                    last_message_at = posted_at
                label = self._label_for(message_id, version)
                if label == "POS":
                    positive += 1
                elif label == "NEU":
                    neutral += 1
                elif label == "NEG":
                    negative += 1
                else:
                    not_analyzed += 1
            summaries.append(
                ReelSummary(
                    thread_id=thread_id,
                    external_thread_id=thread_external_id[thread_id],
                    last_message_at=last_message_at,
                    total=len(message_ids),
                    positive=positive,
                    neutral=neutral,
                    negative=negative,
                    not_analyzed=not_analyzed,
                )
            )
        summaries.sort(key=lambda s: (s.last_message_at, s.thread_id), reverse=True)
        if cursor is not None:
            summaries = [
                s
                for s in summaries
                if (s.last_message_at, s.thread_id) < (cursor.last_message_at, cursor.thread_id)
            ]
        return tuple(summaries[:limit])

    def global_sentiment_summary(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> GlobalSentimentSummary:
        positive = neutral = negative = not_analyzed = 0
        for message_id, (conn_id, *_rest) in self._messages.items():
            if conn_id != connection_id:
                continue
            label = self._label_for(message_id, version)
            if label == "POS":
                positive += 1
            elif label == "NEU":
                neutral += 1
            elif label == "NEG":
                negative += 1
            else:
                not_analyzed += 1
        return GlobalSentimentSummary(
            positive=positive,
            neutral=neutral,
            negative=negative,
            not_analyzed=not_analyzed,
            total=positive + neutral + negative + not_analyzed,
        )

    def list_comments_for_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        version: AnalysisVersion,
        sentiment_filter: str | None,
        search: str | None,
        cursor: CommentListCursor | None,
        limit: int = DEFAULT_COMMENT_PAGE_SIZE,
    ) -> tuple[AnalyzedComment, ...]:
        rows = []
        for message_id, (
            conn_id,
            source_id,
            comment_text,
            author_username,
            posted_at,
            external_thread_id,
            msg_thread_id,
        ) in self._messages.items():
            if conn_id != connection_id or msg_thread_id != thread_id:
                continue
            label = self._label_for(message_id, version)
            score = self._score_for(message_id, version)
            if sentiment_filter == SENTIMENT_FILTER_PENDING and label is not None:
                continue
            if sentiment_filter in ("POS", "NEG", "NEU") and label != sentiment_filter:
                continue
            if search and (
                comment_text is None
                or _normalize_for_search(search) not in _normalize_for_search(comment_text)
            ):
                continue
            sort_key = posted_at if posted_at is not None else NULL_POSTED_AT_SENTINEL
            rows.append(
                (
                    sort_key,
                    AnalyzedComment(
                        message_id=message_id,
                        source_id=source_id,
                        text=comment_text,
                        author_username=author_username,
                        posted_at=posted_at,
                        external_thread_id=external_thread_id,
                        label=label,
                        score=score,
                    ),
                )
            )
        rows.sort(key=lambda pair: (pair[0], pair[1].message_id), reverse=True)
        if cursor is not None:
            rows = [
                pair
                for pair in rows
                if (pair[0], pair[1].message_id) < (cursor.sort_key, cursor.message_id)
            ]
        return tuple(comment for _sort_key, comment in rows[:limit])


class PostgresSentimentRepository:
    """All access through `tenant_session` — RLS scopes every statement, and the
    composite FKs keep a row's tenant agreeing with both its message and its
    connection.

    `list_reel_summaries`/`global_sentiment_summary`/`list_comments_for_thread` are raw
    SQL — see the module docstring for why (a validated-then-regressed query shape),
    before touching them: re-run `EXPLAIN (ANALYZE, BUFFERS)` against a seeded
    1,000-Reel/100-comment connection, not just the offline/small-fixture tests.
    """

    def list_pending_for_analysis(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> tuple[PendingComment, ...]:
        with tenant_session(tenant_id) as session:
            already_analyzed = (
                select(CommentSentimentResult.message_id)
                .where(
                    CommentSentimentResult.message_id == Message.id,
                    CommentSentimentResult.detector_version == version.detector_version,
                    CommentSentimentResult.pipeline_version == version.pipeline_version,
                    CommentSentimentResult.model_id == version.model_id,
                )
                .exists()
            )
            # COALESCE mirrors the migration's unique index: NULL model_revision must
            # compare equal to NULL model_revision for "already analyzed" to hold.
            if version.model_revision is None:
                already_analyzed = already_analyzed.where(
                    CommentSentimentResult.model_revision.is_(None)
                )
            else:
                already_analyzed = already_analyzed.where(
                    CommentSentimentResult.model_revision == version.model_revision
                )

            rows = session.execute(
                select(Message.id, Message.external_message_id, Message.text)
                .join(Thread, Thread.id == Message.thread_id)
                .where(
                    Thread.channel == _COMMENT_CHANNEL,
                    Message.direction == _INBOUND,
                    Message.connection_id == connection_id,
                    Message.text.is_not(None),
                    ~already_analyzed,
                )
            ).all()
            return tuple(
                PendingComment(message_id=row.id, source_id=row.external_message_id, text=row.text)
                for row in rows
                if row.text is not None  # belt-and-suspenders; the query already filters this
            )

    def record_sentiment_result(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        message_id: UUID,
        source_id: str,
        version: AnalysisVersion,
        label: str,
        score: float,
    ) -> bool:
        try:
            with tenant_session(tenant_id) as session:
                session.add(
                    CommentSentimentResult(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        message_id=message_id,
                        source_id=source_id,
                        detector_version=version.detector_version,
                        pipeline_version=version.pipeline_version,
                        model_id=version.model_id,
                        model_revision=version.model_revision,
                        label=label,
                        score=score,
                    )
                )
                session.flush()  # trips uq_comment_sentiment_analysis on a duplicate
                return True
        except IntegrityError:
            # Same (message, version) tuple already recorded. Not an error — the
            # append-only design means this is the expected shape of "already done".
            return False

    def list_reel_summaries(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        version: AnalysisVersion,
        cursor: ReelListCursor | None,
        limit: int = DEFAULT_REEL_PAGE_SIZE,
    ) -> tuple[ReelSummary, ...]:
        with tenant_session(tenant_id) as session:
            thread_sql = """
                SELECT id, external_thread_id, last_message_at
                FROM threads
                WHERE connection_id = :cid AND channel = 'comment'
            """
            params: dict[str, object] = {"cid": str(connection_id), "limit": limit}
            if cursor is not None:
                thread_sql += " AND (last_message_at, id) < (:cts, :ctid)"
                params["cts"] = cursor.last_message_at
                params["ctid"] = str(cursor.thread_id)
            thread_sql += " ORDER BY last_message_at DESC, id DESC LIMIT :limit"

            thread_rows = session.execute(text(thread_sql), params).all()
            if not thread_rows:
                return ()
            thread_ids = [str(row.id) for row in thread_rows]

            # LATERAL: forces one indexed lookup per message via
            # ix_comment_sentiment_message, independent of total table size — see the
            # module docstring for the 28.5s-vs-23ms measurement that makes this
            # non-negotiable. `csr.tenant_id = :tenant_id` below is REDUNDANT with RLS
            # (RLS already scopes every read of this table) — it exists purely as a
            # planner hint: `current_setting('app.tenant_id')`, RLS's own predicate, is
            # opaque at plan time, and at real scale (1,000 Reels x 100 comments) that
            # opacity was measured to make Postgres pick `ix_comment_sentiment_tenant`
            # (filtering tens of thousands of rows per outer row) over the far cheaper
            # `uq_comment_sentiment_analysis` (message_id-first, a guaranteed single-row
            # lookup) — 29s vs 23ms for the identical rows, identical RLS policy. This
            # literal alone was NOT a reliable fix (still measured 22-30s intermittently
            # afterward, with the literal already in place) — `ix_comment_sentiment_tenant`
            # itself was dropped in migration 0012 (QUA-93) so the ambiguity no longer
            # exists; the literal stays here as a harmless, still-correct filter and as
            # the same planner-hint pattern `global_sentiment_summary` also carries. See
            # this method's sibling `list_comments_for_thread` for the second instance.
            agg_sql = """
                SELECT m.thread_id,
                  count(*) AS total,
                  count(*) FILTER (WHERE csr.label = 'POS') AS positive,
                  count(*) FILTER (WHERE csr.label = 'NEU') AS neutral,
                  count(*) FILTER (WHERE csr.label = 'NEG') AS negative,
                  count(*) FILTER (WHERE csr.label IS NULL) AS not_analyzed
                FROM messages m
                LEFT JOIN LATERAL (
                  SELECT label
                  FROM comment_sentiment_results csr
                  WHERE csr.message_id = m.id
                    AND csr.tenant_id = :tenant_id
                    AND csr.detector_version = :dv AND csr.pipeline_version = :pv
                    AND csr.model_id = :mid
                    AND COALESCE(csr.model_revision, '') = COALESCE(:mrev, '')
                  LIMIT 1
                ) csr ON true
                WHERE m.thread_id = ANY(:tids) AND m.direction = 'inbound'
                GROUP BY m.thread_id
            """
            agg_rows = session.execute(
                text(agg_sql),
                {
                    "tids": thread_ids,
                    "tenant_id": str(tenant_id),
                    "dv": version.detector_version,
                    "pv": version.pipeline_version,
                    "mid": version.model_id,
                    "mrev": version.model_revision,
                },
            ).all()
            counts_by_thread = {str(row.thread_id): row for row in agg_rows}

            summaries = []
            for row in thread_rows:
                counts = counts_by_thread.get(str(row.id))
                summaries.append(
                    ReelSummary(
                        thread_id=row.id,
                        external_thread_id=row.external_thread_id,
                        last_message_at=row.last_message_at,
                        total=counts.total if counts else 0,
                        positive=counts.positive if counts else 0,
                        neutral=counts.neutral if counts else 0,
                        negative=counts.negative if counts else 0,
                        not_analyzed=counts.not_analyzed if counts else 0,
                    )
                )
            return tuple(summaries)

    def global_sentiment_summary(
        self, *, tenant_id: UUID, connection_id: UUID, version: AnalysisVersion
    ) -> GlobalSentimentSummary:
        # Plain JOIN, NOT lateral — the module docstring's measurement showed LATERAL is
        # ~7x SLOWER here (1.95s vs 268ms at 100k rows): this query deliberately scans
        # the whole connection, so a hash join over the full sets beats a per-row loop.
        #
        # `tenant_id = :tenant_id` on all three tables below is REDUNDANT with RLS, same
        # planner-hint reasoning as `list_reel_summaries`/`list_comments_for_thread` — but
        # here the opaque `current_setting('app.tenant_id')` RLS predicate was measured
        # (QUA-93) to make Postgres estimate ~1 row on `messages`/`threads`/
        # `comment_sentiment_results` alike (real: tens of thousands), which picks Nested
        # Loop joins over Hash Join and regresses to ~24 minutes at 1,000 Reels x 100
        # comments. A literal bound parameter lets the planner use real per-value
        # selectivity (pg_stats) instead of that opaque default.
        sql = """
            SELECT
              count(*) FILTER (WHERE csr.label = 'POS') AS positive,
              count(*) FILTER (WHERE csr.label = 'NEU') AS neutral,
              count(*) FILTER (WHERE csr.label = 'NEG') AS negative,
              count(*) FILTER (WHERE csr.label IS NULL) AS not_analyzed,
              count(*) AS total
            FROM messages m
            JOIN threads t ON t.id = m.thread_id AND t.tenant_id = :tenant_id
            LEFT JOIN comment_sentiment_results csr
              ON csr.message_id = m.id
              AND csr.tenant_id = :tenant_id
              AND csr.detector_version = :dv AND csr.pipeline_version = :pv
              AND csr.model_id = :mid
              AND COALESCE(csr.model_revision, '') = COALESCE(:mrev, '')
            WHERE m.tenant_id = :tenant_id
              AND t.connection_id = :cid AND t.channel = 'comment' AND m.direction = 'inbound'
        """
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(sql),
                {
                    "tenant_id": str(tenant_id),
                    "cid": str(connection_id),
                    "dv": version.detector_version,
                    "pv": version.pipeline_version,
                    "mid": version.model_id,
                    "mrev": version.model_revision,
                },
            ).one()
            return GlobalSentimentSummary(
                positive=row.positive,
                neutral=row.neutral,
                negative=row.negative,
                not_analyzed=row.not_analyzed,
                total=row.total,
            )

    def list_comments_for_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID,
        version: AnalysisVersion,
        sentiment_filter: str | None,
        search: str | None,
        cursor: CommentListCursor | None,
        limit: int = DEFAULT_COMMENT_PAGE_SIZE,
    ) -> tuple[AnalyzedComment, ...]:
        if sentiment_filter is not None and sentiment_filter not in _VALID_SENTIMENT_FILTERS:
            raise ValueError(f"invalid sentiment_filter: {sentiment_filter!r}")

        # `csr.tenant_id = :tenant_id` in the LATERAL below is REDUNDANT with RLS (RLS
        # already scopes every read of comment_sentiment_results) — a planner hint, same
        # reasoning `list_reel_summaries`'s identical LATERAL carries: RLS's own
        # `current_setting('app.tenant_id')` predicate is opaque at plan time, and that
        # opacity was measured (at 1,000 Reels x 100 comments) to make Postgres prefer
        # `ix_comment_sentiment_tenant` over the far cheaper, message_id-first
        # `uq_comment_sentiment_analysis`. That index was since dropped (migration 0012,
        # QUA-93) because the literal alone did not reliably prevent the bad plan — see
        # `list_reel_summaries`'s comment for the full before/after measurement.
        sql = """
            SELECT m.id, m.external_message_id, m.text, m.author_username, m.posted_at,
                   csr.label, csr.score
            FROM messages m
            LEFT JOIN LATERAL (
              SELECT label, score
              FROM comment_sentiment_results csr
              WHERE csr.message_id = m.id
                AND csr.tenant_id = :tenant_id
                AND csr.detector_version = :dv AND csr.pipeline_version = :pv
                AND csr.model_id = :mid
                AND COALESCE(csr.model_revision, '') = COALESCE(:mrev, '')
              LIMIT 1
            ) csr ON true
            WHERE m.thread_id = :tid AND m.connection_id = :cid AND m.direction = 'inbound'
        """
        params: dict[str, object] = {
            "tid": str(thread_id),
            "cid": str(connection_id),
            "tenant_id": str(tenant_id),
            "dv": version.detector_version,
            "pv": version.pipeline_version,
            "mid": version.model_id,
            "mrev": version.model_revision,
            "null_sentinel": NULL_POSTED_AT_SENTINEL,
            "limit": limit,
        }
        if sentiment_filter == SENTIMENT_FILTER_PENDING:
            sql += " AND csr.label IS NULL"
        elif sentiment_filter is not None:
            sql += " AND csr.label = :sentiment_filter"
            params["sentiment_filter"] = sentiment_filter
        if search:
            # Accent- and case-insensitive: fold both sides (message text via SQL
            # `translate(lower(...))`, the search term via `_normalize_for_search`)
            # through the same `_ACCENT_FROM`/`_ACCENT_TO` mapping before comparing —
            # see that constant's docstring for why "llego" must match "llegó".
            sql += (
                " AND translate(lower(m.text), :accent_from, :accent_to) LIKE :search ESCAPE '\\'"
            )
            params["search"] = f"%{_escape_ilike(_normalize_for_search(search))}%"
            params["accent_from"] = _ACCENT_FROM
            params["accent_to"] = _ACCENT_TO
        if cursor is not None:
            sql += " AND (COALESCE(m.posted_at, :null_sentinel), m.id) < (:cts, :ctid)"
            params["cts"] = cursor.sort_key
            params["ctid"] = str(cursor.message_id)
        sql += """
            ORDER BY COALESCE(m.posted_at, :null_sentinel) DESC, m.id DESC
            LIMIT :limit
        """

        with tenant_session(tenant_id) as session:
            rows = session.execute(text(sql), params).all()
            return tuple(
                AnalyzedComment(
                    message_id=row.id,
                    source_id=row.external_message_id,
                    text=row.text,
                    author_username=row.author_username,
                    posted_at=row.posted_at,
                    external_thread_id="",  # caller already knows thread_id; not re-fetched here
                    label=row.label,
                    score=row.score,
                )
                for row in rows
            )
