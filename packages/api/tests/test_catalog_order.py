"""The catalog's one ordering rule (m-24955643), offline.

- `order_catalog` / `ordered_categories`: the owner's categories first, the rest
  alphabetically, «Otros» last; `position` then name inside a category.
- `CatalogService` order writes (`set_category_order`, `reorder_products`,
  `move_category`, `move_product`) and reads (`list_products`, `list_ordered`) through a
  fake `tenant_session` holding a Bianki-shaped brand (invented names).
- The WhatsApp list (`to_catalog_items`), the chat picker (`list_products_for_chat`) and
  «Tu menú» return the SAME order; the import review follows the same rule.

The real table, its constraints and RLS are `test_catalog_order_db.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql.dml import Delete

from qualify_api.catalog.models import BrandProduct, BrandProductCategory, ProductMedia
from qualify_api.catalog.order import (
    FALLBACK_CATEGORY,
    category_key,
    category_label,
    order_catalog,
    ordered_categories,
)
from qualify_api.catalog.service import (
    CatalogService,
    OrderRefused,
    UnknownCategory,
    UnknownProduct,
)
from qualify_api.whatsapp.catalog import to_catalog_items
from qualify_api.whatsapp.menus.import_ai import FoundProduct, order_found_products

TENANT = UUID("00000000-0000-4000-8000-0000000000aa")
BRAND = UUID("00000000-0000-4000-8000-0000000000bb")
USER = UUID("00000000-0000-4000-8000-0000000000cc")


@dataclass(frozen=True)
class Item:
    name: str
    category: str | None = ""
    position: int | None = 0


def names(items: list[Any]) -> list[str]:
    return [i.name for i in items]


# --- the pure rule ----------------------------------------------------------------------


def _bianki() -> list[Item]:
    """Bianki-shaped: the alphabetical order puts the shawarmas LAST (the bug)."""
    return [
        Item("Limonada", "Bebidas", 1),
        Item("Agua", "Bebidas", 0),
        Item("Combo familiar", "Combos", 1),
        Item("Combo personal", "Combos", 0),
        Item("Ensalada griega", "Ensaladas", 0),
        Item("Shawarma mixto", "Shawarmas", 1),
        Item("Shawarma de pollo", "Shawarmas", 0),
        Item("Salsa de ajo", "", 0),
    ]


def test_without_a_stored_order_categories_are_alphabetical_and_otros_last() -> None:
    assert names(order_catalog(_bianki())) == [
        "Agua",
        "Limonada",
        "Combo personal",
        "Combo familiar",
        "Ensalada griega",
        "Shawarma de pollo",
        "Shawarma mixto",
        "Salsa de ajo",
    ]


def test_the_owners_order_comes_first_then_the_rest_alphabetically() -> None:
    ordered = order_catalog(_bianki(), ["Shawarmas", "Combos"])
    assert names(ordered) == [
        "Shawarma de pollo",
        "Shawarma mixto",
        "Combo personal",
        "Combo familiar",
        "Agua",
        "Limonada",
        "Ensalada griega",
        "Salsa de ajo",
    ]


def test_category_names_match_ignoring_case_accents_and_spaces() -> None:
    items = [Item("Té", " bebidas  frías "), Item("Pan", "Panadería")]
    assert names(order_catalog(items, ["PANADERIA", "Bebidas Frías"])) == ["Pan", "Té"]
    assert category_key(" Bebidas  FRÍAS ") == category_key("bebidas frias")


def test_blank_and_literal_otros_are_one_fallback_group_last_unless_placed() -> None:
    items = [Item("A", ""), Item("B", "Otros", 1), Item("C", "Zumos"), Item("D", None, 2)]
    assert names(order_catalog(items)) == ["C", "A", "B", "D"]
    assert names(order_catalog(items, ["otros"])) == ["A", "B", "D", "C"]
    assert category_label("  ") == FALLBACK_CATEGORY == category_label(None)


def test_inside_a_category_position_then_name_then_input_order() -> None:
    items = [
        Item("b", "X", 1),
        Item("B", "X", 0),
        Item("a", "X", 1),
        Item("dup", "X", None),
        Item("dup", "X", 0),
    ]
    assert names(order_catalog(items)) == ["B", "dup", "dup", "a", "b"]


def test_a_stored_category_without_products_is_harmless() -> None:
    assert names(order_catalog(_bianki(), ["Postres", "Shawarmas"]))[:2] == [
        "Shawarma de pollo",
        "Shawarma mixto",
    ]


def test_ordered_categories_lists_each_section_once_in_order() -> None:
    cats = [i.category for i in _bianki()] + ["bebidas"]
    assert ordered_categories(cats, ["Shawarmas", "Combos"]) == [
        "Shawarmas",
        "Combos",
        "Bebidas",
        "Ensaladas",
        "",
    ]


def test_the_import_review_uses_the_same_rule_and_keeps_the_sources_order() -> None:
    def found(name: str, category: str = "") -> FoundProduct:
        return FoundProduct(name, None, "", "", name, category=category)

    proposal = [
        found("Té frío", "Bebidas"),
        found("Sin categoría"),
        found("Shawarma XL", "Shawarmas"),
        found("Postre nuevo", "Postres"),
        found("Agua", "Bebidas"),
    ]
    ordered = order_found_products(proposal, ["Shawarmas", "Combos"])
    assert [p.name for p in ordered] == [
        "Shawarma XL",
        "Té frío",  # new categories after the placed ones, alphabetically,
        "Agua",  # in the source's order inside each
        "Postre nuevo",
        "Sin categoría",  # «Otros» last
    ]


# --- the service, over a fake tenant door -----------------------------------------------


class FakeSession:
    """A brand's `brand_products` and `brand_product_categories` in memory; it answers
    the statements the order code issues and records the advisory lock."""

    def __init__(self, world: World) -> None:
        self.w = world

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, stmt: Any) -> None:
        if isinstance(stmt, Delete):
            self.w.categories = [c for c in self.w.categories if c.brand_id != BRAND]
            return
        assert "pg_advisory_xact_lock" in str(stmt)
        self.w.locks += 1

    def scalars(self, stmt: Any) -> list[Any]:
        desc = stmt.column_descriptions[0]
        if desc["entity"] is ProductMedia:
            return []
        if desc["entity"] is BrandProductCategory:
            rows = sorted(self.w.categories, key=lambda c: (c.position, c.name_key))
            return [c.name for c in rows]
        assert desc["entity"] is BrandProduct
        rows = list(self.w.products)
        if "is_active IS true" in str(stmt):
            rows = [p for p in rows if p.is_active]
        if desc["name"] == "category":
            return [p.category for p in rows]
        return sorted(rows, key=lambda p: (p.position, p.name))

    def add(self, row: Any) -> None:
        assert isinstance(row, BrandProductCategory)
        assert row.tenant_id == TENANT
        self.w.categories.append(row)

    def flush(self) -> None:
        keys = [(c.brand_id, c.name_key) for c in self.w.categories]
        assert len(keys) == len(set(keys)), "uq_brand_product_categories_key"


class World:
    def __init__(self) -> None:
        self.products: list[BrandProduct] = []
        self.categories: list[BrandProductCategory] = []
        self.locks = 0
        self.service = CatalogService(store=None)  # type: ignore[arg-type]

    def product(self, name: str, category: str, position: int, active: bool = True) -> UUID:
        row = BrandProduct(
            id=uuid4(),
            tenant_id=TENANT,
            brand_id=BRAND,
            name=name,
            slug=name.lower().replace(" ", "-"),
            description="",
            price_amount=Decimal("5"),
            price_currency="USD",
            category=category,
            tags=[],
            is_active=active,
            position=position,
        )
        self.products.append(row)
        return row.id

    def by_name(self, name: str) -> BrandProduct:
        return next(p for p in self.products if p.name == name)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    from qualify_api.catalog import service as mod

    w = World()
    # Global positions as `create_product` appends them, in creation order.
    for i, (name, category) in enumerate(
        [
            ("Agua", "Bebidas"),
            ("Ensalada griega", "Ensaladas"),
            ("Combo personal", "Combos"),
            ("Shawarma de pollo", "Shawarmas"),
            ("Shawarma mixto", "Shawarmas"),
            ("Limonada", "Bebidas"),
            ("Combo familiar", "Combos"),
            ("Salsa de ajo", ""),
        ]
    ):
        w.product(name, category, i)
    w.product("Shawarma retirado", "Shawarmas", 99, active=False)

    def door(tenant_id: UUID) -> FakeSession:
        assert tenant_id == TENANT
        return FakeSession(w)

    monkeypatch.setattr(mod, "tenant_session", door)
    return w


def test_set_category_order_stores_it_and_every_read_follows(world: World) -> None:
    stored = world.service.set_category_order(
        tenant_id=TENANT, brand_id=BRAND, names=["  shawarmas ", "Combos"], user_id=USER
    )
    assert stored == ("shawarmas", "Combos")
    assert [(c.name_key, c.position, c.updated_by) for c in world.categories] == [
        ("shawarmas", 0, USER),
        ("combos", 1, USER),
    ]
    assert world.locks == 1
    listed = world.service.list_products(tenant_id=TENANT, brand_id=BRAND)
    assert names(list(listed)) == [
        "Shawarma de pollo",
        "Shawarma mixto",
        "Combo personal",
        "Combo familiar",
        "Agua",
        "Limonada",
        "Ensalada griega",
        "Salsa de ajo",
    ]
    groups = world.service.list_ordered(tenant_id=TENANT, brand_id=BRAND)
    assert [(g.name, g.label, g.placed, len(g.products)) for g in groups] == [
        ("Shawarmas", "Shawarmas", True, 2),
        ("Combos", "Combos", True, 2),
        ("Bebidas", "Bebidas", False, 2),
        ("Ensaladas", "Ensaladas", False, 1),
        ("", "Otros", False, 1),
    ]
    assert world.service.category_order(tenant_id=TENANT, brand_id=BRAND) == stored


def test_set_category_order_is_idempotent_and_replaces_the_whole_order(world: World) -> None:
    for _ in range(2):
        world.service.set_category_order(
            tenant_id=TENANT, brand_id=BRAND, names=["Shawarmas", "Combos"], user_id=USER
        )
    assert len(world.categories) == 2
    world.service.set_category_order(
        tenant_id=TENANT, brand_id=BRAND, names=["Bebidas"], user_id=USER
    )
    assert [c.name for c in world.categories] == ["Bebidas"]
    world.service.set_category_order(tenant_id=TENANT, brand_id=BRAND, names=[], user_id=USER)
    assert world.categories == []


def test_set_category_order_refuses_unknown_and_repeated_names(world: World) -> None:
    with pytest.raises(UnknownCategory):
        world.service.set_category_order(
            tenant_id=TENANT, brand_id=BRAND, names=["Shawarmas", "Postres"], user_id=USER
        )
    with pytest.raises(OrderRefused):
        world.service.set_category_order(
            tenant_id=TENANT, brand_id=BRAND, names=["Combos", "COMBOS"], user_id=USER
        )
    assert world.categories == []  # nothing half-written


def test_the_fallback_can_be_placed_by_blank_or_by_name(world: World) -> None:
    world.service.set_category_order(
        tenant_id=TENANT, brand_id=BRAND, names=["Otros", "Shawarmas"], user_id=USER
    )
    first = world.service.list_products(tenant_id=TENANT, brand_id=BRAND)[0]
    assert first.name == "Salsa de ajo"


def test_reorder_products_rewrites_positions_inside_one_category(world: World) -> None:
    mixto, pollo = world.by_name("Shawarma mixto").id, world.by_name("Shawarma de pollo").id
    world.service.reorder_products(
        tenant_id=TENANT,
        brand_id=BRAND,
        category="shawarmas",
        product_ids=[mixto, pollo],
        user_id=USER,
    )
    assert world.by_name("Shawarma mixto").position == 0
    assert world.by_name("Shawarma de pollo").position == 1
    # The archived one the screen did not list keeps its place after them.
    assert world.by_name("Shawarma retirado").position == 2
    # Other categories untouched.
    assert world.by_name("Agua").position == 0 and world.by_name("Limonada").position == 5
    shawarmas = [
        p.name
        for p in world.service.list_products(tenant_id=TENANT, brand_id=BRAND)
        if p.category == "Shawarmas"
    ]
    assert shawarmas == ["Shawarma mixto", "Shawarma de pollo"]


def test_reorder_products_refuses_strays_repeats_and_unknown_categories(world: World) -> None:
    pollo, agua = world.by_name("Shawarma de pollo").id, world.by_name("Agua").id
    before = [(p.name, p.position) for p in world.products]
    with pytest.raises(OrderRefused):
        world.service.reorder_products(
            tenant_id=TENANT,
            brand_id=BRAND,
            category="Shawarmas",
            product_ids=[pollo, agua],
            user_id=USER,
        )
    with pytest.raises(OrderRefused):
        world.service.reorder_products(
            tenant_id=TENANT,
            brand_id=BRAND,
            category="Shawarmas",
            product_ids=[pollo, pollo],
            user_id=USER,
        )
    with pytest.raises(UnknownCategory):
        world.service.reorder_products(
            tenant_id=TENANT, brand_id=BRAND, category="Postres", product_ids=[], user_id=USER
        )
    with pytest.raises(OrderRefused):
        world.service.reorder_products(
            tenant_id=TENANT, brand_id=BRAND, category="", product_ids=[uuid4()], user_id=USER
        )
    assert [(p.name, p.position) for p in world.products] == before


def test_move_category_and_move_product_step_one_place_and_clamp(world: World) -> None:
    # Alphabetical today: Bebidas, Combos, Ensaladas, Shawarmas, Otros.
    for _ in range(5):
        world.service.move_category(
            tenant_id=TENANT, brand_id=BRAND, name="Shawarmas", offset=-1, user_id=USER
        )
    groups = world.service.list_ordered(tenant_id=TENANT, brand_id=BRAND)
    assert [g.label for g in groups] == ["Shawarmas", "Bebidas", "Combos", "Ensaladas", "Otros"]
    world.service.move_product(
        tenant_id=TENANT,
        brand_id=BRAND,
        product_id=world.by_name("Shawarma mixto").id,
        offset=-1,
        user_id=USER,
    )
    assert names(list(groups[0].products)) == ["Shawarma de pollo", "Shawarma mixto"]
    first = world.service.list_ordered(tenant_id=TENANT, brand_id=BRAND)[0]
    assert names(list(first.products)) == ["Shawarma mixto", "Shawarma de pollo"]
    with pytest.raises(UnknownCategory):
        world.service.move_category(
            tenant_id=TENANT, brand_id=BRAND, name="Postres", offset=1, user_id=USER
        )
    with pytest.raises(UnknownProduct):
        world.service.move_product(
            tenant_id=TENANT, brand_id=BRAND, product_id=uuid4(), offset=1, user_id=USER
        )


# --- the WhatsApp list, the chat picker and «Tu menú» agree -----------------------------


def test_whatsapp_list_picker_and_menu_return_the_same_order() -> None:
    from qualify_api.whatsapp.attachments import (
        ChatAttachmentService,
        MemoryAttachmentReads,
        MemoryBlobStore,
        ProductRow,
    )

    conn = uuid4()
    reads = MemoryAttachmentReads()
    reads.brands[(TENANT, conn)] = BRAND
    reads.category_orders[(TENANT, BRAND)] = ("Shawarmas", "Combos")
    for i, item in enumerate(_bianki()):
        row = ProductRow(
            id=uuid4(),
            brand_id=BRAND,
            name=item.name,
            description="",
            price_amount=Decimal("5"),
            price_currency="USD",
            category=item.category or "",
            position=item.position or 0,
            photo_key=f"t/{TENANT}/p/{i}.jpg",
        )
        reads.product_rows[row.id] = (TENANT, row)
    service = ChatAttachmentService(None, reads, MemoryBlobStore())  # type: ignore[arg-type]

    whatsapp = [
        i.name for i in to_catalog_items(reads.products(TENANT, BRAND), ("Shawarmas", "Combos"))
    ]
    picker = [p.name for p in service.list_products_for_chat(TENANT, BRAND)]
    reads.menus[(TENANT, conn)] = object()  # type: ignore[assignment]
    _ref, menu = service._menu(TENANT, conn)
    assert whatsapp == picker == [i.name for i in menu]
    assert whatsapp[:4] == [
        "Shawarma de pollo",
        "Shawarma mixto",
        "Combo personal",
        "Combo familiar",
    ]
    assert whatsapp[-1] == "Salsa de ajo"
    assert to_catalog_items(reads.products(TENANT, BRAND))[-1].category == FALLBACK_CATEGORY


def test_whatsapp_list_accepts_the_workers_folded_keys() -> None:
    """The worker reads `name_key` (its only grant), not the owner's spelling."""
    rows = [
        type(
            "R",
            (),
            {
                "id": uuid4(),
                "name": i.name,
                "price_amount": None,
                "price_currency": "",
                "category": i.category,
                "is_active": True,
                "position": i.position,
            },
        )()
        for i in _bianki()
    ]
    keys = (category_key("Shawarmas"), category_key("Combos"))
    assert [i.name for i in to_catalog_items(rows, keys)][:2] == [
        "Shawarma de pollo",
        "Shawarma mixto",
    ]
