"""The seam between the inbox content screen and the real inbox backend (Fase 1 Parte
4-B, B2 UI slice).

Same split `publishing_provider.py` documents:

- **Reads this module reuses.** `instagram_connections` reuses `connections_provider.
  connections_for` exactly as it is, filtered to `platform == "instagram"`, `status ==
  "active"` and the `READ_COMMENTS` capability (C-05) being enabled — this module adds
  zero new database access for that list.
- **In-process writes/reads.** `candidate_media`/`toggle_monitoring`/`sync_now` are thin
  async projections over `qualify_api.inbox.composition`'s published seam
  (`list_candidate_media`/`set_media_monitored`/`sync_comments`, re-exported from
  `qualify_api.inbox`), same role `publishing_provider.py` has over `qualify_api.
  publishing.composition` — no HTTP hop, same posture `http/app.py`'s own module docstring
  documents for the Reflex CRM in general. `analyze_sentiment_now` (QUA-92) does the same
  over `qualify_api.sentiment.analyze_pending_comments` — the very seam `POST /api/
  sentiment/analyze` wraps, so there is still one analysis engine, not two.

**Why sync and analysis no longer go through their HTTP routes (B8, 2026-10-08).** They
used to, via an in-process ASGI client authenticated by a hardcoded dev bearer that
`QUALIFY_DEV_PRINCIPALS` mapped to ONE tenant (PuntoServis). Every other tenant was
refused before any call — in production, every tenant, and the screen showed «Esa cuenta
ya no está disponible». Both routes (`POST /api/inbox/sync`, `POST /api/sentiment/
analyze`) still exist for API callers; the CRM now calls the seams behind them with the
session's tenant, and RLS (`tenant_session`) is what scopes every read to that tenant.

`sync_now` is the transport both the manual button and the automatic poll share (QUA-89,
2026-08-19) — see `inbox_page.py`'s module docstring for the UI side. It adds no sync
logic of its own: `InboxService.sync_comments` already reads ONLY `InboxRepository.
list_monitored_media_ids` (media with `is_monitored=True`), so which Reels get synced is
entirely decided by the toggle, not by anything in this module.

`candidate_media`/`toggle_monitoring`/`sync_now` are already `async def` (the whole chain
down to `InjectingCredentialResolver.client_for` is), so none needs `asyncio.to_thread` —
same posture `publishing_provider.start_publish`/`poll_publish` already have over their
own already-async seam. `analyze_sentiment_now`'s seam is synchronous, so it does.

`reel_summaries_page`/`global_summary_vm`/`thread_comments_page` (QUA-93) are the read
side of the comments view — thin, synchronous projections over `qualify_api.sentiment`'s
three read seams (`list_reel_summaries`/`global_sentiment_summary`/
`list_comments_for_thread`), in process, no HTTP hop, same posture `candidate_media`/
`toggle_monitoring` have over `qualify_api.inbox`. None of the three is `async def`
(Postgres access via `tenant_session` is ordinary blocking I/O, same as
`instagram_connections` above), so `InboxState` is responsible for `asyncio.to_thread`,
not this module. None analyzes anything or calls Meta — pure re-reads of `messages`/
`threads`/`comment_sentiment_results`, safe to call as often as the UI needs.

Cursors cross the Reflex boundary as `ReelPageCursorVM`/`CommentPageCursorVM` (ISO-8601
strings, never a raw `datetime` — same convention every `*_at` VM field in this module
already follows), converted to/from the repository's typed `ReelListCursor`/
`CommentListCursor` right here, in `_reel_cursor_from_vm`/`_comment_cursor_from_vm`. This
module is the ONLY place that conversion happens — `InboxState` never sees the
repository's cursor types, only the VM ones.

`reel_summaries_page`'s caption/permalink (QUA-149) come from the PERSISTED
`monitored_media` metadata first, so a Reel keeps them after its 14-day window; the
`CandidateMediaVM` list the caller already loaded (opción A, founder-approved 2026-08-25 —
no new query, no new Meta call) is the fallback, and the only source of `thumbnail_url`
(Meta's CDN URLs expire, so they are not stored; outside the list the page shows its
generic icon).

`ReelSummaryVM.monitoring_state` (QUA-149) is what the badge shows. It is computed here
by `_monitoring_state` from the SHARED rule (`qualify_api.inbox.monitoring.
effective_state`) over the raw flag AND the persisted publication date — never from
`is_monitored` alone, because a Reel still flagged monitored but past its window is no
longer synced (`expired`). `is_monitored` (QUA-94) is still forwarded as the raw flag.

`analyze_sentiment_now` (QUA-92) is the manual "Analizar sentimiento" button's transport.
It adds no analysis logic of its own and is never called from `sync_now`/`InboxState.
sync_comments` in either direction — QUA-21 stays exactly as manual as it already was.

**Commercial intent (m-24789644, PR 4b).** `thread_comments_page` decorates each comment
with its intent signal under `CURRENT_INTENT_VERSION` — ONE extra `current_signals` read
for the page's ids, never one per comment — and marks every class the committed golden-set
report does not back as «no fiable» (`class_reliability`, fail-closed). Its
`intent_filter` (`INTENT_FILTER_COMMERCIAL`) narrows the SAME paginated query to the
comments whose signal is commercial, so the cursor, the sentiment filter and the search
all keep working together. `analyze_intent_now` is the "Analizar intención" button's
transport over `qualify_api.intent.analyze_pending_intents`; like sentiment's, it is
manual-only and independent of sync in both directions.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.inbox import (
    list_candidate_media,
    set_media_monitored,
    sync_comments,
    sync_in_progress,
)
from qualify_api.inbox import (
    seconds_since_last_sync as _seconds_since_last_sync,
)
from qualify_api.inbox.monitoring import MonitoringState, effective_state
from qualify_api.inbox.service import CandidateMedia
from qualify_api.intent import (
    COMMERCIAL_CLASSES,
    CURRENT_INTENT_VERSION,
    INTENT_CLASS_LABELS,
    IntentClass,
    IntentSignal,
    analyze_pending_intents,
    class_reliability,
)
from qualify_api.intent import current_signals as _current_signals
from qualify_api.sentiment import analyze_pending_comments
from qualify_api.sentiment import global_sentiment_summary as _global_sentiment_summary
from qualify_api.sentiment import list_comments_for_thread as _list_comments_for_thread
from qualify_api.sentiment import list_reel_summaries as _list_reel_summaries
from qualify_api.sentiment.repository import (
    DEFAULT_COMMENT_PAGE_SIZE,
    DEFAULT_REEL_PAGE_SIZE,
    NULL_POSTED_AT_SENTINEL,
    AnalyzedComment,
    CommentListCursor,
    ReelListCursor,
    ReelSummary,
)

from .capabilities import Capability
from .connections_provider import connections_for
from .inbox_vm import (
    MONITORING_ACTIVE,
    MONITORING_EXPIRED,
    MONITORING_INACTIVE,
    MONITORING_PENDING,
    AnalysisSummaryVM,
    CandidateMediaVM,
    CommentPageCursorVM,
    CommentVM,
    GlobalSentimentSummaryVM,
    IntentAnalysisSummaryVM,
    IntentChipVM,
    ReelPageCursorVM,
    ReelSummaryVM,
    SyncSummaryVM,
    candidate_picture_url,
    media_format_label,
)
from .publishing_vm import ConnectionOptionVM


def instagram_connections(tenant_id: UUID) -> list[ConnectionOptionVM]:
    """Active Instagram connections that can actually list/monitor comments right now —
    same 'active status' filter `publishing_provider.active_connections` uses, narrowed
    further to `platform == "instagram"` and `READ_COMMENTS` (C-05) enabled.

    Blocking DB call (via `connections_for`) — callers on the event loop must run it
    off-thread, same as `connections_for` itself.
    """
    return [
        ConnectionOptionVM(
            id=connection.id,
            external_username=connection.external_username,
            platform=connection.platform,
        )
        for connection in connections_for(tenant_id)
        if connection.status == "active"
        and connection.platform == "instagram"
        and any(
            cap.key == Capability.READ_COMMENTS.value and cap.enabled
            for cap in connection.enabled_capabilities
        )
    ]


def _to_vm(media: CandidateMedia) -> CandidateMediaVM:
    return CandidateMediaVM(
        external_media_id=media.external_media_id,
        posted_at=media.timestamp.strftime("%d %b %Y, %H:%M"),
        is_monitored=media.is_monitored,
        caption=media.caption or "",
        permalink=media.permalink or "",
        thumbnail_url=candidate_picture_url(media.media_type, media.thumbnail_url, media.media_url),
        format_label=media_format_label(media.media_product_type, media.media_type),
    )


async def candidate_media(*, tenant_id: UUID, connection_id: UUID) -> list[CandidateMediaVM]:
    """The last-2-weeks Reels and feed posts (QUA-146) for this connection, newest first,
    cross-referenced against what is already monitored. Delegates entirely to
    `qualify_api.inbox`'s published seam.

    Raises `UnknownInboxConnection` (propagates — same posture `publishing_provider.
    active_connections` has for whatever `connections_for` raises) and any exception the
    Meta call itself can raise (`MediaReadError`, wrapped inside the service as "no
    candidates" only in the sense that the caller must handle it, never silently as an
    empty list — an empty list means "really nothing in the window", not "failed").
    """
    media = await list_candidate_media(tenant_id=tenant_id, connection_id=connection_id)
    return [_to_vm(m) for m in sorted(media, key=lambda m: m.timestamp, reverse=True)]


async def toggle_monitoring(
    *, tenant_id: UUID, connection_id: UUID, external_media_id: str, monitored: bool
) -> None:
    """Flip one Reel's monitoring toggle through the real B2 service.

    Raises `MediaNotEligible` (the 2-week re-validation refused it) and
    `UnknownInboxConnection` (connection not visible to this tenant) — both propagate,
    never swallowed, same posture `connections_provider.disconnect` already has for
    `ConnectionNotFound`. The caller (`InboxState`) maps these to Spanish messages and
    ALWAYS reloads the candidate list afterward regardless of outcome — see
    `inbox_state.py`'s module docstring for why this is never an optimistic update.
    """
    await set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=external_media_id,
        monitored=monitored,
    )


#: The intent filter's one real value; anything else (`"ALL"`, `""`) means no filter.
INTENT_FILTER_COMMERCIAL = "COMMERCIAL"


def _intent_chips(signal: IntentSignal, reliable: dict[IntentClass, bool]) -> list[IntentChipVM]:
    """The signal's classes, highest confidence first (ties by label, so the order is
    stable across reloads)."""
    ranked = sorted(
        signal.classes.items(), key=lambda item: (-item[1], INTENT_CLASS_LABELS[item[0]])
    )
    return [
        IntentChipVM(
            label=INTENT_CLASS_LABELS[intent_class],
            commercial=intent_class in COMMERCIAL_CLASSES,
            reliable=reliable.get(intent_class, False),
        )
        for intent_class, _confidence in ranked
    ]


def _to_comment_vm(
    comment: AnalyzedComment,
    signal: IntentSignal | None = None,
    reliable: dict[IntentClass, bool] | None = None,
) -> CommentVM:
    return CommentVM(
        message_id=str(comment.message_id),
        text=comment.text or "",
        author_username=comment.author_username or "",
        posted_at=comment.posted_at.strftime("%d %b %Y, %H:%M") if comment.posted_at else "",
        external_thread_id=comment.external_thread_id,
        sentiment_label=comment.label or "",
        score_display=f"{comment.score:.2f}" if comment.score is not None else "",
        intent_analyzed=signal is not None,
        intent_chips=_intent_chips(signal, reliable or {}) if signal is not None else [],
    )


def _reel_cursor_from_vm(cursor: ReelPageCursorVM | None) -> ReelListCursor | None:
    if cursor is None:
        return None
    return ReelListCursor(
        last_message_at=datetime.fromisoformat(cursor.last_message_at),
        thread_id=UUID(cursor.thread_id),
    )


def _comment_cursor_from_vm(cursor: CommentPageCursorVM | None) -> CommentListCursor | None:
    if cursor is None:
        return None
    return CommentListCursor(
        sort_key=datetime.fromisoformat(cursor.sort_key), message_id=UUID(cursor.message_id)
    )


def _monitoring_state(summary: ReelSummary, now: datetime) -> str:
    """QUA-149: the badge's state, from the SHARED rule — this module never compares
    dates itself. `effective_state` already treats an unknown date as active (the sync
    still processes that media); `pending` only splits that case out so the badge can
    say the date is still to be verified."""
    state = effective_state(
        is_monitored=summary.is_monitored, posted_at=summary.media_posted_at, now=now
    )
    if state is MonitoringState.ACTIVE:
        return MONITORING_PENDING if summary.media_posted_at is None else MONITORING_ACTIVE
    if state is MonitoringState.EXPIRED:
        return MONITORING_EXPIRED
    return MONITORING_INACTIVE


def _to_reel_summary_vm(
    summary: ReelSummary, candidates_by_media_id: dict[str, CandidateMediaVM], now: datetime
) -> ReelSummaryVM:
    enrichment = candidates_by_media_id.get(summary.external_thread_id)
    return ReelSummaryVM(
        thread_id=str(summary.thread_id),
        external_thread_id=summary.external_thread_id,
        last_message_at=summary.last_message_at.strftime("%d %b %Y, %H:%M"),
        total=summary.total,
        positive=summary.positive,
        neutral=summary.neutral,
        negative=summary.negative,
        not_analyzed=summary.not_analyzed,
        thumbnail_url=enrichment.thumbnail_url if enrichment else "",
        # QUA-149: persisted first (survives the window), live candidate list as fallback.
        caption=summary.caption or (enrichment.caption if enrichment else ""),
        permalink=summary.permalink or (enrichment.permalink if enrichment else ""),
        is_monitored=summary.is_monitored,
        monitoring_state=_monitoring_state(summary, now),
        # m-24789644 (B2): persisted type first, the live candidate's label as fallback.
        format_label=media_format_label(summary.media_product_type, summary.media_type)
        or (enrichment.format_label if enrichment else ""),
    )


def reel_summaries_page(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    cursor: ReelPageCursorVM | None,
    candidates: list[CandidateMediaVM],
    now: datetime | None = None,
) -> tuple[list[ReelSummaryVM], ReelPageCursorVM | None, bool]:
    """QUA-93: one page of Reel summary cards — never the full comment list of any Reel,
    let alone the connection (see `qualify_api.sentiment.repository`'s module docstring
    for the measured 1,200x this bound is worth). `candidates` is the ALREADY-loaded
    Reels-monitoring list (opción A enrichment, zero extra query/Meta call — see the
    module docstring).

    Returns `(items, next_cursor, has_more)`. `has_more` is a cheap heuristic — a full
    page might mean more exist, a short page never does — not a second `COUNT` query;
    a "Cargar más" that then returns nothing is harmless and self-correcting.

    Blocking DB call — callers on the event loop must run it off-thread. Raises
    `UnknownSentimentConnection` if the connection is not visible to this tenant.
    """
    candidates_by_media_id = {c.external_media_id: c for c in candidates}
    page = _list_reel_summaries(
        tenant_id=tenant_id,
        connection_id=connection_id,
        cursor=_reel_cursor_from_vm(cursor),
        limit=DEFAULT_REEL_PAGE_SIZE,
    )
    reference_now = now if now is not None else datetime.now(UTC)
    items = [_to_reel_summary_vm(s, candidates_by_media_id, reference_now) for s in page]
    next_cursor = None
    if page:
        last = page[-1]
        next_cursor = ReelPageCursorVM(
            last_message_at=last.last_message_at.isoformat(), thread_id=str(last.thread_id)
        )
    return items, next_cursor, len(page) == DEFAULT_REEL_PAGE_SIZE


def global_summary_vm(*, tenant_id: UUID, connection_id: UUID) -> GlobalSentimentSummaryVM:
    """QUA-93: the top-of-page 5-number widget — one aggregate query, never a list.
    Blocking DB call, same posture as `reel_summaries_page`. Raises
    `UnknownSentimentConnection` if the connection is not visible to this tenant."""
    summary = _global_sentiment_summary(tenant_id=tenant_id, connection_id=connection_id)
    return GlobalSentimentSummaryVM(
        positive=summary.positive,
        neutral=summary.neutral,
        negative=summary.negative,
        not_analyzed=summary.not_analyzed,
        total=summary.total,
    )


def thread_comments_page(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    thread_id: UUID,
    sentiment_filter: str,
    search: str,
    cursor: CommentPageCursorVM | None,
    intent_filter: str = "",
) -> tuple[list[CommentVM], CommentPageCursorVM | None, bool]:
    """QUA-93: one page of ONE Reel's comments — the detail view's read seam. `""`/`"ALL"`
    for `sentiment_filter` means no filter; any other value is passed straight through to
    `qualify_api.sentiment.repository.SENTIMENT_FILTER_PENDING`/`"POS"`/`"NEG"`/`"NEU"`
    (the UI's filter values already match those constants exactly, no translation table).
    Blank/whitespace `search` means no search. `intent_filter == INTENT_FILTER_COMMERCIAL`
    keeps only the comments commercial under `CURRENT_INTENT_VERSION`; any other value
    means no intent filter.

    Each comment carries its intent signal (m-24789644): one `current_signals` read for
    the whole page, skipped when the page is empty.

    Blocking DB call, same posture as `reel_summaries_page`. Raises
    `UnknownSentimentConnection` if the connection is not visible to this tenant.
    """
    repo_filter = sentiment_filter if sentiment_filter not in ("", "ALL") else None
    repo_search = search.strip() or None
    page = _list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        sentiment_filter=repo_filter,
        search=repo_search,
        cursor=_comment_cursor_from_vm(cursor),
        limit=DEFAULT_COMMENT_PAGE_SIZE,
        commercial_intent=(
            CURRENT_INTENT_VERSION if intent_filter == INTENT_FILTER_COMMERCIAL else None
        ),
    )
    signals = (
        _current_signals(tenant_id=tenant_id, message_ids=[c.message_id for c in page])
        if page
        else {}
    )
    reliable = class_reliability(CURRENT_INTENT_VERSION.detector_version) if signals else {}
    items = [_to_comment_vm(c, signals.get(c.message_id), reliable) for c in page]
    next_cursor = None
    if page:
        last = page[-1]
        sort_key = last.posted_at if last.posted_at is not None else NULL_POSTED_AT_SENTINEL
        next_cursor = CommentPageCursorVM(
            sort_key=sort_key.isoformat(), message_id=str(last.message_id)
        )
    return items, next_cursor, len(page) == DEFAULT_COMMENT_PAGE_SIZE


async def sync_now(
    *, tenant_id: UUID, connection_id: UUID, run_token: str | None = None
) -> SyncSummaryVM:
    """One `InboxService.sync_comments` pass, in process, for the session's tenant — the
    transport both the manual button and the automatic poll share (QUA-89).

    `tenant_id` is the authenticated session's (`InboxState` reads `auth.session_tenant_id`)
    and reaches `composition.sync_comments` as is: every read below it goes through
    `tenant_session`, so RLS — not this module — keeps one tenant out of another's
    connections. There is no tenant allow-list and no bearer token here.

    Every typed refusal of the seam propagates unchanged for `InboxState` to map to its
    own message: `UnknownInboxConnection`, `InboxConnectionInactive`,
    `CommentsPermissionMissing`, `SyncBudgetExhausted`, `CommentsAuthExpired` and
    `CommentsReadError` — plus `SyncAlreadyRunning` when another pass holds the
    connection's lease. `run_token` names the pass so `sync_still_running` can ask about
    it later.
    """
    summary = await sync_comments(
        tenant_id=tenant_id, connection_id=connection_id, run_token=run_token
    )
    return SyncSummaryVM(
        media_checked=summary.media_checked,
        new_comments=summary.new_comments,
        truncated=summary.truncated,
        skipped_missing_media=tuple(summary.skipped_missing_media),
        deleted_comments=summary.deleted_comments,
        expired_skipped=summary.expired_skipped,
        metadata_backfilled=summary.metadata_backfilled,
        metadata_failed=summary.metadata_failed,
        metadata_deferred=summary.metadata_deferred,
    )


async def sync_still_running(*, tenant_id: UUID, connection_id: UUID, run_token: str) -> bool:
    """Whether the pass `run_token` names still holds its lease (some process is executing
    it). Unknown — Redis unreachable — answers True."""
    return await sync_in_progress(tenant_id=tenant_id, connection_id=connection_id, token=run_token)


async def seconds_since_last_sync(*, tenant_id: UUID, connection_id: UUID) -> float | None:
    """Age of the last finished pass on this connection, shared across tabs and
    processes; `None` when unknown. What the cooldown of the automatic triggers reads."""
    return await _seconds_since_last_sync(tenant_id=tenant_id, connection_id=connection_id)


async def analyze_sentiment_now(*, tenant_id: UUID, connection_id: UUID) -> AnalysisSummaryVM:
    """One QUA-21 analysis pass, in process, for the session's tenant — the same
    `analyze_pending_comments` seam `POST /api/sentiment/analyze` wraps, not a second
    analysis engine. Off the event loop: the seam is synchronous (Postgres + the local
    model).

    Propagates `UnknownSentimentConnection` and `SentimentModelUnavailable` (the `ml`
    group is not installed in this deployment) for `InboxState` to map.
    """
    summary = await asyncio.to_thread(
        analyze_pending_comments, tenant_id=tenant_id, connection_id=connection_id
    )
    return AnalysisSummaryVM(
        comments_checked=summary.comments_checked,
        new_results=summary.new_results,
        skipped_empty=summary.skipped_empty,
    )


async def analyze_intent_now(*, tenant_id: UUID, connection_id: UUID) -> IntentAnalysisSummaryVM:
    """One commercial-intent pass (m-24789644), in process, for the session's tenant —
    `qualify_api.intent.analyze_pending_intents`, the one intent engine. Off the event
    loop: the seam is synchronous (Postgres + the Claude call).

    Propagates `UnknownIntentConnection` and `IntentModelUnavailable` (no
    `QUALIFY_ANTHROPIC_API_KEY` in this deployment) for `InboxState` to map.
    """
    summary = await asyncio.to_thread(
        analyze_pending_intents, tenant_id=tenant_id, connection_id=connection_id
    )
    return IntentAnalysisSummaryVM(
        comments_checked=summary.comments_checked,
        new_results=summary.new_results,
        skipped_empty=summary.skipped_empty,
        unclassified=summary.unclassified,
    )
