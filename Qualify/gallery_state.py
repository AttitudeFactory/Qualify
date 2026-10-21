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
from uuid import UUID

import reflex as rx
from qualify_api.creative.service import ApprovalBlocked

from .auth_state import AuthState
from .creative_provider import acting_user_id, approve_draft, draft_detail, reject_draft
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
_REVIEW_FAILED = "No se pudo completar la acción. Abre el POST y vuelve a intentarlo."
_NO_PASSING_VARIANT = (
    "Ninguna variante cumple las reglas de tu marca: abre el POST para editarla o regenerar."
)

# The gallery's reading order: what can go out now first, then what needs you, then
# history. A stable sort, so within a state the newest stays first.
_STATE_ORDER = {"schedulable": 0, "needs_action": 1, "draft": 2, "used": 3, "discarded": 4}


def sort_for_gallery(posts: list[PostOptionVM]) -> list[PostOptionVM]:
    """Ready POSTs first, history last (pure — tested directly)."""
    return sorted(posts, key=lambda p: _STATE_ORDER.get(p.gallery_state, 9))


class GalleryState(rx.State):
    loading: bool = True
    error: str = ""
    posts: list[PostOptionVM] = []
    categories: list[CategoryOptionVM] = []
    state_filter: str = GALLERY_FILTER_ALL
    category_filter: str = GALLERY_FILTER_ALL
    # Quick review from a card: the POST being approved/rejected (its buttons spin), and
    # the one whose rejection is being confirmed — a mis-click never discards a draft.
    busy_post_id: str = ""
    reject_post_id: str = ""
    reject_post_title: str = ""

    @rx.var
    def visible(self) -> list[PostOptionVM]:
        return sort_for_gallery(
            filter_posts(self.posts, state=self.state_filter, category=self.category_filter)
        )

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

    # -- quick review from a card ----------------------------------------------------

    async def _tenant(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            return tenant_uuid(auth.session_tenant_id)

    @rx.event(background=True)
    async def quick_approve(self, post_id: str):
        """«Aprobar» on a card: the draft's chosen variant — or the first one that passes
        the brand rules — becomes the POST's approved text, as on the POST's own page."""
        async with self:
            if self.busy_post_id:
                return
            self.busy_post_id = post_id
        tenant_id = await self._tenant()
        try:
            draft_id = UUID(post_id)
            if tenant_id is None:
                raise LookupError("no tenant")
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
            draft = await asyncio.to_thread(draft_detail, tenant_id, draft_id)
            variant = next((v for v in (draft.variants if draft else ()) if v.passed), None)
            if draft is None or user_id is None:
                raise LookupError("draft or user missing")
            if variant is None:
                async with self:
                    self.busy_post_id = ""
                yield rx.toast.warning(_NO_PASSING_VARIANT)
                return
            await asyncio.to_thread(
                approve_draft, tenant_id, draft_id, UUID(variant.variant_id), user_id
            )
        except ApprovalBlocked as exc:
            # ticket 24803289: a variations piece quoting a price that is not the
            # catalog's — said as it is, so the operator knows what to correct
            async with self:
                self.busy_post_id = ""
            yield rx.toast.error(exc.detail)
            return
        except Exception as exc:  # noqa: BLE001 — one card's failure never breaks the grid
            logger.warning("gallery quick approve failed: %s", type(exc).__name__)
            async with self:
                self.busy_post_id = ""
            yield rx.toast.error(_REVIEW_FAILED)
            return
        async with self:
            self.busy_post_id = ""
        yield rx.toast.success("POST aprobado: ya puedes programarlo en el Planificador.")
        yield GalleryState.load

    @rx.event
    def ask_reject_post(self, post_id: str, title: str) -> None:
        self.reject_post_id = post_id
        self.reject_post_title = title

    @rx.event
    def set_reject_post_open(self, value: bool) -> None:
        if not value:
            self.reject_post_id = ""
            self.reject_post_title = ""

    @rx.event(background=True)
    async def confirm_reject_post(self):
        async with self:
            post_id = self.reject_post_id
            self.reject_post_id = ""
            if not post_id or self.busy_post_id:
                return
            self.busy_post_id = post_id
        tenant_id = await self._tenant()
        try:
            if tenant_id is None:
                raise LookupError("no tenant")
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
            if user_id is None:
                raise LookupError("no user")
            await asyncio.to_thread(
                lambda: reject_draft(
                    tenant_id,
                    UUID(post_id),
                    user_id,
                    reason="rejected from the gallery",
                    regenerate=False,
                )
            )
        except Exception as exc:  # noqa: BLE001 — one card's failure never breaks the grid
            logger.warning("gallery quick reject failed: %s", type(exc).__name__)
            async with self:
                self.busy_post_id = ""
            yield rx.toast.error(_REVIEW_FAILED)
            return
        async with self:
            self.busy_post_id = ""
        yield rx.toast.success("POST rechazado.")
        yield GalleryState.load
