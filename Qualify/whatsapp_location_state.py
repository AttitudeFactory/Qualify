"""«Tu local en el mapa» in Tu número › Perfil (m-24945889, `docs/ux-whatsapp-atajos.md`
§3): the number's map point — from the browser («Usar mi ubicación») or from a Google
Maps link — shown with «Ver en el mapa» and «Quitar del mapa». A result that lands after
the owner switched numbers is dropped. «‹ Volver al chat» when the owner came from a
chat's «Cómo llegar» (`?volver=`)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .catalog_vm import return_path_from_query
from .tenant import tenant_uuid
from .whatsapp_location_provider import MapPoint, clear_point, read_point, save_point
from .whatsapp_location_vm import (
    GEO_DENIED,
    GEO_JS,
    LOAD_FAILED,
    NO_SESSION,
    REMOVED,
    SAVE_FAILED,
    SAVED,
    approximate_note,
    chat_back_path,
    parse_maps_link,
)
from .whatsapp_state import WhatsAppState

logger = logging.getLogger(__name__)

_TOAST_MS = 6000


class WhatsAppLocationState(rx.State):
    loaded_for: str = ""
    loading: bool = False
    busy: bool = False
    locating: bool = False
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
    def use_my_location(self) -> rx.event.EventSpec | None:
        """«Usar mi ubicación»: the browser asks the owner; nothing is saved until it
        answers with a close-enough position."""
        if self.busy or self.locating:
            return None
        self.locating = True
        self.error = ""
        return rx.call_script(GEO_JS, callback=WhatsAppLocationState.got_position)

    @rx.event
    def got_position(self, result: Any) -> rx.event.EventSpec | None:
        self.locating = False
        if not isinstance(result, dict) or "error" in result:
            self.error = GEO_DENIED
            return None
        try:
            lat, lng = float(result["lat"]), float(result["lng"])
            accuracy = float(result.get("acc") or 0)
        except (KeyError, TypeError, ValueError):
            self.error = GEO_DENIED
            return None
        note = approximate_note(accuracy)
        if note:
            self.error = note
            return None
        return WhatsAppLocationState.save_coordinates(lat, lng)

    @rx.event
    def save_link(self) -> rx.event.EventSpec | None:
        """«Guardar en el mapa» with the pasted Google Maps link."""
        if self.busy:
            return None
        found = parse_maps_link(self.link_text)
        if found.error or found.latitude is None or found.longitude is None:
            self.error = found.error
            return None
        return WhatsAppLocationState.save_coordinates(found.latitude, found.longitude)

    @rx.event(background=True)
    async def save_coordinates(self, latitude: float, longitude: float) -> AsyncIterator[Any]:
        from qualify_api.whatsapp.directions import LocationInvalid  # noqa: PLC0415

        async with self:
            if self.busy:
                return
            self.busy = True
            self.error = ""
            tenant_id, connection_id = await self._ids()
        error, point = "", MapPoint()
        try:
            if tenant_id is None or not connection_id:
                raise PermissionError
            point = await asyncio.to_thread(
                save_point, tenant_id, UUID(connection_id), float(latitude), float(longitude)
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
            self._show(point)
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
