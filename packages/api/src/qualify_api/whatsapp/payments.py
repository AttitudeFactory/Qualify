"""How a business takes payment (m-24955648, design `docs/opciones-conectar-sistema-de-
pedidos.md` §3.1, founder decision D3): the methods the owner offers, per business, for the
WhatsApp menu's payment step and the chat picker. Table `brand_payment_methods` (0135).

## Why it lives in `whatsapp/`

Its only readers are WhatsApp's: the automatic menu (the `payment_method` step, part 2),
the chat picker («Formas de pago») and the starter's «Formas de pago» answer. It is not
catalog data (a method is not sold) and the catalog module belongs to another area; if a
second channel ever needs it, it moves up — the table does not change.

## Rules

- **Assisted, never autonomous.** This module says HOW to pay; it records no payment and
  never marks one as received — the owner or the cashier does that by hand.
- **One list, two uses.** `active_payment_methods(tenant_id, brand_id)` is the one reader
  of what a customer may be offered (active, by `position`), for the chat (`qualify_app`,
  RLS) and for the menu worker (`as_worker=True`: `qualify_webhook_worker`, BYPASSRLS,
  only the 0135-granted columns, tenant AND brand filtered in code).
- **Active needs content.** A method paid before delivery can be active only with
  instructions or a QR (also a CHECK in 0135): an active method with nothing to send
  leaves the customer stuck. A `pay_on_delivery` one (cash on arrival) needs neither —
  part 2 asks no receipt for it. At most `MAX_ACTIVE` (10) active per business.
- **No placeholder reaches a customer.** Instructions that still hold a `[…]` gap (the
  starter's `find_gaps`, so a `[x](url)` link is not one) are refused on every save.
- Limits come from the UX spec `docs/ux-paso-de-pago.md` §1: name ≤ 20 (a button label),
  instructions ≤ 900.
- **Names fold** like categories (`catalog.order.category_key`): «Pago Móvil» and «pago
  movil» are the same name in a business.
- **The QR image** is normalised exactly like a chat photo (`attachments.fit_image`:
  ≤ 15 MB in, JPEG/PNG ≤ 5 MB out, 40 MP guard) and stored through `ObjectGate` at
  `t/{tenant}/whatsapp/payments/{brand}/{uuid}.{jpg|png}`. That root is outside
  `PURGEABLE_ROOTS`: piece retention (ADR 39) never touches it; a replaced or removed QR
  is deleted by its exact key (`ObjectGate.delete_payment_qr`), after the row points
  elsewhere — a failed delete leaves an orphan, never a row without its image.
- Owner-facing refusals are typed errors whose `message` is Spanish (qualify-copy-es).
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_shared.objects.keys import tenant_prefix

from qualify_api.catalog.order import category_key
from qualify_api.whatsapp.attachments import (
    MAX_INPUT_BYTES,
    PHONE_PHOTO_TYPES,
    AttachmentRefused,
    fit_image,
    sniff_image_type,
)
from qualify_api.whatsapp.menus.engine import PaymentOption

logger = logging.getLogger("qualify_api.whatsapp.payments")

#: A WhatsApp reply-button label (the payment step shows ≤ 3 methods as buttons).
MAX_NAME_CHARS: Final = 20
#: The QR's caption is these + the total + the closing line (~120), within 1024.
MAX_INSTRUCTIONS_CHARS: Final = 900
#: The rows one WhatsApp list message holds (4 to 10 active methods go as a list).
MAX_ACTIVE: Final = 10
SOURCES: Final = ("manual", "import")
_CURRENCY = re.compile(r"[A-Z0-9]{0,8}")
_EXTENSIONS: Final = {"image/jpeg": "jpg", "image/png": "png"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def name_key(name: str) -> str:
    """The comparable form of a method name (the categories' fold)."""
    return category_key(name)


def payments_prefix(tenant_id: UUID, brand_id: UUID) -> str:
    return f"{tenant_prefix(tenant_id)}whatsapp/payments/{brand_id}/"


# ======================================================================================
# Errors (Spanish `message` for the owner)
# ======================================================================================


class PaymentMethodError(ValueError):
    """A refusal the owner reads as it is (`message`)."""

    message: str = "No pudimos guardar la forma de pago."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message


class PaymentMethodNotFound(LookupError):
    """No method with this id in this business (another tenant's reads as missing)."""


class PaymentNameRequired(PaymentMethodError):
    message = "Escribe el nombre de la forma de pago."


class PaymentNameTooLong(PaymentMethodError):
    message = f"El nombre admite hasta {MAX_NAME_CHARS} caracteres."


class PaymentNameTaken(PaymentMethodError):
    message = "Ya tienes una forma de pago con ese nombre."


class PaymentInstructionsTooLong(PaymentMethodError):
    message = f"Las instrucciones admiten hasta {MAX_INSTRUCTIONS_CHARS} caracteres."


class PaymentCurrencyInvalid(PaymentMethodError):
    message = "Escribe la moneda con su código, por ejemplo USD, VES o COP."


class PaymentMethodIncomplete(PaymentMethodError):
    message = "Para ofrecerla, escribe cómo te pagan o sube tu QR."


class PaymentTooManyActive(PaymentMethodError):
    message = (
        f"Puedes ofrecer hasta {MAX_ACTIVE} formas de pago a la vez. Apaga una para ofrecer esta."
    )


class PaymentPlaceholderLeft(PaymentMethodError):
    """Instructions still holding a `[…]` gap; `gaps` names them."""

    def __init__(self, gaps: Sequence[str]) -> None:
        self.gaps = tuple(gaps)
        super().__init__(f"Cambia lo que está entre [ ] por tus datos: {', '.join(self.gaps)}.")


class PaymentImageRefused(PaymentMethodError):
    """The QR image was refused; `reason` is `attachments.AttachmentRefused`'s."""

    def __init__(self, refused: AttachmentRefused) -> None:
        super().__init__(refused.message)
        self.reason = refused.reason


class PaymentMethodRejected(PaymentMethodError):
    """The database refused the row for a reason the service did not foresee (a CHECK).
    Fixed text on purpose: Postgres' own message quotes the row — the bank data."""

    message = "No pudimos guardar la forma de pago. Revisa los datos y vuelve a intentarlo."


class PaymentOrderMismatch(PaymentMethodError):
    message = "La lista cambió mientras la ordenabas. Vuelve a intentarlo."


# ======================================================================================
# Records
# ======================================================================================


@dataclass(frozen=True)
class PaymentMethod:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    name: str
    name_key: str
    currency: str = ""
    instructions: str = ""
    qr_media_key: str | None = None
    active: bool = False
    pay_on_delivery: bool = False
    position: int = 0
    external_code: str | None = None
    source: str = "manual"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    @property
    def can_be_offered(self) -> bool:
        """Paid on delivery, or something to send: instructions or a QR."""
        return (
            self.pay_on_delivery or bool(self.instructions.strip()) or self.qr_media_key is not None
        )


# ======================================================================================
# Validation (pure)
# ======================================================================================


def clean_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise PaymentNameRequired()
    if len(cleaned) > MAX_NAME_CHARS:
        raise PaymentNameTooLong()
    return cleaned


def clean_instructions(text: str) -> str:
    from qualify_api.whatsapp.menus.starter import find_gaps  # noqa: PLC0415

    cleaned = (text or "").strip()
    if len(cleaned) > MAX_INSTRUCTIONS_CHARS:
        raise PaymentInstructionsTooLong()
    gaps = find_gaps(cleaned)
    if gaps:
        raise PaymentPlaceholderLeft(gaps)
    return cleaned


def clean_currency(code: str) -> str:
    cleaned = (code or "").strip().upper()
    if not _CURRENCY.fullmatch(cleaned):
        raise PaymentCurrencyInvalid()
    return cleaned


# ======================================================================================
# Seams
# ======================================================================================


class PaymentMethodRepository(Protocol):
    """Tenant-scoped (Postgres: `tenant_session` per call, RLS bounds every statement)."""

    def list(self, *, tenant_id: UUID, brand_id: UUID) -> list[PaymentMethod]: ...

    def get(self, *, tenant_id: UUID, method_id: UUID) -> PaymentMethod | None: ...

    def insert(self, method: PaymentMethod) -> PaymentMethod:
        """Raises `PaymentNameTaken` when `(brand_id, name_key)` exists."""
        ...

    def save(self, method: PaymentMethod) -> PaymentMethod:
        """Write the mutable fields of an existing row EXCEPT `active` (only `activate`
        and `deactivate` write it: a save that started while the method was offered must
        never turn it back on outside the lock). Validated against the row's CURRENT
        `active`: leaving an offered method with nothing to send raises
        `PaymentMethodIncomplete`. `PaymentNameTaken` on a clash. Returns the row as
        stored."""
        ...

    def deactivate(self, method: PaymentMethod, *, by: UUID | None, at: datetime) -> PaymentMethod:
        """Turn `method` off (no cap to respect)."""
        ...

    def save_qr(self, method: PaymentMethod) -> tuple[PaymentMethod, str | None]:
        """`save`, plus the QR key the row held right BEFORE this write (read on the
        locked row): the image to delete, even if another save replaced it meanwhile."""
        ...

    def set_positions(
        self, *, tenant_id: UUID, brand_id: UUID, positions: dict[UUID, int], by: UUID | None
    ) -> None: ...

    def activate(
        self, method: PaymentMethod, *, max_active: int, by: UUID | None, at: datetime
    ) -> PaymentMethod:
        """Turn `method` on unless the business already offers `max_active` others —
        count and write in ONE transaction under the business's lock, so two taps at
        once cannot both pass the count. Raises `PaymentTooManyActive`."""
        ...

    def delete(self, *, tenant_id: UUID, method_id: UUID) -> None: ...


class QrStore(Protocol):
    """`ObjectGate.put_media` + `ObjectGate.delete_payment_qr`."""

    def put(self, tenant_id: UUID, key: str, content: bytes, content_type: str) -> None: ...

    def delete(self, tenant_id: UUID, brand_id: UUID, key: str) -> None: ...


class ThumbLinker(Protocol):
    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str: ...


# ======================================================================================
# Service
# ======================================================================================


@dataclass(frozen=True)
class QrChange:
    """What `save_payment_method` does with the QR: a new image, or remove it."""

    content: bytes | None = None
    content_type: str = ""
    remove_image: bool = False

    @classmethod
    def image(cls, content: bytes, content_type: str) -> QrChange:
        return cls(content=content, content_type=content_type)

    @classmethod
    def remove(cls) -> QrChange:
        return cls(remove_image=True)


class PaymentMethodService:
    """The owner's «Formas de pago». Every method takes the caller's `tenant_id` and the
    business (`brand_id`); a method of another business reads as `PaymentMethodNotFound`."""

    def __init__(
        self,
        repo: PaymentMethodRepository,
        qr: QrStore,
        *,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], UUID] = uuid.uuid4,
    ) -> None:
        self._repo = repo
        self._qr = qr
        self._clock = clock
        self._new_id = id_factory

    def _method(self, tenant_id: UUID, brand_id: UUID, method_id: UUID) -> PaymentMethod:
        method = self._repo.get(tenant_id=tenant_id, method_id=method_id)
        if method is None or method.brand_id != brand_id:
            raise PaymentMethodNotFound(str(method_id))
        return method

    def list_payment_methods(
        self, *, tenant_id: UUID, brand_id: UUID, only_active: bool = False
    ) -> tuple[PaymentMethod, ...]:
        methods = sorted(
            self._repo.list(tenant_id=tenant_id, brand_id=brand_id),
            key=lambda m: (m.position, m.name_key, str(m.id)),
        )
        return tuple(m for m in methods if m.active or not only_active)

    def create_payment_method(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        name: str,
        currency: str = "",
        instructions: str = "",
        pay_on_delivery: bool = False,
        external_code: str | None = None,
        source: str = "manual",
    ) -> PaymentMethod:
        """A new method, inactive, at the end of the list."""
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        cleaned = clean_name(name)
        existing = self._repo.list(tenant_id=tenant_id, brand_id=brand_id)
        if any(m.name_key == name_key(cleaned) for m in existing):
            raise PaymentNameTaken()
        now = self._clock()
        return self._repo.insert(
            PaymentMethod(
                id=self._new_id(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                name=cleaned,
                name_key=name_key(cleaned),
                currency=clean_currency(currency),
                instructions=clean_instructions(instructions),
                pay_on_delivery=bool(pay_on_delivery),
                position=max((m.position for m in existing), default=-1) + 1,
                external_code=(external_code or "").strip() or None,
                source=source,
                created_by=user_id,
                updated_by=user_id,
                created_at=now,
                updated_at=now,
            )
        )

    def update_payment_method(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        method_id: UUID,
        user_id: UUID | None,
        name: str | None = None,
        currency: str | None = None,
        instructions: str | None = None,
        pay_on_delivery: bool | None = None,
    ) -> PaymentMethod:
        """Change what was given; stamps `updated_at`/`updated_by`. Leaving an active
        method with nothing to offer is refused."""
        method = self._method(tenant_id, brand_id, method_id)
        changes: dict[str, Any] = {}
        if name is not None:
            cleaned = clean_name(name)
            key = name_key(cleaned)
            if key != method.name_key and any(
                m.name_key == key and m.id != method.id
                for m in self._repo.list(tenant_id=tenant_id, brand_id=brand_id)
            ):
                raise PaymentNameTaken()
            changes.update(name=cleaned, name_key=key)
        if currency is not None:
            changes["currency"] = clean_currency(currency)
        if instructions is not None:
            changes["instructions"] = clean_instructions(instructions)
        if pay_on_delivery is not None:
            changes["pay_on_delivery"] = bool(pay_on_delivery)
        updated = replace(method, **changes, updated_by=user_id, updated_at=self._clock())
        if updated.active and not updated.can_be_offered:
            raise PaymentMethodIncomplete()
        return self._repo.save(updated)

    def set_active(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        method_id: UUID,
        user_id: UUID | None,
        active: bool,
    ) -> PaymentMethod:
        method = self._method(tenant_id, brand_id, method_id)
        if method.active == active:
            return method
        if active:
            if not method.can_be_offered:
                raise PaymentMethodIncomplete()
            # A row saved before the placeholder rule (an import) is checked again here.
            clean_instructions(method.instructions)
            return self._repo.activate(method, max_active=MAX_ACTIVE, by=user_id, at=self._clock())
        return self._repo.deactivate(method, by=user_id, at=self._clock())

    def reorder_payment_methods(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        ids: Sequence[UUID],
    ) -> tuple[PaymentMethod, ...]:
        """`ids` is the business's whole list in the new order (no more, no less)."""
        current = {m.id for m in self._repo.list(tenant_id=tenant_id, brand_id=brand_id)}
        wanted = list(dict.fromkeys(ids))
        if len(wanted) != len(ids) or set(wanted) != current:
            raise PaymentOrderMismatch()
        self._repo.set_positions(
            tenant_id=tenant_id,
            brand_id=brand_id,
            positions={method_id: i for i, method_id in enumerate(wanted)},
            by=user_id,
        )
        return self.list_payment_methods(tenant_id=tenant_id, brand_id=brand_id)

    def delete_payment_method(self, *, tenant_id: UUID, brand_id: UUID, method_id: UUID) -> None:
        method = self._method(tenant_id, brand_id, method_id)
        self._repo.delete(tenant_id=tenant_id, method_id=method_id)
        if method.qr_media_key:
            self._forget(tenant_id, brand_id, method.qr_media_key)

    def set_qr_image(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        method_id: UUID,
        user_id: UUID | None,
        content: bytes,
        content_type: str,
        filename: str = "",
    ) -> PaymentMethod:
        """Normalise the QR like a chat photo, store it, point the method at it, then
        delete the image it replaces."""
        method = self._method(tenant_id, brand_id, method_id)
        key, data = self._store_qr(tenant_id, brand_id, content, content_type)
        try:
            saved, previous = self._repo.save_qr(
                replace(method, qr_media_key=key, updated_by=user_id, updated_at=self._clock())
            )
        except Exception:
            # Nothing points at the new object: delete it (it is outside the purgeable
            # roots, nothing else would), then let the failure through.
            self._forget(tenant_id, brand_id, key)
            raise
        if previous and previous != key:
            self._forget(tenant_id, brand_id, previous)
        logger.info(
            "whatsapp.payments.qr_set method_id=%s bytes=%d filename_len=%d",
            method_id,
            len(data),
            len(filename or ""),
        )
        return saved

    def _store_qr(
        self, tenant_id: UUID, brand_id: UUID, content: bytes, content_type: str
    ) -> tuple[str, bytes]:
        """Normalise like a chat photo and upload under a new key; returns (key, bytes)."""
        declared = (content_type or "").split(";", 1)[0].strip().lower()
        try:
            if declared not in PHONE_PHOTO_TYPES or sniff_image_type(content or b"") is None:
                raise AttachmentRefused("unsupported_type" if content else "empty")
            if len(content) > MAX_INPUT_BYTES:
                raise AttachmentRefused("too_large")
            data, stored_type = fit_image(content)
        except AttachmentRefused as refused:
            raise PaymentImageRefused(refused) from refused
        name = f"{self._new_id().hex}.{_EXTENSIONS[stored_type]}"
        key = f"{payments_prefix(tenant_id, brand_id)}{name}"
        self._qr.put(tenant_id, key, data, stored_type)
        return key, data

    def save_payment_method(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        method_id: UUID,
        user_id: UUID | None,
        name: str | None = None,
        currency: str | None = None,
        instructions: str | None = None,
        pay_on_delivery: bool | None = None,
        qr: QrChange | None = None,
    ) -> PaymentMethod:
        """ONE save for the fields AND the QR (m-24955648): everything is validated on the
        final state, the new image (if any) is uploaded first, the row is written once
        with the fields and `qr_media_key` together — so a customer can never get new
        instructions with an old QR — and only then is the replaced image deleted. A
        failed write deletes the new image. `qr=None` keeps the current one,
        `QrChange.remove()` drops it, `QrChange.image(…)` replaces it."""
        method = self._method(tenant_id, brand_id, method_id)
        changes: dict[str, Any] = {}
        if name is not None:
            cleaned = clean_name(name)
            key_name = name_key(cleaned)
            if key_name != method.name_key and any(
                m.name_key == key_name and m.id != method.id
                for m in self._repo.list(tenant_id=tenant_id, brand_id=brand_id)
            ):
                raise PaymentNameTaken()
            changes.update(name=cleaned, name_key=key_name)
        if currency is not None:
            changes["currency"] = clean_currency(currency)
        if instructions is not None:
            changes["instructions"] = clean_instructions(instructions)
        if pay_on_delivery is not None:
            changes["pay_on_delivery"] = bool(pay_on_delivery)
        if qr is not None and qr.remove_image:
            changes["qr_media_key"] = None
        final = replace(method, **changes, updated_by=user_id, updated_at=self._clock())
        # Validated BEFORE anything is uploaded: the final state, the new image included.
        will_have_qr = (qr is not None and qr.content is not None) or final.qr_media_key
        if final.active and not (
            final.pay_on_delivery or final.instructions.strip() or will_have_qr
        ):
            raise PaymentMethodIncomplete()
        new_key: str | None = None
        if qr is not None and qr.content is not None:
            new_key, _ = self._store_qr(tenant_id, brand_id, qr.content, qr.content_type)
            final = replace(final, qr_media_key=new_key)
        try:
            # The key to delete comes from the LOCKED row, not from the read above.
            saved, previous = self._repo.save_qr(final)
        except Exception:
            if new_key is not None:
                self._forget(tenant_id, brand_id, new_key)
            raise
        if previous and previous != saved.qr_media_key:
            self._forget(tenant_id, brand_id, previous)
        return saved

    def remove_qr_image(
        self, *, tenant_id: UUID, brand_id: UUID, method_id: UUID, user_id: UUID | None
    ) -> PaymentMethod:
        method = self._method(tenant_id, brand_id, method_id)
        if method.qr_media_key is None:
            return method
        updated = replace(method, qr_media_key=None, updated_by=user_id, updated_at=self._clock())
        if updated.active and not updated.can_be_offered:
            raise PaymentMethodIncomplete()
        saved, previous = self._repo.save_qr(updated)
        if previous:
            self._forget(tenant_id, brand_id, previous)
        return saved

    def _forget(self, tenant_id: UUID, brand_id: UUID, key: str) -> None:
        try:
            self._qr.delete(tenant_id, brand_id, key)
        except Exception as exc:  # noqa: BLE001 — an orphan object, never a broken row
            logger.warning("whatsapp.payments.qr_delete_failed error=%s", type(exc).__name__)


# ======================================================================================
# The one reader of what a customer may be offered
# ======================================================================================


def _from_row(row: Any) -> PaymentMethod:
    return PaymentMethod(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        name=row.name,
        name_key=getattr(row, "name_key", "") or name_key(row.name),
        currency=row.currency or "",
        instructions=row.instructions or "",
        qr_media_key=row.qr_media_key,
        active=bool(row.active),
        pay_on_delivery=bool(getattr(row, "pay_on_delivery", False)),
        position=int(row.position or 0),
        external_code=getattr(row, "external_code", None),
        source=getattr(row, "source", "manual") or "manual",
        created_by=getattr(row, "created_by", None),
        updated_by=getattr(row, "updated_by", None),
        created_at=getattr(row, "created_at", None) or _utcnow(),
        updated_at=getattr(row, "updated_at", None) or _utcnow(),
    )


def active_payment_methods(
    tenant_id: UUID, brand_id: UUID, *, as_worker: bool = False
) -> tuple[PaymentMethod, ...]:
    """The business's active methods, by `position` — what the menu's payment step and
    the chat picker offer. `as_worker=True` reads as `qualify_webhook_worker` (the menu
    engine's door): only the columns 0135 grants it, tenant AND brand filtered here."""
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

    columns = (
        T.id,
        T.tenant_id,
        T.brand_id,
        T.name,
        T.currency,
        T.instructions,
        T.qr_media_key,
        T.active,
        T.pay_on_delivery,
        T.position,
    )
    stmt = (
        select(*columns)
        .where(T.tenant_id == tenant_id, T.brand_id == brand_id, T.active.is_(True))
        .order_by(T.position, T.name, T.id)
    )
    if as_worker:
        from qualify_shared.db.webhook import webhook_worker_session  # noqa: PLC0415

        with webhook_worker_session() as session:
            rows = session.execute(stmt).all()
    else:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(stmt).all()
    return tuple(_from_row(r) for r in rows)


def as_option(method: PaymentMethod) -> PaymentOption:
    """The engine's pure view of a method (`menus.engine.PaymentOption`)."""
    return PaymentOption(
        id=str(method.id),
        name=method.name,
        currency=method.currency,
        instructions=method.instructions,
        qr_media_key=method.qr_media_key,
        pay_on_delivery=method.pay_on_delivery,
        brand_id=str(method.brand_id),
    )


def current_qr_key(*, tenant_id: UUID, method_id: str, brand_id: str = "") -> str | None:
    """The method's QR key NOW, for a menu card whose image was replaced or removed. Read
    through the same door as every other read of the WhatsApp sender:
    `tenant_session(tenant_id)` (`qualify_app` under RLS — the whatsapp-worker drains each
    tenant's outbox that way; it never uses the webhook worker's door). Only
    `qr_media_key` is read, and only for a method STILL OFFERED (`active`) of that
    business. `None` — the card then goes as text — for a method turned off, gone, of
    another business or tenant, or without a QR."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

    try:
        method_uuid, brand_uuid = UUID(method_id), UUID(brand_id)
    except ValueError:
        return None
    with tenant_session(tenant_id) as session:
        return session.scalar(
            select(T.qr_media_key).where(
                T.id == method_uuid, T.brand_id == brand_uuid, T.active.is_(True)
            )
        )


def load_payment_options_for_phone(phone_number_row_id: UUID) -> tuple[PaymentOption, ...]:
    """The production `payment_loader` of the WA-07 handler (m-24955648), as
    `qualify_webhook_worker`: phone row → `(tenant_id, brand_id)` (0059's grants, as the
    catalog loader), then the business's active methods through the 0134 column grants.
    Empty for an unknown number or one without a business."""
    from qualify_shared.db.webhook import webhook_worker_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.whatsapp.models import WhatsAppPhoneNumber  # noqa: PLC0415

    with webhook_worker_session() as session:
        phone = session.execute(
            select(WhatsAppPhoneNumber.tenant_id, WhatsAppPhoneNumber.brand_id).where(
                WhatsAppPhoneNumber.id == phone_number_row_id
            )
        ).first()
    if phone is None or phone.brand_id is None:
        return ()
    return tuple(
        as_option(m)
        for m in active_payment_methods(phone.tenant_id, phone.brand_id, as_worker=True)
    )


def qr_thumb_url(tenant_id: UUID, method: PaymentMethod, linker: ThumbLinker | None = None) -> str:
    """A 15-minute public-media URL for the method's QR, or "" (no QR, or no linker)."""
    key = method.qr_media_key
    if not key or not key.startswith(payments_prefix(tenant_id, method.brand_id)):
        return ""
    if linker is None:
        from qualify_api.whatsapp.attachments import production_thumb_linker  # noqa: PLC0415

        linker = production_thumb_linker()
        if linker is None:
            return ""
    content_type = "image/png" if key.endswith(".png") else "image/jpeg"
    try:
        return linker.link(tenant_id=tenant_id, object_key=key, content_type=content_type)
    except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth the screen
        logger.warning("whatsapp.payments.thumb_failed error=%s", type(exc).__name__)
        return ""


# ======================================================================================
# Implementations
# ======================================================================================


class MemoryPaymentMethodRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, PaymentMethod] = {}

    def list(self, *, tenant_id: UUID, brand_id: UUID) -> list[PaymentMethod]:
        return [
            m for m in self.rows.values() if m.tenant_id == tenant_id and m.brand_id == brand_id
        ]

    def get(self, *, tenant_id: UUID, method_id: UUID) -> PaymentMethod | None:
        found = self.rows.get(method_id)
        return found if found is not None and found.tenant_id == tenant_id else None

    def _clash(self, method: PaymentMethod) -> bool:
        return any(
            m.brand_id == method.brand_id and m.name_key == method.name_key and m.id != method.id
            for m in self.rows.values()
        )

    def insert(self, method: PaymentMethod) -> PaymentMethod:
        if self._clash(method):
            raise PaymentNameTaken()
        self.rows[method.id] = method
        return method

    def save(self, method: PaymentMethod) -> PaymentMethod:
        current = self.get(tenant_id=method.tenant_id, method_id=method.id)
        if current is None:
            raise PaymentMethodNotFound(str(method.id))
        if self._clash(method):
            raise PaymentNameTaken()
        stored = replace(method, active=current.active)  # never written by a save
        if stored.active and not stored.can_be_offered:
            raise PaymentMethodIncomplete()
        self.rows[method.id] = stored
        return stored

    def save_qr(self, method: PaymentMethod) -> tuple[PaymentMethod, str | None]:
        current = self.get(tenant_id=method.tenant_id, method_id=method.id)
        previous = current.qr_media_key if current is not None else None
        return self.save(method), previous

    def deactivate(self, method: PaymentMethod, *, by: UUID | None, at: datetime) -> PaymentMethod:
        current = self.get(tenant_id=method.tenant_id, method_id=method.id)
        if current is None:
            raise PaymentMethodNotFound(str(method.id))
        stored = replace(current, active=False, updated_by=by, updated_at=at)
        self.rows[method.id] = stored
        return stored

    def set_positions(
        self, *, tenant_id: UUID, brand_id: UUID, positions: dict[UUID, int], by: UUID | None
    ) -> None:
        for method_id, position in positions.items():
            row = self.get(tenant_id=tenant_id, method_id=method_id)
            if row is not None and row.brand_id == brand_id:
                self.rows[method_id] = replace(row, position=position, updated_by=by)

    def activate(
        self, method: PaymentMethod, *, max_active: int, by: UUID | None, at: datetime
    ) -> PaymentMethod:
        # The store itself, as the Postgres count reads the table inside the lock.
        others = [
            m
            for m in self.rows.values()
            if m.tenant_id == method.tenant_id and m.brand_id == method.brand_id
        ]
        if sum(1 for m in others if m.active and m.id != method.id) >= max_active:
            raise PaymentTooManyActive()
        current = self.get(tenant_id=method.tenant_id, method_id=method.id)
        if current is None:
            raise PaymentMethodNotFound(str(method.id))
        _check_offerable(current)  # the stored row, as Postgres checks the locked one
        stored = replace(current, active=True, updated_by=by, updated_at=at)
        self.rows[method.id] = stored
        return stored

    def delete(self, *, tenant_id: UUID, method_id: UUID) -> None:
        if self.get(tenant_id=tenant_id, method_id=method_id) is not None:
            del self.rows[method_id]


class MemoryQrStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[UUID, str], tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    def put(self, tenant_id: UUID, key: str, content: bytes, content_type: str) -> None:
        if not key.startswith(tenant_prefix(tenant_id)):
            raise PermissionError("key outside the tenant prefix")
        self.objects[(tenant_id, key)] = (content, content_type)

    def delete(self, tenant_id: UUID, brand_id: UUID, key: str) -> None:
        if not key.startswith(payments_prefix(tenant_id, brand_id)):
            raise PermissionError("not this brand's QR")
        self.objects.pop((tenant_id, key), None)
        self.deleted.append(key)


class PostgresPaymentMethodRepository:
    """`tenant_session(tenant_id)` per call (`qualify_app`, RLS)."""

    def list(self, *, tenant_id: UUID, brand_id: UUID) -> list[PaymentMethod]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.scalars(select(T).where(T.brand_id == brand_id)).all()
            return [_from_row(r) for r in rows]

    def get(self, *, tenant_id: UUID, method_id: UUID) -> PaymentMethod | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.get(T, method_id)
            return _from_row(row) if row is not None else None

    def _write(self, method: PaymentMethod, *, new: bool) -> tuple[PaymentMethod, str | None]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

        values = {
            "name": method.name,
            "name_key": method.name_key,
            "currency": method.currency,
            "instructions": method.instructions,
            "qr_media_key": method.qr_media_key,
            "pay_on_delivery": method.pay_on_delivery,
            "position": method.position,
            "external_code": method.external_code,
            "source": method.source,
            "updated_by": method.updated_by,
            "updated_at": method.updated_at,
        }
        refusal: PaymentMethodError | None = None
        previous: str | None = None
        try:
            with tenant_session(method.tenant_id) as session:
                if new:
                    row = T(
                        id=method.id,
                        tenant_id=method.tenant_id,
                        brand_id=method.brand_id,
                        active=method.active,
                        created_by=method.created_by,
                        created_at=method.created_at,
                        **values,
                    )
                    session.add(row)
                else:
                    row = session.get(T, method.id, with_for_update=True)
                    if row is None:
                        raise PaymentMethodNotFound(str(method.id))
                    previous = row.qr_media_key
                    for column, value in values.items():
                        setattr(row, column, value)
                    # Against the CURRENT `active` (locked row), not the one read earlier.
                    if row.active and not (
                        row.pay_on_delivery or (row.instructions or "").strip() or row.qr_media_key
                    ):
                        raise PaymentMethodIncomplete()
                session.flush()
                stored = _from_row(row)
        except IntegrityError as exc:
            refusal = _refusal(exc)  # raised below: outside `except`, no context kept
        if refusal is not None:
            raise refusal
        return stored, previous

    def activate(
        self, method: PaymentMethod, *, max_active: int, by: UUID | None, at: datetime
    ) -> PaymentMethod:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import func, select  # noqa: PLC0415
        from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

        try:
            with tenant_session(method.tenant_id) as session:
                _lock_brand_payments(session, method.brand_id)
                row = session.get(T, method.id, with_for_update=True)
                if row is None:
                    raise PaymentMethodNotFound(str(method.id))
                # The offer rule on the LOCKED row, not on the service's earlier read:
                # another tab may have emptied it meanwhile.
                _check_offerable(_from_row(row))
                active = session.scalar(
                    select(func.count())
                    .select_from(T)
                    .where(T.brand_id == method.brand_id, T.active.is_(True), T.id != method.id)
                )
                if int(active or 0) >= max_active:
                    raise PaymentTooManyActive()
                row.active, row.updated_by, row.updated_at = True, by, at
                session.flush()
                return _from_row(row)
        except IntegrityError as exc:
            refusal = _refusal(exc)
        raise refusal  # outside `except`: the IntegrityError (and its row) is not kept

    def deactivate(self, method: PaymentMethod, *, by: UUID | None, at: datetime) -> PaymentMethod:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

        with tenant_session(method.tenant_id) as session:
            row = session.get(T, method.id, with_for_update=True)
            if row is None:
                raise PaymentMethodNotFound(str(method.id))
            row.active, row.updated_by, row.updated_at = False, by, at
            session.flush()
            return _from_row(row)

    def insert(self, method: PaymentMethod) -> PaymentMethod:
        return self._write(method, new=True)[0]

    def save(self, method: PaymentMethod) -> PaymentMethod:
        return self._write(method, new=False)[0]

    def save_qr(self, method: PaymentMethod) -> tuple[PaymentMethod, str | None]:
        return self._write(method, new=False)

    def set_positions(
        self, *, tenant_id: UUID, brand_id: UUID, positions: dict[UUID, int], by: UUID | None
    ) -> None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import update  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

        now = _utcnow()
        with tenant_session(tenant_id) as session:  # one transaction for the whole order
            for method_id, position in positions.items():
                session.execute(
                    update(T)
                    .where(T.id == method_id, T.brand_id == brand_id)
                    .values(position=position, updated_by=by, updated_at=now)
                )

    def delete(self, *, tenant_id: UUID, method_id: UUID) -> None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import delete  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandPaymentMethod as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            session.execute(delete(T).where(T.id == method_id))


def _check_offerable(method: PaymentMethod) -> None:
    """What a method needs to be offered, on the row as stored: something to send (or
    paid on delivery) and no `[…]` placeholder left."""
    if not method.can_be_offered:
        raise PaymentMethodIncomplete()
    clean_instructions(method.instructions)


def _lock_brand_payments(session: Any, brand_id: UUID) -> None:
    """Serialize the activations of one business for the transaction's life — the
    catalog's pattern (`catalog.service._lock_brand_order`): a transaction-scoped
    advisory lock, no UPDATE grant on `brands` needed."""
    from sqlalchemy import func, select  # noqa: PLC0415

    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"payment-methods:{brand_id}", 0)))
    )


def _refusal(exc: Exception) -> PaymentMethodError:
    """An `IntegrityError` as the owner's refusal, keeping NOTHING of its text: the name
    clash by its constraint name, everything else (a CHECK, a foreign key) as the fixed
    `PaymentMethodRejected`. Never logged with the row."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None) or ""
    if constraint == "uq_brand_payment_methods_key" or (
        not constraint and "uq_brand_payment_methods_key" in str(orig)
    ):
        return PaymentNameTaken()
    logger.warning(
        "whatsapp.payments.integrity_refused sqlstate=%s constraint=%s",
        getattr(orig, "sqlstate", None),
        constraint or "?",
    )
    return PaymentMethodRejected()


class GateQrStore:
    """R2 through `ObjectGate` (tenant prefix re-checked; deletion by exact key only)."""

    def __init__(self, gate: Any = None) -> None:
        self._gate = gate

    def _object_gate(self) -> Any:
        if self._gate is None:
            from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
            from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
            from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

            self._gate = ObjectGate(R2ObjectStore(R2Settings.from_env()))
        return self._gate

    def put(self, tenant_id: UUID, key: str, content: bytes, content_type: str) -> None:
        self._object_gate().put_media(tenant_id, key, io.BytesIO(content), content_type)

    def delete(self, tenant_id: UUID, brand_id: UUID, key: str) -> None:
        self._object_gate().delete_payment_qr(tenant_id, brand_id, key)


def production_payment_method_service() -> PaymentMethodService:
    return PaymentMethodService(PostgresPaymentMethodRepository(), GateQrStore())


__all__ = [
    "MAX_ACTIVE",
    "MAX_INSTRUCTIONS_CHARS",
    "MAX_NAME_CHARS",
    "GateQrStore",
    "MemoryPaymentMethodRepository",
    "MemoryQrStore",
    "PaymentCurrencyInvalid",
    "PaymentImageRefused",
    "PaymentInstructionsTooLong",
    "PaymentMethod",
    "PaymentMethodError",
    "PaymentMethodIncomplete",
    "PaymentMethodNotFound",
    "PaymentMethodService",
    "PaymentNameRequired",
    "PaymentNameTaken",
    "PaymentNameTooLong",
    "PaymentMethodRejected",
    "PaymentOrderMismatch",
    "PaymentPlaceholderLeft",
    "PaymentTooManyActive",
    "QrChange",
    "PostgresPaymentMethodRepository",
    "active_payment_methods",
    "as_option",
    "current_qr_key",
    "load_payment_options_for_phone",
    "name_key",
    "payments_prefix",
    "production_payment_method_service",
    "qr_thumb_url",
]
