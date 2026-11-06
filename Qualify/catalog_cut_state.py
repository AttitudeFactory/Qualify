"""Reflex state for «Corta tu video en partes» (CM-4, m-24955924).

A drawer over Galería for ONE ready video of the business. The owner moves the line
(a slider; the video shows that frame), fine-tunes it with «Atrás» / «Adelante», splits
the part under it with «Cortar aquí», removes parts with «Quitar esta parte» and saves
with «Guardar partes». Until «Guardar» nothing is written anywhere: the timeline lives
in this state only (`catalog_cut_vm`), so «Cancelar» needs no undo. «Guardar» queues ONE
`cut` job through the service (`start_cut`, CM-3) and closes the drawer; the section
then shows «Cortando tu video…» on the tile (read from the job, so it survives a reload)
and «Listo: tu video quedó en N partes.» when media-worker is done
(`CatalogGalleryState.track_cut`).

The video element is only a preview of the line's frame (no native controls): the
state is the single truth for where the line is, and each move seeks the video with a
one-line script. Provider calls run in `asyncio.to_thread`; the state is reset on
logout (`auth_state.business_state_classes`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .catalog_cut_vm import (
    FRAME_MS,
    SAVED_TOAST,
    PartRow,
    Span,
    TimelineBlock,
    cut_at,
    cut_spans,
    is_dirty,
    part_rows,
    playhead_label,
    remove_part,
    save_blocker,
    save_text,
    start,
    timeline_blocks,
)
from .catalog_gallery_provider import CatalogError, start_cut
from .catalog_gallery_state import CatalogGalleryState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

#: The preview `<video>`'s id (the seek script finds it by it).
VIDEO_ID = "q-cut-video"
_GONE = "Ese video ya no está en tu Galería. Cierra y vuelve a intentarlo."
_FAILED = "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."
_TOAST_MS = 5000


def _seek(ms: int) -> rx.event.EventSpec:
    return rx.call_script(
        f"(() => {{ const v = document.getElementById('{VIDEO_ID}');"
        f" if (v) {{ v.currentTime = {max(int(ms), 0) / 1000:.3f}; }} }})()"
    )


class CatalogCutState(rx.State):
    """The open cutter: which video, its timeline, the line, the open question."""

    open: bool = False
    media_id: str = ""
    video_url: str = ""
    poster_url: str = ""
    duration_ms: int = 0
    playhead_ms: int = 0
    #: The part tapped in the list (1-based among the kept ones; 0 = none).
    selected: int = 0
    #: Why the last «Cortar aquí» / «Guardar» did not go (the owner's words).
    error: str = ""
    remove_open: bool = False
    save_open: bool = False
    leave_open: bool = False
    saving: bool = False
    #: The timeline: [start_ms, end_ms, keep (0/1)] per span, covering the video.
    _spans: list[list[int]] = []

    # -- derived ------------------------------------------------------------------------

    def _timeline(self) -> list[Span]:
        return [Span(int(a), int(b), bool(k)) for a, b, k in self._spans]

    def _store(self, spans: list[Span]) -> None:
        self._spans = [[s.start_ms, s.end_ms, int(s.keep)] for s in spans]

    @rx.var
    def rows(self) -> list[PartRow]:
        return part_rows(self._timeline())

    @rx.var
    def blocks(self) -> list[TimelineBlock]:
        return timeline_blocks(self._timeline(), self.selected)

    @rx.var
    def playhead_text(self) -> str:
        return playhead_label(self.playhead_ms)

    @rx.var
    def playhead_left(self) -> str:
        total = self.duration_ms or 1
        return f"{100 * min(max(self.playhead_ms, 0), total) / total:.3f}%"

    @rx.var
    def blocker(self) -> str:
        return save_blocker(self._timeline(), self.duration_ms) if self.open else ""

    @rx.var
    def save_question(self) -> str:
        return save_text(len(self.rows))

    @rx.var
    def has_selection(self) -> bool:
        return 1 <= self.selected <= len(self.rows)

    # -- open / close ---------------------------------------------------------------------

    @rx.event
    async def open_cut(self, media_id: str) -> rx.event.EventSpec | None:
        """«Cortar video» on a ready video of the section."""
        gallery = await self.get_state(CatalogGalleryState)
        item = next((i for i in gallery.items if i.media_id == str(media_id) and i.cuttable), None)
        if item is None:
            return None
        self.media_id = item.media_id
        self.video_url = item.video_url
        self.poster_url = item.thumb_url
        self.duration_ms = int(item.duration_ms)
        self._store(start(self.duration_ms))
        self.playhead_ms = 0
        self.selected = 0
        self.error = ""
        self.remove_open = self.save_open = self.leave_open = False
        self.saving = False
        self.open = True
        return None

    def _close(self) -> None:
        self.open = False
        self.leave_open = self.remove_open = self.save_open = False
        self._spans = []
        self.media_id = ""
        self.error = ""

    @rx.event
    def request_close(self) -> None:
        """«Cancelar», the ×, Esc or the backdrop: with changes, «¿Salir sin guardar?»
        first; without them, straight out."""
        if self.saving:
            return
        if is_dirty(self._timeline(), self.duration_ms):
            self.leave_open = True
        else:
            self._close()

    @rx.event
    def set_open(self, value: bool) -> None:
        if not value:
            self.request_close()

    @rx.event
    def stay(self) -> None:
        self.leave_open = False

    @rx.event
    def set_leave_open(self, value: bool) -> None:
        if not value:
            self.leave_open = False

    @rx.event
    def page_left(self) -> None:
        """Galería unmounted (the phone's back, a menu entry): the cutter never comes
        back open by itself with an old timeline."""
        if not self.saving:
            self._close()

    @rx.event
    def discard(self) -> None:
        """«Salir sin guardar»: the video stays as it was (nothing was written)."""
        self._close()

    # -- the line -------------------------------------------------------------------------

    @rx.event
    def move_line(self, value: list[Any]) -> rx.event.EventSpec | None:
        """The slider (dragged with one finger): the video shows that frame."""
        try:
            ms = int(float(value[0]))
        except (TypeError, ValueError, IndexError):
            return None
        self.playhead_ms = min(max(ms, 0), self.duration_ms)
        self.error = ""
        return _seek(self.playhead_ms)

    @rx.event
    def nudge(self, frames: int) -> rx.event.EventSpec:
        """«Atrás» / «Adelante»: one frame each."""
        ms = self.playhead_ms + int(frames) * FRAME_MS
        self.playhead_ms = min(max(ms, 0), self.duration_ms)
        self.error = ""
        return _seek(self.playhead_ms)

    # -- cut, select, remove ----------------------------------------------------------------

    @rx.event
    def cut_here(self) -> None:
        spans, reason = cut_at(self._timeline(), self.playhead_ms)
        self._store(spans)
        self.error = reason

    @rx.event
    def select_part(self, part: int) -> None:
        """Tapping a part only selects it (it lights up on the bar too): the line stays
        where the owner left it, so «Cortar aquí» keeps meaning «here» (UX review)."""
        try:
            part = int(part)
        except (TypeError, ValueError):
            return
        if 1 <= part <= len(self.rows):
            self.selected = part
            self.error = ""

    @rx.event
    def ask_remove_part(self) -> None:
        if self.has_selection:
            self.remove_open = True

    @rx.event
    def set_remove_open(self, value: bool) -> None:
        if not value:
            self.remove_open = False

    @rx.event
    def confirm_remove_part(self) -> None:
        self.remove_open = False
        if self.has_selection:
            self._store(remove_part(self._timeline(), self.selected))
            self.selected = 0
            self.error = ""

    # -- save -------------------------------------------------------------------------------

    @rx.event
    def ask_save(self) -> None:
        reason = save_blocker(self._timeline(), self.duration_ms)
        if reason:
            self.error = reason
            return
        self.save_open = True

    @rx.event
    def set_save_open(self, value: bool) -> None:
        if not value:
            self.save_open = False

    @rx.event(background=True)
    async def confirm_save(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Guardar»: one `cut` job; the drawer closes and the section watches it."""
        async with self:
            if self.saving or not self.open:
                return
            self.save_open = False
            self.saving = True
            self.error = ""
            media_id = self.media_id
            spans = cut_spans(self._timeline())
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id or "")
        failure = ""
        job_id = ""
        if tenant_id is None:
            failure = _FAILED
        else:
            try:
                job_id = await asyncio.to_thread(start_cut, tenant_id, UUID(media_id), spans)
            except CatalogError as exc:  # too short, none kept, already cutting, full
                failure = str(exc.args[0]) if exc.args else _FAILED
            except (KeyError, ValueError):
                failure = _GONE
            except Exception as exc:  # noqa: BLE001 — never stuck saving
                logger.error("gallery cut start failed: %s", type(exc).__name__)
                failure = _FAILED
        async with self:
            self.saving = False
            if failure:
                self.error = failure
                return
            self._close()
        yield CatalogGalleryState.track_cut(job_id)
        yield rx.toast.info(SAVED_TOAST, duration=_TOAST_MS)
