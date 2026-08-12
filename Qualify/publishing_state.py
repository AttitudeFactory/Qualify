"""Reflex state for the publish screen (A5 vertical slice).

Reads the active tenant from `ConnectionsState.session_tenant_id` (via `self.get_state`)
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
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.publishing.service import UnknownAttempt, UnknownConnection
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectSizeExceeded, UnsizedStream
from qualify_shared.objects.keys import TenantPrefixViolation

from .connections_state import ConnectionsState
from .publishing_provider import PublishAttemptVM, active_connections, poll_publish, start_publish
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
# Client-side safety net only — the SERVER already settles an attempt as 'failed' once
# CONTAINER_POLL_CEILING_SECONDS (300 s) elapses, at roughly one poll per
# CONTAINER_POLL_INTERVAL_SECONDS (60 s). This is just the belt on top of that suspenders,
# in case a future response ever advertises an unexpectedly short interval.
_MAX_POLLS = 30


class PublishState(rx.State):
    """State for the "Publicar" screen: pick a connected account, upload a reel, publish."""

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
    # slow staging/publish work) — see the module docstring's deviation note.
    _pending_bytes: bytes = b""
    _pending_content_type: str = ""
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
            connections_state = await self.get_state(ConnectionsState)
            session_tenant_id = connections_state.session_tenant_id
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
            return None

        upload = files[0]
        content_type = getattr(upload, "content_type", None) or "video/mp4"
        try:
            data = await upload.read()
        except Exception:
            self.phase = "failure"
            self.error = _BAD_MEDIA
            return None

        self._pending_bytes = data
        self._pending_content_type = content_type
        self._idempotency_key = uuid4().hex
        self.phase = "staging_and_starting"
        self.error = ""
        self.attempt = None
        return PublishState.publish_background

    async def _fail_pending_attempt(self, idempotency_key: str, message: str) -> None:
        """Record a failure for the attempt `idempotency_key` names, and release the
        buffered upload.

        Called from EVERY failure branch in `publish_background` (including the
        pre-staging `tenant_id is None` case) so none of them can leave `_pending_bytes`
        holding a full video (up to 300 MB) in this session's memory after a failed
        attempt — previously only the success path cleared it. Guarded by the
        idempotency key: a stale (superseded) attempt's failure must not clobber a
        newer attempt's in-progress state, and must not clear a newer attempt's
        `_pending_bytes` out from under it.
        """
        async with self:
            if self._idempotency_key != idempotency_key:
                return
            self.phase = "failure"
            self.error = message
            self._pending_bytes = b""

    @rx.event(background=True)
    async def publish_background(self) -> AsyncIterator[None]:
        """Stage the bytes `publish` captured and start a publish attempt, then hand off
        to polling. Reads everything it needs from the private vars `publish` set."""
        async with self:
            if self.phase != "staging_and_starting":
                return  # superseded, or nothing was actually queued
            connection_id = self.selected_connection_id
            caption = self.caption
            idempotency_key = self._idempotency_key
            data = self._pending_bytes
            content_type = self._pending_content_type

        async with self:
            connections_state = await self.get_state(ConnectionsState)
            session_tenant_id = connections_state.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            await self._fail_pending_attempt(idempotency_key, _NO_TENANT)
            return
        async with self:
            self._active_tenant_id = str(tenant_id)

        try:
            attempt = await start_publish(
                tenant_id=tenant_id,
                connection_id=UUID(connection_id),
                fileobj=io.BytesIO(data),
                content_type=content_type,
                caption=caption,
                idempotency_key=idempotency_key,
            )
        except R2ConfigurationError:
            await self._fail_pending_attempt(idempotency_key, _NOT_CONFIGURED)
            return
        except (ObjectSizeExceeded, UnsizedStream):
            await self._fail_pending_attempt(idempotency_key, _TOO_LARGE)
            return
        except (TenantPrefixViolation, ValueError):
            await self._fail_pending_attempt(idempotency_key, _BAD_MEDIA)
            return
        except UnknownConnection:
            await self._fail_pending_attempt(idempotency_key, _UNKNOWN_CONNECTION)
            return
        except Exception as exc:
            logger.error("start_publish failed: %s", type(exc).__name__)
            await self._fail_pending_attempt(idempotency_key, _START_FAILED)
            return

        async with self:
            # A newer attempt (a fresh click) superseded this one while we staged.
            if self._idempotency_key != idempotency_key:
                return
            self._pending_bytes = b""  # release the buffer, staged copy already in R2
            self.attempt = attempt
            if attempt.settled:
                self.phase = "success" if attempt.status == "published" else "failure"
                if self.phase == "failure":
                    self.error = attempt.reason or _START_FAILED
            else:
                self.phase = "polling"
            should_poll = self.phase == "polling"
        yield

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
                async with self:
                    if self._idempotency_key == idempotency_key:
                        self.phase = "failure"
                        self.error = _POLL_FAILED
                yield
                return
            except Exception as exc:
                logger.error("poll_publish failed: %s", type(exc).__name__)
                async with self:
                    if self._idempotency_key == idempotency_key:
                        self.phase = "failure"
                        self.error = _POLL_FAILED
                yield
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
            yield
            if settled:
                return
            await asyncio.sleep(interval)

        async with self:
            if self._idempotency_key == idempotency_key and self.phase == "polling":
                self.phase = "failure"
                self.error = _POLL_FAILED
        yield
