"""Reflex state for «Ordenar tu menú» in «Galería» (m-24955643).

The owner orders the categories (a category moves with all its products) and the products
inside each category; that is the order the customer gets on WhatsApp. Spec:
`docs/ux-orden-de-productos.md`.

- Every move is optimistic: the screen shows the new order at once (`assets/rank-drag.js`
  already slid the rows there), the write is queued and `flush_order` stores it through
  `CatalogService` (`set_category_order` / `reorder_products`, both whole-list and
  idempotent) — one write at a time, in the order the moves were made.
- A refused or failed write puts the screen back where it was before that move and says
  «No pudimos guardar el orden…»; a typed refusal (the list changed under the screen, in
  another tab) also re-reads the order.
- «Deshacer» (6 s, in the toast) stores the previous order through the same calls.
- Holds only `catalog_order_vm` dataclasses (plain strings/ints); provider calls block, so
  they run with `asyncio.to_thread` inside background handlers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .catalog_order_vm import (
    ORDER_FAILED,
    TAB_CATEGORIES_VALUE,
    TAB_PRODUCTS_VALUE,
    UNDO_LABEL,
    UNDONE,
    OrderCategoryVM,
    OrderGroup,
    build_order_view,
    cancelled_text,
    category_moved_text,
    category_names,
    category_place_label,
    category_rank_key,
    find_category,
    find_product,
    focus_handle_script,
    focus_more_script,
    lifted_text,
    move_category,
    move_product,
    opens_order,
    product_moved_text,
    product_place_label,
    restore_categories,
    restore_products,
    stayed_text,
)
from .catalog_provider import (
    OrderRefused,
    UnknownCategory,
    UnknownProduct,
    list_order,
    save_category_order,
    save_product_order,
)
from .catalog_state import CatalogState
from .catalog_vm import return_path_from_query
from .creative_provider import acting_user_id, default_brand_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Primero completa tu marca (logo y colores) y vuelve a subir tus productos."
_DB_ERROR = "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."
#: How long «Listo: … va primero» and its «Deshacer» stay (spec §3: 6 s).
_UNDO_MS = 6000

#: A write the screen already shows and the service has not stored yet.
_REFUSALS = (UnknownCategory, UnknownProduct, OrderRefused)


class CatalogOrderState(rx.State):
    """«Ordenar tu menú»: open or not, the tab, the order on screen and its writes."""

    ordering: bool = False
    tab: str = TAB_CATEGORIES_VALUE
    loading_order: bool = False
    order_error: str = ""
    #: Said by the `aria-live` line after every move (the toast says it too).
    announce: str = ""
    #: The app route the owner came from (`?volver=`, WhatsApp step 3's link).
    return_to: str = ""
    order_busy: bool = False

    _groups: list[OrderGroup] = []
    #: Writes waiting for `flush_order`: {"kind", "names" | "category"+"ids", "before",
    #: "toast", "undo"}.
    _queue: list[dict[str, Any]] = []
    #: What «Deshacer» stores again ({} = nothing to undo).
    _undo: dict[str, Any] = {}
    #: The row lifted by `rank-drag.js` (a category name or a product id), until the drop.
    _dragging: str = ""
    #: The row lifted from the keyboard (its rank key: `cat:<name>` or a product id) and
    #: the order when it was lifted (what Escape brings back, and the write's `before`).
    lifted: str = ""
    _lift_before: list[OrderGroup] = []
    _brand_id: str = ""

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def categories(self) -> list[OrderCategoryVM]:
        return build_order_view(self._groups)

    @rx.var
    def product_total(self) -> int:
        return sum(len(g.products) for g in self._groups)

    @rx.var
    def has_order_products(self) -> bool:
        return any(g.products for g in self._groups)

    @rx.var
    def single_category(self) -> bool:
        return len(self._groups) == 1

    @rx.var
    def single_product(self) -> bool:
        return sum(len(g.products) for g in self._groups) == 1

    @rx.var
    def returning(self) -> bool:
        return self.return_to != ""

    # -- session --------------------------------------------------------------------------

    async def _session_ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        """(tenant, brand, acting user) or None with the reason already in `order_error`."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            cached_brand_id = self._brand_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            async with self:
                self.order_error = _NO_SESSION
            return None
        brand_id: UUID | None
        if cached_brand_id:
            brand_id = UUID(cached_brand_id)
        else:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
            if brand_id is not None:
                async with self:
                    self._brand_id = str(brand_id)
        if brand_id is None:
            async with self:
                self.order_error = _NO_BRAND
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        return tenant_id, brand_id, user_id

    # -- open, load, close ----------------------------------------------------------------

    @rx.event
    def arrive(self) -> rx.event.EventSpec | None:
        """The catalog mounted: `?ordenar=1` (WhatsApp step 3's «Cambiar el orden») opens
        «Ordenar tu menú» with the way back; any other visit starts on the list."""
        try:
            params = self.router.url.query_parameters
        except Exception:  # noqa: BLE001 — no router outside a request (tests)
            params = {}
        if opens_order(params):
            self.return_to = return_path_from_query(params)
            return self.open_order()
        self.ordering = False
        self.return_to = ""
        return None

    @rx.event
    def open_order(self) -> rx.event.EventSpec:
        self.ordering = True
        self.tab = TAB_CATEGORIES_VALUE
        self.order_error = ""
        self.announce = ""
        return CatalogOrderState.load_order

    @rx.event
    def set_tab(self, value: str | list[str]) -> None:
        if isinstance(value, str) and value in (TAB_CATEGORIES_VALUE, TAB_PRODUCTS_VALUE):
            self.tab = value

    @rx.event
    def close_order(self) -> None:
        """Out of «Ordenar tu menú» without going anywhere (its «Agregar producto»)."""
        self.ordering = False
        self._dragging = ""

    @rx.event
    def finish_order(self) -> rx.event.EventSpec:
        """«Listo»: back where the owner came from, or to the list (re-read: its grid
        follows the same order)."""
        self.ordering = False
        self._dragging = ""
        self.lifted = ""
        if self.return_to:
            return rx.redirect(self.return_to)
        return CatalogState.load_catalog

    @rx.event(background=True)
    async def load_order(self) -> None:
        async with self:
            self.loading_order = not self._groups
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.loading_order = False
            return
        tenant_id, brand_id, _ = ids
        try:
            groups = await asyncio.to_thread(list_order, tenant_id, brand_id)
        except SQLAlchemyError as exc:
            logger.error("catalog order load failed: %s", type(exc).__name__)
            async with self:
                self.loading_order = False
                self.order_error = _DB_ERROR
            return
        async with self:
            # a move made while this read was in flight wins: its write is queued
            if not self._queue and not self.order_busy:
                self._groups = list(groups)
            self.loading_order = False

    # -- the moves ------------------------------------------------------------------------

    @rx.event
    def place_category(self, name: str, to: int) -> list[rx.event.EventSpec] | None:
        """«Primero / Subir uno / Bajar uno / Último / Mover a la posición…»: `name`
        ("" = «Otros») to 0-based `to`; the focus goes back to the row's «⋯»."""
        if self._place_category(name, to) is None:
            return None
        return [
            CatalogOrderState.flush_order,
            rx.call_script(focus_more_script(category_rank_key(name))),
        ]

    @rx.event
    def place_product(self, product_id: str, to: int) -> list[rx.event.EventSpec] | None:
        """The same for a product, inside its own category only."""
        if self._place_product(product_id, to) is None:
            return None
        return [CatalogOrderState.flush_order, rx.call_script(focus_more_script(product_id))]

    def _place_category(self, name: str, to: int) -> rx.event.EventSpec | None:
        """Every category move (menu or drop): optimistic, then queued for the writer."""
        new = move_category(self._groups, name, int(to))
        if new is None:
            return None
        before = list(self._groups)
        self._groups = new
        return self._queue_category(name, before)

    def _queue_category(self, name: str, before: list[OrderGroup]) -> rx.event.EventSpec:
        """The order on screen, stored: `before` is what «Deshacer» and a failure bring
        back (for a keyboard move, the order when the row was lifted)."""
        groups = self._groups
        self.lifted = ""
        index = find_category(groups, name) or 0
        text = category_moved_text(groups[index].label, index + 1, len(groups))
        self.announce = text
        self.order_error = ""
        self._queue = [
            *self._queue,
            {
                "kind": "categories",
                "names": category_names(groups),
                "before": before,
                "toast": text,
                "undo": {"kind": "categories", "names": category_names(before)},
            },
        ]
        return CatalogOrderState.flush_order

    def _place_product(self, product_id: str, to: int) -> rx.event.EventSpec | None:
        result = move_product(self._groups, product_id, int(to))
        if result is None:
            return None
        before = list(self._groups)
        self._groups = result[0]
        return self._queue_product(product_id, before)

    def _queue_product(self, product_id: str, before: list[OrderGroup]) -> rx.event.EventSpec:
        self.lifted = ""
        g_index, index = find_product(self._groups, product_id) or (0, 0)
        group = self._groups[g_index]
        ids = [p.product_id for p in group.products]
        text = product_moved_text(group.products[index].name, index + 1, len(ids), group.label)
        self.announce = text
        self.order_error = ""
        old = find_category(before, group.name)
        old_ids = [p.product_id for p in before[old].products] if old is not None else ids
        self._queue = [
            *self._queue,
            {
                "kind": "products",
                "category": group.name,
                "ids": ids,
                "before": before,
                "toast": text,
                "undo": {"kind": "products", "category": group.name, "ids": old_ids},
            },
        ]
        return CatalogOrderState.flush_order

    # the keyboard on the handle (`ui.sort_handle`): Espacio lifts and drops, ↑/↓ move
    # while lifted (on screen only: one write on the drop), Escape puts it back

    @rx.event
    def category_handle_key(self, name: str, key: str) -> list[rx.event.EventSpec] | None:
        index = find_category(self._groups, name)
        if index is None:
            return None
        rank_key = category_rank_key(name)
        label = self._groups[index].label
        total = len(self._groups)

        def moved_to(to: int) -> bool:
            new = move_category(self._groups, name, to)
            if new is None:
                return False
            self._groups = new
            return True

        def store() -> rx.event.EventSpec:
            return self._queue_category(name, list(self._lift_before))

        def place(groups: list[OrderGroup]) -> str:
            i = find_category(groups, name) or 0
            return category_place_label(groups[i].label, i + 1, len(groups))

        return self._handle_key(
            rank_key, key, index, label, total, moved_to, store, category_names, place
        )

    @rx.event
    def product_handle_key(self, product_id: str, key: str) -> list[rx.event.EventSpec] | None:
        found = find_product(self._groups, product_id)
        if found is None:
            return None
        g_index, index = found
        group = self._groups[g_index]

        def moved_to(to: int) -> bool:
            result = move_product(self._groups, product_id, to)
            if result is None:
                return False
            self._groups = result[0]
            return True

        def store() -> rx.event.EventSpec:
            return self._queue_product(product_id, list(self._lift_before))

        def ids(groups: list[OrderGroup]) -> list[str]:
            g = find_category(groups, group.name)
            return [p.product_id for p in groups[g].products] if g is not None else []

        def place(groups: list[OrderGroup]) -> str:
            gi, pi = find_product(groups, product_id) or (0, 0)
            g = groups[gi]
            return product_place_label(g.products[pi].name, pi + 1, len(g.products), g.label)

        return self._handle_key(
            product_id,
            key,
            index,
            group.products[index].name,
            len(group.products),
            moved_to,
            store,
            ids,
            place,
        )

    def _handle_key(
        self,
        rank_key: str,
        key: str,
        index: int,
        label: str,
        total: int,
        moved_to: Any,
        store: Any,
        order_of: Any,
        place_of: Any,
    ) -> list[rx.event.EventSpec] | None:
        focus = rx.call_script(focus_handle_script(rank_key))
        if key in (" ", "Spacebar", "Enter"):
            if self.lifted != rank_key:  # lift
                self.lifted = rank_key
                self._lift_before = list(self._groups)
                self.announce = lifted_text(label, index + 1, total)
                return None
            changed = order_of(self._groups) != order_of(self._lift_before)
            if not changed:  # dropped where it was
                self.lifted = ""
                self.announce = stayed_text(label)
                return None
            return [store(), focus]
        if self.lifted != rank_key:
            return None
        if key == "Escape":
            self._groups = list(self._lift_before)
            self.lifted = ""
            self.announce = cancelled_text(label)
            return [focus]
        step = {"ArrowUp": -1, "ArrowDown": 1}.get(key)
        if step is None or not moved_to(index + step):
            return None
        self.announce = place_of(self._groups)
        return [focus]

    # drag (`assets/rank-drag.js` fires `dragstart` on the lifted row, `drop` on the target)

    @rx.event
    def pick(self, key: str) -> None:
        """A category lifts as its rank key (`cat:<name>`, so «Otros» = `cat:` is not
        «nothing»), a product as its id."""
        self._dragging = key

    @rx.event
    def drop_category(self, target: str) -> rx.event.EventSpec | None:
        lifted, self._dragging = self._dragging, ""
        prefix = category_rank_key("")
        if not lifted.startswith(prefix):  # nothing lifted, or a product
            return None
        source = lifted.removeprefix(prefix)  # "" is «Otros», a real category
        to = find_category(self._groups, target)
        if to is None or find_category(self._groups, source) is None or source == target:
            return None
        return self._place_category(source, to)

    @rx.event
    def drop_product(self, target_id: str) -> rx.event.EventSpec | None:
        source, self._dragging = self._dragging, ""
        a = find_product(self._groups, source)
        b = find_product(self._groups, target_id)
        if a is None or b is None or a[0] != b[0] or source == target_id:
            return None  # only inside one category: changing it is an edit
        return self._place_product(source, b[1])

    # -- «Deshacer» ---------------------------------------------------------------------

    @rx.event
    def undo_order(self) -> rx.event.EventSpec | None:
        undo, self._undo = self._undo, {}
        if not undo:
            return None
        before = list(self._groups)
        if undo["kind"] == "categories":
            self._groups = restore_categories(self._groups, undo["names"])
            job: dict[str, Any] = {"kind": "categories", "names": list(undo["names"])}
        else:
            self._groups = restore_products(self._groups, undo["category"], undo["ids"])
            job = {"kind": "products", "category": undo["category"], "ids": list(undo["ids"])}
        self.announce = UNDONE
        self._queue = [*self._queue, {**job, "before": before, "toast": UNDONE, "undo": {}}]
        return CatalogOrderState.flush_order

    # -- the writer -----------------------------------------------------------------------

    @rx.event(background=True)
    async def flush_order(self) -> AsyncIterator[rx.event.EventSpec]:
        """Store the queued moves one by one, in order. Only one writer runs at a time;
        a move made while it works is picked up by the same loop."""
        async with self:
            if self.order_busy or not self._queue:
                return
            self.order_busy = True
        try:
            ids = await self._session_ids()
        except Exception as exc:  # noqa: BLE001 — e.g. the DB is down: never stay busy
            logger.warning("catalog order session failed: %s", type(exc).__name__)
            ids = None
            async with self:
                self.order_error = ORDER_FAILED
                self.announce = ORDER_FAILED
        if ids is None:
            async with self:
                self.order_busy = False
                if self._queue:
                    self._groups = list(self._queue[0]["before"])
                self._queue = []
                self._undo = {}
            return
        tenant_id, brand_id, user_id = ids
        while True:
            async with self:
                if not self._queue:
                    self.order_busy = False
                    return
                job = self._queue[0]
            try:
                if job["kind"] == "categories":
                    await asyncio.to_thread(
                        save_category_order, tenant_id, brand_id, user_id, job["names"]
                    )
                else:
                    await asyncio.to_thread(
                        save_product_order,
                        tenant_id,
                        brand_id,
                        user_id,
                        job["category"],
                        job["ids"],
                    )
            except Exception as exc:  # noqa: BLE001 — any failure: never stay busy
                # A typed refusal or the database is expected; anything else (a malformed
                # id, a bug) must not leave the writer busy with a queue nobody stores
                # while the screen shows an order that was never saved.
                logger.warning("catalog order write refused: %s", type(exc).__name__)
                async with self:
                    self._groups = list(job["before"])
                    self._queue = []
                    self._undo = {}
                    self.order_busy = False
                    self.order_error = ORDER_FAILED
                    self.announce = ORDER_FAILED
                if isinstance(exc, _REFUSALS):  # the list changed under the screen
                    yield CatalogOrderState.load_order
                return
            async with self:
                self._queue = self._queue[1:]
                last = not self._queue
                if job.get("undo"):
                    self._undo = job["undo"]
            if last:
                if job.get("undo"):
                    yield rx.toast.success(
                        job["toast"],
                        duration=_UNDO_MS,
                        action={"label": UNDO_LABEL, "on_click": CatalogOrderState.undo_order},
                    )
                else:
                    yield rx.toast.success(job["toast"], duration=_UNDO_MS)
