"""Reflex state for Creadores (Delivery 1: m-24946129 list, add, sheet, «Actualizar»;
m-24946132 «Comparar creadores»). Screens: `creators_page.py`, `creator_sheet_page.py`,
`creators_compare_page.py`; copy and rules: `docs/ux-creadores.md` §1-3; backend
contract: `docs/diseno-modulo-creadores.md` §10-11.

Custody, as in every business state: the tenant comes from `AuthState` (server side,
through `get_state`, never as an event argument) and the business from
`creators_provider.session_brand`; the browser holds only frozen VMs and the text being
typed; every backend call runs in a background event through `asyncio.to_thread`. An id
arriving from the browser (a checkbox, the URL) is accepted only if the loaded list
holds it — the service checks it again under RLS anyway.

**The one paid call.** `refresh_creator` runs only from a background event the owner
started («Ver cómo le va», «Actualizar», «Intentar de nuevo»), never on a page load. The
owner never sees credits: the outcome becomes a sentence (`creators_vm.refresh_outcome_vm`).

**The switch** (§11). `CreatorsAccessState.access` is ``""`` until the backend answered,
then ``"on"`` / ``"off"``. Off → the «Pronto» screen of before and the «Pronto» menu
entry; the service checks it again on every call.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID

import reflex as rx

from . import creators_provider as provider
from .auth_state import AuthState
from .creators_access import CreatorsAccessState
from .creators_vm import (
    ADD_FAILED,
    ARCHIVE_FAILED,
    COMPARE_INVALID,
    COMPARE_LOAD_FAILED,
    COMPARE_MAX,
    COMPARE_MIN,
    CREATORS_ROUTE,
    EMPTY_COMPARISON,
    EMPTY_SHEET,
    FLOW_ADD,
    IDS_PARAM,
    INVALID_HANDLE,
    LOAD_FAILED,
    NO_SESSION,
    ONLY_INSTAGRAM,
    PICK_LIMIT,
    PICK_PARAM,
    PROGRESS_STEPS,
    REVIEW_OTHER_ACCOUNT,
    SEARCH_FROM,
    SEE_RESULTS,
    SHEET_GONE,
    SHEET_LOAD_FAILED,
    TRY_AGAIN,
    UPDATE,
    ComparisonVM,
    CreatorCardVM,
    MobileColumnVM,
    SheetVM,
    archived_notice,
    at,
    compare_url,
    display_handle,
    existing_notice,
    filter_cards,
    page_counter,
    parse_ids,
    pick_button,
    pick_reason,
    refresh_outcome_vm,
    sheet_url,
)
from .nav_url import close_flow_script, flow_param, scalar_param
from .tenant import tenant_uuid
from .ui.route_history import history_ack_value, route_history_ready

logger = logging.getLogger(__name__)

#: How often the drawer's wait moves to its next stage while the read runs (a single
#: call that reports no progress: the stages are the honest order of the work).
STAGE_SECONDS = 3.0

_ACTION_RETRY = "retry"
_ACTION_OTHER = "other"
_ACTION_EXISTING = "existing"


async def _session_ids(state: rx.State) -> tuple[UUID, UUID, str] | None:
    """(tenant, business, email) of this session, or None. Module-level so the tests
    replace it in one place."""
    async with state:
        auth = await state.get_state(AuthState)
        raw_tenant = auth.session_tenant_id
        email = auth.user_email
    tenant_id = tenant_uuid(raw_tenant) if raw_tenant else None
    if tenant_id is None:
        return None
    brand_id = await asyncio.to_thread(provider.session_brand, tenant_id)
    if brand_id is None:
        return None
    return tenant_id, brand_id, email


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _ensure_access(state: rx.State, tenant_id: UUID) -> bool:
    """Ask the switch (cheap) and publish it to the menu; True when on."""
    enabled = await asyncio.to_thread(provider.creators_enabled, tenant_id)
    async with state:
        access = await state.get_state(CreatorsAccessState)
        access.access = "on" if enabled else "off"
        access._checked_for = str(tenant_id)
    return enabled


async def _access_off(state: rx.State) -> None:
    """The service said the module is off for this business: back to «Pronto»."""
    async with state:
        access = await state.get_state(CreatorsAccessState)
        access.access = "off"


async def _tell_list(state: rx.State, message: str) -> None:
    """A sentence the list shows on top when the owner lands on it (N3)."""
    async with state:
        listing = await state.get_state(CreatorsState)
        listing.notice = message
        listing.notice_href = ""


# ======================================================================================
# The list «Tus creadores» and the «Revisar un creador» drawer
# ======================================================================================


class CreatorsState(rx.State):
    loading: bool = True
    load_error: str = ""
    cards: list[CreatorCardVM] = []
    query: str = ""
    notice: str = ""
    notice_href: str = ""

    # «Comparar creadores» mode (elige de 2 a 4)
    picking: bool = False
    picked: list[str] = []
    pick_error: str = ""

    # rows being read by this session (the list shows them «Revisando sus reels…»)
    working: list[str] = []

    # the drawer
    drawer_open: bool = False
    flow_ready: bool = False
    history_ack: str = ""
    handle_input: str = ""
    adding: bool = False
    adding_handle: str = ""
    stage: int = 0
    add_message: str = ""
    add_tone: str = "error"
    add_action: str = ""
    existing_id: str = ""
    _existing_handle: str = ""

    # --- computed ------------------------------------------------------------------

    @rx.var
    def shown_cards(self) -> list[CreatorCardVM]:
        return filter_cards(self.cards, self.query)

    @rx.var
    def has_cards(self) -> bool:
        return len(self.cards) > 0

    @rx.var
    def show_search(self) -> bool:
        return len(self.cards) > SEARCH_FROM

    @rx.var
    def ready_count(self) -> int:
        return sum(1 for card in self.cards if card.state == "ready")

    @rx.var
    def can_compare(self) -> bool:
        return self.ready_count >= COMPARE_MIN

    @rx.var
    def pick_count(self) -> int:
        return len(self.picked)

    @rx.var
    def pick_label(self) -> str:
        return pick_button(len(self.picked))

    @rx.var
    def pick_hint(self) -> str:
        return self.pick_error or pick_reason(len(self.picked))

    @rx.var
    def pick_ready(self) -> bool:
        return COMPARE_MIN <= len(self.picked) <= COMPARE_MAX

    @rx.var
    def submit_disabled(self) -> bool:
        return self.handle_input.strip() == "" or self.adding

    @rx.var
    def progress_title(self) -> str:
        return f"Revisando a {self.adding_handle}" if self.adding_handle else "Revisando…"

    @rx.var
    def progress_steps(self) -> list[dict[str, str]]:
        return [
            {
                "title": title,
                "status": "done"
                if index < self.stage
                else ("running" if index == self.stage else "pending"),
            }
            for index, title in enumerate(PROGRESS_STEPS)
        ]

    @rx.var
    def existing_href(self) -> str:
        return sheet_url(self.existing_id) if self.existing_id else ""

    @rx.var
    def action_label(self) -> str:
        return {
            _ACTION_RETRY: TRY_AGAIN,
            _ACTION_OTHER: REVIEW_OTHER_ACCOUNT,
            _ACTION_EXISTING: UPDATE,
        }.get(self.add_action, "")

    @rx.var
    def see_results_label(self) -> str:
        return SEE_RESULTS

    # --- loading -------------------------------------------------------------------

    def _ready_ids(self) -> set[str]:
        return {card.tracked_id for card in self.cards if card.state == "ready"}

    async def _read_cards(self, tenant_id: UUID, brand_id: UUID) -> None:
        async with self:
            working = list(self.working)
        try:
            zone = await asyncio.to_thread(provider.business_zone, tenant_id)
            cards = await asyncio.to_thread(
                provider.cards, tenant_id, brand_id, working=working, zone=zone
            )
        except provider.CreatorsUnavailable:
            async with self:
                self.cards = []
                self.loading = False
            await _access_off(self)
            return
        except Exception as exc:  # noqa: BLE001 — a failed read is a sentence, never a 500
            logger.error("creators list failed: %s", type(exc).__name__)
            async with self:
                self.load_error = LOAD_FAILED
                self.loading = False
            return
        async with self:
            self.cards = cards
            self.load_error = ""
            self.loading = False
            # A creator picked for Comparar that left the list is unpicked.
            ready = self._ready_ids()
            self.picked = [i for i in self.picked if i in ready]

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """on_load: the switch, then the list; `?comparar=<ids>` opens the «elige» mode
        with those marked (N4), `?flujo=agregar` the drawer (N5)."""
        async with self:
            self.loading = True
            self.load_error = ""
            params = self.router.url.query_parameters
            pick_raw = scalar_param(params, PICK_PARAM)
            wants_pick = PICK_PARAM in params
            wants_flow = bool(flow_param(params, FLOW_ADD, 1))
        ids = await _session_ids(self)
        if ids is None:
            async with self:
                self.load_error = NO_SESSION
                self.loading = False
            return
        tenant_id, brand_id, _email = ids
        if not await _ensure_access(self, tenant_id):
            async with self:
                self.loading = False
                self.cards = []
            return
        await self._read_cards(tenant_id, brand_id)
        async with self:
            if wants_pick:
                ready = self._ready_ids()
                self.picked = [i for i in parse_ids(pick_raw, COMPARE_MAX) if i in ready]
                self.picking = True
                self.pick_error = ""
            if wants_flow and not self.drawer_open:
                self._open()

    @rx.event(background=True)
    async def reload(self) -> None:
        ids = await _session_ids(self)
        if ids is None:
            return
        await self._read_cards(ids[0], ids[1])

    # --- notices -------------------------------------------------------------------

    @rx.event
    def dismiss_notice(self) -> None:
        self.notice = ""
        self.notice_href = ""

    @rx.event
    def set_query(self, value: str) -> None:
        self.query = value

    # --- «Comparar creadores» mode -------------------------------------------------

    @rx.event
    def start_pick(self) -> None:
        self.picking = True
        self.picked = []
        self.pick_error = ""

    @rx.event
    def cancel_pick(self) -> rx.event.EventSpec | None:
        self.picking = False
        self.picked = []
        self.pick_error = ""
        params = self.router.url.query_parameters
        if PICK_PARAM in params:
            return rx.redirect(CREATORS_ROUTE, replace=True)
        return None

    @rx.event
    def toggle_pick(self, tracked_id: str) -> None:
        if tracked_id not in self._ready_ids():
            return
        if tracked_id in self.picked:
            self.picked = [i for i in self.picked if i != tracked_id]
            self.pick_error = ""
            return
        if len(self.picked) >= COMPARE_MAX:
            self.pick_error = PICK_LIMIT
            return
        self.picked = [*self.picked, tracked_id]
        self.pick_error = ""

    @rx.event
    def go_compare(self) -> rx.event.EventSpec | None:
        if not COMPARE_MIN <= len(self.picked) <= COMPARE_MAX:
            return None
        url = compare_url(self.picked)
        self.picking = False
        return rx.redirect(url)

    # --- the drawer ----------------------------------------------------------------

    def _clear_message(self) -> None:
        self.add_message = ""
        self.add_action = ""
        self.add_tone = "error"
        self.existing_id = ""
        self._existing_handle = ""

    def _open(self) -> None:
        self.drawer_open = True
        self.flow_ready = True
        if not self.adding:
            self._clear_message()

    @rx.event
    def open_drawer(self) -> None:
        self._open()

    @rx.event
    def close_drawer(self) -> rx.event.EventSpec:
        """The ✕, Esc, the backdrop and «Cancelar». A read already running goes on: the
        row says «Revisando sus reels…» in the list (UX §2.2)."""
        self.drawer_open = False
        self.flow_ready = False
        if not self.adding:
            self._clear_message()
        return rx.call_script(close_flow_script(FLOW_ADD))

    @rx.event
    def set_drawer_open(self, value: bool) -> rx.event.EventSpec | None:
        if value:
            self._open()
            return None
        return CreatorsState.close_drawer

    @rx.event
    def enter_history(self, lease: dict) -> list[rx.event.EventSpec]:
        """Back/forward and reloads: the drawer follows `?flujo=agregar`."""
        self.history_ack = history_ack_value(lease)
        params = self.router.url.query_parameters
        if flow_param(params, FLOW_ADD, 1):
            self._open()
        else:
            self.drawer_open = False
            self.flow_ready = False
        return [route_history_ready(CREATORS_ROUTE, lease)]

    @rx.event
    def leave_flow(self) -> None:
        self.flow_ready = False
        self.drawer_open = False

    @rx.event
    def set_handle_input(self, value: str) -> None:
        self.handle_input = value
        if self.add_action != _ACTION_EXISTING:
            self.add_message = ""
            self.add_action = ""

    def _review_other(self) -> None:
        self.handle_input = ""
        self._clear_message()

    @rx.event
    def review_other(self) -> None:
        """«Revisar otra cuenta»: an empty field and no message."""
        self._review_other()

    @rx.event
    def on_action(self) -> rx.event.EventSpec | None:
        """The button inside the drawer's callout."""
        if self.add_action == _ACTION_OTHER:
            self._review_other()
            return None
        if self.add_action == _ACTION_EXISTING:
            return CreatorsState.refresh_existing
        return CreatorsState.submit

    @rx.event(background=True)
    async def submit(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Ver cómo le va»: save the creator (free), then read it (paid), in the
        background; the drawer waits on a progress panel (UX §2.2)."""
        async with self:
            raw = self.handle_input.strip()
            if not raw or self.adding:
                return
            self._clear_message()
            self.adding = True
            self.stage = 0
            self.adding_handle = display_handle(raw)
        ids = await _session_ids(self)
        if ids is None:
            async with self:
                self.adding = False
                self.add_message = NO_SESSION
            return
        tenant_id, brand_id, email = ids
        try:
            user_id = await asyncio.to_thread(provider.acting_user, tenant_id, email)
            if user_id is None:
                raise LookupError("no user")
            added = await asyncio.to_thread(provider.add, tenant_id, brand_id, raw, user_id=user_id)
        except provider.BadHandle:
            async with self:
                self.adding = False
                self.add_message = INVALID_HANDLE
            return
        except provider.WrongNetwork:
            async with self:
                self.adding = False
                self.add_message = ONLY_INSTAGRAM
            return
        except provider.CreatorsUnavailable:
            async with self:
                self.adding = False
                self.drawer_open = False
            await _access_off(self)
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("creators add failed: %s", type(exc).__name__)
            async with self:
                self.adding = False
                self.add_message = ADD_FAILED
            return

        async with self:
            already = next((c for c in self.cards if c.tracked_id == added.tracked_id), None)
            if already is not None and already.state == "ready":
                # «Ya está en tu lista»: nothing paid; the owner chooses.
                self.adding = False
                self.add_tone = "info"
                self.add_message = existing_notice(added.handle, max(already.days, 0))
                self.add_action = _ACTION_EXISTING
                self.existing_id = added.tracked_id
                self._existing_handle = added.handle
                return
            self.adding_handle = at(added.handle)
        async for event in self._read_one(
            tenant_id, brand_id, added.tracked_id, added.handle, drop_new=not added.had_read
        ):
            yield event

    @rx.event(background=True)
    async def refresh_existing(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Actualizar» from «Ya está en tu lista»."""
        async with self:
            tracked_id, handle = self.existing_id, self._existing_handle
            if not tracked_id or self.adding:
                return
            self._clear_message()
            self.adding = True
            self.stage = 0
            self.adding_handle = at(handle)
        ids = await _session_ids(self)
        if ids is None:
            async with self:
                self.adding = False
                self.add_message = NO_SESSION
            return
        async for event in self._read_one(ids[0], ids[1], tracked_id, handle, drop_new=False):
            yield event

    async def _read_one(
        self, tenant_id: UUID, brand_id: UUID, tracked_id: str, handle: str, *, drop_new: bool
    ) -> AsyncIterator[rx.event.EventSpec | None]:
        """The paid read behind the drawer. While it runs the panel walks its stages;
        if the owner closed the drawer, the list shows the row as working and the
        result arrives as a notice."""
        async with self:
            if tracked_id not in self.working:
                self.working = [*self.working, tracked_id]
        await self._read_cards(tenant_id, brand_id)
        task = asyncio.ensure_future(
            asyncio.to_thread(provider.refresh, tenant_id, brand_id, UUID(tracked_id))
        )
        while True:
            done, _pending = await asyncio.wait({task}, timeout=STAGE_SECONDS)
            if done:
                break
            async with self:
                self.stage = min(self.stage + 1, len(PROGRESS_STEPS) - 1)
        try:
            status = task.result()
        except Exception as exc:  # noqa: BLE001
            logger.error("creators refresh failed: %s", type(exc).__name__)
            status = "error"
        outcome = refresh_outcome_vm(status, handle)
        if not outcome.done and outcome.drop_new and drop_new:
            # A typo or a private account is not a creator the owner wants listed.
            try:
                await asyncio.to_thread(provider.archive, tenant_id, brand_id, UUID(tracked_id))
            except Exception as exc:  # noqa: BLE001
                logger.warning("creators drop after %s failed: %s", status, type(exc).__name__)
        async with self:
            self.working = [i for i in self.working if i != tracked_id]
            self.adding = False
            self.stage = 0
            still_open = self.drawer_open
            if outcome.done:
                self.handle_input = ""
                if still_open:
                    self.drawer_open = False
                    self.flow_ready = False
                else:
                    self.notice = f"Listo: ya puedes ver cómo le va a {at(handle)}."
                    self.notice_href = sheet_url(tracked_id)
            elif still_open:
                self.add_message = outcome.message
                self.add_tone = outcome.tone
                self.add_action = (
                    _ACTION_OTHER
                    if outcome.action == REVIEW_OTHER_ACCOUNT
                    else (_ACTION_RETRY if outcome.action == TRY_AGAIN else "")
                )
            else:
                self.notice = outcome.message
                self.notice_href = ""
        await self._read_cards(tenant_id, brand_id)
        if outcome.done and still_open:
            # N3: the result is the sheet, not a floating notice.
            yield rx.redirect(sheet_url(tracked_id))

    @rx.event(background=True)
    async def retry_card(self, tracked_id: str) -> None:
        """«Intentar de nuevo» / «Revisar ahora» on a row that has no read yet."""
        async with self:
            card = next((c for c in self.cards if c.tracked_id == tracked_id), None)
            if card is None or tracked_id in self.working:
                return
            self.working = [*self.working, tracked_id]
            self.cards = [c if c.tracked_id != tracked_id else _as_working(c) for c in self.cards]
            handle = card.handle
        ids = await _session_ids(self)
        if ids is None:
            async with self:
                self.working = [i for i in self.working if i != tracked_id]
            return
        tenant_id, brand_id, _email = ids
        try:
            status = await asyncio.to_thread(
                provider.refresh, tenant_id, brand_id, UUID(tracked_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("creators retry failed: %s", type(exc).__name__)
            status = "error"
        outcome = refresh_outcome_vm(status, handle)
        async with self:
            self.working = [i for i in self.working if i != tracked_id]
            if outcome.done:
                self.notice = f"Listo: ya puedes ver cómo le va a {at(handle)}."
                self.notice_href = sheet_url(tracked_id)
        await self._read_cards(tenant_id, brand_id)


def _as_working(card: CreatorCardVM) -> CreatorCardVM:
    return replace(card, state="working", problem="")


# ======================================================================================
# The sheet /creadores/[creator_id]
# ======================================================================================


class CreatorSheetState(rx.State):
    loading: bool = True
    load_error: str = ""
    tracked_id: str = ""
    sheet: SheetVM = EMPTY_SHEET
    has_read: bool = False
    pending_handle: str = ""
    refreshing: bool = False
    refresh_message: str = ""
    refresh_tone: str = "error"
    refresh_done: bool = False
    list_count: int = 0
    archive_open: bool = False
    archiving: bool = False
    archive_error: str = ""

    def _route_id(self) -> UUID | None:
        # the dynamic route arg (as `CampaignState._post_id` reads it)
        return _uuid(getattr(self, "creator_id", ""))

    @rx.var
    def title(self) -> str:
        if self.has_read:
            return self.sheet.title
        return self.pending_handle or "Creador"

    @rx.var
    def handle(self) -> str:
        return self.sheet.handle if self.has_read else self.pending_handle

    @rx.var
    def primary_compare(self) -> bool:
        return self.list_count >= COMPARE_MIN

    @rx.var
    def compare_href(self) -> str:
        if not self.tracked_id:
            return CREATORS_ROUTE
        return f"{CREATORS_ROUTE}?{PICK_PARAM}={self.tracked_id}"

    @rx.var
    def update_label(self) -> str:
        if self.refreshing:
            return "Actualizando…"
        return UPDATE

    async def _load(self) -> None:
        tracked_id = self._route_id()
        ids = await _session_ids(self)
        if ids is None or tracked_id is None:
            async with self:
                self.loading = False
                self.load_error = NO_SESSION if ids is None else SHEET_GONE
            return
        tenant_id, brand_id, _email = ids
        if not await _ensure_access(self, tenant_id):
            async with self:
                self.loading = False
            return
        try:
            zone = await asyncio.to_thread(provider.business_zone, tenant_id)
            cards = await asyncio.to_thread(provider.cards, tenant_id, brand_id, zone=zone)
            mine = next((c for c in cards if c.tracked_id == str(tracked_id)), None)
            sheet = (
                await asyncio.to_thread(provider.sheet, tenant_id, brand_id, tracked_id, zone=zone)
                if mine is not None
                else None
            )
        except provider.CreatorsUnavailable:
            async with self:
                self.loading = False
            await _access_off(self)
            return
        except provider.NotFound:
            async with self:
                self.loading = False
                self.load_error = SHEET_GONE
                self.has_read = False
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("creator sheet failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.load_error = SHEET_LOAD_FAILED
            return
        async with self:
            self.loading = False
            self.list_count = sum(1 for c in cards if c.state == "ready")
            self.tracked_id = str(tracked_id)
            if mine is None:
                self.load_error = SHEET_GONE
                self.sheet = EMPTY_SHEET
                self.has_read = False
                return
            self.load_error = ""
            self.sheet = sheet if sheet is not None else EMPTY_SHEET
            self.has_read = sheet is not None
            self.pending_handle = mine.handle

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            self.loading = True
            self.load_error = ""
            self.refresh_message = ""
            self.refresh_done = False
            self.archive_open = False
            self.archive_error = ""
            if self.tracked_id != str(self._route_id()):
                # another creator's sheet must never show under this address
                self.sheet = EMPTY_SHEET
                self.has_read = False
                self.pending_handle = ""
                self.list_count = 0
        await self._load()

    @rx.event(background=True)
    async def refresh(self) -> None:
        """«Actualizar»: the old sheet stays on screen while the read runs (UX §2.3)."""
        async with self:
            tracked_id = self._route_id()
            if tracked_id is None or self.refreshing:
                return
            self.refreshing = True
            self.refresh_message = ""
            self.refresh_done = False
            handle = self.handle
        ids = await _session_ids(self)
        if ids is None:
            async with self:
                self.refreshing = False
                self.refresh_message = NO_SESSION
            return
        try:
            status = await asyncio.to_thread(provider.refresh, ids[0], ids[1], tracked_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("creator refresh failed: %s", type(exc).__name__)
            status = "error"
        outcome = refresh_outcome_vm(status, handle)
        await self._load()
        async with self:
            self.refreshing = False
            self.refresh_done = outcome.done
            self.refresh_message = "" if outcome.done else outcome.message
            self.refresh_tone = outcome.tone

    @rx.event
    def ask_archive(self) -> None:
        self.archive_open = True
        self.archive_error = ""

    @rx.event
    def set_archive_open(self, value: bool) -> None:
        self.archive_open = value

    @rx.event(background=True)
    async def confirm_archive(self) -> AsyncIterator[rx.event.EventSpec | None]:
        async with self:
            tracked_id = self._route_id()
            handle = self.handle
            if tracked_id is None or self.archiving:
                return
            self.archiving = True
        ids = await _session_ids(self)
        try:
            if ids is None:
                raise LookupError("no session")
            await asyncio.to_thread(provider.archive, ids[0], ids[1], tracked_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("creator archive failed: %s", type(exc).__name__)
            async with self:
                self.archiving = False
                self.archive_error = ARCHIVE_FAILED
            return
        async with self:
            self.archiving = False
            self.archive_open = False
            self.sheet = EMPTY_SHEET
            self.has_read = False
        await _tell_list(self, archived_notice(handle))
        # N3: back to the list with the sentence on top, not a toast alone.
        yield rx.redirect(CREATORS_ROUTE)


# ======================================================================================
# Comparar /creadores/comparar?ids=…
# ======================================================================================


class CreatorsCompareState(rx.State):
    loading: bool = True
    load_error: str = ""
    comparison: ComparisonVM = EMPTY_COMPARISON
    has_comparison: bool = False
    page: int = 0
    updating: list[str] = []
    update_message: str = ""

    @rx.var
    def columns_count(self) -> int:
        return len(self.comparison.columns)

    @rx.var
    def page_count(self) -> int:
        return len(self.comparison.pages)

    @rx.var
    def visible(self) -> list[MobileColumnVM]:
        if not self.comparison.pages:
            return []
        page = self.comparison.pages[max(0, min(self.page, len(self.comparison.pages) - 1))]
        return [self.comparison.mobile[i] for i in page]

    @rx.var
    def counter(self) -> str:
        return page_counter(self.page, self.comparison.pages, len(self.comparison.columns))

    @rx.var
    def has_prev(self) -> bool:
        return self.page > 0

    @rx.var
    def has_next(self) -> bool:
        return self.page < self.page_count - 1

    @rx.var
    def is_updating(self) -> bool:
        return len(self.updating) > 0

    @rx.event
    def prev_page(self) -> None:
        self.page = max(self.page - 1, 0)

    @rx.event
    def next_page(self) -> None:
        self.page = min(self.page + 1, max(self.page_count - 1, 0))

    def _requested(self) -> list[str]:
        params = self.router.url.query_parameters
        return parse_ids(scalar_param(params, IDS_PARAM))

    async def _read(self, requested: list[str]) -> bool:
        """Load the comparison; False when the ids are not 2-4 of this business (the
        state then sends the owner back to the list with the reason)."""
        ids = await _session_ids(self)
        if ids is None:
            async with self:
                self.loading = False
                self.load_error = NO_SESSION
            return True
        tenant_id, brand_id, _email = ids
        if not await _ensure_access(self, tenant_id):
            async with self:
                self.loading = False
            return True
        if not COMPARE_MIN <= len(requested) <= COMPARE_MAX:
            return False
        try:
            zone = await asyncio.to_thread(provider.business_zone, tenant_id)
            vm = await asyncio.to_thread(
                provider.compare, tenant_id, brand_id, [UUID(i) for i in requested], zone=zone
            )
        except (provider.WrongCount, provider.NotFound):
            return False
        except provider.CreatorsUnavailable:
            async with self:
                self.loading = False
            await _access_off(self)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("creators compare failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.load_error = COMPARE_LOAD_FAILED
            return True
        if len(vm.columns) < COMPARE_MIN:
            return False
        async with self:
            self.comparison = vm
            self.has_comparison = True
            self.loading = False
            self.load_error = ""
            self.page = min(self.page, max(len(vm.pages) - 1, 0))
        return True

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec | None]:
        async with self:
            self.loading = True
            self.load_error = ""
            self.update_message = ""
            self.page = 0
            requested = self._requested()
        if not await self._read(requested):
            async with self:
                self.loading = False
            await _tell_list(self, COMPARE_INVALID)
            yield rx.redirect(CREATORS_ROUTE, replace=True)

    @rx.event(background=True)
    async def update_stale(self) -> None:
        """«Actualizar @x» / «Actualizar los 2»: the paid reads, one after the other;
        the table stays on screen and each column says «Actualizando…»."""
        async with self:
            if not self.has_comparison or self.updating:
                return
            targets = [
                (c.tracked_id, c.handle)
                for c in self.comparison.columns
                if c.tracked_id in self.comparison.stale_ids
            ]
            self.updating = [t for t, _h in targets]
            self.update_message = ""
            requested = self._requested()
        ids = await _session_ids(self)
        if ids is None:
            async with self:
                self.updating = []
                self.update_message = NO_SESSION
            return
        problems: list[str] = []
        for tracked_id, handle in targets:
            try:
                status = await asyncio.to_thread(provider.refresh, ids[0], ids[1], UUID(tracked_id))
            except Exception as exc:  # noqa: BLE001
                logger.error("creators compare refresh failed: %s", type(exc).__name__)
                status = "error"
            outcome = refresh_outcome_vm(status, handle)
            if not outcome.done:
                problems.append(outcome.message)
            async with self:
                self.updating = [i for i in self.updating if i != tracked_id]
        await self._read(requested)
        async with self:
            self.updating = []
            self.update_message = " ".join(dict.fromkeys(problems))
