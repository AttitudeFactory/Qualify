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
from dataclasses import dataclass, field
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
from . import part_review_provider as review_provider
from . import part_review_vm as review_vm
from .auth_state import AuthState
from .creative_vm import not_enough_creations_text, previews_short_text, videos_short_text
from .final_video_vm import APPROVED as JOIN_APPROVED
from .final_video_vm import JOINING, READY, REJOINING, FinalVideoCardVM
from .final_video_vm import PURGED as JOIN_PURGED
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


#: m-25016656: the piece page's silent re-read of its draft (`CreativeState.view_version`
#: with no version: the current one, no skeleton — `load_draft` would swap the whole page
#: for its skeleton and remount this card). By NAME for the same reason as the poll; a
#: test pins it to `CreativeState.get_full_name() + ".view_version"`.
PIECE_PAGE_REREAD = (
    "reflex___state____state.qualify___creative_state____creative_state.view_version"
)


def _reread_piece_page() -> Event:
    """`/drafts/<id>` reads its draft again, so the status at the top of the page says
    «Aprobado» as the card does. Only sent from that page (see `_on_piece_page`)."""
    return Event(name=PIECE_PAGE_REREAD, payload={"requested_version_id": ""})


APPROVE = "approve"
REJOIN = "rejoin"
RECREATE = "recreate"
CHANGE = "change"
CREATE = "create"
#: m-24921083: «Usar esta versión» of a part
USE = "use"

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
#: m-25016656: the parts' status line (`part_progress_state.STATUS_ID`, by value — that
#: module imports this one; a test pins them equal) and each part's «Cambiar esta»
#: (`final_video_card.CHOOSE_ID_PREFIX` + its plan index).
PARTS_STATUS_ID = "q-parts-status"
CHOOSE_ID_PREFIX = "q-part-choose-"
#: m-24921083: the chosen part's panel title («Parte 2»): the keyboard lands there when
#: a part is chosen, so its place is not lost below the tiles
CHANGE_TITLE_ID = "q-final-video-change-title"
#: the panel's fields and its [Intentar de nuevo] (the view uses the same ids): where
#: the keyboard goes when «Crear otra versión» has to wait (UX review of UI-8)
CHANGE_DESCRIPTION_ID = "q-final-video-change-description"
CHANGE_PHOTOS_ID = "q-final-video-change-photos"
REVIEW_RETRY_ID = "q-final-video-review-retry"
_WAIT_TARGETS = {
    review_vm.DESCRIPTION_REQUIRED: CHANGE_DESCRIPTION_ID,
    review_vm.PHOTO_REQUIRED: CHANGE_PHOTOS_ID,
}
#: «Crear otra versión» tapped on a panel never read (internal: nothing is said)
REVIEW_NOT_READ = "not-read"
#: Deivid, 2026-11-13: while the parts are being joined the card hides everything but
#: this wait (`progress_panel`, the stage line above the bar)
JOINING_ONLY_TEXT = "Estamos juntando tus partes. En un momento lo ves aquí."
USE_REFUSED_TEXT = "Ya no se puede usar esa versión. Mira cómo está tu parte ahora."


def _focus_script(element_id: str, *, inner: bool = False) -> rx.event.EventSpec:
    """The keyboard to `element_id` once it is drawn (the button tapped just went) — or,
    `inner`, to the first button inside it (a group of photos)."""
    find = (
        f"document.querySelector('#{element_id} button')"
        if inner
        else f"document.getElementById('{element_id}')"
    )
    return rx.call_script(f"setTimeout(()=>{find}?.focus(),0)")


#: what each action says when the backend failed for a reason the owner cannot fix
FAILED_TEXT = {
    APPROVE: "No pudimos aprobar tu video. Inténtalo de nuevo en un momento.",
    REJOIN: "No pudimos juntar tus partes otra vez. Inténtalo de nuevo en un momento.",
    RECREATE: "No pudimos crear otra vez tus partes. Inténtalo de nuevo en un momento.",
    CHANGE: "No pudimos cambiar esa parte. Inténtalo de nuevo en un momento.",
    CREATE: "No pudimos crear tus partes. Inténtalo de nuevo en un momento.",
    USE: "No pudimos usar esa versión. Inténtalo de nuevo en un momento.",
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
    if isinstance(exc, review_provider.NotReviewable):
        return exc.text or USE_REFUSED_TEXT  # the backend's own words for the owner
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


@dataclass(frozen=True)
class PartVersionView:
    """One version of the chosen part (m-24921083): «Versión 1 de 2» and the description
    it was made with (its vista previa is the tile's: the panel plays none)."""

    version_id: str = ""
    ordinal: int = 0
    current: bool = False
    description: str = ""
    photo_keys: list[str] = field(default_factory=list)
    expired: bool = False
    label: str = ""
    made_with: str = ""
    use_reason: str = ""
    #: its own vista previa (signed) and the names of its ▶ — the part's tile plays it
    #: while the owner looks at this version
    video_url: str = ""
    poster_url: str = ""
    play_label: str = ""
    pause_label: str = ""


@dataclass(frozen=True)
class PhotoChoiceView:
    """A photo of the product the chosen part may use («Fotos de tu producto»)."""

    key: str
    url: str = ""
    label: str = ""


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
    # -- m-24921083: the chosen part's panel («Revisar y rehacer una parte») ----------
    review_loading: bool = False
    #: the panel was read: its fields are the part's own (the description and photos
    #: «Crear otra versión» sends are the owner's whole edit, never a note on top)
    review_ready: bool = False
    review_error: str = ""
    review_mode_label: str = ""
    review_mode_help: str = ""
    review_versions: list[PartVersionView] = []
    #: the version on screen (its position in `review_versions`)
    review_at: int = 0
    review_photos: list[PhotoChoiceView] = []
    review_selected: list[str] = []
    review_use_text: str = ""
    #: Deivid, 2026-11-13: the reel the video is inspired by — the «Video de
    #: inspiración» card on its page, above «Campaña» ("" = no card) — and its account
    #: («@thegoldenbalance», "" when unknown). Read once per video.
    inspiration_url: str = ""
    inspiration_account: str = ""
    #: the month has no vista previa left: «Crear otra versión» waits, saying why
    review_out: bool = False
    _review_token: int = 0
    _review_description: str = ""
    _review_photos: list[str] = []
    #: every photo of the part's active brief, in order (product, place, style…)
    _review_all_photos: list[str] = []
    #: the part's own draft, for [Intentar de nuevo]
    _review_draft: str = ""
    _renews: str = ""
    _preview_quota: int = 0
    _token: int = 0

    @rx.var
    def review_version(self) -> PartVersionView:
        """The version of the chosen part on screen (an empty one before the read)."""
        if 0 <= self.review_at < len(self.review_versions):
            return self.review_versions[self.review_at]
        return PartVersionView()

    @rx.var
    def review_peek(self) -> PartVersionView:
        """Deivid, 2026-11-13: an earlier version the owner is looking at («Ver la
        anterior») — the chosen part's TILE plays it, marked «Versión 1 de 2», until he
        goes back to the current one, lets the part go or uses it. Empty otherwise (the
        tile plays the part's current vista previa). Read straight off the fields: no
        dynamic `getattr`."""
        if not self.change_open or not (0 <= self.review_at < len(self.review_versions)):
            return PartVersionView()
        version = self.review_versions[self.review_at]
        return PartVersionView() if version.current else version

    @rx.var
    def joining_steps(self) -> list[dict[str, str]]:
        """While the parts are being joined the card is ONLY this wait (Deivid,
        2026-11-13): «Estamos juntando tus partes…» as the comment above the bar."""
        if self.join_state not in (JOINING, REJOINING):
            return []
        return [{"title": JOINING_ONLY_TEXT, "status": "running"}]

    @rx.var
    def review_has_previous(self) -> bool:
        return self.review_at > 0 and len(self.review_versions) > 1

    @rx.var
    def review_has_next(self) -> bool:
        return self.review_at < len(self.review_versions) - 1

    @rx.var
    def review_blocked(self) -> str:
        """Why «Crear otra versión» waits ("" when it can go): the panel could not be read
        (its fields are hidden: never an empty box sent as the description), the month
        has no vista previa, the description is empty or no photo is chosen. While it is
        being read the button is simply off."""
        if not self.review_ready:
            return self.review_error
        if self.review_out:
            return self.review_use_text
        if not self.change_text.strip():
            return review_vm.DESCRIPTION_REQUIRED
        if self.review_photos and not self.review_selected:
            return review_vm.PHOTO_REQUIRED
        return ""

    @rx.var
    def closed(self) -> bool:
        """The whole video is approved (or its files are gone): its parts are only to
        watch. A part kept 7 days still reads «Venció» in the backend (`derive_state`)
        — never a decision to ask for here (m-25016656)."""
        return self.join_state in (JOIN_APPROVED, JOIN_PURGED)

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

    @rx.var
    def change_number(self) -> str:
        """The number the owner reads for the chosen part («Parte 2: ¿qué le
        cambiamos?»), off `part_thumbs` (no gap after a removed part)."""
        for thumb in self.part_thumbs:
            if thumb.get("index") == self.change_index:
                return str(thumb.get("number") or self.change_index)
        return self.change_index

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
            if self.change_index not in self.part_options or read.state in (JOINING, REJOINING):
                # the chosen part can no longer change — or the parts are being joined
                # (Deivid, 2026-11-13: the card is only the wait then): its words go
                self._clear_change()
            self._renews, self._preview_quota = read.renews, read.preview_quota

    @rx.event(background=True)
    async def load(self, parent_id: str) -> None:
        """The first read (the card's `on_mount`). Another video resets the card. Then,
        once per video, the reel it is inspired by (a courtesy: never fails the card)."""
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
        try:
            url, account = await asyncio.to_thread(review_provider.inspiration, ids[0], parent)
        except Exception as exc:  # noqa: BLE001 — a card, not worth an error
            logger.warning("inspiration reel unreadable: %s", type(exc).__name__)
            url, account = "", ""
        async with self:
            if self.parent_id == str(parent):
                self.inspiration_url = url
                self.inspiration_account = account

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

    def _on_piece_page(self) -> bool:
        """Whether the card sits on this video's own page (`/drafts/[draft_id]`), not on
        the generator's result (no route id there): the dynamic route arg, read as
        `CreativeState._route_draft_id` reads it."""
        raw = getattr(self, "draft_id", "")
        route = tenant_uuid(raw) if isinstance(raw, str) and raw else None
        return route is not None and str(route) == self.parent_id

    def _reset(self, parent_id: str) -> None:
        self.parent_id = parent_id
        self._token += 1  # a read of the previous video still in flight lands nowhere
        self.loaded = self.missing = self.loading = False
        self.busy = self.error = self.announce = self.join_state = ""
        self.video_key = self.video_url = self.poster_key = self.poster_url = ""
        self.part_options = []
        self.part_thumbs = []
        self.inspiration_url = self.inspiration_account = ""
        self._clear_change()
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
        expected = (
            NotEnoughCreations | PartChangeRefused | RecreateRefused | review_provider.NotReviewable
        )
        if not isinstance(exc, expected):
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
        async with self:
            on_piece_page = self._on_piece_page()
        if on_piece_page:
            # m-25016656: the page's own status (top right) stops saying «Listo para
            # revisar»; the generator has no route draft, so nothing to re-read there
            yield _reread_piece_page()

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
    def choose_part(self, value: str, draft_id: str = "") -> list[rx.event.EventSpec]:
        """«Cambiar esta» on a part's tile (m-25016656): that part is chosen and its panel
        opens under «Tus partes» — m-24921083: read once (`load_review`), the keyboard on
        its title. Tapping the chosen one («✓ Elegida») lets it go, as «Cancelar» does.
        A part that cannot change is never chosen. `draft_id`: the part's own draft (what
        another version uses of the month is read from it)."""
        if self.change_open and value == self.change_index:
            self._clear_change()
            return []
        if value not in self.part_options:
            return []
        if value != self.change_index:
            self._clear_review()  # the panel was the other part's
            self.change_text = ""
        self.change_index = value
        self.change_open = True
        self.error = "" if self.error == CHOOSE_PART_TEXT else self.error
        self.review_loading = True
        self._review_token += 1
        self._review_draft = draft_id if isinstance(draft_id, str) else ""
        return [
            FinalVideoState.load_review(value, self._review_draft),
            _focus_script(CHANGE_TITLE_ID),
        ]

    @rx.event
    def retry_review(self) -> list[rx.event.EventSpec]:
        """[Intentar de nuevo] after «No pudimos abrir esta parte.»: read the panel once
        more (nothing else changes)."""
        if not self.change_open or not self.change_index or self.review_loading:
            return []
        self.review_error = ""
        self.review_loading = True
        self._review_token += 1
        return [FinalVideoState.load_review(self.change_index, self._review_draft)]

    @rx.event
    def cancel_change(self) -> rx.event.EventSpec | None:
        """«Cancelar»: nothing chosen, the words cleared — and the keyboard back on that
        part's «Cambiar esta» («Cancelar» itself just went)."""
        index = self.change_index
        self._clear_change()
        return _focus_script(CHOOSE_ID_PREFIX + index) if index else None

    def _clear_review(self) -> None:
        self._review_token += 1  # a read still on its way lands nowhere
        self.review_loading = self.review_ready = self.review_out = False
        self.review_error = self.review_mode_label = self.review_mode_help = ""
        self.review_versions = []
        self.review_at = 0
        self.review_photos = []
        self.review_selected = []
        self.review_use_text = ""
        self._review_description = ""
        self._review_photos = []
        self._review_all_photos = []

    def _clear_change(self) -> None:
        self._review_draft = ""
        self.change_open = False
        self.change_index = ""
        self.change_text = ""
        self._clear_review()

    @rx.event
    def set_change_index(self, value: str) -> None:
        self.change_index = value if value in self.part_options else ""

    @rx.event
    def set_change_text(self, value: str) -> None:
        self.change_text = value

    # -- m-24921083: the chosen part's panel -------------------------------------------

    @rx.event(background=True)
    async def load_review(self, index: str, draft_id: str = "") -> None:
        """ONE read of the chosen part's panel: its versions, how it is made, what it
        shows, its photos, its original and what another version uses. The fields are
        filled with what the part has now. A read of a part no longer chosen lands
        nowhere."""
        async with self:
            token = self._review_token
            parent = tenant_uuid(self.parent_id)
            number = int(self.change_number) if self.change_number.isdigit() else 0
        part = int(index) if isinstance(index, str) and index.isdigit() else 0
        if parent is None or part <= 0:
            return
        ids = await self._identity()
        if ids is None:
            async with self:
                if token == self._review_token:
                    self.review_loading = False
                    self.review_error = NO_SESSION_TEXT
            return
        draft = tenant_uuid(draft_id) if isinstance(draft_id, str) and draft_id else None
        try:
            review = await asyncio.to_thread(
                review_provider.read_review, ids[0], parent, part, draft
            )
            view = review_vm.review_view(review, number or part)
        except Exception as exc:  # noqa: BLE001 — the panel says so; the card stays up
            logger.warning("part review unreadable: %s", type(exc).__name__)
            async with self:
                if token == self._review_token:
                    self.review_loading = False
                    self.review_error = review_vm.REVIEW_FAILED_TEXT
            return
        async with self:
            if token != self._review_token or self.change_index != str(part):
                return
            self.review_loading = False
            self.review_ready = True
            self.review_error = ""
            self.review_mode_label = view.mode_label
            self.review_mode_help = view.mode_help
            self.review_versions = [PartVersionView(**v) for v in view.versions]
            self.review_at = view.at
            self.review_photos = [PhotoChoiceView(**p) for p in view.photos]
            self.review_selected = list(view.selected)
            self._review_description = view.description
            self._review_photos = list(view.selected)
            self._review_all_photos = list(view.all_photo_keys)
            self.change_text = view.description
            self.review_use_text = view.use_text
            self.review_out = view.out_of_previews

    @rx.event
    def show_version(self, step: int) -> None:
        """«Ver la anterior» (-1) / «Ver la siguiente» (+1). The fields are filled with
        that version's own description and photos (another version made from there starts
        from them); back on the current one, with what the part has now."""
        try:
            at = self.review_at + int(step)
        except (TypeError, ValueError):
            return
        if not 0 <= at < len(self.review_versions):
            return
        self.review_at = at
        version = self.review_versions[at]
        if version.current:
            self.change_text = self._review_description
            self.review_selected = list(self._review_photos)
        else:
            self.change_text = version.description
            self.review_selected = list(version.photo_keys)

    @rx.event
    def toggle_photo(self, key: str) -> None:
        """A photo of «Fotos de tu producto» on or off (only the part's choosable ones)."""
        if not any(photo.key == key for photo in self.review_photos):
            return
        if key in self.review_selected:
            self.review_selected = [k for k in self.review_selected if k != key]
        else:
            order = [p.key for p in self.review_photos]
            chosen = {*self.review_selected, key}
            self.review_selected = [k for k in order if k in chosen]

    @rx.event(background=True)
    async def use_version(self) -> AsyncIterator[Event | rx.event.EventSpec]:
        """«Usar esta versión»: the earlier version on screen becomes the part's again
        and the whole video is joined once more — no vista previa used. Never for the
        current one or an expired one."""
        async with self:
            index = int(self.change_index) if self.change_index.isdigit() else 0
            version = self.review_version
            number = self.change_number
            usable = (
                index > 0 and version.version_id != "" and not version.current
            ) and not version.expired
        if not usable:
            return
        version_id = tenant_uuid(version.version_id)
        if version_id is None:
            return
        claimed = await self._begin(USE)
        if claimed is None:
            return
        tenant_id, user_id, parent = claimed
        try:
            await asyncio.to_thread(
                review_provider.use_version, tenant_id, parent, index, version_id, user_id
            )
        except Exception as exc:  # noqa: BLE001
            await self._refused(exc, USE, tenant_id, parent)
            return
        await self._read(parent, tenant_id)
        async with self:
            self.busy = ""
            self._clear_change()
            self.announce = review_vm.USED_VERSION_TEXT.format(v=version.ordinal, n=number)
        yield _focus_script(PARTS_STATUS_ID)
        yield _restart_progress()

    @rx.event(background=True)
    async def change_part(self) -> AsyncIterator[Event]:
        """Another version of the chosen part (`PartsService.regenerate_part`) with what
        the owner left in its panel: the WHOLE description (filled in with the part's
        own, never a note that replaces it) and the chosen photos. 1 vista previa; the
        others are untouched. Waits while the panel says why it cannot go."""
        async with self:
            index = int(self.change_index) if self.change_index.isdigit() else 0
            if index <= 0:
                self.error = CHOOSE_PART_TEXT
                return
            if self.review_loading:
                return
            text = self.change_text
            reason = self.review_blocked or ("" if self.review_ready else REVIEW_NOT_READ)
            if reason:
                # UX review: said where the owner is — the live region, and the keyboard
                # on what is missing — never in the card's error far above at 375 px
                self.announce = reason if reason != REVIEW_NOT_READ else ""
                target = _WAIT_TARGETS.get(reason, "")
                if not self.review_ready:
                    target = REVIEW_RETRY_ID
                if target:
                    yield _focus_script(target, inner=target == CHANGE_PHOTOS_ID)
                return
            # the photos only when the owner touched them, with the part's other photos
            photos = review_vm.photos_to_send(
                self.review_selected, self._review_photos, self._review_all_photos
            )
        claimed = await self._begin(CHANGE)
        if claimed is None:
            return
        tenant_id, user_id, parent = claimed
        try:
            await asyncio.to_thread(
                provider.change_part, tenant_id, parent, index, text, user_id, photos
            )
        except Exception as exc:  # noqa: BLE001
            await self._refused(exc, CHANGE, tenant_id, parent)
            return
        await self._read(parent, tenant_id)
        async with self:
            self.busy = ""
            self._clear_change()
            self.announce = DONE_TEXT[CHANGE]
        # «Crear otra versión» just went: the keyboard waits on the parts' status line
        yield _focus_script(PARTS_STATUS_ID)
        yield _restart_progress()


__all__ = ["FinalVideoState", "refusal_text"]
