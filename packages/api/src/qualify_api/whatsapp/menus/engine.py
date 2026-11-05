"""Deterministic menu engine (WA-14, pure half).

`step()` takes a validated `MenuDefinition`, the thread's current `ThreadMenuState`
and one `Inbound` event, and returns the outbound actions plus the next state. It is
**synchronous and pure**: no network, no DB, no clock, no randomness — the webhook
handler (WA-07) persists the returned state to `whatsapp_thread_state` and enqueues
the returned actions in `whatsapp_outbox`. Re-running `step` with the same inputs
yields the same outputs, which is what makes a replayed webhook delivery harmless.

Rules (backlog WA-14/WA-15, plan §5.3):

- A **paused** state (a person took the thread over, or a handoff happened) is inert:
  no actions, state returned unchanged. Resuming is the handler's decision.
- Global entries — a `/command`, an ice-breaker tap (arrives as its text), a keyword —
  route from **any** node. On a thread's first message (or Meta's `request_welcome`)
  with `entry.on_first_message` enabled, `entry.welcome` is sent before the node.
- An idle thread (`node_id is None`) that says something unrecognized re-enters at
  `start_node`, unless it is the first message and `on_first_message` is off.
- A `products` node renders the catalog as a list: one section per category, at most
  `page_size` rows per message, one row spent on "Ver más" when the catalog overflows.
  Picking a product adds it to `context["order"]` (qty 1, a repeat pick increments)
  and continues to `next_after_pick`.
- **Categories first** (founder, 2026-11-06, m-24955838): when the catalog has more
  than `page_size - 1` products AND two or more categories, the node first sends a
  list of the categories (`categories_body`, default «¿Qué se te antoja?»), one row
  each in the catalog's order (`whatsapp.catalog.to_catalog_items` already applied the
  owner's order — the engine keeps first appearance; a row with no category at all
  joins «Otros», last), described «N productos»; more than `MAX_LIST_ROWS` categories
  page as 9 + «Ver más categorías». Choosing one shows only that category: its
  products, a «Ver otras categorías» row back to the list (the order is kept), and
  «Ver más» when it has more than `page_size - 2` products. A catalog that fits one
  list, or has a single category, keeps the direct list above, unchanged.
  Row ids: `cat:<category_key>` — the case-, accent- and space-insensitive key of
  `catalog.order.category_key`, so «Café» renamed «cafe» keeps its id, as product ids
  survive a renamed product; `catmore:<page>`; `cats:back`. The current view lives in
  `context`: `products_category` (the key, absent on the categories list),
  `products_page` (page inside the category / the direct list) and
  `products_categories_page`. A key no longer in the catalog (category removed or
  emptied meanwhile) shows the categories list — never an error.
- `order_summary` renders the order lines, `{total}`, and the three fixed buttons.
  `confirm` marks `context["order_confirmed"]` and follows `confirm_next` (a handoff,
  possibly through `collect`/`text` nodes); `cancel` clears the order.
- `collect` validates (`text` / `phone` / `yes_no`) and stores under
  `context["collected"][field]`; an invalid answer counts as unknown input.
- Unknown input re-renders the current node prefixed with a short help line, at most
  `MAX_UNKNOWN_ATTEMPTS` times in a row; the next one hands off (to
  `entry.fallback_node` when declared, otherwise with a built-in message).
- `handoff` sends its message, emits `Handoff(reason, summary)` with the structured
  order and collected fields, and sets `paused=True`.

Everything a person can type is matched after `normalize_keyword` (case/accents
insensitive); a typed option label or its 1-based position counts as a pick, so the
menu also works for people who type instead of tapping.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from qualify_shared.social.wa_shapes import WAMessage

from qualify_api.catalog.order import FALLBACK_CATEGORY, category_key
from qualify_api.whatsapp.menus.schema import (
    BODY_MAX_LEN,
    LIST_ROW_TITLE_MAX_LEN,
    LIST_SECTION_TITLE_MAX_LEN,
    MAX_LIST_ROWS,
    NO_ID,
    ORDER_ADD_MORE_ID,
    ORDER_CANCEL_ID,
    ORDER_CONFIRM_ID,
    YES_ID,
    ButtonsNode,
    CollectNode,
    HandoffNode,
    ListNode,
    MenuDefinition,
    Node,
    OrderSummaryNode,
    ProductsNode,
    TextNode,
    normalize_keyword,
)

# Recorded in every `Handoff.summary` so a stored order says which engine built it.
ENGINE_VERSION: Final = "wa-menu-engine-0.1.0"

MAX_UNKNOWN_ATTEMPTS: Final = 2
HELP_LINE: Final = "No entendí tu respuesta. Elige una de las opciones:"
UNKNOWN_INPUT_REASON: Final = "unknown_input"
UNKNOWN_HANDOFF_MESSAGE: Final = "Te paso con una persona del equipo para ayudarte."

PRODUCT_ROW_PREFIX: Final = "prod:"
MORE_ROW_PREFIX: Final = "more:"
MORE_SECTION_TITLE: Final = "Más"
DEFAULT_CATEGORY: Final = "Productos"

# Categories first (m-24955838).
CATEGORY_ROW_PREFIX: Final = "cat:"
CATEGORIES_MORE_ROW_PREFIX: Final = "catmore:"
CATEGORIES_BACK_ROW_ID: Final = "cats:back"
CATEGORIES_SECTION_TITLE: Final = "Categorías"
CATEGORIES_MORE_LABEL: Final = "Ver más categorías"
CATEGORIES_BACK_LABEL: Final = "Ver otras categorías"
# Meta caps a row id at 200 characters; a category key never gets near it, but clip.
_CATEGORY_ID_MAX_LEN: Final = 190

# Context keys the engine owns. Everything under `context` must stay JSON-serializable:
# the handler stores it as jsonb and the preview UI reads it back.
CTX_ORDER: Final = "order"
CTX_COLLECTED: Final = "collected"
CTX_ORDER_CONFIRMED: Final = "order_confirmed"
CTX_PRODUCTS_PAGE: Final = "products_page"
CTX_PRODUCTS_CATEGORY: Final = "products_category"
CTX_CATEGORIES_PAGE: Final = "products_categories_page"
_PRODUCTS_VIEW_KEYS: Final = (CTX_PRODUCTS_PAGE, CTX_PRODUCTS_CATEGORY, CTX_CATEGORIES_PAGE)

_YES_WORDS: Final = frozenset({"si", "s", "yes", "y", "claro", "dale", "ok", "confirmo"})
_NO_WORDS: Final = frozenset({"no", "n", "nop", "nope"})
_PHONE_CLEAN_RE = re.compile(r"[\s\-().]")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")

# --- Inputs ----------------------------------------------------------------------

InboundKind = Literal["text", "button_reply", "list_reply", "command", "welcome", "unsupported"]


@dataclass(frozen=True)
class Inbound:
    """One event the engine reacts to. `value` is the text body, the reply id, the
    command name or the unsupported message type depending on `kind`;
    `first_message` is the handler's knowledge that this thread is new."""

    kind: InboundKind
    value: str = ""
    first_message: bool = False

    @classmethod
    def text(cls, body: str, *, first_message: bool = False) -> Inbound:
        return cls("text", body, first_message)

    @classmethod
    def button_reply(cls, reply_id: str, *, first_message: bool = False) -> Inbound:
        return cls("button_reply", reply_id, first_message)

    @classmethod
    def list_reply(cls, reply_id: str, *, first_message: bool = False) -> Inbound:
        return cls("list_reply", reply_id, first_message)

    @classmethod
    def command(cls, name: str, *, first_message: bool = False) -> Inbound:
        return cls("command", name.lstrip("/"), first_message)

    @classmethod
    def welcome(cls) -> Inbound:
        """Meta's `request_welcome` message: the user opened the chat, nothing typed."""
        return cls("welcome", "", True)

    @classmethod
    def unsupported(cls, message_type: str, *, first_message: bool = False) -> Inbound:
        return cls("unsupported", message_type, first_message)

    @property
    def is_reply(self) -> bool:
        return self.kind in ("button_reply", "list_reply")


def inbound_from_message(message: WAMessage, *, first_message: bool = False) -> Inbound:
    """Project a parsed webhook message onto an `Inbound`. Anything the engine cannot
    route (image, audio, location, order, …) becomes `unsupported` with its type, which
    the engine treats as unknown input — it never raises on a message type."""
    if message.type == "text" and message.text is not None:
        return Inbound.text(message.text.body, first_message=first_message)
    if message.type == "interactive" and message.interactive is not None:
        reply = message.interactive.reply
        if reply is not None:
            if message.interactive.list_reply is not None:
                return Inbound.list_reply(reply.id, first_message=first_message)
            return Inbound.button_reply(reply.id, first_message=first_message)
    if message.type == "request_welcome":
        return Inbound.welcome()
    return Inbound.unsupported(message.type, first_message=first_message)


@dataclass(frozen=True)
class CatalogItem:
    """One sellable row injected into a `products` node. The adapter that builds these
    from `brand_products` is WA-15's; the engine only renders and picks."""

    product_id: str
    name: str
    price_amount: Decimal | None = None
    price_currency: str | None = None
    category: str | None = None


# --- State -----------------------------------------------------------------------


@dataclass(frozen=True)
class ThreadMenuState:
    """Per-thread engine state. `context` is JSON-serializable by construction:
    `order` is a list of `{product_id, name, qty, price, currency}` with `price` as a
    decimal string, `collected` a `{field: value}` dict."""

    node_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    paused: bool = False
    attempts: int = 0

    @property
    def order(self) -> list[dict[str, Any]]:
        return list(self.context.get(CTX_ORDER, []))

    @property
    def collected(self) -> dict[str, Any]:
        return dict(self.context.get(CTX_COLLECTED, {}))


# --- Outbound actions ------------------------------------------------------------


@dataclass(frozen=True)
class SendText:
    body: str


@dataclass(frozen=True)
class Button:
    id: str
    title: str


@dataclass(frozen=True)
class SendButtons:
    body: str
    buttons: tuple[Button, ...]
    header: str | None = None
    footer: str | None = None


@dataclass(frozen=True)
class ListRowOut:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class ListSectionOut:
    title: str
    rows: tuple[ListRowOut, ...]


@dataclass(frozen=True)
class SendList:
    body: str
    button_label: str
    sections: tuple[ListSectionOut, ...]
    header: str | None = None
    footer: str | None = None

    @property
    def rows(self) -> tuple[ListRowOut, ...]:
        return tuple(r for s in self.sections for r in s.rows)


@dataclass(frozen=True)
class Handoff:
    """Hand the thread to a person. `summary` is JSON-serializable and carries the
    structured order (`order`, `total`, `currency`), `collected`, `order_confirmed`
    and `engine_version` — what WA-15 posts as the internal order message."""

    reason: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class SetContext:
    """Emitted (last) whenever the step changed `context`, carrying the new value, so
    a consumer that only looks at actions still sees the order/collected changes."""

    context: dict[str, Any]


OutboundAction = SendText | SendButtons | SendList | Handoff | SetContext


@dataclass(frozen=True)
class RenderResult:
    actions: list[OutboundAction]
    state: ThreadMenuState


@dataclass(frozen=True)
class StepResult:
    actions: list[OutboundAction]
    state: ThreadMenuState
    handed_off: bool


# --- Money / order helpers -------------------------------------------------------


def format_money(amount: Decimal, currency: str | None) -> str:
    """`COP 12.500` / `USD 9,99`: thousands with `.`, decimals with `,` only when the
    amount has cents. Deterministic, locale-free."""
    q = amount.quantize(Decimal("0.01"))
    if q == q.to_integral_value():
        num = f"{int(q):,}".replace(",", ".")
    else:
        num = f"{q:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{currency} {num}" if currency else num


def order_total(order: Sequence[dict[str, Any]]) -> tuple[Decimal, str | None]:
    """Sum of `qty * price` over the lines that carry a price, plus the first currency
    seen (a menu sells in one currency; mixing is the adapter's bug, not handled here)."""
    total = Decimal("0")
    currency: str | None = None
    for line in order:
        price = line.get("price")
        if price is None:
            continue
        try:
            total += Decimal(str(price)) * int(line.get("qty", 1))
        except (InvalidOperation, ValueError, TypeError):
            continue
        currency = currency or line.get("currency")
    return total, currency


def _order_lines(order: Sequence[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for line in order:
        qty = int(line.get("qty", 1))
        text = f"{qty} x {line['name']}"
        if line.get("price") is not None:
            unit = Decimal(str(line["price"]))
            text += f" — {format_money(unit * qty, line.get('currency'))}"
        lines.append(text)
    return lines


def _add_to_order(context: dict[str, Any], item: CatalogItem) -> None:
    order: list[dict[str, Any]] = context.setdefault(CTX_ORDER, [])
    for line in order:
        if line["product_id"] == item.product_id:
            line["qty"] = int(line.get("qty", 1)) + 1
            return
    order.append(
        {
            "product_id": item.product_id,
            "name": item.name,
            "qty": 1,
            "price": str(item.price_amount) if item.price_amount is not None else None,
            "currency": item.price_currency,
        }
    )


def _summary(state: ThreadMenuState, node_id: str) -> dict[str, Any]:
    order = state.order
    total, currency = order_total(order)
    return {
        "order": order,
        "total": str(total),
        "currency": currency,
        "order_confirmed": bool(state.context.get(CTX_ORDER_CONFIRMED, False)),
        "collected": state.collected,
        "node_id": node_id,
        "engine_version": ENGINE_VERSION,
    }


# --- Catalog pagination ----------------------------------------------------------


def _ordered_by_category(catalog: Sequence[CatalogItem]) -> list[CatalogItem]:
    """Stable: categories in order of first appearance, items in catalog order inside."""
    order: dict[str, list[CatalogItem]] = {}
    for item in catalog:
        order.setdefault(item.category or DEFAULT_CATEGORY, []).append(item)
    return [item for items in order.values() for item in items]


def _pages(catalog: Sequence[CatalogItem], page_size: int) -> list[list[CatalogItem]]:
    items = _ordered_by_category(catalog)
    if len(items) <= page_size:
        return [items]
    per_page = page_size - 1  # one row goes to "Ver más"
    return [items[i : i + per_page] for i in range(0, len(items), per_page)]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _products_list(
    node: ProductsNode, catalog: Sequence[CatalogItem], page: int, body: str
) -> tuple[SendList, int]:
    pages = _pages(catalog, node.page_size)
    page = max(0, min(page, len(pages) - 1))
    sections: list[ListSectionOut] = []
    current_title: str | None = None
    current_rows: list[ListRowOut] = []
    for item in pages[page]:
        category = item.category or DEFAULT_CATEGORY
        if category != current_title:
            if current_rows and current_title is not None:
                sections.append(
                    ListSectionOut(
                        _clip(current_title, LIST_SECTION_TITLE_MAX_LEN), tuple(current_rows)
                    )
                )
            current_title, current_rows = category, []
        description = (
            format_money(item.price_amount, item.price_currency)
            if item.price_amount is not None
            else None
        )
        current_rows.append(
            ListRowOut(
                id=f"{PRODUCT_ROW_PREFIX}{item.product_id}",
                title=_clip(item.name, LIST_ROW_TITLE_MAX_LEN),
                description=description,
            )
        )
    if current_rows and current_title is not None:
        sections.append(
            ListSectionOut(_clip(current_title, LIST_SECTION_TITLE_MAX_LEN), tuple(current_rows))
        )
    if page < len(pages) - 1:
        sections.append(
            ListSectionOut(
                MORE_SECTION_TITLE,
                (
                    ListRowOut(
                        id=f"{MORE_ROW_PREFIX}{page + 1}",
                        title=node.more_label,
                        description=f"Página {page + 2} de {len(pages)}",
                    ),
                ),
            )
        )
    return (
        SendList(
            body=body,
            button_label=node.button_label,
            sections=tuple(sections),
            header=node.header,
            footer=node.footer,
        ),
        page,
    )


# --- Categories first (m-24955838) --------------------------------------------------


@dataclass(frozen=True)
class _CategoryGroup:
    key: str
    label: str
    items: tuple[CatalogItem, ...]


@dataclass(frozen=True)
class _ProductsView:
    """Where the customer is inside a `products` node. `category` is a category key
    (`None` = the categories list, or the direct list when the catalog is not in
    categories mode); `page` pages the products shown, `categories_page` the list of
    categories."""

    category: str | None = None
    page: int = 0
    categories_page: int = 0


def _category_id_key(name: str | None) -> str:
    return category_key(name)[:_CATEGORY_ID_MAX_LEN]


def _category_groups(catalog: Sequence[CatalogItem]) -> list[_CategoryGroup]:
    """Categories in order of first appearance (the catalog's order); a row with no
    category at all joins «Otros», after every named category's first appearance."""
    labels: dict[str, str] = {}
    members: dict[str, list[CatalogItem]] = {}
    named = [i for i in catalog if i.category is not None]
    unnamed = [i for i in catalog if i.category is None]
    for item in [*named, *unnamed]:
        key = _category_id_key(item.category)
        labels.setdefault(key, " ".join((item.category or "").split()) or FALLBACK_CATEGORY)
        members.setdefault(key, []).append(item)
    return [_CategoryGroup(k, labels[k], tuple(v)) for k, v in members.items()]


def _categories_mode(node: ProductsNode, catalog: Sequence[CatalogItem]) -> bool:
    """The founder's rule: the catalog does not fit one list page and has 2+ categories."""
    if len(catalog) <= node.page_size - 1:
        return False
    return len({_category_id_key(i.category) for i in catalog}) >= 2


def _chunks[T](items: Sequence[T], fits: int, per_page: int) -> list[list[T]]:
    if len(items) <= fits:
        return [list(items)]
    return [list(items[i : i + per_page]) for i in range(0, len(items), per_page)]


def _count_label(count: int) -> str:
    return "1 producto" if count == 1 else f"{count} productos"


def _page_label(page: int, pages: int) -> str:
    return f"Página {page + 1} de {pages}"


def _categories_list(
    node: ProductsNode, groups: Sequence[_CategoryGroup], categories_page: int, body: str
) -> tuple[SendList, int]:
    pages = _chunks(groups, MAX_LIST_ROWS, MAX_LIST_ROWS - 1)
    categories_page = max(0, min(categories_page, len(pages) - 1))
    rows = tuple(
        ListRowOut(
            id=f"{CATEGORY_ROW_PREFIX}{g.key}",
            title=_clip(g.label, LIST_ROW_TITLE_MAX_LEN),
            description=_count_label(len(g.items)),
        )
        for g in pages[categories_page]
    )
    sections = [ListSectionOut(CATEGORIES_SECTION_TITLE, rows)]
    if categories_page < len(pages) - 1:
        sections.append(
            ListSectionOut(
                MORE_SECTION_TITLE,
                (
                    ListRowOut(
                        id=f"{CATEGORIES_MORE_ROW_PREFIX}{categories_page + 1}",
                        title=CATEGORIES_MORE_LABEL,
                        description=_page_label(categories_page + 1, len(pages)),
                    ),
                ),
            )
        )
    send = SendList(
        body=body,
        button_label=node.button_label,
        sections=tuple(sections),
        header=node.header,
        footer=node.footer,
    )
    return send, categories_page


def _category_products_list(
    node: ProductsNode, group: _CategoryGroup, page: int, body: str
) -> tuple[SendList, int]:
    # Two rows are reserved: «Ver otras categorías» always, «Ver más» when it pages.
    per_page = max(1, node.page_size - 2)
    pages = _chunks(group.items, per_page, per_page)
    page = max(0, min(page, len(pages) - 1))
    rows = tuple(
        ListRowOut(
            id=f"{PRODUCT_ROW_PREFIX}{item.product_id}",
            title=_clip(item.name, LIST_ROW_TITLE_MAX_LEN),
            description=(
                format_money(item.price_amount, item.price_currency)
                if item.price_amount is not None
                else None
            ),
        )
        for item in pages[page]
    )
    nav: list[ListRowOut] = []
    if page < len(pages) - 1:
        nav.append(
            ListRowOut(
                id=f"{MORE_ROW_PREFIX}{page + 1}",
                title=node.more_label,
                description=_page_label(page + 1, len(pages)),
            )
        )
    nav.append(ListRowOut(id=CATEGORIES_BACK_ROW_ID, title=CATEGORIES_BACK_LABEL))
    send = SendList(
        body=body,
        button_label=node.button_label,
        sections=(
            ListSectionOut(_clip(group.label, LIST_SECTION_TITLE_MAX_LEN), rows),
            ListSectionOut(MORE_SECTION_TITLE, tuple(nav)),
        ),
        header=node.header,
        footer=node.footer,
    )
    return send, page


def _products_view(
    node: ProductsNode,
    catalog: Sequence[CatalogItem],
    view: _ProductsView,
    help_line: str | None = None,
) -> tuple[SendList, _ProductsView, bool]:
    """The list for `view` (clamped), the view actually shown, and whether the catalog
    is in categories mode. A category key that is gone shows the categories list."""
    if not _categories_mode(node, catalog):
        send, page = _products_list(node, catalog, view.page, _with_help(node.body, help_line))
        return send, _ProductsView(page=page), False
    groups = _category_groups(catalog)
    group = next((g for g in groups if g.key == view.category), None)
    if group is not None:
        send, page = _category_products_list(
            node, group, view.page, _with_help(node.body, help_line)
        )
        return send, _ProductsView(group.key, page, view.categories_page), True
    send, categories_page = _categories_list(
        node, groups, view.categories_page, _with_help(node.categories_body, help_line)
    )
    return send, _ProductsView(categories_page=categories_page), True


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _view_from_context(context: dict[str, Any]) -> _ProductsView:
    category = context.get(CTX_PRODUCTS_CATEGORY)
    return _ProductsView(
        category=category if isinstance(category, str) and category else None,
        page=_as_int(context.get(CTX_PRODUCTS_PAGE, 0)),
        categories_page=_as_int(context.get(CTX_CATEGORIES_PAGE, 0)),
    )


def _store_view(context: dict[str, Any], view: _ProductsView, categories: bool) -> None:
    """Write the shown view into `context`. The direct list keeps today's single key."""
    _clear_view(context)
    if not categories:
        context[CTX_PRODUCTS_PAGE] = view.page
        return
    context[CTX_CATEGORIES_PAGE] = view.categories_page
    if view.category is not None:
        context[CTX_PRODUCTS_CATEGORY] = view.category
        context[CTX_PRODUCTS_PAGE] = view.page


def _clear_view(context: dict[str, Any]) -> None:
    for key in _PRODUCTS_VIEW_KEYS:
        context.pop(key, None)


def _is_category_nav(reply_id: str) -> bool:
    return reply_id == CATEGORIES_BACK_ROW_ID or reply_id.startswith(
        (CATEGORY_ROW_PREFIX, CATEGORIES_MORE_ROW_PREFIX)
    )


def products_list(node: ProductsNode, catalog: Sequence[CatalogItem], page: int = 0) -> SendList:
    """The list a `products` node sends on entry (`page` pages the direct list) — the
    very message the customer gets from «Ver menú y pedir»: the categories list when the
    catalog is in categories mode. Public for the chat's «Tu menú» (m-24945888), so the
    owner's send and the automation's can never render the catalog two ways."""
    return _products_view(node, catalog, _ProductsView(page=page))[0]


def is_categories_mode(node: ProductsNode, catalog: Sequence[CatalogItem]) -> bool:
    """Whether `products_list` opens on the categories list (m-24955838)."""
    return _categories_mode(node, catalog)


# --- Rendering -------------------------------------------------------------------


def _with_help(body: str, help_line: str | None) -> str:
    if not help_line:
        return body
    return _clip(f"{help_line}\n\n{body}", BODY_MAX_LEN)


def render_node(
    definition: MenuDefinition,
    node_id: str,
    state: ThreadMenuState,
    catalog: Sequence[CatalogItem] = (),
    *,
    help_line: str | None = None,
    page: int = 0,
    view: _ProductsView | None = None,
) -> RenderResult:
    """Render `node_id` for `state`: the outbound actions and the state the thread is
    left in (`node_id` where the next answer is expected, `None` when the node ended
    the session, `paused=True` after a handoff). A `text` node chains into its `next`
    within the same call. Shared by `step` and the WA-16 phone-style preview. A
    `products` node opens on `view` (default: the first page — the categories list in
    categories mode, page `page` of the direct list otherwise)."""
    context = copy.deepcopy(state.context)
    actions: list[OutboundAction] = []
    current = node_id
    while True:
        node: Node = definition.node(current)
        if isinstance(node, TextNode):
            actions.append(SendText(_with_help(node.body, help_line)))
            help_line = None
            if node.next is None:
                _clear_view(context)
                return RenderResult(actions, replace(state, node_id=None, context=context))
            current = node.next
            continue
        if isinstance(node, ButtonsNode):
            actions.append(
                SendButtons(
                    body=_with_help(node.body, help_line),
                    buttons=tuple(Button(o.id, o.label) for o in node.options),
                    header=node.header,
                    footer=node.footer,
                )
            )
        elif isinstance(node, ListNode):
            actions.append(
                SendList(
                    body=_with_help(node.body, help_line),
                    button_label=node.button_label,
                    sections=tuple(
                        ListSectionOut(
                            s.title, tuple(ListRowOut(r.id, r.title, r.description) for r in s.rows)
                        )
                        for s in node.sections
                    ),
                    header=node.header,
                    footer=node.footer,
                )
            )
        elif isinstance(node, ProductsNode):
            if not catalog:
                actions.append(SendText(_with_help(node.empty_body, help_line)))
                _clear_view(context)
                return RenderResult(actions, replace(state, node_id=None, context=context))
            send, shown, categories = _products_view(
                node, catalog, view or _ProductsView(page=page), help_line
            )
            _store_view(context, shown, categories)
            actions.append(send)
        elif isinstance(node, OrderSummaryNode):
            order = context.get(CTX_ORDER, [])
            total, currency = order_total(order)
            lines = _order_lines(order) or [node.empty_line]
            body = "\n".join(lines) + "\n\n" + node.body.format(total=format_money(total, currency))
            actions.append(
                SendButtons(
                    body=_with_help(_clip(body, BODY_MAX_LEN), help_line),
                    buttons=(
                        Button(ORDER_CONFIRM_ID, node.confirm_label),
                        Button(ORDER_ADD_MORE_ID, node.add_more_label),
                        Button(ORDER_CANCEL_ID, node.cancel_label),
                    ),
                )
            )
        elif isinstance(node, CollectNode):
            prompt = _with_help(node.prompt, help_line)
            if node.validation == "yes_no":
                actions.append(
                    SendButtons(
                        body=prompt,
                        buttons=(Button(YES_ID, node.yes_label), Button(NO_ID, node.no_label)),
                    )
                )
            else:
                actions.append(SendText(prompt))
        elif isinstance(node, HandoffNode):
            actions.append(SendText(_with_help(node.message, help_line)))
            paused = replace(state, node_id=None, context=context, paused=True)
            actions.append(Handoff(node.reason, _summary(paused, current)))
            return RenderResult(actions, paused)
        else:  # pragma: no cover - the discriminated union is closed
            raise TypeError(f"unknown node kind {type(node).__name__}")
        return RenderResult(actions, replace(state, node_id=current, context=context))


# --- Routing ---------------------------------------------------------------------


def _global_route(definition: MenuDefinition, inbound: Inbound) -> str | None:
    """Commands, ice breakers and keywords, in that order. Commands arrive either as
    `Inbound.command` or as text starting with `/`."""
    entry = definition.entry
    if inbound.kind == "command":
        name = normalize_keyword(inbound.value)
        for cmd in entry.commands:
            if normalize_keyword(cmd.name) == name:
                return cmd.node
        return None
    if inbound.kind != "text":
        return None
    text = inbound.value.strip()
    if text.startswith("/"):
        name = normalize_keyword(text[1:].split(maxsplit=1)[0]) if len(text) > 1 else ""
        for cmd in entry.commands:
            if normalize_keyword(cmd.name) == name:
                return cmd.node
    norm = normalize_keyword(text)
    if not norm:
        return None
    for ib in entry.ice_breakers:
        if normalize_keyword(ib.text) == norm:
            return ib.node
    return entry.keywords.get(norm)


def _pick(inbound: Inbound, choices: Sequence[tuple[str, str]]) -> str | None:
    """Resolve an answer to one of `choices` (`(id, label)`): a reply id exactly, or a
    typed label / 1-based position after normalization. `None` when nothing matches."""
    if inbound.is_reply:
        return next((cid for cid, _ in choices if cid == inbound.value), None)
    if inbound.kind != "text":
        return None
    norm = normalize_keyword(inbound.value)
    if not norm:
        return None
    for cid, label in choices:
        if normalize_keyword(label) == norm:
            return cid
    if norm.isdigit():
        index = int(norm)
        if 1 <= index <= len(choices):
            return choices[index - 1][0]
    return None


def _validate_collect(node: CollectNode, inbound: Inbound) -> tuple[bool, Any]:
    if node.validation == "yes_no":
        if inbound.is_reply:
            if inbound.value == YES_ID:
                return True, True
            if inbound.value == NO_ID:
                return True, False
            return False, None
        if inbound.kind == "text":
            norm = normalize_keyword(inbound.value)
            if norm in _YES_WORDS:
                return True, True
            if norm in _NO_WORDS:
                return True, False
        return False, None
    if inbound.kind != "text":
        return False, None
    answer = inbound.value.strip()
    if node.validation == "phone":
        cleaned = _PHONE_CLEAN_RE.sub("", answer)
        if _PHONE_RE.match(cleaned):
            return True, cleaned
        return False, None
    return (True, answer) if answer else (False, None)


def _handle_at_node(
    definition: MenuDefinition,
    state: ThreadMenuState,
    node: Node,
    inbound: Inbound,
    catalog: Sequence[CatalogItem],
) -> RenderResult | None:
    """Node-local interpretation of `inbound`; `None` means unknown input."""
    if isinstance(node, ButtonsNode):
        picked = _pick(inbound, [(o.id, o.label) for o in node.options])
        if picked is None:
            return None
        target = next(o.next for o in node.options if o.id == picked)
        return render_node(definition, target, state, catalog)

    if isinstance(node, ListNode):
        rows = [r for s in node.sections for r in s.rows]
        picked = _pick(inbound, [(r.id, r.title) for r in rows])
        if picked is None:
            return None
        target = next(r.next for r in rows if r.id == picked)
        return render_node(definition, target, state, catalog)

    if isinstance(node, ProductsNode):
        assert state.node_id is not None
        if not catalog:
            return None
        current, shown, _ = _products_view(node, catalog, _view_from_context(state.context))
        picked = _pick(inbound, [(r.id, r.title) for r in current.rows])
        if picked is None and inbound.is_reply and _is_category_nav(inbound.value):
            # A tap on an older list's category row: honoured; a stale key resolves to
            # the categories list in `_products_view`, never to an error.
            picked = inbound.value
        if picked is None:
            return None
        if picked == CATEGORIES_BACK_ROW_ID:
            target = _ProductsView(categories_page=shown.categories_page)
        elif picked.startswith(CATEGORIES_MORE_ROW_PREFIX):
            target = _ProductsView(
                categories_page=_as_int(picked[len(CATEGORIES_MORE_ROW_PREFIX) :])
            )
        elif picked.startswith(CATEGORY_ROW_PREFIX):
            target = _ProductsView(
                category=picked[len(CATEGORY_ROW_PREFIX) :],
                categories_page=shown.categories_page,
            )
        elif picked.startswith(MORE_ROW_PREFIX):
            target = replace(shown, page=_as_int(picked[len(MORE_ROW_PREFIX) :]))
        else:
            target = None
        if target is not None:
            return render_node(definition, state.node_id, state, catalog, view=target)
        product_id = picked[len(PRODUCT_ROW_PREFIX) :]
        item = next((i for i in catalog if i.product_id == product_id), None)
        if item is None:
            return None
        context = copy.deepcopy(state.context)
        _add_to_order(context, item)
        _clear_view(context)
        return render_node(
            definition, node.next_after_pick, replace(state, context=context), catalog
        )

    if isinstance(node, OrderSummaryNode):
        picked = _pick(
            inbound,
            [
                (ORDER_CONFIRM_ID, node.confirm_label),
                (ORDER_ADD_MORE_ID, node.add_more_label),
                (ORDER_CANCEL_ID, node.cancel_label),
            ],
        )
        if picked is None:
            return None
        context = copy.deepcopy(state.context)
        if picked == ORDER_CONFIRM_ID:
            context[CTX_ORDER_CONFIRMED] = True
            target = node.confirm_next
        elif picked == ORDER_ADD_MORE_ID:
            target = node.add_more_next
        else:
            context.pop(CTX_ORDER, None)
            context.pop(CTX_ORDER_CONFIRMED, None)
            target = node.cancel_next
        return render_node(definition, target, replace(state, context=context), catalog)

    if isinstance(node, CollectNode):
        ok, value = _validate_collect(node, inbound)
        if not ok:
            return None
        context = copy.deepcopy(state.context)
        context.setdefault(CTX_COLLECTED, {})[node.field] = value
        return render_node(definition, node.next, replace(state, context=context), catalog)

    # `text` and `handoff` never remain current (render_node leaves `None`), so an
    # inbound at one of them is a stale state: fall through to the idle rule.
    return None


def _unknown(
    definition: MenuDefinition,
    state: ThreadMenuState,
    node: Node | None,
    catalog: Sequence[CatalogItem],
) -> RenderResult:
    if state.attempts >= MAX_UNKNOWN_ATTEMPTS:
        fallback = definition.entry.fallback_node
        if fallback is not None:
            result = render_node(definition, fallback, state, catalog)
            return RenderResult(result.actions, replace(result.state, attempts=0))
        paused = replace(state, node_id=None, paused=True, attempts=0)
        return RenderResult(
            [
                SendText(UNKNOWN_HANDOFF_MESSAGE),
                Handoff(UNKNOWN_INPUT_REASON, _summary(paused, state.node_id or "")),
            ],
            paused,
        )
    help_line = node.error_message if isinstance(node, CollectNode) else HELP_LINE
    assert state.node_id is not None
    result = render_node(
        definition,
        state.node_id,
        state,
        catalog,
        help_line=help_line,
        view=_view_from_context(state.context),
    )
    return RenderResult(result.actions, replace(result.state, attempts=state.attempts + 1))


def _enter(
    definition: MenuDefinition,
    state: ThreadMenuState,
    target: str,
    inbound: Inbound,
    catalog: Sequence[CatalogItem],
) -> RenderResult:
    """Fresh entry into `target`: welcome first when this is a first message and the
    menu greets, unknown-input counter reset."""
    entry = definition.entry
    actions: list[OutboundAction] = []
    if inbound.first_message and entry.on_first_message and entry.welcome:
        actions.append(SendText(entry.welcome))
    result = render_node(definition, target, state, catalog)
    return RenderResult(actions + result.actions, replace(result.state, attempts=0))


def step(
    definition: MenuDefinition,
    state: ThreadMenuState,
    inbound: Inbound,
    *,
    catalog: Sequence[CatalogItem] = (),
) -> StepResult:
    """Advance one thread by one inbound event. See the module docstring for the rules."""
    if state.paused:
        return StepResult([], state, False)

    entry = definition.entry
    result: RenderResult
    if inbound.kind == "welcome":
        if not entry.on_first_message:
            return StepResult([], state, False)
        result = _enter(definition, state, definition.start_node, inbound, catalog)
    else:
        target = _global_route(definition, inbound)
        if target is not None:
            result = _enter(definition, state, target, inbound, catalog)
        else:
            node = definition.nodes.get(state.node_id) if state.node_id else None
            local = (
                _handle_at_node(definition, state, node, inbound, catalog)
                if node is not None
                else None
            )
            if local is not None:
                result = RenderResult(local.actions, replace(local.state, attempts=0))
            elif node is not None and not isinstance(node, TextNode | HandoffNode):
                result = _unknown(definition, state, node, catalog)
            elif inbound.first_message and not entry.on_first_message:
                return StepResult([], replace(state, node_id=None), False)
            else:
                result = _enter(
                    definition,
                    replace(state, node_id=None),
                    definition.start_node,
                    inbound,
                    catalog,
                )

    actions = list(result.actions)
    if result.state.context != state.context:
        actions.append(SetContext(copy.deepcopy(result.state.context)))
    handed_off = any(isinstance(a, Handoff) for a in actions)
    return StepResult(actions, result.state, handed_off)


__all__ = [
    "CATEGORIES_BACK_LABEL",
    "CATEGORIES_BACK_ROW_ID",
    "CATEGORIES_MORE_LABEL",
    "CATEGORIES_MORE_ROW_PREFIX",
    "CATEGORY_ROW_PREFIX",
    "CTX_CATEGORIES_PAGE",
    "CTX_COLLECTED",
    "CTX_PRODUCTS_CATEGORY",
    "CTX_ORDER",
    "CTX_ORDER_CONFIRMED",
    "CTX_PRODUCTS_PAGE",
    "ENGINE_VERSION",
    "HELP_LINE",
    "MAX_UNKNOWN_ATTEMPTS",
    "MORE_ROW_PREFIX",
    "PRODUCT_ROW_PREFIX",
    "UNKNOWN_HANDOFF_MESSAGE",
    "UNKNOWN_INPUT_REASON",
    "Button",
    "CatalogItem",
    "Handoff",
    "Inbound",
    "InboundKind",
    "ListRowOut",
    "ListSectionOut",
    "OutboundAction",
    "RenderResult",
    "SendButtons",
    "SendList",
    "SendText",
    "SetContext",
    "StepResult",
    "ThreadMenuState",
    "format_money",
    "inbound_from_message",
    "is_categories_mode",
    "order_total",
    "products_list",
    "render_node",
    "step",
]
