"""Reflex state for Galería's WhatsApp layer (m-25017357, ADR 48): the per-product badges
and editor block, «Subir / Actualizar en WhatsApp» on one product, «Actualizar mi
catálogo de WhatsApp» with its confirmation, progress and summary, and the way to ask the
Qualify team when there is no catalog or the permission was lost.

Custody rules, as in `catalog_state.py`:

- Holds only plain values (str/int/bool dicts and lists), never service records.
- Tenant from `AuthState.session_tenant_id` (through `tenant.tenant_uuid`), the brand is
  the tenant's one brand, the acting user its owner — never anything from the client.
- Every provider call blocks (Postgres): background handlers run them in a thread.
- Nothing is uploaded on save or by itself: every upload is the owner's tap.

The grid and the editor live in `CatalogState`; this state keeps its per-product values in
dicts keyed by product id, which the page indexes with the card's or the editor's id, and
writes the «con problemas» filter's ids into `CatalogState` (its `visible_products`).
While items are on their way it re-reads every `WATCH_EVERY_S` (as the Galería section
does for its videos) and stops when nothing is in flight or the owner leaves the page.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.support import InvalidSupportRequest

from . import catalog_whatsapp_vm as vm
from .auth_state import AuthState
from .catalog_state import CatalogState
from .catalog_vm import ProductVM
from .catalog_whatsapp_provider import (
    CatalogMediaUnavailable,
    CatalogNotConnected,
    CatalogPermissionMissing,
    CatalogSyncError,
    PlanChanged,
    PlanVM,
    ProductNotEligible,
    ProductNotFound,
    SyncViewVM,
    load_view,
    plan_all,
    product_names,
    request_team,
    send_all,
    update_one,
    upload_one,
)
from .creative_provider import acting_user_id, default_brand_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

#: How often the layer re-reads while items are on their way, and for how long at most.
WATCH_EVERY_S = 4.0
WATCH_MAX_S = 15 * 60
_TOAST_MS = 4000
#: This process: a `_watching` flag written by another one (a deploy, a restart) belongs
#: to a loop that died with it, and `arrive` clears it (as `CatalogGalleryState` does).
_PROCESS = uuid4().hex


class CatalogWhatsAppState(rx.State):
    """Galería's products in the owner's WhatsApp catalog."""

    #: "" until the first read, then `none` / `connected` / `missing_permission` /
    #: `auth_error`. A failed read leaves "" (the layer hides; the list never breaks).
    connection: str = ""

    # -- per product (keyed by product id) ----------------------------------------------
    card_kind: dict[str, str] = {}
    card_text: dict[str, str] = {}
    ed_badge: dict[str, str] = {}
    ed_tone: dict[str, str] = {}
    ed_icon: dict[str, str] = {}
    ed_help: dict[str, str] = {}
    ed_action: dict[str, str] = {}
    #: The products in WhatsApp now (the delete dialog says it will leave WhatsApp).
    live_ids: list[str] = []
    #: The product whose «Subir / Actualizar» is on its way to the service.
    acting: str = ""
    #: A refusal of the last one-product action, and for which product.
    ed_error: str = ""
    ed_error_for: str = ""

    # -- the bulk block over «Productos» --------------------------------------------------
    bulk_text: str = ""
    bulk_tone: str = "info"
    bulk_button: str = ""
    bulk_error: str = ""
    problem_count: int = 0
    first_time: bool = True
    running: bool = False
    progress_done: int = 0
    progress_total: int = 0
    summary_text: str = ""
    summary_tone: str = "ok"
    _run_counts: list[int] = [0, 0, 0]

    # -- the confirmation ----------------------------------------------------------------
    planning: bool = False
    confirming: bool = False
    dialog_open: bool = False
    dialog_title: str = ""
    dialog_lines: list[str] = []
    dialog_removal: str = ""
    dialog_footer: str = ""
    dialog_confirm: str = ""
    dialog_notice: str = ""
    _plan_key: str = ""

    # -- «Pedir mi catálogo» / «Escribir al equipo» --------------------------------------
    team_busy: bool = False
    team_sent: bool = False
    team_notice: str = ""
    team_error: str = ""

    # -- reading ---------------------------------------------------------------------------
    #: product id → the verb the owner tapped in this tab, until it is no longer in flight
    #: (then «"{nombre}" ya está en WhatsApp»).
    _watch_products: dict[str, str] = {}
    _brand_id: str = ""
    _on_page: bool = False
    _watching: bool = False
    _process: str = ""

    # -- derived ---------------------------------------------------------------------------

    @rx.var
    def connected(self) -> bool:
        return self.connection == vm.CONNECTED

    @rx.var
    def lost_access(self) -> bool:
        return self.connection in vm.LOST_ACCESS

    @rx.var
    def not_connected(self) -> bool:
        return self.connection == vm.NOT_CONNECTED

    @rx.var
    def shows_products(self) -> bool:
        """Badges and the editor block exist only with a catalog (no state is shown for
        what the owner cannot use yet)."""
        return self.connected or self.lost_access

    @rx.var
    def progress_title(self) -> str:
        return vm.progress_title(self.progress_done, self.progress_total)

    @rx.var
    def progress_value(self) -> int:
        return vm.progress_value(self.progress_done, self.progress_total)

    # -- session -----------------------------------------------------------------------------

    async def _current_tenant(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        return tenant_uuid(session_tenant_id) if session_tenant_id else None

    async def _session_ids(self) -> tuple[UUID, UUID] | None:
        """(tenant, brand) or None (CatalogState already says why on the page)."""
        tenant_id = await self._current_tenant()
        if tenant_id is None:
            return None
        async with self:
            cached = self._brand_id
        if cached:
            return tenant_id, UUID(cached)
        brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
        if brand_id is None:
            return None
        async with self:
            self._brand_id = str(brand_id)
        return tenant_id, brand_id

    # -- applying a read ---------------------------------------------------------------------

    def _apply(
        self, view: SyncViewVM, products: Sequence[ProductVM], catalog: Any, *, announce: bool
    ) -> list[rx.event.EventSpec]:
        """Paint one read. Returns the toasts for the products the owner sent from this
        tab that just arrived (only when `announce`: the watch loop's own reads)."""
        photo_counts = {p.product_id: p.photo_count for p in products}
        screen = vm.screen_view(view.connection, view.states, photo_counts)
        self.connection = view.connection
        self.card_kind = screen.card_kind
        self.card_text = screen.card_text
        self.ed_badge = {k: e.badge for k, e in screen.editor.items()}
        self.ed_tone = {k: e.tone for k, e in screen.editor.items()}
        self.ed_icon = {k: e.icon for k, e in screen.editor.items()}
        self.ed_help = {k: e.help for k, e in screen.editor.items()}
        self.ed_action = {k: e.action for k, e in screen.editor.items()}
        self.live_ids = [
            k
            for k, kind in screen.card_kind.items()
            if kind in (vm.CARD_SYNCED, vm.CARD_OUT_OF_DATE)
        ]
        self.bulk_text = screen.bulk.text
        self.bulk_tone = screen.bulk.tone
        self.bulk_button = screen.bulk.button
        self.problem_count = len(screen.problem_ids)
        self.first_time = not screen.counts.ever_sent
        catalog.wa_problem_ids = list(screen.problem_ids)
        missing_photo = {p.product_id for p in products if p.photo_count == 0}
        # «Ver los {m} con problemas» already includes the products without a photo: the
        # two filters never show at once (§3)
        catalog.wa_hides_photo_filter = bool(screen.problem_ids) and missing_photo <= set(
            screen.problem_ids
        )
        if not screen.problem_ids:
            catalog.only_wa_problems = False

        in_flight = sum(1 for s, _ in view.states.values() if s in vm.IN_FLIGHT)
        run = view.last_run
        events: list[rx.event.EventSpec] = []
        if not self.running and run is not None and run.trigger == "sync_all":
            if run.status not in vm.RUN_DONE and in_flight:
                # an update started elsewhere (another tab, before a reload): follow it
                self.running = True
                self.progress_total = run.upserts + run.deletes
                self._run_counts = [run.upserts, 0, run.deletes]
        if self.running:
            self.progress_total = max(self.progress_total, in_flight)
            self.progress_done = max(self.progress_total - in_flight, 0)
            if not in_flight and (run is None or run.status in vm.RUN_DONE):
                self.running = False
                new, changed, deletes = (self._run_counts + [0, 0, 0])[:3]
                summary = vm.run_summary(
                    status=run.status if run is not None else "finished",
                    new=new,
                    changed=changed,
                    deletes=deletes,
                    failed=run.items_failed if run is not None else 0,
                    error_code=run.error_code if run is not None else None,
                )
                self.summary_text = summary.text
                self.summary_tone = summary.tone
                if summary.problems == 0 and announce:
                    events.append(rx.toast.success(vm.UP_TO_DATE_TOAST, duration=_TOAST_MS))
        if announce and self._watch_products:
            names = {p.product_id: p.name for p in products}
            for tone, text in vm.finished_toasts(self._watch_products, view.states, names):
                toast = rx.toast.success if tone == "ok" else rx.toast.error
                events.append(toast(text, duration=_TOAST_MS))
            self._watch_products = {
                pid: verb
                for pid, verb in self._watch_products.items()
                if view.states.get(pid, ("", None))[0] in vm.IN_FLIGHT
            }
        return events

    async def _read(
        self, tenant_id: UUID, brand_id: UUID, *, announce: bool = True
    ) -> tuple[bool, list[rx.event.EventSpec]]:
        """Read and paint; (something still in flight, toasts). A read started before a
        business switch never paints into the other business."""
        try:
            view = await asyncio.to_thread(load_view, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — a failed read hides the layer, never the list
            logger.error("whatsapp catalog view failed: %s", type(exc).__name__)
            return False, []
        if await self._current_tenant() != tenant_id:
            return False, []
        async with self:
            catalog = await self.get_state(CatalogState)
            catalog.wa_ready = True
            events = self._apply(view, catalog.products, catalog, announce=announce)
        flying = any(s in vm.IN_FLIGHT for s, _ in view.states.values())
        return flying, events

    # -- arrive, load, watch -----------------------------------------------------------------

    @rx.event
    def arrive(self) -> rx.event.EventSpec:
        """The Galería page mounted."""
        self._on_page = True
        if self._process != _PROCESS:
            self._watching = False
            self.acting = ""
            self.planning = False
            self.confirming = False
            self.team_busy = False
            self._process = _PROCESS
        self.bulk_error = ""
        self.ed_error = ""
        return CatalogWhatsAppState.load

    @rx.event
    def leave(self) -> None:
        self._on_page = False
        self.dialog_open = False

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec]:
        ids = await self._session_ids()
        if ids is None:
            return
        flying, events = await self._read(*ids)
        for event in events:
            yield event
        if flying:
            yield CatalogWhatsAppState.watch

    @rx.event(background=True)
    async def watch(self) -> AsyncIterator[rx.event.EventSpec]:
        """Re-read every `WATCH_EVERY_S` while something is on its way; stops when nothing
        is in flight, the owner leaves the page, or after `WATCH_MAX_S`."""
        async with self:
            if self._watching:
                return  # one loop per tab
            self._watching = True
            self._process = _PROCESS
        try:
            ids = await self._session_ids()
            if ids is None:
                return
            deadline = time.monotonic() + WATCH_MAX_S
            while time.monotonic() < deadline:
                await asyncio.sleep(WATCH_EVERY_S)
                async with self:
                    if not self._on_page:
                        return
                flying, events = await self._read(*ids)
                for event in events:
                    yield event
                if not flying:
                    return
        finally:
            async with self:
                self._watching = False

    # -- one product -----------------------------------------------------------------------

    @rx.event
    async def act(self, product_id: str) -> rx.event.EventSpec | None:
        """The editor's button. With unsaved changes, «Guardar y subir a WhatsApp» saves
        first: `CatalogState.save_product` chains `send_one` once the save lands."""
        product_id = str(product_id)
        action = self.ed_action.get(product_id, "")
        if self.acting or action not in (vm.ACTION_UPLOAD, vm.ACTION_UPDATE, vm.ACTION_RETRY):
            return None
        if not self.connected:
            return None
        catalog = await self.get_state(CatalogState)
        if catalog.selected_id == product_id and catalog.edit_dirty:
            if action != vm.ACTION_UPLOAD:
                return None  # the page only offers «Guardar y subir» for a new one
            catalog._wa_after_save = product_id
            return CatalogState.save_product
        return CatalogWhatsAppState.send_one(product_id)

    @rx.event(background=True)
    async def send_one(self, product_id: str) -> AsyncIterator[rx.event.EventSpec]:
        product_id = str(product_id)
        async with self:
            if self.acting:
                return
            action = self.ed_action.get(product_id, vm.ACTION_UPLOAD)
            self.acting = product_id
            self.ed_error = ""
            self.ed_error_for = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.acting = ""
                self.ed_error, self.ed_error_for = vm.NO_SESSION_ERROR, product_id
            return
        tenant_id, brand_id = ids
        error = ""
        sent = None
        try:
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
            if user_id is None:
                error = vm.NO_SESSION_ERROR
            else:
                call = upload_one if action == vm.ACTION_UPLOAD else update_one
                sent = await asyncio.to_thread(call, tenant_id, brand_id, user_id, UUID(product_id))
        except Exception as exc:  # noqa: BLE001 — every refusal becomes the owner's words
            error = refusal_text(exc)
        events: list[rx.event.EventSpec] = []
        async with self:
            self.acting = ""
            if error:
                self.ed_error, self.ed_error_for = error, product_id
                events.append(rx.toast.error(error, duration=_TOAST_MS))
            elif sent is not None and sent.run_ids:
                verb = vm.ACTION_UPLOAD if action == vm.ACTION_UPLOAD else vm.ACTION_UPDATE
                self._watch_products = {**self._watch_products, product_id: verb}
            elif sent is not None and sent.in_flight:
                events.append(rx.toast.info(vm.ALREADY_ON_ITS_WAY, duration=_TOAST_MS))
            elif sent is not None:
                events.append(rx.toast.info(vm.ALREADY_UP_TO_DATE, duration=_TOAST_MS))
        for event in events:
            yield event
        flying, toasts = await self._read(tenant_id, brand_id)
        for event in toasts:
            yield event
        if flying:
            yield CatalogWhatsAppState.watch

    # -- every product -----------------------------------------------------------------------

    def _show_plan(self, plan: PlanVM, names: dict[str, str], removed: Sequence[str]) -> None:
        dialog = vm.dialog_view(
            new=plan.new,
            changed=plan.changed,
            deletes=plan.deletes,
            not_eligible=plan.not_eligible,
            first_time=self.first_time,
            removal_names=[names[r] for r in removed if r in names],
        )
        self.dialog_title = dialog.title
        self.dialog_lines = list(dialog.lines)
        self.dialog_removal = dialog.removal
        self.dialog_footer = dialog.footer
        self.dialog_confirm = dialog.confirm
        self._plan_key = plan.plan_key
        self._run_counts = [plan.new, plan.changed, plan.deletes]

    async def _plan(
        self, tenant_id: UUID, brand_id: UUID
    ) -> tuple[PlanVM | None, dict[str, str], list[str], str]:
        """(plan, names of the removed ones, their ids, refusal in the owner's words)."""
        try:
            plan = await asyncio.to_thread(plan_all, tenant_id, brand_id)
            view = await asyncio.to_thread(load_view, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001
            return None, {}, [], refusal_text(exc)
        async with self:
            catalog = await self.get_state(CatalogState)
            active = [p.product_id for p in catalog.products]
        removed = vm.removed_ids(view.states, active)
        names: dict[str, str] = {}
        if 0 < len(removed) <= 5:
            try:
                names = await asyncio.to_thread(product_names, tenant_id, removed)
            except Exception as exc:  # noqa: BLE001 — the counts alone still say it
                logger.warning("removed product names failed: %s", type(exc).__name__)
        return plan, names, removed, ""

    @rx.event(background=True)
    async def open_dialog(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Actualizar mi catálogo de WhatsApp»: the counts first, nothing written."""
        async with self:
            if self.planning or self.confirming or self.running:
                return
            self.planning = True
            self.bulk_error = ""
            self.dialog_notice = ""
            self.summary_text = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.planning = False
                self.bulk_error = vm.NO_SESSION_ERROR
            return
        plan, names, removed, error = await self._plan(*ids)
        async with self:
            self.planning = False
            if plan is None:
                self.bulk_error = error
            elif plan.new + plan.changed + plan.deletes == 0:
                self.bulk_error = ""
            else:
                self._show_plan(plan, names, removed)
                self.dialog_open = True
            nothing = plan is not None and plan.new + plan.changed + plan.deletes == 0
        if nothing:
            yield rx.toast.info(vm.NOTHING_TO_SEND, duration=_TOAST_MS)
            flying, events = await self._read(*ids)
            for event in events:
                yield event

    @rx.event
    def set_dialog_open(self, value: bool) -> None:
        """Esc and «Volver»: nothing is sent."""
        if not value and not self.confirming:
            self.dialog_open = False
            self.dialog_notice = ""

    @rx.event(background=True)
    async def confirm_all(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Sí, actualizar»: what the owner saw, or the confirmation again with the new
        counts when something changed meanwhile (`PlanChanged`)."""
        async with self:
            if self.confirming or not self._plan_key:
                return
            self.confirming = True
            plan_key = self._plan_key
            counts = list(self._run_counts)
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.confirming = False
                self.dialog_open = False
                self.bulk_error = vm.NO_SESSION_ERROR
            return
        tenant_id, brand_id = ids
        error = ""
        sent = None
        changed = False
        try:
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
            if user_id is None:
                error = vm.NO_SESSION_ERROR
            else:
                sent = await asyncio.to_thread(send_all, tenant_id, brand_id, user_id, plan_key)
        except PlanChanged:
            changed = True
        except Exception as exc:  # noqa: BLE001
            error = refusal_text(exc)
        if changed:
            plan, names, removed, error = await self._plan(tenant_id, brand_id)
            async with self:
                self.confirming = False
                if plan is None:
                    self.dialog_open = False
                    self.bulk_error = error
                elif plan.new + plan.changed + plan.deletes == 0:
                    self.dialog_open = False
                else:
                    self._show_plan(plan, names, removed)
                    self.dialog_notice = vm.PLAN_CHANGED
            return
        async with self:
            self.confirming = False
            self.dialog_open = False
            self.dialog_notice = ""
            self._plan_key = ""
            if error:
                self.bulk_error = error
            elif sent is not None and sent.run_ids:
                self.running = True
                self.summary_text = ""
                self.progress_total = sent.upserts + sent.deletes
                self.progress_done = 0
                self._run_counts = counts
        if error:
            yield rx.toast.error(error, duration=_TOAST_MS)
        flying, events = await self._read(tenant_id, brand_id)
        for event in events:
            yield event
        if flying:
            yield CatalogWhatsAppState.watch

    @rx.event
    def dismiss_summary(self) -> None:
        self.summary_text = ""

    @rx.event
    async def toggle_problems(self) -> None:
        """«Ver los {m} con problemas» / «Ver todos los productos»."""
        catalog = await self.get_state(CatalogState)
        catalog.only_wa_problems = not catalog.only_wa_problems
        if catalog.only_wa_problems:
            catalog.only_missing_photo = False

    # -- the team --------------------------------------------------------------------------

    @rx.event(background=True)
    async def ask_team(self) -> None:
        """«Pedir mi catálogo de WhatsApp» or, after a lost permission, «Escribir al
        equipo»: one support ticket, like Configuración's (one tap files one)."""
        async with self:
            if self.team_busy or self.team_sent:
                return
            auth = await self.get_state(AuthState)
            email = (auth.user_email or "").strip()
            self.team_error = ""
            self.team_notice = ""
            if "@" not in email:
                self.team_error = vm.TEAM_NO_EMAIL
                return
            lost = self.connection in vm.LOST_ACCESS
            self.team_busy = True
        tenant_id = await self._current_tenant()
        if tenant_id is None:
            async with self:
                self.team_busy = False
                self.team_error = vm.NO_SESSION_ERROR
            return
        try:
            ticket = await asyncio.to_thread(
                lambda: request_team(
                    tenant_id,
                    contact_email=email,
                    message=vm.ASK_RECONNECT_MESSAGE if lost else vm.ASK_CATALOG_MESSAGE,
                    screen=vm.ASK_RECONNECT_SCREEN if lost else vm.ASK_CATALOG_SCREEN,
                )
            )
        except InvalidSupportRequest:
            async with self:
                self.team_busy = False
                self.team_error = vm.TEAM_NO_EMAIL
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("whatsapp catalog team request failed: %s", type(exc).__name__)
            async with self:
                self.team_busy = False
                self.team_error = vm.TEAM_FAILED
            return
        template = vm.TEAM_SENT if ticket.notified else vm.TEAM_SAVED
        async with self:
            self.team_busy = False
            self.team_sent = True
            self.team_notice = template.format(reference=ticket.reference, email=email)


def refusal_text(exc: BaseException) -> str:
    """The service's typed refusals in the owner's words (`qualify-copy-es`)."""
    if isinstance(exc, CatalogNotConnected):
        return vm.NOT_CONNECTED_ERROR
    if isinstance(exc, CatalogPermissionMissing):
        return vm.LOST_ACCESS_TEXT
    if isinstance(exc, ProductNotEligible):
        return vm.NOT_ELIGIBLE.get(exc.reason, vm.NOT_ELIGIBLE_FALLBACK)[1]
    if isinstance(exc, ProductNotFound):
        return vm.PRODUCT_GONE_ERROR
    if isinstance(exc, CatalogMediaUnavailable):
        return vm.MEDIA_UNAVAILABLE_ERROR
    if not isinstance(exc, CatalogSyncError):
        logger.error("whatsapp catalog action failed: %s", type(exc).__name__)
    return vm.DB_ERROR


async def sync_after_catalog_change(catalog: CatalogState, tenant_id: UUID, brand_id: UUID) -> None:
    """Called by `CatalogState` after it re-reads the products (a save, a delete, a new
    photo): the badges follow without waiting for a reload. Only once this layer has read
    at least once (`wa_ready`), and never fatal."""
    try:
        view = await asyncio.to_thread(load_view, tenant_id, brand_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("whatsapp catalog refresh failed: %s", type(exc).__name__)
        return
    async with catalog:
        wa = await catalog.get_state(CatalogWhatsAppState)
        wa._apply(view, catalog.products, catalog, announce=False)
