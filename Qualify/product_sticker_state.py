"""«Tu producto en sticker» (m-25017912 over the backend of m-25017372): the five-step flow
in Tu marca › «Stickers y videos de tu marca». Every gateway call blocks, so it runs off the
event loop (`asyncio.to_thread`), and a read lands only for the open it belongs to (`_gen`).
A drawing being made is re-read every few seconds while the panel is open. The stickers
themselves land in the seasonal library (season «De tus productos»), where «Por aprobar» and
«Aprobados» already approve, redraw and delete them (`SeasonalState`)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .nav_url import close_flow_script, flow_param, replace_url_script, scalar_param
from .product_sticker_provider import gateway
from .product_sticker_vm import (
    ACTION_FAILED,
    BRAND_KIT_PATH,
    CREATE_PARAM_VALUE,
    DRAFTS_STICKERS_HREF,
    DRAWINGS_FAILED,
    FLOW_NAME,
    FLOW_STEPS,
    LOAD_FAILED,
    NO_MESSAGES,
    NO_SESSION,
    NO_VARIANT,
    PICK_A_DRAWING,
    RESTORE_FAILED,
    SEARCH_FROM,
    SEE_DRAFTS_LABEL,
    STARTED_TOAST,
    STEP_DRAWING,
    STEP_MESSAGE,
    STEP_MOTION,
    STEP_PRODUCT,
    STEP_REVIEW,
    STEP_TITLES,
    UNDO_BUTTON_ID,
    DrawingVM,
    ProductVM,
    ask_another_label,
    base_address,
    can_next,
    chosen_messages,
    drawing_vms,
    filter_products,
    last_message,
    message_count,
    own_message_error,
    prepare_label,
    preselection,
    product_vms,
    reachable_step,
    review_line,
    start_cost_line,
    sticker_total,
    without_photo_line,
)
from .tenant import tenant_uuid
from .ui.route_history import history_ack_value, route_history_ready

logger = logging.getLogger(__name__)

_TOAST_MS = 6000
#: A drawing takes ~30 s – 2 min: re-read this often while one is «Dibujando…».
POLL_SECONDS = 5.0
#: ≈ 10 min, then the owner can come back later (it keeps being drawn).
POLL_ROUNDS = 120
#: A request still «in flight» after this long was lost (a deploy, a restart): its flag no
#: longer holds the panel open nor blocks the buttons (review finding A).
BUSY_STALE_SECONDS = 180.0
#: After the address became the flow's own (`?crear=producto` → `?flujo=…&paso=1`), the
#: route's history handler runs again for it, with a fresh lease (`ui/route_history.py`).
#: The pop caused by closing (`history.go(-n)`) lands within this long; a later pop onto a
#: step's address (or one in a new page document) is the owner's own and opens the flow.
CLOSE_POP_SECONDS = 3.0
_REENTER_JS = (
    " window.setTimeout(() => document.querySelector('main.q-panel .q-route-pop')?.click(), 0);"
)


def _worded(exc: BaseException, what: str, fallback: str = ACTION_FAILED) -> str:
    """The backend's own Spanish `message` for its refusals, else the generic line — never
    the exception's text."""
    from qualify_api.creative.product_stickers import ProductStickerError  # noqa: PLC0415
    from qualify_api.whatsapp.seasonal import SeasonalError  # noqa: PLC0415

    if isinstance(exc, (ProductStickerError, SeasonalError)):
        return exc.message
    logger.error("product sticker %s failed: %s", what, type(exc).__name__)
    return fallback


def _renamed_presets() -> dict[str, str]:
    """Old preset words → new ones (the backend's), for the last message's pre-selection."""
    from qualify_api.creative.product_stickers import RENAMED_PRESETS  # noqa: PLC0415

    return dict(RENAMED_PRESETS)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class ProductStickerState(rx.State):
    # -- the start card -------------------------------------------------------------------
    #: creaciones per drawing, read when Tu marca mounts (0: not known)
    start_creations: int = 0
    #: why the month cannot pay a drawing («Te falta 1 creación este mes…»), on the card
    start_blocked: str = ""
    #: the start card's cost read finished (ok or not)
    start_read: bool = False

    # -- the flow ---------------------------------------------------------------------------
    flow_open: bool = False
    flow_step: int = STEP_PRODUCT
    #: the open's reads landed and its step is decided: only then the step's address is
    #: written (`flow_sync` marker), never a «paso=1» over a deep link still being read
    flow_ready: bool = False
    #: the route's history lease this state answered (`ui/route_history.py`)
    history_ack: str = ""
    #: the page document the last lease came from: a new one is a reload (re-read all)
    _history_doc: str = ""
    #: `?crear=producto` was taken off the address: open on the handler's next pass
    _open_on_enter: bool = False
    #: the owner closed the panel and its address is being taken back (`_close_address`)
    _just_closed: float = 0.0
    loading: bool = False
    load_error: str = ""
    flow_error: str = ""

    products: list[ProductVM] = []
    without_photo: int = 0
    product_id: str = ""
    product_query: str = ""

    # the drawing's cost, from the backend (creaciones, never money)
    cost_creations: int = 0
    cost_line: str = ""
    cost_button: str = ""
    cost_message: str = ""
    cost_can_pay: bool = False
    cost_known: bool = False

    drawings: list[DrawingVM] = []
    drawings_loading: bool = False
    drawing_id: str = ""
    #: «Crear dibujo» / «Pedir otro dibujo» in flight
    asking: bool = False
    #: «Siguiente» on step 2 marks the drawing as used (`use_character`)
    picking: bool = False
    discarding: list[str] = []
    #: the drawing just quitado, while «Deshacer» is offered under step 2's help line
    undo_drawing: str = ""
    _undo_chosen: bool = False

    presets: list[str] = []
    max_chars: int = 25
    picked: list[str] = []
    own_on: bool = False
    own_text: str = ""
    _last_message: str = ""

    animated: bool = True
    still: bool = False
    creating: bool = False

    _brand: str = ""
    _gen: int = 0
    _poll_gen: int = 0
    #: when `asking` / `creating` was set (time.time())
    _busy_since: float = 0.0

    # -- computed ---------------------------------------------------------------------------

    @rx.var
    def flow_title(self) -> str:
        return STEP_TITLES.get(self.flow_step, "")

    @rx.var
    def start_cost(self) -> str:
        return start_cost_line(self.start_creations, self.start_read or self.cost_known)

    @rx.var
    def show_search(self) -> bool:
        return len(self.products) > SEARCH_FROM

    @rx.var
    def shown_products(self) -> list[ProductVM]:
        return filter_products(self.products, self.product_query)

    @rx.var
    def without_photo_text(self) -> str:
        return without_photo_line(self.without_photo)

    @rx.var
    def no_products(self) -> bool:
        return not self.loading and self.load_error == "" and not self.products

    @rx.var
    def product_name(self) -> str:
        return next((p.name for p in self.products if p.id == self.product_id), "")

    @rx.var
    def chosen_drawing(self) -> DrawingVM:
        return next((d for d in self.drawings if d.id == self.drawing_id), DrawingVM())

    @rx.var
    def has_usable_drawing(self) -> bool:
        return any(d.usable for d in self.drawings)

    @rx.var
    def any_drawing_pending(self) -> bool:
        return any(d.pending and not d.stale for d in self.drawings)

    @rx.var
    def drawing_button(self) -> str:
        """«Crear dibujo · 1 creación» (the backend's label) the first time; after that
        «Pedir otro dibujo · 1 creación» — a NEW drawing, the earlier ones are kept."""
        if not self.drawings:
            return self.cost_button
        return ask_another_label(self.cost_creations)

    @rx.var
    def can_ask_drawing(self) -> bool:
        # one drawing at a time: a second tap while «Dibujando…» would spend another creación
        return (
            self.cost_known
            and self.cost_can_pay
            and not self.asking
            and not any(d.pending and not d.stale for d in self.drawings)
        )

    @rx.var
    def messages(self) -> list[str]:
        return chosen_messages(self.presets, self.picked, self.own_on, self.own_text)

    @rx.var
    def own_count(self) -> str:
        return message_count(self.own_text, self.max_chars)

    @rx.var
    def own_count_live(self) -> str:
        """`aria-live` only from 20 letters on (UX doc §7)."""
        return "polite" if len(self.own_text) >= 20 else "off"

    @rx.var
    def own_error(self) -> str:
        return own_message_error(self.own_text, self.max_chars) if self.own_on else ""

    @rx.var
    def total(self) -> int:
        return sticker_total(len(self.messages), self.animated, self.still)

    @rx.var
    def review(self) -> str:
        return review_line(self.product_name, self.messages, self.animated, self.still)

    @rx.var
    def prepare_button(self) -> str:
        return prepare_label(self.total)

    @rx.var
    def can_go_on(self) -> bool:
        if self.flow_step == STEP_REVIEW:
            return self.total > 0 and not self.creating
        drawing = next((d for d in self.drawings if d.id == self.drawing_id), None)
        return (
            can_next(
                self.flow_step,
                product_id=self.product_id,
                drawing=drawing,
                messages=self.messages,
                own_error=self.own_error,
                animated=self.animated,
                still=self.still,
            )
            and not self.picking
        )

    # -- plumbing ---------------------------------------------------------------------------

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    def _in_flight(self) -> bool:
        """A paid or free request is on its way (and not lost: see `BUSY_STALE_SECONDS`)."""
        if not (self.asking or self.creating):
            return False
        if time.time() - self._busy_since > BUSY_STALE_SECONDS:
            self.asking = self.creating = False
            return False
        return True

    def _can_ask(self) -> bool:
        return (
            self.cost_known
            and self.cost_can_pay
            and not any(d.pending and not d.stale for d in self.drawings)
        )

    def _set_cost(self, cost: Any) -> None:
        self.cost_creations = int(cost.creations)
        self.cost_line = str(cost.cost_line)
        self.cost_button = str(cost.button_label)
        self.cost_message = str(cost.message or "")
        self.cost_can_pay = bool(cost.can_pay)
        self.cost_known = True
        self.start_creations = int(cost.creations)
        self.start_blocked = "" if cost.can_pay else str(cost.message or "")

    # -- the start card ---------------------------------------------------------------------

    @rx.event(background=True)
    async def load_start(self) -> None:
        """Tu marca mounted: what a drawing costs, for the start card (a failed read only
        loses the number)."""
        async with self:
            tenant_id = await self._tenant()
        if tenant_id is None:
            return
        try:
            gw = gateway()
            brand = await asyncio.to_thread(gw.brand, tenant_id)
            if brand is None:
                return
            cost = await asyncio.to_thread(gw.cost, tenant_id, brand)
        except Exception as exc:  # noqa: BLE001 — the card says only the free part
            logger.warning("product sticker start cost failed: %s", type(exc).__name__)
            async with self:
                self.start_read = True
            return
        async with self:
            self.start_read = True
            self.start_creations = int(cost.creations)
            self.start_blocked = "" if cost.can_pay else str(cost.message or "")

    # -- open and read ----------------------------------------------------------------------

    def _params(self) -> dict[str, Any]:
        try:
            return dict(self.router.url.query_parameters)
        except Exception:  # noqa: BLE001 — no router outside a page
            return {}

    def _close(self) -> None:
        self.flow_open = False
        self.flow_ready = False
        self._poll_gen += 1

    def _close_address(self) -> Any:
        """Take `?flujo=…&paso=N` off the address, back to where the flow was opened. When
        the flow began on a step's own address (a link, a reload) that place is itself a
        flow address: the pop that lands there is told apart (`_just_closed`) and only
        tidies the address, never reopens the panel the owner just closed."""
        self._just_closed = time.time()
        return rx.call_script(close_flow_script(FLOW_NAME))

    @rx.event
    def enter_history(self, lease: dict) -> list[Any]:
        """The route's history handler (`ui/route_history.py`): on mount, on a reload and on
        «atrás»/«adelante» of the browser the panel follows the address. `?flujo=
        sticker-producto&paso=N` opens it (or moves it) to that step, never past a missing
        choice (`reachable_step`); no `flujo` closes it. The old opener `?crear=producto`
        comes off the address first and the flow opens over Tu marca's own address, so
        each step is pushed on top of it and closing goes back there."""
        self.history_ack = history_ack_value(lease)
        document = self.history_ack.split(":", 1)[0]
        fresh = document != self._history_doc
        self._history_doc = document
        params = self._params()
        requested = flow_param(params, FLOW_NAME, FLOW_STEPS)
        if scalar_param(params, "crear") == CREATE_PARAM_VALUE:
            # then this handler runs again for the clean address, with a fresh lease
            self._open_on_enter = not self._in_flight()
            return [rx.call_script(replace_url_script(base_address(params)) + _REENTER_JS)]
        closed_at, self._just_closed = self._just_closed, 0.0
        just_closed = not fresh and time.time() - closed_at < CLOSE_POP_SECONDS
        if requested and just_closed and not self.flow_open:
            return [rx.call_script(replace_url_script(base_address(params)) + _REENTER_JS)]
        events: list[Any] = []
        busy = self._in_flight() or self.picking
        if self._open_on_enter:
            self._open_on_enter = False
            events.append(ProductStickerState.open_flow)
        elif requested:
            if self.flow_open and self.flow_ready and not fresh:
                if not busy:
                    events.extend(self._go_to(requested))
            elif not (self.flow_open and self.loading and not fresh) and not busy:
                # a reload re-reads everything (never a panel restored with stale drawings)
                events.append(ProductStickerState.open_at(requested))
        elif self.flow_open and not busy:
            self._close()  # «atrás» past step 1, or left open by an earlier visit
        events.append(route_history_ready(BRAND_KIT_PATH, lease))
        return events

    def _go_to(self, requested: int) -> list[Any]:
        """«atrás»/«adelante» of the browser inside an open flow."""
        target = reachable_step(
            requested,
            product_id=self.product_id,
            drawing=next((d for d in self.drawings if d.id == self.drawing_id), None),
            messages=self.messages,
            own_error=self.own_error,
            animated=self.animated,
            still=self.still,
        )
        before, self.flow_step = self.flow_step, target
        self.flow_error = ""
        if target != before:
            self.undo_drawing = ""
        if target == STEP_DRAWING and before == STEP_PRODUCT:
            return [ProductStickerState.read_drawings]
        return []

    @rx.event(background=True)
    async def open_flow(self) -> AsyncIterator[Any]:
        """«Crear sticker de producto»: step 1 with everything already chosen (the last
        product and message used), then the reads off the loop."""
        async for event in self._open(STEP_PRODUCT):
            yield event

    @rx.event(background=True)
    async def open_at(self, requested: int) -> AsyncIterator[Any]:
        """A step's address (a deep link, a reload): the flow opens there when its choices
        are there, else on the earlier step that is missing one."""
        async for event in self._open(int(requested or STEP_PRODUCT)):
            yield event

    async def _open(self, requested: int) -> AsyncIterator[Any]:
        async with self:
            self._in_flight()  # a request lost long ago (a restart) frees its flag here
            self._gen += 1
            self._poll_gen += 1
            gen = self._gen
            self.flow_open = True
            self.flow_ready = False
            self._just_closed = 0.0
            self.flow_step = STEP_PRODUCT
            self.undo_drawing = ""
            self.flow_error = ""
            self.load_error = ""
            self.loading = True
            self.picking = False
            self.product_query = ""
            self.drawings = []
            self.drawing_id = ""
            tenant_id = await self._tenant()
        error, read = "", None
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            brand = await asyncio.to_thread(gw.brand, tenant_id)
            if brand is None:
                raise PermissionError
            step = await asyncio.to_thread(gw.products, tenant_id, brand)
            cost = await asyncio.to_thread(gw.cost, tenant_id, brand)
            presets = list(gw.presets())
            limit = int(gw.max_message_chars())
            try:
                last = last_message(await asyncio.to_thread(gw.stickers, tenant_id, brand))
            except Exception as exc:  # noqa: BLE001 — only the pre-selection is lost
                logger.warning("product sticker last message failed: %s", type(exc).__name__)
                last = ""
            read = (str(brand), step, cost, presets, limit, last)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "open", LOAD_FAILED)
        async with self:
            if gen != self._gen:
                return
            self.loading = False
            if error or read is None:
                self.load_error = error or LOAD_FAILED
                self.flow_ready = True
                return
            brand_s, step, cost, presets, limit, last = read
            self._brand = brand_s
            self.products = product_vms(step.products)
            self.without_photo = int(step.without_photo)
            if not any(p.id == self.product_id for p in self.products):
                self.product_id = str(step.preselected or "")
            self._set_cost(cost)
            self.presets = presets
            self.max_chars = limit
            self._last_message = last
            # the last message used, else the first one («¡Gracias por tu pedido!»)
            self.picked, self.own_on, self.own_text = preselection(
                last, presets, _renamed_presets(), limit
            )
            self.animated, self.still = True, False
            if requested <= STEP_PRODUCT or not self.product_id:
                self.flow_ready = True
                return
        # a later step's address: its drawing must be read before the step is decided
        pending = await self._read_drawings(gen)
        async with self:
            if gen != self._gen:
                return
            chosen = next((d for d in self.drawings if d.id == self.drawing_id), None)
            if requested > STEP_DRAWING and not (chosen is not None and chosen.approved):
                used = next((d for d in self.drawings if d.approved), None)
                if used is not None:
                    self.drawing_id = used.id  # the drawing these stickers were made from
            self._go_to(requested)
            self.flow_ready = True
        if pending:
            yield ProductStickerState.poll

    @rx.event
    def set_flow_open(self, is_open: bool) -> Any:
        if not is_open and not self._in_flight():
            self._close()
            return self._close_address()
        return None

    @rx.event
    def close_for_season(self) -> Any:
        """«Crear para esta temporada» from an empty month: this panel closes and the free
        seasonal one opens next (`SeasonalState.open_flow`)."""
        if self._in_flight():
            return None
        self._close()
        from .seasonal_state import SeasonalState  # noqa: PLC0415 — no import cycle

        return [self._close_address(), SeasonalState.open_flow]

    @rx.event
    def flow_back(self) -> Any:
        """«‹ Atrás» keeps everything chosen; on step 1 it closes. The step's address
        follows (`flow_sync`: the browser's own entry is consumed, never a new one)."""
        if self._in_flight() or self.picking:
            return None
        self.flow_error = ""
        if self.flow_step <= STEP_PRODUCT:
            self._close()
            return self._close_address()
        self.flow_step -= 1
        self.undo_drawing = ""
        return None

    @rx.event
    def flow_next(self) -> Any:
        self.flow_error = ""
        step = self.flow_step
        if step == STEP_DRAWING:
            if not self.chosen_drawing.usable:
                self.flow_error = PICK_A_DRAWING
                return None
            return ProductStickerState.use_drawing
        if step == STEP_MESSAGE:
            if self.own_error:
                self.flow_error = self.own_error
                return None
            if not self.messages:
                self.flow_error = NO_MESSAGES
                return None
        if step == STEP_MOTION and not (self.animated or self.still):
            self.flow_error = NO_VARIANT
            return None
        if not self.can_go_on or step >= FLOW_STEPS:
            return None
        self.flow_step += 1
        self.undo_drawing = ""
        if step == STEP_PRODUCT:
            return ProductStickerState.read_drawings
        return None

    # -- step 1 -----------------------------------------------------------------------------

    @rx.event
    def choose_product(self, product_id: str) -> None:
        if any(p.id == product_id for p in self.products):
            if product_id != self.product_id:
                self.drawings, self.drawing_id = [], ""
            self.product_id = product_id
            self.flow_error = ""

    @rx.event
    def set_product_query(self, value: str) -> None:
        self.product_query = value[:60] if isinstance(value, str) else ""

    # -- step 2: the drawings ---------------------------------------------------------------

    async def _read_drawings(self, gen: int) -> bool:
        """Re-read the chosen product's drawings; True while one is still being drawn."""
        async with self:
            if gen != self._gen:
                return False
            product, brand = _uuid(self.product_id), _uuid(self._brand)
            wanted = self.product_id
            tenant_id = await self._tenant()
        cards, error = None, ""
        try:
            if tenant_id is None or brand is None or product is None:
                raise PermissionError
            cards = await asyncio.to_thread(gateway().characters, tenant_id, brand, product)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "drawings", DRAWINGS_FAILED)
        async with self:
            # a newer open, or the owner went back and chose another product meanwhile
            if gen != self._gen or self.product_id != wanted:
                if gen == self._gen:
                    self.drawings_loading = False
                return False
            self.drawings_loading = False
            if cards is None:
                self.flow_error = error
                return False
            self.drawings = drawing_vms(cards)
            chosen = next((d for d in self.drawings if d.id == self.drawing_id), None)
            if chosen is None or not chosen.usable:
                # the newest drawing that can be used (one just finished, or the last used)
                first = next((d for d in self.drawings if d.usable), None)
                self.drawing_id = first.id if first is not None else ""
            return any(d.pending for d in self.drawings)

    @rx.event(background=True)
    async def read_drawings(self) -> AsyncIterator[Any]:
        async with self:
            gen = self._gen
            self.drawings_loading = True
        if await self._read_drawings(gen):
            yield ProductStickerState.poll

    @rx.event(background=True)
    async def poll(self) -> None:
        """Re-read while a drawing is «Dibujando…» and the panel is open (one at a time)."""
        async with self:
            self._poll_gen += 1
            mine, gen = self._poll_gen, self._gen
        for _ in range(POLL_ROUNDS):
            await asyncio.sleep(POLL_SECONDS)
            async with self:
                if mine != self._poll_gen or not self.flow_open:
                    return
            if not await self._read_drawings(gen):
                return

    @rx.event
    def stop_poll(self) -> None:
        """Tu marca unmounted: no more reads, and the panel does not come back open (with a
        stale «Dibujando…») unless a paid request is still on its way."""
        self._poll_gen += 1
        # a `?crear=producto` whose second pass never came (left mid-way) never opens later
        self._open_on_enter = False
        if not self._in_flight():
            self.flow_open = False
            self.flow_ready = False

    @rx.event
    def pick_drawing(self, drawing_id: str) -> None:
        if any(d.id == drawing_id and d.usable for d in self.drawings):
            self.drawing_id = drawing_id
            self.flow_error = ""

    async def _requote(self, tenant_id: UUID, brand: UUID) -> None:
        try:
            cost = await asyncio.to_thread(gateway().cost, tenant_id, brand)
        except Exception as exc:  # noqa: BLE001 — the button stays off without a cost
            logger.warning("product sticker requote failed: %s", type(exc).__name__)
            async with self:
                self.cost_known = False
            return
        async with self:
            self._set_cost(cost)

    @rx.event(background=True)
    async def ask_drawing(self) -> AsyncIterator[Any]:
        """«Crear dibujo · 1 creación» / «Pedir otro dibujo · 1 creación»: always a NEW
        drawing for the cost the owner saw (`accepted_creations`); the earlier ones stay."""
        async with self:
            if self._in_flight() or not self._can_ask():
                return
            product, brand = _uuid(self.product_id), _uuid(self._brand)
            accepted, gen = self.cost_creations, self._gen
            self.asking = True
            self._busy_since = time.time()
            self.flow_error = ""
            tenant_id = await self._tenant()
        from qualify_api.creative.product_stickers import (  # noqa: PLC0415
            CostChanged,
            NotEnoughCreationsLeft,
        )

        card, error, requote = None, "", False
        try:
            if tenant_id is None or brand is None or product is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            card = await asyncio.to_thread(
                gw.create_character, tenant_id, brand, product, user, accepted
            )
        except PermissionError:
            error = NO_SESSION
        except (CostChanged, NotEnoughCreationsLeft) as exc:
            # the new cost (or the empty month) is shown before anything else is spent
            error, requote = exc.message, True
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "ask drawing")
        if requote and tenant_id is not None and brand is not None:
            await self._requote(tenant_id, brand)
        async with self:
            self.asking = False
            if gen != self._gen:
                return
            if error or card is None:
                self.flow_error = error or ACTION_FAILED
                return
            if str(card.product_id) == self.product_id:
                fresh = drawing_vms([card])
                self.drawings = fresh + [d for d in self.drawings if d.id != card.id]
        if tenant_id is not None and brand is not None:
            await self._requote(tenant_id, brand)  # «Te quedan 11 este mes»
        yield ProductStickerState.poll

    @rx.event(background=True)
    async def discard_drawing(self, drawing_id: str) -> AsyncIterator[Any]:
        """«Quitar este dibujo»: the drawing leaves the list at once (stickers made from it
        stay) and the panel offers «Deshacer» (`restore_drawing`) — no question first. The
        way back lives in the panel, not in a toast: the panel is modal, so a toast's button
        could not be touched nor reached with the keyboard while it is open."""
        async with self:
            found = next((d for d in self.drawings if d.id == drawing_id), None)
            brand = _uuid(self._brand)
            if found is None or found.pending or drawing_id in self.discarding or brand is None:
                return
            was_chosen = self.drawing_id == drawing_id
            self.discarding = [*self.discarding, drawing_id]
            self.flow_error = ""
            gen = self._gen
            tenant_id = await self._tenant()
        error = ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            await asyncio.to_thread(gw.discard_character, tenant_id, brand, UUID(drawing_id), user)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "discard drawing")
        async with self:
            self.discarding = [i for i in self.discarding if i != drawing_id]
            if gen != self._gen:
                return
            if error:
                self.flow_error = error
                return
            self.drawings = [d for d in self.drawings if d.id != drawing_id]
            if self.drawing_id == drawing_id:
                first = next((d for d in self.drawings if d.usable), None)
                self.drawing_id = first.id if first is not None else ""
            self.undo_drawing, self._undo_chosen = drawing_id, was_chosen
        # its «Quitar» button is gone with it: the focus lands on «Deshacer», not on <body>
        yield rx.call_script(
            "window.requestAnimationFrame(() =>"
            f" document.getElementById({UNDO_BUTTON_ID!r})?.focus());"
        )

    @rx.event(background=True)
    async def restore_drawing(self) -> None:
        """«Deshacer»: the last drawing quitado comes back as it was (backend
        `restore_character`: only while it is still discarded; a second tap is harmless)."""
        async with self:
            drawing_id, was_chosen = self.undo_drawing, self._undo_chosen
            brand, character = _uuid(self._brand), _uuid(drawing_id)
            if brand is None or character is None or drawing_id in self.discarding:
                return
            self.discarding = [*self.discarding, drawing_id]
            self.flow_error = ""
            gen = self._gen
            tenant_id = await self._tenant()
        error = ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            await asyncio.to_thread(gw.restore_character, tenant_id, brand, character, user)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "restore drawing", RESTORE_FAILED)
        async with self:
            self.discarding = [i for i in self.discarding if i != drawing_id]
            if gen != self._gen or not self.flow_open:
                return
            if error:
                self.flow_error = error
                return
            if self.undo_drawing == drawing_id:
                self.undo_drawing = ""
            if was_chosen:
                self.drawing_id = drawing_id
        # the list is re-read (its order and the others' state are the backend's)
        await self._read_drawings(gen)

    @rx.event(background=True)
    async def use_drawing(self) -> None:
        """Step 2's «Siguiente»: the chosen drawing becomes the one the stickers are made
        from (`use_character`, the first approval); an already used one goes straight on."""
        async with self:
            chosen = next((d for d in self.drawings if d.id == self.drawing_id), None)
            brand = _uuid(self._brand)
            if chosen is None or not chosen.usable or self.picking or brand is None:
                return
            if chosen.approved:
                self.flow_step = STEP_MESSAGE
                self.undo_drawing = ""
                return
            self.picking = True
            gen = self._gen
            tenant_id = await self._tenant()
        card, error = None, ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            card = await asyncio.to_thread(
                gw.use_character, tenant_id, brand, UUID(chosen.id), user
            )
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "use drawing")
        async with self:
            self.picking = False
            if gen != self._gen:
                return
            if error or card is None:
                self.flow_error = error or ACTION_FAILED
                return
            updated = drawing_vms([card])
            self.drawings = [updated[0] if d.id == card.id else d for d in self.drawings]
            self.flow_step = STEP_MESSAGE
            self.undo_drawing = ""

    # -- step 3 and 4 -----------------------------------------------------------------------

    @rx.event
    def toggle_message(self, text: str) -> None:
        if text not in self.presets:
            return
        self.picked = (
            [p for p in self.picked if p != text]
            if text in self.picked
            else [
                *self.picked,
                text,
            ]
        )
        self.flow_error = ""

    @rx.event
    def toggle_own(self) -> None:
        self.own_on = not self.own_on
        self.flow_error = ""

    @rx.event
    def set_own_text(self, value: str) -> None:
        self.own_text = value[: self.max_chars] if isinstance(value, str) else ""
        self.own_on = True
        self.flow_error = ""

    @rx.event
    def toggle_animated(self) -> None:
        self.animated = not self.animated
        self.flow_error = ""

    @rx.event
    def toggle_still(self) -> None:
        self.still = not self.still
        self.flow_error = ""

    # -- step 5 -----------------------------------------------------------------------------

    @rx.event(background=True)
    async def create(self) -> AsyncIterator[Any]:
        """«Preparar 3 stickers · gratis»: one library row per message and variant, to Por
        aprobar (nothing is approved, nothing is sent)."""
        async with self:
            if self._in_flight() or self.flow_step != STEP_REVIEW or not self.flow_open:
                return
            drawing, brand = _uuid(self.drawing_id), _uuid(self._brand)
            messages, animated, still = list(self.messages), self.animated, self.still
            if drawing is None or brand is None or not messages:
                self.flow_error = NO_MESSAGES if not messages else ACTION_FAILED
                return
            self.creating = True
            self._busy_since = time.time()
            self.flow_error = ""
            tenant_id = await self._tenant()
        error = ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            await asyncio.to_thread(
                lambda: gw.make_stickers(
                    tenant_id, brand, drawing, messages, user, animated=animated, still=still
                )
            )
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "make stickers")
        async with self:
            self.creating = False
            if error:
                self.flow_error = error
                return
            self._close()
            self._last_message = messages[-1]
            close_address = self._close_address()  # sets its flag under the state's lock
        from .seasonal_state import SeasonalState  # noqa: PLC0415 — no import cycle

        yield close_address
        yield rx.toast.success(
            STARTED_TOAST,
            duration=_TOAST_MS,
            action={"label": SEE_DRAFTS_LABEL, "on_click": rx.redirect(DRAFTS_STICKERS_HREF)},
        )
        yield SeasonalState.load
