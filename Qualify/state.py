"""State for the Dashboard de Menciones (QUA-49, paginated and auto-refreshed by QUA-152).

Reads through `.mentions_provider` (an in-process seam over `qualify_api.mentions.
composition`), same pattern `inbox_state.py` establishes: `AuthState.session_tenant_id` ->
`asyncio.to_thread` -> a provider function.

## Paging over ALL stored mentions (QUA-152)

The table shows 12 mentions per page, read from the backend — never a capped slice
filtered in the browser. Totals and counters come from the backend too, over the whole
filtered set. Every page of one listing is read under one snapshot (`as_of`); the rules
for paging and the refresh tick live in `.mentions_paging` (pure, tested there), and this
class only applies them:

- changing a filter or the search starts a new snapshot on page 1;
- changing page keeps the snapshot, so no row repeats or goes missing — except going back
  to page 1, which takes a new snapshot so what arrived meanwhile shows at once;
- the 45-second tick re-reads the current page (fresh sentiment states, no skeleton):
  under the SAME snapshot on a later page; on page 1 under a NEW one, with the period's
  window recomputed, so new mentions appear with no notice and no "Nueva" mark — a
  mention is not a message (QUA-152, 2026-10-15). A failed tick keeps the rows and says
  so softly; the next tick runs as usual.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import reflex as rx
from qualify_api.mentions.repository import MentionQuery

from .auth_state import AuthState
from .mentions_paging import (
    ALL_ACCOUNTS,
    ALL_HISTORY,
    ALL_ORIGINS,
    ALL_SENTIMENTS,
    DEFAULT_PERIOD,
    NEW_MENTIONS_NOTICE,
    ORIGIN_OPTIONS,
    PERIOD_OPTIONS,
    REFRESH_FAILED_NOTICE,
    REFRESH_STARTED_TOAST,
    SENTIMENT_OPTIONS,
    SENTIMENT_PARAM,
    THROTTLED_NOTICE,
    USAGE_PAUSED_NOTICE,
    decide_tick,
    more_filters_count,
    new_mentions_arrived,
    refresh_outcome,
    refresh_still_running,
    sentiment_from_param,
    stopped_outcome,
    tick_takes_new_snapshot,
    toggle_sentiment,
)
from .mentions_paging import page_items as _page_items
from .mentions_provider import (
    MentionPageVM,
    list_total_now,
    load_page,
    refresh_content,
    refresh_scope,
)
from .mentions_provider import MentionVM as MentionRow
from .mentions_provider import account_options as _account_options
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

__all__ = ["DashboardState", "MentionRow"]

_NO_TENANT = "Tu sesión se cerró. Vuelve a entrar para ver tus menciones."
_LOAD_ERROR = "No pudimos traer tus menciones. Recarga la página en unos minutos."
_REFRESH_ERROR = (
    "No pudimos actualizar la lista. Te mostramos lo último que cargamos; "
    "vuelve a intentarlo en unos minutos."
)


def _utc_stamp() -> str:
    """'2026-10-13T22:53:12Z' — what `rx.moment` parses reliably. A full `isoformat()`
    (microseconds + '+00:00') was read in the browser as local midnight, so the "Actualizado
    hace X" indicator said "hace 19 horas" right after a load (found in QUA-152's visual
    validation)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window_start(period: str) -> str:
    """The view window's start for `period` (ISO-8601), '' for the whole history. Fixed
    when a listing starts, so every page of one snapshot uses the same window."""
    days = PERIOD_OPTIONS.get(period)
    return "" if days is None else (datetime.now(UTC) - timedelta(days=days)).isoformat()


class DashboardState(rx.State):
    """State for the mentions dashboard."""

    mentions: list[MentionRow] = []
    is_loading_mentions: bool = False
    mentions_error: str = ""
    refresh_error: str = ""

    page: int = 1
    total_pages: int = 1
    pages_label: str = ""
    # What the table shows: the fully filtered set.
    filtered_total: int = 0
    # The summary cards: the scope only (account + period) — never moved by a search.
    total_mentions: int = 0
    positive_count: int = 0
    neutral_count: int = 0
    negative_count: int = 0
    pending_count: int = 0
    no_text_count: int = 0
    error_count: int = 0

    # The snapshot every page of this listing is read under (ISO-8601), and how many
    # mentions it held. A tick that re-reads a different total announces the change.
    as_of: str = ""
    snapshot_total: int = 0
    list_changed: bool = False
    # A later page's tick found more mentions in the scope than its snapshot holds:
    # «Llegaron menciones nuevas.» + «Verlas» (RESULTADOS-1, QUA-152).
    new_mentions_waiting: bool = False
    last_updated: str = ""
    # True for the whole "Actualizar menciones" run: the visible page first, then the
    # rest of the scope (account + period) in the background.
    is_refreshing: bool = False
    # One short on-page sentence with what to do about a run that left something pending;
    # '' otherwise. The run's flow (started, finished) is told by toasts, never here.
    refresh_notice: str = ""
    # Bumped by every new run and when opening the screen unlocks a dead one: a run whose
    # token is no longer current stops and never writes, so it cannot overwrite a newer one.
    refresh_run: int = 0
    # The token whose background step has actually started, and when the run was clicked
    # (epoch seconds) — what tells a live run from one that never started or died.
    refresh_alive_run: int = 0
    refresh_started_at: float = 0.0

    account_filter: str = ALL_ACCOUNTS
    # The view window: opens on the last 14 days (nothing is deleted; "Todo el historial"
    # shows everything). `since` is its start, fixed per listing.
    period_filter: str = DEFAULT_PERIOD
    since: str = ""
    origin_filter: str = ALL_ORIGINS
    sentiment_filter: str = ALL_SENTIMENTS
    search_query: str = ""
    # '@username' -> connection id, for the account filter.
    accounts: dict[str, str] = {}
    # RESULTADOS-1 (m-24843000): the mentions opened with «Ver más», and the phone's
    # «Más filtros» panel.
    expanded_ids: list[str] = []
    filters_open: bool = False

    # ----------------------------------------------------------------- derived

    @rx.var
    def account_options(self) -> list[str]:
        return [ALL_ACCOUNTS, *sorted(self.accounts)]

    @rx.var
    def show_account_filter(self) -> bool:
        """Only useful with more than one connected account — the common case has one."""
        return len(self.accounts) > 1

    @rx.var
    def more_filters_label(self) -> str:
        """«Más filtros», with how many are in use: a filter kept behind the button on
        the phone is never invisible."""
        used = more_filters_count(
            account=self.account_filter,
            origin=self.origin_filter,
            sentiment=self.sentiment_filter,
        )
        return f"Más filtros ({used})" if used else "Más filtros"

    @rx.var
    def new_mentions_notice(self) -> str:
        return NEW_MENTIONS_NOTICE if self.new_mentions_waiting else ""

    @rx.var
    def is_windowed(self) -> bool:
        return self.period_filter != ALL_HISTORY

    @rx.var
    def page_items(self) -> list[str]:
        return _page_items(self.page, self.total_pages)

    @rx.var
    def has_prev(self) -> bool:
        return self.page > 1

    @rx.var
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @rx.var
    def has_filters(self) -> bool:
        return (
            self.account_filter != ALL_ACCOUNTS
            or self.origin_filter != ALL_ORIGINS
            or self.sentiment_filter != ALL_SENTIMENTS
            or bool(self.search_query.strip())
        )

    @rx.var
    def show_empty_state(self) -> bool:
        """No mention stored at all — never overlapping the skeleton or the error."""
        return (
            not self.is_loading_mentions
            and not self.mentions_error
            and self.filtered_total == 0
            and not self.has_filters
        )

    @rx.var
    def show_no_results(self) -> bool:
        """Mentions exist, but none match the filters."""
        return (
            not self.is_loading_mentions
            and not self.mentions_error
            and self.filtered_total == 0
            and self.has_filters
        )

    @rx.var
    def states_hint(self) -> str:
        """What is not (yet) a polarity, under the total — never folded into one, and in
        the same words as each row's reason (N1, UX review): «por revisar», «sin texto para
        leer», «que no pudimos leer». Neither of the last two is a sentiment (founder review
        2026-10-13)."""
        parts = []
        if self.pending_count:
            parts.append(f"{self.pending_count} por revisar")
        if self.no_text_count:
            parts.append(f"{self.no_text_count} sin texto para leer")
        if self.error_count:
            parts.append(f"{self.error_count} que no pudimos leer")
        return " · ".join(parts)

    # ---------------------------------------------------------------- helpers

    def _query(self, since: str | None = None) -> MentionQuery:
        """The listing's query; `since` overrides the stored window start (ISO-8601)."""
        since = self.since if since is None else since
        return MentionQuery(
            connection_id=(
                UUID(self.accounts[self.account_filter])
                if self.account_filter in self.accounts
                else None
            ),
            origin=ORIGIN_OPTIONS.get(self.origin_filter),
            sentiment_state=SENTIMENT_OPTIONS.get(self.sentiment_filter),
            search=self.search_query,
            since=datetime.fromisoformat(since) if since else None,
        )

    def _scope_query(self) -> MentionQuery:
        """What "Actualizar menciones" re-reads: the account and period being viewed —
        every page of them. Origin, sentiment and search never narrow a refresh."""
        return MentionQuery(
            connection_id=(
                UUID(self.accounts[self.account_filter])
                if self.account_filter in self.accounts
                else None
            ),
            since=datetime.fromisoformat(self.since) if self.since else None,
        )

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id)

    def _apply_page(self, vm: MentionPageVM, *, new_snapshot: bool) -> None:
        self.mentions = vm.rows
        self.page = vm.page
        self.total_pages = vm.total_pages
        self.pages_label = vm.pages_label
        self.filtered_total = vm.filtered_total
        counts = vm.summary
        self.total_mentions = counts.total
        self.positive_count = counts.positive
        self.neutral_count = counts.neutral
        self.negative_count = counts.negative
        self.pending_count = counts.pending
        self.no_text_count = counts.no_text
        self.error_count = counts.error
        if new_snapshot:
            self.as_of = vm.as_of
            self.snapshot_total = vm.filtered_total
            self.list_changed = False
            self.new_mentions_waiting = False
        self.last_updated = _utc_stamp()
        self.refresh_error = ""

    async def _read(self, *, page: int, new_snapshot: bool) -> None:
        """Read one page — under a new snapshot, or the current one — and apply it."""
        tenant_id = await self._tenant()
        if tenant_id is None:
            self.mentions_error = _NO_TENANT
            return
        if new_snapshot:
            self.since = _window_start(self.period_filter)
        try:
            vm = await asyncio.to_thread(
                load_page,
                tenant_id,
                query=self._query(),
                page=page,
                as_of="" if new_snapshot else self.as_of,
            )
        except Exception as exc:  # noqa: BLE001 — shown as a callout, logged by type only
            logger.error("mentions_provider.load_page failed: %s", type(exc).__name__)
            self.mentions_error = _LOAD_ERROR
            return
        self.mentions_error = ""
        self._apply_page(vm, new_snapshot=new_snapshot)

    async def _restart(self) -> None:
        """A new listing: page 1 under a new snapshot. Keeps the rows on screen while it
        reads (no skeleton) — a filter change must not flash."""
        if not self.is_refreshing:
            self.refresh_notice = ""  # it described another scope
        await self._read(page=1, new_snapshot=True)

    # ----------------------------------------------------------------- events

    @rx.event
    async def load_mentions(self) -> AsyncIterator[None]:
        """Opening the screen: the accounts for the filter, then page 1."""
        self.is_loading_mentions = True
        self.mentions_error = ""
        yield
        if refresh_still_running(
            is_refreshing=self.is_refreshing,
            alive_run=self.refresh_alive_run,
            current_run=self.refresh_run,
            started_at=self.refresh_started_at,
            now=time.time(),
        ):
            # A live run keeps the button (it shows as loading); it reports when it finishes.
            pass
        else:
            # A run that never started (tab closed after the click) or died (restart) must
            # not leave the button locked; bumping the token stops it if it ever resumes.
            self.is_refreshing = False
            self.refresh_run += 1
            self.refresh_notice = ""
        tenant_id = await self._tenant()
        if tenant_id is None:
            self.is_loading_mentions = False
            self.mentions_error = _NO_TENANT
            return
        try:
            self.accounts = await asyncio.to_thread(_account_options, tenant_id)
        except Exception as exc:  # noqa: BLE001 — the filter degrades to "all accounts"
            logger.error("mentions_provider.account_options failed: %s", type(exc).__name__)
            self.accounts = {}
        if self.account_filter not in self.accounts:
            self.account_filter = ALL_ACCOUNTS
        # `?sentimiento=negativas` (N11): a figure elsewhere opens the list it counts.
        wanted = self.router.url.query_parameters.get(SENTIMENT_PARAM)
        if wanted is not None:
            self.sentiment_filter = sentiment_from_param(str(wanted))
        await self._restart()
        self.is_loading_mentions = False

    @rx.event
    async def set_account_filter(self, value: str) -> None:
        self.account_filter = value
        await self._restart()

    @rx.event
    async def set_period_filter(self, value: str) -> None:
        self.period_filter = value if value in PERIOD_OPTIONS else DEFAULT_PERIOD
        await self._restart()

    @rx.event
    async def set_origin_filter(self, value: str) -> None:
        self.origin_filter = value
        await self._restart()

    @rx.event
    async def set_sentiment_filter(self, value: str) -> None:
        self.sentiment_filter = value
        await self._restart()

    @rx.event
    async def pick_sentiment(self, label: str) -> None:
        """A summary card was tapped: show only that sentiment, or all again when it
        was already the one shown (the «Total» card always shows all)."""
        self.sentiment_filter = toggle_sentiment(self.sentiment_filter, label)
        await self._restart()

    @rx.event
    def toggle_expanded(self, mention_id: str) -> None:
        """«Ver más» / «Ver menos» on one mention."""
        if mention_id in self.expanded_ids:
            self.expanded_ids = [m for m in self.expanded_ids if m != mention_id]
        else:
            self.expanded_ids = [*self.expanded_ids, mention_id]

    @rx.event
    def set_filters_open(self, value: bool) -> None:
        self.filters_open = value

    @rx.event
    async def clear_more_filters(self) -> None:
        """«Quitar filtros» in the phone's panel: back to every account, origin and
        sentiment; the period stays (it is the one filter always on screen)."""
        self.account_filter = ALL_ACCOUNTS
        self.origin_filter = ALL_ORIGINS
        self.sentiment_filter = ALL_SENTIMENTS
        await self._restart()

    @rx.event
    async def set_search_query(self, value: str) -> None:
        self.search_query = value
        await self._restart()

    @rx.event
    async def go_to_page(self, page: str) -> None:
        """Same snapshot, another page: no row can repeat or be skipped. Page 1 takes a
        new snapshot: what arrived meanwhile shows at once."""
        if not page.isdigit():
            return  # the "…" gap is not a page
        await self._read(page=int(page), new_snapshot=int(page) == 1)

    @rx.event
    async def prev_page(self) -> None:
        if self.page > 1:
            await self._read(page=self.page - 1, new_snapshot=self.page - 1 == 1)

    @rx.event
    async def next_page(self) -> None:
        if self.page < self.total_pages:
            await self._read(page=self.page + 1, new_snapshot=False)

    @rx.event
    def refresh_now(self) -> list[rx.event.EventSpec] | None:
        """ "Actualizar menciones": re-read from the network every mention of the scope
        (account + period, all pages) and store what changed. This handler only marks the
        run as started; the work happens in `refresh_scope`, in the background, so the
        network reads never hold this session — filters, paging and the tick stay
        responsive however slowly the network answers. Only this click calls the network —
        the 45 s tick reads Postgres alone. That it started is a toast; the button shows
        it as loading until the run reports."""
        if self.is_refreshing:
            return None
        self.is_refreshing = True
        self.refresh_run += 1
        self.refresh_started_at = time.time()
        self.refresh_notice = ""
        return [
            rx.toast.info(REFRESH_STARTED_TOAST),
            DashboardState.refresh_scope(self.refresh_run),
        ]

    @rx.event(background=True)
    async def refresh_scope(self, run: int) -> AsyncIterator[rx.event.EventSpec]:
        """The "Actualizar menciones" run. The VISIBLE page first, so what the person is
        looking at updates right away; then one bounded run over the scope; then the
        outcome: always a toast (done, or a warning when something is pending), plus one
        short on-page notice with what to do when something is pending. A run superseded by
        a newer one, or by reopening the screen, never writes its outcome over theirs."""
        report = None
        visible = None
        stopped_notice = ""
        try:
            async with self:
                if self.refresh_run != run:
                    return  # superseded before it even started
                self.refresh_alive_run = run
                tenant_id = await self._tenant()
                visible_ids = [row.id for row in self.mentions]
                scope = self._scope_query()
            if tenant_id is None:
                logger.warning("mentions refresh: no tenant for this session")
                stopped_notice = _NO_TENANT
            else:
                if visible_ids:
                    try:
                        visible = await refresh_content(tenant_id, visible_ids)
                    except Exception as exc:  # noqa: BLE001 — still reload and go on
                        logger.warning("mentions visible refresh failed: %s", type(exc).__name__)
                async with self:
                    if self.refresh_run != run:
                        return
                    await self._read(page=self.page, new_snapshot=True)
                if visible is not None and visible.rate_limited:
                    # Throttled already: asking for the rest of the scope now would only
                    # spend more of the account's budget.
                    stopped_notice = THROTTLED_NOTICE
                elif visible is not None and visible.usage_paused:
                    stopped_notice = USAGE_PAUSED_NOTICE
                else:
                    async with self:
                        superseded = self.refresh_run != run
                    if superseded:
                        return  # never spend the scope's reads for a run nobody will see
                    report = await refresh_scope(tenant_id, scope=scope)
        except Exception as exc:  # noqa: BLE001 — reported below as not completed
            logger.warning("mentions refresh failed: %s", type(exc).__name__)
        async with self:
            if self.refresh_run != run:
                return  # superseded: the newer run owns the button and the notice
            self.is_refreshing = False
            # A mention whose content was deleted left the scope: it is neither current nor
            # pending, only announced — also when the run stops early. The visible pass
            # removes before the scope run plans, so both passes' removals are added up.
            visible_removed = visible.removed if visible is not None else 0
            if stopped_notice or report is None:
                outcome = stopped_outcome(
                    stopped_notice or REFRESH_FAILED_NOTICE, removed=visible_removed
                )
            else:
                outcome = refresh_outcome(
                    in_scope=report.remaining_scope,
                    refreshed=report.refreshed,
                    already_fresh=report.already_fresh,
                    failed=report.failed,
                    not_attempted=report.not_attempted,
                    rate_limited=report.rate_limited,
                    usage_paused=report.usage_paused,
                    planning_failed=report.planning_failed,
                    credential_failed=report.credential_failed,
                    removed=report.removed + visible_removed,
                    restored=report.restored,
                )
                # Same page under a NEW snapshot: the stored changes (likes, text, a date
                # that moves a row, a sentiment that changes its filter) are what the page
                # now shows, and the snapshot's total is re-taken so the tick does not
                # report a stale change.
                await self._read(page=self.page, new_snapshot=True)
            self.refresh_notice = outcome.notice
        show = {"ok": rx.toast.success, "warn": rx.toast.warning}.get(outcome.tone, rx.toast.info)
        yield show(outcome.toast)

    @rx.event
    async def refresh_tick(self) -> None:
        """The 45-second heartbeat. Re-reads the current page: on page 1 under a NEW
        snapshot with the period's window recomputed, so what arrived meanwhile simply shows
        (no notice); on a later page under the SAME snapshot, whose set of rows never changes
        by itself. ONE read per tick. A failure keeps the rows on screen with a soft notice
        and never stops the next tick (it never touches `mentions_error`)."""
        if self.is_loading_mentions or not self.as_of or self.mentions_error:
            return
        tenant_id = await self._tenant()
        if tenant_id is None:
            return
        fresh = tick_takes_new_snapshot(self.page)
        since = _window_start(self.period_filter) if fresh else self.since
        try:
            reread = await asyncio.to_thread(
                load_page,
                tenant_id,
                query=self._query(since=since),
                page=self.page,
                as_of="" if fresh else self.as_of,
            )
        except Exception as exc:  # noqa: BLE001 — keep the rows; say it, don't break
            logger.warning("mentions refresh tick failed: %s", type(exc).__name__)
            self.refresh_error = _REFRESH_ERROR
            return
        if fresh:
            self.since = since
            self._apply_page(reread, new_snapshot=True)
            return
        if decide_tick(snapshot_total=self.snapshot_total, reread_total=reread.filtered_total) == (
            "update_rows"
        ):
            self._apply_page(reread, new_snapshot=False)
        else:
            self.list_changed = True
            self.last_updated = _utc_stamp()
            self.refresh_error = ""
        # A later page never shows what arrived after its snapshot; one count says whether
        # anything did (QUA-152). The count uses the list's own filters and is compared with
        # the list's own total, so «Verlas» always leads to something new (UX review). Best
        # effort: a failed count only skips the notice.
        try:
            now_total = await asyncio.to_thread(
                list_total_now, tenant_id, query=self._query(since=since)
            )
        except Exception as exc:  # noqa: BLE001 — the notice is optional
            logger.warning("mentions new-arrivals count failed: %s", type(exc).__name__)
            return
        if new_mentions_arrived(snapshot_total=self.snapshot_total, current_total=now_total):
            self.new_mentions_waiting = True
