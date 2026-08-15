"""Reflex state for the inbox content screen — pick which recent Reels to monitor
(Fase 1 Parte 4-B, B2 UI slice).

Reads the active tenant from `ConnectionsState.session_tenant_id` (via `self.get_state`),
same single-source-of-truth decision `publishing_state.py` already documents — one place
answers "which tenant", not a second selector duplicating it.

**The monitoring toggle never updates local state optimistically.** `toggle_monitored`
always re-fetches the full candidate list from the real backend after `set_media_
monitored` settles — success OR the caller-visible `MediaNotEligible` refusal — so the
switch on screen can never show a state Postgres does not actually hold. This is an
explicit product decision (not just this module's default), same "reload so the UI shows
the reconciled state" posture `ConnectionsState.disconnect_connection` already
established for revoke.

`sync_comments` is deliberately not called anywhere in this file — the next slice's job.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import reflex as rx
from qualify_api.inbox import MediaNotEligible, UnknownInboxConnection
from sqlalchemy.exc import SQLAlchemyError

from .connections_state import ConnectionsState
from .inbox_provider import candidate_media, instagram_connections, toggle_monitoring
from .inbox_vm import CandidateMediaVM
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

    @rx.var
    def has_connections(self) -> bool:
        return len(self.connections) > 0

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
            connections_state = await self.get_state(ConnectionsState)
            session_tenant_id = connections_state.session_tenant_id
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
            connections_state = await self.get_state(ConnectionsState)
            session_tenant_id = connections_state.session_tenant_id

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
            connections_state = await self.get_state(ConnectionsState)
            session_tenant_id = connections_state.session_tenant_id

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
            async with self:
                self.toggling_media_ids.remove(external_media_id)

        # Reload from the backend regardless of outcome, so the switch reflects reality —
        # success, a refused toggle, and an infrastructure failure all leave the DB in
        # SOME real state, and only a fresh read shows what it actually is. show_loading
        # =False: this reload must NOT blank the other rows' switches — only THIS row's
        # own `toggling_media_ids` membership (already cleared above) controls its state.
        await self._load_candidates(tenant_id, connection_id, show_loading=False)
