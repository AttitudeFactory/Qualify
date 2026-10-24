"""Reflex state for the Stories flow of `/publish` (QUA-106 V1 redesign; a flow inside
Publicar since QUA-113): a single publish form for
Instagram Stories, structurally the same flow `/publish` already has — pick a
connected account, select one video, see it in the gallery, hit "Publicar", poll
until Meta settles — narrowed to exactly one file (a Story is never a carousel) and
one fixed `media_product_type`.

**No `StoryProposal`, no approval, no review, no history.** There is no concept
here of a pending/pending-review/approved/rejected item — `publish()` calls
`publishing_provider.start_publish(media_product_type="STORIES")` directly, the
EXACT seam `/publish` uses for a single video, just with a different
`media_product_type`. `publish_attempts` (already existing, already the audit trail
for every other publish in this app) is the only record this produces — no second
table, no list screen, no detail screen.

**Media is always the operator's own upload.** No AI generation, no reuse of
scraped third-party content. A video (`.mp4`/`.mov`) or, since QUA-113, a JPEG
image (`.jpg`/`.jpeg`). The image goes through the SAME `start_publish` call with
`media_product_type="STORIES"`; `PublishService` sees the image `content_type` and
publishes it as an image container with `media_type=STORIES` (Meta fetches it from
the public media URL — same requirement as a feed image).

**No caption field.** Instagram never shows a caption on a Story published via the
API — confirmed during manual testing — so there is nothing to collect from the
operator; `publish_background` always sends `caption=""`.

**Trending audio/content lives in `TrendingState` (`trending_state.py`, QUA-113).**
This state only tells it which account Meta's `ig_audio` lookup may use
(`TrendingState.set_audio_connection` when the account changes,
`release_audio_connection` after a successful publish). Nothing from the trending
panel ever reaches `publish_background`'s call to `start_publish`.

**Connected accounts load on demand (QUA-113).** `ensure_connections_loaded` loads
them the first time the Stories flow is entered and is a no-op afterwards, so a
screen that shows Stories as a second flow never queries for it up front;
`invalidate_connections` marks the cached list stale so the next entry reloads.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.publishing import MEDIA_TYPE_STORIES
from qualify_api.publishing.service import UnknownAttempt, UnknownConnection
from qualify_api.publishing.staging import UnsupportedImageFormat
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectSizeExceeded, UnsizedStream
from qualify_shared.objects.keys import TenantPrefixViolation

from .auth_state import AuthState
from .publishing_provider import active_connections, poll_publish, start_publish
from .publishing_vm import ConnectionOptionVM, PublishAttemptVM
from .tenant import tenant_uuid
from .trending_state import TrendingState

logger = logging.getLogger(__name__)

_NO_TENANT = "No encontramos tu negocio en esta sesión. Cierra sesión y vuelve a entrar."
_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_NO_CONNECTION_SELECTED = "Elige una cuenta conectada antes de publicar."
_NO_FILE = "Sube el video o la imagen de la historia antes de publicar."
_UNSUPPORTED_FORMAT = (
    "Ese archivo no se puede publicar como historia. Sube una foto o un video tal como salen "
    "de la cámara de tu celular."
)
# Same wording `publishing_state.py` uses for its own magic-byte rejection.
_UNSUPPORTED_IMAGE_FORMAT = (
    "Esta foto no se puede usar tal cual. Desde tu celular, compártela como “JPG” o "
    "haz una captura de pantalla y súbela."
)
_BAD_MEDIA = "No se pudo leer el archivo subido. Intenta con otro archivo."
_NOT_CONFIGURED = (
    "No podemos subir archivos en este momento. Inténtalo en unos minutos; si sigue, escríbenos."
)
_TOO_LARGE = "El video supera el tamaño máximo permitido (300 MB)."
_IMAGE_TOO_LARGE = "La imagen supera el tamaño máximo permitido (8 MB)."
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la lista e intenta de nuevo."
_START_FAILED = "No se pudo iniciar la publicación. Vuelve a intentarlo en un momento."
_POLL_FAILED = (
    "No sabemos todavía si se publicó. Revisa tu Instagram en unos minutos antes de "
    "volver a intentarlo, para no publicarlo dos veces."
)
_WAIT_EXPLANATION = "Instagram está preparando tu historia. Puede tardar unos minutos."

_MP4_CONTENT_TYPE = "video/mp4"
_MOV_CONTENT_TYPE = "video/quicktime"
_VIDEO_CONTENT_TYPES = {_MP4_CONTENT_TYPE, _MOV_CONTENT_TYPE}
_JPEG_CONTENT_TYPE = "image/jpeg"

_UPLOAD_ID = "story_upload"

#: Client-side safety net only — the SERVER already settles an attempt as 'failed'
#: once its own ceiling elapses (`publishing/client.py`). Same belt-and-suspenders
#: posture `publishing_state.py` documents for its own identical constant.
_MAX_POLLS = 30

_RESULT_TOAST_DURATION_MS = 6000


def _success_toast() -> rx.event.EventSpec:
    return rx.toast.success("¡Historia publicada en Instagram!", duration=_RESULT_TOAST_DURATION_MS)


def _failure_toast(message: str) -> rx.event.EventSpec:
    return rx.toast.error(
        "No se pudo publicar la historia", description=message, duration=_RESULT_TOAST_DURATION_MS
    )


def _resolve_story_media(content_type: str | None, filename: str) -> str | None:
    """`(canonical_content_type)` for one dropped/picked file — an MP4/MOV video or a
    JPEG image (QUA-113) — or `None` if it cannot be resolved. Same "no silent
    fallback" discipline `publishing_state._resolve_media` documents for its own
    resolver. Only JPEG for images: it is the one image format Meta's Content
    Publishing API accepts (`client.IMAGE_CONTENT_TYPE`)."""
    ct = (content_type or "").strip().lower()
    if ct in _VIDEO_CONTENT_TYPES or ct == _JPEG_CONTENT_TYPE:
        return ct
    name = filename.lower()
    if name.endswith(".mp4"):
        return _MP4_CONTENT_TYPE
    if name.endswith(".mov"):
        return _MOV_CONTENT_TYPE
    if name.endswith((".jpg", ".jpeg")):
        return _JPEG_CONTENT_TYPE
    return None


class StoriesState(rx.State):
    """Backs the Stories publish flow — one file, one publish action. Structurally the
    single-item path of `PublishState` (`publishing_state.py`). The trending panel
    shown next to it is `TrendingState`, not part of this state."""

    connections: list[ConnectionOptionVM] = []
    is_loading_connections: bool = False
    connections_error: str = ""

    selected_connection_id: str = ""
    pending_filename: str = ""
    # QUA-113: the buffered file is a JPEG (vs a video) — picks the tile's fallback
    # icon and the size message; the publish call itself only needs the content type.
    pending_is_image: bool = False

    # idle | staging_and_starting | polling | success | failure — same vocabulary
    # `PublishState.phase` already uses.
    phase: str = "idle"
    attempt: PublishAttemptVM | None = None
    error: str = ""

    # Private: bridges the foreground `add_file` (the only handler allowed to receive
    # the upload) to the background `publish_background` — same split
    # `publishing_state.py`'s own upload deviation note documents, narrowed to one
    # file (a Story is never a carousel).
    _pending_bytes: bytes = b""
    _pending_content_type: str = ""
    _idempotency_key: str = ""
    _active_tenant_id: str = ""
    # `time.monotonic()` at the moment `phase` becomes "polling", purely to derive
    # `elapsed_label` — same posture `PublishState`'s own field documents.
    _poll_started_monotonic: float = 0.0
    # True once `load_stories_screen` has succeeded for the current entry — lets
    # `ensure_connections_loaded` skip the query on every later entry into the flow.
    # Stays False after a failed load, so the next entry retries.
    _connections_loaded: bool = False

    @rx.var
    def can_publish(self) -> bool:
        return (
            bool(self.selected_connection_id)
            and bool(self.pending_filename)
            and self.phase in ("idle", "success", "failure")
        )

    @rx.var
    def can_edit_gallery(self) -> bool:
        """Whether the gallery (dropzone, remove button) may be touched right now —
        same condition `PublishState.can_edit_gallery` documents for itself, deliberately
        NOT the same as `can_publish`, which also requires a file to already be selected."""
        return self.phase in ("idle", "success", "failure")

    @rx.var
    def elapsed_label(self) -> str:
        if self.phase != "polling" or self._poll_started_monotonic <= 0:
            return ""
        elapsed = max(0, int(time.monotonic() - self._poll_started_monotonic))
        minutes, seconds = divmod(elapsed, 60)
        return f"{minutes:02d}:{seconds:02d}"

    async def _session_tenant_id(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        return tenant_uuid(session_tenant_id) if session_tenant_id else None

    # -- load ----------------------------------------------------------------

    @rx.event(background=True)
    async def load_stories_screen(self) -> None:
        async with self:
            self.is_loading_connections = True
            self.connections_error = ""

        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_TENANT
            return
        async with self:
            self._active_tenant_id = str(tenant_id)

        try:
            connections = await asyncio.to_thread(active_connections, tenant_id)
        except Exception as exc:
            logger.error("active_connections failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_CONNECTIONS
            return
        async with self:
            self.connections = connections
            self.is_loading_connections = False
            self._connections_loaded = True

    @rx.event
    def ensure_connections_loaded(self) -> rx.event.EventSpec | None:
        """Load the connected accounts only if this flow has not loaded them yet —
        the first entry into Stories pays for the query, later entries are free. A
        load already in flight is not started twice: `is_loading_connections` is set
        HERE, in the foreground, before the background load is even scheduled."""
        if self._connections_loaded or self.is_loading_connections:
            return None
        self.is_loading_connections = True
        return StoriesState.load_stories_screen

    @rx.event
    def invalidate_connections(self) -> None:
        """Mark the loaded accounts stale — the next `ensure_connections_loaded`
        queries again. Called when the screen itself is (re)entered, so a newly
        connected account shows up on a fresh visit exactly as it did before."""
        self._connections_loaded = False

    # -- form ------------------------------------------------------------------

    @rx.event
    def select_connection(self, connection_id: str) -> rx.event.EventSpec:
        self.selected_connection_id = connection_id
        # The trending panel's Meta audio lookup follows this flow's account — and
        # drops whatever it suggested for the PREVIOUS one (TrendingState owns that).
        return TrendingState.set_audio_connection(connection_id)

    @rx.event
    async def add_file(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Buffers ONE file (a video or a JPEG) — a second drop REPLACES the first,
        there is no gallery/carousel for a Story. Must not be `background=True`: Reflex forbids
        that combination for a handler receiving `list[rx.UploadFile]` (same
        constraint `publishing_state.py`'s module docstring documents)."""
        if not files:
            return None
        if self.phase not in ("idle", "success", "failure"):
            return None
        upload = files[0]
        filename = getattr(upload, "filename", None) or getattr(upload, "name", None) or "archivo"
        content_type = _resolve_story_media(getattr(upload, "content_type", None), filename)
        if content_type is None:
            return rx.toast.error(_UNSUPPORTED_FORMAT)
        try:
            data = await upload.read()
        except Exception:
            return rx.toast.error(_BAD_MEDIA)
        self._pending_bytes = data
        self._pending_content_type = content_type
        self.pending_filename = filename
        self.pending_is_image = content_type == _JPEG_CONTENT_TYPE
        return None

    @rx.event
    def clear_file(self) -> None:
        if self.phase not in ("idle", "success", "failure"):
            return
        self._pending_bytes = b""
        self._pending_content_type = ""
        self.pending_filename = ""
        self.pending_is_image = False

    def adopt_file(
        self, *, filename: str, content_type: str, data: bytes, connection_id: str
    ) -> bool:
        """Take the one file and the account chosen in steps 1-2 of «Publicar ahora»
        (PUBLICAR-4) — the assistant buffers files in `PublishState` whatever they end
        up being, and hands them over here only when the owner publishes a historia.
        A plain method, called server-side by `PublishHubState.publish_now` (the bytes
        never travel through the browser). Refuses — returning False — while a publish
        is in flight or for a type a historia cannot carry."""
        if self.phase not in ("idle", "success", "failure"):
            return False
        resolved = _resolve_story_media(content_type, filename)
        if resolved is None or not data:
            return False
        self._pending_bytes = data
        self._pending_content_type = resolved
        self.pending_filename = filename
        self.pending_is_image = resolved == _JPEG_CONTENT_TYPE
        self.selected_connection_id = connection_id
        return True

    @rx.event
    def reset_form(self) -> None:
        """«Publicar otra» (PUBLICAR-4): forget the last historia and its outcome.
        A no-op while a publish is in flight."""
        if self.phase not in ("idle", "success", "failure"):
            return
        self._pending_bytes = b""
        self._pending_content_type = ""
        self.pending_filename = ""
        self.pending_is_image = False
        self.phase = "idle"
        self.error = ""
        self.attempt = None
        self._poll_started_monotonic = 0.0

    # -- share to Instagram (Web Share API handoff) -------------------------

    @rx.event
    def handle_share_result(self, result: str) -> rx.event.EventSpec | None:
        """Receives the outcome of `_SHARE_TO_INSTAGRAM_SCRIPT` (`stories_page.py`).
        This is a pure client-side OS handoff (`navigator.share`) — it never touches
        Meta's Graph API and never changes `phase`/`attempt`: it is an ALTERNATIVE
        to `publish()`, not a step of it, for the video the user wants to finish
        inside Instagram itself with a native Music sticker — Meta's Graph API
        `audio_configuration` only ever applies to Reels container creation; there is
        no equivalent parameter for `media_type=STORIES`, confirmed against Meta's
        current Instagram Platform docs (Content Publishing / Audio API references)."""
        if result == "shared":
            return rx.toast.success(
                "Archivo compartido. Termina en Instagram: elige Historia, "
                "agrega la música y publica ahí."
            )
        if result == "cancelled":
            return None  # the user closed the OS share sheet — not an error
        if result == "desktop":
            return rx.toast.error(
                "Esta opción es para el celular: abre Qualify desde tu teléfono "
                "para que Instagram reciba el video directamente."
            )
        if result == "insecure":
            return rx.toast.error("Esta página necesita HTTPS para poder compartir el video.")
        if result == "unsupported":
            return rx.toast.error(
                "Este navegador no soporta compartir video directamente. "
                "Prueba desde Chrome (Android) o Safari (iPhone)."
            )
        if result == "no_file":
            return rx.toast.error(
                "Vuelve al paso 1 y elige otra vez la foto o el video para abrirlo en Instagram."
            )
        if result == "cannot_share_file":
            return rx.toast.error(
                "Este navegador no puede compartir este archivo (formato o tamaño no soportado)."
            )
        return rx.toast.error("No se pudo compartir el video.")

    # -- publish -----------------------------------------------------------

    @rx.event
    def publish(self) -> rx.event.EventSpec | None:
        """Validate the buffered file and hand off to `publish_background` — same
        split `publishing_state.publish` documents for its own foreground/background
        boundary. The `self.phase` check is the SERVER-SIDE guard against a
        double-submit, same reasoning `PublishState.publish` documents for its own
        identical check."""
        if self.phase not in ("idle", "success", "failure"):
            return None  # a publish is already in flight for this session
        if not self.selected_connection_id:
            self.phase = "failure"
            self.error = _NO_CONNECTION_SELECTED
            return _failure_toast(_NO_CONNECTION_SELECTED)
        if not self._pending_bytes:
            self.phase = "failure"
            self.error = _NO_FILE
            return _failure_toast(_NO_FILE)

        self._idempotency_key = uuid4().hex
        self.phase = "staging_and_starting"
        self.error = ""
        self.attempt = None
        return StoriesState.publish_background

    async def _fail_pending(self, idempotency_key: str, message: str) -> rx.event.EventSpec | None:
        """Record a failure for the attempt `idempotency_key` names, and release the
        buffered upload — same posture `PublishState._fail_pending_attempt`
        documents. Guarded by the idempotency key: a stale (superseded) attempt's
        failure must not clobber a newer attempt's in-progress state."""
        async with self:
            if self._idempotency_key != idempotency_key:
                return None
            self.phase = "failure"
            self.error = message
            self._pending_bytes = b""
            self._pending_content_type = ""
            self.pending_filename = ""
            self.pending_is_image = False
            return _failure_toast(message)

    @rx.event(background=True)
    async def publish_background(self) -> AsyncIterator[None]:
        """Stage the bytes `publish` captured and start a `STORIES` publish attempt,
        then hand off to polling. Reads everything it needs from the private vars
        `publish` set — mirrors `PublishState.publish_background`'s single-item path
        exactly, with `media_product_type` fixed to `MEDIA_TYPE_STORIES` — for a video
        AND for a JPEG (QUA-113): the backend routes an image Story by its content type."""
        async with self:
            if self.phase != "staging_and_starting":
                return  # superseded, or nothing was actually queued
            connection_id = self.selected_connection_id
            idempotency_key = self._idempotency_key
            data = self._pending_bytes
            content_type = self._pending_content_type

        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            toast = await self._fail_pending(idempotency_key, _NO_TENANT)
            if toast is not None:
                yield toast
            return
        async with self:
            self._active_tenant_id = str(tenant_id)

        try:
            attempt = await start_publish(
                tenant_id=tenant_id,
                connection_id=UUID(connection_id),
                fileobj=io.BytesIO(data),
                content_type=content_type,
                media_product_type=MEDIA_TYPE_STORIES,
                # Instagram never shows a caption on a Story published via the API —
                # there is nothing here to collect or send (product decision,
                # confirmed during QUA-106 V1 manual testing).
                caption="",
                idempotency_key=idempotency_key,
            )
        except R2ConfigurationError:
            toast = await self._fail_pending(idempotency_key, _NOT_CONFIGURED)
            if toast is not None:
                yield toast
            return
        except UnsupportedImageFormat:
            toast = await self._fail_pending(idempotency_key, _UNSUPPORTED_IMAGE_FORMAT)
            if toast is not None:
                yield toast
            return
        except (ObjectSizeExceeded, UnsizedStream):
            # 8 MB for an image Story, 300 MB for a video one — same split
            # `publishing_state.py` makes for its own single item.
            size_message = _IMAGE_TOO_LARGE if content_type == _JPEG_CONTENT_TYPE else _TOO_LARGE
            toast = await self._fail_pending(idempotency_key, size_message)
            if toast is not None:
                yield toast
            return
        except (TenantPrefixViolation, ValueError):
            toast = await self._fail_pending(idempotency_key, _BAD_MEDIA)
            if toast is not None:
                yield toast
            return
        except UnknownConnection:
            toast = await self._fail_pending(idempotency_key, _UNKNOWN_CONNECTION)
            if toast is not None:
                yield toast
            return
        except Exception as exc:
            logger.error("start_publish failed: %s", type(exc).__name__)
            toast = await self._fail_pending(idempotency_key, _START_FAILED)
            if toast is not None:
                yield toast
            return

        async with self:
            # A newer attempt (a fresh click) superseded this one while we staged.
            if self._idempotency_key != idempotency_key:
                return
            self._pending_bytes = b""  # release the buffer, the staged copy is in R2
            self.attempt = attempt
            if attempt.settled:
                self.phase = "success" if attempt.status == "published" else "failure"
                if self.phase == "failure":
                    self.error = attempt.reason or _START_FAILED
                self.pending_filename = ""
            else:
                self.phase = "polling"
                self._poll_started_monotonic = time.monotonic()
            should_poll = self.phase == "polling"
            is_success = self.phase == "success"
            if is_success:
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
            yield StoriesState.poll_attempt

    @rx.event(background=True)
    async def poll_attempt(self) -> AsyncIterator[None]:
        """Client-driven polling: one `advance()` step per iteration, self-scheduling
        by yielding itself again until the attempt settles or the safety ceiling is
        hit — same shape `PublishState.poll_attempt` already has, minus the carousel
        per-child read (a Story is never a carousel)."""
        for _ in range(_MAX_POLLS):
            async with self:
                if self.phase != "polling" or self.attempt is None:
                    return
                tenant_id = tenant_uuid(self._active_tenant_id)
                attempt_id = self.attempt.attempt_id
                idempotency_key = self._idempotency_key

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
                        self.pending_filename = ""
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
                        self.pending_filename = ""
                        toast = _failure_toast(_POLL_FAILED)
                yield
                if toast is not None:
                    yield toast
                return

            async with self:
                if self._idempotency_key != idempotency_key:
                    return  # superseded by a newer attempt
                self.attempt = attempt
                if attempt.settled:
                    self.phase = "success" if attempt.status == "published" else "failure"
                    if self.phase == "failure":
                        self.error = attempt.reason or _START_FAILED
                    self.pending_filename = ""
                interval = attempt.poll_interval_seconds
                settled = attempt.settled
                is_success = self.phase == "success"
                if is_success:
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
                self.pending_filename = ""
                toast = _failure_toast(_POLL_FAILED)
        yield
        if toast is not None:
            yield toast
