"""Reflex state for the publish screen (A5 vertical slice).

Reads the active tenant from `AuthState.session_tenant_id` (via `self.get_state`)
rather than duplicating the dev tenant selector — one source of truth for "which tenant"
(decision 7 of the approved plan).

**Deviation from the approved plan, discovered while building it (not a scope change):**
the plan called for a single `publish` handler, `@rx.event(background=True)`, receiving
`files: list[rx.UploadFile]` directly. The Reflex version installed here forbids that
combination outright — `resolve_upload_handler_param` raises `UploadTypeError` for any
upload-receiving handler marked `background=True` (verified by constructing the page:
`.venv/Lib/site-packages/reflex_base/event/__init__.py:330-340`). So the upload is
received by a small FOREGROUND `publish` handler that only reads the bytes and hands off
to `publish_background` (`background=True`, no upload parameter) for the actual
staging/starting work. Same phases, same seam calls, same user-visible behavior — just
split across the one boundary Reflex actually enforces.

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
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.publishing.service import TooManyItems, UnknownAttempt, UnknownConnection
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectSizeExceeded, UnsizedStream
from qualify_shared.objects.keys import TenantPrefixViolation

from .auth_state import AuthState
from .publishing_provider import (
    PendingUpload,
    PublishAttemptVM,
    active_connections,
    poll_publish,
    start_many_publish,
    start_publish,
)
from .publishing_vm import ConnectionOptionVM
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay ningún tenant activo. Entra a Conexiones y elige uno primero."
_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_NO_CONNECTION_SELECTED = "Elige una cuenta conectada antes de publicar."
_NOT_CONFIGURED = "El almacenamiento (R2) todavía no está configurado en este entorno."
_TOO_LARGE = "El video supera el tamaño máximo permitido (300 MB)."
_BAD_MEDIA = "No se pudo leer el archivo subido. Intenta con otro video."
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la lista e intenta de nuevo."
_START_FAILED = "No se pudo iniciar la publicación. Vuelve a intentarlo en un momento."
_POLL_FAILED = "No se pudo consultar el estado de la publicación."
# QUA-99 (6/6): Meta caps a carousel at 10 items (client.py's MAX_CAROUSEL_ITEMS,
# service.py). Checked HERE too, before a single byte is read off the upload — the
# dropzone's own `max_files=10` (publishing_page.py) is the client-side nicety on top of
# this, same "server-side guard is the real invariant" posture the double-submit check
# below already documents.
_MAX_ITEMS = 10
_TOO_MANY = f"Puedes publicar hasta {_MAX_ITEMS} videos a la vez."
# Client-side safety net only — the SERVER already settles an attempt as 'failed' once
# CONTAINER_POLL_CEILING_SECONDS (300 s) elapses, at roughly one poll per
# CONTAINER_POLL_INTERVAL_SECONDS (60 s). This is just the belt on top of that suspenders,
# in case a future response ever advertises an unexpectedly short interval.
_MAX_POLLS = 30

# The upload widget's id — lives here (not in publishing_page.py) because this module
# needs it too, to clear the dropzone's client-side selection after a successful publish
# (`rx.clear_selected_files`). The page imports this constant rather than keeping its own
# copy, so the two can never drift apart.
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
    preserved end to end, never re-sorted."""

    content_type: str
    data: bytes


class PublishState(rx.State):
    """State for the "Publicar" screen: pick a connected account, upload 1-10 videos
    (2-10 publish as one carousel, QUA-99), publish."""

    connections: list[ConnectionOptionVM] = []
    is_loading_connections: bool = False
    load_error: str = ""

    selected_connection_id: str = ""
    caption: str = ""

    # idle | staging_and_starting | polling | success | failure
    phase: str = "idle"
    attempt: PublishAttemptVM | None = None
    error: str = ""

    # Private: bridges the foreground `publish` handler (which alone may receive the
    # upload) to the background `publish_background` handler (which alone may do the
    # slow staging/publish work) — see the module docstring's deviation note. A list
    # (QUA-99, 6/6) rather than a single buffer — how many items it holds is what decides,
    # inside `publish_background`, whether the existing single-video path or the carousel
    # path runs; the UI itself never makes that choice.
    _pending_files: list[_PendingFile] = []
    # Generated once per publish attempt, preserved across its polls, never regenerated
    # by a poll itself. A new click on "Publicar" after a failure generates a fresh one
    # (decision 3 of the approved plan).
    _idempotency_key: str = ""
    _active_tenant_id: str = ""

    @rx.var
    def can_publish(self) -> bool:
        return bool(self.selected_connection_id) and self.phase in ("idle", "success", "failure")

    @rx.event(background=True)
    async def load_active_connections(self) -> None:
        """Load the active connections for the current session tenant."""
        async with self:
            self.is_loading_connections = True
            self.load_error = ""

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

    @rx.event
    def set_caption(self, value: str) -> None:
        self.caption = value

    @rx.event
    def select_connection(self, connection_id: str) -> None:
        self.selected_connection_id = connection_id

    @rx.event
    async def publish(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Receive the upload and hand off to `publish_background`.

        Must NOT be `background=True` — Reflex forbids that combination for a handler
        that receives `list[rx.UploadFile]` (see the module docstring). Reading the
        upload is quick local I/O; the actual network work happens in the handler this
        hands off to.

        The `self.phase` check below is the SERVER-SIDE guard against a double-submit —
        `can_publish`/`disabled=` on the button in `publishing_page.py` is a UX nicety on
        top of it, not the actual invariant. It is sufficient on its own: `publish` is a
        FOREGROUND handler, and Reflex serializes foreground events per session (its
        per-token event queue) — background events like `publish_background` do not get
        that ordering. So without this check, two rapid submissions could each pass
        through to `publish_background` and each start a REAL publish against Meta before
        either settles; the `_idempotency_key` guard inside `publish_background` only
        stops the superseded one from corrupting the UI's final state, it does not stop
        it from having already published something. With this check, the second `publish`
        call is rejected here, before a second `publish_background` is ever dispatched.
        """
        if not files:
            return None
        if self.phase not in ("idle", "success", "failure"):
            return None  # a publish is already in flight for this session
        if not self.selected_connection_id:
            self.phase = "failure"
            self.error = _NO_CONNECTION_SELECTED
            return _failure_toast(_NO_CONNECTION_SELECTED)
        if len(files) > _MAX_ITEMS:
            # Rejected BEFORE reading a single byte — no staging, no R2, no Meta call.
            # The dropzone's max_files=10 already stops this in the common case; this is
            # the real, server-side invariant behind that client-side nicety.
            self.phase = "failure"
            self.error = _TOO_MANY
            return _failure_toast(_TOO_MANY)

        pending: list[_PendingFile] = []
        for upload in files:
            content_type = getattr(upload, "content_type", None) or "video/mp4"
            try:
                data = await upload.read()
            except Exception:
                self.phase = "failure"
                self.error = _BAD_MEDIA
                return _failure_toast(_BAD_MEDIA)
            pending.append(_PendingFile(content_type=content_type, data=data))

        self._pending_files = pending
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
        `_pending_files` out from under it.
        """
        async with self:
            if self._idempotency_key != idempotency_key:
                return None
            self.phase = "failure"
            self.error = message
            self._pending_files = []
            return _failure_toast(message)

    @rx.event(background=True)
    async def publish_background(self) -> AsyncIterator[None]:
        """Stage the bytes `publish` captured and start a publish attempt, then hand off
        to polling. Reads everything it needs from the private vars `publish` set.

        QUA-99 (6/6): the only new decision here is `len(pending)` — 1 item calls
        `start_publish` (UNCHANGED code path, byte-for-byte the same call QUA-19 always
        made), 2-10 calls `start_many_publish` (QUA-99 5/6). Everything AFTER that split
        — the try/except tree, the phase transitions, the toasts, the poll handoff — is
        the SAME code for both: one unified machine, not two parallel ones. Both provider
        functions raise the same exception set (R2ConfigurationError,
        ObjectSizeExceeded/UnsizedStream, TenantPrefixViolation/ValueError,
        UnknownConnection), plus `TooManyItems` for the multi path only — a single
        `except` clause covers it too, as defense-in-depth behind `publish`'s own
        earlier, cheaper rejection.
        """
        async with self:
            if self.phase != "staging_and_starting":
                return  # superseded, or nothing was actually queued
            connection_id = self.selected_connection_id
            caption = self.caption
            idempotency_key = self._idempotency_key
            pending = list(self._pending_files)

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
                attempt = await start_publish(
                    tenant_id=tenant_id,
                    connection_id=UUID(connection_id),
                    fileobj=io.BytesIO(item.data),
                    content_type=item.content_type,
                    caption=caption,
                    idempotency_key=idempotency_key,
                )
            else:
                attempt = await start_many_publish(
                    tenant_id=tenant_id,
                    connection_id=UUID(connection_id),
                    items=[
                        PendingUpload(fileobj=io.BytesIO(p.data), content_type=p.content_type)
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
        except (ObjectSizeExceeded, UnsizedStream):
            toast = await self._fail_pending_attempt(idempotency_key, _TOO_LARGE)
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
            else:
                self.phase = "polling"
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
            yield rx.clear_selected_files(_UPLOAD_ID)
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
                yield rx.clear_selected_files(_UPLOAD_ID)
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
                toast = _failure_toast(_POLL_FAILED)
        yield
        if toast is not None:
            yield toast
