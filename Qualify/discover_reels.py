"""«Ideas para tus reels» in /create («Descubrir reels» in the code, § request 2026-10-15):
the reels that work best among the accounts the brand follows — only the ones of its own
product or category — as cards the owner can watch, read and replicate.

ADR 42 R7 (m-24854854): opening the view ONLY READS WHAT IS STORED. The weekly run (R8)
and the owner's search (R9) are what pay; the view brings their latest `ok` run from
Postgres (`reels_discovery.load_ideas`) and shows it at once, dated in the business's
zone (`reels_ideas_vm`). Nothing here reads ScrapeCreators or asks the model: the old
on-mount read, «Actualizar», the 90-day tab and the on-demand «Ver transcripción» —
all four paid inline — are gone; a card shows the transcript the run stored.

Two writes ride on opening, both through `reels_discovery` (decisions of 2026-11-04):
the brand's «last opened» mark (the worker's 14-day rule) and, for a brand that never had
a run, its first run queued (option A, confirmed by the founder) — the view then says it is
being prepared and, from the browser (`_ticker`), reads the view again — free — every
`POLL_SECONDS` until that run ends or has been in line too long.

RF-02 (m-25119460): a filter bar over the ideas — «Canal», «Tipo de cuenta», «Cuenta» (one
or several), «Duración» and «Restablecer filtros» (`reels_filters_vm`); desktop dropdowns
in the bar, phone chips that open a sheet from the bottom. Changing a filter is one
more read of what is stored (RF-01's `reviewed_reels`): it never queues a run, never marks
the brand, never pays.

RF-13 (m-25120327, Deivid 2026-11-25): the bar is drawn with the system's pieces only —
Radix buttons, popovers and `drawer` under the global Liquid Glass skin, no box behind
it — and under it there is ONE list with no heading: the ideas first, then the other
reels the check kept (RF-01's second list), `LIST_PAGE` at a time; «Ver más» brings the
next `LIST_PAGE`. Only the ideas offer «Hacer uno parecido».

RF-05 (m-25119465), option A chosen by Deivid on 2026-11-25: «Tus competidores» at the end
of the bar opens a drawer (`reels_competitors_vm`) — ticking a competitor saves the
brand's labels — with «Ver sus reels ahora» for the others, which only QUEUES the read
inside the daily cap (the reels-worker pays). While one is in flight a clock outside the
drawer reads the rows again every `POLL_SECONDS` (free) and, when it ends, the lists too;
with the drawer closed a toast says how it ended.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.referentes import reels_ai
from qualify_api.referentes.competitors import STATE_READING
from qualify_api.referentes.reel_reference import ReelReferenceUnavailable
from qualify_api.referentes.reviewed_reels import KIND_REFERENTE

from . import (
    reel_wait_vm,
    reels_competitors_vm,
    reels_discovery,
    reels_filters_vm,
    reels_ideas_vm,
)
from .auth_state import AuthState
from .catalog_vm import IDEAS_RETURN_PATH, brand_referentes_href
from .creative_provider import default_brand_id
from .creative_state import CreativeState
from .r2_media import BACKEND_BASE
from .reel_replication import import_reference
from .reels_filters_vm import (
    AXIS_ACCOUNT,
    AXIS_DURATION,
    AXIS_KIND,
    AXIS_LABELS,
    AXIS_NETWORK,
    EMPTY_COMPETITORS,
    EMPTY_FILTERS,
    EMPTY_NO_COMPETITORS,
    EMPTY_NO_IDEAS,
    LIST_PAGE,
    FilterChoice,
)
from .reels_ideas_vm import (
    SCREEN_CHECK_FAILED,
    SCREEN_IDEAS,
    SCREEN_NO_ACCOUNTS,
    SCREEN_NO_BRIEF,
    SCREEN_NO_IDEAS,
    SCREEN_PREPARING,
    SCREEN_SLOW,
    SCREEN_UNAVAILABLE,
)
from .tenant import tenant_uuid
from .ui import (
    callout,
    card,
    drawer,
    empty_state,
    loading_spinner,
    signal_pill,
    skeleton_card,
)
from .ui import tokens as T
from .ui.steps import go_to_step

#: «Hacer uno parecido»'s help (UI-1), always visible on phones too; opening the form
#: never generates a paid piece.
REPLICATE_HELP = reels_ideas_vm.SIMILAR_HELP
#: The reel's video could not be prepared for the piece (no «referencia»: UX §2).
PREPARE_FAILED = "No pudimos preparar este video. Inténtalo de nuevo."

#: Where the empty states' buttons lead (UX review 4): «Negocios parecidos al tuyo» on the
#: brand page, open — choosing the accounts and the search that says what the business
#: sells (the check's brief) both live there — with «‹ Ideas de videos» to come back.
ACCOUNTS_HREF = brand_referentes_href(IDEAS_RETURN_PATH)

#: The «preparando» screen's browser clock asks for a new read (a database read, free)
#: this often, only while that screen is on screen. How long it may spin is the data's
#: (`reels_ideas_vm.PREPARING_LIMIT`, from the run's `queued_at`): a reload or a deploy
#: never leaves it spinning.
POLL_SECONDS = 12.0

logger = logging.getLogger(__name__)


class DiscoverReelsState(rx.State):
    """What «Ideas para tus reels» shows: one `reels_ideas_vm.SCREEN_*` and its words,
    and the stored ideas as cards (`reels.reel_card`). The cards stay on the backend
    (`_cards`) — only a server-held card can open a replica — and the browser receives
    `reels`, the ones the check kept for the product or its category."""

    replicating: str = ""
    replicate_error: str = ""
    _cards_tenant_id: str = ""

    #: Which `reels_ideas_vm.SCREEN_*` is on screen; "" until the first read lands.
    screen: str = ""
    #: The header over the ideas, or the empty state's title, body and button.
    title: str = ""
    body: str = ""
    action: str = ""
    #: What that button does (`reels_ideas_vm.ACTION_*`).
    action_to: str = ""
    #: A notice above stored ideas that are still true (a newer run failed its check).
    notice_title: str = ""
    notice_body: str = ""
    #: The browser clock re-reads the view (`reels_ideas_vm.IdeasScreen.waiting`): the first
    #: run in flight, or a failed run the worker will try again.
    waiting: bool = False
    #: Why the stored ideas could not be read (`reels_ideas_vm.LOAD_ERROR`), "" none.
    load_error: str = ""
    #: RF-13: «Eso es todo por ahora…» under the list once nothing is left to page
    #: (`reels_ideas_vm.END_OF_LIST`), "" when there is no Monday to give.
    end_note: str = ""
    #: RF-02: the bar's values ("" = «Todos»; `accounts` are `account_key`s). Held in
    #: memory only — never in the browser's storage — and cleared with another business.
    filter_network: str = ""
    filter_kind: str = ""
    filter_duration: str = ""
    filter_accounts: list[str] = []
    #: The accounts «Cuenta» offers (`reels_filters_vm.account_options`) and their kinds.
    account_options: list[dict[str, str]] = []
    _accounts: dict[str, str] = {}
    #: Which axis' sheet is open on a phone ("" none).
    sheet: str = ""
    #: The axis whose chip opened the last sheet — kept after it closes, so the focus
    #: goes back to that chip (Escape, the backdrop, «Cerrar» or «Listo»; RF-13).
    sheet_chip: str = ""
    #: A filtered read is in flight (the lists dim until it lands).
    filtering: bool = False
    #: The reviewed reels after the ideas (RF-01's second list, RF-13's one list): the
    #: ones shown so far, whether more exist, the offset «Ver más» reads from next, and
    #: that read in flight / its error.
    more_reels: list[dict[str, str]] = []
    has_more: bool = False
    more_loading: bool = False
    more_error: str = ""
    _more_next: int = 0
    #: The reel playing inside its own card (its `key`), "" when none — one at a time,
    #: so starting another stops the previous (its iframe unmounts).
    playing_key: str = ""
    #: RF-05: the competitors panel (`reels_competitors_vm.rows`), the row being saved or
    #: asked to read now ("" none) and the panel's last refusal or error.
    competitor_rows: list[dict[str, str]] = []
    competitor_busy: str = ""
    competitor_error: str = ""
    #: Option A (Deivid, 2026-11-25): the panel lives in a drawer opened from the bar —
    #: open or not, and whether it rises from the bottom (the phone's chip) or slides from
    #: the right (the desktop button).
    competitors_open: bool = False
    competitors_bottom: bool = False

    #: The stored ideas, best first (backend only).
    _cards: list[dict[str, str]] = []
    #: Which read is the live one: a new mount, or leaving the view, supersedes the
    #: others — a stale read never paints.
    _load_id: int = 0
    #: The brand the cards are of, and when the screen was last painted from a read
    #: (epoch seconds): the «preparando» clock re-reads the same brand, and not twice at
    #: once nor right after a read.
    _brand_id: str = ""
    _read_at: float = 0.0
    _ticking: bool = False

    @rx.var
    def reels(self) -> list[dict[str, str]]:
        """The ideas the check kept for the brand's product or category — never another
        product's reel, even from a card stored under another rule."""
        return [c for c in self._cards if c.get("affinity") in reels_ai.FITS]

    def _claim_cards(self, tenant_id: str) -> None:
        if self._cards_tenant_id != tenant_id:
            self._cards = []
            self.playing_key = ""
            self.failed_videos = []
            self.failed_covers = []
            self.expanded = []
            # another business: its filters, accounts and reels are not this one's
            self._set_choice(reels_filters_vm.NO_CHOICE)
            self.account_options = []
            self._accounts = {}
            self.more_reels = []
            self.has_more = False
            self._more_next = 0
            self.sheet = ""
            self.sheet_chip = ""
            self.competitor_rows = []
            self.competitor_busy = ""
            self.competitor_error = ""
            self.competitors_open = False
            self.competitors_bottom = False
            self._cards_tenant_id = tenant_id

    # -- RF-02: the filter bar ------------------------------------------------------------

    def _choice(self) -> FilterChoice:
        return FilterChoice.of(
            network=self.filter_network,
            kind=self.filter_kind,
            duration=self.filter_duration,
            accounts=self.filter_accounts,
        )

    def _set_choice(self, choice: FilterChoice) -> None:
        self.filter_network = choice.network
        self.filter_kind = choice.kind
        self.filter_duration = choice.duration
        self.filter_accounts = list(choice.accounts)

    @rx.var
    def filters_on(self) -> bool:
        """Some filter narrows the lists («Restablecer filtros» is offered)."""
        return bool(
            self.filter_network or self.filter_kind or self.filter_duration or self.filter_accounts
        )

    @rx.var
    def filter_values(self) -> dict[str, str]:
        """axis → what it is set to, in words («Todos», «Instagram», «2 cuentas»).
        The vars are read here, not through `_choice()`: a computed var only tracks the
        attributes it reads itself, so a helper would leave it stale."""
        choice = FilterChoice.of(
            network=self.filter_network,
            kind=self.filter_kind,
            duration=self.filter_duration,
            accounts=self.filter_accounts,
        )
        return {
            chip["axis"]: chip["value"]
            for chip in reels_filters_vm.chips(choice, self.account_options)
        }

    @rx.var
    def sheet_title(self) -> str:
        return AXIS_LABELS.get(self.sheet, "")

    @rx.var
    def empty_kind(self) -> str:
        """Which `reels_filters_vm.EMPTY_*` replaces both lists when they are empty."""
        if self.screen != SCREEN_IDEAS:
            return ""
        choice = FilterChoice.of(
            network=self.filter_network,
            kind=self.filter_kind,
            duration=self.filter_duration,
            accounts=self.filter_accounts,
        )
        shown = [c for c in self._cards if c.get("affinity") in reels_ai.FITS]
        return reels_filters_vm.empty_message(
            choice, self._accounts, ideas=len(shown), more=len(self.more_reels)
        ).kind

    @rx.var
    def no_ideas_left(self) -> bool:
        """RF-13: with no filter on, the run's ideas are all gone (their accounts now «No
        va contigo») but reviewed reels are left: the list says so over them, with
        «Elegir cuentas» (`NO_IDEAS_LEFT`). The vars are read here, not via helpers."""
        if self.screen != SCREEN_IDEAS or not self.more_reels:
            return False
        if self.filter_network or self.filter_kind or self.filter_duration:
            return False
        if self.filter_accounts:
            return False
        return not any(c.get("affinity") in reels_ai.FITS for c in self._cards)

    @rx.var
    def no_ideas_filtered(self) -> bool:
        """RF-13 (ux-designer, Deivid 2026-11-26): with a filter on, no idea left (so none
        to make again with «Hacer uno parecido»): the list says so over what it shows
        (`NO_IDEAS_FILTERED`); «Restablecer filtros» is already in the bar."""
        if self.screen != SCREEN_IDEAS:
            return False
        filtered = bool(
            self.filter_network or self.filter_kind or self.filter_duration or self.filter_accounts
        )
        if not filtered:
            return False
        # the same count as `no_ideas_left`: an idea whose video was not kept says so on
        # its own card (`CANNOT_REPLICATE`), so it is no reason to ask to drop a filter
        return not any(c.get("affinity") in reels_ai.FITS for c in self._cards)

    @rx.event
    def open_sheet(self, axis: str) -> None:
        """A phone chip: open its axis' sheet (and remember the chip, for the focus)."""
        self.sheet = axis if axis in reels_filters_vm.AXES else ""
        if self.sheet:
            self.sheet_chip = self.sheet

    @rx.event
    def sheet_changed(self, is_open: bool) -> None:
        """The sheet closed (Esc, the backdrop, «Cerrar»)."""
        if not is_open:
            self.sheet = ""

    @rx.event
    def close_sheet(self) -> None:
        self.sheet = ""

    @rx.event
    def set_filter(self, axis: str, value: str) -> Any:
        """One single-choice axis to `value` ("" = «Todos»); its sheet closes and the
        lists are read again — what is stored, free."""
        self.sheet = ""
        before = self._choice()
        choice = reels_filters_vm.set_axis(before, axis, value)
        if choice == before:
            return None
        self._set_choice(choice)
        return DiscoverReelsState.refilter

    @rx.event
    def toggle_account(self, key: str) -> Any:
        """«Cuenta»: add or remove one account (several may be chosen; the sheet stays)."""
        if key not in self._accounts and key not in self.filter_accounts:
            return None
        self._set_choice(reels_filters_vm.toggle_account(self._choice(), key))
        return DiscoverReelsState.refilter

    @rx.event
    def all_accounts(self) -> Any:
        """«Cuenta: Todas»."""
        if not self.filter_accounts:
            return None
        self._set_choice(reels_filters_vm.clear_accounts(self._choice()))
        return DiscoverReelsState.refilter

    @rx.event
    def show_inspiring(self) -> Any:
        """«Ver cuentas que te inspiran» (competitors not read yet): «Tipo de cuenta» to
        «Inspiradores», with no account chosen — a competitor account would leave it
        empty again."""
        self.sheet = ""
        before = self._choice()
        choice = reels_filters_vm.set_axis(
            reels_filters_vm.clear_accounts(before), AXIS_KIND, KIND_REFERENTE
        )
        if choice == before:
            return None
        self._set_choice(choice)
        return DiscoverReelsState.refilter

    @rx.event
    def reset_filters(self) -> Any:
        """«Restablecer filtros»: every axis back to «Todos», the full list again."""
        self.sheet = ""
        if not self._choice().active:
            return None
        self._set_choice(reels_filters_vm.NO_CHOICE)
        return DiscoverReelsState.refilter

    @rx.event(background=True)
    async def refilter(self) -> None:
        """Read the lists again with the bar's values (RF-01's read): Postgres only — it
        never queues a run, never marks the brand, never reads the vendor nor asks the
        model. A newer read supersedes it (`_load_id`)."""
        async with self:
            if not self._brand_id or not self._cards_tenant_id:
                return
            self._load_id += 1
            load_id = self._load_id
            self.filtering = True
            filters = self._choice().to_filters()
            tenant_id = tenant_uuid(self._cards_tenant_id)
            brand_id = UUID(self._brand_id)
        shown: reels_ideas_vm.IdeasScreen | None = None
        try:
            if tenant_id is not None:
                shown = await asyncio.to_thread(
                    reels_discovery.load_ideas,
                    tenant_id,
                    brand_id,
                    first_run=False,
                    filters=filters,
                )
        except Exception as exc:  # noqa: BLE001 — the view says it, the log keeps why
            logger.warning("filtered reel ideas unreadable: %s: %s", type(exc).__name__, exc)
            async with self:
                if self._load_id == load_id:
                    self.filtering = False
                    self.load_error = reels_ideas_vm.LOAD_ERROR
            return
        async with self:
            if self._load_id != load_id:
                return
            self.filtering = False
            if (
                shown is not None
                and tenant_id is not None
                and await _still_mine(self, load_id, tenant_id)
            ):
                self._show(shown)

    @rx.event(background=True)
    async def load_more(self) -> None:
        """«Ver más»: the next `LIST_PAGE` reviewed reels of the one list, same filters —
        what is stored, free."""
        async with self:
            # never while a filtered read is in flight: its list restarts the paging
            if self.more_loading or self.filtering or not self.has_more or not self._brand_id:
                return
            self.more_loading = True
            self.more_error = ""
            load_id = self._load_id
            filters = self._choice().to_filters()
            offset = self._more_next
            tenant_id = tenant_uuid(self._cards_tenant_id)
            brand_id = UUID(self._brand_id)
        try:
            if tenant_id is None:
                raise LookupError("no tenant in this session")
            cards, has_more = await asyncio.to_thread(
                reels_discovery.more_reviewed,
                tenant_id,
                brand_id,
                filters=filters,
                offset=offset,
                limit=LIST_PAGE,
            )
        except Exception as exc:  # noqa: BLE001 — the button says it, the log keeps why
            logger.warning("more reviewed reels unreadable: %s: %s", type(exc).__name__, exc)
            async with self:
                self.more_loading = False
                if self._load_id == load_id:
                    self.more_error = reels_filters_vm.MORE_ERROR
            return
        async with self:
            self.more_loading = False
            if self._more_next != offset or not await _still_mine(self, load_id, tenant_id):
                return  # the filters changed (or the session) meanwhile: not this list
            seen = {c.get("key") for c in self.more_reels}
            self.more_reels = [*self.more_reels, *(c for c in cards if c.get("key") not in seen)]
            self.has_more = has_more
            self._more_next = offset + LIST_PAGE

    def _show(self, shown: reels_ideas_vm.IdeasScreen) -> None:
        self.screen = shown.screen
        self.title = shown.title
        self.body = shown.body
        self.action = shown.action
        self.action_to = shown.action_to
        self.notice_title = shown.notice_title
        self.notice_body = shown.notice_body
        self.waiting = shown.waiting
        self.end_note = shown.end_note
        self._read_at = time.time()
        self._cards = list(shown.cards)
        # RF-13: the one list's first `LIST_PAGE` — the ideas, then the reviewed reels
        # that fit after them; the rest waits for «Ver más». RF-02: the accounts
        # «Cuenta» offers — a chosen account the brand no longer offers is dropped
        ideas = sum(1 for c in self._cards if c.get("affinity") in reels_ai.FITS)
        page = reels_filters_vm.first_page(ideas, shown.more_cards, has_more=shown.has_more)
        self.more_reels = page.more
        self.has_more = page.has_more
        self.more_error = ""
        self._more_next = page.next_offset
        self._accounts = dict(shown.accounts)
        self.account_options = reels_filters_vm.account_options(shown.accounts)
        if shown.screen == SCREEN_IDEAS:
            self._set_choice(reels_filters_vm.known_accounts(self._choice(), shown.accounts))
        keys = {c.get("key", "") for c in self._cards} | {c.get("key", "") for c in self.more_reels}
        if self.playing_key not in keys:
            self.playing_key = ""
        self.expanded = [k for k in self.expanded if k in keys]

    @rx.event(background=True)
    async def load(self) -> None:
        """Bring what is stored (ADR 42 R7): Postgres only — opening never reads the
        vendor nor asks the model. Marks the brand as opened beside the read, without
        waiting for it. Also «Ver si ya están» and «Intentar de nuevo»: one more read,
        and the first run queued again if it never could be."""
        async with self:
            self._load_id += 1
            load_id = self._load_id
            self.load_error = ""
            auth = await self.get_state(AuthState)
            # the logged-in tenant only: a pre-login Brand Kit draft never opens /create
            session_tenant_id = auth.session_tenant_id
            # RF-02: the bar's values of this business only (another one starts with none)
            filters = (
                self._choice().to_filters()
                if self._cards_tenant_id == session_tenant_id
                else reels_filters_vm.NO_CHOICE.to_filters()
            )
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        opened: asyncio.Task[None] | None = None
        try:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id) if tenant_id else None
            if tenant_id is None or brand_id is None:
                raise LookupError("no brand in this session")
            # the «last opened» mark (R8's 14-day rule) goes first, in its own thread —
            # the read never waits for it
            opened = asyncio.create_task(
                asyncio.to_thread(reels_discovery.mark_opened, tenant_id, brand_id)
            )
            shown = await asyncio.to_thread(
                reels_discovery.load_ideas, tenant_id, brand_id, filters=filters
            )
            rivals = await _competitor_rows(tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the view says it, the log keeps why
            logger.warning("stored reel ideas unreadable: %s: %s", type(exc).__name__, exc)
            async with self:
                if self._load_id == load_id:
                    self.load_error = reels_ideas_vm.LOAD_ERROR
            await _settle(opened)
            return
        async with self:
            if await _still_mine(self, load_id, tenant_id):
                self._claim_cards(str(tenant_id))
                self._brand_id = str(brand_id)
                self._show(shown)
                if rivals is not None:
                    self.competitor_rows = rivals
        await _settle(opened)

    # -- RF-05: the competitors panel -----------------------------------------------------

    @rx.var
    def competitors_count(self) -> str:
        """«3 de 6 marcados»: how many the Monday run reads."""
        return reels_competitors_vm.picked_count(self.competitor_rows)

    @rx.var
    def competitors_label(self) -> str:
        """The bar button's accessible name: the count, or that a read is in flight."""
        return reels_competitors_vm.button_label(self.competitor_rows)

    @rx.event
    def open_competitors(self, bottom: bool) -> None:
        """«Tus competidores»: the drawer from the right (desktop) or the bottom (phone)."""
        if not self.competitor_rows:
            return
        self.competitors_bottom = bool(bottom)
        self.competitors_open = True
        self.competitor_error = ""

    @rx.event
    def competitors_changed(self, is_open: bool) -> None:
        """The drawer closed (Esc, the backdrop, «Cerrar»)."""
        if not is_open:
            self.competitors_open = False

    @rx.event
    def close_competitors(self) -> None:
        """«Listo»."""
        self.competitors_open = False

    @rx.var
    def competitors_reading(self) -> bool:
        """A manual read is queued or running: the panel asks again every `POLL_SECONDS`."""
        return reels_competitors_vm.reading(self.competitor_rows)

    def _session_brand(self) -> tuple[UUID, UUID] | None:
        tenant_id = tenant_uuid(self._cards_tenant_id) if self._cards_tenant_id else None
        if tenant_id is None or not self._brand_id:
            return None
        return tenant_id, UUID(self._brand_id)

    @rx.event(background=True)
    async def toggle_weekly(self, key: str) -> None:
        """Tick or untick a competitor for the Monday run (at most 6). Saves the brand's
        own labels — never a read, never a paid call."""
        async with self:
            if self.competitor_busy:
                return
            change = reels_competitors_vm.toggle(self.competitor_rows, key)
            if change is None:
                return
            if change.error:
                self.competitor_error = change.error
                return
            target = self._session_brand()
            if target is None:
                return
            self.competitor_busy = key
            self.competitor_error = ""
        tenant_id, brand_id = target
        try:
            await asyncio.to_thread(
                reels_discovery.choose_competitors, tenant_id, brand_id, list(change.picks)
            )
        except Exception as exc:  # noqa: BLE001 — the panel says it, the log keeps why
            logger.warning("competitor picks not saved: %s: %s", type(exc).__name__, exc)
            async with self:
                self.competitor_busy = ""
                self.competitor_error = reels_competitors_vm.SAVE_FAILED
            return
        rivals = await _competitor_rows(tenant_id, brand_id)
        async with self:
            self.competitor_busy = ""
            if rivals is not None and self._session_brand() == target:
                self.competitor_rows = rivals

    @rx.event(background=True)
    async def read_competitor(self, key: str) -> None:
        """«Ver sus reels ahora»: queue that competitor's read for today — once — inside
        the business's daily cap. It only QUEUES: the reels-worker pays (ADR 42 R4/R8)."""
        async with self:
            if self.competitor_busy or key not in {r["key"] for r in self.competitor_rows}:
                return
            target = self._session_brand()
            if target is None:
                return
            self.competitor_busy = key
            self.competitor_error = ""
        tenant_id, brand_id = target
        try:
            answer = await asyncio.to_thread(
                reels_discovery.read_competitor_now, tenant_id, brand_id, key
            )
        except Exception as exc:  # noqa: BLE001 — the panel says it, the log keeps why
            logger.warning("competitor read not queued: %s: %s", type(exc).__name__, exc)
            async with self:
                self.competitor_busy = ""
                self.competitor_error = reels_competitors_vm.READ_FAILED
            return
        rivals = await _competitor_rows(tenant_id, brand_id)
        async with self:
            self.competitor_busy = ""
            if self._session_brand() != target:
                return
            # a refused press (the daily cap) queues no read: its answer is the row's line
            self.competitor_rows = reels_competitors_vm.with_answer(
                rivals if rivals is not None else self.competitor_rows, key, answer
            )

    @rx.event(background=True)
    async def refresh_competitors(self, _shown: str = "") -> Any:
        """The panel's browser clock, while a manual read is in flight — mounted outside
        the drawer, so it keeps going with the drawer closed: read the rows again
        (Postgres, free). When a read has just ended, the lists are read again too, so its
        reels show under «Competidores»; with the drawer closed a toast says how it ended
        (open, the row's own line says it)."""
        async with self:
            target = self._session_brand()
            before = {r["key"]: r.get("state", "") for r in self.competitor_rows}
        if target is None:
            return None
        rivals = await _competitor_rows(*target)
        if rivals is None:
            return None
        async with self:
            if self._session_brand() != target:
                return None
            self.competitor_rows = rivals
            closed = not self.competitors_open
        finished = reels_competitors_vm.ended(before, rivals)
        if not finished:
            return None
        toasts = [
            rx.toast.success(text)
            if tone == "ok"
            else rx.toast.warning(text)
            if tone == "warn"
            else rx.toast.error(text)
            for tone, text in finished
        ]
        return [DiscoverReelsState.refilter, *(toasts if closed else [])]

    @rx.event(background=True)
    async def tick(self, _shown: str = "") -> None:
        """The browser clock (`_ticker`, every `POLL_SECONDS`, only while `waiting`: the
        first run in flight, or a failed run the worker will try again): read the view
        again — a database read, free; it never queues a run nor marks the brand — until
        the view model says the screen stops waiting (the clock is gone with it)."""
        async with self:
            if (
                not self.waiting
                or self._ticking
                or not self._brand_id
                or time.time() - self._read_at < POLL_SECONDS / 2
            ):
                return
            self._ticking = True
            load_id = self._load_id
            filters = self._choice().to_filters()
            tenant_id = tenant_uuid(self._cards_tenant_id)
            brand_id = UUID(self._brand_id)
        shown: reels_ideas_vm.IdeasScreen | None = None
        try:
            if tenant_id is not None:
                shown = await asyncio.to_thread(
                    reels_discovery.load_ideas,
                    tenant_id,
                    brand_id,
                    first_run=False,
                    filters=filters,
                )
        except Exception as exc:  # noqa: BLE001 — the screen stays; the next tick retries
            logger.warning("reel ideas re-read failed: %s: %s", type(exc).__name__, exc)
        async with self:
            self._ticking = False
            if (
                shown is not None
                and tenant_id is not None
                and await _still_mine(self, load_id, tenant_id)
            ):
                self._show(shown)

    @rx.event
    def leave(self) -> None:
        """The view left the page: a read still in flight never paints (and the
        «preparando» clock unmounts with the view)."""
        self._load_id += 1
        self.playing_key = ""
        self.sheet = ""
        self.filtering = False
        self.more_loading = False

    @rx.event
    def play(self, key: str) -> None:
        """Play the reel `key` inside its card, in the network's own player."""
        self.playing_key = key

    @rx.event
    def stop(self) -> None:
        self.playing_key = ""

    #: Reels whose own MP4 would not play (its signed CDN URL died, ~24-33 h after the
    #: run read it): they play in the network's embed instead.
    failed_videos: list[str] = []

    @rx.event
    def video_failed(self, key: str) -> None:
        if key not in self.failed_videos:
            self.failed_videos = [*self.failed_videos, key]

    #: Reels whose cover would not load (no copy in R2 and a CDN link already dead, R12):
    #: their card shows the placeholder instead.
    failed_covers: list[str] = []

    @rx.event
    def cover_failed(self, key: str) -> None:
        if key not in self.failed_covers:
            self.failed_covers = [*self.failed_covers, key]

    #: Cards whose «Detalles» is open (an accordion under the figures).
    expanded: list[str] = []

    @rx.event
    def toggle_details(self, key: str) -> None:
        if key in self.expanded:
            self.expanded = [k for k in self.expanded if k != key]
        else:
            self.expanded = [*self.expanded, key]

    def _card(self, key: str) -> dict[str, str] | None:
        return next((c for c in self._cards if c.get("key") == key), None)

    @rx.event(background=True)
    async def replicate(self, key: str) -> AsyncIterator[rx.event.EventSpec]:
        """«Hacer uno parecido» (ADR 44 UI-1, m-24921075): only a server-held card of
        this session opens the create flow on «Qué mostrar» (`/create?paso=1`), with
        «‹ Ideas para tus reels» in its head. The business is sealed once, from the
        session (ADR 43 §2.4), and checked again before anything is applied.

        What it touches: the copy of the reel's video the run kept (or its CDN link
        while fresh) for the Clip's reference, and the reel's shared analysis — reused
        when it is `ok`, moved ahead or queued for the `reels-worker` otherwise
        (`reels_discovery.request_similar`). Never ScrapeCreators, never the model:
        Reflex never analyses a reel (F5)."""
        async with self:
            if self.replicating:
                return
            self.replicate_error = ""
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id)
            creative = await self.get_state(CreativeState)
            card = self._card(key)
            if tenant_id is None or self._cards_tenant_id != str(tenant_id):
                self.replicate_error = "Vuelve a abrir los reels de tu marca para continuar."
                return
            if card is None or card.get("affinity") not in reels_ai.FITS:
                self.replicate_error = "Este reel ya no está en la selección. Elige otro."
                return
            if card.get("can_replicate") != "1":
                # its video was not kept (R2): nothing to prepare the reference from
                self.replicate_error = reels_ideas_vm.CANNOT_REPLICATE
                return
            if creative.gen_generating or creative.gen_mode != "discover":
                return
            product = (creative.selected_product_id, creative.product_source)
            card = dict(card)
            self.replicating = key
        try:
            imported = await asyncio.to_thread(import_reference, tenant_id, card)
        except Exception as exc:
            logger.warning("reel reference failed: %s", type(exc).__name__)
            async with self:
                self.replicating = ""
                self.replicate_error = (
                    str(exc) if isinstance(exc, ReelReferenceUnavailable) else PREPARE_FAILED
                )
            return
        # after the reference is ready, so a failed one never spends the platform's
        # on-demand analysis quota; a failed request never costs the owner the flow
        asked = await asyncio.to_thread(reels_discovery.request_similar, tenant_id, card)
        analysis_id = str(asked.id) if asked is not None and asked.id is not None else ""
        # UI-2: what the request answered, kept even without an id (`no_video`,
        # `daily_limit`), so «Qué mostrar» (step 1) can say why it will not wait
        analysis_status = asked.status if asked is not None else reel_wait_vm.OUTCOME_UNASKED
        async with self:
            self.replicating = ""
            auth = await self.get_state(AuthState)
            creative = await self.get_state(CreativeState)
            if (
                auth.session_tenant_id != str(tenant_id)
                or creative.gen_mode != "discover"
                or creative.gen_generating
                or product != (creative.selected_product_id, creative.product_source)
            ):
                return
            creative._apply_reel_reference(card, imported, analysis_id, analysis_status)
            self.playing_key = ""
        # no `?analisis=`: the id rides in the server-side state only, and «Qué mostrar»'s wait
        # (UI-2) polls it from there (`CreativeState.poll_reel_analysis`); coming back
        # via the card asks again and gets the same id (`request_analysis`)
        yield go_to_step("/create", 1)


async def _competitor_rows(tenant_id: UUID, brand_id: UUID) -> list[dict[str, str]] | None:
    """RF-05: the competitors panel's rows (Postgres only, free); None when they could not
    be read — the panel keeps what it showed and the rest of the screen goes on."""
    try:
        return await asyncio.to_thread(reels_discovery.competitor_rows, tenant_id, brand_id)
    except Exception as exc:  # noqa: BLE001 — the ideas must show whatever happens here
        logger.warning("competitors panel unreadable: %s: %s", type(exc).__name__, exc)
        return None


async def _still_mine(state: Any, load_id: int, tenant_id: UUID) -> bool:
    """`state`'s read `load_id` is still the live one, for the tenant still logged in.
    Called inside `async with state`."""
    auth = await state.get_state(AuthState)
    # the session's tenant on the right: `test_auth_state`'s guard (only auth_state
    # writes it) reads an equality with it on the left as an assignment
    return state._load_id == load_id and str(tenant_id) == auth.session_tenant_id


async def _settle(task: asyncio.Task[None] | None) -> None:
    """Wait for the «last opened» mark after the screen was painted; it never raises
    (`reels_discovery.mark_opened`), and nothing it does may reach the owner."""
    if task is not None:
        with contextlib.suppress(Exception):
            await task


# --------------------------------------------------------------------------------------
# view
# --------------------------------------------------------------------------------------


class _ReelVideo(rx.el.Video):
    """The reel's own MP4. Reflex's `video` element declares no `error` trigger; this
    one does, so a signed CDN URL that already died hands the card over to the
    network's embed (`DiscoverReelsState.video_failed`)."""

    on_error: rx.EventHandler[rx.event.no_args_event_spec]


class _ReelCover(rx.el.Img):
    """The reel's cover. Reflex's `img` declares no `error` trigger either; this one
    does, so a CDN picture that expired shows the card's placeholder instead of a broken
    image (`DiscoverReelsState.cover_failed`)."""

    on_error: rx.EventHandler[rx.event.no_args_event_spec]


def _detail(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.fragment(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.text(value, size="1", weight="medium"),
    )


def _reel_media(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """The card's picture, and its player (§ request 2026-10-15): the cover — or, when
    there is none or it would not load, the film placeholder — with the lift, the network
    and the length over it; a click plays JUST the video in its place — the reel's own
    MP4, streamed from the network's CDN, no page around it — or, when the reel has no
    MP4 or its signed URL already died, the network's own embed."""
    key = reel["key"]
    has_cover = (reel["cover"] != "") & ~DiscoverReelsState.failed_covers.contains(key)
    cover = rx.box(
        rx.cond(
            has_cover,
            _ReelCover.create(
                src=BACKEND_BASE + reel["cover"],
                alt="",
                loading="lazy",
                class_name="q-dr-cover-img",
                on_error=DiscoverReelsState.cover_failed(key),
            ),
            # RF-02: a reviewed reel (not an idea) keeps no copy of its cover (its CDN link
            # lives ~4 days): the placeholder says so instead of looking broken
            rx.center(
                rx.vstack(
                    rx.icon("film", size=28, color=T.TEXT_FAINT, aria_hidden="true"),
                    rx.text(
                        reels_filters_vm.COVER_GONE,
                        size="1",
                        color=T.TEXT_MUTED,
                        text_align="center",
                    ),
                    spacing="2",
                    align="center",
                ),
                class_name="q-dr-cover-img q-dr-cover-empty",
            ),
        ),
        rx.cond(
            reel["lift"] != "",
            rx.box(
                rx.text(reel["lift"], size="1", weight="bold"),
                class_name=rx.cond(
                    reel["lift_tone"] == "ok", "q-dr-lift q-dr-lift--ok", "q-dr-lift"
                ),
            ),
        ),
        rx.box(
            rx.text(reel["network_label"], size="1", weight="medium"),
            class_name="q-cr-mark",
            top="0.45rem",
            right="0.45rem",
            padding="0.1rem 0.45rem",
        ),
        rx.cond(
            reel["seconds"] != "",
            rx.box(
                rx.text(reel["seconds"], size="1", weight="medium"),
                class_name="q-cr-mark",
                bottom="0.45rem",
                right="0.45rem",
                padding="0.1rem 0.45rem",
            ),
        ),
        rx.center(rx.icon("play", size=22), class_name="q-dr-play", aria_hidden="true"),
        class_name="q-dr-cover",
    )
    embed_only = DiscoverReelsState.failed_videos.contains(key) | (reel["video"] == "")
    player = rx.box(
        rx.cond(
            embed_only,
            rx.el.iframe(
                src=reel["embed"],
                title="Reproductor del reel",
                allow="autoplay; fullscreen; encrypted-media; picture-in-picture",
                allow_full_screen=True,
                class_name="q-dr-embed",
            ),
            _ReelVideo.create(
                src=reel["video"],
                auto_play=True,
                controls=True,
                loop=True,
                plays_inline=True,
                preload="auto",
                class_name="q-dr-video",
                on_error=DiscoverReelsState.video_failed(key),
            ),
        ),
        rx.icon_button(
            rx.icon("x", size=14),
            size="1",
            variant="solid",
            color_scheme="gray",
            high_contrast=True,
            radius="full",
            aria_label="Cerrar video",
            title="Cerrar video",
            on_click=DiscoverReelsState.stop,
            class_name="q-dr-close",
        ),
        class_name=rx.cond(embed_only, "q-dr-cover q-dr-cover--embed", "q-dr-cover"),
    )
    return rx.cond(
        DiscoverReelsState.playing_key == key,
        player,
        rx.el.button(
            cover,
            type="button",
            on_click=DiscoverReelsState.play(key),
            class_name="q-dr-cover-button",
            aria_label="Ver el reel aquí",
        ),
    )


def _transcript_block(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """What is said in the reel, as the run stored it (ADR 42 R7: the screen never pays
    for a transcript) — «no tiene voz» when it was transcribed and says nothing, nothing
    at all when it never was."""
    return rx.cond(
        reel["transcript"] != "",
        rx.vstack(
            rx.hstack(
                rx.icon("captions", size=13, color=T.TEXT_MUTED),
                rx.text("Lo que se dice", size="1", weight="medium"),
                spacing="1",
                align="center",
            ),
            rx.text(reel["transcript"], size="1", color=T.TEXT_MUTED, class_name="q-dr-transcript"),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        rx.cond(
            reel["transcript_state"] == "none",
            rx.text("Este video no tiene voz.", size="1", color=T.TEXT_MUTED),
        ),
    )


def _details_panel(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """Everything else about the reel (§ request 2026-10-15): a «Detalles» bar that
    opens the card downwards — an accordion, by click, the same on a phone — with the
    other figures, the caption, the sound, why it is of the rubro and the transcript."""
    figures = rx.box(
        _detail("Me gusta", reel["likes"]),
        _detail("Comentarios", reel["comments"]),
        rx.cond(reel["saves"] != "", _detail("Guardados", reel["saves"])),
        rx.cond(reel["seconds"] != "", _detail("Duración", reel["seconds"])),
        _detail("Publicado", reel["age"]),
        class_name="q-dr-figures",
    )
    panel = rx.vstack(
        figures,
        rx.cond(
            reel["caption"] != "",
            rx.text(reel["caption"], size="1", color=T.TEXT_MUTED, class_name="q-dr-caption"),
        ),
        rx.cond(
            reel["sound"] != "",
            rx.hstack(
                rx.icon("music", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
                rx.text(reel["sound"], size="1", color=T.TEXT_MUTED, class_name="q-dr-ellipsis"),
                spacing="1",
                align="center",
                width="100%",
            ),
        ),
        rx.cond(
            reel["reason"] != "",
            rx.hstack(
                rx.icon("sparkles", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
                rx.text(reel["reason"], size="1", color=T.TEXT_MUTED),
                spacing="1",
                align="start",
                width="100%",
            ),
        ),
        _transcript_block(reel),
        rx.link(
            rx.hstack(
                rx.icon("external-link", size=13),
                rx.text("Abrir en ", reel["network_label"], size="1"),
                spacing="1",
                align="center",
            ),
            href=reel["url"],
            is_external=True,
        ),
        spacing="2",
        width="100%",
        align_items="start",
        class_name="q-dr-more-panel",
    )
    open_ = DiscoverReelsState.expanded.contains(reel["key"])
    return rx.box(
        rx.el.button(
            rx.text(rx.cond(open_, "Menos", "Detalles"), size="1", weight="medium"),
            rx.icon(rx.cond(open_, "chevron-up", "chevron-down"), size=14),
            type="button",
            class_name="q-dr-more-bar",
            aria_expanded=rx.cond(open_, "true", "false"),
            on_click=DiscoverReelsState.toggle_details(reel["key"]),
        ),
        rx.cond(open_, panel),
        class_name="q-dr-more",
    )


def _reel_tile(reel: rx.Var[dict[str, str]], *, more: bool = False) -> rx.Component:
    """One idea as the «C» card (§ request 2026-10-15): the picture with how it does
    against its own account, who and how many views, what it is (format and hook), the
    rest folded into «Detalles», what its analysis saw, and «Hacer uno parecido».
    `more` (RF-02/RF-13): a reviewed reel after the ideas — the same card without «Hacer uno
    parecido» (its video was not kept); in its place, a grey line that says why
    (`MORE_ONLY_LOOK`, styled as `CANNOT_REPLICATE`)."""
    if more:
        foot: rx.Component = rx.text(
            reels_filters_vm.MORE_ONLY_LOOK,
            size="2",
            color=T.TEXT_MUTED,
            class_name="q-dr-replicate-help",
        )
    else:
        # founder, 2026-11-04: only when the run kept the reel's video (R2) — the
        # reference is prepared from that copy, never from a link the browser holds
        foot = rx.cond(
            reel["can_replicate"] == "1",
            _replicate(reel),
            rx.text(
                reels_ideas_vm.CANNOT_REPLICATE,
                size="2",
                color=T.TEXT_MUTED,
                class_name="q-dr-replicate-help",
            ),
        )
    return card(
        rx.vstack(
            _reel_media(reel),
            rx.vstack(
                rx.hstack(
                    rx.text(reel["handle"], size="2", weight="bold", class_name="q-dr-ellipsis"),
                    rx.spacer(),
                    rx.text(reel["age"], size="1", color=T.TEXT_MUTED, white_space="nowrap"),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                # the three figures that rank a reel (§ 2026-10-15): «2.7M vistas ·
                # 92K/día · 15%» — views, views per day since it was published, and
                # interactions over views
                rx.hstack(
                    rx.text(reel["views"], " vistas", size="3", weight="medium"),
                    rx.cond(
                        reel["per_day"] != "",
                        rx.fragment(
                            rx.text("·", size="3", color=T.TEXT_FAINT),
                            rx.text(reel["per_day"], size="3", weight="medium"),
                        ),
                    ),
                    rx.cond(
                        reel["engagement"] != "",
                        rx.fragment(
                            rx.text("·", size="3", color=T.TEXT_FAINT),
                            rx.text(
                                reel["engagement"],
                                size="3",
                                weight="medium",
                                title="Interacciones sobre vistas",
                            ),
                        ),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                    class_name="q-dr-figures-line",
                ),
                # § 2026-10-20: the shown reels are the product OR its category again, so
                # the card says which (it had no pill while only the product was shown)
                rx.hstack(
                    rx.cond(
                        reel["affinity"] == "categoria",
                        rx.box(
                            rx.text("Tu categoría", size="1"),
                            class_name="q-dr-tag q-dr-tag--muted",
                            title="La misma clase de oferta que vendes, sin ser tu producto",
                        ),
                        rx.box(rx.text("Tu producto", size="1"), class_name="q-dr-tag"),
                    ),
                    rx.cond(
                        reel["format"] != "",
                        rx.box(
                            rx.text(reel["format"], size="1"),
                            class_name="q-dr-tag q-dr-tag--muted",
                        ),
                    ),
                    _analysis_pill(reel),
                    spacing="1",
                    wrap="wrap",
                    align="center",
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            _details_panel(reel),
            foot,
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="0.6rem",
        width="100%",
        class_name="q-dr-card",
        # Keep each card tied to its reel when the list changes.
        key=reel["key"],
    )


def _analysis_pill(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """What the reel's shared analysis says, as a pill by tone (UI-1, design §13.7):
    «Aparece una persona» (info) when a person or a face was seen in some part, «Aún no
    lo revisamos» (neutral) without an `ok` analysis, «Lo estamos revisando» in line.
    Nothing when nothing was seen or the analysis could not tell — never «sin personas»."""
    return rx.match(
        reel["analysis"],
        (reels_ideas_vm.BADGE_PERSON, signal_pill(reels_ideas_vm.BADGE_PERSON_TEXT, "info")),
        (
            reels_ideas_vm.BADGE_NOT_ANALYZED,
            signal_pill(reels_ideas_vm.BADGE_NOT_ANALYZED_TEXT, "neutral"),
        ),
        (
            reels_ideas_vm.BADGE_LOOKING,
            signal_pill(reels_ideas_vm.BADGE_LOOKING_TEXT, "neutral"),
        ),
        rx.fragment(),
    )


def _replicate(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """«Hacer uno parecido» (UI-1) and what it does, always visible (a phone has no
    hover): a 44 px button, its help in `size="2"`."""
    busy = DiscoverReelsState.replicating == reel["key"]
    return rx.vstack(
        rx.button(
            rx.cond(busy, loading_spinner("sm"), rx.icon("sparkles", size=14)),
            rx.cond(busy, reels_ideas_vm.SIMILAR_BUSY, reels_ideas_vm.SIMILAR_LABEL),
            size="2",
            width="100%",
            min_height="44px",
            variant="soft",
            on_click=DiscoverReelsState.replicate(reel["key"]),
            disabled=(DiscoverReelsState.replicating != "") | CreativeState.gen_generating,
            class_name="q-dr-replicate",
        ),
        rx.text(
            REPLICATE_HELP,
            size="2",
            color=T.TEXT_MUTED,
            class_name="q-dr-replicate-help",
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


# --------------------------------------------------------------------------------------
# RF-02: the filter bar (m-25119460) — RF-13 (m-25120327): the system's pieces only
# --------------------------------------------------------------------------------------

#: The single-choice axes, in the bar's order around «Cuenta».
_SINGLE_AXES = (AXIS_NETWORK, AXIS_KIND)
_STATE_VALUE = {
    AXIS_NETWORK: lambda: DiscoverReelsState.filter_network,
    AXIS_KIND: lambda: DiscoverReelsState.filter_kind,
    AXIS_DURATION: lambda: DiscoverReelsState.filter_duration,
}
#: The phone's chips and the desktop's dropdowns swap at Reflex's `xs` breakpoint
#: (30em, 480 px): a phone gets the chips and their sheet, anything wider the dropdowns.
_PHONE = rx.breakpoints(initial="flex", xs="none")
_WIDE = rx.breakpoints(initial="none", xs="flex")
#: The marks of an option (lucide, painted with the system's tokens): a radio is a ring
#: that fills, a checkbox an empty square that gets its check — never an empty gap.
_MARKS = {"radio": ("circle-dot", "circle"), "checkbox": ("square-check", "square")}
#: The bar's buttons and the sheet's rows: the 44 px target (docs/design-system.md §8).
_TARGET = "44px"


def _option_row(
    label: str | rx.Var[str],
    chosen: rx.Var[bool],
    on_click: Any,
    *,
    role: str,
    detail: str | rx.Var[str] | None = None,
) -> rx.Component:
    """One option of a filter (and one competitor of RF-05's drawer): a 44 px `ghost`
    Radix button (the skin's row button, §5.5) — a radio for the single-choice axes, a
    checkbox for «Cuenta» and the competitors, read as such by a screen reader — with
    its mark always drawn: the empty ring or square when it is not chosen (RF-13)."""
    on, off = _MARKS[role]
    return rx.button(
        # two static icons, not one named at run time: the mark paints with the row
        rx.cond(
            chosen,
            rx.icon(
                on,
                size=T.ICON_MD,
                color=T.tone_color("accent", 11),
                flex_shrink="0",
                aria_hidden="true",
            ),
            rx.icon(off, size=T.ICON_MD, color=T.TEXT_MUTED, flex_shrink="0", aria_hidden="true"),
        ),
        rx.vstack(
            rx.text(
                label,
                size="2",
                weight=rx.cond(chosen, "medium", "regular"),
                color=T.TEXT_STRONG,
            ),
            *([rx.text(detail, size="1", color=T.TEXT_MUTED)] if detail is not None else []),
            spacing="0",
            align_items="start",
            min_width="0",
        ),
        type="button",
        variant="ghost",
        color_scheme="gray",
        size="2",
        role=role,
        aria_checked=rx.cond(chosen, "true", "false"),
        on_click=on_click,
        width="100%",
        min_height=_TARGET,
        height="auto",
        margin="0",
        padding="0.35rem 0.75rem",
        box_sizing="border-box",
        justify_content="flex-start",
        text_align="start",
        gap="0.6rem",
    )


def _options(*rows: rx.Component, role: str, label: str) -> rx.Component:
    return rx.flex(
        *rows, direction="column", spacing="1", width="100%", role=role, aria_label=label
    )


def _single_options(axis: str, *, close: bool) -> rx.Component:
    """«Todos» and the axis' options. `close`: each option also closes the desktop
    dropdown it sits in (the phone's sheet closes from the state)."""
    current = _STATE_VALUE[axis]()
    rows = []
    for option in reels_filters_vm.single_options(axis):
        row = _option_row(
            option["label"],
            current == option["value"],
            DiscoverReelsState.set_filter(axis, option["value"]),
            role="radio",
        )
        rows.append(rx.popover.close(row) if close else row)
    return _options(*rows, role="radiogroup", label=AXIS_LABELS[axis])


def _account_options() -> rx.Component:
    """«Todas» and every account the brand labelled (one or several, checkboxes)."""
    S = DiscoverReelsState
    return _options(
        _option_row(
            reels_filters_vm.ALL_LABELS[AXIS_ACCOUNT],
            S.filter_accounts.length() == 0,
            S.all_accounts,
            role="checkbox",
        ),
        rx.foreach(
            S.account_options,
            lambda option: _option_row(
                option["label"],
                S.filter_accounts.contains(option["key"]),
                S.toggle_account(option["key"]),
                role="checkbox",
                detail=option["detail"],
            ),
        ),
        rx.cond(
            S.account_options.length() == 0,
            rx.text(
                reels_filters_vm.NO_ACCOUNTS_OPTION,
                size="2",
                color=T.TEXT_MUTED,
                padding="0.5rem 0.75rem",
            ),
        ),
        role="group",
        label=AXIS_LABELS[AXIS_ACCOUNT],
    )


def _axis_value(axis: str) -> rx.Var[str]:
    return DiscoverReelsState.filter_values[axis].to(str)


def _axis_on(axis: str) -> rx.Var[bool]:
    S = DiscoverReelsState
    if axis == AXIS_ACCOUNT:
        return S.filter_accounts.length() > 0
    return _STATE_VALUE[axis]() != ""


def _filter_button(axis: str, **props: Any) -> rx.Component:
    """What a dropdown or a chip reads — «Canal» · «Todos» ▾ — as a Radix button with
    the skin: `soft` (the accent wash) while the axis narrows the list, `surface`
    otherwise. It never overflows its row (RF-13: «Tipo de cuenta: Competidores» was cut
    in a ~730 px panel): it may shrink to the row, and only the value then ends in «…»,
    with the whole value in `title`."""
    on = _axis_on(axis)
    value = _axis_value(axis)
    return rx.button(
        rx.text(AXIS_LABELS[axis], size="2", weight="regular", color=T.TEXT_MUTED, as_="span"),
        rx.text(
            value,
            size="2",
            weight="medium",
            as_="span",
            truncate=True,
            min_width="0",
            color=rx.cond(on, T.tone_color("accent", 11), T.TEXT_STRONG),
        ),
        rx.icon("chevron-down", size=T.ICON_SM, flex_shrink="0", aria_hidden="true"),
        type="button",
        variant=rx.cond(on, "soft", "surface"),
        size="3",
        min_height=_TARGET,
        max_width="100%",
        aria_label=AXIS_LABELS[axis] + ": " + value,
        title=AXIS_LABELS[axis] + ": " + value,
        **props,
    )


def _dropdown(axis: str) -> rx.Component:
    """A desktop filter: a button that opens its options under it (Radix popover, the
    skin's glass; Escape gives the focus back to the button)."""
    options = _account_options() if axis == AXIS_ACCOUNT else _single_options(axis, close=True)
    return rx.popover.root(
        rx.popover.trigger(_filter_button(axis)),
        rx.popover.content(
            options,
            side="bottom",
            align="start",
            size="1",
            min_width="15rem",
            max_height="22rem",
            overflow_y="auto",
        ),
    )


#: The phone's chips carry `data-sheet-chip="1"` on the one that opened the last sheet;
#: closing the sheet (Escape, the backdrop, «Cerrar», «Listo» or a choice) gives the
#: focus back to it (RF-13, UX of #810).
SHEET_FOCUS_SCRIPT = (
    "window.setTimeout(function () {"
    "  var b = document.querySelector('[data-sheet-chip=\"1\"]');"
    "  if (b && b.offsetParent !== null) { b.focus(); }"
    "}, 0);"
)


def _chip(axis: str) -> rx.Component:
    """A phone filter: a chip that opens its sheet from the bottom."""
    S = DiscoverReelsState
    return _filter_button(
        axis,
        on_click=S.open_sheet(axis),
        aria_haspopup="dialog",
        aria_expanded=rx.cond(S.sheet == axis, "true", "false"),
        custom_attrs={"data-sheet-chip": rx.cond(S.sheet_chip == axis, "1", "0")},
    )


def _reset_button() -> rx.Component:
    """«Restablecer filtros»: shown while some filter narrows the lists — a `ghost`
    button of the skin, at the end of the filters."""
    return rx.cond(
        DiscoverReelsState.filters_on,
        rx.button(
            rx.icon("rotate-ccw", size=T.ICON_SM, aria_hidden="true"),
            reels_filters_vm.RESET_LABEL,
            type="button",
            variant="ghost",
            size="3",
            min_height=_TARGET,
            margin="0",
            on_click=DiscoverReelsState.reset_filters,
        ),
    )


def _sheet() -> rx.Component:
    """The phone's sheet of the chip that was tapped: its options, «Restablecer filtros»
    and «Listo». A single-choice option closes it; «Cuenta» stays open to pick several.
    However it closes, the focus goes back to the chip that opened it."""
    S = DiscoverReelsState
    foot = rx.hstack(
        rx.button(
            reels_filters_vm.RESET_LABEL,
            variant="ghost",
            size="3",
            min_height=_TARGET,
            margin="0",
            on_click=S.reset_filters,
            disabled=~S.filters_on,
        ),
        rx.spacer(),
        rx.button(
            reels_filters_vm.DONE_LABEL,
            size="3",
            min_height=_TARGET,
            on_click=S.close_sheet,
        ),
        width="100%",
        align="center",
    )
    return drawer(
        rx.match(
            S.sheet,
            (AXIS_NETWORK, _single_options(AXIS_NETWORK, close=False)),
            (AXIS_KIND, _single_options(AXIS_KIND, close=False)),
            (AXIS_ACCOUNT, _account_options()),
            (AXIS_DURATION, _single_options(AXIS_DURATION, close=False)),
            rx.fragment(),
        ),
        open=S.sheet != "",
        on_open_change=S.sheet_changed,
        title=S.sheet_title,
        footer=foot,
        side="bottom",
        on_close_auto_focus=rx.call_script(SHEET_FOCUS_SCRIPT).prevent_default,
    )


def _filter_bar() -> rx.Component:
    """RF-02's bar, as TikTok Creative Center's Top Ads: «Canal», «Tipo de cuenta»,
    «Cuenta», «Duración» and «Restablecer filtros». From 480 px up, dropdowns; on a
    phone, chips (wrapping onto a second row, none hidden) that open a sheet from the
    bottom. Every change is one more read of what is stored — never a paid call. RF-13:
    no box behind it, and only the system's pieces (Radix buttons, popovers, `drawer`)."""
    axes = (*_SINGLE_AXES, AXIS_ACCOUNT, AXIS_DURATION)
    return rx.box(
        rx.flex(
            *(_dropdown(axis) for axis in axes),
            _reset_button(),
            # RF-05, option A: «Tus competidores» after the filters, set apart
            rx.cond(
                DiscoverReelsState.competitor_rows.length() > 0,
                rx.separator(orientation="vertical", size="1"),
            ),
            _rivals_button(chip=False),
            display=_WIDE,
            wrap="wrap",
            align="center",
            spacing="2",
            width="100%",
        ),
        rx.flex(
            *(_chip(axis) for axis in axes),
            _reset_button(),
            _rivals_button(chip=True),
            display=_PHONE,
            wrap="wrap",
            align="center",
            spacing="2",
            width="100%",
        ),
        _sheet(),
        _competitors_drawer(bottom=False),
        _competitors_drawer(bottom=True),
        role="search",
        aria_label=reels_filters_vm.BAR_LABEL,
        width="100%",
    )


def _empty_lists() -> rx.Component:
    """Nothing left with these filters — never a mute list: competitors before any of
    their reels is read (RF-05), a brand that marked none, or the ticket's «No hay reels con estos
    filtros», each with the way out."""
    S = DiscoverReelsState
    reset = rx.button(
        rx.icon("rotate-ccw", size=14, aria_hidden="true"),
        reels_filters_vm.RESET_LABEL,
        variant="soft",
        size="3",
        on_click=S.reset_filters,
    )
    return rx.match(
        S.empty_kind,
        (
            EMPTY_COMPETITORS,
            empty_state(
                "users",
                reels_filters_vm.COMPETITORS_EMPTY_TITLE,
                reels_filters_vm.COMPETITORS_EMPTY_BODY,
                rx.button(
                    reels_filters_vm.COMPETITORS_EMPTY_ACTION,
                    variant="soft",
                    size="3",
                    on_click=S.show_inspiring,
                ),
            ),
        ),
        (
            EMPTY_NO_COMPETITORS,
            empty_state(
                "users",
                reels_filters_vm.NO_COMPETITORS_TITLE,
                reels_filters_vm.NO_COMPETITORS_BODY,
                rx.link(
                    rx.button(reels_filters_vm.NO_COMPETITORS_ACTION, variant="soft", size="3"),
                    href=ACCOUNTS_HREF,
                ),
            ),
        ),
        (
            EMPTY_FILTERS,
            rx.center(
                rx.vstack(
                    rx.icon("search-x", size=T.ICON_LG, color=T.TEXT_FAINT, aria_hidden="true"),
                    rx.text(reels_filters_vm.EMPTY_FILTERED, size="3", text_align="center"),
                    reset,
                    spacing="3",
                    align="center",
                ),
                padding=T.PAD_EMPTY,
                width="100%",
                class_name="q-empty",
            ),
        ),
        (EMPTY_NO_IDEAS, _no_ideas_left()),
        rx.fragment(),
    )


def _no_ideas_left() -> rx.Component:
    """No idea of the run is left with no filter on (their accounts are now «No va
    contigo»): says so with the way on, «Elegir cuentas» — never a dead end (UX review 2).
    Alone when nothing else is left; over the reviewed reels when some are (RF-13)."""
    return rx.vstack(
        rx.text(reels_filters_vm.NO_IDEAS_LEFT, size="2", color=T.TEXT_MUTED),
        rx.link(
            rx.button(reels_filters_vm.NO_IDEAS_LEFT_ACTION, variant="soft", size="3"),
            href=ACCOUNTS_HREF,
        ),
        spacing="3",
        align_items="start",
        width="100%",
    )


def _pager() -> rx.Component:
    """«Ver más» under the one list (RF-13): the next `LIST_PAGE` reviewed reels, while
    more exist; its error, when the read failed, above it."""
    S = DiscoverReelsState
    return rx.vstack(
        rx.cond(S.more_error != "", callout(S.more_error, "error")),
        rx.cond(
            S.has_more,
            rx.button(
                rx.cond(S.more_loading, loading_spinner("sm"), rx.icon("chevron-down", size=14)),
                rx.cond(S.more_loading, reels_filters_vm.MORE_BUSY, reels_filters_vm.MORE_BUTTON),
                variant="soft",
                size="3",
                min_height="44px",
                on_click=S.load_more,
                disabled=S.more_loading,
                aria_busy=rx.cond(S.more_loading, "true", "false"),
            ),
            # nothing left to page: the list ends saying when the next ideas come (RF-13;
            # the list has no heading any more) — only when there is a Monday to give
            rx.cond(
                S.end_note != "",
                rx.text(S.end_note, size="2", color=T.TEXT_MUTED, text_align="center"),
            ),
        ),
        spacing="2",
        width="100%",
        align="center",
    )


def _ideas() -> rx.Component:
    """The notice of a newer run that failed — «No pudimos traer ideas nuevas», in the info
    tone (founder, 2026-11-04): the ideas below are still true and there is nothing to
    fix — then the filter bar and, under it, ONE list (RF-13, Deivid 2026-11-25): no
    heading, the ideas first (with «Hacer uno parecido») and then the other reels the
    check kept (without it), `LIST_PAGE` at a time with «Ver más» — or, when the filters
    leave nothing, the message that says why and how to go back."""
    S = DiscoverReelsState
    grid = rx.box(
        rx.foreach(S.reels, _reel_tile),
        rx.foreach(S.more_reels, lambda reel: _reel_tile(reel, more=True)),
        class_name="q-dr-grid",
        role="list",
        aria_label="Ideas para tus reels",
    )
    lists = rx.cond(
        S.empty_kind != "",
        _empty_lists(),
        rx.vstack(
            # no idea left, but reviewed reels are: they show, and the owner is told why
            # none offers «Hacer uno parecido» and how to get ideas again
            # with filters on and no idea left that can be made again, the same place
            # says so; «Restablecer filtros» is in the bar (ux-designer, Deivid 2026-11-26)
            rx.cond(
                S.no_ideas_left,
                _no_ideas_left(),
                rx.cond(
                    S.no_ideas_filtered,
                    rx.text(reels_filters_vm.NO_IDEAS_FILTERED, size="2", color=T.TEXT_MUTED),
                ),
            ),
            grid,
            _pager(),
            spacing="4",
            width="100%",
        ),
    )
    return rx.vstack(
        rx.cond(
            S.notice_title != "",
            callout(
                rx.fragment(rx.text.strong(S.notice_title), rx.el.br(), S.notice_body),
                "info",
            ),
        ),
        _filter_bar(),
        # RF-05: the competitors' clock, outside their drawer — it keeps following a
        # manual read with the drawer closed (and says how it ended in a toast)
        rx.cond(S.competitors_reading, _ticker(S.refresh_competitors)),
        rx.box(
            lists,
            # a filtered read in flight: the list dims and takes no clicks until it lands
            opacity=rx.cond(S.filtering, "0.55", "1"),
            pointer_events=rx.cond(S.filtering, "none", "auto"),
            transition=f"opacity {T.DUR} {T.EASE}",
            aria_busy=rx.cond(S.filtering, "true", "false"),
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def _read_state(row: rx.Var[dict[str, str]]) -> rx.Component:
    """Under a row, today's «Ver sus reels ahora»: reading, done, a limit or a failure, in
    the tone of each (`reels_competitors_vm.STATE_TONES`)."""
    message = row["message"].to(str)
    return rx.match(
        row["tone"],
        ("info", callout(message, "info")),
        ("ok", callout(message, "ok")),
        ("warn", callout(message, "warn")),
        ("error", callout(message, "error")),
        rx.fragment(),
    )


def _competitor_row(row: rx.Var[dict[str, str]]) -> rx.Component:
    """One competitor: a 44 px checkbox row («leemos cada lunes») and, outside the 6,
    «Ver sus reels ahora». The button drops under the name on a phone."""
    S = DiscoverReelsState
    key = row["key"].to(str)
    weekly = row["weekly"].to(str) != ""
    busy = S.competitor_busy == key
    read_now = rx.button(
        rx.cond(busy, loading_spinner("sm"), rx.icon("play", size=14, aria_hidden="true")),
        reels_competitors_vm.READ_NOW,
        variant="soft",
        size="2",
        min_height="44px",
        on_click=S.read_competitor(key),
        disabled=(S.competitor_busy != "") | (row["state"].to(str) == STATE_READING),
        aria_busy=rx.cond(busy, "true", "false"),
        aria_label=reels_competitors_vm.READ_NOW + ": " + row["label"].to(str),
    )
    return rx.vstack(
        rx.flex(
            rx.box(
                _option_row(
                    row["label"].to(str),
                    weekly,
                    S.toggle_weekly(key),
                    role="checkbox",
                    detail=row["detail"].to(str),
                ),
                flex="1 1 14rem",
                min_width="0",
            ),
            rx.cond(weekly, rx.fragment(), read_now),
            wrap="wrap",
            align="center",
            spacing="2",
            width="100%",
        ),
        _read_state(row),
        spacing="1",
        width="100%",
        role="listitem",
    )


#: The bar's «Tus competidores» button (desktop) and chip (phone): the drawer gives the
#: focus back to whichever of the two is on screen when it closes.
RIVALS_BUTTON_ID = "reels-rivals"
RIVALS_CHIP_ID = "reels-rivals-chip"
RIVALS_FOCUS_SCRIPT = (
    "window.setTimeout(function () {"
    f" var ids = ['{RIVALS_BUTTON_ID}', '{RIVALS_CHIP_ID}'];"
    " for (var i = 0; i < ids.length; i++) {"
    "  var b = document.getElementById(ids[i]);"
    "  if (b && b.offsetParent !== null) { b.focus(); return; }"
    " }"
    "}, 0);"
)


def _rivals_button(*, chip: bool) -> rx.Component:
    """«Tus competidores» at the end of the bar (option A, Deivid 2026-11-25): opens the
    drawer — from the right on a desktop, from the bottom on a phone. While a manual read
    is in flight it shows the spinner instead of its icon. Not drawn for a brand that
    marked no competitor (RF-02's empty message tells it how). RF-13: a `surface` Radix
    button of the skin, like the filters beside it."""
    S = DiscoverReelsState
    return rx.cond(
        S.competitor_rows.length() > 0,
        rx.button(
            rx.cond(
                S.competitors_reading,
                loading_spinner("sm"),
                rx.icon("users", size=T.ICON_SM, aria_hidden="true"),
            ),
            reels_competitors_vm.PICKER_TITLE,
            type="button",
            id=RIVALS_CHIP_ID if chip else RIVALS_BUTTON_ID,
            on_click=S.open_competitors(chip),
            variant="surface",
            size="3",
            min_height=_TARGET,
            aria_label=S.competitors_label,
            aria_haspopup="dialog",
            aria_expanded=rx.cond(S.competitors_open, "true", "false"),
        ),
    )


def _competitors_drawer(*, bottom: bool) -> rx.Component:
    """The competitors panel in the system's `drawer`: the same rows (ticking saves the
    brand's labels; «Ver sus reels ahora» only queues the read, the reels-worker pays
    inside the daily cap) and «Listo». Its clock is NOT here (`_ideas` mounts it), so
    closing the drawer never stops a read's follow-up."""
    S = DiscoverReelsState
    body = rx.vstack(
        signal_pill(S.competitors_count, "accent"),
        rx.cond(S.competitor_error != "", callout(S.competitor_error, "warn")),
        rx.vstack(
            rx.foreach(S.competitor_rows, _competitor_row),
            spacing="2",
            width="100%",
            role="list",
            aria_label=reels_competitors_vm.PICKER_TITLE,
        ),
        spacing="3",
        width="100%",
    )
    foot = rx.hstack(
        rx.spacer(),
        rx.button(
            reels_filters_vm.DONE_LABEL,
            size="3",
            min_height="44px",
            on_click=S.close_competitors,
        ),
        width="100%",
        align="center",
    )
    shown = S.competitors_bottom if bottom else ~S.competitors_bottom
    return drawer(
        body,
        open=S.competitors_open & shown,
        on_open_change=S.competitors_changed,
        title=reels_competitors_vm.PICKER_TITLE,
        description=reels_competitors_vm.PICKER_BODY,
        footer=foot,
        side="bottom" if bottom else "right",
        on_close_auto_focus=rx.call_script(RIVALS_FOCUS_SCRIPT).prevent_default,
    )


def _action() -> rx.Component:
    """The empty state's one button, doing what the view model says (`action_to`):
    - «Elegir cuentas», «Completar tu marca», «Sumar cuentas»: «Negocios parecidos al tuyo»
      on the brand page, open, with «‹ Ideas de videos» to come back (UX review 4) — its
      search is also what tells Qualify what the business sells;
    - «Ver si ya están»: one more read of what is stored — free;
    - «Crear una publicación»: back to the create flow (UX re-check 1)."""
    S = DiscoverReelsState
    label = S.action
    return rx.match(
        S.action_to,
        (
            reels_ideas_vm.ACTION_ACCOUNTS,
            rx.link(rx.button(label, variant="soft", size="3"), href=ACCOUNTS_HREF),
        ),
        (
            reels_ideas_vm.ACTION_REREAD,
            rx.button(label, variant="soft", size="3", on_click=S.load),
        ),
        (
            reels_ideas_vm.ACTION_CREATE,
            rx.button(
                label,
                variant="soft",
                size="3",
                on_click=CreativeState.open_create_options,
                disabled=CreativeState.gen_generating,
            ),
        ),
        rx.fragment(),
    )


def _empty(icon: str) -> rx.Component:
    """The empty state on screen: its words, and its one button when it has one."""
    S = DiscoverReelsState
    return empty_state(icon, S.title, S.body, rx.cond(S.action != "", _action()))


def _ticker(on_change: Any = None) -> rx.Component:
    """The browser clock: every `POLL_SECONDS` it asks for one more read
    (`DiscoverReelsState.tick`). It lives only while the screen waits — leaving it, or the
    end of the wait, unmounts it — and it is the browser's, so a deploy that restarts the
    server never leaves a screen without it. Nothing of it is seen or read. RF-05's panel
    mounts the same clock on `refresh_competitors` while a manual read is in flight."""
    return rx.moment(
        interval=int(POLL_SECONDS * 1000),
        on_change=on_change if on_change is not None else DiscoverReelsState.tick,
        display="none",
        aria_hidden="true",
    )


def _preparing() -> rx.Component:
    """The first run is being prepared (option A): work in progress, so a spinner over
    the sentence that says it (`docs/design-system.md` §5.4), centred like
    `empty_state`."""
    S = DiscoverReelsState
    return rx.center(
        rx.vstack(
            loading_spinner("md"),
            rx.heading(S.title, size="5", as_="h2", text_align="center"),
            rx.text(S.body, size="2", color=T.TEXT_MUTED, text_align="center", max_width="440px"),
            spacing="3",
            align="center",
        ),
        padding=T.PAD_EMPTY,
        width="100%",
        flex="1",
    )


def _loading() -> rx.Component:
    """The stored ideas are being read: content loading, so skeletons in the shape of
    the cards (`docs/design-system.md` §5.4), never a spinner."""
    return rx.box(
        *(skeleton_card(lines=4) for _ in range(3)),
        class_name="q-dr-grid",
    )


def _load_failed() -> rx.Component:
    """The stored ideas could not be read: the error replaces the list, with the button
    that reads them again (a database read — it never searches nor pays)."""
    return rx.vstack(
        callout(DiscoverReelsState.load_error, "error"),
        rx.button(
            rx.icon("refresh-cw", size=14),
            reels_ideas_vm.RETRY,
            variant="soft",
            on_click=DiscoverReelsState.load,
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _body() -> rx.Component:
    S = DiscoverReelsState
    return rx.cond(
        S.load_error != "",
        _load_failed(),
        rx.match(
            S.screen,
            ("", _loading()),
            (SCREEN_IDEAS, _ideas()),
            (SCREEN_NO_ACCOUNTS, _empty("users")),
            (SCREEN_NO_BRIEF, _empty("store")),
            (SCREEN_CHECK_FAILED, _empty("clock")),
            (SCREEN_NO_IDEAS, _empty("film")),
            (SCREEN_UNAVAILABLE, _empty("calendar-clock")),
            (SCREEN_PREPARING, _preparing()),
            (SCREEN_SLOW, _empty("hourglass")),
            _loading(),
        ),
    )


def discover_view() -> rx.Component:
    """The centre of /create when «Descubrir reels» is chosen. Opening it reads only what
    is stored (ADR 42 R7): the ideas show at once, nothing is searched or paid; leaving it
    stops the browser clock with it."""
    return card(
        rx.vstack(
            rx.cond(
                DiscoverReelsState.replicate_error != "",
                callout(DiscoverReelsState.replicate_error, "error"),
            ),
            _body(),
            # the one browser clock, while the screen waits (`DiscoverReelsState.waiting`)
            rx.cond(DiscoverReelsState.waiting & (DiscoverReelsState.load_error == ""), _ticker()),
            spacing="4",
            width="100%",
            flex="1",
        ),
        padding="1.25rem",
        width="100%",
        flex="1",
        display="flex",
        on_mount=DiscoverReelsState.load,
        on_unmount=DiscoverReelsState.leave,
    )
