"""Reflex state for «Tu Galería», a tab of the generator's media drawer (m-24985141).

The drawer («Tus productos · Tu Galería · Subir · Publicaciones · Inspiración», opened by
«Elegir fotos, videos o audios» and by each slot's «Elegir …») shows CM-5's tiles here («De
tu negocio», «De tus productos»), read the first time the tab shows. A tap chooses or
unchooses within the slot's room (`CreativeState.gallery_room`: a Clip's 9 photos and 3
videos, counting its grid; a slot of one file: the new tap replaces the earlier one).
«Agregar» — the drawer's one button — resolves the tokens again on the server under RLS
(`gen_gallery_pick_provider`), copies a business medium into the owner's uploads ONCE per
session (`_copied`), puts each one in the slot (`CreativeState.add_gallery_picks`) and closes
the drawer; with nothing chosen here it only closes it. Session-only state, reset on logout
(`auth_state.business_state_classes`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .catalog_choose_vm import ChoiceVM, ProductChoicesVM, spoken_label, with_order
from .creative_provider import default_brand_id
from .creative_state import MEDIA_DRAWER_CLIP, CreativeState
from .gen_gallery_pick_provider import gallery_choices, resolve_picks
from .gen_gallery_pick_vm import (
    FAILED,
    LOAD_FAILED,
    add_label,
    added_note,
    pick_limit,
    to_add_text,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."


class GenGalleryPickState(rx.State):
    loading: bool = False
    loaded: bool = False
    adding: bool = False
    #: The last read or add failed, or a tap did not fit: said beside «Agregar».
    error: str = ""
    #: The chosen tokens (`n:<uuid>` / `p:<uuid>`), in the order tapped.
    chosen: list[str] = []
    #: The slot the chosen tokens are for (a new slot starts a new choice).
    _target: str = ""
    _business: list[ChoiceVM] = []
    _products: list[ProductChoicesVM] = []
    #: token → "image" | "video", for the limits.
    _media_of: dict[str, str] = {}
    #: token → the key an earlier «Agregar» copied a business medium to (review #4: a
    #: second «Agregar» of the same medium never copies it again).
    _copied: dict[str, str] = {}
    #: The tokens already among the slot's files (marked «Ya está»).
    held: list[str] = []

    def _marked(self, choices: list[ChoiceVM] | tuple[ChoiceVM, ...]) -> list[ChoiceVM]:
        held = set(self.held)
        out = []
        for c in with_order(list(choices), self.chosen):
            if c.token in held:
                spoken = spoken_label(c.label, c.media_type, c.order) + ", ya está"
                c = replace(c, added=True, spoken=spoken)
            out.append(c)
        return out

    @rx.var
    def business(self) -> list[ChoiceVM]:
        return self._marked(self._business)

    @rx.var
    def products(self) -> list[ProductChoicesVM]:
        return [
            ProductChoicesVM(name=g.name, choices=tuple(self._marked(g.choices)))
            for g in self._products
        ]

    def _sync_held(self, creative: CreativeState, target: str) -> None:
        """Which tiles the slot already holds: a product's medium by its own key, a
        business one by the copy an earlier «Agregar» made (`_copied`)."""
        if target == MEDIA_DRAWER_CLIP:
            keys = {
                *creative.picker_selected.get("clip_images", []),
                *creative.picker_selected.get("clip_videos", []),
            }
        else:
            keys = set(creative.picker_selected.get(target, []))
        keys.discard("")
        held = []
        for c in [*self._business, *(c for g in self._products for c in g.choices)]:
            key = self._copied.get(c.token) or c.thumb or c.video
            if key in keys or self._copied.get(c.token) in keys:
                held.append(c.token)
        self.held = held

    @rx.event
    async def reset_choice(self) -> None:
        """The media drawer opened (or its slot changed): no choice is carried over."""
        creative = await self.get_state(CreativeState)
        self.chosen = []
        self.error = ""
        self._target = creative.media_drawer_target
        self._sync_held(creative, self._target)

    @rx.var
    def add_text(self) -> str:
        return add_label(len(self.chosen))

    @rx.var
    def empty(self) -> bool:
        return self.loaded and not self._business and not self._products

    @rx.var
    def count_text(self) -> str:
        return to_add_text(len(self.chosen))

    async def _ids(self) -> tuple[UUID, UUID] | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            return None
        brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
        if brand_id is None:
            return None
        return tenant_id, brand_id

    @rx.event(background=True)
    async def load(self) -> None:
        """The tab showed: its media are read (again, so a medium uploaded meanwhile
        appears); what is chosen stays while the tiles are still offered."""
        async with self:
            if self.loading:
                return
            self.loading = True
            self.error = ""
        ids = await self._ids()
        if ids is None:
            async with self:
                self.loading = False
                self.error = _NO_SESSION
            return
        try:
            business, products = await asyncio.to_thread(gallery_choices, *ids)
        except Exception as exc:  # noqa: BLE001 — never a skeleton forever
            logger.warning("generator gallery read failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = LOAD_FAILED
            return
        async with self:
            self._business = business
            self._products = products
            self._media_of = {
                c.token: c.media_type
                for c in [*business, *(c for g in products for c in g.choices)]
            }
            self.chosen = [t for t in self.chosen if t in self._media_of]
            creative = await self.get_state(CreativeState)
            self._sync_held(creative, self._target or creative.media_drawer_target)
            self.loading = False
            self.loaded = True

    @rx.event
    async def pick(self, token: str, target: str = "") -> None:
        """A tap on a tile: in or out, within the slot's room. `target`: the slot of an
        in-line selector (a part's sheet, UI-4); "" = the media drawer's."""
        if token not in self._media_of or self.adding:
            return
        creative = await self.get_state(CreativeState)
        target = target or creative.media_drawer_target
        if target != self._target:
            self._target = target
            self.chosen = []
        photo_room, video_room = creative.gallery_room(target)
        self.chosen, self.error = pick_limit(
            self.chosen,
            self._media_of,
            token,
            photo_room=photo_room,
            video_room=video_room,
            clip=target == MEDIA_DRAWER_CLIP,
        )

    @rx.event(background=True)
    async def finish(self, target: str = "") -> AsyncIterator[Any]:
        """«Agregar»: what is chosen here goes into the slot (resolved on the server under
        RLS, copied when it is the business's) and the drawer closes. Nothing chosen
        here: the drawer just closes (the other tabs add on the tap). `target`: an
        in-line selector's slot (a part's sheet): nothing closes, the sheet stays."""
        inline = bool(target)
        async with self:
            if self.adding:
                return
            creative = await self.get_state(CreativeState)
            target = target or creative.media_drawer_target
            tokens = list(self.chosen) if self._target == target else []
            if not tokens:
                self.chosen = []
                self.error = ""
                if not inline:
                    yield creative.close_media_drawer()
                return
            self.adding = True
            self.error = ""
            copied = dict(self._copied)
        ids = await self._ids()
        if ids is None:
            async with self:
                self.adding = False
                self.error = _NO_SESSION
            return
        try:
            picks = await asyncio.to_thread(resolve_picks, ids[0], ids[1], tokens, copied)
        except Exception as exc:  # noqa: BLE001 — say so, keep the choice
            logger.warning("generator gallery add failed: %s", type(exc).__name__)
            async with self:
                self.adding = False
                self.error = FAILED
            return
        async with self:
            self.adding = False
            self._copied = {**self._copied, **{p.token: p.key for p in picks if p.token}}
            creative = await self.get_state(CreativeState)
            added = creative.add_gallery_picks(picks, target)
            note = added_note(len(tokens), added)
            if added == 0:
                self.error = note
                return
            creative.gallery_pick_note = note
            self.chosen = []
            self.error = ""
            self._sync_held(creative, target)
            follow = [] if inline else [creative.close_media_drawer()]
        if target in ("part_images", "part_videos"):
            # UI-4: what a part's files trigger when they change (as `pick_media`)
            follow += [CreativeState.inspect_part_videos, CreativeState.inspect_part_merge]
        for event in follow:
            yield event
