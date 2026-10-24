"""Reflex state for «Consultas desde comentarios» (m-24789646, PR 3), the second view of
`/conversations`: the commercial queries found in Interacciones, each with its draft, that
a person reviews, edits, regenerates, discards or approves.

Custody, the same as `ConversationsState`: the tenant comes from `AuthState` (server
side, through `get_state`, never as an event argument); the browser holds only frozen VMs
and the text being edited; every Postgres or Claude call runs in a background event
through `asyncio.to_thread`. An id arriving from the browser is accepted only if the
loaded cards hold it.

**Views.** «Mensajes» is the inbox as it always was; «Consultas desde comentarios» lists
the open followups (`followups_count` in the toggle). `/conversations?consulta=<id>` —
where «Responder por DM» in Interacciones lands — opens this view with that card first
and highlighted.

**Approving** signs with the logged-in person's `users.id` (resolved once per session)
and sends the text in the box: the draft as written, or edited. The workspace queues it
through the outbox (the only way out) and records the draft's verdict, so the
generated→sent diff is kept. Every refusal is worded — no route can reach the person, the
comment already got its private reply, someone else decided the query first — never a
500.

**The public notice** (PR 4): when a card offers it (`public_notice` on, a comment), the
person sees its text — «Te escribimos al privado 💬» unless edited — with a box
to include it, and approves it in the same click as the message. Unticking the box sends
the message alone. It is posted later, by the worker, only once the message is confirmed
sent.

**Three steps** (m-24842991, ATENDER-6): each card walks ① «Qué preguntó» ② «Qué le
respondes» ③ «Revisa y aprueba» (`steps`, by followup id). «Atrás» only changes the step:
the text in the box and the notice stay as the person left them (N6). Approving ends in
a confirmation that stays on screen — «Listo. Le escribiste a @ana. ¿Seguimos con la
siguiente?» with «Siguiente» and «Volver a comentarios» (N3) — never a toast alone.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx
from qualify_api.claude_tools import ClaudeToolError, MissingAPIKey
from qualify_api.conversations.contracts import UnknownChannel
from qualify_api.conversations.outbox import ApprovalRequired, PrivateReplyExists
from qualify_api.followups.repository import InvalidFollowupTransition, UnknownFollowup
from qualify_api.followups.service import CapabilityUnavailable, RouteUnavailable
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .followups_provider import gateway
from .followups_vm import (
    STEP_ASKED,
    STEP_REPLY,
    STEP_REVIEW,
    STEP_TITLES,
    VIEW_MESSAGES,
    VIEW_PARAM,
    VIEW_QUERIES,
    VIEWS,
    FollowupCardVM,
    done_title,
    view_from_param,
    view_url,
)
from .nav_url import push_url_script
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

QUERY_PARAM = "consulta"

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudieron cargar las consultas. Vuelve a intentarlo en un momento."
_NO_USER = (
    "No encontramos tu usuario en este negocio, así que no podemos firmar el mensaje. "
    "Vuelve a iniciar sesión."
)
_DRAFT_UNAVAILABLE = "Ahora no podemos sugerirte un mensaje. Escríbelo tú y apruébalo."
_DRAFT_FAILED = "No pudimos escribir el mensaje. Vuelve a intentarlo o escríbelo tú."
_GONE = "Esta consulta ya la decidió otra persona o ya no está disponible."
_ALREADY_REPLIED = (
    "Este comentario ya tiene su respuesta privada: Instagram permite solo una por comentario."
)
_NO_ROUTE = "Ahora mismo no hay forma de escribirle a esta persona:"
_EMPTY = "Escribe el mensaje antes de aprobarlo."
_TOO_LONG = "El mensaje es demasiado largo (máximo 1000 caracteres)."
_NOTICE_EMPTY = "Escribe lo que dejamos en su comentario o desmarca la casilla."
_NOTICE_TOO_LONG = "Lo que dejamos en su comentario es demasiado largo (máximo 300 caracteres)."
_NOTICE_QUEUED = " Lo que dejamos en su comentario aparece cuando el mensaje salga."
_SEND_FAILED = "No pudimos enviar el mensaje. Vuelve a intentarlo en un momento."
_DISCARD_FAILED = "No pudimos descartar la consulta. Vuelve a intentarlo en un momento."


def queued_message(author: str) -> str:
    """m-24842988 (m5 hallazgo 12): the confirmation names who gets the message —
    «Tu mensaje privado a @ana sale en unos segundos.» — whichever private route it
    takes; without a handle (`author` is «Cliente») it stays generic. Still queued, so
    never «Listo» (N13)."""
    if author.startswith("@"):
        return f"Tu mensaje privado a {author} sale en unos segundos."
    return "Tu mensaje privado sale en unos segundos."


_DISCARDED = "Consulta descartada."
_TOAST_MS = 5000

_DB_ERRORS = (SQLAlchemyError, OSError)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


class FollowupsState(rx.State):
    view: str = VIEW_MESSAGES
    cards: list[FollowupCardVM] = []
    loaded: bool = False
    loading: bool = False
    error: str = ""
    # The text in each card's box, by followup id — the draft until the person edits it.
    edits: dict[str, str] = {}
    # The public notice of each card that offers it: whether it goes, and its text.
    notice_on: dict[str, bool] = {}
    notice_edits: dict[str, str] = {}
    busy_id: str = ""
    busy_action: str = ""
    highlight_id: str = ""
    # m-24842991: the step each card is on (1 «Qué preguntó» … 3 «Revisa y aprueba»).
    steps: dict[str, int] = {}
    # The confirmation after approving: who got the message, and what was queued.
    done_author: str = ""
    done_note: str = ""
    _zone_name: str = ""
    _user_id: str = ""

    @rx.var
    def followups_count(self) -> int:
        return len(self.cards)

    @rx.var
    def toggle_label(self) -> str:
        count = len(self.cards)
        return f"Consultas desde comentarios ({count})" if count else "Consultas desde comentarios"

    @rx.var
    def showing_queries(self) -> bool:
        return self.view == VIEW_QUERIES

    @rx.var
    def showing_done(self) -> bool:
        return self.done_author != ""

    @rx.var
    def done_text(self) -> str:
        if not self.done_author:
            return ""
        return done_title(self.done_author, more_left=bool(self.cards))

    # -- plumbing -------------------------------------------------------------------------

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    def _known(self, followup_id: str) -> FollowupCardVM | None:
        return next((c for c in self.cards if c.followup_id == followup_id), None)

    def _order(self, cards: list[FollowupCardVM]) -> list[FollowupCardVM]:
        """The highlighted card (a «Responder por DM» landing) first."""
        if not self.highlight_id:
            return cards
        first = [c for c in cards if c.followup_id == self.highlight_id]
        return first + [c for c in cards if c.followup_id != self.highlight_id]

    async def _acting_user(self, tenant_id: UUID) -> UUID | None:
        async with self:
            cached = self._user_id
            auth = await self.get_state(AuthState)
            email = auth.user_email
        if cached:
            return _uuid(cached)
        user_id = await asyncio.to_thread(gateway().acting_user, tenant_id, email)
        if user_id is not None:
            async with self:
                self._user_id = str(user_id)
        return user_id

    # -- entry --------------------------------------------------------------------------

    @rx.event
    def enter_page(self) -> rx.event.EventSpec:
        """The route's `on_load`: `?vista=` picks the view (N5 — reloading or «atrás»
        lands on the view the address names); a `?consulta=<id>` opens this view on that
        card."""
        params = self.router.url.query_parameters
        self.view = view_from_param(str(params.get(VIEW_PARAM, "") or ""))
        wanted = str(params.get(QUERY_PARAM, "") or "")
        if _uuid(wanted) is not None:
            self.view = VIEW_QUERIES
            self.highlight_id = wanted
        self.done_author, self.done_note = "", ""
        return FollowupsState.load

    @rx.event
    def set_view(self, view: str | list[str]) -> list[rx.event.EventSpec] | None:
        """The toggle. The view is written to the address as a new history step (N5)."""
        if not isinstance(view, str) or view not in VIEWS:
            return None
        self.view = view
        events = [rx.call_script(push_url_script(view_url(view)))]
        if view == VIEW_QUERIES:
            events.append(FollowupsState.load())
        return events

    @rx.event
    def set_edit(self, followup_id: str, text: str) -> None:
        if self._known(followup_id) is not None and isinstance(text, str):
            self.edits = {**self.edits, followup_id: text}

    @rx.event
    def go_step(self, followup_id: str, step: int) -> rx.event.EventSpec | None:
        """«Siguiente» / «Atrás» inside a card. Only the step changes — what the person
        wrote stays (N6). Reaching the review needs a message to review."""
        if self._known(followup_id) is None or not isinstance(step, int):
            return None
        if step not in STEP_TITLES:
            return None
        if step == STEP_REVIEW and not self.edits.get(followup_id, "").strip():
            self.steps = {**self.steps, followup_id: STEP_REPLY}
            return rx.toast.warning(_EMPTY, duration=_TOAST_MS)
        self.steps = {**self.steps, followup_id: step}
        return None

    @rx.event
    def next_query(self) -> rx.event.EventSpec | None:
        """«Siguiente» on the confirmation: the next card, on its first step, in view."""
        self.done_author, self.done_note = "", ""
        if not self.cards:
            return None
        first = self.cards[0].followup_id
        self.highlight_id = first
        self.steps = {**self.steps, first: STEP_ASKED}
        return rx.scroll_to("consulta-" + first)

    @rx.event
    def set_notice_on(self, followup_id: str, on: bool) -> None:
        card = self._known(followup_id)
        if card is not None and card.notice_available and isinstance(on, bool):
            self.notice_on = {**self.notice_on, followup_id: on}

    @rx.event
    def set_notice_edit(self, followup_id: str, text: str) -> None:
        card = self._known(followup_id)
        if card is not None and card.notice_available and isinstance(text, str):
            self.notice_edits = {**self.notice_edits, followup_id: text}

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            if self.loading:
                return
            self.loading = True
            tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.loading, self.loaded, self.error = False, True, _NO_SESSION
            return
        try:
            async with self:
                zone_name = self._zone_name
            if not zone_name:
                zone_name = await asyncio.to_thread(gateway().timezone, tenant_id)
            cards = await asyncio.to_thread(gateway().cards, tenant_id, zone_name)
        except _DB_ERRORS as exc:
            logger.error("followups load failed: %s", type(exc).__name__)
            async with self:
                self.loading, self.loaded, self.error = False, True, _LOAD_FAILED
            return
        async with self:
            self._zone_name = zone_name
            self.cards = self._order(cards)
            # Keep what the person is typing; seed new cards with their draft.
            self.edits = {c.followup_id: self.edits.get(c.followup_id, c.draft_text) for c in cards}
            self.steps = {c.followup_id: self.steps.get(c.followup_id, STEP_ASKED) for c in cards}
            offered = [c for c in cards if c.notice_available]
            self.notice_on = {
                c.followup_id: self.notice_on.get(c.followup_id, True) for c in offered
            }
            self.notice_edits = {
                c.followup_id: self.notice_edits.get(c.followup_id, c.notice_default)
                for c in offered
            }
            self.loading, self.loaded, self.error = False, True, ""

    # -- actions ------------------------------------------------------------------------

    def _notice_for(self, card: FollowupCardVM | None) -> str | None:
        """The notice text the person approves with the message, or None (not offered,
        or the box unticked)."""
        if card is None or not card.notice_available:
            return None
        if not self.notice_on.get(card.followup_id, True):
            return None
        return self.notice_edits.get(card.followup_id, card.notice_default)

    async def _begin(self, followup_id: str, action: str) -> tuple[UUID, UUID] | None:
        async with self:
            if self.busy_id or self._known(followup_id) is None:
                return None
            tenant_id = await self._tenant()
            if tenant_id is None:
                return None
            self.busy_id, self.busy_action = followup_id, action
        return tenant_id, UUID(followup_id)

    async def _end(self) -> None:
        async with self:
            self.busy_id, self.busy_action = "", ""

    def _reseed(self, followup_id: str) -> None:
        """After a new draft, the box shows it (the old text was the old draft's)."""
        edits = dict(self.edits)
        edits.pop(followup_id, None)
        self.edits = edits

    @rx.event(background=True)
    async def generate(self, followup_id: str) -> AsyncIterator[rx.event.EventSpec]:
        started = await self._begin(followup_id, "generate")
        if started is None:
            return
        tenant_id, fid = started
        try:
            await asyncio.to_thread(gateway().suggest, tenant_id, fid)
        except MissingAPIKey:
            yield rx.toast.warning(_DRAFT_UNAVAILABLE, duration=_TOAST_MS)
        except (ClaudeToolError, *_DB_ERRORS) as exc:
            logger.warning("followups draft failed: %s", type(exc).__name__)
            yield rx.toast.error(_DRAFT_FAILED, duration=_TOAST_MS)
        except UnknownFollowup:
            yield rx.toast.warning(_GONE, duration=_TOAST_MS)
        async with self:
            self._reseed(followup_id)
        await self._end()
        yield FollowupsState.load

    @rx.event(background=True)
    async def regenerate(self, followup_id: str) -> AsyncIterator[rx.event.EventSpec]:
        started = await self._begin(followup_id, "regenerate")
        if started is None:
            return
        tenant_id, fid = started
        user_id = await self._acting_user(tenant_id)
        if user_id is None:
            await self._end()
            yield rx.toast.error(_NO_USER, duration=_TOAST_MS)
            return
        try:
            await asyncio.to_thread(gateway().regenerate, tenant_id, fid, user_id)
        except MissingAPIKey:
            yield rx.toast.warning(_DRAFT_UNAVAILABLE, duration=_TOAST_MS)
        except (ClaudeToolError, *_DB_ERRORS) as exc:
            logger.warning("followups regenerate failed: %s", type(exc).__name__)
            yield rx.toast.error(_DRAFT_FAILED, duration=_TOAST_MS)
        except UnknownFollowup:
            yield rx.toast.warning(_GONE, duration=_TOAST_MS)
        async with self:
            self._reseed(followup_id)
        await self._end()
        yield FollowupsState.load

    @rx.event(background=True)
    async def discard(self, followup_id: str) -> AsyncIterator[rx.event.EventSpec]:
        started = await self._begin(followup_id, "discard")
        if started is None:
            return
        tenant_id, fid = started
        user_id = await self._acting_user(tenant_id)
        if user_id is None:
            await self._end()
            yield rx.toast.error(_NO_USER, duration=_TOAST_MS)
            return
        try:
            await asyncio.to_thread(gateway().discard, tenant_id, fid, user_id)
            yield rx.toast.info(_DISCARDED, duration=_TOAST_MS)
        except (InvalidFollowupTransition, UnknownFollowup):
            yield rx.toast.warning(_GONE, duration=_TOAST_MS)
        except _DB_ERRORS as exc:
            logger.error("followups discard failed: %s", type(exc).__name__)
            yield rx.toast.error(_DISCARD_FAILED, duration=_TOAST_MS)
        await self._end()
        yield FollowupsState.load

    @rx.event(background=True)
    async def approve(self, followup_id: str) -> AsyncIterator[rx.event.EventSpec]:
        started = await self._begin(followup_id, "approve")
        if started is None:
            return
        tenant_id, fid = started
        async with self:
            card = self._known(followup_id)
            text = self.edits.get(followup_id, card.draft_text if card else "")
            draft_id = _uuid(card.draft_id) if card else None
            notice_text = self._notice_for(card)
        if not text.strip():
            await self._end()
            yield rx.toast.warning(_EMPTY, duration=_TOAST_MS)
            return
        if notice_text is not None and not notice_text.strip():
            await self._end()
            yield rx.toast.warning(_NOTICE_EMPTY, duration=_TOAST_MS)
            return
        user_id = await self._acting_user(tenant_id)
        if user_id is None:
            await self._end()
            yield rx.toast.error(_NO_USER, duration=_TOAST_MS)
            return
        queued = False
        try:
            # Both private routes read the same to the owner (m-24842988).
            await asyncio.to_thread(
                lambda: gateway().approve(
                    tenant_id,
                    fid,
                    text=text,
                    user_id=user_id,
                    draft_id=draft_id,
                    notice_text=notice_text,
                )
            )
            queued = True
            # N3: the confirmation stays on screen with the next step — not a toast.
            message = queued_message(card.author if card else "") + (
                _NOTICE_QUEUED if notice_text else ""
            )
            async with self:
                self.done_author = card.author if card else ""
                self.done_note = message
        except RouteUnavailable as exc:
            reasons = " ".join(
                f"{o.reason}" for o in (exc.options.dm, exc.options.private_reply) if o.reason
            )
            yield rx.toast.warning(f"{_NO_ROUTE} {reasons}", duration=_TOAST_MS * 2)
        except PrivateReplyExists:
            yield rx.toast.warning(_ALREADY_REPLIED, duration=_TOAST_MS)
        except (InvalidFollowupTransition, UnknownFollowup):
            yield rx.toast.warning(_GONE, duration=_TOAST_MS)
        except CapabilityUnavailable as exc:
            yield rx.toast.warning(exc.availability.owner_reason, duration=_TOAST_MS)
        except ValueError as exc:
            reason = str(exc)
            if "notice" in reason:
                warning = _NOTICE_TOO_LONG
            else:
                warning = _TOO_LONG if "at most" in reason else _EMPTY
            yield rx.toast.warning(warning, duration=_TOAST_MS)
        except (ApprovalRequired, UnknownChannel, *_DB_ERRORS) as exc:
            logger.error("followups approve failed: %s", type(exc).__name__)
            yield rx.toast.error(_SEND_FAILED, duration=_TOAST_MS)
        if queued:  # a refused approval keeps the person's text in the box
            async with self:
                edits = dict(self.edits)
                edits.pop(followup_id, None)
                self.edits = edits
                steps = dict(self.steps)
                steps.pop(followup_id, None)
                self.steps = steps
                if self.highlight_id == followup_id:
                    self.highlight_id = ""
        await self._end()
        yield FollowupsState.load
