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
import time
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
    deactivate_product,
    list_products,
    remove_media,
    reorder_media,
    update_product,
)
from .catalog_vm import (
    ProductVM,
    create_with_product_href,
    currency_from_choice,
    opens_new_product_form,
    parse_price_input,
    return_path_from_query,
    return_with_product_href,
)
from .creative_provider import acting_user_id, default_brand_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Primero completa tu marca (logo y colores) y vuelve a subir tus productos."
_DB_ERROR = "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."
_NAME_REQUIRED = "El producto necesita un nombre."
_UPLOAD_UNREADABLE = "No se pudo leer uno de los archivos. Intenta con otro."
_PRODUCT_GONE = "Ese producto ya no está en tu catálogo. Actualiza la página."
_SAVED = "Cambios guardados."
_ORDER_SAVED = "Orden guardado: la primera foto es la principal."
_DELETED = "Producto eliminado."
#: How long a confirmation stays in the corner.
_TOAST_MS = 4000

#: Where a dropped file waits between the foreground upload handler and the background
#: ingest: under the upload dir, per tenant, never served to anyone (nothing links it).
_STAGING = "catalog_staging"
#: A parked file older than this was orphaned (a closed tab, a crashed ingest): the next
#: `load_catalog` deletes it.
_STAGING_TTL_S = 6 * 60 * 60


class CatalogState(rx.State):
    """State for /catalog: the list, the "Agregar producto" form, and one product's
    editor (fields + media) at a time."""

    products: list[ProductVM] = []
    loading: bool = False
    error: str = ""
    _brand_id: str = ""

    # -- the "Agregar producto" form ------------------------------------------------------
    form_open: bool = False
    new_name: str = ""
    new_description: str = ""
    new_category: str = ""
    #: m-24803289 — the price came back as an OPTIONAL field. Empty means the product
    #: has no price, and its pieces then print none instead of an invented one.
    new_price: str = ""
    new_currency: str = ""
    form_error: str = ""
    saving: bool = False
    #: Photos and videos dropped in the form before the product exists (§ request
    #: 2026-10-19: «no me deja poner la imagen de una vez»): their names, shown as chips;
    #: parked in staging and ingested as soon as the product is created.
    new_files: list[str] = []
    #: The same files as the form shows them (request 2026-10-22: a thumbnail, not a
    #: name): `{"name", "key", "kind"}` — `key` is the staged file under the upload dir,
    #: so `rx.get_upload_url` previews it; `kind` is image / video / file (HEIC and the
    #: like, which a browser cannot draw before the ingest converts them).
    new_previews: list[dict[str, str]] = []
    _new_pending: list[list[str]] = []

    # -- the selected product's editor -------------------------------------------------
    selected_id: str = ""
    edit_name: str = ""
    edit_description: str = ""
    edit_category: str = ""
    edit_price: str = ""
    edit_currency: str = ""
    edit_error: str = ""
    edit_saving: bool = False
    #: «Eliminar producto» (request 2026-10-22): the dialog is open while this names it.
    delete_product_name: str = ""

    # -- media uploads ----------------------------------------------------------------
    uploading: bool = False
    upload_done: int = 0
    upload_total: int = 0
    upload_current: str = ""
    upload_error: str = ""
    #: (staging path, original filename, product id) of the files waiting for the
    #: ingest — each carries its own product, so a file never lands on whichever product
    #: is selected when its turn comes.
    _pending: list[list[str]] = []
    media_busy: bool = False
    #: The tile lifted by `assets/rank-drag.js` (`media_pick`), until `media_drop`.
    media_dragging: str = ""
    #: The order a drop (or «Hacer principal») asked for, waiting for `sync_media_order`.
    _media_order: list[str] = []

    # -- «Listo» after «Crear producto» (m-24842972, N3) ------------------------------
    #: The product just created: the page says «Listo» with the next step (make a
    #: publication with it) until the owner moves on. "" when there is nothing to say.
    created_id: str = ""

    # -- «Volver a tu publicación» (m-24842973, N4) -------------------------------------
    #: The app route the owner came from to add a product (`?volver=`, made safe by
    #: `catalog_vm.safe_return_path`); "" when they came from the menu.
    return_to: str = ""

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def selected(self) -> ProductVM | None:
        return next((p for p in self.products if p.product_id == self.selected_id), None)

    @rx.var
    def created(self) -> ProductVM | None:
        """The product «Listo» talks about, as the list holds it now — so its photos
        count as soon as the ingest stores them."""
        if not self.created_id:
            return None
        return next((p for p in self.products if p.product_id == self.created_id), None)

    @rx.var
    def created_href(self) -> str:
        """«Crear publicación» after creating: `/create?producto=<id>` — or, when the
        owner came from a publication, back there with the product (N4)."""
        return self._with_product_href(self.created_id)

    @rx.var
    def selected_create_href(self) -> str:
        """The editor's «Crear publicación con este producto»: `/create?producto=<id>` —
        or back to the publication the owner came from, with this product (N4)."""
        return self._with_product_href(self.selected_id)

    @rx.var
    def returning(self) -> bool:
        """The owner came here from a publication to add a product (`?volver=`)."""
        return self.return_to != ""

    def _with_product_href(self, product_id: str) -> str:
        if not product_id:
            return ""
        if self.return_to:
            back = return_with_product_href(self.return_to, product_id)
            if back:
                return back
        return create_with_product_href(product_id)

    @rx.var
    def has_products(self) -> bool:
        return len(self.products) > 0

    @rx.var
    def needs_brand(self) -> bool:
        """The load stopped because the business has no brand yet: the page shows the way
        to it («Completar mi marca») under the error."""
        return self.error == _NO_BRAND

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
            self._read_return_query()
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.loading = False
            return
        tenant_id, brand_id, _ = ids
        await asyncio.to_thread(_sweep_staging, tenant_id)
        try:
            products = await asyncio.to_thread(list_products, tenant_id, brand_id)
        except SQLAlchemyError as exc:
            logger.error("catalog load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = _DB_ERROR
            return
        async with self:
            self.products = list(products)
            self.loading = False
            self.created_id = ""
            if self.selected_id and self.selected is None:
                self.selected_id = ""

    def _read_return_query(self) -> None:
        """«Agregar producto» from Crear or Variaciones (m-24842973, N4) lands here as
        `/catalog?nuevo=1&volver=<ruta>`: the form opens and «Listo» offers «Volver a
        tu publicación». Only one of the app's own routes is kept as the way back
        (`safe_return_path`); a visit from the menu (no `?volver=`) forgets it."""
        try:
            params = self.router.url.query_parameters
        except AttributeError:  # no router outside a request (tests, background start)
            params = {}
        self.return_to = return_path_from_query(params)
        if opens_new_product_form(params) and not self.form_open:
            self.form_open = True
            self.form_error = ""
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
        self.created_id = ""

    @rx.event
    def dismiss_created(self) -> None:
        """«Listo»'s «Seguir en Tus productos»: the notice goes, the list stays."""
        self.created_id = ""

    @rx.event
    def close_form(self) -> None:
        self.form_open = False
        self.form_error = ""
        self._drop_new_files()

    def _drop_new_files(self) -> None:
        for path_str, _ in self._new_pending:
            try:
                Path(path_str).unlink(missing_ok=True)
            except OSError:
                pass
        self._new_pending = []
        self.new_files = []
        self.new_previews = []

    def _sync_new_files(self) -> None:
        self.new_files = [name for _, name in self._new_pending]
        self.new_previews = [_preview_row(path, name) for path, name in self._new_pending]

    @rx.event
    async def handle_new_media(self, files: list[rx.UploadFile]) -> None:
        """The form's own drop zone: the files wait (FOREGROUND, parked like the
        editor's) until «Crear producto», then go through the same ingest."""
        parked = await self._park(files)
        if parked:
            self._new_pending = [*self._new_pending, *parked]
            self._sync_new_files()

    @rx.event
    def remove_new_file(self, index: int) -> None:
        index = int(index)
        if not 0 <= index < len(self._new_pending):
            return
        path_str, _ = self._new_pending[index]
        try:
            Path(path_str).unlink(missing_ok=True)
        except OSError:
            pass
        self._new_pending = [p for i, p in enumerate(self._new_pending) if i != index]
        self._sync_new_files()

    @rx.event
    def set_new_name(self, value: str) -> None:
        self.new_name = value

    @rx.event
    def set_new_description(self, value: str) -> None:
        self.new_description = value

    @rx.event
    def set_new_category(self, value: str) -> None:
        self.new_category = value

    @rx.event
    def set_new_price(self, value: str) -> None:
        self.new_price = value
        self.form_error = ""

    @rx.event
    def set_new_currency(self, value: str) -> None:
        self.new_currency = currency_from_choice(value)

    @rx.event(background=True)
    async def submit_new_product(self) -> AsyncIterator[rx.event.EventSpec]:
        """Create the product; the files dropped in the form follow it straight away
        (`ingest_pending`, with its progress in the editor that opens)."""
        async with self:
            if self.saving:
                return
            if not self.new_name.strip():
                self.form_error = _NAME_REQUIRED
                return
            try:
                price = parse_price_input(self.new_price)
            except ValueError as exc:
                self.form_error = str(exc)
                return
            self.saving = True
            self.form_error = ""
            form = (self.new_name, self.new_description, self.new_category)
            currency = self.new_currency
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.saving = False
            return
        tenant_id, brand_id, user_id = ids
        name, description, category = form
        try:
            product_id = await asyncio.to_thread(
                lambda: create_product(
                    tenant_id,
                    brand_id,
                    user_id,
                    name=name,
                    description=description,
                    category=category,
                    price_amount=price,
                    price_currency=currency,
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
            self.new_description = ""
            self.new_category = ""
            self.new_price = ""
            self.new_currency = ""
            files = self._new_pending
            self.new_previews = []
            # The editor does NOT open on the new product (request 2026-10-22): only its
            # card shows, and a tap on the card opens the editor. The files dropped in
            # the form still follow it — their progress shows at page level.
            self.selected_id = ""
            # N3 (m-24842972): «Listo» stays on the page with the next step — make a
            # publication with it — instead of a toast that vanishes.
            self.created_id = str(product_id)
            self._new_pending = []
            self.new_files = []
            if files:
                self._pending = [
                    *self._pending,
                    *([path, name, str(product_id)] for path, name in files),
                ]
                self.upload_done = 0
                self.upload_total = len(self._pending)
                self.upload_error = ""
        if files:
            yield CatalogState.ingest_pending

    # -- the editor -----------------------------------------------------------------------

    def _fill_editor(self, product: ProductVM) -> None:
        self.edit_name = product.name
        self.edit_description = product.description
        self.edit_category = product.category
        self.edit_price = product.price_amount
        self.edit_currency = product.price_currency

    @rx.event
    def select_product(self, product_id: str) -> None:
        """Open one product's editor (fields + media). Selecting the open one closes it."""
        self.edit_error = ""
        self.upload_error = ""
        self.created_id = ""
        if self.selected_id == product_id:
            self.selected_id = ""
            return
        self.selected_id = product_id
        product = self.selected
        if product is not None:
            self._fill_editor(product)

    @rx.event
    def ask_delete_product(self) -> None:
        product = self.selected
        if product is not None:
            self.delete_product_name = product.name

    @rx.event
    def set_delete_product_open(self, value: bool) -> None:
        if not value:
            self.delete_product_name = ""

    @rx.event(background=True)
    async def confirm_delete_product(self) -> AsyncIterator[rx.event.EventSpec]:
        """The open product leaves the catalog; the editor closes on its card's absence."""
        async with self:
            self.delete_product_name = ""
            if self.media_busy or self.edit_saving or not self.selected_id:
                return
            self.edit_saving = True
            product_id = UUID(self.selected_id)
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.edit_saving = False
            return
        tenant_id, brand_id, _ = ids
        try:
            await asyncio.to_thread(deactivate_product, tenant_id, product_id)
        except KeyError:
            async with self:
                self.edit_saving = False
                self.edit_error = _PRODUCT_GONE
            return
        except SQLAlchemyError as exc:
            logger.error("product delete failed: %s", type(exc).__name__)
            async with self:
                self.edit_saving = False
                self.edit_error = _DB_ERROR
            return
        async with self:
            self.selected_id = ""
            self.edit_error = ""
        await self._refresh(tenant_id, brand_id)
        async with self:
            self.edit_saving = False
        yield rx.toast.success(_DELETED, duration=_TOAST_MS)

    @rx.event
    def close_editor(self) -> None:
        self.selected_id = ""
        self.edit_error = ""
        self.upload_error = ""

    @rx.event
    def set_edit_name(self, value: str) -> None:
        self.edit_name = value

    @rx.event
    def set_edit_description(self, value: str) -> None:
        self.edit_description = value

    @rx.event
    def set_edit_category(self, value: str) -> None:
        self.edit_category = value

    @rx.event
    def set_edit_price(self, value: str) -> None:
        self.edit_price = value
        self.edit_error = ""

    @rx.event
    def set_edit_currency(self, value: str) -> None:
        self.edit_currency = currency_from_choice(value)

    @rx.event(background=True)
    async def save_product(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.edit_saving or not self.selected_id:
                return
            if not self.edit_name.strip():
                self.edit_error = _NAME_REQUIRED
                return
            try:
                price = parse_price_input(self.edit_price)
            except ValueError as exc:
                self.edit_error = str(exc)
                return
            self.edit_saving = True
            self.edit_error = ""
            product_id = UUID(self.selected_id)
            form = (self.edit_name, self.edit_description, self.edit_category)
            currency = self.edit_currency
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.edit_saving = False
            return
        tenant_id, brand_id, _ = ids
        name, description, category = form
        try:
            await asyncio.to_thread(
                lambda: update_product(
                    tenant_id,
                    product_id,
                    name=name,
                    description=description,
                    category=category,
                    price_amount=price,
                    price_currency=currency,
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
            # Saving closes the editor (request 2026-10-22): the card is what is left,
            # with the saved name and price on it.
            self.edit_saving = False
            self.edit_error = ""
            self.selected_id = ""
        yield rx.toast.success(_SAVED, duration=_TOAST_MS)

    # -- media --------------------------------------------------------------------------

    @rx.event
    async def handle_media_upload(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Park the dropped files (FOREGROUND, see the module docstring) and chain the
        background ingest that normalizes and stores them one at a time."""
        if not files or not self.selected_id:
            return None
        parked = await self._park(files)
        if not parked:
            return None
        self._pending = [
            *self._pending,
            *([path, name, self.selected_id] for path, name in parked),
        ]
        self.upload_total = len(self._pending) + self.upload_done
        if self.uploading:
            return None  # the running ingest picks the new files up
        self.upload_done = 0
        self.upload_total = len(self._pending)
        self.upload_error = ""
        return CatalogState.ingest_pending

    async def _park(self, files: list[rx.UploadFile]) -> list[list[str]]:
        """Write the dropped files to the tenant's staging folder: [path, name] each."""
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            self.upload_error = _NO_SESSION
            return []
        staging = _staging_dir(tenant_id)
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
        return parked

    @rx.event(background=True)
    async def ingest_pending(self) -> AsyncIterator[None]:
        """Normalize + store every parked file through the service, reporting progress
        per file; errors are collected (a bad clip does not stop the photos)."""
        async with self:
            if self.uploading or not self._pending:
                return
            self.uploading = True
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
                path_str, name, product_str = self._pending[0]
                self._pending = self._pending[1:]
                self.upload_current = name
            yield
            path = Path(path_str)
            try:
                product_id = UUID(product_str)
                data = await asyncio.to_thread(path.read_bytes)
                await asyncio.to_thread(
                    lambda: add_media(tenant_id, product_id, data=data, filename=name)
                )
            except CatalogError as exc:
                failures.append(f"{name}: {exc.args[0] if exc.args else 'no se pudo procesar'}")
            except (KeyError, ValueError):
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

    # -- the order of the media: the first photo is the primary (request 2026-10-22) ----

    @rx.event
    def media_pick(self, media_id: str) -> None:
        """A tile was lifted (`assets/rank-drag.js` fires `dragstart` on it); `media_drop`
        on the tile it is released over does the move."""
        self.media_dragging = media_id

    @rx.event
    def media_drop(self, target_id: str) -> rx.event.EventSpec | None:
        source, self.media_dragging = self.media_dragging, ""
        if not source or source == target_id:
            return None
        return self._place(source, target_id)

    @rx.event
    def make_primary(self, media_id: str) -> rx.event.EventSpec | None:
        """«Hacer principal» = put it first: the order IS the choice."""
        return self._place(media_id, None)

    def _place(self, media_id: str, before: str | None) -> rx.event.EventSpec | None:
        """`media_id` takes `before`'s slot as the grid showed it (the front when None):
        the same remove-then-insert `rank-drag.js` animates, so the screen never snaps
        back. The new order waits in `_media_order` for `sync_media_order`."""
        product = self.selected
        if product is None:
            return None
        ids = [m.media_id for m in product.media]
        if media_id not in ids or (before is not None and before not in ids):
            return None
        target = ids.index(before) if before is not None else 0
        ids.remove(media_id)
        ids.insert(target, media_id)
        self._media_order = ids
        return CatalogState.sync_media_order

    @rx.event(background=True)
    async def sync_media_order(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.media_busy or not self.selected_id or not self._media_order:
                return
            self.media_busy = True
            self.upload_error = ""
            product_id = UUID(self.selected_id)
            order = list(self._media_order)
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.media_busy = False
            return
        tenant_id, brand_id, _ = ids
        failed = False
        try:
            await asyncio.to_thread(reorder_media, tenant_id, product_id, order)
        except KeyError:  # UnknownProduct: the media changed under us
            failed = True
            async with self:
                self.upload_error = _PRODUCT_GONE
        except SQLAlchemyError as exc:
            failed = True
            logger.error("media reorder failed: %s", type(exc).__name__)
            async with self:
                self.upload_error = _DB_ERROR
        await self._refresh(tenant_id, brand_id)
        async with self:
            self.media_busy = False
            self._media_order = []
        if not failed:
            yield rx.toast.success(_ORDER_SAVED, duration=_TOAST_MS)

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


_BROWSER_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_VIDEOS = {".mp4", ".mov", ".m4v", ".webm"}


def _preview_row(path_str: str, name: str) -> dict[str, str]:
    """How the form draws one staged file: its key under the upload dir (what
    `rx.get_upload_url` serves) and whether a browser can show it as a picture."""
    suffix = Path(name).suffix.lower()
    kind = "image" if suffix in _BROWSER_IMAGES else ("video" if suffix in _VIDEOS else "file")
    try:
        key = Path(path_str).resolve().relative_to(rx.get_upload_dir().resolve()).as_posix()
    except ValueError:  # parked somewhere else (tests): nothing to preview
        key = ""
        kind = "file"
    return {"name": name, "key": key, "kind": kind}


def _staging_dir(tenant_id: UUID) -> Path:
    return rx.get_upload_dir() / "uploads" / str(tenant_id) / _STAGING


def _sweep_staging(tenant_id: UUID, *, now: float | None = None) -> None:
    """Delete the tenant's parked files older than `_STAGING_TTL_S`: the ingest unlinks
    what it consumes, but a closed tab or a crash leaves the rest behind for good."""
    cutoff = (time.time() if now is None else now) - _STAGING_TTL_S
    try:
        entries = list(_staging_dir(tenant_id).iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
        except OSError:
            pass
