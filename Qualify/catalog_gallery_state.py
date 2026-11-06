"""Reflex state for «Fotos y videos de tu negocio» in Galería (CM-2, m-24955919).

The business's own photos and videos (not a product's), kept by
`qualify_api.catalog.business_media` (CM-1, ADR 47). Rules this state keeps:

- **Streaming upload.** «Agregar fotos o videos» sends the files with
  `rx.upload_files_chunk` to `receive_upload`, a BACKGROUND handler with an
  `rx.UploadChunkIterator` parameter: the chunks go to the waiting room on disk as they
  arrive (never `list[rx.UploadFile]`, whose `request.form()` copies the whole body to
  `/tmp` first, never a whole file in memory).
- **Refused before uploading.** The picker sends the names and sizes of what was chosen
  as a bound argument, which Reflex parses BEFORE the first file byte. The handler asks
  the service first (`check_upload`: the Galería full, 3 videos already waiting) and, if
  it refuses, returns without reading a chunk — Reflex then answers 400 and the browser
  stops sending. A video over 500 MB never leaves the phone (the picker's `max_size`).
- **Progress** comes from the browser (`on_upload_progress` → `upload_progress`):
  «Subiendo tu video (45 %)…». A cut connection, or a closed screen, cancels the
  handler: `stage_chunks` deletes the partial file and the screen says «Se cortó la
  subida…» — nothing half-saved appears.
- **Preparing** is read from the service's jobs (`list_gallery_jobs`), never from this
  state, so «Preparando tu video…» survives a reload and a deploy. While a job is active
  `watch` re-reads every few seconds, for as long as the section is on screen.
- Every provider call blocks (SQLAlchemy, Pillow, R2, Redis) and runs in
  `asyncio.to_thread`. Business data only in server-side vars; logout resets this state
  (`auth_state._business_states`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .catalog_gallery_provider import (
    CatalogError,
    GallerySnapshot,
    add_staged,
    check_upload,
    discard_staged_files,
    dismiss_job,
    free_places,
    load_gallery,
    remove_media,
    stage_upload,
)
from .catalog_gallery_vm import (
    GALLERY_FULL_TEXT,
    MAX_WAITING_VIDEOS,
    SAVE_FAILED_TEXT,
    UPLOAD_CUT_TEXT,
    VIDEOS_WAITING_TEXT,
    GalleryItemVM,
    OutcomeRow,
    count_videos,
    outcome_messages,
    rejection_text,
    remove_title,
    upload_text,
)
from .catalog_vm import too_much_at_once, too_much_text
from .creative_provider import default_brand_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

#: The picker's id (`ui.dropzone`) — also the key of the browser's upload controller.
UPLOAD_ID = "gallery_business_media"
#: How often the section re-reads while a video is being prepared, and for how long at
#: most per visit (a tab left open does not poll forever).
WATCH_EVERY_S = 5.0
WATCH_MAX_S = 20 * 60
_TOAST_MS = 4000
_REMOVED = "Listo, lo quitamos de tu Galería."
#: This process. The tab's state outlives the process (it is saved between events): an
#: «uploading», «busy» or «watching» flag written by another process (before a deploy, a
#: restart or a crash) belongs to work that died with it, and `arrive` clears it.
_PROCESS = uuid4().hex


class CatalogGalleryState(rx.State):
    """The section: its tiles, the running upload, the «Quitar» confirmation."""

    items: list[GalleryItemVM] = []
    loaded: bool = False
    #: The business has a brand and a session: the section shows (else CatalogState
    #: already says what is missing).
    available: bool = False
    load_error: str = ""
    #: Active `ingest` jobs (0..3).
    waiting: int = 0
    #: Finished uploads over a minute long («guardamos solo el primero»).
    trimmed_ids: list[str] = []

    uploading: bool = False
    upload_percent: int = 0
    upload_videos: int = 0
    upload_photos: int = 0
    #: What went wrong with the last upload (the service's sentences) / what was skipped.
    upload_error: str = ""
    upload_info: str = ""

    #: «Quitar» asks first: the medium waiting for «Sí, quitar» ("" = no dialog).
    remove_id: str = ""
    busy: bool = False

    _brand_id: str = ""
    #: The section is on screen (between `arrive` and `leave`): `watch` runs only then.
    _on_page: bool = False
    _watching: bool = False
    #: The process that set `uploading` / `busy` / `_watching` (see `_PROCESS`).
    _process: str = ""

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def has_items(self) -> bool:
        return len(self.items) > 0

    @rx.var
    def upload_label(self) -> str:
        return upload_text(
            self.upload_percent, videos=self.upload_videos, photos=self.upload_photos
        )

    @rx.var
    def videos_full(self) -> bool:
        """3 videos are being prepared: the section says so before the owner tries."""
        return self.waiting >= MAX_WAITING_VIDEOS

    @rx.var
    def show_trimmed(self) -> bool:
        return len(self.trimmed_ids) > 0

    @rx.var
    def remove_open(self) -> bool:
        return self._item(self.remove_id) is not None

    @rx.var
    def remove_title_text(self) -> str:
        item = self._item(self.remove_id)
        return remove_title(item.media_type if item is not None else "image")

    def _item(self, media_id: str) -> GalleryItemVM | None:
        if not media_id:
            return None
        return next((i for i in self.items if i.media_id == media_id), None)

    # -- session --------------------------------------------------------------------------

    async def _session_ids(self) -> tuple[UUID, UUID] | None:
        """(tenant, brand), or None: the section then stays hidden (CatalogState shows
        why — no session, no brand yet)."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            cached_brand_id = self._brand_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            return None
        if cached_brand_id:
            return tenant_id, UUID(cached_brand_id)
        brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
        if brand_id is None:
            return None
        async with self:
            self._brand_id = str(brand_id)
        return tenant_id, brand_id

    def _apply(self, snapshot: GallerySnapshot) -> None:
        self.items = list(snapshot.items)
        if snapshot.waiting < MAX_WAITING_VIDEOS and self.upload_error == VIDEOS_WAITING_TEXT:
            self.upload_error = ""  # a video finished: the next one may go up now
        self.waiting = snapshot.waiting
        self.trimmed_ids = list(snapshot.trimmed_ids)
        self.loaded = True
        self.available = True
        self.load_error = ""

    async def _read(self, tenant_id: UUID, brand_id: UUID) -> GallerySnapshot | None:
        """Re-read the section and show it — only if the tab still works for `tenant_id`:
        a read started before «Cambiar de negocio» never paints the other business's
        media into this one (None then, which also stops `watch`)."""
        try:
            snapshot = await asyncio.to_thread(load_gallery, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — DB, Redis or R2 config: never a skeleton forever
            logger.error("gallery read failed: %s", type(exc).__name__)
            async with self:
                self.loaded = True
                self.load_error = SAVE_FAILED_TEXT
            return None
        if await self._current_tenant() != tenant_id:
            return None
        async with self:
            self._apply(snapshot)
        return snapshot

    async def _current_tenant(self) -> UUID | None:
        """The business this tab works for right now (it changes on «Cambiar de
        negocio», which resets this state under any read still running)."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        return tenant_uuid(session_tenant_id) if session_tenant_id else None

    # -- arrive, read, watch --------------------------------------------------------------

    @rx.event
    def arrive(self) -> rx.event.EventSpec:
        """The section mounted (the Galería page opened): read it."""
        self._on_page = True
        stale = self._process != _PROCESS
        if stale:
            # The flags belong to a process that is gone (a deploy, a restart, a crash):
            # its work did not survive. An upload leaves nothing half-saved (the waiting
            # room's file is the reconciler's); say so once.
            cut = self.uploading
            self.upload_error = UPLOAD_CUT_TEXT if cut else ""
            self.upload_info = ""
            self.uploading = False
            self.busy = False
            self._watching = False
            self._process = _PROCESS
        if not self.uploading and not stale:
            # what the last visit said about its upload is old news on a new visit
            self.upload_error = ""
            self.upload_info = ""
        return CatalogGalleryState.load

    @rx.event
    def leave(self) -> None:
        """The section unmounted: `watch` stops at its next turn (unless the owner is
        back by then — the same loop then keeps serving the new visit)."""
        self._on_page = False

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec]:
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.available = False
                self.loaded = True
            return
        snapshot = await self._read(*ids)
        if snapshot is not None and snapshot.busy:
            yield CatalogGalleryState.watch

    @rx.event(background=True)
    async def watch(self) -> None:
        """While a video is being prepared (or cut), re-read every `WATCH_EVERY_S`:
        the tile turns into the video the moment `media-worker` finishes. Stops when
        nothing is pending, when the owner leaves the page, or after `WATCH_MAX_S`."""
        async with self:
            if self._watching:
                return  # one loop per tab; it follows whichever visit is on screen
            self._watching = True
            self._process = _PROCESS
        try:
            ids = await self._session_ids()
            if ids is None:
                return
            for _ in range(int(WATCH_MAX_S / WATCH_EVERY_S)):
                await asyncio.sleep(WATCH_EVERY_S)
                async with self:
                    if not self._on_page:
                        return
                snapshot = await self._read(*ids)
                if snapshot is None or not snapshot.busy:
                    return
        finally:
            async with self:
                self._watching = False

    # -- upload -----------------------------------------------------------------------------

    @rx.event
    def upload_progress(self, progress: dict[str, Any]) -> None:
        """The browser's own count of bytes sent. Never 100 % before the handler is
        done: the last step (saving a photo) still takes a moment."""
        try:
            fraction = float(progress.get("progress", 0) or 0)
        except (TypeError, ValueError):
            return
        if not self.uploading:
            return
        percent = min(99, max(0, int(fraction * 100)))
        if percent != self.upload_percent:
            self.upload_percent = percent

    @rx.event
    def picker_rejected(self, rejected: list[dict[str, Any]]) -> None:
        """Files the picker refused before uploading (over 500 MB, not a photo or a
        video): the owner's sentence, nothing sent."""
        self.upload_info = ""
        self.upload_error = rejection_text(rejected)

    @rx.event(background=True)
    async def receive_upload(
        self, chunks: rx.UploadChunkIterator, picked: list[dict[str, Any]]
    ) -> AsyncIterator[rx.event.EventSpec]:
        """«Agregar fotos o videos». `picked` = [{name, size}] of the chosen files,
        parsed by Reflex before any file byte: the refusal happens here, BEFORE reading a
        chunk (see the module docstring). Then every file is staged as it arrives and
        saved (a photo) or queued for `media-worker` (a video), one outcome each."""
        picked = [row for row in (picked or []) if isinstance(row, dict)]
        videos = count_videos(picked)
        photos = max(0, len(picked) - videos)
        async with self:
            if self.uploading:
                return  # the browser already refuses a second upload of the same picker
            self.upload_error = ""
            self.upload_info = ""
        refusal = ""
        ids = await self._session_ids()
        max_videos = max_files = 0
        if ids is not None:
            tenant_id, brand_id = ids
            try:
                await asyncio.to_thread(check_upload, tenant_id, brand_id, videos)
                max_videos, max_files = await asyncio.to_thread(free_places, tenant_id, brand_id)
            except CatalogError as exc:
                refusal = str(exc.args[0]) if exc.args else GALLERY_FULL_TEXT
            except (SQLAlchemyError, KeyError) as exc:
                logger.error("gallery pre-check failed: %s", type(exc).__name__)
                refusal = SAVE_FAILED_TEXT
            else:
                if picked and len(picked) > max_files:
                    refusal = GALLERY_FULL_TEXT
                elif too_much_at_once(picked):
                    # one drop is one request: Caddy refuses one over 520 MB
                    refusal = too_much_text(picked)
        if refusal or ids is None:
            # Nothing read: Reflex answers 400, and the browser is told to stop sending
            # (one drop is one request; Caddy would refuse one over 520 MB anyway).
            if refusal:
                async with self:
                    self.upload_error = refusal
            yield rx.cancel_upload(UPLOAD_ID)
            return
        tenant_id, brand_id = ids

        async with self:
            self.uploading = True
            self.upload_percent = 0
            self.upload_videos = videos
            self.upload_photos = photos
            self._process = _PROCESS
        staged = []
        try:
            staged = await stage_upload(
                chunks, tenant_id, max_videos=max_videos, max_files=max_files
            )
        except asyncio.CancelledError:
            # The connection was cut or the screen closed: `stage_chunks` already deleted
            # what it wrote. Say so (it shows if the owner is still there) and let go.
            async with self:
                self.uploading = False
                self.upload_error = UPLOAD_CUT_TEXT
            raise
        except Exception as exc:  # noqa: BLE001 — a broken stream is a cut upload
            logger.warning("gallery upload stream failed: %s", type(exc).__name__)
            async with self:
                self.uploading = False
                self.upload_error = UPLOAD_CUT_TEXT
            return

        rows: list[OutcomeRow] = []
        handed = 0  # files given to the service: from then on the staged copy is its own
        error, info = SAVE_FAILED_TEXT, ""
        try:
            for item in staged:
                handed += 1
                try:
                    rows.append(await asyncio.to_thread(add_staged, tenant_id, brand_id, item))
                except Exception as exc:  # noqa: BLE001 — one file never stops the others
                    logger.error("gallery save failed: %s", type(exc).__name__)
                    rows.append(
                        OutcomeRow(
                            item.filename, error_text=SAVE_FAILED_TEXT, is_video=item.is_video
                        )
                    )
            error, info = outcome_messages(rows)
        finally:
            if staged[handed:]:
                await asyncio.to_thread(discard_staged_files, tenant_id, staged[handed:])
            # never «Subiendo…» forever, whatever happened above
            async with self:
                self.uploading = False
                self.upload_percent = 0
                self.upload_error = error
                self.upload_info = info
        snapshot = await self._read(tenant_id, brand_id)
        if info:
            yield rx.toast.success(info, duration=_TOAST_MS)
        if snapshot is not None and snapshot.busy:
            yield CatalogGalleryState.watch

    # -- «Quitar» --------------------------------------------------------------------------

    @rx.event
    def ask_remove(self, media_id: str) -> None:
        """«Quitar» asks «¿Quitar este video de tu Galería?» first."""
        if self.busy:
            return
        item = self._item(str(media_id))
        if item is not None and item.can_remove:
            self.remove_id = item.media_id

    @rx.event
    def set_remove_open(self, value: bool) -> None:
        if not value:
            self.remove_id = ""

    @rx.event
    def confirm_remove(self) -> rx.event.EventSpec | None:
        media_id, self.remove_id = self.remove_id, ""
        if not media_id:
            return None
        return CatalogGalleryState.remove(media_id)

    @rx.event(background=True)
    async def remove(self, media_id: str) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.busy:
                return
            self.busy = True
            self._process = _PROCESS
            self.upload_error = ""
            self.upload_info = ""
        try:
            ids = await self._session_ids()
            if ids is None:
                return
            tenant_id, brand_id = ids
            try:
                await asyncio.to_thread(remove_media, tenant_id, UUID(str(media_id)))
            except CatalogError as exc:  # being cut (CM-3)
                async with self:
                    self.upload_error = str(exc.args[0]) if exc.args else SAVE_FAILED_TEXT
                return
            except (SQLAlchemyError, ValueError) as exc:
                logger.error("gallery remove failed: %s", type(exc).__name__)
                async with self:
                    self.upload_error = SAVE_FAILED_TEXT
                return
            await self._read(tenant_id, brand_id)
            yield rx.toast.success(_REMOVED, duration=_TOAST_MS)
        finally:
            async with self:
                self.busy = False

    @rx.event(background=True)
    async def dismiss(self, job_id: str) -> None:
        """«Quitar» on a video that could not be prepared: there is no file to lose, so
        no question first — the tile goes."""
        await self._dismiss([str(job_id)])

    @rx.event(background=True)
    async def dismiss_trimmed(self) -> None:
        """«Entendido» on «guardamos solo el primero [minuto]»."""
        async with self:
            job_ids = list(self.trimmed_ids)
            self.trimmed_ids = []
        await self._dismiss(job_ids)

    async def _dismiss(self, job_ids: list[str]) -> None:
        async with self:
            if self.busy or not job_ids:
                return
            self.busy = True
            self._process = _PROCESS
        try:
            ids = await self._session_ids()
            if ids is None:
                return
            tenant_id, brand_id = ids
            for job_id in job_ids:
                try:
                    await asyncio.to_thread(dismiss_job, tenant_id, UUID(job_id))
                except (KeyError, ValueError):
                    continue  # already gone, or still active: the next read says which
                except SQLAlchemyError as exc:
                    logger.error("gallery dismiss failed: %s", type(exc).__name__)
                    async with self:
                        self.upload_error = SAVE_FAILED_TEXT
                    break
            await self._read(tenant_id, brand_id)
        finally:
            async with self:
                self.busy = False
