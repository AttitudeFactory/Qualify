"""Menu definition schema (WA-14, pure half).

A WhatsApp menu is **data written by the business** that the deterministic engine in
`engine.py` executes: it routes, it never decides (plan §5.3, rule D2 — automatic =
deterministic and declared, generative = assisted). This module is the shape of that
data: a `MenuDefinition` is what `whatsapp_menu_versions.definition` (jsonb, migration
`0057`, not part of this slice) will hold, and what the WA-16 editor produces.

Every Meta limit the definition can violate is enforced HERE, at validation time, so a
published version can never produce a message the Cloud API rejects at send time
(interactive messages and the conversational-components page, verified 2026-10-14):

- ice breakers: at most 4, each at most 80 characters, no emoji;
- commands: at most 30, name at most 32, hint at most 256, no emoji;
- reply buttons: at most 3, title at most 20;
- lists: at most 10 sections, at most 10 rows in total, row title at most 24,
  row description at most 72, section title at most 24, button label at most 20;
- body at most 1024, header text and footer at most 60.

Structural invariants are enforced by `MenuDefinition` as a whole: every `next` and
every node reference resolves to an existing node, `start_node` exists, option ids are
unique within a node, there is at most one `order_summary`, a chain of `text` nodes
never loops back on itself, and an `order_summary`'s `confirm` edge leads (possibly
through `collect`/`text` nodes) to a `handoff`.

No DB, no HTTP, no I/O of any kind.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Meta limits -----------------------------------------------------------------

MAX_ICE_BREAKERS = 4
ICE_BREAKER_MAX_LEN = 80
MAX_COMMANDS = 30
COMMAND_NAME_MAX_LEN = 32
COMMAND_HINT_MAX_LEN = 256
MAX_BUTTONS = 3
BUTTON_TITLE_MAX_LEN = 20
MAX_LIST_SECTIONS = 10
MAX_LIST_ROWS = 10
LIST_SECTION_TITLE_MAX_LEN = 24
LIST_ROW_TITLE_MAX_LEN = 24
LIST_ROW_DESCRIPTION_MAX_LEN = 72
LIST_BUTTON_MAX_LEN = 20
BODY_MAX_LEN = 1024
HEADER_MAX_LEN = 60
FOOTER_MAX_LEN = 60

# Reserved option ids the engine owns inside `order_summary` and `collect` nodes.
ORDER_CONFIRM_ID = "confirm"
ORDER_ADD_MORE_ID = "add_more"
ORDER_CANCEL_ID = "cancel"
YES_ID = "yes"
NO_ID = "no"

# Emoji detection: the pictographic blocks plus the variation selector that turns a
# text symbol into its emoji presentation. Conservative on purpose — a false positive
# costs an editor a rewording, a false negative costs a rejected publish.
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U00002b00-\U00002bff️]",
)

_NODE_ID_RE = re.compile(r"^[a-z0-9_][a-z0-9_\-]{0,63}$")


def contains_emoji(text: str) -> bool:
    """True when `text` holds a character Meta would render as an emoji."""
    return _EMOJI_RE.search(text) is not None


def normalize_keyword(text: str) -> str:
    """Case- and accent-insensitive canonical form used for keyword / ice-breaker /
    label matching: NFKD, combining marks dropped, casefolded, whitespace collapsed.
    Public because the engine must normalize inbound text with the very same rule."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


class _Model(BaseModel):
    # Definitions are authored by the editor and stored as jsonb; an unknown key is a
    # typo or a newer editor than engine, and either must fail loudly rather than be
    # silently dropped from the published version.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _no_emoji(label: str, value: str) -> str:
    if contains_emoji(value):
        raise ValueError(f"{label} must not contain emoji")
    return value


# --- Entry -----------------------------------------------------------------------


class IceBreaker(_Model):
    """One conversational-components prompt; its tap arrives as a plain text message
    equal to `text`, which is why the engine matches it by normalized text."""

    text: str = Field(min_length=1, max_length=ICE_BREAKER_MAX_LEN)
    node: str

    @field_validator("text")
    @classmethod
    def _text_no_emoji(cls, value: str) -> str:
        return _no_emoji("ice breaker text", value)


class Command(_Model):
    """One `/command`. Meta renders `hint` under the name; the tap arrives as text
    starting with `/name`."""

    name: str = Field(min_length=1, max_length=COMMAND_NAME_MAX_LEN)
    hint: str = Field(min_length=1, max_length=COMMAND_HINT_MAX_LEN)
    node: str

    @field_validator("name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        _no_emoji("command name", value)
        if any(ch.isspace() for ch in value) or value.startswith("/"):
            raise ValueError("command name must be a single word without the leading '/'")
        return value

    @field_validator("hint")
    @classmethod
    def _hint_no_emoji(cls, value: str) -> str:
        return _no_emoji("command hint", value)


class EntryConfig(_Model):
    """How a conversation enters the menu. `keywords` maps a normalized keyword to a
    node id (keys are normalized on validation, so `"Menú"` and `"menu"` collide)."""

    on_first_message: bool = True
    keywords: dict[str, str] = Field(default_factory=dict)
    ice_breakers: list[IceBreaker] = Field(default_factory=list, max_length=MAX_ICE_BREAKERS)
    commands: list[Command] = Field(default_factory=list, max_length=MAX_COMMANDS)
    welcome: str | None = Field(default=None, max_length=BODY_MAX_LEN)
    # Handoff node the engine renders after `MAX_UNKNOWN_ATTEMPTS` unrecognized
    # answers in a row; `None` falls back to the engine's built-in handoff text.
    fallback_node: str | None = None

    @field_validator("keywords")
    @classmethod
    def _normalize_keys(cls, value: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for raw, node in value.items():
            key = normalize_keyword(raw)
            if not key:
                raise ValueError("keyword must not be empty")
            if key in out:
                raise ValueError(f"duplicate keyword after normalization: {key!r}")
            out[key] = node
        return out

    @field_validator("ice_breakers")
    @classmethod
    def _unique_ice_breakers(cls, value: list[IceBreaker]) -> list[IceBreaker]:
        seen: set[str] = set()
        for ib in value:
            key = normalize_keyword(ib.text)
            if key in seen:
                raise ValueError(f"duplicate ice breaker after normalization: {key!r}")
            seen.add(key)
        return value

    @field_validator("commands")
    @classmethod
    def _unique_commands(cls, value: list[Command]) -> list[Command]:
        seen: set[str] = set()
        for cmd in value:
            key = normalize_keyword(cmd.name)
            if key in seen:
                raise ValueError(f"duplicate command after normalization: {key!r}")
            seen.add(key)
        return value

    def referenced_nodes(self) -> set[str]:
        refs = (
            set(self.keywords.values())
            | {ib.node for ib in self.ice_breakers}
            | {c.node for c in self.commands}
        )
        if self.fallback_node:
            refs.add(self.fallback_node)
        return refs


# --- Nodes -----------------------------------------------------------------------


class _InteractiveNode(_Model):
    body: str = Field(min_length=1, max_length=BODY_MAX_LEN)
    header: str | None = Field(default=None, max_length=HEADER_MAX_LEN)
    footer: str | None = Field(default=None, max_length=FOOTER_MAX_LEN)


class Option(_Model):
    """A reply button: `id` is the edge the webhook echoes back in `button_reply.id`."""

    id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=BUTTON_TITLE_MAX_LEN)
    next: str


class TextNode(_Model):
    """Say `body`; then continue to `next` if set, otherwise end the menu session
    (the thread returns to idle and the next message re-enters through `entry`)."""

    kind: Literal["text"]
    body: str = Field(min_length=1, max_length=BODY_MAX_LEN)
    next: str | None = None

    def references(self) -> set[str]:
        return {self.next} if self.next else set()


class ButtonsNode(_InteractiveNode):
    kind: Literal["buttons"]
    options: list[Option] = Field(min_length=1, max_length=MAX_BUTTONS)

    @field_validator("options")
    @classmethod
    def _unique_ids(cls, value: list[Option]) -> list[Option]:
        _assert_unique_ids([o.id for o in value], "button")
        return value

    def references(self) -> set[str]:
        return {o.next for o in self.options}


class ListRow(_Model):
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=LIST_ROW_TITLE_MAX_LEN)
    description: str | None = Field(default=None, max_length=LIST_ROW_DESCRIPTION_MAX_LEN)
    next: str


class ListSection(_Model):
    title: str = Field(min_length=1, max_length=LIST_SECTION_TITLE_MAX_LEN)
    rows: list[ListRow] = Field(min_length=1, max_length=MAX_LIST_ROWS)


class ListNode(_InteractiveNode):
    kind: Literal["list"]
    button_label: str = Field(min_length=1, max_length=LIST_BUTTON_MAX_LEN)
    sections: list[ListSection] = Field(min_length=1, max_length=MAX_LIST_SECTIONS)

    @model_validator(mode="after")
    def _rows_total(self) -> ListNode:
        rows = [r for s in self.sections for r in s.rows]
        if len(rows) > MAX_LIST_ROWS:
            raise ValueError(f"list has {len(rows)} rows, Meta allows at most {MAX_LIST_ROWS}")
        _assert_unique_ids([r.id for r in rows], "list row")
        return self

    def references(self) -> set[str]:
        return {r.next for s in self.sections for r in s.rows}


class ProductsNode(_InteractiveNode):
    """Catalog list. Rows are injected at runtime from the brand catalog (WA-15's
    adapter over `brand_products`); `page_size` caps rows per message, and when the
    catalog overflows the engine spends one row on "Ver más"."""

    kind: Literal["products"]
    source: Literal["catalog"] = "catalog"
    button_label: str = Field(default="Ver productos", min_length=1, max_length=LIST_BUTTON_MAX_LEN)
    more_label: str = Field(default="Ver más", min_length=1, max_length=LIST_ROW_TITLE_MAX_LEN)
    page_size: int = Field(default=MAX_LIST_ROWS, ge=2, le=MAX_LIST_ROWS)
    next_after_pick: str
    empty_body: str = Field(
        default="Por ahora no tenemos productos disponibles.",
        min_length=1,
        max_length=BODY_MAX_LEN,
    )

    def references(self) -> set[str]:
        return {self.next_after_pick}


class OrderSummaryNode(_Model):
    """Renders `context.order` as lines plus `body` with `{total}` substituted, and
    three fixed buttons (`confirm` / `add_more` / `cancel`, ids owned by the engine).
    `confirm_next` must lead to a `handoff` — the order is always closed by a person
    (plan §5.3)."""

    kind: Literal["order_summary"]
    body: str = Field(min_length=1, max_length=BODY_MAX_LEN)
    confirm_next: str
    add_more_next: str
    cancel_next: str
    confirm_label: str = Field(default="Confirmar", min_length=1, max_length=BUTTON_TITLE_MAX_LEN)
    add_more_label: str = Field(
        default="Agregar más", min_length=1, max_length=BUTTON_TITLE_MAX_LEN
    )
    cancel_label: str = Field(default="Cancelar", min_length=1, max_length=BUTTON_TITLE_MAX_LEN)
    empty_line: str = Field(default="(tu pedido está vacío)", min_length=1, max_length=200)

    @field_validator("body")
    @classmethod
    def _has_total(cls, value: str) -> str:
        if "{total}" not in value:
            raise ValueError("order_summary body must contain the {total} placeholder")
        return value

    def references(self) -> set[str]:
        return {self.confirm_next, self.add_more_next, self.cancel_next}


class CollectNode(_Model):
    """Ask `prompt`, validate the answer, store it under `context.collected[field]`,
    continue to `next`. `yes_no` is rendered as two buttons and also accepts typed
    sí/no; `phone` accepts 7–15 digits with optional `+` and separators."""

    kind: Literal["collect"]
    prompt: str = Field(min_length=1, max_length=BODY_MAX_LEN)
    field: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    validation: Literal["text", "phone", "yes_no"] = "text"
    error_message: str = Field(
        default="No pude entender tu respuesta.", min_length=1, max_length=BODY_MAX_LEN
    )
    yes_label: str = Field(default="Sí", min_length=1, max_length=BUTTON_TITLE_MAX_LEN)
    no_label: str = Field(default="No", min_length=1, max_length=BUTTON_TITLE_MAX_LEN)
    next: str

    def references(self) -> set[str]:
        return {self.next}


class HandoffNode(_Model):
    """Say `message`, hand the thread to a person and pause the menu on it."""

    kind: Literal["handoff"]
    message: str = Field(min_length=1, max_length=BODY_MAX_LEN)
    reason: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")

    def references(self) -> set[str]:
        return set()


Node = Annotated[
    TextNode | ButtonsNode | ListNode | ProductsNode | OrderSummaryNode | CollectNode | HandoffNode,
    Field(discriminator="kind"),
]


def _assert_unique_ids(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"duplicate {what} id {i!r} within one node")
        seen.add(i)


# --- Definition ------------------------------------------------------------------


class MenuDefinition(_Model):
    version: Literal[1] = 1
    entry: EntryConfig = Field(default_factory=EntryConfig)
    nodes: dict[str, Node] = Field(min_length=1)
    start_node: str

    @field_validator("nodes")
    @classmethod
    def _node_ids(cls, value: dict[str, Node]) -> dict[str, Node]:
        for node_id in value:
            if not _NODE_ID_RE.match(node_id):
                raise ValueError(
                    f"node id {node_id!r} must match {_NODE_ID_RE.pattern} "
                    "(lowercase, digits, '_' or '-', at most 64 chars)"
                )
        return value

    @model_validator(mode="after")
    def _structure(self) -> MenuDefinition:
        if self.start_node not in self.nodes:
            raise ValueError(f"start_node {self.start_node!r} is not a node")
        dangling: list[str] = []
        for node_id, node in self.nodes.items():
            for ref in sorted(node.references()):
                if ref not in self.nodes:
                    dangling.append(f"{node_id} -> {ref!r}")
        for ref in sorted(self.entry.referenced_nodes()):
            if ref not in self.nodes:
                dangling.append(f"entry -> {ref!r}")
        if dangling:
            raise ValueError("dangling node references: " + ", ".join(dangling))

        fallback = self.entry.fallback_node
        if fallback is not None and not isinstance(self.nodes[fallback], HandoffNode):
            raise ValueError(f"entry.fallback_node {fallback!r} must be a handoff node")

        summaries = [i for i, n in self.nodes.items() if isinstance(n, OrderSummaryNode)]
        if len(summaries) > 1:
            raise ValueError(f"at most one order_summary node per menu, found {summaries}")

        self._check_text_chains()
        for node_id in summaries:
            self._check_confirm_reaches_handoff(node_id)
        return self

    def _check_text_chains(self) -> None:
        """A `text` node chains into `next` immediately; a cycle made only of such
        nodes would render forever."""
        for start in self.nodes:
            seen = {start}
            cur = self.nodes[start]
            while isinstance(cur, TextNode) and cur.next:
                if cur.next in seen:
                    raise ValueError(f"text nodes form a cycle through {cur.next!r}")
                seen.add(cur.next)
                cur = self.nodes[cur.next]

    def _check_confirm_reaches_handoff(self, summary_id: str) -> None:
        node = self.nodes[summary_id]
        assert isinstance(node, OrderSummaryNode)
        cur_id = node.confirm_next
        seen: set[str] = set()
        while cur_id not in seen:
            seen.add(cur_id)
            cur = self.nodes[cur_id]
            if isinstance(cur, HandoffNode):
                return
            if isinstance(cur, TextNode | CollectNode) and cur.next:
                cur_id = cur.next
                continue
            break
        raise ValueError(
            f"order_summary {summary_id!r}: confirm must lead to a handoff node "
            "(directly or through text/collect nodes)"
        )

    def node(self, node_id: str) -> Node:
        """Look a node up; `KeyError` here is an engine bug, never user input."""
        return self.nodes[node_id]


__all__ = [
    "BODY_MAX_LEN",
    "BUTTON_TITLE_MAX_LEN",
    "COMMAND_HINT_MAX_LEN",
    "COMMAND_NAME_MAX_LEN",
    "FOOTER_MAX_LEN",
    "HEADER_MAX_LEN",
    "ICE_BREAKER_MAX_LEN",
    "LIST_BUTTON_MAX_LEN",
    "LIST_ROW_DESCRIPTION_MAX_LEN",
    "LIST_ROW_TITLE_MAX_LEN",
    "LIST_SECTION_TITLE_MAX_LEN",
    "MAX_BUTTONS",
    "MAX_COMMANDS",
    "MAX_ICE_BREAKERS",
    "MAX_LIST_ROWS",
    "MAX_LIST_SECTIONS",
    "NO_ID",
    "ORDER_ADD_MORE_ID",
    "ORDER_CANCEL_ID",
    "ORDER_CONFIRM_ID",
    "YES_ID",
    "ButtonsNode",
    "CollectNode",
    "Command",
    "EntryConfig",
    "HandoffNode",
    "IceBreaker",
    "ListNode",
    "ListRow",
    "ListSection",
    "MenuDefinition",
    "Node",
    "Option",
    "OrderSummaryNode",
    "ProductsNode",
    "TextNode",
    "contains_emoji",
    "normalize_keyword",
]
