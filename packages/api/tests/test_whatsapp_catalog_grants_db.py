"""Migration 0059 (WA-15), checked as the REAL `qualify_webhook_worker` — same method as
`test_whatsapp_schema_db.py`: one statement per check, always rolled back, writes with
`WHERE false` so the grant is exercised without a row (and without RLS, whose refusal is
also SQLSTATE 42501).

Then `load_catalog_for_phone` runs through the production door (`webhook_worker_session`)
against real rows: a number with a brand sells that brand's ACTIVE products, ordered; a
number without a brand sells nothing; another tenant's products never leak in.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from psycopg.errors import InsufficientPrivilege
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import webhook_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from qualify_api.catalog.models import BrandProduct
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.whatsapp.catalog import FALLBACK_CATEGORY, load_catalog_for_phone
from qualify_api.whatsapp.models import WhatsAppPhoneNumber

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-000000000e15")
OTHER_TENANT = UUID("a0000000-0000-4000-8000-000000000f15")

_PRODUCT_COLUMNS = (
    "id",
    "tenant_id",
    "brand_id",
    "name",
    "price_amount",
    "price_currency",
    "category",
    "is_active",
    "position",
)


@pytest.fixture(scope="module")
def worker() -> Iterator[Engine]:
    engine = create_engine(webhook_worker_dsn())
    try:
        yield engine
    finally:
        engine.dispose()


def _attempt(engine: Engine, sql: str) -> str:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(sql))
            return "ok"
        except DBAPIError as exc:
            if isinstance(exc.orig, InsufficientPrivilege):
                return "denied"
            raise
        finally:
            trans.rollback()


# --- the grants -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT {', '.join(_PRODUCT_COLUMNS)} FROM brand_products LIMIT 1",
        "SELECT id, tenant_id, brand_id FROM whatsapp_phone_numbers LIMIT 1",
    ],
)
def test_worker_reads_the_catalog_loader_columns(worker: Engine, sql: str) -> None:
    assert _attempt(worker, sql) == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM brand_products LIMIT 1",
        "SELECT slug FROM brand_products LIMIT 1",
        "SELECT description FROM brand_products LIMIT 1",
        "SELECT tags FROM brand_products LIMIT 1",
        "SELECT created_by FROM brand_products LIMIT 1",
        "INSERT INTO brand_products (tenant_id, brand_id, name, slug) "
        "SELECT gen_random_uuid(), gen_random_uuid(), 'n', 's' WHERE false",
        "UPDATE brand_products SET is_active = is_active WHERE false",
        "DELETE FROM brand_products WHERE false",
        "SELECT 1 FROM product_media LIMIT 1",
        "SELECT * FROM whatsapp_phone_numbers LIMIT 1",
        "UPDATE whatsapp_phone_numbers SET brand_id = brand_id WHERE false",
    ],
)
def test_worker_is_denied_the_rest_of_the_catalog(worker: Engine, sql: str) -> None:
    assert _attempt(worker, sql) == "denied"


# --- the loader, with real rows ---------------------------------------------------------


def _tenant(session, tenant_id: UUID, name: str) -> None:
    if session.get(Tenant, tenant_id) is None:
        session.add(
            Tenant(
                id=tenant_id,
                name=name,
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()


def _phone(tenant_id: UUID, app_id: UUID, user_id: UUID, brand_id: UUID | None) -> UUID:
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"wa-{uuid4()}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        phone = WhatsAppPhoneNumber(
            tenant_id=tenant_id,
            brand_id=brand_id,
            connection_id=conn.id,
            waba_id="waba-15",
            phone_number_id=f"pn-{uuid4()}",
            display_phone_number="+57 300 000 0015",
        )
        session.add(phone)
        session.flush()
        return phone.id


def _product(
    session,
    tenant_id: UUID,
    brand_id: UUID,
    name: str,
    *,
    category: str = "",
    position: int = 0,
    price: str | None = "10000.00",
    active: bool = True,
) -> None:
    session.add(
        BrandProduct(
            tenant_id=tenant_id,
            brand_id=brand_id,
            name=name,
            slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
            price_amount=Decimal(price) if price is not None else None,
            price_currency="COP",
            category=category,
            is_active=active,
            position=position,
        )
    )


@pytest.fixture
def seeded() -> dict[str, UUID]:
    """A tenant with a fresh brand, a number on that brand and one without a brand, plus
    a second tenant whose brand also has products. Fresh brands per run keep re-runs
    independent of earlier rows."""
    with admin_session() as session:
        _tenant(session, TENANT, "t-wa15")
        _tenant(session, OTHER_TENANT, "t-wa15-other")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa15.co", display_name="U")
        other_user = User(tenant_id=OTHER_TENANT, email=f"u-{uuid4()}@wa15.co", display_name="O")
        brand = Brand(tenant_id=TENANT, name=f"wa15-{uuid4().hex[:8]}")
        other_brand = Brand(tenant_id=OTHER_TENANT, name=f"wa15-other-{uuid4().hex[:8]}")
        session.add_all([app, user, other_user, brand, other_brand])
        session.flush()
        ids = {
            "app": app.id,
            "user": user.id,
            "other_user": other_user.id,
            "brand": brand.id,
            "other_brand": other_brand.id,
        }

    with tenant_session(TENANT) as session:
        _product(session, TENANT, ids["brand"], "Gaseosa", category="Bebidas", position=1)
        _product(session, TENANT, ids["brand"], "Agua", category="Bebidas", position=0)
        _product(session, TENANT, ids["brand"], "Hamburguesa", category="Comidas")
        _product(session, TENANT, ids["brand"], "Salsa extra", price=None)
        _product(session, TENANT, ids["brand"], "Descontinuado", category="Comidas", active=False)
    with tenant_session(OTHER_TENANT) as session:
        _product(session, OTHER_TENANT, ids["other_brand"], "Ajeno", category="Bebidas")

    ids["phone"] = _phone(TENANT, ids["app"], ids["user"], ids["brand"])
    ids["phone_no_brand"] = _phone(TENANT, ids["app"], ids["user"], None)
    ids["other_phone"] = _phone(OTHER_TENANT, ids["app"], ids["other_user"], ids["other_brand"])
    return ids


def test_loader_returns_the_brands_active_products_in_order(seeded) -> None:
    items = load_catalog_for_phone(seeded["phone"])
    assert [(i.category, i.name) for i in items] == [
        ("Bebidas", "Agua"),
        ("Bebidas", "Gaseosa"),
        ("Comidas", "Hamburguesa"),
        (FALLBACK_CATEGORY, "Salsa extra"),
    ]
    by_name = {i.name: i for i in items}
    assert by_name["Agua"].price_amount == Decimal("10000.00")
    assert by_name["Agua"].price_currency == "COP"
    assert by_name["Salsa extra"].price_amount is None


def test_loader_is_empty_for_a_number_without_brand_or_unknown(seeded) -> None:
    assert load_catalog_for_phone(seeded["phone_no_brand"]) == ()
    assert load_catalog_for_phone(uuid4()) == ()


def test_loader_never_mixes_tenants(seeded) -> None:
    mine = {i.name for i in load_catalog_for_phone(seeded["phone"])}
    theirs = {i.name for i in load_catalog_for_phone(seeded["other_phone"])}
    assert "Ajeno" not in mine
    assert theirs == {"Ajeno"}
