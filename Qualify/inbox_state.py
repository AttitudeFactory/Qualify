"""Reflex state for the inbox content screen — pick which recent Reels to monitor
(Fase 1 Parte 4-B, B2 UI slice).

Reads the active tenant from `AuthState.session_tenant_id` (via `self.get_state`),
same single-source-of-truth decision `publishing_state.py` already documents — one place
answers "which tenant", not a second selector duplicating it.

**The monitoring toggle never updates local state optimistically.** `toggle_monitored`
always re-fetches the full candidate list from the real backend after `set_media_
monitored` settles — success OR the caller-visible `MediaNotEligible` refusal — so the
switch on screen can never show a state Postgres does not actually hold. This is an
explicit product decision (not just this module's default), same "reload so the UI shows
the reconciled state" posture `ConnectionsState.disconnect_connection` already
established for revoke.

**`sync_comments` (the event handler below) is a TEMPORARY manual trigger**, added
2026-08-15 to demonstrate the B2 flow end to end (monitored Reel → click → Meta →
Postgres) before a real scheduler exists — see `inbox_page.py`'s module docstring for the
UI half. It adds no sync logic of its own: `InboxService.sync_comments` already reads
only `is_monitored=True` media, so which Reels get synced is entirely decided by the
toggle above it, not by this handler. As of 2026-08-16 it reaches that service through
the real `POST /api/inbox/sync` route (B2's acceptance criterion) rather than calling
`composition.sync_comments` in-process — see `inbox_provider.sync_now`'s docstring for
how and for the one consequence worth knowing here: the bridge only authenticates ONE
dev tenant (PuntoServis), so `sync_now` raises `UnknownInboxConnection` for any other
selected tenant, surfacing as this handler's ordinary `_UNKNOWN_CONNECTION` message —
not a new failure mode this handler needs to special-case.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

import reflex as rx
from qualify_api.inbox import MediaNotEligible, UnknownInboxConnection
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .inbox_provider import candidate_media, instagram_connections, sync_now, toggle_monitoring
from .inbox_vm import CandidateMediaVM, SyncSummaryVM
from .publishing_vm import ConnectionOptionVM
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay ningún tenant activo. Entra a Conexiones y elige uno primero."
_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_LOAD_FAILED = "No se pudo cargar el contenido reciente. Revisa la conexión con Instagram."
_TOGGLE_FAILED = "No se pudo actualizar el monitoreo. Intenta de nuevo."
_TOO_OLD = "Este contenido ya no está dentro de las últimas 2 semanas y no se puede monitorear."
_NOT_ELIGIBLE = (
    "No se pudo verificar este contenido contra Instagram. Actualiza la lista e intenta de nuevo."
)
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la lista e intenta de nuevo."
_SYNC_FAILED = "No se pudo sincronizar los comentarios. Intenta de nuevo."
# Turning monitoring OFF never calls Meta (InboxService.set_media_monitored only
# re-validates against Meta when monitored=True — see its docstring); a straight Postgres
# UPDATE + reload can settle in well under 50ms, too fast for the card skeleton to ever
# be perceived. Turning ON's real Meta round-trip is not. Padding BOTH to at least this
# long makes the skeleton behave identically regardless of direction — a pure UI-timing
# floor, not a change to how fast the real operation is.
_MIN_TOGGLE_ANIMATION_SECONDS = 0.5


class InboxState(rx.State):
    """State for the "Contenido" screen: pick an Instagram connection, see its Reels
    from the last 2 weeks, toggle which ones are monitored."""

    connections: list[ConnectionOptionVM] = []
    selected_connection_id: str = ""
    is_loading_connections: bool = False
    connections_error: str = ""

    candidates: list[CandidateMediaVM] = []
    is_loading_candidates: bool = False
    load_error: str = ""
    # Errors from the toggle action, kept apart from `load_error`: a refused toggle must
    # not blank the list the operator is looking at.
    action_error: str = ""
    # Media ids whose switch is mid-flight, so each row can disable itself against a
    # double-click on ITSELF while staying independent of every other row — a list
    # (not a single id) so toggling Reel B while Reel A is still in flight starts its
    # own operation instead of being silently ignored.
    toggling_media_ids: list[str] = []

    # TEMPORARY manual-sync affordance (see module docstring). Screen-wide, not per-row —
    # unlike toggling_media_ids, a sync pass has no single Reel it belongs to.
    is_syncing: bool = False
    sync_error: str = ""
    sync_result: SyncSummaryVM | None = None

    @rx.var
    def has_connections(self) -> bool:
        return len(self.connections) > 0

    @rx.var
    def can_sync(self) -> bool:
        return bool(self.selected_connection_id) and not self.is_syncing

    @rx.var
    def show_empty_state(self) -> bool:
        return (
            not self.is_loading_candidates
            and not self.load_error
            and bool(self.selected_connection_id)
            and len(self.candidates) == 0
        )

    async def _load_candidates(
        self, tenant_id: UUID, connection_id: str, *, show_loading: bool = True
    ) -> None:
        """Shared by the initial load, a connection switch, and every toggle's
        post-action reload. Private (not `@rx.event`) — same role `PublishState.
        _fail_pending_attempt` has, a helper called FROM background handlers, not one
        itself.

        `show_loading=False` is what `toggle_monitored` passes: `is_loading_candidates`
        drives `_candidates_body()`'s full-list skeleton swap in `inbox_page.py`, which
        is correct for the initial load / a connection switch (nothing valid to show
        yet) but was WRONG for a toggle's reload — it blanked every row's switch, not
        just the one being toggled, which is what a per-row `disabled` binding
        (`toggling_media_ids`) already exists to do on its own.
        """
        async with self:
            if show_loading:
                self.is_loading_candidates = True
            self.load_error = ""

        try:
            resolved_connection = UUID(connection_id)
        except ValueError:
            async with self:
                self.is_loading_candidates = False
            return

        try:
            items = await candidate_media(tenant_id=tenant_id, connection_id=resolved_connection)
        except UnknownInboxConnection:
            async with self:
                self.is_loading_candidates = False
                self.load_error = _UNKNOWN_CONNECTION
            return
        except Exception as exc:
            # Only the exception TYPE is logged — same posture as connections_state.py's
            # loader for infrastructure/Meta errors that may carry connection details.
            logger.error("candidate_media failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_candidates = False
                self.load_error = _LOAD_FAILED
            return

        async with self:
            # Guard against a connection switch that raced this load.
            if connection_id == self.selected_connection_id:
                self.candidates = items
                self.is_loading_candidates = False

    @rx.event(background=True)
    async def load_screen(self) -> None:
        """Load the operator's eligible Instagram connections, then the last-2-weeks
        Reels for the first one — mirrors `ConnectionsState.load_connections`'s single
        combined loader rather than `PublishState`'s separate load+select, since this
        screen has nothing useful to show without a connection already selected."""
        async with self:
            self.is_loading_connections = True
            self.connections_error = ""

        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_TENANT
            return

        try:
            options = await asyncio.to_thread(instagram_connections, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("instagram_connections failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_CONNECTIONS
            return

        async with self:
            self.connections = options
            self.is_loading_connections = False
            if options and not self.selected_connection_id:
                self.selected_connection_id = options[0].id
            connection_id = self.selected_connection_id

        if connection_id:
            await self._load_candidates(tenant_id, connection_id)

    @rx.event(background=True)
    async def select_connection(self, connection_id: str) -> None:
        """Dev-only-adjacent: switch which connection's content is shown."""
        async with self:
            if not any(option.id == connection_id for option in self.connections):
                return
            self.selected_connection_id = connection_id
            self.candidates = []
            self.action_error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        if tenant_id is None:
            return
        await self._load_candidates(tenant_id, connection_id)

    @rx.event(background=True)
    async def toggle_monitored(self, external_media_id: str, monitored: bool) -> None:
        """Flip one Reel's monitoring toggle through the real B2 service, then ALWAYS
        reload the whole candidate list from the backend — see the module docstring for
        why this is never an optimistic local update."""
        async with self:
            if external_media_id in self.toggling_media_ids:
                return  # THIS row already has a toggle in flight; ignore a double-click
            self.toggling_media_ids.append(external_media_id)
            self.action_error = ""
            connection_id = self.selected_connection_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        started_at = time.monotonic()

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection: UUID | None = None
        if connection_id:
            try:
                resolved_connection = UUID(connection_id)
            except ValueError:
                resolved_connection = None

        if tenant_id is None or resolved_connection is None:
            async with self:
                self.toggling_media_ids.remove(external_media_id)
                self.action_error = _NO_TENANT
            return

        try:
            await toggle_monitoring(
                tenant_id=tenant_id,
                connection_id=resolved_connection,
                external_media_id=external_media_id,
                monitored=monitored,
            )
        except MediaNotEligible as exc:
            async with self:
                self.action_error = _TOO_OLD if exc.reason == "too_old" else _NOT_ELIGIBLE
        except UnknownInboxConnection:
            async with self:
                self.action_error = _UNKNOWN_CONNECTION
        except Exception as exc:
            logger.error("toggle_monitoring failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _TOGGLE_FAILED
        finally:
            # Pad OUT here, before clearing `toggling_media_ids` — this is what makes
            # OFF (a bare Postgres write) show the same card skeleton for the same
            # minimum duration as ON (a real Meta round-trip), see
            # `_MIN_TOGGLE_ANIMATION_SECONDS`'s docstring.
            remaining = _MIN_TOGGLE_ANIMATION_SECONDS - (time.monotonic() - started_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            async with self:
                self.toggling_media_ids.remove(external_media_id)

        # Reload from the backend regardless of outcome, so the switch reflects reality —
        # success, a refused toggle, and an infrastructure failure all leave the DB in
        # SOME real state, and only a fresh read shows what it actually is. show_loading
        # =False: this reload must NOT blank the other rows' switches — only THIS row's
        # own `toggling_media_ids` membership (already cleared above) controls its state.
        await self._load_candidates(tenant_id, connection_id, show_loading=False)

    @rx.event(background=True)
    async def sync_comments(self) -> None:
        """TEMPORARY manual trigger for `InboxService.sync_comments` (B2) — see the
        module docstring. Never touches `candidates`/`toggling_media_ids`: a sync pass
        writes to `threads`/`messages`, never to `monitored_media`, so the Reel list has
        nothing to reload afterward — unlike `toggle_monitored`, this handler's only
        externally visible effect is `sync_result`/`sync_error`.
        """
        async with self:
            if self.is_syncing:
                return  # a sync is already in flight; ignore a rapid double-click
            self.is_syncing = True
            self.sync_error = ""
            self.sync_result = None
            connection_id = self.selected_connection_id
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        tenant_id = tenant_uuid(session_tenant_id)
        resolved_connection: UUID | None = None
        if connection_id:
            try:
                resolved_connection = UUID(connection_id)
            except ValueError:
                resolved_connection = None

        if tenant_id is None or resolved_connection is None:
            async with self:
                self.is_syncing = False
                self.sync_error = _NO_TENANT
            return

        try:
            result = await sync_now(tenant_id=tenant_id, connection_id=resolved_connection)
        except UnknownInboxConnection:
            async with self:
                self.sync_error = _UNKNOWN_CONNECTION
            return
        except Exception as exc:
            # Only the exception TYPE is logged — same posture as every other handler in
            # this file for infrastructure/Meta errors that may carry connection details.
            logger.error("sync_now failed: %s", type(exc).__name__)
            async with self:
                self.sync_error = _SYNC_FAILED
            return
        else:
            async with self:
                self.sync_result = result
        finally:
            async with self:
                self.is_syncing = False
