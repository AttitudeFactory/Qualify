"""«No tengo código» on the access gate (MARCA-5, m-24842968; founder decision 7b).

A visitor without an invitation leaves name, business and WhatsApp; the entry goes to
the house tenant's `/leads` through `qualify_api.leads.interest` (in-process, off the
event loop). No account and no tenant are created. The form's values are never kept in
state after sending, and nothing here is persisted in the browser."""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from qualify_api.leads.interest import (
    InterestInvalid,
    InterestNotConfigured,
    InterestRateLimited,
    InterestRequest,
)
from sqlalchemy.exc import SQLAlchemyError

from .access_vm import interest_error_message

logger = logging.getLogger(__name__)

#: The three views of the gate's second path.
MODE_CODE = ""  # the notice and the code field (the default)
MODE_FORM = "form"  # «No tengo código»: the short form
MODE_SENT = "sent"  # the confirmation


def _submit_blocking(request: InterestRequest, client_key: str) -> bool:
    from qualify_api.leads.composition import in_process_interest_service

    return in_process_interest_service().submit(request, client_key=client_key).saved


class AccessInterestState(rx.State):
    mode: str = MODE_CODE
    consent: bool = False
    error: str = ""
    sending: bool = False

    @rx.event
    def open_form(self) -> None:
        self.mode = MODE_FORM
        self.error = ""

    @rx.event
    def back_to_code(self) -> None:
        self.mode = MODE_CODE
        self.error = ""

    @rx.event
    def set_consent(self, checked: bool) -> None:
        self.consent = bool(checked)

    def _client_key(self) -> str:
        """First X-Forwarded-For hop (the app sits behind Caddy), else the socket peer —
        the same rule as the HTTP intake. Only a rate-limit bucket, never logged."""
        raw = self.router.headers.raw_headers
        forwarded = str(raw.get("x-forwarded-for", "") or "")
        first_hop = forwarded.split(",")[0].strip()
        return first_hop or self.router.session.client_ip or "unknown"

    @rx.event(background=True)
    async def submit(self, form_data: dict):
        async with self:
            if self.sending:
                return
            self.sending = True
            self.error = ""
            consent = self.consent
            client_key = self._client_key()
        request = InterestRequest(
            full_name=str(form_data.get("full_name", "")),
            business_name=str(form_data.get("business_name", "")),
            whatsapp_phone=str(form_data.get("whatsapp_phone", "")),
            consent=consent,
            honeypot=str(form_data.get("website", "")),
        )
        reason = ""
        try:
            await asyncio.to_thread(_submit_blocking, request, client_key)
        except InterestInvalid as exc:
            reason = exc.field
        except InterestRateLimited:
            reason = "rate_limited"
        except InterestNotConfigured:
            reason = "not_configured"
        except (SQLAlchemyError, OSError) as exc:
            # The type only: the request carries a phone number.
            logger.error("interest form failed: %s", type(exc).__name__)
            reason = "down"
        async with self:
            self.sending = False
            if reason:
                self.error = interest_error_message(reason)
                return
            self.mode = MODE_SENT
            self.consent = False
