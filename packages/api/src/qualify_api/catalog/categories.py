"""Grouping suggestions for products without a category, with no AI (m-24955838).

Products created by the menu import before `wa-import-3` have no category, so the
catalog is one section on WhatsApp and «Ordenar tu menú» has no categories to order.
`suggest_groups` proposes sections the owner confirms with one tap
(`CatalogService.set_products_category`):

- Only products whose category is blank (or «Otros») are considered.
- Products are grouped by their leading word (case and accents folded): «Combo
  Vecino», «Combo Mixto» → «Combos»; «Shawarma de carne», «Shawarma mixto» →
  «Shawarmas». A group needs at least 2 products; the rest stay ungrouped (the owner
  assigns them by hand — drinks rarely share a first word).
- The name is the plural of the leading word as the first product spells it
  (`pluralize`), or the spelling of an existing category with the same key, so a
  suggestion joins a section the brand already has instead of creating a twin.
- Groups come out largest first, then by name; products inside keep the input order.

Pure: no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from qualify_api.catalog.order import FALLBACK_KEY, category_key

#: Leading words that never name a section (articles, connectors, sizes).
_NOT_A_GROUP = frozenset(
    {"el", "la", "los", "las", "un", "una", "de", "del", "con", "sin", "y", "para", "mi"}
)
_VOWELS = "aeiouáéíóú"
_STRESSED_TO_PLAIN = str.maketrans("áéíóú", "aeiou")


class ProductLike(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def name(self) -> str: ...

    @property
    def category(self) -> str: ...


@dataclass(frozen=True)
class SuggestedGroup:
    """A section to propose: its `name` and the products that would go in it."""

    name: str
    product_ids: tuple[UUID, ...]


def pluralize(word: str) -> str:
    """Simple Spanish plural, keeping the word's capitalisation:
    already plural (ends in «s»/«x») → unchanged («Papas»); vowel → +s («Combo» →
    «Combos», «Café» → «Cafés»); «z» → «ces» («Lápiz» → «Lápices»); a stressed final
    syllable loses its accent before +es («Limón» → «Limones», «Maracuyá» stays vowel);
    any other consonant → +es («Pan» → «Panes», «Sándwich» → «Sándwiches»)."""
    if not word:
        return word
    last = word[-1].lower()
    if last in "sx":
        return word
    if last in _VOWELS:
        return word + "s"
    if last == "z":
        return word[:-1] + "ces"
    if len(word) >= 2 and word[-2].lower() in "áéíóú":
        word = word[:-2] + word[-2].translate(_STRESSED_TO_PLAIN) + word[-1]
    return word + "es"


def _leading_word(name: str) -> str:
    words = re.findall(r"[^\W\d_][\w'-]*", name or "")
    return words[0] if words else ""


def _fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def is_uncategorized(category: str | None) -> bool:
    return category_key(category) == FALLBACK_KEY


def uncategorized_count(products: Iterable[ProductLike]) -> int:
    """How many products have no category — the «N productos sin categoría» notice."""
    return sum(1 for p in products if is_uncategorized(p.category))


def suggest_groups(
    products: Iterable[ProductLike], existing_categories: Sequence[str] = ()
) -> tuple[SuggestedGroup, ...]:
    """Sections for the products without a category (module docstring)."""
    known = {category_key(c): " ".join(c.split()) for c in existing_categories if c.strip()}
    buckets: dict[str, list[ProductLike]] = {}
    for product in products:
        if not is_uncategorized(product.category):
            continue
        word = _leading_word(product.name)
        if len(word) < 3 or _fold(word) in _NOT_A_GROUP:
            continue
        # «Papa» and «Papas» are one group: key on the plural.
        buckets.setdefault(_fold(pluralize(word)), []).append(product)
    groups: list[SuggestedGroup] = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        word = _leading_word(members[0].name)
        plural = pluralize(word[:1].upper() + word[1:].lower())
        name = known.get(category_key(plural), plural)
        groups.append(SuggestedGroup(name, tuple(p.id for p in members)))
    groups.sort(key=lambda g: (-len(g.product_ids), category_key(g.name)))
    return tuple(groups)


__all__ = [
    "SuggestedGroup",
    "is_uncategorized",
    "pluralize",
    "suggest_groups",
    "uncategorized_count",
]
