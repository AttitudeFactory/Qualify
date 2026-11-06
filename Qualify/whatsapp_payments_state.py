"""Reflex state for «Formas de pago» (WhatsApp → Tu número, m-24955648, first PR).

The owner manages the business's payment methods: the list (order, «La ofreces»,
«Borrar») and a four-step flow to add or edit one (name, currency and when the customer
pays → instructions → QR, optional → «Así le llega a tu cliente»). Spec:
`docs/ux-paso-de-pago.md` §1–§2.

Discipline (the order writer's, `catalog_order_state`):

- Every write goes through `whatsapp_payments_provider` → `PaymentMethodService`, off the
  event loop, one at a time (`busy`).
- A list change is optimistic and a failure — the session lookup included — puts the
  screen back as it was, with the service's Spanish `message` (or a plain «No pudimos
  guardar…» for anything else).
- The QR follows the chat photo: checked here (type, 15 MB), parked in a private temp
  file (never in the state), only a small preview in the browser; the service checks
  and normalises it again.
- The business behind the number is read from the number (`brand_for_number`); a number
  without one shows `NO_BRAND`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .tenant import tenant_uuid
from .ui.steps import settle_step
from .whatsapp_chats_state import PhotoTooLarge, discard_photo, stage_photo
from .whatsapp_chats_vm import MAX_PHOTO_BYTES
from .whatsapp_payments_provider import (
    PaymentMethodError,
    PaymentMethodNotFound,
    PaymentNameTaken,
    PaymentTooManyActive,
    acting_user_id,
    brand_for_number,
    business_currency,
    create_method,
    delete_method,
    instruction_gaps,
    list_methods,
    remove_qr,
    reorder_methods,
    set_active,
    set_qr,
    update_method,
)
from .whatsapp_payments_vm import (
    CURRENCY_CODES,
    INCOMPLETE,
    MAX_INSTRUCTIONS,
    MAX_NAME,
    PARTLY_SAVED,
    QR_TOO_LARGE,
    QR_UNREADABLE,
    QR_WRONG_TYPE,
    SAVE_FAILED,
    SAVED_NOT_OFFERED,
    SAVED_THE_REST,
    SHORTCUTS,
    STEPS,
    UNDO_LABEL,
    UNDONE,
    PaymentRowVM,
    can_offer,
    counter,
    delete_title,
    instructions_problem,
    moved,
    moved_text,
    name_problem,
    payment_rows,
    preview_lines,
    saved_text,
)
from .whatsapp_state import WhatsAppState

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_UNDO_MS = 6000
_QR_TYPES = frozenset({"image/jpeg", "image/png"})
_EXAMPLES = frozenset(example for *_rest, example in SHORTCUTS if example)


def _message(exc: BaseException) -> str:
    """The service's own sentence, else the plain failure."""
    if isinstance(exc, PaymentMethodError):
        return str(getattr(exc, "message", "") or exc.args[0] or SAVE_FAILED)
    if isinstance(exc, PaymentMethodNotFound):
        return "Esa forma de pago ya no está. Te mostramos las que sí están."
    return SAVE_FAILED


def _read(path: str) -> bytes:
    return Path(path).read_bytes()


class WhatsAppPaymentsState(rx.State):
    """The list, its writes and the add/edit flow."""

    loaded_for: str = ""
    loading: bool = False
    error: str = ""
    no_brand: bool = False
    busy: bool = False
    #: The method «La ofreces» refused for having nothing to send: its [Editar].
    incomplete_id: str = ""
    announce: str = ""
    #: The row lifted from the keyboard (`sort_handle`), and the order before.
    lifted: str = ""
    delete_id: str = ""

    _methods: list[dict[str, Any]] = []
    _lift_before: list[dict[str, Any]] = []
    _dragging: str = ""
    _undo_ids: list[str] = []
    _brand_id: str = ""
    _business_currency: str = ""

    # -- the flow -------------------------------------------------------------------------
    flow_open: bool = False
    step: int = 1
    editing_id: str = ""
    f_shortcut: str = ""
    f_name: str = ""
    f_currency: str = "USD"
    f_on_delivery: bool = False
    f_instructions: str = ""
    f_active: bool = True
    f_error: str = ""
    f_qr_preview: str = ""
    f_qr_name: str = ""
    f_qr_error: str = ""
    f_existing_qr: str = ""  # the saved QR's thumbnail (editing)
    f_had_qr: bool = False
    f_remove_qr: bool = False
    saving: bool = False
    _f_qr_path: str = ""
    _f_qr_type: str = ""
    _f_was_active: bool = False

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def rows(self) -> list[PaymentRowVM]:
        return payment_rows(self._methods)

    @rx.var
    def has_methods(self) -> bool:
        return len(self._methods) > 0

    @rx.var
    def delete_open(self) -> bool:
        return any(m["method_id"] == self.delete_id for m in self._methods)

    @rx.var
    def delete_title_text(self) -> str:
        name = next((m["name"] for m in self._methods if m["method_id"] == self.delete_id), "")
        return delete_title(name)

    @rx.var
    def name_count(self) -> str:
        return counter(self.f_name, MAX_NAME)

    @rx.var
    def instructions_count(self) -> str:
        return counter(self.f_instructions, MAX_INSTRUCTIONS)

    @rx.var
    def preview_text(self) -> list[str]:
        return preview_lines(
            instructions=self.f_instructions,
            currency=self.f_currency,
            business_currency=self._business_currency,
            pay_on_delivery=self.f_on_delivery,
        )

    @rx.var
    def preview_qr(self) -> str:
        if self.f_qr_preview:
            return self.f_qr_preview
        return "" if self.f_remove_qr else self.f_existing_qr

    @rx.var
    def has_qr_now(self) -> bool:
        return bool(self.f_qr_preview) or (self.f_had_qr and not self.f_remove_qr)

    @rx.var
    def editing(self) -> bool:
        return self.editing_id != ""

    # -- session --------------------------------------------------------------------------

    async def _session_ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        """(tenant, brand, acting user) or None with the reason in `error`."""
        async with self:
            auth = await self.get_state(AuthState)
            wa = await self.get_state(WhatsAppState)
            session_tenant_id = auth.session_tenant_id
            connection_id = wa.selected_connection_id
            cached = self._brand_id if self.loaded_for == connection_id else ""
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None or not connection_id:
            async with self:
                self.error = _NO_SESSION
            return None
        if cached:
            brand_id: UUID | None = UUID(cached)
        else:
            brand_id = await asyncio.to_thread(brand_for_number, tenant_id, UUID(connection_id))
        if brand_id is None:
            async with self:
                self.no_brand = True
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        return tenant_id, brand_id, user_id

    async def _ids_or_fail(self) -> tuple[UUID, UUID, UUID | None] | None:
        try:
            return await self._session_ids()
        except Exception as exc:  # noqa: BLE001 — the database down: say so, never stay busy
            logger.warning("whatsapp payments session failed: %s", type(exc).__name__)
            async with self:
                self.error = SAVE_FAILED
            return None

    # -- load -----------------------------------------------------------------------------

    @rx.event(background=True)
    async def ensure_loaded(self) -> None:
        """The panel mounted (or the number changed): read the list once per number."""
        async with self:
            wa = await self.get_state(WhatsAppState)
            connection_id = wa.selected_connection_id
            if not connection_id or (self.loaded_for == connection_id and not self.error):
                return
            self.loading = True
            self.error = ""
            self.no_brand = False
            self._brand_id = ""
            self.loaded_for = ""
        await self._load(connection_id)

    async def _load(self, connection_id: str) -> None:
        ids = await self._ids_or_fail()
        if ids is None:
            async with self:
                self.loading = False
                self._methods = []
            return
        tenant_id, brand_id, _ = ids
        try:
            methods = await asyncio.to_thread(list_methods, tenant_id, brand_id)
            currency = await asyncio.to_thread(business_currency, tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("whatsapp payments load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = SAVE_FAILED
            return
        async with self:
            self._methods = methods
            self._brand_id = str(brand_id)
            self._business_currency = (currency or "").upper()
            self.loaded_for = connection_id
            self.loading = False

    @rx.event(background=True)
    async def reload(self) -> None:
        async with self:
            connection_id = self.loaded_for
        if connection_id:
            await self._load(connection_id)

    # -- the order ------------------------------------------------------------------------

    def _index(self, method_id: str) -> int | None:
        return next((i for i, m in enumerate(self._methods) if m["method_id"] == method_id), None)

    @rx.event
    def place(self, method_id: str, to: int) -> rx.event.EventSpec | None:
        """«Primero / Subir uno / Bajar uno / Último» and a drop."""
        index = self._index(method_id)
        if self.busy or index is None:
            return None
        to = max(0, min(len(self._methods) - 1, int(to)))
        if to == index:
            return None
        before = [dict(m) for m in self._methods]
        self._methods = moved(self._methods, index, to)
        return self._queue_order(method_id, before)

    def _queue_order(
        self, method_id: str, before: list[dict[str, Any]]
    ) -> rx.event.EventSpec | None:
        self.lifted = ""
        self._lift_before = before
        index = self._index(method_id) or 0
        self.announce = moved_text(self._methods[index]["name"], index + 1, len(self._methods))
        self.error = ""
        self.busy = True
        return WhatsAppPaymentsState.store_order

    @rx.event
    def pick(self, method_id: str) -> None:
        self._dragging = method_id

    @rx.event
    def drop(self, target_id: str) -> rx.event.EventSpec | None:
        source, self._dragging = self._dragging, ""
        to = self._index(target_id)
        if not source or to is None or source == target_id:
            return None
        return self.place(source, to)

    @rx.event
    def handle_key(self, method_id: str, key: str) -> rx.event.EventSpec | None:
        """`sort_handle`: Espacio lifts and drops (one write), ↑/↓ move on screen while
        lifted, Escape puts it back."""
        index = self._index(method_id)
        if self.busy or index is None:
            return None
        name = self._methods[index]["name"]
        total = len(self._methods)
        if key in (" ", "Spacebar", "Enter"):
            if self.lifted != method_id:
                self.lifted = method_id
                self._lift_before = [dict(m) for m in self._methods]
                self.announce = (
                    f"Levantaste «{name}», posición {index + 1} de {total}. Muévela con las "
                    "flechas y suéltala con Espacio. Escape la deja donde estaba."
                )
                return None
            before_ids = [m["method_id"] for m in self._lift_before]
            if before_ids == [m["method_id"] for m in self._methods]:
                self.lifted = ""
                self.announce = f"«{name}» se quedó en su lugar."
                return None
            return self._queue_order(method_id, [dict(m) for m in self._lift_before])
        if self.lifted != method_id:
            return None
        if key == "Escape":
            self._methods = [dict(m) for m in self._lift_before]
            self.lifted = ""
            self.announce = f"Listo, no cambiamos nada: «{name}» volvió a su lugar."
            return None
        step = {"ArrowUp": -1, "ArrowDown": 1}.get(key)
        if step is None or not 0 <= index + step < total:
            return None
        self._methods = moved(self._methods, index, index + step)
        self.announce = f"{name}, posición {index + step + 1} de {total}"
        return None

    @rx.event(background=True)
    async def store_order(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            ids_now = [m["method_id"] for m in self._methods]
            before = [dict(m) for m in self._lift_before]
            toast = self.announce
        ids = await self._ids_or_fail()
        failure: BaseException | None = None
        if ids is not None:
            tenant_id, brand_id, user_id = ids
            try:
                await asyncio.to_thread(reorder_methods, tenant_id, brand_id, user_id, ids_now)
            except Exception as exc:  # noqa: BLE001 — any failure rolls the screen back
                failure = exc
        if ids is None or failure is not None:
            async with self:
                self._methods = before
                self.busy = False
                self._undo_ids = []
                if failure is not None:
                    logger.warning("whatsapp payments reorder: %s", type(failure).__name__)
                    self.error = _message(failure)
                self.announce = self.error
            return
        async with self:
            self.busy = False
            self._undo_ids = [m["method_id"] for m in before]
        yield rx.toast.success(
            toast,
            duration=_UNDO_MS,
            action={"label": UNDO_LABEL, "on_click": WhatsAppPaymentsState.undo_order},
        )

    @rx.event
    def undo_order(self) -> rx.event.EventSpec | None:
        wanted, self._undo_ids = self._undo_ids, []
        if self.busy or not wanted:
            return None
        by_id = {m["method_id"]: m for m in self._methods}
        if set(wanted) != set(by_id):
            return None
        self._lift_before = [dict(m) for m in self._methods]
        self._methods = [by_id[i] for i in wanted]
        self.announce = UNDONE
        self.busy = True
        return WhatsAppPaymentsState.store_undo

    @rx.event(background=True)
    async def store_undo(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._store_order_plain():
            yield event

    async def _store_order_plain(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            ids_now = [m["method_id"] for m in self._methods]
            before = [dict(m) for m in self._lift_before]
        ids = await self._ids_or_fail()
        failure: BaseException | None = None
        if ids is not None:
            try:
                await asyncio.to_thread(reorder_methods, *ids, ids_now)
            except Exception as exc:  # noqa: BLE001
                failure = exc
        async with self:
            self.busy = False
            if ids is None or failure is not None:
                self._methods = before
                if failure is not None:
                    self.error = _message(failure)
                return
        yield rx.toast.success(UNDONE, duration=_UNDO_MS)

    # -- «La ofreces» --------------------------------------------------------------------

    @rx.event
    def toggle_active(self, method_id: str, value: bool) -> rx.event.EventSpec | None:
        index = self._index(method_id)
        if self.busy or index is None:
            return None
        method = self._methods[index]
        if value and not can_offer(
            pay_on_delivery=bool(method.get("pay_on_delivery")),
            instructions=method.get("instructions", ""),
            has_qr=bool(method.get("has_qr")),
        ):
            self.incomplete_id = method_id
            self.error = INCOMPLETE
            return None
        self.incomplete_id = ""
        self.error = ""
        self._lift_before = [dict(m) for m in self._methods]
        rows = [dict(m) for m in self._methods]
        rows[index]["active"] = bool(value)
        self._methods = rows
        self.busy = True
        return WhatsAppPaymentsState.store_active(method_id, bool(value))

    @rx.event(background=True)
    async def store_active(self, method_id: str, value: bool) -> None:
        async with self:
            before = [dict(m) for m in self._lift_before]
        ids = await self._ids_or_fail()
        failure: BaseException | None = None
        if ids is not None:
            try:
                await asyncio.to_thread(set_active, *ids, method_id, value)
            except Exception as exc:  # noqa: BLE001
                failure = exc
        async with self:
            self.busy = False
            if ids is None or failure is not None:
                self._methods = before
                if failure is not None:
                    logger.warning("whatsapp payments active: %s", type(failure).__name__)
                    self.error = _message(failure)
                    if self.error == INCOMPLETE:
                        self.incomplete_id = method_id

    # -- «Borrar» -------------------------------------------------------------------------

    @rx.event
    def ask_delete(self, method_id: str) -> None:
        if not self.busy:
            self.delete_id = method_id

    @rx.event
    def set_delete_open(self, value: bool) -> None:
        if not value:
            self.delete_id = ""

    @rx.event
    def confirm_delete(self) -> rx.event.EventSpec | None:
        method_id, self.delete_id = self.delete_id, ""
        if self.busy or self._index(method_id) is None:
            return None
        self._lift_before = [dict(m) for m in self._methods]
        self._methods = [m for m in self._methods if m["method_id"] != method_id]
        self.busy = True
        return WhatsAppPaymentsState.store_delete(method_id)

    @rx.event(background=True)
    async def store_delete(self, method_id: str) -> None:
        async with self:
            before = [dict(m) for m in self._lift_before]
        ids = await self._ids_or_fail()
        failure: BaseException | None = None
        if ids is not None:
            tenant_id, brand_id, _ = ids
            try:
                await asyncio.to_thread(delete_method, tenant_id, brand_id, method_id)
            except Exception as exc:  # noqa: BLE001
                failure = exc
        async with self:
            self.busy = False
            if ids is None or failure is not None:
                self._methods = before
                if failure is not None:
                    self.error = _message(failure)

    def _discard_files(self) -> None:
        """A logout or a business switch (`AuthState._reset_business_states`, right
        before `reset`): the QR parked for the form is a file, not a field — delete it."""
        discard_photo(self._f_qr_path)
        self._f_qr_path = ""

    # -- the add / edit flow --------------------------------------------------------------

    def _reset_form(self) -> None:
        discard_photo(self._f_qr_path)
        self._f_qr_path = self._f_qr_type = ""
        self.f_qr_preview = self.f_qr_name = self.f_qr_error = ""
        self.f_existing_qr = ""
        self.f_had_qr = self.f_remove_qr = False
        self.f_error = ""
        self.f_shortcut = ""

    def _default_currency(self) -> str:
        return self._business_currency if self._business_currency in CURRENCY_CODES else "USD"

    @rx.event
    def open_new(self) -> rx.event.EventSpec | None:
        if self.no_brand:
            return None
        self._reset_form()
        self.editing_id = ""
        self.f_name = ""
        self.f_currency = self._default_currency()
        self.f_on_delivery = False
        self.f_instructions = ""
        self.f_active = True
        self._f_was_active = False
        self.step = 1
        self.flow_open = True
        return None

    @rx.event
    def open_edit(self, method_id: str) -> None:
        """Editing opens on the last step, with «Cambiar» on each block (§2)."""
        index = self._index(method_id)
        if index is None:
            return
        m = self._methods[index]
        self._reset_form()
        self.editing_id = method_id
        self.f_name = m["name"]
        self.f_currency = m.get("currency") or self._default_currency()
        self.f_on_delivery = bool(m.get("pay_on_delivery"))
        self.f_instructions = m.get("instructions", "")
        self.f_active = bool(m.get("active"))
        self._f_was_active = self.f_active
        self.f_had_qr = bool(m.get("has_qr"))
        self.f_existing_qr = m.get("thumb_url", "")
        self.incomplete_id = ""
        self.step = STEPS
        self.flow_open = True

    @rx.event
    def set_flow_open(self, value: bool) -> None:
        if not value:
            self.close_flow()

    @rx.event
    def close_flow(self) -> None:
        self.flow_open = False
        self._reset_form()

    @rx.event
    def pick_shortcut(self, key: str) -> None:
        shortcut = next((s for s in SHORTCUTS if s[0] == key), None)
        if shortcut is None:
            return
        _key, name, currency, on_delivery, example = shortcut
        self.f_shortcut = key
        self.f_name = "" if key == "otra" else name
        self.f_currency = currency or self._default_currency()
        self.f_on_delivery = on_delivery
        if not self.f_instructions.strip() or self.f_instructions in _EXAMPLES:
            self.f_instructions = example
        self.f_error = ""

    @rx.event
    def set_f_name(self, value: str) -> None:
        self.f_name = value
        self.f_error = ""

    @rx.event
    def set_f_currency(self, value: str) -> None:
        if value in CURRENCY_CODES:
            self.f_currency = value

    @rx.event
    def set_f_on_delivery(self, value: str) -> None:
        self.f_on_delivery = value == "entrega"

    @rx.event
    def set_f_instructions(self, value: str) -> None:
        self.f_instructions = value
        self.f_error = ""

    @rx.event
    def set_f_active(self, value: bool) -> None:
        self.f_active = bool(value)
        self.f_error = ""

    def _step_problem(self, step: int) -> str:
        if step == 1:
            return name_problem(self.f_name)
        if step == 2:
            return instructions_problem(self.f_instructions, instruction_gaps(self.f_instructions))
        return ""

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        problem = self._step_problem(self.step)
        if problem:
            self.f_error = problem
            return None
        self.f_error = ""
        self.step = min(STEPS, self.step + 1)
        return settle_step("drawer")

    @rx.event
    def back_step(self) -> rx.event.EventSpec | None:
        self.f_error = ""
        self.step = max(1, self.step - 1)
        return settle_step("drawer")

    @rx.event
    def go_step(self, step: int) -> rx.event.EventSpec | None:
        """«Cambiar» on a block of the last step."""
        if 1 <= step <= STEPS:
            self.step = step
            self.f_error = ""
            return settle_step("drawer")
        return None

    @rx.event
    async def handle_qr(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """The QR photo: checked here (JPG/PNG, 15 MB) and again by the service; it waits
        in a private temp file, the browser gets a small preview."""
        if not self.flow_open or not files:
            return None
        upload = files[0]
        content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
        declared = getattr(upload, "size", None)
        if content_type not in _QR_TYPES:
            self.f_qr_error = QR_WRONG_TYPE
            return None
        if isinstance(declared, int) and declared > MAX_PHOTO_BYTES:
            self.f_qr_error = QR_TOO_LARGE
            return None
        try:
            data = await upload.read(MAX_PHOTO_BYTES + 1)
        except Exception:  # noqa: BLE001 — the browser's stream
            self.f_qr_error = QR_UNREADABLE
            return None
        if not data:
            self.f_qr_error = QR_UNREADABLE
            return None
        if len(data) > MAX_PHOTO_BYTES:
            self.f_qr_error = QR_TOO_LARGE
            return None
        try:
            path, preview = await asyncio.to_thread(stage_photo, data)
        except PhotoTooLarge:
            self.f_qr_error = QR_TOO_LARGE
            return None
        except Exception as exc:  # noqa: BLE001 — a corrupt file
            logger.warning("whatsapp payments qr preview failed: %s", type(exc).__name__)
            self.f_qr_error = QR_UNREADABLE
            return None
        discard_photo(self._f_qr_path)
        self._f_qr_path = path
        self._f_qr_type = content_type
        self.f_qr_preview = preview
        self.f_qr_name = (getattr(upload, "name", "") or "qr").split("/")[-1][:120]
        self.f_qr_error = ""
        self.f_remove_qr = False
        return None

    @rx.event
    def qr_rejected(self, _files: Any = None) -> None:
        self.f_qr_error = QR_WRONG_TYPE

    @rx.event
    def drop_qr(self) -> None:
        """«Quitar el QR»: the new one goes; a saved one is removed on «Guardar»."""
        discard_photo(self._f_qr_path)
        self._f_qr_path = self._f_qr_type = ""
        self.f_qr_preview = self.f_qr_name = ""
        self.f_remove_qr = self.f_had_qr

    @rx.event
    def skip_qr(self) -> rx.event.EventSpec:
        """«Sin QR»: on to the preview (a saved QR stays unless «Quitar el QR»)."""
        self.step = STEPS
        return settle_step("drawer")

    @rx.event(background=True)
    async def save_flow(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Guardar». New: create → QR → offer; any refusal after the create deletes it
        again, so the list never shows half a method. Editing: the changes in order, and
        on a refusal the list is read again (what the database has)."""
        async with self:
            if self.saving or not self.flow_open:
                return
            for step in (1, 2):
                problem = self._step_problem(step)
                if problem:
                    self.f_error = problem
                    self.step = step
                    return
            if self.f_active and not can_offer(
                pay_on_delivery=self.f_on_delivery,
                instructions=self.f_instructions,
                has_qr=self.has_qr_now,
            ):
                self.f_error = INCOMPLETE
                return
            self.saving = True
            self.f_error = ""
            form = {
                "name": " ".join(self.f_name.split()),
                "currency": self.f_currency,
                "instructions": self.f_instructions.strip(),
                "pay_on_delivery": self.f_on_delivery,
            }
            editing = self.editing_id
            active, was_active = self.f_active, self._f_was_active
            qr_path, qr_type, qr_name = self._f_qr_path, self._f_qr_type, self.f_qr_name
            drop_saved_qr = self.f_remove_qr and not qr_path
        ids = await self._ids_or_fail()
        if ids is None:
            async with self:
                self.saving = False
                self.f_error = self.error or SAVE_FAILED
            return
        tenant_id, brand_id, _user = ids
        created = ""
        wrote = False  # editing: something is already stored
        offered_full = False  # new: saved, but 10 are already offered
        try:
            if editing:
                method_id = editing
                if was_active and not active:
                    await asyncio.to_thread(set_active, *ids, editing, False)
                    wrote = True
                # Order matters (the service checks every state in between): a new QR
                # first, then the fields, then a QR removal — so «clear the text and
                # upload a QR» and «remove the QR and write the text» both pass.
                if qr_path:
                    content = await asyncio.to_thread(_read, qr_path)
                    await asyncio.to_thread(
                        set_qr,
                        *ids,
                        method_id,
                        content=content,
                        content_type=qr_type,
                        filename=qr_name,
                    )
                    wrote = True
                await asyncio.to_thread(update_method, *ids, editing, **form)
                wrote = True
                if drop_saved_qr:
                    await asyncio.to_thread(remove_qr, *ids, method_id)
                if active and not was_active:
                    await asyncio.to_thread(set_active, *ids, method_id, True)
            else:
                method_id = await asyncio.to_thread(create_method, *ids, **form)
                created = method_id
                if qr_path:
                    content = await asyncio.to_thread(_read, qr_path)
                    await asyncio.to_thread(
                        set_qr,
                        *ids,
                        method_id,
                        content=content,
                        content_type=qr_type,
                        filename=qr_name,
                    )
                if active:
                    try:
                        await asyncio.to_thread(set_active, *ids, method_id, True)
                    except PaymentTooManyActive:
                        offered_full = True  # keep it: saved, not offered
        except Exception as exc:  # noqa: BLE001 — say why, keep everything typed
            logger.warning("whatsapp payments save: %s", type(exc).__name__)
            if created:
                try:
                    await asyncio.to_thread(delete_method, tenant_id, brand_id, created)
                except Exception as undo_exc:  # noqa: BLE001
                    logger.error("whatsapp payments rollback: %s", type(undo_exc).__name__)
            async with self:
                self.saving = False
                if isinstance(exc, PaymentNameTaken):
                    self.step = 1  # the name lives on step 1: the message goes there
                    self.f_error = _message(exc)
                elif wrote and isinstance(exc, PaymentTooManyActive):
                    # Turned on with 10 already offered: the rest of the edit is stored;
                    # it stays off, so «Guardar» does not fail the same way again.
                    self.f_active = False
                    self.f_error = f"{_message(exc)} {SAVED_THE_REST}"
                elif wrote and isinstance(exc, PaymentMethodError):
                    self.f_error = f"{_message(exc)} {PARTLY_SAVED}"  # the reason, too
                elif wrote:
                    self.f_error = PARTLY_SAVED
                else:
                    self.f_error = _message(exc)
            if editing and wrote:
                yield WhatsAppPaymentsState.reload
            return
        async with self:
            self.saving = False
            self.flow_open = False
            self._reset_form()
            name = form["name"]
        yield WhatsAppPaymentsState.reload
        if offered_full:
            yield rx.toast.info(SAVED_NOT_OFFERED, duration=_UNDO_MS)
        else:
            yield rx.toast.success(saved_text(name, active), duration=_UNDO_MS)
