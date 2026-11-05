"""View models of «Agrupa tus productos» (m-24955838) — pure, no Reflex, no DB.

Products loaded from a page or a photo before the import proposed categories have
none, so WhatsApp shows them as one long list and «Ordenar tu menú» has nothing to
order. The notice («Tienes N productos sin categoría…») opens a flow of two steps:

1. the groups `CatalogService.suggest_category_groups` proposes (by the products'
   leading word), each accepted by default, with «Cambiar nombre» and «No agrupar»;
2. what is left, with checkboxes and «Poner en…» an existing category or a new one,
   or «Dejar el resto en «Otros»» (the notice then stays hidden until a NEW product
   without a category appears).

Spec: `docs/ux-categorias-de-productos.md`. Every write is
`CatalogService.set_products_category` (through `catalog_provider`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

from qualify_api.catalog.order import FALLBACK_KEY, category_key
from qualify_api.catalog.service import CATEGORY_NAME_MAX, CATEGORY_TOO_LONG_TEXT

from .catalog_vm import RETURN_PARAM, safe_return_path

# -- copy (docs/ux-categorias-de-productos.md §1, §2, §5) --------------------------------
GROUP_BUTTON: Final = "Agruparlos"
ONLY_OTROS_TEXT: Final = (
    "Todos tus productos están en «Otros». Agrúpalos para que tu cliente encuentre rápido lo "
    "que busca."
)
ONLY_OTROS_BUTTON: Final = "Agrupar tus productos"
FLOW_TITLE: Final = "Agrupa tus productos"
STEP1_TITLE: Final = "Te proponemos estos grupos"
STEP1_HELP: Final = "Los juntamos por la primera palabra del nombre. Revisa cada uno."
RENAME: Final = "Cambiar nombre"
SKIP: Final = "No agrupar"
UNSKIP: Final = "Deshacer"
NEXT: Final = "Siguiente"
NAME_LABEL: Final = "Nombre de la categoría"
NAME_HELP: Final = "Hasta 24 letras: es el título que ve tu cliente en WhatsApp."
NAME_PLACEHOLDER: Final = "Por ejemplo: Bebidas"
NAME_EMPTY: Final = "Escribe el nombre de la categoría."
NAME_TOO_LONG: Final = CATEGORY_TOO_LONG_TEXT
NAME_MAX: Final = CATEGORY_NAME_MAX
STEP2_TITLE: Final = "¿Dónde va cada uno de estos?"
STEP2_HELP: Final = "Marca los que van juntos y toca «Poner en…»."
BACK_TO_GROUPS: Final = "Volver a los grupos"
PUT_IN: Final = "Poner en…"
NEW_CATEGORY: Final = "+ Nueva categoría"
PUT_HERE: Final = "Poner aquí"
LEAVE_REST: Final = "Dejar el resto en «Otros»"
DONE_HELP: Final = "Así los ve tu cliente en WhatsApp: elige qué va primero."
SAVE_FAILED: Final = "No pudimos guardar la categoría. Revisa tu conexión y vuelve a intentarlo."
UNDONE: Final = "Listo: volvieron a «Otros»."
UNDO_LABEL: Final = "Deshacer"
ALL_GROUPED: Final = "Todos tus productos ya tienen categoría."
#: The value of «+ Nueva categoría» among the choices of «Poner en…».
NEW_CHOICE: Final = "__nueva__"

STEP_GROUPS: Final = 1
STEP_LEFTOVERS: Final = 2
STEP_DONE: Final = 3

#: `/catalog?agrupar=1`: the catalog opens the flow (WhatsApp step 3's «Agruparlos»).
GROUP_PARAM: Final = "agrupar"


def is_uncategorized(category: str | None) -> bool:
    """No category, or the fallback «Otros» itself."""
    return category_key(category) == FALLBACK_KEY


def notice_text(n: int) -> str:
    """«Tienes 22 productos sin categoría. En WhatsApp salen todos en una sola lista larga.»"""
    return f"Tienes {n} productos sin categoría. En WhatsApp salen todos en una sola lista larga."


def notice_count(uncategorized_ids: Iterable[str], dismissed: Iterable[str]) -> int:
    """How many products the notice counts — 0 when it must not show: fewer than 2
    without a category, or the owner chose «Dejar el resto en «Otros»» and no NEW one
    has appeared since (`dismissed` = the ids left in «Otros» then)."""
    ids = list(dict.fromkeys(uncategorized_ids))
    if len(ids) < 2:
        return 0
    if set(ids) <= set(dismissed):
        return 0
    return len(ids)


def products_label(n: int) -> str:
    return "1 producto" if n == 1 else f"{n} productos"


def names_line(names: Sequence[str], shown: int = 4) -> str:
    """«Combo Vecino, Combo Shawarma, Combo Carne, Combo Mixto, …»."""
    head = ", ".join(names[:shown])
    return f"{head}, …" if len(names) > shown else head


def name_counter(text: str) -> str:
    """«8 de 24»."""
    return f"{len(text.strip())} de {NAME_MAX}"


def name_error(text: str) -> str:
    """ "" when the name can be saved, else what to do, in the owner's words."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return NAME_EMPTY
    if len(cleaned) > NAME_MAX:
        return NAME_TOO_LONG
    return ""


def left_line(n: int) -> str:
    """Under step 1: «Quedan 7 para el paso 2»."""
    if n <= 0:
        return ""
    return "Queda 1 para el paso 2" if n == 1 else f"Quedan {n} para el paso 2"


def chosen_label(n: int) -> str:
    return "1 elegido" if n == 1 else f"{n} elegidos"


def saved_text(n: int, category: str) -> str:
    """«Listo: 5 productos ahora están en «Combos».»."""
    if n == 1:
        return f"Listo: 1 producto ahora está en «{category}»."
    return f"Listo: {n} productos ahora están en «{category}»."


def done_title(n: int) -> str:
    """«Listo: tu menú tiene 5 categorías.»."""
    if n == 1:
        return "Listo: tu menú tiene 1 categoría."
    return f"Listo: tu menú tiene {n} categorías."


def groups_saved_text(n: int) -> str:
    """After step 1: «Listo: guardamos 4 categorías.»."""
    if n == 1:
        return "Listo: guardamos 1 categoría."
    return f"Listo: guardamos {n} categorías."


@dataclass(frozen=True)
class GroupCardVM:
    index: int
    name: str
    count_label: str
    names_line: str
    accepted: bool
    renaming: bool
    rename_label: str  # «Cambiar nombre de «Combos»»
    skip_label: str


@dataclass(frozen=True)
class LeftoverVM:
    product_id: str
    name: str
    price_label: str
    checked: bool


def group_cards(groups: Sequence[dict], names: dict[str, str], renaming: int) -> list[GroupCardVM]:
    """`groups`: [{"name", "ids", "accepted"}] in the order proposed."""
    out: list[GroupCardVM] = []
    for i, g in enumerate(groups):
        ids = list(g["ids"])
        out.append(
            GroupCardVM(
                index=i,
                name=g["name"],
                count_label=products_label(len(ids)),
                names_line=names_line([names.get(pid, "") for pid in ids]),
                accepted=bool(g["accepted"]),
                renaming=i == renaming,
                rename_label=f"{RENAME} de «{g['name']}»",
                skip_label=f"{SKIP} «{g['name']}»",
            )
        )
    return out


def leftovers_after(products: Sequence[dict], groups: Sequence[dict]) -> list[dict]:
    """The products without a category that no ACCEPTED group takes: step 2's list."""
    taken = {pid for g in groups if g["accepted"] for pid in g["ids"]}
    return [p for p in products if p["product_id"] not in taken]


def leftover_rows(products: Sequence[dict], checked: Iterable[str]) -> list[LeftoverVM]:
    marked = set(checked)
    return [
        LeftoverVM(
            product_id=p["product_id"],
            name=p["name"],
            price_label=p.get("price_label", ""),
            checked=p["product_id"] in marked,
        )
        for p in products
    ]


def same_category(a: str, b: str) -> bool:
    return category_key(a) == category_key(b)


def existing_spelling(name: str, categories: Iterable[str]) -> str:
    """A typed name that matches an existing category (case and accents ignored) joins
    it with ITS spelling, instead of creating a twin."""
    cleaned = " ".join(name.split())
    return next((c for c in categories if same_category(c, cleaned)), cleaned)


def group_href(return_to: str = "") -> str:
    """`/catalog?agrupar=1&volver=<ruta>`."""
    query = {GROUP_PARAM: "1"}
    safe = safe_return_path(return_to)
    if safe:
        query[RETURN_PARAM] = safe
    return f"/catalog?{urlencode(query)}"


def opens_group(params: object) -> bool:
    getter = getattr(params, "get", None)
    raw = getter(GROUP_PARAM, "") if callable(getter) else ""
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    return str(raw or "").strip() == "1"


# -- the menu-import review: the category each new product will get (§4) ------------------


def import_category_label(category: str) -> str:
    return category.strip() or "Sin categoría"


def import_categories_line(new_categories: Sequence[str]) -> str:
    """«Vamos a crear 4 categorías: Combos, Shawarmas, Ensaladas y Bebidas. Cámbialas si
    quieres.»; "" when none is new."""
    names = list(dict.fromkeys(new_categories))
    if not names:
        return ""
    if len(names) == 1:
        return f"Vamos a crear 1 categoría: {names[0]}. Cámbiala si quieres."
    listed = ", ".join(names[:-1]) + f" y {names[-1]}"
    return f"Vamos a crear {len(names)} categorías: {listed}. Cámbialas si quieres."
