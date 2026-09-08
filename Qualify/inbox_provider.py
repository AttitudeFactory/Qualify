"""The seam between the inbox content screen and the real inbox backend (Fase 1 Parte
4-B, B2 UI slice).

Same split `publishing_provider.py` documents, with one deliberate exception:

- **Reads this module reuses.** `instagram_connections` reuses `connections_provider.
  connections_for` exactly as it is, filtered to `platform == "instagram"`, `status ==
  "active"` and the `READ_COMMENTS` capability (C-05) being enabled — this module adds
  zero new database access for that list.
- **In-process writes/reads.** `candidate_media`/`toggle_monitoring` are thin async
  projections over `qualify_api.inbox.composition`'s published seam
  (`list_candidate_media`/`set_media_monitored`, re-exported from `qualify_api.inbox`),
  same role `publishing_provider.py` has over `qualify_api.publishing.composition` — no
  HTTP hop, same posture `http/app.py`'s own module docstring documents for the Reflex
  CRM in general.
- **The exceptions that go through HTTP: `sync_now` and `analyze_sentiment_now`.** B2's
  acceptance criteria (`docs/backlog-sprint3-meta-publishing-inbox.md`) explicitly
  requires `POST /api/inbox/sync` as sync's production route — unlike candidate listing
  and the toggle, which were never asked for one. `analyze_sentiment_now` (QUA-92) is
  built the same way ON PURPOSE: `/api/sentiment/analyze` is QUA-21's existing,
  already-wired mechanism (`http/app.py` overrides `sentiment_routes.
  get_analyze_pending_comments` to the real `composition.analyze_pending_comments` in
  production), and reusing that route is what "no crear otro motor de análisis" means in
  practice — not a second, in-process call path to the same service. Both reach their
  service through that real route, via an in-process ASGI transport
  (`httpx.ASGITransport`) — real HTTP semantics (status codes, JSON (de)serialization,
  the route's own error mapping), no socket, no second process to run/manage. See
  `_inbox_sync_asgi_client` below for what that buys and what it costs (a single
  dev-tenant scope, see its docstring) — both functions share that one cached client.

`sync_now` (2026-08-15, wired to HTTP 2026-08-16) is the transport both the manual button
and the automatic poll share (QUA-89, 2026-08-19) — see `inbox_page.py`'s module
docstring for the UI side. It adds no sync logic of its own: `InboxService.sync_comments`
already reads ONLY `InboxRepository.list_monitored_media_ids` (media with
`is_monitored=True`), so which Reels get synced is entirely decided by the toggle, not
by anything in this module.

`candidate_media`/`toggle_monitoring` are already `async def` (the whole chain down to
`InjectingCredentialResolver.client_for` is), so neither needs `asyncio.to_thread` — same
posture `publishing_provider.start_publish`/`poll_publish` already have over their own
already-async seam. `sync_now` is `async def` for the same reason `httpx.AsyncClient` is.

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

`reel_summaries_page`'s thumbnail/caption/permalink enrichment (opción A's one widening,
founder-approved 2026-08-25) cross-references `CandidateMediaVM` the caller already
loaded for the Reels-monitoring list — this module makes no new query and no new Meta
call for it. A Reel outside that list's 2-week window simply gets `""` for all three;
see `qualify_api.sentiment.repository`'s module docstring for why enriching those too
is explicit fast-follow work, not silently attempted here.

`ReelSummaryVM.is_monitored` (QUA-94) is a straight pass-through of `ReelSummary.
is_monitored` — no lookup against `candidates_by_media_id` needed (unlike the
thumbnail/caption/permalink trio above), because `_list_reel_summaries` already
decorates each row with its current `monitored_media` state via a LEFT JOIN. A Reel
outside the 2-week candidate window can still be `is_monitored=True` (it was turned on
before it aged out — see the `list_candidate_media` vs `monitored_media` distinction in
`qualify_api.inbox.service`'s module docstring); the two flags are independent and both
already correct at the repository layer, so this function only ever forwards the value.

`analyze_sentiment_now` (QUA-92) is the manual "Analizar sentimiento" button's transport
— see above for why it goes through `POST /api/sentiment/analyze` rather than calling
`qualify_api.sentiment.composition.analyze_pending_comments` in process. It adds no
analysis logic of its own and is never called from `sync_now`/`InboxState.sync_comments`
in either direction — QUA-21 stays exactly as manual as it already was; this only gives
that existing trigger a visible button.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from uuid import UUID

import httpx
from qualify_api.inbox import (
    CommentsAuthExpired,
    CommentsPermissionMissing,
    SyncBudgetExhausted,
    list_candidate_media,
    set_media_monitored,
)
from qualify_api.inbox.composition import UnknownInboxConnection
from qualify_api.inbox.service import CandidateMedia
from qualify_api.sentiment import UnknownSentimentConnection
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
    AnalysisSummaryVM,
    CandidateMediaVM,
    CommentPageCursorVM,
    CommentVM,
    GlobalSentimentSummaryVM,
    ReelPageCursorVM,
    ReelSummaryVM,
    SyncSummaryVM,
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
        thumbnail_url=media.thumbnail_url or "",
    )


async def candidate_media(*, tenant_id: UUID, connection_id: UUID) -> list[CandidateMediaVM]:
    """The last-2-weeks Reels for this connection, newest first, cross-referenced against
    what is already monitored. Delegates entirely to `qualify_api.inbox`'s published seam.

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


def _to_comment_vm(comment: AnalyzedComment) -> CommentVM:
    return CommentVM(
        message_id=str(comment.message_id),
        text=comment.text or "",
        author_username=comment.author_username or "",
        posted_at=comment.posted_at.strftime("%d %b %Y, %H:%M") if comment.posted_at else "",
        external_thread_id=comment.external_thread_id,
        sentiment_label=comment.label or "",
        score_display=f"{comment.score:.2f}" if comment.score is not None else "",
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


def _to_reel_summary_vm(
    summary: ReelSummary, candidates_by_media_id: dict[str, CandidateMediaVM]
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
        caption=enrichment.caption if enrichment else "",
        permalink=enrichment.permalink if enrichment else "",
        is_monitored=summary.is_monitored,
    )


def reel_summaries_page(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    cursor: ReelPageCursorVM | None,
    candidates: list[CandidateMediaVM],
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
    items = [_to_reel_summary_vm(s, candidates_by_media_id) for s in page]
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
) -> tuple[list[CommentVM], CommentPageCursorVM | None, bool]:
    """QUA-93: one page of ONE Reel's comments — the detail view's read seam. `""`/`"ALL"`
    for `sentiment_filter` means no filter; any other value is passed straight through to
    `qualify_api.sentiment.repository.SENTIMENT_FILTER_PENDING`/`"POS"`/`"NEG"`/`"NEU"`
    (the UI's filter values already match those constants exactly, no translation table).
    Blank/whitespace `search` means no search.

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
    )
    items = [_to_comment_vm(c) for c in page]
    next_cursor = None
    if page:
        last = page[-1]
        sort_key = last.posted_at if last.posted_at is not None else NULL_POSTED_AT_SENTINEL
        next_cursor = CommentPageCursorVM(
            sort_key=sort_key.isoformat(), message_id=str(last.message_id)
        )
    return items, next_cursor, len(page) == DEFAULT_COMMENT_PAGE_SIZE


# Matches the single `QUALIFY_DEV_PRINCIPALS` entry added to `.env` on 2026-08-16 — the
# ONLY tenant this temporary bridge can authenticate as (PuntoServis, the real
# qualifymkt.co demo tenant). Adding more dev tenants means adding more entries to that
# env var, not changing this module — see `.env`'s comment for the format.
_DEV_SYNC_BEARER_TOKEN = "dev-inbox-sync-puntoservis"  # noqa: S105 - a local dev credential, not a secret
_DEV_SYNC_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")  # PuntoServis


@lru_cache(maxsize=1)
def _inbox_sync_asgi_client() -> httpx.AsyncClient:
    """The real, production-configured FastAPI app (`create_app()` — the same factory a
    real `uvicorn` deployment would use), reached via `httpx.ASGITransport` instead of a
    socket: real HTTP semantics (status codes, JSON (de)serialization, `inbox_routes.
    sync_inbox`'s own error mapping) with no server process to start, monitor or stop —
    there isn't one running in this dev environment (no `just` recipe, no uvicorn
    entrypoint) and standing one up is out of scope for what is explicitly a temporary
    affordance. Cached: rebuilding the app (and its `dependency_overrides`) on every
    click would be pure waste — the app is stateless and safe to reuse across requests,
    same reasoning `publishing.composition.production_publish_service` is `@cache`d.

    `create_app(configure_production=True)` is cheap to call: the OTHER dependency
    overrides it wires (`get_connect_service`, `get_publish_service`, ...) are bare
    function references, not invoked until a request actually needs them — and this
    client only ever calls `/api/inbox/sync` and `/api/sentiment/analyze` (QUA-92 reuses
    this same cached client rather than building a second one — see the module
    docstring). The one override that DOES run eagerly is
    `current_principal`'s (`deps.build_dev_principal_dependency()` parses
    `QUALIFY_DEV_PRINCIPALS` immediately) — pure string parsing, no I/O, and `.env` is
    already loaded by the time any Reflex event handler runs (`rxconfig.py`'s
    `env_file`).
    """
    from qualify_api.http.app import create_app  # noqa: PLC0415 - see the module docstring

    app = create_app(configure_production=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inbox-sync.internal"
    )


async def sync_now(*, tenant_id: UUID, connection_id: UUID) -> SyncSummaryVM:
    """Trigger one `InboxService.sync_comments` pass via `POST /api/inbox/sync` — the
    temporary manual caller's provider half, now the route rather than
    `composition.sync_comments` directly (see the module docstring for why).

    Raises `UnknownInboxConnection` in two cases the caller cannot tell apart, both
    already handled identically by `InboxState.sync_comments` (which shows the same
    "esa cuenta ya no está disponible" message either way, so collapsing them is a
    correct simplification, not a lost distinction):
    - `tenant_id` is not the one tenant `QUALIFY_DEV_PRINCIPALS` authenticates as this
      temporary bridge — refused BEFORE any HTTP call, so a mismatched dev tenant never
      silently syncs against the wrong one's data.
    - the route itself answers 404 (the connection is not visible to the authenticated
      tenant) — the same condition `candidate_media`/`toggle_monitoring` already raise
      this for.

    Raises `CommentsPermissionMissing` (403 — `cannot_observe`, QUA-88) and
    `SyncBudgetExhausted` (429 — the real Meta call budget is spent, QUA-88), same
    "reconstruct a typed exception from the status code" posture the 404 branch below
    already establishes for `UnknownInboxConnection`. Neither carries the server's exact
    message back through: `InboxState.sync_comments` only branches on exception TYPE to
    pick a Spanish message, the same way it already does for `UnknownInboxConnection`.

    Raises `CommentsAuthExpired` (401 — a real runtime auth failure against Meta, QUA-90),
    same reconstruct-from-status-code posture as the other three. By the time this status
    code reaches here the connection has already been degraded server-side
    (`InboxService.sync_comments`); this is only the client-visible signal of that.

    Any other non-2xx response (502 from a failed Meta call, 500 from anything
    unexpected) raises `httpx.HTTPStatusError` via `raise_for_status()` — an ordinary
    exception `InboxState.sync_comments`'s blanket `except Exception` already catches,
    same as it already did for whatever `composition.sync_comments` could raise directly
    before this change.
    """
    if tenant_id != _DEV_SYNC_TENANT_ID:
        raise UnknownInboxConnection(
            f"tenant {tenant_id} is not wired to the temporary dev sync bridge "
            f"(QUALIFY_DEV_PRINCIPALS only authenticates tenant {_DEV_SYNC_TENANT_ID})"
        )
    client = _inbox_sync_asgi_client()
    response = await client.post(
        "/api/inbox/sync",
        json={"connection_id": str(connection_id)},
        headers={"Authorization": f"Bearer {_DEV_SYNC_BEARER_TOKEN}"},
    )
    if response.status_code == 404:
        raise UnknownInboxConnection(str(connection_id))
    if response.status_code == 401:
        raise CommentsAuthExpired(connection_id=connection_id)
    if response.status_code == 403:
        raise CommentsPermissionMissing(connection_id=connection_id)
    if response.status_code == 429:
        # The route's exact needed/remaining are not reconstructed here — the caller
        # only branches on exception TYPE, same posture as the 404/403 cases above.
        raise SyncBudgetExhausted(needed=0, remaining=0)
    response.raise_for_status()
    data = response.json()
    return SyncSummaryVM(
        media_checked=data["media_checked"],
        new_comments=data["new_comments"],
        truncated=data.get("truncated", False),
        # `.get(..., [])`, not a required key: keeps this projection backward-compatible
        # with a response shape from before this field existed (bug fix, 2026-09-01),
        # same defensive posture `truncated` above already established for itself.
        skipped_missing_media=tuple(data.get("skipped_missing_media", [])),
        # Same backward-compatible `.get(..., 0)` posture, for the same reason (QUA-101).
        deleted_comments=data.get("deleted_comments", 0),
    )


async def analyze_sentiment_now(*, tenant_id: UUID, connection_id: UUID) -> AnalysisSummaryVM:
    """Trigger one QUA-21 analysis pass via `POST /api/sentiment/analyze` — reuses that
    exact, already-wired route/mechanism (see the module docstring for why this is a
    second HTTP caller, never a second analysis engine). Same dev-tenant-bridge
    precondition and same "reconstruct a typed exception from the status code" posture
    `sync_now` above establishes, deliberately NOT shared code between the two beyond the
    cached client: the two routes' error vocabularies differ (this one has no
    `CommentsPermissionMissing`/`SyncBudgetExhausted`/`CommentsAuthExpired` — analysis
    never calls Meta, so none of those Meta-specific refusals apply here).

    Raises `UnknownSentimentConnection` in the same two cases `sync_now` raises
    `UnknownInboxConnection` for: a tenant mismatch with the dev bridge (refused BEFORE
    any HTTP call), or the route's own 404 (the connection is not visible to the
    authenticated tenant — the same condition the route's `UnknownSentimentConnection`
    handler already maps to 404). Any other non-2xx response raises
    `httpx.HTTPStatusError` via `raise_for_status()`, same as `sync_now`.
    """
    if tenant_id != _DEV_SYNC_TENANT_ID:
        raise UnknownSentimentConnection(
            f"tenant {tenant_id} is not wired to the temporary dev sync bridge "
            f"(QUALIFY_DEV_PRINCIPALS only authenticates tenant {_DEV_SYNC_TENANT_ID})"
        )
    client = _inbox_sync_asgi_client()
    response = await client.post(
        "/api/sentiment/analyze",
        json={"connection_id": str(connection_id)},
        headers={"Authorization": f"Bearer {_DEV_SYNC_BEARER_TOKEN}"},
    )
    if response.status_code == 404:
        raise UnknownSentimentConnection(str(connection_id))
    response.raise_for_status()
    data = response.json()
    return AnalysisSummaryVM(
        comments_checked=data["comments_checked"],
        new_results=data["new_results"],
        skipped_empty=data["skipped_empty"],
    )
