"""Where a chat's payment stands (m-24955648, UX spec `docs/ux-paso-de-pago.md` §3–§4):
«Esperando el pago» → «Pago por revisar» → «Pago recibido», or «Paga al recibir».

## Where it lives

In the thread's `whatsapp_thread_state.context`, under the reserved key `_payment`, next
to the order record (`orders.CTX_ORDER_RECORD`, `_order`) — no new table, no migration.
One current payment per thread, like one current order:

    {"choice": "method" | "other" | "none",
     "method_id", "name", "currency", "pay_on_delivery",
     "status": "awaiting" | "review" | "on_delivery" | "received" | None,
     "order_message_id": the inbound wamid that confirmed the order (provenance),
     "chosen_at", "source": "menu" | "chat",
     "review_message_id", "review_at",                      # set by the webhook worker
     "confirmed_by", "confirmed_at", "notified", "confirm_outbox_id"}   # the owner's tap

## Who moves it

- The **menu** (`handler.py`) writes it when a confirmed order is handed over after the
  payment step: «awaiting» when the card went out, «on_delivery» for a method paid on
  delivery (no receipt is expected), no status when the customer chose «Otra forma» or
  did not choose. A person's «Formas de pago» send from the chat (`attachments`) writes
  «awaiting» too when the chat has an order.
- The **webhook worker** moves «awaiting» → «review» on the customer's next text or
  media message (a tap or a menu keyword is not), with a guarded UPDATE
  (`repository.mark_payment_review`); its own whole-state save keeps `_payment` as
  stored. A person re-sending the card for the same order never regresses «review» or
  «received» (`_SET_RECORD`'s guard).
  The automation answers nothing: the thread was already handed to a person.
- **Only a person** moves it to «received»: `PaymentStatusService.confirm_payment` (the
  owner's «Enviar y marcar pagado») sends the owner's message through the normal reply
  path — the 24 h window refuses BEFORE anything is marked — then records who and when;
  `mark_paid_without_message` («Marcar pagado sin avisar», for a closed window) records
  it without sending. Nothing here ever runs by itself.

Every write is a guarded `jsonb_set` on `_payment` (never a whole-context overwrite), so
the worker and the app cannot clobber each other's keys.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_api.whatsapp.chats import ChatService, TextSend
from qualify_api.whatsapp.orders import read_order

CTX_PAYMENT_RECORD: Final = "_payment"

STATUS_AWAITING: Final = "awaiting"
STATUS_REVIEW: Final = "review"
STATUS_ON_DELIVERY: Final = "on_delivery"
STATUS_RECEIVED: Final = "received"
#: What the owner reads (spec §4 `signal_pill`).
STATUS_LABELS: Final[dict[str, str]] = {
    STATUS_AWAITING: "Esperando el pago",
    STATUS_REVIEW: "Pago por revisar",
    STATUS_ON_DELIVERY: "Paga al recibir",
    STATUS_RECEIVED: "Pago recibido",
}
#: The order card's «Forma de pago: …» when no method was chosen (spec §3).
CHOICE_LABELS: Final[dict[str, str]] = {"other": "quiere otra", "none": "no eligió"}
#: The owner's pre-written texts (spec §4); the owner may edit them before sending.
CONFIRM_TEXT: Final = "¡Pago recibido, gracias! Ya estamos preparando tu pedido."
#: Paid on delivery: the order already arrived, so nothing is «being prepared».
CONFIRM_ON_DELIVERY_TEXT: Final = "¡Pago recibido, gracias por tu compra!"
NOT_FOUND_TEXT: Final = (
    "Todavía no nos aparece tu pago. ¿Nos mandas la foto del comprobante o el número de referencia?"
)
_CONFIRMABLE: Final = (STATUS_AWAITING, STATUS_REVIEW, STATUS_ON_DELIVERY, None)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NoPendingPayment(LookupError):
    """«Pago recibido» on a thread with no payment record, or one already received."""


# ======================================================================================
# The record (pure)
# ======================================================================================


def payment_record(
    choice: Mapping[str, Any], *, order_message_id: str | None, at: datetime, source: str
) -> dict[str, Any]:
    """The `_payment` record for an engine choice (`menus.engine` `context["payment"]`)
    or a person's send from the chat."""
    picked = choice.get("choice") == "method"
    status: str | None = None
    if picked:
        status = STATUS_ON_DELIVERY if choice.get("pay_on_delivery") else STATUS_AWAITING
    return {
        "choice": choice.get("choice") or "none",
        "method_id": choice.get("method_id") if picked else None,
        "name": choice.get("name") if picked else None,
        "currency": choice.get("currency") if picked else None,
        "pay_on_delivery": bool(choice.get("pay_on_delivery")) if picked else False,
        "status": status,
        "order_message_id": order_message_id,
        "chosen_at": at.isoformat(),
        "source": source,
    }


@dataclass(frozen=True)
class PaymentStatus:
    """What the chats list and the thread header read (spec §4)."""

    status: str | None
    label: str
    choice: str
    method_id: str | None
    method_name: str | None
    currency: str | None
    pay_on_delivery: bool
    order_total: Decimal | None
    order_currency: str | None
    confirmed_by: UUID | None = None
    confirmed_at: datetime | None = None
    #: The pre-written «Pago recibido» message for THIS order (the sheet shows it; the
    #: owner may edit it): `CONFIRM_ON_DELIVERY_TEXT` when paid on delivery.
    confirm_text: str = CONFIRM_TEXT

    @property
    def needs_review(self) -> bool:
        return self.status == STATUS_REVIEW


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def read_payment(context: Mapping[str, Any] | None) -> PaymentStatus | None:
    record = (context or {}).get(CTX_PAYMENT_RECORD)
    if not isinstance(record, Mapping):
        return None
    status = record.get("status")
    status = status if status in STATUS_LABELS else None
    choice = str(record.get("choice") or "none")
    label = STATUS_LABELS[status] if status else CHOICE_LABELS.get(choice, "")
    order = read_order(context)
    confirmed_by = record.get("confirmed_by")
    try:
        by = UUID(str(confirmed_by)) if confirmed_by else None
    except ValueError:
        by = None
    return PaymentStatus(
        status=status,
        label=label,
        choice=choice,
        method_id=record.get("method_id"),
        method_name=record.get("name"),
        currency=record.get("currency"),
        pay_on_delivery=bool(record.get("pay_on_delivery")),
        order_total=order.total if order is not None else None,
        order_currency=order.currency if order is not None else None,
        confirmed_by=by,
        confirmed_at=_when(record.get("confirmed_at")),
        confirm_text=(CONFIRM_ON_DELIVERY_TEXT if record.get("pay_on_delivery") else CONFIRM_TEXT),
    )


# ======================================================================================
# Store
# ======================================================================================


class PaymentStatusStore(Protocol):
    def context(self, tenant_id: UUID, thread_id: UUID) -> dict[str, Any]: ...

    def contexts(self, tenant_id: UUID, thread_ids: Iterable[UUID]) -> dict[UUID, dict]: ...

    def mark_received(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        at: datetime,
        notified: bool,
        outbox_id: UUID | None,
    ) -> bool:
        """`_payment.status` → «received» unless it already is; True if it moved."""
        ...

    def set_record(self, *, tenant_id: UUID, thread_id: UUID, record: dict[str, Any]) -> bool:
        """Replace `_payment` (a person's send from the chat) — unless the record is
        already «review» or «received» for the same order (`order_message_id`): a re-send
        never regresses it. False with no state row or when kept."""
        ...


_MARK_RECEIVED = """
UPDATE whatsapp_thread_state
   SET context = jsonb_set(
           context, '{_payment}',
           (context->'_payment') || jsonb_build_object(
               'status', 'received',
               'confirmed_by', CAST(:user_id AS text),
               'confirmed_at', CAST(:at AS text),
               'notified', CAST(:notified AS boolean),
               'confirm_outbox_id', CAST(:outbox_id AS text))),
       updated_at = now()
 WHERE thread_id = :thread_id
   AND jsonb_typeof(context->'_payment') = 'object'
   AND COALESCE(context->'_payment'->>'status', '') <> 'received'
"""

# A person re-sending the card for the SAME order must not regress it: a record already
# «review» or «received» for that order is kept (`_KEEPS`).
_SET_RECORD = """
UPDATE whatsapp_thread_state
   SET context = jsonb_set(context, '{_payment}', CAST(:record AS jsonb)), updated_at = now()
 WHERE thread_id = :thread_id
   AND NOT (
       jsonb_typeof(context->'_payment') = 'object'
       AND context->'_payment'->>'order_message_id'
           IS NOT DISTINCT FROM CAST(:order_message_id AS text)
       AND context->'_payment'->>'status' IN ('review', 'received')
   )
"""
_KEEPS: Final = (STATUS_REVIEW, STATUS_RECEIVED)


class PostgresPaymentStatusStore:
    """`tenant_session(tenant_id)` per call (`qualify_app`: SELECT/UPDATE on
    `whatsapp_thread_state` since 0057; RLS bounds every statement)."""

    def context(self, tenant_id: UUID, thread_id: UUID) -> dict[str, Any]:
        return self.contexts(tenant_id, [thread_id]).get(thread_id, {})

    def contexts(self, tenant_id: UUID, thread_ids: Iterable[UUID]) -> dict[UUID, dict]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppThreadState  # noqa: PLC0415

        ids = list(dict.fromkeys(thread_ids))
        if not ids:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(WhatsAppThreadState.thread_id, WhatsAppThreadState.context).where(
                    WhatsAppThreadState.thread_id.in_(ids)
                )
            ).all()
        return {r.thread_id: dict(r.context or {}) for r in rows}

    def mark_received(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        at: datetime,
        notified: bool,
        outbox_id: UUID | None,
    ) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            result = session.execute(
                text(_MARK_RECEIVED),
                {
                    "thread_id": thread_id,
                    "user_id": str(user_id),
                    "at": at.isoformat(),
                    "notified": notified,
                    "outbox_id": str(outbox_id) if outbox_id else None,
                },
            )
        return bool(result.rowcount)

    def set_record(self, *, tenant_id: UUID, thread_id: UUID, record: dict[str, Any]) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            result = session.execute(
                text(_SET_RECORD),
                {
                    "thread_id": thread_id,
                    "record": json.dumps(record, ensure_ascii=False),
                    "order_message_id": record.get("order_message_id"),
                },
            )
        return bool(result.rowcount)


class MemoryPaymentStatusStore:
    """Over `chats.MemoryChatRepository.states` (the same thread state the chat tests
    use), tenant-checked like RLS."""

    def __init__(self, chat_repo: Any) -> None:
        self._repo = chat_repo

    def _state(self, tenant_id: UUID, thread_id: UUID) -> Any:
        state = self._repo.states.get(thread_id)
        return state if state is not None and state.tenant_id == tenant_id else None

    def context(self, tenant_id: UUID, thread_id: UUID) -> dict[str, Any]:
        state = self._state(tenant_id, thread_id)
        return dict(state.context) if state is not None else {}

    def contexts(self, tenant_id: UUID, thread_ids: Iterable[UUID]) -> dict[UUID, dict]:
        out: dict[UUID, dict] = {}
        for thread_id in thread_ids:
            state = self._state(tenant_id, thread_id)
            if state is not None:
                out[thread_id] = dict(state.context)
        return out

    def mark_received(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        at: datetime,
        notified: bool,
        outbox_id: UUID | None,
    ) -> bool:
        state = self._state(tenant_id, thread_id)
        record = state.context.get(CTX_PAYMENT_RECORD) if state is not None else None
        if not isinstance(record, dict) or record.get("status") == STATUS_RECEIVED:
            return False
        record.update(
            status=STATUS_RECEIVED,
            confirmed_by=str(user_id),
            confirmed_at=at.isoformat(),
            notified=notified,
            confirm_outbox_id=str(outbox_id) if outbox_id else None,
        )
        return True

    def set_record(self, *, tenant_id: UUID, thread_id: UUID, record: dict[str, Any]) -> bool:
        state = self._state(tenant_id, thread_id)
        if state is None:
            return False
        current = state.context.get(CTX_PAYMENT_RECORD)
        if (
            isinstance(current, dict)
            and current.get("order_message_id") == record.get("order_message_id")
            and current.get("status") in _KEEPS
        ):
            return False
        state.context[CTX_PAYMENT_RECORD] = dict(record)
        return True


# ======================================================================================
# Service (the owner's taps)
# ======================================================================================


class PaymentStatusService:
    def __init__(
        self,
        chats: ChatService,
        store: PaymentStatusStore,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._chats = chats
        self._store = store
        self._clock = clock

    def payment_for(self, tenant_id: UUID, thread_id: UUID) -> PaymentStatus | None:
        return read_payment(self._store.context(tenant_id, thread_id))

    def payments_for(
        self, tenant_id: UUID, thread_ids: Iterable[UUID]
    ) -> dict[UUID, PaymentStatus]:
        """For the chats list: the threads that carry a payment record."""
        out: dict[UUID, PaymentStatus] = {}
        for thread_id, context in self._store.contexts(tenant_id, thread_ids).items():
            payment = read_payment(context)
            if payment is not None:
                out[thread_id] = payment
        return out

    def _pending(self, tenant_id: UUID, thread_id: UUID) -> PaymentStatus:
        payment = self.payment_for(tenant_id, thread_id)
        if payment is None or payment.status not in _CONFIRMABLE:
            raise NoPendingPayment(str(thread_id))
        return payment

    def confirm_payment(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        message: str,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """«Enviar y marcar pagado»: the owner's message goes out through the normal
        reply path (window refused → `chats.WindowClosed`, nothing marked), then the
        payment is recorded as received by `user_id`. Returns the outbox id."""
        self._pending(tenant_id, thread_id)
        text = (message or "").strip()
        if not text:
            raise ValueError("the confirmation message must not be empty")
        if request_key is not None:
            outbox_id = self._chats.send_prepared(
                tenant_id,
                thread_id,
                user_id,
                lambda thread: _text_send(thread.wa_id, text),
                request_key=request_key,
            )
        else:
            outbox_id = self._chats.send(tenant_id, thread_id, user_id, TextSend(text=text))
        self._store.mark_received(
            tenant_id=tenant_id,
            thread_id=thread_id,
            user_id=user_id,
            at=self._clock(),
            notified=True,
            outbox_id=outbox_id,
        )
        return outbox_id

    def mark_paid_without_message(self, tenant_id: UUID, thread_id: UUID, user_id: UUID) -> None:
        """«Marcar pagado sin avisar» (spec §4, a closed window): records it, sends nothing."""
        self._pending(tenant_id, thread_id)
        self._store.mark_received(
            tenant_id=tenant_id,
            thread_id=thread_id,
            user_id=user_id,
            at=self._clock(),
            notified=False,
            outbox_id=None,
        )


def _text_send(to: str, text: str) -> Any:
    from qualify_api.whatsapp.chats import PreparedSend  # noqa: PLC0415
    from qualify_api.whatsapp.client import build_text_body  # noqa: PLC0415

    return PreparedSend(payload=build_text_body(to, text, False))


def production_payment_status_service(chats: ChatService) -> PaymentStatusService:
    return PaymentStatusService(chats, PostgresPaymentStatusStore())


__all__ = [
    "CHOICE_LABELS",
    "CONFIRM_ON_DELIVERY_TEXT",
    "CONFIRM_TEXT",
    "CTX_PAYMENT_RECORD",
    "NOT_FOUND_TEXT",
    "STATUS_AWAITING",
    "STATUS_LABELS",
    "STATUS_ON_DELIVERY",
    "STATUS_RECEIVED",
    "STATUS_REVIEW",
    "MemoryPaymentStatusStore",
    "NoPendingPayment",
    "PaymentStatus",
    "PaymentStatusService",
    "PaymentStatusStore",
    "PostgresPaymentStatusStore",
    "payment_record",
    "production_payment_status_service",
    "read_payment",
]
