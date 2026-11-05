"""View-models and pure logic for the `/whatsapp` → Menú tab (WA-16).

Three jobs, all pure (no Reflex, no network, no database — the unit tests import this
module directly, `test_whatsapp_menu_editor.py`):

1. **The editor form.** A `MenuDefinition` (WA-14, `qualify_api.whatsapp.menus.schema`)
   is a nested, discriminated structure; Reflex edits flat, typed lists far better. So the
   form is a set of frozen dataclasses (`MenuForm` → `NodeForm` → `OptionForm`, plus the
   entry rows) that carry plain strings, and two functions convert both ways:
   `definition_to_form` and `form_to_payload`. A list node's sections are flattened into
   rows with a `section` title each; consecutive rows with the same title are one section
   again on the way back, so a round trip is exact.
2. **Validation in Spanish, next to the field.** `validate_form` runs
   `MenuDefinition.model_validate` — the schema stays the ONE authority on Meta's limits
   and the menu's structure — and translates every pydantic error into Spanish copy
   attached to the offending row/field (`errors` dicts on the form items). A few checks
   the flat form introduces itself (a step id used twice, a «siguiente» pointing at a
   step that no longer exists) run first, because pydantic's structural validator only
   runs once every field is valid, and an editor needs the message where the problem is.
3. **The phone preview and the version/menu lists.** `preview_turn` runs `engine.step`
   and turns its actions into chat bubbles; menus and versions become display-ready VMs
   with pre-formatted dates.

Security boundary, same as `whatsapp_vm.py`: every VM is frozen and none has a field
that could carry a token or a credential (`test_whatsapp_menu_vm_has_no_credential_fields`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from pydantic import ValidationError
from qualify_api.catalog.order import category_key, category_label
from qualify_api.whatsapp.menus.engine import (
    CatalogItem,
    Handoff,
    Inbound,
    OutboundAction,
    SendButtons,
    SendList,
    SendText,
    ThreadMenuState,
    format_money,
    order_total,
    step,
)
from qualify_api.whatsapp.menus.ids import new_node_id, new_option_id
from qualify_api.whatsapp.menus.import_ai import MAX_UPLOAD_BYTES, REASON_TOO_BIG, fact_kind
from qualify_api.whatsapp.menus.schema import (
    MAX_BUTTONS,
    MAX_COMMANDS,
    MAX_ICE_BREAKERS,
    MAX_LIST_ROWS,
    MAX_LIST_SECTIONS,
    ButtonsNode,
    CollectNode,
    HandoffNode,
    ListNode,
    MenuDefinition,
    OrderSummaryNode,
    ProductsNode,
    TextNode,
    normalize_keyword,
)
from qualify_api.whatsapp.menus.starter import (
    ANSWER_LABEL_MAX,
    BUTTONS_WITH_MORE,
    ENTRY_SHORTCUTS,
    MAX_ANSWERS,
    MORE_BODY,
    MORE_BUTTON,
    MORE_LABEL,
    MORE_NODE_ID,
    MORE_OPTION_ID,
    MORE_SECTION,
    STARTER_ANSWERS,
    SUGGESTED_TEXTS,
    Gap,
    StarterFacts,
    build_starter_menu,
    find_gaps,
)

from .catalog_group_vm import import_categories_line, import_category_label
from .connections_vm import WHATSAPP_RECONNECT_HINT
from .whatsapp_vm import format_timestamp

# --------------------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------------------

KIND_TEXT = "text"
KIND_BUTTONS = "buttons"
KIND_LIST = "list"
KIND_PRODUCTS = "products"
KIND_ORDER_SUMMARY = "order_summary"
KIND_COLLECT = "collect"
KIND_HANDOFF = "handoff"

# Order = the «Agregar paso» menu's order.
NODE_KINDS: tuple[tuple[str, str], ...] = (
    (KIND_BUTTONS, "Botones"),
    (KIND_LIST, "Lista de opciones"),
    (KIND_TEXT, "Texto"),
    (KIND_PRODUCTS, "Productos del catálogo"),
    (KIND_ORDER_SUMMARY, "Resumen del pedido"),
    (KIND_COLLECT, "Pregunta"),
    (KIND_HANDOFF, "Pasar a una persona"),
)
KIND_LABELS: dict[str, str] = dict(NODE_KINDS)
KIND_KEYS: frozenset[str] = frozenset(KIND_LABELS)

COLLECT_VALIDATIONS: tuple[tuple[str, str], ...] = (
    ("text", "Texto libre"),
    ("phone", "Teléfono"),
    ("yes_no", "Sí / No (botones)"),
)

# Radix selects cannot hold "" as an item value: «ninguno» travels as this sentinel.
NONE_VALUE: Final = "__none__"

TEMPLATE_EMPTY: Final = "empty"
TEMPLATE_FAST_FOOD: Final = "fast_food"

_NODE_ID_RE = re.compile(r"^[a-z0-9_][a-z0-9_\-]{0,63}$")

# Kind-specific defaults: what a new step (or a kind switch) starts with. They mirror the
# schema's own defaults, so a step the editor did not touch serializes to the same data.
_DEFAULT_LIST_BUTTON = "Ver opciones"
_DEFAULT_PRODUCTS_BUTTON = "Ver productos"
_DEFAULT_MORE_LABEL = "Ver más"
_DEFAULT_PAGE_SIZE = str(MAX_LIST_ROWS)
_DEFAULT_EMPTY_BODY = "Por ahora no tenemos productos disponibles."
_DEFAULT_CONFIRM = "Confirmar"
_DEFAULT_ADD_MORE = "Agregar más"
_DEFAULT_CANCEL = "Cancelar"
_DEFAULT_EMPTY_LINE = "(tu pedido está vacío)"
_DEFAULT_COLLECT_ERROR = "No pude entender tu respuesta."
_DEFAULT_YES = "Sí"
_DEFAULT_NO = "No"
_DEFAULT_REASON = "customer_request"
_DEFAULT_FIELD = "respuesta"

# What a question stores, in the owner's words (m-24848536: no «Se guarda como» with an
# identifier). The keys are the ones Chats already labels (`whatsapp_chats_vm.
# _COLLECTED_LABELS`); an older menu's own key still shows, humanized, in Chats.
COLLECT_FIELDS: tuple[tuple[str, str], ...] = (
    ("direccion", "Dirección"),
    ("barrio", "Barrio"),
    ("nombre", "Nombre"),
    ("telefono", "Teléfono"),
    ("metodo_pago", "Método de pago"),
    ("notas", "Notas"),
    (_DEFAULT_FIELD, "Otra respuesta"),
)

# Why a step hands the chat to a person — Chats shows it; the owner picks a phrase.
HANDOFF_REASONS: tuple[tuple[str, str], ...] = (
    ("customer_request", "El cliente pidió hablar con alguien"),
    ("order_confirmed", "El cliente confirmó un pedido"),
    ("unknown_input", "El menú no entendió al cliente"),
)
_DEFAULT_SECTION = "Opciones"


# --------------------------------------------------------------------------------------
# The form
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordForm:
    word: str
    node: str
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IceBreakerForm:
    text: str
    node: str
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandForm:
    name: str
    hint: str
    node: str
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OptionForm:
    """A reply button (buttons step) or a row (list step). `description` and `section`
    only mean something on a list row."""

    option_id: str
    label: str
    description: str
    next: str
    section: str
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeForm:
    """One step, every kind's fields side by side as strings so the editor can switch the
    kind without losing what was typed. `body` is the step's main text whatever the kind
    calls it (`prompt` on a question, `message` on a handoff)."""

    node_id: str
    kind: str
    title: str = ""  # the step's name (schema `title`); renaming edits only this
    body: str = ""
    header: str = ""
    footer: str = ""
    next: str = ""
    options: list[OptionForm] = field(default_factory=list)
    button_label: str = ""
    more_label: str = ""
    page_size: str = ""
    next_after_pick: str = ""
    empty_body: str = ""
    confirm_next: str = ""
    add_more_next: str = ""
    cancel_next: str = ""
    confirm_label: str = ""
    add_more_label: str = ""
    cancel_label: str = ""
    empty_line: str = ""
    field_name: str = ""
    validation: str = "text"
    error_message: str = ""
    yes_label: str = ""
    no_label: str = ""
    reason: str = ""
    errors: dict[str, str] = field(default_factory=dict)
    has_issue: bool = False
    kind_label: str = ""
    label: str = ""  # what the editor shows for the step (`node_label`), never the id
    unused: bool = False  # nothing leads here: not the entry, a button nor another step


@dataclass(frozen=True)
class MenuForm:
    welcome: str
    on_first_message: bool
    start_node: str
    fallback_node: str  # NONE_VALUE = the engine's built-in handoff text
    keywords: list[KeywordForm]
    ice_breakers: list[IceBreakerForm]
    commands: list[CommandForm]
    nodes: list[NodeForm]
    entry_errors: dict[str, str] = field(default_factory=dict)
    menu_errors: list[str] = field(default_factory=list)


def new_node(kind: str, node_id: str, title: str = "") -> NodeForm:
    """A fresh step of `kind` with the schema's defaults filled in."""
    return apply_kind_defaults(NodeForm(node_id=node_id, kind=kind, title=title))


def apply_kind_defaults(node: NodeForm) -> NodeForm:
    """Fill the empty kind-specific fields of `node` with defaults; keep what is typed."""

    def keep(value: str, default: str) -> str:
        return value if value.strip() else default

    kind = node.kind
    node = replace(node, kind_label=KIND_LABELS.get(kind, kind))
    if kind == KIND_LIST:
        return replace(node, button_label=keep(node.button_label, _DEFAULT_LIST_BUTTON))
    if kind == KIND_PRODUCTS:
        return replace(
            node,
            button_label=keep(node.button_label, _DEFAULT_PRODUCTS_BUTTON),
            more_label=keep(node.more_label, _DEFAULT_MORE_LABEL),
            page_size=keep(node.page_size, _DEFAULT_PAGE_SIZE),
            empty_body=keep(node.empty_body, _DEFAULT_EMPTY_BODY),
        )
    if kind == KIND_ORDER_SUMMARY:
        return replace(
            node,
            body=keep(node.body, "Total: {total}\n¿Confirmas tu pedido?"),
            confirm_label=keep(node.confirm_label, _DEFAULT_CONFIRM),
            add_more_label=keep(node.add_more_label, _DEFAULT_ADD_MORE),
            cancel_label=keep(node.cancel_label, _DEFAULT_CANCEL),
            empty_line=keep(node.empty_line, _DEFAULT_EMPTY_LINE),
        )
    if kind == KIND_COLLECT:
        return replace(
            node,
            validation=node.validation or "text",
            field_name=keep(node.field_name, _DEFAULT_FIELD),
            error_message=keep(node.error_message, _DEFAULT_COLLECT_ERROR),
            yes_label=keep(node.yes_label, _DEFAULT_YES),
            no_label=keep(node.no_label, _DEFAULT_NO),
        )
    if kind == KIND_HANDOFF:
        return replace(node, reason=keep(node.reason, _DEFAULT_REASON))
    return node


def new_option(node: NodeForm, label: str = "", next_node: str = "") -> OptionForm:
    """A new button/row with a generated id unique inside the step (never shown)."""
    taken = {o.option_id for o in node.options}
    section = node.options[-1].section if node.options else _DEFAULT_SECTION
    return OptionForm(
        option_id=new_option_id(label or "boton", taken),
        label=label,
        description="",
        next=next_node,
        section=section if node.kind == KIND_LIST else "",
    )


def fresh_node_id(form: MenuForm, label: str) -> str:
    """A generated id (slug of `label` + random suffix) unused in `form`. Ids are made
    once, at creation, and never regenerated (m-24848536)."""
    return new_node_id(label, {n.node_id for n in form.nodes})


def empty_form() -> MenuForm:
    """«Nuevo menú» → vacío: one text step to start from. Invalid until its text is
    written — the validation says so right where to type."""
    return MenuForm(
        welcome="",
        on_first_message=True,
        start_node="inicio",
        fallback_node=NONE_VALUE,
        keywords=[],
        ice_breakers=[],
        commands=[],
        nodes=[new_node(KIND_TEXT, "inicio", "Saludo")],
    )


def template_definition(template: str, facts: StarterFacts | None = None) -> MenuDefinition | None:
    """The starting definition of a new menu: the usual answers filled with what Qualify
    knows (`starter.build_starter_menu`, m-24936836), or None (empty). The fast-food
    example (`examples.BIANKI_DEMO_MENU`) never seeds a menu: its address and hours are invented."""
    if template != TEMPLATE_FAST_FOOD:
        return None
    return build_starter_menu(facts or StarterFacts())


# --------------------------------------------------------------------------------------
# Definition → form
# --------------------------------------------------------------------------------------


def _s(value: str | None) -> str:
    return value or ""


def _node_to_form(node_id: str, node: Any) -> NodeForm:
    base = NodeForm(node_id=node_id, kind=node.kind, title=_s(getattr(node, "title", None)))
    if isinstance(node, TextNode):
        base = replace(base, body=node.body, next=node.next or NONE_VALUE)
    elif isinstance(node, ButtonsNode):
        base = replace(
            base,
            body=node.body,
            header=_s(node.header),
            footer=_s(node.footer),
            options=[
                OptionForm(option_id=o.id, label=o.label, description="", next=o.next, section="")
                for o in node.options
            ],
        )
    elif isinstance(node, ListNode):
        base = replace(
            base,
            body=node.body,
            header=_s(node.header),
            footer=_s(node.footer),
            button_label=node.button_label,
            options=[
                OptionForm(
                    option_id=r.id,
                    label=r.title,
                    description=_s(r.description),
                    next=r.next,
                    section=s.title,
                )
                for s in node.sections
                for r in s.rows
            ],
        )
    elif isinstance(node, ProductsNode):
        base = replace(
            base,
            body=node.body,
            header=_s(node.header),
            footer=_s(node.footer),
            button_label=node.button_label,
            more_label=node.more_label,
            page_size=str(node.page_size),
            next_after_pick=node.next_after_pick,
            empty_body=node.empty_body,
        )
    elif isinstance(node, OrderSummaryNode):
        base = replace(
            base,
            body=node.body,
            confirm_next=node.confirm_next,
            add_more_next=node.add_more_next,
            cancel_next=node.cancel_next,
            confirm_label=node.confirm_label,
            add_more_label=node.add_more_label,
            cancel_label=node.cancel_label,
            empty_line=node.empty_line,
        )
    elif isinstance(node, CollectNode):
        base = replace(
            base,
            body=node.prompt,
            field_name=node.field,
            validation=node.validation,
            error_message=node.error_message,
            yes_label=node.yes_label,
            no_label=node.no_label,
            next=node.next,
        )
    elif isinstance(node, HandoffNode):
        base = replace(base, body=node.message, reason=node.reason)
    return apply_kind_defaults(base)


def _ordered_refs(node: Any) -> list[str]:
    """A step's arrows in the order the customer meets them (the schema's
    `references()` is a set)."""
    if isinstance(node, TextNode | CollectNode):
        return [node.next] if node.next else []
    if isinstance(node, ButtonsNode):
        return [o.next for o in node.options]
    if isinstance(node, ListNode):
        return [r.next for s in node.sections for r in s.rows]
    if isinstance(node, ProductsNode):
        return [node.next_after_pick]
    if isinstance(node, OrderSummaryNode):
        return [node.confirm_next, node.add_more_next, node.cancel_next]
    return []


def flow_order(definition: MenuDefinition) -> list[str]:
    """The steps in the order a conversation reaches them: the start step, then
    breadth-first along the arrows, then what only the entry reaches (keywords, ice
    breakers, commands, fallback), then anything unreachable, alphabetically.

    Why not the stored order: `whatsapp_menu_versions.definition` is `jsonb`, and jsonb
    does not keep object key order (it sorts keys by length, then bytes), so a saved menu
    comes back as `info, inicio, horario, …`. The schema forbids extra keys, so an order
    cannot be stored next to the steps; the flow order is stable and reads like the menu.
    """
    order: list[str] = []
    seen: set[str] = set()

    def walk(roots: list[str]) -> None:
        queue = [r for r in roots if r in definition.nodes]
        while queue:
            node_id = queue.pop(0)
            if node_id in seen:
                continue
            seen.add(node_id)
            order.append(node_id)
            queue.extend(
                r for r in _ordered_refs(definition.nodes[node_id]) if r in definition.nodes
            )

    entry = definition.entry
    walk([definition.start_node])
    walk(
        [ib.node for ib in entry.ice_breakers]
        + [c.node for c in entry.commands]
        + sorted(set(entry.keywords.values()))
        + ([entry.fallback_node] if entry.fallback_node else [])
    )
    walk(sorted(definition.nodes))
    return order


def definition_to_form(definition: MenuDefinition) -> MenuForm:
    entry = definition.entry
    return MenuForm(
        welcome=_s(entry.welcome),
        on_first_message=entry.on_first_message,
        start_node=definition.start_node,
        fallback_node=entry.fallback_node or NONE_VALUE,
        # Keywords are a jsonb object too: alphabetical is the only stable order.
        keywords=[KeywordForm(word=w, node=n) for w, n in sorted(entry.keywords.items())],
        ice_breakers=[IceBreakerForm(text=ib.text, node=ib.node) for ib in entry.ice_breakers],
        commands=[CommandForm(name=c.name, hint=c.hint, node=c.node) for c in entry.commands],
        nodes=[
            _node_to_form(node_id, definition.nodes[node_id]) for node_id in flow_order(definition)
        ],
    )


# --------------------------------------------------------------------------------------
# Form → payload (the JSON `MenuDefinition.model_validate` takes)
# --------------------------------------------------------------------------------------


def _opt(value: str) -> str | None:
    cleaned = value.strip()
    return cleaned or None


def _ref(value: str) -> str | None:
    return None if value in ("", NONE_VALUE) else value


def _page_size(value: str) -> int | str:
    cleaned = value.strip()
    return int(cleaned) if cleaned.isdigit() else cleaned


@dataclass(frozen=True)
class _LocMap:
    """How pydantic's locations land back on the form: step id → index, and for list
    steps (section, row) → flat option index."""

    node_index: dict[str, int]
    list_rows: dict[str, dict[tuple[int, int], int]]
    section_first_row: dict[str, dict[int, int]]
    node_titles: dict[str, str] = field(default_factory=dict)  # id → the owner's name


def _sections(options: Sequence[OptionForm]) -> tuple[list[dict[str, Any]], dict, dict]:
    sections: list[dict[str, Any]] = []
    rows_at: dict[tuple[int, int], int] = {}
    first_row: dict[int, int] = {}
    for index, option in enumerate(options):
        title = option.section.strip()
        if not sections or sections[-1]["title"] != title:
            sections.append({"title": title, "rows": []})
            first_row[len(sections) - 1] = index
        rows = sections[-1]["rows"]
        rows_at[(len(sections) - 1, len(rows))] = index
        rows.append(
            {
                "id": option.option_id.strip(),
                "title": option.label,
                "description": _opt(option.description),
                "next": option.next,
            }
        )
    return sections, rows_at, first_row


def _node_payload(node: NodeForm) -> tuple[dict[str, Any], dict, dict]:
    kind = node.kind
    rows_at: dict[tuple[int, int], int] = {}
    first_row: dict[int, int] = {}
    interactive = {"body": node.body, "header": _opt(node.header), "footer": _opt(node.footer)}
    if kind == KIND_TEXT:
        payload: dict[str, Any] = {"kind": kind, "body": node.body, "next": _ref(node.next)}
    elif kind == KIND_BUTTONS:
        payload = {
            "kind": kind,
            **interactive,
            "options": [
                {"id": o.option_id.strip(), "label": o.label, "next": o.next} for o in node.options
            ],
        }
    elif kind == KIND_LIST:
        sections, rows_at, first_row = _sections(node.options)
        payload = {
            "kind": kind,
            **interactive,
            "button_label": node.button_label,
            "sections": sections,
        }
    elif kind == KIND_PRODUCTS:
        payload = {
            "kind": kind,
            "source": "catalog",
            **interactive,
            "button_label": node.button_label,
            "more_label": node.more_label,
            "page_size": _page_size(node.page_size),
            "next_after_pick": node.next_after_pick,
            "empty_body": node.empty_body,
        }
    elif kind == KIND_ORDER_SUMMARY:
        payload = {
            "kind": kind,
            "body": node.body,
            "confirm_next": node.confirm_next,
            "add_more_next": node.add_more_next,
            "cancel_next": node.cancel_next,
            "confirm_label": node.confirm_label,
            "add_more_label": node.add_more_label,
            "cancel_label": node.cancel_label,
            "empty_line": node.empty_line,
        }
    elif kind == KIND_COLLECT:
        payload = {
            "kind": kind,
            "prompt": node.body,
            "field": node.field_name,
            "validation": node.validation,
            "error_message": node.error_message,
            "yes_label": node.yes_label,
            "no_label": node.no_label,
            "next": node.next,
        }
    else:  # handoff, or an unknown kind the schema will refuse
        payload = {"kind": kind, "message": node.body, "reason": node.reason}
    payload["title"] = _opt(node.title)
    return payload, rows_at, first_row


def form_to_payload(form: MenuForm) -> dict[str, Any]:
    """The definition JSON the form describes (not validated). Rows the pre-checks
    already flagged as unusable (an empty keyword, a step id used twice) are left out —
    their message is on their own row."""
    return _build_payload(form)[0]


def _build_payload(form: MenuForm) -> tuple[dict[str, Any], _LocMap]:
    keywords: dict[str, str] = {}
    seen_keywords: set[str] = set()
    for kw in form.keywords:
        norm = normalize_keyword(kw.word)
        if not norm or norm in seen_keywords:
            continue
        seen_keywords.add(norm)
        keywords[kw.word.strip()] = kw.node
    nodes: dict[str, Any] = {}
    node_index: dict[str, int] = {}
    list_rows: dict[str, dict[tuple[int, int], int]] = {}
    section_first_row: dict[str, dict[int, int]] = {}
    node_titles: dict[str, str] = {}
    for index, node in enumerate(form.nodes):
        node_id = node.node_id.strip()
        if not node_id or node_id in nodes:
            continue
        payload, rows_at, first_row = _node_payload(node)
        nodes[node_id] = payload
        node_index[node_id] = index
        list_rows[node_id] = rows_at
        section_first_row[node_id] = first_row
        node_titles[node_id] = node.title.strip()
    payload = {
        "version": 1,
        "start_node": form.start_node,
        "entry": {
            "on_first_message": form.on_first_message,
            "welcome": _opt(form.welcome),
            "keywords": keywords,
            "ice_breakers": [{"text": ib.text, "node": ib.node} for ib in form.ice_breakers],
            "commands": [{"name": c.name, "hint": c.hint, "node": c.node} for c in form.commands],
            "fallback_node": _ref(form.fallback_node),
        },
        "nodes": nodes,
    }
    return payload, _LocMap(node_index, list_rows, section_first_row, node_titles)


# --------------------------------------------------------------------------------------
# Validation → Spanish, attached to the field
# --------------------------------------------------------------------------------------

REQUIRED = "Obligatorio."
PICK_A_STEP = "Elige un paso que exista."
NO_EMOJI = "Meta no admite emojis aquí."
SLUG_RULE = "Solo minúsculas sin tildes, números y «_», empezando por una letra."
NODE_ID_RULE = "Solo minúsculas sin tildes, números, «_» o «-» (máximo 64)."
STRUCTURE_PROBLEM = "El menú tiene un problema de estructura. Revisa los pasos y sus destinos."

_LIST_WHAT: dict[str, str] = {
    "options": "botones",
    "sections": "secciones",
    "rows": "filas",
    "ice_breakers": "atajos",
    "commands": "comandos",
}

_NODE_FIELD_ALIASES: dict[str, str] = {
    "prompt": "body",
    "message": "body",
    "field": "field_name",
    "sections": "options",
}
_OPTION_FIELD_ALIASES: dict[str, str] = {"id": "option_id", "title": "label"}


def _value_error_text(message: str) -> str:
    """The schema's own `ValueError`s (English, for engineers) → Spanish copy."""
    if "emoji" in message:
        return NO_EMOJI
    if "single word" in message:
        return "Una sola palabra, sin la barra «/»."
    if "keyword must not be empty" in message:
        return "Hay una palabra clave vacía."
    if "duplicate keyword" in message:
        return "Hay palabras clave repetidas (sin contar tildes ni mayúsculas)."
    if "duplicate ice breaker" in message:
        return "Hay atajos repetidos."
    if "duplicate command" in message:
        return "Hay comandos repetidos."
    if "duplicate" in message and "id" in message:
        return "Hay dos opciones con el mismo identificador en este paso."
    match = re.search(r"list has (\d+) rows", message)
    if match:
        return f"Una lista admite máximo {MAX_LIST_ROWS} filas (tiene {match.group(1)})."
    if "{total}" in message:
        return "Incluye {total} en el texto: ahí va el total del pedido."
    return STRUCTURE_PROBLEM


def translate_error(error: Mapping[str, Any]) -> str:
    """One pydantic error → Spanish copy. Lengths name Meta's limit and the current count,
    so the operator knows how much to cut."""
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    loc = tuple(error.get("loc", ()))
    last = next((p for p in reversed(loc) if isinstance(p, str)), "")
    if kind == "string_too_long":
        limit = ctx.get("max_length")
        value = error.get("input")
        current = f" (tiene {len(value)})" if isinstance(value, str) else ""
        return f"Máximo {limit} caracteres{current}."
    if kind in ("string_too_short", "missing"):
        return REQUIRED
    if kind == "too_long":
        what = _LIST_WHAT.get(last, "elementos")
        return f"Máximo {ctx.get('max_length')} {what}."
    if kind == "too_short":
        return "El menú necesita al menos un paso." if last == "nodes" else "Agrega al menos una."
    if kind == "string_pattern_mismatch":
        return SLUG_RULE
    if kind in ("int_parsing", "int_type", "int_from_float"):
        return "Escribe un número."
    if kind == "greater_than_equal":
        return f"Mínimo {ctx.get('ge')}."
    if kind == "less_than_equal":
        return f"Máximo {ctx.get('le')}."
    if kind == "literal_error":
        return "Elige una opción de la lista."
    if kind == "value_error":
        return _value_error_text(str(ctx.get("error", error.get("msg", ""))))
    return "Revisa este campo."


class _Errors:
    """Mutable collector while validating; `annotate` freezes it onto the form."""

    def __init__(self) -> None:
        self.entry: dict[str, str] = {}
        self.menu: list[str] = []
        self.keywords: dict[int, dict[str, str]] = {}
        self.ice_breakers: dict[int, dict[str, str]] = {}
        self.commands: dict[int, dict[str, str]] = {}
        self.nodes: dict[int, dict[str, str]] = {}
        self.options: dict[tuple[int, int], dict[str, str]] = {}

    @staticmethod
    def _put(bucket: dict[str, str], key: str, message: str) -> None:
        bucket.setdefault(key, message)  # first message wins: the pre-check's is precise

    def entry_field(self, key: str, message: str) -> None:
        self._put(self.entry, key, message)

    def row(self, table: dict[int, dict[str, str]], index: int, key: str, message: str) -> None:
        self._put(table.setdefault(index, {}), key, message)

    def option(self, node: int, option: int, key: str, message: str) -> None:
        self._put(self.options.setdefault((node, option), {}), key, message)

    def add_menu(self, message: str) -> None:
        if message not in self.menu:
            self.menu.append(message)

    @property
    def count(self) -> int:
        tables = (self.keywords, self.ice_breakers, self.commands, self.nodes, self.options)
        return (
            len(self.entry)
            + len(self.menu)
            + sum(len(errs) for table in tables for errs in table.values())
        )


def _precheck(form: MenuForm, errors: _Errors) -> None:
    """What the flat form can get wrong before the schema sees it."""
    ids = [n.node_id.strip() for n in form.nodes]
    known = {i for i in ids if i}
    handoffs = {n.node_id.strip() for n in form.nodes if n.kind == KIND_HANDOFF}
    for index, node_id in enumerate(ids):
        if not node_id:
            errors.row(errors.nodes, index, "node_id", REQUIRED)
        elif not _NODE_ID_RE.match(node_id):
            errors.row(errors.nodes, index, "node_id", NODE_ID_RULE)
        elif ids.count(node_id) > 1:  # every holder is flagged: either may be the typo
            errors.row(errors.nodes, index, "node_id", "Ya hay otro paso con este identificador.")

    def ref(value: str, optional: bool = False) -> str | None:
        if value in ("", NONE_VALUE):
            return None if optional else PICK_A_STEP
        return None if value in known else PICK_A_STEP

    if (problem := ref(form.start_node)) is not None:
        errors.entry_field("start_node", problem)
    if form.fallback_node not in ("", NONE_VALUE):
        if form.fallback_node not in known:
            errors.entry_field("fallback_node", PICK_A_STEP)
        elif form.fallback_node not in handoffs:
            errors.entry_field("fallback_node", "Debe ser un paso «Pasar a una persona».")

    seen_words: set[str] = set()
    for index, kw in enumerate(form.keywords):
        norm = normalize_keyword(kw.word)
        if not norm:
            errors.row(errors.keywords, index, "word", REQUIRED)
        elif norm in seen_words:
            errors.row(errors.keywords, index, "word", "Ya está arriba (sin contar tildes).")
        seen_words.add(norm)
        if (problem := ref(kw.node)) is not None:
            errors.row(errors.keywords, index, "node", problem)
    for index, ib in enumerate(form.ice_breakers):
        if (problem := ref(ib.node)) is not None:
            errors.row(errors.ice_breakers, index, "node", problem)
    for index, cmd in enumerate(form.commands):
        if (problem := ref(cmd.node)) is not None:
            errors.row(errors.commands, index, "node", problem)

    for index, node in enumerate(form.nodes):
        refs: list[tuple[str, str, bool]] = []
        if node.kind == KIND_TEXT:
            refs.append(("next", node.next, True))
        elif node.kind == KIND_COLLECT:
            refs.append(("next", node.next, False))
        elif node.kind == KIND_PRODUCTS:
            refs.append(("next_after_pick", node.next_after_pick, False))
        elif node.kind == KIND_ORDER_SUMMARY:
            refs += [
                ("confirm_next", node.confirm_next, False),
                ("add_more_next", node.add_more_next, False),
                ("cancel_next", node.cancel_next, False),
            ]
        for key, value, optional in refs:
            if (problem := ref(value, optional)) is not None:
                errors.row(errors.nodes, index, key, problem)
        if node.kind in (KIND_BUTTONS, KIND_LIST):
            seen_option_ids: set[str] = set()
            for j, option in enumerate(node.options):
                option_id = option.option_id.strip()
                if not option_id:
                    errors.option(index, j, "option_id", REQUIRED)
                elif option_id in seen_option_ids:
                    errors.option(index, j, "option_id", "Repetido en este paso.")
                seen_option_ids.add(option_id)
                if (problem := ref(option.next)) is not None:
                    errors.option(index, j, "next", problem)
            if node.kind == KIND_BUTTONS and len(node.options) > MAX_BUTTONS:
                errors.row(errors.nodes, index, "options", f"Máximo {MAX_BUTTONS} botones.")
            if node.kind == KIND_LIST and len(node.options) > MAX_LIST_ROWS:
                errors.row(
                    errors.nodes,
                    index,
                    "options",
                    f"Una lista admite máximo {MAX_LIST_ROWS} filas (tiene {len(node.options)}).",
                )
    if len(form.ice_breakers) > MAX_ICE_BREAKERS:
        errors.entry_field("ice_breakers", f"Máximo {MAX_ICE_BREAKERS} atajos.")
    if len(form.commands) > MAX_COMMANDS:
        errors.entry_field("commands", f"Máximo {MAX_COMMANDS} comandos.")


def _place_node_error(
    errors: _Errors, locmap: _LocMap, node_id: str, rest: tuple[Any, ...], message: str
) -> None:
    index = locmap.node_index.get(node_id)
    if index is None:
        errors.add_menu(message)
        return
    # rest = (kind_tag, field, ...) — pydantic puts the union tag first.
    tail = rest[1:] if rest and rest[0] in KIND_KEYS else rest
    if not tail:
        errors.row(errors.nodes, index, "options", message)
        return
    head = tail[0]
    if head == "options" and len(tail) >= 3:
        key = _OPTION_FIELD_ALIASES.get(tail[2], tail[2])
        errors.option(index, int(tail[1]), key, message)
        return
    if head == "sections" and len(tail) >= 3:
        section = int(tail[1])
        if tail[2] == "title":
            row = locmap.section_first_row.get(node_id, {}).get(section)
            if row is not None:
                errors.option(index, row, "section", message)
                return
        elif tail[2] == "rows" and len(tail) >= 5:
            row = locmap.list_rows.get(node_id, {}).get((section, int(tail[3])))
            if row is not None:
                key = _OPTION_FIELD_ALIASES.get(tail[4], tail[4])
                errors.option(index, row, key, message)
                return
        errors.row(errors.nodes, index, "options", message)
        return
    errors.row(errors.nodes, index, _NODE_FIELD_ALIASES.get(head, str(head)), message)


DANGLING_STEP: Final = (
    "Un botón lleva a un paso que ya no existe. Elige a dónde lleva en «Más opciones (avanzado)»."
)


def _place_structural(errors: _Errors, locmap: _LocMap, message: str) -> None:
    """The model validator's whole-menu errors (loc `()`), parsed back to a field."""
    if "start_node" in message and "is not a node" in message:
        errors.entry_field("start_node", PICK_A_STEP)
        return
    if message.startswith("dangling node references"):
        for source, _target in re.findall(r"(\S+) -> '([^']*)'", message):
            # Never the missing step's id: the owner only knows steps by their name.
            name = locmap.node_titles.get(source, "")
            text = (
                f"El paso «{name}» lleva a un paso que ya no existe. Elige otro en "
                "«Más opciones (avanzado)»."
                if name
                else DANGLING_STEP
            )
            if source == "entry":
                errors.entry_field("_entry", text)
            elif source in locmap.node_index:
                errors.row(errors.nodes, locmap.node_index[source], "_node", text)
            else:
                errors.add_menu(text)
        return
    if "fallback_node" in message:
        errors.entry_field("fallback_node", "Debe ser un paso «Pasar a una persona».")
        return
    if "at most one order_summary" in message:
        errors.add_menu("Solo puede haber un paso «Resumen del pedido» por menú.")
        return
    match = re.search(r"cycle through '([^']*)'", message)
    if match:
        text = "Los pasos de texto forman un círculo: alguno debe terminar o pedir una respuesta."
        index = locmap.node_index.get(match.group(1))
        if index is not None:
            errors.row(errors.nodes, index, "next", text)
        else:
            errors.add_menu(text)
        return
    match = re.search(r"order_summary '([^']*)': confirm", message)
    if match:
        index = locmap.node_index.get(match.group(1))
        text = (
            "«Confirmar» debe terminar en «Pasar a una persona» (directo o tras preguntas "
            "y textos): un pedido siempre lo cierra una persona."
        )
        if index is not None:
            errors.row(errors.nodes, index, "confirm_next", text)
        else:
            errors.add_menu(text)
        return
    errors.add_menu(STRUCTURE_PROBLEM)


def _place(errors: _Errors, locmap: _LocMap, error: Mapping[str, Any]) -> None:
    loc = tuple(error.get("loc", ()))
    message = translate_error(error)
    if not loc:
        ctx = error.get("ctx") or {}
        _place_structural(errors, locmap, str(ctx.get("error", error.get("msg", ""))))
        return
    head = loc[0]
    if head == "entry" and len(loc) >= 2:
        section = loc[1]
        if section in ("ice_breakers", "commands") and len(loc) >= 4:
            table = errors.ice_breakers if section == "ice_breakers" else errors.commands
            errors.row(table, int(loc[2]), str(loc[3]), message)
        else:
            errors.entry_field(str(section), message)
        return
    if head == "nodes":
        if len(loc) >= 2:
            _place_node_error(errors, locmap, str(loc[1]), loc[2:], message)
        else:
            errors.add_menu(message)
        return
    if head == "start_node":
        errors.entry_field("start_node", message)
        return
    errors.add_menu(message)


@dataclass(frozen=True)
class FormResult:
    form: MenuForm  # with every `errors` filled in
    definition: MenuDefinition | None  # None while anything is wrong
    error_count: int


def validate_form(form: MenuForm) -> FormResult:
    """Validate the whole form through the schema and annotate every item with its
    Spanish messages. `definition` is set only when there is nothing to fix."""
    errors = _Errors()
    _precheck(form, errors)
    payload, locmap = _build_payload(form)
    definition: MenuDefinition | None = None
    try:
        definition = MenuDefinition.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors():
            _place(errors, locmap, error)
    if errors.count:
        definition = None
    return FormResult(_annotate(form, errors), definition, errors.count)


def referenced_node_ids(form: MenuForm) -> set[str]:
    """Every step id something leads to: the entry (start, fallback, keywords, ice
    breakers, commands), a button/row, or another step's «siguiente»."""
    refs = {form.start_node, form.fallback_node}
    refs.update(kw.node for kw in form.keywords)
    refs.update(ib.node for ib in form.ice_breakers)
    refs.update(c.node for c in form.commands)
    for node in form.nodes:
        refs.update(
            (
                node.next,
                node.next_after_pick,
                node.confirm_next,
                node.add_more_next,
                node.cancel_next,
            )
        )
        refs.update(o.next for o in node.options)
    refs.discard("")
    refs.discard(NONE_VALUE)
    return refs


def _annotate(form: MenuForm, errors: _Errors) -> MenuForm:
    nodes: list[NodeForm] = []
    labels = node_labels(form.nodes)
    referenced = referenced_node_ids(form)
    for i, node in enumerate(form.nodes):
        options = [
            replace(option, errors=dict(errors.options.get((i, j), {})))
            for j, option in enumerate(node.options)
        ]
        node_errors = dict(errors.nodes.get(i, {}))
        nodes.append(
            replace(
                node,
                options=options,
                errors=node_errors,
                has_issue=bool(node_errors) or any(o.errors for o in options),
                kind_label=KIND_LABELS.get(node.kind, node.kind),
                label=labels[i],
                unused=node.node_id.strip() not in referenced,
            )
        )
    return replace(
        form,
        keywords=[
            replace(kw, errors=dict(errors.keywords.get(i, {})))
            for i, kw in enumerate(form.keywords)
        ],
        ice_breakers=[
            replace(ib, errors=dict(errors.ice_breakers.get(i, {})))
            for i, ib in enumerate(form.ice_breakers)
        ],
        commands=[
            replace(c, errors=dict(errors.commands.get(i, {}))) for i, c in enumerate(form.commands)
        ],
        nodes=nodes,
        entry_errors=dict(errors.entry),
        menu_errors=list(errors.menu),
    )


def issues_summary(count: int) -> str:
    if count == 0:
        return ""
    if count == 1:
        return "Hay 1 cosa por corregir antes de publicar."
    return f"Hay {count} cosas por corregir antes de publicar."


# --------------------------------------------------------------------------------------
# Form edits that touch more than one item
# --------------------------------------------------------------------------------------


def change_kind(node: NodeForm, kind: str) -> NodeForm:
    """Switch a step's kind keeping its text and options; list rows get a section."""
    if kind not in KIND_KEYS or kind == node.kind:
        return node
    options = node.options
    if kind == KIND_LIST:
        options = [replace(o, section=o.section or _DEFAULT_SECTION) for o in options]
    return apply_kind_defaults(replace(node, kind=kind, options=options))


# --------------------------------------------------------------------------------------
# Step names (m-24848536): what the editor shows instead of an identifier
# --------------------------------------------------------------------------------------

_KIND_FALLBACK_TITLES: dict[str, str] = {
    KIND_PRODUCTS: "Tus productos",
    KIND_ORDER_SUMMARY: "Resumen del pedido",
    KIND_HANDOFF: "Pasar a una persona",
    KIND_COLLECT: "Pregunta",
}
_EXCERPT_LEN = 40


def excerpt(text: str, limit: int = _EXCERPT_LEN) -> str:
    """The first non-empty line of `text`, without WhatsApp's `*bold*` marks, cut to
    `limit` characters with «…»."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = line.replace("*", "").strip()
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def node_label(node: NodeForm) -> str:
    """A step's name: its title; else the start of its text; else what kind it is."""
    if node.title.strip():
        return node.title.strip()
    if node.kind in (KIND_TEXT, KIND_BUTTONS, KIND_LIST, KIND_COLLECT) and node.body.strip():
        return excerpt(node.body)
    return _KIND_FALLBACK_TITLES.get(node.kind, KIND_LABELS.get(node.kind, "Paso"))


def node_labels(nodes: Sequence[NodeForm]) -> list[str]:
    """`node_label` for every step, made unique with « (2)», « (3)»… so two steps never
    read the same in a «Lleva a» list."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for node in nodes:
        label = node_label(node)
        count = seen.get(label, 0) + 1
        seen[label] = count
        out.append(label if count == 1 else f"{label} ({count})")
    return out


@dataclass(frozen=True)
class NodeChoiceVM:
    """One entry of a «Lleva a» select: the value is the id, the owner reads the name."""

    node_id: str
    label: str


def node_choices(nodes: Sequence[NodeForm], *, handoffs_only: bool = False) -> list[NodeChoiceVM]:
    labels = node_labels(nodes)
    return [
        NodeChoiceVM(node.node_id, labels[i])
        for i, node in enumerate(nodes)
        if node.node_id.strip() and (not handoffs_only or node.kind == KIND_HANDOFF)
    ]


# --------------------------------------------------------------------------------------
# The menu in four steps (m-24848536)
# --------------------------------------------------------------------------------------
#
# A guided view over the SAME form the advanced editor edits: every guided edit is a pure
# `MenuForm -> MenuForm` function, so «Atrás», «Más opciones (avanzado)» and back never
# lose anything, and the schema stays the one authority on validity. The four steps map
# onto the starter's shape (`starter.build_starter_menu`):
#
#   1 ¿Cómo saludas?          → entry.welcome
#   2 ¿Qué te preguntan…?     → one ordered list of answers (m-24936836): the first ones
#                                are the start step's buttons, the rest the rows of the
#                                «Más preguntas» list (see «Answers» below)
#   3 Tus productos           → the catalog step's text; on confirm: ask the address or not
#   4 Pruébalo y publícalo    → review in words + the preview + «Publicar en mi WhatsApp»
#
# Steps a guided edit needs (the catalog chain, «hablar con una persona», a message) are
# created with generated ids (`ids.new_node_id`) and never renamed by id.

GUIDED_STEPS: Final = 4
GUIDED_TITLES: tuple[str, ...] = (
    "¿Cómo saludas?",
    "¿Qué te preguntan siempre?",
    "Tus productos",
    "Pruébalo y publícalo",
)
GUIDED_HELP: tuple[str, ...] = (
    "Es lo primero que lee tu cliente cuando te escribe.",
    "Deja listas las respuestas a lo que más te preguntan. Tu cliente las toca y recibe la "
    "respuesta al instante.",
    "Tu cliente elige de tu catálogo, con su precio, y arma su pedido.",
    "Pruébalo como si fueras tu cliente. Cuando te guste, publícalo en tu WhatsApp.",
)

ACTION_PRODUCTS: Final = "products"
ACTION_TEXT: Final = "text"
ACTION_PERSON: Final = "person"
ACTION_MORE: Final = "more"  # a template sub-menu: kept, edited in «Más opciones»
GUIDED_ACTIONS: tuple[tuple[str, str], ...] = (
    (ACTION_PRODUCTS, "Mostrar mis productos"),
    (ACTION_TEXT, "Responder con un mensaje"),
    (ACTION_PERSON, "Pasarme el chat"),
)
ACTION_MORE_LABEL: Final = "Mostrar más botones"

ADDRESS_ASK: Final = "ask"
ADDRESS_SKIP: Final = "skip"

_ADDRESS_FIELD = "direccion"

# Step 3 → Catálogo saves first (guide N6); «Guardar y seguir después» says why it is off.
CATALOG_SAVED_HINT: Final = "Guardamos tu menú. Cuando termines, vuelve a WhatsApp → Menú."
CATALOG_FIX_FIRST: Final = (
    "Corrige lo marcado en rojo antes de salir, o se pierde lo que escribiste."
)
SAVE_NEEDS_FIX: Final = "Para guardar, completa lo marcado en rojo."
SAVE_NOTHING_NEW: Final = "Ya está guardado. Puedes salir y seguir después."
BUTTON_LABEL_MAX: Final = 20  # WhatsApp cuts a reply button's text at 20 characters
_ADDRESS_PROMPT = "¿A qué dirección te lo llevamos? Escríbela completa, con barrio."
_ADDRESS_ERROR = "Necesito la dirección escrita para poder tomar el pedido."
_PERSON_TITLE = "Hablar con una persona"
_PERSON_MESSAGE = "Te paso con una persona del equipo; en un momento te responden."
_DEFAULT_QUESTION = "¿Qué quieres hacer?"
_DEFAULT_PERSON_BUTTON = "Hablar con alguien"

# The template's catalog chain, cloned (with fresh ids) into a menu that lacks one.
_ORDER_CHAIN: tuple[str, ...] = (
    "productos",
    "agregado",
    "resumen",
    "direccion",
    "pedido_confirmado",
    "cancelado",
)
_SUMMARY_CHAIN: tuple[str, ...] = ("resumen", "direccion", "pedido_confirmado")


@dataclass(frozen=True)
class GuidedButtonVM:
    label: str
    action: str  # ACTION_*; "" when the button leads nowhere yet
    text: str  # the message, when action == ACTION_TEXT
    more_summary: str  # «Horario · Ubicación · Volver», when action == ACTION_MORE
    label_error: str
    text_error: str


@dataclass(frozen=True)
class GuidedVM:
    uses_buttons: bool  # the start step is a «Botones» step
    greeting: str
    greeting_error: str
    question: str
    question_error: str
    buttons: list[GuidedButtonVM]
    buttons_full: bool
    can_remove_button: bool
    has_products: bool
    products_intro: str
    products_intro_error: str
    has_order: bool
    address_choice: str  # ADDRESS_ASK / ADDRESS_SKIP
    address_prompt: str
    address_error: str
    hidden_issues: int  # problems only «Más opciones (avanzado)» shows
    # Something to fix in step 1 / 2 / 3 — step 4 links back to each one.
    greeting_issue: bool = False
    buttons_issue: bool = False
    products_issue: bool = False


EMPTY_GUIDED = GuidedVM(
    uses_buttons=False,
    greeting="",
    greeting_error="",
    question="",
    question_error="",
    buttons=[],
    buttons_full=False,
    can_remove_button=False,
    has_products=False,
    products_intro="",
    products_intro_error="",
    has_order=False,
    address_choice=ADDRESS_SKIP,
    address_prompt="",
    address_error="",
    hidden_issues=0,
)


@dataclass(frozen=True)
class CatalogRowVM:
    name: str
    price: str  # PRE-FORMATTED («COP 18.000») or «Sin precio»
    category: str = ""  # the section title the customer sees («Otros» for none)


def catalog_rows(items: Sequence[CatalogItem]) -> list[CatalogRowVM]:
    """In the order the customer gets them (m-24955643: the owner's, from Catálogo)."""
    return [
        CatalogRowVM(
            name=i.name,
            price=(
                format_money(i.price_amount, i.price_currency)
                if i.price_amount is not None
                else "Sin precio"
            ),
            category=category_label(i.category),
        )
        for i in items
    ]


# -- step 3 shows the order, read-only (m-24955643, docs/ux-orden-de-productos.md §1) ----
ORDER_HINT: Final = "Tu cliente los ve en este orden."
CHANGE_ORDER: Final = "Cambiar el orden"
#: A WhatsApp list holds 10 rows; with more products, 9 + «Ver más» per screen
#: (`engine._pages`): the first screen is what step 3 shows.
_LIST_ROWS: Final = 10


@dataclass(frozen=True)
class CatalogSectionVM:
    label: str
    rows: tuple[CatalogRowVM, ...]
    count_label: str = ""  # categories first: «5 productos», and no rows


def _category_counts(rows: Sequence[CatalogRowVM]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.category] = counts.get(row.category, 0) + 1
    return counts


def catalog_by_category(rows: Sequence[CatalogRowVM]) -> bool:
    """WhatsApp opens on the list of categories (`engine`, m-24955838): more products
    than one list holds and two or more categories."""
    return len(rows) > _LIST_ROWS and len(_category_counts(rows)) >= 2


def catalog_mode_line(rows: Sequence[CatalogRowVM]) -> str:
    if not catalog_by_category(rows):
        return ""
    return "Como tienes más de 10 productos, tu cliente primero elige una categoría."


def first_screen(rows: Sequence[CatalogRowVM]) -> list[CatalogRowVM]:
    """The products the customer sees without touching «Ver más» (direct list)."""
    return list(rows) if len(rows) <= _LIST_ROWS else list(rows[: _LIST_ROWS - 1])


def catalog_sections(rows: Sequence[CatalogRowVM]) -> list[CatalogSectionVM]:
    """The first screen: categories first, the list of categories with their counts
    (9 + «Ver más categorías» past 10); otherwise the first products grouped by
    category, in order (consecutive rows of one category are one section)."""
    if catalog_by_category(rows):
        counts = list(_category_counts(rows).items())
        if len(counts) > _LIST_ROWS:
            counts = counts[: _LIST_ROWS - 1]
        return [
            CatalogSectionVM(label, (), "1 producto" if n == 1 else f"{n} productos")
            for label, n in counts
        ]
    out: list[CatalogSectionVM] = []
    for row in first_screen(rows):
        if out and out[-1].label == row.category:
            out[-1] = CatalogSectionVM(out[-1].label, (*out[-1].rows, row))
        else:
            out.append(CatalogSectionVM(row.category, (row,)))
    return out


def catalog_order_line(rows: Sequence[CatalogRowVM]) -> str:
    """Every category, in order: «Shawarmas · Combos · Ensaladas · Otros»."""
    labels: list[str] = []
    for row in rows:
        if row.category not in labels:
            labels.append(row.category)
    return " · ".join(labels)


def catalog_more_line(rows: Sequence[CatalogRowVM]) -> str:
    """«Y 8 más al tocar «Ver más».» — "" when they all fit on the first screen; with
    categories first, the categories past the first screen."""
    if catalog_by_category(rows):
        extra = len(_category_counts(rows)) - len(catalog_sections(rows))
        if extra <= 0:
            return ""
        if extra == 1:
            return "Y 1 categoría más al tocar «Ver más categorías»."
        return f"Y {extra} categorías más al tocar «Ver más categorías»."
    rest = len(rows) - len(first_screen(rows))
    if rest <= 0:
        return ""
    return "Y 1 más al tocar «Ver más»." if rest == 1 else f"Y {rest} más al tocar «Ver más»."


def _find(form: MenuForm, node_id: str) -> int | None:
    return next((i for i, n in enumerate(form.nodes) if n.node_id == node_id), None)


def _first_kind(form: MenuForm, kind: str) -> int | None:
    return next((i for i, n in enumerate(form.nodes) if n.kind == kind), None)


def _person_index(form: MenuForm) -> int | None:
    handoffs = [i for i, n in enumerate(form.nodes) if n.kind == KIND_HANDOFF]
    # The fallback is «hablar con una persona» by construction; another handoff that
    # answers first («Reservas») must never be mistaken for it.
    fallback = _find(form, form.fallback_node)
    if fallback is not None and form.nodes[fallback].kind == KIND_HANDOFF:
        return fallback
    for i in handoffs:
        if form.nodes[i].reason == "customer_request":
            return i
    return next((i for i in handoffs if form.nodes[i].reason != "order_confirmed"), None)


def _set_node(form: MenuForm, index: int, **changes: Any) -> MenuForm:
    nodes = list(form.nodes)
    nodes[index] = replace(nodes[index], **changes)
    return replace(form, nodes=nodes)


def _start(form: MenuForm) -> int | None:
    return _find(form, form.start_node)


def _button_action(form: MenuForm, option: OptionForm) -> str:
    index = _find(form, option.next)
    if index is None:
        return ""
    kind = form.nodes[index].kind
    if kind == KIND_PRODUCTS:
        return ACTION_PRODUCTS
    if kind == KIND_HANDOFF:
        return ACTION_PERSON
    if kind == KIND_TEXT:
        return ACTION_TEXT
    return ACTION_MORE


def guided_view(form: MenuForm, error_count: int = 0) -> GuidedVM:
    """The four steps' fields read off an annotated form (`validate_form(...).form`),
    with the Spanish messages of exactly the fields the steps show; `error_count` (the
    form's total) minus those is what only the advanced editor can show."""
    shown = 0

    def err(errors: Mapping[str, str], key: str) -> str:
        nonlocal shown
        message = errors.get(key, "")
        if message:
            shown += 1
        return message

    greeting_error = err(form.entry_errors, "welcome")
    start_i = _start(form)
    start = form.nodes[start_i] if start_i is not None else None
    uses_buttons = start is not None and start.kind == KIND_BUTTONS
    question_error = err(start.errors, "body") if start is not None else ""
    buttons: list[GuidedButtonVM] = []
    counted_texts: set[int] = set()
    if start is not None and uses_buttons:
        for option in start.options:
            action = _button_action(form, option)
            target_i = _find(form, option.next)
            target = form.nodes[target_i] if target_i is not None else None
            text = target.body if target is not None and action == ACTION_TEXT else ""
            text_error = ""
            if target is not None and action == ACTION_TEXT:
                text_error = target.errors.get("body", "")
                if text_error and target_i not in counted_texts:
                    shown += 1
                    counted_texts.add(target_i)  # type: ignore[arg-type]
            more = ""
            if target is not None and action == ACTION_MORE:
                more = " · ".join(o.label for o in target.options if o.label.strip())
            label_error = err(option.errors, "label") or err(option.errors, "next")
            buttons.append(
                GuidedButtonVM(option.label, action, text, more, label_error, text_error)
            )
    # Step 2 also shows (m-24936836): the rows of «Más preguntas» and every answer's text,
    # the hand-off messages included — their messages are not «hidden» any more.
    rows_issue = False
    if start is not None and uses_buttons:
        owners = [start]
        more_i = _more_index(form, start)
        if more_i is not None:
            owners.append(form.nodes[_find(form, start.options[more_i].next)])  # type: ignore[index]
        for owner_index, owner in enumerate(owners):
            for option in owner.options:
                if owner_index > 0 and (err(option.errors, "label") or err(option.errors, "next")):
                    rows_issue = True
                target_i = _find(form, option.next)
                if target_i is None or target_i in counted_texts:
                    continue
                if owner_index == 0 and _button_action(form, option) == ACTION_TEXT:
                    continue  # counted above
                if form.nodes[target_i].kind in (KIND_TEXT, KIND_HANDOFF):
                    if form.nodes[target_i].errors.get("body"):
                        shown += 1
                        rows_issue = True
                    counted_texts.add(target_i)
    products_i = _first_kind(form, KIND_PRODUCTS)
    products = form.nodes[products_i] if products_i is not None else None
    products_intro_error = err(products.errors, "body") if products is not None else ""
    order_i = _first_kind(form, KIND_ORDER_SUMMARY)
    address_choice, address_prompt, address_error = ADDRESS_SKIP, "", ""
    if order_i is not None:
        confirm_i = _find(form, form.nodes[order_i].confirm_next)
        if confirm_i is not None and form.nodes[confirm_i].kind == KIND_COLLECT:
            address_choice = ADDRESS_ASK
            address_prompt = form.nodes[confirm_i].body
            address_error = err(form.nodes[confirm_i].errors, "body")
    return GuidedVM(
        uses_buttons=uses_buttons,
        greeting=form.welcome,
        greeting_error=greeting_error,
        question=start.body if start is not None else "",
        question_error=question_error,
        buttons=buttons,
        buttons_full=len(buttons) >= MAX_BUTTONS,
        can_remove_button=len(buttons) > 1,
        has_products=products is not None,
        products_intro=products.body if products is not None else "",
        products_intro_error=products_intro_error,
        has_order=order_i is not None,
        address_choice=address_choice,
        address_prompt=address_prompt,
        address_error=address_error,
        hidden_issues=max(0, error_count - shown),
        greeting_issue=bool(greeting_error),
        buttons_issue=bool(question_error)
        or rows_issue
        or any(b.label_error or b.text_error for b in buttons),
        products_issue=bool(products_intro_error or address_error),
    )


def _template_nodes() -> dict[str, NodeForm]:
    # The starter's catalog chain (no invented datum in it, m-24936836).
    return {n.node_id: n for n in definition_to_form(build_starter_menu(StarterFacts())).nodes}


def _remap(node: NodeForm, mapped: Mapping[str, str]) -> NodeForm:
    def move(value: str) -> str:
        return mapped.get(value, value)

    return replace(
        node,
        node_id=mapped[node.node_id],
        next=move(node.next),
        next_after_pick=move(node.next_after_pick),
        confirm_next=move(node.confirm_next),
        add_more_next=move(node.add_more_next),
        cancel_next=move(node.cancel_next),
        options=[replace(o, next=move(o.next)) for o in node.options],
    )


def ensure_products(form: MenuForm) -> tuple[MenuForm, str]:
    """The menu's catalog step, cloning the template's chain (catalog → added → order
    summary → address → «pedido confirmado») with fresh ids when the menu has none. A
    menu that already has an order summary keeps it: only the catalog steps are added."""
    found = _first_kind(form, KIND_PRODUCTS)
    if found is not None:
        return form, form.nodes[found].node_id
    template = _template_nodes()
    mapped: dict[str, str] = {}
    summary_i = _first_kind(form, KIND_ORDER_SUMMARY)
    wanted = list(_ORDER_CHAIN)
    if summary_i is not None:
        mapped["resumen"] = form.nodes[summary_i].node_id
        wanted = [w for w in wanted if w not in _SUMMARY_CHAIN]
    taken = {n.node_id for n in form.nodes}
    for template_id in wanted:
        new_id = new_node_id(template[template_id].title or template_id, taken)
        taken.add(new_id)
        mapped[template_id] = new_id
    added = [_remap(template[t], mapped) for t in wanted]
    return replace(form, nodes=[*form.nodes, *added]), mapped["productos"]


def ensure_person(form: MenuForm) -> tuple[MenuForm, str]:
    """The «hablar con una persona» step, created when the menu has none."""
    found = _person_index(form)
    if found is not None:
        return form, form.nodes[found].node_id
    node = replace(
        new_node(KIND_HANDOFF, fresh_node_id(form, _PERSON_TITLE), _PERSON_TITLE),
        body=_PERSON_MESSAGE,
        reason="customer_request",
    )
    return replace(form, nodes=[*form.nodes, node]), node.node_id


def guided_set_greeting(form: MenuForm, text: str) -> MenuForm:
    return replace(form, welcome=text)


def guided_set_question(form: MenuForm, text: str) -> MenuForm:
    index = _start(form)
    return form if index is None else _set_node(form, index, body=text)


def _start_options(form: MenuForm) -> tuple[int, list[OptionForm]] | None:
    index = _start(form)
    if index is None or form.nodes[index].kind != KIND_BUTTONS:
        return None
    return index, list(form.nodes[index].options)


def guided_set_button_label(form: MenuForm, button: int, label: str) -> MenuForm:
    found = _start_options(form)
    if found is None or not 0 <= button < len(found[1]):
        return form
    index, options = found
    options[button] = replace(options[button], label=label)
    return _set_node(form, index, options=options)


def guided_set_button_action(form: MenuForm, button: int, action: str) -> MenuForm:
    """Point a start button at the catalog, a message, or the owner. A new message
    step is created (generated id, the button's text as its name) unless the button
    already leads to one; nothing is deleted, so switching back keeps what was typed."""
    found = _start_options(form)
    if found is None or not 0 <= button < len(found[1]):
        return form
    option = found[1][button]
    if action == ACTION_PRODUCTS:
        form, target = ensure_products(form)
    elif action == ACTION_PERSON:
        form, target = ensure_person(form)
    elif action == ACTION_TEXT:
        if _button_action(form, option) == ACTION_TEXT:
            return form
        title = option.label.strip() or "Respuesta"
        # Back to «Responder con un mensaje»: reuse the message this button had before
        # (same name, nothing leads to it any more) instead of piling up copies.
        referenced = referenced_node_ids(form)
        previous = next(
            (
                n.node_id
                for n in form.nodes
                if n.kind == KIND_TEXT
                and n.title.strip() == title
                and n.node_id.strip() not in referenced
            ),
            None,
        )
        if previous is not None:
            target = previous
        else:
            node = new_node(KIND_TEXT, fresh_node_id(form, title), title)
            form, target = replace(form, nodes=[*form.nodes, node]), node.node_id
    else:
        return form
    index, options = _start_options(form)  # type: ignore[misc]
    options[button] = replace(options[button], next=target)
    return _set_node(form, index, options=options)


def guided_set_button_text(form: MenuForm, button: int, text: str) -> MenuForm:
    found = _start_options(form)
    if found is None or not 0 <= button < len(found[1]):
        return form
    option = found[1][button]
    target = _find(form, option.next)
    if target is None or form.nodes[target].kind != KIND_TEXT:
        return form
    return _set_node(form, target, body=text)


def guided_add_button(form: MenuForm) -> MenuForm:
    """A new start button (at most 3) that hands the chat to the owner until changed."""
    found = _start_options(form)
    if found is None or len(found[1]) >= MAX_BUTTONS:
        return form
    form, person = ensure_person(form)
    index, options = _start_options(form)  # type: ignore[misc]
    options.append(new_option(form.nodes[index], next_node=person))
    return _set_node(form, index, options=options)


def guided_remove_button(form: MenuForm, button: int) -> MenuForm:
    found = _start_options(form)
    if found is None or len(found[1]) <= 1 or not 0 <= button < len(found[1]):
        return form
    index, options = found
    options.pop(button)
    return _set_node(form, index, options=options)


def guided_use_buttons(form: MenuForm) -> MenuForm:
    """Turn the start step into a «Botones» step (keeping its text) with one button to
    the owner — for a menu started empty."""
    index = _start(form)
    if index is None or form.nodes[index].kind == KIND_BUTTONS:
        return form
    start = change_kind(form.nodes[index], KIND_BUTTONS)
    if not start.body.strip():
        start = replace(start, body=_DEFAULT_QUESTION)
    nodes = list(form.nodes)
    nodes[index] = start
    form, person = ensure_person(replace(form, nodes=nodes))
    if not form.nodes[index].options:
        option = new_option(form.nodes[index], _DEFAULT_PERSON_BUTTON, person)
        form = _set_node(form, index, options=[option])
    return form


def guided_set_products_intro(form: MenuForm, text: str) -> MenuForm:
    index = _first_kind(form, KIND_PRODUCTS)
    return form if index is None else _set_node(form, index, body=text)


def guided_set_address(form: MenuForm, choice: str) -> MenuForm:
    """«Al confirmar el pedido»: «Pedir dirección» puts an address question between
    «Confirmar» and the hand-off; «No pedir nada» goes straight to the hand-off. The
    question step is kept when skipped, so choosing it again brings its text back."""
    order_i = _first_kind(form, KIND_ORDER_SUMMARY)
    if order_i is None or choice not in (ADDRESS_ASK, ADDRESS_SKIP):
        return form
    order = form.nodes[order_i]
    confirm_i = _find(form, order.confirm_next)
    asking = confirm_i is not None and form.nodes[confirm_i].kind == KIND_COLLECT
    if choice == ADDRESS_SKIP:
        if not asking:
            return form
        return _set_node(form, order_i, confirm_next=form.nodes[confirm_i].next)  # type: ignore[index]
    if asking:
        return form
    leftover = next(
        (
            i
            for i, n in enumerate(form.nodes)
            if n.kind == KIND_COLLECT and n.field_name == _ADDRESS_FIELD
        ),
        None,
    )
    if leftover is None:
        title = "Pedir la dirección"
        question = replace(
            new_node(KIND_COLLECT, fresh_node_id(form, title), title),
            body=_ADDRESS_PROMPT,
            field_name=_ADDRESS_FIELD,
            error_message=_ADDRESS_ERROR,
            next=order.confirm_next,
        )
        form = replace(form, nodes=[*form.nodes, question])
        question_id = question.node_id
    else:
        form = _set_node(form, leftover, next=order.confirm_next)
        question_id = form.nodes[leftover].node_id
    return _set_node(form, order_i, confirm_next=question_id)


def guided_set_address_prompt(form: MenuForm, text: str) -> MenuForm:
    order_i = _first_kind(form, KIND_ORDER_SUMMARY)
    if order_i is None:
        return form
    confirm_i = _find(form, form.nodes[order_i].confirm_next)
    if confirm_i is None or form.nodes[confirm_i].kind != KIND_COLLECT:
        return form
    return _set_node(form, confirm_i, body=text)


def guided_step_label(step: int) -> str:
    return f"Paso {step} de {GUIDED_STEPS}"


def _button_does(button: GuidedButtonVM) -> str:
    if button.action == ACTION_PRODUCTS:
        return "muestra tus productos con su precio"
    if button.action == ACTION_PERSON:
        return "te pasa el chat para que respondas tú"
    if button.action == ACTION_TEXT:
        return f"responde «{excerpt(button.text)}»" if button.text.strip() else "aún sin mensaje"
    if button.action == ACTION_MORE:
        return (
            f"muestra más botones ({button.more_summary})"
            if button.more_summary
            else ("muestra más botones")
        )
    return "aún no hace nada"


def guided_review(
    view: GuidedVM,
    catalog_count: int,
    answers: AnswersVM | None = None,
    *,
    has_fallback: bool = False,
) -> list[str]:
    """Step 4's review, in words (guide N6): what the customer gets — with `answers`,
    one summary of the buttons and «Más preguntas» (m-24936836); without, button by
    button — and who closes the order (always the owner — guide N13)."""
    lines: list[str] = []
    if view.greeting.strip():
        lines.append(f"Saluda: «{excerpt(view.greeting, 80)}»")
    else:
        lines.append("No manda un saludo propio: empieza con la pregunta.")
    if answers is not None:
        lines.append(answers_summary(answers, has_fallback=has_fallback))
    elif view.uses_buttons:
        labels = [b.label.strip() for b in view.buttons if b.label.strip()]
        noun = "botón" if len(labels) == 1 else "botones"
        listed = ", ".join(f"«{label}»" for label in labels)
        lines.append(f"Pregunta «{excerpt(view.question, 60)}» con {len(labels)} {noun}: {listed}.")
        for button in view.buttons:
            if button.label.strip():
                lines.append(f"«{button.label.strip()}» {_button_does(button)}.")
    if view.has_products:
        if catalog_count == 0:
            if answers is None:  # with answers, step 4 warns instead (never a green check)
                lines.append(
                    "Tu catálogo está vacío: agrega tus productos para que te puedan pedir."
                )
        else:
            noun = "producto" if catalog_count == 1 else "productos"
            lines.append(f"Muestra tus {catalog_count} {noun} con su precio.")
    if view.has_order:
        if view.address_choice == ADDRESS_ASK:
            lines.append(
                "Al confirmar un pedido, pide la dirección y te pasa el chat para que lo cierres."
            )
        else:
            lines.append("Al confirmar un pedido, te pasa el chat para que lo cierres.")
    return lines


# --------------------------------------------------------------------------------------
# Answers: step 2, «¿Qué te preguntan siempre?» (m-24936836)
# --------------------------------------------------------------------------------------
#
# The owner thinks in answers, not in buttons: ONE ordered list. Read off the form, the
# answers are the start step's buttons (minus «Más preguntas») followed by the rows of the
# list «Más preguntas» opens; written back, the layout rule of `starter` puts the first
# ones on buttons and the rest in the list. Every option keeps its id when it moves, so a
# published reply id never breaks. A gap («[hora de abrir]») marks what is still missing;
# publishing waits until there is none (`form_gaps` + `starter.definition_gaps`).

STATUS_READY: Final = "ready"
STATUS_MISSING: Final = "missing"
STATUS_SUGGESTED: Final = "suggested"
_STATUS: dict[str, tuple[str, str]] = {
    STATUS_READY: ("Lista", "ok"),
    STATUS_MISSING: ("Falta completar", "warn"),
    STATUS_SUGGESTED: ("Sugerida", "info"),
}

ANSWER_NAME_TOO_LONG: Final = (
    "Usa hasta 20 letras: WhatsApp corta lo demás. Por ejemplo: «Horario»."
)
# A list row allows 24: the 20 is so the answer can still move up to a button.
ANSWER_ROW_NAME_TOO_LONG: Final = (
    "Usa hasta 20 letras para que pueda ir en un botón o en la lista. Por ejemplo: «Horario»."
)
ANSWER_NAME_NEEDS_FIX: Final = "Antes de publicar, corrige el nombre de una respuesta en el paso 2."
NO_PRODUCTS_WARNING: Final = (
    "Todavía no tienes productos: tu cliente verá «Ver menú y pedir» vacío."
)
ANSWER_NAME_TAKEN: Final = "Ya tienes una respuesta llamada «{name}». Ponle otro nombre."
ANSWER_TEXT_MISSING: Final = "Escribe lo que le respondes a tu cliente."
ANSWERS_FULL: Final = (
    "Llegaste a 12 respuestas, lo máximo que WhatsApp muestra en un mensaje. Para agregar "
    "otra, quita una o junta dos (por ejemplo, «Horario y dirección»)."
)
ANSWERS_EMPTY: Final = (
    "Tu cliente solo verá tu saludo. Agrega al menos una respuesta para que pueda pedir o "
    "preguntar."
)
NO_PRODUCTS: Final = (
    "Todavía no tienes productos. Agrégalos en Tus productos y aquí salen solos, con su precio."
)
# The screen is «Tus productos» (NAV-1, `test_nav_one_name`); the spec's «Catálogo» is its
# old name.
PRICES_FROM_CATALOG: Final = "Tus precios salen de tus productos. Cámbialos en Tus productos."
BUTTONS_HEADING: Final = "Botones (WhatsApp muestra hasta 3)"
GAPS_ELSEWHERE: Final = "Hay datos por completar en partes del menú que no están en estos 4 pasos."
# m-24945866: the name a gap's place takes in «Domicilio: minutos · Saludo: …».
# Not «Saludo»: that is also the title of the start step (the buttons under the welcome).
GREETING_GAP_PLACE: Final = "Mensaje de bienvenida"
SHORTCUTS_GAP_PLACE: Final = "Atajos y comandos"
UNNAMED_PLACE: Final = "Sin nombre"
PUBLISH_NEEDS_ANSWERS: Final = (
    "Antes de publicar, completa o quita las respuestas con datos por completar."
)
PUBLISH_NEEDS_GREETING: Final = "Antes de publicar, completa tu mensaje de bienvenida."
PUBLISH_NEEDS_DATA: Final = "Antes de publicar, completa los datos que faltan."
# Above the answer's text when «Completarlas» opens it: the gap comes selected.
GAP_FILL_HINT: Final = "Escribe el dato en lugar de lo marcado."
ANSWER_ISSUE: Final = "Una respuesta no tiene nombre o texto, o su nombre se repite."
MORE_HEADING: Final = "En «Más preguntas»"
MORE_ROW_TITLE: Final = "Más preguntas (lo pone Qualify)"
MORE_ROW_TEXT: Final = "Abre la lista de abajo"


def remove_confirm_text(label: str) -> str:
    return f"¿Quitar «{label}»? Tus clientes ya no la verán. Puedes volver a agregarla."


def button_limit_text(label: str) -> str:
    """Why «Subir» does not make the first answer of the list a button (spec §3)."""
    return (
        "Ya usas los 3 botones que deja WhatsApp. El tercero es «Más preguntas» porque "
        f"tienes más respuestas: ahí tu cliente ve «{label}» y las demás. Para que "
        f"«{label}» sea botón, baja otra respuesta."
    )


SUGGESTION_PRODUCTS: Final = "products"
SUGGESTION_CUSTOM: Final = "custom"
# «Agregar otra respuesta»: one-tap starters, each with its gaps (spec §2).
_SUGGESTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "promociones",
        "Promociones",
        "Esta semana tenemos [tu promoción]. Para pedir, escribe *menú*.",
    ),
    (
        "eventos",
        "Pedidos para eventos",
        "Hacemos pedidos para eventos. Escríbenos la fecha, para cuántas personas y qué "
        "quieres, y te enviamos el precio en [cuánto tardas en responder].",
    ),
    (
        "ingredientes",
        "Ingredientes",
        "Nuestros productos llevan [ingredientes principales]. Si tienes una alergia, "
        "escríbenos y te ayudamos.",
    ),
)
_PRODUCTS_LABEL = "Ver menú y pedir"
_CUSTOM_TITLE = "Respuesta"


@dataclass(frozen=True)
class _Answer:
    option_id: str
    label: str
    description: str
    next: str


@dataclass(frozen=True)
class AnswerVM:
    index: int  # position in the one ordered list (what every handler takes)
    label: str
    does: str  # «Muestra tus productos», «Responde con un mensaje»…
    preview: str  # one line of what the customer gets
    text: str  # the editable text (message / hand-off message); "" otherwise
    text_editable: bool
    is_products: bool
    status_label: str
    status_tone: str
    gaps_line: str  # «Falta: hora de abrir · hora de cerrar», "" when nothing is missing
    has_gaps: bool
    label_count: str  # «9 de 20»
    label_error: str
    text_error: str
    is_button: bool
    can_up: bool
    can_down: bool


@dataclass(frozen=True)
class SuggestionVM:
    key: str
    label: str


@dataclass(frozen=True)
class AnswersVM:
    buttons: list[AnswerVM]  # the answers that are reply buttons
    rows: list[AnswerVM]  # the answers inside «Más preguntas»
    count: int
    has_more: bool  # the third button is «Más preguntas»
    rows_count: str  # «5 de 10»
    full: bool
    blocking: bool  # a name too long / repeated, or an answer without text
    shows_products: bool  # an answer opens the catalog («Ver menú y pedir»)
    name_issue: bool  # the blocking part that is a name (not «datos por completar»)
    with_gaps: list[str]  # names of the answers with something to complete, in order
    suggestions: list[SuggestionVM]


EMPTY_ANSWERS = AnswersVM(
    buttons=[],
    rows=[],
    count=0,
    has_more=False,
    rows_count=f"0 de {MAX_LIST_ROWS}",
    full=False,
    blocking=False,
    shows_products=False,
    name_issue=False,
    with_gaps=[],
    suggestions=[],
)


def _more_index(form: MenuForm, start: NodeForm) -> int | None:
    """The start button that opens «Más preguntas»: a button leading to a list that
    Qualify laid out (its option id or the list's id is the «Más preguntas» one). A list an
    older menu built by hand («Ver categorías») is not it: that button is one more answer
    and its list keeps the schema's own rules."""
    for i, option in enumerate(start.options):
        target = _find(form, option.next)
        if target is None or form.nodes[target].kind != KIND_LIST:
            continue
        # Generated fallbacks are slugs («mas-preguntas-7a3f»): compare without hyphens.
        option_id, node_id = option.option_id.replace("-", "_"), option.next.replace("-", "_")
        if option_id.startswith(MORE_OPTION_ID) or node_id.startswith(MORE_NODE_ID):
            return i
    return None


def read_answers(form: MenuForm) -> list[_Answer]:
    """The one ordered list: start buttons (minus «Más preguntas»), then its rows."""
    start_i = _start(form)
    if start_i is None or form.nodes[start_i].kind != KIND_BUTTONS:
        return []
    start = form.nodes[start_i]
    more_i = _more_index(form, start)
    answers = [
        _Answer(o.option_id, o.label, "", o.next)
        for i, o in enumerate(start.options)
        if i != more_i
    ]
    if more_i is not None:
        more = form.nodes[_find(form, start.options[more_i].next)]  # type: ignore[index]
        answers.extend(_Answer(o.option_id, o.label, o.description, o.next) for o in more.options)
    return answers


def _drop_node(form: MenuForm, node_id: str) -> MenuForm:
    """Remove a step nothing leads to any more (never the start or the fallback)."""
    if node_id in (form.start_node, form.fallback_node) or node_id in referenced_node_ids(form):
        return form
    return replace(form, nodes=[n for n in form.nodes if n.node_id != node_id])


def write_answers(form: MenuForm, answers: Sequence[_Answer]) -> MenuForm:
    """Lay `answers` out by the rule: ≤ 3 → all buttons; more → 2 buttons + «Más
    preguntas» with the rest (at most `MAX_ANSWERS`). With none left the start step
    becomes a plain message (a buttons step needs one button); the first answer added
    turns it back."""
    start_i = _start(form)
    if start_i is None:
        return form
    answers = list(answers)[:MAX_ANSWERS]
    start = form.nodes[start_i]
    more_i = _more_index(form, start) if start.kind == KIND_BUTTONS else None
    more_option = start.options[more_i] if more_i is not None else None
    more_node_i = _find(form, more_option.next) if more_option is not None else None
    if not answers:
        text_start = replace(change_kind(start, KIND_TEXT), options=[], next=NONE_VALUE)
        form = _put(form, start_i, text_start)
        return _drop_node(form, more_option.next) if more_option is not None else form
    if start.kind != KIND_BUTTONS:
        start = change_kind(start, KIND_BUTTONS)
        if not start.body.strip():
            start = replace(start, body=_DEFAULT_QUESTION)
        form = _put(form, start_i, start)

    def button(a: _Answer) -> OptionForm:
        return OptionForm(a.option_id, a.label, "", a.next, "")

    if len(answers) <= MAX_BUTTONS:
        form = _set_node(form, start_i, options=[button(a) for a in answers])
        return _drop_node(form, more_option.next) if more_option is not None else form
    buttons, rows = answers[:BUTTONS_WITH_MORE], answers[BUTTONS_WITH_MORE:]
    if more_node_i is None:
        node_id = (
            MORE_NODE_ID if _find(form, MORE_NODE_ID) is None else fresh_node_id(form, MORE_LABEL)
        )
        node = replace(
            new_node(KIND_LIST, node_id, MORE_LABEL), body=MORE_BODY, button_label=MORE_BUTTON
        )
        form = replace(form, nodes=[*form.nodes, node])
        more_node_i = len(form.nodes) - 1
    more_node = form.nodes[more_node_i]
    section = next((o.section for o in more_node.options if o.section.strip()), MORE_SECTION)
    form = _set_node(
        form,
        more_node_i,
        options=[OptionForm(a.option_id, a.label, a.description, a.next, section) for a in rows],
    )
    if more_option is None:
        taken = {a.option_id for a in answers}
        option_id = (
            MORE_OPTION_ID if MORE_OPTION_ID not in taken else new_option_id(MORE_OPTION_ID, taken)
        )
        more_option = OptionForm(option_id, MORE_LABEL, "", more_node.node_id, "")
    return _set_node(form, start_i, options=[*(button(a) for a in buttons), more_option])


def _put(form: MenuForm, index: int, node: NodeForm) -> MenuForm:
    nodes = list(form.nodes)
    nodes[index] = node
    return replace(form, nodes=nodes)


def answers_move(form: MenuForm, index: int, delta: int) -> MenuForm:
    """«Subir» / «Bajar»: swap an answer with its neighbour (ids travel with them)."""
    answers = read_answers(form)
    other = index + delta
    if delta not in (-1, 1) or not 0 <= index < len(answers) or not 0 <= other < len(answers):
        return form
    answers[index], answers[other] = answers[other], answers[index]
    return write_answers(form, answers)


def move_hits_button_limit(count: int, index: int, delta: int) -> bool:
    """«Subir» on the first answer of «Más preguntas»: the screen explains the limit and
    offers to move the last button down instead of moving silently (spec §3)."""
    return count > MAX_BUTTONS and index == BUTTONS_WITH_MORE and delta == -1


def answers_remove(form: MenuForm, index: int) -> MenuForm:
    """«Quitar esta respuesta». Its message step goes too, with the keywords, shortcuts
    and commands that led only there («tus clientes ya no la verán»); the catalog steps,
    the start and the fallback are kept."""
    answers = read_answers(form)
    if not 0 <= index < len(answers):
        return form
    removed = answers.pop(index)
    form = write_answers(form, answers)
    target_i = _find(form, removed.next)
    if target_i is None or removed.next in (form.start_node, form.fallback_node):
        return form
    if form.nodes[target_i].kind not in (KIND_TEXT, KIND_HANDOFF):
        return form
    if any(a.next == removed.next for a in answers):
        return form
    form = replace(
        form,
        keywords=[k for k in form.keywords if k.node != removed.next],
        ice_breakers=[ib for ib in form.ice_breakers if ib.node != removed.next],
        commands=[c for c in form.commands if c.node != removed.next],
    )
    return _drop_node(form, removed.next)


def answers_add(form: MenuForm, key: str) -> tuple[MenuForm, int]:
    """«Agregar otra respuesta»: a one-tap suggestion, «Ver menú y pedir» back, or
    «Escribir la mía» (no name, no text). Returns the form and the new answer's index
    (-1 when the list is full or `key` is unknown)."""
    answers = read_answers(form)
    if len(answers) >= MAX_ANSWERS:
        return form, -1
    starter = next((s for s in STARTER_ANSWERS if s.key == key), None)
    if key == SUGGESTION_PRODUCTS or (starter is not None and starter.kind == "products"):
        form, target = ensure_products(form)
        label = _PRODUCTS_LABEL
    elif starter is not None and starter.kind == "person":
        form, target = ensure_person(form)
        label = starter.label
    elif starter is not None:
        # A removed starter answer comes back with the text it was born with.
        kind = KIND_HANDOFF if starter.kind == "handoff" else KIND_TEXT
        node = replace(
            new_node(kind, fresh_node_id(form, starter.label), starter.label), body=starter.text
        )
        if kind == KIND_HANDOFF:
            node = replace(node, reason="customer_request")
        form, target = replace(form, nodes=[*form.nodes, node]), node.node_id
        label = starter.label
    else:
        found = next((s for s in _SUGGESTIONS if s[0] == key), None)
        if found is None and key != SUGGESTION_CUSTOM:
            return form, -1
        label, text = (found[1], found[2]) if found is not None else ("", "")
        title = label or _CUSTOM_TITLE
        node = replace(new_node(KIND_TEXT, fresh_node_id(form, title), title), body=text)
        form, target = replace(form, nodes=[*form.nodes, node]), node.node_id
    taken = {a.option_id for a in answers} | {MORE_OPTION_ID}
    answer = _Answer(new_option_id(label or "respuesta", taken), label, "", target)
    return write_answers(form, [*answers, answer]), len(answers)


def answer_set_label(form: MenuForm, index: int, label: str) -> MenuForm:
    """Rename an answer; a message step named after it is renamed along (its name in
    «Más opciones»), its id never."""
    answers = read_answers(form)
    if not 0 <= index < len(answers):
        return form
    old = answers[index]
    answers[index] = replace(old, label=label)
    form = write_answers(form, answers)
    target_i = _find(form, old.next)
    if target_i is not None and form.nodes[target_i].kind in (KIND_TEXT, KIND_HANDOFF):
        node = form.nodes[target_i]
        if node.title.strip() in (old.label.strip(), _CUSTOM_TITLE) and label.strip():
            form = _set_node(form, target_i, title=label.strip()[:60])
    return form


def answer_set_text(form: MenuForm, index: int, text: str) -> MenuForm:
    answers = read_answers(form)
    if not 0 <= index < len(answers):
        return form
    target_i = _find(form, answers[index].next)
    if target_i is None or form.nodes[target_i].kind not in (KIND_TEXT, KIND_HANDOFF):
        return form
    return _set_node(form, target_i, body=text)


def gaps_line(names: Sequence[str]) -> str:
    return "Falta: " + " · ".join(names) if names else ""


def _answer_vm(
    form: MenuForm,
    answer: _Answer,
    index: int,
    count: int,
    *,
    catalog_count: int,
    taken: Mapping[str, int],
    option_errors: Mapping[str, str],
    guided_rules: bool,
) -> AnswerVM:
    target_i = _find(form, answer.next)
    target = form.nodes[target_i] if target_i is not None else None
    kind = target.kind if target is not None else ""
    is_products = kind == KIND_PRODUCTS
    text_editable = kind in (KIND_TEXT, KIND_HANDOFF)
    text = target.body if target is not None and text_editable else ""
    if is_products:
        does, preview = "Muestra tus productos", "Tus productos con su precio"
    elif kind == KIND_TEXT:
        does, preview = "Responde con un mensaje", excerpt(text)
    elif kind == KIND_HANDOFF:
        person = answer.next == form.fallback_node
        does = "Te pasa el chat" if person else "Responde y te pasa el chat"
        preview = excerpt(text)
    elif target is not None:
        does = "Muestra otros botones"
        preview = " · ".join(o.label for o in target.options if o.label.strip())
    else:
        does, preview = "Aún no hace nada", ""
    label = answer.label.strip()
    label_error = ""
    if not label:
        label_error = REQUIRED
    elif guided_rules and len(answer.label) > ANSWER_LABEL_MAX:
        is_row = count > MAX_BUTTONS and index >= BUTTONS_WITH_MORE
        label_error = ANSWER_ROW_NAME_TOO_LONG if is_row else ANSWER_NAME_TOO_LONG
    elif guided_rules and taken.get(normalize_keyword(label), 0) > 1:
        label_error = ANSWER_NAME_TAKEN.format(name=label)
    else:
        label_error = option_errors.get("label", "") or option_errors.get("next", "")
    text_error = ""
    if text_editable and not text.strip():
        text_error = ANSWER_TEXT_MISSING
    elif target is not None and text_editable:
        text_error = target.errors.get("body", "")
    gaps = find_gaps(text)
    if gaps or label_error or text_error or (is_products and catalog_count == 0):
        status = STATUS_MISSING  # a gap blocks publishing: never shown as «Sugerida»
    elif text in SUGGESTED_TEXTS:
        status = STATUS_SUGGESTED
    else:
        status = STATUS_READY
    status_label, status_tone = _STATUS[status]
    return AnswerVM(
        index=index,
        label=answer.label,
        does=does,
        preview=preview,
        text=text,
        text_editable=text_editable,
        is_products=is_products,
        status_label=status_label,
        status_tone=status_tone,
        gaps_line=gaps_line(gaps),
        has_gaps=bool(gaps),
        label_count=f"{len(answer.label)} de {ANSWER_LABEL_MAX}",
        label_error=label_error,
        text_error=text_error,
        is_button=count <= MAX_BUTTONS or index < BUTTONS_WITH_MORE,
        can_up=index > 0,
        can_down=index < count - 1,
    )


def answers_view(form: MenuForm, catalog_count: int) -> AnswersVM:
    """Step 2 read off an annotated form (`validate_form(...).form`)."""
    answers = read_answers(form)
    count = len(answers)
    taken: dict[str, int] = {}
    for a in answers:
        key = normalize_keyword(a.label)
        if key:
            taken[key] = taken.get(key, 0) + 1
    # Schema messages of the answers' own options: the start step's and «Más preguntas»'.
    option_errors: dict[str, Mapping[str, str]] = {}
    start_i = _start(form)
    if start_i is not None and form.nodes[start_i].kind == KIND_BUTTONS:
        owners = [form.nodes[start_i]]
        more_i = _more_index(form, form.nodes[start_i])
        if more_i is not None:
            owners.append(form.nodes[_find(form, form.nodes[start_i].options[more_i].next)])  # type: ignore[index]
        for node in owners:
            for option in node.options:
                if option.errors:
                    option_errors.setdefault(option.option_id, option.errors)
    # The 20-letter and repeated-name rules are this step's own, for menus it laid out
    # (with «Más preguntas»); any other menu keeps only the schema's limits.
    guided_rules = False
    if start_i is not None and form.nodes[start_i].kind == KIND_BUTTONS:
        guided_rules = _more_index(form, form.nodes[start_i]) is not None
    vms = [
        _answer_vm(
            form,
            a,
            i,
            count,
            catalog_count=catalog_count,
            taken=taken,
            option_errors=option_errors.get(a.option_id, {}),
            guided_rules=guided_rules,
        )
        for i, a in enumerate(answers)
    ]
    has_more = count > MAX_BUTTONS
    rows = vms[BUTTONS_WITH_MORE:] if has_more else []
    # Removed starter answers come back first (with their first text), then the extras.
    present = {normalize_keyword(v.label) for v in vms}
    shows_products = any(v.is_products for v in vms)
    suggestions = [
        SuggestionVM(s.key, s.label)
        for s in STARTER_ANSWERS
        if (
            not shows_products
            if s.kind == "products"
            else normalize_keyword(s.label) not in present
        )
    ]
    suggestions.extend(
        SuggestionVM(key, label)
        for key, label, _text in _SUGGESTIONS
        if normalize_keyword(label) not in present
    )
    return AnswersVM(
        buttons=vms[:BUTTONS_WITH_MORE] if has_more else vms,
        rows=rows,
        count=count,
        has_more=has_more,
        rows_count=f"{len(rows)} de {MAX_LIST_ROWS}",
        full=count >= MAX_ANSWERS,
        blocking=any(v.label_error or v.text_error for v in vms),
        shows_products=shows_products,
        name_issue=any(v.label_error for v in vms),
        with_gaps=[v.label.strip() or "Sin nombre" for v in vms if v.has_gaps],
        suggestions=suggestions,
    )


def answers_without_gaps(form: MenuForm) -> MenuForm:
    """«Quitar las que faltan y publicar»: every answer with a gap goes."""
    for index in reversed(range(len(read_answers(form)))):
        answers = read_answers(form)
        target_i = _find(form, answers[index].next)
        if target_i is not None and find_gaps(form.nodes[target_i].body):
            form = answers_remove(form, index)
    return form


@dataclass(frozen=True)
class PublishGapsVM:
    """Step 4: what is still to complete before publishing (a gap never goes out)."""

    any: bool
    answers_text: str  # «2 respuestas tienen datos por completar: Horario y Formas de pago…»
    greeting: str  # «Tu saludo tiene datos por completar. Falta: …» (a gap in it)
    elsewhere: bool  # a gap outside the 4 steps (only «Más opciones» shows it)
    can_strip: bool  # «Quitar las que faltan y publicar» leaves nothing missing
    strip_text: str = ""  # «Se quitan Horario y Reservas. ¿Publicar sin ellas?»
    # m-24945866: WHICH data and WHERE, never just «hay datos por completar».
    detail: str = ""  # every gap: «Mensaje de bienvenida: falta nombre de tu negocio · …»
    elsewhere_text: str = ""  # GAPS_ELSEWHERE + «En «Pedido confirmado» falta: …»
    first_index: int = -1  # the first answer with a gap («Completarlas» opens it)
    block_reason: str = ""  # why «Publicar» is off: the answers, the welcome, or other data


NO_PUBLISH_GAPS = PublishGapsVM(False, "", "", False, False)


def first_gap_literal(text: str) -> str:
    """The first real gap as written («[minutos]»), "" when there is none: what
    «Completarlas» selects. An empty «[]» or a link's «[texto](…)» is not a gap
    (`find_gaps`), so it is never what gets selected."""
    names = find_gaps(text)
    if not names:
        return ""
    match = re.search(r"\[\s*" + re.escape(names[0]) + r"\s*\](?!\()", text)
    return match.group(0) if match else ""


def gaps_detail(places: Sequence[tuple[str, Sequence[str]]]) -> str:
    """«Domicilio: falta minutos · Reservas: falta cuánto tardas en responder»: each place
    with its gaps, in the order the customer meets them."""
    return " · ".join(f"{place}: falta {_join_names(names)}" for place, names in places if names)


def elsewhere_gaps_text(places: Sequence[tuple[str, Sequence[str]]]) -> str:
    """GAPS_ELSEWHERE, now naming where: «Hay datos por completar en partes del menú que
    no están en estos 4 pasos. En «Pedido confirmado» falta: tiempo de entrega.»"""
    where = [f"En «{place}» falta: {_join_names(names)}." for place, names in places if names]
    return " ".join([GAPS_ELSEWHERE, *where]) if where else ""


def strip_confirm_text(names: Sequence[str]) -> str:
    """The confirmation of «Quitar las que faltan y publicar»: nothing goes before it."""
    if not names:
        return ""
    if len(names) == 1:
        return f"Se quita {names[0]}. ¿Publicar sin ella?"
    return f"Se quitan {_join_names(names)}. ¿Publicar sin ellas?"


def _join_names(names: Sequence[str]) -> str:
    quoted = list(names)
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " y " + quoted[-1]


def answers_gap_text(places: Sequence[tuple[str, Sequence[str]]]) -> str:
    """ONE notice naming each answer and what it lacks: «2 respuestas tienen datos por
    completar. Domicilio: falta minutos · Reservas: falta cuánto tardas en responder. Así
    no se las mostramos a tus clientes.»"""
    if not places:
        return ""
    if len(places) == 1:
        head = "1 respuesta tiene datos por completar."
    else:
        head = f"{len(places)} respuestas tienen datos por completar."
    detail = gaps_detail(places)
    end = "" if detail.endswith(("…", ".")) else "."
    return f"{head} {detail}{end} Así no se las mostramos a tus clientes."


def publish_gaps(form: MenuForm, gaps: Sequence[Gap], *, strip_leaves_gaps: bool) -> PublishGapsVM:
    """`gaps` = `starter.definition_gaps` of the form's definition (what a customer can
    reach); `strip_leaves_gaps` = the same after `answers_without_gaps`."""
    if not gaps:
        return NO_PUBLISH_GAPS
    answers = read_answers(form)
    answer_nodes = {a.next for a in answers}
    by_node = {g.node_id: g.names for g in gaps}
    answer_places = [
        (index, a.label.strip() or UNNAMED_PLACE, by_node[a.next])
        for index, a in enumerate(answers)
        if a.next in by_node
    ]
    names = [label for _, label, _ in answer_places]
    greeting = next((g for g in gaps if g.node_id is None), None)
    elsewhere_places: list[tuple[str, Sequence[str]]] = []
    for g in gaps:
        if g.node_id is None or g.node_id in answer_nodes:
            continue
        if g.node_id == ENTRY_SHORTCUTS:
            place = SHORTCUTS_GAP_PLACE
        else:
            node_i = _find(form, g.node_id)
            title = form.nodes[node_i].title.strip() if node_i is not None else ""
            place = title or UNNAMED_PLACE
        elsewhere_places.append((place, g.names))
    elsewhere = bool(elsewhere_places)
    answers_part = [(label, gap_names) for _, label, gap_names in answer_places]
    every_place = [
        *([(GREETING_GAP_PLACE, greeting.names)] if greeting is not None else []),
        *answers_part,
        *elsewhere_places,
    ]
    return PublishGapsVM(
        any=True,
        answers_text=answers_gap_text(answers_part),
        greeting=(
            f"Tu saludo tiene datos por completar. {gaps_line(greeting.names)}."
            if greeting is not None
            else ""
        ),
        elsewhere=elsewhere,
        can_strip=bool(names) and not strip_leaves_gaps,
        strip_text=strip_confirm_text(names),
        detail=gaps_detail(every_place),
        elsewhere_text=elsewhere_gaps_text(elsewhere_places),
        first_index=answer_places[0][0] if answer_places else -1,
        block_reason=(
            PUBLISH_NEEDS_ANSWERS
            if answers_part
            else PUBLISH_NEEDS_GREETING
            if greeting is not None and not elsewhere_places
            else PUBLISH_NEEDS_DATA
        ),
    )


def answers_summary(answers: AnswersVM, *, has_fallback: bool) -> str:
    """Step 4, in words: «Tu cliente verá tu saludo, 2 botones y «Más preguntas» con 5
    respuestas. Si escribe algo que el menú no entiende, te pasa el chat.»"""
    if answers.count == 0:
        head = "Tu cliente solo verá tu saludo."
    elif answers.has_more:
        rows = len(answers.rows)
        noun = "respuesta" if rows == 1 else "respuestas"
        head = (
            f"Tu cliente verá tu saludo, {BUTTONS_WITH_MORE} botones y «{MORE_LABEL}» con "
            f"{rows} {noun}."
        )
    else:
        noun = "botón" if answers.count == 1 else "botones"
        head = f"Tu cliente verá tu saludo y {answers.count} {noun}."
    if has_fallback:
        head += " Si escribe algo que el menú no entiende, te pasa el chat."
    return head


# --------------------------------------------------------------------------------------
# Menus and versions (display-ready)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuSummaryVM:
    menu_id: str
    name: str
    published_label: str  # «Publicado: v3» / «Sin publicar»
    is_published: bool
    is_paused: bool
    status_label: str
    status_tone: str
    updated_at: str  # PRE-FORMATTED


@dataclass(frozen=True)
class MenuVersionVM:
    version_id: str
    label: str  # «Versión 3»
    created_at: str  # PRE-FORMATTED
    published_at: str  # PRE-FORMATTED, "" when never published
    is_live: bool  # the version the number runs now


def menu_status(*, published: bool, paused: bool) -> tuple[str, str]:
    """(label, tone) of a menu on its number."""
    if not published:
        return "Sin publicar", "neutral"
    if paused:
        return "En pausa", "warn"
    return "Respondiendo en tu WhatsApp", "ok"


def build_menu_summary(
    *,
    menu_id: str,
    name: str,
    published_version: int | None,
    is_paused: bool,
    updated_at: datetime | None,
) -> MenuSummaryVM:
    published = published_version is not None
    label, tone = menu_status(published=published, paused=is_paused)
    return MenuSummaryVM(
        menu_id=menu_id,
        name=name,
        published_label=f"Publicado: versión {published_version}" if published else "Sin publicar",
        is_published=published,
        is_paused=is_paused,
        status_label=label,
        status_tone=tone,
        updated_at=format_timestamp(updated_at, ""),
    )


def build_version_vm(
    *,
    version_id: str,
    version: int,
    created_at: datetime | None,
    published_at: datetime | None,
    is_live: bool,
) -> MenuVersionVM:
    return MenuVersionVM(
        version_id=version_id,
        label=f"Versión {version}",
        created_at=format_timestamp(created_at, ""),
        published_at=format_timestamp(published_at, ""),
        is_live=is_live,
    )


EMPTY_MENU = MenuSummaryVM(
    menu_id="",
    name="",
    published_label="",
    is_published=False,
    is_paused=False,
    status_label="",
    status_tone="neutral",
    updated_at="",
)

MAX_MENU_NAME_CHARS = 80


def validate_menu_name(name: str, existing: Sequence[str]) -> str:
    """Spanish copy for a bad «Nuevo menú» name, "" when it can be created. Mirrors
    `uq_wa_menu_phone_name` (case-insensitive per number) and the not-blank CHECK."""
    cleaned = name.strip()
    if not cleaned:
        return "Ponle un nombre al menú."
    if len(cleaned) > MAX_MENU_NAME_CHARS:
        return f"El nombre admite hasta {MAX_MENU_NAME_CHARS} caracteres."
    if cleaned.casefold() in {e.strip().casefold() for e in existing}:
        return "Ya hay un menú con ese nombre en este número."
    return ""


# --------------------------------------------------------------------------------------
# Publishing → banner copy
# --------------------------------------------------------------------------------------

PUBLISH_OK = (
    "Listo: tu WhatsApp ya responde con este menú y muestra su bienvenida, atajos y comandos."
)

# m-24842995: one main action. «Publicar en mi WhatsApp» saves the editor (when it has
# changes) and publishes that version after this confirmation; «Guardar sin publicar» is
# the secondary path. The copy says whose words go out (the owner's) and who takes the
# chat (the owner) — never that Qualify answers on its own (guide N13).
PUBLISH_BUTTON = "Publicar en mi WhatsApp"
SAVE_ONLY_BUTTON = "Guardar sin publicar"
PUBLISH_CONFIRM_BUTTON = "Sí, publicar"
PUBLISH_CONFIRM = (
    "Al publicar, tu WhatsApp responde con los mensajes que tú escribiste en este menú, "
    "nada más. Puedes tomar el control de cualquier chat desde Chats."
)
PUBLISH_CONFIRM_SAVES = "Primero guardamos tus cambios como una versión nueva."
PUBLISH_CONFIRM_BACK_TO = "Tu WhatsApp vuelve a responder con la versión {n}."
PUBLISH_CONFIRM_STARTS_WITH = "Tu WhatsApp empieza a responder con la versión {n}."
PUBLISH_CONFIRM_RESEND = (
    "Este menú ya está respondiendo. Volvemos a enviar a WhatsApp la bienvenida, los "
    "atajos y los comandos."
)
PUBLISH_CONFIRM_REPLACES = "Tu menú «{name}» deja de responder y este toma su lugar."
PUBLISH_CONFIRM_PAUSED = (
    "Tu menú está en pausa: después de publicar, tócalo en «Reanudar el menú» para que responda."
)
NEXT_STEP_QR = "Haz que te escriban: crea tu código QR para tu local o tus redes"
# Publishing keeps the pause (the backend does not touch it): «listo» would be false.
PUBLISHED_BUT_PAUSED = "Publicamos el menú, pero está en pausa: no responde hasta que lo reanudes."
RESUME_BUTTON = "Reanudar el menú"


def publish_confirm_lines(
    *,
    dirty: bool,
    version: MenuVersionVM | None,
    other_published_menu: str,
    paused: bool = False,
) -> list[str]:
    """The case-specific lines under `PUBLISH_CONFIRM`: what happens to the version on
    screen (`version` is the saved one the editor shows; ignored while `dirty`, since a
    new one is saved first), then — only when another menu of the number is the one
    answering — that it gets replaced, and — only when this menu is paused — that it
    stays paused until resumed (so «ya está respondiendo» is not said of it)."""
    lines: list[str] = []
    if dirty:
        lines.append(PUBLISH_CONFIRM_SAVES)
    elif version is not None:
        number = version.label.removeprefix("Versión ").strip()
        if version.is_live:
            if not paused:
                lines.append(PUBLISH_CONFIRM_RESEND)
        elif version.published_at:
            lines.append(PUBLISH_CONFIRM_BACK_TO.format(n=number))
        else:
            lines.append(PUBLISH_CONFIRM_STARTS_WITH.format(n=number))
    if other_published_menu.strip():
        lines.append(PUBLISH_CONFIRM_REPLACES.format(name=other_published_menu.strip()))
    if paused:
        lines.append(PUBLISH_CONFIRM_PAUSED)
    return lines


def can_publish(
    *, has_menu: bool, error_count: int, dirty: bool, editing_version_id: str, busy: bool
) -> bool:
    """Whether «Publicar en mi WhatsApp» can run: an open menu with nothing to fix, and
    something to publish — the editor's changes (saved first) or the saved version the
    editor shows. Re-publishing the live version is allowed: it re-sends the shortcuts
    to WhatsApp, which is what the partial-failure banner asks for."""
    if not has_menu or busy or error_count > 0:
        return False
    return dirty or bool(editing_version_id)


PUBLISH_PARTIAL = "Tu WhatsApp ya responde con este menú, pero no tomó los atajos de inicio."


def publish_notice(
    *,
    graph_ok: bool,
    is_auth_error: bool = False,
    rejected_locally: bool = False,
) -> tuple[str, str]:
    """(message, tone) after «Publicar en mi WhatsApp». The menu answers in every case —
    the database publish happens first and is kept; only WhatsApp's copy of the shortcuts
    can lag. The banner says what to do next in the owner's words: never Meta's text and
    never Meta's code (the provider logs the code)."""
    if graph_ok:
        return PUBLISH_OK, "ok"
    if rejected_locally:
        return (
            f"{PUBLISH_PARTIAL} Quita los emojis o símbolos de los atajos y vuelve a publicar.",
            "warn",
        )
    if is_auth_error:
        return f"{PUBLISH_PARTIAL} {WHATSAPP_RECONNECT_HINT}", "error"
    return f"{PUBLISH_PARTIAL} Vuelve a tocar «{PUBLISH_BUTTON}» en un momento.", "warn"


# --------------------------------------------------------------------------------------
# Phone preview
# --------------------------------------------------------------------------------------

REPLY_BUTTON = "button"
REPLY_LIST = "list"

_HANDOFF_REASONS: dict[str, str] = {
    "order_confirmed": "pedido confirmado",
    "customer_request": "el cliente pidió una persona",
    "unknown_input": "el menú no entendió la respuesta",
}


@dataclass(frozen=True)
class PreviewChoiceVM:
    reply_kind: str  # REPLY_BUTTON / REPLY_LIST
    reply_id: str
    title: str
    description: str
    section: str  # the section title on the FIRST row of each section, else ""


@dataclass(frozen=True)
class PreviewMessageVM:
    key: str
    direction: str  # "in" = the customer, "out" = the menu, "note" = what Qualify did
    text: str
    choices: list[PreviewChoiceVM] = field(default_factory=list)
    is_list: bool = False
    list_label: str = ""


def handoff_note(action: Handoff) -> str:
    """What the preview shows when the menu hands the chat to a person."""
    reason = _HANDOFF_REASONS.get(action.reason, action.reason)
    lines = [f"Pasa a una persona ({reason}). El menú queda en pausa en este chat."]
    summary = action.summary
    order = summary.get("order") or []
    if order:
        total, currency = order_total(order)
        lines.append("Pedido:")
        lines += [f"· {int(line.get('qty', 1))} x {line.get('name', '')}" for line in order]
        lines.append(f"Total: {format_money(total, currency)}")
    for key, value in (summary.get("collected") or {}).items():
        shown = "Sí" if value is True else "No" if value is False else str(value)
        lines.append(f"{key}: {shown}")
    return "\n".join(lines)


def _list_choices(action: SendList) -> list[PreviewChoiceVM]:
    choices: list[PreviewChoiceVM] = []
    for section in action.sections:
        for k, row in enumerate(section.rows):
            choices.append(
                PreviewChoiceVM(
                    reply_kind=REPLY_LIST,
                    reply_id=row.id,
                    title=row.title,
                    description=row.description or "",
                    section=section.title if k == 0 else "",
                )
            )
    return choices


def actions_to_messages(
    actions: Sequence[OutboundAction], start_index: int
) -> list[PreviewMessageVM]:
    """The engine's outbound actions as chat bubbles; `SetContext` is not a message."""
    messages: list[PreviewMessageVM] = []
    for action in actions:
        key = f"m{start_index + len(messages)}"
        if isinstance(action, SendText):
            messages.append(PreviewMessageVM(key=key, direction="out", text=action.body))
        elif isinstance(action, SendButtons):
            messages.append(
                PreviewMessageVM(
                    key=key,
                    direction="out",
                    text=action.body,
                    choices=[
                        PreviewChoiceVM(REPLY_BUTTON, b.id, b.title, "", "") for b in action.buttons
                    ],
                )
            )
        elif isinstance(action, SendList):
            messages.append(
                PreviewMessageVM(
                    key=key,
                    direction="out",
                    text=action.body,
                    choices=_list_choices(action),
                    is_list=True,
                    list_label=action.button_label,
                )
            )
        elif isinstance(action, Handoff):
            messages.append(PreviewMessageVM(key=key, direction="note", text=handoff_note(action)))
    return messages


@dataclass(frozen=True)
class PreviewTurn:
    messages: list[PreviewMessageVM]  # the customer's bubble + the menu's answer
    state: ThreadMenuState
    handed_off: bool


def preview_turn(
    definition: MenuDefinition,
    state: ThreadMenuState,
    inbound: Inbound,
    catalog: Sequence[CatalogItem],
    *,
    shown_text: str,
    start_index: int,
) -> PreviewTurn:
    """One customer move in the preview: what they «sent» (`shown_text` — the typed text
    or the tapped option's title) and the engine's real answer for it."""
    result = step(definition, state, inbound, catalog=catalog)
    sent = PreviewMessageVM(key=f"m{start_index}", direction="in", text=shown_text)
    answer = actions_to_messages(result.actions, start_index + 1)
    return PreviewTurn([sent, *answer], result.state, result.handed_off)


def order_lines(state: ThreadMenuState) -> list[str]:
    """The order being built, for the panel under the phone."""
    order = state.order
    if not order:
        return []
    total, currency = order_total(order)
    lines = [f"{int(line.get('qty', 1))} x {line.get('name', '')}" for line in order]
    lines.append(f"Total: {format_money(total, currency)}")
    return lines


def catalog_note(count: int, brand: str) -> str:
    if count == 0:
        return (
            "La marca de este número no tiene productos activos: el paso «Productos del "
            "catálogo» responde con su texto de catálogo vacío."
        )
    noun = "producto activo" if count == 1 else "productos activos"
    return f"La vista previa usa el catálogo real: {count} {noun} de {brand}."


# ======================================================================================
# «Mejorar mi texto» / «Escribirlo por mí» on the greeting and each answer (m-24936838)
# ======================================================================================
# Spec: docs/ux-whatsapp-respuestas-de-siempre.md §5–§6. The button is named like the
# generator's («Mejorar mi texto», founder 2026-11): one name for the same help.

SUGGEST_IMPROVE: Final = "Mejorar mi texto"
SUGGEST_WRITE: Final = "Escribirlo por mí"
SUGGEST_AGAIN: Final = "Otra versión"
SUGGEST_UNDO: Final = "Deshacer"
# Neutral while writing: whether the brand has an identity is only known from the result
# (the result line then names the style).
SUGGEST_WRITING: Final = "Escribiendo tu texto…"
SUGGEST_DONE: Final = "Lo escribimos con tu forma de hablar. Revísalo."
# An answer already shows «Falta: …» under its field (m-24936836): no second notice.
SUGGEST_DONE_GAPS: Final = (
    "Lo escribimos con tu forma de hablar. Revísalo y completa lo que falta antes de publicar."
)
SUGGEST_NEUTRAL: Final = (
    "Todavía no sabemos cómo habla tu marca, así que lo escribimos neutro. Para que suene a "
    "ti, completa Tu marca. Guardamos este texto. Cuando completes Tu marca, vuelve y toca "
    "«Mejorar mi texto»."
)
SUGGEST_GO_BRAND: Final = "Ir a Tu marca"
SUGGEST_FAILED: Final = (
    "No pudimos escribir la sugerencia ahora mismo. Tu texto sigue igual. Inténtalo en un momento."
)
SUGGEST_STALE: Final = "Cambiaste el texto mientras tanto. Vuelve a tocar «{label}»."
SUGGEST_NO_DATA: Final = (
    "Escribe primero los datos (por ejemplo, tus horarios) y lo redactamos con tu estilo."
)

SUGGEST_GREETING: Final = "greeting"
SUGGEST_ANSWER: Final = "answer"

# The fact names match the starter's gaps («[nombre de tu negocio]», «[dirección y
# barrio]»), so the model may fill exactly those gaps from them.
_FACT_BUSINESS: Final = "nombre de tu negocio"
_FACT_ADDRESS: Final = "dirección y barrio"
_FACT_CITY: Final = "ciudad"
_FACT_SECTOR: Final = "rubro"


@dataclass(frozen=True)
class SuggestVM:
    """What one field's «Mejorar mi texto» shows besides the button (its label and the
    busy state are separate vars: they follow the keystrokes and the event)."""

    has_proposal: bool = False  # the field holds the last proposal: «Deshacer» · «Otra versión»
    missing_line: str = ""  # «Dejamos [hora de cerrar] porque no escribiste ese dato…»
    warnings: list[str] = field(default_factory=list)
    neutral: bool = False  # no brand identity: the «Tu marca» hint
    error: str = ""


NO_SUGGESTION = SuggestVM()


def suggest_label(text: str) -> str:
    """«Escribirlo por mí» on an empty field, «Mejorar mi texto» when it has text."""
    return SUGGEST_IMPROVE if (text or "").strip() else SUGGEST_WRITE


def suggest_writing_line() -> str:
    return SUGGEST_WRITING


def suggest_missing_line(missing: Sequence[str]) -> str:
    """§5 «Hueco por dato faltante»: the gaps the proposal kept, named as in the text."""
    names = [m.strip().strip("[]").strip() for m in missing]
    names = [n for i, n in enumerate(names) if n and n not in names[:i]]
    if not names:
        return ""
    gaps = [f"[{n}]" for n in names]
    joined = gaps[0] if len(gaps) == 1 else ", ".join(gaps[:-1]) + " y " + gaps[-1]
    if len(gaps) == 1:
        return f"Dejamos {joined} porque no escribiste ese dato. Complétalo antes de publicar."
    return f"Dejamos {joined} porque no escribiste esos datos. Complétalos antes de publicar."


def suggest_proposal_vm(
    missing: Sequence[str], warnings: Sequence[str], neutral: bool
) -> SuggestVM:
    return SuggestVM(
        has_proposal=True,
        missing_line=suggest_missing_line(missing),
        warnings=[w for w in warnings if w.strip()],
        neutral=neutral,
    )


def suggest_context(
    facts: StarterFacts,
    answers: Sequence[AnswerVM],
    *,
    exclude_index: int = -1,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    """`(facts, other_answers)` for a suggestion: the business facts Qualify already holds
    (the starter's) plus every other answer whose text is complete (no «[…]» gap), as a
    fact named after the answer; and the other answers' (name, text) for consistency.
    `exclude_index` is the answer being written (-1 for the greeting). Only what the
    owner typed or saved — never a guess."""
    out: list[tuple[str, str]] = []
    for name, value in (
        (_FACT_BUSINESS, facts.business_name),
        (_FACT_ADDRESS, facts.address),
        (_FACT_CITY, facts.city),
        (_FACT_SECTOR, facts.sector),
    ):
        if value.strip():
            out.append((name, value.strip()))
    others: list[tuple[str, str]] = []
    for answer in answers:
        if answer.index == exclude_index or not answer.label.strip():
            continue
        text = answer.text.strip() if answer.text_editable else answer.preview.strip()
        others.append((answer.label.strip(), text))
        if answer.text_editable and text and not find_gaps(text):
            out.append((answer.label.strip(), text))
    return tuple(out), tuple(others)


def suggest_has_input(current_text: str, facts: Sequence[tuple[str, str]]) -> bool:
    """§6 «Campo vacío y sin datos»: with no text and no fact to write from, ask first
    (the other answers' names alone are no data)."""
    return bool(current_text.strip()) or any(v.strip() for _n, v in facts)


# --------------------------------------------------------------------------------------
# «Cargar desde una foto o mi página» (m-24936840, spec §4 and §6)
# --------------------------------------------------------------------------------------
# Assisted, never autonomous: Claude PROPOSES facts with their quote; «Usar» only puts one
# into the form on screen (saved by the owner's own «Guardar» / «Publicar»), and products
# reach the catalog only through «Agregar los marcados a Tus productos».

IMPORT_CHOOSE: Final = "choose"  # «¿Tienes tu menú en una foto o en tu página?»
IMPORT_PHOTO: Final = "photo"  # «Sube una foto de tu menú o tu volante»
IMPORT_PAGE: Final = "page"  # «Pega el enlace de tu página»
IMPORT_READING: Final = "reading"  # «Estamos leyendo tu menú…»
IMPORT_REVIEW: Final = "review"  # «Esto encontramos en tu foto»
IMPORT_FAILED_PHASE: Final = "failed"  # a reason (SourceUnsupported) or «No pudimos leer…»
IMPORT_EMPTY_PHASE: Final = "empty"  # «No encontramos horarios, precios ni formas de pago…»
#: The picker's size limit: the reader's own (`import_ai.MAX_UPLOAD_BYTES`, 10 MB).
IMPORT_MAX_BYTES: Final = MAX_UPLOAD_BYTES
IMPORT_PHASES: Final = frozenset(
    {
        IMPORT_CHOOSE,
        IMPORT_PHOTO,
        IMPORT_PAGE,
        IMPORT_READING,
        IMPORT_REVIEW,
        IMPORT_FAILED_PHASE,
        IMPORT_EMPTY_PHASE,
    }
)

FACT_PENDING: Final = "pending"
FACT_USED: Final = "used"
FACT_SKIPPED: Final = "skipped"
#: A fact's `kind` (`import_ai.FoundFact.kind`, m-24945867): a `value` fills a gap; a
#: `sentence` is an explanation that can only become the answer's whole text.
FACT_VALUE: Final = "value"
FACT_SENTENCE: Final = "sentence"

IMPORT_OFFER_TITLE: Final = "¿Tienes tu menú en una foto o en tu página?"
IMPORT_OFFER_HELP: Final = (
    "Leemos tus horarios, tus precios y tus formas de pago, y tú decides qué usar."
)
IMPORT_PHOTO_CARD: Final = "Una foto o PDF"
IMPORT_PHOTO_CARD_HELP: Final = "De tu menú impreso, tu volante o una captura de tu Instagram."
IMPORT_PAGE_CARD: Final = "Mi página web"
IMPORT_PAGE_CARD_HELP: Final = "Pega el enlace y leemos lo que ahí dice."
IMPORT_NOT_NOW: Final = "Ahora no"
IMPORT_LINK: Final = "Cargar desde una foto o mi página"
IMPORT_PHOTO_TITLE: Final = "Sube una foto de tu menú o tu volante"
IMPORT_PHOTO_HELP: Final = "Que se lean bien los precios. Sirve una foto, una captura o un PDF."
IMPORT_PHOTO_BUTTON: Final = "Elegir una foto o un PDF"
IMPORT_PAGE_TITLE: Final = "Pega el enlace de tu página"
IMPORT_PAGE_HELP: Final = "La página de tu negocio, con tu menú, tus horarios o tus formas de pago."
IMPORT_PAGE_LABEL: Final = "Enlace de tu página"
IMPORT_PAGE_PLACEHOLDER: Final = "Por ejemplo: bianki.com"
IMPORT_PAGE_BUTTON: Final = "Leer mi página"
IMPORT_PAGE_NEEDS_LINK: Final = "Pega el enlace de tu página."
IMPORT_PRIVACY: Final = "Solo leemos los datos de tu negocio; no publicamos nada."
IMPORT_READING_TEXT: Final = "Estamos leyendo tu menú… Toma menos de un minuto."
IMPORT_SLOW: Final = (
    "Está tardando más de lo normal. Puedes esperar o seguir con lo que ya sabemos."
)
IMPORT_CANCEL: Final = "Cancelar"
IMPORT_FAILED: Final = "No pudimos leer tu menú ahora mismo. Inténtalo de nuevo en un momento."
IMPORT_UPLOAD_FAILED: Final = "No pudimos recibir tu archivo. Vuelve a elegirlo."
IMPORT_REJECTED: Final = "Sube una foto (JPG, PNG o WEBP) o un PDF de tu menú, de hasta 10 MB."
IMPORT_EMPTY: Final = (
    "No encontramos horarios, precios ni formas de pago en {where}. Tu menú sigue como estaba."
)
IMPORT_REVIEW_HELP: Final = (
    "Revisa cada dato. Solo usamos lo que aceptes, y queda guardado cuando toques «Guardar»."
)
IMPORT_USE: Final = "Usar"
IMPORT_EDIT: Final = "Editar"
IMPORT_SKIP: Final = "No usar"
IMPORT_EDIT_DONE: Final = "Listo"
IMPORT_USE_SENTENCE: Final = "Usar este texto"
IMPORT_SENTENCE_NOTE: Final = "Si lo usas, tu respuesta «{label}» queda así:"
IMPORT_SENTENCE_CHECK: Final = "Revisa el texto: lo copiamos tal cual de {where}."
#: Under the field of «Editar»: what to write for each fact, to shorten a sentence.
IMPORT_EDIT_HINTS: Final[dict[str, str]] = {
    "hours": "Escribe solo el horario, por ejemplo: lunes a sábado, de 11:00 a 22:00",
    "address": "Escribe solo la dirección, por ejemplo: Calle 10 # 5-20, Centro",
    "delivery_zone": "Escribe solo la zona, por ejemplo: todo el centro",
    "delivery_cost": "Escribe solo el costo del envío, por ejemplo: gratis",
    "delivery_time": "Escribe solo el tiempo de entrega en minutos, por ejemplo: 30",
    "payment_methods": "Escribe solo las formas de pago, por ejemplo: efectivo y transferencia",
    "reservations": "Escribe solo cómo reservar, por ejemplo: con un día de anticipación",
}
IMPORT_USED: Final = "Lo usamos"
IMPORT_SKIPPED: Final = "No lo usamos"
IMPORT_GOES_TO: Final = "Así queda tu respuesta «{label}»:"
IMPORT_REPLACES: Final = "Cambiamos el texto de tu respuesta «{label}» por:"
IMPORT_COMES_BACK: Final = "Quitaste la respuesta «{label}». Si lo usas, vuelve con este texto:"
IMPORT_LIST_FULL: Final = (
    "Ya tienes {n} respuestas. Quita una para que «{label}» pueda volver con este dato."
)
IMPORT_NOT_FOUND: Final = "{label}: no lo encontramos. Queda para que lo completes tú."
IMPORT_DONE: Final = "Volver a tus respuestas"
IMPORT_NO_PRICE: Final = "Sin precio"
IMPORT_PRODUCTS_NEW_HELP: Final = (
    "Marca los que quieres agregar. Van sin foto: agrégala después en Tus productos."
)
IMPORT_ADD_BUTTON: Final = "Agregar los marcados a Tus productos"
IMPORT_CHECK_ALL: Final = "Marcar todos"
IMPORT_UNCHECK_ALL: Final = "Desmarcar todos"
IMPORT_OWN_CURRENCY: Final = "moneda de tu negocio"
#: The reader's own size message (`import_ai.REASON_TOO_BIG`), for a file the server
#: refuses before keeping it.
IMPORT_TOO_BIG: Final = REASON_TOO_BIG
IMPORT_ADD_FAILED: Final = (
    "No pudimos agregar tus productos ahora mismo. Inténtalo de nuevo en un momento."
)
IMPORT_ADD_NEEDS_BRAND: Final = (
    "Este número no tiene una marca con productos. Agrégalos en Tus productos."
)

_IMPORT_WHERE: Final = {"image": "tu foto", "pdf": "tu archivo", "url": "tu página"}
_IMPORT_THIS: Final = {"image": "esta foto", "pdf": "este archivo", "url": "esta página"}
_IMPORT_RETRY: Final = {"image": "Probar otra foto", "pdf": "Probar otro archivo"}
_IMPORT_WITHOUT: Final = {"url": "Seguir sin la página"}

#: What each fact is called on screen, and the starter answer («respuesta de siempre»)
#: whose gap it fills.
FACT_TITLES: Final[dict[str, str]] = {
    "hours": "Horario",
    "address": "Dirección",
    "delivery_zone": "Zona de domicilio",
    "delivery_cost": "Precio del domicilio",
    "delivery_time": "Tiempo de entrega",
    "payment_methods": "Formas de pago",
    "reservations": "Reservas",
}
FACT_ANSWERS: Final[dict[str, str]] = {
    "hours": "horario",
    "address": "ubicacion",
    "delivery_zone": "domicilio",
    "delivery_cost": "domicilio",
    "delivery_time": "domicilio",
    "payment_methods": "pagos",
    "reservations": "reservas",
}
# The starter's hours sentence (`starter.HOURS_TEXT`): the three gaps are one fact.
_HOURS_SPAN: Final = "de [qué días], de [hora de abrir] a [hora de cerrar]"
_WEEKDAYS: Final = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_ROUGH: Final = ("unos ", "unas ", "entre ", "de ", "aprox", "menos ", "mas ", "hasta ", "media ")
#: The folded starts of the gaps each fact fills (`[dirección y barrio]`, …).
_FACT_GAPS: Final[dict[str, tuple[str, ...]]] = {
    "address": ("direccion",),
    "delivery_zone": ("barrios", "zona"),
    "delivery_cost": ("precio del envio", "costo del envio"),
    "delivery_time": ("minutos",),
    "payment_methods": ("formas de pago",),
}
_IMPORT_GAP_RE = re.compile(r"\[([^\[\]\n]{1,80})\](?!\()")


def import_where(kind: str) -> str:
    """«tu foto» / «tu archivo» / «tu página»."""
    return _IMPORT_WHERE.get(kind, "tu foto")


def import_retry_label(kind: str) -> str:
    return _IMPORT_RETRY.get(kind, "Probar otro enlace")


def import_without_label(kind: str) -> str:
    return _IMPORT_WITHOUT.get(kind, "Seguir sin la foto")


def import_empty_text(kind: str) -> str:
    return IMPORT_EMPTY.format(where=_IMPORT_THIS.get(kind, "esta foto"))


def import_review_title(kind: str) -> str:
    return f"Esto encontramos en {import_where(kind)}"


def clean_fact_value(value: str) -> str:
    """One line, no brackets (a fact must never read as a gap), no closing period."""
    line = " ".join((value or "").split()).replace("[", "(").replace("]", ")")
    return line.rstrip(" .")[:200].rstrip()


def _sentence(value: str) -> str:
    text = clean_fact_value(value)
    return f"{text[:1].upper()}{text[1:]}." if text else ""


def _hours_phrase(value: str) -> str:
    folded = normalize_keyword(value)
    return f"de {value}" if folded.startswith(_WEEKDAYS) else value


def _replace_gap(text: str, starts: tuple[str, ...], value: str) -> str | None:
    """`text` with its first gap whose folded name starts with one of `starts` replaced
    by `value`; None when there is no such gap."""
    for match in _IMPORT_GAP_RE.finditer(text):
        if normalize_keyword(match.group(1)).startswith(starts):
            return text[: match.start()] + value + text[match.end() :]
    return None


def fill_fact(text: str, key: str, value: str) -> str | None:
    """The answer's text with `key`'s gap(s) filled with `value`; None when the text has
    no gap for it (already written by the owner). «Reservas» has no gap of its own (the
    starter's asks how long the owner takes to answer): the fact becomes the text."""
    v = clean_fact_value(value)
    if not v:
        return None
    if key == "reservations":
        return _sentence(v)
    if key == "hours":
        return text.replace(_HOURS_SPAN, _hours_phrase(v), 1) if _HOURS_SPAN in text else None
    if key == "delivery_time" and "unos [minutos] minutos" in text:
        folded = normalize_keyword(v)
        if folded.startswith(_ROUGH):
            phrase = v
        else:
            phrase = f"unos {v}" if "min" in folded or "hora" in folded else f"unos {v} minutos"
        return text.replace("unos [minutos] minutos", phrase, 1)
    if key == "delivery_cost" and "gratis" in normalize_keyword(v):
        span = "El envío cuesta [precio del envío]"
        if span in text:
            return text.replace(span, "El envío es gratis", 1)
    starts = _FACT_GAPS.get(key)
    return _replace_gap(text, starts, v) if starts else None


def _starter(key: str) -> Any:
    target = FACT_ANSWERS.get(key, "")
    return next((s for s in STARTER_ANSWERS if s.key == target), None)


def find_starter_answer(form: MenuForm, starter_key: str) -> int:
    """The index of the answer that is the starter's `starter_key` («horario»): by its
    option id or step id, else by its name (accents and case folded); -1 when the owner
    removed it."""
    starter = next((s for s in STARTER_ANSWERS if s.key == starter_key), None)
    answers = read_answers(form)
    for i, a in enumerate(answers):
        if a.option_id == starter_key or a.next == starter_key:
            return i
    if starter is not None:
        name = normalize_keyword(starter.label)
        for i, a in enumerate(answers):
            if normalize_keyword(a.label) == name:
                return i
    return -1


@dataclass(frozen=True)
class FactPlan:
    """What «Usar» on one fact would do: `mode` is `fill` (its gaps), `replace` (the
    answer is already written, or «Reservas»), `readd` (the owner removed the answer: it
    comes back with the fact), or `none` (cannot: the list is full)."""

    mode: str
    index: int  # the answer's index; -1 for `readd` / `none`
    label: str  # the answer's name («Horario»)
    text: str  # the answer's text after «Usar»


def fact_plan(form: MenuForm, key: str, value: str) -> FactPlan:
    starter = _starter(key)
    if starter is None:
        return FactPlan("none", -1, "", "")
    index = find_starter_answer(form, starter.key)
    if index < 0:
        text = fill_fact(starter.text, key, value) or ""
        if len(read_answers(form)) >= MAX_ANSWERS:
            return FactPlan("none", -1, starter.label, text)
        return FactPlan("readd" if text else "none", -1, starter.label, text)
    answer = read_answers(form)[index]
    target_i = _find(form, answer.next)
    if target_i is None or form.nodes[target_i].kind not in (KIND_TEXT, KIND_HANDOFF):
        return FactPlan("none", index, answer.label.strip() or starter.label, "")
    current = form.nodes[target_i].body
    label = answer.label.strip() or starter.label
    filled = fill_fact(current, key, value)
    if filled is not None and key != "reservations":
        return FactPlan("fill", index, label, filled)
    # Written by the owner (no gap left for this fact): the starter's text with the fact.
    text = filled if filled is not None else (fill_fact(starter.text, key, value) or "")
    return FactPlan("replace" if text and text != current else "none", index, label, text)


def _apply_plan(form: MenuForm, starter_key: str, plan: FactPlan) -> MenuForm:
    if plan.mode in ("fill", "replace"):
        return answer_set_text(form, plan.index, plan.text)
    if plan.mode == "readd":
        form, index = answers_add(form, starter_key)
        return answer_set_text(form, index, plan.text) if index >= 0 else form
    return form


def apply_fact(form: MenuForm, key: str, value: str) -> MenuForm:
    """«Usar»: the fact goes into its answer (a removed answer comes back with it)."""
    starter = _starter(key)
    if starter is None:
        return form
    return _apply_plan(form, starter.key, fact_plan(form, key, value))


# --- Sentences (m-24945867): an explanation is never pasted into a gap ---------------------

#: The gaps of «Domicilio» that a sentence did not cover stay as one line, worded as in
#: `starter.DELIVERY_TEXT`.
_DELIVERY_ZONE_LINE: Final = "Llevamos tu pedido a [barrios o zona]."
_DELIVERY_COST_TIME_LINE: Final = (
    "El envío cuesta [precio del envío] y tarda unos [minutos] minutos."
)
_DELIVERY_COST_LINE: Final = "El envío cuesta [precio del envío]."
_DELIVERY_TIME_LINE: Final = "El envío tarda unos [minutos] minutos."
_DELIVERY_KEYS: Final = ("delivery_zone", "delivery_cost", "delivery_time")


def row_kind(row: Mapping[str, str]) -> str:
    """A review row's kind; a row without one (older state) is a value."""
    return FACT_SENTENCE if row.get("kind") == FACT_SENTENCE else FACT_VALUE


def as_sentence(value: str) -> str:
    """One line, capitalised, closed by exactly one period («…entrega..» never)."""
    line = " ".join((value or "").split()).replace("[", "(").replace("]", ")")
    line = line.rstrip(" .")
    if not line:
        return ""
    line = f"{line[:1].upper()}{line[1:]}"
    return line if line.endswith(("!", "?", "…")) else f"{line}."


def starter_closing(text: str) -> str:
    """The starter text's last sentence when it sends the client to the menu («Para
    pedir, escribe *menú*.»); "" otherwise."""
    last = text.rsplit(". ", 1)[-1]
    return last if "*menú*" in last else ""


def _uncovered_line(starter_key: str, covered: set[str]) -> str:
    if starter_key != "domicilio":
        return ""
    zone, cost, time = (k not in covered for k in _DELIVERY_KEYS)
    lines = [_DELIVERY_ZONE_LINE] if zone else []
    if cost and time:
        lines.append(_DELIVERY_COST_TIME_LINE)
    elif cost:
        lines.append(_DELIVERY_COST_LINE)
    elif time:
        lines.append(_DELIVERY_TIME_LINE)
    return " ".join(lines)


def sentence_text(
    starter_key: str,
    sentences: Sequence[tuple[str, str]],
    used: Sequence[tuple[str, str]] = (),
) -> str:
    """The answer's whole text from its sentence facts (`(key, value)`, identical ones
    once): the sentences, then the starter's gaps none of them covers (a value already
    used fills its gap again), then the starter's closing line."""
    starter = next((s for s in STARTER_ANSWERS if s.key == starter_key), None)
    if starter is None:
        return ""
    seen: set[str] = set()
    parts: list[str] = []
    for _key, value in sentences:
        sentence = as_sentence(value)
        folded = normalize_keyword(sentence)
        if sentence and folded not in seen:
            seen.add(folded)
            parts.append(sentence)
    if not parts:
        return ""
    covered = {key for key, _value in sentences}
    line = _uncovered_line(starter_key, covered)
    for key, value in used:
        if key not in covered and line:
            line = fill_fact(line, key, value) or line
    if line:
        parts.append(line)
    closing = starter_closing(starter.text)
    if closing and not any("*menú*" in part for part in parts):  # never said twice
        parts.append(closing)
    return " ".join(parts)


def sentence_plan(
    form: MenuForm,
    starter_key: str,
    sentences: Sequence[tuple[str, str]],
    used: Sequence[tuple[str, str]] = (),
) -> FactPlan:
    """What «Usar este texto» would do: the answer's whole text becomes
    `sentence_text` (`replace`), a removed answer comes back with it (`readd`)."""
    starter = next((s for s in STARTER_ANSWERS if s.key == starter_key), None)
    if starter is None:
        return FactPlan("none", -1, "", "")
    text = sentence_text(starter_key, sentences, used)
    index = find_starter_answer(form, starter_key)
    if index < 0:
        if not text or len(read_answers(form)) >= MAX_ANSWERS:
            return FactPlan("none", -1, starter.label, text)
        return FactPlan("readd", -1, starter.label, text)
    answer = read_answers(form)[index]
    label = answer.label.strip() or starter.label
    target_i = _find(form, answer.next)
    if target_i is None or form.nodes[target_i].kind not in (KIND_TEXT, KIND_HANDOFF):
        return FactPlan("none", index, label, "")
    current = form.nodes[target_i].body
    return FactPlan("replace" if text and text != current else "none", index, label, text)


def sentence_group(rows: Sequence[Mapping[str, str]], index: int, editing: int = -1) -> list[int]:
    """The rows offered together with sentence row `index`: the sentences of the same
    answer with the same status. A row being edited stands alone (its new text may turn
    it into a value)."""
    if not 0 <= index < len(rows) or row_kind(rows[index]) != FACT_SENTENCE:
        return []
    if index == editing:
        return [index]
    head = rows[index]
    answer = FACT_ANSWERS.get(head["key"])
    if answer is None:
        return [index]
    return [
        i
        for i, r in enumerate(rows)
        if i != editing
        and row_kind(r) == FACT_SENTENCE
        and FACT_ANSWERS.get(r["key"]) == answer
        and r["status"] == head["status"]
    ]


def _used_values(rows: Sequence[Mapping[str, str]], answer: str) -> list[tuple[str, str]]:
    return [
        (r["key"], r["value"])
        for r in rows
        if row_kind(r) == FACT_VALUE
        and r["status"] == FACT_USED
        and FACT_ANSWERS.get(r["key"]) == answer
    ]


def group_plan(form: MenuForm, rows: Sequence[Mapping[str, str]], group: Sequence[int]) -> FactPlan:
    """`sentence_plan` for the rows of one `sentence_group`."""
    if not group:
        return FactPlan("none", -1, "", "")
    answer = FACT_ANSWERS.get(rows[group[0]]["key"], "")
    # A sentence of the same answer already used stays in the text (and covers its gap).
    used = {
        i
        for i, r in enumerate(rows)
        if row_kind(r) == FACT_SENTENCE
        and r["status"] == FACT_USED
        and FACT_ANSWERS.get(r["key"]) == answer
    }
    sentences = [(rows[i]["key"], rows[i]["value"]) for i in sorted(used | set(group))]
    return sentence_plan(form, answer, sentences, _used_values(rows, answer))


def apply_sentences(
    form: MenuForm, rows: Sequence[Mapping[str, str]], group: Sequence[int]
) -> MenuForm:
    """«Usar este texto»: the answer's text becomes the sentences."""
    if not group:
        return form
    answer = FACT_ANSWERS.get(rows[group[0]]["key"], "")
    return _apply_plan(form, answer, group_plan(form, rows, group))


@dataclass(frozen=True)
class ImportFactVM:
    index: int
    title: str  # «Horario», «Zona de domicilio»…
    value: str  # what goes into the answer (editable with «Editar»)
    evidence_line: str  # «“Lun a Dom 12m – 10pm”, de tu foto»
    note: str  # «Así queda tu respuesta «Horario»:»
    preview: str  # the answer's text after «Usar»
    status_label: str  # «Lo usamos» / «No lo usamos» / ""
    status_tone: str
    pending: bool
    editing: bool
    can_use: bool
    #: A sentence: «Usar este texto» (the answer's whole text), never in a gap.
    is_sentence: bool = False
    edit_hint: str = ""  # under the field of «Editar»: «Escribe solo la zona, …»
    used_note: str = ""  # after «Usar este texto»: «Revisa el texto: lo copiamos tal cual…»


@dataclass(frozen=True)
class ImportProductVM:
    index: int
    name: str
    price: str  # «COP 12.000», «12.000», «Sin precio»
    evidence_line: str
    checked: bool
    #: m-24955838 — «Combos» or «Sin categoría»; «Nueva» when the brand lacks it.
    category_label: str = "Sin categoría"
    category_new: bool = False
    editing_category: bool = False
    category_aria: str = ""  # «Cambiar la categoría de «Combo Vecino»: Combos»


@dataclass(frozen=True)
class ImportVM:
    kind: str  # "image" | "pdf" | "url"
    title: str  # «Esto encontramos en tu foto»
    source_line: str  # the filename or the page's host
    warnings: list[str]
    facts: list[ImportFactVM]
    not_found: list[str]  # «Domicilio: no lo encontramos. Queda para que lo completes tú.»
    has_products: bool
    products_title: str  # «Productos: 14 en tu foto»
    existing_line: str  # «9 ya están en Tus productos: no los cambiamos.»
    conflicts: list[str]  # one line per product whose price differs from the catalog
    new_products: list[ImportProductVM]
    checked_count: int
    checked_line: str  # «Marcamos los que tienen precio (14 de 22)»
    added_lines: list[str]  # what «Agregar los marcados…» did
    #: «Vamos a crear 4 categorías: …. Cámbialas si quieres.» (m-24955838)
    categories_line: str = ""


EMPTY_IMPORT = ImportVM(
    kind="",
    title="",
    source_line="",
    warnings=[],
    facts=[],
    not_found=[],
    has_products=False,
    products_title="",
    existing_line="",
    conflicts=[],
    new_products=[],
    checked_count=0,
    checked_line="",
    added_lines=[],
)


def fact_rows(facts: Sequence[Any]) -> list[dict[str, str]]:
    """Backend-var form of the proposal's facts (`FoundFact`), each `pending`."""
    return [
        {
            "key": f.key,
            "value": f.value,
            "evidence": f.evidence,
            "status": FACT_PENDING,
            "kind": FACT_SENTENCE if getattr(f, "kind", "") == FACT_SENTENCE else FACT_VALUE,
        }
        for f in facts
        if f.key in FACT_TITLES
    ]


def edited_kind(key: str, value: str) -> str:
    """The kind of a value the owner typed: the reader's own rule (`import_ai.fact_kind`),
    so a sentence shortened into «toda la ciudad» fills its gap."""
    return FACT_SENTENCE if fact_kind(key, value) == FACT_SENTENCE else FACT_VALUE


def product_rows(products: Sequence[Any]) -> list[dict[str, str]]:
    """Backend-var form of the proposal's products (`FoundProduct`): plain strings, the
    amount as text. Ticked by default only when it has a price."""
    return [
        {
            "name": p.name,
            "amount": str(p.price_amount) if p.price_amount is not None else "",
            "currency": p.price_currency or "",
            "description": p.description or "",
            "evidence": p.evidence or "",
            "checked": "1" if p.price_amount is not None else "",
            # m-24955838: the section the import proposes; editable in the review
            "category": getattr(p, "category", "") or "",
        }
        for p in products
    ]


def _money(amount: str, currency: str, own_currency: str = "") -> str:
    """The price as it would be saved: a source without an explicit currency (a bare
    «$») takes the business's own, and the row says so («COP 12.000 (moneda de tu
    negocio)») before anything is added."""
    if not amount:
        return IMPORT_NO_PRICE
    try:
        value = Decimal(amount)
    except (InvalidOperation, ValueError):
        return IMPORT_NO_PRICE
    if not currency and own_currency:
        return f"{format_money(value, own_currency)} ({IMPORT_OWN_CURRENCY})"
    return format_money(value, currency or None)


def _evidence_line(evidence: str | Sequence[str], kind: str) -> str:
    """«En tu foto dice: «Lun–Sáb 11–10»»; several quotes (identical ones once) are
    joined with «y»."""
    quotes: list[str] = []
    for raw in [evidence] if isinstance(evidence, str) else evidence:
        quote = " ".join(raw.split())
        if quote and quote not in quotes:
            quotes.append(quote)
    if not quotes:
        return ""
    return f"En {import_where(kind)} dice: " + " y ".join(f"«{q}»" for q in quotes)


def catalog_names(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """The brand's products by folded name (case and accents): the dedupe key."""
    return {normalize_keyword(str(r.get("name") or "")): r for r in rows}


def import_view(
    form: MenuForm,
    *,
    kind: str,
    label: str,
    warnings: Sequence[str],
    facts: Sequence[Mapping[str, str]],
    products: Sequence[Mapping[str, str]],
    catalog: Sequence[Mapping[str, Any]],
    editing: int = -1,
    added: Sequence[str] = (),
    own_currency: str = "",
    category_editing: int = -1,
) -> ImportVM:
    """The review (spec §4 c), re-read on every edit so each preview is the answer's text
    as it would be after «Usar»."""
    fact_vms: list[ImportFactVM] = []
    grouped: set[int] = set()
    for i, f in enumerate(facts):
        if i in grouped:
            continue
        key, value, status = f["key"], f["value"], f["status"]
        sentence = row_kind(f) == FACT_SENTENCE
        group = sentence_group(facts, i, editing) if sentence else [i]
        grouped.update(group)
        plan = group_plan(form, facts, group) if sentence else fact_plan(form, key, value)
        if plan.mode == "fill":
            note = IMPORT_GOES_TO.format(label=plan.label)
        elif plan.mode == "replace":
            template = IMPORT_SENTENCE_NOTE if sentence else IMPORT_REPLACES
            note = template.format(label=plan.label)
        elif plan.mode == "readd":
            note = IMPORT_COMES_BACK.format(label=plan.label)
        elif plan.label and len(read_answers(form)) >= MAX_ANSWERS:
            note = IMPORT_LIST_FULL.format(n=MAX_ANSWERS, label=plan.label)
        else:
            note = ""
        status_label, tone = {
            FACT_USED: (IMPORT_USED, "ok"),
            FACT_SKIPPED: (IMPORT_SKIPPED, "neutral"),
        }.get(status, ("", "neutral"))
        title = FACT_TITLES.get(key, key)
        if len(group) > 1:  # «Domicilio»: zone and cost offered as one text
            title = plan.label or title
        fact_vms.append(
            ImportFactVM(
                index=i,
                title=title,
                value=value,
                evidence_line=_evidence_line([facts[g].get("evidence", "") for g in group], kind),
                note=note,
                preview=plan.text if plan.mode != "none" else "",
                status_label=status_label,
                status_tone=tone,
                pending=status == FACT_PENDING,
                editing=i == editing and status == FACT_PENDING,
                can_use=plan.mode != "none" and bool(clean_fact_value(value)),
                is_sentence=sentence,
                edit_hint=IMPORT_EDIT_HINTS.get(key, ""),
                used_note=(
                    IMPORT_SENTENCE_CHECK.format(where=import_where(kind))
                    if sentence and status == FACT_USED
                    else ""
                ),
            )
        )
    # The answers still waiting for a datum this source did not have (spec mockup).
    found_answers = {FACT_ANSWERS[f["key"]] for f in facts if f["key"] in FACT_ANSWERS}
    not_found: list[str] = []
    for starter in STARTER_ANSWERS:
        if starter.key not in set(FACT_ANSWERS.values()) or starter.key in found_answers:
            continue
        index = find_starter_answer(form, starter.key)
        if index < 0:
            continue
        target_i = _find(form, read_answers(form)[index].next)
        if target_i is not None and find_gaps(form.nodes[target_i].body):
            name = read_answers(form)[index].label.strip() or starter.label
            not_found.append(IMPORT_NOT_FOUND.format(label=name))

    by_name = catalog_names(catalog)
    have_categories = {
        category_key(str(r.get("category") or "")) for r in catalog if r.get("category")
    }
    where = import_where(kind)
    existing = 0
    conflicts: list[str] = []
    new: list[ImportProductVM] = []
    for i, p in enumerate(products):
        price = _money(p.get("amount", ""), p.get("currency", ""), own_currency)
        known = by_name.get(normalize_keyword(p["name"]))
        if known is not None:
            existing += 1
            mine = known.get("price_amount")
            if p.get("amount") and mine is not None and Decimal(p["amount"]) != Decimal(str(mine)):
                theirs = _money(str(mine), str(known.get("price_currency") or ""))
                conflicts.append(
                    f"{known.get('name') or p['name']}: en {where} dice {price} y en Tus "
                    f"productos {theirs}. Dejamos el de Tus productos; si cambió, cámbialo ahí."
                )
            continue
        category = " ".join(str(p.get("category") or "").split())
        is_new = bool(category) and category_key(category) not in have_categories
        label_ = import_category_label(category)
        new.append(
            ImportProductVM(
                index=i,
                name=p["name"],
                price=price,
                evidence_line=_evidence_line(p.get("evidence", ""), kind),
                checked=bool(p.get("checked")),
                category_label=label_,
                category_new=is_new,
                editing_category=i == category_editing,
                category_aria=f"Cambiar la categoría de «{p['name']}»: {label_}",
            )
        )
    if existing == 1:
        existing_line = "1 ya está en Tus productos: no lo cambiamos."
    elif existing > 1:
        existing_line = f"{existing} ya están en Tus productos: no los cambiamos."
    else:
        existing_line = ""
    priced = sum(1 for p in new if p.price != IMPORT_NO_PRICE)
    checked_line = (
        f"Marcamos los que tienen precio ({priced} de {len(new)})" if len(new) > 1 else ""
    )
    return ImportVM(
        kind=kind,
        title=import_review_title(kind),
        source_line=label,
        warnings=list(warnings),
        facts=fact_vms,
        not_found=not_found,
        has_products=bool(products),
        products_title=f"Productos: {len(products)} en {where}" if products else "",
        existing_line=existing_line,
        conflicts=conflicts,
        new_products=new,
        checked_count=sum(1 for p in new if p.checked),
        checked_line=checked_line,
        added_lines=list(added),
        categories_line=import_categories_line(_new_category_names(new, have_categories)),
    )


def _new_category_names(rows: Sequence[ImportProductVM], have: set[str]) -> list[str]:
    """The categories «Agregar a mi menú» would create: those of the ticked products the
    brand does not have yet (one spelling each, case and accents ignored)."""
    out: dict[str, str] = {}
    for row in rows:
        if row.checked and row.category_new:
            out.setdefault(category_key(row.category_label), row.category_label)
    return [n for k, n in out.items() if k not in have]


def added_lines(added: Sequence[str], existing: Sequence[str], failed: Sequence[str]) -> list[str]:
    """What «Agregar los marcados a Tus productos» says when it is done."""
    lines: list[str] = []
    if len(added) == 1:
        lines.append("Agregamos 1 producto a Tus productos. Agrégale la foto cuando quieras.")
    elif added:
        lines.append(
            f"Agregamos {len(added)} productos a Tus productos. Agrégales la foto cuando quieras."
        )
    if existing:
        names = _join_names(list(existing))
        if len(existing) == 1:
            lines.append(f"{names} ya está en Tus productos: no lo cambiamos.")
        else:
            lines.append(f"{names} ya están en Tus productos: no los cambiamos.")
    if failed:
        lines.append(
            f"No pudimos agregar {_join_names(list(failed))}. Agrégalo a mano en Tus productos."
        )
    return lines


__all__ = [
    "starter_closing",
    "sentence_text",
    "sentence_plan",
    "sentence_group",
    "row_kind",
    "group_plan",
    "edited_kind",
    "as_sentence",
    "apply_sentences",
    "IMPORT_EDIT_HINTS",
    "IMPORT_SENTENCE_CHECK",
    "IMPORT_SENTENCE_NOTE",
    "IMPORT_USE_SENTENCE",
    "FACT_VALUE",
    "FACT_SENTENCE",
    "ACTION_MORE",
    "ACTION_MORE_LABEL",
    "ACTION_PERSON",
    "ACTION_PRODUCTS",
    "ACTION_TEXT",
    "ADDRESS_ASK",
    "ADDRESS_SKIP",
    "COLLECT_FIELDS",
    "COLLECT_VALIDATIONS",
    "EMPTY_GUIDED",
    "EMPTY_MENU",
    "GUIDED_ACTIONS",
    "GUIDED_HELP",
    "GUIDED_STEPS",
    "GUIDED_TITLES",
    "HANDOFF_REASONS",
    "KIND_BUTTONS",
    "KIND_COLLECT",
    "KIND_HANDOFF",
    "KIND_LABELS",
    "KIND_LIST",
    "KIND_ORDER_SUMMARY",
    "KIND_PRODUCTS",
    "KIND_TEXT",
    "MAX_LIST_SECTIONS",
    "NEXT_STEP_QR",
    "NODE_KINDS",
    "NONE_VALUE",
    "PUBLISHED_BUT_PAUSED",
    "PUBLISH_BUTTON",
    "PUBLISH_CONFIRM",
    "PUBLISH_CONFIRM_BACK_TO",
    "PUBLISH_CONFIRM_BUTTON",
    "PUBLISH_CONFIRM_PAUSED",
    "PUBLISH_CONFIRM_REPLACES",
    "PUBLISH_CONFIRM_RESEND",
    "PUBLISH_CONFIRM_SAVES",
    "PUBLISH_CONFIRM_STARTS_WITH",
    "PUBLISH_PARTIAL",
    "REPLY_BUTTON",
    "REPLY_LIST",
    "RESUME_BUTTON",
    "SAVE_ONLY_BUTTON",
    "TEMPLATE_EMPTY",
    "TEMPLATE_FAST_FOOD",
    "CatalogRowVM",
    "CatalogSectionVM",
    "CHANGE_ORDER",
    "ORDER_HINT",
    "CommandForm",
    "FormResult",
    "GuidedButtonVM",
    "GuidedVM",
    "IceBreakerForm",
    "KeywordForm",
    "MenuForm",
    "MenuSummaryVM",
    "MenuVersionVM",
    "NodeChoiceVM",
    "NodeForm",
    "OptionForm",
    "PreviewChoiceVM",
    "PreviewMessageVM",
    "PreviewTurn",
    "actions_to_messages",
    "apply_kind_defaults",
    "build_menu_summary",
    "build_version_vm",
    "can_publish",
    "catalog_note",
    "catalog_rows",
    "catalog_sections",
    "catalog_order_line",
    "catalog_more_line",
    "catalog_mode_line",
    "catalog_by_category",
    "first_screen",
    "change_kind",
    "definition_to_form",
    "empty_form",
    "ensure_person",
    "ensure_products",
    "excerpt",
    "flow_order",
    "form_to_payload",
    "fresh_node_id",
    "guided_add_button",
    "guided_remove_button",
    "guided_review",
    "guided_set_address",
    "guided_set_address_prompt",
    "guided_set_button_action",
    "guided_set_button_label",
    "guided_set_button_text",
    "guided_set_greeting",
    "guided_set_products_intro",
    "guided_set_question",
    "guided_step_label",
    "guided_use_buttons",
    "guided_view",
    "handoff_note",
    "issues_summary",
    "menu_status",
    "new_node",
    "new_option",
    "node_choices",
    "node_label",
    "node_labels",
    "order_lines",
    "preview_turn",
    "publish_confirm_lines",
    "publish_notice",
    "template_definition",
    "translate_error",
    "validate_form",
    "validate_menu_name",
    "NO_SUGGESTION",
    "SUGGEST_AGAIN",
    "SUGGEST_ANSWER",
    "SUGGEST_DONE",
    "SUGGEST_DONE_GAPS",
    "SUGGEST_FAILED",
    "SUGGEST_GO_BRAND",
    "SUGGEST_GREETING",
    "SUGGEST_IMPROVE",
    "SUGGEST_NEUTRAL",
    "SUGGEST_NO_DATA",
    "SUGGEST_STALE",
    "SUGGEST_UNDO",
    "SUGGEST_WRITE",
    "SUGGEST_WRITING",
    "SuggestVM",
    "suggest_context",
    "suggest_has_input",
    "suggest_label",
    "suggest_missing_line",
    "suggest_proposal_vm",
    "suggest_writing_line",
    "EMPTY_IMPORT",
    "FACT_ANSWERS",
    "FACT_PENDING",
    "FACT_SKIPPED",
    "FACT_TITLES",
    "FACT_USED",
    "FactPlan",
    "IMPORT_ADD_BUTTON",
    "IMPORT_ADD_FAILED",
    "IMPORT_ADD_NEEDS_BRAND",
    "IMPORT_CANCEL",
    "IMPORT_CHECK_ALL",
    "IMPORT_OWN_CURRENCY",
    "IMPORT_TOO_BIG",
    "IMPORT_UNCHECK_ALL",
    "IMPORT_CHOOSE",
    "IMPORT_DONE",
    "IMPORT_EDIT",
    "IMPORT_EDIT_DONE",
    "IMPORT_EMPTY_PHASE",
    "IMPORT_FAILED",
    "IMPORT_FAILED_PHASE",
    "IMPORT_LINK",
    "IMPORT_MAX_BYTES",
    "IMPORT_NOT_NOW",
    "IMPORT_OFFER_HELP",
    "IMPORT_OFFER_TITLE",
    "IMPORT_PAGE",
    "IMPORT_PAGE_BUTTON",
    "IMPORT_PAGE_CARD",
    "IMPORT_PAGE_CARD_HELP",
    "IMPORT_PAGE_HELP",
    "IMPORT_PAGE_LABEL",
    "IMPORT_PAGE_NEEDS_LINK",
    "IMPORT_PAGE_PLACEHOLDER",
    "IMPORT_PAGE_TITLE",
    "IMPORT_PHASES",
    "IMPORT_PHOTO",
    "IMPORT_PHOTO_BUTTON",
    "IMPORT_PHOTO_CARD",
    "IMPORT_PHOTO_CARD_HELP",
    "IMPORT_PHOTO_HELP",
    "IMPORT_PHOTO_TITLE",
    "IMPORT_PRIVACY",
    "IMPORT_PRODUCTS_NEW_HELP",
    "IMPORT_READING",
    "IMPORT_REJECTED",
    "IMPORT_READING_TEXT",
    "IMPORT_REVIEW",
    "IMPORT_REVIEW_HELP",
    "IMPORT_SKIP",
    "IMPORT_SLOW",
    "IMPORT_UPLOAD_FAILED",
    "IMPORT_USE",
    "ImportFactVM",
    "ImportProductVM",
    "ImportVM",
    "added_lines",
    "apply_fact",
    "catalog_names",
    "clean_fact_value",
    "fact_plan",
    "fact_rows",
    "fill_fact",
    "find_starter_answer",
    "import_empty_text",
    "import_retry_label",
    "import_review_title",
    "import_view",
    "import_where",
    "import_without_label",
    "product_rows",
]
