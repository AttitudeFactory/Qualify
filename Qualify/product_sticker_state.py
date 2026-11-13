"""«Tu producto en sticker» (m-25017912 over the backend of m-25017372): the five-step flow
in Tu marca › «Stickers y videos de tu marca». Every gateway call blocks, so it runs off the
event loop (`asyncio.to_thread`), and a read lands only for the open it belongs to (`_gen`).
A drawing being made is re-read every few seconds while the panel is open. The stickers
themselves land in the seasonal library (season «De tus productos»), where «Por aprobar» and
«Aprobados» already approve, redraw and delete them (`SeasonalState`)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .product_sticker_provider import gateway
from .product_sticker_vm import (
    ACTION_FAILED,
    CREATE_PARAM_VALUE,
    DRAFTS_STICKERS_HREF,
    DRAWINGS_FAILED,
    FLOW_STEPS,
    LOAD_FAILED,
    NO_MESSAGES,
    NO_SESSION,
    NO_VARIANT,
    PICK_A_DRAWING,
    SEARCH_FROM,
    SEE_DRAFTS_LABEL,
    STARTED_TOAST,
    STEP_DRAWING,
    STEP_MESSAGE,
    STEP_MOTION,
    STEP_PRODUCT,
    STEP_REVIEW,
    STEP_TITLES,
    DrawingVM,
    ProductVM,
    ask_another_label,
    can_next,
    chosen_messages,
    drawing_vms,
    filter_products,
    last_message,
    message_count,
    own_message_error,
    prepare_label,
    product_vms,
    review_line,
    start_cost_line,
    sticker_total,
    without_photo_line,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_TOAST_MS = 6000
#: A drawing takes ~30 s – 2 min: re-read this often while one is «Dibujando…».
POLL_SECONDS = 5.0
#: ≈ 10 min, then the owner can come back later (it keeps being drawn).
POLL_ROUNDS = 120


def _worded(exc: BaseException, what: str, fallback: str = ACTION_FAILED) -> str:
    """The backend's own Spanish `message` for its refusals, else the generic line — never
    the exception's text."""
    from qualify_api.creative.product_stickers import ProductStickerError  # noqa: PLC0415
    from qualify_api.whatsapp.seasonal import SeasonalError  # noqa: PLC0415

    if isinstance(exc, (ProductStickerError, SeasonalError)):
        return exc.message
    logger.error("product sticker %s failed: %s", what, type(exc).__name__)
    return fallback


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

    # -- the flow ---------------------------------------------------------------------------
    flow_open: bool = False
    flow_step: int = STEP_PRODUCT
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

    # -- computed ---------------------------------------------------------------------------

    @rx.var
    def flow_title(self) -> str:
        return STEP_TITLES.get(self.flow_step, "")

    @rx.var
    def start_cost(self) -> str:
        return start_cost_line(self.start_creations)

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
    def any_drawing_pending(self) -> bool:
        return any(d.pending for d in self.drawings)

    @rx.var
    def drawing_button(self) -> str:
        """«Crear dibujo · 1 creación» (the backend's label) the first time; after that
        «Pedir otro dibujo · 1 creación» — a NEW drawing, the earlier ones are kept."""
        if not self.drawings:
            return self.cost_button
        return ask_another_label(self.cost_creations)

    @rx.var
    def can_ask_drawing(self) -> bool:
        return self.cost_known and self.cost_can_pay and not self.asking

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
            return
        async with self:
            self.start_creations = int(cost.creations)
            self.start_blocked = "" if cost.can_pay else str(cost.message or "")

    # -- open and read ----------------------------------------------------------------------

    @rx.event
    def open_from_query(self) -> Any:
        """`?crear=producto`: the flow opens by itself."""
        try:
            wanted = self.router.url.query_parameters.get("crear")
        except Exception:  # noqa: BLE001 — no router outside a page
            wanted = None
        if wanted == CREATE_PARAM_VALUE and not (self.asking or self.creating):
            # a reload re-reads everything (never a panel restored with stale drawings)
            return ProductStickerState.open_flow
        if self.flow_open and not (self.asking or self.creating):
            self.flow_open = False  # left open by an earlier visit of this tab
        return None

    @rx.event(background=True)
    async def open_flow(self) -> None:
        """«Crear sticker de producto»: step 1 with everything already chosen (the last
        product and message used), then the reads off the loop."""
        async with self:
            self._gen += 1
            self._poll_gen += 1
            gen = self._gen
            self.flow_open = True
            self.flow_step = STEP_PRODUCT
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
            if last and last not in presets:
                self.picked, self.own_on, self.own_text = [], True, last[:limit]
            else:
                self.picked = [last or (presets[0] if presets else "")]
                self.picked = [p for p in self.picked if p]
                self.own_on, self.own_text = False, ""
            self.animated, self.still = True, False

    @rx.event
    def set_flow_open(self, is_open: bool) -> None:
        if not is_open and not (self.creating or self.asking):
            self.flow_open = False
            self._poll_gen += 1

    @rx.event
    def flow_back(self) -> None:
        """«‹ Atrás» keeps everything chosen; on step 1 it closes."""
        if self.creating or self.asking or self.picking:
            return
        self.flow_error = ""
        if self.flow_step <= STEP_PRODUCT:
            self.flow_open = False
            self._poll_gen += 1
            return
        self.flow_step -= 1

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
        if not (self.asking or self.creating):
            self.flow_open = False

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
            if self.asking or not self.cost_known or not self.cost_can_pay:
                return
            product, brand = _uuid(self.product_id), _uuid(self._brand)
            accepted, gen = self.cost_creations, self._gen
            self.asking = True
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
    async def discard_drawing(self, drawing_id: str) -> None:
        """«No me gusta»: the drawing leaves the list (stickers made from it stay)."""
        async with self:
            found = next((d for d in self.drawings if d.id == drawing_id), None)
            brand = _uuid(self._brand)
            if found is None or found.pending or drawing_id in self.discarding or brand is None:
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
            if self.creating or self.flow_step != STEP_REVIEW or not self.flow_open:
                return
            drawing, brand = _uuid(self.drawing_id), _uuid(self._brand)
            messages, animated, still = list(self.messages), self.animated, self.still
            if drawing is None or brand is None or not messages:
                self.flow_error = NO_MESSAGES if not messages else ACTION_FAILED
                return
            self.creating = True
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
            self.flow_open = False
            self._poll_gen += 1
            self._last_message = messages[-1]
        from .seasonal_state import SeasonalState  # noqa: PLC0415 — no import cycle

        yield rx.toast.success(
            STARTED_TOAST,
            duration=_TOAST_MS,
            action={"label": SEE_DRAFTS_LABEL, "on_click": rx.redirect(DRAFTS_STICKERS_HREF)},
        )
        yield SeasonalState.load
