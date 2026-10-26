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
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .catalog_provider import (
    CatalogError,
    add_media,
    business_currency,
    create_product,
    deactivate_product,
    list_products,
    remove_media,
    reorder_media,
    update_product,
)
from .catalog_vm import (
    NEW_PRODUCT_STEP_TITLES,
    NEW_PRODUCT_STEPS,
    PRODUCT_QUERY,
    RETURN_PARAM,
    STEP_DONE,
    STEP_NAME,
    STEP_PHOTO,
    ProductMediaVM,
    ProductVM,
    business_default_currency,
    create_with_product_href,
    currency_from_choice,
    editor_is_dirty,
    leave_description,
    missing_photo_filter_label,
    opens_new_product_form,
    parse_price_input,
    product_count_label,
    products_to_show,
    rejection_message,
    remove_media_description,
    remove_media_title,
    return_path_from_query,
    return_with_product_href,
    step_counter,
    steps_done,
)
from .creative_provider import acting_user_id, default_brand_id
from .nav_url import close_flow_script, flow_param
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Primero completa tu marca (logo y colores) y vuelve a subir tus productos."
_DB_ERROR = "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."
_NAME_REQUIRED = "El producto necesita un nombre."
_UPLOAD_UNREADABLE = "No se pudo leer uno de los archivos. Intenta con otro."
_PRODUCT_GONE = "Ese producto ya no está en tus productos. Vuelve a la lista."
_LINK_GONE = "Ese producto ya no está en tus productos. Aquí tienes los que sí están."
_SAVED = "Cambios guardados."
_ORDER_SAVED = "Orden guardado: la primera foto es la principal."
_DELETED = "Producto eliminado."
#: How long a confirmation stays in the corner.
_TOAST_MS = 4000
#: The list's own address: where closing an editor opened from a link goes (N5).
_CATALOG_PATH = "/catalog"
#: Closing an editor the owner opened from the list steps back in the browser's history
#: instead of adding a new entry: the list comes back where it was (React Router's
#: scroll restoration answers a «back», never a fresh visit) and «atrás» stays honest.
_HISTORY_BACK = "window.history.back()"

#: Where a dropped file waits between the foreground upload handler and the background
#: ingest: under the upload dir, per tenant, never served to anyone (nothing links it).
_STAGING = "catalog_staging"
#: A parked file older than this was orphaned (a closed tab, a crashed ingest): the next
#: `load_catalog` deletes it. A day, not hours: closing «Agregar producto» halfway keeps
#: the photos already chosen (N6), so a reload must not sweep them from under the form.
_STAGING_TTL_S = 24 * 60 * 60


class CatalogState(rx.State):
    """State for /catalog: the list, the "Agregar producto" form, and one product's
    editor (fields + media) at a time."""

    products: list[ProductVM] = []
    loading: bool = False
    error: str = ""
    _brand_id: str = ""

    # -- the "Agregar producto" form ------------------------------------------------------
    form_open: bool = False
    flow_ready: bool = False
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
    #: m-24842974 — «Agregar producto» is three steps in a drawer: the photo
    #: (`STEP_PHOTO`), the name and price (`STEP_NAME`), and «Listo» (`STEP_DONE`).
    #: Going back never clears what was typed: the fields live here, not in the step.
    new_step: int = STEP_PHOTO
    #: «Más detalles» (category and description) unfolded in the name step.
    new_details_open: bool = False
    #: A file the photo step refused, in the owner's words (formats only appear here).
    new_media_error: str = ""
    #: The product the «Listo» step talks about.
    created_product_id: str = ""
    created_name: str = ""
    created_has_media: bool = False
    #: The business's own currency (`tenants.currency`): what a new product starts with.
    _business_currency: str = ""

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
    #: m-24842976 — «¿Salir sin guardar?»: open while the owner decides what happens to
    #: the changes; `_leave_target` is where they were going ("" = back to the list, a
    #: product id = that product's editor).
    leave_open: bool = False
    _leave_target: str = ""
    #: The editor was opened from the list in this tab (a history entry of the bare list
    #: sits behind it), so closing it can step back instead of navigating forward.
    _opened_in_app: bool = False

    # -- «Volver a tu publicación» (m-24842973, N4) -------------------------------------
    #: The app route the owner came from to add a product (`?volver=`, made safe by
    #: `catalog_vm.safe_return_path`); "" when they came from the menu.
    return_to: str = ""

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
    #: m-24842977 — «Quitar» asks first: the photo or clip waiting for «Sí, quitar»
    #: ("" = no dialog open).
    remove_media_id: str = ""
    #: m-24842977 — the list narrowed to the products with no photo yet.
    only_missing_photo: bool = False

    # -- derived ------------------------------------------------------------------------

    @rx.var
    def selected(self) -> ProductVM | None:
        return next((p for p in self.products if p.product_id == self.selected_id), None)

    @rx.var
    def editor_open(self) -> bool:
        return self.selected is not None

    @rx.var
    def edit_dirty(self) -> bool:
        """The editor holds a change the product does not have yet (m-24842976)."""
        return editor_is_dirty(
            self.selected,
            name=self.edit_name,
            description=self.edit_description,
            category=self.edit_category,
            price=self.edit_price,
            currency=self.edit_currency,
        )

    @rx.var
    def edit_title(self) -> str:
        """The editor drawer's title: the product's stored name, so it does not change
        under the owner's fingers while they retype it."""
        product = self.selected
        return product.name if product is not None else "Editar producto"

    @rx.var
    def leave_text(self) -> str:
        product = self.selected
        return leave_description(product.name if product is not None else self.edit_name)

    @rx.var
    def has_products(self) -> bool:
        return len(self.products) > 0

    @rx.var
    def needs_brand(self) -> bool:
        """The load stopped because the business has no brand yet: the page shows the way
        to it («Completar mi marca») under the error."""
        return self.error == _NO_BRAND

    @rx.var
    def missing_photo_count(self) -> int:
        return sum(1 for p in self.products if p.photo_count == 0)

    @rx.var
    def product_count_label(self) -> str:
        """«3 productos · 1 sin foto» (m-24842977)."""
        return product_count_label(len(self.products), self.missing_photo_count)

    @rx.var
    def missing_filter_on(self) -> bool:
        """The filter only narrows while some product still lacks a photo: once the last
        one gets it, the whole list comes back on its own."""
        return self.only_missing_photo and self.missing_photo_count > 0

    @rx.var
    def visible_products(self) -> list[ProductVM]:
        return products_to_show(self.products, only_missing_photo=self.missing_filter_on)

    @rx.var
    def missing_filter_label(self) -> str:
        return missing_photo_filter_label(self.missing_photo_count, active=self.missing_filter_on)

    @rx.var
    def show_missing_filter(self) -> bool:
        """While it is on, or while some products lack a photo and others have one
        (narrowing everything to everything would mean nothing)."""
        n = self.missing_photo_count
        return self.missing_filter_on or 0 < n < len(self.products)

    @rx.var
    def remove_media_open(self) -> bool:
        return _media_in(self.selected, self.remove_media_id) is not None

    @rx.var
    def remove_media_title_text(self) -> str:
        item = _media_in(self.selected, self.remove_media_id)
        return remove_media_title(item.media_type if item is not None else "image")

    @rx.var
    def remove_media_text(self) -> str:
        item = _media_in(self.selected, self.remove_media_id)
        if item is None:
            return remove_media_description("image", is_primary=False)
        has_other_photo = self.selected is not None and any(
            m.media_type == "image" and m.media_id != item.media_id for m in self.selected.media
        )
        return remove_media_description(
            item.media_type, is_primary=item.is_primary, has_other_photo=has_other_photo
        )

    @rx.var
    def new_step_counter(self) -> str:
        return step_counter(self.new_step)

    @rx.var
    def new_step_title(self) -> str:
        return NEW_PRODUCT_STEP_TITLES[min(max(self.new_step, 0), len(NEW_PRODUCT_STEPS) - 1)]

    @rx.var
    def new_steps_done(self) -> list[bool]:
        return steps_done(self.new_step)

    @rx.var
    def created_href(self) -> str:
        """Where «Crear publicación» goes: Crear with this product already chosen — or,
        when the owner came from a publication, back there with it (m-24842973, N4)."""
        return self._with_product_href(self.created_product_id)

    @rx.var
    def selected_create_href(self) -> str:
        """The editor's «Crear publicación con este producto» (m-24842972):
        `/create?producto=<id>` — or back to the publication the owner came from, with
        this product (m-24842973, N4)."""
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
    def created_ready(self) -> bool:
        """«Crear publicación» is live only once the new product's photos are in: saved
        with files, nothing still uploading or queued, and no upload failure."""
        return (
            self.created_has_media
            and not self.uploading
            and self.upload_total == 0
            and self.upload_error == ""
        )

    @rx.var
    def created_preparing(self) -> bool:
        """The new product's photos are still on their way: «Preparando tu foto…»."""
        return self.created_has_media and (self.uploading or self.upload_total > 0)

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
    async def load_catalog(self) -> AsyncIterator[rx.event.EventSpec]:
        """on_load — also on every change of `?producto=` (N5): a link opens that
        product's editor, the phone's «atrás» closes it. Only the very first load shows
        the skeleton: swapping a filled grid for it would collapse the page under the
        scroll position «atrás» is restoring."""
        async with self:
            self.loading = not self.products
            self.error = ""
            arrival = self._read_return_query()
            self.restore_flow()
            if self.products:
                self._sync_url(final=False)
        for event in arrival:  # the address loses `?nuevo=1`
            yield event
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.loading = False
            return
        tenant_id, brand_id, _ = ids
        await asyncio.to_thread(_sweep_staging, tenant_id)
        try:
            products = await asyncio.to_thread(list_products, tenant_id, brand_id)
            currency = await asyncio.to_thread(business_currency, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("catalog load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = _DB_ERROR
            return
        async with self:
            self.products = list(products)
            self.loading = False
            self._business_currency = business_default_currency(currency)
            if not self.form_open and not self.new_price:
                self.new_currency = self._business_currency
            if self.selected_id and self.selected is None:
                self.selected_id = ""
            follow = self._sync_url(final=True)
        for event in follow:
            yield event
        async with self:
            if flow_param(self.router.url.query_parameters, "producto", 3):
                self.restore_flow()

    def _read_return_query(self) -> list[rx.event.EventSpec]:
        """«Agregar producto» from Crear or Variaciones (m-24842973, N4) lands here as
        `/catalog?nuevo=1&volver=<ruta>`: the form opens and «Listo» offers «Volver a
        tu publicación». Only one of the app's own routes is kept as the way back
        (`safe_return_path`). Moving to a product's editor (`?producto=`, N5) keeps it;
        a visit from the menu (neither) forgets it. `?nuevo=1` comes off the address
        once the form is open, so «atrás» from an editor does not reopen it."""
        try:
            params = self.router.url.query_parameters
        except Exception:  # noqa: BLE001 — no router outside a request (tests)
            params = {}
        back = return_path_from_query(params)
        if back:
            self.return_to = back
        elif not self._url_product():
            self.return_to = ""
        if not (back and opens_new_product_form(params)):
            return []
        if not self.form_open:
            self.selected_id = ""
            self.open_form()
        query = urlencode({RETURN_PARAM: back, "flujo": "producto", "paso": str(self.new_step + 1)})
        return [rx.redirect(f"{_CATALOG_PATH}?{query}", replace=True)]

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
            # A photo change refreshes the list too: never overwrite a name or price the
            # owner is still correcting (m-24842976 UX review).
            keep = self.edit_dirty
            self.products = list(products)
            if self.selected_id and self.selected is not None and not keep:
                self._fill_editor(self.selected)

    # -- the new-product form ---------------------------------------------------------------

    @rx.event
    def restore_flow(self) -> None:
        params = self.router.url.query_parameters
        requested = flow_param(params, "producto", 3)
        if not requested:
            if not opens_new_product_form(params):
                self.form_open = False
                self.flow_ready = False
            return
        self.form_open = True
        target = requested - 1
        if target == STEP_DONE and self._find(self.created_product_id) is None:
            target = STEP_NAME
        self.new_step = target
        self.flow_ready = True

    @rx.event
    def leave_flow(self) -> None:
        self.flow_ready = False
        self.form_open = False

    @rx.event
    def open_form(self) -> None:
        self.form_open = True
        self.flow_ready = True
        self.form_error = ""
        self.new_media_error = ""
        if self.new_step == STEP_DONE:
            self._reset_new_form()
        if not self.new_price and not self.new_currency:
            self.new_currency = self._business_currency

    @rx.event
    def close_form(self) -> rx.event.EventSpec:
        self.form_open = False
        self.form_error = ""
        self.new_media_error = ""
        if self.new_step == STEP_DONE:
            self._drop_new_files()
            self._reset_new_form()
        else:
            # N6: what was typed AND the photos already chosen stay for the next time
            # the form opens (the photos are the hardest part to repeat); the step does not
            pass  # the session draft keeps both its answers and its step
        self.flow_ready = False
        return rx.call_script(close_flow_script("producto"))

    @rx.event
    def upload_photo_for_created(self) -> list[rx.event.EventSpec] | None:
        """«Subirle una foto» from «Listo»: close the drawer and open the new product's
        editor, where its photos go (on a phone the list is hidden behind the drawer)."""
        product = self._find(self.created_product_id)
        self.close_form()
        if product is None:
            return None
        return self._go_to(product)

    @rx.event
    def set_form_open(self, value: bool) -> rx.event.EventSpec | None:
        """The drawer's own close (Esc, the ×, the backdrop)."""
        if value:
            self.open_form()
        else:
            return self.close_form()
        return None

    def _reset_new_form(self) -> None:
        self.new_step = STEP_PHOTO
        self.new_details_open = False
        self.new_name = ""
        self.new_description = ""
        self.new_category = ""
        self.new_price = ""
        self.new_currency = self._business_currency
        self.form_error = ""
        self.new_media_error = ""
        self.created_product_id = ""
        self.created_name = ""
        self.created_has_media = False

    @rx.event
    def add_another_product(self) -> None:
        """«Agregar otro producto» from the «Listo» step: a clean first step."""
        self._drop_new_files()
        self._reset_new_form()
        self.form_open = True

    @rx.event
    def go_to_new_step(self, index: int) -> None:
        """The stepper: back to the photo or forward to the name — never away from
        «Listo» once the product exists, and never to «Listo» before it does."""
        index = int(index)
        if self.new_step == STEP_DONE or index not in (STEP_PHOTO, STEP_NAME):
            return
        self.new_step = index
        self.form_error = ""

    @rx.event
    def next_new_step(self) -> None:
        """«Siguiente» and «Sin foto por ahora»: the photo step is never a gate."""
        if self.new_step == STEP_PHOTO:
            self.new_step = STEP_NAME
            self.new_media_error = ""

    @rx.event
    def back_new_step(self) -> None:
        """«Atrás» (N6): back to the photo with every typed field kept."""
        if self.new_step == STEP_NAME:
            self.new_step = STEP_PHOTO
            self.form_error = ""

    @rx.event
    def toggle_new_details(self) -> None:
        self.new_details_open = not self.new_details_open

    @rx.event
    def new_media_rejected(self, rejected: list[dict[str, Any]]) -> None:
        self.new_media_error = rejection_message(rejected)

    @rx.event
    def media_rejected(self, rejected: list[dict[str, Any]]) -> None:
        self.upload_error = rejection_message(rejected)

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
        self.new_media_error = ""
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
            # m-24842974: the drawer stays open on «Listo», which says what happened and
            # offers the two next moves; the typed fields are spent.
            self.new_step = STEP_DONE
            self.created_product_id = str(product_id)
            self.created_name = name.strip()
            self.new_details_open = False
            self.new_name = ""
            self.new_description = ""
            self.new_category = ""
            self.new_price = ""
            self.new_currency = self._business_currency
            files = self._new_pending
            self.created_has_media = bool(files)
            self.new_previews = []
            # The editor does NOT open on the new product (request 2026-10-22): only its
            # card shows, and a tap on the card opens the editor. The files dropped in
            # the form still follow it — their progress shows in «Listo».
            self.selected_id = ""
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

    def _find(self, product_id: str) -> ProductVM | None:
        return next((p for p in self.products if p.product_id == product_id), None)

    def _url_product(self) -> str:
        """The product the address names (`/catalog?producto=<id>`), "" for the list."""
        try:
            return str(self.router.url.query_parameters.get(PRODUCT_QUERY, "") or "")
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            return ""

    @staticmethod
    def _product_href(product_id: str) -> str:
        return f"{_CATALOG_PATH}?{PRODUCT_QUERY}={product_id}"

    def _open(self, product: ProductVM) -> None:
        self.selected_id = product.product_id
        self.edit_error = ""
        self.upload_error = ""
        self._fill_editor(product)

    def _go_to(self, product: ProductVM) -> list[rx.event.EventSpec]:
        """Open `product`'s editor and give it its address: a new history entry when
        coming from the list (so «atrás» closes it), the same entry when the address
        already names a product."""
        self._open(product)
        href = self._product_href(product.product_id)
        if self._url_product():
            return [rx.redirect(href, replace=True)]
        self._opened_in_app = True
        return [rx.redirect(href)]

    def _close_nav(self) -> list[rx.event.EventSpec]:
        """Take `?producto=` off the address once the editor is closed."""
        if not self._url_product():
            return []  # «atrás» already did
        if self._opened_in_app:
            self._opened_in_app = False
            return [rx.call_script(_HISTORY_BACK)]
        return [rx.redirect(_CATALOG_PATH, replace=True)]

    def _restore_url(self) -> list[rx.event.EventSpec]:
        """The owner chose to stay after «atrás» had already dropped the product from
        the address: put it back, so the next «atrás» works again."""
        if self.selected_id and not self._url_product():
            self._opened_in_app = True
            return [rx.redirect(self._product_href(self.selected_id))]
        return []

    def _leave(self, target: str) -> list[rx.event.EventSpec]:
        """Close the editor (target "") or move to another product's, changes dropped."""
        self.leave_open = False
        self._leave_target = ""
        product = self._find(target) if target else None
        if product is not None:
            return self._go_to(product)
        self.selected_id = ""
        self.edit_error = ""
        self.upload_error = ""
        return self._close_nav()

    def _ask_leave(self, target: str) -> None:
        self._leave_target = target
        self.leave_open = True

    def _sync_url(self, *, final: bool) -> list[rx.event.EventSpec]:
        """Make the editor follow the address after a navigation (N5). Unsaved changes
        are never dropped by it: the owner is asked first."""
        wanted = self._url_product()
        if wanted == self.selected_id:
            return []
        if not wanted:  # the phone's «atrás», or a link to the bare list
            if self.selected_id:
                if self.edit_dirty:
                    if not self.leave_open:
                        self._ask_leave("")
                else:
                    self.selected_id = ""
                    self.edit_error = ""
                    self.upload_error = ""
                    self._opened_in_app = False
            return []
        product = self._find(wanted)
        if product is None:
            # another business's product, a deleted one, a typo: the list, with a word why
            if final and not self.selected_id:
                return [
                    rx.redirect(_CATALOG_PATH, replace=True),
                    rx.toast.info(_LINK_GONE, duration=_TOAST_MS),
                ]
            return []
        if self.selected_id and self.edit_dirty:
            if not self.leave_open:
                self._ask_leave(wanted)
            return []
        self._open(product)
        return []

    @rx.event
    def select_product(self, product_id: str) -> list[rx.event.EventSpec] | None:
        """A card's «Editar»: open that product's editor (m-24842976: never a toggle —
        tapping the open product keeps it open). With unsaved changes in another
        product, «¿Salir sin guardar?» comes first."""
        product = self._find(str(product_id))
        if product is None or product.product_id == self.selected_id:
            return None
        if self.selected_id and self.edit_dirty:
            self._ask_leave(product.product_id)
            return None
        return self._go_to(product)

    @rx.event
    def request_close(self) -> list[rx.event.EventSpec] | None:
        """«Cerrar», the drawer's ×, Esc or the backdrop."""
        if not self.selected_id or self.leave_open or self.delete_product_name:
            return None  # a dialog on top already owns the answer
        if self.edit_dirty:
            self._ask_leave("")
            return None
        return self._leave("")

    @rx.event
    def set_editor_open(self, value: bool) -> list[rx.event.EventSpec] | None:
        return None if value else self.request_close()

    @rx.event
    def stay_in_editor(self) -> list[rx.event.EventSpec]:
        """«Volver»: back to the editor, every change still there."""
        self.leave_open = False
        self._leave_target = ""
        return self._restore_url()

    @rx.event
    def set_leave_open(self, value: bool) -> list[rx.event.EventSpec] | None:
        """The dialog's own close (Esc) is «Volver»: the safe answer."""
        return None if value else self.stay_in_editor()

    @rx.event
    def discard_and_leave(self) -> list[rx.event.EventSpec]:
        """«Salir sin guardar»: the changes go, the owner goes where they were going."""
        return self._leave(self._leave_target)

    @rx.event
    def save_and_leave(self) -> rx.event.EventSpec:
        """«Guardar y salir»: the save leaves to `_leave_target` once it lands; a refused
        save keeps the editor open with its reason."""
        self.leave_open = False
        return CatalogState.save_product

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
            self.leave_open = False
            self._leave_target = ""
            follow = self._close_nav()
        await self._refresh(tenant_id, brand_id)
        async with self:
            self.edit_saving = False
        yield rx.toast.success(_DELETED, duration=_TOAST_MS)
        for event in follow:
            yield event

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
        stay: list[rx.event.EventSpec] | None = None
        async with self:
            if self.edit_saving or not self.selected_id:
                return
            price = None
            if not self.edit_name.strip():
                self.edit_error = _NAME_REQUIRED
                stay = self._stay_after_refusal()
            else:
                try:
                    price = parse_price_input(self.edit_price)
                except ValueError as exc:
                    self.edit_error = str(exc)
                    stay = self._stay_after_refusal()
            if stay is None:
                self.edit_saving = True
                self.edit_error = ""
                product_id = UUID(self.selected_id)
                form = (self.edit_name, self.edit_description, self.edit_category)
                currency = self.edit_currency
        if stay is not None:
            for event in stay:
                yield event
            return
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.edit_saving = False
                self._leave_target = ""
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
                stay = self._stay_after_refusal()
            for event in stay:
                yield event
            return
        except KeyError:  # UnknownProduct: the row vanished under us
            async with self:
                self.edit_saving = False
                self.edit_error = _PRODUCT_GONE
                stay = self._stay_after_refusal()
            for event in stay:
                yield event
            return
        except SQLAlchemyError as exc:
            logger.error("product update failed: %s", type(exc).__name__)
            async with self:
                self.edit_saving = False
                self.edit_error = _DB_ERROR
                stay = self._stay_after_refusal()
            for event in stay:
                yield event
            return
        await self._refresh(tenant_id, brand_id)
        async with self:
            # Saving closes the editor (request 2026-10-22): the card is what is left,
            # with the saved name and price on it — or, from «Guardar y salir» on the way
            # to another product, that product's editor (m-24842976).
            self.edit_saving = False
            self.edit_error = ""
            follow = self._leave(self._leave_target)
        yield rx.toast.success(_SAVED, duration=_TOAST_MS)
        for event in follow:
            yield event

    def _stay_after_refusal(self) -> list[rx.event.EventSpec]:
        """A save that did not land keeps the editor open, and forgets where
        «Guardar y salir» was going. On the phone the reason under the fields may be
        out of view, so it is said as a toast too."""
        self._leave_target = ""
        return [*self._restore_url(), rx.toast.error(self.edit_error, duration=_TOAST_MS)]

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

    @rx.event
    def toggle_missing_photo(self) -> None:
        """«Ver los 2 sin foto» / «Ver todos los productos» (m-24842977)."""
        self.only_missing_photo = not self.only_missing_photo

    @rx.event
    def ask_remove_media(self, media_id: str) -> None:
        """«Quitar» opens «¿Quitar esta foto?» first (m-24842977): nothing is removed
        until «Sí, quitar»."""
        if self.media_busy:
            return
        self.remove_media_id = media_id

    @rx.event
    def set_remove_media_open(self, value: bool) -> None:
        if not value:
            self.remove_media_id = ""

    @rx.event
    def confirm_remove_media(self) -> rx.event.EventSpec | None:
        media_id, self.remove_media_id = self.remove_media_id, ""
        if not media_id:
            return None
        return CatalogState.delete_media(media_id)

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


def _media_in(product: ProductVM | None, media_id: str) -> ProductMediaVM | None:
    """The photo or clip `media_id` of the open product, if it is still there."""
    if product is None or not media_id:
        return None
    return next((m for m in product.media if m.media_id == media_id), None)


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
