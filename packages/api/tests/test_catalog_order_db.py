"""Migration 0128 (`brand_product_categories`, m-24955643) against the compose Postgres:
the constraints, RLS (tenant B never sees or writes tenant A's order), the service
roundtrip through the real tenant door, and the WhatsApp loader ordering the list as the
REAL `qualify_webhook_worker` with only its column grants."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from psycopg.errors import InsufficientPrivilege
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import webhook_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.catalog.models import BrandProductCategory
from qualify_api.catalog.service import CatalogService, UnknownCategory
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.whatsapp.catalog import load_catalog_for_phone
from qualify_api.whatsapp.models import WhatsAppPhoneNumber

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-000000000128")
TENANT_B = UUID("b0000000-0000-4000-8000-000000000128")


@pytest.fixture
def seeded() -> dict[str, UUID]:
    """Fresh brands per run, so re-runs never depend on earlier rows."""
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"order-0128-{name}",
                        country="VE",
                        timezone="America/Caracas",
                        currency="USD",
                    )
                )
                session.flush()
        brand_a = Brand(tenant_id=TENANT_A, name=f"order-a-{uuid4().hex[:8]}")
        brand_b = Brand(tenant_id=TENANT_B, name=f"order-b-{uuid4().hex[:8]}")
        user = User(tenant_id=TENANT_A, email=f"order-{uuid4()}@a.co", display_name="U")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add_all([brand_a, brand_b, user, app])
        session.flush()
        ids = {"brand_a": brand_a.id, "brand_b": brand_b.id, "user": user.id, "app": app.id}
    service = CatalogService(store=None)  # type: ignore[arg-type]
    for name, category in (
        ("Agua", "Bebidas"),
        ("Ensalada griega", "Ensaladas"),
        ("Combo personal", "Combos"),
        ("Shawarma de pollo", "Shawarmas"),
        ("Shawarma mixto", "Shawarmas"),
        ("Salsa de ajo", ""),
    ):
        service.create_product(
            tenant_id=TENANT_A,
            brand_id=ids["brand_a"],
            user_id=ids["user"],
            name=name,
            category=category,
        )
    service.create_product(
        tenant_id=TENANT_B, brand_id=ids["brand_b"], user_id=None, name="Ajeno", category="X"
    )
    return ids


def _phone(ids: dict[str, UUID]) -> UUID:
    with tenant_session(TENANT_A) as session:
        conn = SocialConnection(
            tenant_id=TENANT_A,
            platform_app_id=ids["app"],
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"wa-{uuid4()}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=ids["user"],
        )
        session.add(conn)
        session.flush()
        phone = WhatsAppPhoneNumber(
            tenant_id=TENANT_A,
            brand_id=ids["brand_a"],
            connection_id=conn.id,
            waba_id="waba-0128",
            phone_number_id=f"pn-{uuid4()}",
            display_phone_number="+58 412 000 0128",
        )
        session.add(phone)
        session.flush()
        return phone.id


def test_the_service_roundtrip_orders_the_catalog_and_the_whatsapp_list(seeded) -> None:
    service = CatalogService(store=None)  # type: ignore[arg-type]
    brand = seeded["brand_a"]
    service.set_category_order(
        tenant_id=TENANT_A, brand_id=brand, names=["Shawarmas", "Combos"], user_id=seeded["user"]
    )
    # Same list twice: idempotent, no unique violation.
    service.set_category_order(
        tenant_id=TENANT_A, brand_id=brand, names=["Shawarmas", "Combos"], user_id=seeded["user"]
    )
    products = service.list_products(tenant_id=TENANT_A, brand_id=brand)
    mixto = next(p for p in products if p.name == "Shawarma mixto")
    pollo = next(p for p in products if p.name == "Shawarma de pollo")
    service.reorder_products(
        tenant_id=TENANT_A,
        brand_id=brand,
        category="Shawarmas",
        product_ids=[mixto.id, pollo.id],
        user_id=seeded["user"],
    )
    expected = [
        "Shawarma mixto",
        "Shawarma de pollo",
        "Combo personal",
        "Agua",
        "Ensalada griega",
        "Salsa de ajo",
    ]
    assert [p.name for p in service.list_products(tenant_id=TENANT_A, brand_id=brand)] == expected
    assert [i.name for i in load_catalog_for_phone(_phone(seeded))] == expected
    with pytest.raises(UnknownCategory):
        service.set_category_order(
            tenant_id=TENANT_A, brand_id=brand, names=["Postres"], user_id=None
        )


def test_rls_keeps_each_tenants_order_its_own(seeded) -> None:
    service = CatalogService(store=None)  # type: ignore[arg-type]
    service.set_category_order(
        tenant_id=TENANT_A, brand_id=seeded["brand_a"], names=["Combos"], user_id=None
    )
    with tenant_session(TENANT_B) as session:
        assert (
            session.scalars(
                select(BrandProductCategory).where(
                    BrandProductCategory.brand_id == seeded["brand_a"]
                )
            ).all()
            == []
        )
    # Tenant B cannot order A's brand: none of A's categories are visible to B.
    with pytest.raises(UnknownCategory):
        service.set_category_order(
            tenant_id=TENANT_B, brand_id=seeded["brand_a"], names=["Combos"], user_id=None
        )
    # Nor write a row claiming A's tenant (WITH CHECK).
    with pytest.raises(DBAPIError), tenant_session(TENANT_B) as session:
        session.add(
            BrandProductCategory(
                tenant_id=TENANT_A,
                brand_id=seeded["brand_a"],
                name="Intruso",
                name_key="intruso",
                position=0,
            )
        )
        session.flush()
    assert service.category_order(tenant_id=TENANT_A, brand_id=seeded["brand_a"]) == ("Combos",)


@pytest.mark.parametrize(
    ("name_key", "position", "dup"),
    [("", 0, False), ("negativo", -1, False), ("combos", 1, True)],
)
def test_constraints_refuse_blank_keys_negative_positions_and_duplicates(
    seeded, name_key: str, position: int, dup: bool
) -> None:
    brand = seeded["brand_a"]
    with pytest.raises(IntegrityError), tenant_session(TENANT_A) as session:
        if dup:
            session.add(
                BrandProductCategory(
                    tenant_id=TENANT_A, brand_id=brand, name="Combos", name_key="combos", position=0
                )
            )
            session.flush()
        session.add(
            BrandProductCategory(
                tenant_id=TENANT_A,
                brand_id=brand,
                name=name_key or "x",
                name_key=name_key,
                position=position,
            )
        )
        session.flush()


def test_worker_reads_only_the_granted_columns() -> None:
    engine = create_engine(webhook_worker_dsn())
    try:

        def attempt(sql: str) -> str:
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

        assert (
            attempt("SELECT tenant_id, brand_id, name_key, position FROM brand_product_categories")
            == "ok"
        )
        for sql in (
            "SELECT name FROM brand_product_categories",
            "SELECT * FROM brand_product_categories",
            "DELETE FROM brand_product_categories WHERE false",
            "UPDATE brand_product_categories SET position = position WHERE false",
        ):
            assert attempt(sql) == "denied", sql
    finally:
        engine.dispose()
