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

**The menu in four steps** (m-24848536) is the default view: `guided` reads the four
steps' fields off the same form, and every guided handler is a pure `guided_*` function
of `whatsapp_menu_vm.py` passed through `_apply` — «Atrás», «Siguiente» and «Más opciones
(avanzado)» only move `guided_step` / `advanced_open`, so nothing typed is lost. Step ids
are generated on creation and never edited; a step is renamed through its `title`. The
time from opening a menu to publishing it from the four steps is logged
(`whatsapp_menu_guided_publish`) — the ≤ 5 min goal is measured, not enforced.

**Step 2 is one ordered list of answers** (m-24936836): `answers` (an `AnswersVM`) is
re-read on every `_apply`, every edit goes through a pure `answers_*` function, and the
panel of one answer is `answer_open` (an index, range-checked). A new menu is born from
`starter_facts` (the brand's name, «Tu marca»'s city, and the WhatsApp profile's address
only when the Perfil tab already read it — no Graph call). A gap («[hora de abrir]»)
blocks publishing (`gap_count`), and the provider refuses it again (`MenuHasGaps`).

**The preview runs the real engine** (`engine.step`) over the brand's real catalog, on a
snapshot of the definition taken at «Reiniciar»: editing while a conversation is open
cannot pull a node out from under it; the panel says when the snapshot is stale.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from functools import partial
from typing import Any
from uuid import UUID

import reflex as rx
from pydantic import ValidationError
from qualify_api.catalog.order import category_key
from qualify_api.whatsapp.menus import MenuNotFound, MenuVersionNotFound
from qualify_api.whatsapp.menus.engine import CatalogItem, Inbound, ThreadMenuState
from qualify_api.whatsapp.menus.schema import MAX_COMMANDS, MAX_ICE_BREAKERS, MenuDefinition
from qualify_api.whatsapp.menus.starter import (
    MenuHasGaps,
    StarterFacts,
    definition_gaps,
    payment_answer,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .auth_state import AuthState
from .catalog_group_vm import (
    NAME_MAX,
    NAME_TOO_LONG,
    existing_spelling,
    group_href,
    is_uncategorized,
    name_counter,
    notice_count,
    notice_text,
)
from .catalog_order_vm import order_href
from .catalog_provider import business_currency, uncategorized_notice
from .catalog_state import CatalogState
from .nav_url import flow_param, uuid_param, with_query
from .tenant import tenant_uuid
from .ui.steps import step_settle_script
from .ui.steps_vm import DIR_NEXT, guard_step, step_direction
from .upload_names import safe_upload_name
from .whatsapp_menu_provider import (
    AddedProducts,
    FoundProduct,
    ImportProposal,
    ImportSource,
    MenuDetail,
    NothingFound,
    NumberScope,
    SourceUnsupported,
    SuggestInput,
    SuggestProposal,
    add_catalog_products,
    create_menu,
    import_menu_facts,
    menu_detail,
    menus_for,
    number_scope,
    payment_options,
    preview_catalog,
    publish_version,
    save_version,
    set_paused,
    starter_facts,
    suggest_text,
    user_id_for,
)
from .whatsapp_menu_vm import (
    ANSWER_NAME_NEEDS_FIX,
    CATALOG_FIX_FIRST,
    EMPTY_ANSWERS,
    EMPTY_GUIDED,
    EMPTY_IMPORT,
    EMPTY_MENU,
    FACT_PENDING,
    FACT_SENTENCE,
    FACT_SKIPPED,
    FACT_USED,
    GUIDED_HELP,
    GUIDED_STEPS,
    GUIDED_TITLES,
    IMPORT_ADD_FAILED,
    IMPORT_ADD_NEEDS_BRAND,
    IMPORT_CHOOSE,
    IMPORT_EMPTY_PHASE,
    IMPORT_FAILED,
    IMPORT_FAILED_PHASE,
    IMPORT_MAX_BYTES,
    IMPORT_PAGE,
    IMPORT_PAGE_NEEDS_LINK,
    IMPORT_PHOTO,
    IMPORT_READING,
    IMPORT_REJECTED,
    IMPORT_REVIEW,
    IMPORT_TOO_BIG,
    IMPORT_UPLOAD_FAILED,
    KIND_BUTTONS,
    KIND_KEYS,
    KIND_LABELS,
    KIND_LIST,
    NO_PUBLISH_GAPS,
    NO_SUGGESTION,
    NONE_VALUE,
    PUBLISH_NEEDS_ANSWERS,
    REPLY_LIST,
    SAVE_NEEDS_FIX,
    SUGGEST_ANSWER,
    SUGGEST_FAILED,
    SUGGEST_GREETING,
    SUGGEST_NO_DATA,
    SUGGEST_STALE,
    TEMPLATE_EMPTY,
    TEMPLATE_FAST_FOOD,
    AnswersVM,
    AnswerVM,
    CatalogRowVM,
    CatalogSectionVM,
    CommandForm,
    GuidedVM,
    IceBreakerForm,
    ImportVM,
    KeywordForm,
    MenuForm,
    MenuSummaryVM,
    MenuVersionVM,
    NodeChoiceVM,
    NodeForm,
    PreviewMessageVM,
    PublishGapsVM,
    SuggestVM,
    added_lines,
    answer_set_label,
    answer_set_text,
    answers_add,
    answers_move,
    answers_remove,
    answers_view,
    answers_without_gaps,
    apply_fact,
    apply_sentences,
    button_limit_text,
    can_publish,
    catalog_mode_line,
    catalog_more_line,
    catalog_note,
    catalog_order_line,
    catalog_rows,
    catalog_sections,
    change_kind,
    definition_to_form,
    edited_kind,
    empty_form,
    fact_plan,
    fact_rows,
    first_gap_literal,
    fresh_node_id,
    group_plan,
    guided_add_button,
    guided_remove_button,
    guided_review,
    guided_set_address,
    guided_set_address_prompt,
    guided_set_button_action,
    guided_set_button_label,
    guided_set_button_text,
    guided_set_greeting,
    guided_set_products_intro,
    guided_set_question,
    guided_step_label,
    guided_use_buttons,
    guided_view,
    import_empty_text,
    import_view,
    issues_summary,
    move_hits_button_limit,
    new_node,
    new_option,
    node_choices,
    order_lines,
    preview_turn,
    product_rows,
    publish_confirm_lines,
    publish_gaps,
    read_answers,
    remove_confirm_text,
    row_kind,
    sentence_group,
    suggest_context,
    suggest_has_input,
    suggest_label,
    suggest_proposal_vm,
    suggest_writing_line,
    validate_form,
    validate_menu_name,
)
from .whatsapp_provider import UnknownWhatsAppNumber
from .whatsapp_state import WhatsAppState

logger = logging.getLogger(__name__)

#: WhatsApp → Tu número → Formas de pago (m-24955648).
PAYMENTS_HREF = "/whatsapp?tab=numero&sub=pagos"

#: The review's heading: focus lands there when «Leyendo» turns into the review (the
#: focused «Cancelar» is gone), so a screen reader hears where it is.
IMPORT_REVIEW_HEADING_ID = "whatsapp-menu-import-review"


def _focus_review() -> rx.event.EventSpec:
    return rx.call_script(
        "window.requestAnimationFrame(() => window.requestAnimationFrame(() => {"
        f"const h=document.getElementById('{IMPORT_REVIEW_HEADING_ID}');"
        "if(h)h.focus();}));"
    )


#: Step 2's answer text: «Completarlas» focuses it on its first gap (m-24945866).
ANSWER_TEXT_ID = "whatsapp-menu-answer-text"


def _focus_first_gap(literal: str) -> rx.event.EventSpec:
    """Focus the open answer's text with its first gap (`literal`, «[minutos]») selected and
    in view: a gap at the end of a long text is what the owner could not find (m-24945866).
    The dialog mounts a moment after the panel opens and Radix focuses its first button, so
    this retries for a short while and runs after that."""
    return rx.call_script(
        "(function(){let n=0;const t=()=>{"
        f"const el=document.getElementById('{ANSWER_TEXT_ID}');"
        "if(!el){if(n++<20)setTimeout(t,50);return;}"
        "el.focus({preventScroll:true});"
        f"const g={json.dumps(literal)};const a=g?el.value.indexOf(g):-1;"
        "if(a>=0){el.setSelectionRange(a,a+g.length);"
        "el.scrollTop=el.scrollHeight*(a/Math.max(1,el.value.length))-el.clientHeight/2;}"
        "el.scrollIntoView({block:'center'});};setTimeout(t,80);})();"
    )


#: The one-at-a-time slot (`suggest_busy`) while a menu import reads: no suggestion and no
#: second import while one paid call is in flight (m-24936840).
SUGGEST_IMPORT = "import"
#: Seconds before the waiting screen says «Está tardando más de lo normal…» (spec §4 b).
IMPORT_SLOW_AFTER = 60.0

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudieron cargar los menús de este número. Vuelve a intentarlo en un momento."
_SAVE_FAILED = "No se pudo guardar la versión. Vuelve a intentarlo en un momento."
_PUBLISH_FAILED = "No se pudo publicar la versión. Vuelve a intentarlo en un momento."
_PUBLISH_GAPS = (
    "Esta versión tiene datos por completar. Complétalos o quita esas respuestas y vuelve a "
    "publicar. Si los corchetes son a propósito, cámbialos por paréntesis ( )."
)
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
_SUGGEST_NEEDS_NAME = "Ponle primero un nombre a esta respuesta y lo escribimos con tu estilo."

_ENTRY_TABLES: dict[str, frozenset[str]] = {
    "keywords": frozenset({"word", "node"}),
    "ice_breakers": frozenset({"text", "node"}),
    "commands": frozenset({"name", "hint", "node"}),
}
# No "node_id": a step's id is generated when it is created and never edited
# (m-24848536); renaming a step edits its "title".
_NODE_FIELDS = frozenset(
    {
        "title",
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


def _payment_options(tenant_id: UUID, brand_id: UUID | None) -> tuple[Any, ...] | None:
    """Blocking: the methods the business offers (m-24955648), ONE read per load —
    the live «Formas de pago», the gap rule, the preview and step 3's invitation.
    None = could not read them (the old rule stays: the stored gap blocks)."""
    return payment_options(tenant_id, brand_id)


def _notice_show_for(tenant_id: UUID, brand_id: UUID | None) -> bool:
    """Blocking: whether step 3 shows «N productos sin categoría» (m-24955838). A read
    that fails hides the notice: it is a suggestion, never worth breaking the menu."""
    try:
        return uncategorized_notice(tenant_id, brand_id)[1]
    except Exception as exc:  # noqa: BLE001
        logger.warning("uncategorized notice read failed: %s", type(exc).__name__)
        return False


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

    # -- the menu in four steps (m-24848536) --------------------------------------------
    guided_step: int = 1
    guided_direction: str = DIR_NEXT
    resume_pending: bool = False
    publish_confirm_open: bool = False
    flow_ready: bool = False
    advanced_open: bool = False  # «Más opciones (avanzado)»: the full editor
    catalog: list[CatalogRowVM] = []  # the brand's products, for step 3 (names + prices)
    #: m-24955838 — step 3's «N productos sin categoría» (0 = no line).
    group_notice_count: int = 0
    #: The backend's verdict (`CatalogService.uncategorized_notice`), read with the catalog.
    _notice_show: bool = False
    #: m-24955648 — payment methods the business offers (-1 = could not read them), and
    #: the methods themselves as the engine reads them (`as_option`).
    payments_offered: int = -1
    _payment_options: list[Any] = []
    #: m-24955838 — the import review's category being edited (index in the proposal).
    import_category_editing: int = -1
    import_category_text: str = ""
    import_category_error: str = ""

    # -- step 2: the answers (m-24936836) -----------------------------------------------
    answers: AnswersVM = EMPTY_ANSWERS
    answer_open: int = -1  # the answer whose panel is open; -1 = the list
    answer_from_gaps: bool = False  # opened by step 4 «Completarlas»: say how to fill it
    answer_confirm_remove: bool = False  # «¿Quitar «Reservas»?» inside the panel
    limit_notice: int = -1  # «Subir» hit the 3-button limit on this answer
    add_open: bool = False  # «Agregar otra respuesta» shows its suggestions
    gap_count: int = 0  # places a customer could read a «[…]» gap in
    publish_gaps: PublishGapsVM = NO_PUBLISH_GAPS
    strip_confirm_open: bool = False  # «Se quitan Horario y Reservas. ¿Publicar sin ellas?»

    # -- «Mejorar mi texto» / «Escribirlo por mí» (m-24936838) ---------------------------
    suggest_busy: str = ""  # SUGGEST_GREETING / SUGGEST_ANSWER while Claude writes; one at a time
    greeting_suggest: SuggestVM = NO_SUGGESTION
    answer_suggest: SuggestVM = NO_SUGGESTION  # for the answer whose panel is open
    suggest_writing: str = ""  # «Escribiendo tu texto…»
    suggest_notice: str = ""  # «Ir a Tu marca» refused: shown next to that button

    # -- «Cargar desde una foto o mi página» (m-24936840) --------------------------------
    import_phase: str = ""  # "" = closed; IMPORT_CHOOSE / _PHOTO / _PAGE / _READING / …
    import_offer: bool = False  # opened right after creating the menu: «Ahora no»
    import_kind: str = ""  # what was read: "image" | "pdf" | "url"
    import_url: str = ""
    import_url_error: str = ""
    import_error: str = ""  # the failed state's message (a SourceUnsupported reason)
    import_slow: bool = False  # «Está tardando más de lo normal…»
    import_review: ImportVM = EMPTY_IMPORT
    import_editing: int = -1  # the fact whose value is being edited
    import_adding: bool = False  # «Agregar los marcados a Tus productos» in flight
    import_add_error: str = ""

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
    _guided_started_at: float = 0.0  # wall clock when the menu was opened (measurement)
    _guided_used_advanced: bool = False
    # Per field ("greeting" / "answer:<option id>"): the owner's text before the first
    # proposal (what «Deshacer» brings back, exactly) and the last proposal (what «Otra
    # versión» asks to differ from). Dropped as soon as the owner types in that field.
    _suggest_undo: dict[str, str] = {}
    _suggest_last: dict[str, str] = {}
    # Bumped whenever the editor loads another menu/version or number: a call in flight
    # that started under an older epoch settles without touching the new editor.
    _suggest_epoch: int = 0
    # The proposal under review, as plain JSON (see `fact_rows` / `product_rows`).
    _import_facts: list[dict[str, str]] = []
    _import_products: list[dict[str, str]] = []
    _import_warnings: list[str] = []
    _import_label: str = ""
    _import_added: list[str] = []
    _import_currency: str = ""  # the business's own, for a price without one
    _import_staged: str = ""  # the uploaded file, in a private temp file until read
    # Bumped by «Cancelar» / closing: a read in flight settles without reaching the screen.
    _import_epoch: int = 0

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
    def node_choices(self) -> list[NodeChoiceVM]:
        """«Lleva a» entries: the value is the step id, the owner reads its name."""
        return node_choices(self.nodes)

    @rx.var
    def handoff_choices(self) -> list[NodeChoiceVM]:
        return node_choices(self.nodes, handoffs_only=True)

    @rx.var
    def guided(self) -> GuidedVM:
        if not self.nodes:
            return EMPTY_GUIDED
        # Every field read through `self.` here (not via `_form()`), so the computed var's
        # dependency tracking sees each one.
        form = MenuForm(
            welcome=self.welcome,
            on_first_message=self.on_first_message,
            start_node=self.start_node,
            fallback_node=self.fallback_node,
            keywords=list(self.keywords),
            ice_breakers=list(self.ice_breakers),
            commands=list(self.commands),
            nodes=list(self.nodes),
            entry_errors=dict(self.entry_errors),
            menu_errors=list(self.menu_errors),
        )
        return guided_view(form, self.error_count)

    @rx.var
    def guided_step_text(self) -> str:
        return guided_step_label(self.guided_step)

    @rx.var
    def guided_title(self) -> str:
        return GUIDED_TITLES[min(max(self.guided_step, 1), GUIDED_STEPS) - 1]

    @rx.var
    def guided_help(self) -> str:
        return GUIDED_HELP[min(max(self.guided_step, 1), GUIDED_STEPS) - 1]

    @rx.var
    def guided_review(self) -> list[str]:
        return guided_review(
            self.guided,
            len(self.catalog),
            self.answers,
            has_fallback=self.fallback_node not in ("", NONE_VALUE),
        )

    @rx.var
    def greeting_suggest_label(self) -> str:
        return suggest_label(self.welcome)

    @rx.var
    def answer_suggest_label(self) -> str:
        return suggest_label(self.open_answer.text)

    @rx.var
    def open_answer(self) -> AnswerVM:
        """The answer whose panel is open (an empty one while the list shows)."""
        for answer in [*self.answers.buttons, *self.answers.rows]:
            if answer.index == self.answer_open:
                return answer
        return AnswerVM(
            index=-1,
            label="",
            does="",
            preview="",
            text="",
            text_editable=False,
            is_products=False,
            status_label="",
            status_tone="neutral",
            gaps_line="",
            has_gaps=False,
            label_count="",
            label_error="",
            text_error="",
            is_button=False,
            can_up=False,
            can_down=False,
        )

    @rx.var
    def publish_block_reason(self) -> str:
        """Why «Publicar en mi WhatsApp» is off, in the owner's words ("" when it is on):
        what to fix, data to complete, or an answer's name — never mixed up."""
        if self.error_count > 0:
            return SAVE_NEEDS_FIX
        if self.gap_count > 0:
            return self.publish_gaps.block_reason or PUBLISH_NEEDS_ANSWERS
        # An empty answer text is already a schema error (SAVE_NEEDS_FIX above).
        if self.answers.name_issue:
            return ANSWER_NAME_NEEDS_FIX
        return ""

    @rx.var
    def publish_block_detail(self) -> str:
        """Under `publish_block_reason`: which data, where («Domicilio: minutos · Reservas:
        cuánto tardas en responder»), "" when no gap is what blocks (m-24945866)."""
        if self.error_count > 0 or self.gap_count == 0:
            return ""
        return self.publish_gaps.detail

    @rx.var
    def has_open_answer(self) -> bool:
        return self.answer_open >= 0

    @rx.var
    def remove_confirm_text(self) -> str:
        label = self.open_answer.label.strip() or "esta respuesta"
        return remove_confirm_text(label)

    @rx.var
    def limit_notice_text(self) -> str:
        rows = [a for a in self.answers.rows if a.index == self.limit_notice]
        return button_limit_text(rows[0].label.strip()) if rows else ""

    @rx.var
    def limit_move_label(self) -> str:
        """«Bajar «Horario»»: the last button, the one that would make room."""
        buttons = self.answers.buttons
        return f"Bajar «{buttons[-1].label.strip()}»" if buttons else ""

    @rx.var
    def catalog_count(self) -> int:
        return len(self.catalog)

    @rx.var
    def catalog_first_screen(self) -> list[CatalogSectionVM]:
        """Step 3, read-only (m-24955643): what the customer sees before «Ver más»,
        by category, in the order chosen in Catálogo."""
        return catalog_sections(self.catalog)

    @rx.var
    def catalog_order_text(self) -> str:
        return catalog_order_line(self.catalog)

    @rx.var
    def catalog_more_text(self) -> str:
        return catalog_more_line(self.catalog)

    @rx.var
    def catalog_mode_text(self) -> str:
        """Categories first (m-24955838): the customer picks a category, then products."""
        return catalog_mode_line(self.catalog)

    @rx.var
    def group_notice_text(self) -> str:
        """Step 3 (m-24955838): «Tienes N productos sin categoría…» — "" hides it."""
        return notice_text(self.group_notice_count) if self.group_notice_count else ""

    async def _count_uncategorized(self) -> None:
        """Inside `async with self`: the products of the preview catalog without a
        category, minus the ones the owner chose to leave in «Otros» (Catálogo's
        «Dejar el resto en «Otros»», kept for the session in `CatalogState`)."""
        try:
            dismissed = list((await self.get_state(CatalogState)).dismissed_uncategorized)
        except Exception:  # noqa: BLE001 — no event context (tests): nothing dismissed
            dismissed = []
        self.group_notice_count = notice_count(
            [str(r["product_id"]) for r in self._catalog if is_uncategorized(r.get("category"))],
            dismissed,
            show=self._notice_show,
        )

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
        # A gap («[hora de abrir]») or an answer named twice never reaches a customer.
        return (
            can_publish(
                has_menu=self.has_menu,
                error_count=self.error_count,
                dirty=self.dirty,
                editing_version_id=self.editing_version_id,
                busy=self.saving or self.publishing,
            )
            and self.gap_count == 0
            and not self.answers.blocking
        )

    @rx.var
    def publish_confirm_lines(self) -> list[str]:
        """The confirmation's case lines: save first / back to version n / re-send the
        live one, and the other menu it replaces (only when one is answering)."""
        version = next((v for v in self.versions if v.version_id == self.editing_version_id), None)
        other = next(
            (m.name for m in self.menus if m.is_published and m.menu_id != self.menu.menu_id),
            "",
        )
        return publish_confirm_lines(
            dirty=self.dirty,
            version=version,
            other_published_menu=other,
            paused=self.menu.is_paused,
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

    async def _profile_address(self) -> str:
        """The WhatsApp profile's address, only if the Perfil tab already read it for this
        number (m-24936836: no Graph call to create a menu or to suggest a text)."""
        shell = await self.get_state(WhatsAppState)
        if shell.profile_loaded_for and shell.profile_loaded_for == shell.selected_connection_id:
            return shell.form_address
        return ""

    def _scope_value(self) -> NumberScope | None:
        if not self._scope:
            return None
        brand = self._scope.get("brand_id") or ""
        return NumberScope(
            phone_row_id=UUID(self._scope["phone_row_id"]),
            brand_id=UUID(brand) if brand else None,
            brand_name=self._scope.get("brand_name", ""),
            business_name=self._scope.get("business_name", ""),
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
        self._refresh_answers(annotated, result.definition)
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

    def _live_payment_nodes(self) -> set[str]:
        """The answer composed live from the payment methods ({} when none is)."""
        definition = validate_form(self._form()).definition
        live = payment_answer(definition, self._payment_options) if definition else None
        return {live.node_id} if live is not None and live.auto_composed else set()

    def _refresh_answers(self, annotated: MenuForm, definition: MenuDefinition | None) -> None:
        """Step 2's list and step 4's gaps, from the annotated form (m-24936836)."""
        # m-24955648 §6: the starter's «Formas de pago» is composed live while the
        # business offers methods — its text is theirs, and its stored gap is never read
        # (the same rule as the server's `publish_menu`).
        offered = bool(self._payment_options)
        live = payment_answer(definition, self._payment_options) if definition else None
        composed = {live.node_id: live.text} if live is not None and live.auto_composed else {}
        self.answers = answers_view(annotated, len(self.catalog), composed=composed)
        if self.answer_open >= self.answers.count:
            self.answer_open = -1
            self.answer_confirm_remove = False
        gaps = (
            definition_gaps(definition, payments_offered=offered) if definition is not None else []
        )
        self.gap_count = len(gaps)
        leaves = True
        if gaps:
            stripped = validate_form(answers_without_gaps(annotated, keep=composed)).definition
            leaves = stripped is None or bool(definition_gaps(stripped, payments_offered=offered))
        self.publish_gaps = publish_gaps(annotated, gaps, strip_leaves_gaps=leaves)
        self._refresh_import()

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
        self.guided_step = 1
        self.answer_open = self.limit_notice = -1
        self.answer_confirm_remove = self.add_open = False
        self._guided_started_at = time.time()
        self._guided_used_advanced = self.advanced_open
        self._drop_all_suggestions()
        self._drop_import()
        self._restore_flow_step()

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
        self.flow_ready = False
        self.resume_pending = False
        self.publish_confirm_open = False
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
        self.catalog = []
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
        self.answers = EMPTY_ANSWERS
        self.gap_count = 0
        self.publish_gaps = NO_PUBLISH_GAPS
        self.answer_open = self.limit_notice = -1
        self.answer_confirm_remove = self.add_open = False
        self.strip_confirm_open = False
        self._drop_all_suggestions()
        self._drop_import()
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
            notice_show = await asyncio.to_thread(_notice_show_for, tenant_id, scope.brand_id)
            options = await asyncio.to_thread(_payment_options, tenant_id, scope.brand_id)
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
                "business_name": scope.business_name,
            }
            self._catalog = _catalog_rows(catalog)
            self.catalog = catalog_rows(catalog)
            self.catalog_text = catalog_note(len(catalog), scope.brand_name)
            self._notice_show = notice_show
            self._payment_options = list(options) if options is not None else []
            self.payments_offered = len(options) if options is not None else -1
            await self._count_uncategorized()
            if self.nodes:  # «Ver menú y pedir» says whether the catalog is empty
                self._apply(self._form(), edited=False)
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
            params = self._flow_params()
            requested_menu = uuid_param(params, "objeto")
            if flow_param(params, "menu", GUIDED_STEPS) and requested_menu in {
                m.menu_id for m in menus
            }:
                target = requested_menu if requested_menu != self.menu.menu_id else ""
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
            address = await self._profile_address()
        if tenant_id is None:
            async with self:
                self.creating = False
                self.new_error = _NO_SESSION
            return
        try:
            user_id = await asyncio.to_thread(user_id_for, tenant_id, email)
            facts = StarterFacts(business_name=scope.business_name, address=address)
            if template == TEMPLATE_FAST_FOOD:
                try:
                    facts = await asyncio.to_thread(
                        starter_facts, tenant_id, scope, address=address
                    )
                except SQLAlchemyError as exc:  # «Tu marca» unreadable: start with less
                    logger.warning("whatsapp menu starter facts failed: %s", type(exc).__name__)
            detail = await asyncio.to_thread(
                create_menu, tenant_id, scope, name, template, facts=facts, user_id=user_id
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
            if template == TEMPLATE_FAST_FOOD:
                # The optional step at creation: «¿Tienes tu menú en una foto o en tu
                # página?», with «Ahora no» as the way past it — never a blocker.
                self.import_phase = IMPORT_CHOOSE
                self.import_offer = True

    # ==================================================================================
    # Entry section
    # ==================================================================================

    @rx.event
    def set_welcome(self, value: str) -> None:
        self.welcome = value
        self._apply(self._form())
        self._drop_suggestion(SUGGEST_GREETING)

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
        title = KIND_LABELS[kind]
        node = new_node(kind, fresh_node_id(form, title), title)
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
        nodes = list(form.nodes)
        nodes[index] = replace(nodes[index], **{field: value})
        self._apply(replace(form, nodes=nodes))

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
    # The menu in four steps (m-24848536)
    # ==================================================================================

    def _flow_params(self) -> dict:
        try:
            return self.router.url.query_parameters
        except Exception:  # noqa: BLE001 — no router in offline tests
            return {}

    def _restore_flow_step(self) -> None:
        old = self.guided_step
        params = self._flow_params()
        wanted = uuid_param(params, "objeto")
        if wanted and wanted != self.menu.menu_id:
            return
        requested = flow_param(params, "menu", GUIDED_STEPS)
        if requested:
            g = self.guided
            self.guided_step = (
                requested
                if self.resume_pending
                else guard_step(
                    requested,
                    [
                        bool(g.greeting.strip()) and not g.greeting_issue,
                        not g.buttons_issue,
                        not g.products_issue,
                        True,
                    ],
                )
            )
            self.resume_pending = False
            self.advanced_open = False
        elif not params.get("flujo"):
            self.guided_step = 1
        self.guided_direction = step_direction(old, self.guided_step, self.guided_direction)
        self.flow_ready = bool(requested) and self.has_menu

    @rx.event
    def restore_flow(self) -> rx.event.EventSpec | None:
        """Restore only a loaded number's menu; never save or publish from history."""
        params = self._flow_params()
        wanted = uuid_param(params, "objeto")
        if flow_param(params, "menu", GUIDED_STEPS) and wanted:
            if wanted not in {menu.menu_id for menu in self.menus}:
                self.flow_ready = False
                return None
            if wanted != self.menu.menu_id:
                return WhatsAppMenuState.open_menu(wanted)
        old = self.guided_step
        self._restore_flow_step()
        return self._guided_settle() if self.guided_step != old else None

    @rx.var
    def resume_href(self) -> str:
        return with_query(
            "/whatsapp",
            tab="menu",
            cuenta=self.loaded_for,
            flujo="menu",
            paso=str(self.guided_step),
            objeto=self.menu.menu_id,
        )

    @rx.event
    def guided_go(self, step: int) -> rx.event.EventSpec | None:
        if self.saving or self.publishing:
            return None
        if isinstance(step, int) and 1 <= step <= GUIDED_STEPS:
            self.guided_direction = step_direction(self.guided_step, step, self.guided_direction)
            self.guided_step = step
            self.flow_ready = True
            return self._guided_settle()
        return None

    def _guided_settle(self) -> rx.event.EventSpec:
        # Animate the existing panel, never key/remount the native editor or preview.
        return rx.call_script(
            step_settle_script()
            + "window.requestAnimationFrame(() => window.requestAnimationFrame(() => {"
            "if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;"
            "const panel=document.querySelector('.q-menu-guided-panel');if(!panel)return;"
            "const style=getComputedStyle(panel);"
            "const raw=style.getPropertyValue('--q-dur-slow').trim();"
            "const duration=(parseFloat(raw)||380)*(raw.endsWith('ms')?1:raw.endsWith('s')?1000:1);"
            "const x=panel.dataset.dir==='back'?-8:8;"
            "panel.getAnimations().forEach(a=>a.cancel());"
            "panel.animate([{transform:'translateX('+x+'px)'},{transform:'none'}],"
            "{duration,"
            "easing:style.getPropertyValue('--q-ease').trim()||'ease',fill:'both'});"
            "}));"
        )

    @rx.event
    def guided_next(self) -> rx.event.EventSpec | None:
        return self.guided_go(min(GUIDED_STEPS, self.guided_step + 1))

    @rx.event
    def guided_back(self) -> rx.event.EventSpec | None:
        return self.guided_go(max(1, self.guided_step - 1))

    @rx.event
    def set_publish_confirm_open(self, value: bool) -> None:
        self.publish_confirm_open = bool(value) and self.can_publish

    @rx.event
    def guided_primary(self) -> rx.event.EventSpec | None:
        if self.guided_step < GUIDED_STEPS:
            return self.guided_next()
        self.set_publish_confirm_open(True)
        return None

    @rx.event
    def save_for_later(self) -> rx.event.EventSpec | None:
        """Keep the session draft, including incomplete answers, without publishing."""
        if self.saving or self.publishing:
            return None
        self.resume_pending = True
        self.flow_ready = False
        self.publish_confirm_open = False
        return rx.redirect("/")

    @rx.event
    def leave_guided(self) -> rx.event.EventSpec | None:
        if self.saving or self.publishing:
            return None
        self.flow_ready = False
        self.publish_confirm_open = False
        return rx.redirect("/whatsapp?tab=chats")

    @rx.event
    def set_advanced(self, value: bool) -> None:
        """«Más opciones (avanzado)» ↔ «Volver a los 4 pasos»: same form, other view."""
        self.advanced_open = bool(value)
        if self.advanced_open:
            self._guided_used_advanced = True

    @rx.event
    def set_guided_greeting(self, value: str) -> None:
        if isinstance(value, str):
            self._apply(guided_set_greeting(self._form(), value))
            self._drop_suggestion(SUGGEST_GREETING)  # §5: «Deshacer» lasts until they type

    @rx.event
    def set_guided_question(self, value: str) -> None:
        if isinstance(value, str):
            self._apply(guided_set_question(self._form(), value))

    @rx.event
    def set_guided_button_label(self, button: int, value: str) -> None:
        if isinstance(button, int) and isinstance(value, str):
            self._apply(guided_set_button_label(self._form(), button, value))

    @rx.event
    def set_guided_button_action(self, button: int, action: str) -> None:
        if isinstance(button, int) and isinstance(action, str):
            self._apply(guided_set_button_action(self._form(), button, action))

    @rx.event
    def set_guided_button_text(self, button: int, value: str) -> None:
        if isinstance(button, int) and isinstance(value, str):
            self._apply(guided_set_button_text(self._form(), button, value))

    @rx.event
    def add_guided_button(self) -> None:
        self._apply(guided_add_button(self._form()))

    @rx.event
    def remove_guided_button(self, button: int) -> None:
        if isinstance(button, int):
            self._apply(guided_remove_button(self._form(), button))

    @rx.event
    def use_guided_buttons(self) -> None:
        self._apply(guided_use_buttons(self._form()))

    @rx.event
    def set_guided_products_intro(self, value: str) -> None:
        if isinstance(value, str):
            self._apply(guided_set_products_intro(self._form(), value))

    @rx.event
    def set_guided_address(self, choice: str) -> None:
        if isinstance(choice, str):
            self._apply(guided_set_address(self._form(), choice))

    @rx.event
    def set_guided_address_prompt(self, value: str) -> None:
        if isinstance(value, str):
            self._apply(guided_set_address_prompt(self._form(), value))

    # -- step 2: the answers (m-24936836) -------------------------------------------------

    def _answer_index(self, index: int) -> bool:
        return isinstance(index, int) and 0 <= index < self.answers.count

    @rx.event
    def open_answer_panel(self, index: int) -> None:
        if self._answer_index(index):
            self.answer_open = index
            self.answer_from_gaps = False
            self.answer_confirm_remove = False
            self.limit_notice = -1
            self.answer_suggest = NO_SUGGESTION

    @rx.event
    def close_answer_panel(self) -> None:
        """«Listo» / «Volver a tus respuestas»: what was typed is already in the menu."""
        self._drop_answer_suggestions()
        self.answer_open = -1
        self.answer_from_gaps = False
        self.answer_confirm_remove = False

    @rx.event
    def set_answer_panel_open(self, value: bool) -> None:
        if not value:
            self.close_answer_panel()

    @rx.event
    def set_answer_label(self, value: str) -> None:
        if isinstance(value, str) and self._answer_index(self.answer_open):
            self._apply(answer_set_label(self._form(), self.answer_open, value))

    @rx.event
    def set_answer_text(self, value: str) -> None:
        if isinstance(value, str) and self._answer_index(self.answer_open):
            key = self._answer_key(self.answer_open)
            self._apply(answer_set_text(self._form(), self.answer_open, value))
            self._drop_suggestion(key)

    # -- «Mejorar mi texto» / «Escribirlo por mí» (m-24936838) -----------------------------
    # Assisted, never autonomous: the proposal only replaces the field on screen; it is
    # saved or published by the owner's own «Guardar» / «Publicar», like anything typed.

    def _answer_key(self, index: int) -> str:
        answers = read_answers(self._form())
        return f"{SUGGEST_ANSWER}:{answers[index].option_id}" if 0 <= index < len(answers) else ""

    def _drop_suggestion(self, key: str) -> None:
        if not key:
            return
        self._suggest_undo = {k: v for k, v in self._suggest_undo.items() if k != key}
        self._suggest_last = {k: v for k, v in self._suggest_last.items() if k != key}
        if key == SUGGEST_GREETING:
            self.greeting_suggest = NO_SUGGESTION
        else:
            self.answer_suggest = NO_SUGGESTION

    def _drop_answer_suggestions(self) -> None:
        prefix = SUGGEST_ANSWER + ":"
        self._suggest_undo = {
            k: v for k, v in self._suggest_undo.items() if not k.startswith(prefix)
        }
        self._suggest_last = {
            k: v for k, v in self._suggest_last.items() if not k.startswith(prefix)
        }
        self.answer_suggest = NO_SUGGESTION

    def _drop_all_suggestions(self) -> None:
        self._suggest_undo = {}
        self._suggest_last = {}
        self.greeting_suggest = self.answer_suggest = NO_SUGGESTION
        self.suggest_notice = ""
        # `suggest_busy` stays: a call in flight still holds it until it settles (one
        # paid call at a time); its result is discarded by the epoch.
        self._suggest_epoch += 1

    def _settle(self, epoch: int) -> bool:
        """Free the one-at-a-time slot; True when the result still belongs on screen."""
        self.suggest_busy = ""
        self.suggest_writing = ""
        return epoch == self._suggest_epoch

    def _set_suggest_view(self, kind: str, view: SuggestVM) -> None:
        if kind == SUGGEST_GREETING:
            self.greeting_suggest = view
        else:
            self.answer_suggest = view

    def _field_now(self, kind: str, key: str) -> str | None:
        """The field's text now, or None when it is no longer on screen (another answer's
        panel, or the answer is gone)."""
        if kind == SUGGEST_GREETING:
            return self.welcome
        if not self._answer_index(self.answer_open) or self._answer_key(self.answer_open) != key:
            return None
        return self.open_answer.text

    def _put_field(self, kind: str, text: str) -> None:
        if kind == SUGGEST_GREETING:
            self._apply(guided_set_greeting(self._form(), text))
        else:
            self._apply(answer_set_text(self._form(), self.answer_open, text))

    async def _suggest(self, kind: str, *, again: bool) -> None:
        """Ask Claude for the field's text (`suggest_text`, seconds: off-thread) with only
        the facts on screen, and put the proposal in the field. The field is read-only
        while it writes; if it changed anyway (the advanced editor), the newer words win."""
        async with self:
            if self.suggest_busy:
                return
            scope = self._scope_value()
            if scope is None:
                return
            if kind == SUGGEST_GREETING:
                key, index, name, current = SUGGEST_GREETING, -1, "", self.welcome
            else:
                index = self.answer_open
                if not self._answer_index(index) or not self.open_answer.text_editable:
                    return
                key, name, current = (
                    self._answer_key(index),
                    self.open_answer.label.strip(),
                    self.open_answer.text,
                )
                if not name:
                    self.answer_suggest = replace(NO_SUGGESTION, error=_SUGGEST_NEEDS_NAME)
                    return
            previous = self._suggest_last.get(key, "") if again else ""
            if previous and previous != current:
                previous = ""
            answers = [*self.answers.buttons, *self.answers.rows]
            label = suggest_label(current)
            self._set_suggest_view(kind, NO_SUGGESTION)
            self.suggest_notice = ""
            self.suggest_busy = kind
            self.suggest_writing = suggest_writing_line()
            epoch = self._suggest_epoch
            _tenant, tenant_id, _email = await self._session()
            address = await self._profile_address()
        if tenant_id is None:
            async with self:
                if self._settle(epoch):
                    self._set_suggest_view(kind, replace(NO_SUGGESTION, error=_NO_SESSION))
            return
        try:
            known = await asyncio.to_thread(starter_facts, tenant_id, scope, address=address)
        except Exception as exc:  # noqa: BLE001 — «Tu marca» unreadable: write with less
            logger.warning("whatsapp suggestion facts failed: %s", type(exc).__name__)
            known = StarterFacts(business_name=scope.business_name, address=address)
        facts, others = suggest_context(known, answers, exclude_index=index)
        if not suggest_has_input(current, facts):
            async with self:
                if self._settle(epoch):
                    self._set_suggest_view(kind, replace(NO_SUGGESTION, error=SUGGEST_NO_DATA))
            return
        data = SuggestInput(
            kind=kind,
            answer_name=name,
            current_text=current,
            facts=facts,
            other_answers=others,
            previous_text=previous,
        )
        try:
            proposal: SuggestProposal = await asyncio.to_thread(
                suggest_text, tenant_id, scope.brand_id, data
            )
        except Exception as exc:  # noqa: BLE001 — no key, a refusal, the network: say so
            # Only the type: never the model's output nor the owner's text.
            logger.warning("whatsapp suggestion failed: %s", type(exc).__name__)
            async with self:
                if self._settle(epoch) and self._field_now(kind, key) is not None:
                    self._set_suggest_view(kind, replace(NO_SUGGESTION, error=SUGGEST_FAILED))
            return
        async with self:
            if not self._settle(epoch):
                return  # another menu, version or number is on screen now
            now = self._field_now(kind, key)
            if now is None:
                return  # the owner moved to another answer: nothing to put anywhere
            if now != current:
                stale = SUGGEST_STALE.format(label=label)
                self._set_suggest_view(kind, replace(NO_SUGGESTION, error=stale))
                return
            undo = dict(self._suggest_undo)
            undo.setdefault(key, current)  # «Otra versión» keeps the owner's own text
            self._suggest_undo = undo
            self._suggest_last = {**self._suggest_last, key: proposal.text}
            self._put_field(kind, proposal.text)
            self._set_suggest_view(
                kind,
                suggest_proposal_vm(proposal.missing, proposal.warnings, proposal.neutral_voice),
            )

    def _undo(self, kind: str) -> None:
        key = SUGGEST_GREETING if kind == SUGGEST_GREETING else self._answer_key(self.answer_open)
        if self.suggest_busy or not key or key not in self._suggest_undo:
            return
        before = self._suggest_undo[key]
        self._put_field(kind, before)
        self._drop_suggestion(key)

    @rx.event(background=True)
    async def suggest_greeting(self) -> None:
        """«Mejorar mi texto» / «Escribirlo por mí» on step 1's greeting."""
        await self._suggest(SUGGEST_GREETING, again=False)

    @rx.event(background=True)
    async def suggest_greeting_again(self) -> None:
        """«Otra versión»: a different proposal, with the same facts."""
        await self._suggest(SUGGEST_GREETING, again=True)

    @rx.event
    def undo_greeting_suggestion(self) -> None:
        self._undo(SUGGEST_GREETING)

    @rx.event(background=True)
    async def suggest_answer(self) -> None:
        """The same on the text of the answer whose panel is open (step 2)."""
        await self._suggest(SUGGEST_ANSWER, again=False)

    @rx.event(background=True)
    async def suggest_answer_again(self) -> None:
        await self._suggest(SUGGEST_ANSWER, again=True)

    @rx.event
    def undo_answer_suggestion(self) -> None:
        self._undo(SUGGEST_ANSWER)

    @rx.event
    def ask_remove_answer(self) -> None:
        self.answer_confirm_remove = self._answer_index(self.answer_open)

    @rx.event
    def keep_answer(self) -> None:
        self.answer_confirm_remove = False

    @rx.event
    def remove_answer(self) -> None:
        if self.answer_confirm_remove and self._answer_index(self.answer_open):
            index = self.answer_open
            self.answer_open = -1
            self.answer_confirm_remove = False
            self._apply(answers_remove(self._form(), index))

    @rx.event
    def move_answer(self, index: int, delta: int) -> None:
        """«Subir» / «Bajar». «Subir» on the first answer of «Más preguntas» explains the
        3-button limit instead of moving (never a silent block)."""
        if not self._answer_index(index) or delta not in (-1, 1):
            return
        if move_hits_button_limit(self.answers.count, index, delta):
            self.limit_notice = index
            return
        self.limit_notice = -1
        self._apply(answers_move(self._form(), index, delta))

    @rx.event
    def limit_move_down(self) -> None:
        """«Bajar «Horario»» from the limit message: the last button makes room."""
        index = self.limit_notice
        self.limit_notice = -1
        if self._answer_index(index) and index > 0:
            self._apply(answers_move(self._form(), index - 1, 1))

    @rx.event
    def dismiss_limit_notice(self) -> None:
        self.limit_notice = -1

    @rx.event
    def toggle_add_answer(self) -> None:
        self.add_open = not self.add_open and not self.answers.full

    @rx.event
    def add_answer(self, key: str) -> None:
        """A suggestion, «Ver menú y pedir» back, or «Escribir la mía»: then its panel."""
        if not isinstance(key, str) or self.answers.full:
            return
        form, index = answers_add(self._form(), key)
        if index < 0:
            return
        self.add_open = False
        self._apply(form)
        self.answer_open = index
        self.answer_confirm_remove = False

    # -- «Cargar desde una foto o mi página» (m-24936840) --------------------------------
    # Assisted, never autonomous: the read only PROPOSES; «Usar» puts one fact into the
    # form on screen (saved by the owner's own «Guardar» / «Publicar»). The only write is
    # «Agregar los marcados a Tus productos», and only on that button.

    def _discard_staged(self) -> None:
        path, self._import_staged = self._import_staged, ""
        if path:
            with contextlib.suppress(OSError):
                os.unlink(path)

    def _drop_import(self) -> None:
        """Close the import and forget its proposal. A read in flight keeps the slot
        (`suggest_busy`) until it settles; its result is discarded by the epoch."""
        self.import_phase = ""
        self.import_offer = False
        self.import_kind = ""
        self.import_url_error = self.import_error = self.import_add_error = ""
        self.import_slow = False
        self.import_review = EMPTY_IMPORT
        self.import_editing = -1
        self.import_category_editing = -1
        self._import_facts = []
        self._import_products = []
        self._import_warnings = []
        self._import_label = ""
        self._import_added = []
        self._import_currency = ""
        self._import_epoch += 1
        if not self.import_adding:
            self._discard_staged()

    def _refresh_import(self) -> None:
        """The review re-read off the form: each preview is the answer's text after «Usar»."""
        if self.import_phase != IMPORT_REVIEW:
            return
        self.import_review = import_view(
            self._form(),
            kind=self.import_kind,
            label=self._import_label,
            warnings=self._import_warnings,
            facts=self._import_facts,
            products=self._import_products,
            catalog=self._catalog,
            editing=self.import_editing,
            added=self._import_added,
            own_currency=self._import_currency,
            category_editing=self.import_category_editing,
        )

    @rx.event
    def open_import(self) -> None:
        """«Cargar desde una foto o mi página» (step 2): the same chooser, any time."""
        if not self.has_menu:
            return
        self._drop_import()
        self.import_phase = IMPORT_CHOOSE

    @rx.event
    def close_import(self) -> None:
        """«Ahora no», «Cancelar», «Seguir sin la foto», «Volver a tus respuestas»: the menu
        keeps only what was already used."""
        self._drop_import()

    @rx.event
    def finish_import(self) -> rx.event.EventSpec | None:
        """«Volver a tus respuestas» from the review: step 2, where the used facts now
        read in their answers."""
        self._drop_import()
        if not self.advanced_open and self.guided_step != 2:
            return self.guided_go(2)
        return None

    @rx.event
    def import_file_rejected(self, rejected: list[dict[str, Any]]) -> None:
        """The picker refused the file (its type or its size) before it was sent."""
        if self.import_phase == IMPORT_PHOTO:
            self.import_kind, self.import_error = "image", IMPORT_REJECTED
            self.import_phase = IMPORT_FAILED_PHASE

    @rx.event
    def set_import_open(self, value: bool) -> None:
        """A tap outside or Escape. While reading or reviewing it is ignored — that work
        is lost only through the explicit «Cancelar» / «Volver a tus respuestas»."""
        if not value and self.import_phase not in (IMPORT_READING, IMPORT_REVIEW):
            self._drop_import()

    @rx.event
    def choose_import_source(self, source: str) -> None:
        if self.import_phase == IMPORT_CHOOSE and source in (IMPORT_PHOTO, IMPORT_PAGE):
            self.import_phase = source
            self.import_url_error = ""

    @rx.event
    def import_back(self) -> None:
        """«Atrás» from a source → the chooser; «Probar otra foto» from a failure → the
        same source again."""
        if self.import_phase in (IMPORT_PHOTO, IMPORT_PAGE):
            self.import_phase = IMPORT_CHOOSE
        elif self.import_phase in (IMPORT_FAILED_PHASE, IMPORT_EMPTY_PHASE):
            self.import_phase = IMPORT_PAGE if self.import_kind == "url" else IMPORT_PHOTO
            self.import_error = ""

    @rx.event
    def set_import_url(self, value: str) -> None:
        if isinstance(value, str):
            self.import_url = value[:2048]
            self.import_url_error = ""

    @rx.event
    async def handle_import_upload(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """FOREGROUND (uploads cannot be background handlers): park the bytes in a private
        temp file — never in the state, never in the served upload folder — then hand the
        reading to the background `read_import_file`."""
        if not files or self.suggest_busy or self.import_phase != IMPORT_PHOTO:
            return None
        upload = files[0]
        size = getattr(upload, "size", None)
        too_big = isinstance(size, int) and size > IMPORT_MAX_BYTES
        data = b""
        if not too_big:
            try:
                # The picker's 10 MB cap is the browser's; a crafted POST is cut here,
                # never read whole into memory.
                data = await upload.read(IMPORT_MAX_BYTES + 1)
            except Exception:  # noqa: BLE001 — any read failure is the same message
                self.import_kind, self.import_error = "image", IMPORT_UPLOAD_FAILED
                self.import_phase = IMPORT_FAILED_PHASE
                return None
        if too_big or len(data) > IMPORT_MAX_BYTES:
            self.import_kind, self.import_error = "image", IMPORT_TOO_BIG
            self.import_phase = IMPORT_FAILED_PHASE
            return None
        name = safe_upload_name(upload.name or "menu")
        self._discard_staged()
        handle, path = tempfile.mkstemp(prefix="qualify-menu-import-")
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        self._import_staged = path
        self._import_label = name
        self.import_kind = "pdf" if name.lower().endswith(".pdf") else "image"
        return WhatsAppMenuState.read_import_file()

    @rx.event(background=True)
    async def read_import_file(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            path, name = self._import_staged, self._import_label
            self._import_staged = ""
        if not path:
            return

        def load() -> ImportSource:
            try:
                with open(path, "rb") as staged:
                    return ImportSource(filename=name, data=staged.read())
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(path)

        try:
            shown = await self._run_import(load, IMPORT_PHOTO)
        finally:
            # `load` unlinks the file; when the read never started (cancelled, or the
            # slot was taken) nobody did.
            with contextlib.suppress(OSError):
                os.unlink(path)
        if shown:
            yield _focus_review()

    @rx.event(background=True)
    async def submit_import_url(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Leer mi página»."""
        async with self:
            url = self.import_url.strip()
            if self.import_phase == IMPORT_PAGE and not url:
                self.import_url_error = IMPORT_PAGE_NEEDS_LINK
                return
        if await self._run_import(lambda: ImportSource(url=url), IMPORT_PAGE):
            yield _focus_review()

    async def _run_import(self, load: Any, phase: str) -> bool:
        """Read the source off-thread (`import_menu_facts`, seconds and paid) under the
        one-at-a-time slot, then show the review — or the reason it could not. True when
        the review is on screen."""
        async with self:
            if self.suggest_busy or self.import_phase != phase:
                return False
            self.suggest_busy = SUGGEST_IMPORT
            self.import_phase = IMPORT_READING
            self.import_slow = False
            self.import_error = ""
            if phase == IMPORT_PAGE:
                self.import_kind = "url"
            elif self.import_kind not in ("image", "pdf"):
                self.import_kind = "image"
            epoch, ticket = self._suggest_epoch, self._import_epoch
            _tenant, tenant_id, _email = await self._session()

        def read() -> tuple[ImportProposal, str]:
            proposal = import_menu_facts(load())
            # A price without its currency (a bare «$») is saved in the business's own:
            # the review says so before anything is added (tenant door, under RLS).
            own = ""
            bare = any(
                p.price_amount is not None and not p.price_currency for p in proposal.products
            )
            if bare and tenant_id is not None:
                try:
                    own = business_currency(tenant_id)
                except Exception as exc:  # noqa: BLE001 — show the amount alone
                    logger.warning("whatsapp menu import currency: %s", type(exc).__name__)
            return proposal, own

        def current() -> bool:
            return epoch == self._suggest_epoch and ticket == self._import_epoch

        task = asyncio.ensure_future(asyncio.to_thread(read))
        done, _pending = await asyncio.wait({task}, timeout=IMPORT_SLOW_AFTER)
        if not done:
            async with self:
                if current():
                    self.import_slow = True
        error, empty = "", False
        proposal: ImportProposal | None = None
        own_currency = ""
        try:
            proposal, own_currency = await task
        except SourceUnsupported as exc:
            error = str(exc) or IMPORT_FAILED  # a Spanish reason for the owner
        except NothingFound:
            empty = True
        except Exception as exc:  # noqa: BLE001 — no key, a refusal, the network, the budget
            # Only the type: never the model's output nor the owner's file.
            logger.warning("whatsapp menu import failed: %s", type(exc).__name__)
            error = IMPORT_FAILED
        async with self:
            still = self._settle(epoch) and ticket == self._import_epoch
            if not still:
                return False  # cancelled, or another menu / version / number is on screen
            self.import_slow = False
            if proposal is None:
                self.import_phase = IMPORT_EMPTY_PHASE if empty else IMPORT_FAILED_PHASE
                self.import_error = import_empty_text(self.import_kind) if empty else error
                return False
            self._import_currency = own_currency
            self.import_kind = proposal.source_kind
            self._import_label = proposal.source_label
            self._import_warnings = list(proposal.warnings)
            self._import_facts = fact_rows(proposal.facts)
            self._import_products = product_rows(proposal.products)
            self._import_added = []
            self.import_editing = -1
            self.import_category_editing = -1
            self.import_phase = IMPORT_REVIEW
            self._refresh_import()
        return True

    def _import_fact(self, index: int) -> dict[str, str] | None:
        if self.import_phase != IMPORT_REVIEW or not isinstance(index, int):
            return None
        return self._import_facts[index] if 0 <= index < len(self._import_facts) else None

    def _set_fact(self, index: int, **changes: str) -> None:
        facts = [dict(f) for f in self._import_facts]
        facts[index].update(changes)
        self._import_facts = facts

    @rx.event
    def use_import_fact(self, index: int) -> None:
        """«Usar»: the fact fills its answer's gap(s) on screen (a removed answer comes
        back with it). Nothing is saved until «Guardar» / «Publicar»."""
        fact = self._import_fact(index)
        if fact is None or fact["status"] != FACT_PENDING:
            return
        form = self._form()
        if row_kind(fact) == FACT_SENTENCE:
            # «Usar como texto de la respuesta»: the sentences (zone and cost together)
            # become the answer's whole text; never pasted into a gap (m-24945867).
            rows = self._import_facts
            group = sentence_group(rows, index, self.import_editing)
            if group_plan(form, rows, group).mode == "none":
                return
            updated = apply_sentences(form, rows, group)
        else:
            if fact_plan(form, fact["key"], fact["value"]).mode == "none":
                return
            group = [index]
            updated = apply_fact(form, fact["key"], fact["value"])
        for i in group:
            self._set_fact(i, status=FACT_USED)
        self.import_editing = -1
        self._drop_answer_suggestions()
        self._apply(updated)

    @rx.event
    def skip_import_fact(self, index: int) -> None:
        """«No usar»: the answer stays as it was."""
        fact = self._import_fact(index)
        if fact is not None and fact["status"] == FACT_PENDING:
            group = sentence_group(self._import_facts, index, self.import_editing) or [index]
            for i in group:
                self._set_fact(i, status=FACT_SKIPPED)
            self.import_editing = -1
            self._refresh_import()

    @rx.event
    def edit_import_fact(self, index: int) -> None:
        fact = self._import_fact(index)
        if fact is not None and fact["status"] == FACT_PENDING:
            self.import_editing = -1 if self.import_editing == index else index
            self._refresh_import()

    @rx.event
    def set_import_fact_value(self, value: str) -> None:
        fact = self._import_fact(self.import_editing)
        if fact is not None and isinstance(value, str) and fact["status"] == FACT_PENDING:
            value = value[:200]
            # The owner's own text: a sentence shortened into a value fills its gap.
            kind = edited_kind(fact["key"], value)
            self._set_fact(self.import_editing, value=value, kind=kind)
            self._refresh_import()

    @rx.event
    def toggle_import_product(self, index: int, checked: bool) -> None:
        if self.import_phase != IMPORT_REVIEW or not isinstance(index, int):
            return
        if 0 <= index < len(self._import_products):
            rows = [dict(p) for p in self._import_products]
            rows[index]["checked"] = "1" if checked else ""
            self._import_products = rows
            self._refresh_import()

    # m-24955838: the category each new product will get, editable before adding

    @rx.event
    def edit_import_category(self, index: int) -> None:
        if self.import_phase != IMPORT_REVIEW or not isinstance(index, int):
            return
        if 0 <= index < len(self._import_products):
            self.import_category_editing = index
            self.import_category_text = self._import_products[index].get("category", "")
            self.import_category_error = ""
            self._refresh_import()

    @rx.event
    def set_import_category_text(self, value: str) -> None:
        self.import_category_text = value
        self.import_category_error = ""

    @rx.var
    def import_category_choices(self) -> list[str]:
        """The brand's categories and the ones already proposed in this review, one
        spelling each: tapping one avoids a typo twin («Bebida» next to «Bebidas»)."""
        seen: dict[str, str] = {}
        for raw in [
            *(str(r.get("category") or "") for r in self._catalog),
            *(str(p.get("category") or "") for p in self._import_products),
        ]:
            name = " ".join(raw.split())
            if name and not is_uncategorized(name):
                seen.setdefault(category_key(name), name)
        return list(seen.values())

    @rx.var
    def import_category_count(self) -> str:
        return name_counter(self.import_category_text)

    @rx.event
    def pick_import_category(self, name: str) -> None:
        self.import_category_text = name
        self.import_category_error = ""

    @rx.event
    def import_category_key(self, key: str) -> None:
        """Enter saves the field."""
        if key == "Enter":
            self.save_import_category()

    @rx.event
    def cancel_import_category(self) -> None:
        self.import_category_editing = -1
        self.import_category_error = ""
        self._refresh_import()

    @rx.event
    def save_import_category(self) -> None:
        """Nothing is written here: the category travels with the product and is
        created only by «Agregar los marcados a Tus productos». Empty = «Otros»."""
        index = self.import_category_editing
        if self.import_phase != IMPORT_REVIEW or not 0 <= index < len(self._import_products):
            return
        text = " ".join(self.import_category_text.split())
        if len(text) > NAME_MAX:
            self.import_category_error = NAME_TOO_LONG
            return
        known = [str(r.get("category") or "") for r in self._catalog if r.get("category")]
        known += [str(p.get("category") or "") for p in self._import_products]
        rows = [dict(p) for p in self._import_products]
        rows[index]["category"] = existing_spelling(text, known) if text else ""
        self._import_products = rows
        self.import_category_editing = -1
        self._refresh_import()

    @rx.event
    def set_all_import_products(self, checked: bool) -> None:
        """«Marcar todos» / «Desmarcar todos» over the new products."""
        if self.import_phase != IMPORT_REVIEW:
            return
        new = {p.index for p in self.import_review.new_products}
        self._import_products = [
            {**p, "checked": ("1" if checked else "")} if i in new else dict(p)
            for i, p in enumerate(self._import_products)
        ]
        self._refresh_import()

    @rx.event(background=True)
    async def add_import_products(self) -> None:
        """«Agregar los marcados a Tus productos» — the flow's only write, and only here.
        Through the catalog service (`tenant_session`); a name already in the catalog is
        not created and no price there is changed."""
        async with self:
            if self.import_adding or self.import_phase != IMPORT_REVIEW:
                return
            scope = self._scope_value()
            if scope is None:
                return
            if scope.brand_id is None:
                self.import_add_error = IMPORT_ADD_NEEDS_BRAND
                return
            new = {p.index for p in self.import_review.new_products if p.checked}
            picked = [
                FoundProduct(
                    name=p["name"],
                    price_amount=Decimal(p["amount"]) if p["amount"] else None,
                    price_currency=p["currency"],
                    description=p["description"],
                    evidence=p["evidence"],
                    category=p.get("category", ""),
                )
                for i, p in enumerate(self._import_products)
                if i in new
            ]
            if not picked:
                return
            self.import_adding = True
            self.import_add_error = ""
            currency = self._import_currency
            ticket = self._import_epoch
            connection_id = await self._connection_id()
            _tenant, tenant_id, email = await self._session()
        if tenant_id is None:
            async with self:
                self.import_adding = False
                self.import_add_error = _NO_SESSION
            return
        try:
            user_id = await asyncio.to_thread(user_id_for, tenant_id, email)
            result: AddedProducts = await asyncio.to_thread(
                partial(
                    add_catalog_products,
                    tenant_id,
                    scope.brand_id,
                    picked,
                    user_id,
                    currency=currency,  # "" = no fallback: saved as shown
                )
            )
            catalog = await asyncio.to_thread(preview_catalog, tenant_id, scope.brand_id)
            notice_show = await asyncio.to_thread(_notice_show_for, tenant_id, scope.brand_id)
            options = await asyncio.to_thread(_payment_options, tenant_id, scope.brand_id)
        except Exception as exc:  # noqa: BLE001 — the database: say so, keep the ticks
            logger.error("whatsapp menu import products failed: %s", type(exc).__name__)
            async with self:
                self.import_adding = False
                if ticket == self._import_epoch:
                    self.import_add_error = IMPORT_ADD_FAILED
            return
        async with self:
            self.import_adding = False
            if await self._connection_id() != connection_id:
                return
            self._catalog = _catalog_rows(catalog)
            self.catalog = catalog_rows(catalog)
            self.catalog_text = catalog_note(len(catalog), scope.brand_name)
            self._notice_show = notice_show
            self._payment_options = list(options) if options is not None else []
            self.payments_offered = len(options) if options is not None else -1
            await self._count_uncategorized()
            if ticket == self._import_epoch:
                self._import_added = added_lines(result.added, result.existing, result.failed)
            self._apply(self._form(), edited=False)  # «Ver menú y pedir» sees the products

    @rx.event
    def complete_gaps(self) -> list[rx.event.EventSpec] | None:
        """Step 4 «Completarlas»: back to step 2 with the first answer that has a gap open,
        its text focused on that gap (m-24945866) — not just the list."""
        settle = self.guided_go(2)
        if settle is None:
            return None
        index = self.publish_gaps.first_index
        if not self._answer_index(index):
            return [settle]
        self.open_answer_panel(index)
        if not self.open_answer.text_editable:
            return [settle]
        self.answer_from_gaps = True
        return [settle, _focus_first_gap(first_gap_literal(self.open_answer.text))]

    @rx.event
    def strip_gaps_and_publish(self) -> None:
        """«Quitar las que faltan y publicar»: first a confirmation that names what goes;
        nothing is removed until the owner says yes."""
        if self.saving or self.publishing or not self.publish_gaps.can_strip:
            return
        self.strip_confirm_open = True

    @rx.event
    def set_strip_confirm_open(self, value: bool) -> None:
        self.strip_confirm_open = bool(value) and self.publish_gaps.can_strip

    @rx.event
    def confirm_strip_and_publish(self) -> rx.event.EventSpec | None:
        """«Sí, publicar sin ellas»: the answers with a gap go, then the publish."""
        if not self.strip_confirm_open or self.saving or self.publishing:
            return None
        self.strip_confirm_open = False
        if not self.publish_gaps.can_strip:
            return None
        self._apply(answers_without_gaps(self._form(), keep=self._live_payment_nodes()))
        return WhatsAppMenuState.publish_current if self.can_publish else None

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
        await self._save_now()

    @rx.event(background=True)
    async def save_and_open_catalog(self) -> AsyncIterator[rx.event.EventSpec]:
        """Step 3's way to Catálogo: save what was typed first (guide N6), then go. With
        something to fix nothing is saved and the owner stays — the screen says why."""
        async with self:
            if self.dirty and self.error_count > 0:
                self.banner, self.banner_tone = CATALOG_FIX_FIRST, "warn"
                return
            needs_save = self.dirty
        if needs_save and not await self._save_now():
            return
        yield rx.redirect("/catalog")

    @rx.event(background=True)
    async def save_and_open_payments(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Agregar formas de pago» (m-24955648, spec §6a): save first, then go to
        WhatsApp → Tu número → Formas de pago."""
        async with self:
            if self.dirty and self.error_count > 0:
                self.banner, self.banner_tone = CATALOG_FIX_FIRST, "warn"
                return
            needs_save = self.dirty
        if needs_save and not await self._save_now():
            return
        yield rx.redirect(PAYMENTS_HREF)

    @rx.event(background=True)
    async def save_and_open_group(self) -> AsyncIterator[rx.event.EventSpec]:
        """Step 3's «Agruparlos» (m-24955838): save first, then Catálogo opens
        «Agrupa tus productos» with the way back here."""
        async with self:
            if self.dirty and self.error_count > 0:
                self.banner, self.banner_tone = CATALOG_FIX_FIRST, "warn"
                return
            needs_save = self.dirty
            back = self.resume_href
        if needs_save and not await self._save_now():
            return
        yield rx.redirect(group_href(back))

    @rx.event(background=True)
    async def save_and_open_order(self) -> AsyncIterator[rx.event.EventSpec]:
        """Step 3's «Cambiar el orden» (m-24955643): like `save_and_open_catalog`, but
        Catálogo opens in «Ordenar tu menú» with «Volver a tu menú de WhatsApp» (N7)."""
        async with self:
            if self.dirty and self.error_count > 0:
                self.banner, self.banner_tone = CATALOG_FIX_FIRST, "warn"
                return
            needs_save = self.dirty
            back = self.resume_href
        if needs_save and not await self._save_now():
            return
        yield rx.redirect(order_href(back))

    @rx.event(background=True)
    async def save_and_open_brand(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Ir a Tu marca» (m-24936838, a proposal in the neutral voice): like the way to
        Catálogo, what is on screen — the proposal included — is saved first so nothing is
        lost on the way; the neutral-voice hint says so (UX review U1: save and say so)."""
        async with self:
            if self.dirty and self.error_count > 0:
                # Shown next to the button (it may sit inside the answer's panel, which
                # covers the page banner).
                self.suggest_notice = CATALOG_FIX_FIRST
                return
            self.suggest_notice = ""
            needs_save = self.dirty
        if needs_save and not await self._save_now():
            return
        yield rx.redirect("/brand")

    async def _save_now(self) -> bool:
        """Save the editor as the menu's next version; True when it is on disk."""
        async with self:
            if not self.can_save or self.publishing:
                return False
            scope = self._scope_value()
            if scope is None:
                return False
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
            return False
        detail = await self._save_outside_lock(tenant_id, scope, menu_id, payload)
        if detail is None:
            return False
        async with self:
            label = detail.versions[0].label.lower() if detail.versions else ""
            number = label.removeprefix("versión ").strip()
            self.banner, self.banner_tone = _SAVED.format(n=number), "ok"
        return True

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
        except MenuHasGaps:
            async with self:
                self.publishing = False
                self.banner, self.banner_tone = _PUBLISH_GAPS, "warn"
            return
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
            # A clean publish says «listo» right where the owner tapped (the toolbar)
            # with the next step (the QR); a partial failure shows only its banner — what
            # to fix comes before what to do next.
            self.just_published = outcome.graph_ok
            if not outcome.graph_ok:
                self.banner, self.banner_tone = outcome.notice, outcome.tone
            if self._guided_started_at:
                # m-24848536: how long an owner takes from opening the menu to publishing
                # it (goal ≤ 5 min from the template; measured, never enforced).
                logger.info(
                    "whatsapp_menu_guided_publish seconds=%d advanced=%s",
                    int(time.time() - self._guided_started_at),
                    self._guided_used_advanced,
                )
                self._guided_started_at = 0.0
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
            payment_methods=tuple(self._payment_options),
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
