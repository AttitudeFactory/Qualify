"""Reflex state for the assisted-reply panel on `/inbox` (QUA-22, comments tranche
only). Reads the active tenant from `AuthState.session_tenant_id` and the selected
connection from `InboxState.selected_connection_id` (both via `self.get_state`) — same
single-source-of-truth composition `inbox_state.py` itself documents for `AuthState` —
kept as a SEPARATE `rx.State` rather than folded into `InboxState` because this
panel's lifecycle (generate → decide → send) is independent of the
Reel-monitoring/comment-sync flow `InboxState` owns, same reasoning `mentions_provider`
stays its own module rather than growing `InboxState` further.

**Acting user: the logged-in person (m-24789645).** `AuthState.user_email` resolved to
this tenant's `users.id` through `replies_provider.acting_user` — the same resolution
Conversaciones uses for its `HumanApproval`, read through `tenant_session` so it can only
ever resolve to that tenant's own user. It stamps the decision (`decided_by_user_id`)
and the `HumanApproval` the send demands (`replies_provider.approval_for`). It used to
be the tenant's `owner` row (`connections_provider.acting_user_id`), which attributed
every approval to the owner whoever clicked.

**Two Reflex background-task constraints, both hit and fixed during manual testing
(2026-09-04) — neither is optional, both are enforced at runtime, not just style:**

1. `self.get_state(...)` must be called INSIDE `async with self:` — a background
   task's `self` is an immutable `StateProxy` outside that block for EVERY operation,
   not only attribute writes (`ImmutableStateError` otherwise). See `_resolve_ids`.
2. One `@rx.event(background=True)` handler cannot `await` another background
   handler directly — Reflex raises `RuntimeError` on that (`_no_chain_background_task_co`)
   and requires `yield OtherState.handler` instead. Because introducing a `yield`
   turns a function into an async generator, and Python forbids `return <value>` (even
   `return None`) inside one, every "return an EventSpec" exit below had to become a
   `yield`, and every early exit had to become a bare `return`. `_decide_and_send` is
   therefore a plain async-generator HELPER (no `@rx.event` of its own — it is never
   called directly from the frontend), and `accept_and_send`/`save_and_send` forward
   its yielded events with `async for event in self._decide_and_send(...): yield event`.

**v1 scoping decision — no separate "accepted, awaiting send" queue.** A human
decision (`accept`/`edit`/`discard`) and the resulting Meta send are folded into ONE
click here (`accept_and_send`/`save_and_send`) rather than two separate steps with a
visible "outbox" in between. This still satisfies QUA-22's "ninguna respuesta se envía
sin acción humana explícita": the human's click IS the explicit approval that precedes
the send, in the same request — there is no code path that sends without it. What this
v1 does NOT support: reviewing a batch of accepted drafts and sending them all later
in a second sitting. That is a real, disclosed gap for a fast-follow, not silently
assumed away — `qualify_api.replies` itself supports the two-step flow (`decide` then
`send` are separate service calls); only this UI collapses them.

Every handler below only ever touches comment-channel drafts — `qualify_api.replies`
has no DM code path at all (QUA-20/QUA-69 stay untouched, see that module's own
docstring).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from uuid import UUID

import reflex as rx
from qualify_api.claude_tools import ClaudeToolError
from qualify_api.replies.service import UnknownDraft

from .auth_state import AuthState
from .inbox_state import InboxState
from .replies_provider import (
    DraftVM,
    acting_user,
    approval_for,
    decide_draft,
    generate_drafts,
    pending_drafts,
    send_draft,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la página e intenta de nuevo."
_NO_ACTING_USER = (
    "No encontramos tu usuario en este negocio, así que no podemos firmar la respuesta. "
    "Pide al equipo de Qualify que lo revise."
)
_GENERATE_FAILED = "No se pudieron generar los borradores. Intenta de nuevo en unos minutos."
_DECIDE_FAILED = "No se pudo guardar la decisión. Actualiza la lista e intenta de nuevo."
_SEND_FAILED = "No se pudo enviar la respuesta a Meta. El borrador quedó marcado para revisión."
_RESULT_TOAST_DURATION_MS = 6000


def _try_uuid(value: str) -> UUID | None:
    """Duplicated from `inbox_state._try_uuid` rather than imported — same
    self-containment discipline every module in this codebase already follows for its
    own small helpers."""
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _safe_error_detail(exc: Exception) -> str:
    """The exception TYPE, as every loader here logs — plus the detail only where it is
    known to carry no connection data: our own Claude errors (model id, never comment
    text or keys) and an HTTP status code. A bare type ("ValueError") once hid that
    production had no model credential at all (QUA-128)."""
    detail = type(exc).__name__
    if isinstance(exc, ClaudeToolError):
        detail += f": {exc}"
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        detail += f" (HTTP {status})"
    return detail


class RepliesState(rx.State):
    drafts: list[DraftVM] = []
    is_loading: bool = False
    load_error: str = ""

    is_generating: bool = False
    generate_error: str = ""

    # The one draft currently mid-action (decide+send, or discard) — disables ONLY
    # that draft's buttons, so reviewing one comment never blocks acting on another.
    busy_draft_id: str = ""
    action_error: str = ""

    # Which draft's textarea is open for editing, and its current (uncommitted) text.
    editing_draft_id: str = ""
    edit_text: str = ""

    @rx.var
    def has_pending_drafts(self) -> bool:
        return len(self.drafts) > 0

    async def _resolve_ids(self) -> tuple[UUID | None, UUID | None]:
        """`(tenant_id, connection_id)` — both `None`-safe; callers branch on whichever
        came back `None` to pick the right message.

        `get_state` MUST be called inside `async with self:` for a background-task
        `StateProxy` — see this module's docstring, constraint 1."""
        async with self:
            auth = await self.get_state(AuthState)
            inbox = await self.get_state(InboxState)
            return tenant_uuid(auth.session_tenant_id), _try_uuid(inbox.selected_connection_id)

    async def _acting_user(self, tenant_id: UUID) -> UUID | None:
        """The logged-in person's `users.id` (session email → `users`), or None. Same
        `get_state`-inside-`async with self:` rule as `_resolve_ids`."""
        async with self:
            auth = await self.get_state(AuthState)
            email = auth.user_email
        return await asyncio.to_thread(acting_user, tenant_id, email)

    @rx.event(background=True)
    async def load_pending_drafts(self) -> None:
        """Manual/`on_mount` refresh of the review queue — same "no optimistic local
        state, always re-read after any write" posture `inbox_state.py`'s module
        docstring establishes for its own toggle.

        Never itself `yield`s an event (no other handler needs to chain off ITS
        completion), so it stays a plain `async def` — safe to reach via
        `yield RepliesState.load_pending_drafts` from every other handler below."""
        async with self:
            self.is_loading = True
            self.load_error = ""
        tenant_id, connection_id = await self._resolve_ids()
        if tenant_id is None or connection_id is None:
            async with self:
                self.is_loading = False
                self.load_error = _NO_TENANT if tenant_id is None else _UNKNOWN_CONNECTION
                self.drafts = []
            return
        # m-24842989: the publication thumbnails come from the inbox's already-loaded
        # candidates (`load_screen`/`select_connection` load them before chaining here).
        async with self:
            inbox = await self.get_state(InboxState)
            candidates = list(inbox.candidates)
        try:
            drafts = await asyncio.to_thread(
                pending_drafts,
                tenant_id=tenant_id,
                connection_id=connection_id,
                candidates=candidates,
            )
        except Exception as exc:
            logger.error("pending_drafts failed: %s", type(exc).__name__)
            async with self:
                self.load_error = _UNKNOWN_CONNECTION
                self.drafts = []
        else:
            async with self:
                self.drafts = drafts
        finally:
            async with self:
                self.is_loading = False

    @rx.event(background=True)
    async def generate_drafts(self) -> AsyncGenerator[rx.event.EventSpec, None]:
        """The "Generar borradores" button — runs the gate + generator over every
        pending POS comment for the selected connection. Same double-click guard /
        try-except-else-finally shape `InboxState.analyze_sentiment` establishes.

        An async generator (module docstring, constraint 2): every early exit below
        is a bare `return`, and the two "tell the frontend something" moments
        (refresh the list, show the result toast) are `yield`s, not `return`s."""
        async with self:
            if self.is_generating:
                return
            self.is_generating = True
            self.generate_error = ""
        tenant_id, connection_id = await self._resolve_ids()
        if tenant_id is None or connection_id is None:
            async with self:
                self.is_generating = False
                self.generate_error = _NO_TENANT if tenant_id is None else _UNKNOWN_CONNECTION
            return
        try:
            summary = await asyncio.to_thread(
                generate_drafts, tenant_id=tenant_id, connection_id=connection_id
            )
        except Exception as exc:
            logger.error("generate_drafts failed: %s", _safe_error_detail(exc))
            async with self:
                self.generate_error = _GENERATE_FAILED
            return
        finally:
            async with self:
                self.is_generating = False

        yield RepliesState.load_pending_drafts

        if summary.drafts_created == 0:
            message = "No hay comentarios positivos nuevos para redactar una respuesta."
        else:
            message = (
                f"Borradores nuevos: {summary.drafts_created} · "
                f"Comentarios revisados: {summary.candidates_seen} · "
                f"Descartados por la puerta: {summary.gate_rejected}"
            )
        yield rx.toast.success(message, duration=_RESULT_TOAST_DURATION_MS)

    def start_edit(self, draft_id: str, current_text: str) -> None:
        self.editing_draft_id = draft_id
        self.edit_text = current_text

    def cancel_edit(self) -> None:
        self.editing_draft_id = ""
        self.edit_text = ""

    def set_edit_text(self, value: str) -> None:
        self.edit_text = value

    @rx.event(background=True)
    async def accept_and_send(self, draft_id: str) -> AsyncGenerator[rx.event.EventSpec, None]:
        """Accept a draft AS GENERATED and send it — one human click, the explicit
        approval QUA-22 requires, immediately followed by the real Meta call."""
        async for event in self._decide_and_send(draft_id, decision="accepted", final_text=None):
            yield event

    @rx.event(background=True)
    async def save_and_send(self, draft_id: str) -> AsyncGenerator[rx.event.EventSpec, None]:
        """Accept a draft WITH EDITS and send it. `edit_text` is read at call time —
        it is already bound to the open textarea, never passed in from the click."""
        async with self:
            final_text = self.edit_text
        async for event in self._decide_and_send(
            draft_id, decision="edited", final_text=final_text
        ):
            yield event

    async def _decide_and_send(
        self, draft_id: str, *, decision: str, final_text: str | None
    ) -> AsyncGenerator[rx.event.EventSpec, None]:
        """Plain async-generator HELPER, not its own `@rx.event` — never bound to a
        frontend click directly (module docstring, constraint 2). Its two public
        callers above forward every event it yields verbatim."""
        async with self:
            if self.busy_draft_id:
                return  # another action on some draft is already in flight
            self.busy_draft_id = draft_id
            self.action_error = ""
            self.editing_draft_id = ""

        resolved_draft_id = _try_uuid(draft_id)
        tenant_id, _connection_id = await self._resolve_ids()
        if tenant_id is None or resolved_draft_id is None:
            async with self:
                self.busy_draft_id = ""
                self.action_error = _NO_TENANT if tenant_id is None else _DECIDE_FAILED
            return

        user_id = await self._acting_user(tenant_id)
        if user_id is None:
            async with self:
                self.busy_draft_id = ""
                self.action_error = _NO_ACTING_USER
            return

        try:
            await asyncio.to_thread(
                decide_draft,
                tenant_id=tenant_id,
                draft_id=resolved_draft_id,
                decision=decision,
                final_text=final_text,
                decided_by_user_id=user_id,
            )
        except Exception as exc:
            logger.error("decide_draft failed: %s", type(exc).__name__)
            async with self:
                self.busy_draft_id = ""
                self.action_error = _DECIDE_FAILED
            return

        try:
            await send_draft(
                tenant_id=tenant_id,
                draft_id=resolved_draft_id,
                approval=approval_for(user_id=user_id, draft_id=resolved_draft_id),
            )
        except UnknownDraft:
            async with self:
                self.busy_draft_id = ""
                self.action_error = _UNKNOWN_CONNECTION
            yield RepliesState.load_pending_drafts
            return
        except Exception as exc:
            logger.error("send_draft failed: %s", type(exc).__name__)
            async with self:
                self.busy_draft_id = ""
                self.action_error = _SEND_FAILED
            yield RepliesState.load_pending_drafts
            return
        finally:
            async with self:
                self.busy_draft_id = ""
                self.edit_text = ""

        yield RepliesState.load_pending_drafts
        yield rx.toast.success("Respuesta enviada.", duration=_RESULT_TOAST_DURATION_MS)

    @rx.event(background=True)
    async def discard_draft(self, draft_id: str) -> AsyncGenerator[rx.event.EventSpec, None]:
        async with self:
            if self.busy_draft_id:
                return
            self.busy_draft_id = draft_id
            self.action_error = ""

        resolved_draft_id = _try_uuid(draft_id)
        tenant_id, _connection_id = await self._resolve_ids()
        if tenant_id is None or resolved_draft_id is None:
            async with self:
                self.busy_draft_id = ""
                self.action_error = _NO_TENANT if tenant_id is None else _DECIDE_FAILED
            return

        user_id = await self._acting_user(tenant_id)
        if user_id is None:
            async with self:
                self.busy_draft_id = ""
                self.action_error = _NO_ACTING_USER
            return

        try:
            await asyncio.to_thread(
                decide_draft,
                tenant_id=tenant_id,
                draft_id=resolved_draft_id,
                decision="discarded",
                final_text=None,
                decided_by_user_id=user_id,
            )
        except Exception as exc:
            logger.error("discard decide_draft failed: %s", type(exc).__name__)
            async with self:
                self.busy_draft_id = ""
                self.action_error = _DECIDE_FAILED
            return
        finally:
            async with self:
                self.busy_draft_id = ""

        yield RepliesState.load_pending_drafts
        yield rx.toast.success("Borrador descartado.", duration=_RESULT_TOAST_DURATION_MS)
