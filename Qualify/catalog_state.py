"""Reflex state for /catalog — the product catalog (plan-mvp-plantillas-remotion.md §2.1
#1, Fase 1 "Mié 7": the founder uploads the real products of Bianki and Polette).

Custody rules inherited from `creative_state.py`:

- Holds only `catalog_vm` dataclasses (plain strings/ints), never `ProductRecord`s.
- The active tenant comes from `AuthState.session_tenant_id`, parsed through
  `tenant.tenant_uuid` right before it reaches the provider; the brand is the tenant's
  one brand (`creative_provider.default_brand_id`).
- Every provider call blocks (SQLAlchemy, Pillow, ffmpeg), so background handlers run
  them with `asyncio.to_thread`.
- Uploads arrive in a FOREGROUND handler (Reflex forbids `background=True` on a handler
  that receives `list[rx.UploadFile]`). It only parks the bytes in a staging folder of
  the upload dir and chains `ingest_pending`, the background handler that normalizes
  and stores them one by one — so a 6-photo drop shows "Procesando 2 de 6" instead of
  freezing the screen while ffmpeg works.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .catalog_provider import (
    CatalogError,
    add_media,
    create_product,
    list_products,
    remove_media,
    set_primary,
    tenant_currency,
    update_product,
)
from .catalog_vm import DEFAULT_CURRENCY, ProductVM, currency_choices, parse_price
from .creative_provider import acting_user_id, default_brand_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Este negocio no tiene ninguna marca provisionada todavía."
_DB_ERROR = "No se pudo hablar con la base de datos. Inténtalo de nuevo en un momento."
_NAME_REQUIRED = "El producto necesita un nombre."
_UPLOAD_UNREADABLE = "No se pudo leer uno de los archivos. Intenta con otro."
_PRODUCT_GONE = "Ese producto ya no existe o no es visible para este negocio."
_CREATED = "Producto creado. Ahora súbele sus fotos."
_SAVED = "Cambios guardados."

#: Where a dropped file waits between the foreground upload handler and the background
#: ingest: under the upload dir, per tenant, never served to anyone (nothing links it).
_STAGING = "catalog_staging"


class CatalogState(rx.State):
    """State for /catalog: the list, the "Nuevo producto" form, and one product's
    editor (fields + media) at a time."""

    products: list[ProductVM] = []
    loading: bool = False
    error: str = ""
    notice: str = ""
    currencies: list[str] = list(currency_choices(DEFAULT_CURRENCY))
    _brand_id: str = ""

    # -- the "Nuevo producto" form ------------------------------------------------------
    form_open: bool = False
    new_name: str = ""
    new_price: str = ""
    new_currency: str = DEFAULT_CURRENCY
    new_description: str = ""
    new_category: str = ""
    form_error: str = ""
    saving: bool = False

    # -- the selected product's editor -------------------------------------------------
    selected_id: str = ""
    edit_name: str = ""
    edit_price: str = ""
    edit_currency: str = DEFAULT_CURRENCY
    edit_description: str = ""
    edit_category: str = ""
    edit_error: str = ""
    edit_saving: bool = False

    # -- media uploads ----------------------------------------------------------------
    uploading: bool = False
    upload_done: int = 0
    upload_total: int = 0
    upload_current: str = ""
    upload_error: str = ""
    #: (staging path, original filename) of files parked by `handle_media_upload`.
    _pending: list[list[str]] = []
    media_busy: bool = False

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def selected(self) -> ProductVM | None:
        return next((p for p in self.products if p.product_id == self.selected_id), None)

    @rx.var
    def has_products(self) -> bool:
        return len(self.products) > 0

    @rx.var
    def product_count_label(self) -> str:
        n = len(self.products)
        return "1 producto" if n == 1 else f"{n} productos"

    @rx.var
    def upload_progress(self) -> int:
        if not self.upload_total:
            return 0
        return min(100, round(100 * self.upload_done / self.upload_total))

    @rx.var
    def upload_label(self) -> str:
        if not self.upload_total:
            return "Procesando…"
        return f"Procesando {min(self.upload_done + 1, self.upload_total)} de {self.upload_total}"

    # -- session --------------------------------------------------------------------------

    async def _session_ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        """(tenant, brand, acting user) or None with the reason already in `error`."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            cached_brand_id = self._brand_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            async with self:
                self.error = _NO_SESSION
            return None
        brand_id: UUID | None
        if cached_brand_id:
            brand_id = UUID(cached_brand_id)
        else:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
            if brand_id is not None:
                async with self:
                    self._brand_id = str(brand_id)
        if brand_id is None:
            async with self:
                self.error = _NO_BRAND
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        return tenant_id, brand_id, user_id

    # -- load -----------------------------------------------------------------------------

    @rx.event(background=True)
    async def load_catalog(self) -> None:
        async with self:
            self.loading = True
            self.error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.loading = False
            return
        tenant_id, brand_id, _ = ids
        try:
            products = await asyncio.to_thread(list_products, tenant_id, brand_id)
            currency = await asyncio.to_thread(tenant_currency, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("catalog load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = _DB_ERROR
            return
        async with self:
            self.products = list(products)
            self.currencies = currency_choices(currency)
            if self.new_currency not in self.currencies:
                self.new_currency = self.currencies[0]
            self.loading = False
            if self.selected_id and self.selected is None:
                self.selected_id = ""

    async def _refresh(self, tenant_id: UUID, brand_id: UUID) -> None:
        """Re-read the list after a write (the service is the source of truth for
        slugs, positions and the primary photo — never patched client-side)."""
        try:
            products = await asyncio.to_thread(list_products, tenant_id, brand_id)
        except SQLAlchemyError as exc:
            logger.error("catalog refresh failed: %s", type(exc).__name__)
            async with self:
                self.error = _DB_ERROR
            return
        async with self:
            self.products = list(products)
            if self.selected_id and self.selected is not None:
                self._fill_editor(self.selected)

    # -- the new-product form ---------------------------------------------------------------

    @rx.event
    def open_form(self) -> None:
        self.form_open = True
        self.form_error = ""
        self.notice = ""

    @rx.event
    def close_form(self) -> None:
        self.form_open = False
        self.form_error = ""

    @rx.event
    def set_new_name(self, value: str) -> None:
        self.new_name = value

    @rx.event
    def set_new_price(self, value: str) -> None:
        self.new_price = value

    @rx.event
    def set_new_currency(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value:
            self.new_currency = value

    @rx.event
    def set_new_description(self, value: str) -> None:
        self.new_description = value

    @rx.event
    def set_new_category(self, value: str) -> None:
        self.new_category = value

    @rx.event(background=True)
    async def submit_new_product(self) -> None:
        async with self:
            if self.saving:
                return
            if not self.new_name.strip():
                self.form_error = _NAME_REQUIRED
                return
            try:
                price = parse_price(self.new_price)
            except ValueError as exc:
                self.form_error = str(exc)
                return
            self.saving = True
            self.form_error = ""
            form = (
                self.new_name,
                price,
                self.new_currency,
                self.new_description,
                self.new_category,
            )
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.saving = False
            return
        tenant_id, brand_id, user_id = ids
        name, price, currency, description, category = form
        try:
            product_id = await asyncio.to_thread(
                lambda: create_product(
                    tenant_id,
                    brand_id,
                    user_id,
                    name=name,
                    price_amount=price,
                    currency=currency,
                    description=description,
                    category=category,
                )
            )
        except CatalogError as exc:
            async with self:
                self.saving = False
                self.form_error = str(exc.args[0]) if exc.args else _NAME_REQUIRED
            return
        except SQLAlchemyError as exc:
            logger.error("product create failed: %s", type(exc).__name__)
            async with self:
                self.saving = False
                self.form_error = _DB_ERROR
            return
        await self._refresh(tenant_id, brand_id)
        async with self:
            self.saving = False
            self.form_open = False
            self.new_name = ""
            self.new_price = ""
            self.new_description = ""
            self.new_category = ""
            self.notice = _CREATED
            self.selected_id = str(product_id)
            if self.selected is not None:
                self._fill_editor(self.selected)

    # -- the editor -----------------------------------------------------------------------

    def _fill_editor(self, product: ProductVM) -> None:
        self.edit_name = product.name
        self.edit_price = product.price_text
        self.edit_currency = product.currency or (
            self.currencies[0] if self.currencies else DEFAULT_CURRENCY
        )
        self.edit_description = product.description
        self.edit_category = product.category

    @rx.event
    def select_product(self, product_id: str) -> None:
        """Open one product's editor (fields + media). Selecting the open one closes it."""
        self.edit_error = ""
        self.upload_error = ""
        self.notice = ""
        if self.selected_id == product_id:
            self.selected_id = ""
            return
        self.selected_id = product_id
        product = self.selected
        if product is not None:
            self._fill_editor(product)

    @rx.event
    def close_editor(self) -> None:
        self.selected_id = ""
        self.edit_error = ""
        self.upload_error = ""

    @rx.event
    def set_edit_name(self, value: str) -> None:
        self.edit_name = value

    @rx.event
    def set_edit_price(self, value: str) -> None:
        self.edit_price = value

    @rx.event
    def set_edit_currency(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value:
            self.edit_currency = value

    @rx.event
    def set_edit_description(self, value: str) -> None:
        self.edit_description = value

    @rx.event
    def set_edit_category(self, value: str) -> None:
        self.edit_category = value

    @rx.event(background=True)
    async def save_product(self) -> None:
        async with self:
            if self.edit_saving or not self.selected_id:
                return
            if not self.edit_name.strip():
                self.edit_error = _NAME_REQUIRED
                return
            try:
                price = parse_price(self.edit_price)
            except ValueError as exc:
                self.edit_error = str(exc)
                return
            self.edit_saving = True
            self.edit_error = ""
            product_id = UUID(self.selected_id)
            form = (
                self.edit_name,
                price,
                self.edit_currency,
                self.edit_description,
                self.edit_category,
            )
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.edit_saving = False
            return
        tenant_id, brand_id, _ = ids
        name, price, currency, description, category = form
        try:
            await asyncio.to_thread(
                lambda: update_product(
                    tenant_id,
                    product_id,
                    name=name,
                    price_amount=price,
                    currency=currency,
                    description=description,
                    category=category,
                )
            )
        except CatalogError as exc:
            async with self:
                self.edit_saving = False
                self.edit_error = str(exc.args[0]) if exc.args else _NAME_REQUIRED
            return
        except KeyError:  # UnknownProduct: the row vanished under us
            async with self:
                self.edit_saving = False
                self.edit_error = _PRODUCT_GONE
            return
        except SQLAlchemyError as exc:
            logger.error("product update failed: %s", type(exc).__name__)
            async with self:
                self.edit_saving = False
                self.edit_error = _DB_ERROR
            return
        await self._refresh(tenant_id, brand_id)
        async with self:
            self.edit_saving = False
            self.notice = _SAVED

    # -- media --------------------------------------------------------------------------

    @rx.event
    async def handle_media_upload(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Park the dropped files (FOREGROUND, see the module docstring) and chain the
        background ingest that normalizes and stores them one at a time."""
        if not files or not self.selected_id:
            return None
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            self.upload_error = _NO_SESSION
            return None
        staging = rx.get_upload_dir() / "uploads" / str(tenant_id) / _STAGING
        staging.mkdir(parents=True, exist_ok=True)
        parked: list[list[str]] = []
        for upload in files:
            try:
                data = await upload.read()
            except Exception:
                self.upload_error = _UPLOAD_UNREADABLE
                continue
            name = upload.name or "archivo"
            path = staging / f"{uuid4().hex}_{Path(name).name}"
            path.write_bytes(data)
            parked.append([str(path), name])
        if not parked:
            return None
        self._pending = [*self._pending, *parked]
        self.upload_total = len(self._pending) + self.upload_done
        if self.uploading:
            return None  # the running ingest picks the new files up
        self.upload_done = 0
        self.upload_total = len(self._pending)
        self.upload_error = ""
        return CatalogState.ingest_pending

    @rx.event(background=True)
    async def ingest_pending(self) -> AsyncIterator[None]:
        """Normalize + store every parked file through the service, reporting progress
        per file; errors are collected (a bad clip does not stop the photos)."""
        async with self:
            if self.uploading or not self._pending or not self.selected_id:
                return
            self.uploading = True
            product_id = UUID(self.selected_id)
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.uploading = False
                self._pending = []
            return
        tenant_id, brand_id, _ = ids
        failures: list[str] = []
        while True:
            async with self:
                if not self._pending:
                    break
                path_str, name = self._pending[0]
                self._pending = self._pending[1:]
                self.upload_current = name
            yield
            path = Path(path_str)
            try:
                data = await asyncio.to_thread(path.read_bytes)
                await asyncio.to_thread(
                    lambda: add_media(tenant_id, product_id, data=data, filename=name)
                )
            except CatalogError as exc:
                failures.append(f"{name}: {exc.args[0] if exc.args else 'no se pudo procesar'}")
            except KeyError:
                failures.append(f"{name}: {_PRODUCT_GONE}")
            except SQLAlchemyError as exc:
                logger.error("media add failed: %s", type(exc).__name__)
                failures.append(f"{name}: {_DB_ERROR}")
            except OSError:
                failures.append(f"{name}: {_UPLOAD_UNREADABLE}")
            finally:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            async with self:
                self.upload_done += 1
            yield
        await self._refresh(tenant_id, brand_id)
        async with self:
            self.uploading = False
            self.upload_current = ""
            self.upload_done = 0
            self.upload_total = 0
            self.upload_error = " · ".join(failures)

    @rx.event(background=True)
    async def make_primary(self, media_id: str) -> None:
        await self._media_action(media_id, set_primary)

    @rx.event(background=True)
    async def delete_media(self, media_id: str) -> None:
        await self._media_action(media_id, remove_media)

    async def _media_action(self, media_id: str, action: object) -> None:
        async with self:
            if self.media_busy or not self.selected_id:
                return
            self.media_busy = True
            self.upload_error = ""
            product_id = UUID(self.selected_id)
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.media_busy = False
            return
        tenant_id, brand_id, _ = ids
        try:
            await asyncio.to_thread(action, tenant_id, product_id, UUID(media_id))  # type: ignore[arg-type]
        except KeyError:
            async with self:
                self.upload_error = _PRODUCT_GONE
        except SQLAlchemyError as exc:
            logger.error("media action failed: %s", type(exc).__name__)
            async with self:
                self.upload_error = _DB_ERROR
        await self._refresh(tenant_id, brand_id)
        async with self:
            self.media_busy = False
