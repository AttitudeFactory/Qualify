"""State for `/drafts` — the POST gallery (QUA-118).

Every POST of the brand as a card with its derived state (Borrador · Por completar ·
Listo · Usado · Desechado), filters by state and category, and «Asignar», which hands
the POST to the Planificador's own drawer (`/planner?post=<id>`) — the gallery never
plans anything itself and never duplicates the assign flow.

Reads through `planner_provider.load_gallery` (RLS-scoped, off the event loop), the same
reader and view-model the «Sin programar» panel uses.
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx

from .auth_state import AuthState
from .planner_provider import load_gallery
from .planner_vm import (
    GALLERY_FILTER_ALL,
    GALLERY_STATE_FILTERS,
    CategoryOptionVM,
    PostOptionVM,
    filter_posts,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudo cargar la galería. Inténtalo de nuevo."


class GalleryState(rx.State):
    loading: bool = True
    error: str = ""
    posts: list[PostOptionVM] = []
    categories: list[CategoryOptionVM] = []
    state_filter: str = GALLERY_FILTER_ALL
    category_filter: str = GALLERY_FILTER_ALL

    @rx.var
    def visible(self) -> list[PostOptionVM]:
        return filter_posts(self.posts, state=self.state_filter, category=self.category_filter)

    @rx.var
    def visible_count(self) -> int:
        return len(self.visible)

    @rx.var
    def total_count(self) -> int:
        return len(self.posts)

    @rx.var
    def state_counts(self) -> dict[str, int]:
        """How many POSTs each state filter would show — the number on each chip."""
        counts = {value: 0 for value, _label in GALLERY_STATE_FILTERS}
        counts[GALLERY_FILTER_ALL] = len(self.posts)
        for post in self.posts:
            counts[post.gallery_state] = counts.get(post.gallery_state, 0) + 1
        return counts

    @rx.var
    def is_filtered(self) -> bool:
        return self.state_filter != GALLERY_FILTER_ALL or self.category_filter != GALLERY_FILTER_ALL

    @rx.event
    def set_state_filter(self, value: str) -> None:
        known = {value for value, _label in GALLERY_STATE_FILTERS} | {GALLERY_FILTER_ALL}
        self.state_filter = value if value in known else GALLERY_FILTER_ALL

    @rx.event
    def set_category_filter(self, value: str) -> None:
        self.category_filter = value or GALLERY_FILTER_ALL

    @rx.event
    def clear_filters(self) -> None:
        self.state_filter = GALLERY_FILTER_ALL
        self.category_filter = GALLERY_FILTER_ALL

    @rx.event
    def assign(self, post_id: str):
        """«Asignar» from a card: the Planificador opens its drawer on this POST — one
        drawer, one assign flow, no copy of it here."""
        return rx.redirect(f"/planner?post={post_id}")

    @rx.event(background=True)
    async def load(self):
        async with self:
            self.loading = True
            self.error = ""
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            async with self:
                self.loading = False
                self.error = _NO_TENANT
            return
        try:
            data = await asyncio.to_thread(load_gallery, tenant_id)
        except Exception as exc:
            logger.error("gallery load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = _LOAD_FAILED
            return
        async with self:
            self.posts = list(data.posts)
            self.categories = list(data.categories)
            self.loading = False
