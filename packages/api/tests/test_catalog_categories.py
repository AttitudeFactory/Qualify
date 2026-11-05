"""Categories for products that have none (m-24955838), offline.

- `pluralize` / `suggest_groups`: grouping by a shared leading word, no AI, on a
  Bianki-shaped catalog (invented names).
- `CatalogService.set_products_category`: bulk assign in one locked transaction — new
  category row at the end of the stored order, moved products at the end of the
  category, cross-brand refusal, idempotence, removal («Otros»). Fake tenant door.
- The import's category post-processing (`tidy_categories`, `wa-import-3`) through
  `verify_answer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql.dml import Update

from qualify_api.catalog.categories import (
    pluralize,
    suggest_groups,
    uncategorized_count,
)
from qualify_api.catalog.models import BrandProduct, BrandProductCategory, ProductMedia
from qualify_api.catalog.service import (
    CatalogError,
    CatalogService,
    OrderRefused,
    UnknownBrand,
    UnknownProduct,
)
from qualify_api.tenancy.models import Brand
from qualify_api.whatsapp.menus.import_ai import (
    PROMPT_VERSION,
    SourceDocument,
    _tidy_category,
    _tool,
    order_found_products,
    tidy_categories,
    verify_answer,
)

TENANT = UUID("00000000-0000-4000-8000-0000000000a1")
BRAND = UUID("00000000-0000-4000-8000-0000000000b1")
OTHER_BRAND = UUID("00000000-0000-4000-8000-0000000000b2")
USER = UUID("00000000-0000-4000-8000-0000000000c1")
FOREIGN_BRAND = UUID("00000000-0000-4000-8000-0000000000f1")
OLD = datetime(2026, 11, 1, tzinfo=UTC)

#: Bianki-shaped: every product came from the import, none has a category.
NAMES = [
    "Catering oficina",
    "Combo Vecino",
    "Combo Clásico",
    "Combo Doble",
    "Shawarma de res",
    "Shawarma de pollo",
    "Ensalada verde",
    "Ensalada griega",
    "Ensalada de la casa",
    "Papas grandes",
    "Papas pequeñas",
    "Salchipapa",
    "Cola negra",
    "Jugo del día",
    "Limonada",
]


@dataclass(frozen=True)
class P:
    id: UUID
    name: str
    category: str = ""


# --- pluralize / suggest_groups ---------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "plural"),
    [
        ("Combo", "Combos"),
        ("Shawarma", "Shawarmas"),
        ("Ensalada", "Ensaladas"),
        ("Café", "Cafés"),
        ("Papas", "Papas"),
        ("Pan", "Panes"),
        ("Limón", "Limones"),
        ("Sándwich", "Sándwiches"),
        ("Lápiz", "Lápices"),
        ("", ""),
    ],
)
def test_pluralize_is_simple_spanish(word: str, plural: str) -> None:
    assert pluralize(word) == plural


def test_suggest_groups_on_a_bianki_shaped_catalog() -> None:
    products = [P(uuid4(), n) for n in NAMES]
    groups = suggest_groups(products)
    by_name = {g.name: [p.name for p in products if p.id in g.product_ids] for g in groups}
    assert [g.name for g in groups] == ["Combos", "Ensaladas", "Papas", "Shawarmas"]
    assert by_name["Combos"] == ["Combo Vecino", "Combo Clásico", "Combo Doble"]
    assert by_name["Papas"] == ["Papas grandes", "Papas pequeñas"]
    grouped = {i for g in groups for i in g.product_ids}
    ungrouped = [p.name for p in products if p.id not in grouped]
    assert ungrouped == ["Catering oficina", "Salchipapa", "Cola negra", "Jugo del día", "Limonada"]
    assert uncategorized_count(products) == len(NAMES)


def test_suggest_groups_skips_categorized_products_and_reuses_existing_spelling() -> None:
    products = [
        P(uuid4(), "Combo 1"),
        P(uuid4(), "Combo 2"),
        P(uuid4(), "Combo 3", "Combos especiales"),
        P(uuid4(), "La casa"),
        P(uuid4(), "La otra"),  # «La» is never a section
        P(uuid4(), "Otro", "Otros"),
    ]
    groups = suggest_groups(products, ["COMBOS"])
    assert [(g.name, len(g.product_ids)) for g in groups] == [("COMBOS", 2)]
    assert uncategorized_count(products) == 5


def test_a_singular_and_a_plural_leading_word_are_one_group() -> None:
    products = [P(uuid4(), "Papa rellena"), P(uuid4(), "Papas fritas")]
    assert [g.name for g in suggest_groups(products)] == ["Papas"]


# --- set_products_category over a fake tenant door ------------------------------------


class FakeSession:
    def __init__(self, world: World) -> None:
        self.w = world

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, model: Any, ident: UUID) -> Any:
        assert model is Brand
        return self.w.brands.get(ident)

    def execute(self, stmt: Any) -> None:
        if isinstance(stmt, Update):
            stamp = stmt.compile().params["updated_at"]
            for c in self.w.categories:
                c.updated_at = stamp
            self.w.touches += 1
            return
        assert "pg_advisory_xact_lock" in str(stmt)
        self.w.locks += 1

    def scalars(self, stmt: Any) -> Any:
        if "max(" in str(stmt):
            stamps = [c.updated_at for c in self.w.categories if c.updated_at is not None]
            return _First(max(stamps) if stamps else None)
        desc = stmt.column_descriptions[0]
        if desc["entity"] is ProductMedia:
            return []
        if desc["entity"] is BrandProductCategory:
            return [c.name for c in sorted(self.w.categories, key=lambda c: c.position)]
        assert desc["entity"] is BrandProduct
        # The brand predicate is the service's; the fake honours it by brand.
        brand = OTHER_BRAND if OTHER_BRAND in stmt.compile().params.values() else BRAND
        rows = [p for p in self.w.products if p.brand_id == brand]
        if "is_active IS true" in str(stmt):
            rows = [p for p in rows if p.is_active]
        return sorted(rows, key=lambda p: (p.position, p.name))

    def add(self, row: Any) -> None:
        assert isinstance(row, BrandProductCategory) and row.tenant_id == TENANT
        self.w.categories.append(row)

    def flush(self) -> None:
        keys = [(c.brand_id, c.name_key) for c in self.w.categories]
        assert len(keys) == len(set(keys))


class _First:
    def __init__(self, value: Any) -> None:
        self.value = value

    def first(self) -> Any:
        return self.value


class World:
    def __init__(self) -> None:
        self.products: list[BrandProduct] = []
        self.categories: list[BrandProductCategory] = []
        self.locks = 0
        self.touches = 0
        self.brands = {
            BRAND: Brand(id=BRAND, tenant_id=TENANT, name="b"),
            OTHER_BRAND: Brand(id=OTHER_BRAND, tenant_id=TENANT, name="o"),
        }
        self.service = CatalogService(store=None)  # type: ignore[arg-type]

    def product(
        self,
        name: str,
        category: str = "",
        brand: UUID = BRAND,
        created_at: datetime = OLD,
    ) -> UUID:
        row = BrandProduct(
            id=uuid4(),
            tenant_id=TENANT,
            brand_id=brand,
            name=name,
            slug=name.lower().replace(" ", "-"),
            description="",
            price_amount=Decimal("5"),
            price_currency="USD",
            category=category,
            tags=[],
            is_active=True,
            position=len(self.products),
            created_at=created_at,
        )
        self.products.append(row)
        return row.id

    def by_name(self, name: str) -> BrandProduct:
        return next(p for p in self.products if p.name == name)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    from qualify_api.catalog import service as mod

    w = World()
    for name in NAMES:
        w.product(name)
    w.categories.append(
        BrandProductCategory(
            tenant_id=TENANT,
            brand_id=BRAND,
            name="Bebidas",
            name_key="bebidas",
            position=0,
            updated_at=OLD,
        )
    )
    w.product("Agua", "Bebidas")

    def door(tenant_id: UUID) -> FakeSession:
        assert tenant_id == TENANT
        return FakeSession(w)

    monkeypatch.setattr(mod, "tenant_session", door)
    return w


def _ids(w: World, *names: str) -> list[UUID]:
    return [w.by_name(n).id for n in names]


def test_bulk_assign_creates_the_category_at_the_end_and_appends_products(world: World) -> None:
    result = world.service.set_products_category(
        tenant_id=TENANT,
        brand_id=BRAND,
        product_ids=_ids(world, "Combo Doble", "Combo Vecino"),
        category="  combos ",
        user_id=USER,
    )
    assert (result.category, result.moved, result.created) == ("combos", 2, True)
    assert [(c.name, c.position) for c in world.categories] == [("Bebidas", 0), ("combos", 1)]
    assert world.categories[-1].updated_by == USER and world.locks == 1
    # Catalog order kept: Vecino was before Doble.
    assert (world.by_name("Combo Vecino").position, world.by_name("Combo Doble").position) == (
        0,
        1,
    )
    # A later call appends after them and reuses the stored spelling.
    again = world.service.set_products_category(
        tenant_id=TENANT,
        brand_id=BRAND,
        product_ids=_ids(world, "Combo Clásico", "Combo Vecino"),
        category="COMBOS",
        user_id=USER,
    )
    assert (again.category, again.moved, again.created) == ("combos", 1, False)
    assert world.by_name("Combo Clásico").category == "combos"
    assert world.by_name("Combo Clásico").position == 2
    assert world.by_name("Combo Vecino").position == 0  # already there: did not move


def test_bulk_assign_into_an_existing_category_and_idempotence(world: World) -> None:
    ids = _ids(world, "Cola negra", "Limonada")
    first = world.service.set_products_category(
        tenant_id=TENANT, brand_id=BRAND, product_ids=ids, category="bebidas", user_id=USER
    )
    assert (first.category, first.moved, first.created) == ("Bebidas", 2, False)
    # Appended after «Agua», in their catalog order.
    assert [world.by_name(n).position for n in ("Agua", "Cola negra", "Limonada")] == [
        15,
        16,
        17,
    ]
    snapshot = [(p.name, p.category, p.position) for p in world.products]
    second = world.service.set_products_category(
        tenant_id=TENANT, brand_id=BRAND, product_ids=ids, category="Bebidas", user_id=USER
    )
    assert second.moved == 0 and not second.created
    assert [(p.name, p.category, p.position) for p in world.products] == snapshot
    assert len(world.categories) == 1


def test_bulk_assign_refuses_other_brands_repeats_and_long_names(world: World) -> None:
    foreign = world.product("Ajeno", brand=OTHER_BRAND)
    before = [(p.name, p.category, p.position) for p in world.products]
    with pytest.raises(UnknownProduct):
        world.service.set_products_category(
            tenant_id=TENANT,
            brand_id=BRAND,
            product_ids=[*_ids(world, "Limonada"), foreign],
            category="Bebidas",
            user_id=USER,
        )
    with pytest.raises(OrderRefused):
        world.service.set_products_category(
            tenant_id=TENANT,
            brand_id=BRAND,
            product_ids=_ids(world, "Limonada", "Limonada"),
            category="Bebidas",
            user_id=USER,
        )
    with pytest.raises(CatalogError) as refused:
        world.service.set_products_category(
            tenant_id=TENANT,
            brand_id=BRAND,
            product_ids=_ids(world, "Limonada"),
            category="Bebidas frías y calientes de la casa",
            user_id=USER,
        )
    assert "24" in str(refused.value)
    assert [(p.name, p.category, p.position) for p in world.products] == before
    assert len(world.categories) == 1


def test_empty_category_removes_it(world: World) -> None:
    result = world.service.set_products_category(
        tenant_id=TENANT, brand_id=BRAND, product_ids=_ids(world, "Agua"), category="", user_id=USER
    )
    assert (result.category, result.moved, result.created) == ("", 1, False)
    assert world.by_name("Agua").category == ""
    assert len(world.categories) == 1  # the stored place of «Bebidas» stays
    other = world.service.set_products_category(
        tenant_id=TENANT,
        brand_id=BRAND,
        product_ids=_ids(world, "Agua"),
        category="Otros",
        user_id=USER,
    )
    assert other.moved == 0  # «Otros» is «no category»: already there


def test_the_service_suggests_and_counts(world: World) -> None:
    assert world.service.uncategorized_count(tenant_id=TENANT, brand_id=BRAND) == len(NAMES)
    groups = world.service.suggest_category_groups(tenant_id=TENANT, brand_id=BRAND)
    assert [g.name for g in groups] == ["Combos", "Ensaladas", "Papas", "Shawarmas"]
    for g in groups:
        world.service.set_products_category(
            tenant_id=TENANT,
            brand_id=BRAND,
            product_ids=list(g.product_ids),
            category=g.name,
            user_id=USER,
        )
    assert world.service.uncategorized_count(tenant_id=TENANT, brand_id=BRAND) == 5
    assert [c.name for c in world.categories] == [
        "Bebidas",
        "Combos",
        "Ensaladas",
        "Papas",
        "Shawarmas",
    ]


# --- the import proposes categories (wa-import-3) ---------------------------------------


def test_the_tool_asks_for_a_category_and_the_version_is_bumped() -> None:
    schema = _tool()["input_schema"]["properties"]["products"]["items"]
    assert {"category", "category_heading"} <= set(schema["required"])
    assert PROMPT_VERSION == "wa-import-3"


def test_tidy_categories_folds_cases_trims_and_drops_sentences_and_orphans() -> None:
    text = "COMBOS Combo 1 Combo 2 BEBIDAS Agua POSTRES Torta"
    proposed = [
        ("COMBOS", True),
        ("combos ", True),
        ("Bebidas", True),  # alone but the source's heading → kept
        ("Postres caseros", False),  # alone, invented → dropped
        ("Se entregan frías.", False),  # a sentence → dropped
        ("Bebidas frías y calientes del día", False),  # > 24 chars → dropped
        ("", False),
        ("Extras", True),  # claims heading, not in the text → dropped
    ]
    assert tidy_categories(proposed, text) == [
        "Combos",
        "Combos",
        "Bebidas",
        "",
        "",
        "",
        "",
        "",
    ]
    # A photo has no text to check: a lone heading the model saw is trusted.
    assert tidy_categories([("Postres", True), ("Extras", False)], None) == ["Postres", ""]


def test_verify_answer_puts_the_tidy_category_on_each_product() -> None:
    text = "COMBOS Combo Vecino 9 $ Combo Doble 12 $ BEBIDAS Limonada 2 $"
    document = SourceDocument(({"type": "text", "text": text},), text, "url", "bianki.co", ())

    def prod(name: str, price: str, evidence: str, category: str, heading: bool) -> dict:
        return {
            "name": name,
            "price_text": price,
            "description": "",
            "evidence": evidence,
            "category": category,
            "category_heading": heading,
        }

    verified = verify_answer(
        {
            "facts": [],
            "products": [
                prod("Limonada", "2 $", "BEBIDAS Limonada 2 $", "BEBIDAS", True),
                prod("Combo Vecino", "9 $", "Combo Vecino 9 $", "Combos", True),
                prod("Combo Doble", "12 $", "Combo Doble 12 $", "combos", True),
            ],
        },
        document,
    )
    assert [(p.name, p.category) for p in verified.products] == [
        ("Limonada", "Bebidas"),
        ("Combo Vecino", "Combos"),
        ("Combo Doble", "Combos"),
    ]
    ordered = order_found_products(verified.products, ["Combos"])
    assert [p.name for p in ordered] == ["Combo Vecino", "Combo Doble", "Limonada"]


# --- review follow-ups (C7, C5, U2) -----------------------------------------------------


def test_bulk_assign_refuses_an_empty_list_and_a_brand_the_tenant_does_not_see(
    world: World,
) -> None:
    with pytest.raises(OrderRefused):
        world.service.set_products_category(
            tenant_id=TENANT, brand_id=BRAND, product_ids=[], category="Nueva", user_id=USER
        )
    with pytest.raises(UnknownBrand):
        world.service.set_products_category(
            tenant_id=TENANT,
            brand_id=FOREIGN_BRAND,
            product_ids=_ids(world, "Limonada"),
            category="Nueva",
            user_id=USER,
        )
    assert [c.name for c in world.categories] == ["Bebidas"]


@pytest.mark.parametrize(
    ("raw", "tidy"),
    [
        ("BEBIDAS FRÍAS Y CALIENTES DEL DÍA", "Bebidas frías"),  # cut, no trailing «y»
        ("Hamburguesas de la casa con papas", "Hamburguesas de la casa"),
        ("Alitas BBQ", "Alitas BBQ"),
        ("combos xl", "Combos xl"),
        ("Combos XL de la semana", "Combos XL de la semana"),
        ("COMBOS BBQ", "Combos bbq"),  # all caps: no way to tell an acronym
        ("Supercalifragilisticoespialidoso", ""),  # not even one word fits
        ("Se entregan frías.", ""),
    ],
)
def test_tidy_category_shortens_real_headings_and_keeps_acronyms(raw: str, tidy: str) -> None:
    assert _tidy_category(raw) == tidy


def _notice(w: World) -> tuple[int, bool]:
    n = w.service.uncategorized_notice(tenant_id=TENANT, brand_id=BRAND)
    return n.count, n.show


def test_notice_shows_for_an_ungrouped_menu(world: World) -> None:
    # 15 loose products, one category («Bebidas») with products.
    assert _notice(world) == (len(NAMES), True)


def test_notice_hides_for_a_grouped_menu_with_old_leftovers(world: World) -> None:
    for g in world.service.suggest_category_groups(tenant_id=TENANT, brand_id=BRAND):
        world.service.set_products_category(
            tenant_id=TENANT,
            brand_id=BRAND,
            product_ids=list(g.product_ids),
            category=g.name,
            user_id=USER,
        )
    world.service.set_products_category(
        tenant_id=TENANT,
        brand_id=BRAND,
        product_ids=_ids(world, "Cola negra", "Jugo del día", "Limonada", "Catering oficina"),
        category="Bebidas",
        user_id=USER,
    )
    assert world.touches == 5
    assert _notice(world) == (1, False)  # «Salchipapa» left in «Otros» on purpose
    world.by_name("Catering oficina").category = ""  # two old leftovers
    assert _notice(world) == (2, False)


def test_notice_shows_again_when_a_new_loose_product_arrives(world: World) -> None:
    world.service.set_products_category(
        tenant_id=TENANT,
        brand_id=BRAND,
        product_ids=_ids(world, "Combo Vecino", "Combo Clásico"),
        category="Combos",
        user_id=USER,
    )
    touched = max(c.updated_at for c in world.categories)
    world.product("Postre nuevo", created_at=touched + timedelta(minutes=5))
    count, show = _notice(world)
    assert show and count == len(NAMES) - 1


def test_notice_hides_for_a_single_loose_product(world: World) -> None:
    for p in world.products:
        if p.category == "":
            p.category = "Platos"
    world.by_name("Limonada").category = ""
    assert _notice(world) == (1, False)
