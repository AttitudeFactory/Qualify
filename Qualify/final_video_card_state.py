"""State of «Tu video completo» (m-24921084, `docs/ux-video-por-planos.md` §3e and §4).

A state of its own — never a mixin of `CreativeState` — so the card can sit under any
parts list (UI-7 places it). It resolves the session's tenant and user the way
`FinalReviewState` does (`AuthState.session_tenant_id` / `_session_user_id`), reads the
backend through `final_video_card_provider` off the event loop, and keeps the card as
the pure `final_video_vm.FinalVideoCardVM` plus a few plain vars.

No poll lives here. `load(parent_id)` is the first read (the card's `on_mount`);
`refresh(parent_id)` is ONE read and returns. The parts' screen (UI-7,
`PartProgressState`) owns the only poll and calls `refresh` on every tick while
`wants_refresh` is True — the join runs while no part changes, so nothing else would
tell it the join finished.

Every refusal the backend raises reaches the owner as `refusal_text`'s words, never as
`str(exc)`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.final_video import RecreateRefused
from qualify_api.creative.fsm import InvalidTransition
from qualify_api.creative.part_final import PartFailed, PartsNotReady, StaleJoinedPreview
from qualify_api.creative.parts import (
    PART_FINAL_IN_FLIGHT_TEXT,
    PART_PUBLISHING_TEXT,
    PART_SCHEDULED_TEXT,
    PURGED_PARENT_TEXT,
    ExtendOutOfOrder,
    ExtendTooShort,
    ParentTextMissing,
    PartChangeRefused,
    PartNeedsDescription,
    PartNeedsPrevious,
    PartsOverBudget,
    PartsPlanBusy,
    PartsUnavailable,
)
from qualify_api.creative.service import (
    ApprovalBlocked,
    BrandNotReady,
    DraftExpired,
    RouteBlockedByPolicy,
    UnknownDraft,
    UnknownVariant,
)
from reflex.event import Event

from . import final_video_card_provider as provider
from .auth_state import AuthState
from .creative_vm import not_enough_creations_text, previews_short_text, videos_short_text
from .final_video_vm import JOINING, READY, REJOINING, FinalVideoCardVM
from .pending_state import PendingState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

#: UI-7's parts poll (`part_progress_state.PartProgressState.poll`), by its event NAME —
#: importing that state here would close an import cycle. The poll stops once the join
#: reaches a final state; an action here that sets work going again must restart it,
#: or nobody reads again. Restarting is safe: its token keeps one loop at a time. A test
#: pins this to `PartProgressState.get_full_name() + ".poll"`.
PART_PROGRESS_POLL = (
    "reflex___state____state.qualify___part_progress_state____part_progress_state.poll"
)


def _restart_progress() -> Event:
    """The parts poll, asked again after an action that put work in motion."""
    return Event(name=PART_PROGRESS_POLL)


APPROVE = "approve"
REJOIN = "rejoin"
RECREATE = "recreate"
CHANGE = "change"
CREATE = "create"

NO_SESSION_TEXT = "Vuelve a iniciar sesión para ver tu video."
NOT_FOUND_TEXT = "No encontramos este video. Vuelve a Por aprobar y ábrelo de nuevo."
READ_FAILED_TEXT = "No pudimos mostrar tu video completo. Inténtalo de nuevo en un momento."
NOT_READY_TEXT = "Tu video completo todavía no está listo. Espera a que terminen todas sus partes."
PART_FAILED_TEXT = "Una parte de tu video no salió. Cámbiala para poder aprobarlo."
STALE_TEXT = "Tu video cambió mientras lo veías. Míralo de nuevo antes de aprobarlo."
EXPIRED_TEXT = (
    "Una parte venció: las vistas previas duran 7 días. Créala otra vez para aprobar tu video."
)
RECREATE_REFUSED_TEXT = (
    "Esa parte ya no está vencida: puede que ya se esté creando otra vez. Revisa tus partes."
)
REJOIN_REFUSED_TEXT = (
    "Este video ya no se puede juntar otra vez. Vuelve a Por aprobar y ábrelo de nuevo."
)
PART_BUSY_TEXT = "Esta parte todavía se está creando. Espera a que termine para cambiarla."
CHOOSE_PART_TEXT = "Elige qué parte quieres cambiar."
READY_ANNOUNCE = "Tu video completo está listo para aprobar."
SCHEDULE_BUTTON_ID = "q-final-video-schedule"
FOCUS_SCHEDULE_JS = f"setTimeout(()=>document.getElementById('{SCHEDULE_BUTTON_ID}')?.focus(),0)"
#: what each action says when the backend failed for a reason the owner cannot fix
FAILED_TEXT = {
    APPROVE: "No pudimos aprobar tu video. Inténtalo de nuevo en un momento.",
    REJOIN: "No pudimos juntar tus partes otra vez. Inténtalo de nuevo en un momento.",
    RECREATE: "No pudimos crear otra vez tus partes. Inténtalo de nuevo en un momento.",
    CHANGE: "No pudimos cambiar esa parte. Inténtalo de nuevo en un momento.",
    CREATE: "No pudimos crear tus partes. Inténtalo de nuevo en un momento.",
}
PLAN_ORDER_TEXT = (
    "No pudimos crear esa parte por cómo está ordenado tu plan. Revisa el orden de tus partes."
)
PLAN_BUSY_TEXT = "Tu plan cambió mientras creábamos las partes. Inténtalo de nuevo."
BRAND_NOT_READY_TEXT = (
    "Tu marca todavía no está lista para crear. Complétala y vuelve a intentarlo."
)
#: what the screen reader hears once an action went through (the one `aria-live` region)
DONE_TEXT = {
    REJOIN: "Estamos juntando tus partes otra vez.",
    RECREATE: "Estamos creando otra vez las partes vencidas.",
    CHANGE: "Estamos creando otra versión de la parte.",
    CREATE: "Estamos creando las partes que faltaban.",
}
#: `PartChangeRefused` carries one of these, written for the owner (`parts.py`)
_PART_CHANGE_TEXTS = frozenset(
    {PURGED_PARENT_TEXT, PART_PUBLISHING_TEXT, PART_SCHEDULED_TEXT, PART_FINAL_IN_FLIGHT_TEXT}
)


def refusal_text(
    exc: BaseException, action: str, *, renews: str = "", preview_quota: int = 0
) -> str:
    """The owner's words for a refusal of `action` — what happened and what to do next.
    Typed refusals map to their own text; anything else is the action's generic
    failure. Never `str(exc)` of an unknown exception. Pure."""
    if isinstance(exc, NotEnoughCreations):
        if exc.missing:
            return not_enough_creations_text(exc.missing)
        if exc.missing_videos:
            return videos_short_text(exc.videos, exc.videos_left, exc.video_quota, renews=renews)
        if exc.missing_previews or action in (RECREATE, CHANGE, CREATE):
            return previews_short_text(
                exc.previews, exc.previews_left, preview_quota, renews=renews
            )
        return FAILED_TEXT.get(action, FAILED_TEXT[APPROVE])
    if isinstance(exc, PartChangeRefused):
        said = exc.args[0] if exc.args else ""
        return said if said in _PART_CHANGE_TEXTS else FAILED_TEXT.get(action, FAILED_TEXT[CHANGE])
    # «Crear la parte 6» (`create_parts`' refusals, `part_request.refusal_of`)
    if isinstance(exc, PartsUnavailable | ParentTextMissing | PartNeedsDescription):
        return exc.text  # written for the owner in `parts.py`
    if isinstance(exc, PartsOverBudget):
        return exc.text
    if isinstance(exc, PartNeedsPrevious):
        return (
            f"La parte {exc.index} sigue a la parte {exc.index - 1}: "
            f"crea primero la parte {exc.index - 1}."
        )
    if isinstance(exc, ExtendTooShort | ExtendOutOfOrder):
        return PLAN_ORDER_TEXT
    if isinstance(exc, PartsPlanBusy):
        return PLAN_BUSY_TEXT
    if isinstance(exc, BrandNotReady | RouteBlockedByPolicy):
        return BRAND_NOT_READY_TEXT
    if isinstance(exc, ApprovalBlocked):
        return exc.detail  # the approval guard's own Spanish for the owner
    if isinstance(exc, RecreateRefused):
        return RECREATE_REFUSED_TEXT
    if isinstance(exc, PartFailed):  # before PartsNotReady: it is one
        return PART_FAILED_TEXT
    if isinstance(exc, PartsNotReady):
        return NOT_READY_TEXT
    if isinstance(exc, StaleJoinedPreview):
        return STALE_TEXT
    if isinstance(exc, DraftExpired):
        return EXPIRED_TEXT
    if isinstance(exc, UnknownDraft | UnknownVariant):
        return NOT_FOUND_TEXT
    if isinstance(exc, InvalidTransition):
        return PART_SCHEDULED_TEXT if action == APPROVE else PART_BUSY_TEXT
    return FAILED_TEXT.get(action, READ_FAILED_TEXT)


class FinalVideoState(rx.State):
    """«Tu video completo» of one video by parts (`parent_id`)."""

    parent_id: str = ""
    loading: bool = False
    loaded: bool = False
    missing: bool = False
    #: the action on its way ("" when none): one at a time, a double tap does nothing
    busy: str = ""
    error: str = ""
    #: the card's one `aria-live` message (what just changed)
    announce: str = ""
    card: FinalVideoCardVM = FinalVideoCardVM(
        header="",
        title="",
        seconds_label="",
        badge="",
        pill_word="",
        pill_tone="neutral",
        status_text="",
        show_video=False,
        preview_text="",
        deadline_text="",
        approve_visible=False,
        approve_label="",
        approve_enabled=False,
        approve_hint="",
        quota_text="",
        change_part_visible=False,
        change_part_label="",
        rejoin_visible=False,
        rejoin_label="",
        recreate_visible=False,
        recreate_label="",
        recreate_text="",
    )
    join_state: str = ""
    video_key: str = ""
    video_url: str = ""
    poster_key: str = ""
    poster_url: str = ""
    #: «Cambiar una parte»: the parts that can change, as the select's values
    part_options: list[str] = []
    #: the same parts with their poster: `{"index", "key", "url"}` (the picker's tiles)
    part_thumbs: list[dict[str, str]] = []
    change_open: bool = False
    change_index: str = ""
    change_text: str = ""
    #: after «Aprobar» here: the «Aprobada» block, as the piece's page shows it
    approved_here: bool = False
    approved_ready: bool = False
    approved_note: str = ""
    _renews: str = ""
    _preview_quota: int = 0
    _token: int = 0

    @rx.var
    def wants_refresh(self) -> bool:
        """True while the parts are being joined: UI-7's poll calls `refresh` then."""
        return self.join_state in (JOINING, REJOINING)

    @rx.var
    def join_steps(self) -> list[dict[str, str]]:
        """The `progress_panel` stage while joining: «Juntando tus partes…» as the
        comment above the bar."""
        if self.join_state not in (JOINING, REJOINING):
            return []
        return [{"title": self.card.status_text, "status": "running"}]

    @rx.var
    def working(self) -> bool:
        return self.busy != ""

    # -- session -----------------------------------------------------------------------

    async def _identity(self) -> tuple[UUID, UUID] | None:
        async with self:
            auth = await self.get_state(AuthState)
            tenant = tenant_uuid(auth.session_tenant_id)
            user = tenant_uuid(auth._session_user_id)
        return (tenant, user) if tenant is not None and user is not None else None

    # -- reading -----------------------------------------------------------------------

    async def _read(self, parent: UUID, tenant_id: UUID) -> None:
        async with self:
            self._token += 1
            token = self._token
            self.loading = True
        try:
            read = await asyncio.to_thread(provider.read_card, tenant_id, parent)
        except Exception as exc:  # noqa: BLE001 — the card says so; the page stays up
            logger.warning("final video unreadable: %s", type(exc).__name__)
            async with self:
                if token == self._token:
                    self.loading = False
                    self.error = READ_FAILED_TEXT
            return
        async with self:
            if token != self._token or self.parent_id != str(parent):
                # an older read, or the card moved to another video meanwhile: never
                # leave the card «loading» (a newer read, if any, sets it again)
                if token == self._token:
                    self.loading = False
                return
            self.loading = False
            self.loaded = True
            if read is None:
                self.missing = True
                self.join_state = ""
                return
            self.missing = False
            if self.error in (READ_FAILED_TEXT, NO_SESSION_TEXT):  # stale read errors only
                self.error = ""
            self.card = read.vm
            was = self.join_state
            self.join_state = read.state
            if read.state == READY and was not in ("", READY):
                # the join just finished: the screen reader hears it once, not each read
                self.announce = READY_ANNOUNCE
            self.video_key, self.video_url = read.video_key, read.video_url
            self.poster_key, self.poster_url = read.poster_key, read.poster_url
            self.part_options = [str(i) for i in read.parts]
            self.part_thumbs = [dict(t) for t in read.thumbs]
            if self.change_index not in self.part_options:
                self.change_index = ""
            self._renews, self._preview_quota = read.renews, read.preview_quota

    @rx.event(background=True)
    async def load(self, parent_id: str) -> None:
        """The first read (the card's `on_mount`). Another video resets the card."""
        parent = tenant_uuid(parent_id) if isinstance(parent_id, str) else None
        if parent is None:
            return
        async with self:
            if self.parent_id != str(parent):
                self._reset(str(parent))
        ids = await self._identity()
        if ids is None:
            async with self:
                self.error = NO_SESSION_TEXT
            return
        await self._read(parent, ids[0])

    @rx.event(background=True)
    async def refresh(self, parent_id: str) -> None:
        """ONE read of the same video — no loop (UI-7 owns the poll). Skipped while an
        action or another read is on its way, or for another video than the card's."""
        parent = tenant_uuid(parent_id) if isinstance(parent_id, str) else None
        async with self:
            skip = parent is None or self.parent_id != str(parent) or self.busy or self.loading
        if skip:
            return
        ids = await self._identity()
        if ids is not None and parent is not None:
            await self._read(parent, ids[0])

    def _reset(self, parent_id: str) -> None:
        self.parent_id = parent_id
        self._token += 1  # a read of the previous video still in flight lands nowhere
        self.loaded = self.missing = self.loading = False
        self.busy = self.error = self.announce = self.join_state = ""
        self.video_key = self.video_url = self.poster_key = self.poster_url = ""
        self.part_options = []
        self.part_thumbs = []
        self.change_open = False
        self.change_index = self.change_text = ""
        self.approved_here = self.approved_ready = False
        self.approved_note = ""

    # -- actions -----------------------------------------------------------------------

    async def _begin(self, action: str) -> tuple[UUID, UUID, UUID] | None:
        """(tenant, user, parent) and the action claimed — None when another one is on
        its way, the session is gone or the card has no video."""
        async with self:
            if self.busy:
                return None
            parent = tenant_uuid(self.parent_id)
            if parent is None:
                return None
            self.busy = action
            self.error = ""
            self.announce = ""
        ids = await self._identity()
        if ids is None:
            async with self:
                self.busy = ""
                self.error = NO_SESSION_TEXT
            return None
        return ids[0], ids[1], parent

    async def _refused(
        self, exc: BaseException, action: str, tenant_id: UUID, parent: UUID
    ) -> None:
        async with self:
            text = refusal_text(exc, action, renews=self._renews, preview_quota=self._preview_quota)
        if not isinstance(exc, NotEnoughCreations | PartChangeRefused | RecreateRefused):
            logger.warning("final video %s refused: %s", action, type(exc).__name__)
        await self._read(parent, tenant_id)  # what is true now (nothing was written)
        async with self:
            self.busy = ""
            self.error = text
            self.announce = text

    @rx.event(background=True)
    async def approve(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Aprobar»: the whole video once, through `ContentService.approve_parts` —
        every part's seconds charged together, all or nothing. Then as on the piece's
        own page: the toast (`approval_notice`), the menu's count, and the «Aprobada»
        block with «Elegir día y hora»."""
        async with self:
            if not self.card.approve_enabled:
                return
        claimed = await self._begin(APPROVE)
        if claimed is None:
            return
        tenant_id, user_id, parent = claimed
        try:
            done = await asyncio.to_thread(provider.approve, tenant_id, parent, user_id)
        except Exception as exc:  # noqa: BLE001 — every refusal gets the owner's words
            await self._refused(exc, APPROVE, tenant_id, parent)
            return
        await self._read(parent, tenant_id)
        async with self:
            self.busy = ""
            self.approved_here = True
            self.approved_ready = done.ready
            self.approved_note = done.note
            self.announce = done.text
        yield getattr(rx.toast, done.kind, rx.toast.success)(done.text)
        yield PendingState.refresh_now  # the menu's «Por aprobar» count drops now
        # the keyboard lands on the next step, «Elegir día y hora», once it is drawn
        yield rx.call_script(FOCUS_SCHEDULE_JS)

    @rx.event
    def go_schedule(self) -> rx.event.EventSpec | None:
        """«Elegir día y hora»: Tu semana opens its assign drawer on this publication —
        the same door as the piece's page (`CreativeState.go_schedule`)."""
        if not self.parent_id:
            return None
        return rx.redirect(f"/planner?post={self.parent_id}")

    @rx.event(background=True)
    async def rejoin(self) -> AsyncIterator[Event]:
        """«Juntar otra vez»: ours, nothing charged."""
        claimed = await self._begin(REJOIN)
        if claimed is None:
            return
        tenant_id, _, parent = claimed
        try:
            ok = await asyncio.to_thread(provider.rejoin, tenant_id, parent)
        except Exception as exc:  # noqa: BLE001
            await self._refused(exc, REJOIN, tenant_id, parent)
            return
        await self._read(parent, tenant_id)
        async with self:
            self.busy = ""
            self.error = "" if ok else REJOIN_REFUSED_TEXT
            self.announce = DONE_TEXT[REJOIN] if ok else REJOIN_REFUSED_TEXT
        if ok:
            yield _restart_progress()

    @rx.event(background=True)
    async def recreate(self) -> AsyncIterator[Event]:
        """«Crear la parte N otra vez»: only the expired parts, all or nothing."""
        claimed = await self._begin(RECREATE)
        if claimed is None:
            return
        tenant_id, user_id, parent = claimed
        try:
            await asyncio.to_thread(provider.recreate_expired, tenant_id, parent, user_id)
        except Exception as exc:  # noqa: BLE001
            await self._refused(exc, RECREATE, tenant_id, parent)
            return
        await self._read(parent, tenant_id)
        async with self:
            self.busy = ""
            self.announce = DONE_TEXT[RECREATE]
        yield _restart_progress()

    @rx.event(background=True)
    async def create_missing(self) -> AsyncIterator[Event]:
        """«Crear la parte 6» / «Crear las que faltan»: the parts of the plan never
        created, all or nothing (`PartsRequests.request_parts`)."""
        async with self:
            if not self.card.create_visible:
                return
        claimed = await self._begin(CREATE)
        if claimed is None:
            return
        tenant_id, user_id, parent = claimed
        try:
            await asyncio.to_thread(provider.create_missing, tenant_id, parent, user_id)
        except Exception as exc:  # noqa: BLE001
            await self._refused(exc, CREATE, tenant_id, parent)
            return
        await self._read(parent, tenant_id)
        async with self:
            self.busy = ""
            self.announce = DONE_TEXT[CREATE]
        yield _restart_progress()

    @rx.event
    def toggle_change(self) -> None:
        """«Cambiar una parte» opens (or closes) the chooser under the buttons."""
        self.change_open = not self.change_open
        if self.change_open and not self.change_index and len(self.part_options) == 1:
            self.change_index = self.part_options[0]

    @rx.event
    def set_change_index(self, value: str) -> None:
        self.change_index = value if value in self.part_options else ""

    @rx.event
    def set_change_text(self, value: str) -> None:
        self.change_text = value

    @rx.event(background=True)
    async def change_part(self) -> AsyncIterator[Event]:
        """Another version of the chosen part (`PartsService.regenerate_part`): its new
        description when one was written. 1 vista previa; the others are untouched."""
        async with self:
            index = int(self.change_index) if self.change_index.isdigit() else 0
            if index <= 0:
                self.error = CHOOSE_PART_TEXT
                return
            text = self.change_text
        claimed = await self._begin(CHANGE)
        if claimed is None:
            return
        tenant_id, user_id, parent = claimed
        try:
            await asyncio.to_thread(provider.change_part, tenant_id, parent, index, text, user_id)
        except Exception as exc:  # noqa: BLE001
            await self._refused(exc, CHANGE, tenant_id, parent)
            return
        await self._read(parent, tenant_id)
        async with self:
            self.busy = ""
            self.change_open = False
            self.change_text = ""
            self.announce = DONE_TEXT[CHANGE]
        yield _restart_progress()


__all__ = ["FinalVideoState", "refusal_text"]
