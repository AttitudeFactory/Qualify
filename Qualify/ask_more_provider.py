"""The seam between «Pedir más a Qualify» (Crear and Configuración) and the backend
(`qualify_api.plans.ask_more`, m-24852129). Blocking DB calls through `tenant_session`:
callers on the event loop run them off-thread. Nothing here reads a price or creates a
unit — a person on the team answers the request."""

from __future__ import annotations

from uuid import UUID

from qualify_api.plans.ask_more import AskMoreResult, AskMoreStatus, ask_more_status
from qualify_api.plans.ask_more import request_more as _request_more

__all__ = ["AskMoreResult", "AskMoreStatus", "read_status", "request_more"]


def read_status(tenant_id: UUID) -> AskMoreStatus:
    """Whether a request is already waiting this month, and whether the business has a
    WhatsApp number the team would write to."""
    return ask_more_status(tenant_id)


def request_more(tenant_id: UUID, *, email: str, exhausted: str) -> AskMoreResult:
    """A `more_creations` request: what ran out (`creations`, `videos`, `previews`, or
    `settings` when it comes from Configuración), the plan and the owner's contact."""
    return _request_more(tenant_id, email=email, exhausted=exhausted)
