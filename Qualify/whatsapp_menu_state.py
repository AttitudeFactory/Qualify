"""Reflex state for `/whatsapp` → Menú (WA-16): the number's menus, the structured
editor, the version history, publishing, and the phone preview.

Holds only the frozen VMs/forms of `whatsapp_menu_vm.py` — never an ORM row, never a
Graph client, never a token. The number on screen is `WhatsAppState.selected_connection_id`
(the shell's), the tenant `AuthState.session_tenant_id`.

**Loading.** The tab's root `on_mount` calls `ensure_loaded`; the shell keys the tab by
the selected number, so it fires on tab entry and on every number switch. Guarded by
`loaded_for`/`loading_for` (React may mount twice in dev): a revisit of the same number
costs nothing, a different number drops everything number-scoped first.

**Editing is local and synchronous.** Every edit is a foreground handler that replaces a
frozen form item and re-runs `validate_form` (the schema, in-process, microseconds), so
the Spanish messages follow the keystrokes. Nothing is written until «Publicar en mi
WhatsApp» (saves the changes as a new version, then publishes it) or «Guardar sin
publicar». `editing_version_id` is the saved version the editor shows while it has no
changes — what «Publicar en mi WhatsApp» publishes when there is nothing to save.
Indices arrive over the wire and are range-checked; a `field` name is whitelisted.

**Everything that touches Postgres or Graph is a background event** (SQLAlchemy is
synchronous; a Graph round trip can take seconds) — same rule as `WhatsAppState`.

**The preview runs the real engine** (`engine.step`) over the brand's real catalog, on a
snapshot of the definition taken at «Reiniciar»: editing while a conversation is open
cannot pull a node out from under it; the panel says when the snapshot is stale.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import reflex as rx
from pydantic import ValidationError
from qualify_api.whatsapp.menus import MenuNotFound, MenuVersionNotFound
from qualify_api.whatsapp.menus.engine import CatalogItem, Inbound, ThreadMenuState
from qualify_api.whatsapp.menus.schema import MAX_COMMANDS, MAX_ICE_BREAKERS, MenuDefinition
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .auth_state import AuthState
from .tenant import tenant_uuid
from .whatsapp_menu_provider import (
    MenuDetail,
    NumberScope,
    create_menu,
    menu_detail,
    menus_for,
    number_scope,
    preview_catalog,
    publish_version,
    save_version,
    set_paused,
    user_id_for,
)
from .whatsapp_menu_vm import (
    EMPTY_MENU,
    KIND_BUTTONS,
    KIND_KEYS,
    KIND_LIST,
    NONE_VALUE,
    REPLY_LIST,
    TEMPLATE_EMPTY,
    TEMPLATE_FAST_FOOD,
    CommandForm,
    IceBreakerForm,
    KeywordForm,
    MenuForm,
    MenuSummaryVM,
    MenuVersionVM,
    NodeForm,
    PreviewMessageVM,
    can_publish,
    catalog_note,
    change_kind,
    definition_to_form,
    empty_form,
    issues_summary,
    new_node,
    new_option,
    order_lines,
    preview_turn,
    rename_node,
    unique_node_id,
    validate_form,
    validate_menu_name,
)
from .whatsapp_provider import UnknownWhatsAppNumber
from .whatsapp_state import WhatsAppState

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudieron cargar los menús de este número. Vuelve a intentarlo en un momento."
_SAVE_FAILED = "No se pudo guardar la versión. Vuelve a intentarlo en un momento."
_PUBLISH_FAILED = "No se pudo publicar la versión. Vuelve a intentarlo en un momento."
_PAUSE_FAILED = "No se pudo cambiar la pausa del menú. Vuelve a intentarlo en un momento."
_MENU_GONE = "Ese menú ya no está en este número. Actualizamos la lista."
_NAME_TAKEN = "Ya hay un menú con ese nombre en este número."
_SAVED = (
    "Versión {n} guardada sin publicar. Tu WhatsApp aún no responde con ella: toca "
    "«Publicar en mi WhatsApp» cuando quieras."
)
_PAUSED = "Menú en pausa: tu WhatsApp no responde con el menú hasta que lo reactives."
_RESUMED = "Menú reactivado: tu WhatsApp vuelve a responder con el menú que escribiste."
_DRAFT_EMPTY = "Menú nuevo: escribe el primer paso y publícalo en tu WhatsApp."

_ENTRY_TABLES: dict[str, frozenset[str]] = {
    "keywords": frozenset({"word", "node"}),
    "ice_breakers": frozenset({"text", "node"}),
    "commands": frozenset({"name", "hint", "node"}),
}
_NODE_FIELDS = frozenset(
    {
        "node_id",
        "body",
        "header",
        "footer",
        "next",
        "button_label",
        "more_label",
        "page_size",
        "next_after_pick",
        "empty_body",
        "confirm_next",
        "add_more_next",
        "cancel_next",
        "confirm_label",
        "add_more_label",
        "cancel_label",
        "empty_line",
        "field_name",
        "validation",
        "error_message",
        "yes_label",
        "no_label",
        "reason",
    }
)
_OPTION_FIELDS = frozenset({"option_id", "label", "description", "next", "section"})


def _catalog_rows(items: tuple[CatalogItem, ...]) -> list[dict[str, Any]]:
    """Backend-var form of the preview catalog: plain JSON, Decimals as strings."""
    return [
        {
            "product_id": i.product_id,
            "name": i.name,
            "price_amount": str(i.price_amount) if i.price_amount is not None else None,
            "price_currency": i.price_currency,
            "category": i.category,
        }
        for i in items
    ]


def _catalog_items(rows: list[dict[str, Any]]) -> tuple[CatalogItem, ...]:
    return tuple(
        CatalogItem(
            product_id=r["product_id"],
            name=r["name"],
            price_amount=Decimal(r["price_amount"]) if r["price_amount"] is not None else None,
            price_currency=r["price_currency"],
            category=r["category"],
        )
        for r in rows
    )


class WhatsAppMenuState(rx.State):
    """State for the Menú tab of `/whatsapp`."""

    # -- menus of the number -------------------------------------------------------------
    menus: list[MenuSummaryVM] = []
    loaded_for: str = ""
    loading_for: str = ""
    banner: str = ""
    banner_tone: str = "info"

    # -- «Nuevo menú» dialog --------------------------------------------------------------
    new_open: bool = False
    new_name: str = ""
    new_template: str = TEMPLATE_FAST_FOOD
    new_error: str = ""
    creating: bool = False

    # -- the open menu ------------------------------------------------------------------
    menu: MenuSummaryVM = EMPTY_MENU
    versions: list[MenuVersionVM] = []
    editing_from: str = ""  # «Editando a partir de la versión 3» — pre-formatted
    opening: bool = False
    saving: bool = False
    publishing: bool = False
    editing_version_id: str = ""  # the saved version on screen while `dirty` is False
    just_published: bool = False  # «listo» + the next step (the QR), until the next edit
    versions_open: bool = False  # «Ver versiones anteriores»
    pausing: bool = False
    dirty: bool = False

    # -- the form (see `MenuForm`) --------------------------------------------------------
    welcome: str = ""
    on_first_message: bool = True
    start_node: str = ""
    fallback_node: str = NONE_VALUE
    keywords: list[KeywordForm] = []
    ice_breakers: list[IceBreakerForm] = []
    commands: list[CommandForm] = []
    nodes: list[NodeForm] = []
    entry_errors: dict[str, str] = {}
    menu_errors: list[str] = []
    error_count: int = 0
    selected_node: int = 0

    # -- preview ------------------------------------------------------------------------
    preview_messages: list[PreviewMessageVM] = []
    preview_text: str = ""
    preview_paused: bool = False
    preview_order: list[str] = []
    preview_stale: bool = False
    preview_available: bool = False
    catalog_text: str = ""

    # Backend-only (underscore): never serialized to the browser.
    _scope: dict[str, str] = {}
    _catalog: list[dict[str, Any]] = []
    _payloads: dict[str, dict[str, Any]] = {}
    _valid_payload: dict[str, Any] = {}
    _preview_payload: dict[str, Any] = {}
    _preview_thread: dict[str, Any] = {}

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    @rx.var
    def has_menu(self) -> bool:
        return self.menu.menu_id != ""

    @rx.var
    def node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes if n.node_id.strip()]

    @rx.var
    def handoff_node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes if n.kind == "handoff" and n.node_id.strip()]

    @rx.var
    def selected(self) -> NodeForm:
        if 0 <= self.selected_node < len(self.nodes):
            return self.nodes[self.selected_node]
        return new_node("text", "")

    @rx.var
    def has_selected(self) -> bool:
        return 0 <= self.selected_node < len(self.nodes)

    @rx.var
    def selected_takes_options(self) -> bool:
        node = self.selected
        return node.kind in (KIND_BUTTONS, KIND_LIST)

    @rx.var
    def options_full(self) -> bool:
        node = self.selected
        limit = 3 if node.kind == KIND_BUTTONS else 10
        return len(node.options) >= limit

    @rx.var
    def issues_text(self) -> str:
        return issues_summary(self.error_count)

    @rx.var
    def can_save(self) -> bool:
        return self.error_count == 0 and self.dirty and not self.saving and self.has_menu

    @rx.var
    def can_publish(self) -> bool:
        return can_publish(
            has_menu=self.has_menu,
            error_count=self.error_count,
            dirty=self.dirty,
            editing_version_id=self.editing_version_id,
            busy=self.saving or self.publishing,
        )

    @rx.var
    def ice_breakers_full(self) -> bool:
        return len(self.ice_breakers) >= MAX_ICE_BREAKERS

    @rx.var
    def commands_full(self) -> bool:
        return len(self.commands) >= MAX_COMMANDS

    @rx.var
    def ice_breaker_count(self) -> str:
        return f"{len(self.ice_breakers)}/{MAX_ICE_BREAKERS}"

    @rx.var
    def command_count(self) -> str:
        return f"{len(self.commands)}/{MAX_COMMANDS}"

    @rx.var
    def preview_started(self) -> bool:
        return len(self.preview_messages) > 0

    @rx.var
    def ice_breaker_texts(self) -> list[str]:
        return [ib.text for ib in self.ice_breakers if ib.text.strip()]

    # ==================================================================================
    # Helpers
    # ==================================================================================

    async def _session(self) -> tuple[str, UUID | None, str]:
        auth = await self.get_state(AuthState)
        tenant = auth.session_tenant_id
        return tenant, tenant_uuid(tenant) if tenant else None, auth.user_email

    async def _connection_id(self) -> str:
        shell = await self.get_state(WhatsAppState)
        return shell.selected_connection_id

    def _scope_value(self) -> NumberScope | None:
        if not self._scope:
            return None
        brand = self._scope.get("brand_id") or ""
        return NumberScope(
            phone_row_id=UUID(self._scope["phone_row_id"]),
            brand_id=UUID(brand) if brand else None,
            brand_name=self._scope.get("brand_name", ""),
        )

    def _form(self) -> MenuForm:
        return MenuForm(
            welcome=self.welcome,
            on_first_message=self.on_first_message,
            start_node=self.start_node,
            fallback_node=self.fallback_node,
            keywords=list(self.keywords),
            ice_breakers=list(self.ice_breakers),
            commands=list(self.commands),
            nodes=list(self.nodes),
        )

    def _apply(self, form: MenuForm, *, edited: bool = True) -> None:
        """Validate `form` and put it, annotated, on screen."""
        result = validate_form(form)
        annotated = result.form
        self.welcome = annotated.welcome
        self.on_first_message = annotated.on_first_message
        self.start_node = annotated.start_node
        self.fallback_node = annotated.fallback_node
        self.keywords = annotated.keywords
        self.ice_breakers = annotated.ice_breakers
        self.commands = annotated.commands
        self.nodes = annotated.nodes
        self.entry_errors = annotated.entry_errors
        self.menu_errors = annotated.menu_errors
        self.error_count = result.error_count
        self._valid_payload = (
            result.definition.model_dump(mode="json") if result.definition is not None else {}
        )
        self.preview_available = bool(self._valid_payload)
        # Stale = a snapshot exists and differs from the editor. While the form is invalid
        # and no conversation is open, «Corrige lo marcado» already says it all.
        self.preview_stale = (
            bool(self._preview_payload)
            and self._preview_payload != self._valid_payload
            and (bool(self._valid_payload) or bool(self.preview_messages))
        )
        if not 0 <= self.selected_node < len(self.nodes):
            self.selected_node = max(0, len(self.nodes) - 1)
        if edited:
            self.dirty = True
            self.just_published = False

    def _load_definition(
        self, definition: MenuDefinition | None, label: str, version_id: str = ""
    ) -> None:
        form = definition_to_form(definition) if definition is not None else empty_form()
        self.selected_node = 0
        self._apply(form, edited=False)
        self.dirty = False
        self.editing_from = label
        self.editing_version_id = version_id
        self.just_published = False
        self._restart_preview()

    def _show_detail(self, detail: MenuDetail, *, load_form: bool) -> None:
        self.menu = detail.summary
        self.versions = detail.versions
        self._payloads = detail.payloads
        self.menus = [
            detail.summary if m.menu_id == detail.summary.menu_id else m for m in self.menus
        ]
        if detail.summary.menu_id not in {m.menu_id for m in self.menus}:
            self.menus = [*self.menus, detail.summary]
        if load_form:
            label = (
                f"Editando a partir de la {detail.versions[0].label.lower()}"
                if detail.versions
                else _DRAFT_EMPTY
            )
            newest = detail.versions[0].version_id if detail.versions else ""
            self._load_definition(detail.latest, label, newest)

    def _reset_number_scoped(self) -> None:
        self.menus = []
        self.menu = EMPTY_MENU
        self.versions = []
        self.banner = ""
        self.editing_from = ""
        self.editing_version_id = ""
        self.just_published = False
        self.versions_open = False
        self.dirty = False
        self._scope = {}
        self._catalog = []
        self._payloads = {}
        self.catalog_text = ""
        self.nodes = []
        self.keywords = []
        self.ice_breakers = []
        self.commands = []
        self.entry_errors = {}
        self.menu_errors = []
        self.error_count = 0
        self._valid_payload = {}
        self._restart_preview()

    # ==================================================================================
    # Loading
    # ==================================================================================

    @rx.event(background=True)
    async def ensure_loaded(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._load(force=False):
            yield event

    @rx.event(background=True)
    async def reload(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._load(force=True):
            yield event

    async def _load(self, *, force: bool) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            connection_id = await self._connection_id()
            if not connection_id or self.loading_for == connection_id:
                return
            if not force and self.loaded_for == connection_id:
                return
            if self.loaded_for != connection_id:
                # A new number (or a retry after a failed read): drop the old number's
                # data and its banner. A forced re-read of the number on screen keeps the
                # banner — it may be the outcome of the action that asked for the re-read.
                self._reset_number_scoped()
            self.loading_for = connection_id
            _tenant, tenant_id, _email = await self._session()
        if tenant_id is None:
            async with self:
                self.loading_for = ""
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            scope = await asyncio.to_thread(number_scope, tenant_id, UUID(connection_id))
            menus = await asyncio.to_thread(menus_for, tenant_id, scope)
            catalog = await asyncio.to_thread(preview_catalog, tenant_id, scope.brand_id)
        except (SQLAlchemyError, UnknownWhatsAppNumber) as exc:
            logger.error("whatsapp menus load failed: %s", type(exc).__name__)
            async with self:
                if await self._connection_id() == connection_id:
                    self.loading_for = ""
                    self.banner, self.banner_tone = _LOAD_FAILED, "error"
            return
        async with self:
            if await self._connection_id() != connection_id:
                self.loading_for = ""
                return  # the operator switched numbers while Postgres answered
            self._scope = {
                "phone_row_id": str(scope.phone_row_id),
                "brand_id": str(scope.brand_id) if scope.brand_id else "",
                "brand_name": scope.brand_name,
            }
            self._catalog = _catalog_rows(catalog)
            self.catalog_text = catalog_note(len(catalog), scope.brand_name)
            self.menus = menus
            self.loaded_for = connection_id
            self.loading_for = ""
            keep = self.menu.menu_id in {m.menu_id for m in menus}
            target = (
                ""
                if keep
                else next(
                    (m.menu_id for m in menus if m.is_published), menus[0].menu_id if menus else ""
                )
            )
            if not keep:
                self.menu = EMPTY_MENU
        if target:
            yield WhatsAppMenuState.open_menu(target)

    @rx.event(background=True)
    async def open_menu(self, menu_id: str) -> None:
        async with self:
            if menu_id not in {m.menu_id for m in self.menus} or self.opening:
                return  # arrived over the wire; only menus on screen can be opened
            scope = self._scope_value()
            if scope is None:
                return
            self.opening = True
            _tenant, tenant_id, _email = await self._session()
        if tenant_id is None:
            async with self:
                self.opening = False
            return
        try:
            detail = await asyncio.to_thread(menu_detail, tenant_id, scope, UUID(menu_id))
        except (SQLAlchemyError, MenuNotFound, ValidationError) as exc:
            logger.error("whatsapp menu open failed: %s", type(exc).__name__)
            async with self:
                self.opening = False
                self.banner, self.banner_tone = _MENU_GONE, "warn"
            return
        async with self:
            self.opening = False
            self.banner = ""
            self._show_detail(detail, load_form=True)

    # ==================================================================================
    # «Nuevo menú»
    # ==================================================================================

    @rx.event
    def set_new_open(self, value: bool) -> None:
        self.new_open = value
        if value:
            self.new_name = "" if self.menus else "Menú principal"
            self.new_template = TEMPLATE_FAST_FOOD
            self.new_error = ""

    @rx.event
    def set_new_name(self, value: str) -> None:
        self.new_name = value
        self.new_error = ""

    @rx.event
    def set_new_template(self, value: str | list[str]) -> None:
        if value in (TEMPLATE_EMPTY, TEMPLATE_FAST_FOOD):
            self.new_template = str(value)

    @rx.event(background=True)
    async def create_new_menu(self) -> None:
        async with self:
            if self.creating:
                return
            problem = validate_menu_name(self.new_name, [m.name for m in self.menus])
            if problem:
                self.new_error = problem
                return
            scope = self._scope_value()
            if scope is None:
                return
            self.creating = True
            name, template = self.new_name, self.new_template
            _tenant, tenant_id, email = await self._session()
        if tenant_id is None:
            async with self:
                self.creating = False
                self.new_error = _NO_SESSION
            return
        try:
            user_id = await asyncio.to_thread(user_id_for, tenant_id, email)
            detail = await asyncio.to_thread(
                create_menu, tenant_id, scope, name, template, user_id=user_id
            )
        except (IntegrityError, ValueError):
            async with self:
                self.creating = False
                self.new_error = _NAME_TAKEN
            return
        except SQLAlchemyError as exc:
            logger.error("whatsapp menu create failed: %s", type(exc).__name__)
            async with self:
                self.creating = False
                self.new_error = _SAVE_FAILED
            return
        async with self:
            self.creating = False
            self.new_open = False
            self._show_detail(detail, load_form=True)

    # ==================================================================================
    # Entry section
    # ==================================================================================

    @rx.event
    def set_welcome(self, value: str) -> None:
        self.welcome = value
        self._apply(self._form())

    @rx.event
    def set_on_first_message(self, value: bool) -> None:
        self.on_first_message = bool(value)
        self._apply(self._form())

    @rx.event
    def set_start_node(self, value: str) -> None:
        self.start_node = value
        self._apply(self._form())

    @rx.event
    def set_fallback_node(self, value: str) -> None:
        self.fallback_node = value
        self._apply(self._form())

    @rx.event
    def add_entry_row(self, table: str) -> None:
        form = self._form()
        target = self.start_node if self.start_node in self.node_ids else ""
        if table == "keywords":
            form = replace(form, keywords=[*form.keywords, KeywordForm(word="", node=target)])
        elif table == "ice_breakers" and len(form.ice_breakers) < MAX_ICE_BREAKERS:
            form = replace(
                form, ice_breakers=[*form.ice_breakers, IceBreakerForm(text="", node=target)]
            )
        elif table == "commands" and len(form.commands) < MAX_COMMANDS:
            form = replace(form, commands=[*form.commands, CommandForm("", "", target)])
        else:
            return
        self._apply(form)

    @rx.event
    def remove_entry_row(self, table: str, index: int) -> None:
        if table not in _ENTRY_TABLES:
            return
        rows = list(getattr(self, table))
        if not 0 <= index < len(rows):
            return
        rows.pop(index)
        self._apply(replace(self._form(), **{table: rows}))

    @rx.event
    def set_entry_row(self, table: str, index: int, field: str, value: str) -> None:
        if field not in _ENTRY_TABLES.get(table, frozenset()) or not isinstance(value, str):
            return
        rows = list(getattr(self, table))
        if not 0 <= index < len(rows):
            return
        rows[index] = replace(rows[index], **{field: value})
        self._apply(replace(self._form(), **{table: rows}))

    # ==================================================================================
    # Steps
    # ==================================================================================

    @rx.event
    def select_node(self, index: int) -> None:
        if 0 <= index < len(self.nodes):
            self.selected_node = index

    @rx.event
    def add_node(self, kind: str) -> None:
        if kind not in KIND_KEYS:
            return
        form = self._form()
        node = new_node(kind, unique_node_id(form, kind if kind != "order_summary" else "resumen"))
        self._apply(replace(form, nodes=[*form.nodes, node]))
        self.selected_node = len(self.nodes) - 1

    @rx.event
    def remove_node(self, index: int) -> None:
        if not 0 <= index < len(self.nodes) or len(self.nodes) <= 1:
            return
        nodes = [n for k, n in enumerate(self.nodes) if k != index]
        if self.selected_node >= index:
            self.selected_node = max(0, self.selected_node - 1)
        self._apply(replace(self._form(), nodes=nodes))

    @rx.event
    def set_node_field(self, field: str, value: str) -> None:
        index = self.selected_node
        if field not in _NODE_FIELDS or not isinstance(value, str):
            return
        if not 0 <= index < len(self.nodes):
            return
        form = self._form()
        if field == "node_id":
            form = rename_node(form, index, value.strip().lower())
        else:
            nodes = list(form.nodes)
            nodes[index] = replace(nodes[index], **{field: value})
            form = replace(form, nodes=nodes)
        self._apply(form)

    @rx.event
    def set_node_kind(self, kind: str) -> None:
        index = self.selected_node
        if kind not in KIND_KEYS or not 0 <= index < len(self.nodes):
            return
        nodes = list(self.nodes)
        nodes[index] = change_kind(nodes[index], kind)
        self._apply(replace(self._form(), nodes=nodes))

    def _replace_options(self, options: list) -> None:
        index = self.selected_node
        nodes = list(self.nodes)
        nodes[index] = replace(nodes[index], options=options)
        self._apply(replace(self._form(), nodes=nodes))

    @rx.event
    def add_option(self) -> None:
        index = self.selected_node
        if not 0 <= index < len(self.nodes) or self.options_full:
            return
        node = self.nodes[index]
        self._replace_options([*node.options, new_option(node)])

    @rx.event
    def remove_option(self, option: int) -> None:
        index = self.selected_node
        if not 0 <= index < len(self.nodes):
            return
        options = list(self.nodes[index].options)
        if not 0 <= option < len(options):
            return
        options.pop(option)
        self._replace_options(options)

    @rx.event
    def move_option(self, option: int, delta: int) -> None:
        index = self.selected_node
        if not 0 <= index < len(self.nodes):
            return
        options = list(self.nodes[index].options)
        target = option + delta
        if not (0 <= option < len(options) and 0 <= target < len(options)):
            return
        options[option], options[target] = options[target], options[option]
        self._replace_options(options)

    @rx.event
    def set_option_field(self, option: int, field: str, value: str) -> None:
        index = self.selected_node
        if field not in _OPTION_FIELDS or not isinstance(value, str):
            return
        if not 0 <= index < len(self.nodes):
            return
        options = list(self.nodes[index].options)
        if not 0 <= option < len(options):
            return
        options[option] = replace(options[option], **{field: value})
        self._replace_options(options)

    # ==================================================================================
    # Versions
    # ==================================================================================

    @rx.event
    def open_version(self, version_id: str) -> None:
        """Load a saved version into the editor (no database read: payloads came with the
        history). Unsaved edits are dropped — the button says so."""
        payload = self._payloads.get(version_id)
        version = next((v for v in self.versions if v.version_id == version_id), None)
        if payload is None or version is None:
            return
        self._load_definition(
            MenuDefinition.model_validate(payload),
            f"Editando a partir de la {version.label.lower()}",
            version_id,
        )

    @rx.event
    def toggle_versions(self) -> None:
        self.versions_open = not self.versions_open

    @rx.event
    def dismiss_next_step(self) -> None:
        self.just_published = False

    async def _save_outside_lock(
        self, tenant_id: UUID, scope: NumberScope, menu_id: str, payload: dict[str, Any]
    ) -> MenuDetail | None:
        """Write `payload` as the menu's next version (outside the state lock). On success
        the new version is on screen and the editor is clean; on failure the banner says
        so, `saving` is cleared and None comes back."""
        try:
            detail = await asyncio.to_thread(save_version, tenant_id, scope, UUID(menu_id), payload)
        except ValidationError:
            # The repository re-validates; reaching here means the editor's check and the
            # schema disagree — never Meta's text, never the payload.
            async with self:
                self.saving = False
                self.banner, self.banner_tone = _SAVE_FAILED, "warn"
            return None
        except (SQLAlchemyError, MenuNotFound) as exc:
            logger.error("whatsapp menu save failed: %s", type(exc).__name__)
            async with self:
                self.saving = False
                self.banner, self.banner_tone = _SAVE_FAILED, "error"
            return None
        async with self:
            self.saving = False
            self.dirty = False
            self._show_detail(detail, load_form=False)
            newest = detail.versions[0] if detail.versions else None
            self.editing_version_id = newest.version_id if newest else ""
            self.editing_from = f"Editando a partir de la {newest.label.lower()}" if newest else ""
        return detail

    @rx.event(background=True)
    async def save_current_version(self) -> None:
        """«Guardar sin publicar» — the secondary action."""
        async with self:
            if not self.can_save or self.publishing:
                return
            scope = self._scope_value()
            if scope is None:
                return
            self.saving = True
            self.banner = ""
            self.just_published = False
            payload = dict(self._valid_payload)
            menu_id = self.menu.menu_id
            _tenant, tenant_id, _email = await self._session()
        if tenant_id is None:
            async with self:
                self.saving = False
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        detail = await self._save_outside_lock(tenant_id, scope, menu_id, payload)
        if detail is None:
            return
        async with self:
            label = detail.versions[0].label.lower() if detail.versions else ""
            number = label.removeprefix("versión ").strip()
            self.banner, self.banner_tone = _SAVED.format(n=number), "ok"

    @rx.event(background=True)
    async def publish_current(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Publicar en mi WhatsApp», after its confirmation: save the editor's changes as
        a new version (when there are any), then publish the version on screen. One tap,
        one outcome — the owner never has to find a second button to make it answer."""
        async with self:
            if not self.can_publish:
                return
            scope = self._scope_value()
            if scope is None:
                return
            must_save = self.dirty
            self.saving = must_save
            self.publishing = True
            self.banner = ""
            self.just_published = False
            payload = dict(self._valid_payload)
            menu_id = self.menu.menu_id
            version_id = self.editing_version_id
            connection_id = await self._connection_id()
            _tenant, tenant_id, email = await self._session()
        if tenant_id is None:
            async with self:
                self.saving = self.publishing = False
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        if must_save:
            detail = await self._save_outside_lock(tenant_id, scope, menu_id, payload)
            if detail is None or not detail.versions:
                async with self:
                    self.publishing = False
                return
            version_id = detail.versions[0].version_id
        try:
            user_id = await asyncio.to_thread(user_id_for, tenant_id, email)
            outcome = await publish_version(
                tenant_id,
                UUID(connection_id),
                scope,
                UUID(menu_id),
                UUID(version_id),
                user_id=user_id,
            )
        except (SQLAlchemyError, MenuNotFound, MenuVersionNotFound) as exc:
            logger.error("whatsapp menu publish failed: %s", type(exc).__name__)
            async with self:
                self.publishing = False
                self.banner, self.banner_tone = _PUBLISH_FAILED, "error"
            return
        async with self:
            self.publishing = False
            published = outcome.detail.summary.menu_id
            # Publishing demotes the number's other menus: their summaries are stale.
            self.menus = [
                replace(m, is_published=False, published_label="Sin publicar")
                if m.menu_id != published and m.is_published
                else m
                for m in self.menus
            ]
            self._show_detail(outcome.detail, load_form=False)
            # The menu is live in Qualify in every non-raising case; the next step (the
            # QR) only makes sense when the number is not asking to be reconnected. A
            # clean publish says «listo» right where the owner tapped (the toolbar), so
            # the banner up top only carries the partial failures.
            self.just_published = not outcome.auth_error
            if outcome.tone != "ok" or not self.just_published:
                self.banner, self.banner_tone = outcome.notice, outcome.tone
        if outcome.auth_error:
            yield WhatsAppState.load_numbers

    @rx.event(background=True)
    async def toggle_pause(self, paused: bool) -> None:
        async with self:
            if self.pausing or not self.has_menu:
                return
            scope = self._scope_value()
            if scope is None:
                return
            self.pausing = True
            self.banner = ""
            menu_id = self.menu.menu_id
            _tenant, tenant_id, _email = await self._session()
        if tenant_id is None:
            async with self:
                self.pausing = False
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            detail = await asyncio.to_thread(
                set_paused, tenant_id, scope, UUID(menu_id), bool(paused)
            )
        except (SQLAlchemyError, MenuNotFound) as exc:
            logger.error("whatsapp menu pause failed: %s", type(exc).__name__)
            async with self:
                self.pausing = False
                self.banner, self.banner_tone = _PAUSE_FAILED, "error"
            return
        async with self:
            self.pausing = False
            self._show_detail(detail, load_form=False)
            self.banner, self.banner_tone = (_PAUSED, "warn") if paused else (_RESUMED, "ok")

    # ==================================================================================
    # Preview
    # ==================================================================================

    def _restart_preview(self) -> None:
        self._preview_payload = dict(self._valid_payload)
        self._preview_thread = {"node_id": None, "context": {}, "paused": False, "attempts": 0}
        self.preview_messages = []
        self.preview_order = []
        self.preview_paused = False
        self.preview_stale = False
        self.preview_text = ""

    @rx.event
    def restart_preview(self) -> None:
        self._restart_preview()

    @rx.event
    def set_preview_text(self, value: str) -> None:
        self.preview_text = value

    def _turn(self, inbound: Inbound, shown: str) -> None:
        if not self._preview_payload or self.preview_paused or not shown.strip():
            return
        definition = MenuDefinition.model_validate(self._preview_payload)
        thread = self._preview_thread or {}
        state = ThreadMenuState(
            node_id=thread.get("node_id"),
            context=dict(thread.get("context") or {}),
            paused=bool(thread.get("paused", False)),
            attempts=int(thread.get("attempts", 0)),
        )
        result = preview_turn(
            definition,
            state,
            inbound,
            _catalog_items(self._catalog),
            shown_text=shown,
            start_index=len(self.preview_messages),
        )
        self._preview_thread = {
            "node_id": result.state.node_id,
            "context": result.state.context,
            "paused": result.state.paused,
            "attempts": result.state.attempts,
        }
        self.preview_messages = [*self.preview_messages, *result.messages]
        self.preview_order = order_lines(result.state)
        self.preview_paused = result.state.paused

    def _send_typed(self) -> None:
        text = self.preview_text.strip()
        first = len(self.preview_messages) == 0
        self.preview_text = ""
        self._turn(Inbound.text(text, first_message=first), text)

    @rx.event
    def preview_send(self) -> None:
        self._send_typed()

    @rx.event
    def preview_key(self, key: str) -> None:
        if key == "Enter":
            self._send_typed()

    @rx.event
    def preview_shortcut(self, text: str) -> None:
        """An ice breaker tapped: WhatsApp delivers it as a plain text message."""
        self._turn(Inbound.text(text, first_message=len(self.preview_messages) == 0), text)

    @rx.event
    def preview_open_chat(self) -> None:
        """Meta's `request_welcome`: the customer opened the chat without typing."""
        if self.preview_messages:
            return
        self._turn(Inbound.welcome(), "(abre el chat)")

    @rx.event
    def preview_choose(self, reply_kind: str, reply_id: str, title: str) -> None:
        inbound = (
            Inbound.list_reply(reply_id)
            if reply_kind == REPLY_LIST
            else Inbound.button_reply(reply_id)
        )
        self._turn(inbound, title)
