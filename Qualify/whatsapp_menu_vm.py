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
from typing import Any, Final

from pydantic import ValidationError
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
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
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


def new_node(kind: str, node_id: str) -> NodeForm:
    """A fresh step of `kind` with the schema's defaults filled in."""
    return apply_kind_defaults(NodeForm(node_id=node_id, kind=kind))


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
            error_message=keep(node.error_message, _DEFAULT_COLLECT_ERROR),
            yes_label=keep(node.yes_label, _DEFAULT_YES),
            no_label=keep(node.no_label, _DEFAULT_NO),
        )
    if kind == KIND_HANDOFF:
        return replace(node, reason=keep(node.reason, _DEFAULT_REASON))
    return node


def new_option(node: NodeForm) -> OptionForm:
    """A new button/row with an id unique inside the step."""
    taken = {o.option_id for o in node.options}
    n = len(node.options) + 1
    while f"opcion_{n}" in taken:
        n += 1
    section = node.options[-1].section if node.options else _DEFAULT_SECTION
    return OptionForm(
        option_id=f"opcion_{n}",
        label="",
        description="",
        next="",
        section=section if node.kind == KIND_LIST else "",
    )


def unique_node_id(form: MenuForm, base: str) -> str:
    taken = {n.node_id for n in form.nodes}
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


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
        nodes=[new_node(KIND_TEXT, "inicio")],
    )


def template_definition(template: str) -> MenuDefinition | None:
    """The starting definition of a new menu: the fast-food example, or None (empty)."""
    return BIANKI_DEMO_MENU if template == TEMPLATE_FAST_FOOD else None


# --------------------------------------------------------------------------------------
# Definition → form
# --------------------------------------------------------------------------------------


def _s(value: str | None) -> str:
    return value or ""


def _node_to_form(node_id: str, node: Any) -> NodeForm:
    base = NodeForm(node_id=node_id, kind=node.kind)
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
    for index, node in enumerate(form.nodes):
        node_id = node.node_id.strip()
        if not node_id or node_id in nodes:
            continue
        payload, rows_at, first_row = _node_payload(node)
        nodes[node_id] = payload
        node_index[node_id] = index
        list_rows[node_id] = rows_at
        section_first_row[node_id] = first_row
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
    return payload, _LocMap(node_index, list_rows, section_first_row)


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


def _place_structural(errors: _Errors, locmap: _LocMap, message: str) -> None:
    """The model validator's whole-menu errors (loc `()`), parsed back to a field."""
    if "start_node" in message and "is not a node" in message:
        errors.entry_field("start_node", PICK_A_STEP)
        return
    if message.startswith("dangling node references"):
        for source, target in re.findall(r"(\S+) -> '([^']*)'", message):
            text = f"Lleva a «{target}», un paso que no existe."
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


def _annotate(form: MenuForm, errors: _Errors) -> MenuForm:
    nodes: list[NodeForm] = []
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


def rename_node(form: MenuForm, index: int, new_id: str) -> MenuForm:
    """Change a step's id and carry every reference to it along — but only while both the
    old and the new id are unambiguous; a collision leaves the references for the
    validation to flag instead of silently stealing another step's arrows."""
    if not 0 <= index < len(form.nodes):
        return form
    old_id = form.nodes[index].node_id
    nodes = list(form.nodes)
    nodes[index] = replace(nodes[index], node_id=new_id)
    others = [n.node_id for k, n in enumerate(form.nodes) if k != index]
    if not old_id or old_id in others or new_id in others or not new_id:
        return replace(form, nodes=nodes)

    def move(value: str) -> str:
        return new_id if value == old_id else value

    nodes = [
        replace(
            n,
            next=move(n.next),
            next_after_pick=move(n.next_after_pick),
            confirm_next=move(n.confirm_next),
            add_more_next=move(n.add_more_next),
            cancel_next=move(n.cancel_next),
            options=[replace(o, next=move(o.next)) for o in n.options],
        )
        for n in nodes
    ]
    return replace(
        form,
        nodes=nodes,
        start_node=move(form.start_node),
        fallback_node=move(form.fallback_node),
        keywords=[replace(k, node=move(k.node)) for k in form.keywords],
        ice_breakers=[replace(i, node=move(i.node)) for i in form.ice_breakers],
        commands=[replace(c, node=move(c.node)) for c in form.commands],
    )


def change_kind(node: NodeForm, kind: str) -> NodeForm:
    """Switch a step's kind keeping its text and options; list rows get a section."""
    if kind not in KIND_KEYS or kind == node.kind:
        return node
    options = node.options
    if kind == KIND_LIST:
        options = [replace(o, section=o.section or _DEFAULT_SECTION) for o in options]
    return apply_kind_defaults(replace(node, kind=kind, options=options))


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
NEXT_STEP_QR = "Haz que te escriban: crea tu código QR para el mostrador"


def publish_confirm_lines(
    *, dirty: bool, version: MenuVersionVM | None, other_published_menu: str
) -> list[str]:
    """The case-specific lines under `PUBLISH_CONFIRM`: what happens to the version on
    screen (`version` is the saved one the editor shows; ignored while `dirty`, since a
    new one is saved first), then — only when another menu of the number is the one
    answering — that it gets replaced."""
    lines: list[str] = []
    if dirty:
        lines.append(PUBLISH_CONFIRM_SAVES)
    elif version is not None:
        number = version.label.removeprefix("Versión ").strip()
        if version.is_live:
            lines.append(PUBLISH_CONFIRM_RESEND)
        elif version.published_at:
            lines.append(PUBLISH_CONFIRM_BACK_TO.format(n=number))
        else:
            lines.append(PUBLISH_CONFIRM_STARTS_WITH.format(n=number))
    if other_published_menu.strip():
        lines.append(PUBLISH_CONFIRM_REPLACES.format(name=other_published_menu.strip()))
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


__all__ = [
    "COLLECT_VALIDATIONS",
    "EMPTY_MENU",
    "KIND_BUTTONS",
    "KIND_COLLECT",
    "KIND_HANDOFF",
    "KIND_LABELS",
    "KIND_LIST",
    "KIND_ORDER_SUMMARY",
    "KIND_PRODUCTS",
    "KIND_TEXT",
    "MAX_LIST_SECTIONS",
    "NODE_KINDS",
    "NEXT_STEP_QR",
    "NONE_VALUE",
    "PUBLISH_BUTTON",
    "PUBLISH_CONFIRM",
    "PUBLISH_CONFIRM_BACK_TO",
    "PUBLISH_CONFIRM_BUTTON",
    "PUBLISH_CONFIRM_RESEND",
    "PUBLISH_CONFIRM_STARTS_WITH",
    "PUBLISH_PARTIAL",
    "PUBLISH_CONFIRM_REPLACES",
    "PUBLISH_CONFIRM_SAVES",
    "REPLY_BUTTON",
    "REPLY_LIST",
    "SAVE_ONLY_BUTTON",
    "TEMPLATE_EMPTY",
    "TEMPLATE_FAST_FOOD",
    "CommandForm",
    "FormResult",
    "IceBreakerForm",
    "KeywordForm",
    "MenuForm",
    "MenuSummaryVM",
    "MenuVersionVM",
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
    "change_kind",
    "definition_to_form",
    "empty_form",
    "flow_order",
    "form_to_payload",
    "handoff_note",
    "issues_summary",
    "menu_status",
    "new_node",
    "new_option",
    "order_lines",
    "preview_turn",
    "publish_confirm_lines",
    "publish_notice",
    "rename_node",
    "template_definition",
    "translate_error",
    "unique_node_id",
    "validate_form",
    "validate_menu_name",
]
