"""A new menu, born with the business's usual answers (m-24936836).

`build_starter_menu(facts)` is what «Nuevo menú» saves as version 1: the greeting with the
business's name, and the answers a food business is asked every day — «Ver menú y pedir»,
«Horario», «Domicilio», «Dónde estamos», «Formas de pago», «Reservas», «Hablar con
alguien» (spec: `docs/ux-whatsapp-respuestas-de-siempre.md` §2). What Qualify knows goes
in (`StarterFacts`); what it does not is a **gap in brackets**, `[hora de abrir]`, never an
invented datum — the fast-food example (`examples.BIANKI_DEMO_MENU`, «Calle 10 # 5-20»,
«12:00 a 22:00») stays for the engine tests and never seeds a menu.

**A gap never reaches a customer.** `definition_gaps` lists every gap a customer could
read (the welcome and every step reachable from the entry); the editor refuses to publish
while there is one and the provider refuses again (`MenuHasGaps`), so a stale tab or an
older version cannot slip one through.

**How answers become WhatsApp messages** (Meta: 3 reply buttons, a list of 10 rows): up to
`MAX_BUTTONS` answers are all buttons; with more, the first `BUTTONS_WITH_MORE` are
buttons and the last button is «Más preguntas», which opens a list with the rest — at
most `MAX_ANSWERS` in all. The editor's guided step re-lays them out with the same rule.

Pure: no DB, no network. The definition shape is `schema.MenuDefinition` as is — nothing
here needs a migration.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from qualify_api.whatsapp.menus.schema import (
    MAX_BUTTONS,
    MAX_LIST_ROWS,
    ButtonsNode,
    CollectNode,
    ListNode,
    MenuDefinition,
    OrderSummaryNode,
    ProductsNode,
    TextNode,
)

# --- The layout rule ---------------------------------------------------------------------

#: With more answers than buttons, the last button opens the list of the rest.
BUTTONS_WITH_MORE: Final = MAX_BUTTONS - 1
MAX_ANSWERS: Final = BUTTONS_WITH_MORE + MAX_LIST_ROWS  # 12
#: An answer may be a button (20 characters) or a list row (24): 20 keeps it movable.
ANSWER_LABEL_MAX: Final = 20

MORE_OPTION_ID: Final = "mas_preguntas"
MORE_NODE_ID: Final = "mas_preguntas"
MORE_LABEL: Final = "Más preguntas"
MORE_BODY: Final = "Elige lo que quieres saber."
MORE_BUTTON: Final = "Ver preguntas"
MORE_SECTION: Final = "Más preguntas"

# --- Gaps --------------------------------------------------------------------------------

_GAP_RE = re.compile(r"\[([^\[\]\n]{1,80})\]")
# Keys whose values are identifiers or enums, never text a customer reads.
_NOT_TEXT_KEYS = frozenset(
    {
        "id",
        "kind",
        "next",
        "next_after_pick",
        "confirm_next",
        "add_more_next",
        "cancel_next",
        "source",
        "reason",
        "field",
        "validation",
    }
)


def find_gaps(text: str) -> list[str]:
    """The bracketed gaps of `text`, in order, each once: «[hora de abrir]» → «hora de
    abrir»."""
    out: list[str] = []
    for match in _GAP_RE.finditer(text or ""):
        name = match.group(1).strip()
        if name and name not in out:
            out.append(name)
    return out


def _texts(value: Any, key: str = "") -> Iterable[str]:
    if key in _NOT_TEXT_KEYS:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _texts(v, str(k))
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _texts(item)


def _refs(node: Any) -> list[str]:
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


def reachable_nodes(definition: MenuDefinition) -> list[str]:
    """Every step a customer can reach: from the start step and from every entry door
    (keywords, shortcuts, commands, the fallback), along the arrows."""
    entry = definition.entry
    queue = [
        definition.start_node,
        *entry.keywords.values(),
        *(ib.node for ib in entry.ice_breakers),
        *(c.node for c in entry.commands),
        *([entry.fallback_node] if entry.fallback_node else []),
    ]
    seen: list[str] = []
    while queue:
        node_id = queue.pop(0)
        if node_id in seen or node_id not in definition.nodes:
            continue
        seen.append(node_id)
        queue.extend(_refs(definition.nodes[node_id]))
    return seen


@dataclass(frozen=True)
class Gap:
    """The gaps of one place a customer reads: a step (`node_id`) or the welcome (None)."""

    node_id: str | None
    names: tuple[str, ...]


def definition_gaps(definition: MenuDefinition) -> list[Gap]:
    """Every gap a customer could read; empty when the menu can be published."""
    out: list[Gap] = []
    welcome = find_gaps(definition.entry.welcome or "")
    if welcome:
        out.append(Gap(None, tuple(welcome)))
    for node_id in reachable_nodes(definition):
        node = definition.nodes[node_id].model_dump(mode="json", exclude={"title"})
        names: list[str] = []
        for text in _texts(node):
            names.extend(n for n in find_gaps(text) if n not in names)
        if names:
            out.append(Gap(node_id, tuple(names)))
    return out


class MenuHasGaps(Exception):
    """A version with a gap was asked to go live: refused before anything is written."""


# --- What Qualify knows ------------------------------------------------------------------


@dataclass(frozen=True)
class StarterFacts:
    """Facts already in Postgres (or already on screen): never a guess."""

    business_name: str = ""  # the brand's name, else the number's verified name
    address: str = ""  # the WhatsApp profile's address, when the screen already read it
    city: str = ""  # «Tu marca» → connect.city
    sector: str = ""  # «Tu marca» → connect.sector (only the food set exists yet)


# --- The food set (spec §2, the table «Respuestas con las que nace el menú de comida») ----

NAME_GAP: Final = "[nombre de tu negocio]"
GREETING: Final = (
    "¡Hola! Gracias por escribir a {name}. Aquí ves el menú, haces tu pedido y resuelves tus dudas."
)
QUESTION: Final = "¿En qué te ayudamos?"
HOURS_TEXT: Final = (
    "Abrimos de [qué días], de [hora de abrir] a [hora de cerrar]. Cuando quieras pedir, "
    "escribe *menú*."
)
DELIVERY_TEXT: Final = (
    "Llevamos tu pedido a [barrios o zona]. El envío cuesta [precio del envío] y tarda unos "
    "[minutos] minutos. Para pedir, escribe *menú*."
)
LOCATION_TEXT: Final = "Estamos en {address}. ¡Te esperamos!"
LOCATION_GAP: Final = "[dirección y barrio]"
PAYMENT_TEXT: Final = (
    "Puedes pagar con [formas de pago: efectivo, transferencia…]. Te confirmamos el total "
    "antes de pagar."
)
RESERVATIONS_TEXT: Final = (
    "Para reservar, escríbenos el día, la hora y para cuántas personas. Te confirmamos en "
    "[cuánto tardas en responder]."
)
PERSON_TEXT: Final = "Te paso con una persona del equipo; en un momento te responden."
#: Answers marked «Sugerida» while their text is still the one they were born with.
SUGGESTED_TEXTS: Final = frozenset({PAYMENT_TEXT, RESERVATIONS_TEXT})


def _clean(value: str, limit: int = 120) -> str:
    """One line, no brackets (a fact must never read as a gap), at most `limit`."""
    line = " ".join((value or "").split()).replace("[", "(").replace("]", ")")
    return line[:limit].rstrip()


def _location(facts: StarterFacts) -> str:
    address = _clean(facts.address, 200)
    if address:
        return LOCATION_TEXT.format(address=address.rstrip("."))
    city = _clean(facts.city, 60)
    place = f"{LOCATION_GAP}, {city}" if city else LOCATION_GAP
    return LOCATION_TEXT.format(address=place)


#: (option id, label, step id) in the starting order — the founder's 2026-11-03 call:
#: «Ver menú y pedir» and «Horario» are the two buttons.
_ANSWERS: Final[tuple[tuple[str, str, str], ...]] = (
    ("ver_menu", "Ver menú y pedir", "productos"),
    ("horario", "Horario", "horario"),
    ("domicilio", "Domicilio", "domicilio"),
    ("ubicacion", "Dónde estamos", "ubicacion"),
    ("pagos", "Formas de pago", "pagos"),
    ("reservas", "Reservas", "reservas"),
    ("persona", "Hablar con alguien", "persona"),
)


def lay_out(answers: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(buttons, list rows) for ordered answers, by the layout rule. Each answer is
    `{"id", "label", "next"}`; the «Más preguntas» button is NOT included in `buttons`."""
    if len(answers) <= MAX_BUTTONS:
        return list(answers), []
    return list(answers[:BUTTONS_WITH_MORE]), list(answers[BUTTONS_WITH_MORE:MAX_ANSWERS])


def build_starter_menu(facts: StarterFacts) -> MenuDefinition:
    """The definition a new menu starts from. Valid as is (the gaps are text); publishing
    waits until `definition_gaps` is empty."""
    name = _clean(facts.business_name, 80) or NAME_GAP
    answers = [{"id": i, "label": label, "next": node} for i, label, node in _ANSWERS]
    buttons, rows = lay_out(answers)
    options = [*buttons]
    nodes: dict[str, Any] = {}
    if rows:
        options.append({"id": MORE_OPTION_ID, "label": MORE_LABEL, "next": MORE_NODE_ID})
        nodes[MORE_NODE_ID] = {
            "kind": "list",
            "title": MORE_LABEL,
            "body": MORE_BODY,
            "button_label": MORE_BUTTON,
            "sections": [
                {
                    "title": MORE_SECTION,
                    "rows": [{"id": r["id"], "title": r["label"], "next": r["next"]} for r in rows],
                }
            ],
        }
    nodes = {
        "inicio": {"kind": "buttons", "title": "Saludo", "body": QUESTION, "options": options},
        **nodes,
        "productos": {
            "kind": "products",
            "title": "Ver menú y pedir",
            "source": "catalog",
            "body": "Elige un producto para agregarlo a tu pedido.",
            "button_label": "Ver productos",
            "more_label": "Ver más",
            "page_size": MAX_LIST_ROWS,
            "next_after_pick": "agregado",
            "empty_body": "Por ahora no tenemos productos cargados. Escríbenos y te atendemos.",
        },
        "agregado": {
            "kind": "buttons",
            "title": "Producto agregado",
            "body": "Listo, lo agregué a tu pedido. ¿Qué sigue?",
            "options": [
                {"id": "agregar_mas", "label": "Agregar más", "next": "productos"},
                {"id": "ver_pedido", "label": "Ver mi pedido", "next": "resumen"},
                {"id": "cancelar", "label": "Cancelar pedido", "next": "cancelado"},
            ],
        },
        "resumen": {
            "kind": "order_summary",
            "title": "Resumen del pedido",
            "body": "Total: {total}\n¿Confirmas tu pedido?",
            "confirm_next": "direccion",
            "add_more_next": "productos",
            "cancel_next": "cancelado",
        },
        "direccion": {
            "kind": "collect",
            "title": "Pedir la dirección",
            "prompt": "¿A qué dirección te lo llevamos? Escríbela completa, con barrio.",
            "field": "direccion",
            "validation": "text",
            "error_message": "Necesito la dirección escrita para poder tomar el pedido.",
            "next": "pedido_confirmado",
        },
        "pedido_confirmado": {
            "kind": "handoff",
            "title": "Pedido confirmado",
            "message": (
                "¡Gracias! Una persona del equipo confirma tu pedido y el tiempo de "
                "entrega en un momento."
            ),
            "reason": "order_confirmed",
        },
        "cancelado": {
            "kind": "text",
            "title": "Pedido cancelado",
            "body": "Listo, cancelé el pedido. Cuando quieras volver a empezar, escribe *menú*.",
        },
        "horario": {"kind": "text", "title": "Horario", "body": HOURS_TEXT},
        "domicilio": {"kind": "text", "title": "Domicilio", "body": DELIVERY_TEXT},
        "ubicacion": {"kind": "text", "title": "Dónde estamos", "body": _location(facts)},
        "pagos": {"kind": "text", "title": "Formas de pago", "body": PAYMENT_TEXT},
        "reservas": {
            "kind": "handoff",
            "title": "Reservas",
            "message": RESERVATIONS_TEXT,
            "reason": "customer_request",
        },
        "persona": {
            "kind": "handoff",
            "title": "Hablar con alguien",
            "message": PERSON_TEXT,
            "reason": "customer_request",
        },
    }
    return MenuDefinition.model_validate(
        {
            "version": 1,
            "start_node": "inicio",
            "entry": {
                "on_first_message": True,
                "welcome": GREETING.format(name=name),
                "keywords": {
                    "hola": "inicio",
                    "menú": "productos",
                    "pedido": "productos",
                    "pedir": "productos",
                    "persona": "persona",
                    "ayuda": "persona",
                },
                "fallback_node": "persona",
            },
            "nodes": nodes,
        }
    )


__all__ = [
    "ANSWER_LABEL_MAX",
    "BUTTONS_WITH_MORE",
    "MAX_ANSWERS",
    "MORE_BODY",
    "MORE_BUTTON",
    "MORE_LABEL",
    "MORE_NODE_ID",
    "MORE_OPTION_ID",
    "MORE_SECTION",
    "SUGGESTED_TEXTS",
    "Gap",
    "MenuHasGaps",
    "StarterFacts",
    "build_starter_menu",
    "definition_gaps",
    "find_gaps",
    "lay_out",
    "reachable_nodes",
]
