"""«Pedir más a Qualify» (m-24852129): the one button the owner has to get more
creations, videos or vistas previas — in Crear when a counter is at 0, and always in
Configuración next to the plan. A support request a person answers with a payment link;
never automatic, never a price on screen.

The button reads «Pedido enviado» while a request of this month is still waiting (the
backend decides it, so two taps — or two tabs — never make two requests), and comes back
once the team adds a pack or changes the plan.

Tenant data, so `AuthState.logout` resets this state with the others."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import reflex as rx

from .ask_more_provider import read_status
from .ask_more_provider import request_more as send_request
from .ask_more_vm import (
    ASK_MORE_BUTTON,
    ASK_MORE_FAILED,
    ASK_MORE_SENT_BUTTON,
    ask_more_sent_text,
)
from .auth_state import AuthState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "Tu sesión terminó. Vuelve a entrar para pedir más."


class AskMoreState(rx.State):
    #: A request of this month is waiting for the team: the button reads «Pedido enviado».
    sent: bool = False
    #: The confirmation after this tap (WhatsApp or email, D13); "" before.
    notice: str = ""
    error: str = ""
    requesting: bool = False

    @rx.var
    def button_label(self) -> str:
        return ASK_MORE_SENT_BUTTON if self.sent else ASK_MORE_BUTTON

    async def _tenant(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            return tenant_uuid(auth.session_tenant_id)

    @rx.event(background=True)
    async def load(self):
        """Read whether a request is already waiting (the screen's mount)."""
        tenant_id = await self._tenant()
        if tenant_id is None:
            return
        try:
            status = await asyncio.to_thread(read_status, tenant_id)
        except Exception as exc:  # noqa: BLE001 — the button stays usable; the backend dedupes
            logger.warning("ask-more status unreadable: %s", type(exc).__name__)
            return
        async with self:
            self.sent = status.pending
            # On a reload the disabled «Pedido enviado» still says where the link will
            # arrive (the D13 confirmations, no new copy).
            self.notice = ask_more_sent_text(status.by_whatsapp) if status.pending else ""

    @rx.event(background=True)
    async def request(self, exhausted: str):
        """«Pedir más a Qualify»: `exhausted` is what ran out (`creations`, `videos`,
        `previews`) or `settings` when it comes from Configuración."""
        async with self:
            if self.requesting or self.sent:
                return
            self.requesting = True
            self.error = ""
            auth = await self.get_state(AuthState)
            email = auth.user_email
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.requesting = False
                self.error = _NO_SESSION
            return
        try:
            result = await asyncio.to_thread(
                send_request, tenant_id, email=email, exhausted=exhausted
            )
        except Exception as exc:  # noqa: BLE001 — the owner gets a retry, the log the type
            logger.error("more creations request not saved: %s", type(exc).__name__)
            async with self:
                self.requesting = False
                self.error = ASK_MORE_FAILED
            return
        async with self:
            self.requesting = False
            self.sent = True
            self.notice = ask_more_sent_text(result.by_whatsapp)
