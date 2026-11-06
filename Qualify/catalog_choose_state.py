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

from typing import Any
from urllib.parse import urlencode

import reflex as rx

from .catalog_choose_vm import (
    ChoiceVM,
    ProductChoicesVM,
    business_choices,
    chosen_label,
    create_href,
    product_choices,
    toggle,
    with_order,
)
from .catalog_gallery_state import CatalogGalleryState
from .catalog_state import CatalogState

#: The choice's own address (N5): `/catalog?elegir=1` — the phone's «atrás» closes it
#: and leaves Galería where it was.
CHOOSE_PARAM = "elegir"
_CATALOG_PATH = "/catalog"
_HISTORY_BACK = "window.history.back()"


def choose_href(query: dict[str, Any], on: bool) -> str:
    """`/catalog` with (or without) `?elegir=1`, keeping the address's other parameters."""
    params = {k: str(v) for k, v in (query or {}).items() if k != CHOOSE_PARAM}
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
        """Galería's on_load and back/forward: `?elegir=1` gone → the choice closes
        (the phone's «atrás»); `?elegir=1` this tab did not open (a reload, an old
        link) → dropped, the Galería shows."""
        on = self._url_on()
        if self.choosing and not on:
            self.choosing = False
            self.chosen = []
            self.error = ""
            self._pushed = False
        elif on and not self.choosing:
            return [rx.redirect(choose_href(self._query(), on=False), replace=True)]
        return []

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
