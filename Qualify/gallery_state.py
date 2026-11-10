"""State for `/drafts` — the POST gallery (QUA-118).

Every POST of the brand as a card with its state in words (Por revisar · Le falta algo ·
Lista para programar · Ya salió · Descartada · Creándose, m-24842981), filters by that
state and by category, and «Programar», which hands
the POST to the Planificador's own drawer (`/planner?post=<id>`) — the gallery never
plans anything itself and never duplicates the assign flow.

Reads through `planner_provider.load_gallery` (RLS-scoped, off the event loop), the same
reader and view-model the «Sin programar» panel uses.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from uuid import UUID

import reflex as rx
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.service import ApprovalBlocked, DraftExpired
from qualify_creative.creations import load_weights

from .auth_state import AuthState
from .creative_provider import (
    acting_user_id,
    approval_videos,
    approve_draft,
    creations_balance,
    default_brand_id,
    draft_detail,
    recreate_draft,
    reject_draft,
)

# m-24842978: the same words here and on the publication's own page after approving —
# it is not out yet — live with `approval_notice`; re-exported for the screens' tests.
from .creative_vm import (  # noqa: F401
    APPROVED_NOT_READY_TOAST,
    APPROVED_OPEN_ACTION,
    APPROVED_TOAST,
    APPROVED_TOAST_ACTION,
    approval_notice,
    previews_short_text,
    videos_short_text,
)
from .nav_url import replace_url_script, with_query
from .pending_state import PendingState
from .planner_provider import load_gallery
from .planner_vm import (
    APPROVED_CARD_STATES,
    APPROVED_ROUTE,
    DISCARDED,
    DRAFTS_ROUTE,
    FROM_APPROVED,
    GALLERY_FILTER_ALL,
    GALLERY_FILTER_PARAM,
    GALLERY_ORDER_EXPIRY,
    GALLERY_ORDER_PARAM,
    KIND_PARAM,
    PENDING_CARD_STATES,
    PENDING_STATE_FILTERS,
    VIEW_PARAM,
    VIEW_POSTS,
    VIEW_STICKERS,
    CategoryOptionVM,
    PostOptionVM,
    approved_redirect,
    count_line,
    filter_posts,
    gallery_filter_from_param,
    is_approved_card,
    is_pending_card,
    sort_approved,
    sort_pending,
    tab_label,
    view_from_param,
    with_origin,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No pudimos cargar tus publicaciones. Inténtalo de nuevo."
#: m-24986801 (spec §3): «Aprobados» says what it could not bring, and offers «Reintentar».
APPROVED_LOAD_FAILED = "No pudimos traer lo que aprobaste. Vuelve a intentarlo en un momento."
_REVIEW_FAILED = "No se pudo completar. Abre la publicación y vuelve a intentarlo."
_NO_PASSING_VARIANT = (
    "Ninguna versión cumple las reglas de tu marca: abre la publicación para editarla o crear otra."
)


def approval_refused_text(tenant_id: UUID, draft_id: UUID, exc: NotEnoughCreations) -> str:
    """Why a card's «Aprobar» was refused for want of videos (founder, 2026-10-24) — with
    the day they come back when it can be read. Blocking (DB)."""
    try:
        quote = approval_videos(tenant_id, draft_id)
    except Exception:  # noqa: BLE001 — the words still say what happened
        quote = None
    if quote is not None:
        videos, left, quota, renews = quote
        return videos_short_text(videos, left, quota, renews=renews)
    return videos_short_text(exc.videos, exc.videos_left, exc.video_quota)


def recreate_refused_text(tenant_id: UUID, exc: NotEnoughCreations) -> str:
    """Why «Crearla otra vez» was refused: no vista previa (or creation) left. Blocking."""
    renews = ""
    try:
        brand_id = default_brand_id(tenant_id)
        balance = creations_balance(tenant_id, brand_id) if brand_id else None
        renews = balance[2] if balance else ""
    except Exception:  # noqa: BLE001 — the words still say what happened
        renews = ""
    if exc.missing:
        when = renews or "próximo mes"
        return f"Te faltan {exc.missing} creaciones este mes. El {when} se renuevan tus 30."
    return previews_short_text(
        exc.previews, exc.previews_left, load_weights().monthly_preview_quota, renews=renews
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


POSTS_TAB = "Publicaciones"
STICKERS_TAB = "Stickers y videos"


def sort_for_gallery(posts: list[PostOptionVM], *, by_expiry: bool = False) -> list[PostOptionVM]:
    """«Por aprobar»'s order (m-24986801): «Por revisar» first, then «Creándose» — pure,
    tested directly. `by_expiry` (Inicio's «videos vencen pronto», founder 2026-10-24):
    the vistas previas that expire soonest first, then every other POST as usual."""
    usual = sort_pending(posts)
    if not by_expiry:
        return usual
    expiring = sorted((p for p in usual if p.expires_at > 0), key=lambda p: p.expires_at)
    return expiring + [p for p in usual if p.expires_at <= 0]


def pending_posts(posts: list[PostOptionVM]) -> list[PostOptionVM]:
    """What waits for the owner's decision: «Por revisar» and «Creándose» (and anything
    else not approved and not discarded)."""
    return [p for p in posts if is_pending_card(p)]


def approved_posts(posts: list[PostOptionVM]) -> list[PostOptionVM]:
    """What the owner already approved, in «Aprobados»' order, each ficha link carrying
    `?desde=aprobados` so its way back (and the menu) say «Aprobados» (N7)."""
    return [
        replace(p, detail_href=with_origin(p.detail_href, FROM_APPROVED))
        for p in sort_approved(p for p in posts if is_approved_card(p))
    ]


def kind_options(posts: list[PostOptionVM]) -> list[CategoryOptionVM]:
    """The creation types that exist and have something, first-seen order — never an
    invented category."""
    kinds = {p.content_kind: p.content_kind_label for p in posts if p.content_kind_label}
    return [CategoryOptionVM(value=key, label=label) for key, label in kinds.items()]


class GalleryState(rx.State):
    loading: bool = True
    error: str = ""
    posts: list[PostOptionVM] = []
    categories: list[CategoryOptionVM] = []
    state_filter: str = GALLERY_FILTER_ALL
    category_filter: str = GALLERY_FILTER_ALL
    content_kind_filter: str = GALLERY_FILTER_ALL
    # Quick review from a card: the POST being approved/rejected (its buttons spin), and
    # the one whose rejection is being confirmed — a mis-click never discards a draft.
    busy_post_id: str = ""
    reject_post_id: str = ""
    reject_post_title: str = ""
    #: Opened from Inicio's «videos vencen pronto»: the soonest-expiring first.
    sort_by_expiry: bool = False
    # m-24986801: which list is open (`?ver=`), and whether the address chose it — when
    # it did not and the publications are empty while the stickers are not, the screen
    # opens on «Stickers y videos» (`settle_view`).
    view: str = VIEW_POSTS
    view_chosen: bool = False
    #: Which screen this state is serving: `/drafts` or `/aprobados` (for the address).
    route: str = DRAFTS_ROUTE
    # «Aprobados»: the type filter (`&tipo=`) and the state of an old `?estado=listo|usado`.
    approved_kind_filter: str = GALLERY_FILTER_ALL
    approved_state_filter: str = GALLERY_FILTER_ALL

    # -- «Por aprobar» --------------------------------------------------------------------

    @rx.var
    def pending(self) -> list[PostOptionVM]:
        return pending_posts(self.posts)

    @rx.var
    def visible(self) -> list[PostOptionVM]:
        return sort_for_gallery(
            filter_posts(
                self.pending,
                state=self.state_filter,
                category=self.category_filter,
                content_kind=self.content_kind_filter,
            ),
            by_expiry=self.sort_by_expiry,
        )

    @rx.var
    def visible_count(self) -> int:
        return len(self.visible)

    @rx.var
    def total_count(self) -> int:
        """How many publications wait for the owner (the «Publicaciones (n)» number)."""
        return len(self.pending)

    @rx.var
    def pending_count(self) -> int:
        return len(self.pending)

    @rx.var
    def pending_count_line(self) -> str:
        return count_line(len(self.visible), len(self.pending), filtered=self.is_filtered)

    @rx.var
    def posts_tab_label(self) -> str:
        return tab_label(POSTS_TAB, len(self.pending), known=not self.loading)

    @rx.var
    def discarded(self) -> list[PostOptionVM]:
        """Discarded publications, folded at the foot of «Por aprobar» (decision D2)."""
        return [p for p in self.posts if p.card_state == DISCARDED]

    @rx.var
    def discarded_count(self) -> int:
        return len(self.discarded)

    @rx.var
    def state_counts(self) -> dict[str, int]:
        """How many POSTs each state chip would show — the number on each chip."""
        counts = {value: 0 for value, _label in PENDING_STATE_FILTERS}
        posts = filter_posts(
            self.pending,
            state=GALLERY_FILTER_ALL,
            category=self.category_filter,
            content_kind=self.content_kind_filter,
        )
        counts[GALLERY_FILTER_ALL] = len(posts)
        for post in posts:  # by the card's state (m-24842981), as the filters
            counts[post.card_state] = counts.get(post.card_state, 0) + 1
        return counts

    @rx.var
    def is_filtered(self) -> bool:
        return any(
            value != GALLERY_FILTER_ALL
            for value in (self.state_filter, self.category_filter, self.content_kind_filter)
        )

    @rx.var
    def content_kind_options(self) -> list[CategoryOptionVM]:
        return kind_options(self.pending)

    # -- «Aprobados» ----------------------------------------------------------------------

    @rx.var
    def approved(self) -> list[PostOptionVM]:
        return approved_posts(self.posts)

    @rx.var
    def approved_visible(self) -> list[PostOptionVM]:
        return filter_posts(
            self.approved,
            state=self.approved_state_filter,
            category=GALLERY_FILTER_ALL,
            content_kind=self.approved_kind_filter,
        )

    @rx.var
    def approved_count(self) -> int:
        return len(self.approved)

    @rx.var
    def approved_visible_count(self) -> int:
        return len(self.approved_visible)

    @rx.var
    def approved_count_line(self) -> str:
        return count_line(
            len(self.approved_visible), len(self.approved), filtered=self.approved_is_filtered
        )

    @rx.var
    def approved_tab_label(self) -> str:
        return tab_label(POSTS_TAB, len(self.approved), known=not self.loading)

    @rx.var
    def approved_kind_options(self) -> list[CategoryOptionVM]:
        return kind_options(self.approved)

    @rx.var
    def approved_is_filtered(self) -> bool:
        return (
            self.approved_kind_filter != GALLERY_FILTER_ALL
            or self.approved_state_filter != GALLERY_FILTER_ALL
        )

    @rx.var
    def approved_state_label(self) -> str:
        """The words of an `?estado=` filter carried over from an old link ("" none)."""
        post = next((p for p in self.posts if p.card_state == self.approved_state_filter), None)
        return post.card_label if post is not None else ""

    # -- events ---------------------------------------------------------------------------

    def _address(self) -> str:
        params: dict[str, str] = {VIEW_PARAM: self.view}
        if self.route == APPROVED_ROUTE and self.view == VIEW_POSTS:
            if self.approved_kind_filter != GALLERY_FILTER_ALL:
                params[KIND_PARAM] = self.approved_kind_filter
        return with_query(self.route, **params)

    @rx.event
    def set_view(self, value: str | list[str]):
        """The segmented control: switch the list and write `?ver=` (no new history step,
        no re-read — `replaceState`, as the other tabbed screens)."""
        chosen = view_from_param(value if isinstance(value, str) else "")
        if not chosen:
            return None
        self.view = chosen
        self.view_chosen = True
        return rx.call_script(replace_url_script(self._address()))

    @rx.event
    async def settle_view(self):
        """With no `?ver=`: the publications empty while «Stickers y videos» has something
        opens that list instead. Run when either read lands (both must have)."""
        if self.view_chosen or self.loading or self.error:
            return
        from .seasonal_state import SeasonalState  # noqa: PLC0415 — no import cycle

        seasonal = await self.get_state(SeasonalState)
        if not seasonal.loaded:
            return
        approved_screen = self.route == APPROVED_ROUTE
        posts = self.approved_count if approved_screen else self.pending_count
        stickers = seasonal.approved_count if approved_screen else seasonal.pending_count
        if posts == 0 and stickers > 0:
            self.view = VIEW_STICKERS
        self.view_chosen = True  # decided once per visit

    @rx.event
    def set_approved_kind_filter(self, value: str):
        known = {p.content_kind for p in self.approved}
        self.approved_kind_filter = value if value in known else GALLERY_FILTER_ALL
        return rx.call_script(replace_url_script(self._address()))

    @rx.event
    def clear_approved_filters(self):
        self.approved_kind_filter = GALLERY_FILTER_ALL
        self.approved_state_filter = GALLERY_FILTER_ALL
        return rx.call_script(replace_url_script(self._address()))

    @rx.event
    def set_content_kind_filter(self, value: str) -> None:
        known = {p.content_kind for p in self.posts}
        self.content_kind_filter = value if value in known else GALLERY_FILTER_ALL

    @rx.event
    def set_state_filter(self, value: str) -> None:
        known = {value for value, _label in PENDING_STATE_FILTERS} | {GALLERY_FILTER_ALL}
        self.state_filter = value if value in known else GALLERY_FILTER_ALL

    @rx.event
    def set_category_filter(self, value: str) -> None:
        self.category_filter = value or GALLERY_FILTER_ALL

    @rx.event
    def clear_filters(self) -> None:
        self.state_filter = GALLERY_FILTER_ALL
        self.category_filter = GALLERY_FILTER_ALL
        self.content_kind_filter = GALLERY_FILTER_ALL

    @rx.event
    def assign(self, post_id: str):
        """«Asignar» from a card: the Planificador opens its drawer on this POST — one
        drawer, one assign flow, no copy of it here."""
        return rx.redirect(f"/planner?post={post_id}")

    @rx.event
    def assign_from_approved(self, post_id: str):
        """«Elegir día y hora» from «Aprobados»: the same drawer; Tu semana's way back
        says «‹ Aprobados» (N7)."""
        return rx.redirect(f"/planner?post={post_id}&desde={FROM_APPROVED}")

    def _query(self, key: str) -> str:
        return str(self.router.url.query_parameters.get(key, "") or "")

    @rx.event(background=True)
    async def load(self):
        """`/drafts` on_load: `?ver=`, `?estado=`, `?orden=vence`, then the read."""
        async with self:
            self.route = DRAFTS_ROUTE
            slug = self._query(GALLERY_FILTER_PARAM)
            # m-24986801: «listo» / «usado» live in «Aprobados» now — an old link follows
            moved = approved_redirect(slug)
            if moved:
                self.state_filter = GALLERY_FILTER_ALL
            else:
                # m-24842962: a `?estado=` in the address (Inicio's card) opens filtered.
                requested = gallery_filter_from_param(slug)
                if requested is not None:
                    self.state_filter = (
                        requested if requested in PENDING_CARD_STATES else GALLERY_FILTER_ALL
                    )
            order = self._query(GALLERY_ORDER_PARAM)
            self.sort_by_expiry = order.strip().lower() == GALLERY_ORDER_EXPIRY
            self._read_view()
        if moved:
            yield rx.redirect(moved, replace=True)
            return
        async for event in self._fetch():
            yield event

    @rx.event(background=True)
    async def load_approved(self):
        """`/aprobados` on_load: `?ver=`, `&tipo=`, an old `?estado=listo|usado`."""
        async with self:
            self.route = APPROVED_ROUTE
            self._read_view()
            self.approved_kind_filter = self._query(KIND_PARAM).strip() or GALLERY_FILTER_ALL
            requested = gallery_filter_from_param(self._query(GALLERY_FILTER_PARAM))
            self.approved_state_filter = (
                requested
                if requested is not None and requested in APPROVED_CARD_STATES
                else GALLERY_FILTER_ALL
            )
        async for event in self._fetch():
            yield event

    @rx.event(background=True)
    async def reload(self):
        """Re-read the grid for the screen already open (after a card's action, or
        «Reintentar»), without reading the address again."""
        async for event in self._fetch():
            yield event

    def _read_view(self) -> None:
        chosen = view_from_param(self._query(VIEW_PARAM))
        self.view = chosen or VIEW_POSTS
        self.view_chosen = bool(chosen)

    async def _fetch(self):
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
                self.error = APPROVED_LOAD_FAILED if self.route == APPROVED_ROUTE else _LOAD_FAILED
            return
        async with self:
            self.posts = list(data.posts)
            self.categories = list(data.categories)
            self.loading = False
            if self.approved_kind_filter not in {p.content_kind for p in self.approved}:
                self.approved_kind_filter = GALLERY_FILTER_ALL
        yield GalleryState.settle_view

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
        except NotEnoughCreations as exc:
            # founder 2026-10-24: approving counts the videos — none left, none approved
            text = await asyncio.to_thread(approval_refused_text, tenant_id, UUID(post_id), exc)
            async with self:
                self.busy_post_id = ""
            yield rx.toast.warning(text)
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
        elif notice.offer_open:
            # m-24842981 (finding 8): its final is being made or could not be ordered —
            # the publication's own page says when it is ready and offers to try again.
            yield getattr(rx.toast, notice.kind)(
                notice.text,
                action={
                    "label": APPROVED_OPEN_ACTION,
                    "on_click": rx.redirect(f"/drafts/{post_id}"),
                },
            )
        else:
            yield getattr(rx.toast, notice.kind)(notice.text)
        if data is None:
            yield GalleryState.reload
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now

    @rx.event(background=True)
    async def recreate_post(self, post_id: str):
        """«Crearla otra vez» on a card whose vista previa expired (founder, 2026-10-24):
        a new piece from the same request, opened at once (one vista previa per video)."""
        async with self:
            if self.busy_post_id:
                return
            self.busy_post_id = post_id
        tenant_id = await self._tenant()
        try:
            if tenant_id is None:
                raise LookupError("no tenant")
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
            if user_id is None:
                raise LookupError("no user")
            new_id = await asyncio.to_thread(recreate_draft, tenant_id, UUID(post_id), user_id)
        except NotEnoughCreations as exc:
            assert tenant_id is not None
            text = await asyncio.to_thread(recreate_refused_text, tenant_id, exc)
            async with self:
                self.busy_post_id = ""
            yield rx.toast.warning(text)
            return
        except Exception as exc:  # noqa: BLE001 — one card's failure never breaks the grid
            logger.warning("gallery recreate failed: %s", type(exc).__name__)
            async with self:
                self.busy_post_id = ""
            yield rx.toast.error(_REVIEW_FAILED)
            return
        async with self:
            self.busy_post_id = ""
        yield PendingState.refresh_now
        yield rx.redirect(f"/drafts/{new_id}")

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
        yield GalleryState.reload
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now
