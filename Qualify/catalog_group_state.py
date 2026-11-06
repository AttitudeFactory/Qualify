"""Reflex state for «Agrupa tus productos» (m-24955838).

Two steps in the system's drawer (spec: `docs/ux-categorias-de-productos.md` §2):

1. «Te proponemos estos grupos»: the sections `CatalogService.suggest_category_groups`
   proposes, each accepted by default; «Cambiar nombre», «No agrupar» / «Deshacer».
   «Siguiente» stores the accepted ones, one `set_products_category` per group.
2. «¿Dónde va cada uno de estos?»: what is left, with checkboxes; «Poner en…» an
   existing category or «+ Nueva categoría» moves the marked ones (optimistic: they
   leave the list at once, and come back if the write fails), with «Deshacer» for 6 s.
   «Dejar el resto en «Otros»» stores nothing and keeps the notice hidden until a new
   product without a category appears (`CatalogState.dismissed_uncategorized`).

Same discipline as the order writer (`catalog_order_state`): one write at a time
(`busy`), every failure — the session lookup included — leaves the screen as the
database has it, with «No pudimos guardar la categoría…» (or the service's own Spanish
sentence, e.g. a name over 24 letters). Provider calls run with `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .catalog_group_vm import (
    NEW_CHOICE,
    SAVE_FAILED,
    STEP_DONE,
    STEP_GROUPS,
    STEP_LEFTOVERS,
    UNDO_LABEL,
    UNDONE,
    GroupCardVM,
    LeftoverVM,
    chosen_label,
    done_title,
    existing_spelling,
    group_cards,
    groups_saved_text,
    is_uncategorized,
    left_line,
    leftover_rows,
    leftovers_after,
    name_counter,
    name_error,
    opens_group,
    saved_text,
)
from .catalog_order_state import CatalogOrderState
from .catalog_provider import CatalogError, list_order, list_products, set_category, suggest_groups
from .catalog_state import CatalogState
from .catalog_vm import return_path_from_query
from .creative_provider import acting_user_id, default_brand_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Primero completa tu marca (logo y colores) y vuelve a subir tus productos."
_UNDO_MS = 6000


def _failure_text(exc: BaseException) -> str:
    """The service's own sentence for a name it refuses; the generic one otherwise."""
    if isinstance(exc, CatalogError) and exc.args and isinstance(exc.args[0], str):
        return exc.args[0]
    return SAVE_FAILED


class CatalogGroupState(rx.State):
    """The flow: open or not, its step, the proposals, the leftovers and the writes."""

    open: bool = False
    step: int = STEP_GROUPS
    loading: bool = False
    busy: bool = False
    error: str = ""
    #: The flow had proposals when it opened: «Paso N de 2»; without them, no counter.
    with_groups: bool = False
    #: Nothing was left without a category when it opened (an old link).
    all_grouped: bool = False
    return_to: str = ""
    category_total: int = 0

    renaming: int = -1
    rename_text: str = ""
    rename_error: str = ""

    checked: list[str] = []
    sheet_open: bool = False
    sheet_choice: str = ""
    sheet_new: str = ""
    sheet_error: str = ""
    #: The brand's named categories, in order (the choices of «Poner en…»).
    categories: list[str] = []

    #: {"product_id", "name", "price_label"} of every product without a category.
    _products: list[dict[str, str]] = []
    #: {"name", "ids", "accepted"} — the proposals still to store.
    _groups: list[dict[str, Any]] = []
    #: Step 2's list.
    _left: list[dict[str, str]] = []
    #: The last «Poner en…» (what «Deshacer» sends back to «Otros»).
    _undo: dict[str, Any] = {}
    _brand_id: str = ""

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def cards(self) -> list[GroupCardVM]:
        names = {p["product_id"]: p["name"] for p in self._products}
        return group_cards(self._groups, names, self.renaming)

    @rx.var
    def leftovers(self) -> list[LeftoverVM]:
        return leftover_rows(self._left, self.checked)

    @rx.var
    def left_text(self) -> str:
        """Under step 1: «Quedan 7 para el paso 2»."""
        return left_line(len(leftovers_after(self._products, self._groups)))

    @rx.var
    def chosen_text(self) -> str:
        return chosen_label(len(self.checked))

    @rx.var
    def has_checked(self) -> bool:
        return len(self.checked) > 0

    @rx.var
    def step_number(self) -> int:
        return 2 if self.step == STEP_LEFTOVERS else 1

    @rx.var
    def step_total(self) -> int:
        return 2 if self.with_groups else 1

    @rx.var
    def rename_count(self) -> str:
        return name_counter(self.rename_text)

    @rx.var
    def sheet_count(self) -> str:
        return name_counter(self.sheet_new)

    @rx.var
    def sheet_is_new(self) -> bool:
        return self.sheet_choice == NEW_CHOICE

    @rx.var
    def done_text(self) -> str:
        return done_title(self.category_total)

    @rx.var
    def returning(self) -> bool:
        return self.return_to != ""

    # -- session --------------------------------------------------------------------------

    async def _session_ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            cached_brand_id = self._brand_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            async with self:
                self.error = _NO_SESSION
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
                self.error = _NO_BRAND
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        return tenant_id, brand_id, user_id

    async def _ids_or_fail(self, failure: str) -> tuple[UUID, UUID, UUID | None] | None:
        """`_session_ids`, and a raising lookup (the database down) is a failure too."""
        try:
            return await self._session_ids()
        except Exception as exc:  # noqa: BLE001 — never stay busy
            logger.warning("catalog group session failed: %s", type(exc).__name__)
            async with self:
                self.error = failure
            return None

    # -- open, load, close ----------------------------------------------------------------

    @rx.event
    def arrive(self) -> rx.event.EventSpec | None:
        """`?agrupar=1` (WhatsApp step 3's «Agruparlos») opens the flow."""
        try:
            params = self.router.url.query_parameters
        except Exception:  # noqa: BLE001 — no router outside a request (tests)
            params = {}
        if not opens_group(params):
            return None
        self.return_to = return_path_from_query(params)
        return self.open_flow()

    @rx.event
    def open_flow(self) -> rx.event.EventSpec:
        self.open = True
        self.step = STEP_GROUPS
        self.loading = True
        self.error = ""
        self.all_grouped = False
        self.renaming = -1
        self.checked = []
        self.sheet_open = False
        return CatalogGroupState.load_flow

    @rx.event
    def set_open(self, value: bool) -> rx.event.EventSpec | None:
        if value:
            return None
        return self.close_flow()

    @rx.event
    def close_flow(self) -> rx.event.EventSpec:
        """«Volver a tus productos» (or the drawer closed): the list re-read."""
        self.open = False
        self.sheet_open = False
        if self.return_to:
            back, self.return_to = self.return_to, ""
            return rx.redirect(back)
        return CatalogState.load_catalog

    @rx.event
    def go_order(self) -> list[rx.event.EventSpec]:
        """The end's «Ordenar tu menú»."""
        self.open = False
        self.return_to = ""
        return [CatalogState.load_catalog, CatalogOrderState.open_order]

    @rx.event(background=True)
    async def load_flow(self) -> None:
        ids = await self._ids_or_fail(SAVE_FAILED)
        if ids is None:
            async with self:
                self.loading = False
            return
        tenant_id, brand_id, _ = ids
        try:
            products = await asyncio.to_thread(list_products, tenant_id, brand_id)
            groups = await asyncio.to_thread(suggest_groups, tenant_id, brand_id)
            order = await asyncio.to_thread(list_order, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the database: say so, keep the page
            logger.error("catalog group load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = SAVE_FAILED
            return
        loose = [
            {"product_id": p.product_id, "name": p.name, "price_label": p.price_label}
            for p in products
            if is_uncategorized(p.category)
        ]
        loose_ids = {p["product_id"] for p in loose}
        async with self:
            self._products = loose
            self._groups = [
                {"name": name, "ids": [i for i in ids_ if i in loose_ids], "accepted": True}
                for name, ids_ in groups
            ]
            self._groups = [g for g in self._groups if len(g["ids"]) >= 2]
            self.categories = [g.label for g in order if g.name]
            self.with_groups = bool(self._groups)
            self.loading = False
            if not loose:
                self.all_grouped = True
                self.step = STEP_DONE
                self.category_total = len(self.categories)
            elif not self._groups:
                self._left = list(loose)
                self.step = STEP_LEFTOVERS

    # -- step 1: the proposals ------------------------------------------------------------

    @rx.event
    def toggle_group(self, index: int) -> None:
        """«No agrupar» ↔ «Deshacer»."""
        if self.busy or not 0 <= index < len(self._groups):
            return
        groups = [dict(g) for g in self._groups]
        groups[index]["accepted"] = not groups[index]["accepted"]
        self._groups = groups
        if self.renaming == index:
            self.renaming = -1

    @rx.event
    def start_rename(self, index: int) -> None:
        if self.busy or not 0 <= index < len(self._groups):
            return
        self.renaming = index
        self.rename_text = self._groups[index]["name"]
        self.rename_error = ""

    @rx.event
    def set_rename_text(self, value: str) -> None:
        self.rename_text = value
        self.rename_error = ""

    @rx.event
    def cancel_rename(self) -> None:
        self.renaming = -1
        self.rename_error = ""

    @rx.event
    def save_rename(self) -> None:
        index = self.renaming
        if not 0 <= index < len(self._groups):
            return
        problem = name_error(self.rename_text)
        if problem:
            self.rename_error = problem
            return
        groups = [dict(g) for g in self._groups]
        groups[index]["name"] = existing_spelling(self.rename_text, self.categories)
        self._groups = groups
        self.renaming = -1

    @rx.event(background=True)
    async def store_groups(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Siguiente»: every accepted proposal, one write each. A failure stops there:
        the groups already stored leave the list (the database has them), the rest
        stay, and the owner reads why."""
        async with self:
            if self.busy or self.step != STEP_GROUPS:
                return
            if self.renaming >= 0:
                self.rename_error = self.rename_error or name_error(self.rename_text)
                return
            self.busy = True
            self.error = ""
            pending = [dict(g) for g in self._groups if g["accepted"]]
        ids = await self._ids_or_fail(SAVE_FAILED)
        if ids is None:
            async with self:
                self.busy = False
            return
        tenant_id, brand_id, user_id = ids
        stored = 0
        for group in pending:
            try:
                await asyncio.to_thread(
                    set_category, tenant_id, brand_id, user_id, list(group["ids"]), group["name"]
                )
            except Exception as exc:  # noqa: BLE001 — any failure: say it, keep the rest
                logger.warning("catalog group write failed: %s", type(exc).__name__)
                async with self:
                    self.busy = False
                    self.error = _failure_text(exc)
                return
            stored += 1
            async with self:
                done = set(group["ids"])
                self._groups = [g for g in self._groups if set(g["ids"]) != done]
                self._products = [p for p in self._products if p["product_id"] not in done]
                if group["name"] not in self.categories:
                    self.categories = [*self.categories, group["name"]]
        async with self:
            self.busy = False
            self._left = leftovers_after(self._products, self._groups)
            self._groups = []
            self.checked = []
            if not self._left:
                self.step = STEP_DONE
                self.category_total = len(self.categories)
            else:
                self.step = STEP_LEFTOVERS
        if stored:
            yield rx.toast.success(groups_saved_text(stored))

    # -- step 2: what is left -------------------------------------------------------------

    @rx.event
    def back_to_groups(self) -> rx.event.EventSpec | None:
        """«Volver a los grupos»: the proposals are read again (what was stored stays)."""
        if self.busy or not self.with_groups:
            return None
        return self.open_flow()

    @rx.event
    def toggle_leftover(self, product_id: str) -> None:
        if self.busy or product_id not in {p["product_id"] for p in self._left}:
            return
        if product_id in self.checked:
            self.checked = [i for i in self.checked if i != product_id]
        else:
            self.checked = [*self.checked, product_id]

    @rx.event
    def open_sheet(self) -> None:
        if not self.checked or self.busy:
            return
        self.sheet_open = True
        self.sheet_choice = self.categories[0] if self.categories else NEW_CHOICE
        self.sheet_new = ""
        self.sheet_error = ""

    @rx.event
    def close_sheet(self) -> None:
        self.sheet_open = False
        self.sheet_error = ""

    @rx.event
    def set_sheet_choice(self, value: str) -> None:
        self.sheet_choice = value
        self.sheet_error = ""

    @rx.event
    def set_sheet_new(self, value: str) -> None:
        self.sheet_new = value
        self.sheet_error = ""

    @rx.event
    def put_here(self) -> rx.event.EventSpec | None:
        """«Poner aquí»: the marked products leave the list at once; `store_put` writes."""
        if self.busy or not self.checked:
            return None
        if self.sheet_choice == NEW_CHOICE:
            problem = name_error(self.sheet_new)
            if problem:
                self.sheet_error = problem
                return None
            category = existing_spelling(self.sheet_new, self.categories)
        elif self.sheet_choice in self.categories:
            category = self.sheet_choice
        else:
            self.sheet_error = SAVE_FAILED
            return None
        moving = [p["product_id"] for p in self._left if p["product_id"] in set(self.checked)]
        self._undo = {
            "ids": moving,
            "category": category,
            "left": [dict(p) for p in self._left],
            "categories": list(self.categories),
        }
        self._left = [p for p in self._left if p["product_id"] not in set(moving)]
        self.checked = []
        self.sheet_open = False
        if category not in self.categories:
            self.categories = [*self.categories, category]
        return CatalogGroupState.store_put

    @rx.event(background=True)
    async def store_put(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.busy or not self._undo:
                return
            self.busy = True
            self.error = ""
            job = dict(self._undo)
        ids = await self._ids_or_fail(SAVE_FAILED)
        failure: BaseException | None = None
        if ids is not None:
            tenant_id, brand_id, user_id = ids
            try:
                await asyncio.to_thread(
                    set_category, tenant_id, brand_id, user_id, job["ids"], job["category"]
                )
            except Exception as exc:  # noqa: BLE001 — any failure rolls the screen back
                logger.warning("catalog group put failed: %s", type(exc).__name__)
                failure = exc
        if ids is None or failure is not None:
            async with self:
                self._left = job["left"]
                self.categories = job["categories"]
                self.checked = list(job["ids"])
                self._undo = {}
                self.busy = False
                if failure is not None:
                    self.error = _failure_text(failure)
            return
        async with self:
            self.busy = False
            finished = not self._left
            if finished:
                self.step = STEP_DONE
                self.category_total = len(self.categories)
        yield rx.toast.success(
            saved_text(len(job["ids"]), job["category"]),
            duration=_UNDO_MS,
            action={"label": UNDO_LABEL, "on_click": CatalogGroupState.undo_put},
        )

    @rx.event(background=True)
    async def undo_put(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Deshacer»: the products back to «Otros» and onto step 2's list."""
        async with self:
            if self.busy or not self._undo:
                return
            self.busy = True
            job, self._undo = dict(self._undo), {}
        ids = await self._ids_or_fail(SAVE_FAILED)
        if ids is not None:
            tenant_id, brand_id, user_id = ids
            try:
                await asyncio.to_thread(set_category, tenant_id, brand_id, user_id, job["ids"], "")
            except Exception as exc:  # noqa: BLE001
                logger.warning("catalog group undo failed: %s", type(exc).__name__)
                async with self:
                    self.busy = False
                    self.error = _failure_text(exc)
                return
        else:
            async with self:
                self.busy = False
            return
        async with self:
            self.busy = False
            self._left = job["left"]
            self.step = STEP_LEFTOVERS
        yield rx.toast.success(UNDONE, duration=_UNDO_MS)

    @rx.event
    async def leave_rest(self) -> None:
        """«Dejar el resto en «Otros»»: nothing is stored; the notice stays hidden until a
        NEW product without a category appears."""
        if self.busy:
            return
        catalog = await self.get_state(CatalogState)
        keep = [p["product_id"] for p in self._left]
        catalog.dismissed_uncategorized = sorted({*catalog.dismissed_uncategorized, *keep})
        self._left = []
        self.checked = []
        self.sheet_open = False
        self.step = STEP_DONE
        self.category_total = len(self.categories)
