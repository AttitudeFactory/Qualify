"""Reflex state for «Crear» with what the owner chose in Galería (CM-7, m-24955928).

`/create?medios=…` (CM-5's «Crear publicación con estas») shows its own short screen
instead of the generator's product step (`content_generator.generator_page` switches on
`active`, which reads the address itself, so the generator never flashes first). What it
shows is read through CM-6 (`GalleryPieces.selection`, under RLS): the usable media in
order, how many were left out, whether a business video has sound. «Crear publicación»
makes the piece through `GalleryPieces.create` with a request key that lives as long as
this choice — a second tap (or a retry) is the same piece — and opens it in «Por
aprobar». Session-only state, reset on logout (`auth_state.business_state_classes`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import reflex as rx
from pydantic import ValidationError
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.gallery_piece import MEDIA_QUERY_PARAM
from qualify_api.creative.service import BrandNotReady, RouteBlockedByPolicy

from .auth_state import AuthState
from .create_gallery_provider import (
    GalleryChoice,
    NotEnoughMedia,
    create_gallery_piece,
    gallery_choice,
)
from .create_gallery_vm import (
    DROPPED_TEXT,
    NOT_ENOUGH_MEDIA_TEXT,
    ChosenVM,
    change_href,
    sound_line,
)
from .creative_provider import acting_user_id, default_brand_id
from .creative_vm import not_enough_creations_text
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Completa tu marca (colores, logo y forma de hablar) para que todo salga con tu estilo."
_FAILED = "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."
_CREATING_TOAST = "Estamos creando tu publicación. La verás aquí, en Por aprobar."
_TOAST_MS = 6000


class CreateGalleryState(rx.State):
    loading: bool = False
    loaded: bool = False
    tiles: list[ChosenVM] = []
    kind: str = ""
    dropped: int = 0
    offers_sound: bool = False
    #: D6: «Usar el sonido de tus videos» starts OFF.
    use_audio: bool = False
    topic: str = ""
    creating: bool = False
    error: str = ""
    #: The `medios` value this screen read (the one «Crear» sends again: CM-6 re-reads it).
    _medios: str = ""
    #: One per choice: «Crear» twice (or a retry) makes the same piece.
    _request_key: str = ""

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def medios(self) -> str:
        try:
            raw = self.router.url.query_parameters.get(MEDIA_QUERY_PARAM, "")
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            raw = ""
        return ",".join(raw) if isinstance(raw, list) else str(raw or "")

    @rx.var
    def active(self) -> bool:
        """/create came from Galería's choice: this screen, not the generator."""
        return self.medios != ""

    @rx.var
    def dropped_text(self) -> str:
        return DROPPED_TEXT if self.dropped else ""

    @rx.var
    def sound_text(self) -> str:
        return sound_line(offered=self.offers_sound, on=self.use_audio)

    @rx.var
    def has_media(self) -> bool:
        return len(self.tiles) > 0

    @rx.var
    def change_link(self) -> str:
        return change_href(self.medios)

    # -- session --------------------------------------------------------------------------

    async def _ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            async with self:
                self.error = _NO_SESSION
            return None
        brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
        if brand_id is None:
            async with self:
                self.error = _NO_BRAND
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        return tenant_id, brand_id, user_id

    def _apply(self, choice: GalleryChoice, medios: str) -> None:
        self.tiles = list(choice.tiles)
        self.kind = choice.kind
        self.dropped = choice.dropped
        self.offers_sound = choice.offers_sound
        if not choice.offers_sound:
            self.use_audio = False
        if medios != self._medios:
            # a new choice: a new piece, the switch back OFF (D6)
            self._medios = medios
            self._request_key = str(uuid4())
            self.use_audio = False
            self.topic = ""

    # -- load -------------------------------------------------------------------------------

    @rx.event(background=True)
    async def load(self) -> None:
        """/create's on_load: with `?medios=`, read the choice (under RLS)."""
        async with self:
            medios = self.medios
            if not medios:
                self.loaded = False
                return
            self.loading = True
            self.error = ""
        ids = await self._ids()
        if ids is None:
            async with self:
                self.loading = False
                self.loaded = True
            return
        tenant_id, brand_id, _ = ids
        try:
            choice = await asyncio.to_thread(gallery_choice, tenant_id, brand_id, medios)
        except Exception as exc:  # noqa: BLE001 — never a skeleton forever
            logger.error("create gallery read failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.loaded = True
                self.error = _FAILED
            return
        async with self:
            self._apply(choice, medios)
            self.loading = False
            self.loaded = True

    @rx.event
    def set_use_audio(self, value: bool) -> None:
        self.use_audio = bool(value) and self.offers_sound

    @rx.event
    def set_topic(self, value: str) -> None:
        self.topic = str(value)[:280]

    @rx.event
    def change(self) -> rx.event.EventSpec:
        """«Cambiar»: back to Galería's choice with the same media chosen."""
        return rx.redirect(self.change_link)

    # -- create -----------------------------------------------------------------------------

    @rx.event(background=True)
    async def create(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Crear publicación»: one piece (one creation of the month, D5) in «Por
        aprobar»; the draft opens there."""
        async with self:
            if self.creating or not self.tiles:
                return
            self.creating = True
            self.error = ""
            medios = self._medios
            topic = self.topic
            use_audio = self.use_audio and self.offers_sound
            request_key = UUID(self._request_key) if self._request_key else uuid4()
        ids = await self._ids()
        if ids is None or ids[2] is None:
            async with self:
                self.creating = False
                self.error = self.error or _NO_SESSION
            return
        tenant_id, brand_id, user_id = ids
        try:
            draft_id, _dropped = await asyncio.to_thread(
                lambda: create_gallery_piece(
                    tenant_id,
                    brand_id,
                    user_id,
                    medios=medios,
                    topic=topic,
                    use_audio=use_audio,
                    request_key=request_key,
                )
            )
        except NotEnoughMedia:
            failure = NOT_ENOUGH_MEDIA_TEXT
        except NotEnoughCreations as exc:
            failure = not_enough_creations_text(exc.missing or 1)
        except BrandNotReady:
            failure = _NO_BRAND
        except (RouteBlockedByPolicy, ValidationError, ValueError) as exc:
            logger.warning("create gallery refused: %s", type(exc).__name__)
            failure = _FAILED
        except Exception as exc:  # noqa: BLE001 — never stuck creating
            logger.error("create gallery failed: %s", type(exc).__name__)
            failure = _FAILED
        else:
            failure = ""
        async with self:
            self.creating = False
            self.error = failure
            if not failure:
                # made: a later, deliberate «Crear» with the same media is a new piece
                self._request_key = str(uuid4())
        if failure:
            return
        yield rx.toast.success(_CREATING_TOAST, duration=_TOAST_MS)
        yield rx.redirect(f"/drafts/{draft_id}")
