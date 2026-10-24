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
from qualify_api.creative.service import ApprovalBlocked, DraftExpired

from .auth_state import AuthState
from .creative_provider import acting_user_id, approve_draft, draft_detail, reject_draft

# m-24842978: the same words here and on the publication's own page after approving —
# it is not out yet — live with `approval_notice`; re-exported for the screens' tests.
from .creative_vm import (  # noqa: F401
    APPROVED_NOT_READY_TOAST,
    APPROVED_TOAST,
    APPROVED_TOAST_ACTION,
    approval_notice,
)
from .pending_state import PendingState
from .planner_provider import load_gallery
from .planner_vm import (
    GALLERY_FILTER_ALL,
    GALLERY_FILTER_PARAM,
    GALLERY_STATE_FILTERS,
    CategoryOptionVM,
    PostOptionVM,
    filter_posts,
    gallery_filter_from_param,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudo cargar la galería. Inténtalo de nuevo."
_REVIEW_FAILED = "No se pudo completar. Abre la publicación y vuelve a intentarlo."
_NO_PASSING_VARIANT = (
    "Ninguna versión cumple las reglas de tu marca: abre la publicación para editarla o crear otra."
)


def schedule_readiness(posts: list[PostOptionVM], post_id: str) -> tuple[bool, str]:
    """m-24842978: can this just-approved publication be given a day and time, and if
    not, why (the evaluator's reason, as the card shows it)? An approved publication can
    still be «aprobada pero no lista» (no connected account fits it, its media does not
    suit any destination…). A publication missing from the list is not judged here:
    Tu semana stays the gate and says why itself (pure — tested directly)."""
    for post in posts:
        if post.post_id == post_id:
            return post.schedulable, post.readiness_note
    return True, ""


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
            # m-24842962: a `?estado=` in the address (Inicio's card) opens filtered.
            requested = gallery_filter_from_param(
                str(self.router.url.query_parameters.get(GALLERY_FILTER_PARAM, "") or "")
            )
            if requested is not None:
                self.state_filter = requested
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
            approved = await asyncio.to_thread(
                approve_draft, tenant_id, draft_id, UUID(variant.variant_id), user_id
            )
        except ApprovalBlocked as exc:
            # ticket 24803289: a variations piece quoting a price that is not the
            # catalog's — said as it is, so the operator knows what to correct
            async with self:
                self.busy_post_id = ""
            yield rx.toast.error(exc.detail)
            return
        except DraftExpired as exc:
            # m-24820142: a 480p draft too old to make its final
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
        # The grid is re-read now (not after the toast) so the toast can tell an
        # approved publication that can be given a day and time from one that is
        # «aprobada pero no lista» — and offer «Elegir día y hora» only to the first.
        try:
            data = await asyncio.to_thread(load_gallery, tenant_id)
        except Exception as exc:  # noqa: BLE001 — the approval stands; `load` says the rest
            logger.warning("gallery reload after approve failed: %s", type(exc).__name__)
            data = None
        async with self:
            self.busy_post_id = ""
            if data is not None:
                self.posts = list(data.posts)
                self.categories = list(data.categories)
        ready, _note = schedule_readiness(list(data.posts) if data else [], post_id)
        # m-24820142 first: a 1080p final being made (or that could not be ordered) holds
        # the publication back, so no day and time is offered — the piece says the rest.
        # Otherwise m-24842978: it is not out yet; the card shows what is missing, if any.
        notice = approval_notice(approved.video_draft, ready=ready, elsewhere="Ábrela")
        if notice.offer_schedule:
            yield getattr(rx.toast, notice.kind)(
                notice.text,
                action={
                    "label": APPROVED_TOAST_ACTION,
                    "on_click": rx.redirect(f"/planner?post={post_id}"),
                },
            )
        else:
            yield getattr(rx.toast, notice.kind)(notice.text)
        if data is None:
            yield GalleryState.load
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now

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
        yield rx.toast.success("Publicación descartada.")
        yield GalleryState.load
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now
