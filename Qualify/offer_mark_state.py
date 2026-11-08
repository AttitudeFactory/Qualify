"""«Usar como tu oferta» (m-24945889, `docs/ux-whatsapp-atajos.md` §2): which piece is
the business's offer, and the owner's mark / unmark / «Deshacer». Shown in Por aprobar
(`/drafts/[draft_id]`) and in the Planificador's panel; a result that comes back for a
piece no longer on screen is dropped."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .connections_provider import acting_user_id
from .offer_mark_provider import mark_offer, offer_info, unmark_offer
from .offer_mark_vm import (
    MARK_FAILED,
    NO_SESSION,
    UNDO_LABEL,
    UNDONE_TOAST,
    UNMARK_FAILED,
    UNMARKED_TOAST,
    marked_toast,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_TOAST_MS = 6000


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class OfferMarkState(rx.State):
    #: The piece the control is about (the page's or the panel's).
    draft_id: str = ""
    loaded: bool = False
    is_offer: bool = False
    busy: bool = False
    error: str = ""
    _brand_id: str = ""
    #: «Deshacer» after replacing: the offer before (a draft id), once.
    _undo_previous: str = ""

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    @rx.event(background=True)
    async def load_for(self, draft_id: str) -> None:
        """The Planificador's panel mounted for this piece."""
        await self._load(draft_id if isinstance(draft_id, str) else "")

    async def _load(self, draft_id: str) -> None:
        async with self:
            self.draft_id = draft_id if _uuid(draft_id) is not None else ""
            self.loaded = False
            self.is_offer = False
            self.error = ""
            self._brand_id = ""
            self._undo_previous = ""
            tenant_id = await self._tenant()
        draft = _uuid(draft_id)
        if tenant_id is None or draft is None:
            return
        try:
            info = await asyncio.to_thread(offer_info, tenant_id, draft)
        except Exception as exc:  # noqa: BLE001 — an extra on the screen: hidden, never fatal
            logger.warning("offer mark load failed: %s", type(exc).__name__)
            return
        async with self:
            if self.draft_id != draft_id:
                return  # another piece is on screen now
            self._brand_id = str(info.brand_id) if info.brand_id else ""
            self.is_offer = info.is_offer
            self.loaded = info.brand_id is not None

    @rx.event(background=True)
    async def mark(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.busy or not self.loaded or self.is_offer:
                return
            draft_id = self.draft_id
            self.busy = True
            self.error = ""
            tenant_id = await self._tenant()
        async for event in self._mark(tenant_id, draft_id, undo=False):
            yield event

    async def _mark(
        self, tenant_id: UUID | None, draft_id: str, *, undo: bool
    ) -> AsyncIterator[rx.event.EventSpec]:
        from qualify_api.whatsapp.promotions import PromotionNotAllowed  # noqa: PLC0415

        draft = _uuid(draft_id)
        error, result = "", None
        if tenant_id is None or draft is None:
            error = NO_SESSION
        else:
            try:
                user = await asyncio.to_thread(acting_user_id, tenant_id)
                result = await asyncio.to_thread(mark_offer, tenant_id, draft, user)
            except PromotionNotAllowed as exc:
                error = exc.message
            except Exception as exc:  # noqa: BLE001
                logger.error("offer mark failed: %s", type(exc).__name__)
                error = MARK_FAILED
        async with self:
            self.busy = False
            if error:
                self.error = error
                return
            self.is_offer = self.draft_id == draft_id
            self._undo_previous = "" if undo else (result.previous_id if result else "")
            previous = self._undo_previous
        if undo:
            yield rx.toast.success(UNDONE_TOAST, duration=_TOAST_MS)
            return
        assert result is not None
        text = marked_toast(result.title, result.previous_title)
        if previous:
            yield rx.toast.success(
                text,
                duration=_TOAST_MS,
                action={"label": UNDO_LABEL, "on_click": OfferMarkState.undo},
            )
        else:
            yield rx.toast.success(text, duration=_TOAST_MS)

    @rx.event(background=True)
    async def undo(self) -> AsyncIterator[rx.event.EventSpec]:
        """The toast's «Deshacer»: the previous offer is the offer again."""
        async with self:
            previous, self._undo_previous = self._undo_previous, ""
            if not previous or self.busy:
                return
            self.busy = True
            tenant_id = await self._tenant()
        async for event in self._mark(tenant_id, previous, undo=True):
            yield event

    @rx.event(background=True)
    async def unmark(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.busy or not self.is_offer or not self._brand_id:
                return
            draft_id, brand = self.draft_id, _uuid(self._brand_id)
            self.busy = True
            self.error = ""
            tenant_id = await self._tenant()
        error = ""
        if tenant_id is None or brand is None:
            error = NO_SESSION
        else:
            try:
                await asyncio.to_thread(unmark_offer, tenant_id, brand)
            except Exception as exc:  # noqa: BLE001
                logger.error("offer unmark failed: %s", type(exc).__name__)
                error = UNMARK_FAILED
        async with self:
            self.busy = False
            if error:
                self.error = error
                return
            if self.draft_id == draft_id:
                self.is_offer = False
            self._undo_previous = ""
        yield rx.toast.success(UNMARKED_TOAST, duration=_TOAST_MS)
