"""View models of «Ordenar tu menú» in «Galería» (m-24955643) — pure, no Reflex, no DB.

The owner chooses the order of the categories (a category moves with all its products)
and of the products inside each category (a product never leaves its category here:
changing it is an edit). That is the order the customer gets on WhatsApp («Ver menú y
pedir»), where a list shows 10 rows: with more than 10 products, 9 per screen and «Ver
más» (`qualify_api.whatsapp.menus.engine._pages`) — so the cut after the 9th product is
drawn while ordering. Spec: `docs/ux-orden-de-productos.md`.

The state keeps `OrderGroup`s (what the service returned, re-ordered optimistically);
everything the screen prints — positions, the handle's and the «⋯»'s spoken names, the
targets of «Primero / Subir uno / Bajar uno / Último», the cut — is built here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import urlencode

from .catalog_vm import RETURN_PARAM, safe_return_path

# -- copy (docs/ux-orden-de-productos.md §3) ---------------------------------------------
ORDER_BUTTON: Final = "Ordenar tu menú"
ORDER_DONE: Final = "Listo"
ORDER_TITLE: Final = "¿Qué quieres que vean primero?"
ORDER_HELP: Final = "Así los ve tu cliente en WhatsApp. Mantén pulsado y arrastra, o toca ⋯."
TAB_CATEGORIES: Final = "Categorías"
TAB_PRODUCTS: Final = "Productos"
FIRST_PAGE_CUT: Final = "Hasta aquí se ve sin tocar «Ver más»"
ORDER_FAILED: Final = "No pudimos guardar el orden. Revisa tu conexión y vuelve a moverlo."
#: Under the empty state's title «Aún no tienes productos» (so it does not say it twice).
ORDER_EMPTY: Final = "Agrega el primero y aquí eliges en qué orden los ven tus clientes."
ORDER_ONLY_ONE: Final = (
    "Con uno solo no hay nada que ordenar. Cuando agregues otro, aquí eliges cuál va primero."
)
UNDO_LABEL: Final = "Deshacer"
UNDONE: Final = "Listo: volvió el orden que tenías."
MOVE_FIRST: Final = "Primero"
MOVE_UP: Final = "Subir uno"
MOVE_DOWN: Final = "Bajar uno"
MOVE_LAST: Final = "Último"
MOVE_TO: Final = "Mover a la posición…"
BACK_TO_GALLERY: Final = "Galería"
BACK_TO_WHATSAPP: Final = "Tu menú de WhatsApp"

#: The two tabs' values.
TAB_CATEGORIES_VALUE: Final = "categorias"
TAB_PRODUCTS_VALUE: Final = "productos"

#: A WhatsApp list message holds 10 rows; with more products, 9 + «Ver más» per screen.
WHATSAPP_LIST_ROWS: Final = 10
FIRST_PAGE: Final = WHATSAPP_LIST_ROWS - 1

#: `/catalog?ordenar=1`: the catalog opens in «Ordenar tu menú» (WhatsApp step 3's link).
ORDER_PARAM: Final = "ordenar"


@dataclass(frozen=True)
class OrderItem:
    """One product as the order screen knows it."""

    product_id: str
    name: str
    price_label: str


@dataclass(frozen=True)
class OrderGroup:
    """One category: `name` as the products spell it ("" = without a category, which
    the screen calls «Otros» and moves like any other), `label` what it shows."""

    name: str
    label: str
    products: tuple[OrderItem, ...]


@dataclass(frozen=True)
class OrderProductVM:
    product_id: str
    name: str
    price_label: str
    category: str  # the group's `name` ("" = «Otros»)
    position: int  # 1-based, inside its category
    total: int
    movable: bool
    place_label: str  # the row's spoken name, with its place
    handle_label: str  # the handle's name («Mover «…», posición 3 de 5»)
    more_label: str
    up_to: int  # 0-based targets for «Subir uno» / «Bajar uno» / «Último»
    down_to: int
    last_to: int
    positions: tuple[int, ...]  # 1..total, for «Mover a la posición…»
    after_cut: bool  # the «Ver más» cut goes right after this row
    rank_group: str  # `data-rank-group`: only rows of one category trade places


@dataclass(frozen=True)
class OrderCategoryVM:
    name: str
    label: str
    count_label: str
    position: int
    total: int
    movable: bool
    place_label: str  # the row's spoken name, with its place
    handle_label: str  # the handle's name («Mover «…», posición 3 de 5»)
    more_label: str
    up_to: int
    down_to: int
    last_to: int
    positions: tuple[int, ...]
    rank_key: str  # `data-rank-key` ("" is not a key a DOM attribute keeps well)
    products: tuple[OrderProductVM, ...]
    after_cut: bool  # «Categorías»: the last category whole on WhatsApp's first screen


def count_label(n: int) -> str:
    return "1 producto" if n == 1 else f"{n} productos"


def category_place_label(label: str, position: int, total: int) -> str:
    """«Shawarmas, posición 3 de 5» — how a screen reader names the row."""
    return f"{label}, posición {position} de {total}"


def product_place_label(name: str, position: int, total: int, category: str) -> str:
    """«Shawarma mixto, posición 2 de 6 en «Shawarmas»»."""
    return f"{name}, posición {position} de {total} en «{category}»"


def category_handle_label(label: str, position: int, total: int) -> str:
    """The handle's name: «Mover «Shawarmas», posición 3 de 5»."""
    return f"Mover «{label}», posición {position} de {total}"


def product_handle_label(name: str, position: int, total: int, category: str) -> str:
    """«Mover «Shawarma mixto», posición 2 de 6 en «Shawarmas»»."""
    return f"Mover «{name}», posición {position} de {total} en «{category}»"


def lifted_text(name: str, position: int, total: int) -> str:
    """Said when Espacio lifts a row from the keyboard."""
    return (
        f"Levantaste «{name}», posición {position} de {total}. Muévelo con las flechas y "
        "suéltalo con Espacio. Escape lo deja donde estaba."
    )


def stayed_text(name: str) -> str:
    return f"«{name}» se quedó en su lugar."


def cancelled_text(name: str) -> str:
    return f"Listo, no cambiamos nada: «{name}» volvió a su lugar."


def more_label(name: str) -> str:
    """«Más opciones para «Shawarma mixto»»."""
    return f"Más opciones para «{name}»"


def _where(position: int, total: int) -> str:
    if position == 1:
        return "va primero"
    if position == total:
        return "va al final"
    return f"va en el lugar {position}"


def category_moved_text(label: str, position: int, total: int) -> str:
    """The toast after a category move: «Listo: «Shawarmas» va primero en tu menú.»."""
    return f"Listo: «{label}» {_where(position, total)} en tu menú."


def product_moved_text(name: str, position: int, total: int, category: str) -> str:
    """«Listo: «Shawarma mixto» va primero en «Shawarmas».»."""
    return f"Listo: «{name}» {_where(position, total)} en «{category}»."


def _targets(position: int, total: int) -> tuple[int, int, int]:
    index = position - 1
    return max(0, index - 1), min(total - 1, index + 1), total - 1


def category_rank_key(name: str) -> str:
    return f"cat:{name}"


def _focus_script(attr: str, key: str) -> str:
    """After a move the row re-renders in its new place (by key) and the browser drops
    the focus: give it back to the control `attr` names for that row."""
    return (
        "window.setTimeout(function () {"
        " var k = " + json.dumps(key) + ";"
        " var b = Array.prototype.find.call("
        "document.querySelectorAll('[" + attr + "]'),"
        " function (el) { return el.getAttribute('" + attr + "') === k; });"
        " if (b) b.focus(); }, 80)"
    )


def focus_more_script(rank_key: str) -> str:
    """Back to the row's «⋯» after a menu move (`data-order-more`)."""
    return _focus_script("data-order-more", rank_key)


def focus_handle_script(rank_key: str) -> str:
    """Back to the row's handle after a keyboard move (`ui.sort_handle`, `data-sort-key`)."""
    return _focus_script("data-sort-key", rank_key)


def build_order_view(groups: Sequence[OrderGroup]) -> list[OrderCategoryVM]:
    """The categories in order, each with its products, every row's labels and targets.
    The «Ver más» cut sits after the 9th product overall, only when WhatsApp would
    paginate (more than 10 products); in «Categorías», after the last category whose
    products all fit before it (none when the first category alone does not fit)."""
    total_products = sum(len(g.products) for g in groups)
    cut_at = FIRST_PAGE if total_products > WHATSAPP_LIST_ROWS else -1
    seen = 0
    total = len(groups)
    out: list[OrderCategoryVM] = []
    for c_index, group in enumerate(groups):
        n = len(group.products)
        rows: list[OrderProductVM] = []
        for p_index, item in enumerate(group.products):
            seen += 1
            position = p_index + 1
            up_to, down_to, last_to = _targets(position, n)
            rows.append(
                OrderProductVM(
                    product_id=item.product_id,
                    name=item.name,
                    price_label=item.price_label,
                    category=group.name,
                    position=position,
                    total=n,
                    movable=n > 1,
                    place_label=product_place_label(item.name, position, n, group.label),
                    handle_label=product_handle_label(item.name, position, n, group.label),
                    more_label=more_label(item.name),
                    up_to=up_to,
                    down_to=down_to,
                    last_to=last_to,
                    positions=tuple(range(1, n + 1)),
                    after_cut=seen == cut_at,
                    rank_group=f"order-products:{group.label}",
                )
            )
        following = len(groups[c_index + 1].products) if c_index + 1 < total else 0
        category_cut = cut_at > 0 and following > 0 and seen <= cut_at < seen + following
        position = c_index + 1
        up_to, down_to, last_to = _targets(position, total)
        out.append(
            OrderCategoryVM(
                name=group.name,
                label=group.label,
                count_label=count_label(n),
                position=position,
                total=total,
                movable=total > 1,
                place_label=category_place_label(group.label, position, total),
                handle_label=category_handle_label(group.label, position, total),
                more_label=more_label(group.label),
                up_to=up_to,
                down_to=down_to,
                last_to=last_to,
                positions=tuple(range(1, total + 1)),
                rank_key=category_rank_key(group.name),
                products=tuple(rows),
                after_cut=category_cut,
            )
        )
    return out


# -- the moves (remove-then-insert, the same move `assets/rank-drag.js` animates) ---------


def moved[T](items: Sequence[T], index: int, to: int) -> list[T]:
    out = list(items)
    item = out.pop(index)
    out.insert(max(0, min(len(out), to)), item)
    return out


def category_names(groups: Sequence[OrderGroup]) -> list[str]:
    """What `CatalogService.set_category_order` stores ("" = «Otros»)."""
    return [g.name for g in groups]


def find_category(groups: Sequence[OrderGroup], name: str) -> int | None:
    return next((i for i, g in enumerate(groups) if g.name == name), None)


def find_product(groups: Sequence[OrderGroup], product_id: str) -> tuple[int, int] | None:
    for g_index, group in enumerate(groups):
        for p_index, item in enumerate(group.products):
            if item.product_id == product_id:
                return g_index, p_index
    return None


def move_category(groups: Sequence[OrderGroup], name: str, to: int) -> list[OrderGroup] | None:
    """`name` to 0-based `to` (clamped); None when it is unknown or would not move."""
    index = find_category(groups, name)
    if index is None:
        return None
    to = max(0, min(len(groups) - 1, to))
    if to == index:
        return None
    return moved(groups, index, to)


def move_product(
    groups: Sequence[OrderGroup], product_id: str, to: int
) -> tuple[list[OrderGroup], int] | None:
    """The product to 0-based `to` inside ITS category (clamped): the new groups and the
    index of the group that changed; None when unknown or it would not move."""
    found = find_product(groups, product_id)
    if found is None:
        return None
    g_index, p_index = found
    group = groups[g_index]
    to = max(0, min(len(group.products) - 1, to))
    if to == p_index:
        return None
    out = list(groups)
    out[g_index] = replace(group, products=tuple(moved(group.products, p_index, to)))
    return out, g_index


def restore_products(
    groups: Sequence[OrderGroup], category: str, product_ids: Sequence[str]
) -> list[OrderGroup]:
    """The category's products back in `product_ids` order (any other kept after them):
    what «Deshacer» puts back on screen before it is stored again."""
    index = find_category(groups, category)
    if index is None:
        return list(groups)
    group = groups[index]
    by_id = {p.product_id: p for p in group.products}
    first = [by_id[i] for i in product_ids if i in by_id]
    rest = [p for p in group.products if p.product_id not in set(product_ids)]
    out = list(groups)
    out[index] = replace(group, products=tuple(first + rest))
    return out


def restore_categories(groups: Sequence[OrderGroup], names: Sequence[str]) -> list[OrderGroup]:
    """The categories back in `names` order (any other kept after them)."""
    by_name = {g.name: g for g in groups}
    first = [by_name[n] for n in names if n in by_name]
    rest = [g for g in groups if g.name not in set(names)]
    return first + rest


# -- the way in from WhatsApp («Cambiar el orden», step 3) ---------------------------------


def order_href(return_to: str = "") -> str:
    """`/catalog?ordenar=1&volver=<ruta>`: the catalog opens ordering, with the way back."""
    query = {ORDER_PARAM: "1"}
    safe = safe_return_path(return_to)
    if safe:
        query[RETURN_PARAM] = safe
    return f"/catalog?{urlencode(query)}"


def opens_order(params: object) -> bool:
    getter = getattr(params, "get", None)
    raw = getter(ORDER_PARAM, "") if callable(getter) else ""
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    return str(raw or "").strip() == "1"
