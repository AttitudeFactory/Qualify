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

**Fase B (m-24789645, PR 3).** `regenerate` asks the `replies.regenerate_draft` seam
for another proposal as the logged-in person (never sends), and a draft that needs
review is sent only after «Ya revisé estos puntos» (`reviewed_draft_ids`, checked inside
`_decide_and_send` through `replies_vm.send_block_reason` — the disabled button is only
a hint). The gate only adds a condition in front of the existing decide → approval →
send path; there is still exactly one way to send.

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
from qualify_api.replies.service import RegenerationRefused, UnknownDraft

from .auth_state import AuthState
from .inbox_state import InboxState
from .pending_state import PendingState
from .replies_provider import (
    DraftVM,
    acting_user,
    approval_for,
    decide_draft,
    generate_drafts,
    pending_drafts,
    regenerate_draft,
    send_draft,
)
from .replies_vm import generation_message, regenerate_error_message, send_block_reason
from .tenant import tenant_uuid

#: The element id of the lasting «Listo, le respondiste a @…» confirmation
#: (`inbox_page._replies_sent_block`), scrolled into view after a send (m-24842961).
REPLIES_SENT_ID = "q-replies-sent"

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la página e intenta de nuevo."
_NO_ACTING_USER = (
    "No encontramos tu usuario en este negocio, así que no podemos firmar la respuesta. "
    "Pide al equipo de Qualify que lo revise."
)
_GENERATE_FAILED = "No pudimos preparar las respuestas. Intenta de nuevo en unos minutos."
_DECIDE_FAILED = "No se pudo guardar la decisión. Actualiza la lista e intenta de nuevo."
# m-24842989: a decided draft leaves the «proposed» queue BEFORE the Meta call
# (`decide_draft` moves it to accepted/edited, the send to sending/sent/send_failed/
# send_ambiguous), and nothing regenerates a comment that already has a draft — so a
# failed reply does NOT stay on screen to retry. The copy says what is true: it may or
# may not be out, and the owner checks (or answers) on Instagram itself.
_SEND_FAILED = "No sabemos si salió. Revísalo en Instagram."
# The platform refused it (`send_failed`): it did not go out, and left the list.
_SEND_REFUSED = "Tu respuesta no salió. Respóndela en Instagram."
_RESULT_TOAST_DURATION_MS = 6000


def sent_message(author_username: str) -> str:
    """The confirmation once a reply is out (m-24842989): names who got it when known."""
    if author_username:
        return f"Listo, le respondiste a @{author_username} en Instagram."
    return "Listo, tu respuesta ya está en Instagram."


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
    if isinstance(exc, RegenerationRefused):
        # The gate's reason: versions and conditions, never comment text or a person.
        detail += f": {exc.reason}"
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
    # m-24842961 (N3): «Listo, le respondiste a @…» stays on screen with the next step
    # until the owner closes it or acts again — a toast alone is gone in six seconds.
    sent_notice: str = ""

    # Which draft's textarea is open for editing, and its current (uncommitted) text.
    editing_draft_id: str = ""
    edit_text: str = ""

    # m-24789645: the draft «Regenerar» is working on (it also holds `busy_draft_id`,
    # so the card's other buttons wait), and the drafts the person ticked «Ya revisé
    # estos puntos» for — a draft that needs review is not sent without it
    # (`replies_vm.send_block_reason`). A regenerated draft has a new id, so its tick
    # never carries over to text nobody has read yet.
    regenerating_draft_id: str = ""
    reviewed_draft_ids: list[str] = []

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
        """The «Preparar respuestas» button — runs the gate + generator over every
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

        # The counts stay in the log; the owner only needs what is waiting for them.
        logger.info(
            "generate_drafts: created=%d seen=%d gate_rejected=%d",
            summary.drafts_created,
            summary.candidates_seen,
            summary.gate_rejected,
        )
        yield rx.toast.success(
            generation_message(summary.drafts_created), duration=_RESULT_TOAST_DURATION_MS
        )

    def start_edit(self, draft_id: str, current_text: str) -> None:
        self.editing_draft_id = draft_id
        self.edit_text = current_text

    def cancel_edit(self) -> None:
        self.editing_draft_id = ""
        self.edit_text = ""

    def set_edit_text(self, value: str) -> None:
        self.edit_text = value

    def set_reviewed(self, draft_id: str, checked: bool) -> None:
        """The «Ya revisé estos puntos» box of one draft. Ticking it only allows the send;
        the send itself still goes through the decision + `HumanApproval` path."""
        others = [i for i in self.reviewed_draft_ids if i != draft_id]
        self.reviewed_draft_ids = [*others, draft_id] if checked else others
        if checked and self.action_error:
            self.action_error = ""

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
            # m-24789645: a draft that needs review waits for «Ya revisé estos puntos».
            # Checked here, server side — the disabled button is only a hint.
            blocked = send_block_reason(self.drafts, draft_id, self.reviewed_draft_ids)
            if blocked:
                self.action_error = blocked
            else:
                self.busy_draft_id = draft_id
                self.action_error = ""
                self.sent_notice = ""
                self.editing_draft_id = ""
            # m-24842989: for the confirmation, who the answer goes to — read before the
            # list reloads.
            author = next((d.author_username for d in self.drafts if d.id == draft_id), "")
        if blocked:
            # Also a toast: the callout sits above the list, maybe far from this card.
            yield rx.toast.error(blocked, duration=_RESULT_TOAST_DURATION_MS)
            return

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
            sent = await send_draft(
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
                self.reviewed_draft_ids = [i for i in self.reviewed_draft_ids if i != draft_id]

        yield RepliesState.load_pending_drafts
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now
        # A refusal or a transport failure at Meta does not raise: the service settles the
        # draft as `send_failed` / `send_ambiguous` and returns it. Only `sent` is «Listo».
        if sent.status != "sent":
            async with self:
                self.action_error = _SEND_REFUSED if sent.status == "send_failed" else _SEND_FAILED
            return
        async with self:
            self.sent_notice = sent_message(author)
        # On a phone the answered card vanishes and the confirmation sits above the
        # section, off screen: bring it into view, or the owner never sees the «Listo».
        yield rx.scroll_to(REPLIES_SENT_ID)

    @rx.event
    def dismiss_sent_notice(self) -> None:
        self.sent_notice = ""

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
        yield rx.toast.success("Respuesta descartada.", duration=_RESULT_TOAST_DURATION_MS)
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now

    @rx.event(background=True)
    async def regenerate(self, draft_id: str) -> AsyncGenerator[rx.event.EventSpec, None]:
        """«Regenerar» (m-24789645): ask for another proposal for a `proposed` draft, as
        the logged-in person. Never sends — the new draft lands in the queue like any
        other and still needs «Aprobar y responder». Same busy guard as the other actions,
        and the list is re-read whatever happened (a refusal usually means the draft or
        the comment changed meanwhile)."""
        async with self:
            if self.busy_draft_id:
                return
            self.busy_draft_id = draft_id
            self.regenerating_draft_id = draft_id
            self.action_error = ""
            self.editing_draft_id = ""

        resolved_draft_id = _try_uuid(draft_id)
        tenant_id, _connection_id = await self._resolve_ids()
        if tenant_id is None or resolved_draft_id is None:
            async with self:
                self.busy_draft_id = ""
                self.regenerating_draft_id = ""
                self.action_error = _NO_TENANT if tenant_id is None else _DECIDE_FAILED
            return

        user_id = await self._acting_user(tenant_id)
        if user_id is None:
            async with self:
                self.busy_draft_id = ""
                self.regenerating_draft_id = ""
                self.action_error = _NO_ACTING_USER
            return

        error = ""
        try:
            await asyncio.to_thread(
                regenerate_draft,
                tenant_id=tenant_id,
                draft_id=resolved_draft_id,
                user_id=user_id,
            )
        except Exception as exc:
            logger.error("regenerate_draft failed: %s", _safe_error_detail(exc))
            error = regenerate_error_message(exc)
            async with self:
                self.action_error = error
        finally:
            async with self:
                self.busy_draft_id = ""
                self.regenerating_draft_id = ""
                self.reviewed_draft_ids = [i for i in self.reviewed_draft_ids if i != draft_id]

        yield RepliesState.load_pending_drafts
        if error:
            # Also a toast: the callout sits above the list, maybe far from this card.
            yield rx.toast.error(error, duration=_RESULT_TOAST_DURATION_MS)
        else:
            yield rx.toast.success(
                "Listo: te propusimos otra respuesta.", duration=_RESULT_TOAST_DURATION_MS
            )
