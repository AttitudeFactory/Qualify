"""Reflex state for the publish screen (A5 vertical slice).

Reads the active tenant from `AuthState.session_tenant_id` (via `self.get_state`)
rather than duplicating the dev tenant selector — one source of truth for "which tenant"
(decision 7 of the approved plan).

**Deviation from the approved plan, discovered while building it (not a scope change):**
the plan called for a single `publish` handler, `@rx.event(background=True)`, receiving
`files: list[rx.UploadFile]` directly. The Reflex version installed here forbids that
combination outright — `resolve_upload_handler_param` raises `UploadTypeError` for any
upload-receiving handler marked `background=True` (verified by constructing the page:
`.venv/Lib/site-packages/reflex_base/event/__init__.py:330-340`). So no upload-receiving
handler in this module is ever `background=True`: `publish_background` (background=True,
no upload parameter) does the actual staging/starting work.

**Gallery redesign (QUA-99 UX follow-up)** moved WHICH handler receives the upload:
originally `publish` itself read the bytes, once, at the final click. It now reads
nothing — `add_files` (still FOREGROUND, for the same `UploadTypeError` reason) reads
bytes incrementally, on every interaction with the dropzone's `+` tile, buffering them
into `_pending_files`/`pending_items` as the gallery is built. `publish` only validates
that buffer and hands off to `publish_background`, unchanged in spirit from before.

Neither `publish` nor `publish_background`/`poll_attempt` ever wrap a call in
`asyncio.to_thread`: the seam they call (`publishing_provider.start_publish`/
`poll_publish`) is already `async def`, and the one blocking call anywhere in this chain
(`MediaStagingService.stage_media`, boto3 against R2) is wrapped inside
`qualify_api.publishing.composition` itself, off the event loop there — unlike
`ConnectionsState`, whose services are synchronous and therefore ARE wrapped in
`to_thread` here.

Without R2 configured (`QUALIFY_R2_*` unset — expected right now, Herwin has not handed
the credentials over yet), the first publish attempt fails with `R2ConfigurationError`.
That is shown as a readable Spanish error, not a crash — same posture
`connections_state.py` already uses for `RedisError`/`SQLAlchemyError`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.publishing import (
    IMAGE_CONTENT_TYPE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_VIDEO,
)
from qualify_api.publishing.service import TooManyItems, UnknownAttempt, UnknownConnection
from qualify_api.publishing.staging import UnsupportedImageFormat
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectSizeExceeded, UnsizedStream
from qualify_shared.objects.keys import TenantPrefixViolation

from .auth_state import AuthState
from .publish_wizard_vm import FLOW_POSTS, FLOW_STORIES, review_sentence
from .publishing_provider import (
    PendingUpload,
    PublishAttemptVM,
    active_connections,
    carousel_children_status,
    poll_publish,
    start_many_publish,
    start_publish,
)
from .publishing_vm import ChildStatusVM, ConnectionOptionVM, PendingItemVM
from .tenant import tenant_uuid
from .trending_state import TrendingState

logger = logging.getLogger(__name__)

_NO_TENANT = "No encontramos tu negocio en esta sesión. Cierra sesión y vuelve a entrar."
_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_NO_CONNECTION_SELECTED = "Elige una cuenta conectada antes de publicar."
_NOT_CONFIGURED = (
    "No podemos subir archivos en este momento. Inténtalo en unos minutos; si sigue, escríbenos."
)
_TOO_LARGE = "El video supera el tamaño máximo permitido (300 MB)."
_IMAGE_TOO_LARGE = "La imagen supera el tamaño máximo permitido (8 MB)."
_BAD_MEDIA = "No se pudo leer el archivo subido. Intenta con otro archivo."
# QUA-103 — `add_files` never guesses a type for a file it cannot resolve (no fallback to
# VIDEO/REELS); this is what a rejection reads as instead.
_UNSUPPORTED_FORMAT = (
    "Ese archivo no se puede publicar en Instagram. Sube una foto o un video tal como salen "
    "de la cámara de tu celular."
)
# QUA-103 — the ONE real content check (magic bytes), server-side, for the case a file
# passed the extension/content_type check above but its actual bytes are not a JPEG.
_UNSUPPORTED_IMAGE_FORMAT = (
    "Esta foto no se puede usar tal cual. Desde tu celular, compártela como “JPG” o "
    "haz una captura de pantalla y súbela."
)
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la lista e intenta de nuevo."
_START_FAILED = "No se pudo iniciar la publicación. Vuelve a intentarlo en un momento."
_POLL_FAILED = (
    "No sabemos todavía si se publicó. Revisa tu Instagram en unos minutos antes de "
    "volver a intentarlo, para no publicarlo dos veces."
)
# QUA-99 (6/6): Meta caps a carousel at 10 items (client.py's MAX_CAROUSEL_ITEMS,
# service.py). Checked HERE too, before a single byte is read off the upload — the
# dropzone's own `max_files=10` (publishing_page.py) is the client-side nicety on top of
# this, same "server-side guard is the real invariant" posture the double-submit check
# below already documents.
_MAX_ITEMS = 10
_TOO_MANY = f"Puedes publicar hasta {_MAX_ITEMS} archivos a la vez."
# QUA-99 UX follow-up: shown next to the polling status so a real, multi-minute wait for
# Meta reads as "working", not "frozen" — the audit of attempt 94e09568-... (2026-09-10)
# measured 6 min 8 s end to end for a 2-video carousel with zero errors/retries, entirely
# explained by Meta's own per-container async processing plus this pipeline's 60 s poll
# cadence (client.py's CONTAINER_POLL_INTERVAL_SECONDS) — nothing to fix in the backend,
# only to say out loud in the UI.
_WAIT_EXPLANATION = "Instagram está preparando tu publicación. Puede tardar unos minutos."
# Client-side safety net only — the SERVER already settles an attempt as 'failed' once
# CONTAINER_POLL_CEILING_SECONDS (300 s) elapses, at roughly one poll per
# CONTAINER_POLL_INTERVAL_SECONDS (60 s). This is just the belt on top of that suspenders,
# in case a future response ever advertises an unexpectedly short interval.
_MAX_POLLS = 30

# The upload widget's id — lives here (not in publishing_page.py) because `add_files`
# above is bound to it (`on_drop=PublishState.add_files`, wired in publishing_page.py).
# The page imports this constant rather than keeping its own copy, so the two can never
# drift apart.
_UPLOAD_ID = "publish_upload"

# QUA-98: both outcomes now get a toast — success AND failure — on top of (never instead
# of) the existing persistent `error` callout `_status_block` still renders in
# publishing_page.py. `inbox_state.py`'s convention (docs/design-system.md §5.4:
# "confirmaciones transitorias → rx.toast") only toasts success and leaves failure as a
# plain callout; this screen goes one step further at the operator's request — a failure
# gets an immediate toast too, precisely because the callout alone can be missed if the
# operator has already looked away from the form. The callout is NOT removed: it is the
# one place the full error text stays readable after the toast dismisses itself.
_RESULT_TOAST_DURATION_MS = 6000


def _success_toast() -> rx.event.EventSpec:
    """Deliberately just the headline — no description, no media id, no "Ver detalles".

    Empirically verified (temporary probe on the no-login /design route, removed after)
    that `ToastProps.action`'s `on_click` — the only way this library exposes a clickable
    element inside a toast — never reaches ANY handler in this installed version
    (reflex==0.9.7, reflex_components_sonner==0.9.1): tested both a real state
    EventHandler and a client-side-only follow-up toast, neither fired, no console error
    either time. The wrapper also has no `toast.custom` and types `message`/`description`
    as plain `str`, so there is no way to embed rich/clickable content in a toast body at
    all here — a hard capability ceiling, not a styling choice. Founder's call, given
    that: drop the extra info entirely rather than ship something unreliable or a
    click-target that does nothing. The full id stays on
    `PublishState.attempt.published_media_id` for anything that needs it."""
    return rx.toast.success(
        "¡Publicado correctamente!",
        duration=_RESULT_TOAST_DURATION_MS,
    )


def _failure_toast(message: str) -> rx.event.EventSpec:
    """Same text the persistent `error` callout shows, surfaced immediately as a toast
    too — the callout stays, this just makes sure a failure is never missed because the
    operator wasn't looking at the form when it happened."""
    return rx.toast.error(
        "No se pudo publicar",
        description=message,
        duration=_RESULT_TOAST_DURATION_MS,
    )


@dataclass
class _PendingFile:
    """One buffered upload, kept server-side only — never a reactive Var, same posture
    `_pending_bytes` already had for a single file (QUA-19/QUA-98). A list of these
    replaces the old single-file buffer (QUA-99, 6/6): position in this list IS the
    carousel position downstream (`PublishService.start_many`, QUA-99 4/6), so order is
    preserved end to end, never re-sorted.

    `filename` (gallery redesign, QUA-99 UX follow-up) exists ONLY to back the matching
    entry in the public `pending_items` — never read by `publish_background`/the Meta
    call chain, which only ever needed `content_type`/`data`.

    `media_type` (QUA-103) is `MEDIA_TYPE_IMAGE`/`MEDIA_TYPE_VIDEO` — resolved once, in
    `add_files`, by `_resolve_media` below, and never re-derived or defaulted anywhere
    downstream. `content_type` is the CANONICAL value for that type (`IMAGE_CONTENT_TYPE`
    for an image, the matched video MIME for a video) — not necessarily byte-for-byte what
    the browser reported, since a browser can omit/mangle it; `_resolve_media` is the one
    place that reconciles the two, explicitly, never silently."""

    content_type: str
    data: bytes
    filename: str
    media_type: str


# QUA-103 — the dropzone's own `accept` (`publishing_page.py`) already restricts the
# picker to these, but a drag-and-drop can still hand `add_files` something else (some
# browsers report no `content_type` at all for a dropped file, or a generic one) — these
# are the SAME extensions `accept` advertises, used here only as the explicit fallback
# signal, never silently assumed.
_JPEG_EXTENSIONS = (".jpg", ".jpeg")
_MP4_CONTENT_TYPE = "video/mp4"
_MOV_CONTENT_TYPE = "video/quicktime"
_VIDEO_CONTENT_TYPES = {_MP4_CONTENT_TYPE, _MOV_CONTENT_TYPE}


def _resolve_media(content_type: str | None, filename: str) -> tuple[str, str] | None:
    """Resolve `(media_type, canonical_content_type)` for one dropped/picked file
    (QUA-103) — or `None` if it cannot be resolved at all. The caller MUST reject the
    file on `None`; there is no default here, and in particular NEVER a fallback to
    `MEDIA_TYPE_VIDEO` for a file whose type could not be determined — that silent
    coercion is exactly what QUA-103 forbids (a `.png`/`.heic`/unlabeled file must never
    quietly become "a video").

    The browser's declared `content_type` is trusted first (`image/jpeg` → IMAGE;
    `video/mp4`/`video/quicktime` → VIDEO). When it is missing or something else
    entirely (some browsers report a blank or a generic `application/octet-stream` type
    for a drag-and-dropped file), the filename extension is the explicit fallback
    signal — still a real, named check, never a default. This function only decides
    which Meta call to route to; it is NOT the format's real security boundary — a
    mislabeled file (right extension, wrong bytes) is caught server-side by
    `MediaStagingService`'s JPEG magic-byte check regardless of what this returns.
    """
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


class PublishState(rx.State):
    """State for the "Publicar" screen: pick a connected account, upload 1-10 files —
    JPEG images or MP4/MOV videos — and publish. A single file publishes as-is (an
    image or a reel, QUA-103); 2-10 files publish together as one carousel, any mix of
    image and video (QUA-99 for all-video, QUA-103 for image/mixed) — the only limit is
    `_MAX_ITEMS`."""

    connections: list[ConnectionOptionVM] = []
    is_loading_connections: bool = False
    load_error: str = ""
    # PUBLICAR-4 UX review: True once a load finished without error, so «connect your
    # Instagram first» shows above step 1 only when there really is no account — never
    # as a flash before the first load.
    connections_loaded: bool = False
    # PUBLICAR-4 UX review (N3): the last pick was refused by the dropzone. Step 1 keeps
    # the reason on screen (the toast alone vanishes); cleared by the next valid pick.
    last_drop_rejected: bool = False

    selected_connection_id: str = ""
    caption: str = ""

    # idle | staging_and_starting | polling | success | failure
    phase: str = "idle"
    attempt: PublishAttemptVM | None = None
    error: str = ""

    # Gallery redesign (QUA-99 UX follow-up) — the public, display-only projection of
    # `_pending_files` below: filenames only, in the SAME order, so `rx.foreach` can
    # render the grid and a tile's index IS its carousel position. Kept in lockstep with
    # `_pending_files` by every mutation (`add_files`/`remove_pending_file`/the
    # clear-on-settle sites) — two lists, one order, never a separate source of truth for
    # "how many" or "in what sequence".
    pending_items: list[PendingItemVM] = []

    # Carousel per-child progress (QUA-99 UX follow-up) — populated only while polling a
    # CAROUSEL attempt (`_is_carousel` below), from `carousel_children_status`, a
    # READ-ONLY projection that changes nothing about `advance()`/`_advance_children`.
    # Empty for a single-video attempt, and empty before the first poll of a carousel one.
    carousel_children: list[ChildStatusVM] = []

    # Private: bridges the foreground `publish` handler (which alone may receive the
    # upload) to the background `publish_background` handler (which alone may do the
    # slow staging/publish work) — see the module docstring's deviation note. A list
    # (QUA-99, 6/6) rather than a single buffer — how many items it holds is what decides,
    # inside `publish_background`, whether the existing single-video path or the carousel
    # path runs; the UI itself never makes that choice.
    #
    # Gallery redesign (QUA-99 UX follow-up): this is now populated INCREMENTALLY, by
    # `add_files` on every drop/pick, rather than read fresh in one shot by `publish()` —
    # the native `<input type=file>` dialog has no memory of a PRIOR selection when
    # reopened (a browser/HTML constraint, not a Reflex one: `rx.selected_files` only
    # ever exposes the CURRENT dropzone selection's file `name`s —
    # `reflex_components_core/core/upload.py:104-120` — never a blob/File handle, so
    # there is no way to keep showing a real video-frame thumbnail for it either; see
    # `publishing_page.py`'s `_upload_zone` docstring for that limitation in full). So
    # "add more without losing what's already selected" has to be Python-state merging,
    # not a browser capability.
    _pending_files: list[_PendingFile] = []
    # Generated once per publish attempt, preserved across its polls, never regenerated
    # by a poll itself. A new click on "Publicar" after a failure generates a fresh one
    # (decision 3 of the approved plan).
    _idempotency_key: str = ""
    _active_tenant_id: str = ""
    # QUA-99 UX follow-up — set once, in `publish_background`, from `len(pending) > 1` at
    # the moment the attempt starts (the SAME count that already decided `start_publish`
    # vs `start_many_publish`, not a second guess at it). Gates the extra
    # `carousel_children_status` read in `poll_attempt`: a single-video attempt never had
    # children to begin with, so this stays `False` and that read is never even attempted.
    _is_carousel: bool = False
    # QUA-99 UX follow-up — `time.monotonic()` at the moment `phase` becomes "polling",
    # purely to derive `elapsed_label` below. Monotonic, not wall-clock: immune to the
    # system clock changing mid-poll, and never persisted/serialized anywhere past this
    # session.
    _poll_started_monotonic: float = 0.0

    @rx.var
    def can_publish(self) -> bool:
        return (
            bool(self.selected_connection_id)
            and bool(self.pending_items)
            and self.phase in ("idle", "success", "failure")
        )

    @rx.var
    def can_edit_gallery(self) -> bool:
        """Whether the gallery (add tile, remove buttons) may be touched right now —
        deliberately NOT the same condition as `can_publish` above, which also requires
        at least one pending item: an EMPTY gallery must still accept adds, it just can't
        be published yet. Drives `disabled=` on the `+` tile and each tile's `X` in
        `publishing_page.py`; `add_files`/`remove_pending_file` re-check this same
        condition server-side, so this Var is UX, not the invariant."""
        return self.phase in ("idle", "success", "failure")

    @rx.var
    def remaining_slots(self) -> int:
        """How many more videos the gallery can still accept — drives the dropzone's own
        `max_files` (belt) and whether the `+` tile renders at all (suspenders); the real
        invariant is still `add_files`' own server-side count check, same posture
        `_MAX_ITEMS` already has everywhere else in this module."""
        return max(0, _MAX_ITEMS - len(self.pending_items))

    @rx.var
    def carousel_stage_label(self) -> str:
        """Only meaningful while `phase == "polling"` and this is a carousel — derives
        which of the concrete, backend-verifiable stages the attempt is in from
        `carousel_children`/`attempt.awaiting_confirmation`, nothing invented: no
        percentage, no fabricated sub-steps, only what those two already prove.

        `carousel_children` is position-ordered (QUA-99 3/6's `list_children`) so the
        first child not yet `finished` IS the one currently being worked — that ordering
        is what makes "video N de M" correct without tracking N separately."""
        total = len(self.carousel_children)
        if total == 0:
            return ""
        for child in self.carousel_children:
            if child.status in ("pending", "uploading"):
                return f"Subiendo video {child.position + 1} de {total}"
            if child.status == "processing":
                return f"Preparando video {child.position + 1} de {total} en Instagram"
        if self.attempt is not None and self.attempt.awaiting_confirmation:
            return "Confirmando publicación"
        return "Creando carrusel"

    @rx.var
    def elapsed_label(self) -> str:
        """`mm:ss` since polling started, refreshed whenever the frontend re-renders
        (each poll tick, ~every `poll_interval_seconds`) — not a live per-second ticker,
        deliberately: that would need a client-side timer this screen has never had,
        which is exactly the complexity this follow-up was asked NOT to introduce."""
        if self.phase != "polling" or self._poll_started_monotonic <= 0:
            return ""
        elapsed = max(0, int(time.monotonic() - self._poll_started_monotonic))
        minutes, seconds = divmod(elapsed, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @rx.event(background=True)
    async def load_active_connections(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """Load the active connections for the current session tenant."""
        async with self:
            self.is_loading_connections = True
            self.load_error = ""
            self.connections_loaded = False

        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            async with self:
                self.is_loading_connections = False
                self.load_error = _NO_TENANT
            return

        try:
            options = await asyncio.to_thread(active_connections, tenant_id)
        except Exception as exc:
            # Only the exception TYPE is logged — same posture as connections_state.py's
            # loader for infrastructure errors that may carry connection details.
            logger.error("active_connections failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_connections = False
                self.load_error = _NO_CONNECTIONS
            return

        async with self:
            self.connections = options
            self.is_loading_connections = False
            self.connections_loaded = True
            # PUBLICAR-4: with exactly one connected account, step 2 («¿Dónde sale?»)
            # arrives with it already chosen — the owner only confirms.
            preselected = self._preselect_single_connection()
        if preselected:
            yield TrendingState.set_audio_connection(preselected)

    def _preselect_single_connection(self) -> str:
        """Choose the account when there is exactly one and none is chosen yet;
        returns the id it chose, or `""` when it left the choice alone."""
        if self.selected_connection_id or len(self.connections) != 1:
            return ""
        self.selected_connection_id = self.connections[0].id
        return self.selected_connection_id

    def _selected_connection(self) -> ConnectionOptionVM | None:
        for conn in self.connections:
            if conn.id == self.selected_connection_id:
                return conn
        return None

    @rx.var
    def selected_platform(self) -> str:
        """The chosen account's network (`instagram`, `facebook`…), `""` if none."""
        conn = self._selected_connection()
        return conn.platform if conn is not None else ""

    @rx.var
    def review_post_sentence(self) -> str:
        """Step 3's review for a publication (PUBLICAR-4) — see `publish_wizard_vm`."""
        conn = self._selected_connection()
        if conn is None:
            return ""
        return review_sentence(FLOW_POSTS, username=conn.external_username, platform=conn.platform)

    @rx.var
    def review_story_sentence(self) -> str:
        """Step 3's review for a historia (PUBLICAR-4) — see `publish_wizard_vm`."""
        conn = self._selected_connection()
        if conn is None:
            return ""
        return review_sentence(
            FLOW_STORIES, username=conn.external_username, platform=conn.platform
        )

    @rx.event
    def reset_form(self) -> None:
        """«Publicar otra» (PUBLICAR-4): an empty step 1 again — files, text, outcome.
        A no-op while a publish is in flight. Keeps the loaded accounts and, with only
        one, chooses it again."""
        if self.phase not in ("idle", "success", "failure"):
            return
        self._pending_files = []
        self.pending_items = []
        self.caption = ""
        self.phase = "idle"
        self.error = ""
        self.attempt = None
        self.carousel_children = []
        self._is_carousel = False
        self._poll_started_monotonic = 0.0
        self._preselect_single_connection()

    @rx.event
    def set_caption(self, value: str) -> None:
        self.caption = value

    @rx.event
    def select_connection(self, connection_id: str) -> rx.event.EventSpec:
        self.selected_connection_id = connection_id
        # QUA-113: the trending panel under this flow uses this flow's account for
        # Meta's audio lookup — same hand-off `StoriesState.select_connection` makes.
        return TrendingState.set_audio_connection(connection_id)

    @rx.event
    async def add_files(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Buffer newly picked/dropped files onto the gallery, preserving whatever was
        already selected (gallery redesign, QUA-99 UX follow-up) — bound to the
        dropzone's own `on_drop` (`publishing_page.py`), so this fires on EVERY
        interaction with the `+` tile, not just the first. A second `on_drop` reusing
        the same native `<input type=file>` never remembers a prior selection — that is
        plain HTML, not a Reflex gap — so merging with what is already buffered has to
        happen here, in Python state, rather than by trusting the dropzone's own list.

        Must NOT be `background=True` — Reflex forbids that combination for a handler
        that receives `list[rx.UploadFile]` (see the module docstring's deviation note,
        which `publish` used to be the example of; this is now the other one).

        A no-op while a publish is already in flight (the gallery is read-only then —
        `publishing_page.py` also disables the dropzone; this is the real guard behind
        that nicety, same posture `publish`'s own phase check has) or if nothing was
        actually dropped (every file may have failed react-dropzone's own
        `accept`/`max_size` check and gone through `on_drop_rejected` instead).
        """
        if not files:
            return None
        if self.phase not in ("idle", "success", "failure"):
            return None
        if len(self._pending_files) + len(files) > _MAX_ITEMS:
            # Rejected as ONE whole batch, not partially — same "before a single byte"
            # posture `publish`'s own count guard always had, just measured against what
            # is ALREADY buffered instead of from zero. No phase change: the user hasn't
            # tried to publish anything yet, this is a selection-time rejection.
            return _failure_toast(_TOO_MANY)

        new_pending: list[_PendingFile] = []
        new_items: list[PendingItemVM] = []
        for upload in files:
            filename = (
                getattr(upload, "filename", None) or getattr(upload, "name", None) or "archivo"
            )
            # QUA-103: resolved EXPLICITLY, never defaulted to video — see `_resolve_media`.
            resolved = _resolve_media(getattr(upload, "content_type", None), filename)
            if resolved is None:
                return _failure_toast(_UNSUPPORTED_FORMAT)
            media_type, content_type = resolved
            try:
                data = await upload.read()
            except Exception:
                # Same as above: a bad file at ADD time is not a publish failure, just a
                # rejected selection — no phase change, existing buffer untouched.
                return _failure_toast(_BAD_MEDIA)
            new_pending.append(
                _PendingFile(
                    content_type=content_type, data=data, filename=filename, media_type=media_type
                )
            )
            new_items.append(
                PendingItemVM(
                    filename=filename, kind="image" if media_type == MEDIA_TYPE_IMAGE else "video"
                )
            )

        # QUA-103: carousel-of-image and mixed image+video carousels are supported end
        # to end now (start_many/_create_and_upload_child bifurcate by each item's own
        # media_type) — a gallery combining any mix of image/video, up to _MAX_ITEMS, is
        # a perfectly valid selection. The `_MAX_ITEMS` check above (before this loop)
        # remains the only count guard; there is no longer a type-based restriction here.
        self._pending_files = self._pending_files + new_pending
        self.pending_items = self.pending_items + new_items
        self.last_drop_rejected = False
        return None

    @rx.event
    def mark_drop_rejected(self, _rejected: list[dict] | None = None) -> None:
        """The dropzone refused a pick (format, size or count). Step 1 then shows the
        reason in a lasting callout next to the toast (N3); `add_files` clears it."""
        self.last_drop_rejected = True

    @rx.event
    def remove_pending_file(self, index: int) -> None:
        """Removes one item from the gallery by position (gallery redesign, QUA-99 UX
        follow-up). Reindexing is automatic — both lists stay plain, order-preserving
        Python lists, filtered by index, never re-sorted, so position N+1's neighbours
        simply close the gap exactly like removing an element from any list does.

        A no-op while a publish is in flight (same read-only posture `add_files` already
        has) or for an out-of-range index (defensive — the UI only ever offers a valid
        one, via `rx.foreach`'s own index)."""
        if self.phase not in ("idle", "success", "failure"):
            return
        if not (0 <= index < len(self._pending_files)):
            return
        self._pending_files = [f for i, f in enumerate(self._pending_files) if i != index]
        self.pending_items = [it for i, it in enumerate(self.pending_items) if i != index]

    @rx.event
    def publish(self) -> rx.event.EventSpec | None:
        """Validate the buffered gallery and hand off to `publish_background`.

        No longer receives the upload directly (gallery redesign, QUA-99 UX follow-up):
        `add_files` already buffered everything into `_pending_files`/`pending_items`
        incrementally as the user built the gallery, so there is nothing left to read
        here — this is a plain synchronous handler again, not `async`.

        The `self.phase` check below is the SERVER-SIDE guard against a double-submit —
        `can_publish`/`disabled=` on the button in `publishing_page.py` is a UX nicety on
        top of it, not the actual invariant. It is sufficient on its own: `publish` is a
        FOREGROUND handler, and Reflex serializes foreground events per session (its
        per-token event queue) — background events like `publish_background` do not get
        that ordering. So without this check, two rapid clicks could each pass through to
        `publish_background` and each start a REAL publish against Meta before either
        settles; the `_idempotency_key` guard inside `publish_background` only stops the
        superseded one from corrupting the UI's final state, it does not stop it from
        having already published something. With this check, the second `publish` call
        is rejected here, before a second `publish_background` is ever dispatched.
        """
        if self.phase not in ("idle", "success", "failure"):
            return None  # a publish is already in flight for this session
        if not self.selected_connection_id:
            self.phase = "failure"
            self.error = _NO_CONNECTION_SELECTED
            return _failure_toast(_NO_CONNECTION_SELECTED)
        if not self._pending_files:
            return None  # nothing selected — same silent no-op an empty `files` had
        if len(self._pending_files) > _MAX_ITEMS:
            # Defense-in-depth: `add_files` already refuses to buffer past the cap.
            # Reached only if that guard is ever bypassed.
            self.phase = "failure"
            self.error = _TOO_MANY
            return _failure_toast(_TOO_MANY)

        self._idempotency_key = uuid4().hex
        self.phase = "staging_and_starting"
        self.error = ""
        self.attempt = None
        return PublishState.publish_background

    async def _fail_pending_attempt(
        self, idempotency_key: str, message: str
    ) -> rx.event.EventSpec | None:
        """Record a failure for the attempt `idempotency_key` names, and release the
        buffered upload. Returns the failure toast to yield — or `None` if this call was
        superseded and applied nothing (see below), so the caller never fires a toast for
        an attempt that never actually became the failure.

        Called from EVERY failure branch in `publish_background` (including the
        pre-staging `tenant_id is None` case) so none of them can leave `_pending_files`
        holding up to 10 full videos (up to 300 MB each) in this session's memory after a
        failed attempt — previously only the success path cleared it. Guarded by the
        idempotency key: a stale (superseded) attempt's failure must not clobber a
        newer attempt's in-progress state, and must not clear a newer attempt's
        `_pending_files` out from under it. Clears `pending_items` in lockstep — the
        gallery must empty exactly when its backing buffer does (gallery redesign,
        QUA-99 UX follow-up).
        """
        async with self:
            if self._idempotency_key != idempotency_key:
                return None
            self.phase = "failure"
            self.error = message
            self._pending_files = []
            self.pending_items = []
            return _failure_toast(message)

    @rx.event(background=True)
    async def publish_background(self) -> AsyncIterator[None]:
        """Stage the bytes `publish` captured and start a publish attempt, then hand off
        to polling. Reads everything it needs from the private vars `publish` set.

        QUA-99 (6/6): the first decision here is `len(pending)` — 1 item calls
        `start_publish`, 2-10 calls `start_many_publish` (QUA-99 5/6, still VIDEO-only —
        `publish()`'s own guard keeps an IMAGE out of this branch). QUA-103 adds a second
        decision, only for the single-item path: `media_product_type` is resolved from
        that one item's own `media_type` (`"IMAGE"` or `"REELS"`), never hardcoded.
        Everything AFTER either split — the try/except tree, the phase transitions, the
        toasts, the poll handoff — is the SAME code for every case: one unified machine.
        Both provider functions raise the same exception set (R2ConfigurationError,
        UnsupportedImageFormat, ObjectSizeExceeded/UnsizedStream, TenantPrefixViolation/
        ValueError, UnknownConnection), plus `TooManyItems` for the multi path only — a
        single `except` clause covers it too, as defense-in-depth behind `publish`'s own
        earlier, cheaper rejection.
        """
        async with self:
            if self.phase != "staging_and_starting":
                return  # superseded, or nothing was actually queued
            connection_id = self.selected_connection_id
            caption = self.caption
            idempotency_key = self._idempotency_key
            pending = list(self._pending_files)
            # QUA-99 UX follow-up: the SAME count that decides `start_publish` vs
            # `start_many_publish` below, recorded once so `poll_attempt` knows whether
            # to fetch per-child status — never a second, independent guess at it. Reset
            # `carousel_children` too, so a stale list from a PREVIOUS attempt never
            # shows before this one's first poll tick populates it.
            self._is_carousel = len(pending) > 1
            self.carousel_children = []

        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            toast = await self._fail_pending_attempt(idempotency_key, _NO_TENANT)
            if toast is not None:
                yield toast
            return
        async with self:
            self._active_tenant_id = str(tenant_id)

        try:
            if len(pending) == 1:
                item = pending[0]
                # QUA-103: resolved from the ONE pending item's own type — never
                # hardcoded. `start_publish` itself no longer accepts a default; passing
                # nothing here would be a `TypeError`, not a silent "REELS".
                media_product_type = (
                    MEDIA_TYPE_IMAGE if item.media_type == MEDIA_TYPE_IMAGE else MEDIA_TYPE_REELS
                )
                attempt = await start_publish(
                    tenant_id=tenant_id,
                    connection_id=UUID(connection_id),
                    fileobj=io.BytesIO(item.data),
                    content_type=item.content_type,
                    media_product_type=media_product_type,
                    caption=caption,
                    idempotency_key=idempotency_key,
                )
            else:
                attempt = await start_many_publish(
                    tenant_id=tenant_id,
                    connection_id=UUID(connection_id),
                    items=[
                        PendingUpload(
                            fileobj=io.BytesIO(p.data),
                            content_type=p.content_type,
                            media_type=p.media_type,
                        )
                        for p in pending
                    ],
                    caption=caption,
                    idempotency_key=idempotency_key,
                )
        except R2ConfigurationError:
            toast = await self._fail_pending_attempt(idempotency_key, _NOT_CONFIGURED)
            if toast is not None:
                yield toast
            return
        except UnsupportedImageFormat:
            # QUA-103: the declared content_type/extension said JPEG, but the actual
            # bytes are not (magic-byte check, `MediaStagingService`) — a mislabeled or
            # renamed non-JPEG file, never a silent accept.
            toast = await self._fail_pending_attempt(idempotency_key, _UNSUPPORTED_IMAGE_FORMAT)
            if toast is not None:
                yield toast
            return
        except (ObjectSizeExceeded, UnsizedStream):
            # QUA-103: distinguishes the 8 MB IMAGE ceiling from the 300 MB VIDEO one —
            # both exceptions are shared vocabulary (`gate.py`/`staging.py`), only the
            # MESSAGE differs, based on what was actually being published.
            size_message = (
                _IMAGE_TOO_LARGE
                if len(pending) == 1 and pending[0].media_type == MEDIA_TYPE_IMAGE
                else _TOO_LARGE
            )
            toast = await self._fail_pending_attempt(idempotency_key, size_message)
            if toast is not None:
                yield toast
            return
        except (TenantPrefixViolation, ValueError):
            toast = await self._fail_pending_attempt(idempotency_key, _BAD_MEDIA)
            if toast is not None:
                yield toast
            return
        except UnknownConnection:
            toast = await self._fail_pending_attempt(idempotency_key, _UNKNOWN_CONNECTION)
            if toast is not None:
                yield toast
            return
        except TooManyItems:
            # Defense-in-depth: `publish` already rejects >10 before this handler ever
            # runs. Reached only if that guard and the dropzone's max_files=10 both missed.
            toast = await self._fail_pending_attempt(idempotency_key, _TOO_MANY)
            if toast is not None:
                yield toast
            return
        except Exception as exc:
            logger.error("start_publish failed: %s", type(exc).__name__)
            toast = await self._fail_pending_attempt(idempotency_key, _START_FAILED)
            if toast is not None:
                yield toast
            return

        async with self:
            # A newer attempt (a fresh click) superseded this one while we staged.
            if self._idempotency_key != idempotency_key:
                return
            self._pending_files = []  # release the buffer(s), staged copies already in R2
            self.attempt = attempt
            if attempt.settled:
                self.phase = "success" if attempt.status == "published" else "failure"
                if self.phase == "failure":
                    self.error = attempt.reason or _START_FAILED
                # gallery redesign, QUA-99 UX follow-up: the gallery only clears once
                # there is a final outcome to show INSTEAD of it (a toast) — see the
                # `else` branch below for why it stays populated through polling.
                self.pending_items = []
            else:
                self.phase = "polling"
                # QUA-99 UX follow-up (2/2) — deliberately NOT cleared here, unlike
                # `_pending_files` above: that buffer holds up to 10 full videos' worth
                # of BYTES and must be released the moment they are safely in R2, but
                # `pending_items` is just filenames — keeping it populated through the
                # whole "polling" phase is what lets the gallery keep showing what is
                # actually being published (thumbnails, count, order) instead of
                # reverting to the empty "arrastra tu contenido aquí" prompt while a
                # real, sometimes multi-minute wait is in progress (reported exactly
                # this way: "porque no me sale el carrusel mientras esta en este
                # proceso", 2026-09-10). Cleared once there IS a final outcome to show
                # instead — see `poll_attempt`'s own settle branch below.
                self._poll_started_monotonic = time.monotonic()
            should_poll = self.phase == "polling"
            is_success = self.phase == "success"
            if is_success:
                # QUA-98: clear the whole form after a successful publish, account
                # included — reported explicitly: leaving the account selected read as
                # an incomplete reset.
                self.caption = ""
                self.selected_connection_id = ""
            result_toast = (
                _success_toast()
                if is_success
                else _failure_toast(self.error)
                if self.phase == "failure"
                else None
            )
        yield

        if is_success:
            # The account was just cleared above — the trending panel lets go of it too.
            yield TrendingState.release_audio_connection
        if result_toast is not None:
            yield result_toast

        if should_poll:
            yield PublishState.poll_attempt

    @rx.event(background=True)
    async def poll_attempt(self) -> AsyncIterator[None]:
        """Client-driven polling: one `advance()` step per iteration, self-scheduling by
        yielding itself again until the attempt settles or the safety ceiling is hit —
        never a blocking sleep loop on the request thread."""
        for _ in range(_MAX_POLLS):
            async with self:
                if self.phase != "polling" or self.attempt is None:
                    return
                tenant_id = tenant_uuid(self._active_tenant_id)
                attempt_id = self.attempt.attempt_id
                idempotency_key = self._idempotency_key
                is_carousel = self._is_carousel

            if tenant_id is None:
                return

            try:
                attempt = await poll_publish(tenant_id=tenant_id, attempt_id=UUID(attempt_id))
            except UnknownAttempt:
                toast = None
                async with self:
                    if self._idempotency_key == idempotency_key:
                        self.phase = "failure"
                        self.error = _POLL_FAILED
                        self.pending_items = []  # gallery redesign — releases on any final failure
                        toast = _failure_toast(_POLL_FAILED)
                yield
                if toast is not None:
                    yield toast
                return
            except Exception as exc:
                logger.error("poll_publish failed: %s", type(exc).__name__)
                toast = None
                async with self:
                    if self._idempotency_key == idempotency_key:
                        self.phase = "failure"
                        self.error = _POLL_FAILED
                        self.pending_items = []  # gallery redesign — releases on any final failure
                        toast = _failure_toast(_POLL_FAILED)
                yield
                if toast is not None:
                    yield toast
                return

            # QUA-99 UX follow-up — READ-ONLY carousel progress, fetched alongside (never
            # instead of) the real `poll_publish` call above. Never touches `advance()`/
            # `_advance_children`/`media_publish`; a failure here only means one tick
            # without a per-child label, not a failed poll — so it is swallowed, not
            # allowed to fail the actual settle logic below.
            children_vm: list[ChildStatusVM] | None = None
            if is_carousel and not attempt.settled:
                try:
                    children_vm = await asyncio.to_thread(
                        carousel_children_status, tenant_id=tenant_id, attempt_id=UUID(attempt_id)
                    )
                except Exception as exc:
                    logger.error("carousel_children_status failed: %s", type(exc).__name__)

            async with self:
                if self._idempotency_key != idempotency_key:
                    return  # superseded by a newer attempt
                self.attempt = attempt
                if children_vm is not None:
                    self.carousel_children = children_vm
                if attempt.settled:
                    self.phase = "success" if attempt.status == "published" else "failure"
                    if self.phase == "failure":
                        self.error = attempt.reason or _START_FAILED
                    # gallery redesign, QUA-99 UX follow-up: this is the settle point
                    # `publish_background`'s own docstring points to — `pending_items`
                    # stayed populated through the whole polling wait specifically so
                    # the gallery could keep showing what was being published; now that
                    # there is a final outcome (a toast) to show instead, it releases.
                    self.pending_items = []
                interval = attempt.poll_interval_seconds
                settled = attempt.settled
                is_success = self.phase == "success"
                if is_success:
                    # QUA-98: clear the whole form after a successful publish, account
                    # included — reported explicitly: leaving the account selected read
                    # as an incomplete reset. Same reset as `publish_background`'s own
                    # direct-success path above; this is the poll-settle path, the more
                    # common of the two in practice.
                    self.caption = ""
                    self.selected_connection_id = ""
                result_toast = (
                    _success_toast()
                    if is_success
                    else _failure_toast(self.error)
                    if self.phase == "failure"
                    else None
                )
            yield
            if is_success:
                yield TrendingState.release_audio_connection
            if result_toast is not None:
                yield result_toast
            if settled:
                return
            await asyncio.sleep(interval)

        toast = None
        async with self:
            if self._idempotency_key == idempotency_key and self.phase == "polling":
                self.phase = "failure"
                self.error = _POLL_FAILED
                self.pending_items = []  # gallery redesign — releases on any final failure
                toast = _failure_toast(_POLL_FAILED)
        yield
        if toast is not None:
            yield toast
