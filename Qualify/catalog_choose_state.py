"""Reflex state for «Elegir para una publicación» (CM-5, m-24955926).

The owner taps photos and videos of the business and of the products in the order the
publication will show them (a number on each), up to 10, and «Crear publicación con
estas» opens `/create?medios=…` (CM-6/CM-7). «Cancelar» leaves without choosing.

What can be chosen is a snapshot taken when the view opens: the section's ready tiles
(`CatalogGalleryState.items` — a video being prepared, that failed or being cut is not
`selectable`) and the products with media (`CatalogState.products`). Nothing here reads
the database: the generator re-validates every chosen medium under RLS (CM-6), so a
token from the browser is never trusted beyond being put in the link. Session-only
state, reset on logout (`auth_state.business_state_classes`).
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlencode

import reflex as rx
from qualify_api.creative.gallery_piece import (
    MEDIA_QUERY_PARAM,
    format_media_query,
    parse_media_query,
)

from .auth_state import AuthState
from .catalog_choose_vm import (
    MAX_CHOSEN,
    ChoiceVM,
    ProductChoicesVM,
    business_choices,
    chosen_label,
    create_href,
    product_choices,
    toggle,
    with_order,
)
from .catalog_gallery_provider import load_gallery
from .catalog_gallery_state import CatalogGalleryState
from .catalog_provider import list_products
from .catalog_state import CatalogState
from .creative_provider import default_brand_id
from .tenant import tenant_uuid

#: The choice's own address (N5): `/catalog?elegir=1` — the phone's «atrás» closes it
#: and leaves Galería where it was.
CHOOSE_PARAM = "elegir"
_CATALOG_PATH = "/catalog"
_HISTORY_BACK = "window.history.back()"


def choose_href(query: dict[str, Any], on: bool) -> str:
    """`/catalog` with (or without) `?elegir=1`, keeping the address's other parameters."""
    params = {
        k: str(v) for k, v in (query or {}).items() if k not in (CHOOSE_PARAM, MEDIA_QUERY_PARAM)
    }
    if on:
        params[CHOOSE_PARAM] = "1"
    return f"{_CATALOG_PATH}?{urlencode(params)}" if params else _CATALOG_PATH


class CatalogChooseState(rx.State):
    choosing: bool = False
    #: The chosen tokens (`n:<uuid>` / `p:<uuid>`), in the order they were tapped.
    chosen: list[str] = []
    #: «Puedes elegir hasta 10.» after an eleventh tap.
    error: str = ""
    _business: list[ChoiceVM] = []
    _products: list[ProductChoicesVM] = []
    #: This tab pushed `?elegir=1` (closing then steps back instead of adding an entry).
    _pushed: bool = False

    def _query(self) -> dict[str, Any]:
        try:
            return dict(self.router.url.query_parameters)
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            return {}

    def _url_on(self) -> bool:
        return str(self._query().get(CHOOSE_PARAM, "") or "") == "1"

    def _close(self) -> list[rx.event.EventSpec]:
        """Out of the choice, and `?elegir=1` off the address — decided from the
        address the tap carries."""
        on_address = self._url_on()
        pushed = self._pushed
        self.choosing = False
        self.chosen = []
        self.error = ""
        self._pushed = False
        if not on_address:
            return []
        if pushed:
            return [rx.call_script(_HISTORY_BACK)]
        return [rx.redirect(choose_href(self._query(), on=False), replace=True)]

    @rx.var
    def business(self) -> list[ChoiceVM]:
        return with_order(self._business, self.chosen)

    @rx.var
    def products(self) -> list[ProductChoicesVM]:
        return [
            ProductChoicesVM(name=g.name, choices=tuple(with_order(g.choices, self.chosen)))
            for g in self._products
        ]

    @rx.var
    def count_text(self) -> str:
        return chosen_label(len(self.chosen))

    @rx.var
    def has_chosen(self) -> bool:
        return len(self.chosen) > 0

    @rx.event
    def sync_url(self) -> list[rx.event.EventSpec]:
        """Back/forward (the popstate path, `CatalogState.enter_history`, which reads the
        address at that moment): `?elegir=1` gone → the choice closes (the phone's
        «atrás»). A fresh tab or an old link with `?elegir=1` → dropped, the Galería
        shows (a reload of a tab that is choosing keeps the choice: its state survives).
        Not on on_load: measured live, an on_load carrying the address from before the
        push closed the choice 50 ms after it opened."""
        on = self._url_on()
        if self.choosing and not on:
            self.choosing = False
            self.chosen = []
            self.error = ""
            self._pushed = False
        elif on and not self.choosing:
            if self._query().get(MEDIA_QUERY_PARAM):
                # «Cambiar» in Crear (CM-7): the same choice, to change it
                return [CatalogChooseState.resume]
            return [rx.redirect(choose_href(self._query(), on=False), replace=True)]
        return []

    @rx.event(background=True)
    async def resume(self) -> None:
        """`/catalog?elegir=1&medios=…` (CM-7's «Cambiar»): the choice opens with those
        media already chosen, in their order. The lists are read here, not from the
        section (which may not have loaded yet); a medium no longer offered is simply
        not chosen."""
        async with self:
            raw = self._query().get(MEDIA_QUERY_PARAM, "")
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        brand_id = await asyncio.to_thread(default_brand_id, tenant_id) if tenant_id else None
        if tenant_id is None or brand_id is None:
            return
        try:
            snapshot = await asyncio.to_thread(load_gallery, tenant_id, brand_id)
            products = await asyncio.to_thread(list_products, tenant_id, brand_id)
        except Exception:  # noqa: BLE001 — the Galería shows; the owner chooses again
            return
        business = business_choices(snapshot.items)
        groups = product_choices(products)
        known = {c.token for c in business} | {c.token for g in groups for c in g.choices}
        parsed = parse_media_query(raw)
        wanted = [format_media_query([ref]) for ref in parsed.refs]
        async with self:
            self._business = business
            self._products = groups
            self.chosen = [t for t in dict.fromkeys(wanted) if t in known][:MAX_CHOSEN]
            self.error = ""
            self.choosing = True
            self._pushed = False

    @rx.event
    async def start(self) -> list[rx.event.EventSpec] | None:
        """«Elegir para una publicación»: the choice opens with its own address."""
        if self.choosing:
            return None
        gallery = await self.get_state(CatalogGalleryState)
        catalog = await self.get_state(CatalogState)
        self._business = business_choices(gallery.items)
        self._products = product_choices(catalog.products)
        self.chosen = []
        self.error = ""
        self.choosing = True
        self._pushed = True
        return [rx.redirect(choose_href(self._query(), on=True))]

    @rx.event
    def pick(self, choice: str) -> None:
        """A tap on a tile: in (last) or out. Only tokens on screen count."""
        known = {c.token for c in self._business} | {
            c.token for g in self._products for c in g.choices
        }
        if choice not in known:
            return
        self.chosen, self.error = toggle(self.chosen, choice)

    @rx.event
    def cancel(self) -> list[rx.event.EventSpec]:
        """«Cancelar»: out, nothing chosen."""
        return self._close()

    @rx.event
    def create(self) -> rx.event.EventSpec | None:
        """«Crear publicación con estas»: Crear opens with them, in this order (on top
        of `?elegir=1`: «atrás» from Crear lands on Galería, which drops it)."""
        if not self.chosen:
            return None
        href = create_href(self.chosen)
        self.choosing = False
        self.chosen = []
        self.error = ""
        self._pushed = False
        return rx.redirect(href)

    @rx.event
    def page_left(self) -> None:
        """Galería unmounted: the choice never comes back by itself."""
        self.choosing = False
        self.chosen = []
        self.error = ""
        self._pushed = False
