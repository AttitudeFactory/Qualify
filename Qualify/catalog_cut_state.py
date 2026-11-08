"""Reflex state for «Corta tu video en partes» (CM-4, m-24955924).

A drawer over Galería for ONE ready video of the business. The owner moves the line
(a slider; the video shows that frame), fine-tunes it with «Atrás» / «Adelante», splits
the part under it with «Cortar aquí», removes parts with «Quitar esta parte» and saves
with «Guardar partes». Until «Guardar» nothing is written anywhere: the timeline lives
in this state only (`catalog_cut_vm`), so «Cancelar» needs no undo. «Guardar» queues ONE
`cut` job through the service (`start_cut`, CM-3) and the drawer stays open on a waiting
step (m-24976806, founder 2026-11-08: the cut was invisible): «Cortando tu video en N
partes…» with the job's stage (en cola → cortando → guardando), «Puedes salir…», then
«Listo: tu video quedó en N partes.» with the parts, or the failure with «Intentar de
nuevo». The step reads the section's card for that job (`CatalogGalleryState.panel_*`,
polled while it runs); leaving it leaves the card above the tiles.

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
from urllib.parse import urlencode
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .catalog_cut_vm import (
    FRAME_MS,
    SAVED_TOAST,
    UNDONE_CUT,
    PartRow,
    Span,
    TimelineBlock,
    back_notice,
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

#: Two hidden buttons the playing video clicks (the `ui.route_history` pattern: Reflex
#: 0.10 gives `<video>` no media events): one reads the time so the line follows the
#: video a few times a second, one says the video stopped by itself (its end, or a
#: play the browser refused).
TICK_ID = "q-cut-tick"
ENDED_ID = "q-cut-ended"
#: «Reproducir»: from the line, with sound (the tap is the user gesture that allows it).
PLAY_JS = (
    f"(() => {{ const v = document.getElementById('{VIDEO_ID}'); if (!v) return;"
    " let last = 0;"
    " v.ontimeupdate = () => { const now = Date.now(); if (now - last < 250) return;"
    f" last = now; document.getElementById('{TICK_ID}')?.click(); }};"
    f" v.onended = () => document.getElementById('{ENDED_ID}')?.click();"
    " v.muted = false;"
    f" v.play().catch(() => document.getElementById('{ENDED_ID}')?.click()); }})()"
)
#: The time on screen, in ms (-1: no video) — what the tick reports.
TIME_JS = (
    f"(() => {{ const v = document.getElementById('{VIDEO_ID}');"
    " return v ? Math.round(v.currentTime * 1000) : -1; })()"
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


def cut_href(media_id: str, query: dict[str, Any] | None = None) -> str:
    """`/catalog` with `?cortar=<id>` — keeping the address's other parameters
    (`?volver=` must survive opening the cutter)."""
    params = {k: str(v) for k, v in (query or {}).items() if k != CUT_PARAM}
    if media_id:
        params[CUT_PARAM] = media_id
    return f"{_CATALOG_PATH}?{urlencode(params)}" if params else _CATALOG_PATH


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
    save_open: bool = False
    leave_open: bool = False
    saving: bool = False
    #: The preview is playing («Reproducir»); «Pausar» puts the line where it stopped.
    playing: bool = False
    #: What the last «Quitar esta parte» did, with the way back («Deshacer»).
    notice: str = ""
    #: The timeline: [start_ms, end_ms, keep (0/1)] per span, covering the video.
    _spans: list[list[int]] = []
    #: «Deshacer»: the timelines before each «Cortar aquí» / «Quitar esta parte», and
    #: what undoing each one says.
    _undo: list[list[list[int]]] = []
    _undo_said: list[str] = []
    #: Where «Reproducir» started: the end of the video brings the line back there.
    _play_from: int = 0
    #: The address names the cutter (`?cortar=`) / it was pushed from this tab (so
    #: closing steps back in history instead of adding an entry).
    _url_open: bool = False
    _opened_in_app: bool = False
    #: Galería unmounted while a save ran: its outcome must not navigate.
    _left: bool = False
    #: m-24976806: «Guardar» went through; the drawer shows the cut's progress (the
    #: section's `panel_job`) instead of the timeline.
    waiting: bool = False
    _waiting_job: str = ""

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

    def _query(self) -> dict[str, Any]:
        try:
            return dict(self.router.url.query_parameters)
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            return {}

    def _url_cut(self) -> str:
        return str(self._query().get(CUT_PARAM, "") or "")

    def _push_address(self) -> list[rx.event.EventSpec]:
        self._url_open = True
        self._opened_in_app = True
        return [rx.redirect(cut_href(self.media_id, self._query()))]

    def _leave_nav(self, media_id: str = "") -> list[rx.event.EventSpec]:
        """Take `?cortar=` off the address once the cutter is closed. A click decides
        from the address it carries (what the owner had on screen when tapping), never
        from flags a back/forward race could leave stale; a background save, whose
        router is the tap on «Guardar», decides from `_url_open`."""
        on_address = (self._url_cut() == media_id) if media_id else self._url_open
        in_app = self._opened_in_app
        self._url_open = False
        self._opened_in_app = False
        if not on_address:
            return []  # «atrás» already took it off
        if in_app:
            return [rx.call_script(_HISTORY_BACK)]
        return [rx.redirect(cut_href("", self._query()), replace=True)]

    @rx.event
    def sync_url(self) -> list[rx.event.EventSpec]:
        """Galería's on_load and the browser's back/forward (N5): the address leads.
        Without `?cortar=` an open cutter closes — or, with changes, asks «¿Salir sin
        guardar?» and puts `?cortar=` straight back, so a second «atrás» lands on the
        same question instead of leaving Galería unanswered. A reload of this tab keeps
        the cutter (its state survives); a `?cortar=` this tab did not open (an old
        link) is dropped and the Galería shows."""
        wanted = self._url_cut()
        self._left = False
        if self.open:
            if wanted == self.media_id:
                return []
            if self.leave_open:
                # the question is already open: its two answers read the address at the
                # tap (`stay`, `discard`), so a repeated «atrás» — or on_load and popstate
                # both running for one — changes nothing here
                self._url_open = False
                return []
            self._url_open = False
            self._opened_in_app = False
            if self.saving:
                return []
            if self.waiting:
                # the cut is already queued: «atrás» simply leaves its progress to the card
                self._close()
                return [CatalogGalleryState.release_panel]
            if is_dirty(self._timeline(), self.duration_ms):
                self.leave_open = True
                self.save_open = False  # one question at a time
                stop = [_seek(self.playhead_ms)] if self.playing else []
                self.playing = False
                return [*stop, *self._push_address()]
            self.playing = False
            self._close()
            return []
        if wanted:
            return [rx.redirect(cut_href("", self._query()), replace=True)]
        return []

    @rx.event
    async def open_cut(self, media_id: str) -> list[rx.event.EventSpec] | None:
        """«Cortar video» on a ready video of the section: the cutter opens with its own
        address, a new history entry (so «atrás» closes it)."""
        if self.open and self.media_id == str(media_id):
            return None  # a double tap pushes one entry, not two
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
        self.save_open = self.leave_open = False
        self.saving = False
        self.playing = False
        self.notice = ""
        self._undo = []
        self._undo_said = []
        self.open = True
        return self._push_address()

    def _close(self) -> None:
        self.open = False
        self.leave_open = self.save_open = False
        self._spans = []
        self._undo = []
        self._undo_said = []
        self.media_id = ""
        self.error = ""
        self.notice = ""
        self.playing = False
        self.waiting = False
        self._waiting_job = ""

    @rx.event
    def request_close(self) -> list[rx.event.EventSpec] | None:
        """«Cancelar», the ×, Esc or the backdrop: with changes, «¿Salir sin guardar?»
        first; without them, straight out (and off the address). On the waiting step the
        cut goes on: out at once, its card above the tiles keeps saying how it goes."""
        if self.saving:
            return None
        if self.waiting:
            return self.leave_waiting()
        if is_dirty(self._timeline(), self.duration_ms):
            self.leave_open = True
            return None
        media_id = self.media_id
        self._close()
        return self._leave_nav(media_id)

    @rx.event
    def leave_waiting(self) -> list[rx.event.EventSpec]:
        """«Seguir en Galería» (or «Cerrar» after a failure): the drawer closes, the cut's
        card above the tiles takes over."""
        media_id = self.media_id
        self._close()
        return [*self._leave_nav(media_id), CatalogGalleryState.release_panel]

    @rx.event
    def finish_waiting(self) -> list[rx.event.EventSpec]:
        """«Entendido» on «Listo: tu video quedó en N partes.»: out, and the card goes."""
        media_id, job_id = self.media_id, self._waiting_job
        self._close()
        return [*self._leave_nav(media_id), CatalogGalleryState.dismiss_cut(job_id)]

    @rx.event
    def set_open(self, value: bool) -> list[rx.event.EventSpec] | None:
        return None if value else self.request_close()

    @rx.event
    def stay(self) -> list[rx.event.EventSpec]:
        """«Volver»: back to the cutter. If «atrás» had already taken `?cortar=` off the
        address, put it back, so the next «atrás» asks again."""
        self.leave_open = False
        if self.open and self._url_cut() != self.media_id:
            return self._push_address()
        self._url_open = self.open
        return []

    @rx.event
    def set_leave_open(self, value: bool) -> list[rx.event.EventSpec] | None:
        """The dialog's own close (Esc) is «Volver»: the safe answer."""
        return None if value else self.stay()

    @rx.event
    def page_left(self) -> None:
        """Galería unmounted (the phone's back, a menu entry): the cutter never comes
        back open by itself with an old timeline. The address flags always go: the
        cutter is no longer on this page's history (a save still running then never
        steps «back» on another page)."""
        self._url_open = False
        self._opened_in_app = False
        if self.saving:
            self._left = True
        else:
            self._close()

    @rx.event
    def discard(self) -> list[rx.event.EventSpec]:
        """«Salir sin guardar»: the video stays as it was (nothing was written)."""
        media_id = self.media_id
        self._close()
        return self._leave_nav(media_id)

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
        self._play_from = self.playhead_ms
        self.error = ""

    @rx.event
    def follow(self, ms: Any) -> None:
        """A tick of the playing video: the line and its time follow what is on screen."""
        if not self.playing:
            return
        try:
            at = int(ms)
        except (TypeError, ValueError):
            return
        if at >= 0:
            # only the line and its time: remounting the slider 4 times a second would
            # drop a finger that grabs it (it remounts once, when playback stops)
            self.playhead_ms = min(at, self.duration_ms)

    @rx.event
    def playback_ended(self) -> rx.event.EventSpec | None:
        """The video reached its end (or the browser refused to play): «Reproducir»
        again, and the line back where playback started — the next «Reproducir» plays
        the same stretch, which is what hunting for a cut point needs."""
        if not self.playing:
            return None
        self.playing = False
        self.playhead_ms = self._play_from
        self.line_key += 1
        return _seek(self.playhead_ms)

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

    def _remember(self, said: str) -> None:
        self._undo = [*self._undo, [list(span) for span in self._spans]][-_UNDO_DEPTH:]
        self._undo_said = [*self._undo_said, said][-_UNDO_DEPTH:]

    @rx.event
    def cut_here(self, ms: Any = -1) -> None:
        """«Cortar aquí». Its button first pauses the video and reports where it is, so
        a cut made while watching lands on the frame on screen."""
        if self.playing:
            self._line_from_video(ms)
            self.playing = False
        spans, reason = cut_at(self._timeline(), self.playhead_ms)
        if not reason:
            self._remember(UNDONE_CUT)
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
        row = self.rows[part - 1]
        self._remember(back_notice(row.start_ms, row.end_ms))
        self._store(remove_part(self._timeline(), part))
        self.selected = 0
        self.error = ""
        self.notice = removed_notice(row.start_ms, row.end_ms)

    @rx.event
    def undo(self) -> None:
        """«Deshacer»: the timeline as it was before the last cut or removal."""
        if not self._undo:
            return
        *rest, last = self._undo
        self._undo = rest
        said = self._undo_said[-1] if self._undo_said else ""
        self._undo_said = self._undo_said[:-1]
        self._spans = last
        self.selected = 0
        self.error = ""
        self.notice = said

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
        """«Guardar»: one `cut` job; the drawer turns into its waiting step and the
        section watches the job (m-24976806)."""
        async with self:
            if self.saving or not self.open:
                return
            self.save_open = False
            self.saving = True
            self.error = ""
            media_id = self.media_id
            spans = cut_spans(self._timeline())
            parts = len(self.rows)
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
            if failure and self._left:
                # the owner left Galería meanwhile: nowhere to go, but they must know the
                # cut did not go through (a toast shows on any page)
                self._left = False
                self._close()
                follow = [rx.toast.error(failure, duration=_TOAST_MS)]
            elif failure:
                self.error = failure
                # «atrás» during the save took `?cortar=` away: put it back, so the
                # next «atrás» asks instead of leaving with the cuts
                follow = self._push_address() if self.open and not self._url_open else []
            elif self._left:
                # gone from Galería meanwhile: the cut goes on; say so wherever they are
                self._left = False
                self._close()
                follow = [rx.toast.info(SAVED_TOAST, duration=_TOAST_MS)]
            else:
                # the drawer stays, on its waiting step: the owner sees the cut happen
                self.waiting = True
                self._waiting_job = job_id
                self.playing = False
                follow = []
            in_panel = self.waiting
        for event in follow:
            yield event
        if failure:
            return
        yield CatalogGalleryState.track_cut(job_id, parts, in_panel)
