"""The ONE ordering rule of a brand's catalog (m-24955643).

The owner chooses the order of the categories (`brand_product_categories`, migration
0128) and of the products inside each category (`brand_products.position`). Every
surface that lists products — «Tus productos», the WhatsApp product list («Ver menú y
pedir»), the chat picker «Foto o menú», the menu-import review — sorts with
`order_catalog`, so they can never disagree.

The rule, in order:

1. Categories the owner placed, in the owner's order.
2. Categories nobody placed yet (free text typed on a product, or a new category the
   menu import proposes), alphabetically, case- and accent-insensitive.
3. The fallback «Otros» (a blank category, or one literally called «Otros») last —
   unless the owner placed it explicitly, then rule 1 wins.
4. Inside a category: `position`, then the name (case-insensitive), then the input
   order (the sort is stable).

Category names match case-insensitively and ignoring surrounding/duplicate spaces and
accents («Bebidas», « bebidas », «BEBIDAS» are one category). Pure: no I/O.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable, Sequence
from typing import Final

#: Section title for products whose `category` is blank (0038 defaults it to '').
FALLBACK_CATEGORY: Final = "Otros"


def category_key(name: str | None) -> str:
    """The comparable form of a category name; blank → the fallback's key."""
    cleaned = " ".join((name or "").split())
    if not cleaned:
        cleaned = FALLBACK_CATEGORY
    folded = unicodedata.normalize("NFKD", cleaned.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def category_label(name: str | None) -> str:
    """What a list shows as the section title: the name tidied, blank → «Otros»."""
    cleaned = " ".join((name or "").split())
    return cleaned or FALLBACK_CATEGORY


FALLBACK_KEY: Final = category_key(FALLBACK_CATEGORY)


def _attr(field: str, default: object) -> Callable[[object], object]:
    return lambda item: getattr(item, field, default)


def _index(category_order: Sequence[str]) -> dict[str, int]:
    index: dict[str, int] = {}
    for i, n in enumerate(category_order):
        index.setdefault(category_key(n), i)
    return index


def _bucket(key: str, index: dict[str, int]) -> tuple[int, int, str]:
    if key in index:
        return (0, index[key], "")
    if key == FALLBACK_KEY:
        return (2, 0, "")
    return (1, 0, key)


def category_rank(category: str | None, category_order: Sequence[str] = ()) -> tuple[int, int, str]:
    """The sort key of a category alone: (bucket, owner's index, alphabetical key)."""
    return _bucket(category_key(category), _index(category_order))


def order_catalog[T](
    items: Iterable[T],
    category_order: Sequence[str] = (),
    *,
    category: Callable[[T], str | None] | None = None,
    position: Callable[[T], int | None] | None = None,
    name: Callable[[T], str | None] | None = None,
) -> list[T]:
    """`items` in the catalog's order (module docstring). By default reads the items'
    `category`, `position` and `name` attributes; pass accessors for other shapes (the
    import review has no position: pass `position=lambda _: 0` to keep the source's
    order inside each category)."""
    get_category = category or _attr("category", "")  # type: ignore[assignment]
    get_position = position or _attr("position", 0)  # type: ignore[assignment]
    get_name = name or _attr("name", "")  # type: ignore[assignment]
    index = _index(category_order)

    def rank(item: T) -> tuple[int, int, str, int, str]:
        return (
            *_bucket(category_key(get_category(item)), index),  # type: ignore[arg-type]
            int(get_position(item) or 0),  # type: ignore[arg-type]
            " ".join(str(get_name(item) or "").split()).casefold(),
        )

    return sorted(items, key=rank)


def ordered_categories(
    categories: Iterable[str | None], category_order: Sequence[str] = ()
) -> list[str]:
    """The distinct categories present (by `category_key`, first spelling wins, blank
    kept as "") in the catalog's order — the sections a screen draws."""
    seen: dict[str, str] = {}
    for c in categories:
        cleaned = " ".join((c or "").split())
        seen.setdefault(category_key(cleaned), cleaned)
    index = _index(category_order)
    return sorted(seen.values(), key=lambda c: _bucket(category_key(c), index))


__all__ = [
    "FALLBACK_CATEGORY",
    "FALLBACK_KEY",
    "category_key",
    "category_label",
    "category_rank",
    "order_catalog",
    "ordered_categories",
]
