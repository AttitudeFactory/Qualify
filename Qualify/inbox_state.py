"""Reflex state for the inbox content screen — pick which recent Reels to monitor
(Fase 1 Parte 4-B, B2 UI slice).

Reads the active tenant from `AuthState.session_tenant_id` (via `self.get_state`),
same single-source-of-truth decision `publishing_state.py` already documents — one place
answers "which tenant", not a second selector duplicating it.

**The monitoring toggle never updates local state optimistically.** `toggle_monitored`
always re-fetches from the real backend after `set_media_monitored` settles — success OR
the caller-visible `MediaNotEligible` refusal — so neither the switch on screen nor the
"Comentarios" section's monitoring badge (`reel_summaries[*].is_monitored`, QUA-94) can
ever show a state Postgres does not actually hold. This is an explicit product decision
(not just this module's default), same "reload so the UI shows the reconciled state"
posture `ConnectionsState.disconnect_connection` already established for revoke.

**`sync_comments` (the event handler below) is the one sync trigger** both the manual
"Sincronizar comentarios" button and the automatic 5-minute poll call — added 2026-08-15
as a manual-only demo of the B2 flow (monitored Reel → click → Meta → Postgres), promoted
2026-08-19 (QUA-89) to the permanent trigger for both paths. It adds no sync logic of its
own: `InboxService.sync_comments` already reads only `is_monitored=True` media, so which
Reels get synced is entirely decided by the toggle above it, not by this handler. Because
BOTH callers (`inbox_page.py`'s button and its hidden `rx.moment` heartbeat — see that
module's docstring) invoke this exact same handler, the `is_syncing` guard below is a
single re-entrancy lock shared by both — a tick that lands while the button's click is
still in flight (or vice versa) is a no-op, not a second concurrent sync. There is no
separate scheduler process anywhere: the "automatic" half is a client-side timer, not a
server-side loop — see `inbox_page.py::_polling_timer`'s docstring for why that is what
makes it safe to leave running with nothing to cancel. It reaches that service in
process with the session's tenant (`inbox_provider.sync_now`; B8, 2026-10-08 — it used to
go through a dev-only HTTP bridge that refused every tenant but one). Each failure gets its
own message — session expired, account disconnected, permission missing, Meta auth
expired, budget spent, Instagram failing, anything else — so «Esa cuenta ya no está
disponible» only ever means what it says: the connection is not visible to this tenant.

**`analyze_sentiment` is QUA-21's manual trigger, made visible as a button (QUA-92).** It
is the only place in this file that calls `qualify_api.sentiment` for a WRITE —
`sync_comments` above never mentions it, in either direction (pinned by
`test_analyze_sentiment_is_independent_of_sync_comments_in_both_directions` and
`test_sync_comments_never_runs_sentiment_analysis`).

**QUA-93 replaces the flat `comments` list with a two-level read: Reel summary cards
(`reel_summaries`, paginated) + a global widget (`global_summary`) at the top level, and
one Reel's comments (`thread_comments`, paginated/filtered/searched) in a detail view
toggled by `selected_thread_id`.** Nothing in this file ever holds more than one page of
either list at a time — see `qualify_api.sentiment.repository`'s module docstring for why
that bound is load-bearing, not a style choice (a naive unbounded read regressed to a
28.5-SECOND query at 1,000 Reels x 100 comments).

`_refresh_after_write` is the one post-write re-read THREE handlers call. `sync_comments`
and `analyze_sentiment` call it in their tail, reached ONLY on success (every failure
branch `return`s before it — see each handler's own comment for why that structural
placement is what makes "only on success" true without an extra flag). `toggle_monitored`
(QUA-94) calls it unconditionally, right after `_load_candidates` — see its own comment
for why "regardless of outcome" is correct there too: a refused or failed toggle still
leaves the DB in SOME real state, and only a fresh read shows what it actually is, same
reasoning that already governs `_load_candidates` itself. Whichever caller reaches it,
`_refresh_after_write` always refreshes `global_summary`; if a Reel's detail is open it
refreshes that Reel's comments (so "Sin analizar" flips to POS/NEG/NEU in place) plus a
best-effort refresh of that Reel's summary chips from the reloaded first page of
`reel_summaries` (a Reel that fell off page 1 keeps stale chips until the operator
scrolls to it — a known, accepted gap, not a second backend method for one edge case);
otherwise it refreshes the Reel list's first page. None of the three callers' branches
re-runs analysis or sync — this is always a pure re-read.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Final
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.followups.service import OriginNotSupported, UnknownOrigin
from qualify_api.inbox import (
    CommentsAuthExpired,
    CommentsPermissionMissing,
    CommentsReadError,
    InboxConnectionInactive,
    MediaNotEligible,
    SyncAlreadyRunning,
    SyncBudgetExhausted,
    UnknownInboxConnection,
)
from qualify_api.intent import IntentModelUnavailable, UnknownIntentConnection
from qualify_api.sentiment import SentimentModelUnavailable, UnknownSentimentConnection
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .inbox_provider import (
    INTENT_FILTER_COMMERCIAL,
    analyze_intent_now,
    analyze_sentiment_now,
    candidate_media,
    global_summary_vm,
    instagram_connections,
    reel_summaries_page,
    reply_by_dm,
    seconds_since_last_sync,
    sync_now,
    sync_still_running,
    thread_comments_page,
    toggle_monitoring,
)
from .inbox_sync_policy import claim_is_stale, normalize_trigger, skip_for_cooldown
from .inbox_vm import (
    AnalysisSummaryVM,
    CandidateMediaVM,
    CommentPageCursorVM,
    CommentVM,
    GlobalSentimentSummaryVM,
    IntentAnalysisSummaryVM,
    ReelPageCursorVM,
    ReelSummaryVM,
    SyncSummaryVM,
)
from .publishing_vm import ConnectionOptionVM
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_LOAD_FAILED = (
    "No pudimos cargar tus publicaciones recientes. Revisa que tu Instagram siga "
    "conectado en «Tus redes»."
)
_TOGGLE_FAILED = "No pudimos guardar tu cambio. Intenta de nuevo."
_TOO_OLD = "Esta publicación tiene más de 2 semanas: ya no buscamos sus comentarios."
_NOT_ELIGIBLE = (
    "No se pudo verificar este contenido contra Instagram. Actualiza la lista e intenta de nuevo."
)
# QUA-146: `MediaNotEligible(reason="unsupported_surface")` — a Story, an ad, or a media
# whose surface Instagram did not report. The picker never offers these, so this is the
# message for a stale list or a direct call, not for a normal click.
_UNSUPPORTED_SURFACE = (
    "Solo buscamos comentarios en Reels y publicaciones de tu perfil. "
    "Las historias y los anuncios no se revisan."
)


def is_inbox_path(path: str) -> bool:
    """Whether the tab is on the comments screen (`/responder` since m-24842990, whose
    «Comentarios» tab holds it; `/inbox` only redirects there), with or without the
    trailing slash the production build adds. Used to keep a late sync toast off other
    pages."""
    return path.rstrip("/") in ("/responder", "/inbox")


# `MediaNotEligible.reason` -> message; any other reason keeps `_NOT_ELIGIBLE`.
_NOT_ELIGIBLE_BY_REASON: Final = {
    "too_old": _TOO_OLD,
    "unsupported_surface": _UNSUPPORTED_SURFACE,
}
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la lista e intenta de nuevo."
_SYNC_FAILED = "No pudimos buscar comentarios nuevos. Intenta de nuevo."
# B8: the two halves `_NO_TENANT` used to cover for sync/analysis. No tenant in the
# session means there is no login (`AuthState.session_tenant_id` is set only by one).
_SESSION_EXPIRED = "Tu sesión expiró. Vuelve a iniciar sesión."
_NO_CONNECTION_SELECTED = "Elige primero una cuenta de Instagram."
# The connection is the tenant's but no longer `active` (disconnected or degraded) —
# never synced, and never confused with "not visible" (`_UNKNOWN_CONNECTION`).
_CONNECTION_INACTIVE = (
    "Esta cuenta está desconectada. Reconéctala en «Tus redes» para ver sus comentarios nuevos."
)
# A Graph call that was attempted and failed (`CommentsReadError`) — Instagram's side.
_SYNC_META_FAILED = (
    "Instagram no respondió cuando buscamos tus comentarios. Intenta de nuevo en unos minutos."
)
# cannot_observe (QUA-88): the connection cannot read the comments edge AT ALL — never
# shown as if it were a normal zero-comments result.
_COMMENTS_PERMISSION_MISSING = (
    "Falta un permiso para leer comentarios en esta cuenta. Reconéctala para concederlo."
)
_SYNC_BUDGET_EXHAUSTED = (
    "Buscamos comentarios muchas veces seguidas. Espera unos minutos e intenta de nuevo."
)
# QUA-90: a real runtime 401/190 — the connection is already `degraded` server-side by
# the time this reaches the UI (Conexiones already shows "Reconectar"), so this message
# points there instead of repeating the generic sync-failed copy.
_CONNECTION_AUTH_EXPIRED = (
    "Tu conexión con Instagram dejó de funcionar. Reconéctala en «Tus redes» e intenta de nuevo."
)
_SYNC_ALREADY_RUNNING = "Ya estamos buscando comentarios nuevos. Te avisamos al terminar."
_ANALYZE_FAILED = "No pudimos ver si tus comentarios son buenos o malos. Intenta de nuevo."
# The local model's runtime (`ml` group) is not installed in this deployment — not a
# transient failure, so "intenta de nuevo" would be a lie.
_ANALYZE_UNAVAILABLE = (
    "Ahora no podemos ver si tus comentarios son buenos o malos. "
    "Puedes leerlos y responderlos igual."
)
# m-24789644: same two cases for the intent pass. Unavailable = no Anthropic key here.
_REPLY_BY_DM_GONE = "Ese comentario ya no está disponible."
_REPLY_BY_DM_FAILED = "No pudimos preparar el mensaje privado. Vuelve a intentarlo en un momento."
_ANALYZE_INTENT_FAILED = "No pudimos ver quién quiere comprar. Intenta de nuevo."
_ANALYZE_INTENT_UNAVAILABLE = (
    "Ahora no podemos ver quién quiere comprar. Lee los comentarios y responde tú."
)
# QUA-93 — each of the three new sections has its own load error, same "independent
# §6.1 lifecycle per section" posture the design doc documents.
_REEL_SUMMARIES_LOAD_FAILED = (
    "No pudimos cargar tus publicaciones con comentarios. Intenta de nuevo."
)
_GLOBAL_SUMMARY_LOAD_FAILED = "No pudimos cargar el resumen de tus comentarios. Intenta de nuevo."
_THREAD_COMMENTS_LOAD_FAILED = (
    "No pudimos cargar los comentarios de esta publicación. Intenta de nuevo."
)
# Turning monitoring OFF never calls Meta (InboxService.set_media_monitored only
# re-validates against Meta when monitored=True — see its docstring); a straight Postgres
# UPDATE + reload can settle in well under 50ms, too fast for the card skeleton to ever
# be perceived. Turning ON's real Meta round-trip is not. Padding BOTH to at least this
# long makes the skeleton behave identically regardless of direction — a pure UI-timing
# floor, not a change to how fast the real operation is.
_MIN_TOGGLE_ANIMATION_SECONDS = 0.5

# QUA-93: the sentiment filter's "no filter" value — never sent to the repository as a
# real filter (`inbox_provider.thread_comments_page` maps it to `None`).
FILTER_ALL = "ALL"
# m-24789644: the intent filter's one real value, re-exported for the page.
FILTER_COMMERCIAL = INTENT_FILTER_COMMERCIAL

# Bug fix (2026-08-25): a successful sync/analysis pass used to render its confirmation
# as a persistent `callout` — the same primitive `_sync_error_block`/`_analyze_error_
# block` correctly use for errors — which meant it never went away on its own. Per
# docs/design-system.md §5.4 ("confirmaciones transitorias → rx.toast") and §9.3's own
# known-debt item 5, a SUCCESS confirmation is exactly the transient case a toast is for;
# errors stay persistent callouts, unchanged. `sync_result`/`analyze_result` themselves
# are untouched (still set on every success, still readable by anything that wants the
# last outcome) — only the visible confirmation moves from "rendered forever in
# `inbox_page.py`" to "a toast that dismisses itself after this many milliseconds".
_RESULT_TOAST_DURATION_MS = 6000


class InboxState(rx.State):
    """State for the "Interacciones" screen (formerly "Contenido"): pick an Instagram
    connection, see its Reels from the last 2 weeks, toggle which ones are monitored, and
    browse their comments'
    sentiment two levels deep (Reel summary list -> one Reel's comments)."""

    connections: list[ConnectionOptionVM] = []
    selected_connection_id: str = ""
    is_loading_connections: bool = False
    connections_error: str = ""

    candidates: list[CandidateMediaVM] = []
    is_loading_candidates: bool = False
    load_error: str = ""
    # Errors from the toggle action, kept apart from `load_error`: a refused toggle must
    # not blank the list the operator is looking at.
    action_error: str = ""
    # Media ids whose switch is mid-flight, so each row can disable itself against a
    # double-click on ITSELF while staying independent of every other row — a list
    # (not a single id) so toggling Reel B while Reel A is still in flight starts its
    # own operation instead of being silently ignored.
    toggling_media_ids: list[str] = []

    # Shared by the manual button AND the automatic poll (QUA-89) — see module docstring.
    # Screen-wide, not per-row — unlike toggling_media_ids, a sync pass has no single Reel
    # it belongs to.
    is_syncing: bool = False
    # The run this tab's claim belongs to, and when it was claimed (epoch seconds) — what
    # `sync_comments` needs to tell a live pass from a leftover claim (see its docstring).
    sync_run_id: str = ""
    sync_claimed_at: float = 0.0
    sync_error: str = ""
    sync_result: SyncSummaryVM | None = None

    # QUA-92 — the manual "Analizar sentimiento" button. Its own guard/loading state,
    # same reasoning `is_syncing` has: one screen-wide flag (not per-comment), since one
    # click analyzes every pending comment for the connection at once, not a single row.
    is_analyzing: bool = False
    analyze_error: str = ""
    analyze_result: AnalysisSummaryVM | None = None
    # m-24789644: the "Analizar intención" pass — its own guard, independent of both
    # sync and sentiment analysis, same as those two are of each other.
    is_analyzing_intent: bool = False
    # m-24789646: the comment whose «Responder por DM» is opening its query ("" = none).
    replying_dm_id: str = ""
    analyze_intent_error: str = ""
    analyze_intent_result: IntentAnalysisSummaryVM | None = None

    # QUA-93 — the Reel summary-card list (top level of "Comentarios"). Never holds more
    # than one page; `load_more_reels` appends, it never re-fetches everything.
    reel_summaries: list[ReelSummaryVM] = []
    is_loading_reel_summaries: bool = False
    reel_summaries_error: str = ""
    reel_summaries_cursor: ReelPageCursorVM | None = None
    has_more_reels: bool = False
    is_loading_more_reels: bool = False

    # QUA-93 — the 5-number global sentiment widget. Independent load/error state, same
    # reasoning every other section in this file has.
    global_summary: GlobalSentimentSummaryVM | None = None
    is_loading_global_summary: bool = False
    global_summary_error: str = ""

    # QUA-93 — the Reel detail view. `selected_thread_id == ""` means "showing the
    # summary-card list"; non-empty means "showing this Reel's comments". A cursor is
    # valid only under the `sentiment_filter`/`search_query` that produced it — both
    # setters reset pagination to a fresh first page.
    selected_thread_id: str = ""
    selected_reel_summary: ReelSummaryVM | None = None
    thread_comments: list[CommentVM] = []
    is_loading_thread_comments: bool = False
    thread_comments_error: str = ""
    thread_comments_cursor: CommentPageCursorVM | None = None
    has_more_thread_comments: bool = False
    is_loading_more_thread_comments: bool = False
    sentiment_filter: str = FILTER_ALL
    # m-24789644: `FILTER_ALL` or `FILTER_COMMERCIAL` («Requiere atención comercial»).
    intent_filter: str = FILTER_ALL
    search_query: str = ""

    @rx.var
    def has_connections(self) -> bool:
        return len(self.connections) > 0

    @rx.var
    def can_sync(self) -> bool:
        return bool(self.selected_connection_id) and not self.is_syncing

    @rx.var
    def can_analyze(self) -> bool:
        return bool(self.selected_connection_id) and not self.is_analyzing

    @rx.var
    def can_analyze_intent(self) -> bool:
        return bool(self.selected_connection_id) and not self.is_analyzing_intent

    @rx.var
    def is_prioritizing(self) -> bool:
        """m-24842988: «Ordenar por prioridad» runs both passes; busy while either is."""
        return self.is_analyzing or self.is_analyzing_intent

    @rx.var
    def can_prioritize(self) -> bool:
        return bool(self.selected_connection_id) and not self.is_prioritizing

    @rx.var
    def show_empty_state(self) -> bool:
        return (
            not self.is_loading_candidates
            and not self.load_error
            and bool(self.selected_connection_id)
            and len(self.candidates) == 0
        )

    @rx.var
    def is_showing_reel_detail(self) -> bool:
        return bool(self.selected_thread_id)

    @rx.var
    def show_empty_reel_summaries(self) -> bool:
        return (
            not self.is_loading_reel_summaries
            and not self.reel_summaries_error
            and bool(self.selected_connection_id)
            and len(self.reel_summaries) == 0
        )

    @rx.var
    def show_empty_thread_comments(self) -> bool:
        return (
            not self.is_loading_thread_comments
            and not self.thread_comments_error
            and len(self.thread_comments) == 0
        )

    async def _load_candidates(
        self, tenant_id: UUID, connection_id: str, *, show_loading: bool = True
    ) -> None:
        """Shared by the initial load, a connection switch, and every toggle's
        post-action reload. Private (not `@rx.event`) — same role `PublishState.
        _fail_pending_attempt` has, a helper called FROM background handlers, not one
        itself.

        `show_loading=False` is what `toggle_monitored` passes: `is_loading_candidates`
        drives `_candidates_body()`'s full-list skeleton swap in `inbox_page.py`, which
        is correct for the initial load / a connection switch (nothing valid to show
        yet) but was WRONG for a toggle's reload — it blanked every row's switch, not
        just the one being toggled, which is what a per-row `disabled` binding
        (`toggling_media_ids`) already exists to do on its own.
        """
        async with self:
            if show_loading:
                self.is_loading_candidates = True
            self.load_error = ""

        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            async with self:
                self.is_loading_candidates = False
            return

        try:
            items = await candidate_media(tenant_id=tenant_id, connection_id=resolved_connection)
        except UnknownInboxConnection:
            async with self:
                self.is_loading_candidates = False
                self.load_error = _UNKNOWN_CONNECTION
            return
        except Exception as exc:
            # Only the exception TYPE is logged — same posture as connections_state.py's
            # loader for infrastructure/Meta errors that may carry connection details.
            logger.error("candidate_media failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_candidates = False
                self.load_error = _LOAD_FAILED
            return

        async with self:
            # Guard against a connection switch that raced this load.
            if connection_id == self.selected_connection_id:
                self.candidates = items
                self.is_loading_candidates = False

    async def _load_reel_summaries_first_page(self, tenant_id: UUID, connection_id: str) -> None:
        """QUA-93: loads (or reloads) the FIRST page of Reel summary cards. Reuses
        `self.candidates` (already loaded by `_load_candidates`, called just before this
        in every caller) for opción A's thumbnail/caption/permalink enrichment — zero
        extra query, zero extra Meta call. Same connection-switch race guard as
        `_load_candidates`."""
        async with self:
            self.is_loading_reel_summaries = True
            self.reel_summaries_error = ""
            candidates = list(self.candidates)

        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            async with self:
                self.is_loading_reel_summaries = False
            return

        try:
            items, next_cursor, has_more = await asyncio.to_thread(
                reel_summaries_page,
                tenant_id=tenant_id,
                connection_id=resolved_connection,
                cursor=None,
                candidates=candidates,
            )
        except UnknownSentimentConnection:
            async with self:
                self.is_loading_reel_summaries = False
                self.reel_summaries_error = _UNKNOWN_CONNECTION
            return
        except Exception as exc:
            logger.error("reel_summaries_page failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_reel_summaries = False
                self.reel_summaries_error = _REEL_SUMMARIES_LOAD_FAILED
            return

        async with self:
            if connection_id == self.selected_connection_id:
                self.reel_summaries = items
                self.reel_summaries_cursor = next_cursor
                self.has_more_reels = has_more
                self.is_loading_reel_summaries = False

    async def _load_global_summary(self, tenant_id: UUID, connection_id: str) -> None:
        """QUA-93: the 5-number widget — one aggregate query, independent load/error
        state from every other section."""
        async with self:
            self.is_loading_global_summary = True
            self.global_summary_error = ""

        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            async with self:
                self.is_loading_global_summary = False
            return

        try:
            summary = await asyncio.to_thread(
                global_summary_vm, tenant_id=tenant_id, connection_id=resolved_connection
            )
        except UnknownSentimentConnection:
            async with self:
                self.is_loading_global_summary = False
                self.global_summary_error = _UNKNOWN_CONNECTION
            return
        except Exception as exc:
            logger.error("global_summary_vm failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_global_summary = False
                self.global_summary_error = _GLOBAL_SUMMARY_LOAD_FAILED
            return

        async with self:
            if connection_id == self.selected_connection_id:
                self.global_summary = summary
                self.is_loading_global_summary = False

    async def _load_thread_comments_first_page(self, tenant_id: UUID | None) -> None:
        """QUA-93: the FIRST page of the currently `selected_thread_id`'s comments,
        honoring `sentiment_filter`/`search_query`. Called by `select_reel`,
        `set_sentiment_filter`, `set_search_query` and `_refresh_after_write` — always
        resets the cursor, since a cursor is only valid under the filter/search that
        produced it.

        `tenant_id` is a PARAMETER, not resolved internally via `self.get_state(
        AuthState)` — same shape `_load_reel_summaries_first_page`/`_load_global_summary`
        already use, and for the same reason: it lets every CALLER resolve the tenant
        once (where a live `EventContext` is available) and this helper run standalone
        in tests, exactly like those two already do.
        """
        async with self:
            self.is_loading_thread_comments = True
            self.thread_comments_error = ""
            thread_id = self.selected_thread_id
            connection_id = self.selected_connection_id
            sentiment_filter = self.sentiment_filter
            intent_filter = self.intent_filter
            search_query = self.search_query

        resolved_connection = _try_uuid(connection_id)
        resolved_thread = _try_uuid(thread_id)

        if tenant_id is None or resolved_connection is None or resolved_thread is None:
            async with self:
                self.is_loading_thread_comments = False
                self.thread_comments_error = _NO_TENANT
            return

        try:
            items, next_cursor, has_more = await asyncio.to_thread(
                thread_comments_page,
                tenant_id=tenant_id,
                connection_id=resolved_connection,
                thread_id=resolved_thread,
                sentiment_filter=sentiment_filter,
                search=search_query,
                cursor=None,
                intent_filter=intent_filter,
            )
        except UnknownSentimentConnection:
            async with self:
                self.is_loading_thread_comments = False
                self.thread_comments_error = _UNKNOWN_CONNECTION
            return
        except Exception as exc:
            logger.error("thread_comments_page failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_thread_comments = False
                self.thread_comments_error = _THREAD_COMMENTS_LOAD_FAILED
            return

        async with self:
            # Guard against the operator navigating away or changing filter/search
            # again while this was in flight — same race-guard shape every loader in
            # this file already uses, just against four fields instead of one.
            if (
                thread_id == self.selected_thread_id
                and sentiment_filter == self.sentiment_filter
                and intent_filter == self.intent_filter
                and search_query == self.search_query
            ):
                self.thread_comments = items
                self.thread_comments_cursor = next_cursor
                self.has_more_thread_comments = has_more
                self.is_loading_thread_comments = False

    async def _refresh_after_write(self, tenant_id: UUID, connection_id: str) -> None:
        """QUA-93: what a successful sync (QUA-89) or analysis (QUA-21) pass refreshes —
        see the module docstring for the exact rule and its one accepted gap. Never
        re-runs analysis or sync itself."""
        await self._load_global_summary(tenant_id, connection_id)
        async with self:
            thread_id = self.selected_thread_id
        if thread_id:
            await self._load_thread_comments_first_page(tenant_id)
            await self._load_reel_summaries_first_page(tenant_id, connection_id)
            async with self:
                match = next((r for r in self.reel_summaries if r.thread_id == thread_id), None)
                if match is not None:
                    self.selected_reel_summary = match
        else:
            await self._load_reel_summaries_first_page(tenant_id, connection_id)

    @rx.event(background=True)
    async def load_screen(self):
        """Load the operator's eligible Instagram connections, then the last-2-weeks
        Reels for the first one — mirrors `ConnectionsState.load_connections`'s single
        combined loader rather than `PublishState`'s separate load+select, since this
        screen has nothing useful to show without a connection already selected."""
        async with self:
            self.is_loading_connections = True
            self.connections_error = ""

        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_TENANT
            return

        try:
            options = await asyncio.to_thread(instagram_connections, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("instagram_connections failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_CONNECTIONS
            return

        async with self:
            self.connections = options
            self.is_loading_connections = False
            if options and not self.selected_connection_id:
                self.selected_connection_id = options[0].id
            connection_id = self.selected_connection_id

        if connection_id:
            await self._load_candidates(tenant_id, connection_id)
            await self._load_reel_summaries_first_page(tenant_id, connection_id)
            await self._load_global_summary(tenant_id, connection_id)
            # QUA-22: the reply-drafts panel is a separate `RepliesState` (own module,
            # own lifecycle — see its docstring), triggered here via `yield` rather
            # than a second `on_load` list entry, same reason `AuthState.handle_login`
            # ends in one `yield rx.redirect(...)`: two independent on_load background
            # events are not guaranteed ordered, so a load that depends on
            # `selected_connection_id` being already set must chain from HERE, after
            # it is. Local import breaks the cycle (`replies_state.py` imports THIS
            # module for the connection id) — same technique `AuthState.logout` uses
            # for its own substate imports.
            from .replies_state import RepliesState  # noqa: PLC0415

            yield RepliesState.load_pending_drafts
            # Phase 1: one immediate pass instead of waiting for the first 5-minute tick.
            # `open` is cooldown-gated, so re-opening right after a pass costs no calls.
            yield InboxState.sync_comments("open")

    @rx.event(background=True)
    async def select_connection(self, connection_id: str):
        """Dev-only-adjacent: switch which connection's content is shown."""
        async with self:
            if not any(option.id == connection_id for option in self.connections):
                return
            self.selected_connection_id = connection_id
            self.candidates = []
            self.action_error = ""
            # QUA-93: reset every comments-related section — same "don't show the
            # previous connection's data while the new one loads" reasoning
            # `candidates`/`action_error` above already follow. Also closes any open
            # Reel detail: a Reel from a different connection cannot stay open.
            self.reel_summaries = []
            self.reel_summaries_error = ""
            self.reel_summaries_cursor = None
            self.has_more_reels = False
            self.global_summary = None
            self.global_summary_error = ""
            self.selected_thread_id = ""
            self.selected_reel_summary = None
            self.thread_comments = []
            self.thread_comments_error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            return
        await self._load_candidates(tenant_id, connection_id)
        await self._load_reel_summaries_first_page(tenant_id, connection_id)
        await self._load_global_summary(tenant_id, connection_id)
        # QUA-22: same reason `load_screen` chains into `RepliesState` at its own
        # tail — see that comment for why `yield`, not a second `on_load` entry.
        from .replies_state import RepliesState  # noqa: PLC0415

        yield RepliesState.load_pending_drafts
        # Switching account is opening the screen for that account.
        yield InboxState.sync_comments("open")

    @rx.event(background=True)
    async def toggle_monitored(
        self, external_media_id: str, monitored: bool
    ) -> rx.event.EventSpec | None:
        """Flip one Reel's monitoring toggle through the real B2 service, then ALWAYS
        reload the whole candidate list from the backend — see the module docstring for
        why this is never an optimistic local update."""
        async with self:
            if external_media_id in self.toggling_media_ids:
                return  # THIS row already has a toggle in flight; ignore a double-click
            self.toggling_media_ids.append(external_media_id)
            self.action_error = ""
            connection_id = self.selected_connection_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        started_at = time.monotonic()

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection = _try_uuid(connection_id)

        if tenant_id is None or resolved_connection is None:
            async with self:
                self.toggling_media_ids.remove(external_media_id)
                self.action_error = _NO_TENANT
            return

        toggled = False
        try:
            await toggle_monitoring(
                tenant_id=tenant_id,
                connection_id=resolved_connection,
                external_media_id=external_media_id,
                monitored=monitored,
            )
            toggled = True
        except MediaNotEligible as exc:
            async with self:
                self.action_error = _NOT_ELIGIBLE_BY_REASON.get(exc.reason, _NOT_ELIGIBLE)
        except UnknownInboxConnection:
            async with self:
                self.action_error = _UNKNOWN_CONNECTION
        except Exception as exc:
            logger.error("toggle_monitoring failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _TOGGLE_FAILED
        finally:
            # Pad OUT here, before clearing `toggling_media_ids` — this is what makes
            # OFF (a bare Postgres write) show the same card skeleton for the same
            # minimum duration as ON (a real Meta round-trip), see
            # `_MIN_TOGGLE_ANIMATION_SECONDS`'s docstring.
            remaining = _MIN_TOGGLE_ANIMATION_SECONDS - (time.monotonic() - started_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            async with self:
                self.toggling_media_ids.remove(external_media_id)

        # Reload from the backend regardless of outcome, so the switch reflects reality —
        # success, a refused toggle, and an infrastructure failure all leave the DB in
        # SOME real state, and only a fresh read shows what it actually is. show_loading
        # =False: this reload must NOT blank the other rows' switches — only THIS row's
        # own `toggling_media_ids` membership (already cleared above) controls its state.
        await self._load_candidates(tenant_id, connection_id, show_loading=False)

        # QUA-94: `reel_summaries` carries its own `is_monitored` now (the "Comentarios"
        # section's badge), a fact `_load_candidates` above does NOT refresh — that call
        # only ever touched `self.candidates`, the "Contenido de Instagram" list. Reuses
        # the SAME post-write re-read `sync_comments`/`analyze_sentiment` already call on
        # success (`_refresh_after_write`'s own docstring) rather than inventing a second
        # refresh mechanism — same "known, accepted gap" applies here too: a Reel past
        # page 1 of `reel_summaries` keeps a stale badge until the operator scrolls back.
        await self._refresh_after_write(tenant_id, connection_id)

        # Phase 1: a media just turned ON has never been synced — fetch its comments now
        # instead of at the next 5-minute tick. Turning monitoring OFF triggers nothing.
        if toggled and monitored:
            return InboxState.sync_comments("monitor")
        return None

    def _claim_sync(self, run_id: str) -> None:
        """Mark this tab as running `run_id`. Call inside `async with self`."""
        self.is_syncing = True
        self.sync_run_id = run_id
        self.sync_claimed_at = time.time()

    def _release_sync_claim(self, run_id: str) -> None:
        """Clear the claim only if it is still `run_id`'s. Call inside `async with self`."""
        if self.sync_run_id == run_id:
            self.is_syncing = False
            self.sync_run_id = ""

    def _sync_skipped(
        self, trigger: str, reason: str, *, run_id: str = "-"
    ) -> rx.event.EventSpec | None:
        """Log a skip; only a manual click hears about a pass already running (an
        automatic skip is routine and stays silent)."""
        logger.info("inbox.sync.skipped run=%s trigger=%s reason=%s", run_id, trigger, reason)
        if trigger == "manual" and reason in ("in_flight", "in_flight_elsewhere"):
            return rx.toast.info(_SYNC_ALREADY_RUNNING, duration=_RESULT_TOAST_DURATION_MS)
        return None

    @rx.event(background=True)
    async def sync_comments(self, trigger: str = "manual") -> rx.event.EventSpec | None:
        """The one trigger for `InboxService.sync_comments` (B2/QUA-89): the manual
        button, the 5-minute poll, opening the screen / switching account, and turning
        monitoring on all call it, each naming itself in `trigger` (`inbox_sync_policy`).
        Never touches `candidates`/`toggling_media_ids` ITSELF: a sync pass writes to
        `threads`/`messages` (and, for a media Meta confirms gone, an auto-unmonitor write
        the service makes on its own). Its visible effects are `sync_result`/`sync_error`,
        a refresh of the comments sections, and a toast.

        **Every run leaves one log line per outcome** (`inbox.sync.start` then exactly one
        of `done`/`failed`/`skipped`), keyed by a run id — ids and counts only, never
        comment text or a token.

        **Concurrency.** `is_syncing` is this tab's UI claim, persisted with the tab's state,
        so it can outlive the pass it stood for (a server restart mid-pass). It is NOT the
        lock: the backend's per-connection lease is (`qualify_api.inbox.sync_guard`). A
        leftover claim is cleared only when the backend says that run no longer holds its
        lease AND the claim is past a short grace window (`claim_is_stale`) — never by age
        alone. A manual click that finds a live pass gets a toast instead of silence.
        """
        trigger = normalize_trigger(trigger)
        run_id = uuid4().hex[:12]
        async with self:
            claimed_now = not self.is_syncing
            prior_run_id = self.sync_run_id
            prior_claimed_at = self.sync_claimed_at
            if claimed_now:
                self._claim_sync(run_id)
            connection_id = self.selected_connection_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection = _try_uuid(connection_id)

        if not claimed_now:
            run_alive = True  # conservative: unknown counts as still running
            if tenant_id is not None and resolved_connection is not None and prior_run_id:
                run_alive = await sync_still_running(
                    tenant_id=tenant_id, connection_id=resolved_connection, run_token=prior_run_id
                )
            if not claim_is_stale(
                run_id=prior_run_id,
                run_alive=run_alive,
                claimed_at=prior_claimed_at,
                now=time.time(),
            ):
                return self._sync_skipped(trigger, "in_flight")
            async with self:
                if self.sync_run_id != prior_run_id:
                    # Another event of this tab re-claimed in the meantime — it owns it now.
                    return self._sync_skipped(trigger, "in_flight")
                self._claim_sync(run_id)
            logger.info(
                "inbox.sync.stale_claim_released trigger=%s previous_run=%s", trigger, prior_run_id
            )

        if tenant_id is None or resolved_connection is None:
            async with self:
                self._release_sync_claim(run_id)
                self.sync_error = _SESSION_EXPIRED if tenant_id is None else _NO_CONNECTION_SELECTED
            return self._sync_skipped(
                trigger, "no_session" if tenant_id is None else "no_connection"
            )

        if trigger != "manual":
            since_last = await seconds_since_last_sync(
                tenant_id=tenant_id, connection_id=resolved_connection
            )
            if skip_for_cooldown(trigger, since_last):
                async with self:
                    self._release_sync_claim(run_id)
                return self._sync_skipped(trigger, "cooldown")

        async with self:
            self.sync_error = ""
            self.sync_result = None
        logger.info(
            "inbox.sync.start run=%s trigger=%s tenant=%s connection=%s",
            run_id,
            trigger,
            tenant_id,
            resolved_connection,
        )
        started = time.monotonic()
        try:
            result = await sync_now(
                tenant_id=tenant_id, connection_id=resolved_connection, run_token=run_id
            )
        except SyncAlreadyRunning:
            # Another tab, user or process holds this connection's lease right now.
            return self._sync_skipped(trigger, "in_flight_elsewhere", run_id=run_id)
        except Exception as exc:
            logger.info(
                "inbox.sync.failed run=%s trigger=%s error=%s ms=%d",
                run_id,
                trigger,
                type(exc).__name__,
                (time.monotonic() - started) * 1000,
            )
            async with self:
                self.sync_error = _sync_error_message(exc)
            return None
        else:
            logger.info(
                "inbox.sync.done run=%s trigger=%s media=%d new=%d deleted=%d "
                "missing_media=%d expired=%d meta_ok=%d meta_failed=%d meta_deferred=%d "
                "truncated=%s ms=%d",
                run_id,
                trigger,
                result.media_checked,
                result.new_comments,
                result.deleted_comments,
                len(result.skipped_missing_media),
                result.expired_skipped,
                result.metadata_backfilled,
                result.metadata_failed,
                result.metadata_deferred,
                result.truncated,
                (time.monotonic() - started) * 1000,
            )
            async with self:
                self.sync_result = result
        finally:
            async with self:
                self._release_sync_claim(run_id)

        # QUA-93: refresh — reached ONLY on a successful sync. Every failure branch
        # above `return`s before this point (the `finally` still ran either way,
        # resetting `is_syncing`); this line is therefore never executed unless
        # `sync_now` returned normally. A pure re-read via `_refresh_after_write` — this
        # does NOT run sentiment analysis (QUA-21 stays manual-only, unchanged) and does
        # not modify `sync_comments`'s own logic above it in any way; it is purely
        # additive.
        await self._refresh_after_write(tenant_id, connection_id)

        # The result toast belongs to this screen: a pass that finishes after the person
        # already left /inbox (logged out, opened another page) stays silent instead of
        # popping up there. The sync itself is unaffected — it already happened.
        async with self:
            still_on_inbox = is_inbox_path(self.router.url.path)
        if not still_on_inbox:
            return None

        # A plain `return` of an `EventSpec` from an async (non-generator) background
        # handler is dispatched exactly like an event chain — no `yield` needed, and this
        # function stays a plain coroutine (load-bearing: `sync_comments.fn` is called
        # directly and awaited in tests — see the double-click guard test above).
        message = sync_result_message(result)
        return rx.toast.success(message, duration=_RESULT_TOAST_DURATION_MS)

    @rx.event(background=True)
    async def analyze_sentiment(self) -> rx.event.EventSpec | None:
        """The "Analizar sentimiento" button (QUA-92) — the ONLY trigger for QUA-21's
        analysis pass this screen exposes. Deliberately independent of `sync_comments`
        in both directions: never called FROM `sync_comments` (QUA-21 stays manual-only,
        unchanged by QUA-89's polling) and never calls `sync_now` itself. Same
        double-click guard / `finally`-based reset shape as `sync_comments` above, over
        `inbox_provider.analyze_sentiment_now` — the same seam `POST /api/sentiment/
        analyze` wraps, never a second analysis engine.
        """
        async with self:
            if self.is_analyzing:
                return  # an analysis pass is already in flight; ignore a rapid double-click
            self.is_analyzing = True
            self.analyze_error = ""
            self.analyze_result = None
            connection_id = self.selected_connection_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection = _try_uuid(connection_id)

        if tenant_id is None or resolved_connection is None:
            async with self:
                self.is_analyzing = False
                self.analyze_error = (
                    _SESSION_EXPIRED if tenant_id is None else _NO_CONNECTION_SELECTED
                )
            return

        try:
            result = await analyze_sentiment_now(
                tenant_id=tenant_id, connection_id=resolved_connection
            )
        except UnknownSentimentConnection:
            async with self:
                self.analyze_error = _UNKNOWN_CONNECTION
            return
        except SentimentModelUnavailable:
            async with self:
                self.analyze_error = _ANALYZE_UNAVAILABLE
            return
        except Exception as exc:
            # Only the exception TYPE is logged — same posture as every other handler in
            # this file for infrastructure errors.
            logger.error("analyze_sentiment_now failed: %s", type(exc).__name__)
            async with self:
                self.analyze_error = _ANALYZE_FAILED
            return
        else:
            async with self:
                self.analyze_result = result
        finally:
            async with self:
                self.is_analyzing = False

        # QUA-93: refresh so "Sin analizar" flips to POS/NEG/NEU — reached ONLY on a
        # successful analysis, same "after the whole try/except/else/finally block"
        # structure `sync_comments` already established for its own success-only
        # refresh above.
        await self._refresh_after_write(tenant_id, connection_id)

        # Same plain-`return`-of-an-`EventSpec` shape `sync_comments` uses above, and for
        # the same reason (`analyze_sentiment.fn` is called directly and awaited in
        # tests — this must stay a plain coroutine, never an async generator).
        # m-24842988: «Ordenar por prioridad» runs this AND the intent pass on one
        # click; only the intent result speaks, so success here is silent. Errors still
        # show (`analyze_error`, above).
        return None

    @rx.event(background=True)
    async def analyze_intent(self) -> rx.event.EventSpec | None:
        """The "Analizar intención" button (m-24789644): one pass of
        `inbox_provider.analyze_intent_now` over the connection's pending comments. Same
        double-click guard, `finally` reset, success-only refresh and toast as
        `analyze_sentiment`; never triggers sync or sentiment, and neither of them
        triggers it."""
        async with self:
            if self.is_analyzing_intent:
                return
            self.is_analyzing_intent = True
            self.analyze_intent_error = ""
            self.analyze_intent_result = None
            connection_id = self.selected_connection_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection = _try_uuid(connection_id)

        if tenant_id is None or resolved_connection is None:
            async with self:
                self.is_analyzing_intent = False
                self.analyze_intent_error = (
                    _SESSION_EXPIRED if tenant_id is None else _NO_CONNECTION_SELECTED
                )
            return

        try:
            result = await analyze_intent_now(
                tenant_id=tenant_id, connection_id=resolved_connection
            )
        except UnknownIntentConnection:
            async with self:
                self.analyze_intent_error = _UNKNOWN_CONNECTION
            return
        except IntentModelUnavailable:
            async with self:
                self.analyze_intent_error = _ANALYZE_INTENT_UNAVAILABLE
            return
        except Exception as exc:
            logger.error("analyze_intent_now failed: %s", type(exc).__name__)
            async with self:
                self.analyze_intent_error = _ANALYZE_INTENT_FAILED
            return
        else:
            async with self:
                self.analyze_intent_result = result
        finally:
            async with self:
                self.is_analyzing_intent = False

        await self._refresh_after_write(tenant_id, connection_id)
        return rx.toast.success(_intent_result_message(result), duration=_RESULT_TOAST_DURATION_MS)

    @rx.event(background=True)
    async def reply_by_dm(self, message_id: str) -> rx.event.EventSpec | None:
        """«Responder por DM» (m-24789646): open (or reuse) the comment's query, with
        its draft, and land on it in Conversaciones. Only a comment the page has loaded
        is accepted; a comment that cannot be continued in private says why."""
        async with self:
            if self.replying_dm_id:
                return None
            if message_id not in {c.message_id for c in self.thread_comments}:
                return None  # arrived over the wire; refuse an id the page does not hold
            self.replying_dm_id = message_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        resolved = _try_uuid(message_id)
        try:
            if tenant_id is None or resolved is None:
                return rx.toast.error(_SESSION_EXPIRED, duration=_RESULT_TOAST_DURATION_MS)
            try:
                followup_id = await reply_by_dm(tenant_id=tenant_id, message_id=resolved)
            except OriginNotSupported as exc:
                return rx.toast.warning(exc.reason, duration=_RESULT_TOAST_DURATION_MS)
            except UnknownOrigin:
                return rx.toast.warning(_REPLY_BY_DM_GONE, duration=_RESULT_TOAST_DURATION_MS)
            except Exception as exc:  # noqa: BLE001
                logger.error("reply_by_dm failed: %s", type(exc).__name__)
                return rx.toast.error(_REPLY_BY_DM_FAILED, duration=_RESULT_TOAST_DURATION_MS)
            # m-24842990: the query card lives in «Por responder» › Quieren comprar.
            return rx.redirect(f"/responder?tab=comprar&consulta={followup_id}")
        finally:
            async with self:
                self.replying_dm_id = ""

    @rx.event(background=True)
    async def select_reel(self, thread_id: str) -> None:
        """QUA-93: enter the Reel detail view. Always resets to a clean first page —
        filter "Todos", no search, no cursor — a detail view never opens mid-scroll of
        a previous Reel's state."""
        async with self:
            self.selected_thread_id = thread_id
            self.selected_reel_summary = next(
                (r for r in self.reel_summaries if r.thread_id == thread_id), None
            )
            self.thread_comments = []
            self.thread_comments_error = ""
            self.thread_comments_cursor = None
            self.has_more_thread_comments = False
            self.sentiment_filter = FILTER_ALL
            self.intent_filter = FILTER_ALL
            self.search_query = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        await self._load_thread_comments_first_page(tenant_uuid(session_tenant_id))

    @rx.event
    def back_to_reel_list(self) -> None:
        """QUA-93: "← Volver" — synchronous, no reload. The AC's explicit requirement:
        the Reel list already in state stays exactly as it was, no wasted round-trip."""
        self.selected_thread_id = ""
        self.selected_reel_summary = None

    @rx.event(background=True)
    async def set_sentiment_filter(self, value: str) -> None:
        """QUA-93: the filter select (Todos/Positivos/Neutros/Negativos/Sin analizar).
        A no-op if unchanged (avoids a wasted reload on a re-selected value); otherwise
        resets to a fresh first page under the new filter."""
        async with self:
            if value == self.sentiment_filter:
                return
            self.sentiment_filter = value
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        await self._load_thread_comments_first_page(tenant_uuid(session_tenant_id))

    @rx.event(background=True)
    async def set_intent_filter(self, value: str) -> None:
        """m-24789644: the intent filter (Todas / Requiere atención comercial). Same
        no-op-if-unchanged + fresh-first-page shape as `set_sentiment_filter`."""
        async with self:
            if value == self.intent_filter:
                return
            self.intent_filter = value
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        await self._load_thread_comments_first_page(tenant_uuid(session_tenant_id))

    @rx.event(background=True)
    async def set_search_query(self, value: str) -> None:
        """QUA-93: the search box. Fires on every keystroke (`on_change`) rather than on
        blur/Enter — deliberately simple: `list_comments_for_thread` is already bounded
        to one Reel's rows (validated at ~1ms even at 100 comments/Reel), so a query per
        keystroke is cheap. Debouncing is easy to add later if that stops being true; it
        is not built preemptively here."""
        async with self:
            if value == self.search_query:
                return
            self.search_query = value
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        await self._load_thread_comments_first_page(tenant_uuid(session_tenant_id))

    @rx.event(background=True)
    async def load_more_reels(self) -> None:
        """QUA-93: "Cargar más Reels" — appends the next page, never re-fetches what is
        already shown. `is_loading_more_reels` is separate from `is_loading_reel_
        summaries` so this shows its own small spinner without blanking the list already
        on screen (same reasoning `toggling_media_ids` keeps per-row, not screen-wide)."""
        async with self:
            if self.is_loading_more_reels or not self.has_more_reels:
                return
            self.is_loading_more_reels = True
            connection_id = self.selected_connection_id
            cursor = self.reel_summaries_cursor
            candidates = list(self.candidates)
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection = _try_uuid(connection_id)
        if tenant_id is None or resolved_connection is None:
            async with self:
                self.is_loading_more_reels = False
            return

        try:
            items, next_cursor, has_more = await asyncio.to_thread(
                reel_summaries_page,
                tenant_id=tenant_id,
                connection_id=resolved_connection,
                cursor=cursor,
                candidates=candidates,
            )
        except Exception as exc:
            logger.error("load_more_reels failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_more_reels = False
                self.reel_summaries_error = _REEL_SUMMARIES_LOAD_FAILED
            return

        async with self:
            if connection_id == self.selected_connection_id:
                self.reel_summaries.extend(items)
                self.reel_summaries_cursor = next_cursor
                self.has_more_reels = has_more
            self.is_loading_more_reels = False

    @rx.event(background=True)
    async def load_more_thread_comments(self) -> None:
        """QUA-93: "Cargar más comentarios" — appends the next page of the OPEN Reel's
        comments under the current filter/search, never re-fetches what is already
        shown."""
        async with self:
            if self.is_loading_more_thread_comments or not self.has_more_thread_comments:
                return
            self.is_loading_more_thread_comments = True
            thread_id = self.selected_thread_id
            connection_id = self.selected_connection_id
            sentiment_filter = self.sentiment_filter
            intent_filter = self.intent_filter
            search_query = self.search_query
            cursor = self.thread_comments_cursor
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection = _try_uuid(connection_id)
        resolved_thread = _try_uuid(thread_id)
        if tenant_id is None or resolved_connection is None or resolved_thread is None:
            async with self:
                self.is_loading_more_thread_comments = False
            return

        try:
            items, next_cursor, has_more = await asyncio.to_thread(
                thread_comments_page,
                tenant_id=tenant_id,
                connection_id=resolved_connection,
                thread_id=resolved_thread,
                sentiment_filter=sentiment_filter,
                search=search_query,
                cursor=cursor,
                intent_filter=intent_filter,
            )
        except Exception as exc:
            logger.error("load_more_thread_comments failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_more_thread_comments = False
                self.thread_comments_error = _THREAD_COMMENTS_LOAD_FAILED
            return

        async with self:
            if (
                thread_id == self.selected_thread_id
                and sentiment_filter == self.sentiment_filter
                and intent_filter == self.intent_filter
                and search_query == self.search_query
            ):
                self.thread_comments.extend(items)
                self.thread_comments_cursor = next_cursor
                self.has_more_thread_comments = has_more
            self.is_loading_more_thread_comments = False


def _count(n: int, one: str, many: str) -> str:
    """«1 comentario» / «3 comentarios» — the toasts never say «1 comentarios»."""
    return f"{n} {one if n == 1 else many}"


def _intent_result_message(result: IntentAnalysisSummaryVM) -> str:
    """The «Ordenar por prioridad» toast (intent half). Unclassified comments stay
    pending, so the message says the next click retries them rather than counting them
    as done."""
    if result.comments_checked == 0:
        return "No hay comentarios nuevos para ordenar."
    message = f"Listo: ordenamos {_count(result.new_results, 'comentario', 'comentarios')}."
    if result.unclassified:
        left = _count(result.unclassified, "quedó sin revisar", "quedaron sin revisar")
        message += f" {left}: lo intentamos de nuevo la próxima vez."
    if result.followups_opened:
        buyers = _count(result.followups_opened, "quiere comprar", "quieren comprar")
        message += f" {buyers}: te esperan en «Conversaciones»."
    return message


def sync_result_message(result: SyncSummaryVM) -> str:
    """The toast after a successful comment search (QUA-89), in the owner's words."""
    checked = _count(result.media_checked, "publicación", "publicaciones")
    new = _count(result.new_comments, "comentario nuevo", "comentarios nuevos")
    message = f"Revisamos {checked}: {new}."
    if result.skipped_missing_media:
        # Bug fix (2026-09-01): a Reel deleted at the source is real, informative
        # partial-success context — never silent, never the error callout.
        gone = _count(
            len(result.skipped_missing_media),
            "publicación ya no está en Instagram",
            "publicaciones ya no están en Instagram",
        )
        message += f" {gone}: dejamos de buscar sus comentarios."
    if result.deleted_comments:
        # QUA-101: comments deleted on Instagram — still a success.
        deleted = _count(result.deleted_comments, "comentario se borró", "comentarios se borraron")
        message += f" {deleted} en Instagram y ya no se muestran."
    if result.truncated:
        message += " Faltaron algunas: busca de nuevo en unos minutos para completarlas."
    return message


def _try_uuid(value: str) -> UUID | None:
    """Shared by every handler in this file that resolves a Reflex string field to a
    UUID before calling the backend — a malformed/empty string is a "nothing selected"
    state, never a crash."""
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _sync_error_message(exc: Exception) -> str:
    """One message per failure type — "Esa cuenta ya no está disponible" only ever means
    the connection is not visible to this tenant (B8)."""
    if isinstance(exc, UnknownInboxConnection):
        return _UNKNOWN_CONNECTION
    if isinstance(exc, InboxConnectionInactive):
        return _CONNECTION_INACTIVE
    if isinstance(exc, CommentsAuthExpired):
        return _CONNECTION_AUTH_EXPIRED
    if isinstance(exc, CommentsPermissionMissing):
        return _COMMENTS_PERMISSION_MISSING
    if isinstance(exc, SyncBudgetExhausted):
        return _SYNC_BUDGET_EXHAUSTED
    if isinstance(exc, CommentsReadError):
        return _SYNC_META_FAILED
    return _SYNC_FAILED
