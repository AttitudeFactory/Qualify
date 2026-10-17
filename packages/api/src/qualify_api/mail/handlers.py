"""The Resend handlers of the webhook processor (`docs/plan-altas-meegle.md` §3, M2).

Registered under `resend:<type>` (`webhooks.processor.handler_key`) for the three events
the invitation trail needs — `email.delivered`, `email.opened`, `email.bounced`. Any other
Resend event (`email.sent`, `email.clicked`, `email.complained`, …) has no handler and is
settled `unsupported` by the processor: recorded, ignored, replayable.

Each handler does two things, in this order:

1. **The invite row** (`auth.invites.mark_delivery`): match `data.email_id` to
   `signup_invites.resend_email_id` and set `delivered_at` / `opened_at` / `bounced_at`
   the first time only. No invite with that id (a password-recovery email Supabase sent
   through the same Resend account, or an email sent before M1 stored ids) → `processed`
   with `ignored:unknown_email`. A repeated event → `processed` with `ignored:repeat`, and
   Meegle is not written again.
2. **The Meegle item**, best-effort, only when the invite came from an "Alta de cliente"
   item (`meegle_work_item_id`) and the engine is configured: delivered → `entregada` and
   the node **Invitada** completed; opened → `abierta`; bounced → `rebotó` plus a comment
   with the bounce reason. A Meegle failure is logged with its type and settles the event
   `processed` with `meegle_failed:<type>` — the row is the record and a later event
   writes the next status; retrying would not re-run the write (the column is already
   set), so the queue's backoff has nothing to offer here.

A value that is not `{"type", "data": {"email_id"}}` is `dead` (`contract_violation`).
Anything the database raises propagates: the processor retries with backoff.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from qualify_api.auth.invites import (
    DELIVERY_BOUNCED,
    DELIVERY_DELIVERED,
    DELIVERY_OPENED,
    DeliveryMark,
    mark_delivery,
)
from qualify_api.mail.webhook import (
    EVENT_BOUNCED,
    EVENT_DELIVERED,
    EVENT_OPENED,
    OBJECT_RESEND,
    event_time_ms,
)
from qualify_api.webhooks.processor import Handler, Outcome, handler_key
from qualify_api.webhooks.repository import STATUS_DEAD, STATUS_PROCESSED, ClaimedEvent

logger = logging.getLogger("qualify_api.mail.handlers")

DELIVERED_HANDLER_KEY = handler_key(OBJECT_RESEND, EVENT_DELIVERED)
OPENED_HANDLER_KEY = handler_key(OBJECT_RESEND, EVENT_OPENED)
BOUNCED_HANDLER_KEY = handler_key(OBJECT_RESEND, EVENT_BOUNCED)

CONTRACT_VIOLATION = "contract_violation"
IGNORED_UNKNOWN_EMAIL = "ignored:unknown_email"
IGNORED_REPEAT = "ignored:repeat"
MEEGLE_FAILED_PREFIX = "meegle_failed:"
NO_PROVIDER_REASON = "sin detalle del proveedor"

# `kind` of `mark_delivery` per event type.
_KINDS = {
    EVENT_DELIVERED: DELIVERY_DELIVERED,
    EVENT_OPENED: DELIVERY_OPENED,
    EVENT_BOUNCED: DELIVERY_BOUNCED,
}

# `(email_id, kind=…, at=…) -> DeliveryMark | None`
DeliveryMarker = Callable[..., DeliveryMark | None]


class DeliveryNotifier(Protocol):
    """The slice of `qualify_api.meegle.onboarding.OnboardingEngine` the handlers write
    through. None when Meegle is off."""

    def mark_delivered(self, work_item_id: int, *, already_opened: bool = False) -> None: ...

    def mark_opened(self, work_item_id: int) -> None: ...

    def mark_bounced(self, work_item_id: int, reason: str) -> None: ...


class _Bounce(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str | None = None
    type: str | None = None
    subType: str | None = None  # noqa: N815 — Resend's own spelling


class _EventData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email_id: str
    created_at: str | None = None
    bounce: _Bounce | None = None


class ResendEvent(BaseModel):
    """The recorded value of one Resend change (`webhook.parse_resend_delivery`)."""

    model_config = ConfigDict(extra="ignore")
    type: str
    created_at: str | None = None
    data: _EventData

    def happened_at(self) -> datetime | None:
        ms = event_time_ms(self.created_at) or event_time_ms(self.data.created_at)
        return datetime.fromtimestamp(ms / 1000, UTC) if ms is not None else None

    def bounce_reason(self) -> str:
        bounce = self.data.bounce
        if bounce is None:
            return NO_PROVIDER_REASON
        parts = [p for p in (bounce.message, bounce.type, bounce.subType) if p]
        if not parts:
            return NO_PROVIDER_REASON
        message, *tags = parts
        return f"{message} ({' / '.join(tags)})" if tags else message


def _log_bounce_shape(event: ClaimedEvent) -> None:
    """Resend's bounce shape is documented loosely; log the keys actually seen so the
    first real bounce tells us whether `bounce_reason` reads the right ones."""
    value = event.value if isinstance(event.value, dict) else {}
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    bounce = data.get("bounce") if isinstance(data.get("bounce"), dict) else {}
    logger.info(
        "resend bounce: event=%s data_keys=%s bounce_keys=%s",
        event.id,
        sorted(data),
        sorted(bounce),
    )


def resend_handlers(
    notifier: DeliveryNotifier | None,
    *,
    marker: DeliveryMarker = mark_delivery,
) -> Mapping[str, Handler]:
    async def handle(event: ClaimedEvent) -> Outcome:
        try:
            parsed = ResendEvent.model_validate(event.value or {})
        except ValidationError:
            logger.error("resend event=%s field=%s value off-contract", event.id, event.field)
            return Outcome(STATUS_DEAD, CONTRACT_VIOLATION)
        kind = _KINDS.get(parsed.type)
        if kind is None:
            # Registered keys never reach here; a renamed field would.
            logger.error("resend event=%s type=%r has no handler", event.id, parsed.type)
            return Outcome(STATUS_DEAD, CONTRACT_VIOLATION)
        if parsed.type == EVENT_BOUNCED:
            _log_bounce_shape(event)

        # Sync DB write — off the event loop.
        mark = await asyncio.to_thread(
            marker, parsed.data.email_id, kind=kind, at=parsed.happened_at()
        )
        if mark is None:
            logger.info(
                "resend %s: email_id=%s matches no invite", parsed.type, parsed.data.email_id
            )
            return Outcome(STATUS_PROCESSED, IGNORED_UNKNOWN_EMAIL)
        if not mark.first:
            return Outcome(STATUS_PROCESSED, IGNORED_REPEAT)
        logger.info(
            "resend %s: invite=%s work_item=%s",
            parsed.type,
            mark.invite_id,
            mark.meegle_work_item_id,
        )
        if notifier is None or mark.meegle_work_item_id is None:
            return Outcome(STATUS_PROCESSED)

        try:
            await asyncio.to_thread(_notify, notifier, parsed, mark)
        except Exception as exc:  # noqa: BLE001 — best-effort: the row is the record
            logger.warning(
                "resend %s: invite=%s work_item=%s Meegle write-back failed (%s)",
                parsed.type,
                mark.invite_id,
                mark.meegle_work_item_id,
                type(exc).__name__,
            )
            return Outcome(STATUS_PROCESSED, f"{MEEGLE_FAILED_PREFIX}{type(exc).__name__}"[:200])
        return Outcome(STATUS_PROCESSED)

    return {
        DELIVERED_HANDLER_KEY: handle,
        OPENED_HANDLER_KEY: handle,
        BOUNCED_HANDLER_KEY: handle,
    }


def _notify(notifier: DeliveryNotifier, parsed: ResendEvent, mark: DeliveryMark) -> None:
    work_item_id = mark.meegle_work_item_id
    assert work_item_id is not None
    if parsed.type == EVENT_DELIVERED:
        notifier.mark_delivered(work_item_id, already_opened=mark.opened_at is not None)
    elif parsed.type == EVENT_OPENED:
        notifier.mark_opened(work_item_id)
    else:
        notifier.mark_bounced(work_item_id, parsed.bounce_reason())


def production_resend_handlers() -> Mapping[str, Handler]:
    """What `webhooks.processor.production_processor` registers: the invite columns are
    always written; the Meegle half only when the engine is configured."""
    from qualify_api.meegle.settings import meegle_configured  # noqa: PLC0415

    notifier: Any = None
    if meegle_configured():
        from qualify_api.meegle.handlers import production_engine  # noqa: PLC0415

        notifier = production_engine()
    else:
        logger.info("resend handlers: Meegle engine off, delivery trail stays in signup_invites")
    return resend_handlers(notifier)


__all__ = [
    "BOUNCED_HANDLER_KEY",
    "CONTRACT_VIOLATION",
    "DELIVERED_HANDLER_KEY",
    "IGNORED_REPEAT",
    "IGNORED_UNKNOWN_EMAIL",
    "MEEGLE_FAILED_PREFIX",
    "OPENED_HANDLER_KEY",
    "DeliveryNotifier",
    "ResendEvent",
    "production_resend_handlers",
    "resend_handlers",
]
