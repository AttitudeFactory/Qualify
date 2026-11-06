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


class CatalogChooseState(rx.State):
    choosing: bool = False
    #: The chosen tokens (`n:<uuid>` / `p:<uuid>`), in the order they were tapped.
    chosen: list[str] = []
    #: «Puedes elegir hasta 10.» after an eleventh tap.
    error: str = ""
    _business: list[ChoiceVM] = []
    _products: list[ProductChoicesVM] = []

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
    async def start(self) -> None:
        """«Elegir para una publicación»."""
        gallery = await self.get_state(CatalogGalleryState)
        catalog = await self.get_state(CatalogState)
        self._business = business_choices(gallery.items)
        self._products = product_choices(catalog.products)
        self.chosen = []
        self.error = ""
        self.choosing = True

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
    def cancel(self) -> None:
        """«Cancelar»: out, nothing chosen."""
        self.choosing = False
        self.chosen = []
        self.error = ""

    @rx.event
    def create(self) -> rx.event.EventSpec | None:
        """«Crear publicación con estas»: Crear opens with them, in this order."""
        if not self.chosen:
            return None
        href = create_href(self.chosen)
        self.cancel()
        return rx.redirect(href)

    @rx.event
    def page_left(self) -> None:
        """Galería unmounted: the choice never comes back by itself."""
        self.cancel()
