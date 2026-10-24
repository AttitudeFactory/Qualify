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
from qualify_api.whatsapp.menus.ids import new_node_id, new_option_id
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


def template_definition(template: str) -> MenuDefinition | None:
    """The starting definition of a new menu: the fast-food example, or None (empty)."""
    return BIANKI_DEMO_MENU if template == TEMPLATE_FAST_FOOD else None


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
# onto the template's shape (`BIANKI_DEMO_MENU`):
#
#   1 ¿Cómo saludas?          → entry.welcome
#   2 ¿Qué botones ve…?       → the start step's text and its (up to 3) buttons; each
#                                button shows products, answers with a message, or hands
#                                the chat to the owner
#   3 Tus productos           → the catalog step's text; on confirm: ask the address or not
#   4 Pruébalo y publícalo    → review in words + the preview + «Publicar en mi WhatsApp»
#
# Steps a guided edit needs (the catalog chain, «hablar con una persona», a message) are
# created with generated ids (`ids.new_node_id`) and never renamed by id.

GUIDED_STEPS: Final = 4
GUIDED_TITLES: tuple[str, ...] = (
    "¿Cómo saludas?",
    "¿Qué botones ve al escribirte?",
    "Tus productos",
    "Pruébalo y publícalo",
)
GUIDED_HELP: tuple[str, ...] = (
    "Es lo primero que lee tu cliente cuando te escribe.",
    "Debajo del saludo, tu cliente ve hasta 3 botones. Elige qué pasa al tocar cada uno.",
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


def catalog_rows(items: Sequence[CatalogItem]) -> list[CatalogRowVM]:
    return [
        CatalogRowVM(
            name=i.name,
            price=(
                format_money(i.price_amount, i.price_currency)
                if i.price_amount is not None
                else "Sin precio"
            ),
        )
        for i in items
    ]


def _find(form: MenuForm, node_id: str) -> int | None:
    return next((i for i, n in enumerate(form.nodes) if n.node_id == node_id), None)


def _first_kind(form: MenuForm, kind: str) -> int | None:
    return next((i for i, n in enumerate(form.nodes) if n.kind == kind), None)


def _person_index(form: MenuForm) -> int | None:
    handoffs = [i for i, n in enumerate(form.nodes) if n.kind == KIND_HANDOFF]
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
        buttons_issue=bool(question_error) or any(b.label_error or b.text_error for b in buttons),
        products_issue=bool(products_intro_error or address_error),
    )


def _template_nodes() -> dict[str, NodeForm]:
    return {n.node_id: n for n in definition_to_form(BIANKI_DEMO_MENU).nodes}


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


def guided_review(view: GuidedVM, catalog_count: int) -> list[str]:
    """Step 4's review, in words (guide N6): what the customer gets, button by button,
    and who closes the order (always the owner — guide N13)."""
    lines: list[str] = []
    if view.greeting.strip():
        lines.append(f"Saluda: «{excerpt(view.greeting, 80)}»")
    else:
        lines.append("No manda un saludo propio: empieza con la pregunta.")
    if view.uses_buttons:
        labels = [b.label.strip() for b in view.buttons if b.label.strip()]
        noun = "botón" if len(labels) == 1 else "botones"
        listed = ", ".join(f"«{label}»" for label in labels)
        lines.append(f"Pregunta «{excerpt(view.question, 60)}» con {len(labels)} {noun}: {listed}.")
        for button in view.buttons:
            if button.label.strip():
                lines.append(f"«{button.label.strip()}» {_button_does(button)}.")
    if view.has_products:
        if catalog_count == 0:
            lines.append("Tu catálogo está vacío: agrega tus productos para que te puedan pedir.")
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


__all__ = [
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
]
