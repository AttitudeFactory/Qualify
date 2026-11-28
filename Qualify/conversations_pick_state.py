"""Instagram's «+» panel (m-25143229): «Formas de pago» and «Cómo llegar».

The same steps, names and texts as WhatsApp's «+» (`whatsapp_chats_state`, m-24955785):
the row opens the panel at its first step — «¿Cuál forma de pago?» (one method: straight
to «Revisa y envía») or «Así le llega tu ubicación» — and nothing is queued until the
owner taps «Enviar» on the review. Drawn by `conversations_pick_ui.py` with the shared
steps of `chat_plus_picks.py`.

- **Only inside the 24 h window**: the «+» lives in the live reply box (a closed window
  has no box), `open_pick` refuses when `ConversationsState.can_compose` is false, and
  the service refuses a send once the window closed (`WindowClosed`, nothing written).
- **One send per tap** (review C1): `_begin_send` freezes the plan under the lock and
  sets `pick_busy`, which `_reset` never clears: while it is set the panel cannot be
  closed (✕, Esc, backdrop, «Volver al chat», the phone's «atrás») nor the «+» opened
  again, and its result is always told (in the panel, or a toast when the chat
  changed). (Instagram's outbox has no request key: this is an in-flight guard, like
  every other send of this screen.)
- **The QR once** (review C2): when the QR was queued and its text was not, the retry
  of that method in that chat skips THAT QR object (`_qr_queued`); a QR replaced
  meanwhile has another key and goes.
- **A lost send never locks the «+»** (N2): `pick_busy` counts only for `BUSY_FOR_S`
  after it was set — an app restart mid-send never runs the `finally`.
- **The phone's «atrás»** (review U2): WhatsApp's `?flujo=` mechanism with its own flow
  name (`IG_PICK_FLOW`): one step back, or closed on step 1, in the same chat.
- **Scoped**: every read and send goes through `conversations_provider.gateway()` with
  the session's tenant and the account on screen; the thread is re-checked against that
  account (`_owned`) on every call. A result that lands after the panel closed or the
  chat changed (`_session`) is dropped.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from qualify_api.auth.business import NotAMember
from qualify_api.conversations.service import ThreadNotFound, WindowClosed
from qualify_api.inbox.dispatch import WindowClosed as DispatchWindowClosed
from qualify_api.tenancy.acting import acting_login
from qualify_api.whatsapp.payments import PaymentMethodNotFound

from .auth_state import AuthState
from .conversations_provider import PaymentTextNotQueued, gateway
from .conversations_state import WINDOW_CLOSED_NEUTRAL, ConversationsState
from .conversations_vm import NO_INBOUND_NOTICE, WINDOW_CLOSED_NOTICE, reply_sent_message
from .ig_plus_provider import DirectionsUnavailable
from .nav_url import close_flow_script, flow_param, inbox_chat_href
from .pending_state import PendingState
from .ui.primitives import ORBIT_FOCUS_SCRIPT
from .ui.steps import settle_step
from .whatsapp_chats_vm import (
    DIRECTIONS_FAILED,
    DIRECTIONS_NO_LOCATION,
    EMPTY_DIRECTIONS,
    PAYMENT_GONE,
    PAYMENTS_FAILED,
    PICK_DIRECTIONS,
    PICK_PAYMENTS,
    PROFILE_ROUTE,
    SEND_LABEL,
    SENDING_LABEL,
    DirectionsVM,
    PaymentCardVM,
    build_payment_cards,
    number_settings_href,
    payments_href,
    pick_step_help,
    pick_step_title,
    pick_total_steps,
    send_failed_message,
)

logger = logging.getLogger(__name__)

#: The rows Instagram's «+» opens here (`reply_box_vm.SEND_DOORS`).
IG_PICK_SOURCES = frozenset({PICK_PAYMENTS, PICK_DIRECTIONS})
#: The panel's `?flujo=` (WhatsApp's is «enviar»: a distinct name, so one chat's
#: restore never closes the other's panel).
IG_PICK_FLOW = "enviar-ig"
#: N2: how long an «Enviar» in flight holds the panel (a send that outlives it was lost).
BUSY_FOR_S = 60.0
#: Review U3 (texto nuevo, pendiente de aprobación del fundador): Instagram has no
#: location message — the customer always gets the address with a link to the map.
IG_DIRECTIONS_HELP = (
    "Le llega tu dirección con un enlace al mapa. Nada sale sin que toques «Enviar»."
)
_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_USER = (
    "No encontramos tu usuario en este negocio, así que no podemos firmar la respuesta. "
    "Pide al equipo de Qualify que lo revise."
)
_THREAD_GONE = "Esa conversación ya no está disponible en esta cuenta."
_TOAST_MS = 4000


_Event = rx.event.EventSpec | rx.event.EventHandler


class _NoSession(Exception):
    """No tenant or ids to act on."""


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def ig_pick_can_send(
    *,
    source: str,
    reviewing: bool,
    sending: bool,
    payment_id: str,
    payment_text: str,
    payment_loading: bool,
    directions: DirectionsVM,
) -> bool:
    """«Enviar» on the review: only once what goes out is on screen."""
    if not reviewing or sending:
        return False
    if source == PICK_PAYMENTS:
        return payment_id != "" and payment_text != "" and not payment_loading
    if source == PICK_DIRECTIONS:
        return directions.present and not directions.empty
    return False


def ig_send_error(exc: BaseException, source: str) -> str:
    """The owner's words for a refused or failed send (never the exception's text)."""
    if isinstance(exc, PaymentMethodNotFound):
        return PAYMENT_GONE
    if isinstance(exc, DirectionsUnavailable):
        return DIRECTIONS_NO_LOCATION
    if isinstance(exc, ThreadNotFound):
        return _THREAD_GONE
    return send_failed_message(source)


async def _window_closed_cause(
    tenant_id: UUID | None, connection: UUID | None, thread: UUID | None
) -> str:
    """Why the send was refused, from a FRESH read (`ConversationsState`'s own rule,
    m-25018661): no message left, or 24 h passed; neutral when it cannot be read."""
    if tenant_id is None or connection is None or thread is None:
        return WINDOW_CLOSED_NEUTRAL
    try:
        conv = await asyncio.to_thread(gateway().conversation, tenant_id, connection, thread)
    except Exception as exc:  # noqa: BLE001
        logger.info("instagram plus window re-read failed: %s", type(exc).__name__)
        return WINDOW_CLOSED_NEUTRAL
    if conv.view.thread.last_inbound_at is None:
        return NO_INBOUND_NOTICE
    return WINDOW_CLOSED_NOTICE


@dataclass(frozen=True)
class _Plan:
    session: int
    source: str
    thread_id: str
    connection_id: str
    item_id: str
    skip_qr_key: str = ""


class InstagramPickState(rx.State):
    """The «+» panel of an Instagram chat. Keeps its own copy of the chat it opened on
    (`pick_thread`): the panel shows only while that chat is the open one."""

    pick_open: bool = False
    pick_source: str = ""
    pick_step: int = 1
    pick_thread: str = ""
    pick_loading: bool = False
    pick_error: str = ""
    pick_payments: list[PaymentCardVM] = []
    pick_selected: str = ""
    pick_payment_text: str = ""
    pick_payment_qr: str = ""
    pick_payment_loading: bool = False
    pick_directions: DirectionsVM = EMPTY_DIRECTIONS
    pick_sending: bool = False
    pick_send_error: str = ""
    #: The business's WhatsApp number (its «Formas de pago» and «Perfil» pages), "" if none.
    pick_number: str = ""
    #: A send is in flight (C1): never cleared by `_reset`, only by the send itself.
    pick_busy: bool = False

    _session: int = 0
    _connection: str = ""
    _zone_name: str = ""
    #: C2: "<thread>:<method>" → the QR object key queued while its text was not.
    _qr_queued: dict[str, str] = {}
    #: N2: when `pick_busy` was set (epoch seconds).
    _busy_since: float = 0.0

    # --- computed ------------------------------------------------------------------------

    @rx.var
    def pick_single_payment(self) -> bool:
        return self.pick_source == PICK_PAYMENTS and len(self.pick_payments) == 1

    @rx.var
    def pick_total(self) -> int:
        return pick_total_steps(self.pick_source, single=self.pick_single_payment)

    @rx.var
    def pick_reviewing(self) -> bool:
        return self.pick_source != "" and self.pick_step >= self.pick_total

    @rx.var
    def pick_show_progress(self) -> bool:
        return self.pick_total > 1

    @rx.var
    def pick_title(self) -> str:
        return pick_step_title(self.pick_step, self.pick_source, single=self.pick_single_payment)

    @rx.var
    def pick_help(self) -> str:
        if self.pick_source == PICK_DIRECTIONS:
            return IG_DIRECTIONS_HELP  # U3: WhatsApp's line promises the map pin
        return pick_step_help(self.pick_step, self.pick_source, single=self.pick_single_payment)

    @rx.var
    def pick_can_send(self) -> bool:
        return ig_pick_can_send(
            source=self.pick_source,
            reviewing=self.pick_reviewing,
            sending=self.pick_sending or self._busy(),
            payment_id=self.pick_selected,
            payment_text=self.pick_payment_text,
            payment_loading=self.pick_payment_loading,
            directions=self.pick_directions,
        )

    def _busy(self) -> bool:
        """N2: in flight, and not for longer than a send can take."""
        return self.pick_busy and time.time() - self._busy_since < BUSY_FOR_S

    @rx.var(cache=False)
    def pick_locked(self) -> bool:
        """The «+» is held by a send in flight (the same expiry as the guards)."""
        return self._busy()

    @rx.var
    def pick_send_label(self) -> str:
        return SENDING_LABEL if self.pick_sending else SEND_LABEL

    @rx.var
    def pick_selected_payment(self) -> PaymentCardVM:
        for card in self.pick_payments:
            if card.id == self.pick_selected:
                return card
        return PaymentCardVM()

    def _back(self) -> str:
        return inbox_chat_href(self._connection, self.pick_thread) if self.pick_thread else ""

    @rx.var
    def payments_change_href(self) -> str:
        """«Formas de pago», on the business's WhatsApp number when it has one, with the
        way back to this chat (`?volver=`)."""
        return payments_href(self._back(), account=self.pick_number)

    @rx.var
    def pick_profile_href(self) -> str:
        """«Ajustes de chats › Perfil» (where the address and the map point live)."""
        return number_settings_href(PROFILE_ROUTE, self._back(), self.pick_number)

    # --- plumbing ------------------------------------------------------------------------

    def _reset(self) -> None:
        self._session += 1
        self.pick_open = False
        self.pick_source = ""
        self.pick_step = 1
        self.pick_thread = ""
        self.pick_loading = False
        self.pick_error = ""
        self.pick_payments = []
        self.pick_selected = ""
        self.pick_payment_text = ""
        self.pick_payment_qr = ""
        self.pick_payment_loading = False
        self.pick_directions = EMPTY_DIRECTIONS
        self.pick_sending = False
        self.pick_send_error = ""
        self.pick_number = ""
        self._connection = ""

    def _close(self) -> list[rx.event.EventSpec] | None:
        """Closed (Volver al chat, ✕, Esc, the backdrop): the focus goes back to the «+».
        Refused while a send is in flight (C1): its result must reach this panel."""
        if self._busy():
            return None
        self._reset()
        return [
            rx.call_script(close_flow_script(IG_PICK_FLOW)),
            rx.call_script(ORBIT_FOCUS_SCRIPT),
        ]

    async def _tenant(self) -> UUID | None:
        conv = await self.get_state(ConversationsState)
        return await conv._tenant()

    # --- open, steps, close --------------------------------------------------------------

    @rx.event
    async def open_pick(
        self, source: str
    ) -> list[rx.event.EventSpec | rx.event.EventHandler] | None:
        """A row of the «+»: the panel opens at that row's first step. Only while this
        chat may get a message; choosing a row never sends anything."""
        if not isinstance(source, str) or source not in IG_PICK_SOURCES:
            return None
        if self._busy():
            return None  # C1: the last «Enviar» has not come back yet
        conv = await self.get_state(ConversationsState)
        if not conv.can_compose or conv.busy or not conv.open_thread_id:
            return None
        self._reset()
        self.pick_open = True
        self.pick_source = source
        self.pick_thread = conv.open_thread_id
        self._connection = conv.selected_connection_id
        self._zone_name = conv._zone_name
        loader = (
            InstagramPickState.load_payments
            if source == PICK_PAYMENTS
            else InstagramPickState.load_directions
        )
        return [settle_step("drawer"), loader]

    @rx.event
    def set_picker_open(self, is_open: bool) -> list[rx.event.EventSpec] | None:
        """The drawer's ✕, Esc or the backdrop."""
        if not is_open and self.pick_open:
            return self._close()
        return None

    @rx.event
    def pick_back(self) -> rx.event.EventSpec | list[rx.event.EventSpec] | None:
        """«Atrás»; on step 1 it is «Volver al chat» and closes the panel."""
        if self._busy():
            return None
        if self.pick_step <= 1:
            return self._close()
        self.pick_step -= 1
        self.pick_send_error = ""
        return settle_step("drawer")

    @rx.event
    def restore_picker(self) -> rx.event.EventSpec | None:
        """The phone's «atrás» (WhatsApp's `restore_picker`, U2): the address moved under
        the panel — one step back, or closed on step 1, in the same chat. An address
        that names the panel while it is closed (a reload) is tidied; nothing reopens
        by itself. While a send is in flight the panel stays (C1)."""
        params = self.router.url.query_parameters
        requested = flow_param(params, IG_PICK_FLOW, 2)
        if not self.pick_open:
            return rx.call_script(close_flow_script(IG_PICK_FLOW)) if requested else None
        if self._busy():
            return None
        if not requested:
            self._reset()
            return rx.call_script(ORBIT_FOCUS_SCRIPT)
        if requested < self.pick_step:
            self.pick_step = requested
            self.pick_send_error = ""
            return settle_step("drawer")
        return None

    @rx.event
    def choose_payment(
        self, method_id: str
    ) -> list[rx.event.EventSpec | rx.event.EventHandler] | None:
        """«¿Cuál forma de pago?» → «Revisa y envía» (the text and the QR, read again)."""
        if not isinstance(method_id, str) or self.pick_source != PICK_PAYMENTS:
            return None
        if not any(c.id == method_id for c in self.pick_payments):
            return None
        if self._busy():
            return None
        if method_id != self.pick_selected:
            self.pick_selected = method_id
            self.pick_payment_text = ""
            self.pick_payment_qr = ""
            self.pick_send_error = ""
        self.pick_step = 2
        return [settle_step("drawer"), InstagramPickState.load_payment_preview]

    @rx.event
    def retry_pick_list(self) -> rx.event.EventHandler | None:
        if self.pick_source == PICK_PAYMENTS and self.pick_reviewing:
            return InstagramPickState.load_payment_preview
        if self.pick_source == PICK_PAYMENTS:
            return InstagramPickState.load_payments
        if self.pick_source == PICK_DIRECTIONS:
            return InstagramPickState.load_directions
        return None

    # --- reads ---------------------------------------------------------------------------

    @rx.event(background=True)
    async def load_payments(self) -> AsyncIterator[rx.event.EventSpec | rx.event.EventHandler]:
        async with self:
            if not self.pick_open or self.pick_source != PICK_PAYMENTS:
                return
            session, connection_id = self._session, self._connection
            zone = _zone(self._zone_name)
            self.pick_loading = True
            self.pick_error = ""
            tenant_id = await self._tenant()
        cards: list[PaymentCardVM] = []
        number, error = "", ""
        try:
            connection = _uuid(connection_id)
            if tenant_id is None or connection is None:
                raise _NoSession
            gw = gateway()
            scope = await asyncio.to_thread(gw.plus_scope, tenant_id, connection)
            picks = await asyncio.to_thread(gw.list_payment_methods_for_chat, tenant_id, connection)
            cards = build_payment_cards(picks, zone, datetime.now(UTC))
            number = str(scope.whatsapp_connection_id or "")
        except _NoSession:
            error = _NO_SESSION
        except Exception as exc:  # noqa: BLE001 — Postgres: worded, never shown
            logger.error("instagram plus payments failed: %s", type(exc).__name__)
            error = PAYMENTS_FAILED
        async with self:
            if self._session != session:
                return  # closed or another chat meanwhile
            self.pick_loading = False
            self.pick_error = error
            self.pick_payments = cards
            self.pick_number = number
            # one method: «Revisa y envía» IS the only step (WhatsApp's rule)
            only = not error and len(cards) == 1 and self.pick_step == 1
            events = self.choose_payment(cards[0].id) if only else None
            if only:
                self.pick_step = 1
        for event in events or []:
            yield event

    @rx.event(background=True)
    async def load_payment_preview(self) -> None:
        async with self:
            if self.pick_source != PICK_PAYMENTS or not self.pick_selected:
                return
            session, connection_id = self._session, self._connection
            thread_id, method_id = self.pick_thread, self.pick_selected
            self.pick_payment_loading = True
            self.pick_error = ""
            tenant_id = await self._tenant()
        text, qr, error = "", "", ""
        try:
            tenant, connection = tenant_id, _uuid(connection_id)
            thread, method = _uuid(thread_id), _uuid(method_id)
            if tenant is None or connection is None or thread is None or method is None:
                raise _NoSession
            preview = await asyncio.to_thread(
                gateway().payment_preview, tenant, connection, thread, method
            )
            text, qr = preview.text, preview.qr_src
        except _NoSession:
            error = _NO_SESSION
        except PaymentMethodNotFound:
            error = PAYMENT_GONE
        except ThreadNotFound:
            error = _THREAD_GONE
        except Exception as exc:  # noqa: BLE001
            logger.error("instagram plus payment preview failed: %s", type(exc).__name__)
            error = PAYMENTS_FAILED
        async with self:
            if self._session != session or self.pick_selected != method_id:
                return
            self.pick_payment_loading = False
            self.pick_payment_text = text
            self.pick_payment_qr = qr
            self.pick_error = error

    @rx.event(background=True)
    async def load_directions(self) -> None:
        async with self:
            if not self.pick_open or self.pick_source != PICK_DIRECTIONS:
                return
            session, connection_id = self._session, self._connection
            self.pick_loading = True
            self.pick_error = ""
            tenant_id = await self._tenant()
        directions, number, error = EMPTY_DIRECTIONS, "", ""
        try:
            connection = _uuid(connection_id)
            if tenant_id is None or connection is None:
                raise _NoSession
            gw = gateway()
            scope = await asyncio.to_thread(gw.plus_scope, tenant_id, connection)
            directions = await asyncio.to_thread(gw.directions_preview, tenant_id, connection)
            number = str(scope.whatsapp_connection_id or "")
        except _NoSession:
            error = _NO_SESSION
        except Exception as exc:  # noqa: BLE001
            logger.error("instagram plus directions failed: %s", type(exc).__name__)
            error = DIRECTIONS_FAILED
        async with self:
            if self._session != session:
                return
            self.pick_loading = False
            self.pick_error = error
            self.pick_directions = directions
            self.pick_number = number

    # --- «Enviar» --------------------------------------------------------------------------

    def _begin_send(self) -> _Plan | None:
        if not self.pick_open or not self.pick_can_send or self._busy():
            return None
        self.pick_busy = True
        self._busy_since = time.time()
        self.pick_sending = True
        self.pick_send_error = ""
        return _Plan(
            session=self._session,
            source=self.pick_source,
            thread_id=self.pick_thread,
            connection_id=self._connection,
            item_id=self.pick_selected,
            skip_qr_key=self._qr_queued.get(f"{self.pick_thread}:{self.pick_selected}", ""),
        )

    @rx.event(background=True)
    async def send_pick(self) -> AsyncIterator[_Event]:
        """The owner's «Enviar» — the only path this panel queues by."""
        async with self:
            plan = self._begin_send()
            if plan is None:
                return
        try:
            async for event in self._send(plan):
                yield event
        finally:
            async with self:
                self.pick_busy = False  # C1: whatever happened, the «+» works again

    async def _send(self, plan: _Plan) -> AsyncIterator[_Event]:
        async with self:
            conv = await self.get_state(ConversationsState)
            # the chat the panel opened on is still the one on screen
            same_chat = conv.open_thread_id == plan.thread_id
            tenant_id = await conv._tenant()
            login = await conv._login()
            row = conv.open_thread
            who = row.handle or row.title
            email = (await self.get_state(AuthState)).user_email
        if not same_chat:
            async with self:
                self.pick_busy = False
                self._reset()
            return
        thread, connection = _uuid(plan.thread_id), _uuid(plan.connection_id)
        error, window_closed, qr_now = "", False, ""
        try:
            if tenant_id is None or thread is None or connection is None:
                raise _NoSession
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id, email)
            if user is None:
                error = _NO_USER
            else:
                with acting_login(login):
                    if plan.source == PICK_PAYMENTS:
                        method = _uuid(plan.item_id)
                        if method is None:
                            raise PaymentMethodNotFound(plan.item_id)
                        await asyncio.to_thread(
                            partial(gw.send_payment_method, skip_qr_key=plan.skip_qr_key),
                            tenant_id,
                            connection,
                            thread,
                            user,
                            method,
                        )
                    else:
                        await asyncio.to_thread(
                            gw.send_directions, tenant_id, connection, thread, user
                        )
        except PaymentTextNotQueued as half:
            # C2: the QR is queued; the retry of this method sends the text alone
            qr_now = half.qr_key
            cause = half.cause
            if isinstance(cause, (WindowClosed, DispatchWindowClosed)):
                window_closed = True
            elif isinstance(cause, NotAMember):
                error = cause.message
            else:
                logger.error("instagram plus payment text failed: %s", type(cause).__name__)
                error = ig_send_error(cause, plan.source)
        except _NoSession:
            error = _NO_SESSION
        except NotAMember as gone:
            error = gone.message
        except (WindowClosed, DispatchWindowClosed):
            window_closed = True
        except Exception as exc:  # noqa: BLE001 — every refusal is worded
            if not isinstance(exc, LookupError):
                logger.error("instagram plus send failed: %s", type(exc).__name__)
            error = ig_send_error(exc, plan.source)
        async with self:
            key = f"{plan.thread_id}:{plan.item_id}"
            if qr_now:
                self._qr_queued = {**self._qr_queued, key: qr_now}
            elif not error and not window_closed and key in self._qr_queued:
                self._qr_queued = {k: v for k, v in self._qr_queued.items() if k != key}
        if window_closed:
            notice = await _window_closed_cause(tenant_id, connection, thread)
            async with self:
                self.pick_busy = False
                self._reset()
                conv = await self.get_state(ConversationsState)
                conv._set_banner(notice, "warn")
            yield rx.call_script(close_flow_script(IG_PICK_FLOW))
            yield ConversationsState.refresh
            return
        async with self:
            conv = await self.get_state(ConversationsState)
            # N1: the owner moved to another chat while it was in flight — the panel
            # (even when not reset) is not on screen, so a toast tells the outcome
            elsewhere = conv.open_thread_id != plan.thread_id
            here = self._session == plan.session
            if error:
                self.pick_sending = False
                if here:
                    self.pick_send_error = error
            else:
                self.pick_busy = False
                if here:
                    self._reset()
        if error:
            if not here or elsewhere:  # C1/N1: the panel is not on screen
                yield rx.toast.error(error, duration=_TOAST_MS)
            return
        if here and not elsewhere:
            yield rx.call_script(close_flow_script(IG_PICK_FLOW))
            yield rx.call_script(ORBIT_FOCUS_SCRIPT)
        yield rx.toast.info(reply_sent_message(who), duration=_TOAST_MS)
        yield PendingState.refresh_now
        yield ConversationsState.refresh
