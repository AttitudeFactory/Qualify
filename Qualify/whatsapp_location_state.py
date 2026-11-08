"""«Tu local en el mapa» in Tu número › Perfil (m-24945889, `docs/ux-whatsapp-atajos.md`
§3): the number's map point — from the browser («Usar mi ubicación») or from a Google
Maps link — shown with «Ver en el mapa» and «Quitar del mapa». A result that lands after
the owner switched numbers is dropped. «‹ Volver al chat» when the owner came from a
chat's «Cómo llegar» (`?volver=`)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .catalog_vm import return_path_from_query
from .tenant import tenant_uuid
from .whatsapp_location_provider import (
    LinkPoint,
    MapPoint,
    clear_point,
    read_point,
    resolve_link,
    save_point,
)
from .whatsapp_location_vm import (
    GEO_JS,
    LOAD_FAILED,
    NO_SESSION,
    REMOVED,
    SAVE_FAILED,
    SAVED,
    chat_back_path,
    link_refusal,
    position_point,
)
from .whatsapp_state import WhatsAppState

logger = logging.getLogger(__name__)

_TOAST_MS = 6000


class WhatsAppLocationState(rx.State):
    loaded_for: str = ""
    loading: bool = False
    busy: bool = False
    locating: bool = False
    #: The backend is reading a pasted link («Leyendo el enlace…»).
    reading: bool = False
    #: The number «Usar mi ubicación» was tapped for (backend only).
    _locating_for: str = ""
    has_point: bool = False
    point_label: str = ""
    map_href: str = ""
    link_text: str = ""
    #: Why the point could not be taken (the owner's words, with what to do).
    error: str = ""
    load_error: str = ""
    #: The chat the owner came from («‹ Volver al chat»), already checked.
    return_to: str = ""

    async def _ids(self) -> tuple[UUID | None, str]:
        auth = await self.get_state(AuthState)
        wa = await self.get_state(WhatsAppState)
        tenant = tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None
        return tenant, wa.selected_connection_id

    def _show(self, point: MapPoint) -> None:
        self.has_point = point.has_point
        self.point_label = point.label
        self.map_href = point.href

    @rx.event
    def read_return(self) -> None:
        """Perfil mounted: «‹ Volver al chat» only for the app's own chats address."""
        self.return_to = chat_back_path(return_path_from_query(self.router.url.query_parameters))

    @rx.event(background=True)
    async def ensure_loaded(self) -> None:
        """The Perfil panel mounted (or the number changed): read the point once."""
        async with self:
            tenant_id, connection_id = await self._ids()
            if not connection_id or self.loaded_for == connection_id or self.loading:
                return
            self.loading = True
            self.load_error = ""
            self.error = ""
            self.link_text = ""
        point, failed = MapPoint(), False
        try:
            if tenant_id is None:
                raise PermissionError
            point = await asyncio.to_thread(read_point, tenant_id, UUID(connection_id))
        except Exception as exc:  # noqa: BLE001 — worded, never shown
            if not isinstance(exc, PermissionError):
                logger.warning("whatsapp map point load failed: %s", type(exc).__name__)
            failed = True
        async with self:
            _tenant, current = await self._ids()
            self.loading = False
            if current != connection_id:
                return  # another number is on screen now
            if failed:
                self.load_error = NO_SESSION if tenant_id is None else LOAD_FAILED
                return
            self._show(point)
            self.loaded_for = connection_id

    @rx.event
    def set_link_text(self, value: str) -> None:
        self.link_text = value[:2000] if isinstance(value, str) else ""
        self.error = ""

    @rx.event
    async def use_my_location(self) -> rx.event.EventSpec | None:
        """«Usar mi ubicación»: the browser asks the owner; nothing is saved until it
        answers with a close-enough position — and only to the number on screen NOW
        (captured here, before the prompt)."""
        if self.busy or self.locating:
            return None
        self.locating = True
        self.error = ""
        _tenant, self._locating_for = await self._ids()
        return rx.call_script(GEO_JS, callback=WhatsAppLocationState.got_position)

    @rx.event(background=True)
    async def got_position(self, result: Any) -> AsyncIterator[Any]:
        """The browser's answer. A public event, so its argument is client data: anyone
        driving this session could send a position, but it only ever sets the owner's
        own pin on the number captured by `use_my_location`; the accuracy and range
        rules are checked here and the backend range-checks again."""
        async with self:
            self.locating = False
            started_for, self._locating_for = self._locating_for, ""
            point = position_point(result)
            if isinstance(point, str):
                self.error = point
                return
            if not started_for:
                return  # no «Usar mi ubicación» asked for this answer
            tenant_id, _current = await self._ids()
        async for event in self._save(lambda: (point[0], point[1], None), tenant_id, started_for):
            yield event

    @rx.event(background=True)
    async def save_link(self) -> AsyncIterator[Any]:
        """«Guardar en el mapa» with the pasted Google Maps link: the backend reads it
        (following «Compartir»'s short link), then the one guarded save."""
        async with self:
            text = self.link_text.strip()
            if self.busy or self.reading or not text:
                return
            self.reading = True
            self.error = ""
            # the number on screen NOW: the read below takes seconds of network
            tenant_id, connection_id = await self._ids()
        try:
            found = await asyncio.to_thread(resolve_link, text)
        except Exception as exc:  # noqa: BLE001 — worded, never shown
            logger.warning("whatsapp maps link read failed: %s", type(exc).__name__)
            found = LinkPoint(reason="unreachable")
        async with self:
            self.reading = False
            if found.latitude is None or found.longitude is None:
                self.error = link_refusal(found.reason)
                return
        async for event in self._save(
            lambda: (found.latitude, found.longitude, found.name), tenant_id, connection_id
        ):
            yield event

    async def _save(
        self,
        point: Callable[[], tuple[Any, Any, str | None]],
        tenant_id: UUID | None,
        connection_id: str,
    ) -> AsyncIterator[Any]:
        """The ONLY write of a point (not an event). `tenant_id`/`connection_id` are the
        ones captured when the owner STARTED (the link's read or the browser's prompt):
        if another number is on screen by now, nothing is saved anywhere. One at a time;
        the backend range-checks again."""
        from qualify_api.whatsapp.directions import LocationInvalid  # noqa: PLC0415

        async with self:
            _tenant, current = await self._ids()
            if self.busy or not connection_id or current != connection_id:
                return  # switched numbers meanwhile: dropped, saved on neither
            self.busy = True
            self.error = ""
        latitude, longitude, name = point()
        error, shown = "", MapPoint()
        try:
            if tenant_id is None or not connection_id:
                raise PermissionError
            shown = await asyncio.to_thread(
                save_point, tenant_id, UUID(connection_id), float(latitude), float(longitude), name
            )
        except PermissionError:
            error = NO_SESSION
        except LocationInvalid as exc:
            error = exc.message
        except Exception as exc:  # noqa: BLE001
            logger.error("whatsapp map point save failed: %s", type(exc).__name__)
            error = SAVE_FAILED
        async with self:
            self.busy = False
            _tenant, current = await self._ids()
            if current != connection_id:
                return
            if error:
                self.error = error
                return
            self._show(shown)
            self.link_text = ""
            self.loaded_for = connection_id
        yield rx.toast.success(SAVED, duration=_TOAST_MS)

    @rx.event(background=True)
    async def remove(self) -> AsyncIterator[Any]:
        """«Quitar del mapa»: the point goes, the address stays (the text fallback)."""
        async with self:
            if self.busy or not self.has_point:
                return
            self.busy = True
            self.error = ""
            tenant_id, connection_id = await self._ids()
        error = ""
        try:
            if tenant_id is None or not connection_id:
                raise PermissionError
            await asyncio.to_thread(clear_point, tenant_id, UUID(connection_id))
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            logger.error("whatsapp map point clear failed: %s", type(exc).__name__)
            error = SAVE_FAILED
        async with self:
            self.busy = False
            _tenant, current = await self._ids()
            if current != connection_id:
                return
            if error:
                self.error = error
                return
            self._show(MapPoint())
        yield rx.toast.success(REMOVED, duration=_TOAST_MS)
