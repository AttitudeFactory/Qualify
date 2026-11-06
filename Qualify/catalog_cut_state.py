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
    removed_notice,
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


#: The cutter's own address (N5): `/catalog?cortar=<media id>`, so the phone's «atrás»
#: closes it and leaves Galería where it was.
CUT_PARAM = "cortar"
_CATALOG_PATH = "/catalog"
_HISTORY_BACK = "window.history.back()"
_UNDO_DEPTH = 50

#: «Reproducir»: from the line, with sound (the tap is the user gesture that allows it).
PLAY_JS = (
    f"(() => {{ const v = document.getElementById('{VIDEO_ID}');"
    " if (v) { v.muted = false; v.play(); } })()"
)
#: «Pausar» (and «Cortar aquí» while playing): stop and say where, in ms (-1: no video).
PAUSE_JS = (
    f"(() => {{ const v = document.getElementById('{VIDEO_ID}');"
    " if (!v) return -1; v.pause(); return Math.round(v.currentTime * 1000); })()"
)


def _seek(ms: int) -> rx.event.EventSpec:
    """Stop any playback and show the frame at `ms`."""
    return rx.call_script(
        f"(() => {{ const v = document.getElementById('{VIDEO_ID}');"
        f" if (v) {{ v.pause(); v.currentTime = {max(int(ms), 0) / 1000:.3f}; }} }})()"
    )


def cut_href(media_id: str) -> str:
    return f"{_CATALOG_PATH}?{CUT_PARAM}={media_id}"


class CatalogCutState(rx.State):
    """The open cutter: which video, its timeline, the line, the open question."""

    open: bool = False
    media_id: str = ""
    video_url: str = ""
    poster_url: str = ""
    duration_ms: int = 0
    playhead_ms: int = 0
    #: Bumped when the line moves without the finger («Atrás» / «Adelante», opening):
    #: the slider remounts there (it is uncontrolled while dragged).
    line_key: int = 0
    #: The part tapped in the list (1-based among the kept ones; 0 = none).
    selected: int = 0
    #: Why the last «Cortar aquí» / «Guardar» did not go (the owner's words).
    error: str = ""
    remove_open: bool = False
    save_open: bool = False
    leave_open: bool = False
    saving: bool = False
    #: The preview is playing («Reproducir»); «Pausar» puts the line where it stopped.
    playing: bool = False
    #: What the last «Quitar esta parte» did, with the way back («Deshacer»).
    notice: str = ""
    #: The timeline: [start_ms, end_ms, keep (0/1)] per span, covering the video.
    _spans: list[list[int]] = []
    #: «Deshacer»: the timelines before each «Cortar aquí» / «Quitar esta parte».
    _undo: list[list[list[int]]] = []
    #: The address names the cutter (`?cortar=`) / it was pushed from this tab (so
    #: closing steps back in history instead of adding an entry).
    _url_open: bool = False
    _opened_in_app: bool = False

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
    def can_undo(self) -> bool:
        return len(self._undo) > 0

    @rx.var
    def has_selection(self) -> bool:
        return 1 <= self.selected <= len(self.rows)

    # -- open / close ---------------------------------------------------------------------

    def _url_cut(self) -> str:
        try:
            return str(self.router.url.query_parameters.get(CUT_PARAM, "") or "")
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            return ""

    def _leave_nav(self) -> list[rx.event.EventSpec]:
        """Take `?cortar=` off the address once the cutter is closed."""
        if not self._url_open:
            return []  # «atrás» already did
        self._url_open = False
        if self._opened_in_app:
            self._opened_in_app = False
            return [rx.call_script(_HISTORY_BACK)]
        return [rx.redirect(_CATALOG_PATH, replace=True)]

    @rx.event
    def sync_url(self) -> list[rx.event.EventSpec]:
        """Galería's on_load and the browser's back/forward (N5): the address leads.
        Without `?cortar=` an open cutter closes — asking first when it has changes;
        a `?cortar=` this tab did not open (a reload, an old link) is dropped: the
        Galería shows and the owner taps «Cortar video» again."""
        wanted = self._url_cut()
        if self.open:
            if wanted == self.media_id:
                return []
            self._url_open = False
            self._opened_in_app = False
            if self.saving:
                return []
            if is_dirty(self._timeline(), self.duration_ms):
                self.leave_open = True
            else:
                self._close()
            return []
        if wanted:
            return [rx.redirect(_CATALOG_PATH, replace=True)]
        return []

    @rx.event
    async def open_cut(self, media_id: str) -> list[rx.event.EventSpec] | None:
        """«Cortar video» on a ready video of the section: the cutter opens with its own
        address, a new history entry (so «atrás» closes it)."""
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
        self.line_key += 1
        self.selected = 0
        self.error = ""
        self.remove_open = self.save_open = self.leave_open = False
        self.saving = False
        self.playing = False
        self.notice = ""
        self._undo = []
        self.open = True
        self._url_open = True
        self._opened_in_app = True
        return [rx.redirect(cut_href(self.media_id))]

    def _close(self) -> None:
        self.open = False
        self.leave_open = self.remove_open = self.save_open = False
        self._spans = []
        self._undo = []
        self.media_id = ""
        self.error = ""
        self.notice = ""
        self.playing = False

    @rx.event
    def request_close(self) -> list[rx.event.EventSpec] | None:
        """«Cancelar», the ×, Esc or the backdrop: with changes, «¿Salir sin guardar?»
        first; without them, straight out (and off the address)."""
        if self.saving:
            return None
        if is_dirty(self._timeline(), self.duration_ms):
            self.leave_open = True
            return None
        self._close()
        return self._leave_nav()

    @rx.event
    def set_open(self, value: bool) -> list[rx.event.EventSpec] | None:
        return None if value else self.request_close()

    @rx.event
    def stay(self) -> list[rx.event.EventSpec]:
        """«Volver»: back to the cutter. If «atrás» had already taken `?cortar=` off the
        address, put it back, so the next «atrás» asks again."""
        self.leave_open = False
        if self.open and not self._url_open:
            self._url_open = True
            self._opened_in_app = True
            return [rx.redirect(cut_href(self.media_id))]
        return []

    @rx.event
    def set_leave_open(self, value: bool) -> list[rx.event.EventSpec] | None:
        """The dialog's own close (Esc) is «Volver»: the safe answer."""
        return None if value else self.stay()

    @rx.event
    def page_left(self) -> None:
        """Galería unmounted (the phone's back, a menu entry): the cutter never comes
        back open by itself with an old timeline."""
        if not self.saving:
            self._close()
            self._url_open = False
            self._opened_in_app = False

    @rx.event
    def discard(self) -> list[rx.event.EventSpec]:
        """«Salir sin guardar»: the video stays as it was (nothing was written)."""
        self._close()
        return self._leave_nav()

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
        self.playing = False
        return _seek(self.playhead_ms)

    @rx.event
    def nudge(self, frames: int) -> rx.event.EventSpec:
        """«Atrás» / «Adelante»: one frame each."""
        ms = self.playhead_ms + int(frames) * FRAME_MS
        self.playhead_ms = min(max(ms, 0), self.duration_ms)
        self.line_key += 1
        self.error = ""
        self.playing = False
        return _seek(self.playhead_ms)

    # -- watch (founder 2026-11-07: to find the cut point by watching and listening) ----

    @rx.event
    def started(self) -> None:
        """«Reproducir» was tapped (the video already plays, client-side)."""
        self.playing = True
        self.error = ""

    def _line_from_video(self, ms: Any) -> None:
        """Where the paused video stopped becomes the line."""
        try:
            at = int(ms)
        except (TypeError, ValueError):
            return
        if at >= 0:
            self.playhead_ms = min(at, self.duration_ms)
            self.line_key += 1

    @rx.event
    def paused_at(self, ms: Any) -> None:
        """«Pausar»: the line goes where the video stopped."""
        if self.playing:
            self._line_from_video(ms)
        self.playing = False

    # -- cut, select, remove, undo ----------------------------------------------------------

    def _remember(self) -> None:
        self._undo = [*self._undo, [list(span) for span in self._spans]][-_UNDO_DEPTH:]

    @rx.event
    def cut_here(self, ms: Any = -1) -> None:
        """«Cortar aquí». Its button first pauses the video and reports where it is, so
        a cut made while watching lands on the frame on screen."""
        if self.playing:
            self._line_from_video(ms)
            self.playing = False
        spans, reason = cut_at(self._timeline(), self.playhead_ms)
        if not reason:
            self._remember()
        self._store(spans)
        self.error = reason
        self.notice = ""

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
    def remove_selected(self) -> None:
        """«Quitar esta parte»: at once — «Deshacer» brings it back until «Guardar», and
        the save question says, once, that what was removed is gone for good."""
        if not self.has_selection:
            return
        part = self.selected
        self._remember()
        self._store(remove_part(self._timeline(), part))
        self.selected = 0
        self.error = ""
        self.notice = removed_notice(part)

    @rx.event
    def undo(self) -> None:
        """«Deshacer»: the timeline as it was before the last cut or removal."""
        if not self._undo:
            return
        *rest, last = self._undo
        self._undo = rest
        self._spans = last
        self.selected = 0
        self.error = ""
        self.notice = ""

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
            follow = self._leave_nav()
        for event in follow:
            yield event
        yield CatalogGalleryState.track_cut(job_id)
        yield rx.toast.info(SAVED_TOAST, duration=_TOAST_MS)
