"""Reflex state of «Publicar ahora» (`/publish`): the files, how they go out, their order,
the descriptions, the account — and the run that publishes them.

Spec: `docs/mockups/publicar-varias-imagenes.md`; founder decisions 2026-11-12 (several
files → carousel, one by one or historias; one by one publishes from the last to the
first; only Instagram accounts can be chosen).

How it is organized:

- **One list.** `_order` (file ids, the owner's order), `_files` (id → bytes, backend
  only), `_numbers` (id → «Foto N», kept when a file moves) and `item_captions` (id →
  its own description, «Una por una»). `pending_items` is their display projection,
  rebuilt by `_refresh()` after every change — the gallery, the order step, the mural,
  the descriptions and the progress all render it.
- **Pure rules elsewhere.** Limits, steps, ordering, every sentence: `publish_wizard_vm`.
  Planning the jobs, idempotency keys, the run itself, the error words:
  `publish_engine` (one engine for every mode — before 2026-11-12 a historia had its
  own copy of the whole machine in `StoriesState`).
- **This module only stores.** `publish` plans the jobs and mints the batch key in the
  foreground (its phase check is the double-submit guard: Reflex serializes foreground
  events per session), then `run_batch` (background) drives `publish_engine.run_jobs`
  with the provider as its ports and writes each report into the state.

Uploads: `add_files` must stay a FOREGROUND handler — Reflex forbids
`background=True` on a handler that receives `list[rx.UploadFile]` (`UploadTypeError`).
It buffers the bytes as the owner builds the gallery; nothing is read again at publish.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.publishing import IMAGE_CONTENT_TYPE, MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO

from . import publish_engine as engine
from .auth_state import AuthState
from .publish_engine import JobFile, JobRecord, PublishJob, RunEnd
from .publish_wizard_vm import (
    GALLERY_MAX,
    MODE_CAROUSEL,
    MODE_ONE_BY_ONE,
    MODE_POST,
    STATUS_PILL,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    STATUS_WAITING,
    STEP_WHAT,
    UNDO,
    before_tiles,
    can_advance,
    caption_label,
    continue_label,
    copied_caption_text,
    done_message,
    effective_mode,
    failed_followup,
    failed_headline,
    is_series,
    keep_as_is_text,
    leave_text,
    leftover_text,
    many_for,
    mode_allowed,
    moved,
    moved_text,
    one_by_one_blocked_text,
    partial_message,
    piece_label,
    progress_percent,
    progress_title,
    publish_label,
    removed_text,
    resolve_step,
    review_sentence,
    rows_hint,
    single_for,
    step_ids,
    step_number,
    step_reason,
    step_title,
    wait_text,
)
from .publishing_provider import (
    PendingUpload,
    active_connections,
    carousel_children_status,
    poll_publish,
    start_many_publish,
    start_publish,
)
from .publishing_vm import ChildStatusVM, ConnectionOptionVM, PendingItemVM, PublishAttemptVM
from .tenant import tenant_uuid
from .trending_state import TrendingState

logger = logging.getLogger(__name__)

_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_NO_CONNECTION_SELECTED = "Elige una cuenta de Instagram antes de publicar."
# QUA-103 — `add_files` never guesses a type for a file it cannot resolve.
_UNSUPPORTED_FORMAT = (
    "Ese archivo no se puede publicar en Instagram. Sube una foto o un video tal como salen "
    "de la cámara de tu celular."
)
_BAD_MEDIA = engine.BAD_MEDIA
_MAX_ITEMS = GALLERY_MAX
_TOO_MANY = f"Puedes elegir hasta {_MAX_ITEMS} fotos o videos a la vez."

# The upload widget's id — the page imports it, so the two can never drift apart.
_UPLOAD_ID = "publish_upload"

_RESULT_TOAST_DURATION_MS = 6000
_UNDO_MS = 8000

# `beforeunload` while pieces are still waiting (spec §4.2); the text is the browser's.
_GUARD_ON = (
    "window.__qPubGuard = window.__qPubGuard || function (e) { e.preventDefault(); "
    "e.returnValue = ''; return ''; }; "
    "window.addEventListener('beforeunload', window.__qPubGuard);"
)
_GUARD_OFF = (
    "if (window.__qPubGuard) { window.removeEventListener('beforeunload', window.__qPubGuard); }"
)

_RESTING = ("idle", "success", "failure", "partial")


def _success_toast() -> rx.event.EventSpec:
    """Only the headline: the persistent «listo» carries the rest (N3)."""
    return rx.toast.success("¡Publicado correctamente!", duration=_RESULT_TOAST_DURATION_MS)


def _failure_toast(message: str) -> rx.event.EventSpec:
    """Same text the persistent callout shows, surfaced at once too."""
    return rx.toast.error(
        "No se pudo publicar", description=message, duration=_RESULT_TOAST_DURATION_MS
    )


@dataclass
class _PendingFile:
    """One buffered upload, kept server-side only — never a reactive Var.

    `media_type` is `MEDIA_TYPE_IMAGE`/`MEDIA_TYPE_VIDEO`, resolved once in `add_files`
    (`_resolve_media`) and never re-derived; `content_type` is its canonical value."""

    content_type: str
    data: bytes
    filename: str
    media_type: str


_JPEG_EXTENSIONS = (".jpg", ".jpeg")
_MP4_CONTENT_TYPE = "video/mp4"
_MOV_CONTENT_TYPE = "video/quicktime"
_VIDEO_CONTENT_TYPES = {_MP4_CONTENT_TYPE, _MOV_CONTENT_TYPE}


def _resolve_media(content_type: str | None, filename: str) -> tuple[str, str] | None:
    """`(media_type, canonical_content_type)` for one picked file, or `None` — the caller
    rejects it then; never a fallback to video (QUA-103). The browser's type first, the
    extension as the explicit second signal. Not the security boundary: the staging
    service's magic-byte check is."""
    ct = (content_type or "").strip().lower()
    if ct == IMAGE_CONTENT_TYPE:
        return MEDIA_TYPE_IMAGE, IMAGE_CONTENT_TYPE
    if ct in _VIDEO_CONTENT_TYPES:
        return MEDIA_TYPE_VIDEO, ct
    name = filename.lower()
    if name.endswith(_JPEG_EXTENSIONS):
        return MEDIA_TYPE_IMAGE, IMAGE_CONTENT_TYPE
    if name.endswith(".mp4"):
        return MEDIA_TYPE_VIDEO, _MP4_CONTENT_TYPE
    if name.endswith(".mov"):
        return MEDIA_TYPE_VIDEO, _MOV_CONTENT_TYPE
    return None


class _ProviderPorts:
    """`publish_engine.Ports` over the real provider, for one run of one tenant."""

    def __init__(
        self, state: PublishState, *, tenant_id: UUID, connection_id: UUID, token: str
    ) -> None:
        self._state = state
        self._tenant_id = tenant_id
        self._connection_id = connection_id
        self._token = token

    async def start(self, job: PublishJob, key: str) -> PublishAttemptVM:
        if job.product == engine.PRODUCT_CAROUSEL:
            return await start_many_publish(
                tenant_id=self._tenant_id,
                connection_id=self._connection_id,
                items=[
                    PendingUpload(
                        fileobj=io.BytesIO(f.data),
                        content_type=f.content_type,
                        media_type=f.media_type,
                    )
                    for f in job.files
                ],
                caption=job.caption,
                idempotency_key=key,
            )
        (file,) = job.files
        return await start_publish(
            tenant_id=self._tenant_id,
            connection_id=self._connection_id,
            fileobj=io.BytesIO(file.data),
            content_type=file.content_type,
            media_product_type=job.product,
            caption=job.caption,
            idempotency_key=key,
        )

    async def poll(self, job: PublishJob, attempt_id: str) -> PublishAttemptVM:
        attempt = await poll_publish(tenant_id=self._tenant_id, attempt_id=UUID(attempt_id))
        if job.product == engine.PRODUCT_CAROUSEL and not attempt.settled:
            # READ-ONLY per-child progress; a failure here is one tick without a label.
            try:
                children = await asyncio.to_thread(
                    carousel_children_status,
                    tenant_id=self._tenant_id,
                    attempt_id=UUID(attempt_id),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("carousel_children_status failed: %s", type(exc).__name__)
            else:
                async with self._state:
                    if self._state._run_token == self._token:
                        self._state.carousel_children = children
        async with self._state:
            if self._state._run_token == self._token:
                self._state.attempt = attempt
        return attempt

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class PublishState(rx.State):
    """See the module docstring."""

    connections: list[ConnectionOptionVM] = []
    is_loading_connections: bool = False
    load_error: str = ""
    connections_loaded: bool = False
    last_drop_rejected: bool = False

    selected_connection_id: str = ""
    #: The one description of a publication or a carousel.
    caption: str = ""
    #: «Una por una»: each file's own description, by file id.
    item_captions: dict[str, str] = {}

    #: The owner's choice for one file (`post`/`story`) and for several
    #: (`carousel`/`one_by_one`/`stories`) — `mode` picks the one that applies.
    kind_single: str = MODE_POST
    kind_many: str = MODE_CAROUSEL

    #: The assistant's current step (`publish_wizard_vm.STEP_*`); `PublishHubState` moves it.
    step: str = STEP_WHAT

    pending_items: list[PendingItemVM] = []
    #: Read by a screen reader after each move (`aria-live`).
    announce: str = ""
    #: The file lifted from the keyboard (`sort_handle`).
    lifted: str = ""

    # -- the run --
    #: idle | running | success | failure | partial
    phase: str = "idle"
    error: str = ""
    run_mode: str = ""
    run_total: int = 0
    run_done: int = 0
    stopped: bool = False
    needs_reconnect: bool = False
    #: The list position (0-based) of the piece that did not go out, or -1.
    failed_position: int = -1
    run_unknown: bool = False
    attempt: PublishAttemptVM | None = None
    run_waiting: bool = False
    carousel_children: list[ChildStatusVM] = []

    # -- backend only --
    _order: list[str] = []
    _files: dict[str, _PendingFile] = {}
    _numbers: dict[str, int] = {}
    _many_chosen: bool = False
    _jobs: list[PublishJob] = []
    _records: list[JobRecord] = []
    _run_order: list[str] = []
    _batch_key: str = ""
    _run_token: str = ""
    _stop_requested: bool = False
    _active_tenant_id: str = ""
    _poll_started_monotonic: float = 0.0
    _dragging: str = ""
    _lift_before: list[str] = []
    _undo_remove: dict[str, Any] = {}
    _undo_captions: dict[str, str] = {}

    # -- derived ----------------------------------------------------------------------

    @rx.var
    def file_count(self) -> int:
        return len(self.pending_items)

    @rx.var
    def mode(self) -> str:
        """The mode in force — the run's own while one exists, else the owner's choice."""
        if self.phase in ("running", "failure", "partial") and self.run_mode:
            return self.run_mode
        return effective_mode(self.kind_single, self.kind_many, len(self.pending_items))

    @rx.var
    def selectable_count(self) -> int:
        return sum(1 for c in self.connections if c.selectable)

    @rx.var
    def steps(self) -> list[str]:
        return step_ids(len(self.pending_items), self.selectable_count)

    @rx.var
    def step_id(self) -> str:
        """The step on screen — `step` when it still applies to this selection."""
        return resolve_step(self.step, self.steps)

    @rx.var
    def step_number(self) -> int:
        return step_number(self.step, self.steps)

    @rx.var
    def step_total(self) -> int:
        return len(self.steps)

    @rx.var
    def step_title(self) -> str:
        return step_title(self.step_id, file_count=len(self.pending_items), mode=self.mode)

    @rx.var
    def can_go(self) -> bool:
        return can_advance(
            self.step_id,
            file_count=len(self.pending_items),
            mode=self.mode,
            connection_id=self.selected_connection_id,
        )

    @rx.var
    def step_reason(self) -> str:
        return step_reason(
            self.step_id,
            file_count=len(self.pending_items),
            mode=self.mode,
            connection_id=self.selected_connection_id,
        )

    @rx.var
    def has_instagram(self) -> bool:
        return self.selectable_count > 0

    @rx.var
    def can_edit_gallery(self) -> bool:
        """Whether the list may change now: not while a run goes on, and not while one
        waits to be continued (changing it then would break what is already out)."""
        if self.phase == "running":
            return False
        return not (self.phase == "failure" and self.resumable)

    @rx.var
    def busy(self) -> bool:
        return self.phase == "running"

    @rx.var
    def remaining_slots(self) -> int:
        return max(0, _MAX_ITEMS - len(self.pending_items))

    @rx.var
    def one_by_one_reason(self) -> str:
        return one_by_one_blocked_text(len(self.pending_items))

    @rx.var
    def rows_hint(self) -> str:
        return rows_hint(len(self.pending_items)) if self.mode == MODE_ONE_BY_ONE else ""

    @rx.var
    def before_slots(self) -> list[int]:
        return list(range(before_tiles(len(self.pending_items))))

    @rx.var
    def pending_filenames(self) -> list[str]:
        return [item.filename for item in self.pending_items]

    def _selected_connection(self) -> ConnectionOptionVM | None:
        for conn in self.connections:
            if conn.id == self.selected_connection_id and conn.selectable:
                return conn
        return None

    @rx.var
    def selected_platform(self) -> str:
        conn = self._selected_connection()
        return conn.platform if conn is not None else ""

    @rx.var
    def review_text(self) -> str:
        conn = self._selected_connection()
        if conn is None:
            return ""
        return review_sentence(
            self.mode,
            username=conn.external_username,
            kinds=[item.kind for item in self.pending_items],
        )

    @rx.var
    def can_publish(self) -> bool:
        return (
            self._selected_connection() is not None
            and mode_allowed(self.mode, len(self.pending_items))
            and self.phase in _RESTING
        )

    @rx.var
    def resumable(self) -> bool:
        """«Continuar» applies: the run stopped with something left, and either some of
        it is out already, its last outcome is unknown, or the owner left mid-way."""
        if self.phase != "failure" or not self._records:
            return False
        if engine.first_unpublished(self._records) is None:
            return False
        return self.stopped or self.run_unknown or engine.published_count(self._records) > 0

    @rx.var
    def is_series_run(self) -> bool:
        return is_series(self.run_mode) and self.run_total > 1

    @rx.var
    def primary_label(self) -> str:
        """The review's solid button: publish — or continue a run that stopped."""
        if self.resumable and self.failed_position >= 0 and self.is_series_run:
            item = self._item_at(self.failed_position)
            if item is not None:
                return continue_label(self.run_mode, item.kind, item.number)
        if self.resumable and self.stopped and self.is_series_run:
            return "Continuar"
        return publish_label(self.mode, len(self.pending_items))

    @rx.var
    def progress_title(self) -> str:
        return progress_title(self.run_done, self.run_total)

    @rx.var
    def progress_value(self) -> int:
        return progress_percent(self.run_done, self.run_total)

    @rx.var
    def done_text(self) -> str:
        return done_message(self.run_mode or self.mode, self.run_total or 1)

    @rx.var
    def partial_text(self) -> str:
        return partial_message(self.run_done, self.run_total)

    @rx.var
    def failed_title(self) -> str:
        item = self._item_at(self.failed_position)
        if item is None:
            return ""
        return failed_headline(self.run_done, self.run_total, item.kind, item.number)

    @rx.var
    def failed_next(self) -> str:
        item = self._item_at(self.failed_position)
        if item is None:
            return ""
        return failed_followup(self.run_mode, item.kind, item.number)

    @rx.var
    def remaining_count(self) -> int:
        return max(0, self.run_total - self.run_done)

    @rx.var
    def leftover_text(self) -> str:
        """«Te quedaron {r} sin publicar…» above step 1 (spec §4.2)."""
        if not (self.resumable and self.is_series_run):
            return ""
        return leftover_text(self.run_mode, self.remaining_count)

    @rx.var
    def leave_text(self) -> str:
        return leave_text(max(0, self.run_total - self.run_done - 1))

    @rx.var
    def keep_as_is_text(self) -> str:
        return keep_as_is_text(self.run_done, self.run_total)

    @rx.var
    def carousel_stage_label(self) -> str:
        """Which carousel child is being worked — only what the backend proves."""
        total = len(self.carousel_children)
        if total == 0 or self.phase != "running":
            return ""
        for child in self.carousel_children:
            if child.status in ("pending", "uploading"):
                return f"Subiendo archivo {child.position + 1} de {total}"
            if child.status == "processing":
                return f"Preparando archivo {child.position + 1} de {total} en Instagram"
        if self.attempt is not None and self.attempt.awaiting_confirmation:
            return "Confirmando publicación"
        return "Creando carrusel"

    @rx.var
    def wait_text(self) -> str:
        return wait_text(self.mode)

    @rx.var
    def elapsed_label(self) -> str:
        """`mm:ss` of the current wait, refreshed with each poll."""
        if not self.run_waiting or self._poll_started_monotonic <= 0:
            return ""
        elapsed = max(0, int(time.monotonic() - self._poll_started_monotonic))
        minutes, seconds = divmod(elapsed, 60)
        return f"{minutes:02d}:{seconds:02d}"

    # -- the list -----------------------------------------------------------------------

    def _item_at(self, position: int) -> PendingItemVM | None:
        if 0 <= position < len(self.pending_items):
            return self.pending_items[position]
        return None

    def _statuses(self) -> dict[str, str]:
        if not self._jobs or not self._run_order:
            return {}
        by_position = engine.piece_statuses(self._jobs, self._records, len(self._run_order))
        return dict(zip(self._run_order, by_position, strict=False))

    def _refresh(self) -> None:
        """Rebuild `pending_items` from the source lists (and the run, if any)."""
        statuses = self._statuses()
        total = len(self._order)
        items: list[PendingItemVM] = []
        for position, file_id in enumerate(self._order, start=1):
            file = self._files.get(file_id)
            if file is None:
                continue
            kind = "image" if file.media_type == MEDIA_TYPE_IMAGE else "video"
            number = self._numbers.get(file_id, position)
            label = piece_label(kind, number)
            status = statuses.get(file_id, STATUS_WAITING)
            pill, tone = STATUS_PILL.get(status, STATUS_PILL[STATUS_WAITING])
            items.append(
                PendingItemVM(
                    filename=file.filename,
                    kind=kind,
                    id=file_id,
                    number=number,
                    label=label,
                    position=position,
                    total=total,
                    status=status,
                    status_label=pill,
                    status_tone=tone,
                    handle_label=f"Mover {label}, posición {position} de {total}",
                    more_label=f"Más opciones de {label}",
                    caption_label=caption_label(kind, number),
                )
            )
        self.pending_items = items

    def _clear_run(self) -> None:
        self._jobs = []
        self._records = []
        self._run_order = []
        self._batch_key = ""
        self._run_token = ""
        self._stop_requested = False
        self.run_mode = ""
        self.run_total = 0
        self.run_done = 0
        self.stopped = False
        self.needs_reconnect = False
        self.failed_position = -1
        self.run_unknown = False
        self.attempt = None
        self.run_waiting = False
        self.carousel_children = []
        self._poll_started_monotonic = 0.0

    def _start_editing(self) -> bool:
        """Gate for every change to the list: False while it may not change. A finished
        or failed (non-resumable) run is forgotten — the next «Publicar» is a new one."""
        if not self.can_edit_gallery:
            return False
        if self.phase in ("failure", "partial", "success"):
            self._clear_run()
            self.phase = "idle"
            self.error = ""
        return True

    def _after_count_change(self, before: int) -> None:
        """Keep the mode coherent when the count crosses 1 ↔ 2 (spec §5)."""
        after = len(self._order)
        if before >= 2 and after == 1:
            self.kind_single = single_for(effective_mode(self.kind_single, self.kind_many, before))
        if before <= 1 and after >= 2 and not self._many_chosen:
            self.kind_many = many_for(self.kind_single)
        if self.kind_many == MODE_ONE_BY_ONE and not mode_allowed(MODE_ONE_BY_ONE, after):
            self.kind_many = MODE_CAROUSEL
        self.step = resolve_step(self.step, step_ids(after, self.selectable_count))

    # -- accounts --------------------------------------------------------------------------

    @rx.event(background=True)
    async def load_active_connections(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """Load the accounts «Publicar» offers for the session tenant."""
        async with self:
            self.is_loading_connections = True
            self.load_error = ""
            self.connections_loaded = False
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            async with self:
                self.is_loading_connections = False
                self.load_error = engine.NO_TENANT
            return
        try:
            options = await asyncio.to_thread(active_connections, tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("active_connections failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_connections = False
                self.load_error = _NO_CONNECTIONS
            return
        async with self:
            self.connections = options
            self.is_loading_connections = False
            self.connections_loaded = True
            if self.selected_connection_id and self._selected_connection() is None:
                self.selected_connection_id = ""
            preselected = self._preselect_single_connection()
            self.step = resolve_step(self.step, self.steps)
        if preselected:
            yield TrendingState.set_audio_connection(preselected)

    def _preselect_single_connection(self) -> str:
        """With exactly one Instagram account, it is chosen (step 4 is skipped)."""
        selectable = [c for c in self.connections if c.selectable]
        if self.selected_connection_id or len(selectable) != 1:
            return ""
        self.selected_connection_id = selectable[0].id
        return self.selected_connection_id

    @rx.event
    def select_connection(self, connection_id: str) -> rx.event.EventSpec | None:
        """Only an Instagram account can be chosen; anything else is ignored."""
        if self.phase == "running":
            return None
        if not any(c.id == connection_id and c.selectable for c in self.connections):
            return None
        self.selected_connection_id = connection_id
        return TrendingState.set_audio_connection(connection_id)

    # -- files ------------------------------------------------------------------------------

    @rx.event
    async def add_files(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Buffer newly picked files at the END of the list (spec §5: the order already
        made is kept). Rejected as one batch over the cap or for an unknown type."""
        if not files or not self._start_editing():
            return None
        if len(self._order) + len(files) > _MAX_ITEMS:
            return _failure_toast(_TOO_MANY)
        new: list[tuple[str, _PendingFile]] = []
        for upload in files:
            filename = (
                getattr(upload, "filename", None) or getattr(upload, "name", None) or "archivo"
            )
            resolved = _resolve_media(getattr(upload, "content_type", None), filename)
            if resolved is None:
                return _failure_toast(_UNSUPPORTED_FORMAT)
            media_type, content_type = resolved
            try:
                data = await upload.read()
            except Exception:  # noqa: BLE001
                return _failure_toast(_BAD_MEDIA)
            new.append(
                (
                    uuid4().hex[:12],
                    _PendingFile(
                        content_type=content_type,
                        data=data,
                        filename=filename,
                        media_type=media_type,
                    ),
                )
            )
        before = len(self._order)
        files_map = dict(self._files)
        numbers = dict(self._numbers)
        order = list(self._order)
        for file_id, pending in new:
            order.append(file_id)
            files_map[file_id] = pending
            numbers[file_id] = len(order)
        self._order, self._files, self._numbers = order, files_map, numbers
        self.item_captions = {**self.item_captions, **{fid: "" for fid, _ in new}}
        self.last_drop_rejected = False
        self._undo_remove = {}
        self._after_count_change(before)
        self._refresh()
        return None

    @rx.event
    def mark_drop_rejected(self, _rejected: list[dict] | None = None) -> None:
        """The dropzone refused a pick; step 1 keeps the reason on screen (N3)."""
        self.last_drop_rejected = True

    @rx.event
    def remove_item(self, file_id: str, with_undo: bool = False) -> rx.event.EventSpec | None:
        """«✕» (step 1) or «⋯ › Quitar» (the order step, with «Deshacer»). Takes the file
        out of the publication only — nothing is deleted from the phone."""
        if file_id not in self._order or not self._start_editing():
            return None
        index = self._order.index(file_id)
        number = self._numbers.get(file_id, index + 1)
        removed = self._files[file_id]
        self._undo_remove = {
            "order": list(self._order),
            "numbers": dict(self._numbers),
            "file_id": file_id,
            "file": removed,
            "caption": self.item_captions.get(file_id, ""),
            "kind_single": self.kind_single,
            "kind_many": self.kind_many,
        }
        before = len(self._order)
        self._order = [f for f in self._order if f != file_id]
        self._files = {k: v for k, v in self._files.items() if k != file_id}
        self._numbers = {
            k: (n - 1 if n > number else n) for k, n in self._numbers.items() if k != file_id
        }
        self.item_captions = {k: v for k, v in self.item_captions.items() if k != file_id}
        self.lifted = ""
        self._after_count_change(before)
        self._refresh()
        if not with_undo:
            return None
        kind = "image" if removed.media_type == MEDIA_TYPE_IMAGE else "video"
        text = removed_text(kind, number)
        self.announce = text
        return rx.toast.success(
            text,
            duration=_UNDO_MS,
            action={"label": UNDO, "on_click": PublishState.undo_remove},
        )

    @rx.event
    def undo_remove(self) -> None:
        """«Deshacer» after «Quitar»: the file comes back where it was."""
        snapshot, self._undo_remove = self._undo_remove, {}
        if not snapshot or not self._start_editing():
            return
        if len(self._order) + 1 > _MAX_ITEMS or snapshot["file_id"] in self._order:
            return
        if set(snapshot["order"]) - {snapshot["file_id"]} != set(self._order):
            return  # the list changed since: nothing safe to restore
        self._order = list(snapshot["order"])
        self._files = {**self._files, snapshot["file_id"]: snapshot["file"]}
        self._numbers = dict(snapshot["numbers"])
        self.item_captions = {**self.item_captions, snapshot["file_id"]: snapshot["caption"]}
        self.kind_single = snapshot["kind_single"]
        self.kind_many = snapshot["kind_many"]
        self._refresh()

    # -- how they go out -------------------------------------------------------------------

    def choose_kind(self, kind: str) -> bool:
        """Step 2's choice. A plain method (`PublishHubState.select_kind` calls it, and
        also keeps the address in step). False when it does not fit or cannot change."""
        count = len(self._order)
        if not mode_allowed(kind, max(count, 1)) or not self._start_editing():
            return False
        if count <= 1:
            self.kind_single = kind
        else:
            self.kind_many = kind
            self._many_chosen = True
        return True

    # -- the order -------------------------------------------------------------------------

    @rx.event
    def place(self, file_id: str, to: int) -> None:
        """«Primero / Subir uno / Bajar uno / Último» and a drop."""
        if file_id not in self._order or not self._start_editing():
            return
        index = self._order.index(file_id)
        to = max(0, min(len(self._order) - 1, int(to)))
        if to == index:
            return
        self._order = moved(self._order, index, to)
        self.lifted = ""
        self._refresh()
        self.announce = moved_text(self.pending_items[to].label, to + 1, len(self._order))

    @rx.event
    def pick(self, file_id: str) -> None:
        """`assets/rank-drag.js` lifted this one (`dragstart`)."""
        self._dragging = file_id

    @rx.event
    def drop(self, target_id: str) -> None:
        """…and released it over `target_id` (`drop`)."""
        source, self._dragging = self._dragging, ""
        if not source or source == target_id or target_id not in self._order:
            return
        self.place(source, self._order.index(target_id))

    @rx.event
    def handle_key(self, file_id: str, key: str) -> None:
        """`sort_handle`: Espacio lifts and drops, ↑/↓ (and ←/→ in the mural, reading
        order) move while lifted, Escape puts it back."""
        if file_id not in self._order or not self.can_edit_gallery:
            return
        index = self._order.index(file_id)
        total = len(self._order)
        label = self.pending_items[index].label if index < len(self.pending_items) else ""
        if key in (" ", "Spacebar", "Enter"):
            if self.lifted != file_id:
                self.lifted = file_id
                self._lift_before = list(self._order)
                self.announce = (
                    f"Levantaste {label}, posición {index + 1} de {total}. Muévela con las "
                    "flechas y suéltala con Espacio. Escape la deja donde estaba."
                )
                return
            self.lifted = ""
            self.announce = moved_text(label, index + 1, total)
            return
        if self.lifted != file_id:
            return
        if key == "Escape":
            self._order = list(self._lift_before) or self._order
            self.lifted = ""
            self._refresh()
            self.announce = f"Listo, no cambiamos nada: {label} volvió a su lugar."
            return
        step = {"ArrowUp": -1, "ArrowLeft": -1, "ArrowDown": 1, "ArrowRight": 1}.get(key)
        if step is None or not 0 <= index + step < total or not self._start_editing():
            return
        self._order = moved(self._order, index, index + step)
        self._refresh()
        self.announce = moved_text(label, index + step + 1, total)

    # -- descriptions --------------------------------------------------------------------

    @rx.event
    def set_caption(self, value: str) -> None:
        if self.phase != "running":
            self.caption = value

    @rx.event
    def set_item_caption(self, file_id: str, value: str) -> None:
        if self.phase != "running" and file_id in self._order:
            self.item_captions = {**self.item_captions, file_id: value}

    @rx.var
    def can_copy_caption(self) -> bool:
        """«Usar este texto en las demás» is off while the first description is empty."""
        if self.phase == "running" or len(self.pending_items) < 2:
            return False
        first = self.pending_items[0].id
        return bool(self.item_captions.get(first, "").strip())

    @rx.event
    def copy_first_caption(self) -> rx.event.EventSpec | None:
        """«Usar este texto en las demás»: only the empty ones get it (spec §3)."""
        if self.phase == "running" or len(self._order) < 2:
            return None
        text = self.item_captions.get(self._order[0], "")
        if not text.strip():
            return None
        empty = [f for f in self._order[1:] if not self.item_captions.get(f, "").strip()]
        if not empty:
            return None
        self._undo_captions = dict(self.item_captions)
        self.item_captions = {**self.item_captions, **dict.fromkeys(empty, text)}
        return rx.toast.success(
            copied_caption_text(len(empty)),
            duration=_UNDO_MS,
            action={"label": UNDO, "on_click": PublishState.undo_copy_caption},
        )

    @rx.event
    def undo_copy_caption(self) -> None:
        before, self._undo_captions = self._undo_captions, {}
        if before and self.phase != "running":
            self.item_captions = {k: v for k, v in before.items() if k in self._order}

    # -- publishing --------------------------------------------------------------------------

    @rx.event
    def publish(self) -> list[rx.event.EventSpec] | rx.event.EventSpec | None:
        """Plan the jobs and start a NEW run (a new batch key). The phase check is the
        server-side double-submit guard; a run waiting for «Continuar» is never replaced
        by a new one here (that could publish twice)."""
        if self.phase == "running" or (self.phase == "failure" and self.resumable):
            return None
        conn = self._selected_connection()
        if conn is None:
            self.error = _NO_CONNECTION_SELECTED
            return _failure_toast(_NO_CONNECTION_SELECTED)
        mode = self.mode
        if not self._order or not mode_allowed(mode, len(self._order)):
            return None
        files = [self._files[f] for f in self._order]
        captions = (
            [self.item_captions.get(f, "") for f in self._order]
            if mode == MODE_ONE_BY_ONE
            else [self.caption]
        )
        self._jobs = engine.plan_jobs(
            mode,
            [JobFile(f.content_type, f.data, f.media_type) for f in files],
            captions,
        )
        self._records = [JobRecord() for _ in self._jobs]
        self._run_order = list(self._order)
        self._batch_key = uuid4().hex
        self.run_mode = mode
        self.run_total = len(self._jobs)
        return self._begin()

    @rx.event
    def continue_run(self) -> list[rx.event.EventSpec] | None:
        """«Continuar»: resume from the first piece not yet out, same batch. A failed
        piece gets a new key; one whose outcome is unknown keeps its own (see
        `publish_engine.key_for`). Never while the account must be reconnected."""
        if not self.resumable or self.needs_reconnect:
            return None
        if not engine.can_resume(self._records):
            return None
        return self._begin()

    def _begin(self) -> list[rx.event.EventSpec]:
        self._run_token = uuid4().hex
        self._stop_requested = False
        self.phase = "running"
        self.error = ""
        self.stopped = False
        self.needs_reconnect = False
        self.failed_position = -1
        self.run_unknown = False
        self.run_waiting = False
        self.attempt = None
        self.carousel_children = []
        self.run_done = engine.published_count(self._records)
        self._refresh()
        return [rx.call_script(_GUARD_ON), PublishState.run_batch]

    @rx.event
    def request_stop(self) -> None:
        """«Salir igual»: the piece going out now finishes; the next ones do not start."""
        if self.phase == "running":
            self._stop_requested = True

    def _apply_record(self, index: int, record: JobRecord) -> None:
        records = list(self._records)
        if not 0 <= index < len(records):
            return
        records[index] = record
        self._records = records
        self.run_done = engine.published_count(records)
        waiting = record.status == STATUS_RUNNING and record.polling
        if waiting and not self.run_waiting:
            self._poll_started_monotonic = time.monotonic()
        self.run_waiting = waiting
        if record.status == STATUS_RUNNING and not record.attempt_id:
            self.carousel_children = []
        self._refresh()

    @rx.event(background=True)
    async def run_batch(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """Drive `publish_engine.run_jobs` and write each report into the state."""
        async with self:
            if self.phase != "running":
                return
            token = self._run_token
            jobs = list(self._jobs)
            records = list(self._records)
            batch_key = self._batch_key
            connection_id = self.selected_connection_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            async with self:
                if self._run_token == token:
                    self.phase = "failure"
                    self.error = engine.NO_TENANT
            yield rx.call_script(_GUARD_OFF)
            yield _failure_toast(engine.NO_TENANT)
            return
        async with self:
            self._active_tenant_id = str(tenant_id)

        async def report(index: int, record: JobRecord) -> bool:
            async with self:
                if self._run_token != token:
                    return False
                self._apply_record(index, record)
                return not self._stop_requested

        ports = _ProviderPorts(
            self, tenant_id=tenant_id, connection_id=UUID(connection_id), token=token
        )
        end = await engine.run_jobs(jobs, records, batch_key=batch_key, ports=ports, report=report)

        async with self:
            if self._run_token != token:
                return
            toast = self._finish(end)
        yield rx.call_script(_GUARD_OFF)
        if toast is not None:
            yield toast
        if end.kind == "done":
            yield TrendingState.release_audio_connection

    def _finish(self, end: RunEnd) -> rx.event.EventSpec | None:
        """Settle the screen once the run stopped; returns the toast to show."""
        self.run_waiting = False
        self.carousel_children = []
        if end.kind == "done":
            self.phase = "success"
            self.run_done = self.run_total
            # bytes are in R2 now; the «listo» needs none of them
            self._files = {}
            self._jobs = []
            self.selected_connection_id = ""
            return _success_toast()
        self.phase = "failure"
        if end.kind == "stopped":
            self.stopped = True
            return None
        record = self._records[end.at] if end.at is not None else JobRecord()
        self.error = record.reason or engine.START_FAILED
        self.needs_reconnect = record.needs_reconnect
        self.run_unknown = record.status == STATUS_UNKNOWN
        if end.at is not None and self._jobs:
            first_piece = self._jobs[end.at].pieces[0]
            self.failed_position = first_piece if is_series(self.run_mode) else -1
        return _failure_toast(self.error)

    @rx.event
    def keep_as_is(self) -> rx.event.EventSpec | None:
        """«Dejar así»: the partial end (spec §4.4) — what went out stays, the rest is
        dropped."""
        if self.phase != "failure" or not self.resumable:
            return None
        self.phase = "partial"
        self._files = {}
        self._jobs = []
        return rx.call_script(_GUARD_OFF)

    @rx.event
    def discard_leftover(self) -> None:
        """«Descartar» on «Te quedaron…»: forget the unfinished run and its files."""
        if self.phase == "running":
            return
        self._reset()

    @rx.event
    def reset_form(self) -> None:
        """«Publicar otra»: an empty step 1. A no-op while publishing."""
        if self.phase == "running":
            return
        self._reset()

    def _reset(self) -> None:
        self._clear_run()
        self._order = []
        self._files = {}
        self._numbers = {}
        self.item_captions = {}
        self.caption = ""
        self.pending_items = []
        self.phase = "idle"
        self.error = ""
        self.lifted = ""
        self.announce = ""
        self.step = STEP_WHAT
        self._many_chosen = False
        self.kind_many = MODE_CAROUSEL
        self._undo_remove = {}
        self._undo_captions = {}
        self._preselect_single_connection()

    # -- «Abrir en Instagram» (historia, one file) ----------------------------------------

    @rx.event
    def handle_share_result(self, result: str) -> rx.event.EventSpec | None:
        """Outcome of the phone share-sheet handoff (`stories_page.py`). Never touches
        Meta's Graph API and never changes the run."""
        if result == "shared":
            return rx.toast.success(
                "Archivo compartido. Termina en Instagram: elige Historia, "
                "agrega la música y publica ahí."
            )
        if result == "cancelled":
            return None
        if result == "desktop":
            return rx.toast.error(
                "Esta opción es para el celular: abre Qualify desde tu teléfono "
                "para que Instagram reciba el video directamente."
            )
        if result == "insecure":
            return rx.toast.error("Esta página necesita HTTPS para poder compartir el video.")
        if result == "unsupported":
            return rx.toast.error(
                "Este navegador no permite compartir el video directamente. "
                "Prueba desde Chrome (Android) o Safari (iPhone)."
            )
        if result == "no_file":
            return rx.toast.error(
                "Vuelve al paso 1 y elige otra vez la foto o el video para abrirlo en Instagram."
            )
        if result == "cannot_share_file":
            return rx.toast.error(
                "Este navegador no puede compartir este archivo (formato o tamaño no permitido)."
            )
        return rx.toast.error("No se pudo compartir el video.")


__all__ = ["PublishState", "_PendingFile", "_resolve_media"]
